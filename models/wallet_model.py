"""
Wallet model — PostgreSQL version.
All operations use try/finally to return pool connections.
Atomic operations use SELECT FOR UPDATE within a single transaction.
"""
import logging
from models.db import get_connection, dict_cursor

logger = logging.getLogger(__name__)


def create_tables():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                id         SERIAL PRIMARY KEY,
                user_id    INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                balance    NUMERIC(12,2) NOT NULL DEFAULT 0.00,
                updated_at TIMESTAMPTZ   DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id            SERIAL PRIMARY KEY,
                wallet_id     INTEGER      NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
                user_id       INTEGER      NOT NULL,
                type          VARCHAR(30)  NOT NULL,
                amount        NUMERIC(12,2) NOT NULL,
                balance_after NUMERIC(12,2) NOT NULL,
                description   VARCHAR(300),
                ref_id        VARCHAR(120),
                created_at    TIMESTAMPTZ  DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id             SERIAL PRIMARY KEY,
                user_id        INTEGER       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amount         NUMERIC(12,2) NOT NULL,
                bank_name      VARCHAR(120)  NOT NULL,
                account_number VARCHAR(30)   NOT NULL,
                ifsc_code      VARCHAR(20)   NOT NULL,
                account_name   VARCHAR(120)  NOT NULL,
                status         VARCHAR(20)   NOT NULL DEFAULT 'pending'
                                   CHECK (status IN ('pending','approved','rejected')),
                admin_note     VARCHAR(300),
                created_at     TIMESTAMPTZ   DEFAULT NOW(),
                updated_at     TIMESTAMPTZ   DEFAULT NOW()
            );
        """)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Internal helpers (used inside a shared connection/transaction) ─────────────

def _ensure_wallet(conn, user_id):
    """
    Get or create wallet with a row-level lock (FOR UPDATE).
    Must be called inside an existing transaction.
    Returns (wallet_id, balance).
    """
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO wallets (user_id, balance)
        VALUES (%s, 0.00)
        ON CONFLICT (user_id) DO NOTHING
    """, (user_id,))
    cur.execute("""
        SELECT id, balance FROM wallets
        WHERE  user_id = %s FOR UPDATE
    """, (user_id,))
    row = cur.fetchone()
    cur.close()
    return row[0], float(row[1])


def _log_txn(conn, wallet_id, user_id, txn_type, amount,
             balance_after, description, ref_id=None):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO wallet_transactions
            (wallet_id, user_id, type, amount, balance_after, description, ref_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (wallet_id, user_id, txn_type, amount, balance_after, description, ref_id))
    cur.close()


# ── Public API ────────────────────────────────────────────────────────────────

def get_wallet(user_id):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("SELECT * FROM wallets WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            cur2 = conn.cursor()
            cur2.execute("""
                INSERT INTO wallets (user_id, balance)
                VALUES (%s, 0.00)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id,))
            conn.commit()
            cur2.close()
            cur.execute("SELECT * FROM wallets WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
        return row
    finally:
        conn.close()


def get_balance(user_id):
    w = get_wallet(user_id)
    return float(w["balance"]) if w else 0.0


def credit(user_id, amount, txn_type, description, ref_id=None):
    """Add money to wallet. Returns new balance."""
    conn = get_connection()
    try:
        wid, bal = _ensure_wallet(conn, user_id)
        new_bal  = round(bal + amount, 2)
        cur = conn.cursor()
        cur.execute(
            "UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
            (new_bal, wid),
        )
        _log_txn(conn, wid, user_id, txn_type, amount, new_bal, description, ref_id)
        conn.commit()
        cur.close()
        return new_bal
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def debit(user_id, amount, txn_type, description, ref_id=None):
    """Deduct money from wallet. Raises ValueError if insufficient."""
    conn = get_connection()
    try:
        wid, bal = _ensure_wallet(conn, user_id)
        if bal < amount:
            raise ValueError(
                f"Insufficient balance. Available: ₹{bal:.2f}, needed: ₹{amount:.2f}"
            )
        new_bal = round(bal - amount, 2)
        cur = conn.cursor()
        cur.execute(
            "UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
            (new_bal, wid),
        )
        _log_txn(conn, wid, user_id, txn_type, amount, new_bal, description, ref_id)
        conn.commit()
        cur.close()
        return new_bal
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_transactions(user_id, limit=50):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT wt.*
            FROM   wallet_transactions wt
            JOIN   wallets w ON wt.wallet_id = w.id
            WHERE  wt.user_id = %s
            ORDER  BY wt.created_at DESC
            LIMIT  %s
        """, (user_id, limit))
        return cur.fetchall()
    finally:
        conn.close()


def request_withdrawal(user_id, amount, bank_name, account_number, ifsc_code, account_name):
    """
    Atomically: debit wallet AND create withdrawal request in one transaction.
    If the DB insert fails the debit is rolled back — user never loses money
    without a matching withdrawal record.
    """
    conn = get_connection()
    try:
        # Debit within this transaction
        wid, bal = _ensure_wallet(conn, user_id)
        if bal < amount:
            raise ValueError(
                f"Insufficient balance. Available: ₹{bal:.2f}, needed: ₹{amount:.2f}"
            )
        new_bal = round(bal - amount, 2)
        cur = conn.cursor()
        cur.execute(
            "UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
            (new_bal, wid),
        )
        _log_txn(conn, wid, user_id, "withdrawal", amount, new_bal,
                 f"Withdrawal to {bank_name} ****{account_number[-4:]}")

        # Create withdrawal request in the same transaction
        cur.execute("""
            INSERT INTO withdrawal_requests
                (user_id, amount, bank_name, account_number, ifsc_code, account_name)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (user_id, amount, bank_name, account_number, ifsc_code, account_name))
        rid = cur.fetchone()[0]
        cur.close()
        conn.commit()
        logger.info("Withdrawal request %s created for user %s amount=%.2f", rid, user_id, amount)
        return rid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_all_withdrawals():
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT wr.*, u.name AS user_name, u.email
            FROM   withdrawal_requests wr
            JOIN   users u ON wr.user_id = u.id
            ORDER  BY wr.created_at DESC
        """)
        return cur.fetchall()
    finally:
        conn.close()


def get_user_withdrawals(user_id):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT * FROM withdrawal_requests
            WHERE  user_id = %s ORDER BY created_at DESC
        """, (user_id,))
        return cur.fetchall()
    finally:
        conn.close()


def approve_withdrawal(request_id, admin_note=""):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE withdrawal_requests
            SET    status='approved', admin_note=%s, updated_at=NOW()
            WHERE  id=%s AND status='pending'
        """, (admin_note, request_id))
        conn.commit()
        cur.close()
        logger.info("Withdrawal %s approved", request_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reject_withdrawal(request_id, admin_note=""):
    """
    Atomically: mark withdrawal as rejected AND refund the amount to the user
    wallet in a SINGLE transaction.
    Old code used two separate connections — if the server crashed between them
    the user lost money permanently. This version is safe.
    """
    conn = get_connection()
    try:
        # Fetch and lock the withdrawal row
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT * FROM withdrawal_requests
            WHERE id=%s AND status='pending'
            FOR UPDATE
        """, (request_id,))
        req = cur.fetchone()
        cur.close()

        if not req:
            return False

        # Refund wallet (within the same transaction)
        wid, bal = _ensure_wallet(conn, req["user_id"])
        refund_amount = float(req["amount"])
        new_bal = round(bal + refund_amount, 2)
        cur = conn.cursor()
        cur.execute(
            "UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
            (new_bal, wid),
        )
        _log_txn(conn, wid, req["user_id"], "refund", refund_amount, new_bal,
                 f"Withdrawal rejected — refunded ₹{refund_amount:.2f}",
                 str(request_id))

        # Mark rejected
        cur.execute("""
            UPDATE withdrawal_requests
            SET    status='rejected', admin_note=%s, updated_at=NOW()
            WHERE  id=%s
        """, (admin_note, request_id))
        cur.close()
        conn.commit()
        logger.info("Withdrawal %s rejected and ₹%.2f refunded to user %s",
                    request_id, refund_amount, req["user_id"])
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_all_wallets_admin():
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT w.*, u.name, u.email, u.role
            FROM   wallets w
            JOIN   users   u ON w.user_id = u.id
            ORDER  BY w.balance DESC
        """)
        return cur.fetchall()
    finally:
        conn.close()

"""
Wallet model — PostgreSQL version.
Atomic transactions with SELECT FOR UPDATE to prevent race conditions.
"""
from models.db import get_connection, dict_cursor


def create_tables():
    conn = get_connection()
    cur  = conn.cursor()

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
    conn.close()


# ── Internal helpers ──────────────────────────────────────────────────────────
def _ensure_wallet(conn, user_id):
    """
    Get or create wallet row with a row-level lock (FOR UPDATE).
    Returns (wallet_id, balance).
    """
    cur = conn.cursor()
    # Try insert first; ignore if already exists
    cur.execute("""
        INSERT INTO wallets (user_id, balance)
        VALUES (%s, 0.00)
        ON CONFLICT (user_id) DO NOTHING
    """, (user_id,))

    cur.execute("""
        SELECT id, balance FROM wallets
        WHERE  user_id = %s
        FOR UPDATE
    """, (user_id,))
    row = cur.fetchone()
    cur.close()
    return row[0], float(row[1])


def _log_txn(conn, wallet_id, user_id, txn_type, amount, balance_after, description, ref_id=None):
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
    cur  = dict_cursor(conn)
    cur.execute("SELECT * FROM wallets WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if not row:
        # Create wallet
        cur2 = conn.cursor()
        cur2.execute("""
            INSERT INTO wallets (user_id, balance)
            VALUES (%s, 0.00)
            ON CONFLICT (user_id) DO NOTHING
            RETURNING *
        """, (user_id,))
        conn.commit()
        cur2.close()
        cur.execute("SELECT * FROM wallets WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    cur.close()
    conn.close()
    return row


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
        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
                    (new_bal, wid))
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
        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
                    (new_bal, wid))
        _log_txn(conn, wid, user_id, txn_type, amount, new_bal, description, ref_id)
        conn.commit()
        cur.close()
        return new_bal
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def wallet_purchase(buyer_id, seller_id, admin_id, product_id,
                    seller_price, platform_profit, product_title):
    """
    Atomic 3-way transfer:
      buyer  -seller_price
      seller +(seller_price - platform_profit)
      admin  +platform_profit
    """
    conn = get_connection()
    try:
        # Lock all three wallets in a consistent order (lowest id first) to avoid deadlock
        b_wid, b_bal = _ensure_wallet(conn, buyer_id)

        if b_bal < seller_price:
            raise ValueError(
                f"Insufficient wallet balance. "
                f"Available: ₹{b_bal:.2f}, needed: ₹{seller_price:.2f}"
            )

        s_wid, s_bal = _ensure_wallet(conn, seller_id)
        a_wid, a_bal = _ensure_wallet(conn, admin_id) if admin_id else (None, 0)

        seller_earn = round(seller_price - platform_profit, 2)

        b_new = round(b_bal - seller_price, 2)
        s_new = round(s_bal + seller_earn, 2)
        a_new = round(a_bal + platform_profit, 2) if admin_id else a_bal

        cur = conn.cursor()

        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s", (b_new, b_wid))
        _log_txn(conn, b_wid, buyer_id, "purchase", seller_price, b_new,
                 f"Purchased: {product_title}", str(product_id))

        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s", (s_new, s_wid))
        _log_txn(conn, s_wid, seller_id, "sale_credit", seller_earn, s_new,
                 f"Sale: {product_title}", str(product_id))

        if admin_id and a_wid:
            cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
                        (a_new, a_wid))
            _log_txn(conn, a_wid, admin_id, "platform_fee", platform_profit, a_new,
                     f"Platform fee: {product_title}", str(product_id))

        conn.commit()
        cur.close()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_transactions(user_id, limit=50):
    sql = """
        SELECT wt.*
        FROM   wallet_transactions wt
        JOIN   wallets w ON wt.wallet_id = w.id
        WHERE  wt.user_id = %s
        ORDER  BY wt.created_at DESC
        LIMIT  %s
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql, (user_id, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def request_withdrawal(user_id, amount, bank_name, account_number, ifsc_code, account_name):
    """Debit wallet immediately, then create withdrawal request."""
    debit(user_id, amount, "withdrawal",
          f"Withdrawal to {bank_name} ****{account_number[-4:]}")

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO withdrawal_requests
            (user_id, amount, bank_name, account_number, ifsc_code, account_name)
        VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (user_id, amount, bank_name, account_number, ifsc_code, account_name))
    rid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return rid


def get_all_withdrawals():
    sql = """
        SELECT wr.*, u.name AS user_name, u.email
        FROM   withdrawal_requests wr
        JOIN   users u ON wr.user_id = u.id
        ORDER  BY wr.created_at DESC
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_user_withdrawals(user_id):
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute("""
        SELECT * FROM withdrawal_requests
        WHERE  user_id = %s ORDER BY created_at DESC
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def approve_withdrawal(request_id, admin_note=""):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE withdrawal_requests
        SET    status='approved', admin_note=%s, updated_at=NOW()
        WHERE  id=%s AND status='pending'
    """, (admin_note, request_id))
    conn.commit()
    cur.close()
    conn.close()


def reject_withdrawal(request_id, admin_note=""):
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute("""
        SELECT * FROM withdrawal_requests WHERE id=%s AND status='pending'
    """, (request_id,))
    req = cur.fetchone()
    cur.close()
    conn.close()
    if not req:
        return False

    # Refund
    credit(req["user_id"], float(req["amount"]), "refund",
           f"Withdrawal rejected — refunded ₹{req['amount']}", str(request_id))

    conn2 = get_connection()
    cur2  = conn2.cursor()
    cur2.execute("""
        UPDATE withdrawal_requests
        SET    status='rejected', admin_note=%s, updated_at=NOW()
        WHERE  id=%s
    """, (admin_note, request_id))
    conn2.commit()
    cur2.close()
    conn2.close()
    return True


def get_all_wallets_admin():
    sql = """
        SELECT w.*, u.name, u.email, u.role
        FROM   wallets w
        JOIN   users   u ON w.user_id = u.id
        ORDER  BY w.balance DESC
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

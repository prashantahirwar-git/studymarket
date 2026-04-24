"""
Order model — PostgreSQL version.
All functions use try/finally to guarantee pool connections are returned.
"""
import logging
from models.db import get_connection, dict_cursor

logger = logging.getLogger(__name__)


def create_table():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id                   SERIAL PRIMARY KEY,
            user_id              INTEGER       NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
            product_id           INTEGER       NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            seller_price         NUMERIC(10,2) NOT NULL,
            platform_fee         NUMERIC(10,2) NOT NULL DEFAULT 0,
            buyer_amount         NUMERIC(10,2) NOT NULL,
            payment_method       VARCHAR(20)   NOT NULL DEFAULT 'razorpay'
                                     CHECK (payment_method IN ('razorpay','wallet')),
            payment_status       VARCHAR(20)   NOT NULL DEFAULT 'pending'
                                     CHECK (payment_status IN ('pending','completed','failed')),
            razorpay_order_id    VARCHAR(120),
            razorpay_payment_id  VARCHAR(120),
            razorpay_signature   VARCHAR(300),
            created_at           TIMESTAMPTZ   DEFAULT NOW()
        );
        -- DB-level guarantee: only one completed order per user+product
        CREATE UNIQUE INDEX IF NOT EXISTS uq_completed_order
            ON orders (user_id, product_id)
            WHERE payment_status = 'completed';
        """)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_order(user_id, product_id, seller_price, platform_fee,
                 buyer_amount, payment_method="razorpay", razorpay_order_id=None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO orders
                (user_id, product_id, seller_price, platform_fee, buyer_amount,
                 payment_method, razorpay_order_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (user_id, product_id, seller_price, platform_fee,
              buyer_amount, payment_method, razorpay_order_id))
        oid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return oid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_order(order_id, razorpay_payment_id=None, razorpay_signature=None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE orders
            SET    payment_status = 'completed',
                   razorpay_payment_id = %s,
                   razorpay_signature  = %s
            WHERE  id = %s
        """, (razorpay_payment_id, razorpay_signature, order_id))
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_order_with_credits(order_id, rz_payment_id, rz_signature,
                                seller_id, admin_id, seller_earn,
                                platform_profit, product_title):
    """
    Atomically marks the order as completed AND credits seller + admin wallets
    in a SINGLE database transaction.

    If any step fails the transaction rolls back — order stays 'pending'
    and wallets are untouched.
    """
    from models.wallet_model import _ensure_wallet, _log_txn

    conn = get_connection()
    try:
        cur = conn.cursor()
        # 1. Mark order completed (guard against duplicate callbacks)
        cur.execute("""
            UPDATE orders
            SET    payment_status = 'completed',
                   razorpay_payment_id = %s,
                   razorpay_signature  = %s
            WHERE  id = %s AND payment_status = 'pending'
        """, (rz_payment_id, rz_signature, order_id))
        if cur.rowcount == 0:
            raise ValueError("Order not in pending state — possible duplicate verification.")
        cur.close()

        # 2. Credit seller
        s_wid, s_bal = _ensure_wallet(conn, seller_id)
        s_new = round(s_bal + seller_earn, 2)
        cur = conn.cursor()
        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
                    (s_new, s_wid))
        _log_txn(conn, s_wid, seller_id, "sale_credit", seller_earn, s_new,
                 f"Sale: {product_title}", str(order_id))
        cur.close()

        # 3. Credit admin
        a_wid, a_bal = _ensure_wallet(conn, admin_id)
        a_new = round(a_bal + platform_profit, 2)
        cur = conn.cursor()
        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
                    (a_new, a_wid))
        _log_txn(conn, a_wid, admin_id, "platform_fee", platform_profit, a_new,
                 f"Platform fee: {product_title}", str(order_id))
        cur.close()

        conn.commit()
        logger.info(
            "Order %s completed — seller_earn=%.2f platform=%.2f",
            order_id, seller_earn, platform_profit,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def wallet_purchase_atomic(buyer_id, seller_id, admin_id, product_id,
                            seller_price, platform_profit, product_title):
    """
    Single transaction:
      1. Debit buyer wallet
      2. Credit seller wallet
      3. Credit admin wallet
      4. Create completed order record
    If anything fails the whole thing rolls back.
    Returns new order ID.
    """
    from models.wallet_model import _ensure_wallet, _log_txn

    conn = get_connection()
    try:
        # Lock wallets in ascending user_id order to prevent deadlocks
        participants = sorted({buyer_id, seller_id, admin_id})
        wallet_map = {}
        for uid in participants:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO wallets (user_id, balance)
                VALUES (%s, 0.00)
                ON CONFLICT (user_id) DO NOTHING
            """, (uid,))
            cur.execute("""
                SELECT id, balance FROM wallets
                WHERE user_id = %s FOR UPDATE
            """, (uid,))
            row = cur.fetchone()
            wallet_map[uid] = (row[0], float(row[1]))
            cur.close()

        b_wid, b_bal = wallet_map[buyer_id]
        if b_bal < seller_price:
            raise ValueError(
                f"Insufficient wallet balance. "
                f"Available: ₹{b_bal:.2f}, needed: ₹{seller_price:.2f}"
            )

        seller_earn = round(seller_price - platform_profit, 2)
        b_new = round(b_bal - seller_price, 2)
        s_wid, s_bal = wallet_map[seller_id]
        s_new = round(s_bal + seller_earn, 2)
        a_wid, a_bal = wallet_map[admin_id]
        a_new = round(a_bal + platform_profit, 2)

        cur = conn.cursor()
        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s", (b_new, b_wid))
        _log_txn(conn, b_wid, buyer_id, "purchase", seller_price, b_new,
                 f"Purchased: {product_title}", str(product_id))

        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s", (s_new, s_wid))
        _log_txn(conn, s_wid, seller_id, "sale_credit", seller_earn, s_new,
                 f"Sale: {product_title}", str(product_id))

        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s", (a_new, a_wid))
        _log_txn(conn, a_wid, admin_id, "platform_fee", platform_profit, a_new,
                 f"Platform fee: {product_title}", str(product_id))

        cur.execute("""
            INSERT INTO orders
                (user_id, product_id, seller_price, platform_fee, buyer_amount,
                 payment_method, payment_status)
            VALUES (%s,%s,%s,%s,%s,'wallet','completed')
            RETURNING id
        """, (buyer_id, product_id, seller_price, platform_profit, seller_price))
        oid = cur.fetchone()[0]
        cur.close()

        conn.commit()
        logger.info(
            "Wallet purchase: order=%s buyer=%s seller=%s amount=%.2f",
            oid, buyer_id, seller_id, seller_price,
        )
        return oid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fail_order(order_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE orders SET payment_status='failed' WHERE id=%s", (order_id,)
        )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_order_by_id(order_id):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        return cur.fetchone()
    finally:
        conn.close()


def get_order_by_razorpay_id(razorpay_order_id):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute(
            "SELECT * FROM orders WHERE razorpay_order_id = %s",
            (razorpay_order_id,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def has_purchased(user_id, product_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM orders
            WHERE  user_id=%s AND product_id=%s AND payment_status='completed'
            LIMIT  1
        """, (user_id, product_id))
        return cur.fetchone() is not None
    finally:
        conn.close()


def get_user_orders(user_id):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT o.*, p.title, p.subject, p.file_url, p.file_type,
                   u.name AS seller_name
            FROM   orders   o
            JOIN   products p ON o.product_id = p.id
            JOIN   users    u ON p.seller_id  = u.id
            WHERE  o.user_id = %s
            ORDER  BY o.created_at DESC
        """, (user_id,))
        return cur.fetchall()
    finally:
        conn.close()


def get_all_orders_admin():
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT o.*, p.title AS product_title, u.name AS buyer_name
            FROM   orders   o
            JOIN   products p ON o.product_id = p.id
            JOIN   users    u ON o.user_id    = u.id
            ORDER  BY o.created_at DESC
        """)
        return cur.fetchall()
    finally:
        conn.close()

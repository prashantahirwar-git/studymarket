"""
Order model — PostgreSQL version.
"""
from models.db import get_connection, dict_cursor


def create_table():
    sql = """
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
    -- Prevent race-condition double purchases: only one completed order per user+product
    CREATE UNIQUE INDEX IF NOT EXISTS uq_completed_order
        ON orders (user_id, product_id)
        WHERE payment_status = 'completed';
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.close()
    conn.close()


def create_order(user_id, product_id, seller_price, platform_fee,
                 buyer_amount, payment_method="razorpay", razorpay_order_id=None):
    sql = """
        INSERT INTO orders
            (user_id, product_id, seller_price, platform_fee, buyer_amount,
             payment_method, razorpay_order_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql, (user_id, product_id, seller_price, platform_fee,
                      buyer_amount, payment_method, razorpay_order_id))
    oid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return oid


def complete_order(order_id, razorpay_payment_id=None, razorpay_signature=None):
    sql = """
        UPDATE orders
        SET    payment_status = 'completed',
               razorpay_payment_id = %s,
               razorpay_signature  = %s
        WHERE  id = %s
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql, (razorpay_payment_id, razorpay_signature, order_id))
    conn.commit()
    cur.close()
    conn.close()


def fail_order(order_id):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("UPDATE orders SET payment_status='failed' WHERE id=%s", (order_id,))
    conn.commit()
    cur.close()
    conn.close()


def get_order_by_id(order_id):
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_order_by_razorpay_id(razorpay_order_id):
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute("SELECT * FROM orders WHERE razorpay_order_id = %s", (razorpay_order_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def has_purchased(user_id, product_id):
    sql = """
        SELECT id FROM orders
        WHERE  user_id=%s AND product_id=%s AND payment_status='completed'
        LIMIT  1
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql, (user_id, product_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None


def get_user_orders(user_id):
    sql = """
        SELECT o.*, p.title, p.subject, p.file_url, p.file_type,
               u.name AS seller_name
        FROM   orders   o
        JOIN   products p ON o.product_id = p.id
        JOIN   users    u ON p.seller_id  = u.id
        WHERE  o.user_id = %s
        ORDER  BY o.created_at DESC
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def complete_order_with_credits(order_id, rz_payment_id, rz_signature,
                                seller_id, admin_id, seller_earn,
                                platform_profit, product_title):
    """
    Atomically marks the order as completed AND credits seller + admin wallets
    in a SINGLE database transaction.

    If any step fails the transaction rolls back, leaving the order as 'pending'
    and wallets untouched — no money is ever credited without the order completing.
    """
    from models.wallet_model import _ensure_wallet, _log_txn

    conn = get_connection()
    try:
        # 1. Mark order completed
        cur = conn.cursor()
        cur.execute("""
            UPDATE orders
            SET    payment_status = 'completed',
                   razorpay_payment_id = %s,
                   razorpay_signature  = %s
            WHERE  id = %s AND payment_status = 'pending'
        """, (rz_payment_id, rz_signature, order_id))
        if cur.rowcount == 0:
            raise ValueError("Order was not in pending state — possible duplicate verification.")
        cur.close()

        # 2. Credit seller wallet (within same transaction)
        s_wid, s_bal = _ensure_wallet(conn, seller_id)
        s_new = round(s_bal + seller_earn, 2)
        cur = conn.cursor()
        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
                    (s_new, s_wid))
        _log_txn(conn, s_wid, seller_id, "sale_credit", seller_earn, s_new,
                 f"Sale: {product_title}", str(order_id))
        cur.close()

        # 3. Credit admin wallet (within same transaction)
        a_wid, a_bal = _ensure_wallet(conn, admin_id)
        a_new = round(a_bal + platform_profit, 2)
        cur = conn.cursor()
        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s",
                    (a_new, a_wid))
        _log_txn(conn, a_wid, admin_id, "platform_fee", platform_profit, a_new,
                 f"Platform fee: {product_title}", str(order_id))
        cur.close()

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def wallet_purchase_atomic(buyer_id, seller_id, admin_id, product_id,
                            seller_price, platform_profit, product_title):
    """
    Atomically:
      1. Debits buyer wallet
      2. Credits seller wallet
      3. Credits admin wallet
      4. Creates order record as 'completed'

    Everything happens in ONE transaction. If anything fails, the whole
    thing rolls back — buyer keeps their money and gets no access.
    Returns the new order ID on success.
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
                f"Insufficient wallet balance. Available: ₹{b_bal:.2f}, needed: ₹{seller_price:.2f}"
            )

        seller_earn = round(seller_price - platform_profit, 2)
        b_new = round(b_bal - seller_price, 2)

        s_wid, s_bal = wallet_map[seller_id]
        s_new = round(s_bal + seller_earn, 2)

        a_wid, a_bal = wallet_map[admin_id]
        a_new = round(a_bal + platform_profit, 2)

        # Debit buyer
        cur = conn.cursor()
        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s", (b_new, b_wid))
        _log_txn(conn, b_wid, buyer_id, "purchase", seller_price, b_new,
                 f"Purchased: {product_title}", str(product_id))
        cur.close()

        # Credit seller
        cur = conn.cursor()
        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s", (s_new, s_wid))
        _log_txn(conn, s_wid, seller_id, "sale_credit", seller_earn, s_new,
                 f"Sale: {product_title}", str(product_id))
        cur.close()

        # Credit admin
        cur = conn.cursor()
        cur.execute("UPDATE wallets SET balance=%s, updated_at=NOW() WHERE id=%s", (a_new, a_wid))
        _log_txn(conn, a_wid, admin_id, "platform_fee", platform_profit, a_new,
                 f"Platform fee: {product_title}", str(product_id))
        cur.close()

        # Create completed order
        cur = conn.cursor()
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
        return oid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_all_orders_admin():
    sql = """
        SELECT o.*, p.title AS product_title, u.name AS buyer_name
        FROM   orders   o
        JOIN   products p ON o.product_id = p.id
        JOIN   users    u ON o.user_id    = u.id
        ORDER  BY o.created_at DESC
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

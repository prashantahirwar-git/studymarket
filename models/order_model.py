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

"""
Product model — PostgreSQL version.
"""
from models.db import get_connection, dict_cursor


def create_table():
    sql = """
    CREATE TABLE IF NOT EXISTS products (
        id          SERIAL PRIMARY KEY,
        title       VARCHAR(255)   NOT NULL,
        description TEXT,
        price       NUMERIC(10,2)  NOT NULL DEFAULT 0.00,
        file_url    VARCHAR(500)   NOT NULL,
        file_type   VARCHAR(20),
        preview_url VARCHAR(500),
        subject     VARCHAR(120),
        college     VARCHAR(200),
        year_tag    VARCHAR(50),
        seller_id   INTEGER        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status      VARCHAR(20)    NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','approved','rejected')),
        downloads   INTEGER        DEFAULT 0,
        created_at  TIMESTAMPTZ    DEFAULT NOW()
    );
    -- Add preview_url column if upgrading an existing database
    DO $$ BEGIN
        ALTER TABLE products ADD COLUMN IF NOT EXISTS preview_url VARCHAR(500);
    EXCEPTION WHEN duplicate_column THEN NULL;
    END $$;
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.close()
    conn.close()


def create_product(title, description, price, file_url, file_type,
                   subject, college, year_tag, seller_id, preview_url=None):
    sql = """
        INSERT INTO products
            (title, description, price, file_url, file_type, preview_url,
             subject, college, year_tag, seller_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql, (title, description, price, file_url, file_type, preview_url,
                      subject, college, year_tag, seller_id))
    pid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return pid


def get_approved_products(search=None, subject=None, max_price=None, college=None):
    conditions = ["p.status = 'approved'"]
    params = []

    if search:
        conditions.append(
            "(p.title ILIKE %s OR p.description ILIKE %s OR p.subject ILIKE %s)"
        )
        like = f"%{search}%"
        params.extend([like, like, like])
    if subject:
        conditions.append("p.subject = %s")
        params.append(subject)
    if max_price is not None:
        conditions.append("p.price <= %s")
        params.append(max_price)
    if college:
        conditions.append("p.college ILIKE %s")
        params.append(f"%{college}%")

    where = " AND ".join(conditions)
    sql = f"""
        SELECT p.*,
               u.name                        AS seller_name,
               COALESCE(AVG(r.rating), 0)    AS avg_rating,
               COUNT(DISTINCT r.id)          AS review_count
        FROM   products p
        JOIN   users    u ON p.seller_id = u.id
        LEFT JOIN reviews r ON r.product_id = p.id
        WHERE  {where}
        GROUP  BY p.id, u.name
        ORDER  BY p.created_at DESC
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_product_by_id(product_id):
    sql = """
        SELECT p.*,
               u.name                        AS seller_name,
               COALESCE(AVG(r.rating), 0)    AS avg_rating,
               COUNT(DISTINCT r.id)          AS review_count
        FROM   products p
        JOIN   users    u ON p.seller_id = u.id
        LEFT JOIN reviews r ON r.product_id = p.id
        WHERE  p.id = %s
        GROUP  BY p.id, u.name
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql, (product_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_seller_products(seller_id):
    sql = """
        SELECT p.*,
               COALESCE(COUNT(DISTINCT o.id), 0)  AS total_sales,
               COALESCE(SUM(o.seller_price), 0)   AS total_earnings
        FROM   products p
        LEFT JOIN orders o
               ON o.product_id = p.id AND o.payment_status = 'completed'
        WHERE  p.seller_id = %s
        GROUP  BY p.id
        ORDER  BY p.created_at DESC
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql, (seller_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_all_products_admin():
    sql = """
        SELECT p.*, u.name AS seller_name
        FROM   products p
        JOIN   users    u ON p.seller_id = u.id
        ORDER  BY p.created_at DESC
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def update_product_status(product_id, status):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("UPDATE products SET status = %s WHERE id = %s", (status, product_id))
    conn.commit()
    cur.close()
    conn.close()


def delete_product(product_id):
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute("SELECT file_url FROM products WHERE id = %s", (product_id,))
    row = cur.fetchone()
    cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
    conn.commit()
    cur.close()
    conn.close()
    return row["file_url"] if row else None


def increment_downloads(product_id):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("UPDATE products SET downloads = downloads + 1 WHERE id = %s", (product_id,))
    conn.commit()
    cur.close()
    conn.close()


def get_distinct_subjects():
    sql  = """
        SELECT DISTINCT subject FROM products
        WHERE  status = 'approved' AND subject IS NOT NULL AND subject <> ''
        ORDER  BY subject
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql)
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def get_top_sellers(limit=5):
    sql = """
        SELECT u.id, u.name,
               COUNT(o.id)         AS total_sales,
               SUM(o.seller_price) AS total_earnings
        FROM   orders   o
        JOIN   products p ON o.product_id = p.id
        JOIN   users    u ON p.seller_id  = u.id
        WHERE  o.payment_status = 'completed'
        GROUP  BY u.id, u.name
        ORDER  BY total_sales DESC
        LIMIT  %s
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

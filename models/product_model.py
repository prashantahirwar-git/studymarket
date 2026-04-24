"""
Product model — PostgreSQL version.
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
            status      VARCHAR(20)    NOT NULL DEFAULT 'approved'
                            CHECK (status IN ('pending','approved','rejected')),
            downloads   INTEGER        DEFAULT 0,
            created_at  TIMESTAMPTZ    DEFAULT NOW()
        );
        -- Add preview_url column if upgrading an existing database
        DO $$ BEGIN
            ALTER TABLE products ADD COLUMN IF NOT EXISTS preview_url VARCHAR(500);
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$;
        """)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_product(title, description, price, file_url, file_type,
                   subject, college, year_tag, seller_id, preview_url=None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO products
                (title, description, price, file_url, file_type, preview_url,
                 subject, college, year_tag, seller_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (title, description, price, file_url, file_type, preview_url,
              subject, college, year_tag, seller_id))
        pid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        logger.info("Product created: id=%s seller=%s", pid, seller_id)
        return pid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_approved_products(search=None, subject=None, max_price=None,
                          college=None, page=1, per_page=20):
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

    where  = " AND ".join(conditions)
    offset = (page - 1) * per_page

    count_sql = f"SELECT COUNT(*) FROM products p WHERE {where}"
    data_sql  = f"""
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
        LIMIT  %s OFFSET %s
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(count_sql, params)
        total = cur.fetchone()[0]
        cur.close()

        cur = dict_cursor(conn)
        cur.execute(data_sql, params + [per_page, offset])
        rows = cur.fetchall()
        return rows, total
    finally:
        conn.close()


def get_product_by_id(product_id):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT p.*,
                   u.name                        AS seller_name,
                   COALESCE(AVG(r.rating), 0)    AS avg_rating,
                   COUNT(DISTINCT r.id)          AS review_count
            FROM   products p
            JOIN   users    u ON p.seller_id = u.id
            LEFT JOIN reviews r ON r.product_id = p.id
            WHERE  p.id = %s
            GROUP  BY p.id, u.name
        """, (product_id,))
        return cur.fetchone()
    finally:
        conn.close()


def get_seller_products(seller_id):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT p.*,
                   COALESCE(COUNT(DISTINCT o.id), 0)  AS total_sales,
                   COALESCE(SUM(o.seller_price), 0)   AS total_earnings
            FROM   products p
            LEFT JOIN orders o
                   ON o.product_id = p.id AND o.payment_status = 'completed'
            WHERE  p.seller_id = %s
            GROUP  BY p.id
            ORDER  BY p.created_at DESC
        """, (seller_id,))
        return cur.fetchall()
    finally:
        conn.close()


def get_all_products_admin():
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT p.*, u.name AS seller_name
            FROM   products p
            JOIN   users    u ON p.seller_id = u.id
            ORDER  BY p.created_at DESC
        """)
        return cur.fetchall()
    finally:
        conn.close()


def update_product_status(product_id, status):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE products SET status = %s WHERE id = %s", (status, product_id)
        )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_product(product_id):
    """
    Returns (file_url, preview_url) so the caller can clean up both files
    from storage. Both may be None.
    """
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute(
            "SELECT file_url, preview_url FROM products WHERE id = %s",
            (product_id,),
        )
        row = cur.fetchone()
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
        conn.commit()
        cur.close()
        if row:
            return row["file_url"], row.get("preview_url")
        return None, None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def increment_downloads(product_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE products SET downloads = downloads + 1 WHERE id = %s",
            (product_id,),
        )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_distinct_subjects():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT subject FROM products
            WHERE  status = 'approved' AND subject IS NOT NULL AND subject <> ''
            ORDER  BY subject
        """)
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def get_top_sellers(limit=5):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
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
        """, (limit,))
        return cur.fetchall()
    finally:
        conn.close()

"""
Review model — PostgreSQL version.
"""
from models.db import get_connection, dict_cursor


def create_table():
    sql = """
    CREATE TABLE IF NOT EXISTS reviews (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER  NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
        product_id  INTEGER  NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
        comment     TEXT,
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE (user_id, product_id)
    );
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.close()
    conn.close()


def add_review(user_id, product_id, rating, comment):
    # Upsert: update if already reviewed, insert if not
    sql = """
        INSERT INTO reviews (user_id, product_id, rating, comment)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, product_id)
        DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql, (user_id, product_id, rating, comment))
    conn.commit()
    cur.close()
    conn.close()


def get_product_reviews(product_id):
    sql = """
        SELECT r.*, u.name AS reviewer_name
        FROM   reviews r
        JOIN   users   u ON r.user_id = u.id
        WHERE  r.product_id = %s
        ORDER  BY r.created_at DESC
    """
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql, (product_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def has_reviewed(user_id, product_id):
    sql  = "SELECT id FROM reviews WHERE user_id=%s AND product_id=%s LIMIT 1"
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql, (user_id, product_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None

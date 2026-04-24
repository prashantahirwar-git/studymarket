"""
Review model — PostgreSQL version.
"""
import logging
from models.db import get_connection, dict_cursor

logger = logging.getLogger(__name__)


def create_table():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER  NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
            product_id  INTEGER  NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment     TEXT,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (user_id, product_id)
        );
        """)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_review(user_id, product_id, rating, comment):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reviews (user_id, product_id, rating, comment)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, product_id)
            DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment
        """, (user_id, product_id, rating, comment))
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_product_reviews(product_id):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT r.*, u.name AS reviewer_name
            FROM   reviews r
            JOIN   users   u ON r.user_id = u.id
            WHERE  r.product_id = %s
            ORDER  BY r.created_at DESC
        """, (product_id,))
        return cur.fetchall()
    finally:
        conn.close()


def has_reviewed(user_id, product_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM reviews WHERE user_id=%s AND product_id=%s LIMIT 1",
            (user_id, product_id),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()

"""
User model — PostgreSQL version.
All functions use try/finally to guarantee connections are returned to pool.
"""
import logging
import bcrypt
from models.db import get_connection, dict_cursor

logger = logging.getLogger(__name__)

# Pre-computed hash used by dummy_verify() to keep login timing consistent
_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt()).decode()


def create_table():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id         SERIAL PRIMARY KEY,
            name       VARCHAR(120) NOT NULL,
            email      VARCHAR(255) NOT NULL UNIQUE,
            password   VARCHAR(255) NOT NULL,
            role       VARCHAR(20)  NOT NULL DEFAULT 'buyer'
                           CHECK (role IN ('buyer','seller','admin')),
            created_at TIMESTAMPTZ  DEFAULT NOW()
        );
        """)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_user(name, email, password, role="buyer"):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (name, email, password, role)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (name, email, hashed, role))
        uid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return uid
    except Exception:
        conn.rollback()
        return None   # unique email violation
    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute(
            "SELECT id, name, email, password, role FROM users WHERE email = %s",
            (email,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute(
            "SELECT id, name, email, role FROM users WHERE id = %s",
            (user_id,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def dummy_verify():
    """
    Run a bcrypt check against a dummy hash so that failed-login responses
    take the same time whether the email exists or not. This prevents
    timing-based email enumeration.
    """
    bcrypt.checkpw(b"dummy", _DUMMY_HASH.encode())


def get_all_users():
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute(
            "SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC"
        )
        return cur.fetchall()
    finally:
        conn.close()


def get_admin_user():
    """
    Returns the single admin user (created by seed_admin.py).
    Raises RuntimeError if no admin exists — ensures platform profit
    always has a destination before any payment is processed.
    """
    conn = get_connection()
    try:
        cur = dict_cursor(conn)
        cur.execute("SELECT id, name, email FROM users WHERE role = 'admin' LIMIT 1")
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise RuntimeError(
            "No admin user found. Run seed_admin.py before accepting payments."
        )
    return row


def delete_user(user_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_user_role(user_id, role):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

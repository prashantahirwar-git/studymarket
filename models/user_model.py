"""
User model — PostgreSQL version.
"""
import bcrypt
from models.db import get_connection, dict_cursor


def create_table():
    sql = """
    CREATE TABLE IF NOT EXISTS users (
        id         SERIAL PRIMARY KEY,
        name       VARCHAR(120) NOT NULL,
        email      VARCHAR(255) NOT NULL UNIQUE,
        password   VARCHAR(255) NOT NULL,
        role       VARCHAR(20)  NOT NULL DEFAULT 'buyer'
                       CHECK (role IN ('buyer','seller','admin')),
        created_at TIMESTAMPTZ  DEFAULT NOW()
    );
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.close()
    conn.close()


def create_user(name, email, password, role="buyer"):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    sql = """
        INSERT INTO users (name, email, password, role)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute(sql, (name, email, hashed, role))
        uid = cur.fetchone()[0]
        conn.commit()
        return uid
    except Exception:          # unique violation
        conn.rollback()
        return None
    finally:
        cur.close()
        conn.close()


def get_user_by_email(email):
    sql  = "SELECT id, name, email, password, role FROM users WHERE email = %s"
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql, (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_user_by_id(user_id):
    sql  = "SELECT id, name, email, role FROM users WHERE id = %s"
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql, (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def verify_password(plain, hashed):
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def get_all_users():
    sql  = "SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC"
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_admin_user():
    """
    Returns the single admin user created by seed_admin.py.
    Raises RuntimeError if no admin exists — ensures profits always have a destination.
    """
    sql  = "SELECT id, name, email FROM users WHERE role = 'admin' LIMIT 1"
    conn = get_connection()
    cur  = dict_cursor(conn)
    cur.execute(sql)
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise RuntimeError(
            "No admin user found. Run seed_admin.py before accepting payments."
        )
    return row


def delete_user(user_id):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()


def update_user_role(user_id, role):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))
    conn.commit()
    cur.close()
    conn.close()

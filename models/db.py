"""
db.py — Central PostgreSQL connection helper using psycopg2.
All models import get_connection() from here.

Key differences from MySQL:
  - Placeholders are %s in both (same)
  - AUTO_INCREMENT  →  SERIAL or GENERATED ALWAYS AS IDENTITY
  - ON DUPLICATE KEY UPDATE  →  ON CONFLICT DO UPDATE
  - ENUM types  →  VARCHAR with CHECK constraint
  - TINYINT  →  SMALLINT
  - lastrowid  →  RETURNING id  (fetchone()[0])
  - dictionary cursor  →  RealDictCursor
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL


def get_connection():
    """Return a new psycopg2 connection. Caller is responsible for closing."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


def dict_cursor(conn):
    """Return a cursor that yields rows as dicts."""
    return conn.cursor(cursor_factory=RealDictCursor)

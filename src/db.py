"""Database helpers, shared by the loader, the notebooks and the dashboard."""
import sqlite3

from config import DB_PATH, ROOT

SCHEMA_FILE = ROOT / "sql" / "schema.sql"


def connect(db_path=DB_PATH):
    """Open the SQLite database. The file is created if it does not exist yet."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    # SQLite IGNORES foreign keys unless you switch them on, on every new connection.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn):
    """Create tables, index and views from sql/schema.sql (safe to run many times)."""
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))

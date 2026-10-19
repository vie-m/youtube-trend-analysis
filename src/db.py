"""Database helpers, shared by the loader, the notebooks and the dashboard."""
import sqlite3

from config import DB_PATH, ROOT

SCHEMA_FILE = ROOT / "sql" / "schema.sql"
QUERIES_FILE = ROOT / "sql" / "analysis.sql"


class Median:
    """MEDIAN(x) for SQL queries. SQLite has AVG() but no MEDIAN(), so we add one from Python.

    SQLite calls step() once per row and finalize() once per group, like AVG() does.
    NULLs are skipped (same as AVG and pandas' median). Only works on connections
    made with connect() below, so not in DB Browser for SQLite.
    """

    def __init__(self):
        self.values = []

    def step(self, value):
        if value is not None:
            self.values.append(value)

    def finalize(self):
        if not self.values:
            return None
        v = sorted(self.values)
        mid = len(v) // 2
        return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


def connect(db_path=DB_PATH):
    """Open the SQLite database. The file is created if it does not exist yet."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    # SQLite IGNORES foreign keys unless you switch them on, on every new connection.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_aggregate("MEDIAN", 1, Median)
    return conn


def create_schema(conn):
    """Create tables, index and views from sql/schema.sql (safe to run many times)."""
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))


def load_queries(path=QUERIES_FILE):
    """Read named SQL queries from a .sql file into a dict {name: sql}.

    Each query starts with a line like `-- name: by_weekday`. Keeping the SQL in its
    own file means you can read and test it on its own, and the notebook and the
    dashboard can share the exact same queries.
    """
    queries, name = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("-- name:"):
            name = line.split(":", 1)[1].strip()
            queries[name] = []
        elif name:
            queries[name].append(line)
    return {k: "\n".join(v).strip().rstrip(";") for k, v in queries.items()}

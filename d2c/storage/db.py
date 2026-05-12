import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent.parent / "schema" / "canonical.sql"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # timeout (Python-side) + busy_timeout (SQLite-side) so writers wait
    # politely when readers (e.g., the long-lived MCP server) hold a shared
    # lock. Without this, the default 0ms busy_timeout fails immediately.
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def bootstrap(conn: sqlite3.Connection) -> None:
    """Apply the canonical schema, then any post-create migrations."""
    schema_sql = SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply ALTER-style migrations for columns added after first bootstrap.

    SQLite has no ADD COLUMN IF NOT EXISTS — swallow the duplicate-column error
    to keep this idempotent.
    """
    statements = [
        "ALTER TABLE orders ADD COLUMN total_discount REAL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN total_tax REAL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN total_shipping REAL DEFAULT 0",
    ]
    for stmt in statements:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise

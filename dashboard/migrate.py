# dashboard/migrate.py
"""Run idempotent schema migrations on inbox.db."""
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".claude" / "eng-buddy" / "inbox.db"

MIGRATIONS = [
    # New columns for smart classification
    "ALTER TABLE cards ADD COLUMN section TEXT DEFAULT 'needs-action'",
    "ALTER TABLE cards ADD COLUMN draft_response TEXT",
    "ALTER TABLE cards ADD COLUMN context_notes TEXT",
    "ALTER TABLE cards ADD COLUMN responded INTEGER DEFAULT 0",
    "ALTER TABLE cards ADD COLUMN filter_suggested INTEGER DEFAULT 0",
    # Stats table
    """CREATE TABLE IF NOT EXISTS stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        metric TEXT NOT NULL,
        value REAL DEFAULT 0,
        details TEXT
    )""",
    # Briefing cache
    """CREATE TABLE IF NOT EXISTS briefings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE NOT NULL,
        content TEXT NOT NULL,
        generated_at TEXT NOT NULL
    )""",
    # Filter suggestions tracking
    """CREATE TABLE IF NOT EXISTS filter_suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        pattern TEXT NOT NULL,
        ignore_count INTEGER DEFAULT 0,
        suggested_at TEXT,
        status TEXT DEFAULT 'tracking',
        filter_id TEXT
    )""",
]


def migrate():
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(DB_PATH)
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                print(f"Migration warning: {e}")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    migrate()
    print("Migrations complete.")

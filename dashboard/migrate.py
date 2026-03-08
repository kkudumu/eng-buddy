# dashboard/migrate.py
"""Run idempotent schema migrations on inbox.db."""
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".claude" / "eng-buddy" / "inbox.db"

MIGRATIONS = [
    # Base cards table (for fresh installs)
    """CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        timestamp TEXT,
        summary TEXT,
        classification TEXT,
        status TEXT DEFAULT 'pending',
        proposed_actions TEXT,
        execution_status TEXT DEFAULT 'not_run',
        execution_result TEXT,
        executed_at TEXT,
        section TEXT DEFAULT 'needs-action',
        draft_response TEXT,
        context_notes TEXT,
        responded INTEGER DEFAULT 0,
        filter_suggested INTEGER DEFAULT 0,
        refinement_history TEXT
    )""",
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
    # Decision log
    """CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        source TEXT,
        summary TEXT,
        context_notes TEXT,
        draft_response TEXT,
        refinement_history TEXT,
        execution_result TEXT,
        decision_at TEXT NOT NULL,
        tags TEXT
    )""",
    # FTS5 index for decision search
    """CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
        summary, context_notes, draft_response, execution_result, tags,
        content='decisions', content_rowid='id'
    )""",
    # Triggers to keep FTS in sync
    """CREATE TRIGGER IF NOT EXISTS decisions_ai AFTER INSERT ON decisions BEGIN
        INSERT INTO decisions_fts(rowid, summary, context_notes, draft_response, execution_result, tags)
        VALUES (new.id, new.summary, new.context_notes, new.draft_response, new.execution_result, new.tags);
    END""",
    """CREATE TRIGGER IF NOT EXISTS decisions_ad AFTER DELETE ON decisions BEGIN
        INSERT INTO decisions_fts(decisions_fts, rowid, summary, context_notes, draft_response, execution_result, tags)
        VALUES ('delete', old.id, old.summary, old.context_notes, old.draft_response, old.execution_result, old.tags);
    END""",
    """CREATE TRIGGER IF NOT EXISTS decisions_au AFTER UPDATE ON decisions BEGIN
        INSERT INTO decisions_fts(decisions_fts, rowid, summary, context_notes, draft_response, execution_result, tags)
        VALUES ('delete', old.id, old.summary, old.context_notes, old.draft_response, old.execution_result, old.tags);
        INSERT INTO decisions_fts(rowid, summary, context_notes, draft_response, execution_result, tags)
        VALUES (new.id, new.summary, new.context_notes, new.draft_response, new.execution_result, new.tags);
    END""",
    # Refinement history on cards
    "ALTER TABLE cards ADD COLUMN refinement_history TEXT",
    # Deduplicate all cards: keep newest per (source, summary), delete older copies
    """DELETE FROM cards WHERE id NOT IN (
        SELECT MAX(id) FROM cards GROUP BY source, summary
    )""",
    # Unique index to prevent future duplicates (source + summary)
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_cards_source_summary ON cards(source, summary)",
]


def migrate():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as e:
            if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                print(f"Migration warning: {e}")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    migrate()
    print("Migrations complete.")

import sqlite3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import DB_PATH, get_db, _ensure_audit_schema

# Trigger migration on import
_ensure_audit_schema()

def test_enrichment_status_column_exists():
    """After migration, cards table should have enrichment_status column."""
    conn = get_db()
    cursor = conn.execute("PRAGMA table_info(cards)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    assert "enrichment_status" in columns

def test_classification_buckets_table_exists():
    conn = get_db()
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='classification_buckets'"
    )
    assert cursor.fetchone() is not None
    conn.close()

def test_enrichment_runs_table_exists():
    conn = get_db()
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='enrichment_runs'"
    )
    assert cursor.fetchone() is not None
    conn.close()

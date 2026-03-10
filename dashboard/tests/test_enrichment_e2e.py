"""
End-to-end test: insert a fake freshservice card, run the enrichment pipeline
(mocking the LLM and Freshservice API), verify card gets enriched with actions.
"""
import json, os, sys, sqlite3, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bin"))

def _load_module():
    spec = __import__("importlib").util.spec_from_file_location(
        "enrichment",
        os.path.join(os.path.dirname(__file__), "..", "..", "bin", "freshservice-enrichment.py"),
    )
    mod = __import__("importlib").util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_e2e_classify_and_enrich(tmp_path, monkeypatch):
    mod = _load_module()

    # Use temp DB
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(mod, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE cards (
        id INTEGER PRIMARY KEY, source TEXT, timestamp TEXT, summary TEXT,
        classification TEXT DEFAULT 'needs-response', status TEXT DEFAULT 'pending',
        proposed_actions TEXT, analysis_metadata TEXT, enrichment_status TEXT DEFAULT 'not_enriched',
        execution_status TEXT DEFAULT 'not_run', section TEXT, context_notes TEXT,
        draft_response TEXT, responded INTEGER DEFAULT 0, filter_suggested INTEGER DEFAULT 0,
        refinement_history TEXT, queue TEXT, user_edit TEXT, actioned_at TEXT,
        turns INTEGER DEFAULT 0, execution_result TEXT, executed_at TEXT, event_id INTEGER, draft TEXT
    )""")
    conn.execute("""CREATE TABLE classification_buckets (
        id TEXT PRIMARY KEY, description TEXT, knowledge_files TEXT DEFAULT '[]',
        confidence_keywords TEXT DEFAULT '[]', ticket_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'emerging', created_by_ticket INTEGER,
        created_at TEXT, updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE enrichment_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, card_id INTEGER, stage TEXT,
        model TEXT, duration_ms INTEGER, status TEXT, response_summary TEXT, created_at TEXT
    )""")
    conn.execute("""CREATE UNIQUE INDEX idx_cards_source_summary ON cards(source, summary)""")

    # Insert test card
    meta = json.dumps({"ticket_id": 99999, "status": "Open", "priority": "Medium", "type": "Service Request"})
    conn.execute(
        "INSERT INTO cards (source, timestamp, summary, analysis_metadata, enrichment_status) VALUES (?, ?, ?, ?, ?)",
        ("freshservice", "2026-03-10T00:00:00Z", "#99999 [Service Request] Test Jira Access", meta, "not_enriched"),
    )
    conn.commit()
    conn.close()

    # Mock LLM calls
    call_count = {"n": 0}
    def mock_llm(prompt, stage, timeout=60):
        call_count["n"] += 1
        if stage == "classify":
            return json.dumps({
                "bucket_id": "jira-admin",
                "bucket_description": "Jira admin tasks",
                "is_new_bucket": True,
                "knowledge_files": ["jira-api-reference.md"],
                "confidence_keywords": ["jira", "access"],
                "reasoning": "test",
            })
        elif stage == "enrich":
            return json.dumps({
                "proposed_actions": [
                    {"type": "grant_access", "draft": "Grant Jira access to user"},
                    {"type": "reply_to_requester", "draft": "Confirm access granted"},
                ],
                "playbook_match": None,
            })
        return "{}"

    monkeypatch.setattr(mod, "_run_llm", mock_llm)
    monkeypatch.setattr(mod, "fetch_ticket_description", lambda tid: "User needs Jira access")
    monkeypatch.setattr(mod, "invalidate_dashboard", lambda: None)
    monkeypatch.setattr(mod, "load_approved_playbooks_summary", lambda: "No playbooks")

    # Run pipeline
    cards = mod.fetch_unenriched_cards()
    assert len(cards) == 1

    success = mod.enrich_single_card(cards[0])
    assert success is True
    assert call_count["n"] == 2  # classify + enrich

    # Verify card was enriched
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    card = dict(conn.execute("SELECT * FROM cards WHERE id = 1").fetchone())
    conn.close()

    assert card["enrichment_status"] == "enriched"
    actions = json.loads(card["proposed_actions"])
    assert len(actions) == 2
    assert actions[0]["type"] == "grant_access"

    meta = json.loads(card["analysis_metadata"])
    assert meta["classification_bucket"] == "jira-admin"

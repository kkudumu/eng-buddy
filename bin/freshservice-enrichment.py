#!/usr/bin/env python3
"""
eng-buddy Freshservice Enrichment Pipeline
3-stage AI pipeline: classify → enrich+playbook match → detect patterns.
Runs as LaunchAgent, picks up un-enriched cards from inbox.db.
"""
import json
import os
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path.home() / ".claude" / "eng-buddy"
DB_PATH = BASE_DIR / "inbox.db"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
HEALTH_FILE = BASE_DIR / "health" / "freshservice-enrichment.json"

FRESHSERVICE_DOMAIN = os.environ.get("FRESHSERVICE_DOMAIN", "klaviyo.freshservice.com")
API_KEY = os.environ.get("FRESHSERVICE_API_KEY", "vh78yaatCXcXaHODpYl")
_AUTH = b64encode(f"{API_KEY}:X".encode()).decode()
_FS_HEADERS = {
    "Authorization": f"Basic {_AUTH}",
    "Content-Type": "application/json",
}

DASHBOARD_INVALIDATE_URL = os.environ.get(
    "ENG_BUDDY_DASHBOARD_INVALIDATE_URL",
    "http://127.0.0.1:7777/api/cache-invalidate",
)

MAX_WORKERS = 5
PATTERN_LOOKBACK_DAYS = 30
VETTED_THRESHOLD = 3

# --- Per-stage LLM routing ---
STAGE_LLM_CONFIG = {
    "classify": {"cli": "claude", "args": ["-p"]},
    "enrich": {"cli": "claude", "args": ["-p"]},
    "detect_patterns": {"cli": "claude", "args": ["-p"]},
}


def _llm_env():
    """Clean env for spawning LLM CLI."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    path_parts = ["/opt/homebrew/bin", "/usr/local/bin"]
    existing = env.get("PATH", "")
    if existing:
        path_parts.append(existing)
    env["PATH"] = ":".join(path_parts)
    return env


def _run_llm(prompt: str, stage: str, timeout: int = 60) -> str:
    """Route to configured LLM per stage. Returns raw stdout."""
    config = STAGE_LLM_CONFIG.get(stage, {"cli": "claude", "args": ["-p"]})
    cmd = [config["cli"]] + config["args"] + [prompt]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_llm_env(),
    )
    return result.stdout.strip()


def _parse_llm_json(raw: str, opening: str = "{"):
    """Extract first balanced JSON object/array from LLM output."""
    closing = "}" if opening == "{" else "]"
    for start, char in enumerate(raw):
        if char != opening:
            continue
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(raw)):
            c = raw[i]
            if in_string:
                if escape:
                    escape = False
                    continue
                if c == "\\":
                    escape = True
                    continue
                if c == '"':
                    in_string = False
                continue
            if c == '"':
                in_string = True
                continue
            if c == opening:
                depth += 1
            elif c == closing:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def invalidate_dashboard():
    """Notify dashboard to refresh Freshservice cards."""
    payload = json.dumps({"source": "freshservice"}).encode()
    req = urllib.request.Request(
        DASHBOARD_INVALIDATE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2):
            return
    except (urllib.error.URLError, TimeoutError, OSError):
        return


def write_health(status: str, enriched_count: int, errors: int = 0):
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps({
        "status": status,
        "last_run": datetime.now(timezone.utc).isoformat(),
        "enriched_count": enriched_count,
        "errors": errors,
    }))


def log_enrichment_run(card_id: int, stage: str, model: str, duration_ms: int,
                        status: str, response_summary: str = ""):
    """Write observability record."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO enrichment_runs (card_id, stage, model, duration_ms, status, response_summary)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [card_id, stage, model, duration_ms, status, response_summary[:500]],
        )
        conn.commit()
    finally:
        conn.close()


# --- Stage 1: Classification ---

def load_classification_schema() -> dict:
    """Load current AI-built schema from DB."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM classification_buckets").fetchall()
        buckets = {}
        for row in rows:
            buckets[row["id"]] = {
                "description": row["description"],
                "knowledge_files": json.loads(row["knowledge_files"] or "[]"),
                "confidence_keywords": json.loads(row["confidence_keywords"] or "[]"),
                "ticket_count": row["ticket_count"],
                "status": row["status"],
            }
        return {"buckets": buckets}
    finally:
        conn.close()


def fast_path_classify(card: dict, schema: dict) -> str | None:
    """Check vetted buckets' AI-generated keywords. Returns bucket_id or None."""
    summary_lower = card.get("summary", "").lower()
    meta = json.loads(card.get("analysis_metadata") or "{}")
    ticket_type = str(meta.get("type", "")).lower()
    text = f"{summary_lower} {ticket_type}"

    for bucket_id, bucket in schema.get("buckets", {}).items():
        if bucket.get("status") != "vetted":
            continue
        keywords = bucket.get("confidence_keywords", [])
        if any(kw.lower() in text for kw in keywords):
            return bucket_id
    return None


def build_classify_prompt(card: dict, schema: dict) -> str:
    """Build the classification prompt for a Freshservice ticket."""
    meta = json.loads(card.get("analysis_metadata") or "{}")
    summary = card.get("summary", "")

    # List available knowledge files
    available_knowledge = []
    if KNOWLEDGE_DIR.exists():
        available_knowledge = [f.name for f in KNOWLEDGE_DIR.iterdir() if f.suffix == ".md"]

    schema_json = json.dumps(schema.get("buckets", {}), indent=2) if schema.get("buckets") else "{}"

    return (
        "You are classifying an IT support ticket for an IT systems engineer.\n\n"
        f"Ticket: {summary}\n"
        f"Type: {meta.get('type', 'unknown')} | Priority: {meta.get('priority', 'unknown')}\n"
        f"Status: {meta.get('status', 'unknown')} | Created: {meta.get('created_at', 'unknown')}\n\n"
        f"Current classification schema:\n{schema_json}\n\n"
        f"Available knowledge files: {json.dumps(available_knowledge)}\n\n"
        "Tasks:\n"
        "1. Classify this ticket into an existing bucket, or propose a new one.\n"
        "2. List which knowledge files would help resolve this ticket.\n"
        "3. Provide 3-5 confidence keywords that future similar tickets would contain.\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "bucket_id": "kebab-case-name",\n'
        '  "bucket_description": "what this category covers",\n'
        '  "is_new_bucket": true/false,\n'
        '  "knowledge_files": ["file.md"],\n'
        '  "confidence_keywords": ["keyword1", "keyword2"],\n'
        '  "reasoning": "one sentence"\n'
        "}"
    )


def parse_classify_response(raw: str) -> dict | None:
    """Parse classification JSON from LLM response."""
    result = _parse_llm_json(raw, "{")
    if not isinstance(result, dict):
        return None
    if "bucket_id" not in result:
        return None
    # Normalize
    result["bucket_id"] = str(result["bucket_id"]).strip().lower().replace(" ", "-")
    result["is_new_bucket"] = bool(result.get("is_new_bucket", False))
    result["knowledge_files"] = result.get("knowledge_files", [])
    if not isinstance(result["knowledge_files"], list):
        result["knowledge_files"] = []
    result["confidence_keywords"] = result.get("confidence_keywords", [])
    if not isinstance(result["confidence_keywords"], list):
        result["confidence_keywords"] = []
    return result


def save_classification(card_id: int, classification: dict, schema: dict):
    """Persist classification to card metadata and update schema."""
    conn = get_db()
    try:
        # Update card's analysis_metadata with classification
        row = conn.execute("SELECT analysis_metadata FROM cards WHERE id = ?", [card_id]).fetchone()
        meta = json.loads(row["analysis_metadata"] or "{}") if row else {}
        meta["classification_bucket"] = classification["bucket_id"]
        meta["classification_knowledge_files"] = classification["knowledge_files"]
        meta["classification_reasoning"] = classification.get("reasoning", "")
        conn.execute(
            "UPDATE cards SET analysis_metadata = ? WHERE id = ?",
            [json.dumps(meta), card_id],
        )

        bucket_id = classification["bucket_id"]
        if classification["is_new_bucket"]:
            conn.execute(
                """INSERT OR IGNORE INTO classification_buckets
                   (id, description, knowledge_files, confidence_keywords, ticket_count, status, created_by_ticket)
                   VALUES (?, ?, ?, ?, 1, 'emerging', ?)""",
                [
                    bucket_id,
                    classification.get("bucket_description", ""),
                    json.dumps(classification["knowledge_files"]),
                    json.dumps(classification["confidence_keywords"]),
                    card_id,
                ],
            )
        else:
            conn.execute(
                """UPDATE classification_buckets
                   SET ticket_count = ticket_count + 1,
                       confidence_keywords = ?,
                       updated_at = datetime('now'),
                       status = CASE WHEN ticket_count + 1 >= ? THEN 'vetted' ELSE status END
                   WHERE id = ?""",
                [json.dumps(classification["confidence_keywords"]), VETTED_THRESHOLD, bucket_id],
            )

        conn.commit()
    finally:
        conn.close()


def stage_classify(card: dict) -> dict | None:
    """Run classification stage. Returns classification dict or None on failure."""
    card_id = card["id"]
    schema = load_classification_schema()

    # Try fast-path first (vetted buckets)
    fast = fast_path_classify(card, schema)
    if fast:
        bucket = schema["buckets"][fast]
        result = {
            "bucket_id": fast,
            "bucket_description": bucket["description"],
            "is_new_bucket": False,
            "knowledge_files": bucket["knowledge_files"],
            "confidence_keywords": bucket["confidence_keywords"],
            "reasoning": "fast-path keyword match",
        }
        save_classification(card_id, result, schema)
        log_enrichment_run(card_id, "classify", "fast-path", 0, "success", f"bucket={fast}")
        return result

    # AI classification
    prompt = build_classify_prompt(card, schema)
    model = STAGE_LLM_CONFIG["classify"]["cli"]
    start = time.time()
    try:
        raw = _run_llm(prompt, "classify", timeout=30)
        duration_ms = int((time.time() - start) * 1000)
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        log_enrichment_run(card_id, "classify", model, duration_ms, "failed", str(e))
        return None

    result = parse_classify_response(raw)
    if not result:
        log_enrichment_run(card_id, "classify", model, duration_ms, "failed", raw[:200])
        return None

    save_classification(card_id, result, schema)
    log_enrichment_run(card_id, "classify", model, duration_ms, "success",
                        f"bucket={result['bucket_id']} new={result['is_new_bucket']}")
    return result


# --- Freshservice API helpers ---

def fetch_ticket_description(ticket_id: int) -> str:
    """Fetch ticket description from Freshservice API."""
    url = f"https://{FRESHSERVICE_DOMAIN}/api/v2/tickets/{ticket_id}?include=conversations"
    req = urllib.request.Request(url, headers=_FS_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            ticket = data.get("ticket", {})
            desc = ticket.get("description_text") or ticket.get("description") or ""
            # Also grab first few conversation entries for context
            convos = data.get("conversations", [])
            convo_text = ""
            for c in convos[:3]:
                body = c.get("body_text") or c.get("body") or ""
                if body:
                    convo_text += f"\n---\n{body[:500]}"
            return (desc[:2000] + convo_text[:1000]).strip()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"  Failed to fetch ticket {ticket_id} description: {e}")
        return ""


def load_knowledge_file(filename: str, max_chars: int = 3000) -> str:
    """Load a knowledge file, truncated to max_chars."""
    path = KNOWLEDGE_DIR / filename
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except OSError:
        return ""


def load_approved_playbooks_summary() -> str:
    """Load approved playbook summaries for matching."""
    try:
        result = subprocess.run(
            ["python3", str(BASE_DIR / "bin" / "brain.py"), "--playbook-list"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()[:3000] if result.stdout else "No approved playbooks yet."
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "No approved playbooks yet."


# --- Stage 2: Enrichment + Playbook Matching ---

def build_enrich_prompt(card: dict, classification: dict,
                         description: str, playbook_summaries: list) -> str:
    """Build enrichment prompt with ticket details, knowledge, and playbooks."""
    meta = json.loads(card.get("analysis_metadata") or "{}")
    summary = card.get("summary", "")
    bucket_id = classification.get("bucket_id", "unknown")

    # Load relevant knowledge
    knowledge_text = ""
    for kf in classification.get("knowledge_files", []):
        content = load_knowledge_file(kf)
        if content:
            knowledge_text += f"\n### {kf}\n{content}\n"

    if not knowledge_text:
        knowledge_text = "(No relevant knowledge files found)"

    playbooks_text = "\n".join(playbook_summaries) if playbook_summaries else "No approved playbooks yet."

    return (
        "You are an IT systems engineering assistant triaging a Freshservice ticket.\n\n"
        f"Ticket: {summary}\n"
        f"Description:\n{description[:2000]}\n\n"
        f"Type: {meta.get('type', 'unknown')} | Priority: {meta.get('priority', 'unknown')}\n"
        f"Status: {meta.get('status', 'unknown')} | Created: {meta.get('created_at', 'unknown')}\n"
        f"Classification bucket: {bucket_id}\n\n"
        f"Relevant knowledge:\n{knowledge_text}\n\n"
        f"Approved playbooks:\n{playbooks_text}\n\n"
        "Tasks:\n"
        "1. Generate 2-5 specific, actionable next steps for this ticket.\n"
        "2. If any approved playbook matches, identify which and which steps apply.\n\n"
        "Be SPECIFIC — not 'investigate the issue' but 'check Okta SCIM provisioning logs for failed sync events'.\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "proposed_actions": [\n'
        '    {"type": "action_type", "draft": "specific action description"}\n'
        "  ],\n"
        '  "playbook_match": {\n'
        '    "playbook_id": "id or null",\n'
        '    "playbook_name": "name or null",\n'
        '    "applicable_steps": [1, 2, 4],\n'
        '    "reasoning": "why this playbook matches"\n'
        "  }\n"
        "}\n\n"
        "Action types: reply_to_requester, escalate, create_jira_ticket, "
        "follow_playbook, investigate, close_ticket, request_info, grant_access, "
        "check_integration, review_config, check_logs, update_documentation, "
        "or any other relevant type."
    )


def parse_enrich_response(raw: str) -> dict | None:
    """Parse enrichment JSON from LLM response."""
    result = _parse_llm_json(raw, "{")
    if not isinstance(result, dict):
        return None
    actions = result.get("proposed_actions")
    if not isinstance(actions, list) or not actions:
        return None
    # Normalize and cap
    normalized = []
    for a in actions[:6]:
        if not isinstance(a, dict):
            continue
        action_type = str(a.get("type", "next-step")).strip() or "next-step"
        draft = str(a.get("draft", "")).strip()
        if draft:
            normalized.append({"type": action_type, "draft": draft})
    if not normalized:
        return None

    playbook_match = result.get("playbook_match")
    if isinstance(playbook_match, dict) and not playbook_match.get("playbook_id"):
        playbook_match = None

    return {"proposed_actions": normalized, "playbook_match": playbook_match}


def save_enrichment(card_id: int, enrichment: dict):
    """Persist enrichment results to card."""
    conn = get_db()
    try:
        # Update proposed_actions
        conn.execute(
            "UPDATE cards SET proposed_actions = ?, enrichment_status = 'enriched' WHERE id = ?",
            [json.dumps(enrichment["proposed_actions"]), card_id],
        )
        # Update analysis_metadata with playbook match info
        if enrichment.get("playbook_match"):
            row = conn.execute("SELECT analysis_metadata FROM cards WHERE id = ?", [card_id]).fetchone()
            meta = json.loads(row["analysis_metadata"] or "{}") if row else {}
            meta["playbook_match"] = enrichment["playbook_match"]
            conn.execute(
                "UPDATE cards SET analysis_metadata = ? WHERE id = ?",
                [json.dumps(meta), card_id],
            )
        conn.commit()
    finally:
        conn.close()


def stage_enrich(card: dict, classification: dict) -> dict | None:
    """Run enrichment stage. Returns enrichment dict or None on failure."""
    card_id = card["id"]
    meta = json.loads(card.get("analysis_metadata") or "{}")
    ticket_id = meta.get("ticket_id")

    # Fetch full ticket description
    description = fetch_ticket_description(ticket_id) if ticket_id else ""

    # Load playbook summaries
    playbook_text = load_approved_playbooks_summary()
    playbooks = [playbook_text] if playbook_text else []

    prompt = build_enrich_prompt(card, classification, description, playbooks)
    model = STAGE_LLM_CONFIG["enrich"]["cli"]
    start = time.time()
    try:
        raw = _run_llm(prompt, "enrich", timeout=60)
        duration_ms = int((time.time() - start) * 1000)
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        log_enrichment_run(card_id, "enrich", model, duration_ms, "failed", str(e))
        return None

    result = parse_enrich_response(raw)
    if not result:
        log_enrichment_run(card_id, "enrich", model, duration_ms, "failed", raw[:200])
        # Mark as failed so we don't retry every cycle
        conn = get_db()
        conn.execute("UPDATE cards SET enrichment_status = 'failed' WHERE id = ?", [card_id])
        conn.commit()
        conn.close()
        return None

    save_enrichment(card_id, result)
    log_enrichment_run(card_id, "enrich", model, duration_ms, "success",
                        f"actions={len(result['proposed_actions'])} playbook={'yes' if result.get('playbook_match') else 'no'}")
    return result

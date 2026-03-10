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

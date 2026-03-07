# bin/brain.py
"""
eng-buddy Learning Engine.
Builds context prompts from persistent memory and parses Claude responses
for new patterns, stakeholder updates, and automation opportunities.
"""
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

MEMORY_DIR = Path.home() / ".claude" / "eng-buddy" / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

DB_PATH = Path.home() / ".claude" / "eng-buddy" / "inbox.db"


def _load(name, default=None):
    p = MEMORY_DIR / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return default if default is not None else {}


def _save(name, data):
    (MEMORY_DIR / name).write_text(json.dumps(data, indent=2))


def load_context():
    return _load("context.json", {})


def load_stakeholders():
    return _load("stakeholders.json", {})


def load_patterns():
    return _load("patterns.json", {"patterns": [], "automation_opportunities": []})


def load_traces():
    return _load("traces.json", {"traces": []})


def load_decisions(query, limit=5):
    """Search past decisions by keywords. Returns list of dicts."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Try FTS5 (sanitize query by quoting each term)
        try:
            safe_query = " ".join(f'"{w}"' for w in query.split() if w)
            if not safe_query:
                safe_query = '""'
            rows = conn.execute(
                """SELECT d.summary, d.action, d.source, d.context_notes,
                          d.draft_response, d.decision_at
                   FROM decisions d
                   JOIN decisions_fts fts ON d.id = fts.rowid
                   WHERE decisions_fts MATCH ?
                   ORDER BY d.decision_at DESC LIMIT ?""",
                [safe_query, limit]
            ).fetchall()
        except sqlite3.OperationalError:
            like = f"%{query}%"
            rows = conn.execute(
                """SELECT summary, action, source, context_notes,
                          draft_response, decision_at
                   FROM decisions
                   WHERE summary LIKE ? OR context_notes LIKE ?
                         OR draft_response LIKE ? OR tags LIKE ?
                   ORDER BY decision_at DESC LIMIT ?""",
                [like, like, like, like, limit]
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def build_context_prompt(batch_items=None):
    """Build the persistent context block injected into every Claude CLI call."""
    ctx = load_context()
    stakeholders = load_stakeholders()
    patterns = load_patterns()

    # Pick relevant stakeholders if batch has sender info
    relevant = {}
    if batch_items:
        senders = set()
        for item in batch_items:
            s = item.get("sender_email", "") or item.get("from", "") or item.get("sender", "")
            if s:
                # Normalize to username
                username = s.split("@")[0].replace(".", "_") if "@" in s else s.lower().replace(" ", "_")
                senders.add(username)
        for key, val in stakeholders.items():
            normalized = key.replace(".", "_")
            if normalized in senders or any(normalized in s for s in senders):
                relevant[key] = val

    priorities_str = "\n".join(f"- {p}" for p in ctx.get("current_priorities", [])) or "None set"
    rules_str = "\n".join(f"- {r}" for r in ctx.get("learned_rules", [])) or "None yet"

    stakeholder_str = ""
    if relevant:
        parts = []
        for name, info in relevant.items():
            parts.append(f"  {name}: {info.get('role', 'unknown')} — {info.get('relationship', '')} — expects response in {info.get('avg_response_expectation', 'unknown')}")
        stakeholder_str = "\n".join(parts)
    else:
        stakeholder_str = "  No matching stakeholders for this batch."

    playbook_str = ""
    known = patterns.get("patterns", [])
    if known:
        parts = []
        for p in known[:10]:
            parts.append(f"  - {p['id']}: trigger={p.get('trigger', '?')}, steps={len(p.get('steps', []))}, used {p.get('times_used', 0)} times")
        playbook_str = "\n".join(parts)
    else:
        playbook_str = "  No playbooks captured yet."

    # Find similar past decisions based on batch item summaries
    decisions_str = ""
    if batch_items:
        seen = set()
        all_decisions = []
        for item in batch_items:
            summary = item.get("summary", "") or item.get("subject", "") or ""
            # Extract key words for search
            words = [w for w in summary.split() if len(w) > 3]
            if words:
                query = " ".join(words[:5])
                for d in load_decisions(query, limit=3):
                    key = d.get("summary", "")
                    if key not in seen:
                        seen.add(key)
                        all_decisions.append(d)
        if all_decisions:
            parts = []
            for d in all_decisions[:5]:
                parts.append(f"  - [{d.get('decision_at', '?')[:10]}] {d.get('action', '?')}: {d.get('summary', '?')}")
                if d.get("draft_response"):
                    parts.append(f"    Response sent: {d['draft_response'][:100]}...")
            decisions_str = "\n".join(parts)

    if not decisions_str:
        decisions_str = "  No similar past decisions found."

    return f"""You are eng-buddy, an intelligent work assistant for {ctx.get('role', 'an engineer')} at {ctx.get('company', 'a company')}.
Manager: {ctx.get('manager', 'unknown')}
Team: {ctx.get('team', 'unknown')}
Response tone: {ctx.get('preferences', {}).get('response_tone', 'professional')}

Current priorities:
{priorities_str}

Learned rules (APPLY THESE):
{rules_str}

Relevant stakeholders:
{stakeholder_str}

Known playbooks:
{playbook_str}

Similar past decisions (use these for consistency):
{decisions_str}

AFTER completing your primary task, also output these sections if applicable (as JSON blocks):
- <!--STAKEHOLDER_UPDATES-->: [{{"name": "...", "field": "...", "value": "..."}}]
- <!--NEW_PATTERNS-->: [{{"trigger": "...", "steps": [...], "category": "..."}}]
- <!--AUTOMATION_OPPORTUNITIES-->: [{{"observation": "...", "suggestion": "..."}}]
- <!--LEARNED_RULES-->: ["rule text", ...]
- <!--WORK_TRACES-->: [{{"trigger": "...", "category": "...", "step_observed": "..."}}]
"""


def parse_learning(claude_response):
    """Parse Claude's response for learning sections and merge into memory."""
    sections = {
        "STAKEHOLDER_UPDATES": _parse_section(claude_response, "STAKEHOLDER_UPDATES"),
        "NEW_PATTERNS": _parse_section(claude_response, "NEW_PATTERNS"),
        "AUTOMATION_OPPORTUNITIES": _parse_section(claude_response, "AUTOMATION_OPPORTUNITIES"),
        "LEARNED_RULES": _parse_section(claude_response, "LEARNED_RULES"),
        "WORK_TRACES": _parse_section(claude_response, "WORK_TRACES"),
    }

    if sections["STAKEHOLDER_UPDATES"]:
        sh = load_stakeholders()
        for update in sections["STAKEHOLDER_UPDATES"]:
            name = update.get("name", "")
            if name:
                if name not in sh:
                    sh[name] = {}
                field = update.get("field", "")
                if field:
                    sh[name][field] = update.get("value", "")
                sh[name]["last_updated"] = datetime.now().isoformat()
        _save("stakeholders.json", sh)

    if sections["NEW_PATTERNS"]:
        pt = load_patterns()
        for pattern in sections["NEW_PATTERNS"]:
            pid = pattern.get("category", "unknown") + "-" + str(len(pt["patterns"]))
            pt["patterns"].append({
                "id": pid,
                "trigger": pattern.get("trigger", ""),
                "steps": pattern.get("steps", []),
                "category": pattern.get("category", ""),
                "automation_level": "observe",
                "times_used": 1,
                "detected_at": datetime.now().isoformat(),
            })
        _save("patterns.json", pt)

    if sections["AUTOMATION_OPPORTUNITIES"]:
        pt = load_patterns()
        for opp in sections["AUTOMATION_OPPORTUNITIES"]:
            pt["automation_opportunities"].append({
                "observation": opp.get("observation", ""),
                "suggestion": opp.get("suggestion", ""),
                "status": "pending_review",
                "detected_at": datetime.now().isoformat(),
            })
        _save("patterns.json", pt)

    if sections["LEARNED_RULES"]:
        ctx = load_context()
        existing = set(ctx.get("learned_rules", []))
        for rule in sections["LEARNED_RULES"]:
            if isinstance(rule, str) and rule not in existing:
                ctx.setdefault("learned_rules", []).append(rule)
        _save("context.json", ctx)

    if sections["WORK_TRACES"]:
        tr = load_traces()
        for trace in sections["WORK_TRACES"]:
            tr["traces"].append({
                **trace,
                "timestamp": datetime.now().isoformat(),
            })
        # Cap at 500 traces
        tr["traces"] = tr["traces"][-500:]
        _save("traces.json", tr)

    return sections


def _parse_section(text, section_name):
    """Extract a JSON block between <!--SECTION--> markers."""
    pattern = rf'<!--{section_name}-->\s*(\[.*?\])'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return []

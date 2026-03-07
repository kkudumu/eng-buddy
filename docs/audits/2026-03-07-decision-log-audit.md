# 2026-03-07 Audit: Smart Pollers + Decision Log

## Scope
- Audited latest pushed commit on `main`: `72de492` (with plan baseline from `docs/plans/2026-03-07-smart-pollers-impl.md`)
- Reviewed changed and integration-critical files across `bin/`, `dashboard/`, and `dashboard/static/`
- Validation runs:
  - `python3 -m pytest tests -q` -> **18 passed**
  - `python3 -m py_compile` on modified Python files -> **pass**
  - `node --check dashboard/static/app.js` -> **pass**

## Area 1: Plan Compliance
**Status: WARN**

### Findings
- Tasks 1-9 are implemented in current `main` (migration, brain engine, smart pollers, calendar poller, server APIs, tabbed frontend, morning briefing auto-show, integration tests).
- Task 10 (runtime sync to `~/.claude/eng-buddy`, LaunchAgent install/reload, and push/deploy actions) cannot be fully verified from repository state alone.

### Evidence
- Migration + startup hook: `dashboard/migrate.py`, `dashboard/server.py:34-38`
- Brain + memory injection: `bin/brain.py:88-184`
- Pollers: `bin/slack-poller.py`, `bin/gmail-poller.py`, `bin/calendar-poller.py`
- Frontend sections/briefing: `dashboard/static/app.js:167-247`, `dashboard/static/app.js:370-729`
- Tests: `dashboard/tests/test_server.py`

## Area 2: Runtime Errors
**Status: PASS**

### Findings
- No import/undefined-name failures found in modified Python files.
- Cross-references are valid (`brain` imports, migration symbols, endpoint/function wiring).
- Fixed two runtime correctness bugs during this audit:
  1. Fresh DB bootstrap could fail due missing `cards` table.
  2. Draft-send/filter-create APIs previously marked success even when Claude CLI failed.

### Fixes Applied
- Added base `cards` table bootstrap and removed early return on missing DB:
  - `dashboard/migrate.py:9-27`, `dashboard/migrate.py:98-100`
- Added subprocess return-code checks for send/filter endpoints:
  - `dashboard/server.py:148-154`, `dashboard/server.py:199-205`, `dashboard/server.py:760-766`

## Area 3: Security
**Status: WARN**

### Findings
- **No direct shell command injection** found in subprocess calls (all use argv lists, not `shell=True`).
- **High-risk prompt/tool injection surface remains by design**: untrusted message/email/card data is sent to `claude --dangerously-skip-permissions --print` in pollers/server.
  - `bin/slack-poller.py:349-354`
  - `bin/gmail-poller.py:281-286`
  - `bin/calendar-poller.py:51-54`, `bin/calendar-poller.py:84-87`
  - `dashboard/server.py:148-151`, `dashboard/server.py:199-202`, `dashboard/server.py:523-526`, `dashboard/server.py:696-699`
- Fixed AppleScript injection/syntax-break risk for notifications by escaping user-controlled text:
  - `dashboard/server.py:30-32`, `dashboard/server.py:633-639`
  - `bin/slack-poller.py:119-128`
  - `bin/gmail-poller.py:153-159`
- Frontend hardening fixes:
  - Filter suggestion pattern is now safely encoded before inline handler use: `dashboard/static/app.js:304-315`
  - Calendar join URLs restricted to `http/https`: `dashboard/static/app.js:47-56`, `dashboard/static/app.js:280-291`

## Area 4: DB Consistency
**Status: PASS**

### Findings
- Columns written by pollers/server exist in migration schema.
  - `cards.section`, `cards.draft_response`, `cards.context_notes`, `cards.responded`, `cards.refinement_history`: `dashboard/migrate.py:21-27`, `dashboard/migrate.py:29-33`, `dashboard/migrate.py:94`
- Tables queried/written by server exist in migration schema.
  - `stats`, `briefings`, `filter_suggestions`, `decisions`, `decisions_fts` + triggers:
    - `dashboard/migrate.py:35-92`
- Decision-log queries are parameterized and schema-aligned:
  - `dashboard/server.py:561-607`, `dashboard/server.py:843-885`

## Area 5: Frontend Integration
**Status: PASS**

### Findings
- API endpoints called from `app.js` match server methods/paths.
- All JS functions referenced by inline `onclick` handlers are defined.
- Fixed a functional integration bug where Gmail `alert`/`noise` cards were hidden from the two-section UI.

### Fixes Applied
- Gmail two-section aggregation now includes `action-needed` as needs-action and combines `no-action + alert + noise` for the second section:
  - `dashboard/static/app.js:177-213`
- Send-draft UI now correctly handles HTTP error responses:
  - `dashboard/static/app.js:319-341`

## Area 6: Edge Cases
**Status: WARN**

### Findings
- `inbox.db` missing on startup: now handled by migration bootstrap (creates parent dir + base cards table).
  - `dashboard/migrate.py:98-107`
- Claude timeout/non-JSON in pollers:
  - Slack/Gmail/Calendar classification paths already fail soft and continue.
  - `bin/slack-poller.py:375-383`
  - `bin/gmail-poller.py:301-309`
  - `bin/calendar-poller.py:58-60`, `bin/calendar-poller.py:93-96`
- No messages/emails/events:
  - Pollers already no-op cleanly and persist state where relevant.
  - `bin/slack-poller.py:612-617`, `bin/gmail-poller.py:343-347`, `bin/calendar-poller.py:162-166`
- Remaining risk:
  - Service is local-first and unauthenticated; high-impact endpoints are callable by any local process if port exposure is broadened.

## Area 7: Test Coverage Gaps (Top 5)
**Status: WARN**

1. Missing test for `send-slack`/`send-email` failure path verifying card status is not flipped to completed on nonzero Claude exit.
2. Missing test for `/api/notify` escaping with quotes/newlines in `message`/`title`.
3. Missing frontend test for Gmail two-section rendering that ensures `alert` and `noise` are shown under no-action.
4. Missing migration test that verifies decisions FTS triggers (`ai/ad/au`) actually keep search index in sync.
5. Missing startup integration test from a truly empty workspace (`no inbox.db`) asserting `/api/cards` and `/api/health` behave cleanly after lifespan migration.

## Prioritized Fix List

### P1 (Completed in this audit)
1. Bootstrap schema for fresh DB to avoid `no such table: cards` startup/runtime errors.
2. Prevent false-positive “sent/created” outcomes when Claude CLI command fails in send/filter APIs.
3. Harden notification AppleScript string handling against injected quotes/newlines.
4. Fix Gmail UI section mismatch so `alert`/`noise` cards are visible.
5. Harden frontend inline handler argument encoding and calendar link scheme handling.

### P2 (Recommended next)
1. Add targeted tests for send-failure paths and notification escaping.
2. Add migration trigger-sync test for decision-log FTS behavior.
3. Add a lightweight auth/CSRF strategy if dashboard exposure moves beyond localhost.

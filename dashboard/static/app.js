// ~/.claude/eng-buddy/dashboard/static/app.js

let activeFilter = 'all';
let allCards = [];
const runningTerminals = {};
const CACHE_TTL_MS = 30000;  // 30 seconds — skip re-fetch if cache is fresher
const tabCache = {};  // { cacheKey: { html: string, ts: number } }

function cacheGet(key) {
  const entry = tabCache[key];
  return entry ? entry.html : null;
}

function cacheSet(key, html) {
  tabCache[key] = { html, ts: Date.now() };
}

function cacheIsFresh(key) {
  const entry = tabCache[key];
  return entry && (Date.now() - entry.ts) < CACHE_TTL_MS;
}

/** Map a source name to every cache key it could affect. */
function cacheKeysForSource(source) {
  const keys = [`queue-${source}`, `queue-all`];
  if (source === 'gmail' || source === 'slack') keys.push(`twosection-${source}`);
  if (source === 'calendar') keys.push('calendar');
  if (source === 'tasks') keys.push('tasks');
  if (source === 'jira') keys.push('jira-sprint');
  return keys;
}

function cacheInvalidateSource(source) {
  for (const key of cacheKeysForSource(source)) {
    if (tabCache[key]) tabCache[key].ts = 0;  // mark stale, keep html for instant display
  }
}

// -- Helpers ------------------------------------------------------------------

function timeAgo(ts) {
  if (!ts) return '';
  const d = new Date(ts.replace(' ', 'T') + (ts.includes('Z') ? '' : 'Z'));
  const diff = Math.floor((Date.now() - d) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
  return `${Math.floor(diff/86400)}d ago`;
}

function sourceBadge(source) {
  const s = (source || '').toLowerCase();
  return `<span class="badge source-${s}">${s.toUpperCase()}</span>`;
}

function classBadge(cls) {
  const c = (cls || 'unknown').toLowerCase().replace(/[^a-z-]/g, '-');
  const label = (cls || '').toUpperCase().replace(/-/g, ' ');
  return `<span class="badge cls-${c}">${label}</span>`;
}

function renderAction(action, i) {
  const type = action.type || 'action';
  const draft = action.draft || JSON.stringify(action, null, 2);
  return `
    <div class="action-item">
      <div class="action-type">${i + 1}. ${type.replace(/_/g, ' ')}</div>
      <div class="action-draft">${escHtml(draft)}</div>
    </div>`;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function safeExternalUrl(url) {
  if (!url) return '';
  try {
    const parsed = new URL(String(url), window.location.origin);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href;
    }
  } catch (_) {}
  return '';
}

// -- Card rendering -----------------------------------------------------------

function renderCard(card) {
  const actions = Array.isArray(card.proposed_actions)
    ? card.proposed_actions
    : [];
  const actionCount = actions.length;
  const foldoutId = `foldout-${card.id}`;
  const xtermId = `xterm-${card.id}`;
  const refineId = `refine-${card.id}`;

  const actionsHtml = actions.map((a, i) => renderAction(a, i)).join('');

  return `
  <div class="card ${card.status}" id="card-${card.id}" data-source="${card.source}" data-id="${card.id}">
    <div class="card-header" onclick="toggleFoldout(${card.id})">
      <div class="card-meta">
        ${sourceBadge(card.source)}
        ${classBadge(card.classification)}
      </div>
      <div class="card-summary">${escHtml(card.summary || '(no summary)')}</div>
      <div class="card-time">${timeAgo(card.timestamp)}</div>
      <div class="card-toggle" id="toggle-${card.id}">${actionCount} action${actionCount !== 1 ? 's' : ''} &#9660;</div>
    </div>

    <div class="card-actions">
      <button class="action-btn open-session" onclick="openSession(${card.id})">OPEN SESSION</button>
      <button class="action-btn refine" onclick="toggleRefine(${card.id})">REFINE</button>
      <button class="action-btn hold" onclick="holdCard(${card.id})">HOLD</button>
      <button class="action-btn approve" onclick="approveCard(${card.id})">APPROVE</button>
    </div>

    <div class="card-foldout" id="${foldoutId}">
      <div class="proposed-actions" id="proposed-${card.id}">
        <h4>Proposed Actions</h4>
        ${actionsHtml || '<div style="color:#666">No actions proposed.</div>'}
      </div>

      <div id="${refineId}" style="display:none; margin-top:16px;">
        <div class="refine-panel">
          <div class="proposed-actions"><h4>Refine</h4></div>
          <div class="refine-history" id="refine-history-${card.id}"></div>
          <div class="refine-input-row">
            <textarea class="refine-input" id="refine-input-${card.id}"
              placeholder="e.g. make the tone more casual, don't transition the status..."
              onkeydown="handleRefineKey(event, ${card.id})"></textarea>
            <button class="action-btn" onclick="sendRefine(${card.id})">SEND</button>
          </div>
        </div>
      </div>

      <div id="${xtermId}" class="xterm-container" style="display:none;"></div>
    </div>
  </div>`;
}

// -- Smart Card rendering (for two-section views) ----------------------------

function renderSmartCard(card, source) {
  const draft = card.draft_response ? escHtml(card.draft_response) : '';
  const context = card.context_notes ? escHtml(card.context_notes) : '';
  const hasDraft = !!card.draft_response;
  const isSlack = source === 'slack';
  const isGmail = source === 'gmail';

  let buttons = '';
  if (hasDraft && isSlack) {
    buttons += `<button class="action-btn approve" onclick="sendDraft(${card.id}, 'slack', this)">SEND DRAFT</button>`;
  }
  if (hasDraft && isGmail) {
    buttons += `<button class="action-btn approve" onclick="sendDraft(${card.id}, 'email', this)">SEND DRAFT</button>`;
  }
  buttons += `<button class="action-btn refine" onclick="toggleRefine(${card.id})">REFINE</button>`;
  buttons += `<button class="action-btn" onclick="dismissCard(${card.id})">DISMISS</button>`;
  buttons += `<button class="action-btn open-session" onclick="openSession(${card.id})">OPEN SESSION</button>`;

  return `
  <div class="card smart-card ${card.section === 'needs-action' || card.section === 'action-needed' ? 'needs-action' : ''}"
       id="card-${card.id}" data-source="${card.source}" data-id="${card.id}">
    <div class="card-header" onclick="toggleFoldout(${card.id})">
      <div class="card-meta">
        ${sourceBadge(card.source)}
        ${classBadge(card.classification)}
      </div>
      <div class="card-summary">${escHtml(card.summary || '(no summary)')}</div>
      <div class="card-time">${timeAgo(card.timestamp)}</div>
      <div class="card-toggle" id="toggle-${card.id}">&#9660;</div>
    </div>
    ${context ? `<div class="card-context">${context}</div>` : ''}
    ${draft ? `<div class="card-draft"><span class="draft-label">DRAFT:</span> ${draft}</div>` : ''}
    <div class="card-actions">${buttons}</div>
    <div class="card-foldout" id="foldout-${card.id}">
      <div id="refine-${card.id}" style="display:none; margin-top:16px;">
        <div class="refine-panel">
          <div class="proposed-actions"><h4>Refine</h4></div>
          <div class="refine-history" id="refine-history-${card.id}"></div>
          <div class="refine-input-row">
            <textarea class="refine-input" id="refine-input-${card.id}"
              placeholder="e.g. make the tone more casual..."
              onkeydown="handleRefineKey(event, ${card.id})"></textarea>
            <button class="action-btn" onclick="sendRefine(${card.id})">SEND</button>
          </div>
        </div>
      </div>
      <div id="xterm-${card.id}" class="xterm-container" style="display:none;"></div>
    </div>
  </div>`;
}

// -- Two-section views --------------------------------------------------------

async function loadTwoSectionView(source) {
  const queue = document.getElementById('queue');
  const cacheKey = `twosection-${source}`;

  const cached = cacheGet(cacheKey);
  if (cached) {
    queue.innerHTML = cached;
    if (cacheIsFresh(cacheKey)) return;  // fresh enough — skip fetch
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING...</div>';
  }

  try {
    let needsCards = [];
    let noActionCards = [];
    let suggestions = { suggestions: [] };

    if (source === 'gmail') {
      const [actionR, alertR, noiseR, noActionR, suggestionsR] = await Promise.all([
        fetch('/api/cards?source=gmail&section=action-needed'),
        fetch('/api/cards?source=gmail&section=alert'),
        fetch('/api/cards?source=gmail&section=noise'),
        fetch('/api/cards?source=gmail&section=no-action'),
        fetch('/api/filters/suggestions'),
      ]);

      const actionData = await actionR.json();
      const alertData = await alertR.json();
      const noiseData = await noiseR.json();
      const noActionData = await noActionR.json();
      suggestions = await suggestionsR.json();

      needsCards = actionData.cards || [];
      const mergedNoAction = [
        ...(noActionData.cards || []),
        ...(alertData.cards || []),
        ...(noiseData.cards || []),
      ];
      const seen = new Set();
      noActionCards = mergedNoAction.filter((card) => {
        if (!card || seen.has(card.id)) return false;
        seen.add(card.id);
        return true;
      });
    } else {
      const [needsR, noActionR] = await Promise.all([
        fetch(`/api/cards?source=${source}&section=needs-action`),
        fetch(`/api/cards?source=${source}&section=no-action`),
      ]);
      const needsData = await needsR.json();
      const noActionData = await noActionR.json();
      needsCards = needsData.cards || [];
      noActionCards = noActionData.cards || [];
    }

    const needsHtml = needsCards.map(c => renderSmartCard(c, source)).join('') || '<div class="section-empty">All clear</div>';
    const noActionHtml = noActionCards.map(c => renderSmartCard(c, source)).join('') || '<div class="section-empty">Nothing here</div>';

    let suggestionsHtml = '';
    if (suggestions.suggestions.length) {
      suggestionsHtml = `<div class="section-group"><div class="section-header filter-suggest">
        <span>FILTER SUGGESTIONS</span>
        <span class="section-count">${suggestions.suggestions.length}</span>
      </div><div class="section-body" id="section-filters">` +
      suggestions.suggestions.map(renderFilterSuggestion).join('') +
      `</div></div>`;
    }

    const finalHtml = `
      <div class="section-group">
        <div class="section-header" onclick="toggleSection('needs')">
          <span>NEEDS ACTION / UNREAD</span>
          <span class="section-count">${needsCards.length}</span>
          <span class="section-toggle" id="toggle-needs">&#9660;</span>
        </div>
        <div class="section-body" id="section-needs">${needsHtml}</div>
      </div>
      <div class="section-group">
        <div class="section-header no-action" onclick="toggleSection('noaction')">
          <span>RESPONDED / NO ACTION</span>
          <span class="section-count">${noActionCards.length}</span>
          <span class="section-toggle" id="toggle-noaction">&#9660;</span>
        </div>
        <div class="section-body" id="section-noaction">${noActionHtml}</div>
      </div>
      ${suggestionsHtml}
    `;
    queue.innerHTML = finalHtml;
    cacheSet(cacheKey, finalHtml);
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load: ${e.message}</div>`;
    }
  }
}

function toggleSection(name) {
  const body = document.getElementById(`section-${name}`);
  const toggle = document.getElementById(`toggle-${name}`);
  if (body.style.display === 'none') {
    body.style.display = 'block';
    toggle.innerHTML = '&#9660;';
  } else {
    body.style.display = 'none';
    toggle.innerHTML = '&#9654;';
  }
}

// -- Calendar view ------------------------------------------------------------

async function loadCalendarView() {
  const queue = document.getElementById('queue');
  const cacheKey = 'calendar';

  const cached = cacheGet(cacheKey);
  if (cached) {
    queue.innerHTML = cached;
    if (cacheIsFresh(cacheKey)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING CALENDAR...</div>';
  }

  try {
    const r = await fetch('/api/cards?source=calendar');
    const data = await r.json();

    if (!data.cards.length) {
      const empty = '<div style="color:#444;padding:40px;text-align:center;letter-spacing:4px">NO EVENTS TODAY</div>';
      queue.innerHTML = empty;
      cacheSet(cacheKey, empty);
      return;
    }

    const eventsHtml = data.cards.map(card => {
      const actions = Array.isArray(card.proposed_actions) ? card.proposed_actions : [];
      const event = actions[0] || {};
      const context = card.context_notes ? escHtml(card.context_notes) : '';
      const meetLink = safeExternalUrl(event.hangout_link || '');
      const attendees = (event.attendees || []).slice(0, 5).map(a => escHtml(a)).join(', ');
      const isHighPrio = card.classification === 'high';

      return `
        <div class="calendar-event ${isHighPrio ? 'high-prio' : ''}">
          <div class="event-time">${escHtml(card.summary || '')}</div>
          ${context ? `<div class="event-context">${context}</div>` : ''}
          ${attendees ? `<div class="event-attendees">WITH: ${attendees}</div>` : ''}
          <div class="event-actions">
            ${meetLink ? `<a href="${escHtml(meetLink)}" target="_blank" class="action-btn approve">JOIN</a>` : ''}
            <button class="action-btn open-session" onclick="openSession(${card.id})">PREP NOTES</button>
          </div>
        </div>`;
    }).join('');

    const html = `<div class="calendar-agenda"><div class="section-header"><span>TODAY'S AGENDA</span><span class="section-count">${data.cards.length}</span></div>${eventsHtml}</div>`;
    queue.innerHTML = html;
    cacheSet(cacheKey, html);
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed: ${e.message}</div>`;
    }
  }
}

// -- Filter suggestions -------------------------------------------------------

function renderFilterSuggestion(suggestion) {
  const encodedPattern = encodeURIComponent(String(suggestion.pattern || ''));
  return `
    <div class="filter-suggestion">
      <div class="filter-pattern">PATTERN: ${escHtml(suggestion.pattern)} (ignored ${suggestion.ignore_count}x)</div>
      <div class="filter-actions">
        <button class="action-btn approve" onclick="createFilter(${suggestion.id}, decodeURIComponent('${encodedPattern}'), 'eng-buddy/auto-filtered')">CREATE FILTER</button>
        <button class="action-btn" onclick="dismissFilter(${suggestion.id}, false)">NOT NOW</button>
        <button class="action-btn hold" onclick="dismissFilter(${suggestion.id}, true)">NEVER</button>
      </div>
    </div>`;
}

// -- Smart actions ------------------------------------------------------------

async function sendDraft(id, type, btnEl = null) {
  const endpoint = type === 'slack' ? 'send-slack' : 'send-email';
  const btn = btnEl || (typeof event !== 'undefined' ? event.target : null);
  if (btn) {
    btn.textContent = 'SENDING...';
    btn.disabled = true;
  }
  try {
    const r = await fetch(`/api/cards/${id}/${endpoint}`, { method: 'POST' });
    if (!r.ok) {
      const body = await r.text();
      throw new Error(body || `HTTP ${r.status}`);
    }
    if (btn) btn.textContent = 'SENT';
    const card = document.getElementById(`card-${id}`);
    if (card) card.style.opacity = '0.5';
  } catch (e) {
    if (btn) {
      btn.textContent = 'FAILED';
      btn.disabled = false;
    }
  }
}

async function dismissCard(id) {
  await fetch(`/api/cards/${id}/dismiss`, { method: 'POST' });
  const card = document.getElementById(`card-${id}`);
  if (card) {
    card.style.opacity = '0.3';
    setTimeout(() => card.remove(), 500);
  }
}

async function createFilter(suggestionId, pattern, label) {
  await fetch('/api/filters/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ suggestion_id: suggestionId, pattern: pattern, label: label })
  });
  // Reload the view
  loadTwoSectionView('gmail');
}

async function dismissFilter(suggestionId, permanent) {
  await fetch('/api/filters/dismiss', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ suggestion_id: suggestionId, permanent: permanent })
  });
  loadTwoSectionView('gmail');
}

// -- Briefing -----------------------------------------------------------------

async function loadBriefing() {
  const overlay = document.getElementById('briefing-overlay');
  const content = document.getElementById('briefing-content');
  overlay.style.display = 'flex';
  content.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">GENERATING BRIEFING...</div>';

  try {
    const r = await fetch('/api/briefing');
    const data = await r.json();
    content.innerHTML = renderBriefing(data);
  } catch (e) {
    content.innerHTML = `<div style="color:#ea4335;padding:40px;">Briefing failed: ${e.message}</div>`;
  }
}

function dismissBriefing() {
  document.getElementById('briefing-overlay').style.display = 'none';
}

function renderBriefing(data) {
  if (data.error) return `<div style="color:#ea4335;padding:40px;">${escHtml(data.error)}</div>`;

  const meetings = (data.meetings || []).map(m =>
    `<div class="briefing-item"><span class="briefing-time">${escHtml(m.time || '')}</span> ${escHtml(m.title || '')} ${m.prep ? `<span class="briefing-prep">${escHtml(m.prep)}</span>` : ''}</div>`
  ).join('') || '<div class="briefing-empty">No meetings today</div>';

  const responses = (data.needs_response || []).map(r =>
    `<div class="briefing-item">${sourceBadge(r.source)} ${escHtml(r.summary || '')} <span class="briefing-age">${escHtml(r.age || '')}</span> ${r.has_draft ? '<span class="badge cls-needs-response">DRAFT READY</span>' : ''}</div>`
  ).join('') || '<div class="briefing-empty">All clear</div>';

  const alerts = (data.alerts || []).map(a =>
    `<div class="briefing-item"><span class="badge cls-${a.urgency === 'high' ? 'urgent' : 'informational'}">${(a.urgency || '').toUpperCase()}</span> ${escHtml(a.summary || '')}</div>`
  ).join('');

  const load = data.cognitive_load || {};
  const loadColor = load.level === 'LOW' ? 'var(--fresh)' : load.level === 'MODERATE' ? 'var(--needs-response)' : load.level === 'HIGH' ? 'var(--gmail)' : '#ff0000';

  const stats = data.stats || {};
  const headsUp = (data.heads_up || []).map(h => `<div class="briefing-item">&#9888; ${escHtml(h)}</div>`).join('');

  return `
    <div class="briefing-header">
      <div class="briefing-title">MORNING BRIEFING</div>
      <div class="briefing-date">${escHtml(data.date || '')}</div>
      <button class="action-btn" onclick="dismissBriefing()">DISMISS</button>
    </div>
    <div class="briefing-section">
      <div class="briefing-section-title">COGNITIVE LOAD</div>
      <div class="briefing-load" style="color:${loadColor}">${load.level || '?'}</div>
      <div class="briefing-load-detail">${load.meeting_count || 0} meetings / ${load.action_count || 0} actions / Deep work: ${load.deep_work_window || 'N/A'}</div>
    </div>
    <div class="briefing-section">
      <div class="briefing-section-title">MEETINGS</div>
      ${meetings}
    </div>
    <div class="briefing-section">
      <div class="briefing-section-title">NEEDS RESPONSE</div>
      ${responses}
    </div>
    ${alerts ? `<div class="briefing-section"><div class="briefing-section-title">ALERTS</div>${alerts}</div>` : ''}
    ${headsUp ? `<div class="briefing-section"><div class="briefing-section-title">HEADS UP</div>${headsUp}</div>` : ''}
    <div class="briefing-section">
      <div class="briefing-section-title">STATS</div>
      <div class="briefing-stats">
        <span>${stats.drafts_sent || 0} drafts sent</span>
        <span>${stats.cards_triaged || 0} triaged</span>
        <span>~${stats.time_saved_min || 0}min saved</span>
      </div>
    </div>
    ${data.pep_talk ? `<div class="briefing-pep">${escHtml(data.pep_talk)}</div>` : ''}
  `;
}

// -- Toggle helpers -----------------------------------------------------------

function toggleFoldout(id) {
  const foldout = document.getElementById(`foldout-${id}`);
  const toggle = document.getElementById(`toggle-${id}`);
  foldout.classList.toggle('open');
  toggle.innerHTML = toggle.innerHTML.includes('\u25BC')
    ? toggle.innerHTML.replace('\u25BC', '\u25B2')
    : toggle.innerHTML.replace('\u25B2', '\u25BC');
}

function toggleRefine(id) {
  const refineEl = document.getElementById(`refine-${id}`);
  const foldout = document.getElementById(`foldout-${id}`);
  if (!foldout.classList.contains('open')) {
    foldout.classList.add('open');
  }
  refineEl.style.display = refineEl.style.display === 'none' ? 'block' : 'none';
}

// -- Actions ------------------------------------------------------------------

async function holdCard(id) {
  await fetch(`/api/cards/${id}/hold`, { method: 'POST' });
  const card = document.getElementById(`card-${id}`);
  card.className = card.className.replace(/\b(pending|approved|completed)\b/g, 'held');
  updateCounts();
}

async function approveCard(id) {
  const foldout = document.getElementById(`foldout-${id}`);
  const xtermEl = document.getElementById(`xterm-${id}`);
  const proposedEl = document.getElementById(`proposed-${id}`);

  if (!foldout.classList.contains('open')) foldout.classList.add('open');
  proposedEl.style.display = 'none';
  xtermEl.style.display = 'block';

  const card = document.getElementById(`card-${id}`);
  card.className = card.className.replace(/\b(pending|held)\b/g, 'running');

  // Init xterm
  const term = new Terminal({
    theme: { background: '#000000', foreground: '#ffffff', cursor: '#ffffff' },
    fontFamily: 'JetBrains Mono, monospace',
    fontSize: 13,
    cols: 180,
    rows: 40,
    scrollback: 5000,
  });
  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(xtermEl);
  fitAddon.fit();
  runningTerminals[id] = term;

  // Connect WebSocket
  const ws = new WebSocket(`ws://localhost:7777/ws/execute/${id}`);
  ws.onmessage = (e) => term.write(e.data);
  ws.onclose = () => {
    card.className = card.className.replace('running', 'completed');
    updateCounts();
  };

  // Keyboard input -> PTY
  term.onData((data) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(data);
  });
}

async function openSession(id) {
  await fetch(`/api/cards/${id}/open-session`, { method: 'POST' });
}

// -- Refine -------------------------------------------------------------------

const refineHistories = {};

function handleRefineKey(event, id) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendRefine(id);
  }
}

async function sendRefine(id) {
  const input = document.getElementById(`refine-input-${id}`);
  const history = document.getElementById(`refine-history-${id}`);
  const msg = input.value.trim();
  if (!msg) return;

  if (!refineHistories[id]) refineHistories[id] = [];
  refineHistories[id].push({ role: 'user', content: msg });

  history.innerHTML += `<div class="msg-user">YOU: ${escHtml(msg)}</div>`;
  input.value = '';
  input.disabled = true;

  history.innerHTML += `<div class="msg-claude" id="refine-streaming-${id}">BUDDY: thinking...</div>`;

  try {
    const r = await fetch(`/api/cards/${id}/refine`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, history: refineHistories[id].slice(0, -1) })
    });
    const data = await r.json();
    const streamEl = document.getElementById(`refine-streaming-${id}`);
    streamEl.textContent = `BUDDY: ${data.response}`;
    streamEl.removeAttribute('id');
    refineHistories[id].push({ role: 'assistant', content: data.response });
  } catch (e) {
    document.getElementById(`refine-streaming-${id}`).textContent = 'BUDDY: error — check server logs';
  }

  input.disabled = false;
  input.focus();
  history.scrollTop = history.scrollHeight;
}

// -- Tasks view (from active-tasks.md) ----------------------------------------

function renderTask(task) {
  const prioClass = task.priority === 'critical' ? 'prio-critical'
    : task.priority === 'high' ? 'prio-high'
    : task.priority === 'low' ? 'prio-low' : 'prio-medium';
  const statusClass = task.status === 'in_progress' ? 'status-progress'
    : task.status === 'blocked' ? 'status-blocked' : 'status-pending';
  const statusLabel = task.status === 'in_progress' ? 'IN PROGRESS'
    : task.status === 'blocked' ? 'BLOCKED'
    : 'PENDING';
  const jiraLink = task.jira_key
    ? `<a href="https://klaviyo.atlassian.net/browse/${escHtml(task.jira_key)}" target="_blank" class="task-jira-link">${escHtml(task.jira_key)}</a>`
    : '';

  return `
    <div class="task-row ${prioClass} ${statusClass}">
      <div class="task-num">#${task.num}</div>
      <div class="task-info">
        <div class="task-title">${escHtml(task.title)}</div>
        ${task.description ? `<div class="task-desc">${escHtml(task.description).slice(0, 120)}</div>` : ''}
      </div>
      <div class="task-meta">
        ${jiraLink}
        <span class="task-prio ${prioClass}">${task.priority.toUpperCase()}</span>
        <span class="task-status ${statusClass}">${statusLabel}</span>
      </div>
    </div>`;
}

async function loadTasksView() {
  const queue = document.getElementById('queue');
  const cacheKey = 'tasks';

  const cached = cacheGet(cacheKey);
  if (cached) {
    queue.innerHTML = cached;
    if (cacheIsFresh(cacheKey)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING TASKS...</div>';
  }

  try {
    const r = await fetch('/api/cards?source=tasks');
    const data = await r.json();
    const cards = data.cards || [];

    if (!cards.length) {
      const empty = '<div style="color:#444;padding:40px;text-align:center;letter-spacing:4px">NO ACTIVE TASKS</div>';
      queue.innerHTML = empty;
      cacheSet(cacheKey, empty);
      return;
    }

    // Extract task metadata from proposed_actions
    const tasks = cards.map(card => {
      const actions = Array.isArray(card.proposed_actions) ? card.proposed_actions : [];
      const meta = actions.find(a => a.type === 'task') || {};
      return {
        num: meta.task_num || 0,
        title: (card.summary || '').replace(/^#\d+\s*[—–-]\s*/, ''),
        jira_key: meta.jira_key || null,
        status: meta.task_status || 'pending',
        priority: meta.priority || card.classification || 'medium',
        description: card.context_notes || '',
      };
    });

    const inProgress = tasks.filter(t => t.status === 'in_progress');
    const blocked = tasks.filter(t => t.status === 'blocked');
    const pending = tasks.filter(t => t.status === 'pending');

    const section = (title, items, cls) => {
      if (!items.length) return '';
      return `
        <div class="section-group">
          <div class="section-header ${cls}">
            <span>${title}</span>
            <span class="section-count">${items.length}</span>
          </div>
          <div class="section-body">${items.map(renderTask).join('')}</div>
        </div>`;
    };

    const html = `
      <div class="tasks-view">
        ${section('IN PROGRESS', inProgress, 'tasks-progress')}
        ${section('BLOCKED', blocked, 'tasks-blocked')}
        ${section('PENDING', pending, 'tasks-pending')}
      </div>`;
    queue.innerHTML = html;
    cacheSet(cacheKey, html);
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load tasks: ${e.message}</div>`;
    }
  }
}

// -- Jira Sprint Board --------------------------------------------------------

function statusColor(status) {
  const s = (status || '').toLowerCase();
  if (s.includes('done')) return 'var(--fresh)';
  if (s.includes('progress') || s.includes('review')) return 'var(--jira)';
  return 'var(--muted)';
}

function renderJiraIssue(issue) {
  const labels = (issue.labels || []).map(l => `<span class="jira-label">${escHtml(l)}</span>`).join('');
  const prio = (issue.priority || '').toLowerCase();
  const prioIcon = prio.includes('high') ? '!!!' : prio.includes('low') ? '.' : '!!';
  return `
    <div class="jira-issue" data-key="${issue.key}">
      <div class="jira-issue-key">${escHtml(issue.key)}</div>
      <div class="jira-issue-summary">${escHtml(issue.summary)}</div>
      <div class="jira-issue-meta">
        <span class="jira-status" style="color:${statusColor(issue.status)}">${escHtml(issue.status)}</span>
        <span class="jira-prio">${prioIcon}</span>
        ${labels}
      </div>
    </div>`;
}

function renderSprintBoard(board) {
  const col = (title, items, cls) => `
    <div class="board-col ${cls}">
      <div class="board-col-header">${title} <span class="board-col-count">${items.length}</span></div>
      ${items.map(renderJiraIssue).join('') || '<div class="board-empty">None</div>'}
    </div>`;

  return `
    <div class="sprint-board">
      ${col('TO DO', board.todo, 'col-todo')}
      ${col('IN PROGRESS', board.in_progress, 'col-progress')}
      ${col('DONE', board.done, 'col-done')}
    </div>`;
}

async function loadSprintBoard() {
  const queue = document.getElementById('queue');
  const cacheKey = 'jira-sprint';

  const cached = cacheGet(cacheKey);
  if (cached) {
    queue.innerHTML = cached;
    if (cacheIsFresh(cacheKey)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING SPRINT...</div>';
  }

  try {
    const r = await fetch('/api/jira/sprint');
    const data = await r.json();
    const html = renderSprintBoard(data.board);
    queue.innerHTML = html;
    cacheSet(cacheKey, html);
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load sprint: ${e.message}</div>`;
    }
  }
}

// -- Counts -------------------------------------------------------------------

function updateCounts() {
  fetch('/api/cards?status=pending')
    .then(r => r.json())
    .then(data => {
      document.getElementById('count-pending').textContent = `${data.counts.pending || 0} pending`;
      document.getElementById('count-held').textContent = `${data.counts.held || 0} held`;
      const running = document.querySelectorAll('.card.running').length;
      document.getElementById('count-running').textContent = `${running} running`;
    });
}

// -- Load queue ---------------------------------------------------------------

async function loadQueue(source = 'all') {
  const queue = document.getElementById('queue');
  const cacheKey = `queue-${source}`;

  const cached = cacheGet(cacheKey);
  if (cached) {
    queue.innerHTML = cached;
    if (cacheIsFresh(cacheKey)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING...</div>';
  }

  try {
    const url = source === 'all' ? '/api/cards' : `/api/cards?source=${source}`;
    const r = await fetch(url);
    const data = await r.json();
    allCards = data.cards;

    document.getElementById('count-pending').textContent = `${data.counts.pending || 0} pending`;
    document.getElementById('count-held').textContent = `${data.counts.held || 0} held`;

    if (!allCards.length) {
      const empty = '<div style="color:#444;padding:40px;text-align:center;letter-spacing:4px">QUEUE EMPTY</div>';
      queue.innerHTML = empty;
      cacheSet(cacheKey, empty);
      return;
    }
    const html = allCards.map(renderCard).join('');
    queue.innerHTML = html;
    cacheSet(cacheKey, html);
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load: ${e.message}</div>`;
    }
  }
}

// -- Filters ------------------------------------------------------------------

document.querySelectorAll('.filter-btn[data-source]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.source;
    if (activeFilter === 'tasks') {
      loadTasksView();
    } else if (activeFilter === 'slack') {
      loadTwoSectionView('slack');
    } else if (activeFilter === 'gmail') {
      loadTwoSectionView('gmail');
    } else if (activeFilter === 'calendar') {
      loadCalendarView();
    } else if (activeFilter === 'jira') {
      loadSprintBoard();
    } else {
      loadQueue(activeFilter);
    }
  });
});

// -- SSE live push ------------------------------------------------------------

function connectSSE() {
  const es = new EventSource('/api/events');

  // Handle cache-invalidate events — mark source caches as stale
  es.addEventListener('cache-invalidate', (e) => {
    try {
      const { source } = JSON.parse(e.data);
      if (source) cacheInvalidateSource(source);
    } catch {}
  });

  es.onmessage = (e) => {
    try {
      const card = JSON.parse(e.data);
      updateCounts();

      // Only inject card into queue if we're on the All tab or matching source tab
      if (activeFilter === 'all' || activeFilter === card.source) {
        // Skip live injection for views with custom renderers (Jira board,
        // Gmail/Slack two-section, Calendar) — a full reload is needed.
        if (['tasks', 'jira', 'slack', 'gmail', 'calendar'].includes(activeFilter)) {
          // Silently skip — counts are already updated above
        } else {
          const queue = document.getElementById('queue');
          const placeholder = queue.querySelector('[style*="QUEUE EMPTY"]');
          if (placeholder) placeholder.remove();
          queue.insertAdjacentHTML('afterbegin', renderCard(card));
        }
      }

      // macOS notification via API
      fetch(`/api/notify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'eng-buddy', message: card.summary?.slice(0, 80) })
      });
    } catch {}
  };
  es.onerror = () => setTimeout(connectSSE, 5000);
}

// -- Terminal setting ---------------------------------------------------------

async function loadTerminalSetting() {
  try {
    const r = await fetch('/api/settings');
    const data = await r.json();
    document.getElementById('terminal-select').value = data.terminal || 'Terminal';
  } catch {}
}

document.getElementById('terminal-select').addEventListener('change', async (e) => {
  await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ terminal: e.target.value })
  });
});

// -- Restart ------------------------------------------------------------------

document.getElementById('restart-btn').addEventListener('click', async () => {
  const btn = document.getElementById('restart-btn');
  btn.textContent = 'RESTARTING...';
  btn.classList.add('restarting');
  try {
    await fetch('/api/restart', { method: 'POST' });
  } catch {}
  // Poll until the server comes back
  const poll = setInterval(async () => {
    try {
      const r = await fetch('/api/health');
      if (r.ok) {
        clearInterval(poll);
        location.reload();
      }
    } catch {}
  }, 1000);
  // Safety timeout — stop polling after 30s
  setTimeout(() => {
    clearInterval(poll);
    btn.textContent = 'RESTART';
    btn.classList.remove('restarting');
  }, 30000);
});

// -- Init ---------------------------------------------------------------------

async function init() {
  loadQueue();
  connectSSE();
  loadTerminalSetting();

  // Show briefing on first load of the day or after a server restart
  // sessionStorage resets when the tab is opened fresh (e.g. after restart)
  const today = new Date().toISOString().slice(0, 10);
  const briefingShown = sessionStorage.getItem('eng-buddy-briefing-shown');
  if (briefingShown !== today) {
    await loadBriefing();
    sessionStorage.setItem('eng-buddy-briefing-shown', today);
  }
}

init();

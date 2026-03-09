// ~/.claude/eng-buddy/dashboard/static/app.js

let activeFilter = 'all';
let allCards = [];
const runningTerminals = {};
const tabCache = {};
const TAB_CACHE_TTL_MS = 120000;
const dailyState = {
  selectedDate: '',
};
const learningsState = {
  range: 'day',
  date: new Date().toISOString().slice(0, 10),
};
const knowledgeState = {
  query: '',
  selectedPath: '',
};
const pollerState = {
  pollers: [],
  refreshInFlight: false,
  countdownTimerId: null,
  refreshTimerId: null,
};

// -- Helpers ------------------------------------------------------------------

function timeAgo(ts) {
  if (!ts) return '';
  const d = new Date(String(ts).trim().replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return '';
  const diff = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
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

function sectionDomId(name) {
  return String(name || 'section').toLowerCase().replace(/[^a-z0-9]+/g, '-');
}

function cacheIsFresh(entry) {
  return !!entry && (Date.now() - entry.fetchedAt) < TAB_CACHE_TTL_MS;
}

function cacheView(key, payload) {
  tabCache[key] = { ...payload, fetchedAt: Date.now() };
}

function getCachedView(key) {
  return tabCache[key] || null;
}

function invalidateTabCache() {
  Object.keys(tabCache).forEach((key) => delete tabCache[key]);
}

function parseCalendarDate(value) {
  if (!value) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split('-').map(Number);
    return new Date(year, month - 1, day);
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function startOfLocalDay(value) {
  const day = new Date(value);
  day.setHours(0, 0, 0, 0);
  return day;
}

function addDays(value, days) {
  const copy = new Date(value);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function getUpcomingWeekConfig(now = new Date()) {
  const todayStart = startOfLocalDay(now);
  const isSunday = todayStart.getDay() === 0;
  const rangeStart = addDays(todayStart, 1);
  const rangeEndExclusive = isSunday
    ? addDays(todayStart, 8)
    : addDays(todayStart, 7 - todayStart.getDay() + 1);

  return {
    todayStart,
    rangeStart,
    rangeEndExclusive,
    label: isSunday ? 'UPCOMING NEXT WEEK' : 'UPCOMING THIS WEEK',
    emptyLabel: isSunday ? 'NO EVENTS NEXT WEEK' : 'NOTHING ELSE THIS WEEK',
  };
}

function formatCalendarWhen(startValue, endValue) {
  const start = parseCalendarDate(startValue);
  const end = parseCalendarDate(endValue);

  if (start) {
    const dayLabel = start.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    if ((startValue || '').includes('T')) {
      const startTime = start.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
      const endTime = end ? end.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '';
      return `${dayLabel} ${startTime}${endTime ? ` - ${endTime}` : ''}`;
    }
    return `${dayLabel} ALL DAY`;
  }

  return 'TIME TBD';
}

function renderCalendarEvent(card) {
  const actions = Array.isArray(card.proposed_actions) ? card.proposed_actions : [];
  const event = actions[0] || {};
  const context = card.context_notes ? escHtml(card.context_notes) : '';
  const meetLink = event.hangout_link || '';
  const attendees = (event.attendees || []).slice(0, 5).map(a => escHtml(a)).join(', ');
  const isHighPrio = card.classification === 'high';
  const title = escHtml(event.summary || card.summary || 'Untitled event');
  const when = escHtml(formatCalendarWhen(event.start, event.end));

  return `
    <div class="calendar-event ${isHighPrio ? 'high-prio' : ''}">
      <div class="event-time">${when}</div>
      <div class="event-title">${title}</div>
      ${context ? `<div class="event-context">${context}</div>` : ''}
      ${attendees ? `<div class="event-attendees">WITH: ${attendees}</div>` : ''}
      <div class="event-actions">
        ${meetLink ? `<a href="${escHtml(meetLink)}" target="_blank" class="action-btn approve">JOIN</a>` : ''}
        <button class="action-btn open-session" onclick="openSession(${card.id})">PREP NOTES</button>
      </div>
    </div>`;
}

function renderCalendarSection(title, cards, emptyLabel) {
  const body = cards.length
    ? cards.map(renderCalendarEvent).join('')
    : `<div class="calendar-empty">${escHtml(emptyLabel)}</div>`;

  return `
    <div class="calendar-section">
      <div class="section-header">
        <span>${escHtml(title)}</span>
        <span class="section-count">${cards.length}</span>
      </div>
      ${body}
    </div>`;
}

function setCounts(counts = {}) {
  document.getElementById('count-pending').textContent = `${counts.pending || 0} pending`;
  document.getElementById('count-held').textContent = `${counts.held || 0} held`;
}

function formatCountdown(totalSeconds) {
  const safeSeconds = Math.max(0, Math.ceil(Number(totalSeconds) || 0));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function getPollerCountdownSeconds(poller) {
  if (!poller || !poller.next_run_at) return null;

  const intervalMs = Math.max(1000, Number(poller.interval_seconds || 0) * 1000);
  let diffMs = new Date(poller.next_run_at).getTime() - Date.now();
  if (!Number.isFinite(diffMs)) return null;

  if (diffMs < 0 && intervalMs > 0) {
    const catchUpCycles = Math.floor(Math.abs(diffMs) / intervalMs) + 1;
    diffMs += catchUpCycles * intervalMs;
  }

  return Math.max(0, Math.ceil(diffMs / 1000));
}

function renderPollerTimers() {
  const container = document.getElementById('poller-timers');
  if (!container) return;

  if (!pollerState.pollers.length) {
    container.innerHTML = '';
    return;
  }

  container.innerHTML = pollerState.pollers.map((poller) => {
    const countdownSeconds = getPollerCountdownSeconds(poller);
    const countdownLabel = countdownSeconds === null ? '--:--' : formatCountdown(countdownSeconds);
    const lastSeen = poller.last_run_at ? timeAgo(poller.last_run_at) : 'never';
    const health = poller.health || 'unknown';
    const title = `Last run ${lastSeen}. Next fire in ${countdownLabel}.`;
    return `
      <span class="poller-badge ${health}" title="${escHtml(title)}">
        <span class="poller-name">${escHtml((poller.label || poller.id || 'poller').toUpperCase())}</span>
        <span class="poller-dot">•</span>
        <span class="poller-countdown">${escHtml(countdownLabel)}</span>
      </span>
    `;
  }).join('');
}

async function refreshPollerTimers() {
  if (pollerState.refreshInFlight) return;
  pollerState.refreshInFlight = true;

  try {
    const r = await fetch('/api/pollers/status');
    if (!r.ok) throw new Error('Failed to load poller status');
    const data = await r.json();
    pollerState.pollers = Array.isArray(data.pollers) ? data.pollers : [];
    renderPollerTimers();
  } catch {
    // Leave the last-rendered timers in place if the status fetch fails.
  } finally {
    pollerState.refreshInFlight = false;
  }
}

function startPollerTimers() {
  if (!pollerState.countdownTimerId) {
    pollerState.countdownTimerId = setInterval(renderPollerTimers, 1000);
  }
  if (!pollerState.refreshTimerId) {
    pollerState.refreshTimerId = setInterval(refreshPollerTimers, 30000);
  }
}

async function requestDecision(entityType, entityId, action, decision = 'approved', rationale = '') {
  const safeEntity = entityType === 'task' ? 'tasks' : 'cards';
  const r = await fetch(`/api/${safeEntity}/${entityId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action,
      decision,
      rationale: (rationale || '').trim(),
    }),
  });
  const data = await r.json();
  if (!r.ok) {
    throw new Error(data.detail || 'Failed to record decision');
  }
  return data;
}

async function captureFailureFeedback(entityType, entityId, action, errorMessage) {
  try {
    const promptText = `Action "${action}" failed (${errorMessage}). Add a note for self-learning?`;
    const note = window.prompt(promptText, '') || '';
    if (!note.trim()) return;
    await requestDecision(entityType, entityId, action, 'refined', `Failure: ${errorMessage}. User note: ${note}`);
  } catch {
    // Never block user flow on feedback capture failures.
  }
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
      <button class="action-btn" onclick="closeCard(${card.id}, this)">CLOSE</button>
      <button class="action-btn" onclick="writeCardToJira(${card.id}, this)">WRITE TO JIRA</button>
      <button class="action-btn hold" onclick="saveCardToDailyLog(${card.id}, this)">SAVE TO DAILY LOG</button>
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
    buttons += `<button class="action-btn approve" onclick="sendDraft(${card.id}, 'slack')">SEND DRAFT</button>`;
  }
  if (hasDraft && isGmail) {
    buttons += `<button class="action-btn approve" onclick="sendDraft(${card.id}, 'email')">SEND DRAFT</button>`;
  }
  buttons += `<button class="action-btn refine" onclick="toggleRefine(${card.id})">REFINE</button>`;
  buttons += `<button class="action-btn" onclick="dismissCard(${card.id})">DISMISS</button>`;
  buttons += `<button class="action-btn open-session" onclick="openSession(${card.id})">OPEN SESSION</button>`;
  buttons += `<button class="action-btn" onclick="closeCard(${card.id}, this)">CLOSE</button>`;
  buttons += `<button class="action-btn" onclick="writeCardToJira(${card.id}, this)">WRITE TO JIRA</button>`;
  buttons += `<button class="action-btn hold" onclick="saveCardToDailyLog(${card.id}, this)">SAVE TO DAILY LOG</button>`;

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

async function loadTwoSectionView(source, options = {}) {
  const cacheKey = `inbox-${source}`;
  const queue = document.getElementById('queue');
  const cached = getCachedView(cacheKey);

  if (cached) {
    queue.innerHTML = cached.html;
    if (!options.forceRefresh && cacheIsFresh(cached)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING...</div>';
  }

  try {
    const [inboxR, suggestionsR] = await Promise.all([
      fetch(`/api/inbox-view?source=${source}&days=3`),
      source === 'gmail' ? fetch('/api/filters/suggestions') : Promise.resolve(null),
    ]);

    const inbox = await inboxR.json();
    const suggestions = suggestionsR ? await suggestionsR.json() : { suggestions: [] };

    const needsCards = inbox.needs_action || [];
    const noActionCards = inbox.no_action || [];

    const needsHtml = needsCards.map((c) => renderSmartCard(c, source)).join('') || '<div class="section-empty">All clear</div>';
    const noActionHtml = noActionCards.map((c) => renderSmartCard(c, source)).join('') || '<div class="section-empty">Nothing here</div>';

    let suggestionsHtml = '';
    if (suggestions.suggestions.length) {
      suggestionsHtml = `<div class="section-group"><div class="section-header filter-suggest">
        <span>FILTER SUGGESTIONS</span>
        <span class="section-count">${suggestions.suggestions.length}</span>
      </div><div class="section-body" id="section-filters">` +
      suggestions.suggestions.map(renderFilterSuggestion).join('') +
      `</div></div>`;
    }

    const html = `
      <div class="section-group">
        <div class="section-header" onclick="toggleSection('inbox-needs')">
          <span>NEEDS ACTION / UNREAD</span>
          <span class="section-count">${needsCards.length}</span>
          <span class="section-toggle" id="toggle-inbox-needs">&#9660;</span>
        </div>
        <div class="section-body" id="section-inbox-needs">${needsHtml}</div>
      </div>
      <div class="section-group">
        <div class="section-header no-action" onclick="toggleSection('inbox-noaction')">
          <span>RESPONDED / NO ACTION</span>
          <span class="section-count">${noActionCards.length}</span>
          <span class="section-toggle" id="toggle-inbox-noaction">&#9660;</span>
        </div>
        <div class="section-body" id="section-inbox-noaction">${noActionHtml}</div>
      </div>
      ${suggestionsHtml}
    `;

    cacheView(cacheKey, { html });
    if (activeFilter === source) {
      queue.innerHTML = html;
    }
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load ${escHtml(source)}: ${escHtml(e.message)}</div>`;
    }
  }
}

function toggleSection(name) {
  const key = sectionDomId(name);
  const body = document.getElementById(`section-${key}`);
  const toggle = document.getElementById(`toggle-${key}`);
  if (!body || !toggle) return;
  if (body.style.display === 'none') {
    body.style.display = 'block';
    toggle.innerHTML = '&#9660;';
  } else {
    body.style.display = 'none';
    toggle.innerHTML = '&#9654;';
  }
}

// -- Calendar view ------------------------------------------------------------

async function loadCalendarView(options = {}) {
  const cacheKey = 'calendar';
  const queue = document.getElementById('queue');
  const cached = getCachedView(cacheKey);

  if (cached) {
    queue.innerHTML = cached.html;
    if (!options.forceRefresh && cacheIsFresh(cached)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING CALENDAR...</div>';
  }

  try {
    const r = await fetch('/api/cards?source=calendar');
    const data = await r.json();

    const upcomingConfig = getUpcomingWeekConfig();
    const todayCards = [];
    const upcomingWeekCards = [];

    data.cards.forEach((card) => {
      const actions = Array.isArray(card.proposed_actions) ? card.proposed_actions : [];
      const event = actions[0] || {};
      const eventStart = parseCalendarDate(event.start || card.timestamp);
      if (!eventStart) return;

      const eventDay = startOfLocalDay(eventStart);
      if (eventDay.getTime() === upcomingConfig.todayStart.getTime()) {
        todayCards.push(card);
      } else if (eventDay >= upcomingConfig.rangeStart && eventDay < upcomingConfig.rangeEndExclusive) {
        upcomingWeekCards.push(card);
      }
    });

    const byStartTime = (a, b) => {
      const aStart = parseCalendarDate((Array.isArray(a.proposed_actions) ? a.proposed_actions[0] : null)?.start || a.timestamp);
      const bStart = parseCalendarDate((Array.isArray(b.proposed_actions) ? b.proposed_actions[0] : null)?.start || b.timestamp);
      return (aStart?.getTime() || 0) - (bStart?.getTime() || 0);
    };

    todayCards.sort(byStartTime);
    upcomingWeekCards.sort(byStartTime);

    const html = `
      <div class="calendar-agenda">
        ${renderCalendarSection("TODAY'S AGENDA", todayCards, 'NO EVENTS TODAY')}
        ${renderCalendarSection(upcomingConfig.label, upcomingWeekCards, upcomingConfig.emptyLabel)}
      </div>`;
    cacheView(cacheKey, { html });
    if (activeFilter === 'calendar') queue.innerHTML = html;
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed: ${escHtml(e.message)}</div>`;
    }
  }
}

// -- Filter suggestions -------------------------------------------------------

function renderFilterSuggestion(suggestion) {
  return `
    <div class="filter-suggestion">
      <div class="filter-pattern">PATTERN: ${escHtml(suggestion.pattern)} (ignored ${suggestion.ignore_count}x)</div>
      <div class="filter-actions">
        <button class="action-btn approve" onclick="createFilter(${suggestion.id}, '${escHtml(suggestion.pattern)}', 'eng-buddy/auto-filtered')">CREATE FILTER</button>
        <button class="action-btn" onclick="dismissFilter(${suggestion.id}, false)">NOT NOW</button>
        <button class="action-btn hold" onclick="dismissFilter(${suggestion.id}, true)">NEVER</button>
      </div>
    </div>`;
}

// -- Smart actions ------------------------------------------------------------

async function sendDraft(id, type) {
  const endpoint = type === 'slack' ? 'send-slack' : 'send-email';
  const btn = event.target;
  btn.textContent = 'SENDING...';
  btn.disabled = true;
  try {
    const rationale = window.prompt('Approval note for sending this draft (optional):', '') || '';
    const decision = await requestDecision('card', id, 'send-draft', 'approved', rationale);
    const r = await fetch(`/api/cards/${id}/${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision_event_id: decision.decision_event_id })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Send failed');
    invalidateTabCache();
    btn.textContent = 'SENT';
    const card = document.getElementById(`card-${id}`);
    if (card) card.style.opacity = '0.5';
  } catch (e) {
    await captureFailureFeedback('card', id, 'send-draft', e.message);
    btn.textContent = 'FAILED';
    btn.disabled = false;
  }
}

async function dismissCard(id) {
  try {
    const rationale = window.prompt('Reason for dismissing this card (optional):', '') || '';
    const decision = await requestDecision('card', id, 'dismiss', 'approved', rationale);
    const r = await fetch(`/api/cards/${id}/dismiss`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision_event_id: decision.decision_event_id }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Dismiss failed');
    invalidateTabCache();
    const card = document.getElementById(`card-${id}`);
    if (card) {
      card.style.opacity = '0.3';
      setTimeout(() => card.remove(), 500);
    }
  } catch (e) {
    await captureFailureFeedback('card', id, 'dismiss', e.message);
    alert(`Card #${id}: ${e.message}`);
  }
}

async function createFilter(suggestionId, pattern, label) {
  await fetch('/api/filters/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ suggestion_id: suggestionId, pattern: pattern, label: label })
  });
  invalidateTabCache();
  loadTwoSectionView('gmail', { forceRefresh: true });
}

async function dismissFilter(suggestionId, permanent) {
  await fetch('/api/filters/dismiss', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ suggestion_id: suggestionId, permanent: permanent })
  });
  invalidateTabCache();
  loadTwoSectionView('gmail', { forceRefresh: true });
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
  if (refineEl.style.display === 'block') {
    loadCardRefineHistory(id);
  }
}

// -- Actions ------------------------------------------------------------------

async function holdCard(id) {
  try {
    const rationale = window.prompt('Why hold this card? (optional)', '') || '';
    await requestDecision('card', id, 'hold', 'rejected', rationale);
    await fetch(`/api/cards/${id}/hold`, { method: 'POST' });
    invalidateTabCache();
    const card = document.getElementById(`card-${id}`);
    card.className = card.className.replace(/\b(pending|approved|completed)\b/g, 'held');
    updateCounts();
  } catch (e) {
    await captureFailureFeedback('card', id, 'hold', e.message);
    alert(`Card #${id}: ${e.message}`);
  }
}

async function approveCard(id) {
  try {
    const approved = window.confirm(`Approve execution for card #${id}?`);
    if (!approved) return;
    const rationale = window.prompt('Approval note (optional):', '') || '';
    const decision = await requestDecision('card', id, 'execute', 'approved', rationale);

    invalidateTabCache();
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

    // Connect WebSocket (decision token is mandatory on server)
    const ws = new WebSocket(`ws://localhost:7777/ws/execute/${id}?decision_event_id=${decision.decision_event_id}`);
    ws.onmessage = (e) => term.write(e.data);
    ws.onclose = () => {
      card.className = card.className.replace('running', 'completed');
      updateCounts();
    };

    // Keyboard input -> PTY
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data);
    });
  } catch (e) {
    await captureFailureFeedback('card', id, 'execute', e.message);
    alert(`Card #${id}: ${e.message}`);
  }
}

async function openSession(id) {
  await fetch(`/api/cards/${id}/open-session`, { method: 'POST' });
}

async function closeCard(id, btn) {
  const confirmed = window.confirm(`Mark card #${id} as completed?`);
  if (!confirmed) return;
  const note = window.prompt('Optional close note:', '') || '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'CLOSING...';
  }
  try {
    const decision = await requestDecision('card', id, 'close', 'approved', note);
    const r = await fetch(`/api/cards/${id}/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note, decision_event_id: decision.decision_event_id }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Close failed');
    invalidateTabCache();
    if (activeFilter === 'slack' || activeFilter === 'gmail') {
      await loadTwoSectionView(activeFilter, { forceRefresh: true });
    } else if (activeFilter === 'all' || activeFilter === 'freshservice' || activeFilter === 'jira') {
      await loadQueue(activeFilter, { forceRefresh: true });
    }
    alert(`Card #${id} closed and logged to ${data.daily_file || 'daily log'}.`);
  } catch (e) {
    await captureFailureFeedback('card', id, 'close', e.message);
    alert(`Card #${id}: ${e.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'CLOSE';
    }
  }
}

async function writeCardToJira(id, btn) {
  const note = window.prompt('Jira update note (optional):', '') || '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'WRITING...';
  }
  try {
    const decision = await requestDecision('card', id, 'write-jira', 'approved', note);
    const r = await fetch(`/api/cards/${id}/write-jira`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note, decision_event_id: decision.decision_event_id }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Write Jira failed');
    alert(`Card #${id}: wrote Jira update on ${data.issue_key || 'issue'}.`);
  } catch (e) {
    await captureFailureFeedback('card', id, 'write-jira', e.message);
    alert(`Card #${id}: ${e.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'WRITE TO JIRA';
    }
  }
}

async function saveCardToDailyLog(id, btn) {
  const note = window.prompt('Daily log note (optional):', '') || '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'SAVING...';
  }
  try {
    const decision = await requestDecision('card', id, 'daily-log', 'approved', note);
    const r = await fetch(`/api/cards/${id}/daily-log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note, decision_event_id: decision.decision_event_id }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Save daily log failed');
    alert(`Card #${id}: saved to ${data.daily_file}.`);
  } catch (e) {
    await captureFailureFeedback('card', id, 'daily-log', e.message);
    alert(`Card #${id}: ${e.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'SAVE TO DAILY LOG';
    }
  }
}

// -- Refine -------------------------------------------------------------------

const refineHistories = {};
const loadedCardRefineHistory = {};

async function loadCardRefineHistory(id) {
  if (loadedCardRefineHistory[id]) return;
  loadedCardRefineHistory[id] = true;
  try {
    const r = await fetch(`/api/cards/${id}/chat-history`);
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Failed to load history');
    const messages = Array.isArray(data.messages) ? data.messages : [];
    const historyEl = document.getElementById(`refine-history-${id}`);
    if (!historyEl) return;

    refineHistories[id] = messages.map((m) => ({ role: m.role, content: m.content }));
    historyEl.innerHTML = messages.map((m) => {
      const cls = m.role === 'assistant' ? 'msg-claude' : 'msg-user';
      const who = m.role === 'assistant' ? 'BUDDY' : 'YOU';
      return `<div class="${cls}">${who}: ${escHtml(m.content || '')}</div>`;
    }).join('');
    historyEl.scrollTop = historyEl.scrollHeight;
  } catch {
    // non-fatal
  }
}

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

// -- Jira + Tasks Views -------------------------------------------------------

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

function renderStatusSections(sectionMap, order, emptyLabel) {
  if (!order.length) {
    return `<div class="section-empty">${emptyLabel}</div>`;
  }

  return order.map((statusName) => {
    const sectionKey = `jira-${sectionDomId(statusName)}`;
    const items = sectionMap[statusName] || [];
    return `
      <div class="section-group">
        <div class="section-header" onclick="toggleSection('${sectionKey}')">
          <span>${escHtml(statusName).toUpperCase()}</span>
          <span class="section-count">${items.length}</span>
          <span class="section-toggle" id="toggle-${sectionDomId(sectionKey)}">&#9660;</span>
        </div>
        <div class="section-body" id="section-${sectionDomId(sectionKey)}">
          ${items.map(renderJiraIssue).join('') || '<div class="section-empty">None</div>'}
        </div>
      </div>
    `;
  }).join('');
}

async function loadJiraStatusView(options = {}) {
  const cacheKey = 'jira';
  const queue = document.getElementById('queue');
  const cached = getCachedView(cacheKey);

  if (cached) {
    queue.innerHTML = cached.html;
    if (!options.forceRefresh && cacheIsFresh(cached)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING SPRINT...</div>';
  }

  try {
    const r = await fetch(`/api/jira/sprint?refresh=${options.forceRefresh ? 'true' : 'false'}`);
    const data = await r.json();
    const sectionMap = data.by_status || {};
    const order = data.status_order || Object.keys(sectionMap);
    const html = renderStatusSections(sectionMap, order, 'No Jira issues found');
    cacheView(cacheKey, { html });
    if (activeFilter === 'jira') queue.innerHTML = html;
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load sprint: ${escHtml(e.message)}</div>`;
    }
  }
}

function renderTaskCard(task, index) {
  const taskId = Number(task.number);
  const domId = `task-${taskId}-${index}`;
  const status = escHtml(task.status || 'unknown');
  const priority = escHtml(task.priority || 'unknown');
  const desc = escHtml(task.description || '');
  const jiraKeys = Array.isArray(task.jira_keys) ? task.jira_keys : [];
  const jiraHtml = jiraKeys.length
    ? `<div class="task-jira-keys">${jiraKeys.map((key) => `<span class="jira-label">${escHtml(key)}</span>`).join('')}</div>`
    : '';
  const related = Array.isArray(task.related_cards) ? task.related_cards : [];
  const relatedHtml = related.length
    ? related.map((card) => `
      <button class="task-link-btn" onclick="openCardInAll(${card.id})">
        ${sourceBadge(card.source)} ${escHtml(card.summary || `card-${card.id}`)}
      </button>
    `).join('')
    : '<div class="section-empty">No linked cards yet</div>';

  return `
    <div class="card task-card" id="${domId}" data-task="${taskId}">
      <div class="card-header" onclick="toggleTaskFoldout('${domId}')">
        <div class="card-meta">
          <span class="badge cls-needs-response">TASK #${task.number}</span>
          <span class="badge cls-informational">${status.toUpperCase()}</span>
          <span class="badge cls-informational">${priority.toUpperCase()}</span>
        </div>
        <div class="card-summary">${escHtml(task.title || '(untitled task)')}</div>
        <div class="card-toggle" id="task-toggle-${domId}">&#9660;</div>
      </div>
      <div class="card-actions task-actions">
        <button class="action-btn open-session" onclick="openTaskSession(${taskId}, this)">OPEN SESSION</button>
        <button class="action-btn refine" onclick="toggleTaskRefine('${domId}')">REFINE</button>
        <button class="action-btn approve" onclick="closeTask(${taskId}, this)">CLOSE TASK</button>
        <button class="action-btn" onclick="writeTaskToJira(${taskId}, this)">WRITE TO JIRA</button>
        <button class="action-btn hold" onclick="saveTaskToDailyLog(${taskId}, this)">SAVE TO DAILY LOG</button>
      </div>
      <div class="card-foldout" id="task-foldout-${domId}">
        ${desc ? `<div class="card-context">${desc}</div>` : ''}
        ${jiraHtml}
        <div class="task-links">${relatedHtml}</div>
        <div id="task-refine-${domId}" style="display:none; margin-top:16px;">
          <div class="refine-panel">
            <div class="proposed-actions"><h4>Refine Task</h4></div>
            <div class="refine-history" id="task-refine-history-${domId}"></div>
            <div class="refine-input-row">
              <textarea class="refine-input" id="task-refine-input-${domId}"
                placeholder="e.g. split this into 3 actionable steps and call out blockers"
                onkeydown="handleTaskRefineKey(event, '${domId}', ${taskId})"></textarea>
              <button class="action-btn" onclick="sendTaskRefine('${domId}', ${taskId})">SEND</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

async function loadTasksView(options = {}) {
  const cacheKey = 'tasks';
  const queue = document.getElementById('queue');
  const cached = getCachedView(cacheKey);

  if (cached) {
    queue.innerHTML = cached.html;
    if (!options.forceRefresh && cacheIsFresh(cached)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING TASKS...</div>';
  }

  try {
    const r = await fetch('/api/tasks');
    const data = await r.json();
    const tasks = (data.tasks || []).filter((task) => {
      const s = String(task.status || '').toLowerCase();
      return !/(completed|closed|done|cancelled)/.test(s);
    });
    if (!tasks.length) {
      const html = '<div class="section-empty">No active tasks found in active-tasks.md</div>';
      cacheView(cacheKey, { html });
      if (activeFilter === 'tasks') queue.innerHTML = html;
      return;
    }
    const html = tasks.map(renderTaskCard).join('');
    cacheView(cacheKey, { html });
    if (activeFilter === 'tasks') queue.innerHTML = html;
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load tasks: ${escHtml(e.message)}</div>`;
    }
  }
}

// -- Daily / Learnings / Knowledge views --------------------------------------

async function loadDailyView(options = {}) {
  const cacheKey = `daily-${dailyState.selectedDate || 'latest'}`;
  const queue = document.getElementById('queue');
  const cached = getCachedView(cacheKey);
  if (cached) {
    queue.innerHTML = cached.html;
    if (!options.forceRefresh && cacheIsFresh(cached)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING DAILY LOGS...</div>';
  }

  try {
    const listResp = await fetch('/api/daily/logs');
    const listData = await listResp.json();
    if (!listResp.ok) throw new Error(listData.detail || 'Failed to load daily logs');

    const logs = Array.isArray(listData.logs) ? listData.logs : [];
    if (!logs.length) {
      const html = '<div class="section-empty">No daily logs found</div>';
      cacheView(cacheKey, { html });
      if (activeFilter === 'daily') queue.innerHTML = html;
      return;
    }

    const selectedDate = dailyState.selectedDate || logs[0].date;
    const detailResp = await fetch(`/api/daily/logs/${selectedDate}`);
    const detailData = await detailResp.json();
    if (!detailResp.ok) throw new Error(detailData.detail || 'Failed to load selected daily log');
    dailyState.selectedDate = detailData.date;

    const stats = detailData.stats || {};
    const statsHtml = Object.keys(stats).length
      ? Object.entries(stats).map(([k, v]) => `<span class="badge cls-informational">${escHtml(k)}: ${escHtml(v)}</span>`).join('')
      : '<span class="badge cls-informational">No stats for this day</span>';

    const listHtml = logs.slice(0, 60).map((log) => `
      <button class="task-link-btn ${log.date === dailyState.selectedDate ? 'active' : ''}" onclick="selectDailyDate('${escHtml(log.date)}')">
        ${escHtml(log.date || log.name)}
      </button>
    `).join('');

    const html = `
      <div class="section-group">
        <div class="section-header"><span>DAILY LOGS</span><span class="section-count">${logs.length}</span></div>
        <div class="section-body">
          <div class="task-links">${listHtml}</div>
          <div class="card-context" style="margin-top:12px;">${statsHtml}</div>
          <pre class="action-draft" style="margin-top:12px; white-space:pre-wrap;">${escHtml(detailData.content || '')}</pre>
        </div>
      </div>
    `;

    cacheView(cacheKey, { html });
    if (activeFilter === 'daily') queue.innerHTML = html;
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load daily tab: ${escHtml(e.message)}</div>`;
    }
  }
}

function selectDailyDate(day) {
  dailyState.selectedDate = day;
  loadDailyView({ forceRefresh: true });
}

async function loadLearningsView(options = {}) {
  const cacheKey = `learnings-${learningsState.range}-${learningsState.date}`;
  const queue = document.getElementById('queue');
  const cached = getCachedView(cacheKey);
  if (cached) {
    queue.innerHTML = cached.html;
    if (!options.forceRefresh && cacheIsFresh(cached)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING LEARNINGS...</div>';
  }

  try {
    const [summaryResp, eventsResp] = await Promise.all([
      fetch(`/api/learnings/summary?range=${learningsState.range}&date=${learningsState.date}`),
      fetch(`/api/learnings/events?range=${learningsState.range}&date=${learningsState.date}&limit=200`),
    ]);
    const summary = await summaryResp.json();
    const eventsData = await eventsResp.json();
    if (!summaryResp.ok) throw new Error(summary.detail || 'Failed to load learning summary');
    if (!eventsResp.ok) throw new Error(eventsData.detail || 'Failed to load learning events');

    const byBucket = summary.by_bucket || {};
    const bucketRows = Object.keys(byBucket).length
      ? Object.entries(byBucket).sort((a, b) => (b[1].total || 0) - (a[1].total || 0)).map(([bucket, vals]) => `
          <div class="jira-issue">
            <div class="jira-issue-key">${escHtml(bucket)}</div>
            <div class="jira-issue-summary">total: ${escHtml(vals.total || 0)} | captured: ${escHtml(vals.captured || 0)} | pending-expansion: ${escHtml(vals.needs_category_expansion || 0)}</div>
          </div>
      `).join('')
      : '<div class="section-empty">No learnings captured in this window</div>';

    const pending = Array.isArray(summary.pending_category_expansions) ? summary.pending_category_expansions : [];
    const pendingHtml = pending.length
      ? pending.map((item) => `<span class="badge cls-needs-response">${escHtml(item.category)} (${escHtml(item.count)})</span>`).join('')
      : '<span class="badge cls-informational">No pending category expansion</span>';

    const topTitles = Array.isArray(summary.top_titles) ? summary.top_titles : [];
    const topHtml = topTitles.length
      ? topTitles.map((t) => `<div class="briefing-item">${escHtml(t.title)} <span class="briefing-age">${escHtml(t.count)}</span></div>`).join('')
      : '<div class="section-empty">No repeated learning titles</div>';

    const events = Array.isArray(eventsData.events) ? eventsData.events : [];
    const eventHtml = events.length
      ? events.map((ev) => `
          <div class="action-item">
            <div class="action-type">${escHtml(ev.created_at || '')} | ${escHtml(ev.category || 'uncategorized')} | ${escHtml(ev.status || '')}</div>
            <div class="action-draft">${escHtml(ev.title || ev.note || '')}</div>
          </div>
      `).join('')
      : '<div class="section-empty">No events in this window</div>';

    const html = `
      <div class="section-group">
        <div class="section-header">
          <span>LEARNINGS (${learningsState.range.toUpperCase()})</span>
          <span class="section-count">${events.length}</span>
        </div>
        <div class="section-body">
          <div class="task-links">
            <button class="task-link-btn ${learningsState.range === 'day' ? 'active' : ''}" onclick="setLearningsRange('day')">DAY</button>
            <button class="task-link-btn ${learningsState.range === 'week' ? 'active' : ''}" onclick="setLearningsRange('week')">WEEK</button>
          </div>
          <div class="card-context" style="margin-top:12px;">
            <label style="letter-spacing:2px;">DATE</label>
            <input type="date" value="${escHtml(learningsState.date)}" onchange="setLearningsDate(this.value)" />
          </div>
          <div class="section-group" style="margin-top:12px;">
            <div class="section-header"><span>BY BUCKET</span></div>
            <div class="section-body">${bucketRows}</div>
          </div>
          <div class="section-group">
            <div class="section-header"><span>PENDING CATEGORY EXPANSION</span></div>
            <div class="section-body">${pendingHtml}</div>
          </div>
          <div class="section-group">
            <div class="section-header"><span>TOP TITLES</span></div>
            <div class="section-body">${topHtml}</div>
          </div>
          <div class="section-group">
            <div class="section-header"><span>RECENT EVENTS</span></div>
            <div class="section-body">${eventHtml}</div>
          </div>
        </div>
      </div>
    `;

    cacheView(cacheKey, { html });
    if (activeFilter === 'learnings') queue.innerHTML = html;
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load learnings tab: ${escHtml(e.message)}</div>`;
    }
  }
}

function setLearningsRange(nextRange) {
  learningsState.range = nextRange === 'week' ? 'week' : 'day';
  loadLearningsView({ forceRefresh: true });
}

function setLearningsDate(nextDate) {
  if (!nextDate) return;
  learningsState.date = nextDate;
  loadLearningsView({ forceRefresh: true });
}

async function loadKnowledgeView(options = {}) {
  const cacheKey = `knowledge-${knowledgeState.selectedPath || 'index'}-${knowledgeState.query}`;
  const queue = document.getElementById('queue');
  const cached = getCachedView(cacheKey);
  if (cached) {
    queue.innerHTML = cached.html;
    if (!options.forceRefresh && cacheIsFresh(cached)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING KNOWLEDGE...</div>';
  }

  try {
    const idxResp = await fetch('/api/knowledge/index');
    const idxData = await idxResp.json();
    if (!idxResp.ok) throw new Error(idxData.detail || 'Failed to load knowledge index');
    let docs = Array.isArray(idxData.documents) ? idxData.documents : [];
    const q = knowledgeState.query.trim().toLowerCase();
    if (q) {
      docs = docs.filter((d) => `${d.path} ${d.group} ${d.name}`.toLowerCase().includes(q));
    }

    const selected = knowledgeState.selectedPath || (docs[0] ? docs[0].path : '');
    knowledgeState.selectedPath = selected;
    let detail = { content: '', path: selected, is_markdown: true };
    if (selected) {
      const docResp = await fetch(`/api/knowledge/doc?path=${encodeURIComponent(selected)}`);
      detail = await docResp.json();
      if (!docResp.ok) throw new Error(detail.detail || 'Failed to load selected document');
    }

    const listHtml = docs.slice(0, 300).map((doc) => `
      <button class="task-link-btn ${doc.path === selected ? 'active' : ''}" onclick="selectKnowledgeDoc(decodeURIComponent('${encodeURIComponent(doc.path)}'))">
        [${escHtml(doc.group)}] ${escHtml(doc.path)}
      </button>
    `).join('') || '<div class="section-empty">No documents match this filter</div>';

    const html = `
      <div class="section-group">
        <div class="section-header"><span>KNOWLEDGE BASE</span><span class="section-count">${docs.length}</span></div>
        <div class="section-body">
          <div class="card-context">
            <label style="letter-spacing:2px;">SEARCH</label>
            <input type="text" placeholder="filter docs..." value="${escHtml(knowledgeState.query)}" oninput="setKnowledgeQuery(this.value)" />
          </div>
          <div class="task-links" style="margin-top:12px; max-height:220px; overflow:auto;">${listHtml}</div>
          <pre class="action-draft" style="margin-top:12px; white-space:pre-wrap;">${escHtml(detail.content || '')}</pre>
        </div>
      </div>
    `;

    cacheView(cacheKey, { html });
    if (activeFilter === 'knowledge') queue.innerHTML = html;
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load knowledge tab: ${escHtml(e.message)}</div>`;
    }
  }
}

function setKnowledgeQuery(q) {
  knowledgeState.query = q || '';
  loadKnowledgeView({ forceRefresh: true });
}

function selectKnowledgeDoc(path) {
  knowledgeState.selectedPath = path;
  loadKnowledgeView({ forceRefresh: true });
}

function toggleTaskFoldout(domId) {
  const foldout = document.getElementById(`task-foldout-${domId}`);
  const toggle = document.getElementById(`task-toggle-${domId}`);
  if (!foldout || !toggle) return;

  foldout.classList.toggle('open');
  toggle.innerHTML = toggle.innerHTML.includes('\u25BC')
    ? toggle.innerHTML.replace('\u25BC', '\u25B2')
    : toggle.innerHTML.replace('\u25B2', '\u25BC');
}

function toggleTaskRefine(domId) {
  const foldout = document.getElementById(`task-foldout-${domId}`);
  const refine = document.getElementById(`task-refine-${domId}`);
  if (!foldout || !refine) return;

  if (!foldout.classList.contains('open')) {
    foldout.classList.add('open');
    const toggle = document.getElementById(`task-toggle-${domId}`);
    if (toggle) toggle.innerHTML = '&#9650;';
  }
  refine.style.display = refine.style.display === 'none' ? 'block' : 'none';
  if (refine.style.display === 'block') {
    const taskNumber = Number(domId.split('-')[1] || '0');
    if (taskNumber) loadTaskRefineHistory(domId, taskNumber);
  }
}

const taskRefineHistories = {};
const loadedTaskRefineHistory = {};

function handleTaskRefineKey(event, domId, taskNumber) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendTaskRefine(domId, taskNumber);
  }
}

async function sendTaskRefine(domId, taskNumber) {
  const input = document.getElementById(`task-refine-input-${domId}`);
  const history = document.getElementById(`task-refine-history-${domId}`);
  if (!input || !history) return;

  const msg = input.value.trim();
  if (!msg) return;

  if (!taskRefineHistories[domId]) taskRefineHistories[domId] = [];
  taskRefineHistories[domId].push({ role: 'user', content: msg });

  history.innerHTML += `<div class="msg-user">YOU: ${escHtml(msg)}</div>`;
  input.value = '';
  input.disabled = true;
  history.innerHTML += `<div class="msg-claude" id="task-refine-stream-${domId}">BUDDY: thinking...</div>`;

  try {
    const r = await fetch(`/api/tasks/${taskNumber}/refine`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, history: taskRefineHistories[domId].slice(0, -1) })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Task refine failed');
    const streamEl = document.getElementById(`task-refine-stream-${domId}`);
    streamEl.textContent = `BUDDY: ${data.response || ''}`;
    streamEl.removeAttribute('id');
    taskRefineHistories[domId].push({ role: 'assistant', content: data.response || '' });
  } catch (e) {
    const streamEl = document.getElementById(`task-refine-stream-${domId}`);
    if (streamEl) streamEl.textContent = `BUDDY: ${e.message}`;
  } finally {
    input.disabled = false;
    input.focus();
    history.scrollTop = history.scrollHeight;
  }
}

async function loadTaskRefineHistory(domId, taskNumber) {
  if (loadedTaskRefineHistory[domId]) return;
  loadedTaskRefineHistory[domId] = true;
  try {
    const r = await fetch(`/api/tasks/${taskNumber}/chat-history`);
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Failed to load history');
    const messages = Array.isArray(data.messages) ? data.messages : [];
    const historyEl = document.getElementById(`task-refine-history-${domId}`);
    if (!historyEl) return;

    taskRefineHistories[domId] = messages.map((m) => ({ role: m.role, content: m.content }));
    historyEl.innerHTML = messages.map((m) => {
      const cls = m.role === 'assistant' ? 'msg-claude' : 'msg-user';
      const who = m.role === 'assistant' ? 'BUDDY' : 'YOU';
      return `<div class="${cls}">${who}: ${escHtml(m.content || '')}</div>`;
    }).join('');
    historyEl.scrollTop = historyEl.scrollHeight;
  } catch {
    // non-fatal
  }
}

async function openTaskSession(taskNumber, btn) {
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'OPENING...';
  }
  try {
    const r = await fetch(`/api/tasks/${taskNumber}/open-session`, { method: 'POST' });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Failed to open session');
    if (btn) btn.textContent = 'OPENED';
  } catch (e) {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'OPEN SESSION';
    }
    alert(`Task #${taskNumber}: ${e.message}`);
  }
}

async function closeTask(taskNumber, btn) {
  const confirmed = window.confirm(`Mark Task #${taskNumber} as completed?`);
  if (!confirmed) return;
  const note = window.prompt('Optional close note (saved to task state, daily log, and decision history):', '') || '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'CLOSING...';
  }
  try {
    const decision = await requestDecision('task', taskNumber, 'close', 'approved', note);
    const r = await fetch(`/api/tasks/${taskNumber}/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note, decision_event_id: decision.decision_event_id })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Failed to close task');
    invalidateTabCache();
    await loadTasksView({ forceRefresh: true });
    const dailyFile = data.daily_log_file || 'daily log';
    alert(`Task #${taskNumber} closed and logged to ${dailyFile}.`);
  } catch (e) {
    await captureFailureFeedback('task', taskNumber, 'close', e.message);
    alert(`Task #${taskNumber}: ${e.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'CLOSE TASK';
    }
  }
}

async function writeTaskToJira(taskNumber, btn) {
  const note = window.prompt('Jira update note (optional). Leave blank for auto-generated update:', '') || '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'WRITING...';
  }
  try {
    const decision = await requestDecision('task', taskNumber, 'write-jira', 'approved', note);
    const r = await fetch(`/api/tasks/${taskNumber}/write-jira`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note, decision_event_id: decision.decision_event_id })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Failed to write Jira update');
    const issueKey = data.issue_key || 'issue';
    alert(`Task #${taskNumber}: wrote Jira update on ${issueKey}.`);
  } catch (e) {
    await captureFailureFeedback('task', taskNumber, 'write-jira', e.message);
    alert(`Task #${taskNumber}: ${e.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'WRITE TO JIRA';
    }
  }
}

async function saveTaskToDailyLog(taskNumber, btn) {
  const note = window.prompt('Daily log note (optional):', '') || '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'SAVING...';
  }
  try {
    const decision = await requestDecision('task', taskNumber, 'daily-log', 'approved', note);
    const r = await fetch(`/api/tasks/${taskNumber}/daily-log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note, decision_event_id: decision.decision_event_id })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Failed to save daily log');
    alert(`Task #${taskNumber}: saved to ${data.daily_file}.`);
  } catch (e) {
    await captureFailureFeedback('task', taskNumber, 'daily-log', e.message);
    alert(`Task #${taskNumber}: ${e.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'SAVE TO DAILY LOG';
    }
  }
}

async function openCardInAll(cardId) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  const allBtn = document.querySelector('.filter-btn[data-source="all"]');
  if (allBtn) allBtn.classList.add('active');
  activeFilter = 'all';
  await loadQueue('all', { forceRefresh: true });
  const card = document.getElementById(`card-${cardId}`);
  if (card) {
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card.classList.add('card-flash');
    setTimeout(() => card.classList.remove('card-flash'), 1600);
  }
}

// -- Counts -------------------------------------------------------------------

function updateCounts() {
  fetch('/api/cards?status=pending')
    .then(r => r.json())
    .then(data => {
      setCounts(data.counts || {});
      const running = document.querySelectorAll('.card.running').length;
      document.getElementById('count-running').textContent = `${running} running`;
    });
}

// -- Load queue ---------------------------------------------------------------

async function loadQueue(source = 'all', options = {}) {
  const cacheKey = `queue-${source}`;
  const queue = document.getElementById('queue');
  const cached = getCachedView(cacheKey);

  if (cached) {
    allCards = cached.cards || [];
    setCounts(cached.counts || {});
    queue.innerHTML = cached.html;
    if (!options.forceRefresh && cacheIsFresh(cached)) return;
  } else {
    queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING...</div>';
  }

  const url = source === 'all' ? '/api/cards?status=all' : `/api/cards?source=${source}`;
  try {
    const r = await fetch(url);
    const data = await r.json();
    allCards = data.cards || [];
    setCounts(data.counts || {});

    const html = !allCards.length
      ? '<div style="color:#444;padding:40px;text-align:center;letter-spacing:4px">QUEUE EMPTY</div>'
      : allCards.map(renderCard).join('');

    cacheView(cacheKey, { html, cards: allCards, counts: data.counts || {} });
    if (activeFilter === source) queue.innerHTML = html;
  } catch (e) {
    if (!cached) {
      queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load ${escHtml(source)}: ${escHtml(e.message)}</div>`;
    }
  }
}

// -- Filters ------------------------------------------------------------------

document.querySelectorAll('.filter-btn[data-source]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.source;
    if (activeFilter === 'slack') {
      loadTwoSectionView('slack');
    } else if (activeFilter === 'gmail') {
      loadTwoSectionView('gmail');
    } else if (activeFilter === 'calendar') {
      loadCalendarView();
    } else if (activeFilter === 'jira') {
      loadJiraStatusView();
    } else if (activeFilter === 'tasks') {
      loadTasksView();
    } else if (activeFilter === 'daily') {
      loadDailyView();
    } else if (activeFilter === 'learnings') {
      loadLearningsView();
    } else if (activeFilter === 'knowledge') {
      loadKnowledgeView();
    } else {
      loadQueue(activeFilter);
    }
  });
});

// -- SSE live push ------------------------------------------------------------

function connectSSE() {
  const es = new EventSource('/api/events');
  es.onmessage = (e) => {
    try {
      const card = JSON.parse(e.data);
      // Only live-insert cards while viewing ALL to avoid cross-tab UI jumps.
      if (activeFilter === 'all') {
        const queue = document.getElementById('queue');
        const placeholder = queue.querySelector('[style*="QUEUE EMPTY"]');
        if (placeholder) placeholder.remove();
        queue.insertAdjacentHTML('afterbegin', renderCard(card));
      }
      invalidateTabCache();
      updateCounts();

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

// -- Init ---------------------------------------------------------------------

async function init() {
  await Promise.all([
    loadQueue(),
    loadTerminalSetting(),
    refreshPollerTimers(),
  ]);
  startPollerTimers();
  updateCounts();
  connectSSE();

  // Show briefing on first load of the day
  const today = new Date().toISOString().slice(0, 10);
  const lastBriefing = localStorage.getItem('eng-buddy-last-briefing');
  if (lastBriefing !== today) {
    await loadBriefing();
    localStorage.setItem('eng-buddy-last-briefing', today);
  }
}

init();

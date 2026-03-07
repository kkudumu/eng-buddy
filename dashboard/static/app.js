// ~/.claude/eng-buddy/dashboard/static/app.js

let activeFilter = 'all';
let allCards = [];
const runningTerminals = {};

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
  queue.innerHTML = '<div style="color:#666;padding:40px;text-align:center;letter-spacing:4px">LOADING SPRINT...</div>';
  try {
    const r = await fetch('/api/jira/sprint');
    const data = await r.json();
    queue.innerHTML = renderSprintBoard(data.board);
  } catch (e) {
    queue.innerHTML = `<div style="color:#ea4335;padding:40px;text-align:center;">Failed to load sprint: ${e.message}</div>`;
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
  const url = source === 'all' ? '/api/cards' : `/api/cards?source=${source}`;
  const r = await fetch(url);
  const data = await r.json();
  allCards = data.cards;

  document.getElementById('count-pending').textContent = `${data.counts.pending || 0} pending`;
  document.getElementById('count-held').textContent = `${data.counts.held || 0} held`;

  const queue = document.getElementById('queue');
  if (!allCards.length) {
    queue.innerHTML = '<div style="color:#444;padding:40px;text-align:center;letter-spacing:4px">QUEUE EMPTY</div>';
    return;
  }
  queue.innerHTML = allCards.map(renderCard).join('');
}

// -- Filters ------------------------------------------------------------------

document.querySelectorAll('.filter-btn[data-source]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.source;
    if (activeFilter === 'jira') {
      loadSprintBoard();
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
      // Prepend new card to queue
      const queue = document.getElementById('queue');
      const placeholder = queue.querySelector('[style*="QUEUE EMPTY"]');
      if (placeholder) placeholder.remove();
      queue.insertAdjacentHTML('afterbegin', renderCard(card));
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

loadQueue();
connectSSE();
loadTerminalSetting();

import type {
  CardsResponse, InboxViewResponse, CardSource, SettingsResponse,
  DecisionResponse, RefineResponse, ChatHistoryResponse, TasksResponse,
  JiraSprint, DailyLogsResponse, DailyLog, KnowledgeIndexResponse,
  BriefingResponse, PlanResponse, RestartResponse, RestartStatusResponse,
  PollersResponse, OpenSessionResponse, GmailAnalyzeResponse,
} from './types'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = options ? await fetch(url, options) : await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function fetchCards(source?: CardSource): Promise<CardsResponse> {
  const param = source && source !== 'all' ? `source=${source}` : 'status=all'
  return request<CardsResponse>(`/api/cards?${param}`)
}

export async function fetchInboxView(source: string, days: number = 3): Promise<InboxViewResponse> {
  return request<InboxViewResponse>(`/api/inbox-view?source=${source}&days=${days}`)
}

export async function performCardAction(cardId: number, action: string, body?: Record<string, unknown>): Promise<unknown> {
  return request(`/api/cards/${cardId}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
}

export async function fetchHealth(): Promise<{ status: string }> {
  return request('/api/health')
}

// ── Wave 2 endpoints ────────────────────────────────────

export async function fetchSettings(): Promise<SettingsResponse> {
  return request<SettingsResponse>('/api/settings')
}

export async function updateSettings(body: Partial<SettingsResponse>): Promise<SettingsResponse> {
  return request<SettingsResponse>('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function postDecision(
  entityType: 'cards' | 'tasks',
  entityId: number,
  action: string,
  decision: string,
  rationale: string = '',
): Promise<DecisionResponse> {
  return request<DecisionResponse>(`/api/${entityType}/${entityId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, decision, rationale }),
  })
}

export async function fetchChatHistory(entityType: 'cards' | 'tasks', entityId: number): Promise<ChatHistoryResponse> {
  return request<ChatHistoryResponse>(`/api/${entityType}/${entityId}/chat-history`)
}

export async function postRefine(
  entityType: 'cards' | 'tasks',
  entityId: number,
  message: string,
  history: Array<{ role: string; content: string }> = [],
): Promise<RefineResponse> {
  return request<RefineResponse>(`/api/${entityType}/${entityId}/refine`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  })
}

export async function fetchTasks(): Promise<TasksResponse> {
  return request<TasksResponse>('/api/tasks')
}

export async function fetchJiraSprint(refresh = false): Promise<JiraSprint> {
  return request<JiraSprint>(`/api/jira/sprint${refresh ? '?refresh=true' : ''}`)
}

export async function fetchDailyLogs(): Promise<DailyLogsResponse> {
  return request<DailyLogsResponse>('/api/daily/logs')
}

export async function fetchDailyLog(date: string): Promise<DailyLog> {
  return request<DailyLog>(`/api/daily/logs/${date}`)
}

export async function fetchLearningsSummary(range: string, date?: string): Promise<unknown> {
  const params = new URLSearchParams({ range })
  if (date) params.set('date', date)
  return request(`/api/learnings/summary?${params}`)
}

export async function fetchLearningsEvents(range: string, date?: string, limit = 200): Promise<unknown> {
  const params = new URLSearchParams({ range, limit: String(limit) })
  if (date) params.set('date', date)
  return request(`/api/learnings/events?${params}`)
}

export async function fetchKnowledgeIndex(): Promise<KnowledgeIndexResponse> {
  return request<KnowledgeIndexResponse>('/api/knowledge/index')
}

export async function fetchKnowledgeDoc(path: string): Promise<{ content: string }> {
  return request(`/api/knowledge/doc?path=${encodeURIComponent(path)}`)
}

export async function fetchBriefing(): Promise<BriefingResponse> {
  return request<BriefingResponse>('/api/briefing')
}

export async function fetchSuggestions(refresh = false): Promise<CardsResponse> {
  return request<CardsResponse>(`/api/suggestions${refresh ? '?refresh=true' : ''}`)
}

export async function fetchPlaybooks(): Promise<{ playbooks: unknown[] }> {
  return request('/api/playbooks')
}

export async function fetchPlaybookDrafts(): Promise<{ drafts: unknown[] }> {
  return request('/api/playbooks/drafts')
}

export async function executePlaybook(playbookId: string, ticketContext: unknown, approval: string): Promise<unknown> {
  return request('/api/playbooks/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playbook_id: playbookId, ticket_context: ticketContext, approval }),
  })
}

export async function fetchPlan(cardId: number): Promise<PlanResponse> {
  return request<PlanResponse>(`/api/cards/${cardId}/plan`)
}

export async function fetchPollers(): Promise<PollersResponse> {
  return request<PollersResponse>('/api/pollers/status')
}

export async function syncPoller(pollerId: string): Promise<unknown> {
  return request(`/api/pollers/${pollerId}/sync`, { method: 'POST' })
}

export async function postRestart(): Promise<RestartResponse> {
  return request<RestartResponse>('/api/restart', { method: 'POST' })
}

export async function fetchRestartStatus(): Promise<RestartStatusResponse> {
  return request<RestartStatusResponse>('/api/restart-status')
}

export async function postNotify(title: string, message: string): Promise<unknown> {
  return request('/api/notify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, message }),
  })
}

export async function sendDebugToClaude(logLine: string, level: string, tab: string, details?: Record<string, unknown>): Promise<unknown> {
  return request('/api/debug/send-to-claude', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ log_line: logLine, level, tab, timestamp: new Date().toISOString(), details }),
  })
}

export async function openSession(entityType: 'cards' | 'tasks', entityId: number): Promise<OpenSessionResponse> {
  return request<OpenSessionResponse>(`/api/${entityType}/${entityId}/open-session`, { method: 'POST' })
}

export async function gmailAnalyze(cardId: number, includeLabels = true, includeDraft = true): Promise<GmailAnalyzeResponse> {
  return request<GmailAnalyzeResponse>(`/api/cards/${cardId}/gmail-analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ include_labels: includeLabels, include_draft: includeDraft }),
  })
}

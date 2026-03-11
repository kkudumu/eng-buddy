import type {
  CardsResponse,
  CardSource,
  PlanResponse,
  StepUpdateResponse,
  ApproveRemainingResponse,
  ExecuteResponse,
  RegenerateResponse,
  SettingsResponse,
  PollersResponse,
  PlaybookDetail,
  PlaybookHistoryResponse,
  KnowledgeIndexResponse,
  KnowledgeDocResponse,
  LearningsSummaryResponse,
  LearningsEventsResponse,
  ChatHistoryResponse,
  RefineResponse,
  SuggestionsResponse,
  TasksResponse,
  JiraSprintResponse,
  DailyLogsResponse,
  DailyLogResponse,
  BriefingResponse,
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

export async function fetchPlan(cardId: number): Promise<PlanResponse> {
  return request<PlanResponse>(`/api/cards/${cardId}/plan`);
}

export async function updateStep(
  cardId: number,
  stepIndex: number,
  body: { status?: string; draft_content?: string; feedback?: string },
): Promise<StepUpdateResponse> {
  return request<StepUpdateResponse>(`/api/cards/${cardId}/plan/steps/${stepIndex}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function approveRemaining(
  cardId: number,
  fromIndex?: number,
): Promise<ApproveRemainingResponse> {
  return request<ApproveRemainingResponse>(`/api/cards/${cardId}/plan/approve-remaining`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from_index: fromIndex ?? 0 }),
  });
}

export async function executePlan(cardId: number): Promise<ExecuteResponse> {
  return request<ExecuteResponse>(`/api/cards/${cardId}/plan/execute`, { method: 'POST' });
}

export async function regeneratePlan(
  cardId: number,
  feedback: string,
): Promise<RegenerateResponse> {
  return request<RegenerateResponse>(`/api/cards/${cardId}/plan/regenerate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback }),
  });
}

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

export async function fetchPollers(): Promise<PollersResponse> {
  return request('/api/pollers/status')
}

export async function syncPoller(pollerId: string): Promise<{ status: string }> {
  return request(`/api/pollers/${pollerId}/sync`, { method: 'POST' })
}

export async function postRestart(): Promise<{ status: string }> {
  return request('/api/restart', { method: 'POST' })
}

export async function fetchRestartStatus(): Promise<{ phase: string; message: string }> {
  return request('/api/restart-status')
}

export async function postDecision(
  entity: 'cards' | 'tasks',
  id: number,
  action: string,
  decision: string,
  reason?: string,
): Promise<{ card_id?: number; task_number?: number; action: string; decision: string; decision_event_id: number; action_step_id: number }> {
  return request(`/api/${entity}/${id}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, decision, reason }),
  })
}

export async function fetchPlaybooks(): Promise<{ playbooks: Array<{ id: string; name: string; trigger: string; confidence: number; steps: Array<{ summary: string; tool: string }>; executions: number }> }> {
  return request('/api/playbooks')
}

export async function fetchPlaybookDrafts(): Promise<{ drafts: Array<{ id: string; name: string; trigger: string; confidence: number; steps: Array<{ summary: string; tool: string }> }> }> {
  return request('/api/playbooks/drafts')
}

export async function executePlaybook(
  playbookId: string,
  ticketContext: Record<string, unknown>,
  approval: string,
): Promise<{ status: string }> {
  return request('/api/playbooks/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playbook_id: playbookId, ticket_context: ticketContext, approval }),
  })
}

export async function fetchPlaybookDetail(playbookId: string): Promise<PlaybookDetail> {
  return request<PlaybookDetail>(`/api/playbooks/${playbookId}`)
}

export async function updatePlaybookDraft(
  playbookId: string,
  body: Partial<PlaybookDetail>,
): Promise<{ status: string }> {
  return request(`/api/playbooks/drafts/${playbookId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function promotePlaybook(playbookId: string): Promise<{ status: string }> {
  return request(`/api/playbooks/${playbookId}/promote`, { method: 'POST' })
}

export async function deletePlaybookDraft(playbookId: string): Promise<{ status: string }> {
  return request(`/api/playbooks/drafts/${playbookId}`, { method: 'DELETE' })
}

export async function fetchPlaybookHistory(playbookId: string): Promise<PlaybookHistoryResponse> {
  return request<PlaybookHistoryResponse>(`/api/playbooks/${playbookId}/history`)
}

export async function openSession(
  entity: 'cards' | 'tasks',
  id: number,
): Promise<{ status: string }> {
  return request(`/api/${entity}/${id}/open-session`, { method: 'POST' })
}

export async function gmailAnalyze(
  cardId: number,
): Promise<{ suggested_labels: string[]; draft_response: string; reasoning: string }> {
  return request(`/api/cards/${cardId}/gmail-analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
}

export async function fetchKnowledgeIndex(): Promise<KnowledgeIndexResponse> {
  return request<KnowledgeIndexResponse>('/api/knowledge/index')
}

export async function fetchKnowledgeDoc(path: string): Promise<KnowledgeDocResponse> {
  return request<KnowledgeDocResponse>(`/api/knowledge/doc?path=${encodeURIComponent(path)}`)
}

export async function fetchLearningsSummary(range: string, date: string): Promise<LearningsSummaryResponse> {
  return request<LearningsSummaryResponse>(`/api/learnings/summary?range=${encodeURIComponent(range)}&date=${encodeURIComponent(date)}`)
}

export async function fetchLearningsEvents(range: string, date: string): Promise<LearningsEventsResponse> {
  return request<LearningsEventsResponse>(`/api/learnings/events?range=${encodeURIComponent(range)}&date=${encodeURIComponent(date)}`)
}

export async function fetchChatHistory(
  entity: 'cards' | 'tasks',
  id: number,
): Promise<ChatHistoryResponse> {
  return request<ChatHistoryResponse>(`/api/${entity}/${id}/chat-history`)
}

export async function postRefine(
  entity: 'cards' | 'tasks',
  id: number,
  message: string,
  history: Array<{ role: string; content: string }>,
): Promise<RefineResponse> {
  return request<RefineResponse>(`/api/${entity}/${id}/refine`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  })
}

export async function fetchSuggestions(refresh?: boolean): Promise<SuggestionsResponse> {
  const param = refresh ? '?refresh=true' : ''
  const data = await request<SuggestionsResponse>(`/api/suggestions${param}`)
  // Flatten sections into a convenience `cards` array expected by SuggestionsView
  const allCards = (data.sections ?? []).flatMap((s) => s.cards ?? []).concat(data.held ?? [])
  return { ...data, cards: allCards }
}

export async function fetchTasks(): Promise<TasksResponse> {
  return request<TasksResponse>('/api/tasks')
}

export async function fetchJiraSprint(refresh?: boolean): Promise<JiraSprintResponse> {
  const param = refresh ? '?refresh=true' : ''
  return request<JiraSprintResponse>(`/api/jira/sprint${param}`)
}

export async function fetchDailyLogs(): Promise<DailyLogsResponse> {
  return request<DailyLogsResponse>('/api/daily/logs')
}

export async function fetchDailyLog(day: string): Promise<DailyLogResponse> {
  return request<DailyLogResponse>(`/api/daily/logs/${encodeURIComponent(day)}`)
}

export async function fetchBriefing(): Promise<BriefingResponse> {
  return request<BriefingResponse>('/api/briefing')
}

export async function sendDebugToClaude(
  logLine: string,
  level: string,
  tab: string,
  details?: Record<string, unknown>,
): Promise<{ queued: boolean; message: string }> {
  return request('/api/debug/send-to-claude', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ log_line: logLine, level, tab, details }),
  })
}

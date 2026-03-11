import type {
  CardsResponse,
  InboxViewResponse,
  CardSource,
  PlanResponse,
  StepUpdateResponse,
  ApproveRemainingResponse,
  ExecuteResponse,
  RegenerateResponse,
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

import type { CardsResponse, InboxViewResponse, CardSource } from './types'

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

export interface Card {
  id: number
  source: string
  classification: string
  status: 'pending' | 'held' | 'approved' | 'completed' | 'failed'
  section: string
  summary: string
  context_notes: string
  timestamp: string
  proposed_actions: Action[]
  draft_response?: string
  analysis_metadata?: Record<string, unknown>
}

export interface Action {
  type: string
  draft: string
  [key: string]: unknown
}

export interface CardCounts {
  pending: number
  held: number
  approved: number
  completed: number
  failed: number
}

export interface CardsResponse {
  cards: Card[]
  counts: CardCounts
}

export interface InboxViewResponse {
  needs_action: Card[]
  no_action: Card[]
}

export interface Poller {
  id: string
  label: string
  next_run_at: string
  last_run_at: string
  health: string
  interval_seconds: number
}

export interface PollersResponse {
  pollers: Poller[]
  generated_at: string
}

export interface StatsResponse {
  pending: number
  held: number
  approved: number
  completed: number
  failed: number
}

export type CardSource = 'all' | 'tasks' | 'freshservice' | 'jira' | 'slack' | 'gmail' | 'calendar'

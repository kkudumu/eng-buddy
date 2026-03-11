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

export interface SettingsResponse {
  terminal: string
  macos_notifications: boolean
  theme: string
  mode: string
}

export interface DecisionResponse {
  card_id?: number
  task_number?: number
  action: string
  decision: string
  decision_event_id: number
  action_step_id: number
}

export interface CloseResponse {
  card_id?: number
  task_number?: number
  status: string
  daily_file: string
  entry: string
  inserted: boolean
  decision_event_id: number
  action_step_id: number
}

export interface JiraWriteResponse {
  card_id?: number
  task_number?: number
  issue_key: string
  output: unknown
  decision_event_id: number
  action_step_id: number
}

export interface SendDraftResponse {
  status: string
  output: string
  decision_event_id: number
  action_step_id: number
}

export interface GmailAnalyzeResponse {
  card_id: number
  detected_category: string
  suggested_labels: string[]
  reasoning: string
  draft_response: string
}

export interface RefineResponse {
  response: string
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface ChatHistoryResponse {
  card_id?: number
  task_number?: number
  messages: ChatMessage[]
}

export interface Task {
  number: number
  title: string
  status: string
  priority: string
  description: string
  jira_keys?: string[]
  related_card_ids?: number[]
}

export interface TasksResponse {
  tasks: Task[]
}

export interface JiraSprint {
  issues: JiraIssue[]
}

export interface JiraIssue {
  key: string
  summary: string
  status: string
  assignee: string
  priority: string
}

export interface DailyLog {
  date: string
  content: string
  stats?: Record<string, unknown>
}

export interface DailyLogsResponse {
  logs: string[]
}

export interface KnowledgeDoc {
  path: string
  group: string
  name: string
}

export interface KnowledgeIndexResponse {
  documents: KnowledgeDoc[]
}

export interface BriefingResponse {
  cognitive_load: string
  meetings: Array<{ time: string; title: string; hangout_link?: string; prep_notes?: string }>
  needs_response: Array<{ summary: string; source: string; has_draft: boolean }>
  alerts: Array<{ type: string; message: string }>
  stats: { drafts_sent: number; triaged: number; time_saved_minutes: number }
  pep_talk: string
}

export interface SuggestionCard extends Card {
  suggestion_prompt?: string
}

export interface PlanStep {
  index: number
  summary: string
  status: string
  tool: string
  params: Record<string, unknown>
  draft_content?: string
}

export interface PlanPhase {
  name: string
  steps: PlanStep[]
}

export interface PlanResponse {
  plan: {
    card_id: number
    status: string
    phases: PlanPhase[]
  }
}

export interface PlaybookDraft {
  id: string
  name: string
  trigger: string
  confidence: number
  steps: Array<{ summary: string; tool: string }>
}

export interface Playbook extends PlaybookDraft {
  executions: number
}

export interface RestartResponse {
  status: string
  mode: string
  manager: string
}

export interface RestartStatusResponse {
  phase: string
  message: string
  updated_at: string | null
}

export interface OpenSessionResponse {
  status: string
  terminal: string
  launcher: string
  chat_session_id: number
}

export type TabRoute = 'inbox' | 'tasks' | 'jira' | 'calendar' | 'daily' | 'learnings' | 'knowledge' | 'suggestions' | 'playbooks'

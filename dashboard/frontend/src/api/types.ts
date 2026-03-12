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

export type StepStatus = 'pending' | 'approved' | 'edited' | 'skipped' | 'completed' | 'failed';
export type StepRisk = 'low' | 'medium' | 'high';
export type PlanStatus = 'pending' | 'executing' | 'completed';

export interface PlanStep {
  index: number;
  summary: string;
  detail: string;
  action_type: 'mcp' | 'manual' | 'browser';
  tool: string;
  params: Record<string, unknown>;
  param_sources: Record<string, string>;
  draft_content: string | null;
  risk: StepRisk;
  status: StepStatus;
  output: string | null;
}

export interface PlanPhase {
  name: string;
  steps: PlanStep[];
}

export interface Plan {
  id: string;
  card_id: number;
  source: string;
  playbook_id: string;
  confidence: number;
  status: PlanStatus;
  created_at: string;
  executed_at: string | null;
  phases: PlanPhase[];
}

export interface PlanResponse {
  plan: Plan;
}

export interface GeneratePlanResponse {
  plan: Plan;
  generated: boolean;
}

export interface StepUpdateResponse {
  step: PlanStep;
}

export interface ApproveRemainingResponse {
  approved_count: number;
  plan: Plan;
}

export interface ExecuteResponse {
  status: 'dispatched';
  steps: number;
  skipped: number[];
}

export interface RegenerateResponse {
  status: 'generated';
  feedback: string;
  plan: Plan;
}

export interface SettingsResponse {
  terminal: string
  macos_notifications: boolean
  theme: string
  mode: string
}

export interface PlaybookStepDetail {
  number: number
  description: string
  tool: string
  tool_params: Record<string, unknown>
  requires_human: boolean
  notes: string
}

export interface PlaybookDetail {
  id: string
  name: string
  description: string
  trigger_keywords: string[]
  steps: PlaybookStepDetail[]
  confidence: number
  version: number
  executions: number
  source: string
  runbook_path: string
  related_links: Record<string, string>
}

export interface PlaybookRunStep {
  number: number
  description: string
  tool: string
  status: 'success' | 'failed' | 'skipped'
  output: string | null
  duration_ms: number | null
}

export interface PlaybookRun {
  id: string
  playbook_id: string
  started_at: string
  finished_at: string | null
  status: 'success' | 'failed' | 'partial' | 'running'
  steps: PlaybookRunStep[]
}

export interface PlaybookHistoryResponse {
  runs: PlaybookRun[]
}

// Knowledge
export interface KnowledgeDocument {
  group: string
  name: string
  path: string
  size: number
  modified_at: string
}

export interface KnowledgeIndexResponse {
  documents: KnowledgeDocument[]
  count: number
}

export interface KnowledgeDocResponse {
  path: string
  absolute_path: string
  name: string
  is_markdown: boolean
  content: string
  size: number
  modified_at: string
}

// Learnings
export interface LearningsSummaryResponse {
  range: string
  anchor_date: string
  window_start: string
  window_end_exclusive: string
  by_bucket: Record<string, { captured: number; needs_category_expansion: number; total: number }>
  top_titles: Array<{ title: string; count: number }>
  pending_category_expansions: Array<{ category: string; count: number }>
}

export interface LearningsEvent {
  id: number
  session_id: number | null
  hook_event: string
  source: string
  scope: string
  tool_name: string
  category: string
  title: string
  note: string
  status: string
  requires_category_expansion: number
  proposed_category: string
  created_at: string
}

export interface LearningsEventsResponse {
  range: string
  anchor_date: string
  events: LearningsEvent[]
}

// Chat / Refine
export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface ChatHistoryResponse {
  messages: ChatMessage[]
}

export interface RefineResponse {
  response: string
}

// Suggestions
export interface SuggestionSection {
  key: string
  label: string
  cards: Card[]
  count: number
}

export interface SuggestionsResponse {
  source: string
  sections: SuggestionSection[]
  held: Card[]
  held_count: number
  last_analyzed_at: string | null
  refresh_result: unknown
  // convenience flat list assembled by client
  cards?: Card[]
}

// Tasks
export interface Task {
  number: number
  title: string
  status: string
  priority: string
  description: string
  jira_keys: string[]
  related_cards: unknown[]
  [key: string]: unknown
}

export interface TasksResponse {
  tasks: Task[]
  count: number
  file: string
}

// Jira Sprint
export interface JiraIssue {
  key: string
  summary: string
  status: string
  status_category: string
  assignee: string
  priority: string
  [key: string]: unknown
}

export interface JiraSprintResponse {
  issues: JiraIssue[]
  board: { todo: JiraIssue[]; in_progress: JiraIssue[]; done: JiraIssue[] }
  by_status: Record<string, JiraIssue[]>
  status_order: string[]
  total: number
}

// Daily Log
export interface DailyLogEntry {
  date: string
  name: string
  path: string
  size: number
  modified_at: string
}

export interface DailyLogsResponse {
  logs: string[]
  count: number
}

export interface DailyLogResponse {
  date: string
  file: string
  content: string
  sections: Array<{ heading: string; content: string }>
  stats: Record<string, number>
}

// Briefing
export interface BriefingMeeting {
  time: string
  title: string
  prep?: string
  hangout_link?: string
}

export interface BriefingNeedsResponse {
  source: string
  summary: string
  age: string
  has_draft: boolean
}

export interface BriefingAlert {
  type: string
  message: string
}

export interface BriefingStats {
  drafts_sent: number
  triaged: number
  time_saved_minutes: number
}

export interface BriefingResponse {
  date: string
  meetings: BriefingMeeting[]
  needs_response: BriefingNeedsResponse[]
  alerts: BriefingAlert[]
  cognitive_load: string
  stats: BriefingStats
  pep_talk?: string
}

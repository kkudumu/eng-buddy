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
  status: 'queued';
  feedback: string;
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

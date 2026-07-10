export type SourceType = 'creator' | 'keyword'

export interface SourceBrief {
  id: number
  type: SourceType
  platform: string
  identifier: string
  display_name: string
  enabled: boolean
  interval_hours: number | null
  last_check: string | null
  last_error: string | null
  directory: string
}

export interface Group {
  id: number
  name: string
  slug: string
  description: string
  enabled: boolean
  defaults: Record<string, any>
  prompt_overrides: Record<string, any>
  source_count: number
  created_at: string
  updated_at: string
}

export interface GroupSummary extends Group {
  recent_content_count: number
  recent_signal_count: number
  recent_new_signal_count: number
  failed_source_count: number
  window_days: number
}

export interface GroupDetail extends Group {
  sources: SourceBrief[]
}

export type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'canceled'
export type TaskKind = 'ingest' | 'ingest_target' | 'research' | 'transcribe_backfill'

export interface Task {
  id: string
  kind: TaskKind | string
  status: TaskStatus | string
  group_id: number | null
  source_id: number | null
  params: Record<string, any>
  progress: Record<string, any>
  logs: { ts: string; level: string; message: string }[]
  result: Record<string, any>
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface ReportBrief {
  id: number
  group_id: number | null
  task_id: string | null
  kind: string
  title: string
  summary: string
  created_at: string
}

export interface ReportDetail extends ReportBrief {
  content_md: string
  content_md_path: string
  content_json_path: string | null
  sources_used: any[]
}

export interface ConfigValues {
  [key: string]: any
}

export interface ConfigSchema {
  [key: string]: {
    type: 'int' | 'float' | 'bool' | 'string' | 'secret'
    label: string
    min?: number
    max?: number
    presets?: Record<string, string>
  }
}

export interface ConfigResp {
  values: ConfigValues
  schema: ConfigSchema
}

export interface SchedulerJob {
  id: string
  name: string
  next_run: string | null
}

export interface Signal {
  id: number
  global_content_id?: number | null
  group_id: number | null
  source_id: number
  content_id: string
  is_new: boolean
  summary: string
  matched_points: string[]
  new_points: string[]
  created_at: string
  source_name?: string
  platform?: string
  url?: string
  title?: string
  group_name?: string
}

export interface AdminStats {
  users: number
  active_users: number
  groups: number
  enabled_groups: number
  sources: number
  active_sources: number
  failed_sources: number
  ingest_targets: number
  active_targets: number
  targets_with_error: number
  global_content: number
  group_content: number
  recent_content_7d: number
  signals: number
  new_signals: number
  reports: number
  tasks: number
  running_tasks: number
  failed_tasks: number
  llm_actual_tokens_30d: number
  llm_allocated_tokens_30d: number
  llm_missing_events_30d: number
}

export interface AdminUserRow {
  id: number
  phone: string
  nickname: string
  role: string
  plan: string
  expires_at: string | null
  group_count: number
  source_count: number
  active_source_count: number
  failed_source_count: number
  content_count: number
  signal_count: number
  new_signal_count: number
  report_count: number
  task_count: number
  last_activity_at: string | null
  created_at: string
}

export interface AdminTargetRow {
  id: number
  platform: string
  kind: string
  target_key: string
  enabled: boolean
  admin_paused: boolean
  subscriber_count: number
  group_count: number
  interval_hours: number
  days: number
  content_limit: number
  comment_top_n: number
  last_check: string | null
  last_error: string | null
  running_task_id: string | null
  locked_at: string | null
  updated_at: string | null
}

export interface AdminTaskRow {
  id: string
  kind: string
  status: string
  group_id: number | null
  group_name: string
  source_id: number | null
  source_name: string
  owner_phone: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface AdminUsageOperationRow {
  operation: string
  model: string
  call_count: number
  actual_prompt_tokens: number
  actual_completion_tokens: number
  actual_total_tokens: number
  cached_tokens: number
  reasoning_tokens: number
  missing_events: number
  failed_events: number
}

export interface AdminUsageUserRow {
  user_id: number | null
  phone: string
  nickname: string
  allocated_total_tokens: number
  allocated_estimated_tokens: number
  call_count: number
  group_count: number
  source_count: number
}

export interface AdminUsageCreatorRow {
  creator_id: number | null
  creator_name: string
  actual_total_tokens: number
  allocated_total_tokens: number
  allocated_estimated_tokens: number
  call_count: number
  user_count: number
}

export interface AdminUsageSummary {
  actual_total_tokens_7d: number
  actual_total_tokens_30d: number
  allocated_total_tokens_30d: number
  allocated_estimated_tokens_30d: number
  missing_events_30d: number
  failed_events_30d: number
  by_operation: AdminUsageOperationRow[]
  by_user: AdminUsageUserRow[]
  by_creator: AdminUsageCreatorRow[]
}

export interface AdminOverview {
  generated_at: string
  stats: AdminStats
  users: AdminUserRow[]
  targets: AdminTargetRow[]
  tasks: AdminTaskRow[]
  usage: AdminUsageSummary
}

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

export interface GroupDetail extends Group {
  sources: SourceBrief[]
}

export type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'canceled'
export type TaskKind = 'ingest' | 'research' | 'transcribe_backfill'

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

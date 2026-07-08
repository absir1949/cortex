import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export interface SourceDetail {
  source_id: number
  creator_id: number | null
  name: string
  slug: string | null
  bio: string
  platform: string
  identifier: string
  display_name: string
  enabled: boolean
  last_check: string | null
  last_error: string | null
  aliases: { platform: string; platform_uid: string; display_name: string }[]
}

export interface SourceSummary {
  id: number
  type: 'creator' | 'keyword'
  platform: string
  identifier: string
  display_name: string
  enabled: boolean
  interval_hours: number | null
  last_check: string | null
  last_error: string | null
  directory: string
  recent_content_count: number
  recent_signal_count: number
  recent_new_signal_count: number
  window_days: number
}

export interface SourceContent {
  content_id: string
  title: string
  url: string
  create_time: string
  platform: string
  statistics: Record<string, number>
  transcribed: boolean
  is_new_signal: boolean | null
  signal_summary: string
}

export interface SourceSignal {
  id: number
  content_id: string
  is_new: boolean
  summary: string
  new_points: string[]
  matched_points: string[]
  created_at: string
}

export const useSourceDetail = (groupId: number | null | undefined, sourceId: number | null | undefined) =>
  useQuery({
    queryKey: ['source', groupId, sourceId],
    queryFn: () => api.get<SourceDetail>(`/groups/${groupId}/sources/${sourceId}`),
    enabled: !!groupId && !!sourceId,
  })

export const useGroupSourceSummaries = (groupId: number | null | undefined, days = 7) =>
  useQuery({
    queryKey: ['source-summaries', groupId, days],
    queryFn: () => api.get<SourceSummary[]>(`/groups/${groupId}/sources/summary?days=${days}`),
    enabled: !!groupId,
  })

export const useSourceContents = (groupId: number | null | undefined, sourceId: number | null | undefined, limit = 20, offset = 0) =>
  useQuery({
    queryKey: ['source-contents', groupId, sourceId, limit, offset],
    queryFn: () => api.get<{ items: SourceContent[]; total: number }>(`/groups/${groupId}/sources/${sourceId}/contents?limit=${limit}&offset=${offset}`),
    enabled: !!groupId && !!sourceId,
  })

export const useSourceSignals = (groupId: number | null | undefined, sourceId: number | null | undefined, limit = 50) =>
  useQuery({
    queryKey: ['source-signals', groupId, sourceId, limit],
    queryFn: () => api.get<SourceSignal[]>(`/groups/${groupId}/sources/${sourceId}/signals?limit=${limit}`),
    enabled: !!groupId && !!sourceId,
  })

export const useSourceProfile = (groupId: number | null | undefined, sourceId: number | null | undefined) =>
  useQuery({
    queryKey: ['source-profile', groupId, sourceId],
    queryFn: () => api.get<string>(`/groups/${groupId}/sources/${sourceId}/profile`),
    enabled: !!groupId && !!sourceId,
  })

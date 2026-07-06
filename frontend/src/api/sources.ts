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

export const useSourceContents = (groupId: number | null | undefined, sourceId: number | null | undefined, limit = 50) =>
  useQuery({
    queryKey: ['source-contents', groupId, sourceId, limit],
    queryFn: () => api.get<{ items: SourceContent[]; total: number }>(`/groups/${groupId}/sources/${sourceId}/contents?limit=${limit}`),
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

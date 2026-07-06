import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { Signal } from './types'

export const useRecentSignals = (limit = 20) =>
  useQuery({
    queryKey: ['signals', 'recent'],
    queryFn: () => api.get<Signal[]>(`/signals/recent?limit=${limit}`),
  })

export const useRecentNewSignals = (limit = 10) =>
  useQuery({
    queryKey: ['signals', 'recent', 'new'],
    queryFn: () => api.get<Signal[]>(`/signals/recent?is_new=true&limit=${limit}`),
  })

export const useGroupSignals = (groupId: number, isNew?: boolean) =>
  useQuery({
    queryKey: ['signals', 'group', groupId, isNew],
    queryFn: () => {
      const q = isNew === undefined ? '' : `&is_new=${isNew}`
      return api.get<Signal[]>(`/groups/${groupId}/signals?limit=100${q}`)
    },
    enabled: !!groupId,
  })

export const useSourceProfile = (groupId: number | null | undefined, sourceId: number | null | undefined) =>
  useQuery({
    queryKey: ['profile', groupId, sourceId],
    queryFn: () =>
      api.get<string>(`/groups/${groupId}/profile/${sourceId}`),
    enabled: !!groupId && !!sourceId,
  })

export interface Trend {
  trend: string
  source_names: string[]
  signal_count: number
  momentum: string
  why_hot: string
}

export interface InsightResult {
  trends: Trend[]
  raw_signal_count: number
  days: number
}

export const useGroupInsights = (groupId: number | null | undefined, days = 14) =>
  useQuery({
    queryKey: ['insights', groupId, days],
    queryFn: () => api.get<InsightResult | null>(`/groups/${groupId}/insights?days=${days}`),
    enabled: !!groupId,
  })

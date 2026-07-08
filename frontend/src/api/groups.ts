import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Group, GroupSummary, GroupDetail, SourceBrief } from './types'

export const useGroups = () =>
  useQuery({ queryKey: ['groups'], queryFn: () => api.get<Group[]>('/groups') })

export const useGroupSummaries = (days = 7) =>
  useQuery({
    queryKey: ['groups', 'summary', days],
    queryFn: () => api.get<GroupSummary[]>(`/groups/summary?days=${days}`),
  })

export const useGroup = (id: number | null | undefined) =>
  useQuery({
    queryKey: ['group', id],
    queryFn: () => api.get<GroupDetail>(`/groups/${id}`),
    enabled: !!id,
  })

export const useCreateGroup = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; slug?: string; description?: string; defaults?: Record<string, any> }) =>
      api.post<Group>('/groups', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['groups'] }),
  })
}

export const useUpdateGroup = (id: number) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<Group>) => api.patch<Group>(`/groups/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['groups'] })
      qc.invalidateQueries({ queryKey: ['group', id] })
      qc.invalidateQueries({ queryKey: ['scheduler', 'jobs'] })
    },
  })
}

export const useDeleteGroup = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, cascade }: { id: number; cascade?: boolean }) =>
      api.delete(`/groups/${id}${cascade ? '?cascade=true' : ''}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['groups'] }),
  })
}

export const useCreateSource = (groupId: number) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      type: 'creator' | 'keyword'
      platform: string
      identifier: string
      display_name?: string
      interval_hours?: number
      days?: number
      content_limit?: number
      comment_top_n?: number
    }) => api.post<SourceBrief>(`/groups/${groupId}/sources`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['group', groupId] }),
  })
}

export const useDeleteSource = (groupId: number) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sourceId: number) =>
      api.delete(`/groups/${groupId}/sources/${sourceId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['group', groupId] }),
  })
}

export const useUpdateSource = (groupId: number) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      sourceId: number
      display_name?: string
      enabled?: boolean
      interval_hours?: number
      days?: number
      content_limit?: number
      comment_top_n?: number
    }) => api.patch<SourceBrief>(`/groups/${groupId}/sources/${body.sourceId}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['group', groupId] }),
  })
}

export const useRunSource = (groupId: number) =>
  useMutation({
    mutationFn: (args: { sourceId: number; force?: boolean; days?: number }) => {
      const qs = new URLSearchParams()
      qs.set('force', String(args.force ?? true))
      if (args.days) qs.set('days', String(args.days))
      return api.post<{ task_id: string }>(`/groups/${groupId}/sources/${args.sourceId}/run?${qs.toString()}`)
    },
  })

export const useRunGroup = (groupId: number) =>
  useMutation({
    mutationFn: (opts: { force?: boolean; analyze?: boolean } = {}) => {
      const qs = new URLSearchParams()
      qs.set('force', String(opts.force ?? true))
      qs.set('analyze', String(opts.analyze ?? true))
      return api.post<{ task_id: string }>(`/groups/${groupId}/run?${qs.toString()}`)
    },
  })

export const useAnalyzeGroup = (groupId: number) =>
  useMutation({
    mutationFn: () =>
      api.post<{ task_id: string }>(`/groups/${groupId}/analyze`),
  })

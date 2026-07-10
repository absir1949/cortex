import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { AdminOverview, AdminTargetRow, AdminUserRow } from './types'

export const useAdminOverview = (options?: { enabled?: boolean; refetchInterval?: number | false }) =>
  useQuery({
    queryKey: ['admin', 'overview'],
    queryFn: () => api.get<AdminOverview>('/admin/overview'),
    enabled: options?.enabled ?? true,
    refetchInterval: options?.refetchInterval ?? 15000,
  })

export const useUpdateAdminUser = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      id: number
      nickname?: string
      role?: string
      plan?: string
      expires_at?: string | null
    }) => {
      const { id, ...body } = payload
      return api.patch<AdminUserRow>(`/admin/users/${id}`, body)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'overview'] }),
  })
}

export const useClearTargetError = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (targetId: number) => api.post<AdminTargetRow>(`/admin/targets/${targetId}/clear-error`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'overview'] }),
  })
}

export const useUpdateAdminTarget = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { id: number; enabled: boolean }) =>
      api.patch<AdminTargetRow>(`/admin/targets/${payload.id}`, { enabled: payload.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'overview'] }),
  })
}

export const useRunAdminTarget = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (targetId: number) => api.post<{ ok: boolean; task_id?: string }>(`/admin/targets/${targetId}/run`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'overview'] })
      qc.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export const useRetryAdminTask = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) => api.post<{ ok: boolean; task_id?: string }>(`/admin/tasks/${taskId}/retry`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'overview'] })
      qc.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

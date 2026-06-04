import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { Task } from './types'

export const useTask = (id: string | null | undefined) =>
  useQuery({
    queryKey: ['task', id],
    queryFn: () => api.get<Task>(`/tasks/${id}`),
    enabled: !!id,
    refetchInterval: (q) => {
      const t = q.state.data
      if (!t || t.status === 'pending' || t.status === 'running') return 3000
      return false
    },
  })

export const useTasks = (filters: { kind?: string; status?: string; limit?: number } = {}) =>
  useQuery({
    queryKey: ['tasks', filters],
    queryFn: () => {
      const qs = new URLSearchParams()
      if (filters.kind) qs.set('kind', filters.kind)
      if (filters.status) qs.set('status', filters.status)
      if (filters.limit) qs.set('limit', String(filters.limit))
      return api.get<Task[]>(`/tasks?${qs.toString()}`)
    },
    refetchInterval: 5000,
  })

export const useCancelTask = () =>
  useMutation({ mutationFn: (id: string) => api.post(`/tasks/${id}/cancel`) })

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { SchedulerJob } from './types'

export const useSchedulerJobs = () =>
  useQuery({
    queryKey: ['scheduler', 'jobs'],
    queryFn: () => api.get<SchedulerJob[]>('/scheduler/jobs'),
  })

export const useReloadScheduler = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean; jobs: SchedulerJob[] }>('/scheduler/reload'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scheduler', 'jobs'] }),
  })
}

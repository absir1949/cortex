import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { ReportBrief, ReportDetail } from './types'

export const useGroupReports = (groupId: number, limit = 20) =>
  useQuery({
    queryKey: ['reports', 'group', groupId],
    queryFn: () => api.get<ReportBrief[]>(`/groups/${groupId}/reports?limit=${limit}`),
    enabled: !!groupId,
  })

export const useRecentReports = (limit = 10) =>
  useQuery({
    queryKey: ['reports', 'recent'],
    queryFn: () => api.get<ReportBrief[]>(`/reports/recent?limit=${limit}`),
  })

export const useReport = (id: number | null | undefined) =>
  useQuery({
    queryKey: ['report', id],
    queryFn: () => api.get<ReportDetail>(`/reports/${id}`),
    enabled: !!id,
  })

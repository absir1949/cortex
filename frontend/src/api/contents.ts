import { useQuery } from '@tanstack/react-query'
import { api } from './client'

/** 按 content_id 拿转录原文（hover 时触发，按 content_id 缓存）*/
export const useTranscript = (contentId: string | null | undefined, enabled = false) =>
  useQuery({
    queryKey: ['transcript', contentId],
    queryFn: () => api.get<string>(`/contents/${contentId}/transcript`),
    enabled: !!contentId && enabled,
    staleTime: Infinity,  // 转录不变，永久缓存
  })

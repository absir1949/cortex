import { useMutation } from '@tanstack/react-query'
import { api } from './client'

export const useCreateResearch = (groupId: number) =>
  useMutation({
    mutationFn: (body: {
      question: string
      platforms?: string[]
      days?: number
      search_limit?: number
      comment_top_n?: number
    }) => api.post<{ task_id: string }>(`/groups/${groupId}/research`, body),
  })

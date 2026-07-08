import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface AskEvidence {
  content_id: string
  source_id: number
  author: string
  title: string
  url: string
  create_time: string
  signal_summary: string
  new_points: string[]
  snippet: string
}

export interface AskMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  evidence: AskEvidence[]
  created_at: string
}

export interface AskConversationBrief {
  id: number
  group_id: number
  title: string
  latest_answer: string
  evidence_count: number
  message_count: number
  created_at: string
  updated_at: string
}

export interface AskConversationDetail {
  id: number
  group_id: number
  title: string
  messages: AskMessage[]
  created_at: string
  updated_at: string
}

export const useAskConversations = (groupId: number | null | undefined) =>
  useQuery({
    queryKey: ['ask-conversations', groupId],
    queryFn: () => api.get<AskConversationBrief[]>(`/groups/${groupId}/ask/conversations`),
    enabled: !!groupId,
  })

export const useAskConversation = (
  groupId: number | null | undefined,
  conversationId: number | null | undefined,
) =>
  useQuery({
    queryKey: ['ask-conversation', groupId, conversationId],
    queryFn: () => api.get<AskConversationDetail>(`/groups/${groupId}/ask/conversations/${conversationId}`),
    enabled: !!groupId && !!conversationId,
  })

export const useCreateAskConversation = (groupId: number) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { question: string; days?: number; limit?: number }) =>
      api.post<AskConversationDetail>(`/groups/${groupId}/ask/conversations`, body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['ask-conversations', groupId] })
      qc.setQueryData(['ask-conversation', groupId, data.id], data)
    },
  })
}

export const useContinueAskConversation = (groupId: number, conversationId: number | null | undefined) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { question: string; days?: number; limit?: number }) =>
      api.post<AskConversationDetail>(`/groups/${groupId}/ask/conversations/${conversationId}/messages`, body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['ask-conversations', groupId] })
      qc.setQueryData(['ask-conversation', groupId, data.id], data)
    },
  })
}

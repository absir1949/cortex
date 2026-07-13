import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface AskEvidence {
  kind?: 'content' | 'external_search_task' | string
  task_id?: string | null
  status?: string
  content_id: string
  global_content_id?: number | null
  platform?: string
  source_id?: number | null
  author: string
  title: string
  url: string
  create_time: string
  signal_summary: string
  new_points: string[]
  snippet: string
}

export interface AskRequest {
  question: string
  use_internal?: boolean
  use_external?: boolean
  days?: number
  limit?: number
  platforms?: string[]
  external_days?: number
  external_limit?: number
  comment_top_n?: number
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
    refetchInterval: (query) => {
      const data = query.state.data
      const running = data?.messages.some((msg) =>
        msg.evidence.some((ev) => ev.kind === 'external_search_task' && ev.status === 'running'),
      )
      return running ? 3000 : false
    },
  })

export const useCreateAskConversation = (groupId: number) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AskRequest) =>
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
    mutationFn: (body: AskRequest) =>
      api.post<AskConversationDetail>(`/groups/${groupId}/ask/conversations/${conversationId}/messages`, body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['ask-conversations', groupId] })
      qc.setQueryData(['ask-conversation', groupId, data.id], data)
    },
  })
}

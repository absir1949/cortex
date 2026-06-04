import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ConfigResp } from './types'

export const useConfig = () =>
  useQuery({ queryKey: ['config'], queryFn: () => api.get<ConfigResp>('/config') })

export const useUpdateConfig = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (values: Record<string, any>) =>
      api.patch<ConfigResp>('/config', { values }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['config'] }),
  })
}

export const usePrompts = () =>
  useQuery({
    queryKey: ['prompts'],
    queryFn: () => api.get<Record<string, string>>('/config/prompts'),
  })

export const useUpdatePrompt = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, content }: { name: string; content: string }) =>
      api.patch(`/config/prompts/${name}`, { content }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['prompts'] }),
  })
}

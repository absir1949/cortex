import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export interface PlatformMeta {
  id: string
  label: string
  identifier_hint: string
  capabilities: string[]
}

export const usePlatforms = () =>
  useQuery({
    queryKey: ['platforms'],
    queryFn: () => api.get<PlatformMeta[]>('/platforms'),
    staleTime: Infinity,
  })

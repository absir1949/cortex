import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, clearAuthToken, setAuthToken } from './client'

export interface AuthUser {
  id: number
  phone: string
  nickname: string
  role: 'user' | 'admin' | string
  plan: string
  expires_at: string | null
}

export interface AuthResponse {
  token: string
  user: AuthUser
}

export interface AuthPayload {
  phone: string
  code: string
  invite_code?: string
}

export const useMe = (enabled = true) =>
  useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<AuthUser>('/me'),
    enabled,
    retry: false,
  })

export const useSendCode = () =>
  useMutation({
    mutationFn: (phone: string) => api.post<{ ok: boolean; message: string }>('/auth/code', { phone }),
  })

export const useLogin = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: AuthPayload) => api.post<AuthResponse>('/auth/login', payload),
    onSuccess: (data) => {
      setAuthToken(data.token)
      qc.setQueryData(['me'], data.user)
    },
  })
}

export const useRegister = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: AuthPayload) => api.post<AuthResponse>('/auth/register', payload),
    onSuccess: (data) => {
      setAuthToken(data.token)
      qc.setQueryData(['me'], data.user)
    },
  })
}

export function logout(queryClient?: ReturnType<typeof useQueryClient>) {
  clearAuthToken()
  queryClient?.removeQueries()
}

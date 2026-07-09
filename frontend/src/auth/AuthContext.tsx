import { createContext, ReactNode, useContext, useEffect, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getAuthToken, clearAuthToken } from '../api/client'
import { AuthUser, useMe } from '../api/auth'

interface AuthContextValue {
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean
  isAdmin: boolean
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const hasToken = !!getAuthToken()
  const me = useMe(hasToken)

  useEffect(() => {
    const onExpired = () => {
      qc.removeQueries()
    }
    window.addEventListener('cortex-auth-expired', onExpired)
    return () => window.removeEventListener('cortex-auth-expired', onExpired)
  }, [qc])

  const value = useMemo<AuthContextValue>(() => {
    const user = me.data ?? null
    return {
      user,
      isAuthenticated: !!user && !!getAuthToken(),
      isLoading: hasToken && me.isLoading,
      isAdmin: user?.role === 'admin',
      logout: () => {
        clearAuthToken()
        qc.removeQueries()
        window.location.assign('/login')
      },
    }
  }, [hasToken, me.data, me.isLoading, qc])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

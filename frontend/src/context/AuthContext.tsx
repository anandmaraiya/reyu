/**
 * AuthContext — global auth state + lazy gate system.
 *
 * Lazy-gate philosophy:
 *   • Anonymous users get full UI access — features just work until they hit a gate.
 *   • When the backend returns 401/402, we catch it in the axios interceptor,
 *     fire openGate(), and the GateModal appears.
 *   • After auth/upgrade, the original action is retried automatically.
 *   • No page redirect. No forced login wall.
 */
import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import axios from 'axios'

// ─── Types ────────────────────────────────────────────────────────────────────

export type Tier = 'anonymous' | 'free' | 'pro' | 'algo'

export interface AuthUser {
  id: string
  email: string
  display_name: string
  tier: Tier
  trial_expires_at: string | null
  strategy_count: number
  backtest_count: number
  onboarded_at: string | null
  trader_type: 'RETAIL' | 'HNI' | null
}

export type GateMode = 'login' | 'signup' | 'upgrade' | 'limit' | 'trial' | null

interface GatePayload {
  mode: GateMode
  message?: string
  /** After successful gate, retry this callback */
  onSuccess?: () => void
}

interface AuthContextValue {
  user: AuthUser | null
  tier: Tier
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string) => Promise<void>
  logout: () => void
  /** Open the gate modal with a specific mode */
  openGate: (payload: GatePayload) => void
  closeGate: () => void
  gate: GatePayload | null
  /** Trial days remaining, null if not on free trial */
  trialDaysLeft: number | null
  /** Usage counts for free tier */
  usage: { strategies: number; backtests: number }
}

// ─── Context ──────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

// ─── Axios instance ───────────────────────────────────────────────────────────

export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE || '' })

// ─── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => {
    try { return JSON.parse(localStorage.getItem('reyu_user') || 'null') }
    catch { return null }
  })
  const [gate, setGate] = useState<GatePayload | null>(null)
  const gateSuccessRef = useRef<(() => void) | undefined>(undefined)

  // Attach token to every request
  useEffect(() => {
    const reqId = api.interceptors.request.use(cfg => {
      const token = localStorage.getItem('reyu_access_token')
      if (token && cfg.headers) cfg.headers['Authorization'] = `Bearer ${token}`
      return cfg
    })

    // Gate interceptor — catches 401/402 from backend and opens modal
    const resId = api.interceptors.response.use(
      r => r,
      async err => {
        const status = err?.response?.status
        const data   = err?.response?.data
        const gateType: string = data?.detail?.gate || data?.gate || ''
        const message: string  = data?.detail?.message || data?.message || data?.detail || ''

        if (status === 401 && gateType === 'login') {
          setGate({ mode: 'login', message })
          return Promise.reject(err)
        }
        if (status === 401 && !gateType) {
          // Token expired — try refresh
          const refreshToken = localStorage.getItem('reyu_refresh_token')
          if (refreshToken) {
            try {
              const resp = await axios.post('/api/user/refresh', { refresh_token: refreshToken })
              localStorage.setItem('reyu_access_token', resp.data.access_token)
              localStorage.setItem('reyu_refresh_token', resp.data.refresh_token)
              // Retry original request
              err.config.headers['Authorization'] = `Bearer ${resp.data.access_token}`
              return api(err.config)
            } catch {
              _clearSession()
              setGate({ mode: 'login', message: 'Session expired — please sign in again.' })
            }
          } else {
            setGate({ mode: 'login', message })
          }
        }
        if (status === 402) {
          const mode = gateType === 'limit' ? 'limit' : 'upgrade'
          setGate({ mode, message })
        }
        if (status === 403 && gateType === 'trial') {
          setGate({ mode: 'trial', message })
        }
        return Promise.reject(err)
      }
    )

    return () => {
      api.interceptors.request.eject(reqId)
      api.interceptors.response.eject(resId)
    }
  }, [])

  // ── Helpers ────────────────────────────────────────────────────────────────

  function _saveSession(data: { access_token: string; refresh_token: string; user: any }) {
    localStorage.setItem('reyu_access_token', data.access_token)
    localStorage.setItem('reyu_refresh_token', data.refresh_token)
    const u: AuthUser = {
      id: data.user.id,
      email: data.user.email,
      display_name: data.user.display_name,
      tier: data.user.tier,
      trial_expires_at: data.user.trial_expires_at ?? null,
      strategy_count: data.user.strategy_count ?? 0,
      backtest_count: data.user.backtest_count ?? 0,
      onboarded_at: data.user.onboarded_at ?? null,
      trader_type: data.user.trader_type ?? null,
    }
    localStorage.setItem('reyu_user', JSON.stringify(u))
    setUser(u)
    // Telemetry — identify so subsequent events attach to this user
    import('../telemetry').then(t => t.identifyUser({ id: u.id, email: u.email, tier: u.tier }))
  }

  function _clearSession() {
    localStorage.removeItem('reyu_access_token')
    localStorage.removeItem('reyu_refresh_token')
    localStorage.removeItem('reyu_user')
    setUser(null)
    import('../telemetry').then(t => t.resetTelemetry())
  }

  // ── Auth actions ───────────────────────────────────────────────────────────

  const login = useCallback(async (email: string, password: string) => {
    const resp = await api.post('/api/user/login', { email, password })
    _saveSession(resp.data)
    closeGate()
    gateSuccessRef.current?.()
    gateSuccessRef.current = undefined
  }, [])

  const register = useCallback(async (email: string, password: string, name: string) => {
    const resp = await api.post('/api/user/register', { email, password, display_name: name })
    _saveSession(resp.data)
    closeGate()
    gateSuccessRef.current?.()
    gateSuccessRef.current = undefined
  }, [])

  const logout = useCallback(() => {
    api.post('/api/user/logout').catch(() => {})
    _clearSession()
  }, [])

  // ── Gate ───────────────────────────────────────────────────────────────────

  const openGate = useCallback((payload: GatePayload) => {
    gateSuccessRef.current = payload.onSuccess
    setGate(payload)
  }, [])

  const closeGate = useCallback(() => {
    setGate(null)
    gateSuccessRef.current = undefined
  }, [])

  // ── Derived ────────────────────────────────────────────────────────────────

  const tier: Tier = user?.tier ?? 'anonymous'
  const isAuthenticated = user !== null

  const trialDaysLeft: number | null = (() => {
    if (!user?.trial_expires_at || tier !== 'free') return null
    const ms = new Date(user.trial_expires_at).getTime() - Date.now()
    return Math.max(0, Math.ceil(ms / 86_400_000))
  })()

  const usage = {
    strategies: user?.strategy_count ?? 0,
    backtests:  user?.backtest_count ?? 0,
  }

  return (
    <AuthContext.Provider value={{
      user, tier, isAuthenticated,
      login, register, logout,
      openGate, closeGate, gate,
      trialDaysLeft, usage,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

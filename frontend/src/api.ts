import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8000',
  timeout: 30000,
})

// Attach access token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// On 401, try to refresh the token; if that fails, redirect to login
api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config as any
    if (err.response?.status === 401 && !original._retry) {
      original._retry = true
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        try {
          const { data } = await axios.post(
            `${import.meta.env.VITE_API_BASE || 'http://localhost:8000'}/api/user/refresh`,
            { refresh_token: refresh },
          )
          localStorage.setItem('access_token', data.access_token)
          localStorage.setItem('refresh_token', data.refresh_token)
          original.headers.Authorization = `Bearer ${data.access_token}`
          return api(original)
        } catch {
          // refresh failed — clear tokens, let the page redirect
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
        }
      }
    }
    return Promise.reject(err)
  }
)

export type Strike = {
  strike: number
  ce?: LegData
  pe?: LegData
}
export type LegData = {
  ltp: number; oi: number; oi_change: number; volume: number; iv: number
  delta?: number; gamma?: number; theta?: number; vega?: number; symbol?: string
}
export type ChainSummary = {
  pcr_oi: number; pcr_volume: number; max_pain: number
  total_ce_oi: number; total_pe_oi: number
  ce_oi_change: number; pe_oi_change: number
  atm_strike: number; atm_iv: number
}
export type Chain = {
  underlying: string; ltp: number; expiry: any
  expiries?: { date: string; expiry: number }[]
  strikes: Strike[]; summary: ChainSummary
  bias: { bias: string; score: number; signals: string[] }
}

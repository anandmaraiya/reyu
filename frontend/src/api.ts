import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8000',
  timeout: 30000,
})

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
  strikes: Strike[]; summary: ChainSummary
  bias: { bias: string; score: number; signals: string[] }
}

import { useMemo } from 'react'
import { Chain } from '../api'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'

type Strike = Chain['strikes'][number]

export default function OIChart({ chain, windowSize = 25 }: { chain: Chain; windowSize?: number }) {
  const data = useMemo<Strike[]>(() => {
    const strikes = chain?.strikes ?? []
    const sorted = [...strikes].sort((a, b) => a.strike - b.strike)
    const atmIndex = sorted.findIndex(s => s.strike === chain?.summary.atm_strike)
    if (atmIndex < 0 || windowSize >= sorted.length) {
      return sorted
    }
    const half = Math.floor(windowSize / 2)
    let start = Math.max(0, atmIndex - half)
    let end = Math.min(sorted.length, start + windowSize)
    if (end - start < windowSize) {
      start = Math.max(0, end - windowSize)
    }
    return sorted.slice(start, end)
  }, [chain?.strikes, chain?.summary.atm_strike, windowSize])

  const chartData = data.map((s: Strike) => ({
    strike: s.strike,
    'CE OI': s.ce?.oi || 0,
    'PE OI': s.pe?.oi || 0,
    'CE ΔOI': s.ce?.oi_change || 0,
    'PE ΔOI': s.pe?.oi_change || 0,
  }))

  return (
    <div style={{ width: '100%', height: 280 }}>
      <ResponsiveContainer>
        <BarChart data={chartData}>
          <XAxis dataKey="strike" tick={{ fontSize: 10, fill: '#94a3b8' }} />
          <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} />
          <Tooltip contentStyle={{ background: '#0f1422', border: '1px solid #1f2937' }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="CE OI" fill="#dc2626" />
          <Bar dataKey="PE OI" fill="#16a34a" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

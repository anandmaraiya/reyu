import { useMemo, useState } from 'react'
import { Chain } from '../api'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, ReferenceLine, Cell,
} from 'recharts'

type Strike = Chain['strikes'][number]
type View = 'OI' | 'CHANGE'

export default function OIChart({ chain, windowSize = 25 }: { chain: Chain; windowSize?: number }) {
  const [view, setView] = useState<View>('OI')

  const data = useMemo<Strike[]>(() => {
    const strikes = chain?.strikes ?? []
    const sorted = [...strikes].sort((a, b) => a.strike - b.strike)
    const atmIndex = sorted.findIndex(s => s.strike === chain?.summary.atm_strike)
    if (atmIndex < 0 || windowSize >= sorted.length) return sorted
    const half = Math.floor(windowSize / 2)
    let start = Math.max(0, atmIndex - half)
    let end = Math.min(sorted.length, start + windowSize)
    if (end - start < windowSize) start = Math.max(0, end - windowSize)
    return sorted.slice(start, end)
  }, [chain?.strikes, chain?.summary.atm_strike, windowSize])

  const chartData = data.map((s: Strike) => ({
    strike: s.strike,
    CE: view === 'OI' ? (s.ce?.oi || 0) : (s.ce?.oi_change || 0),
    PE: view === 'OI' ? (s.pe?.oi || 0) : (s.pe?.oi_change || 0),
  }))

  const maxPain = chain?.summary.max_pain
  const atm = chain?.summary.atm_strike

  // Find nearest x-axis value for the reference line — Recharts XAxis is
  // category-typed here, so we have to match an existing dataKey value.
  const closestStrike = (target: number | undefined) => {
    if (!target || chartData.length === 0) return undefined
    return chartData.reduce((p, c) => Math.abs(c.strike - target) < Math.abs(p.strike - target) ? c : p).strike
  }

  return (
    <div>
      <div className="row" style={{ alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <div className="row" style={{ gap: 4 }}>
          <button className={view === 'OI' ? 'primary' : 'ghost'} style={{ padding: '4px 10px', fontSize: 11 }} onClick={() => setView('OI')}>OI</button>
          <button className={view === 'CHANGE' ? 'primary' : 'ghost'} style={{ padding: '4px 10px', fontSize: 11 }} onClick={() => setView('CHANGE')}>ΔOI</button>
        </div>
        <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 'auto' }}>
          ATM <strong>{atm}</strong> · Max-Pain <strong style={{ color: 'var(--amber)' }}>{maxPain}</strong>
        </span>
      </div>
      <div style={{ width: '100%', height: 260 }}>
        <ResponsiveContainer>
          <BarChart data={chartData} margin={{ top: 4, right: 6, bottom: 0, left: 0 }}>
            <XAxis dataKey="strike" tick={{ fontSize: 10, fill: '#94a3b8' }} />
            <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }}
                   tickFormatter={(v) => Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v} />
            <Tooltip contentStyle={{ background: '#0f1422', border: '1px solid #1f2937' }}
                     formatter={(v: number) => v.toLocaleString()} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {view === 'CHANGE' && <ReferenceLine y={0} stroke="#94a3b8" />}
            {atm && (
              <ReferenceLine x={closestStrike(atm)} stroke="var(--accent)" strokeDasharray="4 4"
                             label={{ value: 'ATM', fill: 'var(--accent)', fontSize: 10, position: 'insideTopLeft' }} />
            )}
            {maxPain && (
              <ReferenceLine x={closestStrike(maxPain)} stroke="var(--amber)" strokeDasharray="2 4"
                             label={{ value: 'Max Pain', fill: 'var(--amber)', fontSize: 10, position: 'insideTopRight' }} />
            )}
            <Bar dataKey="CE" name={view === 'OI' ? 'CE OI' : 'CE ΔOI'} animationDuration={400}>
              {chartData.map((d, i) => (
                <Cell key={i} fill={d.CE >= 0 ? '#dc2626' : 'rgba(220,38,38,0.45)'} />
              ))}
            </Bar>
            <Bar dataKey="PE" name={view === 'OI' ? 'PE OI' : 'PE ΔOI'} animationDuration={400}>
              {chartData.map((d, i) => (
                <Cell key={i} fill={d.PE >= 0 ? '#16a34a' : 'rgba(22,163,74,0.45)'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

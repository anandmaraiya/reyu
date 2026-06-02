import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import {
  ComposedChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })
const COLOURS = ['#60a5fa', '#f59e0b', '#16a34a', '#a855f7']

type Slot = string | ''   // strategy name or empty
const SLOTS_DEFAULT: Slot[] = ['', '', '', '']

export default function Compare() {
  const { data: saved } = useQuery<Record<string, any>>({
    queryKey: ['saved'],
    queryFn: async () => (await api.get('/api/strategy/saved')).data,
  })
  const names = Object.keys(saved || {})
  const [slots, setSlots] = useState<Slot[]>(SLOTS_DEFAULT)
  const [results, setResults] = useState<Record<string, any>>({})

  useEffect(() => {
    const load = async (name: string) => {
      if (!name || results[name]) return
      const s = saved![name]
      const r = await api.post('/api/strategy/analyse', {
        underlying: s.underlying, legs: s.legs, range_pct: 0.12, strikecount: 25,
      })
      setResults(p => ({ ...p, [name]: r.data }))
    }
    slots.forEach(load)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slots, saved])

  const active = slots.filter(Boolean) as string[]

  // Build merged payoff data
  const merged: Record<string, any> = {}
  for (const name of active) {
    if (!results[name]?.payoff) continue
    for (const p of results[name].payoff.points) {
      merged[p.S] = { ...(merged[p.S] || {}), S: p.S, [name]: p.pnl }
    }
  }
  const series = Object.values(merged).sort((x: any, y: any) => x.S - y.S)
  const spot = active.map(n => results[n]?.spot).find(Boolean)

  // Best-for badges: lowest |max_loss|, highest max_profit, best R/R, highest theta
  const badges: Record<string, string[]> = {}
  if (active.length > 1) {
    const safe = active.filter(n => results[n]?.payoff)
    if (safe.length) {
      const lowRisk = safe.reduce((p, c) => Math.abs(results[c].payoff.max_loss) < Math.abs(results[p].payoff.max_loss) ? c : p)
      const highReward = safe.reduce((p, c) => results[c].payoff.max_profit > results[p].payoff.max_profit ? c : p)
      const bestRR = safe.reduce((p, c) => {
        const rr = (x: string) => results[x].payoff.max_loss ? Math.abs(results[x].payoff.max_profit / results[x].payoff.max_loss) : 0
        return rr(c) > rr(p) ? c : p
      })
      const income = safe.reduce((p, c) => (results[c].payoff.greeks.theta || 0) > (results[p].payoff.greeks.theta || 0) ? c : p)
      ;(badges[lowRisk] ||= []).push('Low Risk')
      ;(badges[highReward] ||= []).push('High Reward')
      ;(badges[bestRR] ||= []).push('Best R:R')
      ;(badges[income] ||= []).push('Income (θ+)')
    }
  }

  return (
    <div className="page-shell">
      <div className="card" style={{ marginBottom: 12 }}>
        <h3>Strategy Comparison — up to 4</h3>
        <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          {slots.map((s, i) => (
            <select key={i} value={s} onChange={e => setSlots(p => p.map((x, j) => j === i ? e.target.value : x))}>
              <option value="">— Slot {String.fromCharCode(65 + i)} —</option>
              {names.map(n => <option key={n}>{n}</option>)}
            </select>
          ))}
          <button className="ghost" onClick={() => setSlots(SLOTS_DEFAULT)} style={{ marginLeft: 'auto' }}>Clear</button>
        </div>
      </div>

      {active.length > 0 && (
        <div className="card">
          <div style={{ width: '100%', height: 340 }}>
            <ResponsiveContainer>
              <ComposedChart data={series}>
                <XAxis dataKey="S" tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={(v) => num(v, 0)} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={(v) => num(v, 0)} />
                <Tooltip contentStyle={{ background: '#0f1422', border: '1px solid #1f2937' }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <ReferenceLine y={0} stroke="#94a3b8" />
                {spot && <ReferenceLine x={spot} stroke="var(--accent)" strokeDasharray="3 3" label={{ value: 'Spot', fontSize: 10 }} />}
                {active.map((n, i) => (
                  <Line key={n} type="monotone" dataKey={n} stroke={COLOURS[i]} strokeWidth={2} dot={false} />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          <div className="row" style={{ marginTop: 10, overflowX: 'auto' }}>
            <table style={{ minWidth: 600 }}>
              <thead>
                <tr><th>Strategy</th><th>Max Profit</th><th>Max Loss</th><th>POP</th><th>Margin</th><th>R:R</th><th>Net Δ</th><th>Vega</th><th>Best for</th></tr>
              </thead>
              <tbody>
                {active.map((n, i) => {
                  const r = results[n]
                  if (!r?.payoff) return <tr key={n}><td colSpan={9} style={{ color: 'var(--muted)' }}>loading {n}…</td></tr>
                  const rr = r.payoff.max_loss ? Math.abs(r.payoff.max_profit / r.payoff.max_loss) : null
                  return (
                    <tr key={n}>
                      <td>
                        <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, background: COLOURS[i], marginRight: 6 }} />
                        {n}
                      </td>
                      <td className="bull">₹{num(r.payoff.max_profit, 0)}</td>
                      <td className="bear">₹{num(r.payoff.max_loss, 0)}</td>
                      <td>{r.pop?.pop ? (r.pop.pop * 100).toFixed(1) + '%' : '—'}</td>
                      <td>₹{num(r.margin?.total, 0)}</td>
                      <td>{rr == null ? '∞' : num(rr, 2)}</td>
                      <td>{num(r.payoff.greeks.delta, 3)}</td>
                      <td>{num(r.payoff.greeks.vega, 2)}</td>
                      <td style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {(badges[n] || []).map(b => (
                          <span key={b} className="tag" style={{ background: 'rgba(96,165,250,.15)', color: 'var(--accent)' }}>{b}</span>
                        ))}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

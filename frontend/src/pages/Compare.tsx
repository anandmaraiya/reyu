import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import {
  ComposedChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

export default function Compare() {
  const { data: saved } = useQuery<Record<string, any>>({
    queryKey: ['saved'],
    queryFn: async () => (await api.get('/api/strategy/saved')).data,
  })
  const names = Object.keys(saved || {})
  const [a, setA] = useState('')
  const [b, setB] = useState('')
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
    load(a); load(b)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a, b, saved])

  const merged: Record<string, any> = {}
  for (const name of [a, b]) {
    if (!name || !results[name]?.payoff) continue
    for (const p of results[name].payoff.points) {
      merged[p.S] = { ...(merged[p.S] || {}), S: p.S, [name]: p.pnl }
    }
  }
  const series = Object.values(merged).sort((x: any, y: any) => x.S - y.S)
  const spot = results[a]?.spot || results[b]?.spot

  return (
    <div>
      <div className="card" style={{ marginBottom: 12 }}>
        <h3>Strategy Comparison</h3>
        <div className="row">
          <select value={a} onChange={e => setA(e.target.value)}><option value="">— Strategy A —</option>{names.map(n => <option key={n}>{n}</option>)}</select>
          <select value={b} onChange={e => setB(e.target.value)}><option value="">— Strategy B —</option>{names.map(n => <option key={n}>{n}</option>)}</select>
        </div>
      </div>

      {(a || b) && (
        <div className="card">
          <div style={{ width: '100%', height: 320 }}>
            <ResponsiveContainer>
              <ComposedChart data={series}>
                <XAxis dataKey="S" tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={(v) => num(v, 0)} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={(v) => num(v, 0)} />
                <Tooltip contentStyle={{ background: '#0f1422', border: '1px solid #1f2937' }} />
                <Legend />
                <ReferenceLine y={0} stroke="#94a3b8" />
                {spot && <ReferenceLine x={spot} stroke="#60a5fa" strokeDasharray="3 3" label={{ value: 'Spot', fontSize: 10 }} />}
                {a && <Line type="monotone" dataKey={a} stroke="#60a5fa" strokeWidth={2} dot={false} />}
                {b && <Line type="monotone" dataKey={b} stroke="#f59e0b" strokeWidth={2} dot={false} />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          <div className="row" style={{ marginTop: 8 }}>
            {[a, b].filter(Boolean).map(name => results[name] && (
              <div key={name} className="card col" style={{ minWidth: 220 }}>
                <h3>{name}</h3>
                <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                  Max Profit: <span className="bull">₹{num(results[name].payoff.max_profit, 0)}</span><br />
                  Max Loss: <span className="bear">₹{num(results[name].payoff.max_loss, 0)}</span><br />
                  POP: {results[name].pop?.pop ? (results[name].pop.pop * 100).toFixed(1) + '%' : '—'}<br />
                  Margin: ₹{num(results[name].margin?.total, 0)}<br />
                  Net Δ: {num(results[name].payoff.greeks.delta, 3)} · Vega: {num(results[name].payoff.greeks.vega, 2)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

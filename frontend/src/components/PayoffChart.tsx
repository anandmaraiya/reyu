import {
  ComposedChart, Line, Area, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer,
} from 'recharts'

export type Payoff = {
  spot: number
  points: { S: number; pnl: number }[]
  max_profit: number
  max_loss: number
  pnl_at_spot: number
  breakevens: number[]
  greeks: { delta: number; gamma: number; theta: number; vega: number }
  net_debit: number
}

const fmt = (n: number, d = 2) => Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

export default function PayoffChart({ payoff, height = 280 }: { payoff: Payoff; height?: number }) {
  if (!payoff?.points) return null
  const data = payoff.points.map(p => ({
    S: p.S,
    profit: p.pnl >= 0 ? p.pnl : 0,
    loss: p.pnl < 0 ? p.pnl : 0,
    pnl: p.pnl,
  }))
  return (
    <div>
      <div style={{ width: '100%', height }}>
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 8 }}>
            <XAxis dataKey="S" tick={{ fontSize: 10, fill: '#94a3b8' }}
                   tickFormatter={(v) => fmt(v, 0)} />
            <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={(v) => fmt(v, 0)} />
            <Tooltip contentStyle={{ background: '#0f1422', border: '1px solid #1f2937' }}
                     formatter={(v: any) => `₹ ${fmt(v, 0)}`}
                     labelFormatter={(v) => `Spot ${fmt(v as number, 0)}`} />
            <ReferenceLine y={0} stroke="#94a3b8" />
            <ReferenceLine x={payoff.spot} stroke="#60a5fa" strokeDasharray="4 4" label={{ value: 'Spot', fill: '#60a5fa', fontSize: 10 }} />
            {payoff.breakevens.map(b => (
              <ReferenceLine key={b} x={b} stroke="#f59e0b" strokeDasharray="2 4"
                             label={{ value: `BE ${fmt(b, 0)}`, fill: '#f59e0b', fontSize: 10 }} />
            ))}
            <Area type="monotone" dataKey="profit" stroke="none" fill="#16a34a" fillOpacity={0.25} />
            <Area type="monotone" dataKey="loss" stroke="none" fill="#dc2626" fillOpacity={0.25} />
            <Line type="monotone" dataKey="pnl" stroke="#e5e7eb" strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="row" style={{ marginTop: 6, fontSize: 12 }}>
        <span><span style={{ color: 'var(--muted)' }}>Max P:</span> <span className="bull">₹{fmt(payoff.max_profit, 0)}</span></span>
        <span><span style={{ color: 'var(--muted)' }}>Max L:</span> <span className="bear">₹{fmt(payoff.max_loss, 0)}</span></span>
        <span><span style={{ color: 'var(--muted)' }}>@ Spot:</span> {fmt(payoff.pnl_at_spot, 0)}</span>
        <span><span style={{ color: 'var(--muted)' }}>BE:</span> {payoff.breakevens.map(b => fmt(b, 0)).join(', ') || '—'}</span>
        <span><span style={{ color: 'var(--muted)' }}>Net:</span> {fmt(payoff.net_debit, 0)} ({payoff.net_debit >= 0 ? 'Debit' : 'Credit'})</span>
      </div>
    </div>
  )
}

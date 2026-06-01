import { useState } from 'react'
import { api, Chain } from '../api'
import PayoffChart from './PayoffChart'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

export default function HedgeBuilder({ underlying, chain }: { underlying: string, chain: Chain }) {
  const candidates = chain.strikes.flatMap(s => [s.ce, s.pe]).filter(Boolean) as any[]
  const [primary, setPrimary] = useState<string>(candidates[0]?.symbol || '')
  const [action, setAction] = useState<'BUY' | 'SELL'>('BUY')
  const [qty, setQty] = useState(1)
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const build = async () => {
    setLoading(true)
    try {
      const r = await api.post('/api/analytics/hedge', {
        symbol: underlying,
        primary_option_symbol: primary,
        action, qty,
        target_delta: 0,
      })
      setResult(r.data)
    } finally { setLoading(false) }
  }

  return (
    <div className="card">
      <h3>Hedge Builder — risk-adjusted</h3>
      <div className="row" style={{ marginBottom: 8 }}>
        <select value={primary} onChange={e => setPrimary(e.target.value)} style={{ flex: 1 }}>
          {candidates.map(c => <option key={c.symbol} value={c.symbol}>{c.symbol}</option>)}
        </select>
        <select value={action} onChange={e => setAction(e.target.value as any)}>
          <option>BUY</option><option>SELL</option>
        </select>
        <input className="input" type="number" min={1} value={qty} onChange={e => setQty(+e.target.value)} style={{ width: 60 }} />
        <button className="primary" onClick={build} disabled={loading}>{loading ? '…' : 'Suggest'}</button>
      </div>
      {result?.legs && (
        <>
          <table>
            <thead><tr><th>Leg</th><th>Action</th><th>Qty</th><th>LTP</th><th>Δ</th><th>Vega</th></tr></thead>
            <tbody>
              {result.legs.map((l: any, i: number) => (
                <tr key={i}>
                  <td>{l.symbol || `K=${l.strike} ${l.side?.toUpperCase()}`}</td>
                  <td className={l.action === 'BUY' ? 'bull' : 'bear'}>{l.action}</td>
                  <td>{l.qty}</td>
                  <td>{num(l.ltp)}</td>
                  <td>{num(l.delta, 3)}</td>
                  <td>{num(l.vega, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
            Net Δ {num(result.portfolio_greeks.delta, 3)} | Γ {num(result.portfolio_greeks.gamma, 4)} |
            θ {num(result.portfolio_greeks.theta, 2)} | Vega {num(result.portfolio_greeks.vega, 2)} |
            Debit {num(result.portfolio_greeks.net_debit, 2)}
          </div>
          {result.margin && (
            <div style={{ marginTop: 6, fontSize: 12 }}>
              <strong>Margin required:</strong> ₹ {num(result.margin.total, 0)}
              <span style={{ color: 'var(--muted)', marginLeft: 6 }}>({result.margin.source})</span>
            </div>
          )}
          {result.payoff && <div style={{ marginTop: 8 }}><PayoffChart payoff={result.payoff} height={200} /></div>}
        </>
      )}
    </div>
  )
}

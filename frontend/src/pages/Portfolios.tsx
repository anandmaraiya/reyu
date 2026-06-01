import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

type Leg = { symbol: string; action: 'BUY' | 'SELL'; qty: number; entry_price: number; delta?: number; vega?: number }

export default function Portfolios() {
  const qc = useQueryClient()
  const { data } = useQuery<Record<string, any>>({
    queryKey: ['portfolios'],
    queryFn: async () => (await api.get('/api/portfolio')).data,
    refetchInterval: 10000,
  })

  const [draft, setDraft] = useState<{ name: string; style: string; capital: number; legs: Leg[] }>({
    name: 'Scalper-1', style: 'SCALP', capital: 100000, legs: [],
  })
  const [legDraft, setLegDraft] = useState<Leg>({ symbol: '', action: 'BUY', qty: 1, entry_price: 0 })

  const addLeg = () => setDraft(d => ({ ...d, legs: [...d.legs, legDraft] }))
  const save = async () => {
    await api.put('/api/portfolio', draft)
    qc.invalidateQueries({ queryKey: ['portfolios'] })
  }
  const del = async (n: string) => { await api.delete(`/api/portfolio/${encodeURIComponent(n)}`); qc.invalidateQueries({ queryKey: ['portfolios'] }) }

  return (
    <div>
      <div className="card" style={{ marginBottom: 12 }}>
        <h3>New Portfolio</h3>
        <div className="row">
          <input className="input" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} placeholder="Portfolio name" />
          <select value={draft.style} onChange={e => setDraft({ ...draft, style: e.target.value })}>
            <option>SCALP</option><option>SWING</option><option>HEDGED</option>
          </select>
          <input className="input" type="number" value={draft.capital} onChange={e => setDraft({ ...draft, capital: +e.target.value })} placeholder="Capital" />
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <input className="input" placeholder="Symbol" value={legDraft.symbol} onChange={e => setLegDraft({ ...legDraft, symbol: e.target.value })} />
          <select value={legDraft.action} onChange={e => setLegDraft({ ...legDraft, action: e.target.value as any })}><option>BUY</option><option>SELL</option></select>
          <input className="input" type="number" placeholder="Qty" value={legDraft.qty} onChange={e => setLegDraft({ ...legDraft, qty: +e.target.value })} style={{ width: 80 }} />
          <input className="input" type="number" placeholder="Entry" value={legDraft.entry_price} onChange={e => setLegDraft({ ...legDraft, entry_price: +e.target.value })} style={{ width: 100 }} />
          <button onClick={addLeg}>+ Leg</button>
          <button className="primary" onClick={save}>Save Portfolio</button>
        </div>
        {draft.legs.length > 0 && (
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>
            {draft.legs.length} leg(s) staged: {draft.legs.map(l => `${l.action} ${l.qty} ${l.symbol}`).join(' | ')}
          </div>
        )}
      </div>

      <div className="row">
        {data && Object.entries(data).map(([name, p]: any) => (
          <PortfolioCard key={name} name={name} p={p} onDelete={() => del(name)} />
        ))}
      </div>
    </div>
  )
}

function PortfolioCard({ name, p, onDelete }: { name: string; p: any; onDelete: () => void }) {
  const { data: pnl } = useQuery({
    queryKey: ['pnl', name],
    queryFn: async () => (await api.get(`/api/portfolio/${encodeURIComponent(name)}/pnl`)).data,
    refetchInterval: 8000,
  })
  const { data: metrics } = useQuery({
    queryKey: ['metrics', name],
    queryFn: async () => (await api.get(`/api/portfolio/${encodeURIComponent(name)}/metrics`)).data,
    refetchInterval: 60000,
  })
  const r = p.risk || {}
  const killAll = async () => {
    if (!confirm(`Close ALL legs of "${name}"? This sends opposite-side MARKET orders.`)) return
    await api.post(`/api/portfolio/${encodeURIComponent(name)}/kill`, null, { params: { dry_run: false } })
    alert(`Kill switch fired for ${name}`)
  }
  return (
    <div className="card col" style={{ minWidth: 320 }}>
      <h3>{name} <span className="tag neutral" style={{ marginLeft: 6 }}>{p.style}</span>
        <button onClick={killAll} style={{ float: 'right', marginLeft: 4, background: 'var(--red)', color: '#fff', borderColor: 'transparent' }} title="Close all legs">⏻</button>
        <button onClick={onDelete} style={{ float: 'right' }}>×</button>
      </h3>
      <div className="kpi" style={{ color: (pnl?.pnl ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>
        ₹ {num(pnl?.pnl, 0)}
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)', margin: '6px 0' }}>
        Δ {num(r.greeks?.delta, 2)} | Vega {num(r.greeks?.vega, 2)} | Exp ₹{num(r.greeks?.exposure, 0)}
      </div>
      {metrics && (
        <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
          Sharpe {metrics.sharpe ?? '—'} · MaxDD ₹{num(metrics.max_drawdown, 0)} · Win {metrics.win_rate != null ? (metrics.win_rate * 100).toFixed(0) + '%' : '—'}
        </div>
      )}
      {r.violations?.length > 0 && (
        <div className="tag bear" style={{ marginBottom: 6 }}>⚠ {r.violations.join('; ')}</div>
      )}
      <table>
        <thead><tr><th>Leg</th><th>Qty</th><th>Entry</th><th>LTP</th><th>P&L</th></tr></thead>
        <tbody>
          {pnl?.legs?.map((l: any, i: number) => (
            <tr key={i}>
              <td>{l.symbol}</td><td>{l.qty}</td><td>{num(l.entry)}</td><td>{num(l.ltp)}</td>
              <td className={l.pnl >= 0 ? 'bull' : 'bear'}>{num(l.pnl, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

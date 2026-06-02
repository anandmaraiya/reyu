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

  const Field = ({ label, children, w }: { label: string; children: React.ReactNode; w?: number }) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: w }}>
      <span style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: .5 }}>{label}</span>
      {children}
    </div>
  )

  const portfolios = data ? Object.entries(data) : []

  return (
    <div className="page-shell">
      <div className="card">
        <div className="card-header">
          <h3>New Portfolio</h3>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>Build a tracking book — name it, set your capital, add legs.</span>
        </div>
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <Field label="Name" w={200}>
            <input className="input" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} placeholder="e.g. Bull-call NIFTY weekly" />
          </Field>
          <Field label="Style" w={140}>
            <select value={draft.style} onChange={e => setDraft({ ...draft, style: e.target.value })}>
              <option>SCALP</option><option>SWING</option><option>HEDGED</option>
            </select>
          </Field>
          <Field label="Capital (₹)" w={140}>
            <input className="input" type="number" value={draft.capital} onChange={e => setDraft({ ...draft, capital: +e.target.value })} />
          </Field>
        </div>
        <div className="row" style={{ marginTop: 12, alignItems: 'flex-end' }}>
          <Field label="Symbol" w={220}>
            <input className="input" placeholder="NSE:NIFTY2660923500CE" value={legDraft.symbol} onChange={e => setLegDraft({ ...legDraft, symbol: e.target.value })} />
          </Field>
          <Field label="Action" w={90}>
            <select value={legDraft.action} onChange={e => setLegDraft({ ...legDraft, action: e.target.value as any })}>
              <option>BUY</option><option>SELL</option>
            </select>
          </Field>
          <Field label="Quantity" w={90}>
            <input className="input" type="number" min={1} value={legDraft.qty} onChange={e => setLegDraft({ ...legDraft, qty: +e.target.value })} />
          </Field>
          <Field label="Entry ₹" w={110}>
            <input className="input" type="number" step={0.05} value={legDraft.entry_price} onChange={e => setLegDraft({ ...legDraft, entry_price: +e.target.value })} />
          </Field>
          <button onClick={addLeg}>+ Add leg</button>
          <button className="primary" onClick={save} disabled={draft.legs.length === 0}>Save portfolio</button>
        </div>
        {draft.legs.length > 0 && (
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>
            <strong>{draft.legs.length} leg(s) staged:</strong> {draft.legs.map(l => `${l.action} ${l.qty} ${l.symbol}`).join(' · ')}
          </div>
        )}
      </div>

      {portfolios.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', color: 'var(--muted)', padding: '32px 16px' }}>
          <div style={{ fontSize: 30, marginBottom: 6 }}>📊</div>
          <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>No portfolios yet</div>
          Save your first portfolio above to see live P&amp;L, aggregated Greeks, Sharpe / MaxDD,
          and risk-cap violations side-by-side.
        </div>
      ) : (
        <div className="grid-3">
          {portfolios.map(([name, p]: any) => (
            <PortfolioCard key={name} name={name} p={p} onDelete={() => del(name)} />
          ))}
        </div>
      )}
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

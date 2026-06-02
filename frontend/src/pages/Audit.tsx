import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { downloadCSV } from '../utils/csv'

type AuditEntry = {
  ts: string
  label: string
  dry_run: boolean
  legs: any[]
  results: any[]
}

const fmtDate = (s: string) => {
  const d = new Date(s); if (isNaN(+d)) return s
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function statusOf(a: AuditEntry): { label: string; cls: string } {
  if (a.dry_run) return { label: 'DRY', cls: 'neutral' }
  const errs = a.results.filter((r: any) => r.error).length
  if (errs === 0) return { label: 'LIVE · OK', cls: 'bull' }
  if (errs === a.results.length) return { label: 'FAILED', cls: 'bear' }
  return { label: 'PARTIAL', cls: 'neutral' }
}

function batchPnL(a: AuditEntry): number {
  return a.results.reduce((sum: number, r: any) => sum + (r?.response?.realisedPnl || 0), 0)
}

export default function Audit() {
  const [days, setDays] = useState(7)
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'LIVE' | 'DRY' | 'FAILED'>('ALL')

  const { data } = useQuery<AuditEntry[]>({
    queryKey: ['audit', days],
    queryFn: async () => (await api.get('/api/orders/audit', { params: { limit: 200 } })).data,
    refetchInterval: 10000,
  })

  const since = useMemo(() => Date.now() - days * 86400 * 1000, [days])
  const filtered = useMemo(() => {
    return (data || []).filter(a => {
      const ts = new Date(a.ts).getTime()
      if (ts < since) return false
      const s = statusOf(a)
      if (statusFilter === 'ALL') return true
      if (statusFilter === 'DRY') return a.dry_run
      if (statusFilter === 'LIVE') return !a.dry_run && s.cls === 'bull'
      if (statusFilter === 'FAILED') return s.label === 'FAILED'
      return true
    })
  }, [data, since, statusFilter])

  const groups: Record<string, AuditEntry[]> = {}
  for (const a of filtered) {
    const day = new Date(a.ts).toDateString()
    ;(groups[day] ||= []).push(a)
  }
  const days_sorted = Object.keys(groups).sort((x, y) => new Date(y).getTime() - new Date(x).getTime())

  const exportCSV = () => downloadCSV('reyu-audit.csv', filtered.map(d => ({
    ts: d.ts, label: d.label, dry_run: d.dry_run, legs: d.legs.length,
    status: statusOf(d).label, pnl: batchPnL(d),
  })))

  return (
    <div className="page-shell">
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="row" style={{ alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <h3 style={{ margin: 0 }}>Timeline</h3>
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>{filtered.length} of {(data || []).length} entries</span>
          <select value={days} onChange={e => setDays(+e.target.value)}>
            <option value={1}>Last 24h</option>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={9999}>All time</option>
          </select>
          <div className="row" style={{ gap: 4 }}>
            {(['ALL', 'LIVE', 'DRY', 'FAILED'] as const).map(f => (
              <button key={f} className={statusFilter === f ? 'primary' : 'ghost'}
                      style={{ padding: '4px 10px', fontSize: 11 }}
                      onClick={() => setStatusFilter(f)}>{f}</button>
            ))}
          </div>
          <button onClick={exportCSV} style={{ marginLeft: 'auto' }}>Export CSV</button>
        </div>
      </div>

      {days_sorted.length === 0 && (
        <div className="card" style={{ color: 'var(--muted)' }}>No matching audit entries.</div>
      )}

      {days_sorted.map(day => (
        <div key={day} style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>{day}</div>
          <div style={{ borderLeft: '2px solid var(--border)', paddingLeft: 16, marginLeft: 6 }}>
            {groups[day].map((a, i) => {
              const s = statusOf(a)
              const pnl = batchPnL(a)
              return (
                <div key={i} style={{ position: 'relative', marginBottom: 10 }}>
                  <span style={{
                    position: 'absolute', left: -22, top: 14, width: 10, height: 10, borderRadius: 6,
                    background: s.cls === 'bull' ? 'var(--green)' : s.cls === 'bear' ? 'var(--red)' : 'var(--amber)',
                    border: '2px solid var(--bg)',
                  }} />
                  <details className="card" style={{ padding: 10 }}>
                    <summary style={{ cursor: 'pointer', listStyle: 'none', outline: 'none' }}>
                      <div className="row" style={{ alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <strong>{a.label || 'order'}</strong>
                        <span className={`tag ${s.cls}`}>{s.label}</span>
                        <span style={{ fontSize: 11, color: 'var(--muted)' }}>{fmtDate(a.ts)}</span>
                        <span style={{ fontSize: 11, color: 'var(--muted)' }}>{a.legs.length} leg(s)</span>
                        {pnl !== 0 && (
                          <span className={pnl >= 0 ? 'bull' : 'bear'} style={{ marginLeft: 'auto' }}>
                            P&L ₹{pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                          </span>
                        )}
                      </div>
                    </summary>
                    <div style={{ marginTop: 8, overflowX: 'auto' }}>
                      <table style={{ fontSize: 11, minWidth: 500 }}>
                        <thead><tr><th>Symbol</th><th>Action</th><th>Qty</th><th>Type</th><th>Result</th></tr></thead>
                        <tbody>
                          {a.legs.map((leg: any, j: number) => {
                            const r = a.results[j] || {}
                            return (
                              <tr key={j}>
                                <td>{leg.symbol}</td>
                                <td className={leg.side === 'BUY' ? 'bull' : 'bear'}>{leg.side}</td>
                                <td>{leg.qty}</td>
                                <td>{leg.order_type}</td>
                                <td>{r.error ? <span className="bear">{String(r.error).slice(0, 80)}</span> : <span className="bull">OK</span>}</td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  </details>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

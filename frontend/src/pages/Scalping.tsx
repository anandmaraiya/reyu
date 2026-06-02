import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

export default function Scalping() {
  const [wl, setWl] = useState('')
  const { data: wls } = useQuery<Record<string, any>>({
    queryKey: ['watchlists'],
    queryFn: async () => (await api.get('/api/watchlist')).data,
  })
  const { data: scan, refetch, isFetching } = useQuery({
    queryKey: ['scan', wl],
    enabled: !!wl,
    queryFn: async () => (await api.get(`/api/scalping/scan/${encodeURIComponent(wl)}`)).data,
    refetchInterval: 20000,
  })

  return (
    <div className="page-shell">
      <div className="card">
        <div className="card-header">
          <h3>Live Signal Scanner</h3>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            Scans a watchlist for short-term setups (bias × intraday momentum) and surfaces ATM legs to act on.
          </span>
        </div>
        <div className="row" style={{ alignItems: 'center' }}>
          <select value={wl} onChange={e => setWl(e.target.value)} style={{ minWidth: 220 }}>
            <option value="">Select a watchlist…</option>
            {wls && Object.keys(wls).map(n => <option key={n}>{n}</option>)}
          </select>
          <button className="primary" onClick={() => refetch()} disabled={!wl}>
            {isFetching ? 'Scanning…' : 'Scan'}
          </button>
          {!wl && <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            Need a watchlist first? Create one under <a href="/watchlists">Watchlists</a>.
          </span>}
        </div>
      </div>

      {!scan && (
        <div className="card" style={{ textAlign: 'center', color: 'var(--muted)', padding: '32px 16px' }}>
          <div style={{ fontSize: 30, marginBottom: 6 }}>⚡</div>
          <div style={{ fontWeight: 600, color: 'var(--text)' }}>Pick a watchlist and hit Scan</div>
          <div style={{ fontSize: 12, marginTop: 4 }}>
            Signals refresh every 20 seconds once scanning starts.
          </div>
        </div>
      )}

      {scan && (
        <>
          <div className="card" style={{ marginBottom: 12 }}>
            <h3>Actionable now ({scan.actionable.length})</h3>
            <table>
              <thead><tr><th>Symbol</th><th>Dir</th><th>Spot</th><th>Mom%</th><th>Suggested Leg</th><th>Stop / Target</th></tr></thead>
              <tbody>
                {scan.actionable.map((s: any) => (
                  <tr key={s.symbol}>
                    <td>{s.symbol}</td>
                    <td><span className={`tag ${s.direction === 'LONG' ? 'bull' : 'bear'}`}>{s.direction}</span></td>
                    <td>{num(s.ltp)}</td>
                    <td className={s.momentum_pct > 0 ? 'bull' : 'bear'}>{num(s.momentum_pct, 2)}</td>
                    <td>{s.suggested_leg?.symbol} @ {num(s.suggested_leg?.ltp)}</td>
                    <td>{s.stop_pct}% / {s.target_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card">
            <h3>All signals</h3>
            <table>
              <thead><tr><th>Symbol</th><th>Bias</th><th>Score</th><th>Mom%</th><th>Direction</th></tr></thead>
              <tbody>
                {scan.signals.map((s: any) => (
                  <tr key={s.symbol}>
                    <td>{s.symbol}</td>
                    <td>{s.bias?.bias || s.error}</td>
                    <td>{s.bias?.score}</td>
                    <td>{num(s.momentum_pct, 2)}</td>
                    <td>{s.direction || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

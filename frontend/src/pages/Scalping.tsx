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
    <div>
      <div className="card" style={{ marginBottom: 12 }}>
        <h3>Scalping Scanner</h3>
        <div className="row">
          <select value={wl} onChange={e => setWl(e.target.value)}>
            <option value="">Select watchlist…</option>
            {wls && Object.keys(wls).map(n => <option key={n}>{n}</option>)}
          </select>
          <button className="primary" onClick={() => refetch()}>{isFetching ? '…' : 'Scan'}</button>
        </div>
      </div>

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

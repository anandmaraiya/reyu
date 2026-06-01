import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useToast } from '../toast'
import { downloadCSV } from '../utils/csv'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

export default function Watchlists() {
  const qc = useQueryClient()
  const t = useToast()
  const { data: wls } = useQuery<Record<string, any>>({
    queryKey: ['watchlists'],
    queryFn: async () => (await api.get('/api/watchlist')).data,
  })

  const [name, setName] = useState('Nifty50 Heavies')
  const [symbols, setSymbols] = useState('NSE:RELIANCE-EQ,NSE:HDFCBANK-EQ,NSE:INFY-EQ,NSE:TCS-EQ,NSE:ICICIBANK-EQ')
  const [selected, setSelected] = useState<string | null>(null)
  const [compare, setCompare] = useState<any>(null)

  const save = useMutation({
    mutationFn: async () => api.put('/api/watchlist', { name, symbols: symbols.split(',').map(s => s.trim()) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlists'] }),
  })

  const runCompare = async (n: string) => {
    setSelected(n)
    const r = await api.get(`/api/watchlist/${encodeURIComponent(n)}/compare`)
    setCompare(r.data)
  }

  return (
    <div>
      <div className="card" style={{ marginBottom: 12 }}>
        <h3>Create / Update Watchlist</h3>
        <div className="row">
          <input className="input" value={name} onChange={e => setName(e.target.value)} placeholder="Name" />
          <input className="input" value={symbols} onChange={e => setSymbols(e.target.value)}
                 style={{ flex: 1 }} placeholder="comma-separated Fyers symbols" />
          <button className="primary" onClick={() => save.mutate()}>Save</button>
        </div>
      </div>

      <div className="row">
        <div className="card col" style={{ maxWidth: 280 }}>
          <h3>Saved Watchlists</h3>
          {wls && Object.entries(wls).map(([n, w]: any) => (
            <div key={n} style={{ padding: 6, borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                 onClick={() => runCompare(n)}>
              <div style={{ fontWeight: 600 }}>{n}</div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>{w.symbols?.length} symbols</div>
            </div>
          ))}
        </div>

        <div className="card col" style={{ flex: 2 }}>
          <h3>Comparative Analysis {selected && `— ${selected}`}</h3>
          {!compare && <div style={{ color: 'var(--muted)' }}>Select a watchlist to scan.</div>}
          {compare && (
            <>
              <div className="row" style={{ marginBottom: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>Heat:</span>
                {compare.rows.map((r: any) => (
                  <div key={r.symbol} title={`${r.symbol} · score ${r.score ?? '—'}`}
                       style={{
                         width: 22, height: 22, borderRadius: 4, fontSize: 9, display: 'flex',
                         alignItems: 'center', justifyContent: 'center', color: '#fff',
                         background: r.bias?.includes('BULL') ? 'rgba(22,163,74,0.7)'
                                    : r.bias?.includes('BEAR') ? 'rgba(220,38,38,0.7)' : '#334155',
                         border: r.flipped ? '2px solid var(--amber)' : '1px solid var(--border)',
                       }}>
                    {r.symbol.split(':')[1]?.split('-')[0]?.slice(0, 4) || '?'}
                  </div>
                ))}
                <button style={{ marginLeft: 'auto' }} onClick={() => downloadCSV(`${selected}-compare.csv`, compare.rows)}>Export CSV</button>
              </div>
              <table>
                <thead>
                  <tr><th>Symbol</th><th>LTP</th><th>PCR</th><th>Max Pain</th><th>ATM IV</th>
                      <th>OI Δ (CE/PE)</th><th>Bias</th></tr>
                </thead>
                <tbody>
                  {compare.rows.map((r: any) => (
                    <tr key={r.symbol}>
                      <td>{r.symbol}</td>
                      <td>{num(r.ltp)}</td>
                      <td>{num(r.pcr_oi, 2)}</td>
                      <td>{num(r.max_pain, 0)}</td>
                      <td>{r.atm_iv ? (r.atm_iv * 100).toFixed(1) + '%' : '—'}</td>
                      <td>{num(r.ce_oi_change, 0)} / {num(r.pe_oi_change, 0)}</td>
                      <td>
                        <span className={`tag ${r.bias?.includes('BULL') ? 'bull' : r.bias?.includes('BEAR') ? 'bear' : 'neutral'}`}>{r.bias || r.error}</span>
                        {r.flipped && <span className="tag" style={{ marginLeft: 4, background: 'rgba(245,158,11,.2)', color: 'var(--amber)' }}>FLIPPED</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ marginTop: 12 }}>
                <strong className="bull">Long candidates:</strong> {compare.suggestions.long_candidates.join(', ') || '—'}<br />
                <strong className="bear">Short candidates:</strong> {compare.suggestions.short_candidates.join(', ') || '—'}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import PayoffChart from '../components/PayoffChart'
import { downloadCSV } from '../utils/csv'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

export default function Positions() {
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ['pos-by-ticker'],
    queryFn: async () => (await api.get('/api/strategy/positions-by-ticker')).data,
    refetchInterval: 15000,
  })

  return (
    <div>
      <div className="row" style={{ alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Active Positions by Ticker</h3>
        <button onClick={() => refetch()} style={{ marginLeft: 'auto' }}>{isFetching ? '…' : 'Refresh'}</button>
      </div>

      {error && <div className="card bear">{(error as any).message}</div>}
      {data?.error && <div className="card bear">{data.error}</div>}
      {data?.groups?.length === 0 && (
        <div className="card" style={{ color: 'var(--muted)' }}>
          No open positions in your Fyers account.
        </div>
      )}

      {data?.groups?.map((g: any) => (
        <div key={g.underlying} className="card" style={{ marginBottom: 12 }}>
          <div className="row" style={{ alignItems: 'baseline' }}>
            <h3 style={{ margin: 0 }}>{g.underlying}</h3>
            <span style={{ color: 'var(--muted)', fontSize: 12 }}>Spot {num(g.spot, 2)}</span>
            <span style={{ marginLeft: 'auto', fontSize: 14 }}>
              Net P&amp;L:
              <strong className={g.net_pl >= 0 ? 'bull' : 'bear'} style={{ marginLeft: 6 }}>
                ₹{num(g.net_pl, 0)}
              </strong>
            </span>
            <span style={{ fontSize: 12 }}>Margin ₹{num(g.margin?.total, 0)}</span>
            <button onClick={() => downloadCSV(`${g.underlying}-positions.csv`, g.legs)}>CSV</button>
          </div>

          {g.suggestions?.length > 0 && (
            <div className="row" style={{ marginTop: 6, flexWrap: 'wrap', gap: 4 }}>
              {g.suggestions.map((s: any, i: number) => (
                <span key={i} className={`tag ${s.type === 'STOP' ? 'bear' : s.type === 'TAKE_PROFIT' ? 'bull' : 'neutral'}`}>
                  {s.type}: {s.msg}
                </span>
              ))}
            </div>
          )}

          <div className="row" style={{ marginTop: 8 }}>
            <div className="col" style={{ flex: 1 }}>
              <table>
                <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Avg</th><th>LTP</th><th>P&amp;L</th></tr></thead>
                <tbody>
                  {g.legs.map((l: any) => (
                    <tr key={l.symbol}>
                      <td style={{ fontSize: 11 }}>{l.symbol}</td>
                      <td className={l.action === 'BUY' ? 'bull' : 'bear'}>{l.action}</td>
                      <td>{l.qty}</td>
                      <td>{num(l.price)}</td>
                      <td>{num(l.ltp)}</td>
                      <td className={l.pl >= 0 ? 'bull' : 'bear'}>{num(l.pl, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="col" style={{ flex: 2 }}>
              {g.payoff && <PayoffChart payoff={g.payoff} height={220} />}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

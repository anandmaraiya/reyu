import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import {
  ComposedChart, Line, Bar, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { chartTooltipStyles } from '../chartTheme'

const SYMBOLS = [
  'NSE:NIFTY50-INDEX', 'NSE:NIFTYBANK-INDEX', 'NSE:FINNIFTY-INDEX',
  'NSE:MIDCPNIFTY-INDEX', 'BSE:SENSEX-INDEX',
]

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d })

type Trade = {
  day: string; side: 'CE' | 'PE'; strike: number
  entry_spot: number; entry_premium: number
  exit_spot: number; exit_premium: number
  pnl_per_unit: number; return_pct: number
}

type Result = {
  symbol: string; strategy: string
  trades: Trade[]
  equity_curve: { day: string; cum_pnl: number; trade: { side: string; pnl: number } | null }[]
  metrics: {
    total_trades: number; cum_pnl: number; win_rate: number
    avg_win: number; avg_loss: number
    sharpe_annualised: number | null; max_drawdown: number
  }
  error?: string
}

export default function Backtest() {
  const [symbol, setSymbol] = useState(SYMBOLS[0])
  const [strategy, setStrategy] = useState('follow_bias')
  const [days, setDays] = useState(30)

  const { data: strategies } = useQuery<{ strategies: { id: string; name: string; description: string }[] }>({
    queryKey: ['bt-strategies'],
    queryFn: async () => (await api.get('/api/backtest/strategies')).data,
  })

  const { data: result, isFetching, refetch } = useQuery<Result>({
    queryKey: ['bt-run', symbol, strategy, days],
    queryFn: async () => (await api.get('/api/backtest/run', { params: { symbol, strategy, days } })).data,
    enabled: false,   // run only on click
  })

  const m = result?.metrics
  const currentStrat = strategies?.strategies.find(s => s.id === strategy)

  return (
    <div className="page-shell">
      <div className="card">
        <div className="card-header">
          <h3>Backtest</h3>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            Replays stored snapshot history against a strategy. Needs ≥1 trading session of data.
          </span>
        </div>
        <div className="row" style={{ alignItems: 'flex-end', gap: 10 }}>
          <Field label="Underlying">
            <select value={symbol} onChange={e => setSymbol(e.target.value)}>
              {SYMBOLS.map(s => <option key={s}>{s}</option>)}
            </select>
          </Field>
          <Field label="Strategy">
            <select value={strategy} onChange={e => setStrategy(e.target.value)}>
              {strategies?.strategies.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
          <Field label="Lookback (days)">
            <input className="input" type="number" min={1} max={365} value={days}
                   onChange={e => setDays(+e.target.value)} style={{ width: 100 }} />
          </Field>
          <button className="primary" onClick={() => refetch()} disabled={isFetching}>
            {isFetching ? 'Replaying…' : 'Run backtest'}
          </button>
        </div>
        {currentStrat && (
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>{currentStrat.description}</div>
        )}
      </div>

      {result?.error && (
        <div className="card bear" style={{ marginTop: 12 }}>{result.error}</div>
      )}

      {result && !result.error && m && (
        <>
          <div className="grid-4" style={{ marginTop: 12 }}>
            <KPI label="Trades" value={m.total_trades} />
            <KPI label="Cum P&L (per unit)" value={`₹${num(m.cum_pnl, 0)}`}
                 tone={m.cum_pnl >= 0 ? 'bull' : 'bear'} />
            <KPI label="Win rate" value={`${(m.win_rate * 100).toFixed(0)}%`} />
            <KPI label="Sharpe (ann.)" value={m.sharpe_annualised ?? '—'} />
          </div>
          <div className="grid-3" style={{ marginTop: 8 }}>
            <KPI label="Avg win" value={`₹${num(m.avg_win, 2)}`} tone="bull" />
            <KPI label="Avg loss" value={`₹${num(m.avg_loss, 2)}`} tone="bear" />
            <KPI label="Max DD" value={`₹${num(m.max_drawdown, 2)}`} tone="bear" />
          </div>

          <div className="card" style={{ marginTop: 12 }}>
            <div className="card-header">
              <h3>Equity curve</h3>
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>cumulative P&L per unit · daily bars</span>
            </div>
            <div style={{ width: '100%', height: 320 }}>
              <ResponsiveContainer>
                <ComposedChart data={result.equity_curve}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="2 3" />
                  <XAxis dataKey="day" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                  <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} />
                  <Tooltip {...chartTooltipStyles()} />
                  <ReferenceLine y={0} stroke="#94a3b8" />
                  <Line type="monotone" dataKey="cum_pnl" stroke="#60a5fa" strokeWidth={2} dot={false} name="Cum P&L" />
                  <Bar dataKey="trade.pnl" name="Day P&L" fill="#16a34a" opacity={0.5} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card" style={{ marginTop: 12 }}>
            <h3>Trades</h3>
            <div style={{ maxHeight: 320, overflow: 'auto' }}>
              <table>
                <thead style={{ position: 'sticky', top: 0, background: 'var(--panel)' }}>
                  <tr>
                    <th>Day</th><th>Side</th><th>Strike</th>
                    <th>Entry spot</th><th>Entry ₹</th>
                    <th>Exit spot</th><th>Exit ₹</th>
                    <th>P&L</th><th>Ret %</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, i) => (
                    <tr key={i}>
                      <td>{t.day}</td>
                      <td className={t.side === 'CE' ? 'bull' : 'bear'}>{t.side}</td>
                      <td>{num(t.strike, 0)}</td>
                      <td>{num(t.entry_spot, 2)}</td>
                      <td>{num(t.entry_premium, 2)}</td>
                      <td>{num(t.exit_spot, 2)}</td>
                      <td>{num(t.exit_premium, 2)}</td>
                      <td className={t.pnl_per_unit >= 0 ? 'bull' : 'bear'}>{num(t.pnl_per_unit, 2)}</td>
                      <td className={t.return_pct >= 0 ? 'bull' : 'bear'}>{num(t.return_pct, 1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</span>
      {children}
    </div>
  )
}

function KPI({ label, value, tone }: { label: string; value: any; tone?: 'bull' | 'bear' }) {
  return (
    <div className="card">
      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</div>
      <div className={`kpi ${tone || ''}`} style={{ marginTop: 4 }}>{value}</div>
    </div>
  )
}

/**
 * PriceCharts — the /charts price terminal (P-02 redesign, task #85).
 *
 * /charts and /chain used to render the same option-chain Dashboard.
 * They now split by job-to-be-done:
 *   /charts — "how is this INSTRUMENT moving?"  → price + indicators
 *   /chain  — "what is the OPTIONS MARKET saying?" → chain terminal
 *
 * Design: symbol + timeframe up top; price area chart with SMA20/50/200
 * overlays; RSI-14 and volume subpanes; intraday shows session hours
 * only; every y-axis scales to the displayed series. One-click
 * hand-offs to Reyu and the strategy templates keep it on the
 * build-your-own-strategy rail (no signals, no recommendations).
 */
import { useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts'
import { api } from '../api'
import { chartTooltipStyles } from '../chartTheme'
import { fmtIST } from '../marketHours'
import PageHelp from '../components/PageHelp'

type Timeframe = '1D' | '5D' | '1M' | '6M' | '1Y'
type CandlesResp = {
  symbol: string
  timeframe: string
  resolution: string
  source: string
  candles: number[][]        // [epoch, o, h, l, c, v]
}

const SYMBOLS = [
  'NSE:NIFTY50-INDEX', 'NSE:NIFTYBANK-INDEX',
  'NSE:RELIANCE-EQ', 'NSE:HDFCBANK-EQ', 'NSE:TCS-EQ', 'NSE:INFY-EQ',
  'NSE:ICICIBANK-EQ', 'NSE:ITC-EQ', 'NSE:SBIN-EQ', 'NSE:TATAMOTORS-EQ',
]
const short = (s: string) => s.replace('NSE:', '').replace('-INDEX', '').replace('-EQ', '')

function sma(closes: number[], i: number, n: number): number | null {
  if (i + 1 < n) return null
  let sum = 0
  for (let j = i - n + 1; j <= i; j++) sum += closes[j]
  return +(sum / n).toFixed(2)
}

function rsi14(closes: number[], i: number): number | null {
  if (i < 14) return null
  let g = 0, l = 0
  for (let j = i - 13; j <= i; j++) {
    const chg = closes[j] - closes[j - 1]
    if (chg >= 0) g += chg; else l -= chg
  }
  if (l === 0) return 100
  const rs = (g / 14) / (l / 14)
  return +(100 - 100 / (1 + rs)).toFixed(1)
}

const S = {
  page: { padding: '18px 28px', maxWidth: 1200, color: 'var(--text-primary, var(--text))' } as CSSProperties,
  toolbar: { display: 'flex', gap: 8, flexWrap: 'wrap' as const, alignItems: 'center', marginBottom: 14 } as CSSProperties,
  chip: (on: boolean): CSSProperties => ({
    padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
    background: on ? 'var(--brand-primary, #f0a020)' : 'var(--bg-elevated, var(--card2))',
    color: on ? '#fff' : 'var(--text-primary, var(--text))',
    border: '1px solid var(--border-default, var(--border))', borderRadius: 999,
  }),
  head: { display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' as const, margin: '6px 0 12px' } as CSSProperties,
  px: { fontSize: 28, fontWeight: 700, fontFamily: 'var(--font-mono)' } as CSSProperties,
  chg: (up: boolean): CSSProperties => ({
    fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)',
    color: up ? 'var(--gain, #2da14b)' : 'var(--danger, #e05252)',
  }),
  card: {
    background: 'var(--bg-surface, var(--card))', border: '1px solid var(--border-default, var(--border))',
    borderRadius: 10, padding: '12px 14px', marginBottom: 12,
  } as CSSProperties,
  cardTitle: { fontSize: 11, fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase' as const, color: 'var(--text-muted, var(--muted))', marginBottom: 6 } as CSSProperties,
  legend: { display: 'flex', gap: 14, fontSize: 11, color: 'var(--text-secondary, var(--muted))', marginBottom: 4 } as CSSProperties,
  action: {
    padding: '7px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
    background: 'var(--bg-elevated, var(--card2))', color: 'var(--text-primary, var(--text))',
    border: '1px solid var(--border-default, var(--border))', borderRadius: 8,
  } as CSSProperties,
  empty: { padding: 60, textAlign: 'center' as const, color: 'var(--text-secondary, var(--muted))' } as CSSProperties,
}

export default function PriceCharts() {
  const nav = useNavigate()
  const [symbol, setSymbol] = useState('NSE:NIFTY50-INDEX')
  const [tf, setTf] = useState<Timeframe>('1M')

  const { data, isLoading, isError } = useQuery<CandlesResp>({
    queryKey: ['candles', symbol, tf],
    queryFn: async () =>
      (await api.get('/api/market/candles', { params: { symbol, timeframe: tf } })).data,
    refetchInterval: tf === '1D' ? 60_000 : false,
  })

  const rows = useMemo(() => {
    const candles = data?.candles || []
    const closes = candles.map(c => c[4])
    const daily = data?.resolution === 'D'
    return candles.map((c, i) => ({
      ts: c[0],
      label: daily
        ? new Date(c[0] * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' })
        : fmtIST(new Date(c[0] * 1000).toISOString()),
      close: +c[4].toFixed(2),
      volume: c[5] || 0,
      sma20: sma(closes, i, 20),
      sma50: sma(closes, i, 50),
      sma200: sma(closes, i, 200),
      rsi: rsi14(closes, i),
    }))
  }, [data])

  const last = rows.at(-1)
  const first = rows[0]
  const chg = last && first ? last.close - first.close : 0
  const chgPct = last && first && first.close ? (chg / first.close) * 100 : 0
  const showSma = data?.resolution === 'D'

  return (
    <div style={S.page}>
      <PageHelp pageId="charts" />

      <div style={S.toolbar}>
        {SYMBOLS.map(s => (
          <button key={s} style={S.chip(s === symbol)} onClick={() => setSymbol(s)}>
            {short(s)}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        {(['1D', '5D', '1M', '6M', '1Y'] as Timeframe[]).map(t => (
          <button key={t} style={S.chip(t === tf)} onClick={() => setTf(t)}>{t}</button>
        ))}
      </div>

      <div style={S.head}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>{short(symbol)}</h1>
        {last && (
          <>
            <span style={S.px}>{last.close.toLocaleString('en-IN')}</span>
            <span style={S.chg(chg >= 0)}>
              {chg >= 0 ? '▲' : '▼'} {Math.abs(chg).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
              {' '}({chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%) over {tf}
            </span>
          </>
        )}
        <span style={{ flex: 1 }} />
        <button style={S.action} onClick={() => nav(`/?ask=${encodeURIComponent(`Technical analysis of ${short(symbol)}`)}`)}>
          🤖 Ask Reyu about {short(symbol)}
        </button>
        <button style={S.action} onClick={() => nav('/templates?persona=swing_equity')}>
          🧩 Build a strategy on it
        </button>
        {symbol.endsWith('-INDEX') && (
          <button style={S.action} onClick={() => nav('/chain')}>⛓ Option chain</button>
        )}
      </div>

      {isLoading && <div style={S.empty}>Loading candles…</div>}
      {isError && <div style={S.empty}>No data for {short(symbol)} — broker auth may be down.</div>}

      {!isLoading && rows.length > 0 && (
        <>
          {/* Price + SMA overlays */}
          <div style={S.card}>
            <div style={S.cardTitle}>Price ({data?.resolution}) · source {data?.source}</div>
            {showSma && (
              <div style={S.legend}>
                <span style={{ color: '#60a5fa' }}>— SMA20</span>
                <span style={{ color: '#f59e0b' }}>— SMA50</span>
                <span style={{ color: '#a78bfa' }}>— SMA200</span>
              </div>
            )}
            <div style={{ width: '100%', height: 300 }}>
              <ResponsiveContainer>
                <AreaChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id="pxfill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--brand-primary, #f0a020)" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="var(--brand-primary, #f0a020)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#33415522" />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#94a3b8' }} minTickGap={40} />
                  <YAxis domain={['dataMin', 'dataMax']} tick={{ fontSize: 10, fill: '#94a3b8' }}
                         tickFormatter={(v: number) => v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                         width={64} />
                  <Tooltip {...chartTooltipStyles()} />
                  <Area type="monotone" dataKey="close" name="Close"
                        stroke="var(--brand-primary, #f0a020)" fill="url(#pxfill)" dot={false} strokeWidth={2} />
                  {showSma && <Area type="monotone" dataKey="sma20" name="SMA20" stroke="#60a5fa" fill="none" dot={false} />}
                  {showSma && <Area type="monotone" dataKey="sma50" name="SMA50" stroke="#f59e0b" fill="none" dot={false} />}
                  {showSma && <Area type="monotone" dataKey="sma200" name="SMA200" stroke="#a78bfa" fill="none" dot={false} />}
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* RSI */}
          {showSma && (
            <div style={S.card}>
              <div style={S.cardTitle}>RSI-14</div>
              <div style={{ width: '100%', height: 120 }}>
                <ResponsiveContainer>
                  <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#94a3b8' }} minTickGap={40} />
                    <YAxis domain={[0, 100]} ticks={[30, 50, 70]} tick={{ fontSize: 10, fill: '#94a3b8' }} width={64} />
                    <Tooltip {...chartTooltipStyles()} />
                    <ReferenceLine y={70} stroke="#e0525266" strokeDasharray="3 3" />
                    <ReferenceLine y={30} stroke="#2da14b66" strokeDasharray="3 3" />
                    <Line type="monotone" dataKey="rsi" name="RSI" stroke="#63dcd2" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Volume */}
          <div style={S.card}>
            <div style={S.cardTitle}>Volume</div>
            <div style={{ width: '100%', height: 110 }}>
              <ResponsiveContainer>
                <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#94a3b8' }} minTickGap={40} />
                  <YAxis domain={[0, 'dataMax']} tick={{ fontSize: 10, fill: '#94a3b8' }} width={64}
                         tickFormatter={(v: number) => v >= 1e7 ? `${(v / 1e7).toFixed(1)}Cr` : v >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : `${(v / 1e3).toFixed(0)}k`} />
                  <Tooltip {...chartTooltipStyles()} />
                  <Bar dataKey="volume" name="Volume" fill="#60a5fa88" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <p style={{ fontSize: 11, color: 'var(--text-muted, var(--muted))' }}>
            Data for study — intraday shows NSE session hours only. Reyu doesn't recommend
            trades; build and test your own view from <a href="/templates" style={{ color: 'var(--brand-primary, #f0a020)' }}>Templates</a>.
          </p>
        </>
      )}
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { useLiveTicks } from '../hooks/useLiveTicks'
import { api } from '../api'

const SYMBOLS = [
  { label: 'NIFTY',     symbol: 'NSE:NIFTY50-INDEX' },
  { label: 'BANKNIFTY', symbol: 'NSE:NIFTYBANK-INDEX' },
  { label: 'FINNIFTY',  symbol: 'NSE:FINNIFTY-INDEX' },
  { label: 'SENSEX',    symbol: 'BSE:SENSEX-INDEX' },
]

type QuoteRow = { n: string; s: string; v?: { lp?: number; ch?: number; chp?: number } }

const fmt = (n: number | undefined, d = 2) =>
  n == null ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d })

export default function MarketTicker() {
  // REST fallback for initial data + change %
  const { data } = useQuery<{ d?: QuoteRow[] }>({
    queryKey: ['ticker', SYMBOLS.map(s => s.symbol).join(',')],
    queryFn: async () =>
      (await api.get('/api/options/quotes', { params: { symbols: SYMBOLS.map(s => s.symbol).join(',') } })).data,
    refetchInterval: 15000,
    staleTime: 5000,
  })

  // WebSocket live price updates
  const { status, ticks } = useLiveTicks(SYMBOLS.map(s => s.symbol))

  const rows = data?.d || []
  const restLookup: Record<string, QuoteRow['v']> = {}
  for (const r of rows) restLookup[r.n] = r.v

  return (
    <section className="ticker-strip">
      {SYMBOLS.map(s => {
        const rest = restLookup[s.symbol]
        const live = ticks[s.symbol]
        // Use live tick price if available, otherwise fall back to REST
        const lp = live?.close ?? rest?.lp
        const chp = rest?.chp ?? 0
        return (
          <div key={s.symbol} className="ticker-item">
            <span className="ticker-label">{s.label}</span>
            <span className="ticker-value">{fmt(lp)}</span>
            <span className={`ticker-change ${chp >= 0 ? 'positive' : 'negative'}`}>
              {chp >= 0 ? '+' : ''}{fmt(chp, 2)}%
            </span>
            {status === 'connected' && live && lp != null && rest?.lp != null && lp !== rest.lp && (
              <span className="ticker-flash" style={{
                width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
                background: lp >= (rest?.lp ?? 0) ? 'var(--green)' : 'var(--red)',
                marginLeft: 4, verticalAlign: 'middle', animation: 'ticker-pulse 0.6s ease-out',
              }} />
            )}
          </div>
        )
      })}
      <div className="ticker-status" style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: 'var(--muted)' }}>
        <span style={{
          width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
          background: status === 'connected' ? 'var(--green)' : status === 'connecting' ? 'var(--yellow)' : 'var(--red)',
        }} />
        {status === 'connected' ? 'LIVE' : status === 'connecting' ? 'Connecting…' : 'Offline'}
      </div>
    </section>
  )
}

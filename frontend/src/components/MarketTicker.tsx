import { useQuery } from '@tanstack/react-query'
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
  const { data } = useQuery<{ d?: QuoteRow[] }>({
    queryKey: ['ticker', SYMBOLS.map(s => s.symbol).join(',')],
    queryFn: async () =>
      (await api.get('/api/options/quotes', { params: { symbols: SYMBOLS.map(s => s.symbol).join(',') } })).data,
    refetchInterval: 10000,
    staleTime: 5000,
  })

  const rows = data?.d || []
  const lookup: Record<string, QuoteRow['v']> = {}
  for (const r of rows) lookup[r.n] = r.v

  return (
    <section className="ticker-strip">
      {SYMBOLS.map(s => {
        const v = lookup[s.symbol]
        const chp = v?.chp ?? 0
        return (
          <div key={s.symbol} className="ticker-item">
            <span className="ticker-label">{s.label}</span>
            <span className="ticker-value">{fmt(v?.lp)}</span>
            <span className={`ticker-change ${chp >= 0 ? 'positive' : 'negative'}`}>
              {chp >= 0 ? '+' : ''}{fmt(chp, 2)}%
            </span>
          </div>
        )
      })}
    </section>
  )
}

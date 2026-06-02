import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, Chain } from '../api'
import OptionChainTable from '../components/OptionChainTable'
import SummaryStrip from '../components/SummaryStrip'
import OIChart from '../components/OIChart'
import HedgeBuilder from '../components/HedgeBuilder'
import PCRTimeSeries from '../components/PCRTimeSeries'
import OrderModal from '../components/OrderModal'
import IVSmile from '../components/IVSmile'
import GreeksHeatmap from '../components/GreeksHeatmap'
import KeyLevelsStrip from '../components/KeyLevelsStrip'
import RecommendationPanel from '../components/RecommendationPanel'
import FilterBar from '../components/FilterBar'
import OITimeSeries from '../components/OITimeSeries'
import OIBuildup from '../components/OIBuildup'
import StrikeDetailPanel from '../components/StrikeDetailPanel'
import { LoadingSkeleton } from '../components/LoadingStates'
import { useToast } from '../toast'
import { downloadCSV } from '../utils/csv'

const SYMBOL_GROUPS = [
  { label: 'NIFTY', value: 'NSE:NIFTY50-INDEX' },
  { label: 'BANKNIFTY', value: 'NSE:BANKNIFTY-INDEX' },
  { label: 'FINNIFTY', value: 'NSE:FINNIFTY-INDEX' },
]

const POPULAR_SYMBOLS = [
  'NSE:NIFTY50-INDEX',
  'NSE:BANKNIFTY-INDEX',
  'NSE:FINNIFTY-INDEX',
  'NSE:MIDCPNIFTY-INDEX',
  'BSE:SENSEX-INDEX',
]

type OptionChainTableTradableProps = {
  chain: Chain
  onTrade: (s: string, side: 'BUY' | 'SELL', p?: number) => void
  onSelectionChange: (selected: number[]) => void
  onStrategyBuild: (selected: number[]) => void
  onHoverStrike?: (strike: number | null) => void
}

function OptionChainTableTradable({ chain, onTrade, onSelectionChange, onStrategyBuild, onHoverStrike }: OptionChainTableTradableProps) {
  return (
    <div>
      <OptionChainTable chain={chain} onSelectionChange={onSelectionChange} onStrategyBuild={onStrategyBuild} onHoverStrike={onHoverStrike} />
      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)' }}>
        Quick trade ATM:
        {(() => {
          const atm = chain.strikes.find(s => s.strike === chain.summary.atm_strike)
          if (!atm) return ' —'
          return (
            <span style={{ marginLeft: 8 }}>
              {atm.ce && <button className="primary" style={{ marginRight: 6, background: 'var(--green)', borderColor: 'var(--green)', color: '#fff' }}
                      onClick={() => onTrade(atm.ce!.symbol!, 'BUY', atm.ce!.ltp)}>BUY CE @ {atm.ce.ltp}</button>}
              {atm.pe && <button className="primary" style={{ background: 'var(--red)', borderColor: 'var(--red)', color: '#fff' }}
                      onClick={() => onTrade(atm.pe!.symbol!, 'BUY', atm.pe!.ltp)}>BUY PE @ {atm.pe.ltp}</button>}
            </span>
          )
        })()}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const t = useToast()
  const navigate = useNavigate()
  const [symbol, setSymbol] = useState('NSE:NIFTY50-INDEX')
  const [input, setInput] = useState(symbol)
  const [strikes, setStrikes] = useState(25)
  const [expiry, setExpiry] = useState('')
  const [oiWindow, setOiWindow] = useState(15)
  const [oiSeriesInterval, setOiSeriesInterval] = useState<'5m' | '15m'>('5m')
  const [oiSeriesMinutes, setOiSeriesMinutes] = useState(240)
  const [order, setOrder] = useState<{ symbol: string; side: 'BUY' | 'SELL'; price?: number } | null>(null)
  const [searchHistory, setSearchHistory] = useState<string[]>([])
  const [selectedStrikes, setSelectedStrikes] = useState<number[]>([])
  const [hoverStrike, setHoverStrike] = useState<number | null>(null)

  const { data, isFetching, error, refetch } = useQuery<Chain>({
    queryKey: ['chain', symbol, strikes, expiry],
    queryFn: async () => (await api.get('/api/options/chain', { params: { symbol, strikecount: strikes, expiry } })).data,
    refetchInterval: 15000,
  })

  const currentSymbol = useMemo(() => SYMBOL_GROUPS.find(item => item.value === symbol) ?? SYMBOL_GROUPS[0], [symbol])
  const symbolSuggestions = useMemo(() => {
    const query = input.trim().toUpperCase()
    if (!query) return []
    return [...new Set([...searchHistory, ...POPULAR_SYMBOLS])]
      .filter(item => item.toUpperCase().includes(query))
      .slice(0, 6)
  }, [input, searchHistory])

  useEffect(() => {
    const saved = localStorage.getItem('dashboard_search_history')
    if (saved) {
      try {
        setSearchHistory(JSON.parse(saved))
      } catch {
        setSearchHistory([])
      }
    }
  }, [])

  const saveSearchHistory = (value: string) => {
    const normalized = value.trim()
    if (!normalized) return
    setSearchHistory(prev => {
      const next = [normalized, ...prev.filter(item => item !== normalized)].slice(0, 6)
      localStorage.setItem('dashboard_search_history', JSON.stringify(next))
      return next
    })
  }

  const track = async () => {
    await api.post('/api/ts/track', null, { params: { symbol, tracked: true } })
    t.push('success', `Tracking ${symbol} — snapshots will start within ~60s.`)
  }

  const expiryOptions = data?.expiries ?? []
  const expiryLabel = expiryOptions.find(e => String(e.expiry) === expiry)?.date || (expiry ? expiry : 'Current')

  const exportChain = () => {
    if (!data) return
    downloadCSV(`${symbol}-chain.csv`, data.strikes.map(s => ({
      strike: s.strike,
      ce_ltp: s.ce?.ltp, ce_oi: s.ce?.oi, ce_oi_change: s.ce?.oi_change, ce_iv: s.ce?.iv, ce_delta: s.ce?.delta,
      pe_ltp: s.pe?.ltp, pe_oi: s.pe?.oi, pe_oi_change: s.pe?.oi_change, pe_iv: s.pe?.iv, pe_delta: s.pe?.delta,
    })))
  }

  return (
    <div className="page-shell">
      <div className="page-toolbar">
        <FilterBar
          title="Option Chain"
          searchValue={input}
          onSearch={setInput}
          onSearchFocus={() => undefined}
          onClearAll={() => setInput('')}
          filters={SYMBOL_GROUPS.map(item => ({
            label: item.label,
            active: item.value === symbol,
            onClick: () => {
              setSymbol(item.value)
              setInput(item.value)
              saveSearchHistory(item.value)
            },
          }))}
          suggestions={symbolSuggestions}
          onSuggestionClick={value => {
            setSymbol(value)
            setInput(value)
            saveSearchHistory(value)
          }}
          rightContent={(
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button className="primary" onClick={() => { setSymbol(input); saveSearchHistory(input) }}>Load</button>
              <button className="ghost" onClick={() => refetch()}>{isFetching ? 'Refreshing…' : 'Refresh'}</button>
            </div>
          )}
        />
      </div>

      <div className="grid-3">
        <div className="col">
          <div className="card-glass">
            <div className="card-header"><h3>Market</h3></div>
            <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
              <div className="stat-card">
                <div className="stat-label">Active Symbol</div>
                <div className="stat-value">{currentSymbol.label}</div>
                <div className="stat-meta">{symbol}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Strike Width</div>
                <div className="stat-value">{strikes}</div>
                <div className="stat-meta">Visible strikes</div>
              </div>
            </div>
            <div className="row" style={{ gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>Expiry</span>
                <select value={expiry} onChange={e => setExpiry(e.target.value)} style={{ minWidth: 160 }}>
                  <option value="">Current</option>
                  {expiryOptions.map(exp => (
                    <option key={exp.expiry} value={exp.expiry}>{exp.date}</option>
                  ))}
                </select>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>Strike window</span>
                <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                  {[5, 15, 25, 40].map(size => (
                    <button key={size} className={oiWindow === size ? 'primary' : 'ghost'} onClick={() => setOiWindow(size)} style={{ padding: '6px 10px', fontSize: 11 }}>
                      {size}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
        {data ? (
          <>
            <div className="col">
              <RecommendationPanel chain={data} onApply={() => navigate(`/strategy?underlying=${encodeURIComponent(symbol)}`)} />
            </div>
            <div className="col">
              <KeyLevelsStrip chain={data} />
            </div>
          </>
        ) : (
          <div className="col"><LoadingSkeleton /></div>
        )}
      </div>

      {/* KPI strip — full width, prominent */}
      {data && <SummaryStrip chain={data} />}

      {/* Analytical charts — three equal-weight cards */}
      {data && (
        <div className="grid-3">
          <div className="col"><IVSmile chain={data} /></div>
          <div className="col"><GreeksHeatmap chain={data} /></div>
          <div className="col">
            <div className="card">
              <div className="card-header"><h3>OI Distribution</h3></div>
              <OIChart chain={data} windowSize={oiWindow} />
            </div>
          </div>
        </div>
      )}

      {/* OI Build-up — full-width when the Hedge Builder lives at the bottom */}
      {data && (
        <div className="card">
          <div className="card-header"><h3>OI Build-up (ATM ± 4)</h3></div>
          <OIBuildup chain={data} window={4} />
        </div>
      )}

      {/* Option chain (scrolling) + sticky Strike Detail rail */}
      <div className="grid-main">
        <div className="col">
          <div className="card">
            <div className="card-header"><h3>Option Chain — hover any row for live context · click ATM CE/PE to trade</h3></div>
            {data ? (
              <OptionChainTableTradable
                chain={data}
                onTrade={(sym, side, price) => setOrder({ symbol: sym, side, price })}
                onSelectionChange={setSelectedStrikes}
                onHoverStrike={setHoverStrike}
                onStrategyBuild={(selected) => {
                  setSelectedStrikes(selected)
                  if (selected.length > 0) {
                    navigate(`/strategy?underlying=${encodeURIComponent(symbol)}&selected=${selected.join(',')}${expiry ? `&expiry=${encodeURIComponent(expiry)}` : ''}`)
                  }
                }}
              />
            ) : (
              <LoadingSkeleton />
            )}
          </div>
        </div>

        <aside className="col sticky-rail">
          {data ? <StrikeDetailPanel chain={data} strike={hoverStrike} /> : <LoadingSkeleton />}
        </aside>
      </div>

      {/* Intraday time-series — today's session, switchable to a specific option leg */}
      <div className="card">
        <div className="card-header">
          <h3>Intraday Time-Series — today's session (09:15 IST → now)</h3>
          <div className="row" style={{ gap: 6 }}>
            <select value={oiSeriesInterval} onChange={e => setOiSeriesInterval(e.target.value as '5m' | '15m')}>
              <option value="5m">5m</option><option value="15m">15m</option>
            </select>
          </div>
        </div>
        <OITimeSeries symbol={symbol} chain={data} interval={oiSeriesInterval} />
      </div>

      {/* Hedge Builder — anchored at bottom */}
      {data && <HedgeBuilder underlying={symbol} chain={data} />}

      {!data && isFetching && <LoadingSkeleton />}

      {order && (
        <OrderModal symbol={order.symbol} side={order.side} defaultPrice={order.price}
                    onClose={() => setOrder(null)} />
      )}
    </div>
  )
}


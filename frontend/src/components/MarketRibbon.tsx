/**
 * MarketRibbon — persistent top bar with live prices, VIX, expiry countdown, broker status.
 *
 * Always visible. Auto-refreshes every 30s.
 * Scrolls horizontally on mobile — no wrapping.
 */
import React, { useState, useEffect, useRef } from 'react'
import { api } from '../context/AuthContext'

interface RibbonTick {
  symbol: string
  label: string
  ltp: number
  change: number
  changePct: number
}

interface BrokerStatus {
  broker_id: string
  name: string
  connected: boolean
}

const BASE_URL = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const WATCH_SYMBOLS = [
  { symbol: 'NSE:NIFTY50-INDEX',  label: 'NIFTY' },
  { symbol: 'NSE:NIFTYBANK-INDEX', label: 'BANKNIFTY' },
  { symbol: 'NSE:FINNIFTY-INDEX',  label: 'FINNIFTY' },
  { symbol: 'NSE:INDIA VIX-INDEX', label: 'VIX' },
]

export function MarketRibbon() {
  const [ticks, setTicks]           = useState<RibbonTick[]>([])
  const [brokers, setBrokers]       = useState<BrokerStatus[]>([])
  const [expiryIn, setExpiryIn]     = useState<string>('')
  const [marketOpen, setMarketOpen] = useState<boolean | null>(null)
  const [demo, setDemo]             = useState(false)
  const intervalRef                 = useRef<ReturnType<typeof setInterval> | null>(null)

  async function fetchTicks() {
    try {
      // Public endpoint — no auth needed, works for anonymous users too
      const resp = await fetch(`${BASE_URL}/api/market/ticks`)
      if (!resp.ok) return
      const data = await resp.json()
      const raw: any[] = data.ticks || []
      setDemo(data.demo ?? false)
      const enriched: RibbonTick[] = raw.map((q: any) => {
        const change = q.ltp - (q.close || q.ltp)
        return {
          symbol:    q.symbol,
          label:     q.label ?? q.symbol.split(':')[1],
          ltp:       q.ltp,
          change,
          changePct: q.close ? (change / q.close) * 100 : 0,
        }
      })
      setTicks(enriched)
    } catch {}
  }

  async function fetchBrokers() {
    try {
      const resp = await api.get('/api/brokers/connected')
      const connected: BrokerStatus[] = (resp.data.brokers || []).map((b: any) => ({
        broker_id: b.broker_id,
        name: b.broker_id.charAt(0).toUpperCase() + b.broker_id.slice(1),
        connected: b.status === 'connected',
      }))
      setBrokers(connected)
    } catch {}
  }

  function calcExpiry() {
    // NSE weekly expiry is Thursday; monthly is last Thursday
    const now  = new Date()
    const day  = now.getDay() // 0=Sun … 4=Thu
    const daysUntilThursday = (4 - day + 7) % 7 || 7
    const expiry = new Date(now)
    expiry.setDate(now.getDate() + daysUntilThursday)
    expiry.setHours(15, 30, 0, 0)
    const diff = expiry.getTime() - Date.now()
    if (diff <= 0) {
      setExpiryIn('Expired')
      return
    }
    const d = Math.floor(diff / 86_400_000)
    const h = Math.floor((diff % 86_400_000) / 3_600_000)
    const m = Math.floor((diff % 3_600_000)  / 60_000)
    setExpiryIn(d > 0 ? `${d}d ${h}h` : `${h}h ${m}m`)
  }

  function checkMarketHours() {
    const now = new Date()
    const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
    const h = ist.getHours(), m = ist.getMinutes(), day = ist.getDay()
    const open = day >= 1 && day <= 5 && (h > 9 || (h === 9 && m >= 15)) && (h < 15 || (h === 15 && m <= 30))
    setMarketOpen(open)
  }

  useEffect(() => {
    fetchTicks()
    fetchBrokers()
    calcExpiry()
    checkMarketHours()
    intervalRef.current = setInterval(() => {
      fetchTicks()
      calcExpiry()
      checkMarketHours()
    }, 10_000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [])

  return (
    <header className="market-ribbon">
      {/* Market status dot */}
      <div className="ribbon-status">
        <span className={`status-dot ${marketOpen ? 'status-live' : 'status-closed'}`} />
        <span className="status-label">{marketOpen ? 'Live' : 'Closed'}</span>
        {demo && <span className="ribbon-badge demo-badge">DEMO</span>}
      </div>

      {/* Scrollable ticks */}
      <div className="ribbon-ticks" role="marquee" aria-live="off">
        {ticks.length === 0
          ? WATCH_SYMBOLS.map(s => (
              <TickSkeleton key={s.label} label={s.label} />
            ))
          : ticks.map(t => <TickCell key={t.symbol} tick={t} />)
        }
      </div>

      {/* Right section: expiry + brokers */}
      <div className="ribbon-right">
        {expiryIn && (
          <div className="ribbon-expiry" title="Next weekly expiry (NSE Thu 3:30 PM)">
            <span className="expiry-icon">⌛</span>
            <span>{expiryIn}</span>
          </div>
        )}
        {brokers.length > 0 && (
          <div className="ribbon-brokers">
            {brokers.map(b => (
              <span key={b.broker_id} className="broker-pill broker-pill-connected" title={`${b.name} connected`}>
                {b.name[0]}
              </span>
            ))}
          </div>
        )}
      </div>
    </header>
  )
}

function TickCell({ tick }: { tick: RibbonTick }) {
  const pos = tick.change >= 0
  return (
    <div className={`ribbon-tick ${pos ? 'tick-up' : 'tick-down'}`}>
      <span className="tick-label">{tick.label}</span>
      <span className="tick-ltp">{tick.ltp.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
      <span className="tick-change">
        {pos ? '▲' : '▼'} {Math.abs(tick.changePct).toFixed(2)}%
      </span>
    </div>
  )
}

function TickSkeleton({ label }: { label: string }) {
  return (
    <div className="ribbon-tick tick-skeleton">
      <span className="tick-label">{label}</span>
      <span className="skeleton-bar" style={{ width: 64, height: 14 }} />
    </div>
  )
}

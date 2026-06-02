/**
 * Three small visuals used by the Strategy Builder header:
 *   - detectStrategyName(legs)  → human-friendly label (Bull Call Spread, Iron Condor…)
 *   - <RiskMeter />             → horizontal gauge classifying margin/maxloss ratio
 *   - <PopGauge />              → circular probability-of-profit dial
 */
import { useMemo } from 'react'

type Leg = {
  action: 'BUY' | 'SELL'
  qty: number
  strike?: number
  option_type?: 'CE' | 'PE'
}

export function detectStrategyName(legs: Leg[]): string {
  const opts = legs.filter(l => l.option_type === 'CE' || l.option_type === 'PE')
  if (opts.length === 0) return 'Custom'
  if (opts.length === 1) {
    const l = opts[0]
    return `Long ${l.option_type}` // covers naked buy/sell single options
      .replace('Long', l.action === 'BUY' ? 'Long' : 'Short')
  }
  const ce = opts.filter(l => l.option_type === 'CE')
  const pe = opts.filter(l => l.option_type === 'PE')
  const sameStrike = (a: Leg, b: Leg) => a.strike === b.strike
  const buys = opts.filter(l => l.action === 'BUY')
  const sells = opts.filter(l => l.action === 'SELL')

  // Straddle / Strangle
  if (opts.length === 2 && ce.length === 1 && pe.length === 1 &&
      ce[0].action === pe[0].action) {
    const dir = ce[0].action === 'BUY' ? 'Long' : 'Short'
    return sameStrike(ce[0], pe[0]) ? `${dir} Straddle` : `${dir} Strangle`
  }

  // Vertical spread: 2 legs same option type, opposite actions
  if (opts.length === 2 && (ce.length === 2 || pe.length === 2) &&
      buys.length === 1 && sells.length === 1) {
    const k = ce.length === 2 ? 'CE' : 'PE'
    const buy = buys[0], sell = sells[0]
    if (k === 'CE') return (buy.strike ?? 0) < (sell.strike ?? 0) ? 'Bull Call Spread' : 'Bear Call Spread'
    return (buy.strike ?? 0) > (sell.strike ?? 0) ? 'Bear Put Spread' : 'Bull Put Spread'
  }

  // Iron Condor / Butterfly
  if (opts.length === 4) {
    if (ce.length === 2 && pe.length === 2 && buys.length === 2 && sells.length === 2) {
      return 'Iron Condor'
    }
    const strikes = new Set(opts.map(l => l.strike))
    if (strikes.size === 3) return 'Butterfly'
  }

  if (opts.length === 3 && buys.length === 1 && sells.length === 2) return 'Ratio Spread'

  return `${opts.length}-leg Custom`
}

export function RiskMeter({ maxLoss, margin }: { maxLoss: number; margin: number }) {
  // Risk score: 0 (conservative) → 1 (aggressive)
  // Heuristic — large margin and unbounded loss tilt toward aggressive
  const score = useMemo(() => {
    if (!margin) return 0
    const ratio = Math.min(Math.abs(maxLoss) / margin, 2)
    return Math.min(1, Math.max(0, ratio / 2))
  }, [maxLoss, margin])
  const pct = score * 100
  const label = score < 0.33 ? 'Conservative' : score < 0.66 ? 'Moderate' : 'Aggressive'
  const colour = score < 0.33 ? 'var(--green)' : score < 0.66 ? 'var(--amber)' : 'var(--red)'

  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Risk profile</div>
      <div style={{ position: 'relative', height: 8, borderRadius: 999, background: 'var(--border)', overflow: 'hidden' }}>
        <div style={{
          position: 'absolute', inset: 0, width: `${pct}%`,
          background: `linear-gradient(90deg, var(--green), var(--amber) 50%, var(--red))`,
          transition: 'width .5s ease',
        }} />
        <div style={{
          position: 'absolute', top: -3, left: `calc(${pct}% - 6px)`,
          width: 12, height: 14, background: 'var(--text)', borderRadius: 3, border: '2px solid var(--bg)',
        }} />
      </div>
      <div className="row" style={{ justifyContent: 'space-between', fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>
        <span>Conservative</span><strong style={{ color: colour }}>{label}</strong><span>Aggressive</span>
      </div>
    </div>
  )
}

export function PopGauge({ pop }: { pop: number | null | undefined }) {
  // pop in [0, 1]
  const p = pop == null ? 0 : Math.max(0, Math.min(1, pop))
  const r = 36
  const c = 2 * Math.PI * r
  const dash = c * p
  const colour = p >= 0.6 ? 'var(--green)' : p >= 0.4 ? 'var(--amber)' : 'var(--red)'

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
      <svg width="92" height="92" viewBox="0 0 92 92">
        <circle cx="46" cy="46" r={r} fill="none" stroke="var(--border)" strokeWidth="8" />
        <circle cx="46" cy="46" r={r} fill="none" stroke={colour} strokeWidth="8" strokeLinecap="round"
                strokeDasharray={`${dash} ${c}`} transform="rotate(-90 46 46)"
                style={{ transition: 'stroke-dasharray .5s ease' }} />
        <text x="46" y="48" textAnchor="middle" dominantBaseline="middle"
              fill="var(--text)" fontSize="18" fontWeight="700">
          {pop == null ? '—' : `${Math.round(p * 100)}%`}
        </text>
        <text x="46" y="64" textAnchor="middle" fill="var(--muted)" fontSize="9">POP</text>
      </svg>
      <span style={{ fontSize: 11, color: 'var(--muted)' }}>Probability of Profit</span>
    </div>
  )
}

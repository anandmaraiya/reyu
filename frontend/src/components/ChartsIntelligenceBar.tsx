/**
 * Charts Intelligence Bar — CPO redesign top-of-page.
 *
 * Philosophy: every element does one of three things — explain, act, drill.
 * No dumb data-viewers.
 *
 * Layout (top → bottom):
 *   1. Regime pill (persistent) — what the platform would do today
 *   2. Three KPI tiles — Spot & change | AI bias | Regime action
 *   3. Three insight cards — auto-generated from chain data
 *      (Highest OI shift · Max Pain distance · Unusual OI writing)
 *   4. Quick actions — "Ask Reyu about this chain" · "Build strategy" · "Watch"
 *
 * Consumed by both retail (beginner labels + plain-English) and HNI (raw
 * numbers, drill-down affordances).
 */
import type { CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Chain } from '../api'
import { track, Events } from '../telemetry'

type Props = {
  chain: Chain | undefined
  spot: number | undefined
  prevClose: number | undefined
  loading: boolean
  onAskReyu?: (query: string) => void
  onBuildStrategy?: () => void
}

const S = {
  wrap: {
    marginBottom: 24,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 12,
  } as CSSProperties,
  regimePill: (bias: 'BULL' | 'BEAR' | 'RANGE' | 'UNCLEAR'): CSSProperties => {
    const map = {
      BULL:    { bg: 'var(--brand-light)',  fg: 'var(--brand-text)',  border: 'var(--border-brand)' },
      BEAR:    { bg: 'var(--danger-light)', fg: 'var(--danger-text)', border: 'var(--danger)' },
      RANGE:   { bg: 'var(--signal-light)', fg: 'var(--signal-text)', border: 'var(--signal)' },
      UNCLEAR: { bg: 'var(--bg-sunken)',    fg: 'var(--text-secondary)', border: 'var(--border-default)' },
    }[bias]
    return {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 10,
      padding: '8px 14px',
      background: map.bg,
      color: map.fg,
      border: `1px solid ${map.border}`,
      borderRadius: 'var(--radius-full)',
      fontSize: 12,
      fontWeight: 600,
      alignSelf: 'flex-start' as const,
    }
  },
  regimeDot: (color: string): CSSProperties => ({
    width: 8, height: 8, borderRadius: 4, background: color,
    animation: 'pulse-dot 1.6s ease-in-out infinite',
  }),
  hero: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: 12,
  } as CSSProperties,
  heroCard: {
    padding: 16,
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-md)',
    boxShadow: 'var(--shadow-sm)',
  } as CSSProperties,
  heroLabel: {
    fontSize: 10,
    letterSpacing: '0.06em',
    color: 'var(--text-secondary)',
    textTransform: 'uppercase' as const,
    fontWeight: 600,
    marginBottom: 6,
  } as CSSProperties,
  heroValue: {
    fontSize: 26,
    fontWeight: 700,
    fontFeatureSettings: '"tnum"',
    lineHeight: 1,
  } as CSSProperties,
  heroSubtitle: {
    fontSize: 12,
    color: 'var(--text-secondary)',
    marginTop: 6,
    lineHeight: 1.4,
  } as CSSProperties,
  insights: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
    gap: 12,
  } as CSSProperties,
  insightCard: {
    padding: 14,
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-subtle)',
    borderRadius: 'var(--radius-md)',
    display: 'flex',
    gap: 12,
    alignItems: 'flex-start',
  } as CSSProperties,
  insightIcon: {
    fontSize: 20,
    width: 32,
    minWidth: 32,
    height: 32,
    borderRadius: 8,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'var(--brand-light)',
  } as CSSProperties,
  insightTitle: {
    fontSize: 11,
    color: 'var(--text-secondary)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    fontWeight: 600,
  } as CSSProperties,
  insightBody: {
    fontSize: 13,
    color: 'var(--text-primary)',
    marginTop: 2,
    lineHeight: 1.4,
    fontWeight: 500,
  } as CSSProperties,
  insightMeta: {
    fontSize: 11,
    color: 'var(--text-muted)',
    marginTop: 3,
  } as CSSProperties,
  quickActions: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap' as const,
  } as CSSProperties,
  quickBtn: {
    padding: '8px 14px',
    fontSize: 12,
    fontWeight: 600,
    background: 'var(--bg-elevated)',
    color: 'var(--text-primary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
  } as CSSProperties,
  quickBtnPrimary: {
    padding: '8px 14px',
    fontSize: 12,
    fontWeight: 600,
    background: 'var(--brand-primary)',
    color: '#fff',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
  } as CSSProperties,
  skel: {
    height: 96, background: 'var(--bg-sunken)', borderRadius: 'var(--radius-md)',
    animation: 'shimmer 1.5s ease-in-out infinite alternate',
  } as CSSProperties,
}

const inr = (n: number | null | undefined) =>
  n == null || isNaN(n) ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })
const num2 = (n: number | null | undefined) =>
  n == null || isNaN(n) ? '—' : Number(n).toFixed(2)

// ── Regime classification (client-side, matches backend router logic) ──
type Regime = { label: 'TREND_UP' | 'TREND_DOWN' | 'SIDEWAYS' | 'FLAT'; text: string; action: string }
function classifyRegime(chain: Chain | undefined, spot: number | undefined, prevClose: number | undefined): Regime {
  if (!chain || !spot || !prevClose) {
    return { label: 'FLAT', text: 'Not enough data yet', action: 'WAIT' }
  }
  const pcr = chain.summary?.pcr_oi ?? 0
  const mom = ((spot / prevClose) - 1) * 100

  if (mom >= 1.0) return { label: 'TREND_UP', text: `Underlying up ${num2(mom)}% — trend bias`, action: 'BUY CALL (ATM)' }
  if (mom <= -1.0) return { label: 'TREND_DOWN', text: `Underlying down ${num2(mom)}% — put bias`, action: 'BUY PUT (ATM)' }
  if (Math.abs(mom) <= 0.5 && pcr >= 0.7 && pcr <= 1.4) {
    return { label: 'SIDEWAYS', text: `Range-bound (PCR ${num2(pcr)}, move ${num2(mom)}%)`, action: 'IRON CONDOR (ATM±50 / ATM±400)' }
  }
  return { label: 'FLAT', text: 'Signal unclear — sit this one out', action: 'NO TRADE' }
}

// ── Auto-generated insights from chain data ──
function computeInsights(chain: Chain | undefined) {
  if (!chain || !chain.strikes?.length) return []
  const strikes = chain.strikes
  const spot = chain.ltp || 0

  // 1. Max OI shift today — highest |oi_change| across all strikes CE + PE
  let biggestShift = { strike: 0, side: '', oi_change: 0 }
  for (const r of strikes) {
    const ce = r.ce?.oi_change ?? 0
    const pe = r.pe?.oi_change ?? 0
    if (Math.abs(ce) > Math.abs(biggestShift.oi_change)) {
      biggestShift = { strike: r.strike, side: 'CE', oi_change: ce }
    }
    if (Math.abs(pe) > Math.abs(biggestShift.oi_change)) {
      biggestShift = { strike: r.strike, side: 'PE', oi_change: pe }
    }
  }

  // 2. Max Pain distance
  const maxPain = chain.summary?.max_pain ?? 0
  const distance = spot && maxPain ? ((spot - maxPain) / maxPain) * 100 : 0

  // 3. Unusual writing — strikes with heavy PE OI additions above spot (bullish signal)
  //    or heavy CE OI additions below spot (bearish signal)
  let unusual = { strike: 0, side: '', delta: 0, note: '' }
  for (const r of strikes) {
    const peAdd = r.pe?.oi_change ?? 0
    const ceAdd = r.ce?.oi_change ?? 0
    if (r.strike < spot && peAdd > unusual.delta) {
      unusual = { strike: r.strike, side: 'PE', delta: peAdd, note: 'writers defending support' }
    }
    if (r.strike > spot && ceAdd > unusual.delta) {
      unusual = { strike: r.strike, side: 'CE', delta: ceAdd, note: 'writers capping upside' }
    }
  }

  return [
    biggestShift.oi_change !== 0 && {
      icon: biggestShift.oi_change > 0 ? '📈' : '📉',
      title: 'Largest OI shift today',
      body: `${biggestShift.strike} ${biggestShift.side}: ${biggestShift.oi_change > 0 ? '+' : ''}${inr(biggestShift.oi_change)} contracts`,
      meta: biggestShift.oi_change > 0 ? 'Fresh position building' : 'Position unwinding',
    },
    maxPain > 0 && {
      icon: '🎯',
      title: 'Max Pain',
      body: `${inr(maxPain)} — spot is ${distance > 0 ? '+' : ''}${num2(distance)}% away`,
      meta: Math.abs(distance) < 0.5
        ? 'Market is pinned to max pain — expiry drift likely'
        : distance > 0
          ? 'Spot above max pain — sellers may pull it down'
          : 'Spot below max pain — buyers may push it up',
    },
    unusual.delta > 0 && {
      icon: '💡',
      title: 'Unusual writing',
      body: `${unusual.strike} ${unusual.side}: +${inr(unusual.delta)} OI`,
      meta: unusual.note,
    },
  ].filter(Boolean) as { icon: string; title: string; body: string; meta: string }[]
}

// ── Main component ──
export default function ChartsIntelligenceBar({
  chain, spot, prevClose, loading, onAskReyu, onBuildStrategy,
}: Props) {
  const nav = useNavigate()
  const regime = classifyRegime(chain, spot, prevClose)
  const insights = computeInsights(chain)

  const change = spot && prevClose ? spot - prevClose : 0
  const changePct = spot && prevClose ? ((spot / prevClose) - 1) * 100 : 0
  const pcr = chain?.summary?.pcr_oi ?? 0
  const bias = chain?.bias?.bias?.toUpperCase() as 'BULL' | 'BEAR' | 'RANGE' | 'UNCLEAR' | undefined
  const biasDisplay: 'BULL' | 'BEAR' | 'RANGE' | 'UNCLEAR' =
    bias === 'BULL' || bias === 'BEAR' || bias === 'RANGE' ? bias : 'UNCLEAR'

  if (loading && !chain) {
    return (
      <div style={S.wrap}>
        <div style={S.hero}>
          {[0, 1, 2].map(i => <div key={i} style={S.skel} />)}
        </div>
      </div>
    )
  }

  const regimeDotColor =
    regime.label === 'TREND_UP' ? 'var(--brand-primary)' :
    regime.label === 'TREND_DOWN' ? 'var(--danger)' :
    regime.label === 'SIDEWAYS' ? 'var(--signal)' :
    'var(--text-muted)'

  return (
    <div style={S.wrap}>
      {/* Persistent regime pill — what the platform would do right now */}
      <div style={S.regimePill(biasDisplay)}>
        <span style={S.regimeDot(regimeDotColor)} />
        <span>Platform view: <strong>{regime.label.replace('_', ' ')}</strong></span>
        <span style={{ opacity: 0.7 }}>·</span>
        <span>{regime.action}</span>
      </div>

      {/* Hero row — 3 tiles */}
      <div style={S.hero}>
        <div style={S.heroCard}>
          <div style={S.heroLabel}>Spot</div>
          <div style={S.heroValue}>{inr(spot)}</div>
          <div style={{
            ...S.heroSubtitle,
            color: change > 0 ? 'var(--brand-primary)' : change < 0 ? 'var(--danger)' : 'var(--text-secondary)',
            fontWeight: 600,
          }}>
            {change === 0 ? '—' : `${change > 0 ? '▲' : '▼'} ${inr(Math.abs(change))} (${changePct > 0 ? '+' : ''}${num2(changePct)}%)`}
          </div>
        </div>

        <div style={S.heroCard}>
          <div style={S.heroLabel}>AI Bias</div>
          <div style={{
            ...S.heroValue,
            color: biasDisplay === 'BULL' ? 'var(--brand-primary)' :
                    biasDisplay === 'BEAR' ? 'var(--danger)' :
                    biasDisplay === 'RANGE' ? 'var(--signal)' :
                    'var(--text-secondary)',
          }}>
            {biasDisplay}
          </div>
          <div style={S.heroSubtitle}>
            PCR {num2(pcr)} · {chain?.bias?.signals?.[0] || 'Signal loading…'}
          </div>
        </div>

        <div style={S.heroCard}>
          <div style={S.heroLabel}>Suggested action</div>
          <div style={{ ...S.heroValue, fontSize: 18 }}>
            {regime.action}
          </div>
          <div style={S.heroSubtitle}>{regime.text}</div>
        </div>
      </div>

      {/* Auto-generated insights */}
      {insights.length > 0 && (
        <div style={S.insights}>
          {insights.map((ins, i) => (
            <div key={i} style={S.insightCard}>
              <div style={S.insightIcon}>{ins.icon}</div>
              <div style={{ flex: 1 }}>
                <div style={S.insightTitle}>{ins.title}</div>
                <div style={S.insightBody}>{ins.body}</div>
                <div style={S.insightMeta}>{ins.meta}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Quick actions */}
      <div style={S.quickActions}>
        <button
          style={S.quickBtnPrimary}
          onClick={() => {
            track(Events.ChatMsgSent, { source: 'charts_quick_ask' })
            const q = `Explain what the chain is saying right now for ${chain?.underlying ?? 'this symbol'}`
            if (onAskReyu) onAskReyu(q)
            else nav(`/?q=${encodeURIComponent(q)}`)
          }}
        >
          💬 Ask Reyu about this chain
        </button>
        <button
          style={S.quickBtn}
          onClick={() => {
            if (onBuildStrategy) onBuildStrategy()
            else nav('/strategies')
          }}
        >
          ⚡ Build a strategy from this
        </button>
        <button
          style={S.quickBtn}
          onClick={() => nav('/backtest')}
        >
          🔁 Backtest a template on this
        </button>
        <button
          style={S.quickBtn}
          onClick={() => nav('/journal')}
        >
          📓 My journal
        </button>
      </div>
    </div>
  )
}

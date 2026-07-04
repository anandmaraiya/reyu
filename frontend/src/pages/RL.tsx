/**
 * RL Engine Dashboard — /rl
 *
 * Sections:
 *   1. KPI bar          — summary stats (policies, trades, today's reward)
 *   2. Signal feed      — /api/rl/recommendations (LONG/SHORT with conviction)
 *   3. Universe table   — /api/rl/policies (per-underlying win rates, enable/disable)
 *   4. Recent trades    — /api/rl/trades (paper-trade history)
 *   5. Equity curve     — cumulative reward plotted from closed trades
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../context/AuthContext'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Summary {
  policies: number
  enabled: number
  open_trades: number
  total_trades: number
  todays_trades: number
  todays_cum_reward: number
  feature_dim: number
}

interface PolicyRow {
  underlying: string
  n_trades: number
  n_wins: number
  win_rate: number | null
  cum_reward: number
  epsilon: number
  enabled: boolean
  target_pct: number
  stop_pct: number
  last_trained_at: string | null
}

interface Recommendation {
  underlying: string
  action: 'LONG' | 'SHORT' | 'FLAT'
  conviction: number
  p_long?: number
  p_short?: number
  p_flat?: number
}

interface Trade {
  id: number
  underlying: string
  action: string
  leg_symbol: string
  strike: number
  option_type: string
  entry_ts: string
  entry_premium: number
  target_premium: number
  stop_premium: number
  exit_ts: string | null
  exit_premium: number | null
  status: 'OPEN' | 'TP' | 'SL' | 'TIMEOUT'
  reward: number | null
  pnl_pct: number | null
  paper: boolean
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null) return '—'
  return n.toFixed(digits)
}

function pct(n: number | null | undefined): string {
  if (n == null) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

// ─── EquityCurve ─────────────────────────────────────────────────────────────

function EquityCurve({ trades }: { trades: Trade[] }) {
  const closed = [...trades]
    .filter(t => t.reward != null)
    .sort((a, b) => new Date(a.entry_ts).getTime() - new Date(b.entry_ts).getTime())

  if (closed.length < 2) {
    return (
      <div className="rl-equity-empty">
        <span style={{ fontSize: 28 }}>📈</span>
        <p>Equity curve will appear once trades close.</p>
      </div>
    )
  }

  // Cumulative reward series
  let cum = 0
  const points = closed.map(t => { cum += t.reward!; return cum })
  const min = Math.min(0, ...points)
  const max = Math.max(0.01, ...points)
  const range = max - min || 1
  const W = 600; const H = 100
  const xs = points.map((_, i) => (i / (points.length - 1)) * W)
  const ys = points.map(p => H - ((p - min) / range) * H)
  const d = xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ')
  const area = `${d} L${W},${H} L0,${H} Z`
  const finalColor = points[points.length - 1] >= 0 ? '#22c55e' : '#ef4444'

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 100, display: 'block' }} preserveAspectRatio="none">
      <defs>
        <linearGradient id="rl-eq-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={finalColor} stopOpacity="0.3" />
          <stop offset="100%" stopColor={finalColor} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      {/* zero line */}
      {min < 0 && max > 0 && (
        <line
          x1="0" y1={H - ((0 - min) / range) * H}
          x2={W} y2={H - ((0 - min) / range) * H}
          stroke="var(--color-border)" strokeWidth="1" strokeDasharray="4,4"
        />
      )}
      <path d={area} fill="url(#rl-eq-grad)" />
      <path d={d} fill="none" stroke={finalColor} strokeWidth="2" />
    </svg>
  )
}

// ─── StatusChip ──────────────────────────────────────────────────────────────

const STATUS_STYLE: Record<string, { bg: string; color: string }> = {
  OPEN:    { bg: 'rgba(59,130,246,0.15)', color: '#60a5fa' },
  TP:      { bg: 'rgba(34,197,94,0.15)',  color: '#22c55e' },
  SL:      { bg: 'rgba(239,68,68,0.15)',  color: '#ef4444' },
  TIMEOUT: { bg: 'rgba(156,163,175,0.15)', color: '#9ca3af' },
}

function StatusChip({ status }: { status: string }) {
  const s = STATUS_STYLE[status] ?? { bg: 'var(--color-surface)', color: 'var(--color-text-secondary)' }
  return (
    <span style={{
      display: 'inline-block', padding: '1px 8px', borderRadius: 4,
      fontSize: 11, fontWeight: 600, letterSpacing: '0.04em',
      background: s.bg, color: s.color,
    }}>
      {status}
    </span>
  )
}

// ─── ActionBadge ─────────────────────────────────────────────────────────────

function ActionBadge({ action, conviction }: { action: string; conviction?: number }) {
  const isLong = action === 'LONG'
  const isShort = action === 'SHORT'
  const color = isLong ? '#22c55e' : isShort ? '#ef4444' : 'var(--color-text-tertiary)'
  const bg = isLong ? 'rgba(34,197,94,0.12)' : isShort ? 'rgba(239,68,68,0.12)' : 'transparent'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
      background: bg, color,
    }}>
      {isLong ? '▲' : isShort ? '▼' : '—'} {action}
      {conviction != null && <span style={{ opacity: 0.8, fontWeight: 400 }}>({pct(conviction)})</span>}
    </span>
  )
}

// ─── ConvictionBar ───────────────────────────────────────────────────────────

function ConvictionBar({ value }: { value: number }) {
  const w = Math.min(100, value * 100)
  const color = value >= 0.6 ? '#22c55e' : value >= 0.35 ? '#f59e0b' : '#6b7280'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 120 }}>
      <div style={{ flex: 1, height: 4, borderRadius: 2, background: 'var(--color-border)' }}>
        <div style={{ width: `${w}%`, height: '100%', borderRadius: 2, background: color, transition: 'width 0.4s' }} />
      </div>
      <span style={{ fontSize: 11, color: 'var(--color-text-secondary)', width: 36, textAlign: 'right' }}>
        {pct(value)}
      </span>
    </div>
  )
}

// ─── RL Dashboard ─────────────────────────────────────────────────────────────

export default function RL() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [policies, setPolicies] = useState<PolicyRow[]>([])
  const [recs, setRecs] = useState<Recommendation[]>([])
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'recs' | 'universe' | 'trades'>('recs')
  const [toggling, setToggling] = useState<string | null>(null)
  const refreshRef = useRef<ReturnType<typeof setInterval>>()

  const load = useCallback(async () => {
    try {
      const [summaryRes, policiesRes, recsRes, tradesRes] = await Promise.all([
        api.get('/api/rl/summary'),
        api.get('/api/rl/policies'),
        api.get('/api/rl/recommendations?top=30&min_conviction=0.05'),
        api.get('/api/rl/trades?limit=50'),
      ])
      setSummary(summaryRes.data)
      setPolicies(policiesRes.data)
      setRecs(recsRes.data.top ?? [])
      setTrades(tradesRes.data)
      setError(null)
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to load RL data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    refreshRef.current = setInterval(load, 30_000) // refresh every 30s
    return () => clearInterval(refreshRef.current)
  }, [load])

  async function togglePolicy(underlying: string, enabled: boolean) {
    setToggling(underlying)
    try {
      await api.post(`/api/rl/policy/${underlying}/toggle?on=${!enabled}`)
      setPolicies(p => p.map(r => r.underlying === underlying ? { ...r, enabled: !enabled } : r))
    } catch {/* silent */} finally {
      setToggling(null)
    }
  }

  async function trainNow() {
    try {
      await api.post('/api/rl/train')
      await load()
    } catch {/* silent */}
  }

  async function decideNow() {
    try {
      await api.post('/api/rl/decide-now')
      await load()
    } catch {/* silent */}
  }

  // Stats from policies
  const totalWins = policies.reduce((s, p) => s + p.n_wins, 0)
  const totalTrades = policies.reduce((s, p) => s + p.n_trades, 0)
  const globalWR = totalTrades > 0 ? totalWins / totalTrades : null
  const totalReward = policies.reduce((s, p) => s + (p.cum_reward || 0), 0)

  return (
    <>
      <style>{`
        .rl-page { padding: 24px 28px; max-width: 1200px; }
        .rl-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }
        .rl-title { font-size: 20px; font-weight: 700; color: var(--color-text-primary); display: flex; align-items: center; gap: 10px; }
        .rl-title-badge { font-size: 10px; font-weight: 700; letter-spacing: .08em; background: rgba(139,92,246,0.2); color: #a78bfa; padding: 2px 8px; border-radius: 20px; border: 1px solid rgba(139,92,246,0.3); }
        .rl-actions { display: flex; gap: 8px; }
        .rl-btn { padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-text-primary); transition: all 0.15s; }
        .rl-btn:hover { background: var(--color-surface-hover); }
        .rl-btn.primary { background: var(--color-primary); color: #fff; border-color: var(--color-primary); }
        .rl-btn.primary:hover { opacity: 0.9; }

        /* KPI bar */
        .rl-kpi-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 24px; }
        .rl-kpi { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 10px; padding: 14px 16px; }
        .rl-kpi-label { font-size: 11px; color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
        .rl-kpi-value { font-size: 24px; font-weight: 700; color: var(--color-text-primary); line-height: 1; }
        .rl-kpi-sub { font-size: 11px; color: var(--color-text-tertiary); margin-top: 4px; }
        .rl-kpi.positive .rl-kpi-value { color: #22c55e; }
        .rl-kpi.negative .rl-kpi-value { color: #ef4444; }

        /* Equity curve */
        .rl-equity { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 10px; padding: 16px; margin-bottom: 24px; }
        .rl-equity-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
        .rl-equity-title { font-size: 13px; font-weight: 600; color: var(--color-text-primary); }
        .rl-equity-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 24px; color: var(--color-text-tertiary); font-size: 13px; }

        /* Tabs */
        .rl-tabs { display: flex; gap: 2px; margin-bottom: 16px; border-bottom: 1px solid var(--color-border); }
        .rl-tab { padding: 8px 16px; font-size: 13px; font-weight: 500; color: var(--color-text-secondary); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; transition: all 0.15s; }
        .rl-tab:hover { color: var(--color-text-primary); }
        .rl-tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); font-weight: 600; }

        /* Signal feed */
        .rl-signals { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
        .rl-signal-card { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
        .rl-signal-card.long { border-left: 3px solid #22c55e; }
        .rl-signal-card.short { border-left: 3px solid #ef4444; }
        .rl-signal-top { display: flex; align-items: center; justify-content: space-between; }
        .rl-signal-sym { font-size: 14px; font-weight: 700; color: var(--color-text-primary); }
        .rl-prob-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; }
        .rl-prob-cell { text-align: center; padding: 4px; border-radius: 4px; background: var(--color-bg); }
        .rl-prob-cell-label { font-size: 9px; color: var(--color-text-tertiary); text-transform: uppercase; }
        .rl-prob-cell-val { font-size: 12px; font-weight: 600; color: var(--color-text-primary); }

        /* Universe table */
        .rl-table-wrap { overflow-x: auto; }
        .rl-table { width: 100%; border-collapse: collapse; font-size: 12px; }
        .rl-table th { padding: 8px 10px; text-align: left; font-size: 10px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--color-text-tertiary); border-bottom: 1px solid var(--color-border); white-space: nowrap; }
        .rl-table td { padding: 10px 10px; border-bottom: 1px solid var(--color-border); color: var(--color-text-primary); vertical-align: middle; }
        .rl-table tr:hover td { background: var(--color-surface-hover); }
        .rl-table tr:last-child td { border-bottom: none; }
        .rl-toggle { width: 32px; height: 18px; border-radius: 9px; border: none; cursor: pointer; position: relative; transition: background 0.2s; }
        .rl-toggle.on { background: var(--color-primary); }
        .rl-toggle.off { background: var(--color-border); }
        .rl-toggle::after { content: ''; position: absolute; width: 12px; height: 12px; border-radius: 50%; background: #fff; top: 3px; transition: left 0.2s; }
        .rl-toggle.on::after { left: 17px; }
        .rl-toggle.off::after { left: 3px; }

        /* Trades table */
        .rl-trades-table { width: 100%; border-collapse: collapse; font-size: 12px; }
        .rl-trades-table th { padding: 8px 10px; text-align: left; font-size: 10px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--color-text-tertiary); border-bottom: 1px solid var(--color-border); white-space: nowrap; }
        .rl-trades-table td { padding: 10px 10px; border-bottom: 1px solid var(--color-border); color: var(--color-text-primary); vertical-align: middle; white-space: nowrap; }
        .rl-trades-table tr:hover td { background: var(--color-surface-hover); }
        .rl-trades-table tr:last-child td { border-bottom: none; }
        .rl-pnl.pos { color: #22c55e; }
        .rl-pnl.neg { color: #ef4444; }

        .rl-empty { padding: 40px; text-align: center; color: var(--color-text-tertiary); font-size: 13px; }
        .rl-loading { padding: 40px; text-align: center; color: var(--color-text-tertiary); }
        .rl-error { padding: 24px; background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.2); border-radius: 8px; color: #f87171; font-size: 13px; margin-bottom: 20px; }

        .rl-refresh-hint { font-size: 11px; color: var(--color-text-tertiary); }
      `}</style>

      <div className="rl-page">
        {/* Header */}
        <div className="rl-header">
          <div className="rl-title">
            🤖 RL Engine
            <span className="rl-title-badge">PAPER TRADER</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="rl-refresh-hint">Auto-refresh 30s</span>
            <div className="rl-actions">
              <a className="rl-btn" href="/rl/lab" style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center' }}>🧪 Training Lab</a>
              <button className="rl-btn" onClick={decideNow}>▶ Decide Now</button>
              <button className="rl-btn primary" onClick={trainNow}>⚡ Train</button>
            </div>
          </div>
        </div>

        {error && <div className="rl-error">⚠ {error}</div>}

        {/* KPI bar */}
        <div className="rl-kpi-bar">
          <div className="rl-kpi">
            <div className="rl-kpi-label">Active Policies</div>
            <div className="rl-kpi-value">{summary?.enabled ?? '—'}<span style={{ fontSize: 14, fontWeight: 400, color: 'var(--color-text-tertiary)' }}>/{summary?.policies ?? '—'}</span></div>
            <div className="rl-kpi-sub">Feature dim: {summary?.feature_dim ?? '—'}</div>
          </div>
          <div className={`rl-kpi ${globalWR != null && globalWR >= 0.5 ? 'positive' : globalWR != null ? 'negative' : ''}`}>
            <div className="rl-kpi-label">Global Win Rate</div>
            <div className="rl-kpi-value">{pct(globalWR)}</div>
            <div className="rl-kpi-sub">{totalWins}W / {totalTrades - totalWins}L of {totalTrades}</div>
          </div>
          <div className={`rl-kpi ${totalReward > 0 ? 'positive' : totalReward < 0 ? 'negative' : ''}`}>
            <div className="rl-kpi-label">Cum. Reward</div>
            <div className="rl-kpi-value">{fmt(totalReward)}</div>
            <div className="rl-kpi-sub">All-time bandit score</div>
          </div>
          <div className="rl-kpi">
            <div className="rl-kpi-label">Open Trades</div>
            <div className="rl-kpi-value">{summary?.open_trades ?? '—'}</div>
            <div className="rl-kpi-sub">{summary?.todays_trades ?? 0} today</div>
          </div>
          <div className={`rl-kpi ${(summary?.todays_cum_reward ?? 0) > 0 ? 'positive' : (summary?.todays_cum_reward ?? 0) < 0 ? 'negative' : ''}`}>
            <div className="rl-kpi-label">Today's Reward</div>
            <div className="rl-kpi-value">{fmt(summary?.todays_cum_reward, 2)}</div>
            <div className="rl-kpi-sub">Closed today</div>
          </div>
          <div className="rl-kpi">
            <div className="rl-kpi-label">Signals</div>
            <div className="rl-kpi-value">{recs.length}</div>
            <div className="rl-kpi-sub">LONG + SHORT above 5%</div>
          </div>
        </div>

        {/* Equity curve */}
        <div className="rl-equity">
          <div className="rl-equity-header">
            <span className="rl-equity-title">Cumulative Reward Curve</span>
            <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>
              {trades.filter(t => t.reward != null).length} closed trades
            </span>
          </div>
          <EquityCurve trades={trades} />
        </div>

        {/* Tabs */}
        <div className="rl-tabs">
          {([
            ['recs', '🎯 Signals', recs.length],
            ['universe', '🗂 Universe', policies.length],
            ['trades', '📋 Trades', trades.length],
          ] as const).map(([id, label, count]) => (
            <div
              key={id}
              className={`rl-tab ${activeTab === id ? 'active' : ''}`}
              onClick={() => setActiveTab(id)}
            >
              {label} <span style={{ opacity: 0.6, fontSize: 11 }}>({count})</span>
            </div>
          ))}
        </div>

        {loading ? (
          <div className="rl-loading">Loading RL data…</div>
        ) : activeTab === 'recs' ? (
          /* ── Signals ── */
          recs.length === 0 ? (
            <div className="rl-empty">
              <div style={{ fontSize: 32, marginBottom: 8 }}>🎯</div>
              No actionable signals above 5% conviction. The bandit sees the market as flat.
            </div>
          ) : (
            <div className="rl-signals">
              {recs.map(r => (
                <div key={r.underlying} className={`rl-signal-card ${r.action.toLowerCase()}`}>
                  <div className="rl-signal-top">
                    <span className="rl-signal-sym">{r.underlying}</span>
                    <ActionBadge action={r.action} />
                  </div>
                  <ConvictionBar value={r.conviction} />
                  {(r.p_long != null || r.p_short != null) && (
                    <div className="rl-prob-row">
                      <div className="rl-prob-cell">
                        <div className="rl-prob-cell-label">LONG</div>
                        <div className="rl-prob-cell-val" style={{ color: '#22c55e' }}>{pct(r.p_long)}</div>
                      </div>
                      <div className="rl-prob-cell">
                        <div className="rl-prob-cell-label">FLAT</div>
                        <div className="rl-prob-cell-val">{pct(r.p_flat)}</div>
                      </div>
                      <div className="rl-prob-cell">
                        <div className="rl-prob-cell-label">SHORT</div>
                        <div className="rl-prob-cell-val" style={{ color: '#ef4444' }}>{pct(r.p_short)}</div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )
        ) : activeTab === 'universe' ? (
          /* ── Universe table ── */
          policies.length === 0 ? (
            <div className="rl-empty">No policies trained yet. Run /api/rl/backfill to bootstrap.</div>
          ) : (
            <div className="rl-table-wrap">
              <table className="rl-table">
                <thead>
                  <tr>
                    <th>Underlying</th>
                    <th>Win Rate</th>
                    <th>Trades</th>
                    <th>Cum. Reward</th>
                    <th>Epsilon</th>
                    <th>TP / SL</th>
                    <th>Last Trained</th>
                    <th>Enabled</th>
                  </tr>
                </thead>
                <tbody>
                  {policies.map(p => (
                    <tr key={p.underlying}>
                      <td style={{ fontWeight: 600 }}>{p.underlying}</td>
                      <td>
                        {p.win_rate != null ? (
                          <span style={{ color: p.win_rate >= 0.5 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                            {pct(p.win_rate)}
                          </span>
                        ) : '—'}
                        {p.n_trades > 0 && <span style={{ color: 'var(--color-text-tertiary)', marginLeft: 4, fontSize: 10 }}>({p.n_wins}W/{p.n_trades - p.n_wins}L)</span>}
                      </td>
                      <td style={{ color: 'var(--color-text-secondary)' }}>{p.n_trades}</td>
                      <td>
                        <span style={{ color: p.cum_reward > 0 ? '#22c55e' : p.cum_reward < 0 ? '#ef4444' : 'var(--color-text-secondary)', fontWeight: 600 }}>
                          {fmt(p.cum_reward, 2)}
                        </span>
                      </td>
                      <td style={{ color: 'var(--color-text-secondary)' }}>{fmt(p.epsilon, 2)}</td>
                      <td style={{ color: 'var(--color-text-secondary)' }}>
                        {fmt(p.target_pct * 100, 1)}% / {fmt(p.stop_pct * 100, 1)}%
                      </td>
                      <td style={{ color: 'var(--color-text-tertiary)', fontSize: 11 }}>{timeAgo(p.last_trained_at)}</td>
                      <td>
                        <button
                          className={`rl-toggle ${p.enabled ? 'on' : 'off'}`}
                          onClick={() => togglePolicy(p.underlying, p.enabled)}
                          disabled={toggling === p.underlying}
                          title={p.enabled ? 'Disable policy' : 'Enable policy'}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          /* ── Trades ── */
          trades.length === 0 ? (
            <div className="rl-empty">No paper trades yet. Run Decide Now to generate signals.</div>
          ) : (
            <div className="rl-table-wrap">
              <table className="rl-trades-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Symbol</th>
                    <th>Action</th>
                    <th>Leg</th>
                    <th>Entry</th>
                    <th>Entry ₹</th>
                    <th>Exit ₹</th>
                    <th>P&L %</th>
                    <th>Status</th>
                    <th>Reward</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map(t => {
                    const pnlPos = t.pnl_pct != null && t.pnl_pct > 0
                    const pnlNeg = t.pnl_pct != null && t.pnl_pct < 0
                    return (
                      <tr key={t.id}>
                        <td style={{ color: 'var(--color-text-tertiary)' }}>{t.id}</td>
                        <td style={{ fontWeight: 600 }}>{t.underlying}</td>
                        <td><ActionBadge action={t.action} /></td>
                        <td style={{ color: 'var(--color-text-secondary)', fontFamily: 'monospace', fontSize: 11 }}>
                          {t.leg_symbol || `${t.strike}${t.option_type}`}
                        </td>
                        <td style={{ color: 'var(--color-text-tertiary)' }}>
                          {t.entry_ts ? new Date(t.entry_ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}
                        </td>
                        <td>₹{fmt(t.entry_premium)}</td>
                        <td style={{ color: 'var(--color-text-secondary)' }}>
                          {t.exit_premium != null ? `₹${fmt(t.exit_premium)}` : '—'}
                        </td>
                        <td>
                          <span className={`rl-pnl ${pnlPos ? 'pos' : pnlNeg ? 'neg' : ''}`}>
                            {t.pnl_pct != null ? `${t.pnl_pct > 0 ? '+' : ''}${pct(t.pnl_pct / 100)}` : '—'}
                          </span>
                        </td>
                        <td><StatusChip status={t.status} /></td>
                        <td>
                          <span style={{ color: (t.reward ?? 0) > 0 ? '#22c55e' : (t.reward ?? 0) < 0 ? '#ef4444' : 'var(--color-text-tertiary)', fontWeight: 600, fontSize: 12 }}>
                            {t.reward != null ? fmt(t.reward, 3) : '—'}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>
    </>
  )
}

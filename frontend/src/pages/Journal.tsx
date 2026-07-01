/**
 * Journal — P&L Dashboard (F-A2, P-18).
 *
 * Layout (top → bottom):
 *   Header + time-range toggle + mode filter
 *   6 KPI tiles: Total P&L, WR, Trades, Avg P&L, Best, Worst
 *   Daily P&L bar chart (last 30 days)
 *   Monthly bucket table
 *   Recent trades table w/ pagination + export
 *
 * Data source: /api/journal/summary, /api/journal/trades, /api/journal/export.csv
 * Telemetry: journal_viewed on mount, journal_exported on export click.
 */
import { useState, useEffect, type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { track, Events } from '../telemetry'

type Mode = '' | 'PAPER' | 'LIVE'
type Range = 30 | 90 | 365

type Summary = {
  range_days: number
  summary: {
    total_trades: number
    closed: number
    open: number
    skipped: number
    wins: number
    losses: number
    win_rate: number
    total_pnl_inr: number
    avg_pnl_per_trade_inr: number
    best_pnl_inr: number
    worst_pnl_inr: number
  }
  daily_pnl: { date: string; pnl_inr: number; trades: number }[]
  monthly: { month: string; pnl_inr: number; trades: number; wins: number; losses: number }[]
}

type Trades = {
  total: number
  limit: number
  offset: number
  trades: any[]
}

// ── Styles ────────────────────────────────────────────────────────────
const S = {
  page: { padding: '20px 32px', maxWidth: 1400, color: 'var(--text-primary)' } as CSSProperties,
  h1: { fontSize: 22, fontWeight: 600, margin: '0 0 8px 0' } as CSSProperties,
  sub: { color: 'var(--text-secondary)', fontSize: 13, marginBottom: 20 } as CSSProperties,
  toolbar: {
    display: 'flex', gap: 8, alignItems: 'center', marginBottom: 24, flexWrap: 'wrap' as const,
  } as CSSProperties,
  chip: (active: boolean): CSSProperties => ({
    padding: '6px 14px',
    fontSize: 12,
    fontWeight: 500,
    background: active ? 'var(--brand-primary)' : 'var(--bg-elevated)',
    color: active ? '#fff' : 'var(--text-primary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-full)',
    cursor: 'pointer',
    transition: 'all 120ms',
  }),
  card: {
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-md)',
    padding: 18,
    marginBottom: 20,
    boxShadow: 'var(--shadow-sm)',
  } as CSSProperties,
  cardTitle: { margin: '0 0 12px 0', fontSize: 14, fontWeight: 600 } as CSSProperties,
  kpiGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
    gap: 12,
    marginBottom: 24,
  } as CSSProperties,
  kpi: {
    padding: 14,
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
  } as CSSProperties,
  kpiLabel: {
    fontSize: 10,
    letterSpacing: '0.06em',
    textTransform: 'uppercase' as const,
    color: 'var(--text-secondary)',
    fontWeight: 600,
  } as CSSProperties,
  kpiValue: { fontSize: 20, fontWeight: 700, marginTop: 4 } as CSSProperties,
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: 12.5,
  } as CSSProperties,
  th: {
    padding: '8px 10px',
    background: 'var(--bg-sunken)',
    color: 'var(--text-secondary)',
    fontWeight: 600,
    fontSize: 11,
    textAlign: 'left' as const,
    borderBottom: '1px solid var(--border-default)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
  } as CSSProperties,
  td: {
    padding: '6px 10px',
    borderBottom: '1px solid var(--border-subtle)',
    verticalAlign: 'top' as const,
  } as CSSProperties,
  numRight: { textAlign: 'right' as const, fontFeatureSettings: '"tnum"' } as CSSProperties,
  btn: {
    padding: '7px 14px',
    fontSize: 12,
    fontWeight: 600,
    background: 'var(--bg-elevated)',
    color: 'var(--text-primary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
  } as CSSProperties,
  primaryBtn: {
    padding: '7px 14px',
    fontSize: 12,
    fontWeight: 600,
    background: 'var(--brand-primary)',
    color: '#fff',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
  } as CSSProperties,
}

const inr = (n: number | null | undefined) => {
  if (n == null || isNaN(n)) return '—'
  return `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}
const pnlColor = (n: number | null | undefined) =>
  n == null ? 'var(--text-muted)' : n > 0 ? 'var(--brand-primary)' : n < 0 ? 'var(--danger)' : 'var(--text-primary)'

export default function Journal() {
  const [range, setRange] = useState<Range>(90)
  const [mode, setMode] = useState<Mode>('')
  const [page, setPage] = useState(0)
  const pageSize = 25

  useEffect(() => {
    track(Events.JournalViewed, { range_days: range, mode })
  }, [range, mode])

  const summary = useQuery<Summary>({
    queryKey: ['journal-summary', range, mode],
    queryFn: async () =>
      (await api.get(`/api/journal/summary?days=${range}${mode ? `&mode=${mode}` : ''}`)).data,
    refetchInterval: 60_000,
  })

  const tradesQ = useQuery<Trades>({
    queryKey: ['journal-trades', page, mode],
    queryFn: async () =>
      (await api.get(
        `/api/journal/trades?limit=${pageSize}&offset=${page * pageSize}${mode ? `&mode=${mode}` : ''}`
      )).data,
  })

  const exportCsv = () => {
    track(Events.JournalExported, { range_days: range })
    const token = localStorage.getItem('reyu_access_token') || ''
    // Trigger download via anchor with auth header we can't inject via <a>;
    // use fetch → blob → object URL.
    fetch(`/api/journal/export.csv?days=${range}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.blob())
      .then(blob => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `reyu-journal-${new Date().toISOString().slice(0, 10)}.csv`
        a.click()
        URL.revokeObjectURL(url)
      })
  }

  const dailyMax = summary.data
    ? Math.max(1, ...summary.data.daily_pnl.map(d => Math.abs(d.pnl_inr)))
    : 1

  return (
    <div style={S.page}>
      <h1 style={S.h1}>Journal</h1>
      <p style={S.sub}>
        Your P&L across paper and live trades. Auto-refreshes every 60s.
      </p>

      {/* Toolbar */}
      <div style={S.toolbar}>
        <span style={{ fontSize: 11, color: 'var(--text-secondary)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Range</span>
        <button style={S.chip(range === 30)} onClick={() => setRange(30)}>30d</button>
        <button style={S.chip(range === 90)} onClick={() => setRange(90)}>90d</button>
        <button style={S.chip(range === 365)} onClick={() => setRange(365)}>1y</button>

        <span style={{ marginLeft: 20, fontSize: 11, color: 'var(--text-secondary)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Mode</span>
        <button style={S.chip(mode === '')} onClick={() => setMode('')}>All</button>
        <button style={S.chip(mode === 'PAPER')} onClick={() => setMode('PAPER')}>Paper</button>
        <button style={S.chip(mode === 'LIVE')} onClick={() => setMode('LIVE')}>Live</button>

        <div style={{ flex: 1 }} />
        <button style={S.btn} onClick={exportCsv}>Export CSV</button>
      </div>

      {/* KPI tiles */}
      {summary.data && (
        <div style={S.kpiGrid}>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Total P&L</div>
            <div style={{ ...S.kpiValue, color: pnlColor(summary.data.summary.total_pnl_inr) }}>
              {inr(summary.data.summary.total_pnl_inr)}
            </div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Win Rate</div>
            <div style={S.kpiValue}>{(summary.data.summary.win_rate * 100).toFixed(1)}%</div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Trades</div>
            <div style={S.kpiValue}>{summary.data.summary.closed}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              {summary.data.summary.wins}W / {summary.data.summary.losses}L
              {summary.data.summary.open > 0 && ` · ${summary.data.summary.open} open`}
            </div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Avg P&L</div>
            <div style={{ ...S.kpiValue, color: pnlColor(summary.data.summary.avg_pnl_per_trade_inr) }}>
              {inr(summary.data.summary.avg_pnl_per_trade_inr)}
            </div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Best day</div>
            <div style={{ ...S.kpiValue, color: 'var(--brand-primary)' }}>
              {inr(summary.data.summary.best_pnl_inr)}
            </div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Worst day</div>
            <div style={{ ...S.kpiValue, color: 'var(--danger)' }}>
              {inr(summary.data.summary.worst_pnl_inr)}
            </div>
          </div>
        </div>
      )}

      {/* Daily P&L chart */}
      {summary.data && summary.data.daily_pnl.length > 0 && (
        <div style={S.card}>
          <h3 style={S.cardTitle}>Daily P&L — last 30 days</h3>
          <div style={{ display: 'flex', gap: 3, alignItems: 'flex-end', height: 100, borderBottom: '1px solid var(--border-subtle)', paddingBottom: 4 }}>
            {summary.data.daily_pnl.map((d) => {
              const h = (Math.abs(d.pnl_inr) / dailyMax) * 100
              return (
                <div
                  key={d.date}
                  title={`${d.date}: ${inr(d.pnl_inr)} (${d.trades} trades)`}
                  style={{
                    flex: 1,
                    height: `${Math.max(2, h)}%`,
                    background: d.pnl_inr > 0 ? 'var(--brand-primary)' :
                                d.pnl_inr < 0 ? 'var(--danger)' :
                                'var(--border-default)',
                    borderRadius: 2,
                    opacity: d.trades === 0 ? 0.15 : 1,
                    transition: 'all 200ms',
                  }}
                />
              )
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 10, color: 'var(--text-muted)' }}>
            <span>{summary.data.daily_pnl[0]?.date}</span>
            <span>{summary.data.daily_pnl[summary.data.daily_pnl.length - 1]?.date}</span>
          </div>
        </div>
      )}

      {/* Monthly buckets */}
      {summary.data && summary.data.monthly.length > 0 && (
        <div style={S.card}>
          <h3 style={S.cardTitle}>Monthly performance</h3>
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Month</th>
                <th style={{ ...S.th, ...S.numRight }}>P&L</th>
                <th style={{ ...S.th, ...S.numRight }}>Trades</th>
                <th style={{ ...S.th, ...S.numRight }}>Wins</th>
                <th style={{ ...S.th, ...S.numRight }}>Losses</th>
              </tr>
            </thead>
            <tbody>
              {summary.data.monthly.map(m => (
                <tr key={m.month}>
                  <td style={S.td}>{m.month}</td>
                  <td style={{ ...S.td, ...S.numRight, color: pnlColor(m.pnl_inr), fontWeight: 600 }}>
                    {inr(m.pnl_inr)}
                  </td>
                  <td style={{ ...S.td, ...S.numRight }}>{m.trades}</td>
                  <td style={{ ...S.td, ...S.numRight, color: 'var(--brand-primary)' }}>{m.wins}</td>
                  <td style={{ ...S.td, ...S.numRight, color: 'var(--danger)' }}>{m.losses}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Trades list */}
      <div style={S.card}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ ...S.cardTitle, margin: 0, flex: 1 }}>
            Trades{tradesQ.data ? ` (${tradesQ.data.total})` : ''}
          </h3>
          <button
            style={S.btn}
            disabled={page === 0}
            onClick={() => setPage(p => Math.max(0, p - 1))}
          >← Prev</button>
          <span style={{ margin: '0 12px', fontSize: 12, color: 'var(--text-secondary)' }}>
            {tradesQ.data ? `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, tradesQ.data.total)}` : '…'}
          </span>
          <button
            style={S.btn}
            disabled={!tradesQ.data || (page + 1) * pageSize >= tradesQ.data.total}
            onClick={() => setPage(p => p + 1)}
          >Next →</button>
        </div>

        {tradesQ.data && tradesQ.data.trades.length === 0 ? (
          <div style={{ padding: 30, textAlign: 'center', color: 'var(--text-secondary)' }}>
            No trades in this window yet. Try widening the range or check back tomorrow morning — the platform regime router opens a new trade at 09:25 IST.
          </div>
        ) : (
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Date</th>
                <th style={S.th}>Strategy</th>
                <th style={S.th}>Symbol</th>
                <th style={S.th}>Mode</th>
                <th style={{ ...S.th, ...S.numRight }}>P&L ₹</th>
                <th style={{ ...S.th, ...S.numRight }}>P&L %</th>
                <th style={S.th}>Status</th>
              </tr>
            </thead>
            <tbody>
              {tradesQ.data?.trades.map((t) => (
                <tr key={t.id}>
                  <td style={S.td}>{t.date}</td>
                  <td style={S.td}>
                    <div style={{ fontWeight: 500 }}>{t.strategy_name}</div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{t.source}</div>
                  </td>
                  <td style={{ ...S.td, fontFamily: 'var(--font-mono)', fontSize: 11 }}>{t.symbol}</td>
                  <td style={S.td}>{t.mode}</td>
                  <td style={{ ...S.td, ...S.numRight, color: pnlColor(t.pnl_inr), fontWeight: 600 }}>
                    {t.pnl_inr == null ? '—' : inr(t.pnl_inr)}
                  </td>
                  <td style={{ ...S.td, ...S.numRight, color: pnlColor(t.pnl_pct) }}>
                    {t.pnl_pct == null ? '—' : `${t.pnl_pct.toFixed(1)}%`}
                  </td>
                  <td style={{
                    ...S.td,
                    color: t.status === 'TP' ? 'var(--brand-primary)' :
                           t.status === 'SL' ? 'var(--danger)' :
                           t.status === 'OPEN' ? 'var(--signal)' :
                           'var(--text-muted)',
                    fontWeight: 600,
                    fontSize: 11,
                  }}>{t.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

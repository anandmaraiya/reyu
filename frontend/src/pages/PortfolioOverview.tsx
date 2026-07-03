/**
 * PortfolioOverview — the whole-book view for multi-strategy users (P1b).
 *
 * Answers "how is my entire book doing" across every paper/live strategy:
 * capital deployed, live unrealised P&L, realised 30d, combined daily P&L
 * bars, pairwise correlation (diversification signal), and a global
 * kill-switch that halts every running strategy behind a typed-confirm.
 *
 * Data: GET /api/portfolio-overview (15s refetch), POST .../halt-all.
 */
import { useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../toast'
import ConfirmDangerModal from '../components/ConfirmDangerModal'

type StratRow = {
  strategy_id: string
  name: string
  kind: string
  status: string
  modes: string[]
  active_runs: number
  open_positions: number
  capital_deployed_inr: number
  unrealised_inr: number
  realised_30d_inr: number
  max_position_inr: number | null
}
type Overview = {
  as_of: string
  aggregate: {
    strategies_active: number
    open_positions: number
    capital_deployed_inr: number
    unrealised_inr: number
    realised_30d_inr: number
  }
  strategies: StratRow[]
  combined_daily_pnl: { date: string; pnl_inr: number }[]
  correlations: { a: string; b: string; days: number; correlation: number }[]
  notes: string[]
}

const inr = (n: number) =>
  (n < 0 ? '−₹' : '₹') + Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })
const pnlColor = (n: number) => (n > 0 ? 'var(--gain, #2da14b)' : n < 0 ? 'var(--danger, #e05252)' : 'var(--text-muted)')

const S = {
  page: { padding: '24px 32px', maxWidth: 1100, color: 'var(--text-primary)' } as CSSProperties,
  h1: { fontSize: 22, fontWeight: 700, margin: '0 0 4px' } as CSSProperties,
  sub: { fontSize: 13, color: 'var(--text-secondary)', marginBottom: 20 } as CSSProperties,
  kpis: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 24 } as CSSProperties,
  kpi: { background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: '14px 16px' } as CSSProperties,
  kpiLabel: { fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 6 } as CSSProperties,
  kpiValue: { fontSize: 20, fontWeight: 700, fontFamily: 'var(--font-mono)' } as CSSProperties,
  section: { fontSize: 14, fontWeight: 700, margin: '24px 0 10px' } as CSSProperties,
  table: { width: '100%', borderCollapse: 'collapse' as const, fontSize: 13 } as CSSProperties,
  th: { textAlign: 'left' as const, padding: '8px 10px', fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.04em', borderBottom: '1px solid var(--border-default)' } as CSSProperties,
  td: { padding: '10px', borderBottom: '1px solid var(--border-subtle)' } as CSSProperties,
  bars: { display: 'flex', alignItems: 'flex-end', gap: 3, height: 120, padding: '12px 0' } as CSSProperties,
  killBtn: {
    padding: '10px 18px', fontSize: 13, fontWeight: 700,
    background: 'var(--danger, #e05252)', color: '#fff',
    border: 'none', borderRadius: 8, cursor: 'pointer',
  } as CSSProperties,
  empty: { padding: '40px 0', textAlign: 'center' as const, color: 'var(--text-secondary)', fontSize: 14 } as CSSProperties,
}

function DailyBars({ data }: { data: { date: string; pnl_inr: number }[] }) {
  if (!data.length) return <div style={S.empty}>No closed trades in the last 30 days.</div>
  const maxAbs = Math.max(...data.map(d => Math.abs(d.pnl_inr)), 1)
  return (
    <div style={S.bars}>
      {data.map(d => (
        <div key={d.date} title={`${d.date}: ${inr(d.pnl_inr)}`} style={{
          flex: 1, minWidth: 4, borderRadius: 2,
          height: `${Math.max(4, Math.abs(d.pnl_inr) / maxAbs * 100)}%`,
          background: pnlColor(d.pnl_inr),
          opacity: 0.85,
          alignSelf: d.pnl_inr >= 0 ? 'flex-end' : 'flex-end',
        }} />
      ))}
    </div>
  )
}

export default function PortfolioOverview() {
  const { user } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const [killOpen, setKillOpen] = useState(false)

  const { data, isLoading } = useQuery<Overview>({
    queryKey: ['portfolio-overview'],
    queryFn: async () => (await api.get('/api/portfolio-overview')).data,
    enabled: !!user,
    refetchInterval: 15000,
  })

  const haltAll = useMutation({
    mutationFn: async () => (await api.post('/api/portfolio-overview/halt-all')).data,
    onSuccess: (d) => {
      toast.push('success', `Halted ${d.halted_runs} runs (${d.halted_trades} open trades closed)`)
      setKillOpen(false)
      qc.invalidateQueries({ queryKey: ['portfolio-overview'] })
    },
    onError: (e: any) => toast.push('error', e?.response?.data?.detail || 'Halt failed'),
  })

  if (!user) return <div style={S.page}><p style={S.sub}>Sign in to view your portfolio.</p></div>

  const agg = data?.aggregate

  return (
    <div style={S.page}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={S.h1}>Portfolio</h1>
          <p style={S.sub}>Your whole book — every paper and live strategy, aggregated.</p>
        </div>
        {agg && agg.strategies_active > 0 && (
          <button style={S.killBtn} onClick={() => setKillOpen(true)}>
            ⛔ Halt everything
          </button>
        )}
      </div>

      {isLoading && <div style={S.empty}>Loading…</div>}

      {agg && (
        <div style={S.kpis}>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Active strategies</div>
            <div style={S.kpiValue}>{agg.strategies_active}</div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Open positions</div>
            <div style={S.kpiValue}>{agg.open_positions}</div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Capital deployed</div>
            <div style={S.kpiValue}>{inr(agg.capital_deployed_inr)}</div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Unrealised</div>
            <div style={{ ...S.kpiValue, color: pnlColor(agg.unrealised_inr) }}>{inr(agg.unrealised_inr)}</div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Realised (30d)</div>
            <div style={{ ...S.kpiValue, color: pnlColor(agg.realised_30d_inr) }}>{inr(agg.realised_30d_inr)}</div>
          </div>
        </div>
      )}

      {data && data.strategies.length === 0 && (
        <div style={S.empty}>
          Nothing running yet. Promote a strategy to paper-live from{' '}
          <Link to="/strategies" style={{ color: 'var(--brand-primary, #f0a020)' }}>Saved Strategies</Link>{' '}
          and it appears here.
        </div>
      )}

      {data && data.strategies.length > 0 && (
        <>
          <div style={S.section}>Strategies</div>
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Strategy</th>
                <th style={S.th}>Kind</th>
                <th style={S.th}>Mode</th>
                <th style={S.th}>Open</th>
                <th style={S.th}>Deployed</th>
                <th style={S.th}>Unrealised</th>
                <th style={S.th}>Realised 30d</th>
              </tr>
            </thead>
            <tbody>
              {data.strategies.map(row => (
                <tr key={row.strategy_id}>
                  <td style={S.td}>
                    <Link to={`/strategies/${row.strategy_id}`} style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                      {row.name}
                    </Link>
                  </td>
                  <td style={S.td}><span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{row.kind}</span></td>
                  <td style={S.td}>{row.modes.join('+') || row.status}</td>
                  <td style={S.td}>{row.open_positions}</td>
                  <td style={{ ...S.td, fontFamily: 'var(--font-mono)' }}>{inr(row.capital_deployed_inr)}</td>
                  <td style={{ ...S.td, fontFamily: 'var(--font-mono)', color: pnlColor(row.unrealised_inr) }}>{inr(row.unrealised_inr)}</td>
                  <td style={{ ...S.td, fontFamily: 'var(--font-mono)', color: pnlColor(row.realised_30d_inr) }}>{inr(row.realised_30d_inr)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div style={S.section}>Combined daily P&L — last 30 days</div>
          <DailyBars data={data.combined_daily_pnl} />

          {data.correlations.length > 0 && (
            <>
              <div style={S.section}>Strategy correlation</div>
              <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 10 }}>
                Daily-P&L correlation between your strategies. Values near +1 mean they win and
                lose together (concentrated risk); near 0 or negative means they diversify.
              </p>
              <table style={S.table}>
                <thead>
                  <tr>
                    <th style={S.th}>Pair</th>
                    <th style={S.th}>Days</th>
                    <th style={S.th}>Correlation</th>
                  </tr>
                </thead>
                <tbody>
                  {data.correlations.map((c, i) => (
                    <tr key={i}>
                      <td style={S.td}>{c.a} ↔ {c.b}</td>
                      <td style={S.td}>{c.days}</td>
                      <td style={{
                        ...S.td, fontFamily: 'var(--font-mono)',
                        color: Math.abs(c.correlation) > 0.6 ? 'var(--danger, #e05252)' : 'var(--text-primary)',
                      }}>
                        {c.correlation.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}

      <ConfirmDangerModal
        open={killOpen}
        title="Halt every running strategy"
        description={
          'This stops ALL paper and live strategies immediately. Open trades are ' +
          'marked closed at last known price; broker positions are NOT auto-exited — ' +
          'close those from Positions. This cannot be undone.'
        }
        expectedText="HALT-ALL"
        confirmLabel={haltAll.isPending ? 'Halting…' : 'Halt everything'}
        variant="danger"
        onCancel={() => setKillOpen(false)}
        onConfirm={() => haltAll.mutate()}
      />
    </div>
  )
}

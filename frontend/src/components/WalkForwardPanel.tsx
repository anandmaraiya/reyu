/**
 * WalkForwardPanel — rolling out-of-sample analysis for one strategy (F-B7).
 *
 * Splits the last year into N windows, backtests each independently, and
 * shows per-window results + dispersion. One great window and three duds
 * = regime-dependence a single backtest hides.
 *
 * Compliance: shows dispersion FACTS (consistency, spread, worst window);
 * never scores or pass/fails the strategy.
 */
import { useState, type CSSProperties } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api'
import { useToast } from '../toast'

type WindowRow = {
  window: number
  start: string
  end: string
  run_id: string
  status: string
  roi_pct: number | null
  max_drawdown_pct: number | null
  total_trades: number | null
  win_rate: number | null
  error: string | null
}
type Summary = {
  group_id: string
  status: 'RUNNING' | 'COMPLETED'
  windows: WindowRow[]
  stability: {
    windows_completed: number
    windows_profitable: number
    consistency: number
    roi_mean_pct: number
    roi_std_pct: number
    roi_best_pct: number
    roi_worst_pct: number
    worst_window_drawdown_pct: number
  } | null
  note: string
}

const S = {
  wrap: {
    border: '1px solid var(--border-default, var(--border))', borderRadius: 10,
    padding: 16, margin: '16px 0', background: 'var(--bg-surface, var(--card))',
  } as CSSProperties,
  head: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' as const } as CSSProperties,
  title: { fontSize: 14, fontWeight: 700, margin: 0 } as CSSProperties,
  sub: { fontSize: 12, color: 'var(--text-secondary, var(--muted))', margin: '4px 0 0' } as CSSProperties,
  btn: {
    padding: '8px 14px', fontSize: 12.5, fontWeight: 700, cursor: 'pointer',
    background: 'var(--bg-elevated, var(--card2))', color: 'var(--text-primary)',
    border: '1px solid var(--border-default, var(--border))', borderRadius: 8,
  } as CSSProperties,
  table: { width: '100%', borderCollapse: 'collapse' as const, fontSize: 12.5, marginTop: 12 } as CSSProperties,
  th: { textAlign: 'left' as const, padding: '6px 8px', fontSize: 10.5, color: 'var(--text-muted, var(--muted))', textTransform: 'uppercase' as const, letterSpacing: '0.04em', borderBottom: '1px solid var(--border-default, var(--border))' } as CSSProperties,
  td: { padding: '7px 8px', borderBottom: '1px solid var(--border-subtle, var(--border))', fontFamily: 'var(--font-mono)' } as CSSProperties,
  stat: { display: 'inline-flex', flexDirection: 'column' as const, marginRight: 22, marginTop: 12 } as CSSProperties,
  statV: { fontSize: 16, fontWeight: 700, fontFamily: 'var(--font-mono)' } as CSSProperties,
  statL: { fontSize: 10.5, color: 'var(--text-muted, var(--muted))', textTransform: 'uppercase' as const, letterSpacing: '0.04em' } as CSSProperties,
  note: { fontSize: 11, color: 'var(--text-muted, var(--muted))', marginTop: 12, fontStyle: 'italic' } as CSSProperties,
}

const pnlColor = (n: number | null) =>
  n == null ? 'var(--text-muted)' : n > 0 ? 'var(--gain, #2da14b)' : n < 0 ? 'var(--danger, #e05252)' : 'inherit'

export default function WalkForwardPanel({ strategyId }: { strategyId: string }) {
  const toast = useToast()
  const [groupId, setGroupId] = useState<string | null>(null)

  const start = useMutation({
    mutationFn: async () => {
      const end = new Date()
      const startD = new Date(end.getTime() - 364 * 86400_000)
      const iso = (d: Date) => d.toISOString().slice(0, 10)
      return (await api.post(
        `/api/strategies/${strategyId}/walkforward` +
        `?period_start=${iso(startD)}&period_end=${iso(end)}&windows=4`
      )).data
    },
    onSuccess: (d) => setGroupId(d.group_id),
    onError: (e: any) =>
      toast.push('error', e?.response?.data?.detail || 'Walk-forward failed to start'),
  })

  const { data } = useQuery<Summary>({
    queryKey: ['walkforward', groupId],
    queryFn: async () =>
      (await api.get(`/api/strategies/walkforward/${groupId}`)).data,
    enabled: !!groupId,
    refetchInterval: (q) => (q.state.data?.status === 'RUNNING' ? 4000 : false),
  })

  return (
    <div style={S.wrap}>
      <div style={S.head}>
        <div>
          <h3 style={S.title}>Walk-forward — 4 windows, last 12 months</h3>
          <p style={S.sub}>
            The same rules tested in four separate periods. Big spread between windows
            means the result depends on one regime — worth knowing before you deploy.
          </p>
        </div>
        <button
          style={{ ...S.btn, opacity: start.isPending || data?.status === 'RUNNING' ? 0.6 : 1 }}
          disabled={start.isPending || data?.status === 'RUNNING'}
          onClick={() => start.mutate()}
        >
          {start.isPending ? 'Starting…'
            : data?.status === 'RUNNING' ? 'Running windows…'
            : data ? '↻ Re-run' : '▶ Run walk-forward'}
        </button>
      </div>

      {data && (
        <>
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>#</th><th style={S.th}>Period</th><th style={S.th}>Status</th>
                <th style={S.th}>ROI %</th><th style={S.th}>Max DD %</th>
                <th style={S.th}>Trades</th><th style={S.th}>Win rate</th>
              </tr>
            </thead>
            <tbody>
              {data.windows.map(w => (
                <tr key={w.window}>
                  <td style={S.td}>{(w.window ?? 0) + 1}</td>
                  <td style={S.td}>{w.start} → {w.end}</td>
                  <td style={S.td}>{w.status === 'RUNNING' ? '⏳' : w.status === 'COMPLETED' ? '✓' : '✗'}</td>
                  <td style={{ ...S.td, color: pnlColor(w.roi_pct) }}>{w.roi_pct ?? '—'}</td>
                  <td style={S.td}>{w.max_drawdown_pct ?? '—'}</td>
                  <td style={S.td}>{w.total_trades ?? '—'}</td>
                  <td style={S.td}>{w.win_rate != null ? `${(w.win_rate * 100).toFixed(0)}%` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {data.stability && (
            <div>
              <span style={S.stat}>
                <span style={S.statV}>{data.stability.windows_profitable}/{data.stability.windows_completed}</span>
                <span style={S.statL}>Windows positive</span>
              </span>
              <span style={S.stat}>
                <span style={{ ...S.statV, color: pnlColor(data.stability.roi_mean_pct) }}>
                  {data.stability.roi_mean_pct}% ± {data.stability.roi_std_pct}
                </span>
                <span style={S.statL}>ROI mean ± spread</span>
              </span>
              <span style={S.stat}>
                <span style={{ ...S.statV, color: pnlColor(data.stability.roi_worst_pct) }}>
                  {data.stability.roi_worst_pct}%
                </span>
                <span style={S.statL}>Worst window</span>
              </span>
              <span style={S.stat}>
                <span style={S.statV}>{data.stability.worst_window_drawdown_pct}%</span>
                <span style={S.statL}>Worst window DD</span>
              </span>
            </div>
          )}
          <p style={S.note}>{data.note}</p>
        </>
      )}
    </div>
  )
}

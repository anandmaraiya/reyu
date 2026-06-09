import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from 'recharts'
import { api } from '../api'
import { chartTooltipStyles } from '../chartTheme'

const num = (n: any, d = 2) =>
  n == null ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d })

const PALETTE = ['#4a9fda', '#2da14b', '#e54848', '#f0a830', '#6b46c1', '#3acdbe']

type Run = {
  id: string
  strategy_id: string
  strategy_version: number
  mode: string
  status: string
  started_at: string
  metrics: any
}

type CompareResp = {
  count: number
  runs: Array<{
    run_id: string
    strategy_id: string
    strategy_name: string
    strategy_version: number
    mode: string
    metrics: any
    equity_curve: { step: number; equity: number }[]
  }>
  metric_matrix: Array<{ metric: string } & Record<string, any>>
}

export default function StrategyCompare() {
  const [pickedRuns, setPickedRuns] = useState<string[]>([])
  const [compareData, setCompareData] = useState<CompareResp | null>(null)

  // Fetch all strategies' latest runs
  const { data: strategies } = useQuery<{ items: any[] }>({
    queryKey: ['all-strategies'],
    queryFn: async () => (await api.get('/api/strategies')).data,
  })

  // For each strategy, fetch its run list — flatten
  const { data: allRuns } = useQuery<Run[]>({
    queryKey: ['all-runs', strategies?.items.map((s) => s.id)],
    queryFn: async () => {
      if (!strategies?.items.length) return []
      const lists = await Promise.all(
        strategies.items.map((s) =>
          api
            .get(`/api/strategies/${s.id}/runs?limit=20`)
            .then((r) => r.data.map((x: Run) => ({ ...x, strategy_id: s.id }))),
        ),
      )
      return ([] as Run[]).concat(...lists)
    },
    enabled: !!strategies?.items,
  })

  const runsByStrategy = useMemo(() => {
    const out: Record<string, Run[]> = {}
    for (const r of allRuns || []) {
      if (!out[r.strategy_id]) out[r.strategy_id] = []
      out[r.strategy_id].push(r)
    }
    return out
  }, [allRuns])

  const compare = useMutation({
    mutationFn: async (ids: string[]) =>
      (await api.post('/api/strategies/compare', ids)).data,
    onSuccess: (data) => setCompareData(data),
  })

  const toggle = (rid: string) => {
    setPickedRuns((p) =>
      p.includes(rid) ? p.filter((x) => x !== rid) : p.length < 5 ? [...p, rid] : p,
    )
  }

  // Align curves: every run normalised to its starting equity (= 1.0)
  const alignedCurves = useMemo(() => {
    if (!compareData) return [] as any[]
    const len = Math.max(...compareData.runs.map((r) => r.equity_curve.length))
    const out: any[] = []
    for (let i = 0; i < len; i++) {
      const row: any = { step: i }
      for (const r of compareData.runs) {
        const start = r.equity_curve[0]?.equity || 1
        const pt = r.equity_curve[Math.min(i, r.equity_curve.length - 1)]
        row[r.run_id.slice(0, 8)] = pt ? (pt.equity / start - 1) * 100 : null
      }
      out.push(row)
    }
    return out
  }, [compareData])

  return (
    <div className="page-shell">
      <div className="card">
        <div className="card-header">
          <h3>Compare Strategy Runs</h3>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            Pick up to 5 runs across any of your strategies
          </span>
        </div>

        {/* Run picker */}
        <div style={{ padding: 14 }}>
          {!strategies?.items.length ? (
            <div style={{ color: 'var(--muted)', textAlign: 'center', padding: 30 }}>
              No strategies yet. Create one in Strategy Builder.
            </div>
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
                gap: 12,
              }}
            >
              {strategies.items.map((s) => {
                const runs = (runsByStrategy[s.id] || [])
                  .filter((r) => r.status === 'COMPLETED')
                  .slice(0, 6)
                return (
                  <div
                    key={s.id}
                    style={{
                      border: '1px solid var(--border)',
                      borderRadius: 8,
                      padding: 10,
                    }}
                  >
                    <div
                      style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}
                    >
                      {s.name}
                    </div>
                    {runs.length === 0 ? (
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                        No completed runs
                      </div>
                    ) : (
                      runs.map((r) => {
                        const checked = pickedRuns.includes(r.id)
                        const m = r.metrics || {}
                        return (
                          <label
                            key={r.id}
                            style={{
                              display: 'flex',
                              gap: 8,
                              alignItems: 'center',
                              padding: '4px 0',
                              fontSize: 11,
                              cursor: 'pointer',
                              borderTop: '1px solid var(--border)',
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggle(r.id)}
                            />
                            <span style={{ flex: 1 }}>
                              {new Date(r.started_at).toLocaleDateString()} ·{' '}
                              {r.mode}
                            </span>
                            <span
                              style={{
                                color:
                                  (m.roi_pct ?? 0) >= 0 ? '#2da14b' : '#e54848',
                                fontWeight: 600,
                              }}
                            >
                              {m.roi_pct != null
                                ? `${num(m.roi_pct, 1)}%`
                                : '—'}
                            </span>
                          </label>
                        )
                      })
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div
          style={{
            padding: 14,
            borderTop: '1px solid var(--border)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            {pickedRuns.length} run{pickedRuns.length === 1 ? '' : 's'} selected
          </div>
          <button
            className="btn btn-primary"
            disabled={pickedRuns.length < 2 || compare.isPending}
            onClick={() => compare.mutate(pickedRuns)}
          >
            {compare.isPending ? 'Comparing…' : 'Compare'}
          </button>
        </div>
      </div>

      {/* Results */}
      {compareData && (
        <div className="card" style={{ marginTop: 14 }}>
          <div className="card-header">
            <h3>Comparison ({compareData.count} runs)</h3>
          </div>

          {/* Aligned equity curves */}
          <div style={{ padding: 14, height: 360 }}>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>
              Normalised equity (% from each run's start)
            </div>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={alignedCurves}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  dataKey="step"
                  tick={{ fontSize: 10 }}
                  stroke="var(--muted)"
                />
                <YAxis tick={{ fontSize: 10 }} stroke="var(--muted)" />
                <Tooltip {...chartTooltipStyles()} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {compareData.runs.map((r, i) => (
                  <Line
                    key={r.run_id}
                    type="monotone"
                    dataKey={r.run_id.slice(0, 8)}
                    name={`${r.strategy_name} (${r.run_id.slice(0, 6)})`}
                    stroke={PALETTE[i % PALETTE.length]}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Metric matrix */}
          <div style={{ padding: 14, overflowX: 'auto' }}>
            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: 12,
              }}
            >
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  <th
                    style={{
                      textAlign: 'left',
                      padding: '6px 10px',
                      color: 'var(--muted)',
                    }}
                  >
                    Metric
                  </th>
                  {compareData.runs.map((r, i) => (
                    <th
                      key={r.run_id}
                      style={{
                        textAlign: 'right',
                        padding: '6px 10px',
                        color: PALETTE[i % PALETTE.length],
                      }}
                    >
                      {r.strategy_name.length > 18
                        ? r.strategy_name.slice(0, 16) + '…'
                        : r.strategy_name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {compareData.metric_matrix.map((row) => (
                  <tr
                    key={row.metric}
                    style={{ borderBottom: '1px solid var(--border)' }}
                  >
                    <td
                      style={{
                        padding: '5px 10px',
                        color: 'var(--muted)',
                      }}
                    >
                      {row.metric}
                    </td>
                    {compareData.runs.map((r) => {
                      const v = (row as any)[r.run_id.slice(0, 8)]
                      return (
                        <td
                          key={r.run_id}
                          style={{
                            padding: '5px 10px',
                            textAlign: 'right',
                            fontWeight: 600,
                          }}
                        >
                          {typeof v === 'number' ? num(v, 2) : v ?? '—'}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

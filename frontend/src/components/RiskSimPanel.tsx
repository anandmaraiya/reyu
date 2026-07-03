/**
 * RiskSimPanel — "what would the worst stretch have felt like?" (F-B13)
 *
 * The learner persona's missing piece: a backtest's ROI headline hides
 * the pain along the way. This panel scales a run's trade P&L to the
 * user's own capital and shows the uncomfortable facts — worst week,
 * worst trade, longest losing streak, max drawdown in rupees. If those
 * numbers would make someone abandon the strategy mid-drawdown, better
 * to learn that BEFORE deploying. Historical facts only, no predictions.
 */
import { useState, type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

type Sim = {
  trades: number
  period_days?: number
  worst_day_inr?: number
  worst_week_inr?: number
  best_week_inr?: number
  worst_single_trade_inr?: number
  longest_losing_streak?: number
  losing_streak_loss_inr?: number
  max_drawdown_inr?: number
  final_equity_inr?: number
  note?: string
}

const inr = (n?: number) =>
  n == null ? '—' : (n < 0 ? '−₹' : '₹') + Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })

const S = {
  wrap: {
    border: '1px solid var(--border-default, var(--border))', borderRadius: 10,
    padding: 16, margin: '16px 0', background: 'var(--bg-surface, var(--card))',
  } as CSSProperties,
  head: { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' as const, marginBottom: 12 } as CSSProperties,
  title: { fontSize: 14, fontWeight: 700, margin: 0, flex: 1, minWidth: 200 } as CSSProperties,
  input: {
    width: 130, padding: '7px 10px', fontSize: 13, fontFamily: 'var(--font-mono)',
    background: 'var(--bg-elevated, var(--card2))', color: 'var(--text-primary, var(--text))',
    border: '1px solid var(--border-default, var(--border))', borderRadius: 8,
  } as CSSProperties,
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 } as CSSProperties,
  stat: { padding: '10px 12px', background: 'var(--bg-sunken, var(--card2))', borderRadius: 8 } as CSSProperties,
  statL: { fontSize: 10.5, color: 'var(--text-muted, var(--muted))', textTransform: 'uppercase' as const, letterSpacing: '.04em' } as CSSProperties,
  statV: (bad: boolean): CSSProperties => ({
    fontSize: 17, fontWeight: 700, fontFamily: 'var(--font-mono)', marginTop: 3,
    color: bad ? 'var(--danger, #e05252)' : 'var(--text-primary, var(--text))',
  }),
  note: { fontSize: 12, color: 'var(--text-secondary, var(--muted))', marginTop: 12, lineHeight: 1.55 } as CSSProperties,
}

export default function RiskSimPanel({ runId }: { runId: string | null }) {
  const [capital, setCapital] = useState(100_000)

  const { data } = useQuery<Sim>({
    queryKey: ['risk-sim', runId, capital],
    queryFn: async () =>
      (await api.get(`/api/strategies/runs/${runId}/risk-sim`, { params: { capital } })).data,
    enabled: !!runId,
  })

  if (!runId) return null

  return (
    <div style={S.wrap}>
      <div style={S.head}>
        <h3 style={S.title}>Risk simulator — how would the worst stretch feel?</h3>
        <label style={{ fontSize: 12, color: 'var(--text-muted, var(--muted))' }}>Your capital ₹</label>
        <input
          style={S.input}
          type="number" min={10000} step={10000} value={capital}
          onChange={e => setCapital(Math.max(10000, +e.target.value || 100000))}
        />
      </div>

      {data && data.trades === 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--text-muted, var(--muted))' }}>
          No closed trades in this run yet.
        </div>
      )}

      {data && data.trades > 0 && (
        <>
          <div style={S.grid}>
            <div style={S.stat}>
              <div style={S.statL}>Max drawdown</div>
              <div style={S.statV(true)}>{inr(data.max_drawdown_inr)}</div>
            </div>
            <div style={S.stat}>
              <div style={S.statL}>Worst week</div>
              <div style={S.statV(true)}>{inr(data.worst_week_inr)}</div>
            </div>
            <div style={S.stat}>
              <div style={S.statL}>Worst single trade</div>
              <div style={S.statV(true)}>{inr(data.worst_single_trade_inr)}</div>
            </div>
            <div style={S.stat}>
              <div style={S.statL}>Losing streak</div>
              <div style={S.statV(true)}>
                {data.longest_losing_streak} trades ({inr(data.losing_streak_loss_inr)})
              </div>
            </div>
            <div style={S.stat}>
              <div style={S.statL}>Best week (for contrast)</div>
              <div style={S.statV(false)}>{inr(data.best_week_inr)}</div>
            </div>
            <div style={S.stat}>
              <div style={S.statL}>Final equity</div>
              <div style={S.statV((data.final_equity_inr ?? capital) < capital)}>{inr(data.final_equity_inr)}</div>
            </div>
          </div>
          {data.note && <p style={S.note}>{data.note}</p>}
        </>
      )}
    </div>
  )
}

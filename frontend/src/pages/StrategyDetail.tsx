import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from 'recharts'
import { api } from '../api'
import { useToast } from '../toast'
import ConfirmDangerModal from '../components/ConfirmDangerModal'
import PreflightPanel from '../components/PreflightPanel'
import LegalAcceptModal from '../components/LegalAcceptModal'
import RiskNote from '../components/RiskNote'
import StrategyJourney from '../components/StrategyJourney'
import WalkForwardPanel from '../components/WalkForwardPanel'
import type { LegalDocMeta } from '../legal'
import { chartTooltipStyles } from '../chartTheme'

const num = (n: any, d = 2) =>
  n == null ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d })

type Strategy = {
  id: string
  version: number
  name: string
  description: string | null
  kind: string
  status: string
  tier_required: string
  spec: any
  tags: string[]
  created_at: string
}

type Run = {
  id: string
  strategy_id: string
  strategy_version: number
  mode: string
  status: string
  started_at: string
  ended_at: string | null
  metrics: any
  equity_curve: { ts: number | null; equity: number }[]
  data_quality: any
  params: any
  error_message: string | null
}

type Trade = {
  id: string
  entry_ts: string
  exit_ts: string | null
  entry_signal: any
  exit_reason: string
  legs: any[]
  gross_pnl_inr: number | null
  net_pnl_inr: number | null
  pnl_pct: number | null
  mae_pct: number | null
  mfe_pct: number | null
}

type Tab = 'recipe' | 'performance' | 'runs' | 'trades' | 'live'

type LiveMonitor = {
  active_run: { id: string; mode: string; status: string; started_at: string } | null
  open_positions: {
    id: string
    entry_ts: string
    leg: any
    current_ltp: number | null
    unrealised_inr: number | null
    unrealised_pct: number | null
  }[]
  today: {
    fills: number
    open: number
    closed: number
    wins: number
    realised_pnl_inr: number
    unrealised_pnl_inr: number
    total_pnl_inr: number
  }
}

export default function StrategyDetail() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [tab, setTab] = useState<Tab>('recipe')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  const { data: strat } = useQuery<Strategy>({
    queryKey: ['strategy', id],
    queryFn: async () => (await api.get(`/api/strategies/${id}`)).data,
  })

  const { data: runsList, refetch: refetchRuns } = useQuery<Run[]>({
    queryKey: ['runs', id],
    queryFn: async () =>
      (await api.get(`/api/strategies/${id}/runs?limit=50`)).data,
    refetchInterval: 5000,
  })

  // auto-select most recent run when list arrives
  if (runsList && runsList.length && !selectedRunId) {
    setSelectedRunId(runsList[0].id)
  }

  const { data: selRun } = useQuery<Run>({
    queryKey: ['run', selectedRunId],
    queryFn: async () =>
      (await api.get(`/api/strategies/runs/${selectedRunId}`)).data,
    enabled: !!selectedRunId,
    refetchInterval: (q) =>
      q.state.data?.status === 'RUNNING' ? 3000 : false,
  })

  const { data: trades } = useQuery<{ count: number; items: Trade[] }>({
    queryKey: ['trades', selectedRunId],
    queryFn: async () =>
      (
        await api.get(
          `/api/strategies/runs/${selectedRunId}/trades?limit=500`,
        )
      ).data,
    enabled: !!selectedRunId && tab === 'trades',
  })

  const newBacktest = useMutation({
    mutationFn: async () => {
      const today = new Date()
      const end = today.toISOString().slice(0, 10)
      const start = new Date(today.getTime() - 90 * 24 * 3600 * 1000)
        .toISOString()
        .slice(0, 10)
      const r = await api.post(
        `/api/strategies/${id}/runs?period_start=${start}&period_end=${end}&starting_capital=100000&seed=42`,
      )
      return r.data
    },
    onSuccess: () => {
      toast.push('success', 'Backtest queued — auto-refreshes when done')
      qc.invalidateQueries({ queryKey: ['runs', id] })
    },
    onError: (e: any) =>
      toast.push('error', e?.response?.data?.detail || 'Backtest failed'),
  })

  if (!strat) {
    return (
      <div className="page-shell">
        <div className="card" style={{ padding: 24 }}>
          Loading…
        </div>
      </div>
    )
  }

  return (
    <div className="page-shell">
      <RiskNote>
        This strategy is yours to test and deploy — Reyu doesn't recommend it or claim it's
        profitable. Backtest and forward-test results are hypothetical and don't predict future
        outcomes. Live deployment places real orders and needs your explicit approval.
      </RiskNote>
      <StrategyJourney status={strat.status} />
      {/* Header */}
      <div className="card">
        <div
          style={{
            padding: 14,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ flex: 1, minWidth: 240 }}>
            <button
              onClick={() => nav('/strategies')}
              style={{
                fontSize: 11,
                color: 'var(--muted)',
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                padding: 0,
                marginBottom: 6,
              }}
            >
              ← All strategies
            </button>
            <h3 style={{ margin: 0 }}>{strat.name}</h3>
            <div
              style={{
                fontSize: 12,
                color: 'var(--muted)',
                marginTop: 4,
              }}
            >
              {strat.kind} · v{strat.version} · {strat.status}
              {strat.spec?.universe?.[0] && ` · ${strat.spec.universe[0]}`}
            </div>
            {strat.description && (
              <div style={{ marginTop: 10, fontSize: 13 }}>
                {strat.description}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
            <button
              className="btn"
              onClick={() => newBacktest.mutate()}
              disabled={newBacktest.isPending}
            >
              {newBacktest.isPending ? 'Queuing…' : 'Run Backtest (90d)'}
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div
          style={{
            display: 'flex',
            borderTop: '1px solid var(--border)',
            borderBottom: '1px solid var(--border)',
          }}
        >
          {(['recipe', 'performance', 'runs', 'trades', 'live'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                padding: '10px 18px',
                border: 'none',
                background:
                  tab === t ? 'var(--accent)' : 'transparent',
                color: tab === t ? '#fff' : 'var(--text)',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: 12,
                textTransform: 'capitalize',
              }}
            >
              {t}
            </button>
          ))}
        </div>

        <div style={{ padding: 14 }}>
          {tab === 'recipe' && <RecipeTab spec={strat.spec} />}
          {tab === 'performance' && (
            <>
              <PerformanceTab
                run={selRun}
                runs={runsList || []}
                selectedRunId={selectedRunId}
                onSelectRun={setSelectedRunId}
              />
              <WalkForwardPanel strategyId={strat.id} />
            </>
          )}
          {tab === 'runs' && (
            <RunsTab
              runs={runsList || []}
              selectedRunId={selectedRunId}
              onSelect={(rid) => {
                setSelectedRunId(rid)
                setTab('performance')
              }}
            />
          )}
          {tab === 'trades' && (
            <TradesTab
              strategyId={id}
              strategy={strat}
              runs={runsList || []}
            />
          )}
          {tab === 'live' && <LiveTab strategyId={id} strategy={strat} />}
        </div>
      </div>
    </div>
  )
}

// ── Live Monitor tab ────────────────────────────────────────────────
function LiveTab({
  strategyId,
  strategy,
}: {
  strategyId: string
  strategy: Strategy
}) {
  const qc = useQueryClient()
  const toast = useToast()
  const { data, isLoading } = useQuery<LiveMonitor>({
    queryKey: ['live-monitor', strategyId],
    queryFn: async () =>
      (await api.get(`/api/strategies/${strategyId}/live-monitor`)).data,
    refetchInterval: 5000,
  })

  const [promoteMode, setPromoteMode] = useState<'PAPER_LIVE' | 'LIVE' | null>(null)
  const [promotePreflight, setPromotePreflight] = useState<any>(null)
  const [legalPending, setLegalPending] = useState<LegalDocMeta[] | null>(null)

  const promote = useMutation({
    mutationFn: async ({ mode }: { mode: 'PAPER_LIVE' | 'LIVE' }) => {
      const params = mode === 'LIVE' ? '?mode=LIVE&confirm=true' : '?mode=PAPER_LIVE'
      return (await api.post(`/api/strategies/${strategyId}/promote${params}`)).data
    },
    onSuccess: (data) => {
      toast.push('success',
        data.status === 'LIVE'
          ? 'Promoted to LIVE — real orders will fire when signals hit'
          : 'Promoted to PAPER_LIVE — scheduler will fire paper trades'
      )
      setPromoteMode(null)
      setPromotePreflight(null)
      qc.invalidateQueries({ queryKey: ['strategy', strategyId] })
    },
    onError: (e: any) => {
      const detail = e?.response?.data?.detail
      // Legal acceptance required — 451 with structured `legal_pending`.
      if (e?.response?.status === 451 && typeof detail === 'object' && detail?.legal_pending) {
        setLegalPending(detail.legal_pending)
        return
      }
      // Preflight FAIL returns 400 with structured `preflight` payload
      if (typeof detail === 'object' && detail?.preflight) {
        setPromotePreflight(detail.preflight)
        return
      }
      toast.push('error', typeof detail === 'string' ? detail : 'Promote failed')
    },
  })

  const halt = useMutation({
    mutationFn: () =>
      api.post(
        `/api/strategies/runs/${data?.active_run?.id}/halt`,
      ),
    onSuccess: () => {
      toast.push('success', 'Halted — open positions exited at last price')
      qc.invalidateQueries({ queryKey: ['live-monitor', strategyId] })
      qc.invalidateQueries({ queryKey: ['strategy', strategyId] })
    },
    onError: (e: any) =>
      toast.push('error', e?.response?.data?.detail || 'Halt failed'),
  })

  if (isLoading) return <div style={{ color: 'var(--muted)' }}>Loading…</div>

  const isLive = strategy.status === 'PAPER_LIVE' || strategy.status === 'LIVE'

  return (
    <div>
      {/* Header strip */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          marginBottom: 14,
          padding: 12,
          background: isLive ? '#2da14b22' : 'var(--card2)',
          borderRadius: 6,
          border: `1px solid ${isLive ? '#2da14b' : 'var(--border)'}`,
        }}
      >
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            Strategy status
          </div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>{strategy.status}</div>
        </div>
        {!isLive && strategy.status === 'BACKTESTED' && (
          <button
            className="btn btn-primary"
            onClick={() => {
              if (confirm('Promote to PAPER_LIVE? Scheduler will fire paper trades every minute during market hours.'))
                promote.mutate({ mode: 'PAPER_LIVE' })
            }}
          >
            Go Paper-Live
          </button>
        )}
        {strategy.status === 'PAPER_LIVE' && (
          <button
            className="btn"
            style={{ background: 'var(--danger)', color: '#fff', marginLeft: 8 }}
            onClick={() => setPromoteMode('LIVE')}
          >
            🚀 Promote to LIVE
          </button>
        )}
        {isLive && data?.active_run?.id && (
          <button
            className="btn"
            style={{ background: '#e54848', color: '#fff' }}
            onClick={() => {
              if (confirm('Halt this run? All open positions will exit at last-known price.'))
                halt.mutate()
            }}
          >
            🛑 Halt Run
          </button>
        )}
      </div>

      {/* Today KPIs */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
          gap: 10,
          marginBottom: 14,
        }}
      >
        <KPI label="Today's fills" value={num(data?.today.fills, 0)} />
        <KPI label="Open now" value={num(data?.today.open, 0)} />
        <KPI label="Closed" value={num(data?.today.closed, 0)} />
        <KPI
          label="Wins / closed"
          value={
            data?.today.closed
              ? `${data.today.wins} / ${data.today.closed}`
              : '—'
          }
        />
        <KPI
          label="Realised ₹"
          value={num(data?.today.realised_pnl_inr, 0)}
          accent={
            (data?.today.realised_pnl_inr ?? 0) >= 0 ? '#2da14b' : '#e54848'
          }
        />
        <KPI
          label="Unrealised ₹"
          value={num(data?.today.unrealised_pnl_inr, 0)}
          accent={
            (data?.today.unrealised_pnl_inr ?? 0) >= 0 ? '#2da14b' : '#e54848'
          }
        />
        <KPI
          label="Total P&L ₹"
          value={num(data?.today.total_pnl_inr, 0)}
          accent={
            (data?.today.total_pnl_inr ?? 0) >= 0 ? '#2da14b' : '#e54848'
          }
        />
      </div>

      {/* Active run */}
      {data?.active_run ? (
        <div
          style={{
            fontSize: 12,
            color: 'var(--muted)',
            marginBottom: 10,
          }}
        >
          Active run · {data.active_run.mode} · started{' '}
          {new Date(data.active_run.started_at).toLocaleString()} ·{' '}
          status{' '}
          <b style={{ color: 'var(--text)' }}>{data.active_run.status}</b>
        </div>
      ) : (
        <div style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 14 }}>
          No active paper or live run.
        </div>
      )}

      {/* Open positions */}
      <Section title={`Open positions (${data?.open_positions.length ?? 0})`}>
        {data?.open_positions.length ? (
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Entry', 'Symbol', 'Qty', 'Entry ₹', 'Current ₹', 'Unreal %', 'Unreal ₹'].map((h) => (
                  <th
                    key={h}
                    style={{
                      textAlign: 'right',
                      padding: '6px 8px',
                      color: 'var(--muted)',
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.open_positions.map((p) => (
                <tr
                  key={p.id}
                  style={{ borderBottom: '1px solid var(--border)' }}
                >
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                    {new Date(p.entry_ts).toLocaleString()}
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                    {p.leg?.symbol || '—'}
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                    {p.leg?.qty || '—'}
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                    {num(p.leg?.entry_price, 2)}
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                    {num(p.current_ltp, 2)}
                  </td>
                  <td
                    style={{
                      padding: '6px 8px', textAlign: 'right', fontWeight: 600,
                      color: (p.unrealised_pct ?? 0) >= 0 ? '#2da14b' : '#e54848',
                    }}
                  >
                    {p.unrealised_pct != null ? `${num(p.unrealised_pct, 2)}%` : '—'}
                  </td>
                  <td
                    style={{
                      padding: '6px 8px', textAlign: 'right', fontWeight: 600,
                      color: (p.unrealised_inr ?? 0) >= 0 ? '#2da14b' : '#e54848',
                    }}
                  >
                    {num(p.unrealised_inr, 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ color: 'var(--muted)', fontSize: 12 }}>
            No open positions.
          </div>
        )}
      </Section>

      <div
        style={{ marginTop: 12, fontSize: 11, color: 'var(--muted)' }}
      >
        ⟳ auto-refreshes every 5 s
      </div>

      {/* LIVE promotion — typed-confirm modal with preflight results */}
      <ConfirmDangerModal
        open={promoteMode === 'LIVE'}
        title="Promote to LIVE trading"
        description={
          `Promoting to LIVE means the platform will place real orders on your ` +
          `broker account when this strategy signals. This spends real money and ` +
          `is irreversible per-trade. Preflight below shows what would fire.`
        }
        expectedText={strategy?.name || 'CONFIRM'}
        confirmLabel={promote.isPending ? 'Promoting…' : 'Promote to LIVE'}
        variant="danger"
        extraGate={promotePreflight?.verdict !== 'FAIL'}
        onCancel={() => { setPromoteMode(null); setPromotePreflight(null) }}
        onConfirm={() => promote.mutate({ mode: 'LIVE' })}
      >
        {promotePreflight && <PreflightPanel result={promotePreflight} loading={false} />}
        {!promotePreflight && (
          <div style={{
            padding: 10, fontSize: 12,
            color: 'var(--text-secondary)',
            background: 'var(--bg-sunken)',
            borderRadius: 4, marginBottom: 12,
          }}>
            Preflight runs on submit — checks broker auth, margin, lot sizes.
          </div>
        )}
      </ConfirmDangerModal>

      {/* LIVE execution authorization — shown when the backend returns 451
          (legal acceptance required) on a LIVE promote attempt. */}
      {legalPending && (
        <LegalAcceptModal
          docs={legalPending}
          title="Authorize live execution"
          subtitle={
            'Deploying to LIVE places real orders on your broker account. ' +
            'Please review and accept the following before continuing.'
          }
          onClose={() => setLegalPending(null)}
          onAccepted={() => { setLegalPending(null); promote.mutate({ mode: 'LIVE' }) }}
        />
      )}
    </div>
  )
}

// ── Recipe tab ──────────────────────────────────────────────────────
function RecipeTab({ spec }: { spec: any }) {
  if (!spec) return <div>—</div>
  const legs = spec.legs || []
  const ent = spec.entry_rules || {}
  const ex = spec.exit_rules || {}
  const risk = spec.risk || {}

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        gap: 14,
      }}
    >
      <Section title="Legs">
        {legs.map((l: any) => (
          <div
            key={l.leg_id}
            style={{ fontSize: 12, padding: '6px 0', borderBottom: '1px solid var(--border)' }}
          >
            <b>{l.action}</b> {l.qty_lots}× {l.instrument_type}{' '}
            {l.option_type && `${l.option_type}`}
            {l.strike?.mode === 'ATM_OFFSET' &&
              ` @ ATM${l.strike.offset >= 0 ? '+' : ''}${l.strike.offset}`}
            {l.strike?.mode === 'ABSOLUTE' && ` @ ${l.strike.value}`}
            {l.expiry &&
              ` · ${l.expiry.mode}${
                l.expiry.offset != null ? ` +${l.expiry.offset}` : ''
              }`}
          </div>
        ))}
      </Section>

      <Section title="Entry">
        <KV k="Trigger" v={ent.trigger} />
        <KV k="Schedule" v={ent.schedule?.time_window} />
        <KV k="Days" v={(ent.schedule?.days || []).join(', ')} />
        {(ent.conditions || []).map((c: any, i: number) => (
          <KV
            key={i}
            k={`Condition ${i + 1}`}
            v={`${c.feature} ${c.op} ${
              Array.isArray(c.value) ? `[${c.value.join(', ')}]` : c.value
            }`}
          />
        ))}
      </Section>

      <Section title="Exit">
        <KV k="Take-profit" v={ex.tp_pct ? `${(ex.tp_pct * 100).toFixed(1)}%` : '—'} />
        <KV k="Stop-loss" v={ex.sl_pct ? `${(ex.sl_pct * 100).toFixed(1)}%` : '—'} />
        <KV k="Time stop" v={ex.time_stop_minutes ? `${ex.time_stop_minutes} min` : '—'} />
        <KV k="Exit at close" v={ex.exit_at_close ? 'yes' : 'no'} />
      </Section>

      <Section title="Risk caps">
        <KV k="Max concurrent" v={risk.max_concurrent} />
        <KV k="Max daily loss ₹" v={num(risk.max_daily_loss_inr)} />
        <KV k="Max position ₹" v={num(risk.max_position_inr)} />
        <KV k="Max drawdown %" v={risk.max_drawdown_pct} />
      </Section>
    </div>
  )
}

// ── Performance tab ─────────────────────────────────────────────────
function PerformanceTab({
  run,
  runs,
  selectedRunId,
  onSelectRun,
}: {
  run: Run | undefined
  runs: Run[]
  selectedRunId: string | null
  onSelectRun: (id: string) => void
}) {
  if (!run) {
    return (
      <div style={{ textAlign: 'center', color: 'var(--muted)', padding: 30 }}>
        No runs yet. Click <b>Run Backtest</b> above.
      </div>
    )
  }

  const m = run.metrics || {}
  const curve = (run.equity_curve || []).map((p, i) => ({
    idx: i,
    equity: p.equity,
  }))
  const startCap = m.starting_capital ?? 100000

  return (
    <div>
      <div
        style={{
          display: 'flex',
          gap: 8,
          flexWrap: 'wrap',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>Run:</span>
        <select
          value={selectedRunId || ''}
          onChange={(e) => onSelectRun(e.target.value)}
          style={{
            background: 'var(--card2)',
            color: 'var(--text)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            padding: '4px 8px',
            fontSize: 12,
          }}
        >
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              {new Date(r.started_at).toLocaleString()} · {r.mode} ·{' '}
              {r.status}
            </option>
          ))}
        </select>
        {run.status === 'RUNNING' && (
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            ⟳ running…
          </span>
        )}
      </div>

      {/* KPI strip */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
          gap: 10,
          marginBottom: 18,
        }}
      >
        <KPI label="Trades" value={num(m.total_trades, 0)} />
        <KPI
          label="Win rate"
          value={m.win_rate != null ? `${(m.win_rate * 100).toFixed(1)}%` : '—'}
        />
        <KPI
          label="ROI"
          value={m.roi_pct != null ? `${num(m.roi_pct, 2)}%` : '—'}
          accent={(m.roi_pct ?? 0) >= 0 ? '#2da14b' : '#e54848'}
        />
        <KPI
          label="Max DD"
          value={m.max_drawdown_pct != null ? `${num(m.max_drawdown_pct, 2)}%` : '—'}
        />
        <KPI label="Sharpe" value={num(m.sharpe, 2)} />
        <KPI label="Profit fct" value={num(m.profit_factor, 2)} />
        <KPI label="Fees ₹" value={num(m.fees_paid_inr, 0)} />
        <KPI label="Final ₹" value={num(m.final_capital, 0)} />
      </div>

      {/* Equity curve */}
      {curve.length > 1 && (
        <div style={{ height: 260 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
            Equity curve (trade-by-trade)
          </div>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={curve}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="idx" tick={{ fontSize: 10 }} stroke="var(--muted)" />
              <YAxis
                tick={{ fontSize: 10 }}
                stroke="var(--muted)"
                domain={['dataMin', 'dataMax']}
              />
              <Tooltip {...chartTooltipStyles()} />
              <ReferenceLine y={startCap} stroke="var(--muted)" strokeDasharray="3 3" />
              <Line
                type="monotone"
                dataKey="equity"
                stroke="#4a9fda"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Data quality */}
      {run.data_quality && Object.keys(run.data_quality).length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 14 }}>
          <b>Data quality:</b> {run.data_quality.sessions_processed}/
          {(run.data_quality.sessions_processed || 0) +
            (run.data_quality.sessions_skipped || 0)}{' '}
          sessions processed
          {run.data_quality.source_mix_pct && (
            <>
              {' · '}
              source mix:{' '}
              {Object.entries(run.data_quality.source_mix_pct)
                .map(([k, v]) => `${k}: ${v}%`)
                .join(', ')}
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Runs tab ───────────────────────────────────────────────────────
function RunsTab({
  runs,
  selectedRunId,
  onSelect,
}: {
  runs: Run[]
  selectedRunId: string | null
  onSelect: (id: string) => void
}) {
  if (runs.length === 0)
    return <div style={{ color: 'var(--muted)' }}>No runs yet.</div>

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
      <thead>
        <tr style={{ borderBottom: '1px solid var(--border)' }}>
          {['Started', 'Mode', 'Status', 'Trades', 'WR', 'ROI', 'DD', 'Sharpe', ''].map(
            (h) => (
              <th
                key={h}
                style={{
                  textAlign: 'left',
                  padding: '6px 8px',
                  color: 'var(--muted)',
                }}
              >
                {h}
              </th>
            ),
          )}
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => {
          const m = r.metrics || {}
          return (
            <tr
              key={r.id}
              style={{
                borderBottom: '1px solid var(--border)',
                background: r.id === selectedRunId ? 'var(--card2)' : 'transparent',
              }}
            >
              <td style={{ padding: '6px 8px' }}>
                {new Date(r.started_at).toLocaleString()}
              </td>
              <td style={{ padding: '6px 8px' }}>{r.mode}</td>
              <td style={{ padding: '6px 8px' }}>{r.status}</td>
              <td style={{ padding: '6px 8px' }}>{num(m.total_trades, 0)}</td>
              <td style={{ padding: '6px 8px' }}>
                {m.win_rate != null ? `${(m.win_rate * 100).toFixed(1)}%` : '—'}
              </td>
              <td
                style={{
                  padding: '6px 8px',
                  color: (m.roi_pct ?? 0) >= 0 ? '#2da14b' : '#e54848',
                  fontWeight: 600,
                }}
              >
                {m.roi_pct != null ? `${num(m.roi_pct, 2)}%` : '—'}
              </td>
              <td style={{ padding: '6px 8px' }}>
                {m.max_drawdown_pct != null
                  ? `${num(m.max_drawdown_pct, 2)}%`
                  : '—'}
              </td>
              <td style={{ padding: '6px 8px' }}>{num(m.sharpe, 2)}</td>
              <td style={{ padding: '6px 8px' }}>
                <button
                  onClick={() => onSelect(r.id)}
                  style={{
                    fontSize: 11,
                    color: 'var(--accent)',
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    padding: 0,
                  }}
                >
                  view →
                </button>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Trades tab ─────────────────────────────────────────────────────
function TradesTab({
  strategyId,
  strategy,
  runs,
}: {
  strategyId: string
  strategy: Strategy
  runs: Run[]
}) {
  // Default: expand the most recent run only
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(runs[0] ? [runs[0].id] : []),
  )

  // Auto-expand the latest run on first arrival
  useEffect(() => {
    if (runs.length && expanded.size === 0) {
      setExpanded(new Set([runs[0].id]))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs.length])

  if (!runs.length) {
    return (
      <div style={{ color: 'var(--muted)' }}>
        No runs yet. Click <b>Run Backtest</b> above or promote to PAPER_LIVE
        to start seeing trades.
      </div>
    )
  }

  const toggle = (rid: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(rid)) next.delete(rid); else next.add(rid)
      return next
    })
  }

  return (
    <div>
      {runs.map((r) => (
        <RunTradesGroup
          key={r.id}
          run={r}
          strategy={strategy}
          strategyId={strategyId}
          isExpanded={expanded.has(r.id)}
          onToggle={() => toggle(r.id)}
        />
      ))}
    </div>
  )
}

function RunTradesGroup({
  run,
  strategy,
  strategyId,
  isExpanded,
  onToggle,
}: {
  run: Run
  strategy: Strategy
  strategyId: string
  isExpanded: boolean
  onToggle: () => void
}) {
  // Lazy-fetch trades only when expanded; live-mode runs refetch every 5s
  const isLive = run.mode === 'PAPER' || run.mode === 'LIVE'
  const { data: tradesData } = useQuery<{ count: number; items: Trade[] }>({
    queryKey: ['run-trades', run.id],
    queryFn: async () =>
      (await api.get(`/api/strategies/runs/${run.id}/trades?limit=500`)).data,
    enabled: isExpanded,
    refetchInterval: isExpanded && isLive ? 5000 : false,
  })

  const items = tradesData?.items || []
  const m = run.metrics || {}
  const modeColor =
    run.mode === 'LIVE'
      ? '#e54848'
      : run.mode === 'PAPER'
        ? '#f0a830'
        : '#4a9fda'
  const statusColor =
    run.status === 'RUNNING'
      ? '#2da14b'
      : run.status === 'COMPLETED'
        ? '#4a9fda'
        : run.status === 'HALTED'
          ? '#888'
          : '#e54848'

  // Compute on-the-fly aggregates for live runs (DB metrics may be stale)
  const totalPnl =
    items.reduce((s, t) => s + (t.gross_pnl_inr ?? 0), 0) || m.fees_paid_inr
  const wins = items.filter((t) => t.exit_reason === 'TP').length
  const losses = items.filter((t) => t.exit_reason === 'SL').length
  const opens = items.filter((t) => !t.exit_ts).length

  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 6,
        marginBottom: 8,
        overflow: 'hidden',
      }}
    >
      {/* Header — clickable to expand */}
      <div
        onClick={onToggle}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '10px 14px',
          cursor: 'pointer',
          background: isExpanded ? 'var(--card2)' : 'transparent',
          borderBottom: isExpanded ? '1px solid var(--border)' : 'none',
        }}
      >
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          {isExpanded ? '▾' : '▸'}
        </span>
        <span
          style={{
            background: modeColor,
            color: '#fff',
            padding: '2px 8px',
            borderRadius: 10,
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 0.5,
          }}
        >
          {run.mode}
        </span>
        <span
          style={{
            background: statusColor,
            color: '#fff',
            padding: '2px 8px',
            borderRadius: 10,
            fontSize: 10,
            fontWeight: 600,
          }}
        >
          {run.status}
        </span>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>
          {new Date(run.started_at).toLocaleString()}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          strategy: <b style={{ color: 'var(--text)' }}>{strategy.name}</b> v{strategy.version}
        </span>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          trades: <b style={{ color: 'var(--text)' }}>{m.total_trades ?? items.length}</b>
        </span>
        {opens > 0 && (
          <span style={{ fontSize: 11, color: '#f0a830', fontWeight: 600 }}>
            {opens} open
          </span>
        )}
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: (m.roi_pct ?? 0) >= 0 ? '#2da14b' : '#e54848',
          }}
        >
          ROI {m.roi_pct != null ? `${num(m.roi_pct, 2)}%` : '—'}
        </span>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: (totalPnl ?? 0) >= 0 ? '#2da14b' : '#e54848',
          }}
        >
          ₹{num(totalPnl, 0)}
        </span>
      </div>

      {/* Body */}
      {isExpanded && (
        <div style={{ overflowX: 'auto', padding: 8 }}>
          {!tradesData ? (
            <div style={{ color: 'var(--muted)', padding: 12, fontSize: 12 }}>
              Loading trades…
            </div>
          ) : items.length === 0 ? (
            <div style={{ color: 'var(--muted)', padding: 12, fontSize: 12 }}>
              No trades fired in this run yet.
              {run.status === 'RUNNING' &&
                ' (live — auto-refreshes every 5 s)'}
            </div>
          ) : (
            <>
              <table
                style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontSize: 12,
                }}
              >
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {[
                      'Entry',
                      'Exit',
                      'Symbol',
                      'Side',
                      'Reason',
                      'Qty',
                      'Entry ₹',
                      'Exit ₹',
                      'P&L %',
                      'P&L ₹',
                      'MAE %',
                      'MFE %',
                    ].map((h, i) => (
                      <th
                        key={h}
                        style={{
                          textAlign: i < 4 ? 'left' : 'right',
                          padding: '6px 8px',
                          color: 'var(--muted)',
                          fontWeight: 600,
                          fontSize: 10,
                          textTransform: 'uppercase',
                          letterSpacing: 0.4,
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((t) => {
                    const leg = t.legs?.[0] || ({} as any)
                    const pnlColor =
                      (t.pnl_pct ?? 0) >= 0 ? '#2da14b' : '#e54848'
                    const open = !t.exit_ts
                    return (
                      <tr
                        key={t.id}
                        style={{
                          borderBottom: '1px solid var(--border)',
                          background: open ? '#f0a83015' : 'transparent',
                        }}
                      >
                        <td style={{ padding: '4px 8px' }}>
                          {new Date(t.entry_ts).toLocaleTimeString()}
                          <div
                            style={{ fontSize: 10, color: 'var(--muted)' }}
                          >
                            {new Date(t.entry_ts).toLocaleDateString()}
                          </div>
                        </td>
                        <td style={{ padding: '4px 8px' }}>
                          {open
                            ? <span style={{ color: '#f0a830', fontWeight: 600 }}>OPEN</span>
                            : new Date(t.exit_ts!).toLocaleTimeString()}
                        </td>
                        <td
                          style={{
                            padding: '4px 8px',
                            fontFamily: 'monospace',
                            fontSize: 11,
                          }}
                        >
                          {leg.symbol || '—'}
                        </td>
                        <td style={{ padding: '4px 8px' }}>
                          <span
                            style={{
                              background:
                                leg.action === 'BUY' ? '#2da14b22' : '#e5484822',
                              color: leg.action === 'BUY' ? '#2da14b' : '#e54848',
                              padding: '1px 6px',
                              borderRadius: 4,
                              fontSize: 10,
                              fontWeight: 600,
                            }}
                          >
                            {leg.action || '—'}
                          </span>
                        </td>
                        <td style={{ padding: '4px 8px' }}>
                          <span
                            style={{
                              fontSize: 10,
                              color:
                                t.exit_reason === 'TP'
                                  ? '#2da14b'
                                  : t.exit_reason === 'SL'
                                    ? '#e54848'
                                    : 'var(--muted)',
                              fontWeight: 600,
                            }}
                          >
                            {t.exit_reason || (open ? '—' : '?')}
                          </span>
                        </td>
                        <td style={{ padding: '4px 8px', textAlign: 'right' }}>
                          {leg.qty}
                        </td>
                        <td style={{ padding: '4px 8px', textAlign: 'right' }}>
                          {num(leg.entry_price)}
                        </td>
                        <td style={{ padding: '4px 8px', textAlign: 'right' }}>
                          {open ? '—' : num(leg.exit_price)}
                        </td>
                        <td
                          style={{
                            padding: '4px 8px',
                            textAlign: 'right',
                            color: pnlColor,
                            fontWeight: 600,
                          }}
                        >
                          {t.pnl_pct != null ? `${num(t.pnl_pct, 2)}%` : '—'}
                        </td>
                        <td
                          style={{
                            padding: '4px 8px',
                            textAlign: 'right',
                            fontWeight: 600,
                            color: pnlColor,
                          }}
                        >
                          {num(t.gross_pnl_inr, 0)}
                        </td>
                        <td
                          style={{
                            padding: '4px 8px',
                            textAlign: 'right',
                            color: 'var(--muted)',
                          }}
                        >
                          {t.mae_pct != null ? `${num(t.mae_pct, 1)}%` : '—'}
                        </td>
                        <td
                          style={{
                            padding: '4px 8px',
                            textAlign: 'right',
                            color: 'var(--muted)',
                          }}
                        >
                          {t.mfe_pct != null ? `${num(t.mfe_pct, 1)}%` : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <div
                style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}
              >
                Run id: <code>{run.id.slice(0, 8)}</code> · {items.length} trades
                · TP {wins} · SL {losses}
                {isLive && run.status === 'RUNNING' &&
                  ' · ⟳ auto-refresh 5s'}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Small reusables ────────────────────────────────────────────────
function Section({ title, children }: { title: string; children: any }) {
  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 6,
        padding: 10,
      }}
    >
      <div
        style={{
          fontSize: 11,
          color: 'var(--muted)',
          textTransform: 'uppercase',
          letterSpacing: 0.6,
          marginBottom: 8,
        }}
      >
        {title}
      </div>
      {children}
    </div>
  )
}

function KV({ k, v }: { k: string; v: any }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        padding: '4px 0',
        fontSize: 12,
      }}
    >
      <span style={{ color: 'var(--muted)' }}>{k}</span>
      <span style={{ color: 'var(--text)', fontWeight: 600 }}>{v ?? '—'}</span>
    </div>
  )
}

function KPI({
  label,
  value,
  accent,
}: {
  label: string
  value: any
  accent?: string
}) {
  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 6,
        padding: 10,
      }}
    >
      <div style={{ fontSize: 10, color: 'var(--muted)' }}>{label}</div>
      <div
        style={{
          fontSize: 18,
          fontWeight: 700,
          color: accent || 'var(--text)',
        }}
      >
        {value}
      </div>
    </div>
  )
}

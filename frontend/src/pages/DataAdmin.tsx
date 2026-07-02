/**
 * Superadmin (algo@reyu.ai only) — dataset capture dashboard + ops tools.
 *
 *  - Daily fills per table for the last 14 days (raw rowcounts)
 *  - Scheduler job list with next-firing times
 *  - One-click pipeline test against Fyers
 *  - One-click manual job runner (when you don't want to wait for the cron)
 *
 * Styling: uses the design tokens from tokens.css so it follows
 * light/dark theme automatically.
 */
import { useState, type CSSProperties } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useAuth } from '../context/AuthContext'
import PageHelp from '../components/PageHelp'

type DailyFills = {
  days: number
  from: string
  tables: Record<string, {
    total_rows: number
    key_dim: string
    by_day: { day: string; rows: number; distinct_keys: number }[]
  }>
}

type SchedulerStatus = {
  running: boolean
  jobs: { id: string; name: string; trigger: string; next_run_time: string | null }[]
}

type TestResult = {
  underlying: string
  overall: string
  stages: Record<string, any>
}

type JobRunResult = {
  job: string
  ok: boolean
  error: string | null
  duration_sec: number
  started_at: string
  ended_at: string
}

type AuditEntry = {
  id: string; ts: string
  actor_id: string | null; actor_email: string | null
  event_type: string; resource_type: string | null; resource_id: string | null
  action: string | null; ip_address: string | null; user_agent: string
}
type AuditLog = { days: number; total: number; entries: AuditEntry[] }

type RegimeRouterTrades = {
  days: number
  trades: Array<{
    date: string
    underlying: string
    regime: string
    action: string
    mom_3d_pct: number | null
    pcr_oi: number | null
    atm_strike: number | null
    entry_premium: number | null
    exit_premium: number | null
    pnl_inr: number | null
    status: string
  }>
  summary: {
    total: number
    wins: number
    losses: number
    skips: number
    win_rate: number
    total_pnl_inr: number
  }
}

const TABLES = [
  'option_contract_1m',
  'option_strike_snapshot',
  'tick_1m',
  'option_eod',
]

const JOBS = [
  { id: 'daily_options_history', label: 'Daily options-1m backfill (7d × 14 underlyings)' },
  { id: 'weekly_long_backfill', label: 'Weekly 100-day backfill (20 underlyings)' },
  { id: 'morning_batch', label: 'Morning batch (yesterday Bhavcopy + 30d options)' },
  { id: 'bhavcopy_daily', label: 'Bhavcopy pull (today\'s EOD)' },
  { id: 'dataset_health', label: 'Dataset health log' },
  { id: 'fyers_eod_snapshot', label: 'Fyers EOD snapshot (orders/trades)' },
]

// ── Token-based styles (work in light + dark) ─────────────────────────
const S = {
  page: {
    padding: '20px 32px',
    maxWidth: 1400,
    color: 'var(--text-primary)',
    background: 'var(--bg-base)',
    minHeight: '100vh',
  } as CSSProperties,
  title: {
    margin: '0 0 4px 0',
    color: 'var(--text-primary)',
    fontSize: 22,
    fontWeight: 600,
  } as CSSProperties,
  subtitle: {
    color: 'var(--text-secondary)',
    marginBottom: 24,
    fontSize: 13,
  } as CSSProperties,
  card: {
    marginBottom: 24,
    padding: 18,
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-md)',
    boxShadow: 'var(--shadow-sm)',
  } as CSSProperties,
  cardTitle: {
    margin: '0 0 14px 0',
    fontSize: 15,
    fontWeight: 600,
    color: 'var(--text-primary)',
  } as CSSProperties,
  button: {
    padding: '8px 14px',
    fontSize: 13,
    background: 'var(--bg-elevated)',
    color: 'var(--text-primary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    transition: 'all 120ms',
  } as CSSProperties,
  buttonPrimary: {
    padding: '8px 16px',
    fontSize: 13,
    background: 'var(--brand-primary)',
    color: '#fff',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    fontWeight: 600,
  } as CSSProperties,
  buttonDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  } as CSSProperties,
  statTile: {
    padding: 14,
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border-subtle)',
    borderRadius: 'var(--radius-sm)',
  } as CSSProperties,
  statLabel: {
    fontSize: 11,
    color: 'var(--text-secondary)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
    fontWeight: 500,
  } as CSSProperties,
  statValue: {
    fontSize: 22,
    fontWeight: 700,
    color: 'var(--text-primary)',
    marginTop: 2,
  } as CSSProperties,
  statHint: {
    fontSize: 11,
    color: 'var(--text-muted)',
    marginTop: 2,
  } as CSSProperties,
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: 13,
    color: 'var(--text-primary)',
    marginTop: 6,
  } as CSSProperties,
  th: {
    padding: '8px 10px',
    textAlign: 'left' as const,
    background: 'var(--bg-sunken)',
    color: 'var(--text-secondary)',
    fontWeight: 600,
    fontSize: 12,
    borderBottom: '1px solid var(--border-default)',
  } as CSSProperties,
  td: {
    padding: '6px 10px',
    borderBottom: '1px solid var(--border-subtle)',
    color: 'var(--text-primary)',
  } as CSSProperties,
  pre: {
    background: 'var(--bg-sunken)',
    color: 'var(--text-primary)',
    padding: 12,
    fontSize: 12,
    fontFamily: 'var(--font-mono)',
    border: '1px solid var(--border-subtle)',
    borderRadius: 'var(--radius-sm)',
    overflow: 'auto',
    maxHeight: 240,
  } as CSSProperties,
  verdictPass: {
    padding: 12,
    background: 'var(--brand-light)',
    color: 'var(--brand-text)',
    border: '1px solid var(--border-brand)',
    borderRadius: 'var(--radius-sm)',
    marginBottom: 14,
    fontWeight: 600,
  } as CSSProperties,
  verdictFail: {
    padding: 12,
    background: 'var(--danger-light)',
    color: 'var(--danger-text)',
    border: '1px solid var(--danger)',
    borderRadius: 'var(--radius-sm)',
    marginBottom: 14,
    fontWeight: 600,
  } as CSSProperties,
  summary: {
    cursor: 'pointer',
    padding: '8px 0',
    color: 'var(--text-primary)',
    fontSize: 13,
  } as CSSProperties,
}

function verdictColor(verdict: string | undefined): string {
  if (!verdict) return 'var(--text-muted)'
  if (verdict.startsWith('PASS')) return 'var(--brand-primary)'
  if (verdict.startsWith('WARN')) return 'var(--signal)'
  return 'var(--danger)'
}

export default function DataAdmin() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [jobResults, setJobResults] = useState<JobRunResult[]>([])

  // ── Gate: superadmin only ───────────────────────────────────────────
  if (!user || user.email !== 'algo@reyu.ai') {
    return (
      <div style={S.page}>
        <h2 style={S.title}>Access denied</h2>
        <p style={S.subtitle}>This dashboard is restricted to the superadmin account.</p>
      </div>
    )
  }

  // ── Queries ────────────────────────────────────────────────────────
  const fills = useQuery<DailyFills>({
    queryKey: ['daily-fills'],
    queryFn: async () => (await api.get('/api/admin/data/daily-fills?days=14')).data,
    refetchInterval: 60_000,
  })

  const sched = useQuery<SchedulerStatus>({
    queryKey: ['scheduler-status'],
    queryFn: async () => (await api.get('/api/admin/data/scheduler-status')).data,
    refetchInterval: 60_000,
  })

  const runTest = useMutation({
    mutationFn: async () => {
      const { data } = await api.post(
        '/api/admin/data/test-fyers-pipeline?underlying=NSE%3ANIFTY50-INDEX&history_back_days=7',
      )
      return data as TestResult
    },
    onSuccess: (data) => {
      setTestResult(data)
      qc.invalidateQueries({ queryKey: ['daily-fills'] })
    },
  })

  const runJob = useMutation({
    mutationFn: async (job: string) => {
      const { data } = await api.post(`/api/admin/data/run-job?job=${job}`)
      return data as JobRunResult
    },
    onSuccess: (data) => {
      setJobResults((prev) => [data, ...prev].slice(0, 10))
      qc.invalidateQueries({ queryKey: ['daily-fills'] })
    },
  })

  const rrTrades = useQuery<RegimeRouterTrades>({
    queryKey: ['regime-router-trades'],
    queryFn: async () => (await api.get('/api/admin/data/regime-router/trades?days=30')).data,
    refetchInterval: 30_000,
  })

  const auditLog = useQuery<AuditLog>({
    queryKey: ['audit-log'],
    queryFn: async () => (await api.get('/api/audit/log?days=30&limit=50')).data,
    refetchInterval: 30_000,
  })

  const exportAudit = () => {
    const token = localStorage.getItem('reyu_access_token') || ''
    fetch('/api/audit/export.csv?days=365', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.blob())
      .then(blob => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `reyu-audit-${new Date().toISOString().slice(0, 10)}.csv`
        a.click()
        URL.revokeObjectURL(url)
      })
  }

  const runRR = useMutation({
    mutationFn: async (job: 'morning' | 'close') => {
      const { data } = await api.post(`/api/admin/data/regime-router/run-now?job=${job}`)
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['regime-router-trades'] })
    },
  })

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <div style={S.page}>
      <PageHelp pageId="admin-data" />
      <h1 style={S.title}>Dataset Capture — Admin</h1>
      <div style={S.subtitle}>Superadmin · {user.email}</div>

      {/* ── PIPELINE TEST ─────────────────────────────────────────── */}
      <div style={S.card}>
        <h3 style={S.cardTitle}>Fyers Pipeline Test</h3>
        <button
          style={{ ...S.buttonPrimary, ...(runTest.isPending ? S.buttonDisabled : {}) }}
          disabled={runTest.isPending}
          onClick={() => runTest.mutate()}
        >
          {runTest.isPending ? 'Testing…' : 'Run end-to-end test (NIFTY, 7 days)'}
        </button>
        {testResult && (
          <div style={{ marginTop: 16 }}>
            <div style={testResult.overall.startsWith('PASS') ? S.verdictPass : S.verdictFail}>
              {testResult.overall}
            </div>
            {Object.entries(testResult.stages).map(([stage, info]: any) => (
              <details key={stage} style={{ marginBottom: 8 }}>
                <summary style={S.summary}>
                  <strong>{stage}</strong>{' — '}
                  <span style={{ color: verdictColor(info?.verdict) }}>
                    {info?.verdict ?? 'no verdict'}
                  </span>
                </summary>
                <pre style={S.pre}>{JSON.stringify(info, null, 2)}</pre>
              </details>
            ))}
          </div>
        )}
      </div>

      {/* ── DAILY FILLS ───────────────────────────────────────────── */}
      <div style={S.card}>
        <h3 style={S.cardTitle}>Daily Fills — last 14 days</h3>
        {fills.isLoading && <div style={{ color: 'var(--text-secondary)' }}>Loading…</div>}
        {fills.data && (
          <>
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              gap: 14, marginBottom: 16,
            }}>
              {TABLES.map((t) => {
                const info = fills.data!.tables[t]
                if (!info) return null
                return (
                  <div key={t} style={S.statTile}>
                    <div style={S.statLabel}>{t}</div>
                    <div style={S.statValue}>{info.total_rows.toLocaleString()}</div>
                    <div style={S.statHint}>total rows</div>
                  </div>
                )
              })}
            </div>

            {TABLES.map((t) => {
              const info = fills.data!.tables[t]
              if (!info) return null
              return (
                <details key={t} style={{ marginBottom: 8 }}>
                  <summary style={S.summary}>
                    <strong>{t}</strong> — {info.by_day.length} days with data
                  </summary>
                  <table style={S.table}>
                    <thead>
                      <tr>
                        <th style={S.th}>day</th>
                        <th style={{ ...S.th, textAlign: 'right' }}>rows</th>
                        <th style={{ ...S.th, textAlign: 'right' }}>distinct {info.key_dim}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {info.by_day.map((d) => (
                        <tr key={d.day}>
                          <td style={S.td}>{d.day}</td>
                          <td style={{ ...S.td, textAlign: 'right' }}>{d.rows.toLocaleString()}</td>
                          <td style={{ ...S.td, textAlign: 'right' }}>{d.distinct_keys}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )
            })}
          </>
        )}
      </div>

      {/* ── MANUAL JOB RUNNER ─────────────────────────────────────── */}
      <div style={S.card}>
        <h3 style={S.cardTitle}>Manual job runner</h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {JOBS.map((j) => (
            <button
              key={j.id}
              style={{ ...S.button, ...(runJob.isPending ? S.buttonDisabled : {}) }}
              disabled={runJob.isPending}
              onClick={() => runJob.mutate(j.id)}
            >
              {j.label}
            </button>
          ))}
        </div>
        {jobResults.length > 0 && (
          <table style={{ ...S.table, marginTop: 14 }}>
            <thead><tr>
              <th style={S.th}>job</th>
              <th style={S.th}>status</th>
              <th style={{ ...S.th, textAlign: 'right' }}>duration</th>
              <th style={S.th}>finished</th>
              <th style={S.th}>error</th>
            </tr></thead>
            <tbody>
              {jobResults.map((r, i) => (
                <tr key={i}>
                  <td style={S.td}>{r.job}</td>
                  <td style={{ ...S.td, color: r.ok ? 'var(--brand-primary)' : 'var(--danger)', fontWeight: 600 }}>
                    {r.ok ? 'OK' : 'FAIL'}
                  </td>
                  <td style={{ ...S.td, textAlign: 'right' }}>{r.duration_sec}s</td>
                  <td style={S.td}>{new Date(r.ended_at).toLocaleTimeString()}</td>
                  <td style={{ ...S.td, color: 'var(--danger)' }}>{r.error || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── REGIME ROUTER PAPER LIVE ──────────────────────────────── */}
      <div style={S.card}>
        <h3 style={S.cardTitle}>Regime Router — Paper Live</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <button
            style={{ ...S.button, ...(runRR.isPending ? S.buttonDisabled : {}) }}
            disabled={runRR.isPending}
            onClick={() => runRR.mutate('morning')}
          >
            Run morning decision now
          </button>
          <button
            style={{ ...S.button, ...(runRR.isPending ? S.buttonDisabled : {}) }}
            disabled={runRR.isPending}
            onClick={() => runRR.mutate('close')}
          >
            Force EOD close now
          </button>
        </div>
        {rrTrades.data && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 12 }}>
              <div style={S.statTile}>
                <div style={S.statLabel}>Total</div>
                <div style={S.statValue}>{rrTrades.data.summary.total}</div>
                <div style={S.statHint}>last 30 days</div>
              </div>
              <div style={S.statTile}>
                <div style={S.statLabel}>Wins</div>
                <div style={{ ...S.statValue, color: 'var(--brand-primary)' }}>
                  {rrTrades.data.summary.wins}
                </div>
                <div style={S.statHint}>TP exits</div>
              </div>
              <div style={S.statTile}>
                <div style={S.statLabel}>Losses</div>
                <div style={{ ...S.statValue, color: 'var(--danger)' }}>
                  {rrTrades.data.summary.losses}
                </div>
                <div style={S.statHint}>SL exits</div>
              </div>
              <div style={S.statTile}>
                <div style={S.statLabel}>Win Rate</div>
                <div style={S.statValue}>
                  {(rrTrades.data.summary.win_rate * 100).toFixed(1)}%
                </div>
                <div style={S.statHint}>{rrTrades.data.summary.skips} skipped (FLAT)</div>
              </div>
              <div style={S.statTile}>
                <div style={S.statLabel}>Total P&L</div>
                <div style={{
                  ...S.statValue,
                  color: rrTrades.data.summary.total_pnl_inr >= 0 ? 'var(--brand-primary)' : 'var(--danger)',
                }}>
                  ₹{rrTrades.data.summary.total_pnl_inr.toLocaleString()}
                </div>
                <div style={S.statHint}>realized</div>
              </div>
            </div>
            {rrTrades.data.trades.length === 0 ? (
              <div style={{ color: 'var(--text-secondary)', padding: 12 }}>
                No paper trades yet. Scheduled to fire at 09:25 IST Mon-Fri.
              </div>
            ) : (
              <table style={S.table}>
                <thead><tr>
                  <th style={S.th}>date</th>
                  <th style={S.th}>regime</th>
                  <th style={S.th}>action</th>
                  <th style={{ ...S.th, textAlign: 'right' }}>mom 3d%</th>
                  <th style={{ ...S.th, textAlign: 'right' }}>pcr</th>
                  <th style={{ ...S.th, textAlign: 'right' }}>entry</th>
                  <th style={{ ...S.th, textAlign: 'right' }}>exit</th>
                  <th style={{ ...S.th, textAlign: 'right' }}>P&L ₹</th>
                  <th style={S.th}>status</th>
                </tr></thead>
                <tbody>
                  {rrTrades.data.trades.map((t, i) => (
                    <tr key={i}>
                      <td style={S.td}>{t.date}</td>
                      <td style={S.td}>{t.regime}</td>
                      <td style={S.td}>{t.action}</td>
                      <td style={{ ...S.td, textAlign: 'right' }}>{t.mom_3d_pct?.toFixed(2) ?? '—'}</td>
                      <td style={{ ...S.td, textAlign: 'right' }}>{t.pcr_oi?.toFixed(2) ?? '—'}</td>
                      <td style={{ ...S.td, textAlign: 'right' }}>{t.entry_premium ?? '—'}</td>
                      <td style={{ ...S.td, textAlign: 'right' }}>{t.exit_premium ?? '—'}</td>
                      <td style={{
                        ...S.td, textAlign: 'right', fontWeight: 600,
                        color: t.pnl_inr == null ? 'var(--text-muted)'
                             : t.pnl_inr >= 0 ? 'var(--brand-primary)' : 'var(--danger)',
                      }}>{t.pnl_inr?.toLocaleString() ?? '—'}</td>
                      <td style={{
                        ...S.td,
                        color: t.status === 'TP' ? 'var(--brand-primary)'
                             : t.status === 'SL' ? 'var(--danger)'
                             : t.status === 'OPEN' ? 'var(--signal)'
                             : 'var(--text-muted)',
                        fontWeight: 600,
                      }}>{t.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>

      {/* ── AUDIT TRAIL (F-A9) ────────────────────────────────────── */}
      <div style={S.card}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ ...S.cardTitle, margin: 0, flex: 1 }}>Audit Trail</h3>
          {auditLog.data && (
            <span style={{ fontSize: 11, color: 'var(--text-secondary)', marginRight: 12 }}>
              {auditLog.data.total} events · last 30d
            </span>
          )}
          <button style={S.button} onClick={exportAudit}>Export CSV (1y)</button>
        </div>
        {auditLog.data && auditLog.data.entries.length === 0 ? (
          <div style={{ color: 'var(--text-secondary)', padding: 12 }}>
            No audit events yet. Money-path actions (login, order exit, broker connect) auto-record here.
          </div>
        ) : auditLog.data && (
          <table style={S.table}>
            <thead><tr>
              <th style={S.th}>time</th>
              <th style={S.th}>event</th>
              <th style={S.th}>actor</th>
              <th style={S.th}>action</th>
              <th style={S.th}>ip</th>
            </tr></thead>
            <tbody>
              {auditLog.data.entries.slice(0, 30).map(e => {
                const isFail = e.event_type.includes('FAILED') || e.event_type.includes('DISCONNECT')
                return (
                  <tr key={e.id}>
                    <td style={{ ...S.td, whiteSpace: 'nowrap', color: 'var(--text-secondary)', fontSize: 11 }}>
                      {new Date(e.ts).toLocaleString()}
                    </td>
                    <td style={{
                      ...S.td, fontWeight: 600,
                      color: isFail ? 'var(--danger)' : 'var(--text-primary)',
                    }}>{e.event_type}</td>
                    <td style={{ ...S.td, fontSize: 11 }}>{e.actor_email || '—'}</td>
                    <td style={{ ...S.td, fontSize: 12 }}>{e.action || '—'}</td>
                    <td style={{ ...S.td, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                      {e.ip_address || '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* ── SCHEDULER ─────────────────────────────────────────────── */}
      <div style={S.card}>
        <h3 style={S.cardTitle}>Scheduler — registered jobs + next firing</h3>
        {sched.isLoading && <div style={{ color: 'var(--text-secondary)' }}>Loading…</div>}
        {sched.data && (
          <>
            <div style={{ marginBottom: 8, fontSize: 13, color: 'var(--text-primary)' }}>
              Status:{' '}
              <strong style={{ color: sched.data.running ? 'var(--brand-primary)' : 'var(--danger)' }}>
                {sched.data.running ? 'RUNNING' : 'STOPPED'}
              </strong>
              {' · '}
              <span style={{ color: 'var(--text-secondary)' }}>{sched.data.jobs.length} jobs</span>
            </div>
            <table style={S.table}>
              <thead><tr>
                <th style={S.th}>id</th>
                <th style={S.th}>trigger</th>
                <th style={S.th}>next firing</th>
              </tr></thead>
              <tbody>
                {sched.data.jobs.map((j) => (
                  <tr key={j.id}>
                    <td style={S.td}>{j.id}</td>
                    <td style={{ ...S.td, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)' }}>
                      {j.trigger}
                    </td>
                    <td style={S.td}>
                      {j.next_run_time ? new Date(j.next_run_time).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  )
}

/**
 * Superadmin (algo@reyu.ai only) — dataset capture dashboard + ops tools.
 *
 *  - Daily fills per table for the last 14 days (raw rowcounts)
 *  - Scheduler job list with next-firing times
 *  - One-click pipeline test against Fyers
 *  - One-click manual job runner (when you don't want to wait for the cron)
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useAuth } from '../context/AuthContext'

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

export default function DataAdmin() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [jobResults, setJobResults] = useState<JobRunResult[]>([])

  // ── Gate: superadmin only ───────────────────────────────────────────
  if (!user || user.email !== 'algo@reyu.ai') {
    return (
      <div style={{ padding: 40 }}>
        <h2>Access denied</h2>
        <p>This dashboard is restricted to the superadmin account.</p>
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

  // ── Mutations ──────────────────────────────────────────────────────
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

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <div style={{ padding: '20px 32px', maxWidth: 1400 }}>
      <h1 style={{ marginBottom: 4 }}>Dataset Capture — Admin</h1>
      <div style={{ color: 'var(--muted)', marginBottom: 24, fontSize: 14 }}>
        Superadmin · {user.email}
      </div>

      {/* ── PIPELINE TEST ─────────────────────────────────────────── */}
      <Card title="Fyers Pipeline Test">
        <button
          className="primary"
          disabled={runTest.isPending}
          onClick={() => runTest.mutate()}
        >
          {runTest.isPending ? 'Testing…' : 'Run end-to-end test (NIFTY, 7 days)'}
        </button>
        {testResult && (
          <div style={{ marginTop: 16 }}>
            <div style={{
              padding: 12,
              background: testResult.overall.startsWith('PASS')
                ? 'rgba(0,200,0,0.1)' : 'rgba(255,80,0,0.15)',
              borderRadius: 4,
              marginBottom: 12,
              fontWeight: 600,
            }}>
              {testResult.overall}
            </div>
            {Object.entries(testResult.stages).map(([stage, info]: any) => (
              <details key={stage} style={{ marginBottom: 8 }}>
                <summary style={{ cursor: 'pointer', padding: '6px 0' }}>
                  <strong>{stage}</strong> —{' '}
                  <span style={{
                    color: info?.verdict?.startsWith('PASS') ? 'var(--bull)'
                         : info?.verdict?.startsWith('WARN') ? 'orange'
                         : 'var(--bear)',
                  }}>
                    {info?.verdict ?? 'no verdict'}
                  </span>
                </summary>
                <pre style={{
                  background: 'var(--surface-2, #f7f7f8)',
                  padding: 10, fontSize: 12, overflow: 'auto',
                }}>{JSON.stringify(info, null, 2)}</pre>
              </details>
            ))}
          </div>
        )}
      </Card>

      {/* ── DAILY FILLS ───────────────────────────────────────────── */}
      <Card title="Daily Fills — last 14 days">
        {fills.isLoading && <div>Loading…</div>}
        {fills.data && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 16 }}>
              {TABLES.map((t) => {
                const info = fills.data!.tables[t]
                if (!info) return null
                return (
                  <div key={t} style={{
                    padding: 12,
                    background: 'var(--surface-2, #f7f7f8)',
                    borderRadius: 4,
                  }}>
                    <div style={{ fontSize: 12, color: 'var(--muted)' }}>{t}</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>
                      {info.total_rows.toLocaleString()}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>total rows</div>
                  </div>
                )
              })}
            </div>

            {TABLES.map((t) => {
              const info = fills.data!.tables[t]
              if (!info) return null
              return (
                <details key={t} style={{ marginBottom: 8 }}>
                  <summary style={{ cursor: 'pointer', padding: '6px 0' }}>
                    <strong>{t}</strong> — {info.by_day.length} days with data
                  </summary>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginTop: 4 }}>
                    <thead>
                      <tr style={{ background: 'var(--surface-2, #f7f7f8)' }}>
                        <th style={{ padding: 6, textAlign: 'left' }}>day</th>
                        <th style={{ padding: 6, textAlign: 'right' }}>rows</th>
                        <th style={{ padding: 6, textAlign: 'right' }}>distinct {info.key_dim}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {info.by_day.map((d) => (
                        <tr key={d.day}>
                          <td style={{ padding: 4 }}>{d.day}</td>
                          <td style={{ padding: 4, textAlign: 'right' }}>{d.rows.toLocaleString()}</td>
                          <td style={{ padding: 4, textAlign: 'right' }}>{d.distinct_keys}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )
            })}
          </>
        )}
      </Card>

      {/* ── MANUAL JOB RUNNER ─────────────────────────────────────── */}
      <Card title="Manual job runner">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {JOBS.map((j) => (
            <button
              key={j.id}
              disabled={runJob.isPending}
              onClick={() => runJob.mutate(j.id)}
              style={{ padding: '6px 12px' }}
            >
              {j.label}
            </button>
          ))}
        </div>
        {jobResults.length > 0 && (
          <table style={{ marginTop: 14, width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
            <thead><tr style={{ background: 'var(--surface-2, #f7f7f8)' }}>
              <th style={{ padding: 6, textAlign: 'left' }}>job</th>
              <th style={{ padding: 6 }}>status</th>
              <th style={{ padding: 6, textAlign: 'right' }}>duration</th>
              <th style={{ padding: 6, textAlign: 'left' }}>finished</th>
              <th style={{ padding: 6, textAlign: 'left' }}>error</th>
            </tr></thead>
            <tbody>
              {jobResults.map((r, i) => (
                <tr key={i}>
                  <td style={{ padding: 4 }}>{r.job}</td>
                  <td style={{ padding: 4, color: r.ok ? 'var(--bull)' : 'var(--bear)' }}>
                    {r.ok ? 'OK' : 'FAIL'}
                  </td>
                  <td style={{ padding: 4, textAlign: 'right' }}>{r.duration_sec}s</td>
                  <td style={{ padding: 4 }}>{new Date(r.ended_at).toLocaleTimeString()}</td>
                  <td style={{ padding: 4, color: 'var(--bear)' }}>{r.error || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* ── SCHEDULER ─────────────────────────────────────────────── */}
      <Card title="Scheduler — registered jobs + next firing">
        {sched.isLoading && <div>Loading…</div>}
        {sched.data && (
          <>
            <div style={{ marginBottom: 8 }}>
              Status: <strong>{sched.data.running ? 'running' : 'STOPPED'}</strong>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead><tr style={{ background: 'var(--surface-2, #f7f7f8)' }}>
                <th style={{ padding: 6, textAlign: 'left' }}>id</th>
                <th style={{ padding: 6, textAlign: 'left' }}>trigger</th>
                <th style={{ padding: 6, textAlign: 'left' }}>next firing</th>
              </tr></thead>
              <tbody>
                {sched.data.jobs.map((j) => (
                  <tr key={j.id}>
                    <td style={{ padding: 4 }}>{j.id}</td>
                    <td style={{ padding: 4, fontFamily: 'monospace', fontSize: 11 }}>{j.trigger}</td>
                    <td style={{ padding: 4 }}>
                      {j.next_run_time ? new Date(j.next_run_time).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      marginBottom: 28,
      padding: 18,
      background: 'var(--surface, #fff)',
      border: '1px solid var(--border, #e2e2e6)',
      borderRadius: 6,
    }}>
      <h3 style={{ margin: '0 0 14px 0', fontSize: 16 }}>{title}</h3>
      {children}
    </div>
  )
}

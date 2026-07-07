/**
 * Backtest — pick one of YOUR saved strategies and run a real backtest.
 *
 * The old page replayed built-in "template" strategies against a legacy
 * snapshot endpoint that no longer exists (empty dropdown). This launches
 * the real StrategySpec backtest (POST /api/strategies/:id/runs) — the same
 * engine the strategy detail page uses — then hands off to that page's
 * performance tab, which renders results, equity curve, risk sim, and
 * walk-forward. Multi-leg spreads are simulated leg-by-leg by the engine.
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, Link } from 'react-router-dom'
import { api } from '../api'
import { useToast } from '../toast'
import JourneyGuide from '../components/JourneyGuide'

type Strat = { id: string; name: string; kind?: string; status?: string; universe?: string[] }

const iso = (d: Date) => d.toISOString().slice(0, 10)

export default function Backtest() {
  const t = useToast()
  const nav = useNavigate()
  const [strategyId, setStrategyId] = useState('')
  const [start, setStart] = useState(iso(new Date(Date.now() - 90 * 86400000)))
  const [end, setEnd] = useState(iso(new Date()))
  const [capital, setCapital] = useState(100000)
  const [busy, setBusy] = useState(false)

  const { data, isLoading } = useQuery<{ items: Strat[] }>({
    queryKey: ['my-strategies'],
    queryFn: async () => (await api.get('/api/strategies')).data,
  })
  const strategies = data?.items || []
  const selected = useMemo(() => strategies.find(s => s.id === strategyId), [strategies, strategyId])

  async function run() {
    if (!strategyId) { t.push('error', 'Pick a strategy first.'); return }
    setBusy(true)
    try {
      const q = new URLSearchParams({
        period_start: start, period_end: end,
        starting_capital: String(capital), seed: '42',
      })
      const { data: r } = await api.post(`/api/strategies/${strategyId}/runs?${q}`)
      t.push('success', 'Backtest started — opening results…')
      // Hand off to the strategy detail page; its performance tab polls the run.
      nav(`/strategies/${strategyId}?run=${r.run_id}`)
    } catch (e: any) {
      t.push('error', e?.response?.data?.detail || e?.message || 'Could not start the backtest.')
    } finally { setBusy(false) }
  }

  return (
    <div className="page-shell">
      <JourneyGuide current="backtest" note="You're at the backtest step: replay a saved strategy on past data to see how it would have done — before risking anything." />
      <div className="card">
        <div className="card-header">
          <h3>Backtest a saved strategy</h3>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            Runs the real StrategySpec engine on historical data. Results open on the strategy's performance tab.
          </span>
        </div>

        {isLoading ? (
          <div style={{ color: 'var(--muted)', fontSize: 13, padding: '12px 0' }}>Loading your strategies…</div>
        ) : strategies.length === 0 ? (
          <div style={{ color: 'var(--muted)', fontSize: 13, padding: '12px 0' }}>
            You have no saved strategies yet. Build one with{' '}
            <Link to="/" style={{ color: 'var(--accent, var(--brand-primary))' }}>Reyu</Link> or copy a{' '}
            <Link to="/templates" style={{ color: 'var(--accent, var(--brand-primary))' }}>template</Link>, then come back to backtest it.
          </div>
        ) : (
          <>
            <div className="row" style={{ alignItems: 'flex-end', gap: 10, flexWrap: 'wrap' }}>
              <Field label="Strategy">
                <select value={strategyId} onChange={e => setStrategyId(e.target.value)} style={{ minWidth: 220 }}>
                  <option value="">— pick a saved strategy —</option>
                  {strategies.map(s => (
                    <option key={s.id} value={s.id}>
                      {s.name}{s.kind ? ` · ${s.kind}` : ''}{s.status ? ` · ${s.status}` : ''}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="From">
                <input className="input" type="date" value={start} onChange={e => setStart(e.target.value)} />
              </Field>
              <Field label="To">
                <input className="input" type="date" value={end} onChange={e => setEnd(e.target.value)} />
              </Field>
              <Field label="Capital ₹">
                <input className="input" type="number" min={10000} step={10000} value={capital}
                       onChange={e => setCapital(+e.target.value)} style={{ width: 130 }} />
              </Field>
              <button className="primary" onClick={run} disabled={busy || !strategyId}>
                {busy ? 'Starting…' : 'Run backtest'}
              </button>
            </div>
            {selected?.universe?.[0] && (
              <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>
                Universe: {selected.universe[0]} · results will open on{' '}
                <Link to={`/strategies/${selected.id}`} style={{ color: 'var(--accent, var(--brand-primary))' }}>the strategy page</Link>.
              </div>
            )}
          </>
        )}
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6 }}>
          Want to compare several strategies' runs side by side? Use{' '}
          <Link to="/strategies/compare" style={{ color: 'var(--accent, var(--brand-primary))' }}>Compare</Link>.
          Backtests are hypothetical historical simulations — not a performance claim or a prediction.
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</span>
      {children}
    </div>
  )
}

/**
 * Training Lab — /rl/lab
 *
 * Operator/research console to (re)train the two learning engines on real
 * historical data and see the train → out-of-sample journey:
 *
 *   1. RL Bandit (contextual, intraday) — trains on a rolling window and
 *      evaluates on a held-out tail. "Use 1-min option data" flips the fill
 *      source from Black-Scholes to real per-contract premiums from
 *      option_contract_1m (the 1-min history that lives on the VM); the
 *      result reports the real-vs-BS coverage mix so you can see how much of
 *      the backtest was priced off actual traded premiums.
 *
 *   2. Regime Router (EOD) — routes each day to LONG_CE / LONG_PE /
 *      IRON_CONDOR / FLAT and compares against two always-on baselines over
 *      the same window.
 *
 * Everything here is hypothetical validation on historical data. Results are
 * NOT a performance claim, NOT a prediction, and NOT investment advice — they
 * are records of what a fixed rule WOULD have done on past data.
 */
import { useState, type CSSProperties } from 'react'
import { api } from '../context/AuthContext'

// ─── shared bits ──────────────────────────────────────────────────────────────

const card: CSSProperties = {
  border: '1px solid var(--color-border, var(--border))', borderRadius: 12,
  padding: 20, marginBottom: 20, background: 'var(--color-surface, var(--card))',
}
const label: CSSProperties = { fontSize: 11, color: 'var(--color-text-tertiary, var(--muted))', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 4, display: 'block' }
const input: CSSProperties = {
  width: '100%', padding: '8px 10px', fontSize: 13, fontFamily: 'var(--font-mono, monospace)',
  background: 'var(--color-bg, var(--card2))', color: 'var(--color-text-primary, var(--text))',
  border: '1px solid var(--color-border, var(--border))', borderRadius: 8, boxSizing: 'border-box',
}
const grid = (min = 130): CSSProperties => ({ display: 'grid', gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`, gap: 12 })
const btn: CSSProperties = {
  padding: '9px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
  border: '1px solid var(--color-primary, var(--brand-primary))', background: 'var(--color-primary, var(--brand-primary))', color: '#fff',
}
const btnGhost: CSSProperties = { ...btn, background: 'transparent', color: 'var(--color-text-primary, var(--text))', borderColor: 'var(--color-border, var(--border))' }

const pct = (n: number | null | undefined, d = 1) => (n == null ? '—' : `${n.toFixed(d)}%`)
const pctFrac = (n: number | null | undefined) => (n == null ? '—' : `${(n * 100).toFixed(1)}%`)

function Field({ label: l, children }: { label: string; children: React.ReactNode }) {
  return <div><span style={label as any}>{l}</span>{children}</div>
}

function Stat({ k, v, good }: { k: string; v: string; good?: boolean | null }) {
  const color = good == null ? 'var(--color-text-primary, var(--text))' : good ? 'var(--pos, #22c55e)' : 'var(--neg, #ef4444)'
  return (
    <div style={{ padding: '10px 12px', background: 'var(--color-bg, var(--card2))', borderRadius: 8 }}>
      <div style={{ fontSize: 10.5, color: 'var(--color-text-tertiary, var(--muted))', textTransform: 'uppercase', letterSpacing: '.04em' }}>{k}</div>
      <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'var(--font-mono, monospace)', marginTop: 3, color }}>{v}</div>
    </div>
  )
}

const disclaimer = (
  <p style={{ fontSize: 11.5, color: 'var(--color-text-tertiary, var(--muted))', marginTop: 14, lineHeight: 1.55 }}>
    Hypothetical validation on historical data. A backtest shows what a fixed rule <em>would</em> have done — it is not a
    performance claim, not a prediction, and not investment advice. Out-of-sample (test) numbers matter far more than
    training numbers; a big gap between them means the rule is overfit to one period.
  </p>
)

// ─── Card A: RL Bandit trainer ────────────────────────────────────────────────

type EvalResult = {
  underlying: string
  train_trades: number; train_win_rate: number | null
  test_trades: number; test_win_rate: number | null
  test_cum_pnl_pct?: number | null
  roi?: { roi_pct?: number | null; max_drawdown_pct?: number | null; pnl_inr?: number | null; trades_taken?: number | null } | null
  pricer_coverage?: { real?: number; bs?: number; real_pct?: number } | null
}

function BanditTrainer() {
  const [symbols, setSymbols] = useState('NSE:NIFTY50-INDEX')
  const [totalDays, setTotalDays] = useState(180)
  const [testDays, setTestDays] = useState(30)
  const [targetPct, setTargetPct] = useState(0.25)
  const [stopPct, setStopPct] = useState(0.15)
  const [minConv, setMinConv] = useState(0.05)
  const [lr, setLr] = useState(0.10)
  const [epochs, setEpochs] = useState(2)
  const [useRealPricer, setUseRealPricer] = useState(true)
  const [capital, setCapital] = useState(100000)

  const [busy, setBusy] = useState<'' | 'eval' | 'save'>('')
  const [rows, setRows] = useState<EvalResult[] | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [err, setErr] = useState('')

  const symList = symbols.split(',').map(s => s.trim()).filter(Boolean)

  async function runEval() {
    setBusy('eval'); setErr(''); setSaved(null)
    try {
      const q = new URLSearchParams({
        total_days: String(totalDays), test_days: String(testDays),
        target_pct: String(targetPct), stop_pct: String(stopPct),
        min_conviction: String(minConv), lr: String(lr), epochs: String(epochs),
        starting_capital: String(capital), sequential: 'true',
        use_real_pricer: String(useRealPricer),
      })
      const { data } = await api.post(`/api/rl/evaluate?${q}`, symList)
      setRows(data.results || [])
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Training failed.')
    } finally { setBusy('') }
  }

  async function trainAndSave() {
    if (symList.length !== 1) { setErr('Train & save works on one underlying at a time.'); return }
    setBusy('save'); setErr(''); setSaved(null)
    try {
      const q = new URLSearchParams({
        underlying: symList[0], total_days: String(totalDays),
        target_pct: String(targetPct), stop_pct: String(stopPct),
        min_conviction: String(minConv), lr: String(lr), epochs: String(epochs),
      })
      const { data } = await api.post(`/api/rl/train-and-save?${q}`)
      setSaved(`${data.underlying}: trained on ${data.train_trades ?? '—'} trades, weights saved. Live inference now uses this policy.`)
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Train & save failed.')
    } finally { setBusy('') }
  }

  return (
    <div style={card}>
      <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px' }}>RL Bandit — contextual policy</h2>
      <p style={{ fontSize: 13, color: 'var(--color-text-secondary, var(--muted))', margin: '0 0 16px', lineHeight: 1.5 }}>
        Trains a LONG/SHORT/FLAT contextual bandit on a rolling window, then scores it on a held-out tail.
        Toggle <strong>1-min option data</strong> to price fills off real per-contract premiums instead of Black-Scholes.
      </p>

      <div style={{ ...grid(150), marginBottom: 14 }}>
        <Field label="Underlyings (comma-sep)"><input style={input} value={symbols} onChange={e => setSymbols(e.target.value)} /></Field>
        <Field label="Total window (days)"><input style={input} type="number" min={30} max={365} value={totalDays} onChange={e => setTotalDays(+e.target.value)} /></Field>
        <Field label="Held-out test (days)"><input style={input} type="number" min={5} max={90} value={testDays} onChange={e => setTestDays(+e.target.value)} /></Field>
        <Field label="Target %"><input style={input} type="number" step={0.05} value={targetPct} onChange={e => setTargetPct(+e.target.value)} /></Field>
        <Field label="Stop %"><input style={input} type="number" step={0.05} value={stopPct} onChange={e => setStopPct(+e.target.value)} /></Field>
        <Field label="Min conviction"><input style={input} type="number" step={0.01} value={minConv} onChange={e => setMinConv(+e.target.value)} /></Field>
        <Field label="Learning rate"><input style={input} type="number" step={0.01} value={lr} onChange={e => setLr(+e.target.value)} /></Field>
        <Field label="Epochs"><input style={input} type="number" min={1} max={20} value={epochs} onChange={e => setEpochs(+e.target.value)} /></Field>
        <Field label="Capital ₹"><input style={input} type="number" step={10000} value={capital} onChange={e => setCapital(+e.target.value)} /></Field>
      </div>

      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer', marginBottom: 16 }}>
        <input type="checkbox" checked={useRealPricer} onChange={e => setUseRealPricer(e.target.checked)} />
        Use 1-min option data (real per-contract fills; falls back to Black-Scholes where the VM has no bar)
      </label>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <button style={busy ? { ...btn, opacity: 0.6, cursor: 'default' } : btn} disabled={!!busy} onClick={runEval}>
          {busy === 'eval' ? 'Training…' : '▶ Train & evaluate (OOS)'}
        </button>
        <button style={busy ? { ...btnGhost, opacity: 0.6, cursor: 'default' } : btnGhost} disabled={!!busy} onClick={trainAndSave}
          title="Fit on the whole window and persist weights for live paper inference">
          {busy === 'save' ? 'Saving…' : '⇧ Train & save (go-live)'}
        </button>
      </div>

      {err && <div style={{ marginTop: 14, padding: '10px 12px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, color: 'var(--neg, #ef4444)', fontSize: 13 }}>⚠ {err}</div>}
      {saved && <div style={{ marginTop: 14, padding: '10px 12px', background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.25)', borderRadius: 8, color: 'var(--pos, #22c55e)', fontSize: 13 }}>✔ {saved}</div>}

      {rows && rows.length > 0 && (
        <div style={{ marginTop: 18 }}>
          {rows.map(r => {
            const cov = r.pricer_coverage
            const realPct = cov?.real_pct != null ? cov.real_pct : (cov && (cov.real ?? 0) + (cov.bs ?? 0) > 0 ? (cov.real! / ((cov.real ?? 0) + (cov.bs ?? 0))) * 100 : null)
            return (
              <div key={r.underlying} style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>{r.underlying}</div>
                <div style={grid(120)}>
                  <Stat k="Train win rate" v={pctFrac(r.train_win_rate)} />
                  <Stat k="OOS win rate" v={pctFrac(r.test_win_rate)} good={r.test_win_rate == null ? null : r.test_win_rate >= 0.5} />
                  <Stat k="OOS ROI" v={pct(r.roi?.roi_pct)} good={r.roi?.roi_pct == null ? null : r.roi.roi_pct >= 0} />
                  <Stat k="OOS max DD" v={pct(r.roi?.max_drawdown_pct)} good={false} />
                  <Stat k="OOS trades" v={String(r.roi?.trades_taken ?? r.test_trades ?? '—')} />
                  <Stat k="1-min coverage" v={realPct == null ? '—' : `${realPct.toFixed(0)}%`} good={realPct == null ? null : realPct >= 50} />
                </div>
              </div>
            )
          })}
        </div>
      )}
      {disclaimer}
    </div>
  )
}

// ─── Card B: Regime Router backtest ───────────────────────────────────────────

type RouterLeg = { trades: number; win_rate: number | null; roi_pct: number | null; max_drawdown_pct: number | null; final_capital: number | null }
type RouterResult = {
  underlying: string; window: [string, string]
  regime_distribution: Record<string, number>
  router: RouterLeg
  baseline_always_condor: RouterLeg
  baseline_always_long_ce: RouterLeg
}

function todayISO() { return new Date().toISOString().slice(0, 10) }
function daysAgoISO(n: number) { return new Date(Date.now() - n * 86400000).toISOString().slice(0, 10) }

function RegimeRouter() {
  const [underlying, setUnderlying] = useState('NSE:NIFTY50-INDEX')
  const [start, setStart] = useState(daysAgoISO(365))
  const [end, setEnd] = useState(todayISO())
  const [momLookback, setMomLookback] = useState(3)
  const [trendTh, setTrendTh] = useState(1.0)
  const [rangeTh, setRangeTh] = useState(0.5)
  const [pcrLow, setPcrLow] = useState(0.7)
  const [pcrHigh, setPcrHigh] = useState(1.4)

  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<RouterResult | null>(null)
  const [err, setErr] = useState('')

  async function run() {
    setBusy(true); setErr('')
    try {
      const q = new URLSearchParams({
        underlying, start_date: start, end_date: end,
        momentum_lookback: String(momLookback),
        trend_threshold_pct: String(trendTh), range_threshold_pct: String(rangeTh),
        pcr_low: String(pcrLow), pcr_high: String(pcrHigh),
      })
      const { data } = await api.post(`/api/backtest-eod/regime-router?${q}`)
      setRes(data)
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Backtest failed.')
    } finally { setBusy(false) }
  }

  const legs: { name: string; k: keyof RouterResult }[] = [
    { name: 'Regime Router', k: 'router' },
    { name: 'Always Iron-Condor', k: 'baseline_always_condor' },
    { name: 'Always Long-CE', k: 'baseline_always_long_ce' },
  ]

  return (
    <div style={card}>
      <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px' }}>Regime Router — EOD backtest</h2>
      <p style={{ fontSize: 13, color: 'var(--color-text-secondary, var(--muted))', margin: '0 0 16px', lineHeight: 1.5 }}>
        Routes each day to LONG_CE / LONG_PE / IRON_CONDOR / FLAT from rolling momentum + PCR, closes EOD, and shows the
        router next to two always-on baselines on the same window.
      </p>

      <div style={{ ...grid(140), marginBottom: 16 }}>
        <Field label="Underlying"><input style={input} value={underlying} onChange={e => setUnderlying(e.target.value)} /></Field>
        <Field label="Start date"><input style={input} type="date" value={start} onChange={e => setStart(e.target.value)} /></Field>
        <Field label="End date"><input style={input} type="date" value={end} onChange={e => setEnd(e.target.value)} /></Field>
        <Field label="Momentum lookback"><input style={input} type="number" min={1} max={20} value={momLookback} onChange={e => setMomLookback(+e.target.value)} /></Field>
        <Field label="Trend threshold %"><input style={input} type="number" step={0.1} value={trendTh} onChange={e => setTrendTh(+e.target.value)} /></Field>
        <Field label="Range threshold %"><input style={input} type="number" step={0.1} value={rangeTh} onChange={e => setRangeTh(+e.target.value)} /></Field>
        <Field label="PCR low"><input style={input} type="number" step={0.1} value={pcrLow} onChange={e => setPcrLow(+e.target.value)} /></Field>
        <Field label="PCR high"><input style={input} type="number" step={0.1} value={pcrHigh} onChange={e => setPcrHigh(+e.target.value)} /></Field>
      </div>

      <button style={busy ? { ...btn, opacity: 0.6, cursor: 'default' } : btn} disabled={busy} onClick={run}>
        {busy ? 'Running…' : '▶ Run regime-router backtest'}
      </button>

      {err && <div style={{ marginTop: 14, padding: '10px 12px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, color: 'var(--neg, #ef4444)', fontSize: 13 }}>⚠ {err}</div>}

      {res && (
        <div style={{ marginTop: 18, overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>
                {['Strategy', 'Trades', 'Win rate', 'ROI %', 'Max DD %'].map(h => (
                  <th key={h} style={{ textAlign: h === 'Strategy' ? 'left' : 'right', padding: '8px 10px', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--color-text-tertiary, var(--muted))', borderBottom: '1px solid var(--color-border, var(--border))' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {legs.map(({ name, k }) => {
                const leg = res[k] as RouterLeg
                const isRouter = k === 'router'
                return (
                  <tr key={k} style={isRouter ? { background: 'rgba(99,102,241,0.06)' } : undefined}>
                    <td style={{ padding: '9px 10px', fontWeight: isRouter ? 700 : 500, borderBottom: '1px solid var(--color-border, var(--border))' }}>{name}</td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: 'monospace', borderBottom: '1px solid var(--color-border, var(--border))' }}>{leg.trades}</td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: 'monospace', borderBottom: '1px solid var(--color-border, var(--border))' }}>{pctFrac(leg.win_rate)}</td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: 'monospace', color: leg.roi_pct == null ? undefined : leg.roi_pct >= 0 ? 'var(--pos, #22c55e)' : 'var(--neg, #ef4444)', borderBottom: '1px solid var(--color-border, var(--border))' }}>{pct(leg.roi_pct)}</td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', fontFamily: 'monospace', color: 'var(--neg, #ef4444)', borderBottom: '1px solid var(--color-border, var(--border))' }}>{pct(leg.max_drawdown_pct)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {res.regime_distribution && (
            <div style={{ marginTop: 14 }}>
              <span style={label as any}>Regime distribution (days)</span>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {Object.entries(res.regime_distribution).map(([r, n]) => (
                  <span key={r} style={{ padding: '4px 10px', background: 'var(--color-bg, var(--card2))', borderRadius: 999, fontSize: 12, fontFamily: 'monospace' }}>
                    {r}: <strong>{n}</strong>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {disclaimer}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function TrainingLab() {
  return (
    <div style={{ padding: '24px 28px', maxWidth: 1100 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', marginBottom: 6 }}>
        <h1 style={{ fontSize: 21, fontWeight: 700, margin: 0 }}>🧪 Training Lab</h1>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.08em', background: 'rgba(139,92,246,0.18)', color: '#a78bfa', padding: '2px 8px', borderRadius: 20, border: '1px solid rgba(139,92,246,0.3)' }}>RESEARCH</span>
      </div>
      <p style={{ fontSize: 13.5, color: 'var(--color-text-secondary, var(--muted))', margin: '0 0 22px', maxWidth: 720, lineHeight: 1.55 }}>
        Retrain the two learning engines on real historical data and watch the train → out-of-sample journey.
        The RL bandit can price fills off the 1-min option history on the VM; the regime router is compared against
        always-on baselines so you can see what the routing actually buys you.
      </p>

      <BanditTrainer />
      <RegimeRouter />
    </div>
  )
}

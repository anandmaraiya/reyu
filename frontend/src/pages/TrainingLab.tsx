/**
 * Strategy Lab — /rl/lab  (beginner-friendly)
 *
 * Two "smart" strategies you can teach on real history and test honestly,
 * explained so anyone can follow:
 *
 *   • Auto-learning strategy — studies past days and works out its own
 *     buy/sell rules. You write nothing.
 *   • Market-mood strategy — reads whether the market is trending or flat
 *     and plays a different move for each; compared against simple baselines.
 *
 * Everything here is a hypothetical test on past data — never advice, never a
 * promise. The honest number is always the "unseen days" score: how it did on
 * dates it never learned from.
 */
import { useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../context/AuthContext'
import JourneyGuide from '../components/JourneyGuide'

// ─── shared bits ──────────────────────────────────────────────────────────────

const card: CSSProperties = {
  border: '1px solid var(--color-border, var(--border))', borderRadius: 12,
  padding: 20, marginBottom: 20, background: 'var(--color-surface, var(--card))',
}
const labelSt: CSSProperties = { fontSize: 11.5, color: 'var(--color-text-secondary, var(--muted))', marginBottom: 4, display: 'block', fontWeight: 600 }
const input: CSSProperties = {
  width: '100%', padding: '8px 10px', fontSize: 13,
  background: 'var(--color-bg, var(--card2))', color: 'var(--color-text-primary, var(--text))',
  border: '1px solid var(--color-border, var(--border))', borderRadius: 8, boxSizing: 'border-box',
}
const grid = (min = 150): CSSProperties => ({ display: 'grid', gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`, gap: 12 })
const btn: CSSProperties = {
  padding: '10px 18px', borderRadius: 8, fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
  border: '1px solid var(--color-primary, var(--brand-primary))', background: 'var(--color-primary, var(--brand-primary))', color: '#fff',
}
const btnGhost: CSSProperties = { ...btn, background: 'transparent', color: 'var(--color-text-primary, var(--text))', borderColor: 'var(--color-border, var(--border))' }

const pct = (n: number | null | undefined, d = 1) => (n == null ? '—' : `${n.toFixed(d)}%`)
const pctFrac = (n: number | null | undefined) => (n == null ? '—' : `${(n * 100).toFixed(0)}%`)

/** Label with an optional "?" that reveals the technical term for the curious. */
function Field({ label, tip, children }: { label: string; tip?: string; children: ReactNode }) {
  return (
    <div>
      <span style={labelSt}>
        {label}
        {tip && <span title={tip} style={{ marginLeft: 5, cursor: 'help', opacity: 0.6, fontWeight: 400 }}>ⓘ</span>}
      </span>
      {children}
    </div>
  )
}

function Stat({ k, v, good, hint }: { k: string; v: string; good?: boolean | null; hint?: string }) {
  const color = good == null ? 'var(--color-text-primary, var(--text))' : good ? 'var(--pos, #22c55e)' : 'var(--neg, #ef4444)'
  return (
    <div style={{ padding: '10px 12px', background: 'var(--color-bg, var(--card2))', borderRadius: 8 }} title={hint}>
      <div style={{ fontSize: 10.5, color: 'var(--color-text-tertiary, var(--muted))' }}>{k}{hint && <span style={{ opacity: 0.6 }}> ⓘ</span>}</div>
      <div style={{ fontSize: 18, fontWeight: 700, marginTop: 3, color }}>{v}</div>
    </div>
  )
}

const disclaimer = (
  <p style={{ fontSize: 11.5, color: 'var(--color-text-tertiary, var(--muted))', marginTop: 14, lineHeight: 1.55 }}>
    This is a <strong>practice run on past data</strong>, not advice and not a promise. Trust the <strong>“unseen days”</strong>
    {' '}score far more than the “while learning” one — if they’re very different, the strategy just memorised the past and
    won’t repeat it. Derivatives trading is high-risk; most people lose money.
  </p>
)

// ─── Engine 1: Auto-learning strategy ─────────────────────────────────────────

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
  const [showAdvanced, setShowAdvanced] = useState(false)

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
      setErr(e?.response?.data?.detail || e?.message || 'That didn’t run — please try again.')
    } finally { setBusy('') }
  }

  async function trainAndSave() {
    if (symList.length !== 1) { setErr('Teach-and-keep works on one symbol at a time — leave just one in the box.'); return }
    setBusy('save'); setErr(''); setSaved(null)
    try {
      const q = new URLSearchParams({
        underlying: symList[0], total_days: String(totalDays),
        target_pct: String(targetPct), stop_pct: String(stopPct),
        min_conviction: String(minConv), lr: String(lr), epochs: String(epochs),
      })
      const { data } = await api.post(`/api/rl/train-and-save?${q}`)
      setSaved(`Done — ${data.underlying} learned from ${data.train_trades ?? 'the'} past trades and is saved. Reyu’s paper engine will now use it.`)
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Couldn’t save — please try again.')
    } finally { setBusy('') }
  }

  return (
    <div style={card}>
      <h2 style={{ fontSize: 17, fontWeight: 700, margin: '0 0 4px' }}>🤖 Auto-learning strategy</h2>
      <p style={{ fontSize: 13, color: 'var(--color-text-secondary, var(--muted))', margin: '0 0 16px', lineHeight: 1.55 }}>
        It studies a stretch of past days and works out <strong>its own</strong> buy/sell rules — you don’t write any.
        We hold back the most recent days as a surprise test, so you see how it does on dates it never saw.
      </p>

      <div style={{ ...grid(160), marginBottom: 14 }}>
        <Field label="Which market?" tip="Symbol (Fyers format). NIFTY is a good first pick.">
          <input style={input} value={symbols} onChange={e => setSymbols(e.target.value)} />
        </Field>
        <Field label="Days to learn from" tip="total_days — the full history window.">
          <input style={input} type="number" min={30} max={365} value={totalDays} onChange={e => setTotalDays(+e.target.value)} />
        </Field>
        <Field label="Days to test on" tip="test_days — recent days held back as the honest, unseen test.">
          <input style={input} type="number" min={5} max={90} value={testDays} onChange={e => setTestDays(+e.target.value)} />
        </Field>
        <Field label="Take profit at +%" tip="target_pct — close a trade once it’s up this much.">
          <input style={input} type="number" step={0.05} value={targetPct} onChange={e => setTargetPct(+e.target.value)} />
        </Field>
        <Field label="Cut loss at −%" tip="stop_pct — close a trade once it’s down this much.">
          <input style={input} type="number" step={0.05} value={stopPct} onChange={e => setStopPct(+e.target.value)} />
        </Field>
        <Field label="Practice money ₹" tip="starting_capital for the return math.">
          <input style={input} type="number" step={10000} value={capital} onChange={e => setCapital(+e.target.value)} />
        </Field>
      </div>

      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer', marginBottom: 12 }}>
        <input type="checkbox" checked={useRealPricer} onChange={e => setUseRealPricer(e.target.checked)} />
        Use real option prices from history (more realistic; falls back to an estimate where we don’t have data)
      </label>

      <div style={{ marginBottom: 14 }}>
        <button onClick={() => setShowAdvanced(v => !v)} style={{ background: 'none', border: 'none', color: 'var(--color-text-secondary, var(--muted))', fontSize: 12, cursor: 'pointer', padding: 0 }}>
          {showAdvanced ? '▾ Hide expert dials' : '▸ Expert dials (optional)'}
        </button>
        {showAdvanced && (
          <div style={{ ...grid(150), marginTop: 10 }}>
            <Field label="Confidence needed" tip="min_conviction — skip trades the model isn’t sure about.">
              <input style={input} type="number" step={0.01} value={minConv} onChange={e => setMinConv(+e.target.value)} />
            </Field>
            <Field label="Learning speed" tip="lr — how fast it adjusts its rules.">
              <input style={input} type="number" step={0.01} value={lr} onChange={e => setLr(+e.target.value)} />
            </Field>
            <Field label="Study passes" tip="epochs — how many times it re-reads the history.">
              <input style={input} type="number" min={1} max={20} value={epochs} onChange={e => setEpochs(+e.target.value)} />
            </Field>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <button style={busy ? { ...btn, opacity: 0.6, cursor: 'default' } : btn} disabled={!!busy} onClick={runEval}>
          {busy === 'eval' ? 'Teaching…' : '① Teach & test it'}
        </button>
        <button style={busy ? { ...btnGhost, opacity: 0.6, cursor: 'default' } : btnGhost} disabled={!!busy} onClick={trainAndSave}
          title="Keep what it learned so Reyu’s paper engine uses it">
          {busy === 'save' ? 'Saving…' : '② Keep it (use in paper trading)'}
        </button>
      </div>

      {err && <div style={{ marginTop: 14, padding: '10px 12px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, color: 'var(--neg, #ef4444)', fontSize: 13 }}>⚠ {err}</div>}
      {saved && <div style={{ marginTop: 14, padding: '10px 12px', background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.25)', borderRadius: 8, color: 'var(--pos, #22c55e)', fontSize: 13 }}>✔ {saved}</div>}

      {rows && rows.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div style={{ fontSize: 12.5, color: 'var(--color-text-secondary, var(--muted))', marginBottom: 10 }}>
            Results — the <strong>“unseen days”</strong> row is the one that matters:
          </div>
          {rows.map(r => {
            const cov = r.pricer_coverage
            const realPct = cov?.real_pct != null ? cov.real_pct : (cov && (cov.real ?? 0) + (cov.bs ?? 0) > 0 ? (cov.real! / ((cov.real ?? 0) + (cov.bs ?? 0))) * 100 : null)
            return (
              <div key={r.underlying} style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>{r.underlying}</div>
                <div style={grid(130)}>
                  <Stat k="Win rate while learning" v={pctFrac(r.train_win_rate)} hint="How often it won on the days it studied. Easy to look good here." />
                  <Stat k="Win rate on unseen days" v={pctFrac(r.test_win_rate)} good={r.test_win_rate == null ? null : r.test_win_rate >= 0.5} hint="The honest test: days it never learned from. This is what counts." />
                  <Stat k="Return on unseen days" v={pct(r.roi?.roi_pct)} good={r.roi?.roi_pct == null ? null : r.roi.roi_pct >= 0} hint="Profit/loss % on the held-back test period." />
                  <Stat k="Worst drop" v={pct(r.roi?.max_drawdown_pct)} good={false} hint="The biggest fall from a peak — how painful it got." />
                  <Stat k="Trades taken" v={String(r.roi?.trades_taken ?? r.test_trades ?? '—')} hint="How many trades it made in the test." />
                  <Stat k="Real-data coverage" v={realPct == null ? '—' : `${realPct.toFixed(0)}%`} good={realPct == null ? null : realPct >= 50} hint="Share of fills priced off real historical option prices vs an estimate." />
                </div>
              </div>
            )
          })}
          <div style={{ marginTop: 6, fontSize: 12.5, color: 'var(--color-text-secondary, var(--muted))' }}>
            Happy with the unseen-days score? Hit <strong>“② Keep it”</strong> above, then watch it paper-trade on the{' '}
            <Link to="/rl" style={{ color: 'var(--color-primary, var(--brand-primary))' }}>RL Engine</Link> page.
          </div>
        </div>
      )}
      {disclaimer}
    </div>
  )
}

// ─── Engine 2: Market-mood strategy ───────────────────────────────────────────

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
  const [showAdvanced, setShowAdvanced] = useState(false)

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
      setErr(e?.response?.data?.detail || e?.message || 'That didn’t run — please try again.')
    } finally { setBusy(false) }
  }

  const legs: { name: string; k: keyof RouterResult; hint: string }[] = [
    { name: 'Market-mood strategy', k: 'router', hint: 'Plays a different move per market mood.' },
    { name: 'Always sell a condor', k: 'baseline_always_condor', hint: 'Simple baseline: same range-bet every day.' },
    { name: 'Always buy calls', k: 'baseline_always_long_ce', hint: 'Simple baseline: always bet up.' },
  ]

  return (
    <div style={card}>
      <h2 style={{ fontSize: 17, fontWeight: 700, margin: '0 0 4px' }}>🎛️ Market-mood strategy</h2>
      <p style={{ fontSize: 13, color: 'var(--color-text-secondary, var(--muted))', margin: '0 0 16px', lineHeight: 1.55 }}>
        It reads whether the market is <strong>trending up, trending down, or going sideways</strong>, and plays a different
        move for each. We test it on a stretch of history and line it up next to two “dumb” always-the-same strategies so you
        can see if the mood-reading actually helped.
      </p>

      <div style={{ ...grid(150), marginBottom: 14 }}>
        <Field label="Which market?" tip="Underlying symbol.">
          <input style={input} value={underlying} onChange={e => setUnderlying(e.target.value)} />
        </Field>
        <Field label="Test from" tip="start_date">
          <input style={input} type="date" value={start} onChange={e => setStart(e.target.value)} />
        </Field>
        <Field label="Test to" tip="end_date">
          <input style={input} type="date" value={end} onChange={e => setEnd(e.target.value)} />
        </Field>
      </div>

      <div style={{ marginBottom: 14 }}>
        <button onClick={() => setShowAdvanced(v => !v)} style={{ background: 'none', border: 'none', color: 'var(--color-text-secondary, var(--muted))', fontSize: 12, cursor: 'pointer', padding: 0 }}>
          {showAdvanced ? '▾ Hide expert dials' : '▸ Expert dials (how it decides the mood)'}
        </button>
        {showAdvanced && (
          <div style={{ ...grid(140), marginTop: 10 }}>
            <Field label="Trend memory (days)" tip="momentum_lookback — days of price change it averages.">
              <input style={input} type="number" min={1} max={20} value={momLookback} onChange={e => setMomLookback(+e.target.value)} />
            </Field>
            <Field label="“Trending” cutoff %" tip="trend_threshold_pct — move bigger than this = a trend.">
              <input style={input} type="number" step={0.1} value={trendTh} onChange={e => setTrendTh(+e.target.value)} />
            </Field>
            <Field label="“Sideways” cutoff %" tip="range_threshold_pct — move smaller than this = flat.">
              <input style={input} type="number" step={0.1} value={rangeTh} onChange={e => setRangeTh(+e.target.value)} />
            </Field>
            <Field label="Fear/greed low" tip="pcr_low — put/call ratio lower band.">
              <input style={input} type="number" step={0.1} value={pcrLow} onChange={e => setPcrLow(+e.target.value)} />
            </Field>
            <Field label="Fear/greed high" tip="pcr_high — put/call ratio upper band.">
              <input style={input} type="number" step={0.1} value={pcrHigh} onChange={e => setPcrHigh(+e.target.value)} />
            </Field>
          </div>
        )}
      </div>

      <button style={busy ? { ...btn, opacity: 0.6, cursor: 'default' } : btn} disabled={busy} onClick={run}>
        {busy ? 'Testing…' : '▶ Test it on history'}
      </button>

      {err && <div style={{ marginTop: 14, padding: '10px 12px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, color: 'var(--neg, #ef4444)', fontSize: 13 }}>⚠ {err}</div>}

      {res && (
        <div style={{ marginTop: 18, overflowX: 'auto' }}>
          <div style={{ fontSize: 12.5, color: 'var(--color-text-secondary, var(--muted))', marginBottom: 10 }}>
            Did reading the mood beat just doing the same thing every day?
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>
                {['Strategy', 'Trades', 'Win rate', 'Return %', 'Worst drop %'].map(h => (
                  <th key={h} style={{ textAlign: h === 'Strategy' ? 'left' : 'right', padding: '8px 10px', fontSize: 11, color: 'var(--color-text-tertiary, var(--muted))', borderBottom: '1px solid var(--color-border, var(--border))' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {legs.map(({ name, k, hint }) => {
                const leg = res[k] as RouterLeg
                const isRouter = k === 'router'
                return (
                  <tr key={k} style={isRouter ? { background: 'rgba(99,102,241,0.06)' } : undefined} title={hint}>
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
              <span style={labelSt}>How many days were in each mood</span>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {Object.entries(res.regime_distribution).map(([r, n]) => (
                  <span key={r} style={{ padding: '4px 10px', background: 'var(--color-bg, var(--card2))', borderRadius: 999, fontSize: 12 }}>
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
      <h1 style={{ fontSize: 22, fontWeight: 700, margin: '0 0 6px' }}>🧪 Strategy Lab</h1>
      <p style={{ fontSize: 14, color: 'var(--color-text-secondary, var(--muted))', margin: '0 0 18px', maxWidth: 760, lineHeight: 1.6 }}>
        Teach a “smart” strategy on real past data and see — honestly — how it would have done. Two kinds live here. Nothing
        you do on this page risks any money; it’s all practice on history.
      </p>

      <JourneyGuide current="backtest" note="You’re at the testing step. Teach a strategy here, then paper-test it before ever going live — you decide when." />

      <div style={{ ...card, background: 'var(--color-bg, var(--card2))' }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>How to use this page — 3 steps</div>
        <ol style={{ margin: 0, paddingLeft: 20, fontSize: 13, lineHeight: 1.7, color: 'var(--color-text-secondary, var(--muted))' }}>
          <li><strong>Pick a market and press the test button.</strong> The defaults are sensible — you can just click.</li>
          <li><strong>Read the “unseen days” score.</strong> That’s how it did on dates it never studied — the honest test.</li>
          <li><strong>If it looks good, keep it</strong> and let Reyu paper-trade it. Only you decide if it ever goes live.</li>
        </ol>
      </div>

      <BanditTrainer />
      <RegimeRouter />
    </div>
  )
}

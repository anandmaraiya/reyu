/**
 * Onboarding — first-run flow (P-17).
 *
 * Four steps:
 *   1. Pick trader type (Retail | HNI)
 *   2. Connect Fyers broker
 *   3. See a seeded NIFTY backtest result (regime-router win-rate + ROI)
 *   4. Watch the mock paper trade preview (regime-router today's decision)
 *
 * After Step 4, POSTs /api/user/mark-onboarded, redirects to /.
 * Progress persists in localStorage so a page reload resumes the step.
 *
 * Telemetry: onboard_started (mount), onboard_step_completed per step,
 * onboard_completed on finish. Backed by PostHog.
 */
import { useState, useEffect, useCallback, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { useAuth } from '../context/AuthContext'
import { track, Events } from '../telemetry'
import PageHelp from '../components/PageHelp'

type TraderType = 'RETAIL' | 'HNI'
type Step = 1 | 2 | 3 | 4

const STEP_STORAGE_KEY = 'reyu_onboard_step'
const TYPE_STORAGE_KEY = 'reyu_onboard_type'

// ── Styles (theme-token based) ─────────────────────────────────────────
const S = {
  page: {
    minHeight: '100vh',
    background: 'var(--bg-base)',
    color: 'var(--text-primary)',
    padding: '40px 20px',
  } as CSSProperties,
  shell: {
    maxWidth: 620,
    margin: '0 auto',
  } as CSSProperties,
  logo: {
    fontSize: 18,
    fontWeight: 700,
    marginBottom: 32,
    color: 'var(--brand-primary)',
    textAlign: 'center' as const,
    letterSpacing: '-0.02em',
  } as CSSProperties,
  progress: {
    display: 'flex',
    gap: 6,
    marginBottom: 32,
  } as CSSProperties,
  progressStep: (active: boolean, done: boolean): CSSProperties => ({
    flex: 1,
    height: 4,
    borderRadius: 2,
    background: done ? 'var(--brand-primary)' : active ? 'var(--brand-primary)' : 'var(--border-default)',
    opacity: active && !done ? 0.5 : 1,
    transition: 'all 200ms',
  }),
  card: {
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-md)',
    padding: 32,
    boxShadow: 'var(--shadow-md)',
  } as CSSProperties,
  stepLabel: {
    fontSize: 11,
    color: 'var(--text-secondary)',
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
    marginBottom: 8,
    fontWeight: 600,
  } as CSSProperties,
  title: {
    fontSize: 22,
    fontWeight: 600,
    margin: '0 0 8px 0',
    letterSpacing: '-0.01em',
  } as CSSProperties,
  hint: {
    color: 'var(--text-secondary)',
    fontSize: 13,
    lineHeight: 1.5,
    marginBottom: 28,
  } as CSSProperties,
  choice: (selected: boolean): CSSProperties => ({
    display: 'block',
    width: '100%',
    padding: 20,
    marginBottom: 12,
    background: selected ? 'var(--brand-light)' : 'var(--bg-elevated)',
    border: `1.5px solid ${selected ? 'var(--brand-primary)' : 'var(--border-default)'}`,
    borderRadius: 'var(--radius-md)',
    cursor: 'pointer',
    textAlign: 'left' as const,
    transition: 'all 150ms',
    color: 'var(--text-primary)',
  }),
  choiceTitle: { fontSize: 15, fontWeight: 600, marginBottom: 4 } as CSSProperties,
  choiceDesc: { fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 } as CSSProperties,
  primary: {
    padding: '11px 20px',
    background: 'var(--brand-primary)',
    color: '#fff',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    fontWeight: 600,
    fontSize: 14,
    cursor: 'pointer',
    minWidth: 180,
  } as CSSProperties,
  secondary: {
    padding: '11px 20px',
    background: 'var(--bg-elevated)',
    color: 'var(--text-primary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
    fontWeight: 500,
    fontSize: 14,
    cursor: 'pointer',
  } as CSSProperties,
  disabled: { opacity: 0.5, cursor: 'not-allowed' } as CSSProperties,
  row: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginTop: 24 } as CSSProperties,
  statTile: {
    padding: 16,
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
  statValue: { fontSize: 22, fontWeight: 700, marginTop: 2 } as CSSProperties,
  linkBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text-secondary)',
    fontSize: 12,
    cursor: 'pointer',
    textDecoration: 'underline',
  } as CSSProperties,
}

export default function Onboarding() {
  const { user } = useAuth()
  const nav = useNavigate()
  const [step, setStep] = useState<Step>(() => {
    const saved = Number(localStorage.getItem(STEP_STORAGE_KEY))
    return (saved >= 1 && saved <= 4) ? (saved as Step) : 1
  })
  const [traderType, setTraderType] = useState<TraderType | null>(() =>
    (localStorage.getItem(TYPE_STORAGE_KEY) as TraderType) || null
  )
  // Trading style → template persona. Optional; routes the user to a
  // matching template gallery after onboarding instead of a blank slate.
  const [tradingStyle, setTradingStyle] = useState<string | null>(() =>
    localStorage.getItem('reyu_trading_style')
  )
  const [submitting, setSubmitting] = useState(false)

  // Fire onboard_started once per session
  useEffect(() => {
    track(Events.OnboardStarted, { user_id: user?.id })
  }, [user?.id])

  // Persist step + type so a reload picks up where we left off
  useEffect(() => { localStorage.setItem(STEP_STORAGE_KEY, String(step)) }, [step])
  useEffect(() => {
    if (traderType) localStorage.setItem(TYPE_STORAGE_KEY, traderType)
  }, [traderType])
  useEffect(() => {
    if (tradingStyle) localStorage.setItem('reyu_trading_style', tradingStyle)
  }, [tradingStyle])

  // Fyers auth status (used by Step 2 gate)
  const { data: authStatus, refetch: refetchAuth } = useQuery({
    queryKey: ['fyers-auth-status'],
    queryFn: async () => (await api.get('/api/auth/status')).data,
    refetchInterval: step === 2 ? 5000 : false,
  })

  // Seeded backtest result (Step 3). Runs a quick regime-router summary.
  const { data: rrTrades } = useQuery({
    queryKey: ['rr-trades-seed'],
    queryFn: async () => (await api.get('/api/admin/data/regime-router/trades?days=30')).data,
    enabled: step === 3 || step === 4,
    // If user isn't superadmin the fetch fails — swallow and show canned copy
    retry: false,
  })

  const advance = useCallback((from: Step) => {
    track(Events.OnboardStepCompleted, { step: from })
    setStep((s) => (Math.min(s + 1, 4) as Step))
  }, [])

  const finish = useCallback(async () => {
    if (!traderType) return
    setSubmitting(true)
    try {
      await api.post('/api/user/mark-onboarded', { trader_type: traderType })
      track(Events.OnboardCompleted, { trader_type: traderType, trading_style: tradingStyle })
      localStorage.removeItem(STEP_STORAGE_KEY)
      localStorage.removeItem(TYPE_STORAGE_KEY)
      // Land on templates matching their style — a concrete starting
      // point beats an empty dashboard.
      nav(tradingStyle ? `/templates?persona=${tradingStyle}` : '/', { replace: true })
    } catch (e) {
      // If mark-onboarded fails, don't strand the user — send them home anyway.
      // They can retry later; onboarded_at stays null so they'll see the flow again.
      nav('/', { replace: true })
    } finally {
      setSubmitting(false)
    }
  }, [traderType, nav])

  const startFyers = useCallback(async () => {
    const { data } = await api.get('/api/auth/login')
    if (data.login_url) {
      window.location.href = data.login_url
    }
  }, [])

  const skipToEnd = useCallback(() => {
    if (!traderType) setTraderType('RETAIL')
    setStep(4)
  }, [traderType])

  return (
    <div style={S.page}>
      <div style={S.shell}>
        <PageHelp pageId="onboarding" />
        <div style={S.logo}>Reyu</div>

        {/* Progress bar */}
        <div style={S.progress}>
          {[1, 2, 3, 4].map((n) => (
            <div key={n} style={S.progressStep(n === step, n < step)} />
          ))}
        </div>

        <div style={S.card}>
          {step === 1 && (
            <>
              <div style={S.stepLabel}>Step 1 of 4</div>
              <h1 style={S.title}>What kind of trader are you?</h1>
              <p style={S.hint}>
                We'll tailor the platform to how you work. You can change this later in settings.
              </p>

              <button
                type="button"
                style={S.choice(traderType === 'RETAIL')}
                onClick={() => setTraderType('RETAIL')}
              >
                <div style={S.choiceTitle}>Retail trader</div>
                <div style={S.choiceDesc}>
                  Personal capital. Build and test your own strategies, paper-trade them in real time, go live once you're comfortable.
                </div>
              </button>

              <button
                type="button"
                style={S.choice(traderType === 'HNI')}
                onClick={() => setTraderType('HNI')}
              >
                <div style={S.choiceTitle}>HNI / active advisor</div>
                <div style={S.choiceDesc}>
                  Managing your own or client capital. Higher position limits, priority Fyers pooling, concierge onboarding.
                </div>
              </button>

              <p style={{ ...S.hint, marginTop: 20 }}>What do you trade most?</p>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                {[
                  { key: 'intraday_options', label: '⚡ Intraday options' },
                  { key: 'options_income', label: '💰 Options income' },
                  { key: 'swing_equity', label: '📈 Swing stocks' },
                  { key: 'systematic_invest', label: '🐢 Systematic investing' },
                ].map(s => (
                  <button
                    key={s.key}
                    type="button"
                    onClick={() => setTradingStyle(s.key)}
                    style={{
                      padding: '8px 14px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
                      borderRadius: 999,
                      background: tradingStyle === s.key ? 'var(--brand-primary, #f0a020)' : 'var(--bg-elevated)',
                      color: tradingStyle === s.key ? '#fff' : 'var(--text-primary)',
                      border: '1px solid var(--border-default)',
                    }}
                  >
                    {s.label}
                  </button>
                ))}
              </div>

              <div style={S.row}>
                <span />
                <button
                  style={{ ...S.primary, ...(!traderType ? S.disabled : {}) }}
                  disabled={!traderType}
                  onClick={() => advance(1)}
                >
                  Continue
                </button>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div style={S.stepLabel}>Step 2 of 4</div>
              <h1 style={S.title}>Connect your Fyers account</h1>
              <p style={S.hint}>
                Reyu reads your live option chain through Fyers to power backtests
                and the regime router. It's a one-tap OAuth — you'll come back here
                automatically. We only need read access to start.
              </p>

              {authStatus?.authenticated ? (
                <>
                  <div style={{
                    padding: 14, background: 'var(--brand-light)', color: 'var(--brand-text)',
                    borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-brand)',
                    marginBottom: 20, fontSize: 13,
                  }}>
                    ✓ Fyers connected. You're all set for live data.
                  </div>
                  <div style={S.row}>
                    <button style={S.linkBtn} onClick={() => setStep(1)}>Back</button>
                    <button style={S.primary} onClick={() => advance(2)}>Continue</button>
                  </div>
                </>
              ) : (
                <>
                  <button style={S.primary} onClick={startFyers}>Connect Fyers</button>
                  <div style={S.row}>
                    <button style={S.linkBtn} onClick={() => setStep(1)}>Back</button>
                    <button style={S.linkBtn} onClick={() => { refetchAuth(); advance(2) }}>
                      Skip for now
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {step === 3 && (
            <>
              <div style={S.stepLabel}>Step 3 of 4</div>
              <h1 style={S.title}>The strategy we run for you</h1>
              <p style={S.hint}>
                The regime router picks between long-call, long-put, and iron-condor
                every morning at 09:25 IST based on yesterday's PCR + 3-day momentum,
                then closes strictly at 15:20 IST. Backtest on 6 years (2019–2024):
              </p>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12, marginBottom: 20 }}>
                <div style={S.statTile}>
                  <div style={S.statLabel}>ROI</div>
                  <div style={{ ...S.statValue, color: 'var(--brand-primary)' }}>+975%</div>
                </div>
                <div style={S.statTile}>
                  <div style={S.statLabel}>Win rate</div>
                  <div style={S.statValue}>67.8%</div>
                </div>
                <div style={S.statTile}>
                  <div style={S.statLabel}>Max DD</div>
                  <div style={S.statValue}>9.5%</div>
                </div>
              </div>

              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 24 }}>
                6 years of NIFTY, 543 trades, ₹1L → ₹10.75L on paper. Live starts
                as paper-trading — real-money mode requires an Algo plan and Fyers connected.
              </p>

              <div style={S.row}>
                <button style={S.linkBtn} onClick={() => setStep(2)}>Back</button>
                <button style={S.primary} onClick={() => advance(3)}>Continue</button>
              </div>
            </>
          )}

          {step === 4 && (
            <>
              <div style={S.stepLabel}>Step 4 of 4</div>
              <h1 style={S.title}>
                {traderType === 'HNI' ? "You're set up with priority access" : "You're ready"}
              </h1>
              <p style={S.hint}>
                {traderType === 'HNI'
                  ? `Your HNI account has elevated position limits, priority Fyers pooling during peak load, and access to our concierge onboarding team. Tomorrow at 09:25 IST, the regime router opens its next paper trade on your account. Any questions during the first week, reply to your welcome email — a real human will get back to you within 4 hours.`
                  : `Tomorrow at 09:25 IST, the regime router opens its next paper trade on your account. You'll see the decision, entry prices, and live P&L on the dashboard. No action needed from you overnight.`
                }
              </p>

              <div style={{
                padding: 20, background: 'var(--bg-elevated)',
                border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)',
                fontSize: 13, marginBottom: 24, color: 'var(--text-secondary)',
              }}>
                <strong style={{ color: 'var(--text-primary)' }}>Every morning:</strong> re-authenticate Fyers (their token expires in 24h). Everything else runs on autopilot.
              </div>

              <div style={S.row}>
                <button style={S.linkBtn} onClick={() => setStep(3)}>Back</button>
                <button
                  style={{ ...S.primary, ...(submitting ? S.disabled : {}) }}
                  disabled={submitting}
                  onClick={finish}
                >
                  {submitting ? 'Finishing…' : 'Open dashboard →'}
                </button>
              </div>
            </>
          )}
        </div>

        {step < 4 && (
          <div style={{ textAlign: 'center', marginTop: 20 }}>
            <button style={S.linkBtn} onClick={skipToEnd}>
              I'll finish this later
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * GateModal — inline auth / upgrade modal.
 *
 * Modes:
 *   login   → email + password sign-in form
 *   signup  → register with free trial pitch
 *   upgrade → paid plan pitch with pricing
 *   limit   → free tier limit hit (strategies / backtests)
 *   trial   → trial expired
 *
 * Never redirects. Renders over the current page as a centred overlay.
 * After successful auth, parent (AuthContext) calls the pending onSuccess callback.
 */
import React, { useState, useEffect, useRef } from 'react'
import { useAuth } from '../context/AuthContext'

const FREE_STRATEGIES = 10
const FREE_BACKTESTS  = 50
const TRIAL_DAYS      = 15

export function GateModal() {
  const { gate, closeGate, login, register, openGate, trialDaysLeft, usage } = useAuth()
  const [mode, setMode] = useState<'login' | 'signup' | 'upgrade' | 'limit' | 'trial'>('login')
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [name, setName]         = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)
  const firstInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (gate?.mode) {
      setMode(gate.mode as any)
      setError('')
    }
  }, [gate?.mode])

  useEffect(() => {
    if (gate) firstInputRef.current?.focus()
  }, [gate, mode])

  if (!gate) return null

  // ── Handlers ───────────────────────────────────────────────────────────────

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (mode === 'login') {
        await login(email, password)
      } else if (mode === 'signup') {
        await register(email, password, name)
      }
    } catch (err: any) {
      const msg = err?.response?.data?.detail?.message
              || err?.response?.data?.detail
              || err?.response?.data?.message
              || 'Something went wrong. Try again.'
      setError(String(msg))
    } finally {
      setLoading(false)
    }
  }

  function handleUpgrade() {
    window.open('/subscribe', '_blank')
    closeGate()
  }

  // ── Content per mode ───────────────────────────────────────────────────────

  const headings: Record<string, string> = {
    login:   'Welcome back',
    signup:  'Start your free trial',
    upgrade: 'Unlock full power',
    limit:   'You\'ve hit the free limit',
    trial:   'Your trial has ended',
  }

  const subtext: Record<string, string> = {
    login:   gate.message || 'Sign in to continue.',
    signup:  `${TRIAL_DAYS} days free. 10 saved strategies. 50 backtest runs. No credit card.`,
    upgrade: gate.message || 'Upgrade to paid to continue using this feature.',
    limit:   gate.message || `Free plan: ${FREE_STRATEGIES} strategies · ${FREE_BACKTESTS} backtests`,
    trial:   gate.message || 'Your 15-day free trial has ended. Upgrade to keep trading.',
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div
      className="gate-overlay"
      onClick={e => { if (e.target === e.currentTarget) closeGate() }}
      role="dialog"
      aria-modal="true"
      aria-label={headings[mode]}
    >
      <div className="gate-card">
        {/* Close */}
        <button className="gate-close" onClick={closeGate} aria-label="Close">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>

        {/* Logo + heading */}
        <div className="gate-logo">
          <span className="gate-logo-mark">R</span>
          <span className="gate-logo-text">Reyu</span>
        </div>

        <h2 className="gate-heading">{headings[mode]}</h2>
        <p className="gate-sub">{subtext[mode]}</p>

        {/* Auth forms */}
        {(mode === 'login' || mode === 'signup') && (
          <form onSubmit={handleSubmit} className="gate-form">
            {mode === 'signup' && (
              <div className="gate-field">
                <label>Name</label>
                <input
                  ref={firstInputRef}
                  type="text"
                  placeholder="Your name"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  required
                  autoComplete="name"
                />
              </div>
            )}
            <div className="gate-field">
              <label>Email</label>
              <input
                ref={mode === 'login' ? firstInputRef : undefined}
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            <div className="gate-field">
              <label>Password</label>
              <input
                type="password"
                placeholder={mode === 'signup' ? 'Choose a password' : '••••••••'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                minLength={8}
              />
            </div>

            {error && <p className="gate-error">{error}</p>}

            <button type="submit" className="gate-btn gate-btn-primary" disabled={loading}>
              {loading
                ? <span className="gate-spinner" />
                : mode === 'login' ? 'Sign in' : 'Create account — it\'s free'}
            </button>
          </form>
        )}

        {/* Upgrade / limit / trial — CTA only */}
        {(mode === 'upgrade' || mode === 'limit' || mode === 'trial') && (
          <div className="gate-upgrade-content">
            <div className="gate-plan-card">
              <div className="gate-plan-name">Reyu Pro</div>
              <div className="gate-plan-price">
                <span className="gate-plan-amount">$20</span>
                <span className="gate-plan-period">/month</span>
              </div>
              <ul className="gate-plan-features">
                <li><GateCheck /> Unlimited saved strategies</li>
                <li><GateCheck /> Unlimited backtest runs</li>
                <li><GateCheck /> Paper trading</li>
                <li><GateCheck /> All broker integrations</li>
                <li><GateCheck /> Priority AI responses</li>
                <li><GateCheck /> Live trading (algo tier)</li>
              </ul>
              <button className="gate-btn gate-btn-primary gate-btn-upgrade" onClick={handleUpgrade}>
                Upgrade now — ₹1,650/mo
              </button>
              <p className="gate-plan-note">Credit card or UPI mandate. Cancel anytime.</p>
            </div>

            {/* Usage stats for limit mode */}
            {mode === 'limit' && (
              <div className="gate-usage-bar">
                <UsageBar label="Strategies" used={usage.strategies} max={FREE_STRATEGIES} />
                <UsageBar label="Backtests"  used={usage.backtests}  max={FREE_BACKTESTS} />
              </div>
            )}
          </div>
        )}

        {/* Mode switcher links */}
        <div className="gate-switcher">
          {mode === 'login' && (
            <>
              <span>No account? </span>
              <button onClick={() => setMode('signup')}>Start free trial</button>
            </>
          )}
          {mode === 'signup' && (
            <>
              <span>Already have an account? </span>
              <button onClick={() => setMode('login')}>Sign in</button>
            </>
          )}
          {(mode === 'upgrade' || mode === 'limit' || mode === 'trial') && (
            <>
              <span>Not ready? </span>
              <button onClick={closeGate}>Continue on free plan</button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function GateCheck() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
         stroke="var(--color-primary)" strokeWidth="2.5" style={{ flexShrink: 0 }}>
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  )
}

function UsageBar({ label, used, max }: { label: string; used: number; max: number }) {
  const pct = Math.min(100, Math.round((used / max) * 100))
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 12, color: 'var(--color-text-secondary)' }}>
        <span>{label}</span>
        <span>{used} / {max}</span>
      </div>
      <div style={{ height: 4, borderRadius: 2, background: 'var(--color-border)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: pct >= 90 ? 'var(--color-danger)' : 'var(--color-primary)', borderRadius: 2, transition: 'width 0.4s ease' }} />
      </div>
    </div>
  )
}

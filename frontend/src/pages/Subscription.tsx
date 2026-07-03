/**
 * Subscription / billing page  (/subscribe)
 *
 * Tiers match AuthContext: 'free' | 'pro' | 'algo'
 * Pricing (INR): ₹0 (15-day trial) | ₹2,000/mo | ₹9,900/mo
 * Must stay in sync with backend/app/routers/billing.py TIER_PRICES
 * and the Razorpay plan amounts configured in the Razorpay dashboard.
 * Uses useAuth() + api from AuthContext — no old ../api import.
 */
import { useState, useEffect, useCallback } from 'react'
import { useAuth, api } from '../context/AuthContext'

// ─── Plan data ────────────────────────────────────────────────────────────────

interface Plan {
  id: 'free' | 'pro' | 'algo'
  name: string
  priceINR: number
  priceAnnualINR: number
  tagline: string
  cta: string
  highlight: boolean
  features: { label: string; value: boolean | string }[]
}

const PLANS: Plan[] = [
  {
    id: 'free',
    name: 'Starter',
    priceINR: 0,
    priceAnnualINR: 0,
    tagline: '15-day trial with live market data',
    cta: 'Current plan',
    highlight: false,
    features: [
      { label: 'Live NSE option chain (demo)', value: true },
      { label: 'AI agent chat', value: true },
      { label: 'Saved strategies', value: '10 max' },
      { label: 'Backtest runs', value: '50 max' },
      { label: 'Payoff + Greeks charts', value: true },
      { label: 'Live broker connection', value: false },
      { label: 'Paper trading', value: false },
      { label: 'IV smile + skew', value: false },
      { label: 'RL signals', value: false },
      { label: 'Webhook alerts', value: false },
    ],
  },
  {
    id: 'pro',
    name: 'Pro',
    priceINR: 2000,
    priceAnnualINR: 19200, // ₹1,600/mo billed annually (~20% off)
    tagline: 'Full live trading — unlimited everything',
    cta: 'Upgrade to Pro',
    highlight: true,
    features: [
      { label: 'Live NSE option chain', value: true },
      { label: 'AI agent chat', value: true },
      { label: 'Saved strategies', value: 'Unlimited' },
      { label: 'Backtest runs', value: 'Unlimited' },
      { label: 'Payoff + Greeks charts', value: true },
      { label: 'Live broker connection', value: true },
      { label: 'Paper trading', value: true },
      { label: 'IV smile + skew', value: true },
      { label: 'RL signals', value: true },
      { label: 'Webhook alerts (Telegram/Discord)', value: true },
    ],
  },
  {
    id: 'algo',
    name: 'Algo',
    priceINR: 9900,
    priceAnnualINR: 94800, // ₹7,900/mo billed annually (~20% off)
    tagline: 'For systematic traders & desks',
    cta: 'Upgrade to Algo',
    highlight: false,
    features: [
      { label: 'Everything in Pro', value: true },
      { label: 'Multi-portfolio + kill switch', value: true },
      { label: 'Scalping scanner', value: true },
      { label: 'REST + WebSocket API', value: true },
      { label: 'Custom risk policies', value: true },
      { label: 'Multiple broker accounts', value: true },
      { label: 'Backtesting (with real premiums)', value: true },
      { label: 'White-glove onboarding', value: true },
      { label: 'Priority 24/7 support', value: true },
      { label: 'SLA guarantee', value: true },
    ],
  },
]

// ─── Razorpay ─────────────────────────────────────────────────────────────────

let _rzpLoaded = false
function loadRazorpay(): Promise<void> {
  return new Promise((res, rej) => {
    if (_rzpLoaded || (window as any).Razorpay) { _rzpLoaded = true; res(); return }
    const s = document.createElement('script')
    s.src = 'https://checkout.razorpay.com/v1/checkout.js'
    s.onload = () => { _rzpLoaded = true; res() }
    s.onerror = () => rej(new Error('Razorpay SDK failed to load'))
    document.body.appendChild(s)
  })
}

// ─── Sub status ───────────────────────────────────────────────────────────────

interface SubStatus {
  tier: string
  subscription_id: string | null
  subscription_status: string | null
  subscription_ends_at: string | null
  pending_plan: string | null
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function Subscription() {
  const { user, tier, isAuthenticated, openGate, trialDaysLeft, usage } = useAuth()
  const [cycle, setCycle] = useState<'month' | 'year'>('month')
  const [busy, setBusy] = useState(false)
  const [subStatus, setSubStatus] = useState<SubStatus | null>(null)
  const [toast, setToast] = useState<{ type: 'ok' | 'err'; msg: string } | null>(null)

  const pushToast = (type: 'ok' | 'err', msg: string) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 4000)
  }

  const fetchStatus = useCallback(async () => {
    if (!isAuthenticated) return
    try {
      const { data } = await api.get('/api/billing/status')
      setSubStatus(data)
    } catch { /* ignore */ }
  }, [isAuthenticated])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  // ── Upgrade / checkout ────────────────────────────────────────────────────

  async function handleChoose(plan: Plan) {
    if (plan.id === tier) return
    if (!isAuthenticated) {
      openGate({ mode: 'login', message: 'Sign in to upgrade your plan.', onSuccess: () => handleChoose(plan) })
      return
    }

    if (plan.id === 'free') {
      setBusy(true)
      try {
        await api.post('/api/user/tier', { tier: 'free' })
        pushToast('ok', 'Switched to Starter.')
        await fetchStatus()
      } catch (e: any) {
        pushToast('err', e?.response?.data?.detail || 'Could not switch plan.')
      }
      setBusy(false)
      return
    }

    // Paid plans — Razorpay checkout
    setBusy(true)
    try {
      await loadRazorpay()
      const { data: sub } = await api.post('/api/billing/create-subscription', {
        tier: plan.id,
        cycle,
      })
      const rzp = new (window as any).Razorpay({
        key: sub.razorpay_key,
        subscription_id: sub.subscription_id,
        name: 'Reyu.ai',
        description: `${plan.name} Plan — ${cycle === 'month' ? 'Monthly' : 'Annual'}`,
        image: '/reyu-icon.png',
        handler: async () => {
          pushToast('ok', `${plan.name} plan activated! Welcome to the next level.`)
          setTimeout(fetchStatus, 2000)
          setBusy(false)
        },
        prefill: { name: user?.display_name || '', email: user?.email || '' },
        theme: { color: '#10b981' },
        modal: { ondismiss: () => setBusy(false) },
        notes: { tier: plan.id, cycle },
      })
      rzp.open()
    } catch (e: any) {
      pushToast('err', e?.response?.data?.detail || e?.message || 'Checkout failed.')
      setBusy(false)
    }
  }

  async function handleCancel() {
    if (!confirm('Cancel subscription? You keep access until the end of your billing period.')) return
    setBusy(true)
    try {
      await api.post('/api/billing/cancel')
      pushToast('ok', 'Subscription cancelled. Access continues until period end.')
      await fetchStatus()
    } catch (e: any) {
      pushToast('err', e?.response?.data?.detail || 'Failed to cancel.')
    }
    setBusy(false)
  }

  // ── Derived ───────────────────────────────────────────────────────────────

  const inr = (n: number) => n.toLocaleString('en-IN')
  const displayPrice = (plan: Plan) =>
    cycle === 'month' ? plan.priceINR : Math.round(plan.priceAnnualINR / 12)

  const isActive = subStatus?.subscription_status === 'active'

  return (
    <div className="sub-page">
      {/* Toast */}
      {toast && (
        <div className={`sub-toast ${toast.type === 'ok' ? 'sub-toast-ok' : 'sub-toast-err'}`}>
          {toast.type === 'ok' ? '✓' : '⚠'} {toast.msg}
        </div>
      )}

      {/* Header */}
      <div className="sub-header">
        <h1 className="sub-title">Choose your edge</h1>
        <p className="sub-subtitle">
          From learning options to running a systematic algo book — Reyu.ai scales with you.
        </p>

        {/* Billing cycle toggle */}
        <div className="sub-cycle-toggle">
          <button
            className={`sub-cycle-btn ${cycle === 'month' ? 'sub-cycle-active' : ''}`}
            onClick={() => setCycle('month')}
          >Monthly</button>
          <button
            className={`sub-cycle-btn ${cycle === 'year' ? 'sub-cycle-active' : ''}`}
            onClick={() => setCycle('year')}
          >
            Annual
            <span className="sub-save-badge">Save ~20%</span>
          </button>
        </div>
      </div>

      {/* Trial countdown banner */}
      {isAuthenticated && trialDaysLeft !== null && (
        <div className="sub-trial-banner">
          <span className="sub-trial-icon">⏳</span>
          <div>
            <strong>{trialDaysLeft} day{trialDaysLeft !== 1 ? 's' : ''} left on your free trial</strong>
            <span className="sub-trial-sub"> — upgrade before it ends to keep your data.</span>
          </div>
        </div>
      )}

      {/* Free tier usage */}
      {isAuthenticated && tier === 'free' && (
        <div className="sub-usage-block">
          <div className="sub-usage-row">
            <span>Saved strategies</span>
            <span className="sub-usage-count">{usage.strategies} / 10</span>
          </div>
          <div className="sub-usage-bar">
            <div className="sub-usage-fill" style={{ width: `${Math.min(100, (usage.strategies / 10) * 100)}%` }} />
          </div>
          <div className="sub-usage-row" style={{ marginTop: 8 }}>
            <span>Backtest runs</span>
            <span className="sub-usage-count">{usage.backtests} / 50</span>
          </div>
          <div className="sub-usage-bar">
            <div className="sub-usage-fill" style={{ width: `${Math.min(100, (usage.backtests / 50) * 100)}%` }} />
          </div>
        </div>
      )}

      {/* Active subscription banner */}
      {isActive && tier !== 'free' && (
        <div className="sub-active-banner">
          <div className="sub-active-left">
            <span className="sub-active-dot" />
            <div>
              <strong>{PLANS.find(p => p.id === tier)?.name ?? tier} plan active</strong>
              {subStatus?.subscription_ends_at && (
                <div className="sub-active-sub">
                  Renews {new Date(subStatus.subscription_ends_at).toLocaleDateString('en-IN', {
                    year: 'numeric', month: 'short', day: 'numeric',
                  })}
                  {subStatus.pending_plan ? ` · Changing to ${subStatus.pending_plan} at period end` : ''}
                </div>
              )}
            </div>
          </div>
          <button className="sub-cancel-btn" onClick={handleCancel} disabled={busy}>
            Cancel
          </button>
        </div>
      )}

      {/* Plan cards */}
      <div className="sub-plans">
        {PLANS.map(plan => {
          const isCurrent = plan.id === tier
          return (
            <div
              key={plan.id}
              className={`sub-card ${plan.highlight ? 'sub-card-highlight' : ''} ${isCurrent ? 'sub-card-current' : ''}`}
            >
              {plan.highlight && <div className="sub-popular-badge">Most popular</div>}

              <div className="sub-card-header">
                <div className="sub-plan-name">{plan.name}</div>
                <div className="sub-price-row">
                  <span className="sub-price">
                    {plan.priceINR === 0 ? 'Free' : `₹${inr(displayPrice(plan))}`}
                  </span>
                  {plan.priceINR > 0 && <span className="sub-price-unit">/mo</span>}
                </div>
                {cycle === 'year' && plan.priceAnnualINR > 0 && (
                  <div className="sub-billed-note">billed ₹{inr(plan.priceAnnualINR)}/year</div>
                )}
                <div className="sub-tagline">{plan.tagline}</div>
              </div>

              <button
                className={`sub-cta-btn ${plan.highlight ? 'sub-cta-primary' : 'sub-cta-ghost'}`}
                disabled={isCurrent || busy}
                onClick={() => handleChoose(plan)}
              >
                {isCurrent ? '✓ Current plan' : plan.cta}
              </button>

              <ul className="sub-features">
                {plan.features.map(f => (
                  <li key={f.label} className={`sub-feature ${!f.value ? 'sub-feature-off' : ''}`}>
                    <span className="sub-feature-icon">
                      {f.value ? '✓' : '–'}
                    </span>
                    <span>
                      {f.label}
                      {typeof f.value === 'string' && (
                        <span className="sub-feature-val"> ({f.value})</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>

      {/* Footer trust bar */}
      <div className="sub-trust">
        <div className="sub-trust-items">
          <span>🔒 Razorpay secured</span>
          <span>↩ Cancel anytime</span>
          <span>🇮🇳 UPI mandate supported</span>
          <span>💳 All major cards</span>
        </div>
        <p className="sub-trust-note">
          All prices in INR, inclusive of billing via Razorpay (UPI, cards, netbanking).
          No questions asked cancellation policy.
        </p>
      </div>

      <style>{`
        .sub-page {
          max-width: 1060px;
          margin: 0 auto;
          padding: 32px 20px 60px;
          position: relative;
        }
        .sub-toast {
          position: fixed;
          top: 20px;
          left: 50%;
          transform: translateX(-50%);
          z-index: 9999;
          padding: 10px 20px;
          border-radius: 8px;
          font-size: 14px;
          font-weight: 500;
          animation: toastIn .2s ease;
        }
        .sub-toast-ok { background: var(--color-success); color: #fff; }
        .sub-toast-err { background: var(--color-danger); color: #fff; }
        @keyframes toastIn { from { opacity:0; transform: translateX(-50%) translateY(-8px); } to { opacity:1; transform: translateX(-50%) translateY(0); } }

        .sub-header { text-align: center; margin-bottom: 32px; }
        .sub-title { font-size: 30px; font-weight: 700; margin: 0 0 8px; }
        .sub-subtitle { color: var(--color-text-muted); font-size: 15px; margin: 0 0 20px; }

        .sub-cycle-toggle {
          display: inline-flex;
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
          border-radius: 999px;
          padding: 4px;
          gap: 2px;
        }
        .sub-cycle-btn {
          background: none;
          border: none;
          padding: 7px 18px;
          border-radius: 999px;
          font-size: 13px;
          cursor: pointer;
          color: var(--color-text-muted);
          transition: all .15s;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .sub-cycle-active {
          background: var(--color-primary);
          color: #fff;
        }
        .sub-save-badge {
          background: rgba(16,185,129,.18);
          color: var(--color-success);
          font-size: 10px;
          padding: 2px 6px;
          border-radius: 999px;
        }

        .sub-trial-banner {
          display: flex;
          align-items: center;
          gap: 10px;
          background: rgba(245,158,11,.1);
          border: 1px solid rgba(245,158,11,.3);
          border-radius: 10px;
          padding: 12px 16px;
          margin-bottom: 16px;
          font-size: 13px;
        }
        .sub-trial-icon { font-size: 18px; }
        .sub-trial-sub { color: var(--color-text-muted); }

        .sub-usage-block {
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
          border-radius: 10px;
          padding: 14px 16px;
          margin-bottom: 20px;
          font-size: 13px;
        }
        .sub-usage-row {
          display: flex;
          justify-content: space-between;
          margin-bottom: 4px;
          color: var(--color-text-muted);
        }
        .sub-usage-count { font-weight: 600; color: var(--color-text); }
        .sub-usage-bar {
          height: 5px;
          background: var(--color-border);
          border-radius: 999px;
          overflow: hidden;
        }
        .sub-usage-fill {
          height: 100%;
          background: var(--color-primary);
          border-radius: 999px;
          transition: width .4s ease;
        }

        .sub-active-banner {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: rgba(16,185,129,.08);
          border: 1px solid rgba(16,185,129,.25);
          border-radius: 10px;
          padding: 12px 16px;
          margin-bottom: 20px;
        }
        .sub-active-left { display: flex; align-items: center; gap: 10px; font-size: 14px; }
        .sub-active-dot {
          width: 8px; height: 8px;
          background: var(--color-success);
          border-radius: 50%;
          flex-shrink: 0;
          box-shadow: 0 0 0 3px rgba(16,185,129,.2);
        }
        .sub-active-sub { font-size: 12px; color: var(--color-text-muted); margin-top: 2px; }
        .sub-cancel-btn {
          font-size: 12px;
          padding: 5px 12px;
          background: none;
          border: 1px solid var(--color-border);
          border-radius: 6px;
          color: var(--color-text-muted);
          cursor: pointer;
          transition: all .15s;
        }
        .sub-cancel-btn:hover { border-color: var(--color-danger); color: var(--color-danger); }

        .sub-plans {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
          gap: 16px;
          margin-bottom: 32px;
        }

        .sub-card {
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
          border-radius: 14px;
          padding: 24px;
          position: relative;
          transition: box-shadow .2s, transform .2s;
        }
        .sub-card:hover { box-shadow: 0 4px 24px rgba(0,0,0,.12); }
        .sub-card-highlight {
          border-color: var(--color-primary);
          box-shadow: 0 0 0 1px var(--color-primary), 0 8px 32px rgba(16,185,129,.15);
          transform: translateY(-4px);
        }
        .sub-card-current { opacity: .85; }

        .sub-popular-badge {
          position: absolute;
          top: -12px;
          left: 50%;
          transform: translateX(-50%);
          background: var(--color-primary);
          color: #fff;
          font-size: 10px;
          font-weight: 600;
          letter-spacing: .8px;
          text-transform: uppercase;
          padding: 3px 12px;
          border-radius: 999px;
          white-space: nowrap;
        }

        .sub-card-header { margin-bottom: 18px; }
        .sub-plan-name {
          font-size: 12px;
          font-weight: 600;
          letter-spacing: 1px;
          text-transform: uppercase;
          color: var(--color-text-muted);
          margin-bottom: 8px;
        }
        .sub-price-row { display: flex; align-items: baseline; gap: 3px; }
        .sub-price { font-size: 36px; font-weight: 700; }
        .sub-price-unit { font-size: 14px; color: var(--color-text-muted); }
        .sub-billed-note { font-size: 11px; color: var(--color-text-muted); margin-top: 2px; }
        .sub-tagline { font-size: 13px; color: var(--color-text-muted); margin-top: 8px; line-height: 1.4; }

        .sub-cta-btn {
          width: 100%;
          padding: 11px;
          border-radius: 8px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          border: none;
          margin-bottom: 18px;
          transition: all .15s;
        }
        .sub-cta-btn:disabled { opacity: .55; cursor: default; }
        .sub-cta-primary {
          background: var(--color-primary);
          color: #fff;
          box-shadow: 0 2px 12px rgba(16,185,129,.3);
        }
        .sub-cta-primary:hover:not(:disabled) { filter: brightness(1.08); }
        .sub-cta-ghost {
          background: none;
          border: 1px solid var(--color-border);
          color: var(--color-text);
        }
        .sub-cta-ghost:hover:not(:disabled) { border-color: var(--color-primary); color: var(--color-primary); }

        .sub-features { list-style: none; padding: 0; margin: 0; }
        .sub-feature {
          display: flex;
          gap: 8px;
          font-size: 13px;
          padding: 4px 0;
          color: var(--color-text);
          line-height: 1.5;
        }
        .sub-feature-off { color: var(--color-text-muted); }
        .sub-feature-icon {
          flex-shrink: 0;
          width: 16px;
          color: var(--color-success);
          font-size: 12px;
        }
        .sub-feature-off .sub-feature-icon { color: var(--color-text-muted); }
        .sub-feature-val { color: var(--color-text-muted); }

        .sub-trust {
          text-align: center;
          padding-top: 24px;
          border-top: 1px solid var(--color-border);
        }
        .sub-trust-items {
          display: flex;
          justify-content: center;
          flex-wrap: wrap;
          gap: 20px;
          font-size: 13px;
          font-weight: 500;
          margin-bottom: 10px;
        }
        .sub-trust-note { font-size: 11px; color: var(--color-text-muted); margin: 0; }

        @media (max-width: 640px) {
          .sub-title { font-size: 22px; }
          .sub-plans { grid-template-columns: 1fr; }
          .sub-card-highlight { transform: none; }
        }
      `}</style>
    </div>
  )
}

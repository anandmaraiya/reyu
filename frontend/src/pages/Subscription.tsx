import { useState, useEffect, useCallback } from 'react'
import { useToast } from '../toast'
import { api } from '../api'

type Tier = {
  id: 'free' | 'pro' | 'algo'
  name: string
  price_inr_month: number
  price_inr_year: number
  tagline: string
  highlight: boolean
  features: { label: string; included: boolean | string }[]
}

const TIERS: Tier[] = [
  {
    id: 'free', name: 'Starter', price_inr_month: 0, price_inr_year: 0,
    tagline: 'Explore the platform with demo data',
    highlight: false,
    features: [
      { label: 'Demo chain (synthetic)', included: true },
      { label: '1 watchlist · up to 10 symbols', included: true },
      { label: 'Strategy Builder (single leg)', included: true },
      { label: 'Saved strategies', included: '3' },
      { label: 'Live Fyers data', included: false },
      { label: 'Multi-leg payoff + margin', included: false },
      { label: 'Webhook alerts', included: false },
      { label: 'API access', included: false },
      { label: 'Priority support', included: false },
    ],
  },
  {
    id: 'pro', name: 'Pro', price_inr_month: 999, price_inr_year: 9990,
    tagline: 'Most popular — full live trading workflow',
    highlight: true,
    features: [
      { label: 'Live Fyers chain + orders', included: true },
      { label: 'Watchlists · unlimited', included: true },
      { label: 'Strategy Builder (4 legs)', included: true },
      { label: 'Saved strategies', included: 'unlimited' },
      { label: 'Hedge builder + margin', included: true },
      { label: 'IV smile + skew analytics', included: true },
      { label: 'PCR / OI time series', included: true },
      { label: 'Webhook alerts (Telegram/Discord)', included: true },
      { label: 'API access', included: false },
    ],
  },
  {
    id: 'algo', name: 'Algo', price_inr_month: 2999, price_inr_year: 29990,
    tagline: 'For systematic traders & desks',
    highlight: false,
    features: [
      { label: 'Everything in Pro', included: true },
      { label: 'Multi-leg strategies (unlimited)', included: true },
      { label: 'Multi-portfolio book + kill switch', included: true },
      { label: 'Scalping signal scanner', included: true },
      { label: 'Strategy backtesting (coming)', included: true },
      { label: 'REST + WS API access', included: true },
      { label: 'Custom risk policies', included: true },
      { label: 'White-glove onboarding', included: true },
      { label: 'Priority 24/7 support', included: true },
    ],
  },
]

const CURRENT_TIER_KEY = 'reyu_tier'

// Load Razorpay script once
let razorpayScriptLoaded = false
function loadRazorpayScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (razorpayScriptLoaded || (window as any).Razorpay) {
      razorpayScriptLoaded = true
      resolve()
      return
    }
    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.onload = () => { razorpayScriptLoaded = true; resolve() }
    script.onerror = () => reject(new Error('Failed to load Razorpay SDK'))
    document.body.appendChild(script)
  })
}

interface RazorpayResponse {
  razorpay_payment_id: string
  razorpay_subscription_id: string
  razorpay_signature: string
}

export default function Subscription() {
  const t = useToast()
  const [cycle, setCycle] = useState<'month' | 'year'>('month')
  const [current, setCurrent] = useState<Tier['id']>(() => (localStorage.getItem(CURRENT_TIER_KEY) as any) || 'free')
  const [upgrading, setUpgrading] = useState(false)
  const [subStatus, setSubStatus] = useState<{
    tier: string
    subscription_id: string | null
    subscription_status: string | null
    subscription_ends_at: string | null
    pending_plan: string | null
  } | null>(null)

  // Fetch subscription status from backend
  const fetchStatus = useCallback(async () => {
    const token = localStorage.getItem('access_token')
    if (!token) return
    try {
      const { data } = await api.get('/api/billing/status')
      setSubStatus(data)
      if (data.tier) {
        setCurrent(data.tier as Tier['id'])
        localStorage.setItem(CURRENT_TIER_KEY, data.tier)
      }
    } catch {
      // Not logged in or no subscription yet — use local state
    }
  }, [])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  const openRazorpayCheckout = async (tierId: Tier['id']) => {
    setUpgrading(true)
    try {
      await loadRazorpayScript()

      // 1. Create subscription on backend
      const { data: sub } = await api.post('/api/billing/create-subscription', {
        tier: tierId,
        cycle,
      })

      // 2. Open Razorpay checkout modal
      const options = {
        key: sub.razorpay_key,
        subscription_id: sub.subscription_id,
        name: 'Reyu.ai',
        description: `${tierId.charAt(0).toUpperCase() + tierId.slice(1)} Plan (${cycle})`,
        image: '/reyu-icon.png',
        handler: async (_response: RazorpayResponse) => {
          // Payment succeeded — webhook will activate the plan
          t.push('success', `Payment successful! Your ${tierId} plan will activate shortly.`)
          // Refresh status after a short delay
          setTimeout(fetchStatus, 2000)
        },
        prefill: {
          name: sub.customer?.name || '',
          email: sub.customer?.email || '',
        },
        theme: { color: '#60a5fa' },
        modal: {
          ondismiss: () => {
            setUpgrading(false)
            t.push('info', 'Checkout cancelled. You can try again anytime.')
          },
        },
        notes: { tier: tierId, cycle },
        callback_url: sub.callback_url,
      }

      const rzp = new (window as any).Razorpay(options)
      rzp.open()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Failed to start checkout'
      t.push('error', msg)
      setUpgrading(false)
    }
  }

  const choose = async (id: Tier['id']) => {
    if (id === current) return

    if (id === 'free') {
      // Downgrade to free — no payment needed
      setUpgrading(true)
      try {
        const token = localStorage.getItem('access_token')
        if (token) {
          await api.post('/api/user/tier', { tier: id })
        }
      } catch {
        // Backend tier update failed — still save locally
      }
      localStorage.setItem(CURRENT_TIER_KEY, id)
      setCurrent(id)
      t.push('success', 'Switched to Starter.')
      setUpgrading(false)
      return
    }

    // Paid tier — open Razorpay checkout
    await openRazorpayCheckout(id)
  }

  const cancelSubscription = async () => {
    if (!confirm('Cancel your subscription? You will keep access until the end of your current billing period.')) return
    setUpgrading(true)
    try {
      await api.post('/api/billing/cancel')
      t.push('success', 'Subscription cancelled. You will keep access until the end of your current period.')
      await fetchStatus()
    } catch (err: any) {
      t.push('error', err?.response?.data?.detail || 'Failed to cancel subscription')
    }
    setUpgrading(false)
  }

  const price = (tier: Tier) =>
    cycle === 'month' ? tier.price_inr_month : Math.round(tier.price_inr_year / 12)

  const isPaid = (id: Tier['id']) => id === 'pro' || id === 'algo'

  return (
    <div className="page-shell">
      <div style={{ textAlign: 'center', marginBottom: 18 }}>
        <h2 style={{ margin: 0, fontSize: 28 }}>Choose your edge</h2>
        <p style={{ color: 'var(--muted)', marginTop: 6 }}>
          From learning options to running an automated book — Reyu.ai scales with you.
        </p>
        <div style={{ marginTop: 10, display: 'inline-flex', padding: 4, background: 'var(--border)', borderRadius: 999 }}>
          <button onClick={() => setCycle('month')}
                  className={cycle === 'month' ? 'primary' : 'ghost'} style={{ padding: '6px 14px' }}>Monthly</button>
          <button onClick={() => setCycle('year')}
                  className={cycle === 'year' ? 'primary' : 'ghost'} style={{ padding: '6px 14px' }}>
            Annual <span style={{ fontSize: 10, marginLeft: 4, color: 'var(--green)' }}>save ~17%</span>
          </button>
        </div>
      </div>

      {/* Active subscription banner */}
      {subStatus?.subscription_status === 'active' && current !== 'free' && (
        <div className="card" style={{ maxWidth: 720, margin: '0 auto 16px', textAlign: 'center', border: '1px solid var(--green)' }}>
          <div style={{ color: 'var(--green)', fontWeight: 600, marginBottom: 4 }}>
            ✓ {current.charAt(0).toUpperCase() + current.slice(1)} plan active
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            {subStatus.subscription_ends_at
              ? `Renews ${new Date(subStatus.subscription_ends_at).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' })}`
              : 'Auto-renewing'}
            {subStatus.pending_plan && ` · Changing to ${subStatus.pending_plan} at period end`}
          </div>
          <button onClick={cancelSubscription} disabled={upgrading}
                  className="ghost" style={{ fontSize: 11, marginTop: 8, color: 'var(--muted)' }}>
            Cancel subscription
          </button>
        </div>
      )}

      <div className="row" style={{ gap: 14, justifyContent: 'center', flexWrap: 'wrap' }}>
        {TIERS.map(tier => {
          const isCurrent = tier.id === current
          return (
            <div key={tier.id}
                 className={tier.highlight ? 'card-gradient' : 'card-glass'}
                 style={{
                   flex: '1 1 280px', maxWidth: 340, minWidth: 260,
                   border: tier.highlight ? '1px solid var(--accent)' : undefined,
                   transform: tier.highlight ? 'translateY(-4px)' : undefined,
                   boxShadow: tier.highlight ? '0 12px 32px rgba(96,165,250,0.18)' : undefined,
                   position: 'relative',
                 }}>
              {tier.highlight && (
                <div style={{
                  position: 'absolute', top: -10, left: '50%', transform: 'translateX(-50%)',
                  background: 'var(--accent)', color: '#fff', fontSize: 10,
                  padding: '3px 10px', borderRadius: 999, letterSpacing: 1, textTransform: 'uppercase',
                }}>Most popular</div>
              )}
              <div style={{ textAlign: 'center', padding: '8px 0 12px' }}>
                <div style={{ fontSize: 12, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>{tier.name}</div>
                <div style={{ fontSize: 32, fontWeight: 700, marginTop: 4 }}>
                  ₹{price(tier).toLocaleString('en-IN')}
                  <span style={{ fontSize: 13, color: 'var(--muted)', fontWeight: 400 }}>/mo</span>
                </div>
                {cycle === 'year' && tier.price_inr_year > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>billed ₹{tier.price_inr_year.toLocaleString('en-IN')} yearly</div>
                )}
                <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{tier.tagline}</div>
              </div>

              <button
                onClick={() => choose(tier.id)}
                disabled={isCurrent || upgrading}
                className={tier.highlight ? 'primary' : 'ghost'}
                style={{ width: '100%', padding: 10, marginBottom: 12, opacity: isCurrent ? .6 : 1 }}>
                {isCurrent
                  ? 'Current plan'
                  : tier.price_inr_month === 0
                    ? 'Switch to Starter'
                    : `Upgrade to ${tier.name}`}
              </button>

              <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: 12, lineHeight: 1.8 }}>
                {tier.features.map(f => (
                  <li key={f.label} style={{ display: 'flex', gap: 8 }}>
                    <span style={{ color: f.included ? 'var(--green)' : 'var(--muted)' }}>
                      {f.included ? '✓' : '–'}
                    </span>
                    <span style={{ color: f.included ? 'var(--text)' : 'var(--muted)' }}>
                      {f.label}{typeof f.included === 'string' ? ` (${f.included})` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>

      <div className="card" style={{ marginTop: 20, maxWidth: 720, marginInline: 'auto', textAlign: 'center' }}>
        <h3 style={{ margin: '0 0 6px' }}>Why traders choose Reyu.ai</h3>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
          ⚡ Single-view chain · IV smile · Greeks heatmap · PCR time series ·
          payoff + margin in one click · Strategy builder with templates ·
          Multi-portfolio risk caps · Kill-switch · Webhook alerts · Fyers SPAN margin · Demo mode
        </div>
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
          Payments powered by Razorpay. Cancel anytime — no questions asked.
        </div>
      </div>
    </div>
  )
}

import { useState } from 'react'
import { useToast } from '../toast'

type Tier = {
  id: 'free' | 'pro' | 'premium'
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
    id: 'premium', name: 'Algo', price_inr_month: 2999, price_inr_year: 29990,
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

export default function Subscription() {
  const t = useToast()
  const [cycle, setCycle] = useState<'month' | 'year'>('month')
  const [current, setCurrent] = useState<Tier['id']>(() => (localStorage.getItem(CURRENT_TIER_KEY) as any) || 'pro')

  const choose = (id: Tier['id']) => {
    localStorage.setItem(CURRENT_TIER_KEY, id)
    setCurrent(id)
    t.push('success',
      id === 'free' ? 'Downgraded to Starter.' :
      `Upgrade to ${id.toUpperCase()} — billing integration coming soon. We've saved your preference.`)
  }

  const price = (tier: Tier) =>
    cycle === 'month' ? tier.price_inr_month : Math.round(tier.price_inr_year / 12)

  return (
    <div className="page-shell">
      <div style={{ textAlign: 'center', marginBottom: 18 }}>
        <h2 style={{ margin: 0, fontSize: 28 }}>Choose your edge</h2>
        <p style={{ color: 'var(--muted)', marginTop: 6 }}>
          From learning options to running an automated book — Reyu scales with you.
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
                disabled={isCurrent}
                className={tier.highlight ? 'primary' : 'ghost'}
                style={{ width: '100%', padding: 10, marginBottom: 12, opacity: isCurrent ? .6 : 1 }}>
                {isCurrent ? 'Current plan' : tier.price_inr_month === 0 ? 'Switch to Starter' : `Upgrade to ${tier.name}`}
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
        <h3 style={{ margin: '0 0 6px' }}>Why traders choose Reyu</h3>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
          ⚡ Single-view chain · IV smile · Greeks heatmap · PCR time series ·
          payoff + margin in one click · Strategy builder with templates ·
          Multi-portfolio risk caps · Kill-switch · Webhook alerts · Fyers SPAN margin · Demo mode
        </div>
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
          Billing integration is mocked — your plan choice is stored locally for now. Real Razorpay flow coming next release.
        </div>
      </div>
    </div>
  )
}

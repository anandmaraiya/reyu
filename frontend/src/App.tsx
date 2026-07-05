/**
 * App.tsx — Reyu shell.
 *
 * Layout:
 *   MarketRibbon (top, full-width, always visible)
 *   ├── Sidebar   (left, collapsible)
 *   └── <page>   (main content area)
 *
 * Auth: AuthProvider (context/AuthContext.tsx) handles all auth state.
 * Lazy gate: GateModal renders globally — API 401/402 fires it via interceptor.
 * No forced login wall. / → ReyuAgent (Chat) by default.
 */
import { useEffect, useState, lazy, Suspense } from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext'

import { AuthProvider }  from './context/AuthContext'
import { GateModal }     from './components/GateModal'
import LegalGate         from './components/LegalGate'
import { MarketRibbon }  from './components/MarketRibbon'
import { Sidebar }       from './components/Sidebar'
import ErrorBoundary     from './ErrorBoundary'
import CommandPalette    from './CommandPalette'

// ── Style imports ────────────────────────────────────────────────────────────
import './styles/tokens.css'   // Design tokens (must be first)
import './styles/layout.css'   // Shell, ribbon, sidebar
import './styles/gate.css'     // GateModal
import './styles.css'          // Legacy component styles (kept for existing pages)

// ── Page lazy imports ────────────────────────────────────────────────────────
// Default route
const Chat           = lazy(() => import('./pages/Chat'))
const Login          = lazy(() => import('./pages/Login'))
const TrainingLab    = lazy(() => import('./pages/TrainingLab'))
const DataAdmin      = lazy(() => import('./pages/DataAdmin'))
const ResetPassword  = lazy(() => import('./pages/ResetPassword'))
const Onboarding     = lazy(() => import('./pages/Onboarding'))
const Journal        = lazy(() => import('./pages/Journal'))
const Catalog        = lazy(() => import('./pages/Catalog'))
const Legal          = lazy(() => import('./pages/Legal'))
const Activity       = lazy(() => import('./pages/Activity'))
const PortfolioOverview = lazy(() => import('./pages/PortfolioOverview'))
const Templates      = lazy(() => import('./pages/Templates'))
const Creator        = lazy(() => import('./pages/Creator'))
const PriceCharts    = lazy(() => import('./pages/PriceCharts'))
// Core
const Dashboard      = lazy(() => import('./pages/Dashboard'))
const Positions      = lazy(() => import('./pages/Positions'))
// Strategies
const Strategies     = lazy(() => import('./pages/Strategies'))
const StrategyDetail = lazy(() => import('./pages/StrategyDetail'))
const StrategyCompare= lazy(() => import('./pages/StrategyCompare'))
const Backtest       = lazy(() => import('./pages/Backtest'))
// Watchlist
const Scalping       = lazy(() => import('./pages/Scalping'))
const Portfolios     = lazy(() => import('./pages/Portfolios'))
const Audit          = lazy(() => import('./pages/Audit'))
// Account
const Settings       = lazy(() => import('./pages/Settings'))
const Subscription   = lazy(() => import('./pages/Subscription'))
const Brokers        = lazy(() => import('./pages/Brokers'))
// RL dashboard
const RL             = lazy(() => import('./pages/RL'))

// ── Page loading fallback ─────────────────────────────────────────────────────
function PageSkeleton() {
  return (
    <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {[1, 2, 3].map(i => (
        <div key={i} style={{
          height: i === 1 ? 40 : 120,
          borderRadius: 8,
          background: 'var(--color-border)',
          animation: 'shimmer 1.2s infinite',
        }} />
      ))}
    </div>
  )
}

// ── Root component (needs AuthProvider above) ─────────────────────────────────
function AppShell() {
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (localStorage.getItem('reyu_theme') as 'dark' | 'light') || 'dark'
  )

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('reyu_theme', theme)
  }, [theme])

  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')

  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  return (
    <div className="app-shell" data-theme={theme}>
      {/* Mobile hamburger — floats top-left, only shown on mobile via CSS */}
      <button
        className="mobile-menu-btn"
        onClick={() => setMobileNavOpen(true)}
        aria-label="Open navigation"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="3" y1="6"  x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>

      {/* Top market ribbon — always visible */}
      <MarketRibbon />

      <div className="app-body">
        {/* Mobile backdrop (closes drawer on tap) */}
        <div
          className={`sidebar-backdrop ${mobileNavOpen ? 'open' : ''}`}
          onClick={() => setMobileNavOpen(false)}
        />
        {/* Collapsible sidebar — becomes drawer on mobile */}
        <Sidebar mobileOpen={mobileNavOpen} onMobileClose={() => setMobileNavOpen(false)} />

        {/* Main page content */}
        <main className="app-main">
          <ErrorBoundary>
            <Suspense fallback={<PageSkeleton />}>
              <Routes>
                {/* Agent is home — no login required */}
                <Route path="/"           element={<Chat />} />
                <Route path="/agent"      element={<Navigate to="/" replace />} />

                {/* Auth pages — standalone (GateModal handles in-context auth) */}
                <Route path="/login"      element={<Login />} />
                <Route path="/register"   element={<Login />} />

                {/* Price terminal vs option-chain terminal — distinct jobs */}
                <Route path="/charts"     element={<PriceCharts />} />
                <Route path="/chain"      element={<Dashboard />} />

                {/* Positions */}
                <Route path="/positions"  element={<Positions />} />

                {/* Strategies */}
                <Route path="/strategies"          element={<Strategies />} />
                <Route path="/strategies/compare"  element={<StrategyCompare />} />
                <Route path="/strategies/:id"      element={<StrategyDetail />} />
                <Route path="/backtest"            element={<Backtest />} />
                {/* Legacy /compare used dead endpoints — the working
                    saved-strategy comparison lives at /strategies/compare. */}
                <Route path="/compare"             element={<Navigate to="/strategies/compare" replace />} />

                {/* Watchlist */}
                <Route path="/scalping"   element={<Scalping />} />
                <Route path="/portfolios" element={<Portfolios />} />
                <Route path="/orders"     element={<Audit />} />

                {/* Account */}
                <Route path="/brokers"    element={<Brokers />} />
                <Route path="/subscribe"  element={<Subscription />} />
                <Route path="/settings"   element={<Settings theme={theme} setTheme={setTheme} />} />
                <Route path="/admin/data" element={<DataAdmin />} />
                <Route path="/reset-password" element={<ResetPassword />} />
                <Route path="/onboarding" element={<Onboarding />} />
                <Route path="/journal"    element={<Journal />} />
                <Route path="/catalog"    element={<Catalog />} />
                <Route path="/legal"          element={<Legal />} />
                <Route path="/legal/:docType" element={<Legal />} />
                <Route path="/activity"       element={<Activity />} />
                <Route path="/portfolio"      element={<PortfolioOverview />} />
                <Route path="/templates"      element={<Templates />} />
                <Route path="/creators/:id"   element={<Creator />} />

                {/* RL dashboard + training lab */}
                <Route path="/rl"         element={<RL />} />
                <Route path="/rl/lab"     element={<TrainingLab />} />
                <Route path="/lab"        element={<Navigate to="/rl/lab" replace />} />

                {/* Legacy redirects */}
                <Route path="/dashboard"    element={<Navigate to="/charts" replace />} />
                <Route path="/chat"         element={<Navigate to="/" replace />} />
                <Route path="/subscription" element={<Navigate to="/subscribe" replace />} />
                <Route path="/saved"        element={<Navigate to="/strategies" replace />} />
                <Route path="/audit"        element={<Navigate to="/orders" replace />} />
                <Route path="/watchlists"   element={<Navigate to="/scalping" replace />} />
                <Route path="/strategy"     element={<Navigate to="/" replace />} />

                {/* 404 */}
                <Route path="*"           element={<NotFound />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>

      {/* Global overlays */}
      <GateModal />
      <LegalGate />
      <CommandPalette toggleTheme={toggleTheme} />

      {/* First-run onboarding gate — redirects logged-in users with
          onboarded_at === null to /onboarding, once per session. */}
      <OnboardingGate />
    </div>
  )
}

/**
 * Redirects logged-in users to /onboarding ONCE per session on first
 * post-login navigation. After that, users can freely go anywhere —
 * onboarding is a nudge, not a wall.
 *
 * Session flag: sessionStorage 'reyu_onboard_redirected' — cleared
 * automatically when the tab closes. On logout we don't clear it, so a
 * re-login in the same tab respects the user's "I'll do it later" choice.
 */
const REDIRECTED_FLAG = 'reyu_onboard_redirected'

function OnboardingGate() {
  const { user } = useAuth()
  const location = useLocation()
  const nav = useNavigate()

  useEffect(() => {
    if (!user) return
    if (user.onboarded_at) return
    // Only fire once per session — never nag on subsequent navigations
    if (sessionStorage.getItem(REDIRECTED_FLAG) === '1') return
    // Never interrupt these routes even on the first hit
    const skip = ['/onboarding', '/reset-password']
    if (skip.some(p => location.pathname.startsWith(p))) return
    // Anonymous-friendly landing — let users browse without gate
    if (location.pathname === '/') return

    sessionStorage.setItem(REDIRECTED_FLAG, '1')
    nav('/onboarding', { replace: true })
  }, [user, location.pathname, nav])

  return null
}

function NotFound() {
  return (
    <div style={{ padding: 48, textAlign: 'center' }}>
      <div style={{ fontSize: 48, marginBottom: 16 }}>🤖</div>
      <h2 style={{ color: 'var(--color-text-primary)', fontWeight: 700 }}>Page not found</h2>
      <p style={{ color: 'var(--color-text-secondary)', marginTop: 8 }}>Ask Reyu — it can navigate you anywhere.</p>
    </div>
  )
}

// Root export
export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  )
}

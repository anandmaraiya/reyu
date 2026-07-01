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
const DataAdmin      = lazy(() => import('./pages/DataAdmin'))
const ResetPassword  = lazy(() => import('./pages/ResetPassword'))
const Onboarding     = lazy(() => import('./pages/Onboarding'))
const Journal        = lazy(() => import('./pages/Journal'))
// Core
const Dashboard      = lazy(() => import('./pages/Dashboard'))
const Positions      = lazy(() => import('./pages/Positions'))
// Strategies
const Strategies     = lazy(() => import('./pages/Strategies'))
const StrategyDetail = lazy(() => import('./pages/StrategyDetail'))
const StrategyCompare= lazy(() => import('./pages/StrategyCompare'))
const Backtest       = lazy(() => import('./pages/Backtest'))
const Compare        = lazy(() => import('./pages/Compare'))
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

  return (
    <div className="app-shell" data-theme={theme}>
      {/* Top market ribbon — always visible */}
      <MarketRibbon />

      <div className="app-body">
        {/* Collapsible sidebar */}
        <Sidebar />

        {/* Main page content */}
        <main className="app-main">
          <ErrorBoundary>
            <Suspense fallback={<PageSkeleton />}>
              <Routes>
                {/* Agent is home — no login required */}
                <Route path="/"           element={<Chat />} />
                <Route path="/agent"      element={<Navigate to="/" replace />} />

                {/* Charts / option chain */}
                <Route path="/charts"     element={<Dashboard />} />
                <Route path="/chain"      element={<Dashboard />} />

                {/* Positions */}
                <Route path="/positions"  element={<Positions />} />

                {/* Strategies */}
                <Route path="/strategies"          element={<Strategies />} />
                <Route path="/strategies/compare"  element={<StrategyCompare />} />
                <Route path="/strategies/:id"      element={<StrategyDetail />} />
                <Route path="/backtest"            element={<Backtest />} />
                <Route path="/compare"             element={<Compare />} />

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

                {/* RL dashboard */}
                <Route path="/rl"         element={<RL />} />

                {/* Legacy redirects */}
                <Route path="/dashboard"    element={<Navigate to="/charts" replace />} />
                <Route path="/chat"         element={<Navigate to="/" replace />} />
                <Route path="/login"        element={<Navigate to="/" replace />} />
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
      <CommandPalette toggleTheme={toggleTheme} />

      {/* First-run onboarding gate — redirects logged-in users with
          onboarded_at === null to /onboarding, once per session. */}
      <OnboardingGate />
    </div>
  )
}

/**
 * Redirects logged-in users to /onboarding when onboarded_at is null.
 *
 * Runs once per navigation change; skips if already on /onboarding, a
 * public route (/, /reset-password), or if user is anonymous.
 *
 * Intentionally non-blocking — it doesn't wrap Routes because we don't
 * want to force the onboarding flow on people who navigate manually or
 * who are re-visiting pages. It just fires a redirect once per session.
 */
function OnboardingGate() {
  const { user } = useAuth()
  const location = useLocation()
  const nav = useNavigate()

  useEffect(() => {
    if (!user) return
    if (user.onboarded_at) return
    // Never interrupt these routes
    const skip = ['/onboarding', '/reset-password']
    if (skip.some(p => location.pathname.startsWith(p))) return
    // Skip anonymous-friendly landing so users can browse
    if (location.pathname === '/') return
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

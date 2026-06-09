import { useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes, Navigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import Dashboard from './pages/Dashboard'
import Watchlists from './pages/Watchlists'
import Portfolios from './pages/Portfolios'
import Scalping from './pages/Scalping'
import Strategy from './pages/Strategy'
import Chat from './pages/Chat'
import Backtest from './pages/Backtest'
import Positions from './pages/Positions'
import Login from './pages/Login'
import Saved from './pages/Saved'
import Strategies from './pages/Strategies'
import StrategyDetail from './pages/StrategyDetail'
import StrategyCompare from './pages/StrategyCompare'
import Audit from './pages/Audit'
import Compare from './pages/Compare'
import Settings from './pages/Settings'
import Subscription from './pages/Subscription'
import CommandPalette from './CommandPalette'
import ErrorBoundary from './ErrorBoundary'
import MarketTicker from './components/MarketTicker'

type Status = { fyers: boolean; demo_mode: boolean; redis: boolean; postgres: boolean; last_snapshot_at: string | null; tracked_symbols: number }

type NavItem = { to: string; label: string; icon: JSX.Element }

type NavGroup = { group: string; items: NavItem[] }

const NAV: NavGroup[] = [
  { group: 'Trade', items: [
    { to: '/dashboard', label: 'Option Chain', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 17h4V7H4z"/><path d="M10 17h4V4h-4z"/><path d="M16 17h4V11h-4z"/></svg> },
    { to: '/strategy', label: 'Strategy Builder', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"/><path d="M7 12h10"/><path d="M11 18h6"/></svg> },
    { to: '/strategies', label: 'My Strategies', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="7" height="7"/><rect x="14" y="4" width="7" height="7"/><rect x="3" y="13" width="7" height="7"/><rect x="14" y="13" width="7" height="7"/></svg> },
    { to: '/chat', label: 'AI Co-pilot', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/></svg> },
    { to: '/backtest', label: 'Backtest', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18"/><path d="M7 14l3-6 4 4 6-9"/></svg> },
    { to: '/compare', label: 'Compare Strategies', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 6h6v12H4z"/><path d="M14 9h6v9h-6z"/></svg> },
    { to: '/positions', label: 'Positions', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19h16"/><path d="M7 15l3-3 2 2 5-5"/><path d="M8 11V7h8v2"/></svg> },
    { to: '/scalping', label: 'Scalping', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/></svg> },
  ]},
  { group: 'Manage', items: [
    { to: '/watchlists', label: 'Watchlists', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg> },
    { to: '/portfolios', label: 'Portfolios', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 6h16v4H4z"/><path d="M4 14h6v4H4z"/><path d="M14 14h6v4h-6z"/></svg> },
    { to: '/saved', label: 'Saved Strategies', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 5h16v14H4z"/><path d="M8 9h8"/><path d="M8 13h5"/></svg> },
    { to: '/audit', label: 'Order Audit', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 6h16M4 12h16M4 18h10"/></svg> },
  ]},
  { group: 'Account', items: [
    { to: '/login', label: 'Fyers Auth', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5a3 3 0 0 1 3 3v4a3 3 0 1 1-6 0V8a3 3 0 0 1 3-3z"/><path d="M5 21h14"/></svg> },
    { to: '/settings', label: 'Settings', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.7l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.7-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 0 1-4 0v-.2a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.7.3l-.1.1a2 2 0 0 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.7 1.7 1.7 0 0 0-1.6-1H3a2 2 0 0 1 0-4h.2a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.7l-.1-.1a2 2 0 0 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.7.3h.2A1.7 1.7 0 0 0 10 3.6V3a2 2 0 0 1 4 0v.2a1.7 1.7 0 0 0 1 1.6h.2a1.7 1.7 0 0 0 1.7-.3l.1-.1a2 2 0 0 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.7v.2a1.7 1.7 0 0 0 1.6 1H21a2 2 0 0 1 0 4h-.2a1.7 1.7 0 0 0-1.6 1z"/></svg> },
    { to: '/subscription', label: 'Subscription', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2l3 6 6 1-4.5 4.5L18 20l-6-3-6 3 1.5-6.5L3 9l6-1z"/></svg> },
  ]},
]

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="sidebar-status">
      <span className={`status-dot ${ok ? 'ok' : 'err'}`} />
      {label}
    </span>
  )
}

const PAGE_TITLE_MAP: Record<string, string> = {
  '/dashboard': 'Option Chain',
  '/strategy': 'Strategy Builder',
  '/strategies': 'My Strategies',
  '/chat': 'AI Co-pilot',
  '/backtest': 'Backtest',
  '/compare': 'Compare Strategies',
  '/positions': 'Positions',
  '/watchlists': 'Watchlists',
  '/portfolios': 'Portfolios',
  '/scalping': 'Scalping',
  '/saved': 'Saved Strategies',
  '/audit': 'Order Audit',
  '/subscription': 'Subscription',
  '/settings': 'Settings',
  '/login': 'Login',
}

export default function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => (localStorage.getItem('theme') as any) || 'dark')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [user, setUser] = useState<{ id: string; email: string; display_name: string; tier: string } | null>(() => {
    try { return JSON.parse(localStorage.getItem('user') || 'null') } catch { return null }
  })
  const location = useLocation()

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('theme', theme)
  }, [theme])

  const { data: status } = useQuery<Status>({
    queryKey: ['system-status'],
    queryFn: async () => (await api.get('/api/system/status')).data,
    refetchInterval: 10000,
  })

  const pageTitle = useMemo(() => {
    const p = location.pathname
    if (PAGE_TITLE_MAP[p]) return PAGE_TITLE_MAP[p]
    // Dynamic sub-routes
    if (p === '/strategies/compare') return 'Compare Strategies'
    if (p.startsWith('/strategies/')) return 'Strategy Detail'
    return 'Dashboard'
  }, [location.pathname])
  const breadcrumb = useMemo(() => ['Home', pageTitle], [pageTitle])

  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')
  const toggleSidebar = () => setSidebarCollapsed(v => !v)

  const logout = () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
    setUser(null)
  }

  return (
    <div className={`app ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="sidebar-header">
          <div>
            <div className="sidebar-logo">Reyu.ai</div>
            <div className="sidebar-tag">Premium</div>
          </div>
          <button type="button" className="sidebar-collapse-btn" onClick={toggleSidebar} aria-label="Toggle sidebar">
            {sidebarCollapsed ? '➜' : '≡'}
          </button>
        </div>

        <div className="sidebar-nav">
          {NAV.map(g => (
            <div key={g.group} className="sidebar-group">
              <div className="sidebar-group-label">{g.group}</div>
              <nav>
                {g.items.map(i => (
                  <NavLink key={i.to} to={i.to} className={({ isActive }) => isActive ? 'active' : ''}>
                    <span className="nav-icon">{i.icon}</span>
                    <span>{i.label}</span>
                  </NavLink>
                ))}
              </nav>
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          <div className="profile-card">
            <div className="profile-avatar">{user ? user.display_name.charAt(0).toUpperCase() : 'R'}</div>
            <div>
              <div className="profile-name">{user ? user.display_name : 'Reyu Trader'}</div>
              <div className="profile-meta">{user ? `${user.tier.charAt(0).toUpperCase()}${user.tier.slice(1)} Tier` : 'Pro Tier'}</div>
            </div>
          </div>
          {user && (
            <button className="ghost" onClick={logout} style={{ width: '100%', padding: 6, fontSize: 11, marginBottom: 6 }}>
              Sign Out
            </button>
          )}
          <div className="sidebar-status-bar">
            <StatusDot ok={!!status?.fyers} label={status?.fyers ? 'Fyers live' : 'Demo mode'} />
            <StatusDot ok={!!status?.redis} label="Redis" />
            <StatusDot ok={!!status?.postgres} label="Postgres" />
          </div>
          <button className="theme-toggle" onClick={toggleTheme}>
            {theme === 'dark' ? 'Light mode' : 'Dark mode'}
          </button>
        </div>
      </aside>

      <div className="main-wrapper">
        <MarketTicker />

        <div className="page-header">
          <div>
            <div className="page-title">
              <span className="page-title-icon">📈</span>
              {pageTitle}
            </div>
            <div className="page-breadcrumb">
              {breadcrumb.map((part, index) => (
                <span key={part}>
                  {part}
                  {index < breadcrumb.length - 1 && <span>•</span>}
                </span>
              ))}
            </div>
          </div>

          <div className="page-actions">
            <button type="button" className="icon-button" aria-label="Command palette (⌘K)"
                    title="Command palette · ⌘K / Ctrl+K"
                    onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))}>
              <span>🔎</span>
            </button>
            <button type="button" className="icon-button" aria-label="Notifications"
                    title="Notifications (coming soon)"
                    onClick={() => alert('Notification centre coming soon — webhook alerts are in Settings.')}>
              <span>🔔</span>
            </button>
          </div>
        </div>

        <main className="main">
          {status?.demo_mode && (
            <div className="demo-banner">
              <strong>DEMO MODE</strong> — showing synthetic data. <a href="/login">Connect Fyers</a> to switch to live quotes, orders, and positions.
            </div>
          )}
          <ErrorBoundary>
            <div className="route-fade" key={location.pathname}>
              <Routes location={location}>
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/strategy" element={<Strategy />} />
                <Route path="/strategies" element={<Strategies />} />
                <Route path="/strategies/compare" element={<StrategyCompare />} />
                <Route path="/strategies/:id" element={<StrategyDetail />} />
                <Route path="/chat" element={<Chat />} />
                <Route path="/backtest" element={<Backtest />} />
                <Route path="/compare" element={<Compare />} />
                <Route path="/positions" element={<Positions />} />
                <Route path="/watchlists" element={<Watchlists />} />
                <Route path="/portfolios" element={<Portfolios />} />
                <Route path="/scalping" element={<Scalping />} />
                <Route path="/saved" element={<Saved />} />
                <Route path="/audit" element={<Audit />} />
                <Route path="/settings" element={<Settings theme={theme} setTheme={setTheme} />} />
                <Route path="/subscription" element={<Subscription />} />
                <Route path="/login" element={<Login />} />
              </Routes>
            </div>
          </ErrorBoundary>
        </main>
      </div>

      <CommandPalette toggleTheme={toggleTheme} />
    </div>
  )
}

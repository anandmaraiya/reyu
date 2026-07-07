/**
 * Sidebar — collapsible left navigation.
 *
 * Collapsed: shows 40px icon rail.
 * Expanded: shows 220px full nav with labels.
 *
 * Structure:
 *   • Reyu AI       (default, /agent)
 *   • Charts        (/charts)
 *   • Option Chain  (/chain)
 *   • Positions     (/positions)
 *   ── My Strategies ──
 *   • Saved         (/strategies)
 *   • Backtest      (/backtest)
 *   • Compare       (/compare)
 *   ── Watchlist ──
 *   • Scalping      (/scalping)
 *   • Portfolios    (/portfolios)
 *   • Order Audit   (/orders)
 *   ── Account ──
 *   • Brokers       (/brokers)
 *   • Subscription  (/subscribe)
 *   • Settings      (/settings)
 */
import React, { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

interface NavItem {
  id: string
  label: string
  icon: React.ReactNode
  path: string
  group?: string
  badge?: string
  highlight?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { id: 'agent',     label: 'Reyu AI',      icon: <AgentIcon />,     path: '/',          highlight: true },
  { id: 'charts',    label: 'Charts',        icon: <ChartsIcon />,    path: '/charts' },
  { id: 'chain',     label: 'Option Chain',  icon: <ChainIcon />,     path: '/chain' },
  { id: 'positions', label: 'Positions',     icon: <PositionsIcon />, path: '/positions' },
  { id: 'portfolio', label: 'Portfolio',     icon: <PortfolioIcon />, path: '/portfolio' },
  { id: 'journal',   label: 'Journal',       icon: <JournalIcon />,   path: '/journal' },
  { id: 'templates', label: 'Templates',     icon: <TemplateIcon />,  path: '/templates', group: 'My Strategies' },
  { id: 'catalog',   label: 'Catalog',       icon: <CatalogIcon />,   path: '/catalog',   group: 'My Strategies' },
  { id: 'strategies',label: 'Saved',         icon: <SavedIcon />,     path: '/strategies',group: 'My Strategies' },
  { id: 'backtest',  label: 'Backtest',      icon: <BacktestIcon />,  path: '/backtest',  group: 'My Strategies' },
  { id: 'compare',   label: 'Compare',       icon: <CompareIcon />,   path: '/compare',   group: 'My Strategies' },
  { id: 'scalping',  label: 'Scalping',      icon: <ScalpIcon />,     path: '/scalping',  group: 'Watchlist' },
  { id: 'portfolios',label: 'Portfolios',    icon: <BasketIcon />,    path: '/portfolios',group: 'Watchlist' },
  { id: 'orders',    label: 'Order Audit',   icon: <OrderIcon />,     path: '/orders',    group: 'Watchlist' },
  { id: 'brokers',   label: 'Brokers',       icon: <BrokersIcon />,   path: '/brokers',   group: 'Account' },
  { id: 'activity',  label: 'My Activity',   icon: <ActivityIcon />,  path: '/activity',  group: 'Account' },
  { id: 'subscribe', label: 'Subscription',  icon: <SubIcon />,       path: '/subscribe', group: 'Account' },
  { id: 'settings',  label: 'Settings',      icon: <SettingsIcon />,  path: '/settings',  group: 'Account' },
  { id: 'legal',     label: 'Legal',         icon: <LegalIcon />,     path: '/legal',     group: 'Account' },
  { id: 'rl',        label: 'AI Auto-Trader', icon: <RLIcon />,       path: '/rl',        group: 'Account', badge: 'LIVE' },
  { id: 'rl-lab',    label: 'Strategy Lab',  icon: <LabIcon />,       path: '/rl/lab',    group: 'Account' },
  // Superadmin only — Sidebar filters this for non-superadmins.
  { id: 'data-admin',label: 'Data Capture',  icon: <DataIcon />,      path: '/admin/data', group: 'Admin', badge: 'ADMIN' },
]

export function Sidebar({ mobileOpen, onMobileClose }: { mobileOpen?: boolean; onMobileClose?: () => void } = {}) {
  const location  = useLocation()
  const navigate  = useNavigate()
  const { user, tier, trialDaysLeft, logout, openGate } = useAuth()
  const [collapsed, setCollapsed] = useState(() =>
    localStorage.getItem('reyu_sidebar_collapsed') === 'true'
  )

  useEffect(() => {
    localStorage.setItem('reyu_sidebar_collapsed', String(collapsed))
  }, [collapsed])

  // Group items
  const groups = ['', 'My Strategies', 'Watchlist', 'Account', 'Admin']

  // Superadmin-only nav items (filtered out for all other users)
  const isSuperadmin = user?.email === 'algo@reyu.ai'

  function handleNav(item: NavItem) {
    // Protected paths prompt login if anonymous
    const protected_ = ['/positions', '/portfolio', '/strategies', '/backtest', '/compare', '/orders', '/brokers', '/subscribe', '/rl', '/activity']
    if (!user && protected_.includes(item.path)) {
      openGate({ mode: 'login', message: `Sign in to access ${item.label}.`, onSuccess: () => navigate(item.path) })
      return
    }
    navigate(item.path)
  }

  const isActive = (path: string) =>
    path === '/' ? location.pathname === '/' : location.pathname.startsWith(path)

  // Close mobile drawer whenever user navigates to a new path
  useEffect(() => {
    if (mobileOpen && onMobileClose) onMobileClose()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar-collapsed' : 'sidebar-expanded'} ${mobileOpen ? 'sidebar-mobile-open' : ''}`}>
      {/* Toggle button */}
      <button
        className="sidebar-toggle"
        onClick={() => setCollapsed(c => !c)}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <CollapseIcon flipped={collapsed} />
      </button>

      {/* Navigation */}
      <nav className="sidebar-nav" role="navigation" aria-label="Main navigation">
        {groups.map(group => {
          const items = NAV_ITEMS.filter(i => (i.group ?? '') === group)
            // Hide superadmin items unless the logged-in user IS the superadmin.
            .filter(i => i.id !== 'data-admin' || isSuperadmin)
          if (!items.length) return null
          return (
            <div key={group || '__root'} className="sidebar-group">
              {group && !collapsed && (
                <span className="sidebar-group-label">{group}</span>
              )}
              {items.map(item => (
                <button
                  key={item.id}
                  className={`sidebar-item ${isActive(item.path) ? 'sidebar-item-active' : ''} ${item.highlight ? 'sidebar-item-highlight' : ''}`}
                  onClick={() => handleNav(item)}
                  title={collapsed ? item.label : undefined}
                  aria-current={isActive(item.path) ? 'page' : undefined}
                >
                  <span className="sidebar-icon">{item.icon}</span>
                  {!collapsed && (
                    <>
                      <span className="sidebar-label">{item.label}</span>
                      {item.badge && <span className="sidebar-badge">{item.badge}</span>}
                    </>
                  )}
                  {collapsed && item.badge && (
                    <span className="sidebar-badge-dot" />
                  )}
                </button>
              ))}
            </div>
          )
        })}
      </nav>

      {/* Bottom: user / tier pill */}
      <div className="sidebar-footer">
        {user ? (
          <>
            {!collapsed && (
              <div className="sidebar-user">
                <div className="user-avatar">{user.display_name?.[0]?.toUpperCase() ?? user.email[0].toUpperCase()}</div>
                <div className="user-meta">
                  <span className="user-name">{user.display_name || user.email.split('@')[0]}</span>
                  <span className={`tier-pill tier-${tier}`}>
                    {tier === 'free' && trialDaysLeft !== null
                      ? `Trial · ${trialDaysLeft}d left`
                      : tier.charAt(0).toUpperCase() + tier.slice(1)
                    }
                    {user.trader_type === 'HNI' && (
                      <span style={{
                        marginLeft: 6,
                        padding: '1px 6px',
                        borderRadius: 'var(--radius-full)',
                        background: 'var(--accent-primary)',
                        color: '#fff',
                        fontSize: 9,
                        fontWeight: 700,
                        letterSpacing: '0.06em',
                      }}>HNI</span>
                    )}
                  </span>
                </div>
              </div>
            )}
            {collapsed && (
              <div className="user-avatar user-avatar-sm" title={user.email}>
                {user.display_name?.[0]?.toUpperCase() ?? user.email[0].toUpperCase()}
              </div>
            )}
            <button className="sidebar-logout" onClick={logout} title="Sign out">
              <LogoutIcon />
            </button>
          </>
        ) : (
          <button
            className="sidebar-signin-btn"
            onClick={() => openGate({ mode: 'login' })}
            title="Sign in"
          >
            <LoginIcon />
            {!collapsed && <span>Sign in</span>}
          </button>
        )}
      </div>
    </aside>
  )
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function AgentIcon()    { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/><path d="M12 12v2m0 0l-2 2m2-2l2 2" strokeWidth="1.5"/></svg> }
function ChartsIcon()   { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 3v18h18"/><polyline points="7 14 11 10 14 13 19 8"/></svg> }
function ChainIcon()    { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="8" height="8" rx="1"/><rect x="13" y="3" width="8" height="8" rx="1"/><rect x="3" y="13" width="8" height="8" rx="1"/><rect x="13" y="13" width="8" height="8" rx="1"/></svg> }
function PositionsIcon(){ return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg> }
function SavedIcon()    { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/></svg> }
function BacktestIcon() { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg> }
function CompareIcon()  { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6"  y1="20" x2="6"  y2="14"/></svg> }
function ScalpIcon()    { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg> }
function PortfolioIcon(){ return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/></svg> }
function OrderIcon()    { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg> }
function BrokersIcon()  { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/><line x1="12" y1="12" x2="12" y2="16"/><line x1="10" y1="14" x2="14" y2="14"/></svg> }
function SubIcon()      { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> }
function SettingsIcon() { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg> }
function RLIcon()       { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 2a10 10 0 100 20A10 10 0 0012 2z"/><path d="M12 6v6l4 2"/></svg> }
function JournalIcon()  { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 4a2 2 0 012-2h12a1 1 0 011 1v18a1 1 0 01-1 1H6a2 2 0 01-2-2z"/><path d="M4 18a2 2 0 012-2h13"/><line x1="8" y1="7" x2="15" y2="7"/><line x1="8" y1="11" x2="13" y2="11"/></svg> }
function TemplateIcon() { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg> }
function CatalogIcon()  { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 9l1.2-4.4A1 1 0 015.16 4h13.68a1 1 0 01.96.6L21 9"/><path d="M4 9v10a1 1 0 001 1h14a1 1 0 001-1V9"/><path d="M9 20v-6h6v6"/></svg> }
function BasketIcon()   { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg> }
function ActivityIcon() { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg> }
function LegalIcon()    { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><line x1="12" y1="3" x2="12" y2="21"/><line x1="7" y1="7" x2="17" y2="7"/><path d="M7 7l-3 6a3 3 0 006 0z"/><path d="M17 7l-3 6a3 3 0 006 0z"/></svg> }
function DataIcon()     { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5"/><path d="M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"/></svg> }
function LabIcon()      { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9 3h6"/><path d="M10 3v6l-4.5 8.5A2 2 0 007.3 21h9.4a2 2 0 001.8-3L14 9V3"/><line x1="8" y1="15" x2="16" y2="15"/></svg> }
function LogoutIcon()   { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg> }
function LoginIcon()    { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg> }
function CollapseIcon({ flipped }: { flipped: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
         style={{ transform: flipped ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s ease' }}>
      <polyline points="15 18 9 12 15 6"/>
    </svg>
  )
}

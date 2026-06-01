import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import Dashboard from './pages/Dashboard'
import Watchlists from './pages/Watchlists'
import Portfolios from './pages/Portfolios'
import Scalping from './pages/Scalping'
import Strategy from './pages/Strategy'
import Positions from './pages/Positions'
import Login from './pages/Login'
import Saved from './pages/Saved'
import Audit from './pages/Audit'
import Compare from './pages/Compare'
import Settings from './pages/Settings'
import CommandPalette from './CommandPalette'

type Status = { fyers: boolean; demo_mode: boolean; redis: boolean; postgres: boolean; last_snapshot_at: string | null; tracked_symbols: number }

const NAV = [
  { group: 'Trade', items: [
    { to: '/dashboard', label: 'Option Chain' },
    { to: '/strategy', label: 'Strategy Builder' },
    { to: '/compare', label: 'Compare Strategies' },
    { to: '/positions', label: 'Positions' },
    { to: '/scalping', label: 'Scalping' },
  ]},
  { group: 'Manage', items: [
    { to: '/watchlists', label: 'Watchlists' },
    { to: '/portfolios', label: 'Portfolios' },
    { to: '/saved', label: 'Saved Strategies' },
    { to: '/audit', label: 'Order Audit' },
  ]},
  { group: 'Account', items: [
    { to: '/login', label: 'Fyers Auth' },
    { to: '/settings', label: 'Settings' },
  ]},
]

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
      <span style={{ width: 8, height: 8, borderRadius: 4, background: ok ? 'var(--green)' : 'var(--red)' }} />
      {label}
    </span>
  )
}

export default function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => (localStorage.getItem('theme') as any) || 'dark')
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('theme', theme)
  }, [theme])

  const { data: status } = useQuery<Status>({
    queryKey: ['system-status'],
    queryFn: async () => (await api.get('/api/system/status')).data,
    refetchInterval: 10000,
  })

  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')

  return (
    <div className="app">
      <aside className="sidebar">
        <h1>Reyu</h1>
        {NAV.map(g => (
          <div key={g.group} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>{g.group}</div>
            <nav>
              {g.items.map(i => (
                <NavLink key={i.to} to={i.to} className={({ isActive }) => isActive ? 'active' : ''}>{i.label}</NavLink>
              ))}
            </nav>
          </div>
        ))}
        <div style={{ marginTop: 'auto', paddingTop: 12, borderTop: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 4 }}>
          <StatusDot ok={!!status?.fyers} label={status?.fyers ? 'Fyers connected' : 'DEMO MODE'} />
          <StatusDot ok={!!status?.redis} label="Redis" />
          <StatusDot ok={!!status?.postgres} label="Postgres" />
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>
            {status?.tracked_symbols ?? 0} tracked · {status?.last_snapshot_at ? new Date(status.last_snapshot_at).toLocaleTimeString() : '—'}
          </div>
          <button onClick={toggleTheme} style={{ marginTop: 6, fontSize: 11 }}>{theme === 'dark' ? '☼ Light' : '☾ Dark'}</button>
        </div>
      </aside>
      <main className="main">
        {status?.demo_mode && (
          <div style={{ padding: '6px 10px', background: 'rgba(245,158,11,0.15)', borderLeft: '3px solid var(--amber)', marginBottom: 12, fontSize: 12, borderRadius: 4 }}>
            <strong style={{ color: 'var(--amber)' }}>DEMO MODE</strong> — showing synthetic data. <a href="/login">Connect Fyers</a> to switch to live quotes, orders, and positions.
          </div>
        )}
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/strategy" element={<Strategy />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/watchlists" element={<Watchlists />} />
          <Route path="/portfolios" element={<Portfolios />} />
          <Route path="/scalping" element={<Scalping />} />
          <Route path="/saved" element={<Saved />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/settings" element={<Settings theme={theme} setTheme={setTheme} />} />
          <Route path="/login" element={<Login />} />
        </Routes>
      </main>
      <CommandPalette toggleTheme={toggleTheme} />
    </div>
  )
}

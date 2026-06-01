import { NavLink, Route, Routes, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Watchlists from './pages/Watchlists'
import Portfolios from './pages/Portfolios'
import Scalping from './pages/Scalping'
import Login from './pages/Login'

export default function App() {
  return (
    <div className="app">
      <aside className="sidebar">
        <h1>Reyu</h1>
        <nav>
          <NavLink to="/dashboard" className={({ isActive }) => isActive ? 'active' : ''}>Option Chain</NavLink>
          <NavLink to="/watchlists" className={({ isActive }) => isActive ? 'active' : ''}>Watchlists</NavLink>
          <NavLink to="/portfolios" className={({ isActive }) => isActive ? 'active' : ''}>Portfolios</NavLink>
          <NavLink to="/scalping" className={({ isActive }) => isActive ? 'active' : ''}>Scalping</NavLink>
          <NavLink to="/login" className={({ isActive }) => isActive ? 'active' : ''}>Fyers Auth</NavLink>
        </nav>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/watchlists" element={<Watchlists />} />
          <Route path="/portfolios" element={<Portfolios />} />
          <Route path="/scalping" element={<Scalping />} />
          <Route path="/login" element={<Login />} />
        </Routes>
      </main>
    </div>
  )
}

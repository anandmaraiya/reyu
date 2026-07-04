/**
 * Login / Register — standalone auth pages (/login, /register).
 *
 * The GateModal handles lazy in-context auth; these are the direct-navigation
 * pages so marketing links, bookmarks, and "Sign in" buttons resolve to real
 * URLs. Both routes render this component — the pathname sets the initial mode.
 *
 * Uses the AuthContext login/register actions (which write the canonical
 * reyu_* localStorage keys and update global state) — NOT raw localStorage.
 */
import { useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { useAuth, api } from '../context/AuthContext'
import { useToast } from '../toast'

export default function Login() {
  const t = useToast()
  const nav = useNavigate()
  const loc = useLocation()
  const { login, register, isAuthenticated } = useAuth()

  const initialMode: 'login' | 'register' =
    loc.pathname === '/register' ? 'register' : 'login'
  const [mode, setMode] = useState<'login' | 'register'>(initialMode)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Already signed in — nothing to do here.
  if (isAuthenticated) {
    nav('/', { replace: true })
    return null
  }

  const switchMode = (m: 'login' | 'register') => {
    setMode(m)
    setError('')
    // Keep the URL in sync so refresh/bookmark lands on the same tab.
    nav(m === 'register' ? '/register' : '/login', { replace: true })
  }

  const submit = async () => {
    setError('')
    if (!email.trim() || !password.trim()) {
      setError('Email and password are required.')
      return
    }
    if (mode === 'register' && password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    setLoading(true)
    try {
      if (mode === 'login') {
        await login(email.trim(), password)
        t.push('success', 'Welcome back!')
      } else {
        await register(email.trim(), password, name.trim())
        t.push('success', 'Account created — welcome to Reyu!')
      }
      // New accounts land on onboarding; returning users go home.
      nav(mode === 'register' ? '/onboarding' : '/', { replace: true })
    } catch (e: any) {
      const msg =
        e?.response?.data?.detail?.message ||
        e?.response?.data?.detail ||
        e?.message ||
        'Something went wrong. Please try again.'
      setError(typeof msg === 'string' ? msg : 'Authentication failed.')
    } finally {
      setLoading(false)
    }
  }

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '10px 12px', borderRadius: 8,
    border: '1px solid var(--border)', background: 'var(--panel, var(--card2))',
    color: 'var(--text)', fontSize: 14,
  }

  return (
    <div style={{ maxWidth: 420, margin: '48px auto', padding: '0 16px' }}>
      <div className="card" style={{ padding: 28, background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 14 }}>
        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 24, background: 'var(--border)', borderRadius: 999, padding: 3 }}>
          <button
            onClick={() => switchMode('login')}
            className={mode === 'login' ? 'primary' : 'ghost'}
            style={{ flex: 1, padding: '8px 0', borderRadius: 999, cursor: 'pointer' }}
          >Sign In</button>
          <button
            onClick={() => switchMode('register')}
            className={mode === 'register' ? 'primary' : 'ghost'}
            style={{ flex: 1, padding: '8px 0', borderRadius: 999, cursor: 'pointer' }}
          >Register</button>
        </div>

        <h2 style={{ margin: '0 0 4px', fontSize: 22 }}>
          {mode === 'login' ? 'Welcome back' : 'Create your account'}
        </h2>
        <p style={{ color: 'var(--muted)', fontSize: 13, margin: '0 0 20px' }}>
          {mode === 'login'
            ? 'Sign in to build, test, and paper-trade your own strategies.'
            : '15-day free trial. No card needed. Nothing trades until you start it.'}
        </p>

        {error && (
          <div style={{ background: 'rgba(224,82,82,0.12)', color: 'var(--danger, #e05252)', padding: '8px 12px', borderRadius: 8, fontSize: 13, marginBottom: 14 }}>
            {error}
          </div>
        )}

        {mode === 'register' && (
          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Display name</label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="Your name"
              autoComplete="name" style={inputStyle} />
          </div>
        )}

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Email</label>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)}
            placeholder="you@example.com" autoComplete="email" style={inputStyle}
            onKeyDown={e => e.key === 'Enter' && submit()} />
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Password</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder="••••••••" autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            onKeyDown={e => e.key === 'Enter' && submit()} style={inputStyle} />
          {mode === 'login' && (
            <div style={{ textAlign: 'right', marginTop: 6 }}>
              <Link to="/reset-password" style={{ fontSize: 12, color: 'var(--accent, var(--brand-primary))' }}>Forgot password?</Link>
            </div>
          )}
        </div>

        <button className="primary" onClick={submit} disabled={loading}
          style={{ width: '100%', padding: 12, fontSize: 15, opacity: loading ? 0.7 : 1, cursor: loading ? 'default' : 'pointer' }}>
          {loading ? 'Please wait…' : mode === 'login' ? 'Sign In' : 'Create Account'}
        </button>

        <div style={{ marginTop: 16, textAlign: 'center', fontSize: 12, color: 'var(--muted)' }}>
          {mode === 'login' ? (
            <>New to Reyu? <button onClick={() => switchMode('register')} style={{ color: 'var(--accent, var(--brand-primary))', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12 }}>Create an account</button></>
          ) : (
            <>Already have an account? <button onClick={() => switchMode('login')} style={{ color: 'var(--accent, var(--brand-primary))', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12 }}>Sign in</button></>
          )}
        </div>

        {mode === 'register' && (
          <p style={{ marginTop: 14, fontSize: 11, color: 'var(--muted)', textAlign: 'center', lineHeight: 1.5 }}>
            By creating an account you agree to review and accept our{' '}
            <Link to="/legal" style={{ color: 'var(--accent, var(--brand-primary))' }}>Terms, Risk Disclosure & Privacy Policy</Link>{' '}
            before any live execution. Derivatives trading is high-risk.
          </p>
        )}

        {/* Fyers OAuth link */}
        <div style={{ marginTop: 20, borderTop: '1px solid var(--border)', paddingTop: 16, textAlign: 'center' }}>
          <p style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>Or connect your Fyers trading account</p>
          <button type="button" className="ghost" style={{ display: 'inline-block', padding: '8px 16px', fontSize: 13, cursor: 'pointer' }}
            onClick={async () => {
              try {
                const { data } = await api.get('/api/auth/login')
                if (data?.login_url) window.location.href = data.login_url
                else t.push('error', 'Backend did not return a Fyers login URL — is FYERS_APP_ID set?')
              } catch (e: any) {
                t.push('error', e.response?.data?.detail || e.message)
              }
            }}>
            🔗 Connect Fyers
          </button>
        </div>
      </div>
    </div>
  )
}

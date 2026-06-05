import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { api } from '../api'
import { useToast } from '../toast'

export default function Login() {
  const t = useToast()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setError('')
    if (!email.trim() || !password.trim()) {
      setError('Email and password are required.')
      return
    }
    setLoading(true)
    try {
      const endpoint = mode === 'login' ? '/api/user/login' : '/api/user/register'
      const body = mode === 'login'
        ? { email: email.trim(), password }
        : { email: email.trim(), password, display_name: name.trim() }
      const { data } = await api.post(endpoint, body)

      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      localStorage.setItem('user', JSON.stringify(data.user))

      t.push('success', mode === 'login' ? `Welcome back, ${data.user.display_name}!` : `Account created — welcome, ${data.user.display_name}!`)
      navigate('/dashboard')
    } catch (e: any) {
      const msg = e.response?.data?.detail || e.message
      setError(msg)
      t.push('error', msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page-shell" style={{ maxWidth: 420, margin: '60px auto' }}>
      <div className="card" style={{ padding: 28 }}>
        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 24, background: 'var(--border)', borderRadius: 999, padding: 3 }}>
          <button
            onClick={() => { setMode('login'); setError('') }}
            className={mode === 'login' ? 'primary' : 'ghost'}
            style={{ flex: 1, padding: '8px 0', borderRadius: 999 }}
          >Sign In</button>
          <button
            onClick={() => { setMode('register'); setError('') }}
            className={mode === 'register' ? 'primary' : 'ghost'}
            style={{ flex: 1, padding: '8px 0', borderRadius: 999 }}
          >Register</button>
        </div>

        <h2 style={{ margin: '0 0 4px', fontSize: 22 }}>
          {mode === 'login' ? 'Welcome back' : 'Create your account'}
        </h2>
        <p style={{ color: 'var(--muted)', fontSize: 13, margin: '0 0 20px' }}>
          {mode === 'login'
            ? 'Sign in to access your watchlists, strategies, and live data.'
            : 'Start with a free tier — upgrade anytime for live data and advanced tools.'}
        </p>

        {error && (
          <div style={{ background: 'rgba(239,68,68,0.12)', color: 'var(--red)', padding: '8px 12px', borderRadius: 8, fontSize: 13, marginBottom: 14 }}>
            {error}
          </div>
        )}

        {mode === 'register' && (
          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Display name</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Your name"
              style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--panel)', color: 'var(--text)', fontSize: 14 }}
            />
          </div>
        )}

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Email</label>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@example.com"
            autoComplete="email"
            style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--panel)', color: 'var(--text)', fontSize: 14 }}
          />
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Password</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            onKeyDown={e => e.key === 'Enter' && submit()}
            style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--panel)', color: 'var(--text)', fontSize: 14 }}
          />
        </div>

        <button
          className="primary"
          onClick={submit}
          disabled={loading}
          style={{ width: '100%', padding: 12, fontSize: 15, opacity: loading ? 0.7 : 1 }}
        >
          {loading ? 'Please wait…' : mode === 'login' ? 'Sign In' : 'Create Account'}
        </button>

        <div style={{ marginTop: 16, textAlign: 'center', fontSize: 12, color: 'var(--muted)' }}>
          {mode === 'login' ? (
            <>New to Reyu.ai? <button onClick={() => { setMode('register'); setError('') }} style={{ color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12 }}>Create an account</button></>
          ) : (
            <>Already have an account? <button onClick={() => { setMode('login'); setError('') }} style={{ color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12 }}>Sign in</button></>
          )}
        </div>

        {/* Fyers OAuth link */}
        <div style={{ marginTop: 20, borderTop: '1px solid var(--border)', paddingTop: 16, textAlign: 'center' }}>
          <p style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>Or connect with your Fyers trading account</p>
          <button
            type="button"
            className="ghost"
            style={{ display: 'inline-block', padding: '8px 16px', fontSize: 13 }}
            onClick={async () => {
              try {
                const { data } = await api.get('/api/auth/login')
                if (data?.login_url) {
                  window.location.href = data.login_url
                } else {
                  t.push('error', 'Backend did not return a Fyers login URL — is FYERS_APP_ID set?')
                }
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

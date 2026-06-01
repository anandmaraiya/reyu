import { useEffect, useState } from 'react'
import { api } from '../api'

export default function Login() {
  const [status, setStatus] = useState<boolean | null>(null)

  useEffect(() => { api.get('/api/auth/status').then(r => setStatus(r.data.authenticated)) }, [])

  const startLogin = async () => {
    const r = await api.get('/api/auth/login')
    window.location.href = r.data.login_url
  }
  const logout = async () => { await api.post('/api/auth/logout'); setStatus(false) }

  return (
    <div className="card" style={{ maxWidth: 500 }}>
      <h3>Fyers Authentication</h3>
      <p>Status: <span className={status ? 'bull' : 'bear'}>{status ? 'Connected' : 'Not connected'}</span></p>
      {!status && <button className="primary" onClick={startLogin}>Login with Fyers</button>}
      {status && <button onClick={logout}>Logout</button>}
      <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 12 }}>
        Set FYERS_APP_ID / FYERS_SECRET_KEY / FYERS_REDIRECT_URI in <code>.env</code> before logging in.
      </p>
    </div>
  )
}

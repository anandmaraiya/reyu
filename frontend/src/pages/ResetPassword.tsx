/**
 * Reset Password — landing page from the emailed reset link.
 *
 * URL: /reset-password?token=<32-byte-urlsafe-token>
 *
 * Flow:
 *   1. Extract token from query string
 *   2. User types new password + confirm
 *   3. POST /api/user/reset-password { token, new_password }
 *   4. On success, show "Log in" CTA; token is single-use
 */
import { useState, useEffect, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { track, Events } from '../telemetry'

const S = {
  page: {
    minHeight: '100vh',
    background: 'var(--bg-base)',
    display: 'grid',
    placeItems: 'center',
    padding: 20,
  } as CSSProperties,
  card: {
    width: '100%',
    maxWidth: 420,
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-md)',
    padding: 32,
    boxShadow: 'var(--shadow-md)',
  } as CSSProperties,
  title: {
    fontSize: 20,
    fontWeight: 600,
    margin: '0 0 8px 0',
    color: 'var(--text-primary)',
  } as CSSProperties,
  hint: {
    color: 'var(--text-secondary)',
    fontSize: 13,
    marginBottom: 20,
  } as CSSProperties,
  label: {
    display: 'block',
    color: 'var(--text-secondary)',
    fontSize: 12,
    marginBottom: 6,
    marginTop: 12,
    fontWeight: 500,
  } as CSSProperties,
  input: {
    width: '100%',
    padding: '10px 12px',
    fontSize: 14,
    background: 'var(--bg-elevated)',
    color: 'var(--text-primary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
    outline: 'none',
  } as CSSProperties,
  btn: {
    width: '100%',
    marginTop: 20,
    padding: '10px 16px',
    fontSize: 14,
    fontWeight: 600,
    background: 'var(--brand-primary)',
    color: '#fff',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
  } as CSSProperties,
  btnDisabled: { opacity: 0.55, cursor: 'not-allowed' } as CSSProperties,
  err: {
    marginTop: 14,
    padding: 10,
    background: 'var(--danger-light)',
    color: 'var(--danger-text)',
    fontSize: 13,
    borderRadius: 'var(--radius-sm)',
  } as CSSProperties,
  ok: {
    marginTop: 14,
    padding: 10,
    background: 'var(--brand-light)',
    color: 'var(--brand-text)',
    fontSize: 13,
    borderRadius: 'var(--radius-sm)',
  } as CSSProperties,
}

export default function ResetPassword() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const token = params.get('token') || ''
  const [pw, setPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!token) {
      setStatus('error')
      setMessage('This reset link is missing its token. Request a new one from the login screen.')
    }
  }, [token])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (pw.length < 8) {
      setStatus('error'); setMessage('Password must be at least 8 characters.'); return
    }
    if (pw !== confirm) {
      setStatus('error'); setMessage('Passwords do not match.'); return
    }
    setStatus('loading'); setMessage(null)
    try {
      await api.post('/api/user/reset-password', { token, new_password: pw })
      track(Events.PasswordReset)
      setStatus('success')
      setMessage('Password updated. Redirecting to login…')
      setTimeout(() => nav('/'), 2000)
    } catch (err: any) {
      setStatus('error')
      setMessage(err?.response?.data?.detail || 'Reset failed. The link may have expired.')
    }
  }

  return (
    <div style={S.page}>
      <div style={S.card}>
        <h1 style={S.title}>Choose a new password</h1>
        <p style={S.hint}>
          Set a strong password (8+ characters). This link expires 30 minutes after it was sent.
        </p>

        <form onSubmit={submit}>
          <label style={S.label}>New password</label>
          <input
            type="password"
            style={S.input}
            value={pw}
            onChange={e => setPw(e.target.value)}
            disabled={status === 'loading' || status === 'success' || !token}
            autoComplete="new-password"
          />
          <label style={S.label}>Confirm password</label>
          <input
            type="password"
            style={S.input}
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
            disabled={status === 'loading' || status === 'success' || !token}
            autoComplete="new-password"
          />
          <button
            type="submit"
            style={{ ...S.btn, ...((status === 'loading' || !token) ? S.btnDisabled : {}) }}
            disabled={status === 'loading' || !token}
          >
            {status === 'loading' ? 'Updating…' : 'Update password'}
          </button>
        </form>

        {message && status === 'error' && <div style={S.err}>{message}</div>}
        {message && status === 'success' && <div style={S.ok}>{message}</div>}
      </div>
    </div>
  )
}

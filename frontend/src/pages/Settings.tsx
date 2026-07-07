import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useToast } from '../toast'
import { useAuth } from '../context/AuthContext'
import { istDateTime, istDate, istTime } from '../marketHours'

type Tab = 'account' | 'trading' | 'notify' | 'api_keys' | 'event_subs' | 'appearance' | 'shortcuts'

const TABS: { id: Tab; label: string }[] = [
  { id: 'account', label: 'Account' },
  { id: 'trading', label: 'Trading' },
  { id: 'notify', label: 'Notifications' },
  { id: 'api_keys', label: 'API Keys' },
  { id: 'event_subs', label: 'Event Subscriptions' },
  { id: 'appearance', label: 'Appearance' },
  { id: 'shortcuts', label: 'Shortcuts' },
]

const RISK_KEY = 'reyu_risk_prefs'

type RiskPrefs = {
  max_delta: number
  max_vega: number
  capital_pct: number
  default_product: 'INTRADAY' | 'CNC' | 'MARGIN'
  default_validity: 'DAY' | 'IOC'
  dry_run_default: boolean
  refresh_ms: number
}

const DEFAULT_RISK: RiskPrefs = {
  max_delta: 500, max_vega: 2000, capital_pct: 5,
  default_product: 'INTRADAY', default_validity: 'DAY',
  dry_run_default: true, refresh_ms: 15000,
}

export default function Settings({ theme, setTheme }: { theme: string; setTheme: (t: 'dark' | 'light') => void }) {
  const t = useToast()
  const { user: currentUser, logout } = useAuth()
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('account')
  const [url, setUrl] = useState('')
  const [risk, setRisk] = useState<RiskPrefs>(() => {
    try { return { ...DEFAULT_RISK, ...JSON.parse(localStorage.getItem(RISK_KEY) || '{}') } }
    catch { return DEFAULT_RISK }
  })

  // Password change state
  const [pwCurrent, setPwCurrent] = useState('')
  const [pwNew, setPwNew] = useState('')
  const [pwConfirm, setPwConfirm] = useState('')
  const [pwBusy, setPwBusy] = useState(false)

  const changePassword = async () => {
    if (pwNew.length < 8) { t.push('error', 'New password must be ≥ 8 characters'); return }
    if (pwNew !== pwConfirm) { t.push('error', 'Passwords do not match'); return }
    setPwBusy(true)
    try {
      await api.post('/api/user/change-password', { current_password: pwCurrent, new_password: pwNew })
      t.push('success', 'Password changed — please log in again on other devices')
      setPwCurrent(''); setPwNew(''); setPwConfirm('')
    } catch (e: any) {
      t.push('error', e.response?.data?.detail || 'Failed to change password')
    } finally { setPwBusy(false) }
  }

  const reAuthFyers = async () => {
    try {
      const { data } = await api.get('/api/auth/login')
      if (data.login_url) window.location.href = data.login_url
    } catch {
      t.push('error', 'Could not get Fyers login URL — is the backend running?')
    }
  }

  const { data: status } = useQuery<any>({
    queryKey: ['system-status'],
    queryFn: async () => (await api.get('/api/system/status')).data,
  })
  const { data: hooks } = useQuery<{ hooks: string[] }>({
    queryKey: ['hooks'],
    queryFn: async () => (await api.get('/api/notify')).data,
  })

  const addHook = async () => {
    if (!url) return
    await api.post('/api/notify', { url }); setUrl('')
    qc.invalidateQueries({ queryKey: ['hooks'] })
    t.push('success', 'Webhook added')
  }
  const removeHook = async (u: string) => {
    await api.delete('/api/notify', { data: { url: u } })
    qc.invalidateQueries({ queryKey: ['hooks'] })
  }
  const test = async () => { await api.post('/api/notify/test'); t.push('info', 'Test ping sent to all webhooks') }

  const saveRisk = (next: RiskPrefs) => {
    setRisk(next)
    localStorage.setItem(RISK_KEY, JSON.stringify(next))
    t.push('success', 'Trading preferences saved')
  }

  const tierLabel = currentUser?.tier
    ? currentUser.tier.charAt(0).toUpperCase() + currentUser.tier.slice(1)
    : 'Free'

  return (
    <div className="page-shell">
      <div className="row" style={{ gap: 12, alignItems: 'flex-start' }}>
        {/* Tab rail */}
        <aside className="card" style={{ minWidth: 180, padding: 8 }}>
          {TABS.map(item => (
            <button key={item.id}
                    className={tab === item.id ? 'primary' : 'ghost'}
                    onClick={() => setTab(item.id)}
                    style={{ width: '100%', justifyContent: 'flex-start', padding: '8px 12px', marginBottom: 4 }}>
              {item.label}
            </button>
          ))}
        </aside>

        {/* Tab body */}
        <section className="col" style={{ flex: 1, minWidth: 0 }}>
          {tab === 'account' && (
            <div className="col" style={{ gap: 16, maxWidth: 640 }}>
              {/* User info + logout */}
              {currentUser && (
                <div className="card">
                  <div className="row" style={{ alignItems: 'center', justifyContent: 'space-between' }}>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 15 }}>{currentUser.display_name || currentUser.email}</div>
                      <div style={{ fontSize: 12, color: 'var(--muted)' }}>{currentUser.email}</div>
                    </div>
                    <button
                      onClick={() => { logout(); window.location.href = '/' }}
                      style={{ background: 'rgba(239,68,68,0.12)', color: 'var(--red)', border: '1px solid var(--red)', borderRadius: 6, padding: '6px 16px', cursor: 'pointer', fontWeight: 600 }}>
                      Sign Out
                    </button>
                  </div>
                </div>
              )}

              {/* System status card */}
              <div className="card">
                <h3>Account & Connectivity</h3>
                <table>
                  <tbody>
                    <tr><td>Fyers</td><td className={status?.fyers ? 'bull' : 'bear'}>{status?.fyers ? 'connected (live)' : 'demo mode'}</td></tr>
                    <tr><td>Redis</td><td className={status?.redis ? 'bull' : 'bear'}>{status?.redis ? 'ok' : 'down'}</td></tr>
                    <tr><td>Postgres</td><td className={status?.postgres ? 'bull' : 'bear'}>{status?.postgres ? 'ok' : 'down'}</td></tr>
                    <tr><td>Last snapshot</td><td>{status?.last_snapshot_at ? istDateTime(status.last_snapshot_at) : '—'}</td></tr>
                    <tr><td>Tracked symbols</td><td>{status?.tracked_symbols ?? 0}</td></tr>
                    <tr><td>Subscription</td><td><span className="tag" style={{ background: 'rgba(96,165,250,.15)', color: 'var(--accent)' }}>{tierLabel}</span></td></tr>
                  </tbody>
                </table>
                <div className="row" style={{ marginTop: 12, gap: 8 }}>
                  <button className="primary" onClick={reAuthFyers}>Re-authenticate Fyers</button>
                  <a className="ghost" href="/subscription" style={{ padding: '6px 12px', textDecoration: 'none' }}>Manage subscription</a>
                  {!currentUser && (
                    <a className="primary" href="/login" style={{ padding: '6px 12px', textDecoration: 'none' }}>Sign In / Register</a>
                  )}
                </div>
              </div>

              {/* Password change card */}
              {currentUser && (
                <div className="card">
                  <h3>Change Password</h3>
                  <div className="col" style={{ gap: 10 }}>
                    <div className="row" style={{ alignItems: 'center', gap: 8 }}>
                      <label style={{ minWidth: 160 }}>Current password</label>
                      <input className="input" type="password" value={pwCurrent}
                             onChange={e => setPwCurrent(e.target.value)}
                             placeholder="••••••••" style={{ flex: 1 }} />
                    </div>
                    <div className="row" style={{ alignItems: 'center', gap: 8 }}>
                      <label style={{ minWidth: 160 }}>New password</label>
                      <input className="input" type="password" value={pwNew}
                             onChange={e => setPwNew(e.target.value)}
                             placeholder="Min 8 characters" style={{ flex: 1 }} />
                    </div>
                    <div className="row" style={{ alignItems: 'center', gap: 8 }}>
                      <label style={{ minWidth: 160 }}>Confirm new password</label>
                      <input className="input" type="password" value={pwConfirm}
                             onChange={e => setPwConfirm(e.target.value)}
                             placeholder="Repeat password" style={{ flex: 1 }}
                             onKeyDown={e => { if (e.key === 'Enter') changePassword() }} />
                    </div>
                    <div style={{ marginTop: 4 }}>
                      <button className="primary" onClick={changePassword}
                              disabled={pwBusy || !pwCurrent || !pwNew || !pwConfirm}>
                        {pwBusy ? 'Saving…' : 'Update password'}
                      </button>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                      Changing your password will invalidate existing sessions on all other devices.
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === 'trading' && (
            <div className="card" style={{ maxWidth: 640 }}>
              <h3>Trading defaults & risk limits</h3>
              <div className="row" style={{ marginBottom: 8, alignItems: 'center' }}>
                <label style={{ minWidth: 200 }}>Default product</label>
                <select value={risk.default_product} onChange={e => saveRisk({ ...risk, default_product: e.target.value as any })}>
                  <option>INTRADAY</option><option>CNC</option><option>MARGIN</option>
                </select>
              </div>
              <div className="row" style={{ marginBottom: 8, alignItems: 'center' }}>
                <label style={{ minWidth: 200 }}>Default validity</label>
                <select value={risk.default_validity} onChange={e => saveRisk({ ...risk, default_validity: e.target.value as any })}>
                  <option>DAY</option><option>IOC</option>
                </select>
              </div>
              <div className="row" style={{ marginBottom: 8, alignItems: 'center' }}>
                <label style={{ minWidth: 200 }}>Dry-run by default</label>
                <input type="checkbox" checked={risk.dry_run_default}
                       onChange={e => saveRisk({ ...risk, dry_run_default: e.target.checked })} />
              </div>
              <div className="row" style={{ marginBottom: 8, alignItems: 'center' }}>
                <label style={{ minWidth: 200 }}>Max Δ per portfolio</label>
                <input className="input" type="number" value={risk.max_delta}
                       onChange={e => saveRisk({ ...risk, max_delta: +e.target.value })} style={{ width: 120 }} />
              </div>
              <div className="row" style={{ marginBottom: 8, alignItems: 'center' }}>
                <label style={{ minWidth: 200 }}>Max Vega per portfolio</label>
                <input className="input" type="number" value={risk.max_vega}
                       onChange={e => saveRisk({ ...risk, max_vega: +e.target.value })} style={{ width: 120 }} />
              </div>
              <div className="row" style={{ marginBottom: 8, alignItems: 'center' }}>
                <label style={{ minWidth: 200 }}>Capital % per trade</label>
                <input className="input" type="number" min={0.5} max={50} step={0.5} value={risk.capital_pct}
                       onChange={e => saveRisk({ ...risk, capital_pct: +e.target.value })} style={{ width: 120 }} />
              </div>
              <div className="row" style={{ marginBottom: 8, alignItems: 'center' }}>
                <label style={{ minWidth: 200 }}>Live data refresh (ms)</label>
                <input className="input" type="number" min={5000} step={1000} value={risk.refresh_ms}
                       onChange={e => saveRisk({ ...risk, refresh_ms: +e.target.value })} style={{ width: 120 }} />
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>
                These values are saved locally and respected by the order modal and portfolio guard.
              </div>
            </div>
          )}

          {tab === 'notify' && (
            <div className="card" style={{ maxWidth: 640 }}>
              <h3>Notifications — Telegram / Discord / generic</h3>
              <div className="row" style={{ marginBottom: 8 }}>
                <input className="input" value={url} onChange={e => setUrl(e.target.value)}
                       placeholder="https://discord.com/api/webhooks/… or https://api.telegram.org/bot…/sendMessage"
                       style={{ flex: 1 }} />
                <button className="primary" onClick={addHook}>Add</button>
                <button onClick={test}>Send test</button>
              </div>
              {hooks?.hooks?.length === 0 && <div style={{ color: 'var(--muted)', fontSize: 12 }}>No webhooks configured.</div>}
              {hooks?.hooks?.map(h => (
                <div key={h} style={{ display: 'flex', alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{h}</span>
                  <button onClick={() => removeHook(h)}>×</button>
                </div>
              ))}
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>
                Events emitted: BATCH_ORDER, EXIT_POSITIONS, KILL_SWITCH, BIAS_FLIP.
              </div>
              <hr style={{ border: 0, borderTop: '1px solid var(--border)', margin: '14px 0' }} />
              <TelegramLinkPanel toast={t} />
            </div>
          )}

          {tab === 'api_keys' && <ApiKeysPanel toast={t} />}

          {tab === 'event_subs' && <EventSubsPanel toast={t} />}

          {tab === 'appearance' && (
            <div className="card" style={{ maxWidth: 640 }}>
              <h3>Appearance</h3>
              <div className="row" style={{ alignItems: 'center', marginBottom: 8 }}>
                <label style={{ minWidth: 120 }}>Theme</label>
                <select value={theme} onChange={e => setTheme(e.target.value as any)}>
                  <option value="dark">Dark</option><option value="light">Light</option>
                </select>
                <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 8 }}>Shift+T toggles anywhere</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                Theme preference is stored in localStorage and follows you across reloads.
              </div>
            </div>
          )}

          {tab === 'shortcuts' && (
            <div className="card" style={{ maxWidth: 640 }}>
              <h3>Keyboard shortcuts</h3>
              <table style={{ fontSize: 12 }}>
                <tbody>
                  <tr><td>⌘K / Ctrl+K</td><td>command palette</td></tr>
                  <tr><td>Shift+T</td><td>toggle theme</td></tr>
                  <tr><td>Esc</td><td>close modal / palette</td></tr>
                  <tr><td>g d</td><td>Dashboard</td></tr>
                  <tr><td>g s</td><td>Strategy Builder</td></tr>
                  <tr><td>g c</td><td>Compare</td></tr>
                  <tr><td>g p</td><td>Positions</td></tr>
                  <tr><td>g w</td><td>Watchlists</td></tr>
                  <tr><td>g f</td><td>Portfolios</td></tr>
                  <tr><td>g v</td><td>Saved</td></tr>
                  <tr><td>g a</td><td>Audit</td></tr>
                  <tr><td>g ,</td><td>Settings</td></tr>
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}


type ApiKey = { id: number; label: string; key_preview: string; rate_limit_daily: number; created_at: string; last_used: string | null }

function ApiKeysPanel({ toast }: { toast: any }) {
  const qc = useQueryClient()
  const { data } = useQuery<{ keys: ApiKey[] }>({
    queryKey: ['api-keys'],
    queryFn: async () => (await api.get('/api/user/api-keys')).data,
  })
  const keys = data?.keys ?? []
  const [label, setLabel] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)

  const create = async () => {
    if (!label.trim()) return
    try {
      const { data } = await api.post('/api/user/api-keys', { name: label.trim() })
      setNewKey(data.key)
      setLabel('')
      qc.invalidateQueries({ queryKey: ['api-keys'] })
      toast.push('success', 'API key created — copy it now, you won\'t see the full value again.')
    } catch (e: any) {
      toast.push('error', e.response?.data?.detail || e.message)
    }
  }
  const revoke = async (id: number) => {
    if (!confirm('Revoke this API key? Any service using it will start failing immediately.')) return
    await api.delete(`/api/user/api-keys/${id}`)
    qc.invalidateQueries({ queryKey: ['api-keys'] })
    toast.push('info', 'API key revoked')
  }

  const formatLimit = (n: number) => n === 0 ? 'Unlimited' : n.toLocaleString() + '/day'

  return (
    <div className="card" style={{ maxWidth: 720 }}>
      <h3>API Keys</h3>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 12 }}>
        Use these to call <code>/api/data/*</code> endpoints programmatically. Send the key as
        <code> X-API-Key: &lt;key&gt; </code> header. Rate limits are enforced per day (UTC midnight reset).
      </p>

      {newKey && (
        <div style={{ background: 'rgba(99,220,210,0.12)', border: '1px solid var(--accent-border)', padding: 10, borderRadius: 8, marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: .5, marginBottom: 4 }}>
            Copy this now — you won't see it again
          </div>
          <code style={{ display: 'block', fontFamily: 'JetBrains Mono, monospace', fontSize: 12, wordBreak: 'break-all' }}>{newKey}</code>
          <div style={{ marginTop: 6 }}>
            <button onClick={() => { navigator.clipboard.writeText(newKey); toast.push('info', 'Copied to clipboard') }}>Copy</button>
            <button onClick={() => setNewKey(null)} style={{ marginLeft: 6 }}>Dismiss</button>
          </div>
        </div>
      )}

      <div className="row" style={{ marginBottom: 12 }}>
        <input className="input" placeholder="Label (e.g. trading-bot, mobile-app)" value={label}
               onChange={e => setLabel(e.target.value)} style={{ flex: 1 }} />
        <button className="primary" onClick={create} disabled={!label.trim()}>Create key</button>
      </div>

      {keys.length === 0 && (
        <div style={{ color: 'var(--muted)', fontSize: 12 }}>No API keys yet. Create one above.</div>
      )}
      {keys.map(k => (
        <div key={k.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{k.label}</div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                <code>{k.key_preview}</code> · created {istDate(k.created_at)}
                {k.last_used && ` · last used ${istDateTime(k.last_used)}`}
              </div>
            </div>
            <div style={{ textAlign: 'right', marginRight: 8 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Rate limit</div>
              <div style={{ fontSize: 12, fontWeight: 600 }}>{formatLimit(k.rate_limit_daily)}</div>
            </div>
            <button onClick={() => revoke(k.id)} style={{ background: 'var(--red)', color: '#fff', borderColor: 'transparent' }}>Revoke</button>
          </div>
          <ApiKeyUsageRow keyId={String(k.id)} />
        </div>
      ))}

      <div style={{ marginTop: 16, padding: 10, background: 'rgba(96,165,250,0.06)', borderRadius: 8 }}>
        <h4 style={{ margin: '0 0 6px', fontSize: 13 }}>Quick start</h4>
        <pre style={{ fontSize: 11, margin: 0, whiteSpace: 'pre-wrap', color: 'var(--muted)' }}>{`curl -H "X-API-Key: reyu_<your-key>" \\
  "http://localhost:8000/api/data/chain?symbol=NSE:NIFTY50-INDEX&strikecount=15"`}</pre>
      </div>
    </div>
  )
}

function ApiKeyUsageRow({ keyId }: { keyId: string }) {
  const { data: usage } = useQuery({
    queryKey: ['api-usage', keyId],
    queryFn: async () => (await api.get(`/api/user/api-keys/${keyId}/usage`)).data,
    enabled: !!keyId,
  })

  if (!usage) return null

  const pct = usage.limit > 0 ? Math.min(100, Math.round((usage.used / usage.limit) * 100)) : 0
  const barColor = pct > 90 ? 'var(--red)' : pct > 70 ? 'var(--yellow)' : 'var(--accent)'

  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--muted)' }}>
        <span>{usage.used.toLocaleString()} / {usage.limit > 0 ? usage.limit.toLocaleString() : '∞'} requests today</span>
        <span>Resets {istTime(usage.reset_at * 1000)}</span>
      </div>
      <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, marginTop: 2 }}>
        <div style={{ width: `${pct}%`, height: '100%', background: barColor, borderRadius: 2, transition: 'width .3s' }} />
      </div>
    </div>
  )
}


function TelegramLinkPanel({ toast }: { toast: any }) {
  const [code, setCode] = useState<string | null>(null)
  const [botUser, setBotUser] = useState<string>('reyu_ai_bot')
  const [expires, setExpires] = useState<number>(0)
  const [tick, setTick] = useState(0)

  // Countdown
  useEffect(() => {
    if (!expires) return
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [expires])

  const remaining = code ? Math.max(0, expires - Math.floor(Date.now() / 1000)) : 0

  const start = async () => {
    try {
      const { data } = await api.post('/api/telegram/link/start')
      setCode(data.code)
      setBotUser(data.bot_username || 'reyu_ai_bot')
      setExpires(Math.floor(Date.now() / 1000) + (data.expires_in || 600))
      toast.push('info', 'Code generated — send /link to the bot within 10 minutes.')
    } catch (e: any) {
      toast.push('error', e.response?.data?.detail || e.message)
    }
  }
  const unlink = async () => {
    if (!confirm('Unlink Telegram? You won\'t receive bot replies until you re-link.')) return
    await api.post('/api/telegram/link/unlink')
    setCode(null); setExpires(0)
    toast.push('info', 'Telegram unlinked.')
  }

  return (
    <div>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>Telegram Bot</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
        Get the same conversational analytics in your Telegram. Open
        <a href={`https://t.me/${botUser}`} target="_blank" rel="noreferrer"
           style={{ marginLeft: 4, color: 'var(--accent)' }}>@{botUser}</a>,
        send <code>/start</code>, then <code>/link &lt;code&gt;</code> with the 6-digit code below.
      </div>
      {code ? (
        <div style={{ background: 'rgba(99,220,210,0.12)', border: '1px solid var(--accent-border, var(--border))', padding: 10, borderRadius: 8, marginBottom: 8 }}>
          <div style={{ fontSize: 11, color: 'var(--accent)', letterSpacing: 1, textTransform: 'uppercase' }}>Your link code</div>
          <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 26, fontWeight: 700, letterSpacing: 2 }}>{code}</div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>
            expires in {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, '0')} · in Telegram send <code>/link {code}</code>
          </div>
        </div>
      ) : null}
      <div className="row" style={{ gap: 6 }}>
        <button className="primary" onClick={start}>{code ? 'Regenerate code' : 'Generate link code'}</button>
        <button onClick={unlink} className="ghost">Unlink</button>
      </div>
    </div>
  )
}

type EventSub = { event_type: string; url: string; created_at: string }

function EventSubsPanel({ toast }: { toast: any }) {
  const qc = useQueryClient()
  const [eventType, setEventType] = useState('PCR_THRESHOLD')
  const [url, setUrl] = useState('')

  const { data: events } = useQuery<{ events: string[] }>({
    queryKey: ['webhook-events'],
    queryFn: async () => (await api.get('/api/webhooks/events')).data,
  })

  const { data: subs } = useQuery<{ subscriptions: EventSub[] }>({
    queryKey: ['webhook-subs'],
    queryFn: async () => (await api.get('/api/webhooks/subscriptions')).data,
  })

  const subscribe = async () => {
    if (!url.trim()) return
    try {
      await api.post('/api/webhooks/subscriptions', { event_type: eventType, url: url.trim() })
      setUrl('')
      qc.invalidateQueries({ queryKey: ['webhook-subs'] })
      toast.push('success', `Subscribed to ${eventType}`)
    } catch (e: any) {
      toast.push('error', e.response?.data?.detail || e.message)
    }
  }

  const unsubscribe = async (eventType: string) => {
    await api.delete(`/api/webhooks/subscriptions/${eventType}`)
    qc.invalidateQueries({ queryKey: ['webhook-subs'] })
    toast.push('info', `Unsubscribed from ${eventType}`)
  }

  const eventDescriptions: Record<string, string> = {
    PCR_THRESHOLD: 'PCR (Put-Call Ratio) crosses a threshold — signals extreme fear/greed',
    BIAS_CHANGE: 'Market bias flips between bullish and bearish',
    OI_SPIKE: 'Unusual open interest buildup detected',
    ORDER_FILL: 'An order is executed',
    KILL_SWITCH: 'Kill-switch is triggered (all positions flattened)',
  }

  return (
    <div className="card" style={{ maxWidth: 720 }}>
      <h3>Event Subscriptions</h3>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 12 }}>
        Subscribe to real-time events via webhook. Requires <strong>Pro</strong> or <strong>Algo</strong> tier.
        Events are POSTed to your URL as JSON.
      </p>

      <div style={{ marginBottom: 16 }}>
        <div className="row" style={{ marginBottom: 8, gap: 8 }}>
          <select value={eventType} onChange={e => setEventType(e.target.value)} style={{ minWidth: 180 }}>
            {events?.events?.map(ev => (
              <option key={ev} value={ev}>{ev.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <input className="input" placeholder="https://your-server.com/webhook" value={url}
                 onChange={e => setUrl(e.target.value)} style={{ flex: 1 }} />
          <button className="primary" onClick={subscribe} disabled={!url.trim()}>Subscribe</button>
        </div>
        {eventDescriptions[eventType] && (
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
            {eventDescriptions[eventType]}
          </div>
        )}
      </div>

      <h4 style={{ margin: '0 0 8px', fontSize: 13 }}>Active subscriptions</h4>
      {!subs?.subscriptions?.length && (
        <div style={{ color: 'var(--muted)', fontSize: 12 }}>No active subscriptions.</div>
      )}
      {subs?.subscriptions?.map(s => (
        <div key={s.event_type} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 12 }}>{s.event_type.replace(/_/g, ' ')}</div>
            <div style={{ fontSize: 11, color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.url}</div>
          </div>
          <button onClick={() => unsubscribe(s.event_type)} style={{ background: 'var(--red)', color: '#fff', borderColor: 'transparent', fontSize: 11 }}>Remove</button>
        </div>
      ))}
    </div>
  )
}

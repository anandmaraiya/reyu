import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useToast } from '../toast'

type Tab = 'account' | 'trading' | 'notify' | 'appearance' | 'shortcuts'

const TABS: { id: Tab; label: string }[] = [
  { id: 'account', label: 'Account' },
  { id: 'trading', label: 'Trading' },
  { id: 'notify', label: 'Notifications' },
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
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('account')
  const [url, setUrl] = useState('')
  const [risk, setRisk] = useState<RiskPrefs>(() => {
    try { return { ...DEFAULT_RISK, ...JSON.parse(localStorage.getItem(RISK_KEY) || '{}') } }
    catch { return DEFAULT_RISK }
  })

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
            <div className="card" style={{ maxWidth: 640 }}>
              <h3>Account & Connectivity</h3>
              <table>
                <tbody>
                  <tr><td>Fyers</td><td className={status?.fyers ? 'bull' : 'bear'}>{status?.fyers ? 'connected (live)' : 'demo mode'}</td></tr>
                  <tr><td>Redis</td><td className={status?.redis ? 'bull' : 'bear'}>{status?.redis ? 'ok' : 'down'}</td></tr>
                  <tr><td>Postgres</td><td className={status?.postgres ? 'bull' : 'bear'}>{status?.postgres ? 'ok' : 'down'}</td></tr>
                  <tr><td>Last snapshot</td><td>{status?.last_snapshot_at ? new Date(status.last_snapshot_at).toLocaleString() : '—'}</td></tr>
                  <tr><td>Tracked symbols</td><td>{status?.tracked_symbols ?? 0}</td></tr>
                  <tr><td>Subscription</td><td><span className="tag" style={{ background: 'rgba(96,165,250,.15)', color: 'var(--accent)' }}>Pro</span></td></tr>
                </tbody>
              </table>
              <div className="row" style={{ marginTop: 12, gap: 8 }}>
                <a className="primary" href="/login" style={{ padding: '6px 12px', textDecoration: 'none' }}>Re-authenticate Fyers</a>
                <a className="ghost" href="/subscription" style={{ padding: '6px 12px', textDecoration: 'none' }}>Manage subscription</a>
              </div>
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
            </div>
          )}

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

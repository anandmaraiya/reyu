import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useToast } from '../toast'

export default function Settings({ theme, setTheme }: { theme: string; setTheme: (t: 'dark' | 'light') => void }) {
  const t = useToast()
  const qc = useQueryClient()
  const { data: hooks } = useQuery<{ hooks: string[] }>({
    queryKey: ['hooks'],
    queryFn: async () => (await api.get('/api/notify')).data,
  })
  const [url, setUrl] = useState('')

  const add = async () => {
    if (!url) return
    await api.post('/api/notify', { url }); setUrl(''); qc.invalidateQueries({ queryKey: ['hooks'] })
    t.push('success', 'Webhook added')
  }
  const remove = async (u: string) => {
    await api.delete('/api/notify', { data: { url: u } })
    qc.invalidateQueries({ queryKey: ['hooks'] })
  }
  const test = async () => { await api.post('/api/notify/test'); t.push('info', 'Test ping sent to all webhooks') }

  return (
    <div>
      <div className="card" style={{ marginBottom: 12, maxWidth: 600 }}>
        <h3>Appearance</h3>
        <div className="row" style={{ alignItems: 'center' }}>
          <label style={{ minWidth: 100 }}>Theme</label>
          <select value={theme} onChange={e => setTheme(e.target.value as any)}>
            <option value="dark">Dark</option><option value="light">Light</option>
          </select>
          <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 8 }}>Shift+T to toggle anywhere</span>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12, maxWidth: 600 }}>
        <h3>Webhooks (Telegram / Discord / generic)</h3>
        <div className="row" style={{ marginBottom: 8 }}>
          <input className="input" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://discord.com/api/webhooks/… or https://api.telegram.org/bot…/sendMessage" style={{ flex: 1 }} />
          <button className="primary" onClick={add}>Add</button>
          <button onClick={test}>Send test</button>
        </div>
        {hooks?.hooks?.length === 0 && <div style={{ color: 'var(--muted)', fontSize: 12 }}>No webhooks configured.</div>}
        {hooks?.hooks?.map(h => (
          <div key={h} style={{ display: 'flex', alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{h}</span>
            <button onClick={() => remove(h)}>×</button>
          </div>
        ))}
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>
          Events emitted: BATCH_ORDER, BIAS_FLIP (when implemented), KILL_SWITCH.
        </div>
      </div>

      <div className="card" style={{ maxWidth: 600 }}>
        <h3>Keyboard shortcuts</h3>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
          ⌘K / Ctrl+K — command palette<br />
          g d / g s / g p / g w / g f / g c / g v / g a / g , — jump to pages<br />
          Shift+T — toggle theme · Esc — close modals
        </div>
      </div>
    </div>
  )
}

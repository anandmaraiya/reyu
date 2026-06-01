import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

const ACTIONS = [
  { label: 'Go to Option Chain', to: '/dashboard', keys: 'g d' },
  { label: 'Go to Strategy Builder', to: '/strategy', keys: 'g s' },
  { label: 'Go to Positions', to: '/positions', keys: 'g p' },
  { label: 'Go to Watchlists', to: '/watchlists', keys: 'g w' },
  { label: 'Go to Portfolios', to: '/portfolios', keys: 'g f' },
  { label: 'Go to Scalping', to: '/scalping', keys: 'g c' },
  { label: 'Go to Saved Strategies', to: '/saved', keys: 'g v' },
  { label: 'Go to Order Audit', to: '/audit', keys: 'g a' },
  { label: 'Go to Settings', to: '/settings', keys: 'g ,' },
  { label: 'Go to Fyers Auth', to: '/login', keys: 'g l' },
]

export default function CommandPalette({ toggleTheme }: { toggleTheme: () => void }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const nav = useNavigate()

  useEffect(() => {
    const seq: string[] = []
    let timer: any
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setOpen(o => !o); return }
      if (e.key === 'Escape') { setOpen(false); return }
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return
      if (e.key === 't' && e.shiftKey) { toggleTheme(); return }
      seq.push(e.key.toLowerCase())
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => seq.length = 0, 800)
      const joined = seq.join(' ')
      const hit = ACTIONS.find(a => a.keys === joined)
      if (hit) { nav(hit.to); seq.length = 0 }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [nav, toggleTheme])

  if (!open) return null
  const matches = ACTIONS.filter(a => a.label.toLowerCase().includes(q.toLowerCase()))

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 300, display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: 80 }} onClick={() => setOpen(false)}>
      <div className="card" style={{ width: 480 }} onClick={e => e.stopPropagation()}>
        <input className="input" autoFocus placeholder="Type to navigate… (⌘K)"
               value={q} onChange={e => setQ(e.target.value)} style={{ width: '100%', marginBottom: 8 }} />
        {matches.map(a => (
          <div key={a.to} onClick={() => { nav(a.to); setOpen(false) }}
               style={{ padding: '6px 8px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', borderRadius: 4 }}
               onMouseEnter={e => (e.currentTarget.style.background = 'var(--border)')}
               onMouseLeave={e => (e.currentTarget.style.background = '')}>
            <span>{a.label}</span>
            <kbd style={{ fontSize: 10, color: 'var(--muted)' }}>{a.keys}</kbd>
          </div>
        ))}
        <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 8 }}>
          Shift+T toggles theme · ⌘K opens this · Esc closes
        </div>
      </div>
    </div>
  )
}

import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useToast } from '../toast'
import { detectStrategyName } from '../components/StrategyVisuals'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

type SavedRow = {
  name: string; underlying: string; view: string
  legs: any[]; saved_at: string; notes?: string; tags?: string[]
}

const CATEGORIES = ['ALL', 'BULLISH', 'BEARISH', 'NEUTRAL', 'INCOME'] as const

function MiniPayoffSparkline({ legs }: { legs: any[] }) {
  // Synthetic 21-point payoff using each leg's strike (mock-y but visually
  // representative — the real number is available after analysis).
  const pts = useMemo(() => {
    if (!legs.length) return []
    const ks = legs.map(l => l.strike || l.price || 0).filter(Boolean)
    if (!ks.length) return []
    const min = Math.min(...ks), max = Math.max(...ks)
    const span = Math.max((max - min) * 1.6, 100)
    const center = (min + max) / 2
    const xs = Array.from({ length: 21 }, (_, i) => center - span / 2 + (span * i) / 20)
    return xs.map(S => {
      let p = 0
      for (const l of legs) {
        const sign = l.action === 'BUY' ? 1 : -1
        if (l.option_type === 'CE') p += sign * (Math.max(S - (l.strike || 0), 0) - l.price) * (l.qty || 0)
        else if (l.option_type === 'PE') p += sign * (Math.max((l.strike || 0) - S, 0) - l.price) * (l.qty || 0)
      }
      return p
    })
  }, [legs])
  if (pts.length === 0) return null
  const w = 200, h = 50
  const min = Math.min(...pts), max = Math.max(...pts), range = max - min || 1
  const path = pts.map((y, i) => {
    const xx = (i / (pts.length - 1)) * w
    const yy = h - ((y - min) / range) * h
    return `${i === 0 ? 'M' : 'L'}${xx.toFixed(1)},${yy.toFixed(1)}`
  }).join(' ')
  const zeroY = h - ((0 - min) / range) * h
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
      <line x1="0" x2={w} y1={zeroY} y2={zeroY} stroke="var(--border)" strokeDasharray="2 3" />
      <path d={path} stroke="var(--accent)" strokeWidth="1.6" fill="none" />
    </svg>
  )
}

export default function Saved() {
  const qc = useQueryClient()
  const t = useToast()
  const nav = useNavigate()
  const [filter, setFilter] = useState<typeof CATEGORIES[number]>('ALL')
  const [q, setQ] = useState('')

  const { data } = useQuery<Record<string, any>>({
    queryKey: ['saved'],
    queryFn: async () => (await api.get('/api/strategy/saved')).data,
  })

  const rows = (Object.values(data || {}) as SavedRow[])

  const categorise = (s: SavedRow): typeof CATEGORIES[number] => {
    const name = detectStrategyName(s.legs).toLowerCase()
    if (name.includes('bull')) return 'BULLISH'
    if (name.includes('bear')) return 'BEARISH'
    if (name.includes('condor') || name.includes('butterfly') || name.includes('strangle')) return 'NEUTRAL'
    if (name.includes('short')) return 'INCOME'
    return 'NEUTRAL'
  }

  const filtered = rows.filter(s => {
    const matchQ = !q || s.name.toLowerCase().includes(q.toLowerCase()) || s.underlying.toLowerCase().includes(q.toLowerCase())
    const matchCat = filter === 'ALL' || categorise(s) === filter
    return matchQ && matchCat
  })

  const counts: Record<string, number> = { ALL: rows.length }
  for (const s of rows) {
    const c = categorise(s); counts[c] = (counts[c] || 0) + 1
  }

  const del = async (name: string) => {
    await api.delete(`/api/strategy/saved/${encodeURIComponent(name)}`)
    qc.invalidateQueries({ queryKey: ['saved'] })
    t.push('info', `Deleted ${name}`)
  }
  const deploy = (s: SavedRow) => {
    const strikeList = s.legs.map(l => l.strike).filter(Boolean).join(',')
    nav(`/strategy?underlying=${encodeURIComponent(s.underlying)}&load=${encodeURIComponent(s.name)}${strikeList ? `&selected=${strikeList}` : ''}`)
  }
  const duplicate = async (s: SavedRow) => {
    const name = `${s.name} (copy)`
    await api.post('/api/strategy/saved', { ...s, name })
    qc.invalidateQueries({ queryKey: ['saved'] })
    t.push('success', `Duplicated as "${name}"`)
  }

  return (
    <div className="page-shell">
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="row" style={{ alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <h3 style={{ margin: 0 }}>Filter</h3>
          <input className="input" placeholder="Search by name / underlying"
                 value={q} onChange={e => setQ(e.target.value)} style={{ minWidth: 220 }} />
          <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
            {CATEGORIES.map(c => (
              <button key={c} className={filter === c ? 'primary' : 'ghost'}
                      onClick={() => setFilter(c)} style={{ padding: '4px 10px', fontSize: 11 }}>
                {c} <span style={{ opacity: .6, marginLeft: 4 }}>{counts[c] ?? 0}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {filtered.length === 0 && (
        <div className="card" style={{ color: 'var(--muted)' }}>
          {rows.length === 0
            ? 'No saved strategies yet. Build one in Strategy Builder and click Save.'
            : 'No strategies match your filters.'}
        </div>
      )}

      <div className="row" style={{ flexWrap: 'wrap', gap: 12 }}>
        {filtered.map(s => {
          const cat = categorise(s)
          const detected = detectStrategyName(s.legs)
          return (
            <div key={s.name} className="card-glass col"
                 style={{ minWidth: 320, maxWidth: 360, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="row" style={{ alignItems: 'baseline', gap: 6 }}>
                <h3 style={{ margin: 0 }}>{s.name}</h3>
                <span className={`tag ${cat === 'BULLISH' ? 'bull' : cat === 'BEARISH' ? 'bear' : 'neutral'}`}
                      style={{ marginLeft: 'auto', fontSize: 10 }}>{cat}</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                {detected} · {s.underlying}<br />saved {new Date(s.saved_at).toLocaleString()}
              </div>
              <MiniPayoffSparkline legs={s.legs} />
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                {s.legs.length} leg(s) · Net ₹{num(s.legs.reduce((a, l) => a + (l.action === 'BUY' ? 1 : -1) * l.price * l.qty, 0), 0)}
              </div>
              {s.notes && (
                <div style={{ fontSize: 11, padding: 6, background: 'var(--panel-hover, var(--panel))', borderRadius: 6 }}>
                  {s.notes}
                </div>
              )}
              <div className="row" style={{ gap: 6, marginTop: 'auto' }}>
                <button className="primary" style={{ flex: 1 }} onClick={() => deploy(s)}>Deploy</button>
                <button className="ghost" onClick={() => duplicate(s)}>Duplicate</button>
                <button className="ghost" onClick={() => del(s.name)} title="Delete">×</button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

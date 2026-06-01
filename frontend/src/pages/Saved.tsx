import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useToast } from '../toast'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

export default function Saved() {
  const qc = useQueryClient()
  const t = useToast()
  const { data } = useQuery<Record<string, any>>({
    queryKey: ['saved'],
    queryFn: async () => (await api.get('/api/strategy/saved')).data,
  })

  const del = async (name: string) => {
    await api.delete(`/api/strategy/saved/${encodeURIComponent(name)}`)
    qc.invalidateQueries({ queryKey: ['saved'] })
    t.push('info', `Deleted ${name}`)
  }

  const rows = Object.values(data || {}) as any[]

  return (
    <div>
      <h3>Saved Strategies</h3>
      {rows.length === 0 && <div className="card" style={{ color: 'var(--muted)' }}>No saved strategies yet. Build one in Strategy Builder and click Save.</div>}
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {rows.map(s => (
          <div key={s.name} className="card col" style={{ minWidth: 300 }}>
            <h3>{s.name} <span className="tag neutral" style={{ marginLeft: 6 }}>{s.view}</span>
              <button onClick={() => del(s.name)} style={{ float: 'right' }}>×</button>
            </h3>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>{s.underlying} · saved {new Date(s.saved_at).toLocaleString()}</div>
            <table style={{ marginTop: 6 }}>
              <thead><tr><th>Leg</th><th>Action</th><th>Qty</th><th>Price</th></tr></thead>
              <tbody>
                {s.legs.map((l: any, i: number) => (
                  <tr key={i}><td style={{ fontSize: 11 }}>{l.symbol}</td><td className={l.action === 'BUY' ? 'bull' : 'bear'}>{l.action}</td><td>{l.qty}</td><td>{num(l.price)}</td></tr>
                ))}
              </tbody>
            </table>
            {s.notes && <div style={{ fontSize: 11, marginTop: 6, color: 'var(--muted)' }}>{s.notes}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

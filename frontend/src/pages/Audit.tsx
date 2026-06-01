import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { downloadCSV } from '../utils/csv'

export default function Audit() {
  const { data } = useQuery<any[]>({
    queryKey: ['audit'],
    queryFn: async () => (await api.get('/api/orders/audit', { params: { limit: 100 } })).data,
    refetchInterval: 8000,
  })

  return (
    <div>
      <div className="row" style={{ alignItems: 'center', marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>Order Audit Log (last 100)</h3>
        <button style={{ marginLeft: 'auto' }} onClick={() => downloadCSV('reyu-audit.csv', (data || []).map(d => ({
          ts: d.ts, label: d.label, dry_run: d.dry_run, legs: d.legs.length,
          ok: d.results.every((r: any) => !r.error),
        })))}>Export CSV</button>
      </div>
      <div className="card">
        {!data?.length && <div style={{ color: 'var(--muted)' }}>No orders yet.</div>}
        {data?.map((a, i) => (
          <details key={i} style={{ borderBottom: '1px solid var(--border)', padding: '6px 0' }}>
            <summary style={{ cursor: 'pointer' }}>
              <span style={{ color: 'var(--muted)', fontSize: 11 }}>{new Date(a.ts).toLocaleString()}</span>
              <strong style={{ marginLeft: 8 }}>{a.label || 'Batch'}</strong>
              <span className={`tag ${a.dry_run ? 'neutral' : 'bull'}`} style={{ marginLeft: 8 }}>{a.dry_run ? 'DRY' : 'LIVE'}</span>
              <span style={{ marginLeft: 8, fontSize: 12 }}>{a.legs.length} legs</span>
            </summary>
            <pre style={{ fontSize: 10, background: '#0f1422', padding: 8, borderRadius: 4, overflow: 'auto', marginTop: 6 }}>
              {JSON.stringify(a, null, 2)}
            </pre>
          </details>
        ))}
      </div>
    </div>
  )
}

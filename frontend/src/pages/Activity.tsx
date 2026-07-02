/**
 * Activity — the signed-in user's own compliance trail.
 *
 * Surfaces /api/audit/my: the prompts sent to Reyu, the AI responses,
 * legal acceptances, strategy approvals/promotions, and executed orders.
 * Read-only and scoped to the current user (backend filters by actor_id).
 */
import { type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { useAuth } from '../context/AuthContext'

type Entry = {
  id: string
  ts: string | null
  event_type: string
  resource_type: string | null
  resource_id: string | null
  action: string | null
  meta: any
}

const LABELS: Record<string, { label: string; color: string }> = {
  CHAT_TURN: { label: 'Reyu chat', color: '#6366f1' },
  LEGAL_ACCEPT: { label: 'Legal accepted', color: '#0ea5e9' },
  STRATEGY_CREATE: { label: 'Strategy created', color: '#22c55e' },
  STRATEGY_PROMOTE: { label: 'Strategy promoted', color: '#f59e0b' },
  STRATEGY_HALT: { label: 'Strategy halted', color: '#ef4444' },
  ORDER_EXECUTE: { label: 'Order executed', color: '#ef4444' },
  ORDER_EXIT_LIVE: { label: 'Live exit', color: '#ef4444' },
  ORDER_EXIT_DRY: { label: 'Dry-run exit', color: '#64748b' },
  BROKER_CONNECT: { label: 'Broker connected', color: '#22c55e' },
  BROKER_DISCONNECT: { label: 'Broker disconnected', color: '#f59e0b' },
  LOGIN: { label: 'Sign in', color: '#64748b' },
}

const S = {
  page: { padding: '24px 32px', maxWidth: 900, color: 'var(--text-primary)' } as CSSProperties,
  h1: { fontSize: 22, fontWeight: 700, margin: '0 0 4px' } as CSSProperties,
  sub: { fontSize: 13, color: 'var(--text-secondary)', marginBottom: 20, lineHeight: 1.5 } as CSSProperties,
  row: {
    display: 'grid', gridTemplateColumns: '160px 150px 1fr', gap: 12, alignItems: 'start',
    padding: '12px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 13,
  } as CSSProperties,
  ts: { color: 'var(--text-muted)', fontSize: 12, fontFamily: 'var(--font-mono)' } as CSSProperties,
  badge: (c: string): CSSProperties => ({
    display: 'inline-block', padding: '2px 8px', borderRadius: 'var(--radius-full, 999px)',
    fontSize: 11, fontWeight: 600, background: `${c}22`, color: c,
  }),
  action: { color: 'var(--text-primary)' } as CSSProperties,
  detail: { color: 'var(--text-secondary)', fontSize: 12, marginTop: 4, whiteSpace: 'pre-wrap' as const } as CSSProperties,
  empty: { padding: '48px 0', textAlign: 'center' as const, color: 'var(--text-secondary)' } as CSSProperties,
}

function renderMeta(e: Entry) {
  if (e.event_type === 'CHAT_TURN' && e.meta) {
    return (
      <div style={S.detail}>
        <b>You:</b> {e.meta.prompt}
        {'\n'}<b>Reyu:</b> {e.meta.response}
      </div>
    )
  }
  if (e.meta && typeof e.meta === 'object') {
    const keys = Object.keys(e.meta)
    if (keys.length) return <div style={S.detail}>{keys.map(k => `${k}: ${e.meta[k]}`).join(' · ')}</div>
  }
  return null
}

export default function Activity() {
  const { user } = useAuth()
  const { data, isLoading } = useQuery<{ entries: Entry[] }>({
    queryKey: ['my-activity'],
    queryFn: async () => (await api.get('/api/audit/my?days=90&limit=200')).data,
    enabled: !!user,
  })

  if (!user) return <div style={S.page}><p style={S.sub}>Sign in to view your activity log.</p></div>

  return (
    <div style={S.page}>
      <h1 style={S.h1}>My Activity</h1>
      <p style={S.sub}>
        A record of your prompts to Reyu, AI responses, approvals, and executed orders —
        retained for compliance. Only you and platform compliance can see this.
      </p>
      {isLoading && <div style={S.empty}>Loading…</div>}
      {data && data.entries.length === 0 && <div style={S.empty}>No activity in the last 90 days.</div>}
      {data?.entries.map(e => {
        const l = LABELS[e.event_type] || { label: e.event_type, color: '#64748b' }
        return (
          <div key={e.id} style={S.row}>
            <div style={S.ts}>{e.ts ? new Date(e.ts).toLocaleString() : '—'}</div>
            <div><span style={S.badge(l.color)}>{l.label}</span></div>
            <div>
              <div style={S.action}>{e.action || e.resource_type || ''}</div>
              {renderMeta(e)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

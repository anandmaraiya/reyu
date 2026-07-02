import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useToast } from '../toast'

const num = (n: any, d = 2) =>
  n == null ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d })

type Strategy = {
  id: string
  version: number
  name: string
  description: string | null
  kind: 'CONDITIONAL' | 'RL_BANDIT'
  status: 'DRAFT' | 'BACKTESTED' | 'PAPER_LIVE' | 'LIVE' | 'ARCHIVED'
  tier_required: string
  created_by: string
  tags: string[]
  spec: any
  updated_at: string
  is_published?: boolean
  copies_count?: number
}

const STATUS_COLORS: Record<string, string> = {
  DRAFT: '#888',
  BACKTESTED: '#4a9fda',
  PAPER_LIVE: '#f0a830',
  LIVE: '#2da14b',
  ARCHIVED: '#555',
}

function StatusPill({ status }: { status: string }) {
  return (
    <span
      style={{
        background: STATUS_COLORS[status] || '#666',
        color: '#fff',
        padding: '2px 8px',
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
      }}
    >
      {status}
    </span>
  )
}

function KindBadge({ kind }: { kind: string }) {
  return (
    <span
      style={{
        background: kind === 'RL_BANDIT' ? '#6b46c1' : '#37415140',
        color: kind === 'RL_BANDIT' ? '#fff' : 'var(--text)',
        padding: '2px 8px',
        borderRadius: 10,
        fontSize: 10,
        fontWeight: 600,
      }}
    >
      {kind}
    </span>
  )
}

export default function Strategies() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [filter, setFilter] = useState<string>('ALL')

  const { data, isLoading } = useQuery<{ count: number; items: Strategy[] }>({
    queryKey: ['strategies', filter],
    queryFn: async () => {
      const params: any = {}
      if (filter !== 'ALL') params.status = filter
      return (await api.get('/api/strategies', { params })).data
    },
    refetchInterval: 10000,
  })

  const archive = useMutation({
    mutationFn: (id: string) => api.post(`/api/strategies/${id}/archive`),
    onSuccess: () => {
      toast.push('success', 'Archived')
      qc.invalidateQueries({ queryKey: ['strategies'] })
    },
    onError: (e: any) => toast.push('error', e?.response?.data?.detail || 'Archive failed'),
  })

  const togglePublish = useMutation({
    mutationFn: ({ id, published }: { id: string; published: boolean }) =>
      api.post(`/api/strategies/${id}/publish`, { published }),
    onSuccess: (_, vars) => {
      toast.push('success', vars.published ? 'Published to catalog' : 'Removed from catalog')
      qc.invalidateQueries({ queryKey: ['strategies'] })
    },
    onError: (e: any) => toast.push('error', e?.response?.data?.detail || 'Publish failed'),
  })

  const items = data?.items || []
  const filtered =
    filter === 'ALL' ? items : items.filter((s) => s.status === filter)

  const counts = items.reduce<Record<string, number>>(
    (acc, s) => ({ ...acc, [s.status]: (acc[s.status] || 0) + 1 }),
    {},
  )

  return (
    <div className="page-shell">
      <div className="card">
        <div className="card-header">
          <h3>Strategies</h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>
              {data?.count ?? 0} total
            </span>
            <button
              className="btn btn-primary"
              onClick={() => nav('/strategies/new')}
            >
              + New Strategy
            </button>
          </div>
        </div>

        {/* Filter pills */}
        <div
          style={{
            display: 'flex',
            gap: 6,
            padding: '8px 14px',
            flexWrap: 'wrap',
            borderBottom: '1px solid var(--border)',
          }}
        >
          {['ALL', 'DRAFT', 'BACKTESTED', 'PAPER_LIVE', 'LIVE', 'ARCHIVED'].map(
            (f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  padding: '4px 10px',
                  borderRadius: 14,
                  fontSize: 11,
                  fontWeight: 600,
                  border: '1px solid var(--border)',
                  background:
                    filter === f ? 'var(--accent)' : 'transparent',
                  color:
                    filter === f ? '#fff' : 'var(--text)',
                  cursor: 'pointer',
                }}
              >
                {f} {counts[f] != null && f !== 'ALL' ? `· ${counts[f]}` : ''}
              </button>
            ),
          )}
        </div>

        {/* Grid */}
        {isLoading ? (
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--muted)' }}>
            Loading…
          </div>
        ) : filtered.length === 0 ? (
          <div
            style={{
              padding: 40,
              textAlign: 'center',
              color: 'var(--muted)',
              fontSize: 13,
            }}
          >
            No strategies in <b>{filter}</b>.
            <br />
            <button
              className="btn btn-primary"
              style={{ marginTop: 14 }}
              onClick={() => nav('/strategies/new')}
            >
              Create your first strategy
            </button>
          </div>
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
              gap: 12,
              padding: 14,
            }}
          >
            {filtered.map((s) => (
              <StrategyCard
                key={s.id}
                s={s}
                onClick={() => nav(`/strategies/${s.id}`)}
                onArchive={() => archive.mutate(s.id)}
                onTogglePublish={() => togglePublish.mutate({ id: s.id, published: !s.is_published })}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function StrategyCard({
  s,
  onClick,
  onArchive,
  onTogglePublish,
}: {
  s: Strategy
  onClick: () => void
  onArchive: () => void
  onTogglePublish: () => void
}) {
  const universe = (s.spec?.universe || [])[0] || '—'
  const tp = s.spec?.exit_rules?.tp_pct
  const sl = s.spec?.exit_rules?.sl_pct
  const trigger = s.spec?.entry_rules?.trigger || '—'

  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: 12,
        cursor: 'pointer',
        background: 'var(--card)',
      }}
      onClick={onClick}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: 8,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontWeight: 600,
              fontSize: 14,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {s.name}
          </div>
          <div
            style={{
              fontSize: 11,
              color: 'var(--muted)',
              marginTop: 2,
            }}
          >
            {universe} · v{s.version}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
          <KindBadge kind={s.kind} />
          <StatusPill status={s.status} />
        </div>
      </div>

      {s.description && (
        <div
          style={{
            fontSize: 12,
            color: 'var(--muted)',
            margin: '6px 0',
            display: '-webkit-box',
            WebkitBoxOrient: 'vertical',
            WebkitLineClamp: 2,
            overflow: 'hidden',
          }}
        >
          {s.description}
        </div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 6,
          fontSize: 11,
          color: 'var(--muted)',
          padding: '8px 0',
          borderTop: '1px solid var(--border)',
          borderBottom: '1px solid var(--border)',
        }}
      >
        <div>
          <div style={{ color: 'var(--muted)' }}>Trigger</div>
          <div style={{ color: 'var(--text)', fontWeight: 600 }}>{trigger}</div>
        </div>
        <div>
          <div style={{ color: 'var(--muted)' }}>TP/SL</div>
          <div style={{ color: 'var(--text)', fontWeight: 600 }}>
            {tp ? `${(tp * 100).toFixed(0)}/${(sl * 100).toFixed(0)}%` : '—'}
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--muted)' }}>Tier</div>
          <div style={{ color: 'var(--text)', fontWeight: 600 }}>
            {s.tier_required}
          </div>
        </div>
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginTop: 8,
          fontSize: 11,
          color: 'var(--muted)',
        }}
      >
        <span>
          {s.tags?.slice(0, 3).map((t) => (
            <span
              key={t}
              style={{
                background: 'var(--card2)',
                padding: '1px 6px',
                borderRadius: 8,
                marginRight: 4,
              }}
            >
              #{t}
            </span>
          ))}
        </span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {s.is_published && (
            <span
              title={`${s.copies_count ?? 0} copies`}
              style={{
                background: 'var(--brand-primary)',
                color: '#fff',
                padding: '1px 8px',
                borderRadius: 8,
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: '0.05em',
              }}
            >
              PUBLISHED · {s.copies_count ?? 0}
            </span>
          )}
          {s.status !== 'ARCHIVED' && s.status !== 'LIVE' && (
            <>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onTogglePublish()
                }}
                style={{
                  fontSize: 11,
                  color: s.is_published ? 'var(--signal)' : 'var(--brand-primary)',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: 0,
                }}
              >
                {s.is_published ? 'unpublish' : 'publish'}
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  if (confirm(`Archive "${s.name}"?`)) onArchive()
                }}
                style={{
                  fontSize: 11,
                  color: 'var(--muted)',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: 0,
                }}
              >
                archive
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

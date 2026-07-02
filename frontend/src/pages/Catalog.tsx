/**
 * Catalog — public strategy discovery + copy-to-account (F-A6, P-19).
 *
 * Anon users can browse. Copy requires login; if anon, click triggers
 * the sign-in gate then completes the copy.
 *
 * KPIs surfaced per strategy: kind, underlying, TP/SL brackets, copies.
 */
import { useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useAuth } from '../context/AuthContext'
import { track, Events } from '../telemetry'
import PageHelp from '../components/PageHelp'
import RiskNote from '../components/RiskNote'

type Preview = {
  kind: string | null
  underlying: string | null
  brackets: { target_pct?: number; stop_pct?: number } | null
}
type CatalogItem = {
  id: string
  name: string
  description: string
  kind: string
  version: number
  published_at: string | null
  copies_count: number
  preview: Preview
}

const S = {
  page: { padding: '20px 32px', maxWidth: 1200, color: 'var(--text-primary)' } as CSSProperties,
  h1: { fontSize: 22, fontWeight: 600, margin: '0 0 4px 0' } as CSSProperties,
  sub: { color: 'var(--text-secondary)', fontSize: 13, marginBottom: 20 } as CSSProperties,
  toolbar: { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 20 } as CSSProperties,
  chip: (active: boolean): CSSProperties => ({
    padding: '6px 14px',
    fontSize: 12,
    fontWeight: 500,
    background: active ? 'var(--brand-primary)' : 'var(--bg-elevated)',
    color: active ? '#fff' : 'var(--text-primary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-full)',
    cursor: 'pointer',
  }),
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    gap: 14,
  } as CSSProperties,
  card: {
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-md)',
    padding: 18,
    boxShadow: 'var(--shadow-sm)',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 12,
    transition: 'transform 120ms',
  } as CSSProperties,
  badge: {
    display: 'inline-block',
    padding: '2px 8px',
    fontSize: 10,
    fontWeight: 600,
    background: 'var(--brand-light)',
    color: 'var(--brand-text)',
    borderRadius: 'var(--radius-full)',
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
  } as CSSProperties,
  name: { fontSize: 16, fontWeight: 600, margin: 0, color: 'var(--text-primary)' } as CSSProperties,
  desc: { fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.4, margin: 0 } as CSSProperties,
  specRow: {
    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 11,
    padding: 10, background: 'var(--bg-sunken)', borderRadius: 'var(--radius-sm)',
    color: 'var(--text-secondary)',
  } as CSSProperties,
  specLabel: { color: 'var(--text-muted)', fontSize: 10, letterSpacing: '0.04em', textTransform: 'uppercase' as const } as CSSProperties,
  specValue: { color: 'var(--text-primary)', fontWeight: 600, fontFamily: 'var(--font-mono)', marginTop: 1 } as CSSProperties,
  footer: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'auto',
  } as CSSProperties,
  copies: { fontSize: 11, color: 'var(--text-muted)' } as CSSProperties,
  copyBtn: {
    padding: '7px 14px',
    fontSize: 12,
    fontWeight: 600,
    background: 'var(--brand-primary)',
    color: '#fff',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
  } as CSSProperties,
  empty: {
    padding: '48px 24px', textAlign: 'center' as const,
    color: 'var(--text-secondary)', fontSize: 14,
  } as CSSProperties,
}

export default function Catalog() {
  const { user, openGate } = useAuth()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [sort, setSort] = useState<'recent' | 'popular'>('recent')

  const q = useQuery<{ strategies: CatalogItem[] }>({
    queryKey: ['catalog', sort],
    queryFn: async () => (await api.get(`/api/catalog?sort=${sort}&limit=50`)).data,
  })

  const copy = useMutation({
    mutationFn: async (id: string) =>
      (await api.post(`/api/catalog/${id}/copy`, {})).data,
    onSuccess: (data, sourceId) => {
      track(Events.StrategyCopied, { source_id: sourceId })
      qc.invalidateQueries({ queryKey: ['catalog'] })
      nav(`/strategies/${data.id}`)
    },
  })

  const follow = useMutation({
    mutationFn: async (leaderId: string) =>
      (await api.post('/api/follows', { leader_strategy_id: leaderId, mode: 'PAPER' })).data,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['catalog'] })
      nav(`/strategies/${data.follower_strategy_id}`)
    },
  })

  const handleFollow = (id: string) => {
    if (!user) {
      openGate({
        mode: 'login',
        message: 'Sign in to follow this strategy.',
        onSuccess: () => follow.mutate(id),
      })
      return
    }
    follow.mutate(id)
  }

  const handleCopy = (id: string) => {
    if (!user) {
      openGate({
        mode: 'login',
        message: 'Sign in to copy this strategy to your account.',
        onSuccess: () => copy.mutate(id),
      })
      return
    }
    copy.mutate(id)
  }

  return (
    <div style={S.page}>
      <PageHelp pageId="catalog" />
      <h1 style={S.h1}>Strategy Catalog</h1>
      <p style={S.sub}>
        Discover strategies other traders have published. Copy any into your account as a
        draft — backtest, review, then promote to paper or live at your own pace.
      </p>

      <RiskNote />

      <div style={S.toolbar}>
        <span style={{ fontSize: 11, color: 'var(--text-secondary)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Sort</span>
        <button style={S.chip(sort === 'recent')} onClick={() => setSort('recent')}>Recent</button>
        <button style={S.chip(sort === 'popular')} onClick={() => setSort('popular')}>Most copied</button>
      </div>

      {q.isLoading && <div style={S.empty}>Loading catalog…</div>}

      {q.data && q.data.strategies.length === 0 && (
        <div style={S.empty}>
          No published strategies yet. Publish your first strategy from{' '}
          <a href="/strategies" style={{ color: 'var(--brand-primary)' }}>Saved</a>.
        </div>
      )}

      <div style={S.grid}>
        {q.data?.strategies.map(s => (
          <div key={s.id} style={S.card}>
            <div>
              <span style={S.badge}>{s.kind}</span>
              {s.preview.underlying && (
                <span style={{ ...S.badge, marginLeft: 6, background: 'var(--accent-light)', color: 'var(--accent-text)' }}>
                  {s.preview.underlying.replace('NSE:', '').replace('-INDEX', '').replace('-EQ', '')}
                </span>
              )}
            </div>

            <h3 style={S.name}>{s.name}</h3>
            {s.description && <p style={S.desc}>{s.description}</p>}

            {(s.preview.brackets?.target_pct || s.preview.brackets?.stop_pct) && (
              <div style={S.specRow}>
                {s.preview.brackets.target_pct != null && (
                  <div>
                    <div style={S.specLabel}>Target</div>
                    <div style={S.specValue}>+{(s.preview.brackets.target_pct * 100).toFixed(0)}%</div>
                  </div>
                )}
                {s.preview.brackets.stop_pct != null && (
                  <div>
                    <div style={S.specLabel}>Stop</div>
                    <div style={S.specValue}>−{(s.preview.brackets.stop_pct * 100).toFixed(0)}%</div>
                  </div>
                )}
              </div>
            )}

            <div style={S.footer}>
              <span style={S.copies}>
                {s.copies_count === 0 ? 'No copies yet' : `${s.copies_count} ${s.copies_count === 1 ? 'copy' : 'copies'}`}
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                <button
                  style={{
                    ...S.copyBtn,
                    background: 'var(--bg-elevated)',
                    color: 'var(--text-primary)',
                    border: '1px solid var(--border-default)',
                    opacity: follow.isPending ? 0.5 : 1,
                  }}
                  disabled={follow.isPending}
                  onClick={() => handleFollow(s.id)}
                  title="Auto-mirror this strategy's trades under your account"
                >
                  {follow.isPending ? '…' : '⚡ Follow'}
                </button>
                <button
                  style={{ ...S.copyBtn, opacity: copy.isPending ? 0.5 : 1 }}
                  disabled={copy.isPending}
                  onClick={() => handleCopy(s.id)}
                >
                  {copy.isPending ? 'Copying…' : 'Copy'}
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

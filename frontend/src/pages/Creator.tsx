/**
 * Creator — public profile for a strategy publisher (P3, #78).
 *
 * Route: /creators/:id — display name, membership date, and every
 * published strategy with forward-test facts + copy/follow counts.
 * Facts only: no P&L, no returns, no rankings (compliance stance).
 * Linked from "by <name>" on Catalog cards.
 */
import { type CSSProperties } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../toast'
import RiskNote from '../components/RiskNote'

type ProfileStrategy = {
  id: string
  name: string
  description: string
  kind: string
  published_at: string | null
  copies_count: number
  followers: number
  preview: { kind: string | null; underlying: string | null }
  forward_test: { forward_traded_days: number; forward_trades: number }
}
type Profile = {
  creator: { id: string; display_name: string; member_since: string | null }
  totals: { published_strategies: number; total_copies: number; total_followers: number }
  strategies: ProfileStrategy[]
}

const S = {
  page: { padding: '24px 32px', maxWidth: 900, color: 'var(--text-primary)' } as CSSProperties,
  head: { display: 'flex', alignItems: 'center', gap: 16, marginBottom: 8 } as CSSProperties,
  avatar: {
    width: 56, height: 56, borderRadius: '50%', display: 'grid', placeItems: 'center',
    background: 'var(--brand-primary, #f0a020)', color: '#fff', fontSize: 24, fontWeight: 700,
  } as CSSProperties,
  h1: { fontSize: 22, fontWeight: 700, margin: 0 } as CSSProperties,
  sub: { fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 2 } as CSSProperties,
  totals: { display: 'flex', gap: 24, margin: '16px 0 20px', fontSize: 13 } as CSSProperties,
  totalNum: { fontSize: 18, fontWeight: 700, fontFamily: 'var(--font-mono)' } as CSSProperties,
  totalLabel: { fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.05em' } as CSSProperties,
  card: {
    background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
    borderRadius: 10, padding: 16, marginBottom: 12,
    display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' as const,
  } as CSSProperties,
  name: { fontSize: 15, fontWeight: 700, margin: '0 0 4px' } as CSSProperties,
  desc: { fontSize: 12.5, color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 } as CSSProperties,
  facts: { fontSize: 11.5, color: 'var(--text-muted)', marginTop: 8, display: 'flex', gap: 14, flexWrap: 'wrap' as const } as CSSProperties,
  ftBadge: {
    display: 'inline-flex', gap: 6, alignItems: 'center', padding: '2px 10px',
    borderRadius: 999, fontSize: 11, fontWeight: 600,
    background: 'var(--accent-light, #4a9fda22)', color: 'var(--accent-text, #4a9fda)',
  } as CSSProperties,
  copyBtn: {
    padding: '8px 16px', fontSize: 12.5, fontWeight: 700, alignSelf: 'center',
    background: 'var(--brand-primary, #f0a020)', color: '#fff',
    border: 'none', borderRadius: 8, cursor: 'pointer',
  } as CSSProperties,
  empty: { padding: '40px 0', textAlign: 'center' as const, color: 'var(--text-secondary)' } as CSSProperties,
}

export default function Creator() {
  const { id } = useParams<{ id: string }>()
  const { user, openGate } = useAuth()
  const toast = useToast()
  const nav = useNavigate()

  const { data, isLoading, isError } = useQuery<Profile>({
    queryKey: ['creator', id],
    queryFn: async () => (await api.get(`/api/creators/${id}`)).data,
    enabled: !!id,
  })

  const copy = useMutation({
    mutationFn: async (sid: string) => (await api.post(`/api/catalog/${sid}/copy`, {})).data,
    onSuccess: (d) => { toast.push('success', `Copied to your strategies as DRAFT`); nav(`/strategies/${d.id}`) },
    onError: (e: any) => toast.push('error', e?.response?.data?.detail || 'Copy failed'),
  })
  const handleCopy = (sid: string) => {
    if (!user) {
      openGate({ mode: 'login', message: 'Sign in to copy this strategy.', onSuccess: () => copy.mutate(sid) })
      return
    }
    copy.mutate(sid)
  }

  if (isLoading) return <div style={S.page}><div style={S.empty}>Loading…</div></div>
  if (isError || !data) return <div style={S.page}><div style={S.empty}>Creator not found.</div></div>

  const c = data.creator

  return (
    <div style={S.page}>
      <Link to="/catalog" style={{ fontSize: 13, color: 'var(--brand-primary, #f0a020)', textDecoration: 'none' }}>
        ← Catalog
      </Link>
      <div style={{ ...S.head, marginTop: 12 }}>
        <div style={S.avatar}>{(c.display_name[0] || 'R').toUpperCase()}</div>
        <div>
          <h1 style={S.h1}>{c.display_name}</h1>
          {c.member_since && <div style={S.sub}>Publishing on Reyu since {c.member_since}</div>}
        </div>
      </div>

      <div style={S.totals}>
        <div><div style={S.totalNum}>{data.totals.published_strategies}</div><div style={S.totalLabel}>Published</div></div>
        <div><div style={S.totalNum}>{data.totals.total_copies}</div><div style={S.totalLabel}>Copies</div></div>
        <div><div style={S.totalNum}>{data.totals.total_followers}</div><div style={S.totalLabel}>Followers</div></div>
      </div>

      <RiskNote />

      {data.strategies.length === 0 && (
        <div style={S.empty}>No published strategies yet.</div>
      )}

      {data.strategies.map(s => (
        <div key={s.id} style={S.card}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <h3 style={S.name}>{s.name}</h3>
            {s.description && <p style={S.desc}>{s.description}</p>}
            <div style={S.facts}>
              <span>{s.kind}</span>
              {s.preview.underlying && (
                <span>{s.preview.underlying.replace('NSE:', '').replace('-INDEX', '').replace('-EQ', '')}</span>
              )}
              {s.forward_test.forward_traded_days > 0 && (
                <span style={S.ftBadge}>
                  ⏱ Forward-tested {s.forward_test.forward_traded_days}d · {s.forward_test.forward_trades} trades
                </span>
              )}
              <span>{s.copies_count} {s.copies_count === 1 ? 'copy' : 'copies'}</span>
              {s.followers > 0 && <span>{s.followers} followers</span>}
            </div>
          </div>
          <button
            style={{ ...S.copyBtn, opacity: copy.isPending ? 0.6 : 1 }}
            disabled={copy.isPending}
            onClick={() => handleCopy(s.id)}
          >
            {copy.isPending ? 'Copying…' : 'Copy'}
          </button>
        </div>
      ))}
    </div>
  )
}

/**
 * Templates — persona-grouped strategy starting points (P2a).
 *
 * Four personas (intraday options / options income / swing equity /
 * systematic investing), each with curated templates. One click copies a
 * template into the user's account as a DRAFT they own and can backtest,
 * tweak, and promote. Anonymous users can browse; copying prompts login.
 *
 * Compliance: templates are structural starting points, not
 * recommendations — RiskNote is pinned at the top.
 */
import { useState, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../toast'
import RiskNote from '../components/RiskNote'
import PageHelp from '../components/PageHelp'

type TemplateRow = {
  id: string
  persona: string
  name: string
  description: string
  kind: string
  underlying: string
  tags: string[]
}
type Payload = {
  personas: Record<string, { label: string; blurb: string }>
  templates: TemplateRow[]
}

const S = {
  page: { padding: '24px 32px', maxWidth: 1100, color: 'var(--text-primary)' } as CSSProperties,
  h1: { fontSize: 22, fontWeight: 700, margin: '0 0 4px' } as CSSProperties,
  sub: { fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 } as CSSProperties,
  chips: { display: 'flex', gap: 8, flexWrap: 'wrap' as const, marginBottom: 20 } as CSSProperties,
  chip: (active: boolean): CSSProperties => ({
    padding: '7px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
    background: active ? 'var(--brand-primary, #f0a020)' : 'var(--bg-elevated)',
    color: active ? '#fff' : 'var(--text-primary)',
    border: '1px solid var(--border-default)', borderRadius: 999,
  }),
  blurb: { fontSize: 12.5, color: 'var(--text-secondary)', marginBottom: 16 } as CSSProperties,
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 } as CSSProperties,
  card: {
    background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
    borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column' as const, gap: 10,
  } as CSSProperties,
  kindBadge: (kind: string): CSSProperties => ({
    display: 'inline-block', padding: '2px 8px', fontSize: 10, fontWeight: 700,
    borderRadius: 999, textTransform: 'uppercase' as const,
    background: kind === 'EQUITY_EOD' ? '#2da14b22' : '#4a9fda22',
    color: kind === 'EQUITY_EOD' ? '#2da14b' : '#4a9fda',
  }),
  name: { fontSize: 15, fontWeight: 700, margin: 0 } as CSSProperties,
  desc: { fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.5, margin: 0, flex: 1 } as CSSProperties,
  meta: { fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' } as CSSProperties,
  useBtn: {
    padding: '8px 14px', fontSize: 12.5, fontWeight: 700, alignSelf: 'flex-start',
    background: 'var(--brand-primary, #f0a020)', color: '#fff',
    border: 'none', borderRadius: 8, cursor: 'pointer',
  } as CSSProperties,
}

export default function Templates() {
  const { user, openGate } = useAuth()
  const toast = useToast()
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [persona, setPersona] = useState<string>(
    () => params.get('persona') || 'swing_equity'
  )

  const { data } = useQuery<Payload>({
    queryKey: ['templates'],
    queryFn: async () => (await api.get('/api/templates')).data,
  })

  const copy = useMutation({
    mutationFn: async (id: string) => (await api.post(`/api/templates/${id}/copy`)).data,
    onSuccess: (d) => {
      toast.push('success', `"${d.name}" copied to your strategies as DRAFT`)
      nav(`/strategies/${d.id}`)
    },
    onError: (e: any) =>
      toast.push('error', e?.response?.data?.detail || 'Copy failed'),
  })

  const useTemplate = (id: string) => {
    if (!user) {
      openGate({
        mode: 'login',
        message: 'Sign in to copy this template into your account.',
        onSuccess: () => copy.mutate(id),
      })
      return
    }
    copy.mutate(id)
  }

  const personas = data?.personas || {}
  const rows = (data?.templates || []).filter(t => t.persona === persona)

  return (
    <div style={S.page}>
      <PageHelp pageId="strategies" />
      <h1 style={S.h1}>Strategy Templates</h1>
      <p style={S.sub}>
        Pick the style that matches how you trade — copy a template, backtest it on real
        data, tweak until it's yours, then promote at your own pace.
      </p>
      <RiskNote>
        Templates are structural starting points, not recommendations. Nothing here is
        investment advice, and no template is claimed to be profitable — backtest and
        judge for yourself. Derivatives and equity trading involve risk of loss.
      </RiskNote>

      <div style={S.chips}>
        {Object.entries(personas).map(([key, p]) => (
          <button key={key} style={S.chip(key === persona)} onClick={() => setPersona(key)}>
            {p.label}
          </button>
        ))}
      </div>
      {personas[persona] && <p style={S.blurb}>{personas[persona].blurb}</p>}

      <div style={S.grid}>
        {rows.map(t => (
          <div key={t.id} style={S.card}>
            <div>
              <span style={S.kindBadge(t.kind)}>
                {t.kind === 'EQUITY_EOD' ? 'Equity · daily' : 'Options · intraday'}
              </span>
            </div>
            <h3 style={S.name}>{t.name}</h3>
            <p style={S.desc}>{t.description}</p>
            <div style={S.meta}>{t.underlying.replace('NSE:', '').replace('-EQ', '').replace('-INDEX', '')}</div>
            <button
              style={{ ...S.useBtn, opacity: copy.isPending ? 0.6 : 1 }}
              disabled={copy.isPending}
              onClick={() => useTemplate(t.id)}
            >
              {copy.isPending ? 'Copying…' : 'Use this template'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

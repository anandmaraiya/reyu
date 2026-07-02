/**
 * ChatUsageMeter — shows the user's current daily chat usage
 * (messages + tokens) alongside their tier limit.
 *
 * Appears in the Chat page header. Two thin progress bars, colored:
 *   green  ≤ 70% consumed
 *   amber  70-90%
 *   red    ≥ 90%
 *
 * Auto-refreshes every 30s and after each successful chat message.
 */
import { useQuery } from '@tanstack/react-query'
import type { CSSProperties } from 'react'
import { api } from '../api'

type Usage = {
  tier: string
  resets_at: string
  usage: { date: string; messages: number; tokens: number }
  limits: { messages: number; tokens: number }
}

const barColor = (pct: number) =>
  pct >= 90 ? 'var(--danger)' :
  pct >= 70 ? 'var(--signal)' :
              'var(--brand-primary)'

const S = {
  wrap: {
    display: 'flex',
    gap: 14,
    alignItems: 'center',
    padding: '6px 12px',
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border-subtle)',
    borderRadius: 'var(--radius-sm)',
    fontSize: 11,
    color: 'var(--text-secondary)',
  } as CSSProperties,
  meter: { display: 'flex', flexDirection: 'column' as const, gap: 3, minWidth: 130 } as CSSProperties,
  label: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 10,
    fontWeight: 500,
    letterSpacing: '0.03em',
  } as CSSProperties,
  track: {
    height: 4,
    background: 'var(--bg-sunken)',
    borderRadius: 2,
    overflow: 'hidden' as const,
  } as CSSProperties,
  fill: (pct: number): CSSProperties => ({
    height: '100%',
    width: `${Math.min(100, pct)}%`,
    background: barColor(pct),
    transition: 'width 200ms',
    borderRadius: 2,
  }),
  tierPill: (isPaid: boolean): CSSProperties => ({
    padding: '2px 8px',
    borderRadius: 'var(--radius-full)',
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.05em',
    textTransform: 'uppercase',
    background: isPaid ? 'var(--brand-light)' : 'var(--bg-sunken)',
    color: isPaid ? 'var(--brand-text)' : 'var(--text-secondary)',
  }),
}

const fmt = (n: number) => n.toLocaleString('en-IN')

export default function ChatUsageMeter() {
  const q = useQuery<Usage>({
    queryKey: ['chat-usage'],
    queryFn: async () => (await api.get('/api/chat/usage')).data,
    refetchInterval: 30_000,
  })

  if (!q.data) return null
  const { tier, usage, limits } = q.data
  const msgPct = limits.messages === -1 ? 0 : (usage.messages / Math.max(1, limits.messages)) * 100
  const tokPct = limits.tokens === -1 ? 0 : (usage.tokens / Math.max(1, limits.tokens)) * 100
  const isPaid = tier === 'pro' || tier === 'algo' || tier === 'superadmin'

  return (
    <div style={S.wrap} title={`Resets at midnight UTC · ${new Date(q.data.resets_at).toLocaleString()}`}>
      <span style={S.tierPill(isPaid)}>{tier}</span>

      <div style={S.meter}>
        <div style={S.label}>
          <span>Messages</span>
          <span>
            {fmt(usage.messages)}
            {limits.messages !== -1 && ` / ${fmt(limits.messages)}`}
            {limits.messages === -1 && ' · unlimited'}
          </span>
        </div>
        <div style={S.track}>
          <div style={S.fill(msgPct)} />
        </div>
      </div>

      <div style={S.meter}>
        <div style={S.label}>
          <span>Tokens</span>
          <span>
            {fmt(usage.tokens)}
            {limits.tokens !== -1 && ` / ${fmt(limits.tokens)}`}
            {limits.tokens === -1 && ' · unlimited'}
          </span>
        </div>
        <div style={S.track}>
          <div style={S.fill(tokPct)} />
        </div>
      </div>
    </div>
  )
}

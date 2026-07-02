/**
 * StrategyJourney — gamified progression ladder from idea to live.
 *
 * Maps a strategy's lifecycle to five visible milestones so users always
 * know where they are and what the next step is:
 *
 *   1. Built        (strategy exists — DRAFT)
 *   2. Backtested   (has run against history — BACKTESTED+)
 *   3. Forward-tested (paper-live scheduler running — PAPER_LIVE+)
 *   4. Authorized   (accepted live-execution legal docs)
 *   5. Live         (deployed to real-money execution — LIVE)
 *
 * This is guidance + motivation, not a control surface — the actual
 * actions (backtest, promote, accept) live in the header/Live tab. The
 * ladder tells users what to do next and celebrates progress.
 */
import { type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchLegalStatus } from '../legal'
import { useAuth } from '../context/AuthContext'

type Status = 'DRAFT' | 'BACKTESTED' | 'PAPER_LIVE' | 'LIVE' | 'ARCHIVED' | string

const STEPS = [
  { key: 'built', icon: '🧩', label: 'Built', hint: 'Strategy created.' },
  { key: 'backtested', icon: '🧪', label: 'Backtested', hint: 'Run it against history to see how it behaved.' },
  { key: 'forward', icon: '📡', label: 'Forward-tested', hint: 'Promote to paper-live — the scheduler paper-trades it in real time.' },
  { key: 'authorized', icon: '✍️', label: 'Authorized', hint: 'Accept the live-execution authorization.' },
  { key: 'live', icon: '🚀', label: 'Live', hint: 'Deployed — real orders fire on signals (Algo tier).' },
]

function stageFromStatus(status: Status, liveOk: boolean): number {
  // Returns count of COMPLETED steps (0..5).
  switch (status) {
    case 'DRAFT': return 1
    case 'BACKTESTED': return 2
    case 'PAPER_LIVE': return liveOk ? 4 : 3
    case 'LIVE': return 5
    default: return 1
  }
}

const S = {
  wrap: {
    border: '1px solid var(--border-default, var(--border))', borderRadius: 10,
    padding: 16, margin: '0 0 16px', background: 'var(--bg-surface, var(--card))',
  } as CSSProperties,
  head: { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 } as CSSProperties,
  title: { fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' } as CSSProperties,
  count: { fontSize: 12, color: 'var(--text-muted, var(--muted))' } as CSSProperties,
  track: { display: 'flex', gap: 6, marginBottom: 12 } as CSSProperties,
  seg: (done: boolean, current: boolean): CSSProperties => ({
    flex: 1, height: 6, borderRadius: 3,
    background: done ? 'var(--brand-primary, #f0a020)' : current ? 'var(--brand-primary, #f0a020)55' : 'var(--bg-sunken, var(--card2))',
  }),
  steps: { display: 'flex', gap: 8, flexWrap: 'wrap' as const } as CSSProperties,
  step: (done: boolean, current: boolean): CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px', borderRadius: 999,
    fontSize: 11.5, fontWeight: 600,
    background: done ? 'var(--brand-primary, #f0a020)22' : current ? 'var(--bg-elevated, var(--card2))' : 'transparent',
    color: done ? 'var(--brand-primary, #f0a020)' : current ? 'var(--text-primary)' : 'var(--text-muted, var(--muted))',
    border: `1px solid ${current ? 'var(--brand-primary, #f0a020)' : 'var(--border-subtle, var(--border))'}`,
    opacity: !done && !current ? 0.6 : 1,
  }),
  next: {
    marginTop: 12, padding: '10px 12px', borderRadius: 8, fontSize: 12.5, lineHeight: 1.5,
    background: 'var(--bg-sunken, var(--card2))', color: 'var(--text-secondary, var(--muted))',
  } as CSSProperties,
  done: {
    marginTop: 12, padding: '10px 12px', borderRadius: 8, fontSize: 12.5,
    background: 'var(--brand-primary, #f0a020)18', color: 'var(--brand-primary, #f0a020)', fontWeight: 600,
  } as CSSProperties,
}

export default function StrategyJourney({ status }: { status: Status }) {
  const { user } = useAuth()
  const { data: legal } = useQuery({
    queryKey: ['legal-status'],
    queryFn: fetchLegalStatus,
    enabled: !!user,
  })
  const liveOk = !!legal?.live_ok
  const completed = stageFromStatus(status, liveOk)
  const nextStep = completed < STEPS.length ? STEPS[completed] : null

  return (
    <div style={S.wrap}>
      <div style={S.head}>
        <span style={S.title}>Reyu Journey — idea to live</span>
        <span style={S.count}>{Math.min(completed, 5)} of 5</span>
      </div>
      <div style={S.track}>
        {STEPS.map((_, i) => (
          <div key={i} style={S.seg(i < completed, i === completed)} />
        ))}
      </div>
      <div style={S.steps}>
        {STEPS.map((st, i) => {
          const done = i < completed
          const current = i === completed
          return (
            <div key={st.key} style={S.step(done, current)}>
              <span>{done ? '✓' : st.icon}</span>
              <span>{st.label}</span>
            </div>
          )
        })}
      </div>
      {nextStep ? (
        <div style={S.next}>
          <b style={{ color: 'var(--text-primary)' }}>Next: {nextStep.label}.</b> {nextStep.hint}
        </div>
      ) : (
        <div style={S.done}>🎉 Live and running. Monitor it in the Live tab — halt any time.</div>
      )}
    </div>
  )
}

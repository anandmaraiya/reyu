/**
 * JourneyGuide — the one path, in plain words, shown on every builder/test page.
 *
 * The platform's whole point is a 5-step ladder from idea to real money:
 *
 *   1. Build   → 2. Backtest → 3. Paper-test → 4. Approve → 5. Go live
 *
 * Anyone (a first-time user, a high-schooler) should be able to look at this
 * strip and know exactly where they are and what comes next. Pass `current`
 * to highlight the active step; each step shows a one-line, jargon-free "what
 * it means".
 */
import type { CSSProperties } from 'react'

export type JourneyStep = 'build' | 'backtest' | 'paper' | 'approve' | 'live'

const STEPS: { key: JourneyStep; n: number; icon: string; title: string; plain: string }[] = [
  { key: 'build',    n: 1, icon: '🧩', title: 'Build',      plain: 'Pick a ready-made strategy or make your own. No coding.' },
  { key: 'backtest', n: 2, icon: '🧪', title: 'Backtest',   plain: 'Replay it on past data to see how it would have done.' },
  { key: 'paper',    n: 3, icon: '📡', title: 'Paper-test', plain: 'Run it live with fake money — no risk, real signals.' },
  { key: 'approve',  n: 4, icon: '✍️', title: 'Approve',    plain: 'Read and accept the risk terms before any real order.' },
  { key: 'live',     n: 5, icon: '🚀', title: 'Go live',    plain: 'Only when YOU choose — real orders via your broker.' },
]

const S: Record<string, any> = {
  wrap: {
    border: '1px solid var(--color-border, var(--border))', borderRadius: 12,
    padding: 14, margin: '0 0 18px', background: 'var(--color-surface, var(--card))',
  },
  head: { fontSize: 12.5, color: 'var(--color-text-secondary, var(--muted))', margin: '0 0 12px' },
  row: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 },
  step: (active: boolean): CSSProperties => ({
    position: 'relative', padding: '10px 12px', borderRadius: 10,
    background: active ? 'rgba(99,102,241,0.10)' : 'var(--color-bg, var(--card2))',
    border: active ? '1px solid rgba(99,102,241,0.45)' : '1px solid transparent',
  }),
  top: { display: 'flex', alignItems: 'center', gap: 7, marginBottom: 4 },
  badge: (active: boolean): CSSProperties => ({
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    width: 18, height: 18, borderRadius: '50%', fontSize: 11, fontWeight: 700,
    background: active ? 'var(--color-primary, var(--brand-primary))' : 'var(--color-border, var(--border))',
    color: active ? '#fff' : 'var(--color-text-secondary, var(--muted))', flexShrink: 0,
  }),
  title: (active: boolean): CSSProperties => ({
    fontSize: 13, fontWeight: 700,
    color: active ? 'var(--color-text-primary, var(--text))' : 'var(--color-text-secondary, var(--muted))',
  }),
  plain: { fontSize: 11.5, lineHeight: 1.45, color: 'var(--color-text-tertiary, var(--muted))' },
}

export default function JourneyGuide({ current, note }: { current?: JourneyStep; note?: string }) {
  return (
    <div style={S.wrap}>
      <div style={S.head}>
        {note || 'The path from idea to real trading — you move at your own pace, and nothing goes live until you say so.'}
      </div>
      <div style={S.row}>
        {STEPS.map(s => {
          const active = s.key === current
          return (
            <div key={s.key} style={S.step(active)}>
              <div style={S.top}>
                <span style={S.badge(active)}>{s.n}</span>
                <span>{s.icon}</span>
                <span style={S.title(active)}>{s.title}</span>
              </div>
              <div style={S.plain}>{s.plain}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

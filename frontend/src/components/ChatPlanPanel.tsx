/**
 * ChatPlanPanel — visible summary of the running multi-turn plan (F-A10).
 *
 * Renders as a floating card in the top-right of the Chat page. Shows
 * goal, underlying, bias, brackets, recent decisions, and next-step
 * hints — everything the LLM sees between turns.
 *
 * Collapsed by default. Click header to expand.
 */
import { useState, type CSSProperties } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'

type Plan = {
  created_at: string
  updated_at: string
  goal: string | null
  underlying: string | null
  bias: string | null
  brackets: { target_pct?: number; stop_pct?: number } | null
  strategy_draft: any
  decisions: { ts: string; choice?: string; why?: string }[]
  next_step: string | null
}

const S = {
  wrap: (open: boolean): CSSProperties => ({
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-md)',
    padding: 0,
    fontSize: 12,
    color: 'var(--text-primary)',
    minWidth: open ? 260 : 130,
    maxWidth: 320,
    boxShadow: 'var(--shadow-sm)',
    overflow: 'hidden',
  }),
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 12px',
    background: 'var(--bg-elevated)',
    borderBottom: '1px solid var(--border-subtle)',
    cursor: 'pointer' as const,
    fontWeight: 600,
    fontSize: 11,
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
    color: 'var(--text-secondary)',
  } as CSSProperties,
  body: { padding: 10 } as CSSProperties,
  row: {
    display: 'grid',
    gridTemplateColumns: '68px 1fr',
    gap: 8,
    padding: '4px 0',
    borderBottom: '1px solid var(--border-subtle)',
    fontSize: 12,
    lineHeight: 1.35,
  } as CSSProperties,
  key: { color: 'var(--text-secondary)', fontWeight: 600, fontSize: 10, textTransform: 'uppercase' as const, letterSpacing: '0.04em', paddingTop: 2 } as CSSProperties,
  val: { color: 'var(--text-primary)', wordBreak: 'break-word' as const } as CSSProperties,
  empty: { color: 'var(--text-muted)', fontSize: 11, padding: '8px 4px' } as CSSProperties,
  actions: {
    display: 'flex', gap: 6, marginTop: 8, justifyContent: 'flex-end',
  } as CSSProperties,
  btn: {
    padding: '4px 8px',
    fontSize: 10,
    fontWeight: 600,
    color: 'var(--text-secondary)',
    background: 'transparent',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
  } as CSSProperties,
}

const isEmpty = (p: Plan | undefined) =>
  !p || (!p.goal && !p.underlying && !p.bias && !p.brackets && (!p.decisions || p.decisions.length === 0) && !p.next_step)

export default function ChatPlanPanel({ sessionId }: { sessionId: string | null }) {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()

  const q = useQuery<Plan>({
    queryKey: ['chat-plan', sessionId],
    queryFn: async () => (await api.get(`/api/chat/plan/${sessionId}`)).data,
    enabled: !!sessionId,
    refetchInterval: 15_000,
  })

  const clear = useMutation({
    mutationFn: async () => (await api.delete(`/api/chat/plan/${sessionId}`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat-plan', sessionId] }),
  })

  if (!sessionId) return null
  const plan = q.data
  const empty = isEmpty(plan)

  return (
    <div style={S.wrap(open)}>
      <div style={S.header} onClick={() => setOpen(o => !o)}>
        <span>{empty ? 'Plan · empty' : 'Session Plan'}</span>
        <span>{open ? '▾' : '▸'}</span>
      </div>

      {open && (
        <div style={S.body}>
          {empty && (
            <div style={S.empty}>
              Ask Reyu a strategy question — the plan will auto-fill as the
              conversation develops (goal, symbol, bias, brackets, decisions).
            </div>
          )}
          {plan?.goal && <div style={S.row}><span style={S.key}>Goal</span><span style={S.val}>{plan.goal}</span></div>}
          {plan?.underlying && <div style={S.row}><span style={S.key}>Symbol</span><span style={S.val}>{plan.underlying}</span></div>}
          {plan?.bias && <div style={S.row}><span style={S.key}>Bias</span><span style={S.val}>{plan.bias}</span></div>}
          {plan?.brackets && (plan.brackets.target_pct != null || plan.brackets.stop_pct != null) && (
            <div style={S.row}>
              <span style={S.key}>Brackets</span>
              <span style={S.val}>
                +{plan.brackets.target_pct != null ? (plan.brackets.target_pct * 100).toFixed(0) + '%' : '—'} / −
                {plan.brackets.stop_pct != null ? (plan.brackets.stop_pct * 100).toFixed(0) + '%' : '—'}
              </span>
            </div>
          )}
          {plan?.decisions && plan.decisions.length > 0 && (
            <div style={S.row}>
              <span style={S.key}>Recent</span>
              <span style={S.val}>
                {plan.decisions.slice(-3).map((d, i) => (
                  <div key={i} style={{ marginBottom: 3 }}>
                    <span style={{ fontWeight: 500 }}>{d.choice || '—'}</span>
                    {d.why && <span style={{ color: 'var(--text-secondary)' }}> · {d.why}</span>}
                  </div>
                ))}
              </span>
            </div>
          )}
          {plan?.next_step && <div style={S.row}><span style={S.key}>Next</span><span style={S.val}>{plan.next_step}</span></div>}

          {!empty && (
            <div style={S.actions}>
              <button style={S.btn} onClick={() => clear.mutate()}>Reset plan</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

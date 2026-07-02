/**
 * LegalGate — blocking acceptance gate for the mandatory platform legal
 * documents (Terms of Use, SEBI/NSE risk disclosure, privacy policy).
 *
 * Mounted globally in the app shell. For a signed-in user it checks
 * /api/legal/status; if any platform document is unaccepted (or its
 * version bumped), it renders a full-screen modal that the user must
 * clear by reading and accepting each pending document before continuing.
 *
 * LIVE-execution authorization is a separate gate handled at the point of
 * LIVE deployment (StrategyDetail), not here.
 */
import { useState, type CSSProperties } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import { fetchLegalStatus, fetchLegalDoc, acceptLegalDocs, type LegalDocMeta } from '../legal'
import Markdown from './Markdown'

const S = {
  backdrop: {
    position: 'fixed' as const, inset: 0, background: 'var(--bg-overlay, rgba(0,0,0,.6))',
    zIndex: 2000, display: 'grid', placeItems: 'center', padding: 20,
  } as CSSProperties,
  modal: {
    background: 'var(--bg-surface)', borderRadius: 'var(--radius-md, 10px)',
    padding: 24, maxWidth: 640, width: '100%', maxHeight: '90vh',
    display: 'flex', flexDirection: 'column' as const,
    boxShadow: 'var(--shadow-lg)', border: '1px solid var(--border-default)',
  } as CSSProperties,
  title: { fontSize: 18, fontWeight: 700, margin: '0 0 4px', color: 'var(--text-primary)' } as CSSProperties,
  sub: { fontSize: 13, color: 'var(--text-secondary)', margin: '0 0 16px', lineHeight: 1.5 } as CSSProperties,
  scroller: { overflowY: 'auto' as const, flex: 1, marginBottom: 16, paddingRight: 4 } as CSSProperties,
  docCard: {
    border: '1px solid var(--border-default)', borderRadius: 8, marginBottom: 12,
    overflow: 'hidden',
  } as CSSProperties,
  docHead: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '12px 14px', cursor: 'pointer', background: 'var(--bg-elevated)',
  } as CSSProperties,
  docTitle: { fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' } as CSSProperties,
  docSummary: { fontSize: 12, color: 'var(--text-muted)', marginTop: 2 } as CSSProperties,
  body: { padding: '4px 14px 14px', maxHeight: 260, overflowY: 'auto' as const } as CSSProperties,
  checkRow: {
    display: 'flex', gap: 10, alignItems: 'flex-start', padding: '10px 14px',
    borderTop: '1px solid var(--border-subtle)', fontSize: 13, color: 'var(--text-primary)',
  } as CSSProperties,
  accept: (enabled: boolean): CSSProperties => ({
    padding: '10px 18px', fontSize: 14, fontWeight: 600, border: 'none',
    borderRadius: 8, width: '100%',
    background: enabled ? 'var(--brand-primary, #f0a020)' : 'var(--bg-sunken)',
    color: enabled ? '#fff' : 'var(--text-muted)',
    cursor: enabled ? 'pointer' : 'not-allowed',
  }),
  logout: {
    marginTop: 10, background: 'none', border: 'none', color: 'var(--text-muted)',
    fontSize: 12, cursor: 'pointer', textDecoration: 'underline', width: '100%',
  } as CSSProperties,
}

function DocSection({ doc, checked, onToggle }: {
  doc: LegalDocMeta; checked: boolean; onToggle: () => void
}) {
  const [open, setOpen] = useState(false)
  const { data } = useQuery({
    queryKey: ['legal-doc', doc.doc_type],
    queryFn: () => fetchLegalDoc(doc.doc_type),
    enabled: open,
  })
  return (
    <div style={S.docCard}>
      <div style={S.docHead} onClick={() => setOpen(o => !o)}>
        <div>
          <div style={S.docTitle}>{doc.title}</div>
          <div style={S.docSummary}>{doc.summary}</div>
        </div>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{open ? '▲ Hide' : '▼ Read'}</span>
      </div>
      {open && (
        <div style={S.body}>
          {data ? <Markdown text={data.body} /> : <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading…</div>}
        </div>
      )}
      <label style={S.checkRow}>
        <input type="checkbox" checked={checked} onChange={onToggle} style={{ marginTop: 2 }} />
        <span>I have read and agree to the <b>{doc.title}</b>.</span>
      </label>
    </div>
  )
}

export default function LegalGate() {
  const { user, logout } = useAuth()
  const qc = useQueryClient()
  const [checks, setChecks] = useState<Record<string, boolean>>({})

  const { data: status } = useQuery({
    queryKey: ['legal-status'],
    queryFn: fetchLegalStatus,
    enabled: !!user,
  })

  const accept = useMutation({
    mutationFn: (items: { doc_type: string; version: number }[]) => acceptLegalDocs(items),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['legal-status'] })
      setChecks({})
    },
  })

  // Only gate signed-in users with outstanding platform docs.
  if (!user || !status || status.platform_pending.length === 0) return null

  const pending = status.platform_pending
  const allChecked = pending.every(d => checks[d.doc_type])

  return (
    <div style={S.backdrop}>
      <div style={S.modal}>
        <h2 style={S.title}>Before you continue</h2>
        <p style={S.sub}>
          Reyu is a strategy-automation platform — it does not provide investment advice
          or manage your money. Trading in derivatives is high-risk. Please review and
          accept the following to keep using Reyu.
        </p>
        <div style={S.scroller}>
          {pending.map(doc => (
            <DocSection
              key={doc.doc_type}
              doc={doc}
              checked={!!checks[doc.doc_type]}
              onToggle={() => setChecks(c => ({ ...c, [doc.doc_type]: !c[doc.doc_type] }))}
            />
          ))}
        </div>
        <button
          style={S.accept(allChecked && !accept.isPending)}
          disabled={!allChecked || accept.isPending}
          onClick={() => accept.mutate(pending.map(d => ({ doc_type: d.doc_type, version: d.version })))}
        >
          {accept.isPending ? 'Recording…' : 'I Accept & Continue'}
        </button>
        <button style={S.logout} onClick={() => logout()}>
          Not now — sign out
        </button>
      </div>
    </div>
  )
}

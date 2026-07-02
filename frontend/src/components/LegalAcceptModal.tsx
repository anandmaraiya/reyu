/**
 * LegalAcceptModal — reusable acceptance modal for a specific set of legal
 * documents. Used for the LIVE-execution authorization gate (and any other
 * point-of-action legal acceptance beyond the global platform gate).
 *
 * Renders each document with expandable full text + a per-doc checkbox,
 * records acceptance via /api/legal/accept, and calls onAccepted() so the
 * caller can retry the gated action (e.g. re-attempt LIVE promotion).
 */
import { useState, type CSSProperties } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchLegalDoc, acceptLegalDocs, type LegalDocMeta } from '../legal'
import Markdown from './Markdown'

const S = {
  backdrop: {
    position: 'fixed' as const, inset: 0, background: 'var(--bg-overlay, rgba(0,0,0,.6))',
    zIndex: 2100, display: 'grid', placeItems: 'center', padding: 20,
  } as CSSProperties,
  modal: {
    background: 'var(--bg-surface)', borderRadius: 'var(--radius-md, 10px)', padding: 24,
    maxWidth: 600, width: '100%', maxHeight: '88vh', display: 'flex', flexDirection: 'column' as const,
    boxShadow: 'var(--shadow-lg)', border: '1px solid var(--border-default)',
  } as CSSProperties,
  title: { fontSize: 17, fontWeight: 700, margin: '0 0 4px', color: 'var(--text-primary)' } as CSSProperties,
  sub: { fontSize: 13, color: 'var(--text-secondary)', margin: '0 0 14px', lineHeight: 1.5 } as CSSProperties,
  scroller: { overflowY: 'auto' as const, flex: 1, marginBottom: 14 } as CSSProperties,
  card: { border: '1px solid var(--border-default)', borderRadius: 8, marginBottom: 10, overflow: 'hidden' } as CSSProperties,
  head: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', cursor: 'pointer', background: 'var(--bg-elevated)' } as CSSProperties,
  headTitle: { fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' } as CSSProperties,
  body: { padding: '4px 12px 12px', maxHeight: 240, overflowY: 'auto' as const } as CSSProperties,
  check: { display: 'flex', gap: 10, alignItems: 'flex-start', padding: '10px 12px', borderTop: '1px solid var(--border-subtle)', fontSize: 13, color: 'var(--text-primary)' } as CSSProperties,
  btnRow: { display: 'flex', gap: 8, justifyContent: 'flex-end' } as CSSProperties,
  cancel: { padding: '9px 16px', fontSize: 13, background: 'var(--bg-elevated)', color: 'var(--text-primary)', border: '1px solid var(--border-default)', borderRadius: 8, cursor: 'pointer' } as CSSProperties,
  accept: (on: boolean): CSSProperties => ({
    padding: '9px 18px', fontSize: 13, fontWeight: 600, border: 'none', borderRadius: 8,
    background: on ? 'var(--brand-primary, #f0a020)' : 'var(--bg-sunken)',
    color: on ? '#fff' : 'var(--text-muted)', cursor: on ? 'pointer' : 'not-allowed',
  }),
}

function Section({ doc, checked, onToggle }: { doc: LegalDocMeta; checked: boolean; onToggle: () => void }) {
  const [open, setOpen] = useState(false)
  const { data } = useQuery({ queryKey: ['legal-doc', doc.doc_type], queryFn: () => fetchLegalDoc(doc.doc_type), enabled: open })
  return (
    <div style={S.card}>
      <div style={S.head} onClick={() => setOpen(o => !o)}>
        <div>
          <div style={S.headTitle}>{doc.title}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{doc.summary}</div>
        </div>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{open ? '▲ Hide' : '▼ Read'}</span>
      </div>
      {open && <div style={S.body}>{data ? <Markdown text={data.body} /> : <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading…</div>}</div>}
      <label style={S.check}>
        <input type="checkbox" checked={checked} onChange={onToggle} style={{ marginTop: 2 }} />
        <span>I have read and agree to the <b>{doc.title}</b>.</span>
      </label>
    </div>
  )
}

export default function LegalAcceptModal({
  docs, title = 'Authorization required', subtitle, onClose, onAccepted,
}: {
  docs: LegalDocMeta[]
  title?: string
  subtitle?: string
  onClose: () => void
  onAccepted: () => void
}) {
  const qc = useQueryClient()
  const [checks, setChecks] = useState<Record<string, boolean>>({})
  const accept = useMutation({
    mutationFn: () => acceptLegalDocs(docs.map(d => ({ doc_type: d.doc_type, version: d.version }))),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['legal-status'] })
      onAccepted()
    },
  })
  const allChecked = docs.every(d => checks[d.doc_type])
  return (
    <div style={S.backdrop} onClick={onClose}>
      <div style={S.modal} onClick={e => e.stopPropagation()}>
        <h2 style={S.title}>{title}</h2>
        <p style={S.sub}>{subtitle || 'Please review and accept the following before continuing.'}</p>
        <div style={S.scroller}>
          {docs.map(d => (
            <Section key={d.doc_type} doc={d} checked={!!checks[d.doc_type]}
              onToggle={() => setChecks(c => ({ ...c, [d.doc_type]: !c[d.doc_type] }))} />
          ))}
        </div>
        <div style={S.btnRow}>
          <button style={S.cancel} onClick={onClose}>Cancel</button>
          <button style={S.accept(allChecked && !accept.isPending)} disabled={!allChecked || accept.isPending}
            onClick={() => accept.mutate()}>
            {accept.isPending ? 'Recording…' : 'Accept & Continue'}
          </button>
        </div>
      </div>
    </div>
  )
}

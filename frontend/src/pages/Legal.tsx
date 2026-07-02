/**
 * Legal — public viewer for Reyu's legal & compliance documents.
 *
 * Route: /legal            → index of all documents
 *        /legal/:docType   → full text of one document
 *
 * Documents are served from /api/legal/docs (public, no auth) so anyone
 * can read them before signing up. Acceptance is recorded separately via
 * the LegalGate (platform docs) and the LIVE-deployment flow.
 */
import { type CSSProperties } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchLegalDocs, fetchLegalDoc } from '../legal'
import Markdown from '../components/Markdown'

const S = {
  page: { padding: '24px 32px', maxWidth: 820, margin: '0 auto', color: 'var(--text-primary)' } as CSSProperties,
  h1: { fontSize: 24, fontWeight: 700, margin: '0 0 6px' } as CSSProperties,
  sub: { fontSize: 13, color: 'var(--text-secondary)', marginBottom: 24, lineHeight: 1.5 } as CSSProperties,
  card: {
    display: 'block', textDecoration: 'none', border: '1px solid var(--border-default)',
    borderRadius: 8, padding: 16, marginBottom: 12, background: 'var(--bg-surface)',
  } as CSSProperties,
  cardTitle: { fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 } as CSSProperties,
  cardSummary: { fontSize: 13, color: 'var(--text-secondary)' } as CSSProperties,
  meta: { fontSize: 11, color: 'var(--text-muted)', marginTop: 6 } as CSSProperties,
  back: { fontSize: 13, color: 'var(--brand-primary, #f0a020)', textDecoration: 'none', display: 'inline-block', marginBottom: 16 } as CSSProperties,
}

function LegalIndex() {
  const { data } = useQuery({ queryKey: ['legal-docs'], queryFn: fetchLegalDocs })
  return (
    <div style={S.page}>
      <h1 style={S.h1}>Legal & Compliance</h1>
      <p style={S.sub}>
        Reyu is an AI-powered trading-strategy automation platform. It does not provide
        investment advice, does not manage portfolios, and does not claim any strategy is
        profitable. Trading in derivatives is high-risk. These documents govern your use of
        the platform.
      </p>
      {data?.docs.map(d => (
        <Link key={d.doc_type} to={`/legal/${d.doc_type}`} style={S.card}>
          <div style={S.cardTitle}>{d.title}</div>
          <div style={S.cardSummary}>{d.summary}</div>
          <div style={S.meta}>v{d.version} · effective {d.effective_date}</div>
        </Link>
      ))}
    </div>
  )
}

function LegalDocView({ docType }: { docType: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['legal-doc', docType],
    queryFn: () => fetchLegalDoc(docType),
  })
  return (
    <div style={S.page}>
      <Link to="/legal" style={S.back}>← All documents</Link>
      {isLoading && <div style={{ color: 'var(--text-muted)' }}>Loading…</div>}
      {isError && <div style={{ color: 'var(--text-muted)' }}>Document not found.</div>}
      {data && (
        <>
          <div style={S.meta}>v{data.version} · effective {data.effective_date}</div>
          <Markdown text={data.body} />
        </>
      )}
    </div>
  )
}

export default function Legal() {
  const { docType } = useParams<{ docType: string }>()
  return docType ? <LegalDocView docType={docType} /> : <LegalIndex />
}

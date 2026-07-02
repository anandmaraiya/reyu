/**
 * PageHelp — floating "?" button that opens a side drawer with docs
 * explaining what the current page does and how to use it.
 *
 * Usage on any page:
 *   <PageHelp pageId="charts" />
 *
 * Content lives in `pageDocs.ts` so it's grep-able and updatable
 * without touching each page component.
 */
import { useState, useEffect, type CSSProperties } from 'react'
import { pageDocs, type PageDoc } from '../pageDocs'

const S = {
  fab: {
    position: 'fixed' as const,
    bottom: 20,
    right: 20,
    width: 40,
    height: 40,
    borderRadius: '50%',
    background: 'var(--brand-primary)',
    color: '#fff',
    border: 'none',
    boxShadow: 'var(--shadow-md)',
    cursor: 'pointer',
    fontSize: 18,
    fontWeight: 700,
    zIndex: 60,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'transform 120ms',
  } as CSSProperties,
  backdrop: {
    position: 'fixed' as const,
    inset: 0,
    background: 'var(--bg-overlay)',
    zIndex: 70,
    animation: 'fade-in 150ms',
  } as CSSProperties,
  drawer: {
    position: 'fixed' as const,
    top: 0, right: 0, bottom: 0,
    width: 380,
    maxWidth: '92vw',
    background: 'var(--bg-surface)',
    borderLeft: '1px solid var(--border-default)',
    boxShadow: 'var(--shadow-lg)',
    padding: '20px 22px',
    overflowY: 'auto' as const,
    zIndex: 80,
    animation: 'slide-in 200ms var(--ease-out)',
    color: 'var(--text-primary)',
  } as CSSProperties,
  close: {
    position: 'absolute' as const,
    top: 12, right: 14,
    width: 28, height: 28,
    background: 'transparent',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    color: 'var(--text-secondary)',
    fontSize: 14,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  } as CSSProperties,
  title: { fontSize: 18, fontWeight: 700, margin: '0 0 6px 0' } as CSSProperties,
  subtitle: { fontSize: 12, color: 'var(--text-secondary)', marginBottom: 16 } as CSSProperties,
  section: { marginTop: 18 } as CSSProperties,
  sectionTitle: {
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--text-secondary)',
    letterSpacing: '0.06em',
    textTransform: 'uppercase' as const,
    marginBottom: 8,
  } as CSSProperties,
  bodyText: {
    fontSize: 13,
    lineHeight: 1.5,
    color: 'var(--text-primary)',
    marginBottom: 12,
  } as CSSProperties,
  bullet: {
    display: 'flex',
    gap: 10,
    fontSize: 13,
    lineHeight: 1.4,
    padding: '6px 0',
    borderBottom: '1px solid var(--border-subtle)',
  } as CSSProperties,
  bulletKey: {
    minWidth: 90, maxWidth: 120,
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--text-secondary)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
    paddingTop: 1,
  } as CSSProperties,
  bulletVal: { flex: 1, color: 'var(--text-primary)' } as CSSProperties,
  tip: {
    padding: '10px 12px',
    background: 'var(--brand-light)',
    color: 'var(--brand-text)',
    borderRadius: 'var(--radius-sm)',
    fontSize: 12,
    lineHeight: 1.5,
    marginBottom: 8,
  } as CSSProperties,
  footer: {
    marginTop: 24,
    fontSize: 11,
    color: 'var(--text-muted)',
    borderTop: '1px solid var(--border-subtle)',
    paddingTop: 12,
  } as CSSProperties,
}

export default function PageHelp({ pageId }: { pageId: keyof typeof pageDocs }) {
  const [open, setOpen] = useState(false)
  const doc: PageDoc | undefined = pageDocs[pageId]

  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open])

  if (!doc) return null

  return (
    <>
      <button
        style={S.fab}
        onClick={() => setOpen(true)}
        aria-label="How this page works"
        title="How this page works"
      >
        ?
      </button>

      {open && (
        <>
          <div style={S.backdrop} onClick={() => setOpen(false)} />
          <div style={S.drawer} role="dialog" aria-modal="true">
            <button style={S.close} onClick={() => setOpen(false)} aria-label="Close help">✕</button>

            <h2 style={S.title}>{doc.title}</h2>
            <div style={S.subtitle}>{doc.subtitle}</div>

            <div style={S.section}>
              <div style={S.sectionTitle}>What this page does</div>
              <p style={S.bodyText}>{doc.what}</p>
            </div>

            {doc.actions && doc.actions.length > 0 && (
              <div style={S.section}>
                <div style={S.sectionTitle}>Actions you can take</div>
                {doc.actions.map((a, i) => (
                  <div key={i} style={S.bullet}>
                    <div style={S.bulletKey}>{a.name}</div>
                    <div style={S.bulletVal}>{a.detail}</div>
                  </div>
                ))}
              </div>
            )}

            {doc.tips && doc.tips.length > 0 && (
              <div style={S.section}>
                <div style={S.sectionTitle}>Tips</div>
                {doc.tips.map((t, i) => (
                  <div key={i} style={S.tip}>💡 {t}</div>
                ))}
              </div>
            )}

            {doc.blocked && doc.blocked.length > 0 && (
              <div style={S.section}>
                <div style={S.sectionTitle}>What you can't do here</div>
                {doc.blocked.map((b, i) => (
                  <div key={i} style={{ ...S.tip, background: 'var(--danger-light)', color: 'var(--danger-text)' }}>
                    ⛔ {b}
                  </div>
                ))}
              </div>
            )}

            <div style={S.footer}>
              Have feedback on this page? Reply to any Reyu email with your thoughts.
            </div>
          </div>
        </>
      )}

      <style>{`
        @keyframes slide-in {
          from { transform: translateX(100%); }
          to   { transform: translateX(0); }
        }
      `}</style>
    </>
  )
}

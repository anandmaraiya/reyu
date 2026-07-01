/**
 * Confirmation modal for irreversible / financially-sensitive actions.
 *
 * Per PRODUCT_SPEC §3, the following actions require typed-symbol
 * confirmation before proceeding:
 *   - P-07 Position exit (LIVE)
 *   - P-11 Broker disconnect (when active paper run exists)
 *   - P-14 Subscription downgrade (with live strategies)
 *   - P-16 Superadmin force-close on real orders
 *
 * User must type the exact `expectedText` (e.g. the position symbol) to
 * enable the Confirm button. Prevents muscle-memory accidents.
 */
import { useState, useEffect, type CSSProperties } from 'react'

type Props = {
  open: boolean
  title: string
  description: string
  expectedText: string          // user must type this exactly to confirm
  confirmLabel?: string
  variant?: 'danger' | 'warning'
  onConfirm: () => void
  onCancel: () => void
  // Optional slot to render preflight results, warnings, extra info
  // between the description and the typed-input.
  children?: React.ReactNode
  // If provided and returns false, submit stays disabled even when
  // typed text matches. Used by preflight FAIL blocks.
  extraGate?: boolean
}

const S = {
  backdrop: {
    position: 'fixed' as const,
    inset: 0,
    background: 'var(--bg-overlay)',
    zIndex: 1000,
    display: 'grid',
    placeItems: 'center',
    padding: 20,
    animation: 'fade-in 150ms ease-out',
  } as CSSProperties,
  modal: {
    background: 'var(--bg-surface)',
    borderRadius: 'var(--radius-md)',
    padding: 24,
    maxWidth: 460,
    width: '100%',
    boxShadow: 'var(--shadow-lg)',
    border: '1px solid var(--border-default)',
    animation: 'slide-up 200ms var(--ease-out)',
  } as CSSProperties,
  title: {
    fontSize: 17,
    fontWeight: 600,
    margin: '0 0 8px 0',
    color: 'var(--text-primary)',
  } as CSSProperties,
  desc: {
    fontSize: 13,
    color: 'var(--text-secondary)',
    lineHeight: 1.5,
    marginBottom: 16,
  } as CSSProperties,
  code: {
    display: 'inline-block',
    padding: '2px 8px',
    background: 'var(--bg-sunken)',
    color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    borderRadius: 'var(--radius-sm)',
    border: '1px solid var(--border-subtle)',
  } as CSSProperties,
  label: {
    display: 'block',
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--text-secondary)',
    marginBottom: 6,
    marginTop: 12,
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
  } as CSSProperties,
  input: {
    width: '100%',
    padding: '10px 12px',
    fontSize: 14,
    fontFamily: 'var(--font-mono)',
    background: 'var(--bg-elevated)',
    color: 'var(--text-primary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
    outline: 'none',
  } as CSSProperties,
  buttons: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 8,
    marginTop: 20,
  } as CSSProperties,
  cancel: {
    padding: '8px 16px',
    fontSize: 13,
    background: 'var(--bg-elevated)',
    color: 'var(--text-primary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    fontWeight: 500,
  } as CSSProperties,
  confirm: (variant: 'danger' | 'warning', enabled: boolean): CSSProperties => ({
    padding: '8px 16px',
    fontSize: 13,
    fontWeight: 600,
    background: enabled
      ? (variant === 'danger' ? 'var(--danger)' : 'var(--signal)')
      : 'var(--bg-sunken)',
    color: enabled ? '#fff' : 'var(--text-muted)',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    cursor: enabled ? 'pointer' : 'not-allowed',
  }),
}

export default function ConfirmDangerModal({
  open,
  title,
  description,
  expectedText,
  confirmLabel = 'Confirm',
  variant = 'danger',
  onConfirm,
  onCancel,
  children,
  extraGate = true,
}: Props) {
  const [typed, setTyped] = useState('')

  // Clear input when modal opens/closes
  useEffect(() => { if (!open) setTyped('') }, [open])

  // Close on ESC
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onCancel()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onCancel])

  if (!open) return null

  const matches = typed === expectedText && extraGate

  return (
    <div style={S.backdrop} onClick={onCancel}>
      <div style={S.modal} onClick={e => e.stopPropagation()}>
        <h2 style={S.title}>{title}</h2>
        <p style={S.desc}>{description}</p>

        {children}

        <p style={S.desc}>
          To confirm, type <span style={S.code}>{expectedText}</span> below.
        </p>

        <label style={S.label}>Type the identifier to confirm</label>
        <input
          type="text"
          style={S.input}
          value={typed}
          onChange={e => setTyped(e.target.value)}
          autoFocus
          autoComplete="off"
          spellCheck={false}
          placeholder={expectedText}
        />

        <div style={S.buttons}>
          <button style={S.cancel} onClick={onCancel}>Cancel</button>
          <button
            style={S.confirm(variant, matches)}
            disabled={!matches}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

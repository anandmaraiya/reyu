/**
 * ResponseCard — standardised wrapper for all Reyu AI responses.
 *
 * Anatomy:
 *   ┌─────────────────────────────────────────────────────┐
 *   │ [QC dot] Title                      freshness  [⋯] │
 *   │ ─────────────────────────────────────────────────── │
 *   │ content slot (text, chart, table, etc.)             │
 *   │ ─────────────────────────────────────────────────── │
 *   │ [📌 Pin]  [↗ Expand]  [📋 Copy]                   │
 *   └─────────────────────────────────────────────────────┘
 *
 * QC dot colours:
 *   green  = live data (< 60 s)
 *   amber  = stale (1–5 min)
 *   grey   = no live data / demo mode
 *   red    = error
 */
import React, { useState } from 'react'
import { istTime } from '../marketHours'

export type QCStatus = 'live' | 'stale' | 'demo' | 'error'

export interface ResponseCardProps {
  title?: string
  fetchedAt?: Date | string | null
  qcStatus?: QCStatus
  demo?: boolean
  children: React.ReactNode
  /** Called when user pins this card to the tray */
  onPin?: () => void
  /** Called when user copies text content */
  onCopy?: () => void
  className?: string
  /** If true, renders compact (no footer actions) */
  compact?: boolean
}

function useAge(fetchedAt?: Date | string | null): { label: string; qc: QCStatus } {
  if (!fetchedAt) return { label: '', qc: 'demo' }
  const ts = typeof fetchedAt === 'string' ? new Date(fetchedAt) : fetchedAt
  const secs = Math.floor((Date.now() - ts.getTime()) / 1000)
  if (secs < 5)   return { label: 'just now', qc: 'live' }
  if (secs < 60)  return { label: `${secs}s ago`, qc: 'live' }
  if (secs < 300) return { label: `${Math.floor(secs / 60)}m ago`, qc: 'stale' }
  return { label: `${Math.floor(secs / 60)}m ago`, qc: 'stale' }
}

const QC_LABELS: Record<QCStatus, string> = {
  live:  'Live',
  stale: 'Stale',
  demo:  'Demo',
  error: 'Error',
}

export function ResponseCard({
  title,
  fetchedAt,
  qcStatus,
  demo,
  children,
  onPin,
  onCopy,
  className = '',
  compact = false,
}: ResponseCardProps) {
  const [pinned, setPinned] = useState(false)
  const { label: ageLabel, qc: derivedQC } = useAge(fetchedAt)
  const qc: QCStatus = demo ? 'demo' : qcStatus ?? derivedQC

  function handlePin() {
    setPinned(p => !p)
    onPin?.()
  }

  function handleCopy() {
    const text = document.querySelector('.rc-body')?.textContent ?? ''
    navigator.clipboard.writeText(text).catch(() => {})
    onCopy?.()
  }

  return (
    <div className={`response-card ${className}`} role="article">
      {/* Header */}
      {(title || fetchedAt || qcStatus) && (
        <div className="rc-header">
          <div className="rc-header-left">
            <span className={`qc-dot qc-${qc}`} title={QC_LABELS[qc]} aria-label={`Data status: ${QC_LABELS[qc]}`} />
            {title && <span className="rc-title">{title}</span>}
          </div>
          <div className="rc-header-right">
            {demo && <span className="rc-badge demo-tag">DEMO</span>}
            {ageLabel && <span className="rc-age" title={fetchedAt ? istTime(fetchedAt) : ''}>{ageLabel}</span>}
          </div>
        </div>
      )}

      {/* Body */}
      <div className="rc-body">{children}</div>

      {/* Footer actions */}
      {!compact && (onPin || onCopy) && (
        <div className="rc-footer">
          {onPin && (
            <button
              className={`rc-action ${pinned ? 'rc-action-active' : ''}`}
              onClick={handlePin}
              title={pinned ? 'Unpin from tray' : 'Pin to tray'}
            >
              <PinIcon filled={pinned} />
              <span>{pinned ? 'Pinned' : 'Pin'}</span>
            </button>
          )}
          {onCopy && (
            <button className="rc-action" onClick={handleCopy} title="Copy response">
              <CopyIcon />
              <span>Copy</span>
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ── NoDataState ────────────────────────────────────────────────────────────────

export type NoDataVariant = 'no-data' | 'loading' | 'error' | 'demo' | 'no-broker'

export interface NoDataStateProps {
  variant?: NoDataVariant
  title?: string
  message?: string
  action?: { label: string; onClick: () => void }
}

const NO_DATA_DEFAULTS: Record<NoDataVariant, { icon: string; title: string; message: string }> = {
  'no-data':   { icon: '📭', title: 'No data available', message: 'There\'s nothing here yet. Try a different query or time range.' },
  'loading':   { icon: '⏳', title: 'Fetching live data…', message: 'Connecting to market feed. This takes a moment.' },
  'error':     { icon: '⚠️', title: 'Something went wrong', message: 'Market data couldn\'t be fetched. Check your connection and try again.' },
  'demo':      { icon: '🧪', title: 'Demo mode', message: 'Showing sample data. Connect a broker to see your live positions and real quotes.' },
  'no-broker': { icon: '🔗', title: 'No broker connected', message: 'Connect Fyers, Zerodha, or AngelOne to fetch live data, positions, and place orders.' },
}

export function NoDataState({ variant = 'no-data', title, message, action }: NoDataStateProps) {
  const defaults = NO_DATA_DEFAULTS[variant]
  return (
    <div className={`no-data-state no-data-${variant}`} role="status" aria-live="polite">
      <span className="no-data-icon" aria-hidden="true">{defaults.icon}</span>
      <h3 className="no-data-title">{title ?? defaults.title}</h3>
      <p className="no-data-msg">{message ?? defaults.message}</p>
      {action && (
        <button className="no-data-action" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </div>
  )
}

// ── Strategy lifecycle strip ───────────────────────────────────────────────────

export type StrategyStage = 'created' | 'backtest' | 'paper' | 'paper-live' | 'live'

const STAGES: { id: StrategyStage; label: string }[] = [
  { id: 'created',    label: 'Created' },
  { id: 'backtest',   label: 'Backtest' },
  { id: 'paper',      label: 'Paper' },
  { id: 'paper-live', label: 'Paper-Live' },
  { id: 'live',       label: '🔴 Live' },
]

export function StrategyLifecycleStrip({ current }: { current: StrategyStage }) {
  const currentIdx = STAGES.findIndex(s => s.id === current)
  return (
    <div className="strategy-strip" role="progressbar" aria-label={`Strategy stage: ${current}`}>
      {STAGES.map((stage, i) => (
        <React.Fragment key={stage.id}>
          <div className={`strip-step ${i <= currentIdx ? 'strip-done' : ''} ${i === currentIdx ? 'strip-current' : ''}`}>
            <div className="strip-dot" />
            <span className="strip-label">{stage.label}</span>
          </div>
          {i < STAGES.length - 1 && (
            <div className={`strip-connector ${i < currentIdx ? 'strip-connector-done' : ''}`} />
          )}
        </React.Fragment>
      ))}
    </div>
  )
}

// ── Icons ──────────────────────────────────────────────────────────────────────
function PinIcon({ filled }: { filled: boolean }) {
  return filled
    ? <svg width="13" height="13" viewBox="0 0 24 24" fill="var(--color-primary)" stroke="var(--color-primary)" strokeWidth="1.5"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17 5.8 21.3l2.4-7.4L2 9.4h7.6z"/></svg>
    : <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17 5.8 21.3l2.4-7.4L2 9.4h7.6z"/></svg>
}
function CopyIcon() {
  return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
}

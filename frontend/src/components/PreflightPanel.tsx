/**
 * PreflightPanel — visual for /api/orders/preflight results.
 *
 * Renders check-by-check with green/amber/red status icons plus a
 * summary strip (contracts, est margin, funds).
 *
 * Used inside ConfirmDangerModal for LIVE order flows.
 */
import type { CSSProperties } from 'react'

type Check = { check: string; status: 'PASS' | 'WARN' | 'FAIL'; detail: string }
type Summary = {
  legs: number
  contracts_total: number
  margin_estimate_inr: number
  funds_available_inr: number
  checked_at: string
}

export type PreflightResult = {
  verdict: 'PASS' | 'WARN' | 'FAIL'
  checks: Check[]
  summary: Summary
}

const S = {
  wrap: {
    marginBottom: 12,
    background: 'var(--bg-sunken)',
    border: '1px solid var(--border-subtle)',
    borderRadius: 'var(--radius-sm)',
    padding: 12,
    fontSize: 12,
  } as CSSProperties,
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
    fontWeight: 600,
    fontSize: 11,
    letterSpacing: '0.04em',
    textTransform: 'uppercase' as const,
    color: 'var(--text-secondary)',
  } as CSSProperties,
  verdictPill: (v: 'PASS' | 'WARN' | 'FAIL'): CSSProperties => ({
    padding: '2px 10px',
    borderRadius: 'var(--radius-full)',
    fontSize: 11,
    fontWeight: 700,
    color: '#fff',
    background:
      v === 'PASS' ? 'var(--brand-primary)' :
      v === 'WARN' ? 'var(--signal)' :
      'var(--danger)',
  }),
  check: {
    display: 'flex',
    gap: 8,
    marginBottom: 6,
    alignItems: 'flex-start',
  } as CSSProperties,
  icon: (status: 'PASS' | 'WARN' | 'FAIL'): CSSProperties => ({
    width: 16, height: 16, borderRadius: 8,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 11, fontWeight: 700, color: '#fff',
    background:
      status === 'PASS' ? 'var(--brand-primary)' :
      status === 'WARN' ? 'var(--signal)' :
      'var(--danger)',
    flexShrink: 0, marginTop: 1,
  }),
  detail: {
    flex: 1,
    color: 'var(--text-primary)',
    lineHeight: 1.4,
  } as CSSProperties,
  summary: {
    marginTop: 10,
    paddingTop: 8,
    borderTop: '1px solid var(--border-subtle)',
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: 8,
    fontSize: 11,
  } as CSSProperties,
  summaryLabel: { color: 'var(--text-secondary)' } as CSSProperties,
  summaryValue: {
    color: 'var(--text-primary)',
    fontWeight: 600,
    fontFamily: 'var(--font-mono)',
    marginTop: 2,
  } as CSSProperties,
}

const inr = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

export default function PreflightPanel({ result, loading }: { result: PreflightResult | null; loading: boolean }) {
  if (loading) {
    return (
      <div style={S.wrap}>
        <div style={S.header}>
          <span>Preflight checks</span>
        </div>
        <div style={{ color: 'var(--text-secondary)' }}>Validating…</div>
      </div>
    )
  }
  if (!result) return null

  return (
    <div style={S.wrap}>
      <div style={S.header}>
        <span>Preflight checks</span>
        <span style={S.verdictPill(result.verdict)}>{result.verdict}</span>
      </div>
      {result.checks.map((c, i) => (
        <div key={i} style={S.check}>
          <div style={S.icon(c.status)}>
            {c.status === 'PASS' ? '✓' : c.status === 'WARN' ? '!' : '✕'}
          </div>
          <div style={S.detail}>{c.detail}</div>
        </div>
      ))}
      <div style={S.summary}>
        <div>
          <div style={S.summaryLabel}>Contracts</div>
          <div style={S.summaryValue}>{result.summary.contracts_total}</div>
        </div>
        <div>
          <div style={S.summaryLabel}>Est. margin</div>
          <div style={S.summaryValue}>{inr(result.summary.margin_estimate_inr)}</div>
        </div>
        <div>
          <div style={S.summaryLabel}>Available</div>
          <div style={S.summaryValue}>{inr(result.summary.funds_available_inr)}</div>
        </div>
      </div>
    </div>
  )
}

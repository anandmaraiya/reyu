/**
 * RiskNote — compact, reusable compliance disclaimer.
 *
 * Dropped onto surfaces where users browse or evaluate strategies
 * (catalog, shared strategy detail) to make the platform's stance
 * explicit: strategies are user-published, not vetted or ranked by
 * performance, no profitability is claimed, and past/backtested results
 * do not predict the future. Not investment advice.
 */
import { type CSSProperties } from 'react'
import { Link } from 'react-router-dom'

const wrap: CSSProperties = {
  display: 'flex', gap: 8, alignItems: 'flex-start',
  padding: '10px 14px', margin: '0 0 16px',
  background: 'var(--bg-sunken)', border: '1px solid var(--border-subtle)',
  borderRadius: 8, fontSize: 11.5, lineHeight: 1.5, color: 'var(--text-secondary)',
}

export default function RiskNote({ children, style }: { children?: React.ReactNode; style?: CSSProperties }) {
  return (
    <div style={{ ...wrap, ...style }}>
      <span aria-hidden style={{ fontSize: 13 }}>⚠️</span>
      <span>
        {children || (
          <>
            Strategies here are published by users, not vetted, endorsed, or ranked by
            performance. Reyu makes no claim that any strategy is profitable — backtested and
            past results do not predict future outcomes. This is not investment advice, and
            derivatives trading is high-risk. See{' '}
            <Link to="/legal" style={{ color: 'var(--brand-primary, #f0a020)' }}>Legal &amp; Risk</Link>.
          </>
        )}
      </span>
    </div>
  )
}

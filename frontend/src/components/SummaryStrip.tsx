import { Chain } from '../api'
import Tooltip from './Tooltip'

const fmt = (n: number | null | undefined, d = 2) =>
  n === null || n === undefined || Number.isNaN(n) ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

const biasClass = (b: string) =>
  b.includes('BULL') ? 'bull' : b.includes('BEAR') ? 'bear' : 'neutral'

export default function SummaryStrip({ chain }: { chain: Chain }) {
  const s = chain.summary
  const b = chain.bias
  return (
    <div className="summary-strip">
      <div className="summary-card">
        <div className="summary-card-header">
          <span>Underlying</span>
          <Tooltip content="Current spot quote for the loaded instrument">i</Tooltip>
        </div>
        <div className="summary-card-value">{fmt(chain.ltp)}</div>
      </div>

      <div className="summary-card">
        <div className="summary-card-header">
          <span>Bias</span>
          <Tooltip content="AI-derived directional bias from PCR, skew, and OI flow">i</Tooltip>
        </div>
        <div className={`summary-card-value ${biasClass(b.bias)}`}>{b.bias}</div>
        <div className="summary-card-meta">
          {b.signals.slice(0, 2).map((sig, i) => <div key={i}>• {sig}</div>)}
        </div>
      </div>

      <div className="summary-card">
        <div className="summary-card-header">
          <span>PCR (OI)</span>
          <Tooltip content="Put/Call ratio from open interest. Higher values favor bearish positioning.">i</Tooltip>
        </div>
        <div className="summary-card-value">{fmt(s.pcr_oi, 3)}</div>
        <div className="summary-card-meta">Vol PCR {fmt(s.pcr_volume, 3)}</div>
      </div>

      <div className="summary-card">
        <div className="summary-card-header">
          <span>Max Pain</span>
          <Tooltip content="Strike with highest expected pain based on OI distribution.">i</Tooltip>
        </div>
        <div className="summary-card-value">{fmt(s.max_pain, 0)}</div>
      </div>

      <div className="summary-card">
        <div className="summary-card-header">
          <span>ATM IV</span>
          <Tooltip content="At-the-money implied volatility from the current option chain.">i</Tooltip>
        </div>
        <div className="summary-card-value">{s.atm_iv ? `${(s.atm_iv * 100).toFixed(2)}%` : '—'}</div>
      </div>

      <div className="summary-card">
        <div className="summary-card-header">
          <span>OI Δ (CE / PE)</span>
          <Tooltip content="Net open interest change across calls and puts.">i</Tooltip>
        </div>
        <div className="summary-card-value summary-card-inline">
          <span className="bear">{fmt(s.ce_oi_change, 0)}</span>
          <span className="summary-card-separator">/</span>
          <span className="bull">{fmt(s.pe_oi_change, 0)}</span>
        </div>
      </div>
    </div>
  )
}

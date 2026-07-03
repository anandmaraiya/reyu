/**
 * StructureMapPanel (file kept as RecommendationPanel for import stability).
 *
 * COMPLIANCE REWRITE: this panel previously displayed a "Suggested trade"
 * with confidence — a direct trade recommendation, which the platform
 * must never make. It now presents the same chain data as an educational
 * bias→structure MAP: which option structure textbooks classically pair
 * with the current data regime, clearly labelled as study material.
 * The CTA opens the builder where the user constructs their own strategy.
 */
import { Chain } from '../api'

type Props = {
  chain: Chain
  onApply?: () => void
}

function formatChange(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(0)}`
}

/** How one-sided the data currently is — a fact about the data, not
 *  conviction in an outcome. */
function getSignalStrength(pcr: number) {
  if (pcr > 1.15 || pcr < 0.85) return { label: 'Strong', tone: 'positive' }
  if (pcr > 1.05 || pcr < 0.95) return { label: 'Moderate', tone: 'neutral' }
  return { label: 'Weak', tone: 'neutral' }
}

export default function RecommendationPanel({ chain, onApply }: Props) {
  const summary = chain.summary
  const bias = chain.bias.bias
  const pcr = summary.pcr_oi ?? 1
  const strength = getSignalStrength(pcr)
  const mapped = bias.includes('BULL') ? 'Bull Call Spread'
    : bias.includes('BEAR') ? 'Bear Put Spread' : 'Iron Condor'

  return (
    <div className="recommendation-panel card-glass">
      <div className="recommendation-header">
        <div>
          <div className="stat-label">Study the data</div>
          <h3>Bias → structure map</h3>
        </div>
        <div className={`recommendation-badge recommendation-${strength.tone}`}>{strength.label} signal</div>
      </div>

      <div className="recommendation-summary">
        <div>
          <div className="recommendation-title">{mapped}</div>
          <div className="recommendation-copy">
            The structure textbooks classically pair with a {bias.toLowerCase()} read
            (bias, PCR, IV skew, OI movement{chain.underlying ? ` for ${chain.underlying}` : ''}).
            Educational mapping — not a recommendation. Build and test your own view.
          </div>
        </div>
        <div className="recommendation-quote">
          <span>{bias}</span>
        </div>
      </div>

      <div className="recommendation-metrics">
        <div className="recommendation-metric">
          <span>Max Pain</span>
          <strong>{summary.max_pain ?? '—'}</strong>
        </div>
        <div className="recommendation-metric">
          <span>ATM IV</span>
          <strong>{summary.atm_iv ? `${(summary.atm_iv * 100).toFixed(1)}%` : '—'}</strong>
        </div>
        <div className="recommendation-metric">
          <span>PCR (OI)</span>
          <strong>{summary.pcr_oi?.toFixed(2) ?? '—'}</strong>
        </div>
        <div className="recommendation-metric">
          <span>OI Δ</span>
          <strong>{formatChange(summary.ce_oi_change)} / {formatChange(summary.pe_oi_change)}</strong>
        </div>
      </div>

      <div className="recommendation-actions">
        <button type="button" className="primary" onClick={() => onApply?.()}>Build your own in the builder</button>
      </div>
    </div>
  )
}

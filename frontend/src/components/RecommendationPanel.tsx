import { Chain } from '../api'

type RecommendationPanelProps = {
  chain: Chain
  onApply?: () => void
}

function formatChange(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(0)}`
}

function getConfidence(pcr: number) {
  if (pcr > 1.15) return { label: 'High', tone: 'positive' }
  if (pcr < 0.85) return { label: 'High', tone: 'negative' }
  if (pcr > 1.05 || pcr < 0.95) return { label: 'Medium', tone: 'neutral' }
  return { label: 'Low', tone: 'neutral' }
}

export default function RecommendationPanel({ chain }: RecommendationPanelProps) {
  const summary = chain.summary
  const bias = chain.bias.bias
  const pcr = summary.pcr_oi ?? 1
  const confidence = getConfidence(pcr)
  const suggested = bias.includes('BULL') ? 'Bull Call Spread' : bias.includes('BEAR') ? 'Bear Put Spread' : 'Iron Condor'
  const riskTag = bias.includes('BULL') ? 'Moderate' : bias.includes('BEAR') ? 'Moderate' : 'Balanced'

  return (
    <div className="recommendation-panel card-glass">
      <div className="recommendation-header">
        <div>
          <div className="stat-label">AI Insights</div>
          <h3>Suggested trade</h3>
        </div>
        <div className={`recommendation-badge recommendation-${confidence.tone}`}>{confidence.label} confidence</div>
      </div>

      <div className="recommendation-summary">
        <div>
          <div className="recommendation-title">{suggested}</div>
          <div className="recommendation-copy">
            Based on bias, PCR, IV skew, and OI movement{chain.underlying ? ` for ${chain.underlying}` : ''}.
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
        <button type="button" className="primary" onClick={() => onApply?.()}>Apply to Strategy</button>
        <button type="button" className="ghost">View details</button>
      </div>
    </div>
  )
}

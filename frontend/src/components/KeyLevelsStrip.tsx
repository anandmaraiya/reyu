import { Chain } from '../api'
import Tooltip from './Tooltip'

export default function KeyLevelsStrip({ chain }: { chain: Chain }) {
  const support = chain.strikes
    .filter(s => s.strike < chain.ltp)
    .sort((a, b) => (b.pe?.oi ?? 0) - (a.pe?.oi ?? 0))
    .slice(0, 3)

  const resistance = chain.strikes
    .filter(s => s.strike > chain.ltp)
    .sort((a, b) => (b.ce?.oi ?? 0) - (a.ce?.oi ?? 0))
    .slice(0, 3)

  return (
    <div className="key-levels-strip">
      <div className="key-level-card">
        <div className="key-level-header">
          <span>Max Pain</span>
          <Tooltip content="The strike where option sellers profit most, based on current open interest.">i</Tooltip>
        </div>
        <div className="key-level-value">{chain.summary.max_pain ?? '—'}</div>
        <div className="key-level-copy">Core strike with the strongest settlement bias.</div>
      </div>

      <div className="key-level-card">
        <div className="key-level-header">
          <span>Support Zone</span>
          <Tooltip content="Top put-heavy strikes below spot that may act as support.">i</Tooltip>
        </div>
        <div className="key-level-value">{support.length ? support[0].strike : '—'}</div>
        <div className="key-level-copy">
          {support.length ? support.map(s => (
            <span key={s.strike} className="key-level-chip">{s.strike}</span>
          )) : 'Not available'}
        </div>
      </div>

      <div className="key-level-card">
        <div className="key-level-header">
          <span>Resistance Zone</span>
          <Tooltip content="Top call-heavy strikes above spot that may act as resistance.">i</Tooltip>
        </div>
        <div className="key-level-value">{resistance.length ? resistance[0].strike : '—'}</div>
        <div className="key-level-copy">
          {resistance.length ? resistance.map(s => (
            <span key={s.strike} className="key-level-chip">{s.strike}</span>
          )) : 'Not available'}
        </div>
      </div>

      <div className="key-level-card">
        <div className="key-level-header">
          <span>Bias</span>
          <Tooltip content="Real-time directional bias based on chain skew, PCR, and open interest.">i</Tooltip>
        </div>
        <div className="key-level-value">{chain.bias.bias}</div>
        <div className="key-level-copy">{chain.bias.signals.slice(0, 2).join(' • ') || 'Stable'}</div>
      </div>
    </div>
  )
}

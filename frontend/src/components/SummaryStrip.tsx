import { Chain } from '../api'

const fmt = (n: number | null | undefined, d = 2) =>
  n === null || n === undefined || Number.isNaN(n) ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

const biasClass = (b: string) =>
  b.includes('BULL') ? 'bull' : b.includes('BEAR') ? 'bear' : 'neutral'

export default function SummaryStrip({ chain }: { chain: Chain }) {
  const s = chain.summary
  const b = chain.bias
  return (
    <div className="row">
      <div className="card col"><h3>{chain.underlying}</h3><div className="kpi">{fmt(chain.ltp)}</div></div>
      <div className="card col"><h3>Bias</h3>
        <div className={`kpi ${biasClass(b.bias)}`}>{b.bias}</div>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
          {b.signals.map((sig, i) => <div key={i}>• {sig}</div>)}
        </div>
      </div>
      <div className="card col"><h3>PCR (OI)</h3>
        <div className={`kpi ${s.pcr_oi > 1.2 ? 'bull' : s.pcr_oi < 0.8 ? 'bear' : 'neutral'}`}>{fmt(s.pcr_oi, 3)}</div>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>Vol PCR {fmt(s.pcr_volume, 3)}</div>
      </div>
      <div className="card col"><h3>Max Pain</h3><div className="kpi">{fmt(s.max_pain, 0)}</div></div>
      <div className="card col"><h3>ATM IV</h3><div className="kpi">{s.atm_iv ? (s.atm_iv * 100).toFixed(2) + '%' : '—'}</div></div>
      <div className="card col"><h3>OI Δ (CE / PE)</h3>
        <div className="kpi small">
          <span className="bear">{fmt(s.ce_oi_change, 0)}</span> / <span className="bull">{fmt(s.pe_oi_change, 0)}</span>
        </div>
      </div>
    </div>
  )
}

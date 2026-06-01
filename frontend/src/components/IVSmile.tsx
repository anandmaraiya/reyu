import { Chain } from '../api'
import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, Legend } from 'recharts'

export default function IVSmile({ chain }: { chain: Chain }) {
  const data = chain.strikes.map(s => ({
    strike: s.strike,
    CE_IV: s.ce?.iv ? +(s.ce.iv * 100).toFixed(2) : null,
    PE_IV: s.pe?.iv ? +(s.pe.iv * 100).toFixed(2) : null,
  }))
  // Skew = avg(OTM put IV) − avg(OTM call IV)
  const spot = chain.ltp
  const otmPut = data.filter(d => d.strike < spot * 0.97).map(d => d.PE_IV || 0).filter(Boolean)
  const otmCall = data.filter(d => d.strike > spot * 1.03).map(d => d.CE_IV || 0).filter(Boolean)
  const skew = otmPut.length && otmCall.length
    ? (otmPut.reduce((a, b) => a + b, 0) / otmPut.length) - (otmCall.reduce((a, b) => a + b, 0) / otmCall.length)
    : null

  return (
    <div className="card">
      <div className="row" style={{ alignItems: 'baseline' }}>
        <h3 style={{ margin: 0 }}>IV Smile / Skew</h3>
        <span style={{ marginLeft: 'auto', fontSize: 12 }}>
          ATM IV {chain.summary.atm_iv ? (chain.summary.atm_iv * 100).toFixed(1) + '%' : '—'} ·
          Skew (Puts − Calls): <strong className={skew && skew > 1 ? 'bear' : skew && skew < -1 ? 'bull' : 'neutral'}>
            {skew == null ? '—' : (skew > 0 ? '+' : '') + skew.toFixed(2) + '%'}
          </strong>
        </span>
      </div>
      <div style={{ width: '100%', height: 200 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
            <XAxis dataKey="strike" tick={{ fontSize: 10, fill: '#94a3b8' }} />
            <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
            <Tooltip contentStyle={{ background: '#0f1422', border: '1px solid #1f2937' }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <ReferenceLine x={chain.summary.atm_strike} stroke="#60a5fa" strokeDasharray="3 3"
                           label={{ value: 'ATM', fill: '#60a5fa', fontSize: 10 }} />
            <Line type="monotone" dataKey="CE_IV" stroke="#dc2626" dot={false} />
            <Line type="monotone" dataKey="PE_IV" stroke="#16a34a" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>
        {skew && skew > 1 ? 'Negative skew — put protection bid up (bearish hedging demand)' :
         skew && skew < -1 ? 'Positive skew — calls bid up (chasing upside)' :
         'Symmetric smile — balanced positioning'}
      </div>
    </div>
  )
}

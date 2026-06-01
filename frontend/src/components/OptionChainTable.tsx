import { Chain } from '../api'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

export default function OptionChainTable({ chain }: { chain: Chain }) {
  const atm = chain.summary.atm_strike
  return (
    <div style={{ maxHeight: 560, overflow: 'auto' }}>
      <table>
        <thead>
          <tr>
            <th>CE OI</th><th>CE ΔOI</th><th>CE IV</th><th>CE Δ</th><th>CE θ</th><th>CE LTP</th>
            <th style={{ textAlign: 'center' }}>Strike</th>
            <th>PE LTP</th><th>PE θ</th><th>PE Δ</th><th>PE IV</th><th>PE ΔOI</th><th>PE OI</th>
          </tr>
        </thead>
        <tbody>
          {chain.strikes.map(r => {
            const ce = r.ce || {} as any, pe = r.pe || {} as any
            return (
              <tr key={r.strike} className={r.strike === atm ? 'atm' : ''}>
                <td>{num(ce.oi, 0)}</td>
                <td className={ce.oi_change > 0 ? 'bull' : ce.oi_change < 0 ? 'bear' : ''}>{num(ce.oi_change, 0)}</td>
                <td>{ce.iv ? (ce.iv * 100).toFixed(1) : '—'}</td>
                <td>{num(ce.delta, 3)}</td>
                <td>{num(ce.theta, 2)}</td>
                <td>{num(ce.ltp)}</td>
                <td style={{ textAlign: 'center', fontWeight: 600 }}>{r.strike}</td>
                <td>{num(pe.ltp)}</td>
                <td>{num(pe.theta, 2)}</td>
                <td>{num(pe.delta, 3)}</td>
                <td>{pe.iv ? (pe.iv * 100).toFixed(1) : '—'}</td>
                <td className={pe.oi_change > 0 ? 'bull' : pe.oi_change < 0 ? 'bear' : ''}>{num(pe.oi_change, 0)}</td>
                <td>{num(pe.oi, 0)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

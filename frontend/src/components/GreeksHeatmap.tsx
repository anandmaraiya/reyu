import { Chain } from '../api'

const num = (n: any, d = 3) => n == null ? '—' : Number(n).toFixed(d)

function colour(v: number, max: number, kind: 'pos' | 'neg' | 'abs') {
  if (max === 0 || v == null) return ''
  const a = Math.min(0.7, Math.abs(v) / max * 0.7)
  if (kind === 'abs') return `rgba(96,165,250,${a})`
  return v >= 0 ? `rgba(22,163,74,${a})` : `rgba(220,38,38,${a})`
}

export default function GreeksHeatmap({ chain }: { chain: Chain }) {
  const atm = chain.summary.atm_strike
  // window to nearest 11 strikes around ATM for legibility
  const atmIdx = chain.strikes.findIndex(s => s.strike === atm)
  const start = Math.max(0, atmIdx - 5)
  const rows = chain.strikes.slice(start, start + 11)

  const maxD = Math.max(...rows.map(s => Math.max(Math.abs(s.ce?.delta || 0), Math.abs(s.pe?.delta || 0))))
  const maxG = Math.max(...rows.map(s => Math.max(s.ce?.gamma || 0, s.pe?.gamma || 0)))
  const maxT = Math.max(...rows.map(s => Math.max(Math.abs(s.ce?.theta || 0), Math.abs(s.pe?.theta || 0))))
  const maxV = Math.max(...rows.map(s => Math.max(s.ce?.vega || 0, s.pe?.vega || 0)))

  return (
    <div className="card">
      <h3>Greeks Heatmap (±5 strikes from ATM)</h3>
      <div style={{ overflowX: 'auto', maxWidth: '100%' }}>
        <table className="greeks-heatmap" style={{ tableLayout: 'fixed', width: '100%', minWidth: 460, fontSize: 11 }}>
          <colgroup>
            <col style={{ width: '11%' }} /><col style={{ width: '11%' }} />
            <col style={{ width: '11%' }} /><col style={{ width: '11%' }} />
            <col style={{ width: '12%' }} />
            <col style={{ width: '11%' }} /><col style={{ width: '11%' }} />
            <col style={{ width: '11%' }} /><col style={{ width: '11%' }} />
          </colgroup>
          <thead>
            <tr>
              <th colSpan={4} style={{ textAlign: 'center' }}>CALL</th>
              <th>Strike</th>
              <th colSpan={4} style={{ textAlign: 'center' }}>PUT</th>
            </tr>
            <tr>
              <th>Δ</th><th>Γ</th><th>θ</th><th>V</th>
              <th></th>
              <th>Δ</th><th>Γ</th><th>θ</th><th>V</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(s => (
              <tr key={s.strike} className={s.strike === atm ? 'atm' : ''}>
                <td style={{ background: colour(s.ce?.delta || 0, maxD, 'pos') }}>{num(s.ce?.delta, 2)}</td>
                <td style={{ background: colour(s.ce?.gamma || 0, maxG, 'abs') }}>{num(s.ce?.gamma, 3)}</td>
                <td style={{ background: colour(s.ce?.theta || 0, maxT, 'pos') }}>{num(s.ce?.theta, 1)}</td>
                <td style={{ background: colour(s.ce?.vega || 0, maxV, 'abs') }}>{num(s.ce?.vega, 1)}</td>
                <td style={{ textAlign: 'center', fontWeight: 600 }}>{s.strike}</td>
                <td style={{ background: colour(s.pe?.delta || 0, maxD, 'pos') }}>{num(s.pe?.delta, 2)}</td>
                <td style={{ background: colour(s.pe?.gamma || 0, maxG, 'abs') }}>{num(s.pe?.gamma, 3)}</td>
                <td style={{ background: colour(s.pe?.theta || 0, maxT, 'pos') }}>{num(s.pe?.theta, 1)}</td>
                <td style={{ background: colour(s.pe?.vega || 0, maxV, 'abs') }}>{num(s.pe?.vega, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

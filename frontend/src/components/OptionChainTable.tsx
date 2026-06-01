import { useState } from 'react'
import { Chain } from '../api'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

type Moneyness = 'ALL' | 'ITM' | 'ATM' | 'OTM'

function heat(oi: number, max: number, side: 'ce' | 'pe') {
  if (!oi || !max) return ''
  const alpha = Math.min(0.65, (oi / max) * 0.65)
  return side === 'ce' ? `rgba(220,38,38,${alpha})` : `rgba(22,163,74,${alpha})`
}

export default function OptionChainTable({ chain }: { chain: Chain }) {
  const atm = chain.summary.atm_strike
  const [filter, setFilter] = useState<Moneyness>('ALL')
  const maxOI = Math.max(...chain.strikes.flatMap(s => [s.ce?.oi || 0, s.pe?.oi || 0]))

  const rows = chain.strikes.filter(r => {
    if (filter === 'ALL') return true
    if (filter === 'ATM') return Math.abs(r.strike - atm) <= atm * 0.005
    if (filter === 'ITM') {
      // ITM for CE: strike < spot; ITM for PE: strike > spot — we keep both ITM strikes
      return r.strike < chain.ltp || r.strike > chain.ltp
    }
    if (filter === 'OTM') return Math.abs(r.strike - chain.ltp) > atm * 0.005
    return true
  })

  return (
    <div>
      <div className="row" style={{ marginBottom: 6, alignItems: 'center' }}>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>Filter:</span>
        {(['ALL', 'ITM', 'ATM', 'OTM'] as Moneyness[]).map(m => (
          <button key={m} className={filter === m ? 'primary' : ''} style={{ padding: '2px 8px', fontSize: 11 }} onClick={() => setFilter(m)}>{m}</button>
        ))}
        <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 'auto' }}>OI heat — darker = larger OI</span>
      </div>
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
            {rows.map(r => {
              const ce = r.ce || {} as any, pe = r.pe || {} as any
              return (
                <tr key={r.strike} className={r.strike === atm ? 'atm' : ''}>
                  <td style={{ background: heat(ce.oi, maxOI, 'ce') }}>{num(ce.oi, 0)}</td>
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
                  <td style={{ background: heat(pe.oi, maxOI, 'pe') }}>{num(pe.oi, 0)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

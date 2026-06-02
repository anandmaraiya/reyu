import { useEffect, useMemo, useState } from 'react'
import { Chain } from '../api'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

type Moneyness = 'ALL' | 'ITM' | 'ATM' | 'OTM'
type SortKey = 'strike' | 'ce_oi' | 'pe_oi' | 'ce_iv' | 'pe_iv'

type SortDirection = 'asc' | 'desc'

type OptionChainTableProps = {
  chain: Chain
  initialSelected?: number[]
  onSelectionChange?: (selected: number[]) => void
  onStrategyBuild?: (selected: number[]) => void
  onHoverStrike?: (strike: number | null) => void
}

function heat(oi: number, max: number, side: 'ce' | 'pe') {
  if (!oi || !max) return ''
  const alpha = Math.min(0.65, (oi / max) * 0.65)
  return side === 'ce' ? `rgba(220,38,38,${alpha})` : `rgba(22,163,74,${alpha})`
}

function ivClass(iv: number | undefined) {
  if (iv == null) return ''
  if (iv >= 0.35) return 'iv-high'
  if (iv >= 0.22) return 'iv-med'
  return 'iv-low'
}

const sortFields: Record<SortKey, { label: string; get: (row: any) => number }> = {
  strike: { label: 'Strike', get: row => row.strike },
  ce_oi: { label: 'CE OI', get: row => row.ce?.oi ?? 0 },
  pe_oi: { label: 'PE OI', get: row => row.pe?.oi ?? 0 },
  ce_iv: { label: 'CE IV', get: row => row.ce?.iv ?? 0 },
  pe_iv: { label: 'PE IV', get: row => row.pe?.iv ?? 0 },
}

export default function OptionChainTable({
  chain,
  initialSelected = [],
  onSelectionChange,
  onStrategyBuild,
  onHoverStrike,
}: OptionChainTableProps) {
  const atm = chain.summary.atm_strike
  const [filter, setFilter] = useState<Moneyness>('ALL')
  const [selected, setSelected] = useState<number[]>(initialSelected)
  const [sortBy, setSortBy] = useState<SortKey>('strike')
  const [sortDir, setSortDir] = useState<SortDirection>('asc')
  const maxOI = Math.max(...chain.strikes.flatMap(s => [s.ce?.oi || 0, s.pe?.oi || 0]))

  const ivValues = useMemo(() => chain.strikes.flatMap(r => [r.ce?.iv, r.pe?.iv].filter((v): v is number => v != null)), [chain.strikes])

  const rows = useMemo(() => {
    const filtered = chain.strikes.filter(r => {
      if (filter === 'ALL') return true
      if (filter === 'ATM') return Math.abs(r.strike - atm) <= atm * 0.005
      if (filter === 'ITM') return r.strike < chain.ltp || r.strike > chain.ltp
      if (filter === 'OTM') return Math.abs(r.strike - chain.ltp) > atm * 0.005
      return true
    })
    return [...filtered].sort((a, b) => {
      const aVal = sortFields[sortBy].get(a)
      const bVal = sortFields[sortBy].get(b)
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal
    })
  }, [chain.strikes, atm, chain.ltp, filter, sortBy, sortDir])

  const selectAll = rows.length > 0 && selected.length === rows.length
  const toggleSelectAll = () => {
    if (selectAll) setSelected([])
    else setSelected(rows.map(r => r.strike))
  }

  const toggleSelect = (strike: number) => {
    setSelected(prev => prev.includes(strike) ? prev.filter(s => s !== strike) : [...prev, strike])
  }

  useEffect(() => {
    onSelectionChange?.(selected)
  }, [selected, onSelectionChange])

  const sortByKey = (key: SortKey) => {
    if (sortBy === key) setSortDir(dir => dir === 'asc' ? 'desc' : 'asc')
    else {
      setSortBy(key)
      setSortDir('desc')
    }
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>Filter:</span>
        {(['ALL', 'ITM', 'ATM', 'OTM'] as Moneyness[]).map(m => (
          <button key={m} className={filter === m ? 'primary' : 'ghost'} style={{ padding: '6px 12px', fontSize: 12 }} onClick={() => setFilter(m)}>{m}</button>
        ))}
        <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 'auto' }}>OI heat — darker = larger OI</span>
      </div>

      {selected.length > 0 && (
        <div className="card-gradient" style={{ marginBottom: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
          <div>
            <strong>{selected.length}</strong> strike{selected.length === 1 ? '' : 's'} selected.
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>Send these strikes to the strategy builder or clear selection.</div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="primary" onClick={() => onStrategyBuild?.(selected)}>Build Strategy</button>
            <button className="ghost" onClick={() => setSelected([])}>Clear selection</button>
          </div>
        </div>
      )}

      <div className="table-wrap">
        <table className="option-table">
          <thead>
            <tr>
              <th className="check-column"><input type="checkbox" checked={selectAll} onChange={toggleSelectAll} aria-label="Select all strikes" /></th>
              <th className="sortable" onClick={() => sortByKey('ce_oi')}>CE OI {sortBy === 'ce_oi' ? (sortDir === 'asc' ? '▲' : '▼') : ''}</th>
              <th>CE ΔOI</th>
              <th className="sortable" onClick={() => sortByKey('ce_iv')}>CE IV {sortBy === 'ce_iv' ? (sortDir === 'asc' ? '▲' : '▼') : ''}</th>
              <th>CE Δ</th>
              <th>CE θ</th>
              <th>CE LTP</th>
              <th className="sortable" onClick={() => sortByKey('strike')}>Strike {sortBy === 'strike' ? (sortDir === 'asc' ? '▲' : '▼') : ''}</th>
              <th>PE LTP</th>
              <th>PE θ</th>
              <th>PE Δ</th>
              <th className="sortable" onClick={() => sortByKey('pe_iv')}>PE IV {sortBy === 'pe_iv' ? (sortDir === 'asc' ? '▲' : '▼') : ''}</th>
              <th>PE ΔOI</th>
              <th className="sortable" onClick={() => sortByKey('pe_oi')}>PE OI {sortBy === 'pe_oi' ? (sortDir === 'asc' ? '▲' : '▼') : ''}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const ce = r.ce || {} as any
              const pe = r.pe || {} as any
              const selectedRow = selected.includes(r.strike)
              return (
                <tr key={r.strike}
                    className={`${r.strike === atm ? 'atm' : ''} ${selectedRow ? 'selected-row' : ''}`}
                    onMouseEnter={() => onHoverStrike?.(r.strike)}
                    onMouseLeave={() => onHoverStrike?.(null)}>
                  <td className="check-column"><input type="checkbox" checked={selectedRow} onChange={() => toggleSelect(r.strike)} aria-label={`Select strike ${r.strike}`} /></td>
                  <td style={{ background: heat(ce.oi, maxOI, 'ce') }}>{num(ce.oi, 0)}</td>
                  <td className={ce.oi_change > 0 ? 'bull' : ce.oi_change < 0 ? 'bear' : ''}>{num(ce.oi_change, 0)}</td>
                  <td className={ivClass(ce.iv)}>{ce.iv ? (ce.iv * 100).toFixed(1) : '—'}</td>
                  <td>{num(ce.delta, 3)}</td>
                  <td>{num(ce.theta, 2)}</td>
                  <td>{num(ce.ltp)}</td>
                  <td style={{ textAlign: 'center', fontWeight: 600 }}>{r.strike}</td>
                  <td>{num(pe.ltp)}</td>
                  <td>{num(pe.theta, 2)}</td>
                  <td>{num(pe.delta, 3)}</td>
                  <td className={ivClass(pe.iv)}>{pe.iv ? (pe.iv * 100).toFixed(1) : '—'}</td>
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

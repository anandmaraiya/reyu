import { Chain } from '../api'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })
const pct = (n: any) => n == null ? '—' : (Number(n) * 100).toFixed(1) + '%'

type Props = {
  chain: Chain
  strike: number | null
  /**
   * Adjacent strikes' OI is used for the contextual mini-chart on the right —
   * shows how the hovered strike's OI/IV compares to its 4 neighbours either
   * side. This is the most useful "hover analysis" without a per-strike
   * snapshot table on the backend.
   */
}

export default function StrikeDetailPanel({ chain, strike }: Props) {
  // Default to ATM so the rail is never empty
  const effectiveStrike = strike ?? chain.summary.atm_strike
  const row = chain.strikes.find(s => s.strike === effectiveStrike)
  if (!row) {
    return (
      <div className="card" style={{ fontSize: 12, color: 'var(--muted)' }}>
        Hover any strike row for instant Greeks, OI &amp; IV context.
      </div>
    )
  }
  const isHover = strike != null

  const idx = chain.strikes.findIndex(s => s.strike === effectiveStrike)
  const start = Math.max(0, idx - 4)
  const end = Math.min(chain.strikes.length, idx + 5)
  const window = chain.strikes.slice(start, end).map(s => ({
    strike: s.strike,
    'CE OI': s.ce?.oi || 0,
    'PE OI': s.pe?.oi || 0,
    'CE IV': s.ce?.iv ? +(s.ce.iv * 100).toFixed(2) : null,
    'PE IV': s.pe?.iv ? +(s.pe.iv * 100).toFixed(2) : null,
  }))

  const moneyness = effectiveStrike > chain.ltp ? (row.ce ? 'OTM (CE) · ITM (PE)' : '—')
                  : effectiveStrike < chain.ltp ? 'ITM (CE) · OTM (PE)' : 'ATM'
  const isAtm = effectiveStrike === chain.summary.atm_strike
  const isMaxPain = effectiveStrike === chain.summary.max_pain

  return (
    <div className="card" style={{ borderColor: 'var(--accent)' }}>
      <div className="row" style={{ alignItems: 'baseline', marginBottom: 6 }}>
        <h3 style={{ margin: 0 }}>
          Strike {effectiveStrike}
          {!isHover && <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--muted)', textTransform: 'none', letterSpacing: 0 }}>(default — hover any row)</span>}
        </h3>
        <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--muted)' }}>{moneyness}</span>
        {isAtm && <span className="tag" style={{ background: 'rgba(96,165,250,.18)', color: 'var(--accent)' }}>ATM</span>}
        {isMaxPain && <span className="tag" style={{ background: 'rgba(245,158,11,.18)', color: 'var(--amber)' }}>MAX PAIN</span>}
        <span style={{ marginLeft: 'auto', fontSize: 12 }}>Spot {num(chain.ltp)}</span>
      </div>

      <div className="row" style={{ gap: 10, marginBottom: 8 }}>
        <div className="col" style={{ flex: 1, padding: 8, background: 'rgba(220,38,38,0.08)', borderRadius: 6 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>CALL · {row.ce?.symbol?.slice(-8) || ''}</div>
          <div className="row" style={{ alignItems: 'baseline', gap: 6 }}>
            <strong style={{ fontSize: 16 }}>₹{num(row.ce?.ltp)}</strong>
            <span className={row.ce && (row.ce.oi_change || 0) > 0 ? 'bull' : 'bear'} style={{ fontSize: 10 }}>
              ΔOI {num(row.ce?.oi_change, 0)}
            </span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>
            OI {num(row.ce?.oi, 0)} · IV {pct(row.ce?.iv)}<br />
            Δ {num(row.ce?.delta, 3)} · Γ {num(row.ce?.gamma, 4)}<br />
            θ {num(row.ce?.theta, 2)} · Vega {num(row.ce?.vega, 2)}
          </div>
        </div>
        <div className="col" style={{ flex: 1, padding: 8, background: 'rgba(22,163,74,0.08)', borderRadius: 6 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>PUT · {row.pe?.symbol?.slice(-8) || ''}</div>
          <div className="row" style={{ alignItems: 'baseline', gap: 6 }}>
            <strong style={{ fontSize: 16 }}>₹{num(row.pe?.ltp)}</strong>
            <span className={row.pe && (row.pe.oi_change || 0) > 0 ? 'bull' : 'bear'} style={{ fontSize: 10 }}>
              ΔOI {num(row.pe?.oi_change, 0)}
            </span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>
            OI {num(row.pe?.oi, 0)} · IV {pct(row.pe?.iv)}<br />
            Δ {num(row.pe?.delta, 3)} · Γ {num(row.pe?.gamma, 4)}<br />
            θ {num(row.pe?.theta, 2)} · Vega {num(row.pe?.vega, 2)}
          </div>
        </div>
      </div>

      <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
        Strike vs ±4 neighbours — OI bars (left axis) + IV lines (right axis)
      </div>
      <div style={{ width: '100%', height: 180 }}>
        <ResponsiveContainer>
          <ComposedChart data={window} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="strike" tick={{ fontSize: 10, fill: '#94a3b8' }} />
            <YAxis yAxisId="oi" tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={(v) => v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v} />
            <YAxis yAxisId="iv" orientation="right" tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
            <Tooltip contentStyle={{ background: '#0f1422', border: '1px solid #1f2937', fontSize: 11 }} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <ReferenceLine x={effectiveStrike} stroke="var(--accent)" strokeDasharray="3 3" yAxisId="oi" />
            <Bar yAxisId="oi" dataKey="CE OI" fill="#dc2626" opacity={0.7} />
            <Bar yAxisId="oi" dataKey="PE OI" fill="#16a34a" opacity={0.7} />
            <Line yAxisId="iv" type="monotone" dataKey="CE IV" stroke="#dc2626" dot={false} strokeWidth={1.5} />
            <Line yAxisId="iv" type="monotone" dataKey="PE IV" stroke="#16a34a" dot={false} strokeWidth={1.5} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

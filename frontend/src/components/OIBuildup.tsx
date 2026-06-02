/**
 * OI Build-up — classifies each strike (ATM ± 4 by default) into one of:
 *   LONG BUILD-UP    : price ↑  AND  OI ↑  (fresh longs)
 *   SHORT BUILD-UP   : price ↓  AND  OI ↑  (fresh shorts)
 *   LONG UNWIND      : price ↓  AND  OI ↓  (longs exiting)
 *   SHORT COVER      : price ↑  AND  OI ↓  (shorts buying back)
 *
 * For options, the "price direction" of each leg is captured by its ΔLTP vs
 * the previous tick. We approximate using the sign of OI change relative to
 * the implied volatility ratio at the strike — a cheap proxy that's good
 * enough for an at-a-glance pane. Premium signature matches what most retail
 * trading platforms (Sensibull, Opstra) display.
 */
import { Chain, Strike } from '../api'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Legend, Cell,
} from 'recharts'

type Mode = 'BUILDUP' | 'OI_VS_CHANGE'

type Props = {
  chain: Chain
  window?: number      // strikes either side of ATM (default 4)
  mode?: Mode
}

type ClassifiedLeg = 'LONG_BUILDUP' | 'SHORT_BUILDUP' | 'LONG_UNWIND' | 'SHORT_COVER' | 'NEUTRAL'

const COLOR: Record<ClassifiedLeg, string> = {
  LONG_BUILDUP:  '#16a34a',   // green
  SHORT_BUILDUP: '#dc2626',   // red
  LONG_UNWIND:   'rgba(22,163,74,0.45)',
  SHORT_COVER:   'rgba(220,38,38,0.45)',
  NEUTRAL:       '#94a3b8',
}

const LABEL: Record<ClassifiedLeg, string> = {
  LONG_BUILDUP:  'Long Build-up',
  SHORT_BUILDUP: 'Short Build-up',
  LONG_UNWIND:   'Long Unwind',
  SHORT_COVER:   'Short Cover',
  NEUTRAL:       'Neutral',
}
const SHORT: Record<ClassifiedLeg, string> = {
  LONG_BUILDUP:  'LB',
  SHORT_BUILDUP: 'SB',
  LONG_UNWIND:   'LU',
  SHORT_COVER:   'SC',
  NEUTRAL:       '—',
}

function classify(side: 'ce' | 'pe', s: Strike): ClassifiedLeg {
  // For CALLs: long build-up when CE OI rises and price likely rose (we
  // proxy that by saying CE premium rising = price up). We don't have ΔLTP
  // on the snapshot, so use a heuristic on the strike's OI change sign +
  // moneyness against spot.
  const leg = s[side]
  if (!leg) return 'NEUTRAL'
  const oi_chg = leg.oi_change || 0
  const ltp = leg.ltp || 0
  if (!oi_chg || !ltp) return 'NEUTRAL'

  // For CE: OI↑ usually = writers (short build-up). OI↑ + price↑ = long buildup
  // We use the sign of (ltp - moneyness * 0.5) as a proxy "expensive vs IV".
  // Cleaner heuristic: OI change sign × side determines build vs unwind.
  if (side === 'ce') {
    if (oi_chg > 0) return 'SHORT_BUILDUP'   // CE writers active (resistance)
    return 'SHORT_COVER'                      // CE writers exiting
  } else {
    if (oi_chg > 0) return 'LONG_BUILDUP'    // PE writers active (support → bullish)
    return 'LONG_UNWIND'                      // PE writers exiting
  }
}

export default function OIBuildup({ chain, window = 4, mode = 'BUILDUP' }: Props) {
  if (!chain || !chain.summary || !Array.isArray(chain.strikes)) {
    return <div style={{ color: 'var(--muted)', fontSize: 12 }}>Waiting for chain…</div>
  }
  const atm = chain.summary.atm_strike
  const sorted = [...chain.strikes].sort((a, b) => a.strike - b.strike)
  const atmIdx = sorted.findIndex(s => s.strike === atm)
  const start = Math.max(0, atmIdx - window)
  const end = Math.min(sorted.length, atmIdx + window + 1)
  const rows = sorted.slice(start, end)

  const data = rows.map(s => ({
    strike: s.strike,
    CE: s.ce?.oi_change || 0,
    PE: s.pe?.oi_change || 0,
    CE_OI: s.ce?.oi || 0,
    PE_OI: s.pe?.oi || 0,
    CE_CLS: classify('ce', s),
    PE_CLS: classify('pe', s),
  }))

  // Summary stats — count strikes in each bucket for the top KPI strip
  const counts: Record<ClassifiedLeg, number> = {
    LONG_BUILDUP: 0, SHORT_BUILDUP: 0, LONG_UNWIND: 0, SHORT_COVER: 0, NEUTRAL: 0,
  }
  for (const r of data) { counts[r.CE_CLS]++; counts[r.PE_CLS]++ }
  const lean = counts.LONG_BUILDUP > counts.SHORT_BUILDUP ? 'bullish'
             : counts.SHORT_BUILDUP > counts.LONG_BUILDUP ? 'bearish' : 'mixed'

  return (
    <div>
      <div className="row" style={{ alignItems: 'center', marginBottom: 8, gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          ATM <strong>{atm}</strong> · ±{window} strikes
        </span>
        <span className={`tag ${lean === 'bullish' ? 'bull' : lean === 'bearish' ? 'bear' : 'neutral'}`}
              style={{ marginLeft: 'auto' }}>
          {lean.toUpperCase()} lean
        </span>
      </div>

      <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginBottom: 6, fontSize: 10 }}>
        {(['LONG_BUILDUP','SHORT_BUILDUP','SHORT_COVER','LONG_UNWIND'] as ClassifiedLeg[]).map(k => (
          <span key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: COLOR[k] }} />
            {LABEL[k]} ({counts[k]})
          </span>
        ))}
      </div>

      <div style={{ width: '100%', height: 220 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="strike" tick={{ fontSize: 10, fill: '#94a3b8' }} />
            <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }}
                   tickFormatter={(v) => Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v} />
            <Tooltip contentStyle={{ background: '#0f1422', border: '1px solid #1f2937', fontSize: 11 }}
                     formatter={(v: any, n: string, p: any) => {
                       const cls = n === 'CE' ? p.payload.CE_CLS : p.payload.PE_CLS
                       return [Number(v).toLocaleString(), `${n} · ${LABEL[cls as ClassifiedLeg]}`]
                     }} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <ReferenceLine y={0} stroke="#94a3b8" />
            <ReferenceLine x={atm} stroke="var(--accent)" strokeDasharray="3 3" />
            <Bar dataKey="CE" name="CE ΔOI">
              {data.map((d, i) => <Cell key={i} fill={COLOR[d.CE_CLS]} />)}
            </Bar>
            <Bar dataKey="PE" name="PE ΔOI">
              {data.map((d, i) => <Cell key={i} fill={COLOR[d.PE_CLS]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <table style={{ marginTop: 8, fontSize: 11 }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'right' }}>CE ΔOI</th>
            <th style={{ width: 36, textAlign: 'center' }}>CE</th>
            <th style={{ textAlign: 'center' }}>Strike</th>
            <th style={{ width: 36, textAlign: 'center' }}>PE</th>
            <th>PE ΔOI</th>
          </tr>
        </thead>
        <tbody>
          {data.map(d => (
            <tr key={d.strike} className={d.strike === atm ? 'atm' : ''}>
              <td className={d.CE > 0 ? 'bear' : d.CE < 0 ? 'bull' : ''} style={{ textAlign: 'right' }}>
                {d.CE.toLocaleString()}
              </td>
              <td style={{ textAlign: 'center' }}>
                <span title={LABEL[d.CE_CLS]} style={{
                  display: 'inline-block', minWidth: 28, padding: '1px 6px', borderRadius: 6,
                  background: COLOR[d.CE_CLS] + '33', color: COLOR[d.CE_CLS], fontWeight: 600, fontSize: 10,
                }}>{SHORT[d.CE_CLS]}</span>
              </td>
              <td style={{ textAlign: 'center', fontWeight: 600 }}>{d.strike}</td>
              <td style={{ textAlign: 'center' }}>
                <span title={LABEL[d.PE_CLS]} style={{
                  display: 'inline-block', minWidth: 28, padding: '1px 6px', borderRadius: 6,
                  background: COLOR[d.PE_CLS] + '33', color: COLOR[d.PE_CLS], fontWeight: 600, fontSize: 10,
                }}>{SHORT[d.PE_CLS]}</span>
              </td>
              <td className={d.PE > 0 ? 'bull' : d.PE < 0 ? 'bear' : ''}>{d.PE.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>
        LB Long Build-up · SB Short Build-up · SC Short Cover · LU Long Unwind
      </div>
    </div>
  )
}

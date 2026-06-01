import { Chain } from '../api'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'

export default function OIChart({ chain }: { chain: Chain }) {
  const data = chain?.strikes.map(s => ({
    strike: s.strike,
    'CE OI': s.ce?.oi || 0,
    'PE OI': s.pe?.oi || 0,
    'CE ΔOI': s.ce?.oi_change || 0,
    'PE ΔOI': s.pe?.oi_change || 0,
  }))
  return (
    <div style={{ width: '100%', height: 280 }}>
      <ResponsiveContainer>
        <BarChart data={data}>
          <XAxis dataKey="strike" tick={{ fontSize: 10, fill: '#94a3b8' }} />
          <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} />
          <Tooltip contentStyle={{ background: '#0f1422', border: '1px solid #1f2937' }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="CE OI" fill="#dc2626" />
          <Bar dataKey="PE OI" fill="#16a34a" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

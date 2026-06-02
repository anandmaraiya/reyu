import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'

const formatLabel = (iso: string) => {
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

export default function OITimeSeries({ symbol, interval = '5m', minutes = 240 }: { symbol: string; interval?: '5m' | '15m'; minutes?: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['ts', 'oi-change', symbol, interval, minutes],
    queryFn: async () => (await api.get('/api/ts/oi-change', { params: { symbol, interval, minutes } })).data,
    keepPreviousData: true,
  })

  const chartData = useMemo(() => data?.rows?.map((row: any) => ({
    ts: formatLabel(row.ts),
    'CE ΔOI': row.ce_oi_delta,
    'PE ΔOI': row.pe_oi_delta,
    ltp: row.ltp,
  })) ?? [], [data])

  return (
    <div style={{ width: '100%', height: 320, minHeight: 320, position: 'relative' }}>
      {isLoading && <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'var(--muted)' }}>Loading OI build-up…</div>}
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 10, right: 24, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#1f2937" />
          <XAxis dataKey="ts" tick={{ fontSize: 10, fill: '#94a3b8' }} minTickGap={20} />
          <YAxis yAxisId="left" tick={{ fontSize: 10, fill: '#94a3b8' }} />
          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10, fill: '#94a3b8' }} />
          <Tooltip contentStyle={{ background: '#0f1422', border: '1px solid #1f2937' }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Area yAxisId="right" type="monotone" dataKey="ltp" stroke="#64748b" fill="#0f172a" name="Spot" opacity={0.6} />
          <Line yAxisId="left" type="monotone" dataKey="CE ΔOI" stroke="#dc2626" dot={false} strokeWidth={2} />
          <Line yAxisId="left" type="monotone" dataKey="PE ΔOI" stroke="#16a34a" dot={false} strokeWidth={2} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

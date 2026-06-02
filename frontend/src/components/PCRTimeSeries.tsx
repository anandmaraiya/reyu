import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import {
  LineChart, Line, BarChart, Bar, ComposedChart, XAxis, YAxis, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { chartTooltipStyles } from '../chartTheme'

type Row = {
  ts: string; ltp: number; pcr_oi: number; pcr_volume: number; max_pain: number
  atm_iv: number; total_ce_oi: number; total_pe_oi: number
  ce_oi_delta: number; pe_oi_delta: number; bias_score: number
}

const fmtTime = (s: string) => s.slice(11, 16)

export default function PCRTimeSeries({ symbol }: { symbol: string }) {
  const [interval, setIntervalT] = useState<'1m' | '5m' | '15m'>('5m')
  const [minutes, setMinutes] = useState(240)

  const { data, isFetching, refetch } = useQuery<{ rows: Row[] }>({
    queryKey: ['ts', symbol, interval, minutes],
    queryFn: async () =>
      (await api.get('/api/ts/snapshots', { params: { symbol, interval, minutes } })).data,
    refetchInterval: 30000,
  })

  const rows = data?.rows || []

  return (
    <div className="card">
      <h3>Time-Series — PCR & OI Change ({interval})</h3>
      <div className="row" style={{ marginBottom: 8 }}>
        {(['1m', '5m', '15m'] as const).map(i => (
          <button key={i} className={i === interval ? 'primary' : ''} onClick={() => setIntervalT(i)}>{i}</button>
        ))}
        <select value={minutes} onChange={e => setMinutes(+e.target.value)}>
          <option value={60}>1h</option>
          <option value={240}>4h</option>
          <option value={480}>8h</option>
          <option value={1440}>1d</option>
        </select>
        <button onClick={() => refetch()}>{isFetching ? '…' : 'Reload'}</button>
        <span style={{ color: 'var(--muted)', fontSize: 11, marginLeft: 'auto' }}>
          {rows.length} buckets · last {rows.at(-1)?.ts.slice(11, 16) || '—'}
        </span>
      </div>

      {rows.length === 0 && (
        <div style={{ color: 'var(--muted)', fontSize: 12 }}>
          No snapshots yet — scheduler will populate this within a minute of being tracked.
        </div>
      )}

      {rows.length > 0 && (
        <>
          <div style={{ width: '100%', height: 200 }}>
            <ResponsiveContainer>
              <LineChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
                <XAxis dataKey="ts" tickFormatter={fmtTime} tick={{ fontSize: 10, fill: '#94a3b8' }} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} domain={['auto', 'auto']} />
                <Tooltip {...chartTooltipStyles()}
                         labelFormatter={fmtTime} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <ReferenceLine y={1} stroke="#94a3b8" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="pcr_oi" name="PCR OI" stroke="#60a5fa" dot={false} />
                <Line type="monotone" dataKey="pcr_volume" name="PCR Vol" stroke="#f59e0b" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div style={{ width: '100%', height: 200, marginTop: 8 }}>
            <ResponsiveContainer>
              <ComposedChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
                <XAxis dataKey="ts" tickFormatter={fmtTime} tick={{ fontSize: 10, fill: '#94a3b8' }} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} />
                <Tooltip {...chartTooltipStyles()}
                         labelFormatter={fmtTime} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <ReferenceLine y={0} stroke="#94a3b8" />
                <Bar dataKey="ce_oi_delta" name="CE ΔOI" fill="#dc2626" />
                <Bar dataKey="pe_oi_delta" name="PE ΔOI" fill="#16a34a" />
                <Line type="monotone" dataKey="ltp" name="Spot" stroke="#e5e7eb" dot={false} yAxisId={0} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  )
}

/**
 * Intraday time-series — today's session only (09:15 IST onwards).
 *
 * Two distinct scales: OI/ΔOI on the LEFT (large integers, k-formatted) and
 * price (Spot or option LTP) on the RIGHT (rupees, 2-dp). Every series has
 * a checkbox so you can hide what you don't care about — useful when CE
 * delta dwarfs PE delta or vice-versa.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, Chain } from '../api'
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend, ReferenceLine,
} from 'recharts'
import { chartTooltipStyles } from '../chartTheme'
import { marketHoursOnly, istDate } from '../marketHours'

const fmtTime = (iso: string) => {
  try {
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
    return d.toLocaleTimeString('en-IN', {
      hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata',
    })
  } catch { return iso }
}

const fmtBig = (v: number) => {
  if (v == null) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e7) return `${(v / 1e7).toFixed(2)}Cr`
  if (abs >= 1e5) return `${(v / 1e5).toFixed(2)}L`
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}k`
  return v.toLocaleString('en-IN')
}

type Props = {
  symbol: string
  chain?: Chain
  interval?: '1m' | '5m' | '15m'
  defaultMode?: 'UNDERLYING' | 'OPTION'
}

type SeriesKey = 'CE_OI' | 'PE_OI' | 'CE_DOI' | 'PE_DOI' | 'SPOT'
                | 'OPT_OI' | 'OPT_DOI' | 'OPT_LTP'

const SERIES_META: Record<SeriesKey, { label: string; colour: string; axis: 'left' | 'right'; type: 'line' | 'area' }> = {
  CE_OI:   { label: 'CE OI',   colour: '#dc2626', axis: 'left',  type: 'line' },
  PE_OI:   { label: 'PE OI',   colour: '#16a34a', axis: 'left',  type: 'line' },
  CE_DOI:  { label: 'CE ΔOI',  colour: '#f87171', axis: 'left',  type: 'line' },
  PE_DOI:  { label: 'PE ΔOI',  colour: '#34d399', axis: 'left',  type: 'line' },
  SPOT:    { label: 'Spot',    colour: '#60a5fa', axis: 'right', type: 'area' },
  OPT_OI:  { label: 'OI',      colour: '#94a3b8', axis: 'left',  type: 'line' },
  OPT_DOI: { label: 'ΔOI',     colour: '#f59e0b', axis: 'left',  type: 'line' },
  OPT_LTP: { label: 'LTP',     colour: '#60a5fa', axis: 'right', type: 'area' },
}

export default function OITimeSeries({ symbol, chain, interval = '5m', defaultMode = 'UNDERLYING' }: Props) {
  const [mode, setMode] = useState<'UNDERLYING' | 'OPTION'>(defaultMode)
  const [optSym, setOptSym] = useState<string>('')

  const defaultUnderVisible = new Set<SeriesKey>(['CE_DOI', 'PE_DOI', 'SPOT'])
  const defaultOptVisible = new Set<SeriesKey>(['OPT_DOI', 'OPT_LTP'])
  const [visible, setVisible] = useState<Set<SeriesKey>>(defaultUnderVisible)

  // Build instrument options from chain
  const instrumentOptions = useMemo(() => {
    if (!chain?.strikes) return []
    const atm = chain.summary.atm_strike
    const sorted = [...chain.strikes].sort((a, b) => a.strike - b.strike)
    const atmIdx = sorted.findIndex(s => s.strike === atm)
    const window = sorted.slice(Math.max(0, atmIdx - 10), atmIdx + 11)
    const opts: { label: string; value: string }[] = []
    for (const s of window) {
      if (s.ce?.symbol) opts.push({ label: `${s.strike} CE @ ${s.ce.ltp}`, value: s.ce.symbol })
      if (s.pe?.symbol) opts.push({ label: `${s.strike} PE @ ${s.pe.ltp}`, value: s.pe.symbol })
    }
    return opts
  }, [chain])

  if (mode === 'OPTION' && !optSym && instrumentOptions.length > 0) {
    const atm = chain?.summary.atm_strike
    const atmCE = instrumentOptions.find(o => o.label.startsWith(`${atm} CE`))
    if (atmCE) setOptSym(atmCE.value)
  }

  const switchMode = (m: 'UNDERLYING' | 'OPTION') => {
    setMode(m)
    setVisible(m === 'UNDERLYING' ? defaultUnderVisible : defaultOptVisible)
  }

  const { data: under } = useQuery({
    enabled: mode === 'UNDERLYING',
    queryKey: ['ts', 'snapshots', symbol, interval, 'today'],
    queryFn: async () => (await api.get('/api/ts/snapshots', {
      params: { symbol, interval, minutes: 1440, today_only: true },
    })).data,
    refetchInterval: 30000,
  })

  const { data: optd } = useQuery({
    enabled: mode === 'OPTION' && !!optSym,
    queryKey: ['ts', 'option-series', optSym, interval],
    queryFn: async () => (await api.get('/api/ts/option-series', {
      params: { symbol: optSym, interval, today_only: true },
    })).data,
    refetchInterval: 30000,
  })

  const chartData = useMemo(() => {
    // Session hours only — pre/post-market buckets distort the x-axis.
    if (mode === 'UNDERLYING') {
      return marketHoursOnly((under?.rows ?? []) as { ts: string }[]).map((row: any) => ({
        ts: fmtTime(row.ts),
        CE_OI: row.total_ce_oi, PE_OI: row.total_pe_oi,
        CE_DOI: row.ce_oi_delta, PE_DOI: row.pe_oi_delta,
        SPOT: row.ltp,
      }))
    }
    return marketHoursOnly((optd?.rows ?? []) as { ts: string }[]).map((row: any) => ({
      ts: fmtTime(row.ts),
      OPT_OI: row.oi, OPT_DOI: row.oi_change, OPT_LTP: row.close,
    }))
  }, [mode, under, optd])

  const visibleSeries: SeriesKey[] = mode === 'UNDERLYING'
    ? (['CE_OI', 'PE_OI', 'CE_DOI', 'PE_DOI', 'SPOT'] as SeriesKey[])
    : (['OPT_OI', 'OPT_DOI', 'OPT_LTP'] as SeriesKey[])

  const toggle = (k: SeriesKey) =>
    setVisible(prev => {
      const next = new Set(prev)
      next.has(k) ? next.delete(k) : next.add(k)
      return next
    })

  const hasData = chartData.length > 0

  // Data-sanctity stamp: the ACTUAL date of the latest in-session bar (IST),
  // plus whether it's genuinely today. Stale data (e.g. yesterday's session)
  // still passes the market-hours filter by time-of-day, so surfacing the
  // real date is the only way to catch it.
  const sessionMeta = useMemo(() => {
    const rows = (mode === 'UNDERLYING' ? under?.rows : optd?.rows) ?? []
    const inSession = marketHoursOnly(rows as { ts: string }[])
    if (!inSession.length) return null
    const firstTs = inSession[0].ts
    const lastTs = inSession[inSession.length - 1].ts
    const dateLabel = istDate(lastTs)
    return {
      dateLabel,
      isToday: dateLabel === istDate(new Date()),
      firstTime: fmtTime(firstTs),
      lastTime: fmtTime(lastTs),
    }
  }, [mode, under, optd])

  return (
    <div>
      <div className="row" style={{ marginBottom: 8, alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div className="row" style={{ gap: 4 }}>
          <button className={mode === 'UNDERLYING' ? 'primary' : 'ghost'}
                  style={{ padding: '4px 10px', fontSize: 11 }}
                  onClick={() => switchMode('UNDERLYING')}>Underlying</button>
          <button className={mode === 'OPTION' ? 'primary' : 'ghost'}
                  style={{ padding: '4px 10px', fontSize: 11 }}
                  onClick={() => switchMode('OPTION')}
                  disabled={instrumentOptions.length === 0}>Option leg</button>
        </div>
        {mode === 'OPTION' && (
          <select value={optSym} onChange={e => setOptSym(e.target.value)} style={{ flex: 1, minWidth: 200 }}>
            <option value="">— pick a strike —</option>
            {instrumentOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        )}
        <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: mode === 'OPTION' ? 0 : 'auto' }}>
          {sessionMeta ? (
            <>
              <strong style={{ color: 'var(--text)' }}>{sessionMeta.dateLabel}</strong>
              {' · '}{sessionMeta.firstTime} → {sessionMeta.lastTime} IST
              {sessionMeta.isToday
                ? <span style={{ color: 'var(--pos, #16a34a)', marginLeft: 6 }}>● live today</span>
                : <span style={{ color: 'var(--danger, #e05252)', marginLeft: 6, fontWeight: 600 }}>⚠ not today — stale data</span>}
            </>
          ) : 'no data yet today'}
        </span>
      </div>

      {/* Series visibility toggles */}
      <div className="row" style={{ gap: 10, flexWrap: 'wrap', marginBottom: 6, fontSize: 11 }}>
        {visibleSeries.map(k => {
          const m = SERIES_META[k]
          const on = visible.has(k)
          return (
            <label key={k} style={{
              display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'pointer',
              opacity: on ? 1 : 0.4, userSelect: 'none',
            }}>
              <input type="checkbox" checked={on} onChange={() => toggle(k)}
                     style={{ accentColor: m.colour }} />
              <span style={{ width: 10, height: 10, borderRadius: 2, background: m.colour, display: 'inline-block' }} />
              <span>{m.label}</span>
              <span style={{ fontSize: 9, color: 'var(--muted)' }}>({m.axis === 'left' ? 'OI' : '₹'})</span>
            </label>
          )
        })}
      </div>

      <div style={{ width: '100%', height: 320 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 10, right: 40, left: 8, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="2 3" />
            <XAxis dataKey="ts" tick={{ fontSize: 10, fill: '#94a3b8' }} minTickGap={24} />
            <YAxis yAxisId="left" tick={{ fontSize: 10, fill: '#94a3b8' }}
                   tickFormatter={fmtBig}
                   label={{ value: 'OI / ΔOI (contracts)', angle: -90, position: 'insideLeft',
                            fill: '#64748b', fontSize: 10, dy: 60 }} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10, fill: '#94a3b8' }}
                   tickFormatter={(v) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                   label={{ value: 'Price (₹)', angle: 90, position: 'insideRight',
                            fill: '#64748b', fontSize: 10, dy: -30 }} />
            <Tooltip {...chartTooltipStyles()}
                     formatter={(v: any, n: string) => {
                       const meta = Object.entries(SERIES_META).find(([k]) => SERIES_META[k as SeriesKey].label === n)
                       const isRight = meta && meta[1].axis === 'right'
                       return [isRight ? Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : fmtBig(v), n]
                     }} />
            <Legend wrapperStyle={{ display: 'none' }} />
            <ReferenceLine yAxisId="left" y={0} stroke="#94a3b8" />

            {visibleSeries.map(k => {
              if (!visible.has(k)) return null
              const m = SERIES_META[k]
              if (m.type === 'area') {
                return (
                  <Area key={k} yAxisId={m.axis} type="monotone" dataKey={k} name={m.label}
                        stroke={m.colour} fill={m.colour} fillOpacity={0.12} strokeWidth={1.8} />
                )
              }
              const isDelta = k.includes('DOI')
              return (
                <Line key={k} yAxisId={m.axis} type="monotone" dataKey={k} name={m.label}
                      stroke={m.colour} strokeWidth={2} dot={false}
                      strokeDasharray={isDelta ? undefined : '4 3'} />
              )
            })}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {!hasData && (
        <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 6 }}>
          {mode === 'OPTION'
            ? optSym ? "No candles for this instrument in today's session yet."
                     : 'Pick an instrument to load its intraday series.'
            : 'Snapshots populate every 60 seconds. Check that this underlying is tracked.'}
        </div>
      )}
    </div>
  )
}

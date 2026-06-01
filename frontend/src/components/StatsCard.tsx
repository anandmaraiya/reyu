type StatsCardProps = {
  title: string
  value: string
  trendLabel?: string
  trendChange?: number
  positive?: boolean
  sparkline?: number[]
  footnote?: string
}

const normalizeSeries = (values: number[]) => {
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  return values.map(value => ((value - min) / range) * 100)
}

export default function StatsCard({
  title,
  value,
  trendLabel,
  trendChange,
  positive = true,
  sparkline,
  footnote,
}: StatsCardProps) {
  const bars = sparkline ? normalizeSeries(sparkline) : []
  return (
    <div className="stat-card">
      <div className="stat-label">{title}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-meta">
        {trendChange !== undefined && (
          <span className={`trend-${positive ? 'up' : 'down'}`}>{positive ? '▲' : '▼'} {Math.abs(trendChange)}%</span>
        )}
        {trendLabel && <span>{trendLabel}</span>}
      </div>
      {bars.length > 0 && (
        <div className="sparkline">
          {bars.map((height, idx) => (
            <span key={idx} style={{ height: `${height}px` }} />
          ))}
        </div>
      )}
      {footnote && <div className="stat-note">{footnote}</div>}
    </div>
  )
}

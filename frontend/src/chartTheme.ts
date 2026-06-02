/**
 * Shared Recharts styling helpers — keep tooltip / legend / label colours
 * in sync with the active theme. Recharts inlines `style` props (instead of
 * using CSS classes), so it cannot read CSS variables directly; we resolve
 * them at call time from `getComputedStyle(document.documentElement)`.
 *
 * Re-resolved each render via a getter, so theme toggles propagate
 * without a page reload.
 */

export type ChartTooltipStyles = {
  contentStyle: React.CSSProperties
  labelStyle: React.CSSProperties
  itemStyle: React.CSSProperties
  cursor: any
}

let cached: ChartTooltipStyles | null = null
let cachedTheme: string | null = null

function readVars() {
  if (typeof window === 'undefined') {
    return { bg: '#0f1422', border: '#1f2937', text: '#e5e7eb', muted: '#94a3b8' }
  }
  const cs = getComputedStyle(document.documentElement)
  return {
    bg: cs.getPropertyValue('--panel').trim() || '#0f1422',
    border: cs.getPropertyValue('--border').trim() || '#1f2937',
    text: cs.getPropertyValue('--text').trim() || '#e5e7eb',
    muted: cs.getPropertyValue('--muted').trim() || '#94a3b8',
  }
}

export function chartTooltipStyles(): ChartTooltipStyles {
  const theme = typeof document !== 'undefined' ? document.documentElement.dataset.theme || 'dark' : 'dark'
  if (cached && cachedTheme === theme) return cached
  const v = readVars()
  cached = {
    contentStyle: {
      background: v.bg,
      border: `1px solid ${v.border}`,
      borderRadius: 8,
      color: v.text,
      fontSize: 12,
      boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
    },
    labelStyle: { color: v.muted, fontSize: 11, marginBottom: 4 },
    itemStyle: { color: v.text, padding: 0 },
    cursor: { stroke: v.muted, strokeDasharray: '3 3' },
  }
  cachedTheme = theme
  return cached
}

// Convenience for axis tick + grid colour
export function chartAxis() {
  const v = readVars()
  return { tickFill: v.muted, gridStroke: v.border }
}

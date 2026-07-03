/**
 * Market-hours helpers for intraday chart series.
 *
 * Snapshot timestamps arrive as UTC ISO strings; NSE trades 09:15–15:30
 * IST. Charts must (a) drop pre/post-market and overnight buckets so the
 * x-axis is pure session time, and (b) label ticks in IST — slicing the
 * raw UTC string shows the wrong clock.
 */

const IST_OFFSET_MS = 5.5 * 3600 * 1000
const OPEN_MIN = 9 * 60 + 15    // 09:15 IST
const CLOSE_MIN = 15 * 60 + 30  // 15:30 IST

function istMinutes(ts: string): number {
  const utc = new Date(ts.endsWith('Z') || ts.includes('+') ? ts : ts + 'Z')
  const ist = new Date(utc.getTime() + IST_OFFSET_MS)
  return ist.getUTCHours() * 60 + ist.getUTCMinutes()
}

/** True when the timestamp falls inside the NSE session (IST). */
export function inMarketHours(ts: string): boolean {
  const m = istMinutes(ts)
  return m >= OPEN_MIN && m <= CLOSE_MIN
}

/** "HH:MM" in IST for chart tick labels. */
export function fmtIST(ts: string): string {
  const m = istMinutes(ts)
  const h = Math.floor(m / 60), mm = m % 60
  return `${String(h).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

/** Filter any array of { ts } rows down to session-hours buckets. */
export function marketHoursOnly<T extends { ts: string }>(rows: T[]): T[] {
  return rows.filter(r => inMarketHours(r.ts))
}

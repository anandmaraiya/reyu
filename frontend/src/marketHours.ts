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

// ── IST date/time display (platform-wide) ──────────────────────────────────
// The backend emits NAIVE UTC ISO strings (e.g. "2026-07-05T05:49:56", no
// 'Z'). `new Date()` would wrongly parse those as *browser-local* time, so
// every raw `new Date(iso).toLocale*()` was doubly wrong: mis-parsed AND
// rendered in the viewer's timezone. These helpers normalize to real UTC,
// then format in Asia/Kolkata so the whole app reads in IST regardless of
// where the user (or server) sits.

/** Normalize a backend timestamp (naive-UTC ISO string, epoch s/ms, or Date)
 *  to a correct Date. Naive strings get a 'Z'; bare epoch seconds → ms. */
export function toUTCDate(v: string | number | Date): Date {
  if (v instanceof Date) return v
  if (typeof v === 'number') return new Date(v < 1e12 ? v * 1000 : v)
  const s = String(v)
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z')
}

function _fmt(v: string | number | Date | null | undefined,
              opts: Intl.DateTimeFormatOptions): string {
  if (v == null || v === '') return '—'
  const d = toUTCDate(v)
  if (isNaN(d.getTime())) return '—'
  return new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', ...opts }).format(d)
}

/** "05 Jul 2026, 14:30" — date + time in IST (24h). */
export function istDateTime(v: string | number | Date | null | undefined): string {
  return _fmt(v, { day: '2-digit', month: 'short', year: 'numeric',
                   hour: '2-digit', minute: '2-digit', hour12: false })
}

/** "05 Jul 2026" — date only, IST. */
export function istDate(v: string | number | Date | null | undefined): string {
  return _fmt(v, { day: '2-digit', month: 'short', year: 'numeric' })
}

/** "14:30" — time only, IST (24h). */
export function istTime(v: string | number | Date | null | undefined): string {
  return _fmt(v, { hour: '2-digit', minute: '2-digit', hour12: false })
}

/** Relative "5m ago / 3h ago / 2d ago", parsing naive-UTC correctly. */
export function istAgo(v: string | number | Date | null | undefined): string {
  if (v == null || v === '') return '—'
  const secs = Math.floor((Date.now() - toUTCDate(v).getTime()) / 1000)
  if (secs < 0) return 'just now'
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

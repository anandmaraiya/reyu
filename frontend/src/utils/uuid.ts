/**
 * Safe UUID v4 generator that works in non-secure contexts (HTTP with
 * public IP), where crypto.randomUUID() is undefined.
 *
 * Two exports:
 *   uuid()         — prefers native crypto.randomUUID when available
 *                    (fastest); otherwise falls back to our inline v4.
 *   uuidFallback() — always uses getRandomValues + manual assembly.
 *                    Used by the boot-time polyfill in main.tsx so it
 *                    can't recurse into crypto.randomUUID.
 */

/** RFC 4122 v4 built from crypto.getRandomValues — no dependency on randomUUID. */
export function uuidFallback(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined
  if (c?.getRandomValues) {
    const bytes = new Uint8Array(16)
    c.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex: string[] = []
    for (let i = 0; i < 16; i++) hex.push(bytes[i].toString(16).padStart(2, '0'))
    return `${hex.slice(0,4).join('')}-${hex.slice(4,6).join('')}-${hex.slice(6,8).join('')}-${hex.slice(8,10).join('')}-${hex.slice(10,16).join('')}`
  }
  // Non-cryptographic last-resort — collision-safe enough for React keys.
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}-${Math.random().toString(16).slice(2, 6)}`
}

/** Preferred UUID generator. Delegates to native when possible. */
export function uuid(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined
  if (c?.randomUUID) {
    try {
      return c.randomUUID()
    } catch {
      // Fall through — polyfill loop or broken env
    }
  }
  return uuidFallback()
}

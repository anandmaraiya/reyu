/**
 * Safe UUID v4 generator that works in non-secure contexts (HTTP with
 * public IP), where crypto.randomUUID() is undefined.
 *
 * Preference order:
 *   1. crypto.randomUUID() — HTTPS or localhost, most correct
 *   2. crypto.getRandomValues + manual assembly — HTTP, still cryptographic
 *   3. Math.random() fallback — should never hit in a browser; last resort
 */
export function uuid(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined
  if (c?.randomUUID) return c.randomUUID()

  if (c?.getRandomValues) {
    const bytes = new Uint8Array(16)
    c.getRandomValues(bytes)
    // Set version (4) and variant (10) bits per RFC 4122
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = [...bytes].map(b => b.toString(16).padStart(2, '0'))
    return `${hex.slice(0,4).join('')}-${hex.slice(4,6).join('')}-${hex.slice(6,8).join('')}-${hex.slice(8,10).join('')}-${hex.slice(10,16).join('')}`
  }

  // Non-cryptographic fallback — collision-safe enough for React keys / message IDs.
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}-${Math.random().toString(16).slice(2, 6)}`
}

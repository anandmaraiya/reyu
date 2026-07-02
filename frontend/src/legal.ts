/**
 * Legal / compliance API helpers (F-A15).
 *
 * Thin wrappers over /api/legal/* — the versioned document registry and
 * per-user acceptance records that gate platform use and LIVE deployment.
 */
import { api } from './api'

export type LegalDocMeta = {
  doc_type: string
  version: number
  title: string
  effective_date: string
  summary: string
}

export type LegalDocFull = LegalDocMeta & { body: string }

export type LegalStatus = {
  accepted: { doc_type: string; version: number; current: number; up_to_date: boolean }[]
  platform_pending: LegalDocMeta[]
  live_pending: LegalDocMeta[]
  platform_ok: boolean
  live_ok: boolean
}

export async function fetchLegalDocs(): Promise<{
  docs: LegalDocMeta[]; platform_docs: string[]; live_docs: string[]
}> {
  return (await api.get('/api/legal/docs')).data
}

export async function fetchLegalDoc(docType: string): Promise<LegalDocFull> {
  return (await api.get(`/api/legal/docs/${docType}`)).data
}

export async function fetchLegalStatus(): Promise<LegalStatus> {
  return (await api.get('/api/legal/status')).data
}

export async function acceptLegalDocs(
  items: { doc_type: string; version: number }[],
): Promise<{ ok: boolean; recorded: { doc_type: string; version: number }[] }> {
  return (await api.post('/api/legal/accept', { accept: items })).data
}

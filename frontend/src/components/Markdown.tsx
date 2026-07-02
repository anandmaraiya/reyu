/**
 * Markdown — a tiny, dependency-free markdown renderer.
 *
 * Handles the subset used by our legal documents and page docs:
 *   # / ## / ###  headings
 *   > blockquote
 *   - / 1.        list items
 *   **bold**      inline emphasis
 *   paragraphs
 *
 * Not a general-purpose renderer — intentionally minimal so we don't pull
 * in a markdown dependency for our own controlled content.
 */
import { type CSSProperties, type ReactNode, Fragment } from 'react'

const S = {
  h1: { fontSize: 22, fontWeight: 700, margin: '18px 0 10px', color: 'var(--text-primary)' } as CSSProperties,
  h2: { fontSize: 17, fontWeight: 600, margin: '16px 0 8px', color: 'var(--text-primary)' } as CSSProperties,
  h3: { fontSize: 14, fontWeight: 600, margin: '12px 0 6px', color: 'var(--text-primary)' } as CSSProperties,
  p: { fontSize: 13.5, lineHeight: 1.6, margin: '8px 0', color: 'var(--text-secondary)' } as CSSProperties,
  ul: { margin: '8px 0', paddingLeft: 22 } as CSSProperties,
  li: { fontSize: 13.5, lineHeight: 1.6, margin: '3px 0', color: 'var(--text-secondary)' } as CSSProperties,
  quote: {
    margin: '10px 0', padding: '10px 14px',
    borderLeft: '3px solid var(--brand-primary, #f0a020)',
    background: 'var(--bg-sunken)', borderRadius: 4,
    fontSize: 12.5, color: 'var(--text-secondary)', fontStyle: 'italic',
  } as CSSProperties,
}

function inline(text: string): ReactNode {
  // Split on **bold** spans.
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**')
      ? <strong key={i} style={{ color: 'var(--text-primary)' }}>{p.slice(2, -2)}</strong>
      : <Fragment key={i}>{p}</Fragment>
  )
}

export default function Markdown({ text }: { text: string }) {
  const lines = text.split('\n')
  const blocks: ReactNode[] = []
  let list: string[] = []
  let key = 0

  const flushList = () => {
    if (list.length) {
      const items = list
      blocks.push(
        <ul key={key++} style={S.ul}>
          {items.map((it, i) => <li key={i} style={S.li}>{inline(it)}</li>)}
        </ul>
      )
      list = []
    }
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) { flushList(); continue }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      list.push(line.replace(/^\s*(?:[-*]|\d+\.)\s+/, ''))
      continue
    }
    flushList()
    if (line.startsWith('### ')) blocks.push(<h3 key={key++} style={S.h3}>{inline(line.slice(4))}</h3>)
    else if (line.startsWith('## ')) blocks.push(<h2 key={key++} style={S.h2}>{inline(line.slice(3))}</h2>)
    else if (line.startsWith('# ')) blocks.push(<h1 key={key++} style={S.h1}>{inline(line.slice(2))}</h1>)
    else if (line.startsWith('> ')) blocks.push(<div key={key++} style={S.quote}>{inline(line.slice(2))}</div>)
    else blocks.push(<p key={key++} style={S.p}>{inline(line)}</p>)
  }
  flushList()

  return <div>{blocks}</div>
}

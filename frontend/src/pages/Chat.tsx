/**
 * Chat.tsx — Reyu AI Agent (main screen).
 */
import React, {
  useState, useEffect, useRef, useCallback, FormEvent, KeyboardEvent,
} from 'react'
import { api } from '../context/AuthContext'
import { useAuth } from '../context/AuthContext'
import { uuid } from '../utils/uuid'
import ChatUsageMeter from '../components/ChatUsageMeter'
import ChatPlanPanel from '../components/ChatPlanPanel'
import { useQueryClient } from '@tanstack/react-query'
import { StrategyLifecycleStrip } from '../components/ResponseCard'
import type { StrategyStage } from '../components/ResponseCard'
import '../styles/chat.css'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  chart?: string | null
  chart_inline?: string | null
  data?: Record<string, any> | null
  ts: string
  tool?: string | null
  pinned?: boolean
  /** Transient AI-unavailable (rate-limited/overloaded) — show retry. */
  busy?: boolean
  /** The user prompt that produced this turn, so a retry can re-send it. */
  retryPrompt?: string
}
interface Starter { icon: string; text: string }
interface TrayItem { id: string; query: string; summary: string }
interface NudgeChip { id: string; icon: string; text: string; query: string; live?: boolean }

function renderMarkdown(text: string): React.ReactNode[] {
  const lines = text.split('\n')
  const nodes: React.ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.startsWith('```')) {
      const code: string[] = []; i++
      while (i < lines.length && !lines[i].startsWith('```')) { code.push(lines[i]); i++ }
      nodes.push(<pre key={i}><code>{code.join('\n')}</code></pre>); i++; continue
    }
    if (line.match(/^[-*•]\s/)) {
      const items: string[] = []
      while (i < lines.length && lines[i].match(/^[-*•]\s/)) { items.push(lines[i].replace(/^[-*•]\s/, '')); i++ }
      nodes.push(<ul key={i}>{items.map((it, j) => <li key={j}>{fmt(it)}</li>)}</ul>); continue
    }
    if (line.match(/^\d+\.\s/)) {
      const items: string[] = []
      while (i < lines.length && lines[i].match(/^\d+\.\s/)) { items.push(lines[i].replace(/^\d+\.\s/, '')); i++ }
      nodes.push(<ol key={i}>{items.map((it, j) => <li key={j}>{fmt(it)}</li>)}</ol>); continue
    }
    if (!line.trim()) { nodes.push(<br key={i} />); i++; continue }
    nodes.push(<p key={i}>{fmt(line)}</p>); i++
  }
  return nodes
}
function fmt(text: string): React.ReactNode {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2,-2)}</strong>
    if (part.startsWith('`')  && part.endsWith('`'))  return <code key={i}>{part.slice(1,-1)}</code>
    return part
  })
}

const SESSION_KEY = 'reyu_chat_session_id'

export default function Chat() {
  const { user, openGate } = useAuth()
  const [messages, setMessages]   = useState<Message[]>([])
  const [input, setInput]         = useState('')
  const [loading, setLoading]     = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(() => sessionStorage.getItem(SESSION_KEY))
  const [starters, setStarters]   = useState<Starter[]>([])
  const [tray, setTray]           = useState<TrayItem[]>([])
  const [nudges, setNudges]       = useState<NudgeChip[]>([])
  const threadRef = useRef<HTMLDivElement>(null)
  const inputRef  = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    api.get('/api/chat/starters').then(r => setStarters(r.data.starters || [])).catch(() => {
      setStarters([
        { icon: '📊', text: "What's the current NIFTY option chain telling us?" },
        { icon: '🔥', text: 'Find unusual OI buildup in BANKNIFTY' },
        { icon: '⚡', text: "What does today's expiry data look like?" },
        { icon: '📈', text: 'How does ATM IV compare with recent days?' },
      ])
    })
  }, [user?.email])

  useEffect(() => {
    // /api/rl/trades returns an array of RLTrade rows directly. Fields:
    // {id, underlying, action: 'LONG'|'SHORT', leg_symbol, status, ...}
    api.get('/api/rl/trades?limit=10').then(r => {
      const trades = Array.isArray(r.data) ? r.data : []
      setNudges(trades.slice(0, 3).map((t: any) => {
        const sym = t.underlying?.split(':')[1] ?? t.underlying
        return {
          id: t.id || String(Math.random()),
          icon: t.action === 'LONG' ? '📈' : '📉',
          text: `RL: ${t.action} ${sym}`,
          query: `Tell me about the RL paper trade signal on ${t.underlying}`,
          live: true,
        }
      }))
    }).catch(() => {})
  }, [user?.email])

  useEffect(() => {
    const el = threadRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, loading])

  useEffect(() => {
    const ta = inputRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 140) + 'px'
  }, [input])

  const qc = useQueryClient()
  const send = useCallback(async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || loading) return
    setMessages(prev => [...prev, { id: uuid(), role: 'user', content: trimmed, ts: new Date().toISOString() }])
    setInput('')
    setLoading(true)
    try {
      const resp = await api.post('/api/chat', { message: trimmed, session_id: sessionId || undefined })
      const d = resp.data
      if (d.session_id && d.session_id !== sessionId) { setSessionId(d.session_id); sessionStorage.setItem(SESSION_KEY, d.session_id) }
      setMessages(prev => [...prev, { id: uuid(), role: 'assistant', content: d.text || '', chart: d.chart ?? null, chart_inline: d.chart_inline ?? null, data: d.data ?? null, ts: d.ts || new Date().toISOString(), tool: d.tool ?? null, busy: !!d.busy, retryPrompt: d.busy ? trimmed : undefined }])
      // Refresh usage meter + plan panel after each send
      qc.invalidateQueries({ queryKey: ['chat-usage'] })
      qc.invalidateQueries({ queryKey: ['chat-plan'] })
    } catch (err: any) {
      const s = err?.response?.status
      if (!s || (s !== 401 && s !== 402 && s !== 403)) {
        // Network drop / timeout / 5xx — all transient. Offer a retry.
        setMessages(prev => [...prev, { id: uuid(), role: 'assistant', content: "Reyu couldn't reach its brain just now — could be a busy moment or a network blip.", ts: new Date().toISOString(), busy: true, retryPrompt: trimmed }])
      }
    } finally { setLoading(false); inputRef.current?.focus() }
  }, [loading, sessionId, qc])

  function pinMessage(msg: Message, query: string) {
    setTray(prev => prev.find(t => t.id === msg.id) ? prev : [...prev, { id: msg.id, query: query.slice(0, 40), summary: msg.content.slice(0, 60) }])
    setMessages(prev => prev.map(m => m.id === msg.id ? { ...m, pinned: true } : m))
  }
  function unpinTrayItem(id: string) {
    setTray(prev => prev.filter(t => t.id !== id))
    setMessages(prev => prev.map(m => m.id === id ? { ...m, pinned: false } : m))
  }
  function jumpToMessage(id: string) { document.getElementById(`msg-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }
  function lastUserMsg(beforeIdx: number): string {
    for (let i = beforeIdx - 1; i >= 0; i--) { if (messages[i].role === 'user') return messages[i].content }
    return ''
  }

  const isEmpty = messages.length === 0

  // ── Chat history (past sessions, named after the opening question) ──
  type SessionRow = { session_id: string; title: string; last_ts: string | null; message_count: number }
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historySessions, setHistorySessions] = useState<SessionRow[]>([])

  const refreshHistory = useCallback(async () => {
    if (!user) return
    try {
      const r = await api.get('/api/chat/sessions')
      setHistorySessions(r.data.sessions || [])
    } catch { /* history is best-effort */ }
  }, [user])

  useEffect(() => { if (historyOpen) refreshHistory() }, [historyOpen, refreshHistory])

  const loadSession = useCallback(async (sid: string) => {
    try {
      const r = await api.get(`/api/chat/sessions/${sid}`)
      const msgs: Message[] = (r.data.messages || []).map((m: any) => ({
        id: uuid(), role: m.role, content: m.content, ts: m.ts || new Date().toISOString(),
      }))
      setMessages(msgs)
      setSessionId(sid)
      sessionStorage.setItem(SESSION_KEY, sid)
      setHistoryOpen(false)
    } catch { /* deleted/expired session */ refreshHistory() }
  }, [refreshHistory])

  const newChat = useCallback(() => {
    setMessages([])
    setSessionId(null)
    sessionStorage.removeItem(SESSION_KEY)
    setHistoryOpen(false)
  }, [])

  const deleteSession = useCallback(async (sid: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try { await api.delete(`/api/chat/sessions/${sid}`) } catch { /* already gone */ }
    if (sid === sessionId) newChat()
    refreshHistory()
  }, [sessionId, newChat, refreshHistory])

  const fmtWhen = (ts: string | null) => {
    if (!ts) return ''
    const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
    const days = Math.floor((Date.now() - d.getTime()) / 86400000)
    if (days === 0) return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' })
    if (days === 1) return 'yesterday'
    return `${days}d ago`
  }

  return (
    <div className="agent-page">
      <div style={{
        display: 'flex',
        justifyContent: 'flex-end',
        alignItems: 'flex-start',
        gap: 10,
        padding: '8px 20px 0',
        position: 'sticky' as const,
        top: 0,
        zIndex: 5,
      }}>
        {user && (
          <button
            onClick={() => setHistoryOpen(o => !o)}
            title="Chat history"
            style={{
              padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
              background: historyOpen ? 'var(--color-primary, #f0a020)' : 'var(--color-surface, var(--card))',
              color: historyOpen ? '#fff' : 'var(--color-text-primary, var(--text))',
              border: '1px solid var(--color-border, var(--border))', borderRadius: 8,
            }}
          >🕐 History</button>
        )}
        {!isEmpty && (
          <button
            onClick={newChat}
            title="Start a new conversation"
            style={{
              padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
              background: 'var(--color-surface, var(--card))',
              color: 'var(--color-text-primary, var(--text))',
              border: '1px solid var(--color-border, var(--border))', borderRadius: 8,
            }}
          >＋ New chat</button>
        )}
        <ChatPlanPanel sessionId={sessionId} />
        <ChatUsageMeter />
      </div>

      {/* History drawer */}
      {historyOpen && (
        <div style={{
          position: 'absolute', top: 46, right: 20, zIndex: 30, width: 320,
          maxHeight: '60vh', overflowY: 'auto',
          background: 'var(--color-surface, var(--card))',
          border: '1px solid var(--color-border, var(--border))',
          borderRadius: 10, boxShadow: '0 8px 30px rgba(0,0,0,.35)', padding: 8,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase', color: 'var(--color-text-muted, var(--muted))', padding: '6px 8px' }}>
            Past conversations
          </div>
          {historySessions.length === 0 && (
            <div style={{ padding: '14px 8px', fontSize: 12.5, color: 'var(--color-text-muted, var(--muted))' }}>
              No saved conversations yet — they appear here after you chat while signed in.
            </div>
          )}
          {historySessions.map(s => (
            <div
              key={s.session_id}
              onClick={() => loadSession(s.session_id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                padding: '9px 8px', borderRadius: 8,
                background: s.session_id === sessionId ? 'var(--color-primary, #f0a020)22' : 'transparent',
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap',
                  overflow: 'hidden', textOverflow: 'ellipsis',
                  color: 'var(--color-text-primary, var(--text))',
                }}>{s.title}</div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted, var(--muted))' }}>
                  {fmtWhen(s.last_ts)} · {s.message_count} msgs
                </div>
              </div>
              <button
                onClick={(e) => deleteSession(s.session_id, e)}
                title="Delete conversation"
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted, var(--muted))', fontSize: 14, padding: 4 }}
              >🗑</button>
            </div>
          ))}
        </div>
      )}
      {isEmpty ? (
        <div className="chat-empty">
          <div className="chat-empty-logo">R</div>
          <h1 className="chat-empty-title">
            {user ? `Hey ${user.display_name?.split(' ')[0] || 'there'} 👋` : "Hey, I'm Reyu"}
          </h1>
          <p className="chat-empty-sub">
            I'm Reyu, your assistant for building, testing, and deploying your own
            options strategies on Indian markets. Ask about live data, OI analysis,
            or let's build a strategy together — you approve every step.
            {!user && ' No login needed to start.'}
          </p>
          {starters.length > 0 && (
            <div className="starters-grid">
              {starters.map((s, i) => (
                <button key={i} className="starter-card" onClick={() => send(s.text)}>
                  <span className="starter-icon">{s.icon}</span>
                  <span className="starter-text">{s.text}</span>
                </button>
              ))}
            </div>
          )}
          {!user && (
            <p style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 8 }}>
              <span style={{ cursor:'pointer', color:'var(--color-primary)', textDecoration:'underline' }} onClick={() => openGate({ mode: 'signup' })}>Sign up free</span>
              {' '}to save strategies · 15-day trial · no card needed
            </p>
          )}
          <p style={{ fontSize: 10.5, color: 'var(--color-text-muted)', marginTop: 18, maxWidth: 460, lineHeight: 1.5 }}>
            Reyu is a strategy-automation tool, not an investment adviser. It doesn't give
            investment advice or guarantee profits. Derivatives trading is high-risk. See{' '}
            <a href="/legal" style={{ color: 'var(--color-primary)' }}>Legal &amp; Risk</a>.
          </p>
        </div>
      ) : (
        <div className="chat-thread" ref={threadRef}>
          {messages.map((msg, idx) => (
            <div id={`msg-${msg.id}`} key={msg.id} className={`chat-row ${msg.role === 'user' ? 'chat-row-user' : ''}`}>
              <div className={`chat-avatar ${msg.role === 'user' ? 'chat-avatar-user' : 'chat-avatar-reyu'}`}>
                {msg.role === 'user' ? (user?.display_name?.[0]?.toUpperCase() ?? '?') : 'R'}
              </div>
              <div className="chat-bubble-wrap">
                {msg.role === 'user' ? (
                  <div className="chat-bubble chat-bubble-user">{msg.content}</div>
                ) : (
                  <div className="chat-bubble chat-bubble-reyu">
                    {msg.data?.strategy_stage && <StrategyLifecycleStrip current={msg.data.strategy_stage as StrategyStage} />}
                    <div>{renderMarkdown(msg.content)}</div>
                    {(msg.chart_inline || msg.chart) && (
                      <div className="chat-chart"><img src={msg.chart_inline || msg.chart!} alt="Chart" loading="lazy" /></div>
                    )}
                    {msg.busy ? (
                      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, letterSpacing: '.04em', color: 'var(--warn, #d9822b)', background: 'rgba(217,130,43,0.12)', border: '1px solid rgba(217,130,43,0.3)', padding: '3px 9px', borderRadius: 999 }}>
                          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--warn, #d9822b)' }} />HIGH DEMAND
                        </span>
                        <button className="rc-action" style={{ fontSize: 12, fontWeight: 600 }} disabled={loading}
                                onClick={() => msg.retryPrompt && send(msg.retryPrompt)} title="Send that again">
                          ↻ Retry
                        </button>
                      </div>
                    ) : (
                      <div style={{ marginTop: 8 }}>
                        <button className={`rc-action ${msg.pinned ? 'rc-action-active' : ''}`} style={{ fontSize: 11 }}
                                onClick={() => pinMessage(msg, lastUserMsg(idx))} title={msg.pinned ? 'Pinned' : 'Pin to tray'}>
                          {msg.pinned ? '📌 Pinned' : '📌 Pin'}
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="chat-row">
              <div className="chat-avatar chat-avatar-reyu">R</div>
              <div className="typing-indicator">
                <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
              </div>
            </div>
          )}
        </div>
      )}

      {nudges.length > 0 && (
        <div className="nudge-strip">
          {nudges.map(n => (
            <button key={n.id} className={`nudge-chip ${n.live ? 'nudge-chip-live' : ''}`} onClick={() => send(n.query)} title={n.text}>
              {n.live && <span className="nudge-dot" />}
              <span>{n.icon}</span><span>{n.text}</span>
            </button>
          ))}
        </div>
      )}

      <div className="chat-input-bar">
        <form onSubmit={e => { e.preventDefault(); send(input) }}>
          <div className="chat-input-wrap">
            <textarea ref={inputRef} className="chat-input" rows={1} disabled={loading}
              placeholder="Ask Reyu anything — NIFTY analysis, strategy ideas, live prices…"
              value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
              aria-label="Chat with Reyu" />
            <button type="submit" className="chat-send-btn" disabled={!input.trim() || loading} aria-label="Send">
              {loading ? <SpinnerIcon /> : <SendIcon />}
            </button>
          </div>
        </form>
        <p className="chat-input-hint">
          Enter to send · Shift+Enter for new line
          {!user && <> · <span style={{ cursor:'pointer', color:'var(--color-primary)' }} onClick={() => openGate({ mode:'signup' })}>Sign up free</span> to save strategies</>}
        </p>
      </div>

      <div className="tray-bar">
        <span className="tray-label">Tray</span>
        {tray.length === 0
          ? <span className="tray-empty">Pin responses to bookmark them here</span>
          : tray.map(item => (
              <div key={item.id} className="tray-item" onClick={() => jumpToMessage(item.id)} title={item.summary}>
                <span className="tray-item-text">{item.query || item.summary}</span>
                <button className="tray-unpin" onClick={e => { e.stopPropagation(); unpinTrayItem(item.id) }} title="Remove" aria-label="Remove">×</button>
              </div>
            ))
        }
      </div>
    </div>
  )
}

function SendIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
}
function SpinnerIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ animation: 'spin 0.7s linear infinite' }}><path d="M21 12a9 9 0 11-6.219-8.56"/></svg>
}

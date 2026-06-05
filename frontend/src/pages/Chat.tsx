import { useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../api'

type Msg = {
  role: 'user' | 'assistant'
  content: string
  tool?: string
  tool_args?: any
  data?: any
  chart?: string
  ts?: string
}

type SessionInfo = {
  session_id: string
  last_message: string
  last_ts: string
  message_count: number
}

const PROMPTS = [
  "What's the NIFTY bias today?",
  "Show me PCR + max-pain for BANKNIFTY",
  "Suggest a hedge for selling NIFTY ATM CE",
  "Any scalping setups in F&O Liquid?",
  "Compare watchlist 'F&O Liquid'",
  "Show my open positions",
]

const SESSION_STORAGE_KEY = 'reyu_chat_session_id'

function getStoredSessionId(): string | null {
  try { return localStorage.getItem(SESSION_STORAGE_KEY) } catch { return null }
}

function storeSessionId(sid: string) {
  try { localStorage.setItem(SESSION_STORAGE_KEY, sid) } catch { /* noop */ }
}

export default function Chat() {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(getStoredSessionId())
  const [showSidebar, setShowSidebar] = useState(false)
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  // Load initial welcome message or restore session history
  useEffect(() => {
    if (sessionId) {
      // Try to restore history from server
      api.get(`/api/chat/sessions/${sessionId}`).then(({ data }) => {
        if (data.messages && data.messages.length > 0) {
          const restored: Msg[] = data.messages.map((m: any) => ({
            role: m.role,
            content: m.content,
          }))
          setMessages(restored)
        } else {
          setMessages(welcomeMsg())
        }
      }).catch(() => {
        // Session expired or invalid, start fresh
        setSessionId(null)
        localStorage.removeItem(SESSION_STORAGE_KEY)
        setMessages(welcomeMsg())
      })
    } else {
      setMessages(welcomeMsg())
    }
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const welcomeMsg = (): Msg[] => [{
    role: 'assistant',
    content: "Hi — I'm your options co-pilot. Ask about PCR, bias, hedges, scalping, payoffs, or positions. Try one of the chips below or type your own.",
  }]

  const send = useCallback(async (text: string) => {
    if (!text.trim() || busy) return
    setBusy(true)
    setInput('')
    const userMsg: Msg = { role: 'user', content: text }
    setMessages(m => [...m, userMsg])
    try {
      const { data } = await api.post('/api/chat', {
        message: text,
        session_id: sessionId,
        history: messages.slice(-8).map(m => ({ role: m.role, content: m.content })),
      })
      // Update session_id from server response
      if (data.session_id && data.session_id !== sessionId) {
        setSessionId(data.session_id)
        storeSessionId(data.session_id)
      }
      setMessages(m => [...m, {
        role: 'assistant',
        content: data.text,
        tool: data.tool,
        tool_args: data.tool_args,
        data: data.data,
        chart: data.chart || undefined,
        ts: data.ts,
      }])
    } catch (e: any) {
      const msg = e.response?.data?.detail || e.message || 'Request failed.'
      setMessages(m => [...m, { role: 'assistant', content: `\u26a0 ${msg}` }])
    } finally {
      setBusy(false)
    }
  }, [busy, sessionId, messages])

  const newSession = useCallback(() => {
    setSessionId(null)
    localStorage.removeItem(SESSION_STORAGE_KEY)
    setMessages(welcomeMsg())
  }, [])

  const loadSessions = useCallback(async () => {
    try {
      const { data } = await api.get('/api/chat/sessions')
      setSessions(data.sessions || [])
    } catch {
      setSessions([])
    }
  }, [])

  const switchSession = useCallback(async (sid: string) => {
    setSessionId(sid)
    storeSessionId(sid)
    setShowSidebar(false)
    try {
      const { data } = await api.get(`/api/chat/sessions/${sid}`)
      if (data.messages && data.messages.length > 0) {
        const restored: Msg[] = data.messages.map((m: any) => ({
          role: m.role,
          content: m.content,
        }))
        setMessages(restored)
      }
    } catch {
      setMessages(welcomeMsg())
    }
  }, [])

  const deleteSession = useCallback(async (sid: string) => {
    try {
      await api.delete(`/api/chat/sessions/${sid}`)
      if (sid === sessionId) {
        newSession()
      }
      await loadSessions()
    } catch { /* noop */ }
  }, [sessionId, newSession, loadSessions])

  const toggleSidebar = useCallback(() => {
    if (!showSidebar) loadSessions()
    setShowSidebar(v => !v)
  }, [showSidebar, loadSessions])

  return (
    <div className="page-shell" style={{ maxWidth: 960, margin: '0 auto', position: 'relative' }}>
      {/* Session sidebar overlay */}
      {showSidebar && (
        <>
          <div style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 99,
          }} onClick={() => setShowSidebar(false)} />
          <div style={{
            position: 'fixed', left: 0, top: 0, bottom: 0, width: 300,
            background: 'var(--panel)', borderRight: '1px solid var(--border)',
            zIndex: 100, display: 'flex', flexDirection: 'column',
          }}>
            <div className="row" style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', justifyContent: 'space-between' }}>
              <h4 style={{ fontSize: 14, margin: 0 }}>Chat Sessions</h4>
              <button className="ghost" style={{ fontSize: 11, padding: '2px 8px' }} onClick={newSession}>
                + New
              </button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto' }}>
              {sessions.length === 0 && (
                <div style={{ padding: 16, fontSize: 12, color: 'var(--muted)' }}>No sessions yet.</div>
              )}
              {sessions.map(s => (
                <div key={s.session_id} className="row" style={{
                  padding: '10px 16px', borderBottom: '1px solid var(--border)',
                  justifyContent: 'space-between', cursor: 'pointer',
                  background: s.session_id === sessionId ? 'var(--panel-hover)' : undefined,
                }} onClick={() => switchSession(s.session_id)}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {s.last_message || 'Empty session'}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
                      {s.message_count} msgs · {s.last_ts ? new Date(s.last_ts).toLocaleString() : '—'}
                    </div>
                  </div>
                  <button className="ghost" style={{ fontSize: 10, padding: '2px 6px', marginLeft: 8 }}
                          onClick={(e) => { e.stopPropagation(); deleteSession(s.session_id); }}>
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      <div className="card" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 200px)', minHeight: 500 }}>
        <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h3 style={{ margin: 0 }}>Reyu Co-pilot</h3>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>
              Conversational view of your analytics — backed by the same engine as the dashboard.
            </span>
          </div>
          <div className="row" style={{ gap: 6 }}>
            <button className="ghost" style={{ fontSize: 11, padding: '4px 10px' }} onClick={newSession}>
              New Chat
            </button>
            <button className="ghost" style={{ fontSize: 11, padding: '4px 10px' }} onClick={toggleSidebar}>
              History
            </button>
          </div>
        </div>

        <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '8px 4px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {messages.map((m, i) => (
            <MessageBubble key={i} m={m} />
          ))}
          {busy && <MessageBubble m={{ role: 'assistant', content: 'Thinking…' }} />}
        </div>

        {/* Prompt chips */}
        {messages.length <= 2 && (
          <div className="row" style={{ flexWrap: 'wrap', gap: 6, padding: '8px 4px', borderTop: '1px solid var(--border)' }}>
            {PROMPTS.map(p => (
              <button key={p} className="ghost" style={{ fontSize: 11, padding: '4px 10px' }}
                      onClick={() => send(p)} disabled={busy}>{p}</button>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="row" style={{ gap: 6, padding: '8px 4px 0', borderTop: '1px solid var(--border)' }}>
          <input
            className="input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) }}}
            placeholder="Ask about bias, hedge, scalping, payoff…"
            disabled={busy}
            style={{ flex: 1 }}
          />
          <button className="primary" onClick={() => send(input)} disabled={busy || !input.trim()}>
            Send
          </button>
        </div>
      </div>
    </div>
  )
}

function MessageBubble({ m }: { m: Msg }) {
  const isUser = m.role === 'user'
  return (
    <div style={{
      display: 'flex',
      justifyContent: isUser ? 'flex-end' : 'flex-start',
      gap: 8,
    }}>
      {!isUser && <Avatar />}
      <div style={{
        maxWidth: '78%',
        background: isUser ? 'var(--accent-bg, rgba(96,165,250,0.18))' : 'var(--panel-hover, var(--panel))',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: '10px 14px',
        fontSize: 13,
        lineHeight: 1.55,
        whiteSpace: 'pre-wrap',
        color: 'var(--text)',
      }}>
        {renderMarkdown(m.content)}
        {m.chart && (
          <img src={(import.meta.env.VITE_API_BASE || 'http://localhost:8000') + m.chart}
               alt="chart"
               style={{ display: 'block', width: '100%', marginTop: 10, borderRadius: 8, border: '1px solid var(--border)' }} />
        )}
        {m.tool && (
          <div style={{ marginTop: 6, fontSize: 10, color: 'var(--muted)' }}>
            via <code>{m.tool}</code>
          </div>
        )}
      </div>
      {isUser && <Avatar user />}
    </div>
  )
}

function Avatar({ user }: { user?: boolean }) {
  return (
    <div style={{
      width: 28, height: 28, borderRadius: 999, flexShrink: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 12, fontWeight: 700,
      background: user ? 'var(--accent)' : 'var(--panel)',
      color: user ? '#0b0e14' : 'var(--accent)',
      border: '1px solid var(--border)',
    }}>{user ? 'U' : 'R'}</div>
  )
}

// Minimal markdown — bold (**text**) and line breaks. We deliberately avoid
// a full markdown library to keep the bundle thin; the tool layer already
// produces clean text.
function renderMarkdown(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={i} style={{ background: 'var(--border)', padding: '1px 4px', borderRadius: 3, fontSize: 11 }}>{part.slice(1, -1)}</code>
    }
    return <span key={i}>{part}</span>
  })
}

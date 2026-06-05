import { useEffect, useRef, useState, useCallback } from 'react'

export type TickMessage = {
  symbol: string
  ts: number
  close: number
  volume: number
}

export type ChainMessage = {
  symbol: string
  ltp: number
  summary: Record<string, any>
  bias: Record<string, any>
}

export type LiveStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

const WS_URL = (() => {
  const base = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
  return base.replace(/^http/, 'ws') + '/ws/ticks'
})()

const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30000

export function useLiveTicks(symbols: string[]) {
  const [status, setStatus] = useState<LiveStatus>('disconnected')
  const [ticks, setTicks] = useState<Record<string, TickMessage>>({})
  const [chains, setChains] = useState<Record<string, ChainMessage>>({})
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const symbolsRef = useRef(symbols)
  symbolsRef.current = symbols

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState <= 1) return // already open/connecting

    setStatus('connecting')
    let ws: WebSocket
    try {
      ws = new WebSocket(WS_URL)
    } catch {
      setStatus('error')
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      setStatus('connected')
      retryRef.current = 0
      // subscribe to current symbols
      if (symbolsRef.current.length > 0) {
        ws.send(JSON.stringify({ subscribe: symbolsRef.current }))
      }
    }

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.symbol != null && msg.close != null) {
          // tick message
          setTicks(prev => ({ ...prev, [msg.symbol]: msg as TickMessage }))
        }
        if (msg.symbol != null && msg.summary != null) {
          // chain snapshot message
          setChains(prev => ({ ...prev, [msg.symbol]: msg as ChainMessage }))
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onerror = () => {
      setStatus('error')
    }

    ws.onclose = () => {
      setStatus('disconnected')
      wsRef.current = null
      scheduleReconnect()
    }

    wsRef.current = ws
  }, [])

  const scheduleReconnect = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    const delay = Math.min(RECONNECT_BASE_MS * Math.pow(2, retryRef.current), RECONNECT_MAX_MS)
    retryRef.current++
    timerRef.current = setTimeout(() => {
      connect()
    }, delay)
  }, [connect])

  // connect on mount, cleanup on unmount
  useEffect(() => {
    connect()
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null // prevent reconnect on intentional close
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  // update subscriptions when symbols change
  useEffect(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && symbols.length > 0) {
      wsRef.current.send(JSON.stringify({ subscribe: symbols }))
    }
  }, [symbols])

  const subscribe = useCallback((syms: string[]) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ subscribe: syms }))
    }
  }, [])

  const unsubscribe = useCallback((syms: string[]) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ unsubscribe: syms }))
    }
  }, [])

  return { status, ticks, chains, subscribe, unsubscribe }
}

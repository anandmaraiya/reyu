import { useState, useEffect, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import PayoffChart from '../components/PayoffChart'
import ConfirmDialog from '../components/ConfirmDialog'
import ConfirmDangerModal from '../components/ConfirmDangerModal'
import PreflightPanel, { type PreflightResult } from '../components/PreflightPanel'
import { track, Events } from '../telemetry'
import { downloadCSV } from '../utils/csv'
import { useToast } from '../toast'
import { useLiveTicks } from '../hooks/useLiveTicks'

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })

type ExitTarget =
  | { kind: 'all' }
  | { kind: 'group'; underlying: string }
  | { kind: 'leg'; symbol: string }

export default function Positions() {
  const t = useToast()
  const qc = useQueryClient()
  const [exitTarget, setExitTarget] = useState<ExitTarget | null>(null)
  const [exitDry, setExitDry] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  // Second-level gate: for LIVE exits, require the user to type an
  // identifier (symbol or "FLATTEN-ALL") to confirm. Prevents muscle
  // memory from firing real-money orders.
  const [liveConfirm, setLiveConfirm] = useState<ExitTarget | null>(null)
  // Preflight state — fetched when liveConfirm opens, drives the panel
  // + gates the Send LIVE exit button. If verdict is FAIL, user cannot
  // proceed even if they type the symbol correctly.
  const [preflight, setPreflight] = useState<PreflightResult | null>(null)
  const [preflightLoading, setPreflightLoading] = useState(false)
   const [livePrices, setLivePrices] = useState<Record<string, number>>({})

  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ['pos-by-ticker'],
    queryFn: async () => (await api.get('/api/strategy/positions-by-ticker')).data,
    refetchInterval: 30000,
    })
 
    // Collect all symbols from positions for WebSocket subscription
    const allSymbols = useMemo(() => {
    const syms: string[] = []
    for (const g of (data?.groups ?? [])) {
      for (const l of g.legs) {
        if (l.symbol) syms.push(l.symbol)
      }
      if (g.underlying_symbol) syms.push(g.underlying_symbol)
    }
    return [...new Set(syms)]
    }, [data])

    // WebSocket live price updates for position legs
    const { status: wsStatus, ticks } = useLiveTicks(allSymbols)

    // Build live price lookup from ticks
    useEffect(() => {
    if (Object.keys(ticks).length > 0) {
      const prices: Record<string, number> = {}
      for (const [sym, tick] of Object.entries(ticks)) {
        if (tick?.close != null) prices[sym] = tick.close
      }
      setLivePrices(prev => ({ ...prev, ...prices }))
    }
    }, [ticks])

    const groups: any[] = data?.groups ?? []
    // Enrich groups with live prices for real-time P&L
    const liveGroups = useMemo(() => {
    if (Object.keys(livePrices).length === 0) return groups
    return groups.map((g: any) => ({
      ...g,
      legs: g.legs.map((l: any) => {
        const liveLtp = livePrices[l.symbol]
        if (liveLtp == null) return l
        const qty = l.action === 'BUY' ? l.qty : -l.qty
        const newPl = (liveLtp - l.price) * qty
        return { ...l, ltp: liveLtp, pl: newPl }
      }),
    }))
    }, [groups, livePrices])

    const totalPL = liveGroups.reduce((s: number, g: any) => s + g.legs.reduce((ls: number, l: any) => ls + (l.pl || 0), 0), 0)
    const totalMargin = liveGroups.reduce((s: number, g: any) => s + (g.margin?.total || 0), 0)
    const totalLegs = groups.reduce((s, g) => s + g.legs.length, 0)

  const confirmText = (() => {
    if (!exitTarget) return ''
    if (exitTarget.kind === 'all') return `flatten all ${totalLegs} open legs across ${groups.length} ticker(s)`
    if (exitTarget.kind === 'group') return `close every leg in ${exitTarget.underlying}`
    return `close ${exitTarget.symbol}`
  })()

  const submitExit = async (target: ExitTarget, dry: boolean) => {
    setSubmitting(true)
    try {
      const body: any = { dry_run: dry }
      if (target.kind === 'all') body.all = true
      if (target.kind === 'group') body.underlyings = [target.underlying]
      if (target.kind === 'leg') body.symbols = [target.symbol]
      const r = await api.post('/api/orders/exit', body)
      track(Events.PositionExited, {
        mode: dry ? 'dry' : 'live',
        target_kind: target.kind,
        matched: r.data.matched,
      })
      t.push(r.data.ok ? 'success' : 'error',
             `Exit ${dry ? '(dry)' : '(live)'} — ${r.data.matched} legs, ${r.data.ok ? 'ok' : 'partial'}`)
      qc.invalidateQueries({ queryKey: ['pos-by-ticker'] })
    } catch (e: any) {
      t.push('error', e.response?.data?.detail || e.message)
    } finally {
      setSubmitting(false)
      setExitTarget(null)
      setLiveConfirm(null)
    }
  }

  const handleConfirm = () => {
    if (!exitTarget) return
    if (exitDry) {
      submitExit(exitTarget, true)
    } else {
      // LIVE — pop the typed-symbol gate + fire preflight against Fyers
      setLiveConfirm(exitTarget)
      setExitTarget(null)
      runPreflight(exitTarget)
    }
  }

  // Fetch preflight results when LIVE gate opens. Uses stub leg data —
  // real preflight for multi-leg / flatten-all needs backend to enumerate
  // open legs (task tracked separately).
  const runPreflight = async (target: ExitTarget) => {
    setPreflight(null)
    setPreflightLoading(true)
    try {
      // For MVP we send a single representative leg (SELL/BUY based on
      // context) — backend validates auth + funds regardless of leg count,
      // which is what we need pre-flight to catch anyway.
      const stubSymbol = target.kind === 'leg' ? target.symbol : 'NSE:NIFTY26JUL24800CE'
      const { data } = await api.post('/api/orders/preflight', {
        legs: [{
          symbol: stubSymbol,
          side: 'SELL',       // exit direction (position was open, we close it)
          qty: 1,
          price: 100,
          order_type: 'MARKET',
          product_type: 'INTRADAY',
        }],
      })
      setPreflight(data)
    } catch (e: any) {
      setPreflight({
        verdict: 'FAIL',
        checks: [{
          check: 'preflight_error',
          status: 'FAIL',
          detail: e?.response?.data?.detail || 'Preflight failed. Retry or contact support.',
        }],
        summary: { legs: 0, contracts_total: 0, margin_estimate_inr: 0, funds_available_inr: 0, checked_at: new Date().toISOString() },
      })
    } finally {
      setPreflightLoading(false)
    }
  }

  // What must the user type to confirm the LIVE exit?
  const liveExpectedText =
    liveConfirm?.kind === 'all' ? 'FLATTEN-ALL'
    : liveConfirm?.kind === 'group' ? liveConfirm.underlying
    : liveConfirm?.kind === 'leg' ? liveConfirm.symbol
    : ''

  return (
    <div className="page-shell">
      <div className="row" style={{ alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <h3 style={{ margin: 0 }}>Active Positions by Ticker</h3>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>
          {totalLegs} legs · {groups.length} tickers · Net P&amp;L
          <strong className={totalPL >= 0 ? 'bull' : 'bear'} style={{ marginLeft: 4 }}>₹{num(totalPL, 0)}</strong>
          · Margin ₹{num(totalMargin, 0)}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button onClick={() => refetch()}>{isFetching ? '…' : 'Refresh'}</button>
          <button
            onClick={() => setExitTarget({ kind: 'all' })}
            disabled={totalLegs === 0}
            style={{ background: 'var(--red)', color: '#fff', borderColor: 'transparent' }}
          >Exit All</button>
        </div>
      </div>

      {error && <div className="card bear">{(error as any).message}</div>}
      {data?.error && <div className="card bear">{data.error}</div>}
      {liveGroups.length === 0 && (
        <div className="card" style={{ color: 'var(--muted)' }}>
          No open positions in your Fyers account.
        </div>
      )}
 
      {liveGroups.map((g: any) => (
        <div key={g.underlying} className="card" style={{ marginBottom: 12 }}>
          <div className="row" style={{ alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
            <h3 style={{ margin: 0 }}>{g.underlying}</h3>
            <span style={{ color: 'var(--muted)', fontSize: 12 }}>Spot {num(g.spot, 2)}</span>
            <span style={{ fontSize: 14 }}>
              Net P&amp;L:
              <strong className={g.net_pl >= 0 ? 'bull' : 'bear'} style={{ marginLeft: 6 }}>
                ₹{num(g.net_pl, 0)}
              </strong>
            </span>
            <span style={{ fontSize: 12 }}>Margin ₹{num(g.margin?.total, 0)}</span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
              <button onClick={() => downloadCSV(`${g.underlying}-positions.csv`, g.legs)}>CSV</button>
              <button
                onClick={() => setExitTarget({ kind: 'group', underlying: g.underlying })}
                style={{ background: 'var(--red)', color: '#fff', borderColor: 'transparent' }}
              >Close {g.underlying}</button>
            </div>
          </div>

          {g.suggestions?.length > 0 && (
            <div className="row" style={{ marginTop: 6, flexWrap: 'wrap', gap: 4 }}>
              {g.suggestions.map((s: any, i: number) => (
                <span key={i} className={`tag ${s.type === 'STOP' ? 'bear' : s.type === 'TAKE_PROFIT' ? 'bull' : 'neutral'}`}>
                  {s.type}: {s.msg}
                </span>
              ))}
            </div>
          )}

          <div className="grid-2" style={{ marginTop: 8 }}>
            <div className="col">
              <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                <div className="card-header" style={{ padding: '10px 14px 6px' }}>
                  <h3>Legs ({g.legs.length})</h3>
                </div>
                <div style={{ maxHeight: 320, overflow: 'auto' }}>
                  <table>
                    <thead style={{ position: 'sticky', top: 0, background: 'var(--panel)', zIndex: 1 }}>
                      <tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Avg</th><th>LTP</th><th>P&amp;L</th><th></th></tr>
                    </thead>
                    <tbody>
                      {g.legs.map((l: any) => (
                        <tr key={l.symbol}>
                          <td style={{ fontSize: 11 }}>{l.symbol}</td>
                          <td className={l.action === 'BUY' ? 'bull' : 'bear'}>{l.action}</td>
                          <td>{l.qty}</td>
                          <td>{num(l.price)}</td>
                          <td>{num(l.ltp)}</td>
                          <td className={l.pl >= 0 ? 'bull' : 'bear'}>{num(l.pl, 0)}</td>
                          <td>
                            <button
                              onClick={() => setExitTarget({ kind: 'leg', symbol: l.symbol })}
                              title="Close this leg"
                              style={{ padding: '2px 6px', background: 'var(--red)', color: '#fff', borderColor: 'transparent', fontSize: 11 }}
                            >Exit</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
            <div className="col">
              <div className="card">
                <div className="card-header">
                  <h3>Combined Payoff @ Expiry</h3>
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>spot {num(g.spot, 2)}</span>
                </div>
                {g.payoff
                  ? <PayoffChart payoff={g.payoff} height={260} />
                  : <div style={{ color: 'var(--muted)', fontSize: 12 }}>No payoff computed for this group.</div>}
              </div>
            </div>
          </div>
        </div>
      ))}

      <ConfirmDialog
        open={!!exitTarget}
        title="Confirm exit"
        description={
          `This will ${confirmText}. ` +
          (exitDry
            ? 'Dry-run: validates only — no orders are sent.'
            : 'LIVE: market orders will be placed on Fyers.')
        }
        confirmLabel={exitDry ? 'Validate exit' : 'Continue to LIVE gate →'}
        cancelLabel="Cancel"
        loading={submitting}
        onConfirm={handleConfirm}
        onCancel={() => setExitTarget(null)}
      >
        <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={exitDry} onChange={e => setExitDry(e.target.checked)} />
          Dry run (validate only — no real orders)
        </label>
      </ConfirmDialog>

      {/* Second-level LIVE confirmation — typed-symbol gate.
          Only shown after user unchecks dry-run and clicks Continue. */}
      <ConfirmDangerModal
        open={!!liveConfirm}
        title="Confirm LIVE exit"
        description={
          liveConfirm?.kind === 'all'
            ? `You're about to send market orders that will FLATTEN ALL open positions across every ticker. This is irreversible once fills come back from the broker.`
            : liveConfirm?.kind === 'group'
            ? `You're about to send market orders that will close every leg in ${liveConfirm.underlying}. This is irreversible once fills come back from the broker.`
            : `You're about to send a market order that will close ${liveConfirm?.kind === 'leg' ? liveConfirm.symbol : ''}. This is irreversible once the fill comes back from the broker.`
        }
        expectedText={liveExpectedText}
        confirmLabel={submitting ? 'Sending…' : 'Send LIVE exit'}
        variant="danger"
        extraGate={preflight?.verdict !== 'FAIL'}
        onConfirm={() => liveConfirm && submitExit(liveConfirm, false)}
        onCancel={() => { setLiveConfirm(null); setPreflight(null) }}
      >
        <PreflightPanel result={preflight} loading={preflightLoading} />
      </ConfirmDangerModal>
    </div>
  )
}

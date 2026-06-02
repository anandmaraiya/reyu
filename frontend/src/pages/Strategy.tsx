import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api, Chain } from '../api'
import PayoffChart from '../components/PayoffChart'
import { useToast } from '../toast'
import { downloadCSV } from '../utils/csv'
import { detectStrategyName, RiskMeter, PopGauge } from '../components/StrategyVisuals'

type Leg = { symbol: string; action: 'BUY' | 'SELL'; qty: number; price: number; strike?: number; option_type?: 'CE' | 'PE'; lot_size: number }
type Template = { key: string; view: string; label: string; desc: string }

const num = (n: any, d = 2) => n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d })
const pct = (n: any) => n == null ? '—' : (n * 100).toFixed(1) + '%'

const PRESETS = ['NSE:NIFTY50-INDEX', 'NSE:NIFTYBANK-INDEX', 'NSE:FINNIFTY-INDEX', 'NSE:MIDCPNIFTY-INDEX', 'BSE:SENSEX-INDEX']

const lotFor = (sym: string): number => {
  const s = sym.toUpperCase()
  if (s.includes('BANKNIFTY') || s.includes('BANKEX')) return 30
  if (s.includes('FINNIFTY')) return 65
  if (s.includes('MIDCPNIFTY')) return 120
  if (s.includes('SENSEX')) return 20
  if (s.includes('NIFTY')) return 75
  return 1
}

export default function Strategy() {
  const t = useToast()
  const [underlying, setUnderlying] = useState('NSE:NIFTY50-INDEX')
  const [expiry, setExpiry] = useState('')
  const [strikecount, setStrikecount] = useState(25)
  const [legs, setLegs] = useState<Leg[]>([])
  const [analysis, setAnalysis] = useState<any>(null)
  const [analysing, setAnalysing] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveView, setSaveView] = useState('NEUTRAL')
  const [showSend, setShowSend] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [searchParams] = useSearchParams()
  const selectedStrikes = useMemo(() => {
    return searchParams.get('selected')?.split(',').map(s => Number(s)).filter(Boolean) ?? []
  }, [searchParams])

  useEffect(() => {
    const underlyingParam = searchParams.get('underlying')
    if (underlyingParam) setUnderlying(underlyingParam)
    const expiryParam = searchParams.get('expiry')
    if (expiryParam) setExpiry(expiryParam)
  }, [searchParams])

  const { data: chain } = useQuery<Chain>({
    queryKey: ['chain', underlying, strikecount, expiry],
    queryFn: async () => (await api.get('/api/options/chain', { params: { symbol: underlying, strikecount, expiry } })).data,
    refetchInterval: 30000,
  })
  const { data: tpls } = useQuery<Template[]>({
    queryKey: ['templates'],
    queryFn: async () => (await api.get('/api/strategy/templates')).data,
  })

  const atm = chain?.summary.atm_strike
  const strikeRows = chain?.strikes || []

  useEffect(() => {
    if (legs.length === 0) { setAnalysis(null); return }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      setAnalysing(true)
      try {
        const r = await api.post('/api/strategy/analyse', {
          underlying,
          // Keep strike + option_type so the backend doesn't have to rely on
          // the symbol regex; it can mis-parse weekly Fyers symbols.
          legs: legs.map(({ lot_size, ...rest }) => rest),
          range_pct: 0.12, strikecount,
        })
        setAnalysis(r.data)
      } catch (e: any) {
        t.push('error', e.response?.data?.detail || e.message)
      } finally { setAnalysing(false) }
    }, 350)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(legs), underlying, strikecount])

  const addLeg = (row: any, side: 'ce' | 'pe', action: 'BUY' | 'SELL') => {
    const leg = row[side]; if (!leg?.symbol) return
    const lot = lotFor(leg.symbol)
    setLegs(p => [...p, { symbol: leg.symbol, action, qty: lot, price: leg.ltp, strike: row.strike, option_type: side.toUpperCase() as any, lot_size: lot }])
  }
  const removeLeg = (i: number) => setLegs(p => p.filter((_, j) => j !== i))
  const setLots = (i: number, lots: number) =>
    setLegs(p => p.map((l, j) => j === i ? { ...l, qty: Math.max(1, lots) * l.lot_size } : l))
  const updateLeg = (i: number, patch: Partial<Leg>) =>
    setLegs(p => p.map((l, j) => j === i ? { ...l, ...patch } : l))

  const applyTemplate = async (key: string) => {
    try {
      const r = await api.post('/api/strategy/template/apply', { key, underlying, lots: 1, strikecount })
      const newLegs: Leg[] = r.data.legs.map((l: any) => ({
        symbol: l.symbol, action: l.action, qty: l.qty * lotFor(l.symbol),
        price: l.price, strike: l.strike, option_type: l.option_type, lot_size: lotFor(l.symbol),
      }))
      setLegs(newLegs)
      t.push('success', `Applied ${key.replaceAll('_', ' ')}`)
    } catch (e: any) {
      t.push('error', e.response?.data?.detail || e.message)
    }
  }

  const saveStrategy = async () => {
    if (!saveName) return t.push('error', 'Name required')
    await api.put('/api/strategy/saved', {
      name: saveName, underlying, view: saveView,
      legs: legs.map(l => ({ symbol: l.symbol, action: l.action, qty: l.qty, price: l.price })),
    })
    t.push('success', `Saved "${saveName}"`); setSaveName('')
  }

  const sendBatch = async (dryRun: boolean) => {
    const payload = {
      label: `${underlying} ${legs.length}-leg`,
      dry_run: dryRun,
      legs: legs.map(l => ({
        symbol: l.symbol, qty: l.qty, side: l.action,
        order_type: 'MARKET', product: 'INTRADAY', dry_run: dryRun,
      })),
    }
    try {
      const r = await api.post('/api/orders/batch', payload)
      if (r.data.errors) {
        t.push('error', `Validation: ${r.data.errors.map((e: any) => e.error).join('; ')}`)
      } else {
        t.push(dryRun ? 'info' : 'success', dryRun ? 'Dry-run OK' : 'Orders sent')
        setShowSend(false)
      }
    } catch (e: any) {
      t.push('error', e.response?.data?.detail || e.message)
    }
  }

  const exportLegs = () =>
    downloadCSV(`${underlying}-strategy.csv`, legs.map(l => ({ ...l })))

  const netDebit = useMemo(() => legs.reduce((s, l) => s + (l.action === 'BUY' ? 1 : -1) * l.price * l.qty, 0), [legs])

  const strategyName = useMemo(() => detectStrategyName(legs), [legs])

  return (
    <div>
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="row" style={{ alignItems: 'baseline', gap: 10 }}>
          <h3 style={{ margin: 0 }}>Configure</h3>
          {legs.length > 0 && (
            <span className="tag" style={{ background: 'rgba(96,165,250,.15)', color: 'var(--accent)' }}>{strategyName}</span>
          )}
        </div>
        <div className="row" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ fontSize: 12, color: 'var(--muted)' }}>Underlying</label>
          <select value={underlying} onChange={e => { setUnderlying(e.target.value); setLegs([]); setAnalysis(null) }}>
            {PRESETS.map(p => <option key={p}>{p}</option>)}
          </select>
          <label style={{ fontSize: 12, color: 'var(--muted)' }}>Expiry</label>
          <select value={expiry} onChange={e => { setExpiry(e.target.value); setLegs([]); setAnalysis(null) }}>
            <option value="">Default</option>
            {chain?.expiries?.map(exp => (
              <option key={exp.expiry} value={exp.expiry}>{exp.date}</option>
            ))}
          </select>
          <label style={{ fontSize: 12, color: 'var(--muted)' }}>Strikes</label>
          <select value={strikecount} onChange={e => setStrikecount(+e.target.value)}>
            <option value={15}>15 central</option><option value={25}>25 central</option><option value={40}>40 central</option>
          </select>
          <span style={{ color: 'var(--muted)', fontSize: 12 }}>
            Spot {num(chain?.ltp, 2)} · ATM {atm} · IV {pct(chain?.summary.atm_iv)}
          </span>
          {analysing && <span style={{ fontSize: 11, color: 'var(--accent)' }}>analysing…</span>}
          <button onClick={exportLegs} disabled={legs.length === 0}>Export CSV</button>
          <button onClick={() => { setLegs([]); setAnalysis(null) }}>Clear</button>
        </div>

        <div className="row" style={{ marginTop: 10, flexWrap: 'wrap' }}>
          <label style={{ fontSize: 11, color: 'var(--muted)', minWidth: 80 }}>Templates:</label>
          {tpls?.map(tp => (
            <button key={tp.key} onClick={() => applyTemplate(tp.key)} title={tp.desc}
                    style={{ fontSize: 11, padding: '3px 8px' }}>
              {tp.label} <span style={{ color: 'var(--muted)' }}>· {tp.view}</span>
            </button>
          ))}
        </div>
      </div>

      {selectedStrikes.length > 0 && (
        <div className="card-glass summary-banner" style={{ marginBottom: 12 }}>
          <strong>{selectedStrikes.length} strike{selectedStrikes.length === 1 ? '' : 's'}</strong> loaded from dashboard.
          <span style={{ color: 'var(--muted)', marginLeft: 8 }}>Use these strikes as a starting point for your strategy.</span>
        </div>
      )}

      <div className="row">
        <div className="card col" style={{ flex: 1, minWidth: 360 }}>
          <h3>Strikes — click B/S to add</h3>
          <div style={{ maxHeight: 520, overflow: 'auto' }}>
            <table style={{ fontSize: 11, width: '100%' }}>
              <thead style={{ position: 'sticky', top: 0, background: 'var(--panel)', zIndex: 1 }}>
                <tr><th colSpan={2}>CE</th><th style={{ textAlign: 'right' }}>LTP</th><th style={{ textAlign: 'center' }}>Strike</th><th style={{ textAlign: 'right' }}>LTP</th><th colSpan={2}>PE</th></tr>
              </thead>
            <tbody>
              {strikeRows.map(s => {
                const selectedRow = selectedStrikes.includes(s.strike)
                return (
                  <tr key={s.strike} className={`${s.strike === atm ? 'atm' : ''} ${selectedRow ? 'selected-row' : ''}`}>
                    <td><button onClick={() => addLeg(s, 'ce', 'BUY')} style={{ background: 'var(--green)', color: '#fff', borderColor: 'transparent', padding: '2px 6px' }} disabled={!s.ce}>B</button></td>
                    <td><button onClick={() => addLeg(s, 'ce', 'SELL')} style={{ background: 'var(--red)', color: '#fff', borderColor: 'transparent', padding: '2px 6px' }} disabled={!s.ce}>S</button></td>
                    <td style={{ fontSize: 11 }}>{num(s.ce?.ltp)}</td>
                    <td style={{ textAlign: 'center', fontWeight: 600 }}>{s.strike}</td>
                    <td style={{ fontSize: 11 }}>{num(s.pe?.ltp)}</td>
                    <td><button onClick={() => addLeg(s, 'pe', 'BUY')} style={{ background: 'var(--green)', color: '#fff', borderColor: 'transparent', padding: '2px 6px' }} disabled={!s.pe}>B</button></td>
                    <td><button onClick={() => addLeg(s, 'pe', 'SELL')} style={{ background: 'var(--red)', color: '#fff', borderColor: 'transparent', padding: '2px 6px' }} disabled={!s.pe}>S</button></td>
                  </tr>)
                })
              }
            </tbody>
            </table>
          </div>
        </div>

        <div className="col" style={{ flex: 2 }}>
          <div className="card">
            <div className="row" style={{ alignItems: 'center' }}>
              <h3 style={{ margin: 0 }}>Legs ({legs.length})</h3>
              {legs.length > 0 && (
                <div className="row" style={{ marginLeft: 'auto' }}>
                  <input className="input" placeholder="Save name" value={saveName} onChange={e => setSaveName(e.target.value)} style={{ width: 140 }} />
                  <select value={saveView} onChange={e => setSaveView(e.target.value)}>
                    <option>BULLISH</option><option>BEARISH</option><option>NEUTRAL</option>
                    <option>VOL_LONG</option><option>VOL_SHORT</option>
                  </select>
                  <button onClick={saveStrategy}>Save</button>
                  <button className="primary" onClick={() => setShowSend(true)}>Send all legs →</button>
                </div>
              )}
            </div>
            {legs.length === 0 && <div style={{ color: 'var(--muted)', fontSize: 12 }}>Click B/S on a strike or apply a template to start. The scenario updates live.</div>}
            {legs.length > 0 && (
              <table style={{ marginTop: 8 }}>
                <thead><tr><th>Symbol</th><th>Action</th><th>Lots</th><th>Units × Price</th><th>Price</th><th /></tr></thead>
                <tbody>
                  {legs.map((l, i) => (
                    <tr key={i}>
                      <td style={{ fontSize: 11 }}>{l.symbol}</td>
                      <td><select value={l.action} onChange={e => updateLeg(i, { action: e.target.value as any })}><option>BUY</option><option>SELL</option></select></td>
                      <td>
                        <div className="row" style={{ gap: 2 }}>
                          <button onClick={() => setLots(i, Math.floor(l.qty / l.lot_size) - 1)}>−</button>
                          <input className="input" type="number" min={1} value={Math.floor(l.qty / l.lot_size)} onChange={e => setLots(i, +e.target.value)} style={{ width: 50 }} />
                          <button onClick={() => setLots(i, Math.floor(l.qty / l.lot_size) + 1)}>+</button>
                        </div>
                      </td>
                      <td style={{ fontSize: 11, color: 'var(--muted)' }}>{l.qty} × ₹{num(l.price)}</td>
                      <td><input className="input" type="number" step={0.05} value={l.price} onChange={e => updateLeg(i, { price: +e.target.value })} style={{ width: 80 }} /></td>
                      <td><button onClick={() => removeLeg(i)}>×</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>
              Net premium: {netDebit >= 0 ? `₹ ${num(netDebit, 0)} debit` : `₹ ${num(-netDebit, 0)} credit`}
            </div>
          </div>

          {analysis?.payoff && (
            <>
              <div className="row" style={{ marginTop: 12 }}>
                <div className="card col"><h3>Margin</h3>
                  <div className="kpi">₹ {num(analysis.margin?.total, 0)}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                    {analysis.margin?.source === 'fyers' ? 'Fyers SPAN + Exposure' : `${analysis.margin?.category} (est)`}
                  </div>
                </div>
                <div className="card col" style={{ alignItems: 'center', display: 'flex', flexDirection: 'column' }}>
                  <h3 style={{ alignSelf: 'flex-start' }}>POP & Risk</h3>
                  <PopGauge pop={analysis.pop?.pop} />
                  <div style={{ fontSize: 10, color: 'var(--muted)', textAlign: 'center', marginTop: 2 }}>
                    1σ {analysis.pop?.expected_1sd_range?.map((v: number) => num(v, 0)).join(' – ') || '—'}
                  </div>
                  <div style={{ width: '100%', marginTop: 8 }}>
                    <RiskMeter maxLoss={analysis.payoff.max_loss} margin={analysis.margin?.total || 0} />
                  </div>
                </div>
                <div className="card col"><h3>Net Greeks</h3>
                  <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                    Δ {num(analysis.payoff.greeks.delta, 3)}<br />Γ {num(analysis.payoff.greeks.gamma, 4)}<br />
                    θ {num(analysis.payoff.greeks.theta, 2)}<br />Vega {num(analysis.payoff.greeks.vega, 2)}
                  </div>
                </div>
                <div className="card col"><h3>P&amp;L at expiry</h3>
                  <div className="bull" style={{ fontSize: 14 }}>Max ₹{num(analysis.payoff.max_profit, 0)}</div>
                  <div className="bear" style={{ fontSize: 14 }}>Min ₹{num(analysis.payoff.max_loss, 0)}</div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>BE: {analysis.payoff.breakevens.map((b: number) => num(b, 0)).join(', ') || '—'}</div>
                </div>
                <div className="card col"><h3>R:R / ROI</h3>
                  <div className="kpi small">{analysis.payoff.max_loss ? num(Math.abs(analysis.payoff.max_profit / analysis.payoff.max_loss), 2) : '∞'}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                    ROI on margin: {analysis.margin?.total ? ((analysis.payoff.max_profit / analysis.margin.total) * 100).toFixed(1) + '%' : '—'}
                  </div>
                </div>
              </div>

              <div className="card" style={{ marginTop: 12 }}>
                <h3>Payoff @ expiry</h3>
                <PayoffChart payoff={analysis.payoff} />
              </div>

              {analysis.scenarios?.length > 0 && (
                <div className="card" style={{ marginTop: 12 }}>
                  <div className="card-header">
                    <h3>What-if scenarios</h3>
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                      P&amp;L at expiry across spot moves
                    </span>
                  </div>
                  <table>
                    <thead><tr><th>Move</th><th>Spot</th><th>P&amp;L @ expiry</th></tr></thead>
                    <tbody>
                      {analysis.scenarios.map((s: any) => (
                        <tr key={s.move_pct}>
                          <td className={s.move_pct > 0 ? 'bull' : s.move_pct < 0 ? 'bear' : ''}>{s.move_pct > 0 ? '+' : ''}{s.move_pct}%</td>
                          <td>{num(s.spot, 0)}</td>
                          <td className={s.pnl >= 0 ? 'bull' : 'bear'}>₹ {num(s.pnl, 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {showSend && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }} onClick={() => setShowSend(false)}>
          <div className="card" style={{ width: 480 }} onClick={e => e.stopPropagation()}>
            <h3>Send {legs.length}-leg order</h3>
            <table>
              <thead><tr><th>Symbol</th><th>Action</th><th>Qty</th></tr></thead>
              <tbody>
                {legs.map((l, i) => (
                  <tr key={i}><td style={{ fontSize: 11 }}>{l.symbol}</td><td className={l.action === 'BUY' ? 'bull' : 'bear'}>{l.action}</td><td>{l.qty}</td></tr>
                ))}
              </tbody>
            </table>
            <div style={{ fontSize: 12, color: 'var(--muted)', margin: '8px 0' }}>
              Margin: ₹{num(analysis?.margin?.total, 0)} · Premium: ₹{num(Math.abs(netDebit), 0)} {netDebit >= 0 ? 'debit' : 'credit'}
            </div>
            <div className="row">
              <button onClick={() => setShowSend(false)} style={{ flex: 1 }}>Cancel</button>
              <button onClick={() => sendBatch(true)} style={{ flex: 1 }}>Validate (dry-run)</button>
              <button className="primary" onClick={() => sendBatch(false)} style={{ flex: 2, background: 'var(--green)', borderColor: 'transparent', color: '#fff' }}>Send LIVE</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

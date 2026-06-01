import { useEffect, useState } from 'react'
import { api } from '../api'

type Props = {
  symbol: string
  side: 'BUY' | 'SELL'
  defaultPrice?: number
  onClose: () => void
}

type Preview = {
  symbol: string
  instrument: 'EQUITY' | 'INDEX' | 'OPTION' | 'FUTURE' | 'UNKNOWN'
  underlying: string | null
  strike: number | null
  option_type: 'CE' | 'PE' | null
  lot_size: number
  tick_size: number
  tradable: boolean
  suggested_qty: number
  qty_valid: boolean | null
  qty_error: string | null
}

const roundTick = (p: number, tick: number) => tick > 0 ? Math.round(p / tick) * tick : p

export default function OrderModal({ symbol, side, defaultPrice = 0, onClose }: Props) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [qty, setQty] = useState(1)
  const [orderType, setOrderType] = useState<'MARKET' | 'LIMIT' | 'SL' | 'SL-M'>('MARKET')
  const [limitPrice, setLimitPrice] = useState(defaultPrice)
  const [stopPrice, setStopPrice] = useState(0)
  const [product, setProduct] = useState<'INTRADAY' | 'CNC' | 'MARGIN' | 'BO' | 'CO'>('INTRADAY')
  const [takeProfit, setTakeProfit] = useState(0)
  const [stopLoss, setStopLoss] = useState(0)
  const [dryRun, setDryRun] = useState(true)
  const [result, setResult] = useState<any>(null)
  const [submitting, setSubmitting] = useState(false)

  // Load instrument metadata once
  useEffect(() => {
    api.get('/api/orders/preview', { params: { symbol } }).then(r => {
      const p: Preview = r.data
      setPreview(p)
      setQty(p.suggested_qty)
      // Equity defaults to CNC, F&O to INTRADAY
      if (p.instrument === 'EQUITY') setProduct('CNC')
    }).catch(e => setResult({ error: e.response?.data?.detail || e.message }))
  }, [symbol])

  // Live qty validation
  useEffect(() => {
    if (!preview) return
    api.get('/api/orders/preview', { params: { symbol, qty } }).then(r => setPreview(p => p && { ...p, qty_valid: r.data.qty_valid, qty_error: r.data.qty_error }))
  }, [qty, symbol, preview?.lot_size])

  if (!preview) {
    return (
      <Backdrop onClose={onClose}>
        <div className="card" style={{ width: 420 }}>Loading instrument…</div>
      </Backdrop>
    )
  }

  const lots = preview.lot_size > 0 ? Math.floor(qty / preview.lot_size) : null
  const isFno = preview.instrument === 'OPTION' || preview.instrument === 'FUTURE'
  const minQty = isFno ? preview.lot_size : 1
  const stepQty = isFno ? preview.lot_size : 1
  const value = qty * (orderType === 'MARKET' ? defaultPrice : limitPrice)

  const submit = async () => {
    setSubmitting(true)
    try {
      const r = await api.post('/api/orders', {
        symbol, qty, side, order_type: orderType, product,
        limit_price: roundTick(limitPrice, preview.tick_size),
        stop_price: roundTick(stopPrice, preview.tick_size),
        take_profit: takeProfit, stop_loss: stopLoss,
        validity: 'DAY', dry_run: dryRun,
      })
      setResult(r.data)
    } catch (e: any) {
      setResult({ error: e.response?.data?.detail || e.message })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Backdrop onClose={onClose}>
      <div className="card" style={{ width: 460 }} onClick={e => e.stopPropagation()}>
        <h3>
          {side} {symbol}
          <span className="tag neutral" style={{ marginLeft: 8 }}>{preview.instrument}</span>
        </h3>

        {!preview.tradable && (
          <div className="tag bear" style={{ marginBottom: 8 }}>
            Indices are not tradable directly. Use options or futures of the underlying.
          </div>
        )}

        <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
          Lot {preview.lot_size || '—'} · Tick ₹{preview.tick_size}
          {preview.strike && ` · K=${preview.strike} ${preview.option_type}`}
        </div>

        <Field label="Qty">
          <div className="row" style={{ flex: 1 }}>
            <button onClick={() => setQty(Math.max(minQty, qty - stepQty))}>−</button>
            <input className="input" type="number" min={minQty} step={stepQty} value={qty}
                   onChange={e => setQty(+e.target.value)} style={{ flex: 1 }} />
            <button onClick={() => setQty(qty + stepQty)}>+</button>
          </div>
        </Field>
        {isFno && <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>
          {lots} lot(s) × {preview.lot_size} = {qty} units
        </div>}
        {preview.qty_valid === false && (
          <div className="tag bear" style={{ marginBottom: 6 }}>{preview.qty_error}</div>
        )}

        <Field label="Type">
          <select value={orderType} onChange={e => setOrderType(e.target.value as any)} style={{ flex: 1 }}>
            <option>MARKET</option><option>LIMIT</option><option>SL</option><option>SL-M</option>
          </select>
        </Field>

        {(orderType === 'LIMIT' || orderType === 'SL') && (
          <Field label="Limit ₹">
            <input className="input" type="number" step={preview.tick_size} value={limitPrice}
                   onChange={e => setLimitPrice(+e.target.value)} style={{ flex: 1 }} />
          </Field>
        )}
        {(orderType === 'SL' || orderType === 'SL-M') && (
          <Field label="Trigger ₹">
            <input className="input" type="number" step={preview.tick_size} value={stopPrice}
                   onChange={e => setStopPrice(+e.target.value)} style={{ flex: 1 }} />
          </Field>
        )}

        <Field label="Product">
          <select value={product} onChange={e => setProduct(e.target.value as any)} style={{ flex: 1 }}>
            <option>INTRADAY</option>
            {preview.instrument === 'EQUITY' && <option>CNC</option>}
            <option>MARGIN</option><option>BO</option><option>CO</option>
          </select>
        </Field>

        {product === 'BO' && (
          <>
            <Field label="Take Profit ₹"><input className="input" type="number" step={preview.tick_size} value={takeProfit} onChange={e => setTakeProfit(+e.target.value)} style={{ flex: 1 }} /></Field>
            <Field label="Stop Loss ₹"><input className="input" type="number" step={preview.tick_size} value={stopLoss} onChange={e => setStopLoss(+e.target.value)} style={{ flex: 1 }} /></Field>
          </>
        )}

        <div style={{ fontSize: 12, color: 'var(--muted)', margin: '8px 0' }}>
          Est. value: <strong>₹ {value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>
        </div>

        <div className="row" style={{ marginBottom: 12, alignItems: 'center' }}>
          <label style={{ fontSize: 12 }}>
            <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} /> Dry run (validate only)
          </label>
        </div>
        <div className="row">
          <button onClick={onClose} style={{ flex: 1 }}>Cancel</button>
          <button
            className="primary"
            onClick={submit}
            disabled={submitting || preview.qty_valid === false || !preview.tradable}
            style={{ flex: 2, background: side === 'BUY' ? 'var(--green)' : 'var(--red)', borderColor: 'transparent', color: '#fff' }}>
            {submitting ? 'Sending…' : dryRun ? `Validate ${side}` : `Send ${side}`}
          </button>
        </div>
        {result && (
          <pre style={{ marginTop: 10, fontSize: 11, background: '#0f1422', padding: 8, borderRadius: 6, maxHeight: 180, overflow: 'auto' }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </div>
    </Backdrop>
  )
}

function Backdrop({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
    }} onClick={onClose}>
      {children}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="row" style={{ marginBottom: 6, alignItems: 'center' }}>
      <label style={{ fontSize: 12, color: 'var(--muted)', minWidth: 90 }}>{label}</label>
      {children}
    </div>
  )
}

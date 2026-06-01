import { useState } from 'react'
import { api } from '../api'

type Props = {
  symbol: string
  side: 'BUY' | 'SELL'
  defaultPrice?: number
  onClose: () => void
}

export default function OrderModal({ symbol, side, defaultPrice = 0, onClose }: Props) {
  const [qty, setQty] = useState(1)
  const [orderType, setOrderType] = useState<'MARKET' | 'LIMIT' | 'SL' | 'SL-M'>('MARKET')
  const [limitPrice, setLimitPrice] = useState(defaultPrice)
  const [stopPrice, setStopPrice] = useState(0)
  const [product, setProduct] = useState<'INTRADAY' | 'CNC' | 'MARGIN'>('INTRADAY')
  const [dryRun, setDryRun] = useState(true)
  const [result, setResult] = useState<any>(null)
  const [submitting, setSubmitting] = useState(false)

  const submit = async () => {
    setSubmitting(true)
    try {
      const r = await api.post('/api/orders', {
        symbol, qty, side, order_type: orderType, product,
        limit_price: limitPrice, stop_price: stopPrice,
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
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
    }} onClick={onClose}>
      <div className="card" style={{ width: 420 }} onClick={e => e.stopPropagation()}>
        <h3>{side} {symbol}</h3>
        <div className="row" style={{ marginBottom: 6 }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', minWidth: 70 }}>Qty</label>
          <input className="input" type="number" min={1} value={qty} onChange={e => setQty(+e.target.value)} style={{ flex: 1 }} />
        </div>
        <div className="row" style={{ marginBottom: 6 }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', minWidth: 70 }}>Type</label>
          <select value={orderType} onChange={e => setOrderType(e.target.value as any)} style={{ flex: 1 }}>
            <option>MARKET</option><option>LIMIT</option><option>SL</option><option>SL-M</option>
          </select>
        </div>
        {(orderType === 'LIMIT' || orderType === 'SL') && (
          <div className="row" style={{ marginBottom: 6 }}>
            <label style={{ fontSize: 12, color: 'var(--muted)', minWidth: 70 }}>Limit ₹</label>
            <input className="input" type="number" step={0.05} value={limitPrice} onChange={e => setLimitPrice(+e.target.value)} style={{ flex: 1 }} />
          </div>
        )}
        {(orderType === 'SL' || orderType === 'SL-M') && (
          <div className="row" style={{ marginBottom: 6 }}>
            <label style={{ fontSize: 12, color: 'var(--muted)', minWidth: 70 }}>Trigger ₹</label>
            <input className="input" type="number" step={0.05} value={stopPrice} onChange={e => setStopPrice(+e.target.value)} style={{ flex: 1 }} />
          </div>
        )}
        <div className="row" style={{ marginBottom: 8 }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', minWidth: 70 }}>Product</label>
          <select value={product} onChange={e => setProduct(e.target.value as any)} style={{ flex: 1 }}>
            <option>INTRADAY</option><option>CNC</option><option>MARGIN</option>
          </select>
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
            disabled={submitting}
            style={{ flex: 2, background: side === 'BUY' ? 'var(--green)' : 'var(--red)', borderColor: 'transparent', color: '#fff' }}>
            {submitting ? 'Sending…' : dryRun ? `Validate ${side}` : `Send ${side}`}
          </button>
        </div>
        {result && (
          <pre style={{ marginTop: 10, fontSize: 11, background: '#0f1422', padding: 8, borderRadius: 6, maxHeight: 140, overflow: 'auto' }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

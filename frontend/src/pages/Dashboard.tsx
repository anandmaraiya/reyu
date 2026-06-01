import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, Chain } from '../api'
import OptionChainTable from '../components/OptionChainTable'
import SummaryStrip from '../components/SummaryStrip'
import OIChart from '../components/OIChart'
import HedgeBuilder from '../components/HedgeBuilder'
import PCRTimeSeries from '../components/PCRTimeSeries'
import OrderModal from '../components/OrderModal'
import IVSmile from '../components/IVSmile'
import GreeksHeatmap from '../components/GreeksHeatmap'
import { useToast } from '../toast'
import { downloadCSV } from '../utils/csv'

export default function Dashboard() {
  const t = useToast()
  const [symbol, setSymbol] = useState('NSE:NIFTY50-INDEX')
  const [input, setInput] = useState(symbol)
  const [strikes, setStrikes] = useState(25)
  const [expiry, setExpiry] = useState('')
  const [order, setOrder] = useState<{ symbol: string; side: 'BUY' | 'SELL'; price?: number } | null>(null)

  const { data, isFetching, error, refetch } = useQuery<Chain>({
    queryKey: ['chain', symbol, strikes, expiry],
    queryFn: async () => (await api.get('/api/options/chain', { params: { symbol, strikecount: strikes, expiry } })).data,
    refetchInterval: 15000,
  })

  const track = async () => {
    await api.post('/api/ts/track', null, { params: { symbol, tracked: true } })
    t.push('success', `Tracking ${symbol} — snapshots will start within ~60s.`)
  }
  const exportChain = () => {
    if (!data) return
    downloadCSV(`${symbol}-chain.csv`, data.strikes.map(s => ({
      strike: s.strike,
      ce_ltp: s.ce?.ltp, ce_oi: s.ce?.oi, ce_oi_change: s.ce?.oi_change, ce_iv: s.ce?.iv, ce_delta: s.ce?.delta,
      pe_ltp: s.pe?.ltp, pe_oi: s.pe?.oi, pe_oi_change: s.pe?.oi_change, pe_iv: s.pe?.iv, pe_delta: s.pe?.delta,
    })))
  }

  return (
    <div>
      <div className="row" style={{ alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <input className="input" value={input} onChange={e => setInput(e.target.value)}
               style={{ width: 240 }} placeholder="NSE:NIFTY50-INDEX" />
        <select value={strikes} onChange={e => setStrikes(+e.target.value)}>
          <option value={15}>15 strikes</option>
          <option value={25}>25 strikes</option>
          <option value={40}>40 strikes</option>
        </select>
        <select value={expiry} onChange={e => setExpiry(e.target.value)} title="Expiry">
          <option value="">Nearest expiry</option>
          {data?.expiries?.map(e => <option key={e.expiry} value={e.expiry}>{e.date}</option>)}
        </select>
        <button className="primary" onClick={() => setSymbol(input)}>Load</button>
        <button onClick={() => refetch()}>{isFetching ? 'Loading…' : 'Refresh'}</button>
        <button onClick={track}>★ Track 1-min</button>
        <button onClick={exportChain}>CSV</button>
        {error && <span className="bear">{(error as any).message}</span>}
      </div>

      {data && (
        <>
          <SummaryStrip chain={data} />

          <div style={{ marginTop: 12 }}>
            <PCRTimeSeries symbol={symbol} />
          </div>

          <div className="row" style={{ marginTop: 12 }}>
            <div className="col" style={{ flex: 1 }}><IVSmile chain={data} /></div>
            <div className="col" style={{ flex: 1 }}><GreeksHeatmap chain={data} /></div>
          </div>

          <div className="row" style={{ marginTop: 12 }}>
            <div className="col" style={{ flex: 2 }}>
              <div className="card">
                <h3>Option Chain — click ATM CE/PE to trade</h3>
                <OptionChainTableTradable
                  chain={data}
                  onTrade={(sym, side, price) => setOrder({ symbol: sym, side, price })}
                />
              </div>
            </div>
            <div className="col" style={{ flex: 1 }}>
              <div className="card"><h3>OI Distribution</h3><OIChart chain={data} /></div>
              <div style={{ height: 12 }} />
              <HedgeBuilder underlying={symbol} chain={data} />
            </div>
          </div>
        </>
      )}

      {order && (
        <OrderModal symbol={order.symbol} side={order.side} defaultPrice={order.price}
                    onClose={() => setOrder(null)} />
      )}
    </div>
  )
}

function OptionChainTableTradable({ chain, onTrade }: { chain: Chain; onTrade: (s: string, side: 'BUY' | 'SELL', p?: number) => void }) {
  return (
    <div>
      <OptionChainTable chain={chain} />
      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)' }}>
        Quick trade ATM:
        {(() => {
          const atm = chain.strikes.find(s => s.strike === chain.summary.atm_strike)
          if (!atm) return ' —'
          return (
            <span style={{ marginLeft: 8 }}>
              {atm.ce && <button className="primary" style={{ marginRight: 6, background: 'var(--green)', borderColor: 'var(--green)', color: '#fff' }}
                      onClick={() => onTrade(atm.ce!.symbol!, 'BUY', atm.ce!.ltp)}>BUY CE @ {atm.ce.ltp}</button>}
              {atm.pe && <button className="primary" style={{ background: 'var(--red)', borderColor: 'var(--red)', color: '#fff' }}
                      onClick={() => onTrade(atm.pe!.symbol!, 'BUY', atm.pe!.ltp)}>BUY PE @ {atm.pe.ltp}</button>}
            </span>
          )
        })()}
      </div>
    </div>
  )
}

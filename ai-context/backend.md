# BACKEND Technical Deep-Dive

## API Routes

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/api/health` | main.py | Health check endpoint |
| POST | `/api/analytics/hedge` | analytics.hedge_request | Generate hedge recommendations for position |
| GET | `/api/auth/login` | auth.login | Initiate OAuth login flow |
| GET | `/api/auth/callback` | auth.callback | OAuth callback handler |
| GET | `/api/auth/status` | auth.status | Check authentication status |
| POST | `/api/auth/logout` | auth.logout | Clear authentication session |
| GET | `/api/journal/{ref}` | journal.get_notes | Retrieve journal notes by reference |
| POST | `/api/journal` | journal.add_note | Add new journal note |
| DELETE | `/api/journal/{ref}/{idx}` | journal.delete_note | Delete specific journal note |
| GET | `/api/notify` | notify.get_hooks | List notification webhooks |
| POST | `/api/notify` | notify.add_hook | Add webhook URL |
| DELETE | `/api/notify` | notify.delete_hooks | Remove all webhooks |
| POST | `/api/notify/test` | notify.test_hook | Test webhook delivery |
| GET | `/api/options/chain` | options.get_chain | Fetch option chain data |
| GET | `/api/options/expiries` | options.get_expiries | List available expiry dates |
| GET | `/api/options/quotes` | options.get_quotes | Get real-time option quotes |
| GET | `/api/orders/preview` | orders.preview_order | Preview order without execution |
| POST | `/api/orders` | orders.place_order | Execute single order |
| GET | `/api/orders/positions` | orders.get_positions | Fetch current positions |
| POST | `/api/orders/batch` | orders.place_batch | Execute multiple orders |
| GET | `/api/orders/audit` | orders.get_audit_log | Order execution history |
| GET | `/api/portfolio` | portfolio.list_portfolios | List saved portfolios |
| PUT | `/api/portfolio` | portfolio.save_portfolio | Save/update portfolio |
| DELETE | `/api/portfolio/{name}` | portfolio.delete_portfolio | Remove portfolio |
| POST | `/api/portfolio/{name}/kill` | portfolio.kill_positions | Close all positions in portfolio |
| GET | `/api/portfolio/{name}/metrics` | portfolio.get_metrics | Portfolio performance metrics |
| GET | `/api/portfolio/{name}/pnl` | portfolio.get_pnl | P&L breakdown |
| GET | `/api/scalping/signal` | scalping.get_signal | Real-time scalping signals |
| GET | `/api/scalping/scan/{watchlist}` | scalping.scan_watchlist | Scan watchlist for opportunities |
| GET | `/api/strategy/templates` | strategy.list_templates | Available strategy templates |
| POST | `/api/strategy/template/apply` | strategy.apply_template | Apply template to position |
| POST | `/api/strategy/analyse` | strategy.analyse_strategy | Payoff + Greeks analysis |
| GET | `/api/strategy/saved` | strategy.get_saved | List saved strategies |
| PUT | `/api/strategy/saved` | strategy.save_strategy | Save strategy configuration |
| DELETE | `/api/strategy/saved/{name}` | strategy.delete_strategy | Remove saved strategy |
| GET | `/api/strategy/positions-by-ticker` | strategy.group_by_ticker | Group positions by underlying |
| WS | `/api/stream/ws/ticks` | stream.websocket_ticks | Real-time market data stream |
| GET | `/api/system/status` | system.get_status | System health + connectivity |
| GET | `/api/timeseries/snapshots` | timeseries.get_snapshots | OHLC snapshots |
| GET | `/api/timeseries/ticks` | timeseries.get_ticks | Tick-level price data |
| GET | `/api/timeseries/oi-change` | timeseries.get_oi_change | Open interest changes |
| GET | `/api/timeseries/instruments` | timeseries.list_instruments | Available instruments |
| POST | `/api/timeseries/track` | timeseries.track_symbol | Add symbol to tracking |
| GET | `/api/watchlist` | watchlist.list_watchlists | List saved watchlists |
| PUT | `/api/watchlist` | watchlist.save_watchlist | Save/update watchlist |
| DELETE | `/api/watchlist/{name}` | watchlist.delete_watchlist | Remove watchlist |
| GET | `/api/watchlist/{name}/compare` | watchlist.compare_watchlist | Comparative analysis |

## Data Models

| Model | Fields | Types |
|-------|--------|-------|
| **HedgeRequest** | primary_symbol, primary_action, qty, target_delta, max_cost | str, Literal["BUY","SELL"], int, float, float? |
| **Note** | ref, timestamp, content, tags | str, datetime, str, list[str] |
| **HookURL** | url, name, active | str, str, bool |
| **OrderRequest** | symbol, action, qty, order_type, price, product | str, Literal["BUY","SELL"], int, Literal["MARKET","LIMIT"], float?, Literal["INTRADAY","POSITIONAL"] |
| **BatchOrderRequest** | orders | list[OrderRequest] |
| **Leg** | symbol, instrument, strike, option_type, action, qty, price, delta, gamma, theta, vega | str, str, float?, str?, str, int, float, float?, float?, float?, float? |
| **Portfolio** | name, legs, created_at, updated_at | str, list[Leg], datetime, datetime |
| **StrategyLeg** | symbol, strike, option_type, action, qty, price | str, float, Literal["CE","PE"], Literal["BUY","SELL"], int, float |
| **StrategyRequest** | legs, underlying_price, range_pct, hedge_target_delta | list[StrategyLeg], float, float, float? |
| **ApplyTemplate** | template_name, underlying, spot, parameters | str, str, float, dict |
| **SavedStrategy** | name, legs, parameters, created_at | str, list[StrategyLeg], dict, datetime |
| **Watchlist** | name, symbols, created_at, updated_at | str, list[str], datetime, datetime |

## Core Analytics Modules

### Analytics Chain (`app/analytics/chain.py`)
- **normalize_chain()**: Transforms Fyers option chain → standardized format with Greeks
- **_years_to_expiry()**: Converts timestamp → time-to-expiry fraction
- Computes PCR (Put-Call Ratio), max pain, IV, delta/gamma/theta/vega per strike
- Returns: `{underlying, ltp, strikes: [{strike, ce:{...}, pe:{...}}], summary: {...}}`

### Greeks Engine (`app/analytics/greeks.py`) 
- **bs_price()**: Black-Scholes option pricing
- **implied_vol()**: IV solver via Brent's method  
- **greeks()**: Delta, gamma, theta, vega, rho calculation
- **Greeks** dataclass: `{price, delta, gamma, theta, vega, rho, iv}`

### Hedge Construction (`app/analytics/hedge.py`)
- **suggest_hedge()**: Recommends hedge legs to neutralize portfolio Greeks
- Target delta hedging strategy (long CE → short OTM CE or long OTM PE)
- Returns optimal hedge with quantity/action to minimize delta residual

### Margin Calculator (`app/analytics/margin.py`)
- **_fyers_span()**: Authoritative SPAN margin via Fyers API
- **_per_leg_unhedged()**: Individual leg margin estimation
- Index options: 10% SPAN + 3% exposure; Stock options: 17% SPAN + 3% exposure
- Fallback for offline scenarios when SPAN API unavailable

### Payoff Engine (`app/analytics/payoff.py`)
- **compute()**: Strategy P&L across price range
- **_leg_payoff()**: Individual leg contribution (options: max(S-K,0) logic)
- **_breakevens()**: Zero-crossing points via linear interpolation  
- Returns: `{max_profit, max_loss, breakevens, pnl_now, curve: [{price, pnl}]}`

### Comparative Analysis (`app/analytics/compare.py`)
- **compare_watchlist()**: Multi-symbol option chain analysis
- Tracks bias score changes, flags reversals
- Returns ranked suggestions for long/short candidates

## External Dependencies
- **Fyers API**: Market data, order execution, SPAN margins
- **Redis**: Session storage, caching, real-time data
- **WebSocket**: Live market data streaming 
- **OAuth**: Authentication flow via Fyers
- **Notifications**: Webhook delivery for alerts

## Configuration
- Risk-free rate: 7% (India 10Y proxy)
- Default margin rates: 10% index SPAN, 17% stock SPAN, 3% exposure
- Greeks calculation: Black-Scholes with volatility smile handling
- Payoff range: ±10% around spot price (configurable)
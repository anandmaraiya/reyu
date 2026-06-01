# Reyu — Fyers Options Trading Platform

Single-view options analytics & risk-adjusted portfolio platform on top of the
Fyers API v3. FastAPI backend, React + Vite frontend, Redis cache, all wired
together with Docker Compose.

## What's in the box

**Single-view dashboard** (`/dashboard`)
- Full option chain with CE/PE OI, **OI change**, IV, Δ, θ for every strike
- **PCR (OI + Volume)**, **Max-Pain**, ATM IV, aggregate OI-change strip
- Directional bias engine (PCR + OI-change heuristic → BULLISH/BEARISH/NEUTRAL)
- OI distribution chart
- **Hedge Builder**: pick a primary leg + action → backend suggests a hedge
  leg that flattens portfolio delta toward target, respecting `max_cost`,
  reports net Δ/Γ/θ/Vega and debit

**Multi-watchlist comparative analysis** (`/watchlists`)
- Save named watchlists in Redis
- One-click scan returns per-symbol PCR / max-pain / OI-Δ / bias
- Ranks **long_candidates** and **short_candidates** automatically

**Multi-portfolio book** (`/portfolios`)
- Style tags: `SCALP`, `SWING`, `HEDGED`
- Aggregates Greeks across legs; flags **risk violations** vs configured caps
  (`PORTFOLIO_MAX_DELTA`, `PORTFOLIO_MAX_VEGA`, 5× notional)
- Live P&L pulled from Fyers quotes (10s refresh)

**Scalping scanner** (`/scalping`)
- Combines option-chain bias with 5-min momentum vs SMA
- Surfaces LONG/SHORT setups + ATM leg suggestion + stop/target %

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11, FastAPI, fyers-apiv3, scipy (Black-Scholes), Redis async, SQLAlchemy async, APScheduler |
| Frontend | React 18 + Vite + TypeScript, TanStack Query, Recharts |
| Storage | TimescaleDB (Postgres) — hypertables for ticks + option snapshots |
| Infra | Docker Compose (backend / frontend / postgres / redis) |

## Time-series engine

A 1-minute APScheduler job (`app/scheduler.py`) polls every instrument with
`tracked=1` and writes:

- **`tick_1m`** — 1-min OHLCV (Timescale hypertable on `ts`)
- **`option_snapshot`** — per-underlying PCR-OI, PCR-Vol, Max-Pain, ATM-IV,
  total CE/PE OI, OI-change deltas, bias score (Timescale hypertable on `ts`)

The dashboard's **PCRTimeSeries** widget consumes `/api/ts/snapshots` with
`interval=1m|5m|15m` and shows:

- PCR (OI + Volume) line chart with reference line at 1.0
- Window OI Δ bars (CE red / PE green) + spot overlay

Click **★ Track 1-min** on any symbol to enrol it for snapshotting.

## Live ticks & orders

- `ws://localhost:8000/ws/ticks` — send `{"subscribe":["NSE:RELIANCE-EQ"]}`
  to start receiving published ticks + chain summaries.
- `POST /api/orders` — Fyers order placement with `dry_run` defaulted ON.
  The dashboard exposes one-click ATM BUY CE / BUY PE that opens a confirm
  modal; uncheck *Dry run* to send live.

## Run

```bash
cp .env.example .env       # fill in FYERS_APP_ID / FYERS_SECRET_KEY
docker compose up --build
```

- Backend → http://localhost:8000 (`/docs` for OpenAPI)
- Frontend → http://localhost:5173
- Redis → localhost:6379

First load: open **Fyers Auth** in the sidebar → Login → complete the Fyers
consent screen. The token persists in Redis for ~24h.

## Project layout

```
reyu/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile · requirements.txt
│   └── app/
│       ├── main.py · config.py · store.py
│       ├── fyers/client.py            # Fyers REST + WS wrapper
│       ├── analytics/
│       │   ├── greeks.py              # Black-Scholes + IV solver
│       │   ├── chain.py               # Normalise chain + PCR/max-pain/bias
│       │   ├── hedge.py               # Hedge leg suggester
│       │   ├── compare.py             # Multi-symbol ranking
│       │   └── scalping.py            # Quick-gain signal
│       └── routers/                   # auth · options · analytics · watchlist · portfolio · scalping
└── frontend/
    ├── Dockerfile · package.json · vite.config.ts
    └── src/
        ├── App.tsx · main.tsx · api.ts
        ├── pages/        Dashboard · Watchlists · Portfolios · Scalping · Login
        └── components/   OptionChainTable · SummaryStrip · OIChart · HedgeBuilder
```

## API surface

| Endpoint | Purpose |
|---|---|
| `GET  /api/auth/login` | Returns Fyers OAuth URL |
| `GET  /api/auth/callback` | OAuth redirect — stores access token |
| `GET  /api/options/chain?symbol=…` | Normalised chain + Greeks + bias |
| `POST /api/analytics/hedge` | Hedge-leg suggester |
| `GET/PUT/DELETE /api/watchlist` | CRUD watchlists |
| `GET  /api/watchlist/{name}/compare` | Comparative scan |
| `GET/PUT/DELETE /api/portfolio` | CRUD portfolios w/ risk check |
| `GET  /api/portfolio/{name}/pnl` | Live P&L |
| `GET  /api/scalping/signal?symbol=…` | Single-symbol signal |
| `GET  /api/scalping/scan/{watchlist}` | Watchlist-wide scan |

## Extension points

- **Live tick stream**: `app/fyers/client.py:build_socket` is ready — wire it
  into a FastAPI `WebSocket` route and push price updates to the frontend.
- **Order execution**: `fy.place_order(...)` exists; add an `/api/orders`
  router and a confirm-modal in the UI when you're ready to fire live orders.
- **Persistence**: portfolios/watchlists currently live in Redis. Swap
  `app/store.py` for SQLAlchemy + Postgres if you need durability.
- **Strategy plug-ins**: drop new modules into `app/analytics/` and wire them
  into a router; the dashboard's bias engine is a 30-line heuristic that's
  easy to replace.

## Safety

This codebase places **no orders by default**. The `place_order` helper is
provided but not wired to any UI button. Verify behaviour in Fyers' paper /
sandbox environment before adding execution endpoints.

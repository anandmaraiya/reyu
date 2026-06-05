# Reyu.ai — Options Trading Platform

A B2C + B2B options trading platform on the Fyers v3 API for Indian markets.
FastAPI backend, React + Vite frontend, TimescaleDB + Redis storage, Docker
Compose orchestration. Conversational AI agent (OpenRouter), Telegram bot
bridge, server-side chart rendering, and a backtesting engine on top.

---

## 1 · Stack & containers

| Container | Role | Port |
|---|---|---|
| `reyu-backend` | FastAPI app (uvicorn + APScheduler) | 8000 |
| `reyu-frontend` | React 18 + Vite dev server | 5173 |
| `reyu-postgres` | TimescaleDB (Postgres 16 + hypertables) | 5432 |
| `reyu-redis` | Sessions, pub/sub, chart cache, link codes | 6379 |

```bash
cp .env.example .env       # fill in FYERS_APP_ID / FYERS_SECRET_KEY
docker compose up --build
```

- Frontend → http://localhost:5173
- Backend → http://localhost:8000 (`/docs` for OpenAPI, `/redoc` for prose)

---

## 2 · Pages (frontend)

| Route | Purpose |
|---|---|
| `/dashboard` | Single-view: chain (Strike Ladder), IV smile, OI distribution, OI build-up (ATM±4), PCR time-series, key levels, AI recommendation, sticky hover detail, hedge builder |
| `/strategy` | Multi-leg builder with templates (Iron Condor, straddles, spreads, etc.), live POP gauge, risk meter, margin estimate, payoff curve, what-if scenarios |
| `/compare` | Overlay up to 4 saved strategies; best-for badges (Low Risk / High Reward / Income) |
| `/positions` | Live positions grouped by ticker, per-leg + per-group exit buttons, combined payoff per group |
| `/watchlists` | Comparative scans with heat chips and bias-flip badges; rank long/short candidates |
| `/portfolios` | Multi-portfolio book with risk caps, Sharpe/MaxDD/win-rate, kill-switch |
| `/saved` | Card grid of saved strategies with mini payoff sparklines and quick-deploy |
| `/scalping` | Signal scanner (bias × momentum) with watchlist scan |
| `/audit` | Order timeline with status badges, P&L per batch, CSV export |
| `/chat` | AI co-pilot with persistent sessions, inline chart rendering, suggested prompts |
| `/backtest` | Replay snapshot history through Follow-Bias / PCR mean-reversion strategies; equity curve + metrics |
| `/settings` | Account · Trading · Notifications · API Keys · Appearance · Shortcuts tabs |
| `/subscription` | Pricing tiers (Free / Pro / Algo), monthly/annual, current plan |
| `/login` | Email signup/login + Connect Fyers (OAuth) |

---

## 3 · Backend modules

### Analytics (`app/analytics/`)
| Module | Purpose |
|---|---|
| `chain.py` | Normalize Fyers chain, compute PCR / max-pain / OI deltas / bias |
| `greeks.py` | Black-Scholes pricing + IV solver (Brent) |
| `payoff.py` | Multi-leg payoff grid + breakeven detection + aggregated Greeks |
| `margin.py` | Fyers `/multiorder/margin` with payoff-aware fallback; classifies long-only / defined-risk / naked |
| `hedge.py` | Delta-neutral hedge suggester |
| `compare.py` | Watchlist comparative scan + bias-flip detection |
| `scalping.py` | Intraday momentum × bias scalp signals |
| `templates.py` | 8 strategy templates (spreads, straddles, condors, butterflies) |
| `pop.py` | Probability-of-profit via log-normal model |
| `portfolio_metrics.py` | Sharpe, MaxDD, win-rate from snapshot history |
| `backtest.py` | Strategy backtest core (alternate from `app/backtest/engine.py`) |

### Engine
| Module | Purpose |
|---|---|
| `app/backtest/engine.py` | Replay engine — Follow-Bias / PCR mean-reversion strategies over stored snapshots |
| `app/charts/render.py` | Matplotlib (Agg) — payoff, OI distribution, PCR time-series, IV smile PNGs |
| `app/agent/tools.py` | 6-tool registry: chain_summary, suggest_hedge, scalp_scan, compare_watchlist, positions, analyse_strategy |
| `app/agent/router.py` | Rule-based intent matcher (fallback when no LLM key) |
| `app/agent/llm.py` | OpenRouter function-calling loop (default `anthropic/claude-3.5-haiku`) |
| `app/fyers/client.py` | Fyers REST wrapper with demo-mode fallback |
| `app/fyers/symbols.py` | Symbol parser (option / equity / index / future) + lot-size resolver |
| `app/fyers/mock.py` | Synthetic chains for unauthed demo mode |
| `app/scheduler.py` | APScheduler — tier-1 every 60s, tier-2 every 5min; concurrent polling |
| `app/fno_universe.py` | 8 indices + 30 high-priority + 149 broader F&O stocks = 187 tracked symbols |
| `app/notify.py` | Outbound webhooks (Telegram / Discord / generic) |
| `app/ratelimit.py` | Per-API-key daily quota check (free 100, pro 10k, algo unlimited) |
| `app/auth_middleware.py` | JWT or X-API-Key auth on `/api/*`, public-path allowlist |

### Routers (`app/routers/`)
| Prefix | Notes |
|---|---|
| `/api/auth` | Fyers OAuth (public — for OAuth callback) |
| `/api/user` | Register, login, refresh, me, logout, API keys, tier change |
| `/api/options` | Chain, quotes, expiries (public read-only) |
| `/api/analytics` | Hedge builder |
| `/api/strategy` | Analyse, templates, save/load, positions-by-ticker |
| `/api/orders` | Preview, place, batch, exit, audit (paid tiers for live orders) |
| `/api/portfolio` | CRUD, live P&L, metrics, kill switch |
| `/api/watchlist` | CRUD + comparative scan |
| `/api/scalping` | Single-symbol signal + watchlist scan |
| `/api/ts` | Snapshots / option-series / instruments / track (public) |
| `/api/stream` | `/ws/ticks` WebSocket fanout from Redis pub/sub |
| `/api/system` | Status (Fyers, Redis, Postgres, last snapshot, tracked count) |
| `/api/journal` | Trade notes per portfolio / strategy |
| `/api/notify` | Webhook URLs management |
| `/api/admin` | Universe management + manual poll (algo-tier only) |
| `/api/chat` | Conversational agent with Redis session memory |
| `/api/chart` | Server-side PNG rendering (payoff, OI, PCR, IV smile) |
| `/api/telegram` | Webhook + link-code flow |
| `/api/billing` | Razorpay scaffolding (webhook public, others auth) |
| `/api/data` | B2B read-only API (rate-limited per key tier) |
| `/api/webhooks` | Subscription events for B2B consumers |
| `/api/backtest` | Strategy replay over stored snapshots |

### DB (`app/db.py`)
- `instruments` — F&O universe with tier (1=60s poll, 2=5min poll)
- `tick_1m` — 1-min OHLCV hypertable (Timescale)
- `option_snapshot` — per-underlying chain summary hypertable (Timescale)
- `users` — id, email, password_hash, tier (free/pro/algo), is_active, **telegram_chat_id**
- `api_keys` — id, user_id, key_hash, name, is_active, rate_limit_daily

---

## 4 · Auth model

Two authentication paths, both producing a `request.state.user` dict:

1. **Bearer JWT** (browser sessions) — `Authorization: Bearer <token>` from `/api/user/login`. Auto-refresh on 401 via axios interceptor.
2. **X-API-Key** (B2B) — `X-API-Key: reyu_<random>`. Issued via `POST /api/user/api-keys`. Rate-limited per tier on `/api/data/*` paths.

Tier gating via `require_tier("pro", "algo")` dependency. Live orders block free-tier with 403 + upgrade message; dry-runs allowed for everyone.

---

## 5 · Live data flow

```
Fyers REST → scheduler poll → option_snapshot + tick_1m → Redis pub/sub
                                                              ↓
                                                       /ws/ticks → frontend
                                                              ↓
                                                     useLiveTicks hook
                                                              ↓
                                                Dashboard chain + Positions LTPs
```

Tier-1 symbols (37: indices + top 30 stocks) poll every **60s** with concurrency 10.
Tier-2 symbols (149 broader F&O stocks) poll every **5 min** with concurrency 5.
Snapshots clamp to today's session (09:15 IST → now).

---

## 6 · AI agent

The chat endpoint accepts natural language → picks tools → returns text + optional chart.

**With `OPENROUTER_API_KEY` set** (preferred): OpenAI-compatible function calling. Default model `anthropic/claude-3.5-haiku`. Auto-iterates tool calls up to 4 rounds.

**Without an LLM key** (fallback): regex intent router matches keywords (`pcr`, `hedge`, `scalp`, `compare`, `positions`, `payoff`) to the same tool registry.

Tools:
- `chain_summary(symbol)` → spot · bias · PCR · max-pain · ATM IV + chart URL
- `suggest_hedge(underlying, primary_option_symbol, action, qty)` → hedge legs + Greeks
- `scalp_scan(symbol|watchlist)` → actionable signals
- `compare_watchlist(name)` → top-5 by bias score + long/short candidates
- `positions()` → open Fyers positions + P&L
- `analyse_strategy(underlying, legs[])` → payoff + chart

Same engine drives the **Telegram bot** via `/api/telegram/webhook` — users link via 6-digit code from Settings → Notifications.

---

## 7 · Backtesting

`POST /api/backtest/run?symbol&strategy&days` replays stored `option_snapshot` rows.

**Strategies**:
- `follow_bias` — buy ATM CE on bias ≥ 1, ATM PE on ≤ -1, exit at close
- `pcr_meanrev` — buy ATM CE when PCR > 1.3, ATM PE when < 0.7, exit at close

Black-Scholes prices ATM legs using the snapshot's stored `atm_iv`. Returns trades, equity curve, and metrics (`cum_pnl`, `win_rate`, `avg_win`, `avg_loss`, `max_drawdown`, `sharpe_annualised`).

**Known limitation**: ATM-only (no per-strike IV surface yet). Real spread backtesting needs the scheduler to also persist per-strike OI/IV.

---

## 8 · Charts

`/api/chart/{payoff|oi|pcr|iv-smile}` — matplotlib (Agg backend), dark palette matching the web UI, 1200×675 PNG at 110 dpi.

PNGs are cached in Redis for 5 minutes (keyed by params hash) so the agent and Telegram bot can hot-link without re-rendering.

---

## 9 · Telegram bot

1. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_USERNAME` in `.env`
2. Register the webhook: `curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<public-url>/api/telegram/webhook"`
3. Web user goes to Settings → Notifications → "Generate link code"
4. In Telegram, user opens `@reyu_ai_bot` → `/start` → `/link <code>`
5. From then on, every message goes through the same agent and replies with text + chart photo

---

## 10 · Env vars (excerpt — see `.env.example`)

```bash
FYERS_APP_ID=...-200
FYERS_SECRET_KEY=...
FYERS_REDIRECT_URI=http://localhost:8000/api/auth/callback
JWT_SECRET=change-me
DATABASE_URL=postgresql+asyncpg://reyu:reyu@postgres:5432/reyu
REDIS_URL=redis://redis:6379
TRACKED_SYMBOLS=NSE:NIFTY50-INDEX,NSE:NIFTYBANK-INDEX

# Optional
OPENROUTER_API_KEY=
OPENROUTER_MODEL=anthropic/claude-3.5-haiku
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=reyu_ai_bot
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
```

---

## 11 · Project layout

```
reyu/
├── docker-compose.yml · .env.example
├── REYU.md (this file) · TASKS.md (current backlog)
├── backend/
│   ├── Dockerfile · requirements.txt
│   └── app/
│       ├── main.py · config.py · store.py · db.py
│       ├── auth_middleware.py · ratelimit.py · notify.py
│       ├── scheduler.py · seeds.py · fno_universe.py
│       ├── agent/        tools · router (regex) · llm (OpenRouter)
│       ├── analytics/    chain · greeks · payoff · margin · hedge · compare · scalping · templates · pop · backtest
│       ├── backtest/     engine
│       ├── charts/       render (matplotlib)
│       ├── fyers/        client · symbols · mock
│       └── routers/      (24 files — see §3)
└── frontend/
    ├── Dockerfile · package.json · vite.config.ts
    └── src/
        ├── App.tsx · main.tsx · api.ts · chartTheme.ts · toast.tsx · ErrorBoundary.tsx · CommandPalette.tsx
        ├── hooks/        useLiveTicks
        ├── pages/        Dashboard · Strategy · Positions · Watchlists · Portfolios · Saved · Scalping · Compare · Audit · Chat · Backtest · Settings · Subscription · Login
        └── components/   OptionChainTable · SummaryStrip · OIChart · OIBuildup · IVSmile · PayoffChart · StrikeDetailPanel · HedgeBuilder · OrderModal · PCRTimeSeries · OITimeSeries · StrategyVisuals · GreeksHeatmap · KeyLevelsStrip · RecommendationPanel · MarketTicker · FilterBar · LoadingStates · StatsCard · Tooltip · ConfirmDialog
```

---

## 12 · Safety

- **No live orders by default**: order modal defaults `dry_run = true`. Free tier gets 403 for live trades. Always paper-trade in Fyers sandbox before going live.
- **API keys**: hashed (SHA-256) in DB. Full key shown to user **only once** at creation.
- **JWT secret**: change `JWT_SECRET` from the default `dev-secret` before any public deployment.
- **Rate limits**: free tier API keys capped at 100 calls/day on `/api/data/*`.

---

## 13 · Where to look first if something breaks

| Symptom | First check |
|---|---|
| Frontend shows DEMO MODE | `/api/system/status` → if `fyers: false`, re-login via sidebar |
| Charts blank | `/api/chart/oi?symbol=NSE:NIFTY50-INDEX` directly — should return PNG |
| No live ticks | `docker exec reyu-redis redis-cli pubsub channels 'ticks:*'` — should list 4+ channels |
| Backtest "no data" | Need ≥1 session of snapshots; check `/api/admin/universe` (algo tier) |
| Chat says "LLM not configured" | Set `OPENROUTER_API_KEY` — falls back to regex router otherwise |
| Telegram silent | `TELEGRAM_BOT_TOKEN` set? Webhook registered? |

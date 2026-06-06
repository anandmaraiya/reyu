# Reyu.ai — Task tracker

Snapshot: end of session on **2026-06-06 (early hours)**. Working tree is
clean. Next session resumes from the "📌 Next up" list.

## Routine

At the end of every session:
1. `docker compose down` (optional — `stop` to keep state)
2. Update **REYU.md** (architecture / new features)
3. Update this **TASKS.md** (done + pending)
4. `git add . && git commit -m "<message>"` and push if on a branch

---

## ✅ Roadmap done

| # | Item |
|---|---|
| T1 | WebSocket live ticks → frontend (Dashboard + Positions overlay, MarketTicker pulse) |
| T2 | User auth (JWT) + API keys + tier gating (free / pro / algo) |
| T3 | `/api/chat` AI agent — 6 tools, Redis session memory, suggested prompts |
| T4 | Server-side chart rendering (matplotlib, dark palette) — payoff / OI / PCR / IV smile, Redis-cached |
| T5 | Telegram bot bridge — `/start` + `/link` flow, agent backed |
| T6 | LLM via OpenRouter — function-calling loop, regex fallback when no key |
| T7 | Backtesting engine (Follow-Bias, PCR mean-reversion) + `/backtest` page |
| T8 | **RL trading engine** — per-underlying linear bandit, paper trades, scheduled decide/sweep, `/api/rl/*` |

---

## 📌 Next up (priority order)

### NU-1 — Frontend RL page (`/rl`)
Now that the backend RL is live and producing paper trades, build the dashboard:
- **Top section**: universe-wide signal table — sortable by conviction, action column, LTP, # past trades, win rate per ticker. Click row → drill in.
- **Detail pane** (right side or modal): policy weights as bar chart (feature_name × w_long / w_short), recent 20 trades, equity curve, training stats (n_updates, baseline).
- **Top KPIs**: total open trades, today's cum reward, total policies, % enabled.
- **Actions**: Reset policy · Toggle enabled · Force decide-now.
- Hits: `GET /api/rl/summary`, `GET /api/rl/recommendations`, `GET /api/rl/policy/{u}`, `GET /api/rl/trades?underlying=...`, `POST /api/rl/decide-now`.

### NU-2 — Per-strike OI / IV history
Today's `option_snapshot` table stores **aggregate** per-underlying values. To enable real spread-style RL (iron condors, butterflies, ratios) and real spread backtesting, extend the scheduler to also persist per-strike OI & IV.
- New table `option_strike_snapshot` (ts, symbol, strike, ce_oi, pe_oi, ce_ltp, pe_ltp, ce_iv, pe_iv) — Timescale hypertable on ts.
- Only persist ATM ± 10 strikes to keep volume manageable (~21 rows × 60 sec × 200 symbols = 250k/day, fine).
- Update `/api/ts/option-series` to read from the new table when symbol is a strike (it already does, sort of — but currently relies on Fyers `history` per-leg, which is slow).
- Update `backtest/engine.py` to use the new table so multi-leg backtests stop relying on Black-Scholes-from-aggregate-IV.

### NU-3 — Fyers token auto-refresh
Currently the user has to re-login after ~24h. The Fyers v3 SDK has a refresh endpoint. Plumb it through so the access token rolls without user interaction (when the refresh token is also available).

### NU-4 — Razorpay subscription billing
Subscription page + tier persistence already work; the actual payment / webhook handling is stubbed.
- Wire `/api/billing/checkout` to Razorpay subscription creation.
- Verify `/api/billing/webhook` against `RAZORPAY_WEBHOOK_SECRET` and update `users.tier` on `subscription.activated` / `cancelled`.
- Add the tier change to the JWT on next refresh.

### NU-5 — RL: switch to feature-buckets + per-action linear value
The current REINFORCE-style softmax is fine at small data; once we have a few hundred trades per ticker, swap to a contextual Thompson sampler with Bayesian linear regression heads — better exploration, calibrated uncertainty. Optional, only after we have ≥1 week of trades.

### NU-6 — WhatsApp transport
Mirror Telegram via Twilio or Meta Cloud API. Same agent code path, different webhook normalisation. Cite: Indian retail traders are on WhatsApp by default.

### NU-7 — LLM cost guard / streaming
Add per-user daily token budget for `/api/chat` when using OpenRouter (especially with a more expensive model). Stream the response back via SSE so the UI doesn't appear hung on long tool-call loops.

---

## 🐛 Known issues / minor

| Item | Notes |
|---|---|
| `chain NSE:ICICIBANK-EQ failed: math domain error` | Logged on every tier-1 poll. Likely a log/exp on a zero/negative in `compute_payoff` or normalize_chain's bias for that one symbol. Wrap the math in `_safe`. |
| Saved Strategies mini-payoff sparkline | Sometimes flat-line — fallback when legs lack `option_type`. Already coded but reproduce + verify. |
| Backtest sparse data | Only 1 trade returned because we have ≤1 session of snapshot history. Will self-resolve as days accumulate; ensure scheduler ran overnight. |
| Watchlist `compare.py` linter edit | Has `prev_score` + `flipped` fields; chat agent's `compare_watchlist` tool didn't update. Surface "flipped" in chat copy. |

---

## 📦 Operational checklist (before tomorrow)

- [ ] Containers up: `docker compose up -d`
- [ ] Connect Fyers in browser (token expires ~daily): http://localhost:5173/login → "Connect Fyers"
- [ ] `/api/system/status` → `fyers: true, demo_mode: false`
- [ ] `/api/admin/universe` → tracked count ≥ 186
- [ ] First RL inference will fire 5min after backend start; verify `/api/rl/summary` shows `todays_trades > 0` later
- [ ] Optional: set `OPENROUTER_API_KEY` and `TELEGRAM_BOT_TOKEN` in `.env` for the agent + bot

---

## 📋 Backlog (no specific order)

- White-label / embed widget for B2B Algo tier (`/embed/chain?symbol=…`)
- Multi-portfolio backtest (run a saved strategy across the universe)
- Risk pre-trade check on `/api/orders` (compare new leg's Greeks against `RISK_KEY` settings in localStorage)
- Sector grouping on Watchlists (CSV with sector column)
- Sound/visual alerts on Scalping page when actionable signal appears
- Mobile-responsive sidebar collapse
- Onboarding tour (first-run product walkthrough)
- Trade journal UI on Portfolio cards
- AI "Why this trade?" narrative — append a natural-language rationale from the agent next to every order
- Tax & brokerage estimator on order modal

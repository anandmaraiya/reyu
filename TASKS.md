# Reyu.ai — Task tracker

Snapshot: end of session on **2026-06-06**. Working tree has uncommitted RL
work — commit before next session. Resume from the "📌 Next up" list.

## 🟢 This session shipped (2026-06-06)

| # | Item |
|---|---|
| 71 | Per-strike OI/IV snapshot table + scheduler hook (ATM±10 strikes) |
| 72 | Min-conviction filter on policy actions (greedy-only, exploration bypasses) |
| 73 | Asymmetric brackets (TP 25 / SL 15) + 180-day evaluation |
| 74 | ATM-band PCR/OI features (12 new dims encoding writer-equilibrium hypothesis) |
| 75 | FEATURE_DIM bump 18→30 + auto-resize on Policy.from_json, `/policies/reset-all` |
| 76 | 180d eval with conviction 0.05 + HDFCBANK retry |
| 78 | NIFTY deep-dive: sequential no-concurrent + ROI sim + LR/epoch grid `/api/rl/tune` |
| 79 | Persist live-ready config — `min_conviction` column, `/train-and-save`, `brackets` PATCH |
| 80 | F&O sweep: tuned + persisted 6 more underlyings |
| 81 | Fyers symbol-master sync — `/api/rl/sync-lot-sizes` pulls real lot sizes from public CSV |

**Top numbers (14-day OOS holdout, sequential, TP 25 / SL 15, lot from Fyers, ₹100k cap, ₹50/trade):**

| Symbol | Lot | Trades | Test WR | ROI 14d | Max DD | ROI/DD |
|---|---|---|---|---|---|---|
| NIFTY50    | 65  | 84 | 53.6 % | **+29.0 %** | 3.7 %  | 7.84 |
| FINNIFTY   | 60  | 61 | 47.5 % | +17.7 %     | 7.9 %  | 2.24 |
| HDFCBANK   | 650 | 80 | 38.8 % | –0.3 %      | 6.0 %  | – |
| TCS        | 225 | 85 | 36.5 % | +1.2 %      | 8.3 %  | 0.14 |

ROI numbers remain **BS-pricing inflated**; expect real-fill ROI ≈ ⅓ to ½.
Real numbers come once the per-strike snapshot pipeline (filling now since
2026-06-06) has 10+ trading days of data and we swap backfill to real
premiums (NU-2 below).

**Live whitelist (enabled, paper-trading now — post bracket × conviction sweep):**
- NSE:NIFTY50-INDEX   · lot 65 · TP 25 / SL 15 / conv 0.05  (ROI/DD ≈ 2.5–3.2)
- NSE:NIFTYBANK-INDEX · lot 30 · TP **20 / SL 20** / conv **0.025** · 49 % train WR (ROI/DD ≈ 2.6, **changed from 25/15 — 2.5× better risk-adj**)

**Disabled (paper, weak/unreliable):**
- HDFCBANK, TCS, ICICIBANK, INFY, SBIN, RELIANCE — negative-or-marginal ROI at real Fyers lot sizes
- **FINNIFTY** — high run-to-run variance (3-seed test: –27 %, –3 %, +26 % at identical config). Demoted pending multi-seed eval infra.

### Sweep insights (2026-06-06 evening)

Bracket sweeps revealed **each underlying has a different optimal bracket** —
not one-size-fits-all:

| Symbol | Best bracket | Why |
|---|---|---|
| NIFTY50    | 25/15 (1.67:1) | Trends — letting winners run pays |
| NIFTYBANK  | 20/20 (1:1)    | Mean-reverting; symmetric brackets exploit chop |
| FINNIFTY   | ???            | Bracket sweep liked 30/20 but didn't reproduce — too noisy to commit |

Bracket-1-fits-all assumption is *false*; future symbols need per-symbol sweep.

---

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

### NU-2 — Real-premium backfill from OptionStrikeSnapshot ⭐ blocking go-live
The per-strike table is now writing (Task 71 done) — 54k+ rows on Saturday's
mock session alone. **The backfill BS-pricing inflation goes away once we
swap the simulator** in `_seq_simulate_session` to use stored premiums
when the snapshot table has data for that day/strike.

- New `_real_premium_simulate_session()` in `backfill.py`: for each candle
  bar, look up the matching OptionStrikeSnapshot row(s) by `(underlying, ts ± 1min, atm_strike, expiry)`
  and use real CE/PE LTP as entry/exit premium.
- Fall back to BS pricing when no snapshot exists for that bar (pre-Jun-6
  days), so we keep the long training window.
- Re-run `/api/rl/tune` on NIFTY at the end of week-1 — the ROI delta
  vs current backtested numbers will quantify the BS inflation factor.
- Goal: target real-fill ROI numbers replace the inflated synthetic ones
  by ~2026-06-15 (10 trading days of accumulation).

### NU-2b — Spread backtesting upgrade (deferred)
Once the per-strike table has 30+ days, extend `backtest/engine.py` to
support real multi-leg payoffs (iron condors, butterflies, ratios)
without Black-Scholes-from-aggregate-IV approximations.

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

### NU-8 — Fyers history retry / backoff ⭐ blocks reliable tuning
`/api/rl/tune` and batch `/evaluate` calls drop ~30 % of holdout
windows when more than 3 symbols are processed back-to-back — Fyers
silently returns empty candles on overflow. Wrap `fy.history()` in
`tenacity` retry with jittered exponential backoff (e.g. 1s / 3s / 8s)
and log a counter. Also: cache the per-day candle response in Redis for
6 h so repeated tune grid cells on the same symbol stop re-fetching.

### NU-9 — Policy weight clipping + L2 regularisation
NIFTYBANK and RELIANCE returned saturated `prob=1.0` convictions on the
live decide-now sweep — softmax blows up with large unbounded weights.
- Add `weight_decay` already exposed in `train_test_underlying`; apply
  it inside `Policy.update` (currently the param is plumbed but
  unused).
- Clip `|w_long|`, `|w_short|` to e.g. 5.0 after each update.
- Re-run tune grid sweep with a `weight_decay` axis (0, 1e-4, 1e-3).

### NU-10 — RL frontend page (`/rl`)
Build the dashboard view the backend has been ready for since T8:
- KPI bar: open trades, today's cum reward, # enabled, # disabled
- Universe table — sortable by conviction, action, last-trade WR, ROI
  estimate; click row to open detail
- Detail pane: policy weights bar chart (feature_names × w_long/w_short),
  recent trades, equity curve, training stats
- Per-policy actions: Reset, Toggle, Force decide, Edit brackets +
  conviction
- New: live whitelist column + bulk toggle so the user can flip a
  symbol on/off without curl

### NU-11 — Quarterly lot-size auto-sync
NSE rolls F&O contract specs each quarter. Add an APScheduler job that
hits `sync_lot_sizes()` at 18:00 IST on the last Friday of every month
(or any low-traffic time). Alert via Telegram webhook if a tracked
symbol's lot changed by more than 10 % so we can re-tune.

### NU-12a — Multi-seed evaluation + deterministic seeding ⭐ blocks per-symbol commits
Single-run /evaluate gave dramatic variance on FINNIFTY (–27 % to +26 % at
the same config across 3 runs). Until we can average across N seeds,
single-run results aren't trustworthy for go/no-go decisions.

- Add `seed: int | None` param threading into `Policy.act` (set
  `random.seed(seed)`) and `_seq_simulate_session` so a run is reproducible
- New `POST /api/rl/evaluate-multi` runs N seeds, returns median + mean +
  p25 + p75 + std for ROI and DD
- Use median ROI/DD for the leaderboard
- Re-evaluate FINNIFTY across all bracket × conviction combos with N=5
  seeds before deciding whether to re-enable it

### NU-13 — Per-symbol bracket policy (not 1-size-fits-all)
Confirmed via Saturday's sweep: NIFTY likes 1.67:1 (25/15), NIFTYBANK
likes 1:1 (20/20). When onboarding a new symbol, the workflow must
include a 6-bracket × 4-conviction sweep, not a single-config train +
save.

- Build `POST /api/rl/onboard-symbol?underlying=...` that runs the full
  matrix (~24 evals), picks winner by ROI/DD ratio, saves, returns
  full grid + chosen config

### NU-12 — Live vs backtest ROI reconciliation
Once paper trades close at scale, build a daily report comparing
realised paper-trade ROI vs the backtested ROI for the prior 14 days.
Big gap = BS-pricing inflation we should be quantifying. Surface in
`/api/rl/summary` and on `/rl` page.

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
- [ ] **`POST /api/rl/sync-lot-sizes`** once per quarter (or after NSE specs change)
- [ ] First RL inference will fire 5min after backend start; verify `/api/rl/summary` shows `todays_trades > 0` later
- [ ] Confirm `option_strike_snapshot` row count growing (`SELECT count(*) FROM option_strike_snapshot WHERE ts >= now() - interval '1 day';` — should be ~250k/day during market hours)
- [ ] Optional: set `OPENROUTER_API_KEY` and `TELEGRAM_BOT_TOKEN` in `.env` for the agent + bot

## 🎯 Go-live milestones

- **Before next session opens trading** — ship NU-12a multi-seed eval so
  config picks are reliable, then re-onboard FINNIFTY properly
- **2026-06-15** (Mon, ~10 trading days of strike-snapshot data) — run NU-2 real-premium backfill, get honest ROI numbers
- **Next-to-next weekend** — flip live whitelist (NIFTY + NIFTYBANK, possibly FINNIFTY if multi-seed re-eval clears) from paper to small real positions, monitor daily

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

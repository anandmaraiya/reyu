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

### NU-12b — Slippage + tax-correct ROI model
The backtest underestimates friction by ~5–6 % ROI per 14 days. Wire
this into `compute_roi`:

- `bid_ask_pct` query param (default 0.3 %) — applied as round-trip cost
- `stt_pct` (0.0625 % sell side, options)
- `exchange_pct` (0.053 % both legs)
- `gst_pct` on brokerage + transaction charges (18 %)
- Output a `friction_breakdown` block so we can read where ROI went

Once shipped, re-baseline NIFTY / NIFTYBANK — those become the honest
"what you'd actually pocket" numbers we can compare to live paper-trade
performance once Monday's session closes.

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

## 📦 Operational checklist (before Monday 09:15 IST)

**One-shot**: `.\scripts\start_market_day.ps1` does steps 1-5 below
automatically + holds the wake-lock until 15:35 IST.

- [ ] Containers up: `docker compose up -d`
- [ ] Connect Fyers in browser (token expires ~daily): http://localhost:5173/login → "Connect Fyers"
- [ ] `/api/system/status` → `fyers: true, demo_mode: false`
- [ ] `/api/admin/universe` → tracked count ≥ 186
- [ ] **Run `.\scripts\keep_awake.ps1 -ReleaseAt "15:35"`** so the laptop
      can't sleep during market hours (system + display stay on, kernel
      enforced — no Group Policy / power plan changes needed)
- [ ] Monday after 15:30 IST: `GET /api/data/snapshot-health/today` —
      tier-1 coverage should be ≥ 95 %; investigate any symbol below 80 %
- [ ] **`POST /api/rl/sync-lot-sizes`** once per quarter (or after NSE specs change)
- [ ] First RL inference will fire 5min after backend start; verify `/api/rl/summary` shows `todays_trades > 0` later
- [ ] Confirm `option_strike_snapshot` row count growing (`SELECT count(*) FROM option_strike_snapshot WHERE ts >= now() - interval '1 day';` — should be ~155k/day at tier-1 × 21 strikes × 376 minutes during market hours)
- [ ] Optional: set `OPENROUTER_API_KEY` and `TELEGRAM_BOT_TOKEN` in `.env` for the agent + bot

### What happens if the laptop sleeps anyway / internet drops mid-day?

- **Chain snapshot gaps**: those minutes are **lost permanently** — Fyers
  does not expose historical option chains, so there is no backfill.
  The gap-detector endpoint (`/api/data/snapshot-health`) quantifies
  the damage so we can decide whether to use that day's data for RL.
- **Spot candle gaps (`tick_1m`)**: those *can* be backfilled via
  `fy.history()` after reconnect — the scheduler already re-pulls
  the trailing 5 candles on every poll, so a short outage self-heals.
- **RL paper trades during a gap**: the scheduler's `is_trading_hours`
  + Fyers auth checks mean no trades open on stale data. After
  reconnect the next 5-min decide cycle fires normally.

Tier-1 chain-fetch now retries 3× with exponential backoff (0.8s →
1.6s) on transient Fyers throttling, so brief network blips no longer
drop a minute. Persistent outages (> 5 s) still create a gap.

## 🎯 Go-live milestones

- **Mon 2026-06-08 09:15 IST — first real session for data collection**
  - Run `.\scripts\start_market_day.ps1` before 09:15 IST. It brings up
    Docker, verifies Fyers auth, acquires the wake-lock until 15:35 IST.
  - After 15:30, hit `/api/data/snapshot-health/today` — target coverage
    ≥ 95 % on tier-1.
- **Before next session opens trading** — ship NU-12a multi-seed eval so
  config picks are reliable, then re-onboard FINNIFTY properly
- **2026-06-15** (Mon, ~10 trading days of strike-snapshot data) — run NU-2 real-premium backfill, get honest ROI numbers
- **Next-to-next weekend** — flip live whitelist (NIFTY + NIFTYBANK, possibly FINNIFTY if multi-seed re-eval clears) from paper to small real positions, monitor daily

## 📐 ROI math audit (2026-06-06 evening)

Audited `compute_roi` + `_seq_simulate_session`. The accounting is
structurally correct (no concurrent trades, lot math, capital
sequencing, drawdown). The biases are in the **synthetic premium**, not
the arithmetic:

| Friction layer | Adjustment to backtest ROI | Notes |
|---|---|---|
| Brokerage modelled at ₹50 | × 0.97 | Real round-trip ≈ ₹65 incl STT, exchange, GST |
| Slippage = 0 | – 5–6 % abs | Real bid-ask ≈ ₹1 × 65 lot per round trip |
| BS IV = realized vol (no VRP) | × 0.75 | Real IV ~1.3× backtest IV → premium %-moves dampened |
| Burst-spread fill drag | × 0.85 | Real fills at bid not mid on event days |
| 5-min bar TP/SL attribution | × 0.95 | Picks TP first when both fire in a bar |

**Cumulative adjustment: backtest × ~0.5.** NIFTY headline +29 % / 14d →
honest real-fill expectation ≈ +12–16 % / 14d.

Variance bursts (your question): vol clustering helps wins on the
synthetic side (we paid the calm-period BS price, then a burst gives a
fat % move), but hurts real fills via spread widening (₹0.5 spread →
₹3–5 on event days, so theoretical fills you don't actually get). Net
direction is downward on real money but the *shape* (positive
expectancy on indices) holds up.

---

---

## 🏗️ Strategy Builder Roadmap (Sprint plan, 2026-06-06)

User decisions locked:
1. **Versioning** = copy-on-edit (immutable history, every save → version+1)
2. **Multi-symbol** = separate strategies per symbol (universe.length = 1 enforced)
3. **Compare** = across different strategies (any N runs)
4. **Chatbot output** = auto-save as DRAFT with transcript linked
5. **Backtest budget** = no cap. Build symbol-wise data-lake; cache → Fyers → persist
6. **Metrics** = default suite + extensible custom (predefined list first, DSL later)
7. **RL is a strategy variant** (`kind=RL_BANDIT`). Algo-tier users can fork policies. RL strategies trade through `strategy_trades` (auditable); the bandit's research-mode trades stay in `rl_trade`.
8. **Historical option data is mandatory.** Four-source data lake:
   - L1 forward intraday (our scheduler, 2026-06-06+)
   - L2 NSE F&O Bhavcopy EOD (multi-year, free)
   - L3 paid intraday provider stub (deferred slot)
   - L4 BS-synthesized fallback, tagged in `data_quality.source`

### ✅ Sprint 0 — SHIPPED (2026-06-06 evening) · S0.1–S0.5 · #86, 88–89, 102–105

All 7 sub-tasks done. What landed:

| ID | What | Verification |
|---|---|---|
| S0.1 | 4 DB tables: `strategies` (composite id+version PK), `strategy_runs`, `strategy_trades`, `option_eod` (hypertable, 90d chunks). All indices. | `\dt` shows all 4 |
| S0.2a | NSE Bhavcopy ingester `app/data/bhavcopy.py`. URL pattern + ZIP+CSV parser + UPSERT. Real archive smoke-tested 2022/2023/2024 dates → 154k rows ingested. | `POST /api/data/bhavcopy/fetch?date=2024-06-05` → 44,483 rows |
| S0.2b | Source-priority resolver `app/fyers/cache.py::get_strike_data`. L1 → L2 → L3 (stub) → L4. Returns `source` tag on every read. | Module loads, helpers exported |
| S0.2c | Spot candle cache `app/fyers/cache.py::get_candles`. Cache-miss → Fyers history → UPSERT tick_1m → re-read. RL backfill will now read from DB. | Endpoint passes through cleanly |
| S0.3 | `app/strategy/spec.py::StrategySpec` — Pydantic with feature whitelist from FEATURE_NAMES, op validation, len(universe)=1 enforced, `RL_BANDIT` kind requires bandit config + ≥ pro tier. | Loads on import |
| S0.4 | CRUD `app/routers/strategies.py`: POST / GET list / GET / PATCH (copy-on-edit) / archive / versions. Tier caps wired (free=3, pro=20, algo=∞). | Auth-gated; loads cleanly |
| S0.5 | `app/strategy/rl_bridge.py::load_policy_for_strategy` + `bandit_decide`. RL strategies trade through `strategy_trades` with `policy_version` for audit. | Loads on import |

**Coverage now sitting in DB** (sample):
- 2022-06-03: 62,867 option EOD rows (208 underlyings)
- 2023-06-05: 47,022 rows
- 2024-06-05: 44,483 rows
- → run multi-day backfill via `POST /api/data/bhavcopy/backfill?start=...&end=...` to fill remaining range. 5-year backfill ≈ 1,250 days × ~1.5s per day = ~30 min.

**Two ops to run before Sprint 1:**
1. `POST /api/data/bhavcopy/backfill?start=2019-01-01&end=2024-12-31` (background) — 5y EOD multi-underlying history banked
2. Update `app/scheduler.py` to call `bhavcopy.daily_pull_today()` at 18:00 IST every weekday (single one-liner, defer to S1 prep)

### ✅ Sprint 1 — SHIPPED (2026-06-07 morning) · S1.1–S1.5 · #90–94

End-to-end strategy backtest pipeline live. Same simulator powers both
RL bandit and user strategies; same friction model applies to both.

| ID | What | Verification |
|---|---|---|
| S1.1 | `app/sim/engine.py` — shared `simulate_session` + `compute_roi`. `Decision` / `SimTrade` dataclasses. Pluggable `decide`, `pricer`, `feature_extractor`, `on_close`. Seed param threaded (closes NU-12a). | RL backtest still works post-refactor (smoke test) |
| S1.2 | `app/strategy/conditions.py` — ops `> < >= <= == between crosses_above crosses_below`, IST schedule with day + time-window check. `entry_allowed` facade returns (bool, reason) for run logs. | Imports cleanly |
| S1.3 | `app/strategy/runner.py` — `start_backtest_run` + `execute_run`. Loops trading days via cache layer, drives `simulate_session` per day, persists trades + metrics + equity_curve + data_quality. Handles both CONDITIONAL and RL_BANDIT kinds via `_build_decider`. | Test backtest: 62 trades persisted, full equity curve |
| S1.4 | Endpoints `POST /runs`, `GET /runs/{id}`, `GET /{strategy_id}/runs`, `GET /runs/{id}/trades`. Background task fires `execute_run`. Status transitions DRAFT → BACKTESTED on first completed run. | All endpoints respond |
| S1.5 | Default metric suite: total_trades, win_rate, roi_pct, max_dd, sharpe, profit_factor, avg_winner/loser, expectancy, longest streaks, fees. Slippage + STT + exchange + GST friction model (closes NU-12b — ROI numbers now realistic by default). | Test run shows all metrics |

Sample trade from test backtest demonstrates full provenance:
```json
{
  "id": "797c1019-…",
  "entry_ts": "2026-06-05T06:17:50",
  "exit_ts":  "2026-06-05T06:18:27",
  "entry_signal": {"reason": "conditions-met", "entry_unix": …},
  "exit_reason": "TP",
  "legs": [{"action": "BUY", "qty": 65, "entry_price": 48.67,
            "exit_price": 64.10, "fees_inr": 130.99}],
  "gross_pnl_inr": 1002.47,  "pnl_pct": 31.686,
  "mae_pct": -6.956,  "mfe_pct": 31.686
}
```

**Sprint 1 incidental fixes:**
- `bhavcopy.fetch_one` now wraps the CSV parse in `asyncio.to_thread` —
  the parse was blocking the event loop on 30-40k row files, choking
  HTTP traffic during backfill. Backfill now coexists with live API.
- `rl/backfill.py::compute_roi` now delegates to `sim/engine.compute_roi`
  with `realistic_friction=False` default to preserve existing RL numbers.
  Pass `realistic_friction=True` to get honest slippage + tax math.

**Closed by Sprint 1 (carry-over from earlier):**
- NU-12a — seed parameter threaded universally through the engine
- NU-12b — slippage / tax-correct ROI model is now the default in
  `engine.compute_roi`

**Backfill running again (resumed after CSV-parse fix):**
`POST /api/data/bhavcopy/backfill?start=2019-01-01&end=2024-12-31` in background.

### Sprint 0 — original task plan (kept for context, now ✅)


Schema + four-source data-lake + spec validation + CRUD API + RL bridge.
**Blocking everything else.** Data-lake is the architectural pivot —
every read from here on flows through it.

- **S0.1** Schema for `strategies` (id+version composite, `kind` field for
  CONDITIONAL vs RL_BANDIT), `strategy_runs` (config_snapshot JSON,
  metrics JSON, custom_metrics JSON, equity_curve JSON, data_quality
  JSON), `strategy_trades` (legs JSON, entry_signal JSON, MAE/MFE)
- **S0.2a** ⭐ NSE F&O Bhavcopy ingester — daily cron + initial 5-year
  backfill into new `option_eod` table. Unlocks multi-year EOD swing
  backtests immediately.
- **S0.2b** ⭐ Source-priority resolver `app/fyers/cache.py`: L1 → L2 → L3
  → L4. Every returned bar carries `source` tag; backtest runner reports
  source mix per run.
- **S0.2c** Spot candle backfill via Fyers `history` UPSERTed into
  `tick_1m`. RL training reads from DB only after this — eliminates
  Fyers rate-limit choke on tune sweeps (also closes most of NU-8).
- **S0.3** Pydantic `StrategySpec` — feature whitelist from FEATURE_NAMES,
  validated ops, enforce `len(universe) == 1`, kind validation
- **S0.4** CRUD: POST/GET/PATCH (creates version+1)/archive, tier caps
- **S0.5** RL strategy kind + auditable bridge — `kind=RL_BANDIT` references
  existing `rl_policy`. All RL strategy trades land in `strategy_trades`
  with `policy_version` + `entry_signal` for audit.

### Sprint 1 — Backtest core (4–5 days) · S1.1–S1.5 · #90–94

**This sprint unifies the simulator across RL + user strategies — biggest
architectural win.** Same code-path computes both bandit holdouts and
user backtests after this.

- **S1.1** Refactor `_seq_simulate_session` + `compute_roi` →
  `app/sim/engine.py` taking `decide(features) → Action` callable.
  Seed param threaded through (closes NU-12a / #83). RL bandit becomes
  one concrete `decide`; strategy condition evaluator becomes another.
- **S1.2** `app/strategy/conditions.py` — ops: >, <, >=, <=, ==, between,
  crosses_above, crosses_below + schedule check
- **S1.3** `app/strategy/runner.py` orchestrates: spec → simulator →
  trades → run row
- **S1.4** POST `/api/strategies/{id}/runs` (async background, returns
  run_id immediately) + status polling endpoints
- **S1.5** Default metrics + slippage/tax-correct friction (closes NU-12b)

### Sprint 2 — Frontend list + detail (4 days) · S2.1–S2.4 · #95

- `/strategies` list — cards with name, status, mode, latest run KPIs
- `/strategies/:id` — Recipe / Performance / Runs / Trades tabs
- Visual leg builder, equity curve, trade ledger with CSV export

### Sprint 3 — Chatbot agent (3 days) · S3 · #96

- Strategy-builder system prompt elicits universe → legs → entry → exit → risk
- Tools: `create_strategy`, `list_my_strategies`, `backtest_strategy`
- Chat transcript linked to created DRAFT for traceability

### Sprint 4 — Paper-live + risk gates (4 days) · S4.1–S4.3 · #97–99

- **S4.1** Scheduler subscribes PAPER_LIVE strategies, fires every 1 min,
  trades into `strategy_trades` with `mode=PAPER`. Reuses RL sweep cycle
  for TP/SL detection.
- **S4.2** Single pre-trade risk gate function: max_concurrent /
  max_daily_loss_inr / max_position_inr / max_drawdown_pct
- **S4.3** Run state machine (RUNNING/HALTED/COMPLETED/ERRORED), kill
  switch, Live Monitor tab

### Sprint 5 — Compare + custom metrics (3 days) · S5 · #100

- POST `/api/strategies/compare` with `[run_id…]` across any strategies
- Aligned equity curves + side-by-side metric table on a `/strategies/compare` page
- Phase 1 custom metrics: pick from extended list (Calmar, Sortino, Ulcer,
  win/loss ratio). Phase 2 DSL deferred.

### Sprint 6 — LIVE real money (4 days, LAST) · S6 · #101

- Algo tier gate + per-strategy "I confirm real money" double opt-in
- Hard risk caps (max_daily_loss capped at 10 % of pro-rated)
- Full audit log + Telegram/email per fill
- **No-go until paper-live has clean 2-week track record**

### Critical-path dependencies

```
S0.1 ─┬─► S0.4 ─► S0.5 ─► S1.4 ─► S2.* ─► S3 ─► S4.* ─► S5 ─► S6
S0.2a┤
S0.2b┤
S0.2c┤
S0.3 ─┘
       S1.1 ─► S1.2 ─► S1.3 ─► S1.4
              S1.5 ─► (parallel with S1.3)
```

S0 has no incoming dependencies — four engineers could parallelise the
six sub-tasks. S0.2a/b/c can land independently. S0.5 depends on S0.1.
S1.1 (shared simulator) is the bottleneck once S0 lands; S1.2/1.3/1.5
all need it.

### Sprint 0 readiness checklist

- [ ] User decisions locked (✅ above, including #7 RL strategy + #8 four-source data lake)
- [ ] JSON shapes agreed (✅ in chat history)
- [ ] Migration strategy: additive only, no destructive DDL — existing RL tables untouched
- [ ] Data-lake invariant: every Fyers / NSE / paid-provider read goes through `app/fyers/cache.py` from S0.2 onward. PRs that bypass it get rejected at review.
- [ ] **`option_eod` table created and Bhavcopy backfill running** — once this is in, even Sprint 1 backtests have multi-year EOD coverage for swing strategies; only intraday strategies need to wait for L1 forward accumulation.
- [ ] Every backtest run reports `data_quality.source_mix` so reports never lie about provenance.

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

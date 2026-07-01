# reyu.ai — Product Specification

**Version:** 1.0
**Owner:** Product
**Last updated:** 2026-07-01
**Baseline:** branch `basic1`

This is the engineering-ready product spec. Every feature has an ID (F-*), every page has an ID (P-*). Reference these IDs in tickets so specs stay traceable when they evolve. When a row changes, version the row — do not renumber.

---

## 1. Current-State Audit

### 1.1 Feature inventory (mapped to consumer role)

| ID | Feature | Users | Where in code |
|---|---|---|---|
| F-01 | Anonymous option chain + market ribbon | Visitor, All | `/api/options/*`, `Dashboard.tsx` |
| F-02 | User account + JWT auth (register/login/refresh) | All logged-in | `user_auth.py`, `AuthContext.tsx` |
| F-03 | Fyers OAuth (broker link + token stored in Redis, 24h TTL) | Pro, Algo, Superadmin | `auth.py`, `client.py` |
| F-04 | Live per-minute chain snapshots for ATM±15 across 186 F&O symbols | Persisted for platform; queried by all pages | `scheduler.py::poll_high/low` |
| F-05 | Real-time WebSocket ticks | All logged-in | `stream.py`, `useLiveTicks.ts` |
| F-06 | Chat / ReyuAI (LLM strategy conversation) | Free (rate-limited), Pro, Algo | `chat.py`, `Chat.tsx` |
| F-07 | Strategy builder + saved strategies | Pro, Algo | `strategies.py`, `Strategies.tsx` |
| F-08 | Multi-leg strategy P&L + Greeks aggregation | Pro, Algo | `analytics/`, `StrategyDetail.tsx` |
| F-09 | EOD Bhavcopy backtest suite | Pro, Algo | `eod_backtest.py`, `sim/` |
| F-10 | Intraday backtest (option_contract_1m + BS fallback) | Algo | `sim/real_pricer.py` |
| F-11 | RL contextual bandit (single-leg LONG/SHORT/FLAT, 30-dim features) | Algo | `rl/policy.py`, `rl/*.py` |
| F-12 | Regime-router paper-live (LONG_CE/PE/IRON_CONDOR, 09:25→15:20 IST) | Algo (system-run) | `strategy/regime_router_live.py` |
| F-13 | Paper-live strategy runner (existing single-leg RL_BANDIT) | Pro, Algo | `strategy/paper_live.py` |
| F-14 | Pre-trade risk gate (max concurrent, max delta, max vega) | System | `strategy/risk_gate.py` |
| F-15 | Positions viewer w/ real-time unrealised P&L via Fyers quotes | Pro, Algo | `Positions.tsx`, `strategies.py` |
| F-16 | Portfolios (aggregated positions, PnL curve, metrics) | Pro, Algo | `portfolio.py`, `Portfolios.tsx` |
| F-17 | Cross-strategy comparison | Pro, Algo | `StrategyCompare.tsx` |
| F-18 | Order execution stubs (preview/execute/batch) | Algo (LIVE requires `confirm=true`) | `orders.py` |
| F-19 | Fyers EOD sync (orderBook / tradeBook / positions snapshot 15:35 IST) | System | `data/fyers_sync.py` |
| F-20 | Bhavcopy pipeline (2019→present, UDiFF-aware) | System | `data/bhavcopy.py` |
| F-21 | Scalping signals (bias × momentum on watchlist) | Pro, Algo | `scalping.py` |
| F-22 | Hedge suggestions (delta-neutral construction) | Pro, Algo | `analytics/hedge.py` |
| F-23 | Chatbot strategy builder agent | Pro, Algo | `chat.py` (LLM-driven) |
| F-24 | Webhook notifications + Telegram | Pro, Algo | `notify.py`, `telegram.py` |
| F-25 | B2B API keys w/ rate limiting | Algo | `user_auth.py::api_keys`, `ratelimit.py` |
| F-26 | Razorpay billing hooks (stub) | System | `billing.py` |
| F-27 | Admin Data Capture dashboard | Superadmin | `admin_data.py`, `DataAdmin.tsx` |
| F-28 | Timescale-compressed dataset (~8-year capacity on 50GB) | System | `db.py::init_db` |
| F-29 | Scheduler (13 jobs incl. daily/weekly options backfill) | System | `scheduler.py` |
| F-30 | Auto-backfill on Fyers OAuth callback | System | `auth.py::callback` |

### 1.2 Gaps vs. business goal

| Gap | Severity | Notes |
|---|---|---|
| Forgot/reset-password flow | HIGH | Blocks self-serve growth |
| Trader P&L dashboard | HIGH | Users see trades, not "how am I doing?" |
| HNI onboarding | HIGH | Segment named, no UX for it |
| Margin/lot-size validator | HIGH | Live trades rejected without pre-check |
| Chat single-turn only | MED | Limits ReyuAI usefulness |
| Not mobile-responsive | MED | Retail traders check on phone |
| No copy-trading / share links | MED | No discovery loop |
| No compliance surface | MED | Legal risk at HNI scale |
| No email/SMS transactional | LOW-MED | Notify layer exists, no provider wired |
| Bhavcopy stops 2024 → live June 2026 | LOW | Bridging months EOD-only |
| Fyers-only | LOW | Locks out Zerodha/Upstox populations |

### 1.3 Sunset candidates

| Candidate | Rationale |
|---|---|
| Single-leg RL_BANDIT runner (F-13) | Superseded by regime router; retire after 30-day comparison |
| `always_long`/`always_short` decider endpoints | Baseline-only; move to internal helpers |
| Generic `paper_live_cycle` scheduler | Runs every 60s, mostly no-ops if router is sole path |
| Scalping signals (F-21) | Low telemetry; reassess in 30d or remove |
| Order preview stub | Reborn as margin validator |
| `data_api.py` duplicate reads | Consolidate with `option_eod` reads |
| Duplicate `Compare` vs `strategies/compare` | Pick one, redirect the other |

---

## 2. Feature Specification

RICE = (Reach × Impact × Confidence) / Effort. Impact 1–5. Effort person-weeks.

| ID | Feature | JTBD | Reach | Impact | Conf | Effort | RICE | MoSCoW |
|---|---|---|---|---|---|---|---|---|
| F-A1 | Forgot/reset password | Recover account without support | Broad | 4 | 95% | 1 | 380 | Must |
| F-A2 | Trader P&L dashboard | See week's performance at a glance | Broad | 5 | 90% | 3 | 150 | Must |
| F-A3 | Mobile responsive shell | Check positions on phone | Broad | 4 | 90% | 5 | 72 | Must |
| F-A4 | Regime-router paper-live | Platform runs validated strategy | Broad | 5 | 85% | 0 (done) | ∞ | Must |
| F-A5 | Live-order margin validator | Order won't be broker-rejected | Med | 5 | 90% | 3 | 150 | Must |
| F-A6 | Strategy publish + share link | Discover strategies others built | Broad | 4 | 70% | 3 | 93 | Should |
| F-A7 | Multi-broker (Zerodha, Upstox) | Trade via existing broker | Med | 4 | 60% | 6 | 40 | Should |
| F-A8 | HNI tier + onboarding | Serve high-value users | Narrow | 5 | 70% | 4 | 44 | Should |
| F-A9 | Compliance / audit export | Regulator gives license | Narrow | 5 | 85% | 2 | 106 | Should |
| F-A10 | Multi-turn LLM chat w/ plan state | Multi-turn strategy design | Med | 4 | 60% | 5 | 29 | Could |
| F-A11 | Copy-trade follow | Mimic top performer live | Med | 5 | 55% | 8 | 21 | Could |
| F-A12 | Email/SMS transactional | Get TP/SL notified offline | Broad | 3 | 85% | 2 | 128 | Should |
| F-A13 | Broker-neutral order abstraction | Same code across brokers | Med | 4 | 75% | 4 | 56 | Should |
| F-A14 | Retail 1-page onboarding | Reach aha inside 5 min | Broad | 5 | 85% | 3 | 142 | Must |

Dependencies:
- F-A5 depends on F-A13
- F-A11 depends on F-A6
- F-A9 depends on F-A2

---

## 3. Page-by-Page Specification

**Confirmation-step required pages** (irreversible / financial / legal): P-07 (position exit), P-11 (broker disconnect with live run), P-14 (subscription downgrade with live), P-16 (superadmin force-close).

| ID | Page | Purpose | Roles | Allowed Actions | Blocked Actions | States | KPIs | Telemetry |
|---|---|---|---|---|---|---|---|---|
| P-01 | `/` Chat/ReyuAI | Conversational entry | Visitor, Free, Pro, Algo | Send message; click nudge; use starters | LIVE trade from chat (→ /orders) | empty; loading; error; success | Msgs/session, nudge CTR, strategy-from-chat rate | `chat_msg_sent`, `chat_nudge_click`, `strategy_created_from_chat` |
| P-02 | `/charts` Dashboard | Live chain + PCR/max-pain/bias | All | Change symbol; change expiry; change strike count; export CSV (Pro+) | CSV export (Visitor/Free) | empty; loading; error; success | Chain-views/user/day, symbol switches | `chain_viewed`, `chain_exported`, `symbol_switched` |
| P-03 | `/strategies` List | Manage saved strategies | Pro, Algo | Create; edit; duplicate; delete; promote paper-live (Algo); halt | Delete with open paper run | empty; loading; error; success | Strategies/user, active-run count | `strategy_created`, `strategy_promoted`, `strategy_halted`, `strategy_deleted` |
| P-04 | `/strategies/:id` Detail | Inspect one strategy | Pro (own), Algo (own) | View spec/runs/trades; kill run; edit (new version); publish (F-A6) | Edit others'; LIVE promote sans confirm | empty; loading; error; success | Trades/strategy, Sharpe/DD/WR | `strategy_viewed`, `run_killed`, `spec_versioned` |
| P-05 | `/strategies/compare` | Rank strategies | Pro, Algo | Select; select metric; export CSV | — | empty; loading; error; success | Comparisons/user | `strategies_compared`, `compare_exported` |
| P-06 | `/backtest` Runner | Test on historical data | Pro, Algo | Configure; run; view; save | > 3 concurrent (queue) | idle; loading; success; error; queued | Backtests/user/day, avg runtime | `backtest_started`, `backtest_completed`, `backtest_failed` |
| P-07 | `/positions` Positions | Live positions + P&L | Pro, Algo | View; exit (LIVE); adjust; export | Exit ⚠️ **irreversible — confirm modal + typed symbol** | empty; loading; error; success | Open positions, unrealised drift | `position_viewed`, `position_exited`, `position_hedged` |
| P-08 | `/portfolios` | Group positions | Pro, Algo | Create; add/remove; PnL curve; metrics | Delete with open positions | empty; loading; error; success | Portfolios/user, avg size | `portfolio_created`, `portfolio_edited`, `portfolio_deleted` |
| P-09 | `/scalping` | Intraday signals | Pro, Algo | Select watchlist; refresh; open in builder | Real-money order (→ /orders) | empty; loading; error; success | Signals-clicked, signal→strategy CVR | `signal_viewed`, `signal_to_strategy` |
| P-10 | `/orders` Audit | Every placed order | Pro (paper), Algo | View; filter; export CSV; drill | Modify/delete (immutable) | empty; loading; error; success | Orders/day, error-rate/broker, slippage | `order_viewed`, `order_exported` |
| P-11 | `/brokers` | Connect/disconnect | Pro, Algo | Connect (OAuth); disconnect; reconnect | Disconnect w/ live paper run active | empty; loading; error; success | Broker connections active, disconnect rate | `broker_connected`, `broker_disconnected` |
| P-12 | `/rl` RL Engine | Inspect policy + trades | Algo | View weights/trades; refresh recs; toggle enabled | Retrain (superadmin only) | empty; loading; error; success | Recs viewed, trades from rec | `rl_rec_viewed`, `rl_trade_opened_from_rec` |
| P-13 | `/settings` | Account + theme + Fyers + notifications | Free, Pro, Algo | Change password; theme; re-auth Fyers; API keys; webhook | Change email (needs verify) | loading; error; success | Reauth freq, API key issuance | `settings_visited`, `password_changed`, `apikey_created` |
| P-14 | `/subscribe` | View/upgrade tier | Free, Pro, Algo | Start Pro; start Algo; cancel; invoices | Downgrade w/ active LIVE | idle; loading; error; success | Upgrade CVR, downgrade, MRR | `plan_viewed`, `plan_upgraded`, `plan_cancelled` |
| P-15 | `/compare` (cross-symbol) | Compare chains | Pro, Algo | Add/remove symbol; export | — | empty; loading; error; success | Symbols compared/session | `compare_symbol_added` |
| P-16 | `/admin/data` | Superadmin ops | Superadmin | Test pipeline; run job; view fills; view rr trades; force-close | Force-close ⚠️ confirm modal | loading; error; success | Rows/day, job success rate | `admin_test_run`, `admin_job_run`, `admin_regime_forced` |
| P-17 | `/onboarding` (NEW) | First-run flow | Free, Pro, Algo (first login) | Pick trader type; connect broker; seeded backtest | Skip broker-connect step | step-1..N; error; success | Onboarding CVR, time-to-first-backtest | `onboard_started`, `onboard_step_completed`, `onboard_completed` |
| P-18 | `/journal` (NEW) | My P&L dashboard | Free, Pro, Algo | View wk/mo; drill trade; annotate; export | Delete closed trade | empty; loading; error; success | Total P&L, WR, Sharpe, journal opens | `journal_viewed`, `journal_exported` |
| P-19 | `/catalog` (NEW, later) | Public strategy catalog | All | View; filter; sort; copy to account | Copy without broker link (→ /brokers) | empty; loading; error; success | Catalog opens, copies/day | `catalog_viewed`, `strategy_copied` |

---

## 4. RBAC / Permission Matrix

Y=allow, N=deny, C=conditional.

| Action | Anon | Free | Pro | Algo | Superadmin |
|---|:---:|:---:|:---:|:---:|:---:|
| P-02 View chain (delayed) | Y | Y | Y | Y | Y |
| P-02 View chain (live) | N | N | Y | Y | Y |
| P-02 Export CSV | N | N | Y | Y | Y |
| P-01 Send chat message | Y (5/day) | Y (25/day) | Y (500/day) | Y (unlim) | Y |
| P-03 Create strategy | N | N | Y | Y | Y |
| P-03 Promote to PAPER_LIVE | N | N | C¹ | Y | Y |
| P-03 Promote to LIVE (real $) | N | N | N | C² | Y (confirm) |
| P-04 Edit strategy (own) | N | N | Y | Y | Y |
| P-04 Edit strategy (any) | N | N | N | N | Y |
| P-06 Run backtest | N | C³ (1/day) | Y (20/day) | Y (unlim) | Y |
| P-07 View positions | N | N | Y (paper) | Y | Y |
| P-07 Exit position (paper) | N | N | Y | Y | Y |
| P-07 Exit position (live) | N | N | N | C² | Y |
| P-10 Export order CSV | N | N | Y | Y | Y |
| P-11 Connect broker | N | N | Y | Y | Y |
| P-11 Disconnect broker | N | N | Y | Y | Y |
| P-12 View RL policy | N | N | N | Y | Y |
| P-12 Toggle RL enabled | N | N | N | Y | Y |
| P-12 Retrain RL | N | N | N | N | Y |
| P-13 Manage API keys | N | N | N | Y | Y |
| P-14 Change plan | N | Y | Y | Y | Y |
| P-14 Downgrade w/ live | N | N | N | N | C⁴ |
| P-16 View admin dashboard | N | N | N | N | Y |
| P-16 Run scheduler job | N | N | N | N | Y |
| P-16 Trigger pipeline test | N | N | N | N | Y |
| P-17 Onboarding | N | Y (1st login) | Y (1st login) | Y (1st login) | Y |
| P-18 View own journal | N | Y | Y | Y | Y |
| P-19 View catalog | Y | Y | Y | Y | Y |
| P-19 Copy strategy | N | N | Y | Y | Y |

**Conditionals:**
- C¹ Pro can PAPER_LIVE only if < 3 already running
- C² Algo can LIVE only if: (a) Fyers connected, (b) margin validator passed, (c) `confirm=true` + typed-symbol
- C³ Free tier backtests limited to last 90d, ≤5d hold, no LIVE
- C⁴ Downgrade w/ live is Superadmin override + 7-day grace

**Hierarchy:** Roles are additive — Algo ⊇ Pro ⊇ Free. Superadmin is separate `is_superadmin` gate (currently email allowlist; move to DB flag Phase 2).

---

## 5. KPI Framework

### 5.1 North Star

**Ranked-Strategy Live-Trades per Week (RSLT/wk)**

> Count of LIVE trades executed via a strategy whose most-recent backtest scored top-decile in benchmark set, weighted by owner tier (Retail Pro = 1.0, HNI Algo = 3.0).

```
RSLT/wk = Σ trades_i × tier_weight_i
where each trade satisfies:
  - mode = LIVE
  - strategy.last_backtest.rank_percentile ≥ 90
  - trade.executed_ts ∈ last 7 days
```

### 5.2 Input tree

```
              RSLT/wk (North Star)
                    │
  ┌──────────┬─────┼──────┬──────────┬──────────┐
  │          │     │      │          │          │
Active   Ranked  Paper→Live  Live-trade   Live-mode
Traders  Strat.  conversion  hit-rate     retention
/wk                                       (30d)
```

| Input | Definition | Type | Target |
|---|---|---|---|
| Active Traders/wk | ≥1 trade any mode | Leading | 500 by Q4 |
| Ranked Strategies | Rank ≥ 90th %ile last 30d | Leading | 40 by Q4 |
| Paper→Live CVR | % paper strategies with LIVE trade in 14d | Leading | 8% Q4 |
| Live-trade hit-rate | LIVE WR (30d rolling) | Lagging | ≥ 55% |
| Live-mode retention | LIVE users still trading after 30d | Lagging | ≥ 60% |

### 5.3 Per-feature success metrics

| Feature | Metric | Target | Window |
|---|---|---|---|
| F-12 Regime router live | Live P&L / backtest P&L ratio | ≥ 0.75 | 30d rolling |
| F-A2 P&L dashboard | % active traders visiting weekly | ≥ 70% | 7d rolling |
| F-A5 Margin validator | Broker rejects / all live orders | ≤ 2% | 30d rolling |
| F-A6 Strategy publish | Published/Algo user/month | ≥ 0.5 | 30d rolling |
| F-A14 Onboarding | Signup → first backtest p50 | ≤ 5 min | 7d rolling |
| F-06 Chat/ReyuAI | Strategy-from-chat rate | ≥ 12% of sessions | 30d rolling |
| F-27 Admin dashboard | Pipeline test failure rate | ≤ 2% | 7d rolling |
| F-04 Chain snapshot | Rows/min vs expected | ≥ 95% | daily |

### 5.4 What we will NOT optimize for

- DAU / total logins (invites farming)
- Total backtests run (free-tier gaming)
- Chat message count (LLM-cost blowup)
- Strategies created (quality > quantity)
- Fyers API call volume (capture completeness is signal)
- Paper-trade count (paper is means to live)

---

## 6. Engineering Hygiene Standards

### 6.1 Before-merge checklist

| Requirement | Enforcement |
|---|---|
| CLAUDE.md updated when project shape changes | Human review |
| Pydantic + OpenAPI schema for API changes | CI: schemathesis |
| Changelog entry in `[Unreleased]` | CI: grep |
| Migration file if DB schema touched | CI: alembic check |
| Coverage ≥ 70% line / ≥ 60% branch on touched | CI: coverage.py |
| No `TODO`/`XXX` on shipped paths | CI: ripgrep |
| No secrets in diff | CI: gitleaks |
| Lint clean: ruff + eslint | CI |
| Types clean: mypy strict + tsc | CI |
| New endpoints auth-gated or in `_PUBLIC_PATHS` w/ justification | Human review |

### 6.2 Code review

- Min 1 reviewer for features → develop
- Min 2 reviewers (one senior) for money paths: `orders.py`, `paper_live.py`, `regime_router_live.py`, `fyers/*`
- Superadmin approval for `auth_middleware.py`, `user_auth.py`, `SUPERADMIN_EMAILS`, JWT config
- PR description: what/why/RICE justification/screenshots

### 6.3 Branching + commits

- `main` trunk, deployable always
- `develop` integration
- `feat/<ticket>-<slug>`, `fix/<ticket>-<slug>`, `chore/<slug>`
- Conventional Commits
- Squash-merge, PR title = squash message

### 6.4 CI gates (block merge)

```
lint → typecheck → unit → integration → coverage → security → build
```

Coverage floor stepped: 70% now → 80% Q4 → 85% Q1.

### 6.5 Environment / config

- All secrets in `.env` (git-ignored) or GCP Secret Manager
- `.env.example` committed
- Config via `pydantic.BaseSettings` — no scattered `os.environ`
- No `localhost` fallbacks — env or fail loudly
- Feature flags via `settings.py`, never inline email checks

---

## 7. Unit Testing & QA

### 7.1 Coverage

- Line 70% → 80% Q4 → 85% Q1
- Branch 60% → 70% Q4
- Per-PR (touched files, delta ≤ -1%) + nightly global report

### 7.2 Test pyramid

- 70% unit — pure logic, no I/O
- 20% integration — real Postgres (Testcontainers), real Redis, mocked Fyers
- 10% E2E — Playwright, docker-compose stack, one happy-path per role per critical page

### 7.3 Mandatory test cases per feature

| Case class | Description |
|---|---|
| Happy path | Config + valid state → expected outcome |
| Boundary | Min/max/zero inputs, exact thresholds |
| Failure | Downstream unavailable — graceful degradation |
| Permission-denied | Wrong role hits endpoint → 403 |
| Concurrent | Race → idempotence |
| Idempotence | Rerun after failure → no dupes |
| Regression | Specific bug we fixed — must be tested |

### 7.4 Mocking strategy

| Dependency | Approach |
|---|---|
| Fyers API | `respx` + recorded fixtures — never live in CI |
| Postgres/Timescale | Testcontainers, migrations at session start |
| Redis | `fakeredis` unit; real in integration |
| LLM | Recorded fixtures per-PR; live tests nightly only |
| Time | `freezegun` for schedule-sensitive |
| Random | Seeded `random.Random(seed)` — no bare `random.` |

### 7.5 Regression rule

Every bug fix PR includes a test that fails on `main` and passes on branch. Comment references ticket.

### 7.6 Definition of Done

1. All acceptance criteria verified
2. Unit tests written, passing, meet floor
3. Integration test for primary happy path
4. Permission-denied case tested
5. Peer-reviewed by required reviewers
6. CLAUDE.md / API docs / changelog updated
7. Telemetry events fire (verified dev)
8. Deployed to staging, smoke-tested
9. Feature flag defaults off in prod
10. Rollback path documented in PR

---

## 8. Non-Functional Requirements

### 8.1 Performance budgets

| Surface | Metric | Budget |
|---|---|---|
| Public pages | TTI 4G | ≤ 2.5s p75 |
| Auth pages | TTI | ≤ 3.5s p75 |
| API read | p95 | ≤ 300ms |
| API compute-heavy | p95 | ≤ 5s |
| WS tick latency | Fyers → browser | ≤ 500ms p95 |
| Backend cold start | Uvicorn boot | ≤ 15s |

### 8.2 Security

- JWT HS256, rotated quarterly. 30-min access + 7-day refresh
- HTTPS everywhere (blocker for going public)
- bcrypt cost 12 for passwords; Fyers tokens Redis-only 24h TTL
- Audit log: every LIVE trade/order, subscription change, permission upgrade → append-only 7-year retention
- Rate limits: Free 5 rps, Pro 20, Algo 100, Superadmin unlimited
- OAuth state param on all providers (learned this session)
- No cookies for API auth — Authorization header only
- Secrets rotated quarterly (JWT_SECRET), on-demand for compromise

### 8.3 Accessibility

- WCAG 2.1 AA baseline
- Keyboard-navigable everywhere
- Contrast ≥ 4.5:1 verified via axe-core CI
- Screen-reader labels on icon-only buttons
- No color-only signaling (P&L must have +/− or arrow)

### 8.4 Scalability (12-mo horizon)

- Users 10 → 5,000
- Concurrent WS 50 → 2,500
- Fyers seats 1 → 20 (pooled)
- Postgres 2M rows/day → 20M rows/day
- Storage 5 GB/mo raw → 500 GB/mo raw, 50 GB/mo compressed
- Postgres read replica by user 500; primary write-only by 2000
- Backend 1 replica → 3+ by user 1000 (no session affinity needed)

---

## 9. Delivery Roadmap (KPI-gated)

### Phase 0 — Foundations (weeks 1-2) — GATE: `/admin/data` all tabs < 1s
- Deploy pending fixes: `api.ts` localStorage, `regime-router/trades` tz, RL cache
- HTTPS via domain + Caddy
- Forgot/reset password (F-A1)
- Onboarding scaffold (F-A14)
- CI gates per §6.4

### Phase 1 — Trust & Retention (weeks 3-6) — GATE: Live-mode 30d retention ≥ 40%
- Trader P&L dashboard `/journal` (F-A2)
- Live-order margin validator (F-A5)
- Mobile responsive shell (F-A3)
- Confirmation modals + typed-symbol gates (P-07, P-11)
- Audit-log table + write path
- Email transactional (F-A12) — SendGrid or SES

### Phase 2 — Growth Loop (weeks 7-12) — GATE: Paper→Live CVR ≥ 6%
- Strategy publish + share link (F-A6)
- Public catalog `/catalog` (P-19)
- Copy-trade MVP ("duplicate to my account")
- HNI onboarding lane (F-A8) w/ concierge
- Compliance / audit export (F-A9)
- Multi-broker: Zerodha + Upstox abstraction (F-A7 + F-A13)

### Phase 3 — Ranked Value (weeks 13-20) — GATE: RSLT/wk ≥ 200
- Multi-turn LLM chat w/ plan state (F-A10)
- Full copy-trade leader-follower (F-A11)
- Catalog ranking algorithm
- HNI concierge dashboard
- Sunset §1.3 candidates

### Phase 4 — Institutional (weeks 21-30) — GATE: 3 HNI accounts LIVE weekly
- Backend horizontal scale (3 replicas + Postgres read replica)
- Rate limit + quota metering per B2B key
- SOC-2-lite audit trail
- White-label brand kit
- Sub-account structure for HNI advisors

### Cross-phase
- Coverage floor stepped per §7.1
- Nightly Fyers pipeline probe (P0), weekly (P3+)
- Superadmin dashboard evolves: per-user P&L (P1), per-strategy Sharpe (P2), broker latency (P4)

---

## Appendix

Feature IDs F-01..F-30, F-A1..F-A14 and Page IDs P-01..P-19 are stable. Reference in tickets. When specs change, version the row.

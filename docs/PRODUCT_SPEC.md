# reyu.ai — Product Specification v2.0

**Owner:** CPO · **Status:** Active · **Supersedes:** v1.0 (P0/F-A cycle, fully shipped)
**Last major revision:** 2026-07-02 · **Baseline:** branch `basic2`

**Positioning (binding on all copy and features):** reyu.ai is an AI-powered
**strategy-automation platform** for Indian markets (options + cash equities).
Users build, backtest, forward-test, approve, and deploy **their own**
strategies — paper and live. The platform is **not** an investment adviser or
portfolio manager: it gives no investment advice, makes no profitability
claims, and **never ranks strategies by performance**. The AI assistant is
personified as **Reyu**. Every live action is gated by explicit user
confirmation + versioned legal acceptance (`app/legal.py`).

Traceability: feature IDs `F-A*` (v1 cycle, shipped) and `F-B*` (this cycle);
page IDs `P-01…P-26`. IDs are referenced in code comments — when a row
changes, version the row; **never renumber**.

---

## 1. Current-State Audit

### 1.1 Feature inventory (what exists → who uses it → where)

| ID | Feature | Consumer role(s) | State | Where in code |
|---|---|---|---|---|
| F-A1 | Forgot/reset password | All registered | ✅ Live | `user_auth.py`, `ResetPassword.tsx` |
| F-A2 | Journal / P&L dashboard | Free, Pro, Algo | ✅ Live | `journal.py`, `Journal.tsx` |
| F-A3 | Mobile responsive shell | All | ✅ Live | `layout.css`, `Sidebar.tsx` |
| F-A4 | Regime-router paper-live (canonical strategy) | All (read); platform (run) | ✅ Live | `strategy/regime_router_live.py` |
| F-A5 | Live-order margin preflight | Algo | ✅ Wired into LIVE promotion | `routers/preflight.py`, `PreflightPanel.tsx` |
| F-A6 | Strategy publish + catalog + copy | Pro/Algo publish; All browse | ✅ Live | `routers/catalog.py`, `Catalog.tsx` |
| F-A7/13 | Broker abstraction + Zerodha | Pro, Algo | 🟡 Fyers full; Zerodha chain+historical only | `brokers/`, `routers/brokers.py` |
| F-A8 | HNI onboarding lane | HNI | ✅ Live | `Onboarding.tsx`, `trader_type` |
| F-A9 | Compliance audit trail + export | Superadmin; users via `/activity` | ✅ Live | `audit.py`, `routers/audit.py`, `Activity.tsx` |
| F-A10 | Multi-turn LLM chat + plan state | All | ✅ Live | `chat.py`, `chat_plan.py`, `anthropic_llm.py` |
| F-A11 | Copy-trade follow | Pro, Algo | 🟡 Single-leg mirror, PAPER only | `routers/follows.py` |
| F-A12 | Transactional notifications | Registered | ✅ Telegram DM + email | `digest.py`, `notify_email.py` |
| F-A14 | Retail onboarding (4-step + style question) | New users | ✅ Live | `Onboarding.tsx` |
| F-A15 | Legal/compliance layer: versioned ToS, SEBI risk, exec-auth, privacy; acceptance records; prompt/response/order audit | All | ✅ Live — **doc text is DRAFT pending counsel** | `app/legal.py`, `routers/legal.py`, `LegalGate.tsx`, `LegalAcceptModal.tsx` |
| F-A16 | Equity strategy engine — `EQUITY_EOD`: daily-bar eq_* features, multi-day holds, trailing/time stops, CNC, SIP accumulation | Free+ | ✅ Backtest + paper-live; **LIVE CNC blocked** | `strategy/equity_features.py`, `equity_runner.py`, `equity_paper_live.py` |
| F-A17 | Portfolio overview: whole-book capital/MTM/correlation + global kill-switch | Pro, Algo (HNI) | ✅ Live | `routers/portfolio_overview.py`, `PortfolioOverview.tsx` |
| F-A18 | Persona template gallery (8 templates × 4 personas) | All browse; registered copy | ✅ Live | `templates_catalog.py`, `routers/templates.py`, `Templates.tsx` |
| F-A19 | Morning digest + instant trade alerts | Registered w/ active runs | ✅ Live | `digest.py`, scheduler jobs |
| F-A20 | Creator profiles + forward-test badges | All | ✅ Live | `routers/creators.py`, `Creator.tsx` |
| F-A21 | TradingView webhook-in (paper, equity only, HMAC token) | Pro, Algo | ✅ Live | `routers/tv_hooks.py` |
| F-A22 | RL bandit engine + recommendations | Algo | ✅ Live | `rl/*`, `routers/rl.py` |
| F-A23 | B2B data API + API keys + tiered rate limits | Pro, Algo | ✅ Live | `data_api.py`, `ratelimit.py` |
| F-A24 | Reyu Journey gamification ladder (Built→Backtested→Forward→Authorized→Live) | Registered | ✅ Live | `StrategyJourney.tsx` |

### 1.2 Gaps vs. business goal

| # | Gap | Why it matters |
|---|---|---|
| G1 | **No real CNC execution for equity strategies** (LIVE promote blocked for `EQUITY_EOD`) | Stock-investor TAM (largest persona) can forward-test but never deploy |
| G2 | **No SEBI retail-algo strategy-ID registration** in the deploy pipeline | Existential regulatory risk for the LIVE path; retrofit cost grows per live user |
| G3 | **Legal doc text is placeholder** (plumbing production-ready, words are not) | ToS/risk-disclosure not enforceable until counsel signs off |
| G4 | Fyers token expires daily; no proactive re-auth nudge | Every data feature silently degrades each morning (mock fallback) |
| G5 | Zerodha order path incomplete | Single-broker dependency = single point of failure |
| G6 | Copy-trade fan-out single-leg, PAPER only, shares leader's run id | "Others can run them" is half-true |
| G7 | No creator monetization (deliberately deferred) | Creator persona retention ceiling |
| G8 | **No automated tests on money-path code** (runners, preflight, legal gate, billing) | Highest-risk code, lowest verification |
| G9 | TV hook is equity-only (options need strike resolution) | Quant persona friction |
| G10 | No mobile approve-from-phone flow | Time-poor persona must open the app to act |

### 1.3 Sunset candidates

| Candidate | Rationale | Action |
|---|---|---|
| P-15 `/compare` cross-symbol | Overlaps ChartsIntelligenceBar; low usage vs maintenance | Fold into `/charts` tab; redirect; remove after 2 quiet weeks of telemetry |
| P-09 `/scalping` | Pre-repositioning artifact; "signals" phrasing flirts with advice | Reframe as watchlist momentum data or fold into charts; decide end of R3 |
| P-08 `/portfolios` legacy Redis baskets | Superseded by P-22 `/portfolio` (F-A17) for the book-view job | Keep only if basket-grouping shows distinct usage; else redirect |
| Global `notify:webhooks` fan-out | Superseded by per-user digest/alerts + `webhook_subs` | Demote to ops-alerting only; remove from user docs |
| Regex intent router fallback (`agent/router.py`) | Dead weight when Anthropic key present | Freeze; keep as degraded mode only |

---

## 2. Feature Specification — this cycle (F-B)

RICE = (Reach 1–5 × Impact 1–5 × Confidence) ÷ Effort (person-weeks).

| ID | Feature | Job-to-be-done | R | I | C | E | RICE | MoSCoW | Depends on |
|---|---|---|---|---|---|---|---|---|---|
| F-B1 | SEBI algo-ID registration in deploy pipeline | "My live automation is exchange-compliant" | 3 | 5 | 70% | 4 | 2.6 | **Must** | Counsel (G3), F-A5 |
| F-B2 | Counsel-approved legal text swap + version bump | "The terms I accepted are enforceable" | 5 | 4 | 95% | 1 | 19.0 | **Must** | External counsel |
| F-B3 | Equity LIVE execution (real CNC orders) | "Deploy my swing strategy with real money" | 4 | 5 | 75% | 5 | 3.0 | **Must** | F-B1, F-B2, F-A16 |
| F-B4 | Money-path test suite (runners, preflight, legal/tier gates, billing) | Eng: change money code without fear | 5 | 5 | 90% | 3 | 7.5 | **Must** | — |
| F-B5 | Fyers re-auth morning nudge (Telegram + in-app banner) | "My data never silently goes stale" | 5 | 3 | 90% | 1 | 13.5 | **Must** | F-A19 |
| F-B6 | Mobile approve-from-phone (Telegram inline callbacks) | "Approve my strategy's action from lunch" | 4 | 4 | 70% | 3 | 3.7 | **Should** | F-A19 (task #75) |
| F-B7 | Walk-forward + slippage-model backtests | "Trust my backtest isn't overfit" | 3 | 4 | 80% | 4 | 2.4 | **Should** | task #77 |
| F-B8 | Zerodha order path completion | "Trade via the broker I already have" | 3 | 4 | 60% | 5 | 1.4 | **Should** | F-A7/13 |
| F-B13 | Risk simulator ("worst week of ₹1L in this strategy") | Learner: feel the risk before taking it | 3 | 3 | 70% | 2 | 3.2 | **Should** | F-A16 backtest data |
| F-B14 | WCAG 2.1 AA accessibility pass | Usable by everyone; enterprise-ready | 3 | 2 | 80% | 3 | 1.6 | **Should** | — |
| F-B9 | Multi-leg + LIVE copy-trade fan-out | "Actually run someone's published strategy" | 3 | 4 | 55% | 6 | 1.1 | **Could** | F-A11, F-B1 |
| F-B10 | Options income toolkit (covered calls vs holdings) | "Sell premium against stock I own" | 2 | 4 | 60% | 5 | 1.0 | **Could** | F-A16, holdings sync |
| F-B11 | TV hook for options strategies (strike resolution) | Quant: external signal → option entry | 2 | 3 | 60% | 3 | 1.2 | **Could** | F-A21 |
| F-B12 | Creator monetization (paid strategies) | "Earn from my published work" | 2 | 4 | 40% | 8 | 0.4 | **Won't** (founder decision this cycle) | F-A20, payment rails |

Dependency call-outs: **F-B3 blocks on F-B1 AND F-B2** (no real-money equity
without registered algo IDs and enforceable exec-auth). F-B9 blocks on F-B1.
F-B6 reuses F-A19 Telegram plumbing.

---

## 3. Page-by-Page Specification

Roles: **V**isitor(anon) / **F**ree / **P**ro / **A**lgo / **S**uperadmin.
⚠️ = irreversible or financially/legally sensitive → typed-confirm modal
(`ConfirmDangerModal`) and/or legal-acceptance gate is **mandatory**.

| ID | Page | Purpose | Roles | Allowed actions (exhaustive) | Explicitly blocked | States | KPIs on page | Telemetry events |
|---|---|---|---|---|---|---|---|---|
| P-01 | `/` Reyu chat | Conversational entry; build→test arc | V,F,P,A,S | send message (V:5/d, F:25/d, P:500/d, A:∞); click nudge/starter; create strategy via tool; run backtest via tool; pin response; open plan panel | LIVE order from chat (hard tool block); advice-style responses (system-prompt constraint) | empty / loading / streaming / error / rate-limited | msgs/session; strategy-from-chat rate; nudge CTR | `chat_msg_sent`, `chat_nudge_click`, `strategy_created_from_chat` |
| P-02 | `/charts` (+`/chain`) | Chain terminal: PCR, max-pain, bias, regime read | V,F,P,A,S | switch symbol; switch expiry; view insights; ask-Reyu deep-link; build-strategy deep-link; export CSV (P+) | export (V,F); any order action | empty / loading / error / success / market-closed | chain views/user/day; symbol switches; deep-link CTR | `chain_viewed`, `chain_exported`, `symbol_switched` |
| P-03 | `/strategies` | Manage own strategy library | F,P,A,S | create; edit (new version); duplicate; archive; publish/unpublish; promote PAPER_LIVE (P+); open detail | hard delete (archive only); LIVE promote from list; publish others' | empty / loading / error / success | strategies/user; publish rate | `strategy_created`, `strategy_promoted`, `strategy_deleted`(=archive), `spec_versioned` |
| P-04 ⚠️ | `/strategies/:id` | Inspect + operate one strategy | F,P,A,S (owner) | view recipe/performance/runs/trades/live; run backtest; halt run ⚠️; promote PAPER_LIVE (P+); promote LIVE ⚠️ (A: typed name + preflight PASS + exec-auth legal gate); publish; fetch TV-hook URL | others' strategies (404); LIVE for EQUITY_EOD (until F-B3); LIVE without confirm+tier+legal | empty / loading / error / success / run-running | backtest→promote funnel; halt rate | `strategy_viewed`, `backtest_started/completed/failed`, `strategy_promoted`, `run_killed` |
| P-05 | `/strategies/compare` | Side-by-side of **user-selected own** strategies (never platform ranking) | P,A,S | select own strategies; choose metric; export CSV | comparing others' private strategies | empty / loading / error / success | comparisons/user | `strategies_compared`, `compare_exported` |
| P-06 | `/backtest` | Configure + run backtests | F,P,A,S | configure window/capital; run; view result; save | >3 concurrent (queued) | idle / queued / running / success / error | backtests/user/day; completion rate; p95 runtime | `backtest_started/completed/failed` |
| P-07 ⚠️ | `/positions` | Live positions + exits | P,A,S | view; refresh; exit leg ⚠️ (dry-run default; LIVE = typed symbol); exit group ⚠️; flatten-all ⚠️ (typed `FLATTEN-ALL`); view payoff | in-place size edit; LIVE exit without typed confirm | empty / loading / error / success | open positions; dry→live ratio; exit success rate | `position_viewed`, `position_exited`, `position_hedged` |
| P-08 | `/portfolios` (legacy) | Basket grouping (sunset candidate) | P,A,S | create; add/remove leg; PnL curve; basket kill ⚠️ | delete basket w/ open positions | empty / loading / error / success | usage/week (sunset input) | `portfolio_created/edited/deleted` |
| P-09 | `/scalping` | Intraday momentum data (reframe pending) | P,A,S | select watchlist; refresh; open in builder | any auto-execution | empty / loading / error / success | signal→strategy CVR | `signal_viewed`, `signal_to_strategy` |
| P-10 | `/orders` audit | Immutable order log | P,A,S | view; filter; export CSV; drill | modify/delete (append-only) | empty / loading / error / success | orders/day; broker error rate | `order_viewed`, `order_exported` |
| P-11 ⚠️ | `/brokers` | Broker connections | F,P,A,S | connect (OAuth); reconnect; disconnect ⚠️ (typed broker name; warns on active runs) | manual credential entry; >1 account/broker | empty / loading / error / success | connected %; morning re-auth rate | `broker_connected`, `broker_disconnected` |
| P-12 | `/rl` | RL engine inspection | A,S | view weights; view trades; refresh recommendations; toggle enable | retrain (S only); auto-execute a rec | empty / loading / error / success | rec→draft CVR | `rl_rec_viewed`, `rl_trade_opened_from_rec` |
| P-13 | `/settings` | Account, keys, webhooks, theme | F,P,A,S | change password; theme; re-auth Fyers; create/revoke API key; add/remove webhook sub | email change (unverified); viewing others' keys | loading / error / success | API key issuance; webhook adds | `settings_visited`, `password_changed`, `apikey_created` |
| P-14 ⚠️ | `/subscribe` | Tier management (INR: Pro ₹2,000/mo, Algo ₹9,900/mo) | F,P,A,S | start Pro; start Algo; switch cycle; cancel ⚠️ (typed confirm if live strategies) | downgrade with active LIVE runs (halt first) | idle / loading / error / success | upgrade CVR; MRR; churn | `plan_viewed`, `plan_upgraded`, `plan_cancelled` |
| P-15 | `/compare` cross-symbol | Compare chains (sunset candidate) | P,A,S | add/remove symbol; export | — | empty / loading / error / success | usage/week (sunset input) | `compare_symbol_added` |
| P-16 ⚠️ | `/admin/data` | Superadmin ops | S | pipeline test; run job; view fills; force regime decision ⚠️; force EOD close ⚠️; view/export audit | any access by non-superadmin (email allowlist) | loading / error / success | job success rate; rows/day | `admin_test_run`, `admin_job_run`, `admin_regime_forced` |
| P-17 | `/onboarding` | First-run: trader type + trading style + broker + preview | F,P,A (first login) | pick RETAIL/HNI; pick style (4 personas); connect Fyers; skip; finish → `/templates?persona=` | re-entry after completion | step-1..4 / error / success | completion CVR; time-to-first-backtest | `onboard_started`, `onboard_step_completed`, `onboard_completed` |
| P-18 | `/journal` | My P&L across all trades | F,P,A,S | change range; filter mode; daily/monthly views; export CSV | edit/delete closed trades (append-only) | empty / loading / error / success | journal WAU; export rate | `journal_viewed`, `journal_exported` |
| P-19 | `/catalog` | Public strategy discovery | V,F,P,A,S | browse; sort recent/most-copied; copy (auth); follow (auth); open creator profile | performance-ranked sorts; profitability claims in cards | empty / loading / error / success | catalog→copy CVR; forward-test badge CTR | pageview, `strategy_copied` |
| P-20 | `/legal` (+`/:docType`) | Read legal docs (public, pre-signup) | V,F,P,A,S | read index; read full doc | accepting from this page (gates only) | loading / error / success | pre-signup doc reads | pageview |
| P-21 | `/activity` | User's own compliance trail (prompts, responses, approvals, orders) | F,P,A,S | view own rows; paginate | others' rows; any edit | empty / loading / error / success | activity opens (trust signal) | pageview |
| P-22 ⚠️ | `/portfolio` | Whole-book overview (HNI) | F,P,A,S | view aggregates; per-strategy rows; correlation; halt-all ⚠️ (typed `HALT-ALL`) | halt-all without typed confirm | empty / loading / error / success | book size; kill-switch usage | pageview, `run_killed`(halt-all) |
| P-23 | `/templates` | Persona template gallery | V,F,P,A,S | browse by persona; read template; copy (auth → login gate) | unauthenticated copy | empty / loading / error / success | template→copy CVR; persona mix | pageview, `strategy_created`(template) |
| P-24 | `/creators/:id` | Public creator profile | V,F,P,A,S | view profile; view published strategies + forward-test facts; copy (auth) | email/private data; any P&L display | loading / error / not-found / success | profile→copy CVR | pageview, `strategy_copied` |
| P-25 | `/reset-password` | Account recovery | V | request reset; set new password | — | idle / loading / error / success | reset completion rate | `password_changed` |
| P-26 ⚠️ | Global overlays: `GateModal`, `LegalGate`, `LegalAcceptModal` | Auth / upgrade / legal gates | All | login; signup; accept platform docs (per-doc checkbox); accept exec-auth; upgrade CTA | dismissing LegalGate with platform docs pending (sign-out is only escape) | closed / open / submitting / error | gate→signup CVR; acceptance completion | `plan_viewed`, `legal_accept` |

---

## 4. RBAC / Permission Matrix

Legend: **Y** allow · **N** deny · **C(x)** conditional.
**Two-layer logic (explicit):** Layer 1 = role/tier (this grid; enforced in
`auth_middleware.py` `_PUBLIC_PATHS` + `require_user`/`require_tier`/
`require_superadmin` + `tier_gate.py`). Layer 2 = per-action gates applied
*after* role passes — **O** ownership · **L** legal acceptance
(`require_acceptance`, HTTP 451) · **K** typed-confirm · **PF** preflight
PASS · **Q** quota. Superadmin gains admin pages but **does not bypass**
K/L gates.

| Action | Visitor | Free | Pro | Algo | Superadmin |
|---|---|---|---|---|---|
| View chain (delayed) | Y | Y | Y | Y | Y |
| View chain (live) | N | Y | Y | Y | Y |
| Export chain CSV | N | N | Y | Y | Y |
| Chat with Reyu | Y·Q(5/d) | Y·Q(25/d) | Y·Q(500/d) | Y | Y |
| Read legal / templates / catalog / creator pages | Y | Y | Y | Y | Y |
| Accept legal docs | N | Y | Y | Y | Y |
| Create/edit strategy | N | Y·Q(3) | Y·Q(20) | Y | Y |
| Copy template / catalog strategy | N | Y·Q(cap) | Y | Y | Y |
| Publish / unpublish strategy | N | Y·O | Y·O | Y·O | Y·O |
| Run backtest | N | Y | Y | Y | Y |
| Promote → PAPER_LIVE | N | N | Y·O | Y·O | Y·O |
| Promote → LIVE (options) | N | N | N | Y·O·K·PF·L | Y·O·K·PF·L |
| Promote → LIVE (equity) | N | N | N | **N until F-B3** | N |
| Halt own run | N | Y·O | Y·O | Y·O | Y·O |
| Portfolio halt-all | N | Y·O·K | Y·O·K | Y·O·K | Y·K |
| Exit position (dry-run) | N | Y | Y | Y | Y |
| Exit position (LIVE) | N | N | Y·K | Y·K | Y·K |
| Flatten-all (LIVE) | N | N | Y·K(typed) | Y·K(typed) | Y·K(typed) |
| Place manual order (LIVE) | N | N | Y·PF | Y·PF | Y·PF |
| Connect broker / disconnect | N | Y / Y·K | Y / Y·K | Y / Y·K | Y |
| Follow strategy (PAPER / LIVE) | N | Y / N | Y / N | Y / Y | Y |
| View RL engine / toggle bandit | N | N | N | Y / Y | Y (+retrain) |
| Create API key | N | Y·Q | Y·Q | Y | Y |
| B2B data API calls | N | Q(100/d) | Q(10k/d) | Y | Y |
| TV webhook signal (paper) | HMAC token is the auth (role-independent) | — | — | — | — |
| Fetch own TV-hook URL | N | Y·O | Y·O | Y·O | Y·O |
| View own journal / activity | N | Y·O | Y·O | Y·O | Y·O |
| View global audit / export CSV | N | N | N | N | Y |
| Admin jobs / pipeline test / force-close ⚠️ | N | N | N | N | Y·K |
| Upgrade / cancel subscription | N | Y / — | Y / Y·K(if live) | Y / Y·K(if live) | Y |

**Rule for new endpoints:** the handler docstring must name its Layer-1
requirement and every Layer-2 gate, and this table gets a row in the same PR.

---

## 5. KPI Framework

### 5.1 North Star

**Weekly Deployed Strategists (WDS)** — distinct users with ≥1 strategy in
PAPER_LIVE or LIVE that executed ≥1 trade in the trailing 7 days.

```sql
SELECT COUNT(DISTINCT r.owner_id)
FROM strategy_runs r JOIN strategy_trades t ON t.run_id = r.id
WHERE r.mode IN ('PAPER','LIVE') AND t.entry_ts >= now() - interval '7 days';
```

This is the moment the promise is real: *their own* strategy is running
automated. It cannot be gamed with content views or profitability marketing.

### 5.2 Input metric tree

| # | Input metric | Definition | Drives WDS via | Class |
|---|---|---|---|---|
| M1 | Activation | % signups completing first backtest ≤ 24h | Funnel entry | Leading |
| M2 | Backtest→Forward CVR | % backtesters promoting to PAPER_LIVE ≤ 14d | The core conversion | Leading |
| M3 | Forward-test survival | % paper-live strategies still RUNNING at day 21 | Deployment retention | Lagging |
| M4 | Broker-connected rate | % WAU with valid same-day broker auth | Capability to deploy | Leading |
| M5 | Marketplace assist rate | % new deployments from template/catalog/creator copies | Scale beyond self-built | Leading |

### 5.3 Per-feature success metrics

| Feature | Metric | Target | Window |
|---|---|---|---|
| F-A18 Templates | gallery→copy CVR | ≥ 25% | 30d |
| F-A16 Equity engine | equity share of new strategies | ≥ 30% | 60d |
| F-A17 Portfolio | weekly visits by multi-strategy users | ≥ 60% | 30d |
| F-A19 Digest | digest→app-visit rate | ≥ 20% | 30d |
| F-A20 Creators | profile→copy CVR | ≥ 10% | 30d |
| F-A21 TV hooks | strategies receiving ≥1 external signal | ≥ 50 | 90d |
| F-A15 Legal | platform-doc acceptance completion | ≥ 98% of actives | 14d post-bump |
| F-B5 Re-auth nudge | same-day broker re-auth | ≥ 70% | 30d |
| P-14 Subscription | Free→Pro CVR (trial cohort) | ≥ 4% | trial+30d |

### 5.4 What we will NOT optimize for

- **User P&L / win rate** — not our claim; optimizing it is giving advice.
- **Trade count / turnover** — churning users into trades is broker-revenue logic, not ours.
- **LIVE conversion ahead of paper survival** — rushing users live is a trust and compliance failure.
- **Chat message volume** — Reyu succeeding = fewer, better turns to deployment.
- **Copies of unverified strategies** — copies must follow forward-test facts, never hype.

---

## 6. Engineering Hygiene Standards

| Area | Standard |
|---|---|
| Docs before merge | Route PRs → endpoint docstring updated (both RBAC layers named); new feature → CLAUDE.md + §1.1 inventory row; user-visible change → `pageDocs.ts`; schema change → model docstring + `init_db()` block comment |
| API contracts | FastAPI docstrings/OpenAPI (`/docs`) are the contract; breaking response changes need `/api/v2` or additive-only |
| Changelog | One line per PR in `CHANGELOG.md` (Keep-a-Changelog), Unreleased section |
| Review | ≥1 reviewer; **2 for money-path** (`orders`, `preflight`, promote path, `billing`, `legal`, runners) and any `TIER_PRICES`/legal-text diff |
| Branching | `main` protected; `feat/<id>-slug`, `fix/<slug>`; squash-merge; commits `<type>: <summary>` |
| CI gates (merge-blocking) | ruff · `tsc --noEmit` · pytest green · coverage floors (§7.1) · `pip-audit` + `npm audit --audit-level=high` · gitleaks secret scan · pre-push smoke (containers + `/api/health` + UI 200) |
| Config/secrets | Env via `app/config.py` Settings only; `.env` never committed (CI-checked); new keys documented in `.env.example`; broker/payment keys never logged |
| Compliance copy gate | CI grep blocks PR diffs introducing `guaranteed returns / top performing / best strategy / sure profit` in user-facing strings |

---

## 7. Unit Testing & QA Specification

### 7.1 Coverage floors (CI-enforced)

| Scope | Line | Branch |
|---|---|---|
| Money-path (`strategy/*`, `routers/{orders,preflight,strategies,billing,legal}`) | 85% | 75% |
| Other backend | 70% | 60% |
| Frontend (vitest on logic-bearing components) | 60% | 50% |

### 7.2 Test pyramid

**70% unit · 20% integration · 10% E2E.** Integration = FastAPI TestClient +
ephemeral Postgres/Redis (docker-compose). E2E = Playwright vs local stack;
smoke subset per merge, full suite nightly.

### 7.3 Mandatory cases per feature (all six classes ship together)

| Class | Requirement |
|---|---|
| Happy path | Primary flow with realistic fixtures |
| Boundary | Tier quotas; `max_concurrent`; lot-size multiples; feature warmup minimums; same-day SL+TP resolves to SL; legal version bump forces re-accept |
| Failure | Broker 5xx; Fyers auth expired (mock fallback engaged); empty candles; malformed spec JSON; Razorpay bad webhook signature |
| Permission-denied | Every Layer-1 deny AND Layer-2 gate: missing legal → 451; non-owner → 404; missing typed confirm → 400; wrong tier → 402/403 |
| Concurrency | Double-submit promote; halt racing trade-close reconcile; duplicate TV signal; parallel backtests on one strategy |
| Compliance | Advice/ranking phrase snapshot test on prompts + templates; audit row asserted for every money action |

### 7.4 Mocking / fixture strategy

- **Brokers:** never live in tests — extend `app/fyers/mock.py`; record/replay JSON fixtures for chain/history/quotes.
- **DB:** ephemeral Postgres seeded by `init_db()`; factory helpers (User/Strategy/Run/Trade); no cross-test shared state.
- **Redis:** fakeredis or ephemeral container; clock-controlled for chat limits.
- **LLM:** canned tool-call transcripts; zero live tokens in CI.
- **Time:** `freezegun` for scheduler windows and IST boundaries.

### 7.5 Regression rule

Every bug fix includes a failing-first test `test_regress_<issue>_*`. No test,
no merge — sev-1 hotfixes may follow within 24h with a linked issue.

### 7.6 Definition of Done

☐ Code + tests written, CI green ☐ Coverage floors met ☐ Reviewed (×2 money-path)
☐ Docstrings/pageDocs/spec rows updated ☐ Telemetry verified firing in dev
☐ RBAC row added if new action ☐ Safe default / flag ☐ Changelog line
☐ Deployed + smoke passed.

---

## 8. Non-Functional Requirements

### 8.1 Performance budgets

| Surface | Budget |
|---|---|
| Page TTI (P75, 4G mobile) | ≤ 3.0s cold, ≤ 1.5s warm |
| API p95 — reads (chain, catalog, journal, overview) | ≤ 400ms |
| API p95 — writes (create/promote/accept) | ≤ 800ms |
| Backtest p95 (90d options / 1y equity) | ≤ 60s / ≤ 30s |
| WS tick latency broker→client | ≤ 500ms |
| Scheduler | jobs never overlap (`max_instances=1`); morning jobs complete ≤ 5 min |

### 8.2 Security

| Requirement | Standard |
|---|---|
| Auth | Short-TTL JWT + refresh; API keys hashed at rest; bcrypt passwords |
| Transport | TLS everywhere (Caddy/LE); HSTS |
| At rest | Broker tokens encrypted; disk encryption at infra layer |
| Audit | Append-only `audit_log`, 7-yr retention; prompts/responses/approvals/orders; no app-level deletes |
| Secrets | §6 rules; quarterly `jwt_secret` rotation (rotates TV-hook tokens — announce first) |
| Abuse | Per-tier quotas; anonymous chat by IP; HMAC timing-safe webhook compare |
| Regulatory | SEBI algo-ID registration before any retail LIVE order (F-B1); kill-switch ≤ 2 clicks from anywhere |

### 8.3 Accessibility

Target **WCAG 2.1 AA** (F-B14): focus-trapped, ESC-dismissable modals; 4.5:1
contrast both themes; aria-labels on icon buttons; `prefers-reduced-motion`;
confirm-modals screen-reader announced (financial safety requirement).

### 8.4 Scalability assumptions (12-month, ~10× growth)

| Dimension | Now | 12-mo design point |
|---|---|---|
| Registered users | ~10² | 10³–10⁴ |
| Concurrent paper-live strategies | ~10¹ | 10³ → move scheduler to per-strategy queue workers |
| Snapshot ingest | ~250k rows/day | 2.5M/day (Timescale chunking in place) |
| Chat volume | 10² msgs/day | 10⁴/day (tier token budgets in place) |
| Topology | single VM | split web / scheduler-worker / managed DB |

---

## 9. Delivery Roadmap (milestone-gated)

| Phase | Weeks | Scope | Exit gate (measurable) |
|---|---|---|---|
| **R1 — Trust & Rails** | 1–3 | F-B2 legal text + version bump · F-B4 money-path tests · F-B5 re-auth nudge · §6/§7 CI gates live | Acceptance ≥98% of actives · money-path coverage ≥85% · same-day re-auth ≥70% · 2 weeks zero sev-1 in money path |
| **R2 — Compliant LIVE equities** | 3–7 | F-B1 SEBI algo-ID pipeline · F-B3 equity CNC LIVE · F-B13 risk simulator | First 25 equity LIVE deployments, 100% with registered algo IDs · equity ≥30% of new strategies · **WDS +25%** vs R1 baseline |
| **R3 — Time-poor & quant depth** | 7–11 | F-B6 mobile approve · F-B7 walk-forward · F-B11 TV options hooks · execute §1.3 sunset decisions | Digest→approve ≥15% of opens · walk-forward in ≥20% of backtests · M3 survival ≥55% |
| **R4 — Marketplace maturity** | 11–16 | F-B9 copy-trade LIVE/multi-leg · F-B8 Zerodha orders · F-B14 WCAG AA · F-B12 monetization go/no-go review | M5 marketplace-assist ≥30% of new deployments · ≥1 non-Fyers broker executing LIVE · **WDS +60%** vs R1 baseline |

**Standing constraint across all phases:** nothing ships that ranks
strategies by performance, claims profitability, or bypasses confirm+legal
gates. Reviews reject on sight; the §6 CI copy-gate enforces mechanically.

"""Agent tool registry.

Each tool wraps an existing analytics function and exposes:
  - name  : stable identifier
  - description : one-line summary (also fed to LLMs later for function-calling)
  - parameters  : OpenAI/Anthropic-style JSON schema
  - handler     : async fn(args) -> { text, chart?, data? } where:
      text  : human-readable answer
      chart : optional URL/path to a chart image for the reply
      data  : optional structured payload (UI can render this richly)

The format is intentionally close to OpenAI's function-calling spec so we
can plug an LLM in later without rewriting handlers.
"""
from __future__ import annotations

from typing import Any, Callable, Awaitable
from app.fyers import client as fy
from app.analytics.chain import normalize_chain, trade_bias
from app.analytics.compare import compare_watchlist
from app.analytics.scalping import scalp_signal
from app.analytics.hedge import suggest_hedge as _suggest_hedge
from app.analytics.payoff import compute as compute_payoff
from app.agent.strategy_tools import (
    t_create_strategy, t_list_my_strategies, t_backtest_strategy,
)
from app.store import store


Handler = Callable[[dict, dict | None], Awaitable[dict]]


def _fmt_pct(x):
    return "—" if x is None else f"{x * 100:.2f}%"


# ── tool: chain summary ────────────────────────────────────────
async def t_chain_summary(args: dict, _user: dict | None) -> dict:
    symbol = args.get("symbol", "NSE:NIFTY50-INDEX")
    raw = await fy.option_chain(symbol, 25)
    chain = normalize_chain(raw)
    s = chain["summary"]
    bias = trade_bias(s)
    signals = " · ".join(bias["signals"]) or "no strong signals"
    text = (
        f"**{symbol}** spot **{chain['ltp']:,.2f}** · bias **{bias['bias']}** (score {bias['score']}).\n"
        f"PCR (OI) {s['pcr_oi']:.2f} · Max-Pain {s['max_pain']:.0f} · ATM IV {_fmt_pct(s['atm_iv'])}.\n"
        f"CE ΔOI {s['ce_oi_change']:,} · PE ΔOI {s['pe_oi_change']:,}.\n"
        f"Signals: {signals}."
    )
    return {
        "text": text,
        "chart": f"/api/chart/oi?symbol={symbol}&strikecount=25",
        "data": {"symbol": symbol, "summary": s, "bias": bias, "ltp": chain["ltp"]},
    }


# -- tool: chart request (explicit chart intent) ------------------
async def t_chart_request(args: dict, _user: dict | None) -> dict:
    """Handle explicit chart requests like 'show me NIFTY IV smile'."""
    symbol = args.get("symbol", "NSE:NIFTY50-INDEX")
    chart_type = args.get("chart_type", "oi")

    chart_urls = {
        "oi": f"/api/chart/oi?symbol={symbol}&strikecount=25",
        "pcr": f"/api/chart/pcr?symbol={symbol}&interval=5m",
        "iv-smile": f"/api/chart/iv-smile?symbol={symbol}&strikecount=25",
        "iv_smile": f"/api/chart/iv-smile?symbol={symbol}&strikecount=25",
    }
    url = chart_urls.get(chart_type, chart_urls["oi"])
    return {
        "text": f"Here's the {chart_type} chart for {symbol}:",
        "chart": url,
        "data": {"symbol": symbol, "chart_type": chart_type},
    }


# ── tool: hedge suggestion ─────────────────────────────────────
async def t_suggest_hedge(args: dict, _user: dict | None) -> dict:
    underlying = args.get("underlying") or "NSE:NIFTY50-INDEX"
    primary_symbol = args.get("primary_option_symbol")
    if not primary_symbol:
        return {"text": "Tell me which option you're holding — give me the Fyers symbol like `NSE:NIFTY2660923500CE`."}
    action = args.get("action", "BUY").upper()
    qty = int(args.get("qty", 1))
    raw = await fy.option_chain(underlying, 25)
    chain = normalize_chain(raw)
    out = _suggest_hedge(chain, primary_symbol=primary_symbol,
                        primary_action=action, qty=qty, target_delta=0.0)  # type: ignore
    if "legs" not in out:
        return {"text": f"Couldn't build a hedge — {out.get('error', 'leg not found in current chain')}."}
    pg = out["portfolio_greeks"]
    hedge_legs = out["legs"][1:]
    lines = []
    for l in hedge_legs:
        leg_id = l.get("symbol") or f"K{l['strike']} {l.get('side', '').upper()}"
        lines.append(f"• {l['action']} {l['qty']} × {leg_id} @ ₹{l['ltp']:.2f}")
    text = (
        f"**Hedge for {action} {qty} × {primary_symbol}** (target Δ = 0):\n"
        + "\n".join(lines) +
        f"\n\nNet Δ {pg['delta']:.3f} · Vega {pg['vega']:.2f} · Net debit ₹{pg['net_debit']:.0f}."
    )
    return {"text": text, "data": out}


# ── tool: scalping scan ────────────────────────────────────────
async def t_scalp_scan(args: dict, _user: dict | None) -> dict:
    symbol = args.get("symbol")
    if symbol:
        sig = await scalp_signal(symbol)
        if not sig.get("direction"):
            return {"text": f"No actionable scalp signal for {symbol} right now (bias {sig.get('bias',{}).get('bias')}, momentum {sig.get('momentum_pct',0):.2f}%)."}
        leg = sig.get("suggested_leg") or {}
        text = (
            f"**{symbol}** scalp signal: **{sig['direction']}**\n"
            f"Spot {sig['ltp']:.2f} · momentum {sig['momentum_pct']:.2f}%\n"
            f"Suggested leg: {leg.get('symbol','—')} @ ₹{leg.get('ltp','—')}\n"
            f"Stop {sig['stop_pct']}% · Target {sig['target_pct']}%."
        )
        return {"text": text, "data": sig}

    watchlist = args.get("watchlist", "F&O Liquid")
    wls = await store.hgetall_json("watchlists")
    wl = wls.get(watchlist)
    if not wl:
        return {"text": f"Watchlist '{watchlist}' not found. Available: {', '.join(wls.keys()) or '—'}"}
    out = []
    actionable = []
    for sym in wl["symbols"]:
        try:
            sig = await scalp_signal(sym)
            out.append(sig)
            if sig.get("direction"):
                actionable.append(sig)
        except Exception:
            pass
    if not actionable:
        return {"text": f"Scanned {len(out)} symbols in **{watchlist}** — no actionable scalp setups right now."}
    lines = [f"• **{s['symbol']}** {s['direction']} · spot {s['ltp']:.2f} · mom {s['momentum_pct']:.2f}%"
             for s in actionable[:5]]
    return {"text": f"**{len(actionable)} actionable scalp setups** in {watchlist}:\n" + "\n".join(lines),
            "data": {"actionable": actionable, "all": out}}


# ── tool: compare watchlist ────────────────────────────────────
async def t_compare_watchlist(args: dict, _user: dict | None) -> dict:
    name = args.get("name") or args.get("watchlist") or "F&O Liquid"
    wls = await store.hgetall_json("watchlists")
    wl = wls.get(name)
    if not wl:
        return {"text": f"Watchlist '{name}' not found. Available: {', '.join(wls.keys()) or '—'}"}
    res = await compare_watchlist(wl["symbols"], 15)
    rows = sorted([r for r in res["rows"] if "score" in r], key=lambda r: -r["score"])
    top = rows[:5]
    lines = [f"• **{r['symbol']}** · bias {r['bias']} · PCR {r['pcr_oi']:.2f} · OI Δ {r['ce_oi_change']:,}/{r['pe_oi_change']:,}"
             for r in top]
    return {"text": f"**{name}** — top 5 by bias score:\n" + "\n".join(lines)
            + f"\n\n**Long candidates:** {', '.join(res['suggestions']['long_candidates']) or '—'}"
            + f"\n**Short candidates:** {', '.join(res['suggestions']['short_candidates']) or '—'}",
            "data": res}


# ── tool: positions ────────────────────────────────────────────
async def t_positions(_args: dict, _user: dict | None) -> dict:
    try:
        raw = await fy.positions()
    except Exception as e:
        return {"text": f"Could not fetch positions: {e}"}
    nets = raw.get("netPositions", []) if isinstance(raw, dict) else []
    open_legs = [p for p in nets if int(p.get("netQty") or 0) != 0]
    if not open_legs:
        return {"text": "You have no open positions right now."}
    total_pl = sum(float(p.get("pl") or 0) for p in open_legs)
    lines = [f"• {p['symbol']} · Net {p['netQty']} · LTP {p.get('ltp', 0)} · P&L ₹{float(p.get('pl') or 0):.0f}"
             for p in open_legs[:10]]
    return {"text": f"**{len(open_legs)} open legs · Net P&L ₹{total_pl:,.0f}**\n" + "\n".join(lines),
            "data": {"positions": open_legs, "total_pl": total_pl}}


# ── tool: analyse a strategy ───────────────────────────────────
async def t_analyse_strategy(args: dict, _user: dict | None) -> dict:
    underlying = args.get("underlying", "NSE:NIFTY50-INDEX")
    legs = args.get("legs") or []
    if not legs:
        return {"text": "Give me legs like `[{symbol, action: BUY|SELL, qty, price, strike, option_type}]`."}
    raw = await fy.option_chain(underlying, 25)
    chain = normalize_chain(raw)
    enriched = []
    for l in legs:
        enriched.append({
            "symbol": l["symbol"], "instrument": "OPTION",
            "strike": l.get("strike"), "option_type": l.get("option_type"),
            "action": l["action"], "qty": int(l["qty"]),
            "price": float(l.get("price", 0)),
        })
    payoff = compute_payoff(enriched, spot=chain["ltp"], range_pct=0.12)
    text = (
        f"**Payoff @ expiry** for {len(enriched)}-leg strategy on {underlying}:\n"
        f"Max profit ₹{payoff['max_profit']:,.0f} · Max loss ₹{payoff['max_loss']:,.0f}.\n"
        f"Breakevens: {', '.join(f'{b:.0f}' for b in payoff['breakevens']) or '—'}.\n"
        f"Net debit ₹{payoff['net_debit']:,.0f}."
    )
    return {
        "text": text,
        "chart_post": {"url": "/api/chart/payoff", "body": {"underlying": underlying, "legs": legs}},
        "data": {"payoff": payoff, "legs": enriched},
    }


# ── Registry ───────────────────────────────────────────────────
TOOLS: dict[str, dict[str, Any]] = {
    "chain_summary": {
        "description": "Get chain bias, PCR, max-pain, ATM IV, and OI delta for a symbol.",
        "parameters": {"symbol": "string (e.g. NSE:NIFTY50-INDEX)"},
        "handler": t_chain_summary,
    },
    "suggest_hedge": {
        "description": "Suggest a delta-neutral hedge for a given option position.",
        "parameters": {"underlying": "string", "primary_option_symbol": "string", "action": "BUY|SELL", "qty": "int"},
        "handler": t_suggest_hedge,
    },
    "scalp_scan": {
        "description": "Surface actionable scalping setups for a symbol or watchlist.",
        "parameters": {"symbol": "string (optional)", "watchlist": "string (optional, default 'F&O Liquid')"},
        "handler": t_scalp_scan,
    },
    "compare_watchlist": {
        "description": "Rank symbols in a watchlist by bias and surface long/short candidates.",
        "parameters": {"name": "string (watchlist name)"},
        "handler": t_compare_watchlist,
    },
    "positions": {
        "description": "List the user's open positions with live P&L.",
        "parameters": {},
        "handler": t_positions,
    },
    "analyse_strategy": {
        "description": "Compute payoff/Greeks/margin for a multi-leg options strategy.",
        "parameters": {"underlying": "string", "legs": "list of {symbol, action, qty, price, strike, option_type}"},
        "handler": t_analyse_strategy,
    },
    "chart_request": {
        "description": "Return a chart image URL for a symbol. chart_type: oi, pcr, iv-smile.",
        "parameters": {"symbol": "string", "chart_type": "string (oi|pcr|iv-smile)"},
        "handler": t_chart_request,
    },
    "create_strategy": {
        "description": "Create + save a new strategy (options OR cash equity). Accepts shorthand "
                       "(name, universe, action, option_type, tp_pct, sl_pct, feature, op, value) "
                       "or a full {spec} object. Saves as DRAFT. "
                       "For EQUITY strategies (swing/positional/SIP on stocks like NSE:RELIANCE-EQ), "
                       "set kind=EQUITY_EOD — daily-bar signals, delivery (CNC), multi-day holds, "
                       "long-only. Equity condition features (eq_*): eq_close, eq_sma20_dist_pct, "
                       "eq_sma50_dist_pct, eq_sma200_dist_pct, eq_sma20_above_sma50, "
                       "eq_close_above_sma200, eq_rsi_14, eq_high_52w_dist_pct, eq_low_52w_dist_pct, "
                       "eq_high_20d_dist_pct, eq_volume_surge, eq_gap_pct, eq_ret_1d_pct, "
                       "eq_ret_5d_pct, eq_ret_20d_pct. No conditions + kind=EQUITY_EOD = "
                       "SIP-style scheduled accumulation on `days`.",
        "parameters": {
            "name": "string", "universe": "string (e.g. NSE:NIFTY50-INDEX or NSE:RELIANCE-EQ)",
            "kind": "CONDITIONAL|EQUITY_EOD (default CONDITIONAL=options intraday)",
            "action": "BUY|SELL (options only; equity is BUY-only)", "option_type": "CE|PE",
            "tp_pct": "float 0..1", "sl_pct": "float 0..1",
            "trailing_sl_pct": "float 0..1 (EQUITY_EOD: trail from peak close)",
            "time_stop_days": "int (EQUITY_EOD: max holding days)",
            "feature": "string (optional - rl feature or eq_* feature name)",
            "op": "string (>|<|>=|<=|== between crosses_above crosses_below)",
            "value": "float (condition threshold)",
            "conditions": "list[{feature,op,value}] (multiple conditions, ANDed)",
            "days": "list[MON..FRI] (SCHEDULE trigger / SIP days)",
            "qty_lots": "int (default 1)",
            "max_position_inr": "float (per-position capital cap)",
            "max_concurrent": "int (EQUITY_EOD SIP: how many tranches may be open)",
            "tags": "list[string]", "spec": "object (full StrategySpec)",
        },
        "handler": t_create_strategy,
    },
    "list_my_strategies": {
        "description": "List the user's saved strategies — name, status, version, KPIs.",
        "parameters": {},
        "handler": t_list_my_strategies,
    },
    "backtest_strategy": {
        "description": "Kick a backtest run on an existing strategy. Identify by `strategy_id` "
                       "or partial `name`. Default window is last 90 days.",
        "parameters": {
            "strategy_id": "string (optional)",
            "name": "string (optional, partial match)",
            "days": "int (lookback window, default 90)",
            "starting_capital": "float (default 100000)",
        },
        "handler": t_backtest_strategy,
    },
    "update_chat_plan": {
        "description": (
            "Record what you've learned in this conversation so far. Update whenever "
            "the user's goal, symbol, bias, target/stop, or draft strategy becomes clearer. "
            "This state persists across turns — future turns will see it in your context. "
            "Call this frequently. Include an add_decision entry whenever you make a "
            "recommendation the user accepts."
        ),
        "parameters": {
            "goal":         "string (what user wants this session)",
            "underlying":   "string (e.g. NSE:NIFTY50-INDEX)",
            "bias":         "string (bullish|bearish|range|unclear)",
            "brackets":     "object ({target_pct, stop_pct} — floats 0..1)",
            "strategy_draft": "object (partial spec being built)",
            "next_step":    "string (what you suggest doing next)",
            "add_decision": "object ({choice, why} — appended to decision log)",
            "chat_session_id": "string (auto-injected by chat router)",
        },
        "handler": None,        # set below to avoid a forward-ref
    },
}


async def t_update_chat_plan(args: dict, _user: dict | None) -> dict:
    """Merge `args` into the persistent chat plan for the current session."""
    from app.chat_plan import update_plan
    sid = args.pop("chat_session_id", None)
    if not sid:
        return {"text": "Plan not updated — session id missing.", "data": None}

    patch: dict = {k: v for k, v in args.items()
                   if v is not None and k not in ("add_decision",)}
    if args.get("add_decision"):
        from datetime import datetime as _dt
        patch["decisions"] = [{
            "ts": _dt.utcnow().isoformat(),
            **args["add_decision"],
        }]
    updated = await update_plan(sid, patch)
    return {
        "text": f"Plan updated. Now tracking: "
                f"goal={updated.get('goal')!r}, "
                f"underlying={updated.get('underlying')!r}, "
                f"bias={updated.get('bias')!r}, "
                f"{len(updated.get('decisions') or [])} decisions logged.",
        "data": updated,
    }


TOOLS["update_chat_plan"]["handler"] = t_update_chat_plan


async def call_tool(name: str, args: dict, user: dict | None = None) -> dict:
    if name not in TOOLS:
        return {"text": f"Unknown tool `{name}`. Available: {', '.join(TOOLS)}"}
    return await TOOLS[name]["handler"](args, user)


def list_tools() -> list[dict]:
    return [{"name": k, "description": v["description"], "parameters": v["parameters"]}
            for k, v in TOOLS.items()]

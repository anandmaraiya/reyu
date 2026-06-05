"""Rule-based intent router for the chat agent.

Today this picks a tool by keyword + symbol extraction. The shape of the
return ({tool, args}) matches what an LLM would emit via function-calling,
so we can swap in OpenAI/Anthropic later without touching the tool layer
or the FastAPI endpoint.
"""
from __future__ import annotations

import re

from app.fno_universe import all_fno_symbols


# Build a quick lookup: short-name → full Fyers symbol for symbol detection
_UNIVERSE = all_fno_symbols()
_SHORT_MAP: dict[str, str] = {}
for s in _UNIVERSE:
    # NSE:RELIANCE-EQ → RELIANCE ; NSE:NIFTY50-INDEX → NIFTY
    after = s.split(":", 1)[-1]
    base = after.replace("-EQ", "").replace("-INDEX", "")
    if base == "NIFTY50":
        base = "NIFTY"
    if base == "NIFTYBANK":
        base = "BANKNIFTY"
    _SHORT_MAP[base.upper()] = s


def _detect_symbol(text: str) -> str | None:
    t = text.upper()
    # Explicit Fyers symbol present?
    m = re.search(r"\b(NSE|BSE):[A-Z0-9-]+(?:-EQ|-INDEX|\d+[CP]E|FUT)\b", t)
    if m:
        return m.group(0)
    # Short name?
    for short, full in _SHORT_MAP.items():
        if re.search(rf"\b{re.escape(short)}\b", t):
            return full
    return None


def _detect_watchlist(text: str) -> str | None:
    m = re.search(r"watchlist[s]?[:\s]+(['\"]?)(.+?)\1", text, re.IGNORECASE)
    if m:
        return m.group(2).strip()
    return None


# Intent keywords -> tool. Order matters: more specific patterns first.
_INTENTS = [
    (r"\b(positions?|open trade|my book|p&?l)\b", "positions"),
    (r"\b(hedge|delta[- ]?neutral|protect|cover)\b", "suggest_hedge"),
    (r"\b(scalp|scalping|quick|signal|setup)\b", "scalp_scan"),
    (r"\b(compare|watchlist|leaderboard|rank|scan)\b", "compare_watchlist"),
    (r"\b(payoff|p&?l curve|max profit|strategy[: ]+?analy|analyse strategy)\b", "analyse_strategy"),
    (r"\b(chart|oi chart|iv smile|volatility smile|iv chart|pcr chart|show me.*chart)\b", "chart_request"),
    (r"\b(pcr|max[- ]?pain|atm iv|bias|trend|chain|skew|put[- ]?call)\b", "chain_summary"),
]


def route(text: str) -> dict:
    """Returns {tool, args} or {error}."""
    text = (text or "").strip()
    if not text:
        return {"error": "Empty message."}

    # Find tool by intent
    tool = None
    for pat, name in _INTENTS:
        if re.search(pat, text, re.IGNORECASE):
            tool = name
            break
    if not tool:
        # Fallback: if a symbol is mentioned, treat as chain query
        if _detect_symbol(text):
            tool = "chain_summary"
        else:
            return {
                "error": "I can answer questions about PCR, bias, OI, hedges, scalping, watchlist comparisons, payoff, and positions. Try: \"What's the NIFTY bias?\" or \"Suggest a hedge for NSE:NIFTY2660923500CE BUY 75\"."
            }

    # Build args based on intent
    sym = _detect_symbol(text)
    args: dict = {}

    if tool == "chain_summary":
        args["symbol"] = sym or "NSE:NIFTY50-INDEX"

    elif tool == "suggest_hedge":
        # Underlying = parent index if a CE/PE symbol is mentioned, else NIFTY
        m = re.search(r"\b(NSE|BSE):[A-Z]+\d+[CP]E\b", text)
        if m:
            args["primary_option_symbol"] = m.group(0)
            args["underlying"] = sym if sym and "-INDEX" in sym else "NSE:NIFTY50-INDEX"
        args["action"] = "SELL" if re.search(r"\b(sell|short|written)\b", text, re.IGNORECASE) else "BUY"
        q = re.search(r"\b(\d+)\s*(?:qty|lots?|units?)?\b", text)
        if q:
            args["qty"] = int(q.group(1))

    elif tool == "scalp_scan":
        if sym and "-INDEX" not in sym:
            args["symbol"] = sym
        wl = _detect_watchlist(text)
        if wl:
            args["watchlist"] = wl

    elif tool == "compare_watchlist":
        wl = _detect_watchlist(text)
        if wl:
            args["name"] = wl

    elif tool == "analyse_strategy":
        if sym and "-INDEX" in sym:
            args["underlying"] = sym

    elif tool == "chart_request":
        args["symbol"] = sym or "NSE:NIFTY50-INDEX"
        # Detect chart type from text
        t = text.lower()
        if "iv smile" in t or "volatility smile" in t or "iv chart" in t:
            args["chart_type"] = "iv-smile"
        elif "pcr" in t:
            args["chart_type"] = "pcr"
        elif "oi" in t:
            args["chart_type"] = "oi"
        else:
            args["chart_type"] = "oi"

    elif tool == "positions":
        pass

    return {"tool": tool, "args": args}

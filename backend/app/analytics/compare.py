"""Comparative analysis across a watchlist of symbols."""
from __future__ import annotations

from typing import Any
from app.analytics.chain import normalize_chain, trade_bias
from app.fyers import client as fy
from app.store import store

PREV_KEY = "bias:last"


async def compare_watchlist(symbols: list[str], strikecount: int = 15) -> dict[str, Any]:
    prev = await store.hgetall_json(PREV_KEY)
    rows = []
    for sym in symbols:
        try:
            raw = await fy.option_chain(sym, strikecount)
            chain = normalize_chain(raw)
            bias = trade_bias(chain["summary"])
            prev_score = (prev.get(sym) or {}).get("score")
            flipped = prev_score is not None and (
                (prev_score > 0 and bias["score"] < 0) or (prev_score < 0 and bias["score"] > 0)
            )
            rows.append({
                "symbol": sym,
                "ltp": chain["ltp"],
                **chain["summary"],
                **bias,
                "prev_score": prev_score,
                "flipped": flipped,
            })
            await store.hset_json(PREV_KEY, sym, {"score": bias["score"], "bias": bias["bias"]})
        except Exception as e:
            rows.append({"symbol": sym, "error": str(e)})

    # Rank by score (most bullish first)
    valid = [r for r in rows if "score" in r]
    valid.sort(key=lambda r: r["score"], reverse=True)
    top_long = valid[:3]
    top_short = sorted(valid, key=lambda r: r["score"])[:3]

    return {
        "rows": rows,
        "suggestions": {
            "long_candidates": [r["symbol"] for r in top_long if r["score"] > 0],
            "short_candidates": [r["symbol"] for r in top_short if r["score"] < 0],
        },
    }

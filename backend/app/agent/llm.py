"""OpenRouter-powered chat agent using function-calling.

OpenRouter exposes an OpenAI-compatible /chat/completions endpoint. We
package the existing TOOLS registry as OpenAI-style functions, run an
agentic loop (model → maybe tool call → tool result → model …) until the
model returns a text reply, and return that as the assistant turn.

If `OPENROUTER_API_KEY` is empty, callers should fall back to the regex
intent router (see app.agent.router).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.agent.tools import TOOLS, call_tool

log = logging.getLogger("reyu.llm")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_TOOL_ITERATIONS = 4         # safety cap on tool-call loops
REQUEST_TIMEOUT_SEC = 45.0

SYSTEM_PROMPT = """You are Reyu.ai — an expert Indian options trading co-pilot.

You answer questions about NSE/BSE options: PCR, max pain, OI build-up, IV
skew, bias, hedging, payoff, scalping, and live positions.

You MUST use the provided tools to fetch live data — never invent numbers.
Pick the most specific tool. If the user names a symbol use it; otherwise
default to NIFTY.

Respond conversationally in **at most 5 sentences** plus relevant numbers.
Use Markdown sparingly: **bold** for the key answer, bullets only when you
have ≥3 items. Be direct — traders are busy.

If a tool returns a chart URL in its `chart` field, mention "(chart below)"
in the text so the user knows to scroll — the UI renders it inline.
"""


def is_enabled() -> bool:
    return bool(settings.openrouter_api_key)


def _tool_spec() -> list[dict]:
    """Convert TOOLS registry → OpenAI/OpenRouter function-calling schema."""
    funcs = []
    for name, meta in TOOLS.items():
        # Convert our simple {"symbol": "string"} param shapes into JSON-schema
        props: dict[str, Any] = {}
        for pname, pdesc in (meta.get("parameters") or {}).items():
            t = "string"
            if isinstance(pdesc, str) and pdesc.startswith("int"):
                t = "integer"
            elif isinstance(pdesc, str) and pdesc.startswith("list"):
                t = "array"
                props[pname] = {"type": "array", "items": {"type": "object"}, "description": pdesc}
                continue
            elif isinstance(pdesc, str) and ("BUY|SELL" in pdesc or "|" in pdesc):
                t = "string"
            props[pname] = {"type": t, "description": pdesc}
        funcs.append({
            "type": "function",
            "function": {
                "name": name,
                "description": meta["description"],
                "parameters": {"type": "object", "properties": props, "required": []},
            },
        })
    return funcs


async def chat_with_llm(
    user_message: str,
    history: list[dict] | None = None,
    user: dict | None = None,
) -> dict:
    """Run an agentic loop. Returns the same shape as TOOLS handlers:
       { text, chart?, chart_post?, data? }
    """
    if not is_enabled():
        return {"text": "LLM agent is not configured. Set OPENROUTER_API_KEY in .env."}

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.openrouter_referer,
        "X-Title": settings.openrouter_app_name,
    }

    # Build message list: system → history → current user turn
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in (history or [])[-10:]:
        # Strip any past tool_calls — we only feed text turns to keep the
        # window small and avoid confusing the model with stale tool args.
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})

    tools = _tool_spec()

    # Accumulators across the tool-call loop
    chart: str | None = None
    chart_post: dict | None = None
    data: dict | None = None

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SEC) as client:
        for iteration in range(MAX_TOOL_ITERATIONS):
            payload = {
                "model": settings.openrouter_model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.2,
            }
            try:
                r = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            except Exception as e:
                log.exception("OpenRouter call failed")
                return {"text": f"LLM call failed: {e}"}

            if r.status_code != 200:
                log.warning("OpenRouter %d: %s", r.status_code, r.text[:300])
                return {"text": f"LLM returned {r.status_code}. Check OPENROUTER_API_KEY and model name."}

            body = r.json()
            choice = (body.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            tool_calls = msg.get("tool_calls") or []

            # If the model wants to call tools, run them and loop
            if tool_calls:
                # Append the assistant message that requested the calls
                messages.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": tool_calls,
                })
                for tc in tool_calls:
                    fn = (tc.get("function") or {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        args = {}
                    result = await call_tool(name, args, user)
                    # Capture the first chart we see for the final response
                    if chart is None and result.get("chart"):
                        chart = result["chart"]
                    if chart_post is None and result.get("chart_post"):
                        chart_post = result["chart_post"]
                    if data is None and result.get("data"):
                        data = result["data"]
                    # Feed the tool result back to the model
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": result.get("text", "")[:2000],
                    })
                continue  # next iteration: model summarises the tool outputs

            # No tool call → this is the final answer
            return {
                "text": msg.get("content") or "Sorry — no response.",
                "chart": chart, "chart_post": chart_post, "data": data,
            }

    return {"text": "Reached tool-call iteration limit.",
            "chart": chart, "chart_post": chart_post, "data": data}

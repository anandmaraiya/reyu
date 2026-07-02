"""Direct Anthropic Claude API — mirror of app.agent.llm's public shape.

Preferred over OpenRouter when ANTHROPIC_API_KEY is set — cheaper (no
router markup), faster (fewer hops), and gives us access to the newest
Claude models the moment they ship.

Uses the /v1/messages endpoint with native tool-use format. The
tool-call loop is the same as llm.py: model → tool call → tool result →
model → … until stop_reason is `end_turn`.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.agent.tools import TOOLS, call_tool
from app.agent.system_prompt import build_system_prompt

log = logging.getLogger("reyu.anthropic")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOOL_ITERATIONS = 4
REQUEST_TIMEOUT_SEC = 45.0
MAX_TOKENS = 4096


def is_enabled() -> bool:
    return bool(settings.anthropic_api_key)


def _tool_spec() -> list[dict]:
    """TOOLS registry → Anthropic tool-use schema.

    Anthropic wants: {name, description, input_schema: JSONSchema}
    """
    out: list[dict] = []
    for name, meta in TOOLS.items():
        props: dict[str, Any] = {}
        for pname, pdesc in (meta.get("parameters") or {}).items():
            t = "string"
            if isinstance(pdesc, str) and pdesc.startswith("int"):
                t = "integer"
            elif isinstance(pdesc, str) and pdesc.startswith("list"):
                # Anthropic strict schema: describe list items
                props[pname] = {"type": "array", "items": {"type": "object"}, "description": pdesc}
                continue
            props[pname] = {"type": t, "description": pdesc}
        out.append({
            "name": name,
            "description": meta["description"],
            "input_schema": {"type": "object", "properties": props, "required": []},
        })
    return out


async def chat_with_claude(
    user_message: str,
    history: list[dict] | None = None,
    user: dict | None = None,
    *,
    tier: str = "anonymous",
    trial_days_left: int | None = None,
    connected_brokers: list[str] | None = None,
    spot_nifty: float | None = None,
    spot_banknifty: float | None = None,
    vix: float | None = None,
    pcr: float | None = None,
    plan_hint: str | None = None,
) -> dict:
    """Same interface as llm.chat_with_llm — swappable at the caller."""
    if not is_enabled():
        return {"text": "Anthropic LLM not configured. Set ANTHROPIC_API_KEY."}

    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    system_prompt = build_system_prompt(
        tier=tier,
        trial_days_left=trial_days_left,
        connected_brokers=connected_brokers,
        spot_nifty=spot_nifty,
        spot_banknifty=spot_banknifty,
        vix=vix,
        pcr=pcr,
    )
    if plan_hint:
        system_prompt = f"{system_prompt}\n\n{plan_hint}"

    # Anthropic messages array — system is separate, only user/assistant here.
    # Content blocks per message: [{"type": "text", "text": "..."}] for text,
    # or [{"type": "tool_use", ...}] / [{"type": "tool_result", ...}] for tools.
    messages: list[dict] = []
    for h in (history or [])[-10:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})

    tools = _tool_spec()

    chart: str | None = None
    chart_post: dict | None = None
    data: dict | None = None
    total_tokens = 0        # accumulate across tool-call iterations

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SEC) as client:
        for iteration in range(MAX_TOOL_ITERATIONS):
            payload = {
                "model": settings.anthropic_model,
                "max_tokens": MAX_TOKENS,
                "system": system_prompt,
                "messages": messages,
                "tools": tools,
                "temperature": 0.2,
            }
            try:
                r = await client.post(ANTHROPIC_URL, headers=headers, json=payload)
            except Exception as e:
                log.exception("Anthropic call failed")
                return {"text": f"LLM call failed: {e}"}

            if r.status_code != 200:
                log.warning("Anthropic %d: %s", r.status_code, r.text[:400])
                return {"text": f"LLM returned {r.status_code}. Check ANTHROPIC_API_KEY and model name."}

            body = r.json()
            content_blocks = body.get("content") or []
            stop_reason = body.get("stop_reason", "")
            usage = body.get("usage") or {}
            total_tokens += int(usage.get("input_tokens") or 0)
            total_tokens += int(usage.get("output_tokens") or 0)

            # Collect text + tool-use blocks from the assistant turn
            text_parts: list[str] = []
            tool_uses: list[dict] = []
            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_uses.append(block)

            if tool_uses:
                # Append assistant turn (must include the tool_use blocks verbatim)
                messages.append({"role": "assistant", "content": content_blocks})

                # Run each tool, append user turn with tool_result blocks
                tool_results: list[dict] = []
                for tu in tool_uses:
                    name = tu.get("name", "")
                    args = tu.get("input") or {}
                    result = await call_tool(name, args, user)
                    if chart is None and result.get("chart"):
                        chart = result["chart"]
                    if chart_post is None and result.get("chart_post"):
                        chart_post = result["chart_post"]
                    if data is None and result.get("data"):
                        data = result["data"]
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.get("id"),
                        "content": (result.get("text") or "")[:2000],
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            # No tool calls → final answer
            return {
                "text": "\n\n".join(t for t in text_parts if t).strip() or "Sorry — no response.",
                "chart": chart, "chart_post": chart_post, "data": data,
                "tokens": total_tokens,
            }

    return {"text": "Reached tool-call iteration limit.",
            "chart": chart, "chart_post": chart_post, "data": data,
            "tokens": total_tokens}

"""Outbound notifications — Telegram, Discord, generic webhook.

Webhook URLs are stored in Redis under `notify:webhooks` (list). We fan
events out to all of them with a 5-second timeout each.
"""
from __future__ import annotations

import logging
import httpx
from app.store import store

log = logging.getLogger("reyu.notify")
KEY = "notify:webhooks"


async def list_hooks() -> list[str]:
    return await store.r.lrange(KEY, 0, -1) or []


async def add_hook(url: str) -> None:
    await store.r.lpush(KEY, url)
    await store.r.ltrim(KEY, 0, 19)


async def remove_hook(url: str) -> None:
    await store.r.lrem(KEY, 1, url)


def _format_body(url: str, event: str, msg: str, extra: dict | None = None) -> dict:
    if "discord" in url:
        return {"content": f"**[Reyu] {event}** — {msg}"}
    if "telegram" in url:
        return {"text": f"[Reyu] {event}\n{msg}"}
    return {"event": event, "message": msg, "extra": extra or {}}


async def emit(event: str, msg: str, extra: dict | None = None) -> None:
    hooks = await list_hooks()
    if not hooks:
        return
    async with httpx.AsyncClient(timeout=5) as c:
        for url in hooks:
            try:
                await c.post(url, json=_format_body(url, event, msg, extra))
            except Exception as e:
                log.warning("webhook %s failed: %s", url, e)

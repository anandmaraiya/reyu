"""WebSocket fan-out for live ticks and option-chain snapshots.

Clients connect to /ws/ticks and send {"subscribe": ["NSE:NIFTY50-INDEX", ...]}.
The server subscribes to matching Redis pub/sub channels (`ticks:<sym>` and
`chain:<sym>`) populated by the scheduler and forwards messages.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.store import store

router = APIRouter()
log = logging.getLogger("reyu.ws")


@router.websocket("/ws/ticks")
async def ws_ticks(ws: WebSocket):
    await ws.accept()
    pubsub = store.r.pubsub()
    subscribed: set[str] = set()

    async def reader():
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                await ws.send_text(msg["data"])
            except Exception:
                break

    reader_task = asyncio.create_task(reader())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                cmd = json.loads(raw)
            except Exception:
                continue
            syms = cmd.get("subscribe") or []
            channels = []
            for s in syms:
                if s in subscribed:
                    continue
                subscribed.add(s)
                channels.extend([f"ticks:{s}", f"chain:{s}"])
            if channels:
                await pubsub.subscribe(*channels)
            unsub = cmd.get("unsubscribe") or []
            chans = []
            for s in unsub:
                subscribed.discard(s)
                chans.extend([f"ticks:{s}", f"chain:{s}"])
            if chans:
                await pubsub.unsubscribe(*chans)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("ws error: %s", e)
    finally:
        reader_task.cancel()
        try:
            await pubsub.aclose()
        except Exception:
            pass

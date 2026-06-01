"""Trade journal — free-text notes keyed by portfolio/strategy and timestamp.

Notes live in Redis (`journal:<ref>` list). Lightweight by design; if a user
needs query, attach a tag in the note body.
"""
from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel
import json

from app.store import store

router = APIRouter()


class Note(BaseModel):
    ref: str        # e.g. portfolio name or "strategy:NIFTY-IC-1"
    text: str
    tags: list[str] = []


@router.get("/{ref}")
async def list_notes(ref: str, limit: int = 50):
    raw = await store.r.lrange(f"journal:{ref}", 0, limit - 1)
    return [json.loads(x) for x in raw]


@router.post("")
async def add_note(n: Note):
    entry = {**n.model_dump(), "ts": datetime.utcnow().isoformat()}
    await store.r.lpush(f"journal:{n.ref}", json.dumps(entry))
    await store.r.ltrim(f"journal:{n.ref}", 0, 199)
    return entry


@router.delete("/{ref}/{idx}")
async def delete_note(ref: str, idx: int):
    raw = await store.r.lrange(f"journal:{ref}", 0, -1)
    if 0 <= idx < len(raw):
        await store.r.lrem(f"journal:{ref}", 1, raw[idx])
    return {"ok": True}

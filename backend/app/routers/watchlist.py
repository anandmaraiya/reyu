from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.store import store
from app.analytics.compare import compare_watchlist

router = APIRouter()
WL_KEY = "watchlists"


class Watchlist(BaseModel):
    name: str
    symbols: list[str]


@router.get("")
async def list_all():
    return await store.hgetall_json(WL_KEY)


@router.put("")
async def upsert(wl: Watchlist):
    await store.hset_json(WL_KEY, wl.name, wl.model_dump())
    return {"ok": True}


@router.delete("/{name}")
async def delete(name: str):
    await store.hdel(WL_KEY, name)
    return {"ok": True}


@router.get("/{name}/compare")
async def compare(name: str, strikecount: int = 15):
    wls = await store.hgetall_json(WL_KEY)
    wl = wls.get(name)
    if not wl:
        raise HTTPException(404, "watchlist not found")
    return await compare_watchlist(wl["symbols"], strikecount)

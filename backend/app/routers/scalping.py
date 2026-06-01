from fastapi import APIRouter, HTTPException
from app.analytics.scalping import scalp_signal
from app.store import store

router = APIRouter()
WL_KEY = "watchlists"


@router.get("/signal")
async def signal(symbol: str):
    return await scalp_signal(symbol)


@router.get("/scan/{watchlist}")
async def scan(watchlist: str):
    wls = await store.hgetall_json(WL_KEY)
    wl = wls.get(watchlist)
    if not wl:
        raise HTTPException(404, "watchlist not found")
    out = []
    for sym in wl["symbols"]:
        try:
            out.append(await scalp_signal(sym))
        except Exception as e:
            out.append({"symbol": sym, "error": str(e)})
    actionable = [s for s in out if s.get("direction")]
    return {"signals": out, "actionable": actionable}

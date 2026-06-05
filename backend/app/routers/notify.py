from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app import notify
from app.routers.user_auth import require_auth, require_tier

router = APIRouter()


class HookURL(BaseModel):
    url: str


@router.get("")
async def list_hooks(user: dict = Depends(require_tier("pro", "algo"))):
    return {"hooks": await notify.list_hooks()}


@router.post("")
async def add_hook(h: HookURL, user: dict = Depends(require_tier("pro", "algo"))):
    await notify.add_hook(h.url)
    return {"ok": True}


@router.delete("")
async def remove_hook(h: HookURL, user: dict = Depends(require_tier("pro", "algo"))):
    await notify.remove_hook(h.url)
    return {"ok": True}


@router.post("/test")
async def test(user: dict = Depends(require_tier("pro", "algo"))):
    await notify.emit("TEST", "Reyu.ai webhook test ping — looks good.")
    return {"ok": True}

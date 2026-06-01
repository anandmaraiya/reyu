from fastapi import APIRouter
from pydantic import BaseModel
from app import notify

router = APIRouter()


class HookURL(BaseModel):
    url: str


@router.get("")
async def list_hooks():
    return {"hooks": await notify.list_hooks()}


@router.post("")
async def add_hook(h: HookURL):
    await notify.add_hook(h.url)
    return {"ok": True}


@router.delete("")
async def remove_hook(h: HookURL):
    await notify.remove_hook(h.url)
    return {"ok": True}


@router.post("/test")
async def test():
    await notify.emit("TEST", "Reyu webhook test ping — looks good.")
    return {"ok": True}

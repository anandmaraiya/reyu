"""Fyers API v3 wrapper.

Centralises auth-token retrieval and exposes async helpers around the sync
fyers-apiv3 SDK. The SDK calls are wrapped with `run_in_threadpool` so the
event loop stays unblocked.
"""
from __future__ import annotations

from typing import Any
from fastapi.concurrency import run_in_threadpool
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws

from app.config import settings
from app.store import store
from app.fyers import mock


TOKEN_KEY = "fyers:access_token"


async def is_demo() -> bool:
    return not bool(await store.r.get(TOKEN_KEY))


async def get_access_token() -> str | None:
    return await store.r.get(TOKEN_KEY)


async def set_access_token(token: str) -> None:
    # Fyers tokens last ~24h
    await store.r.set(TOKEN_KEY, token, ex=23 * 3600)


async def _model() -> fyersModel.FyersModel | None:
    """Returns a Fyers client, or None to signal demo mode."""
    token = await get_access_token()
    if not token:
        return None
    return fyersModel.FyersModel(
        client_id=settings.fyers_app_id,
        token=token,
        is_async=False,
        log_path="",
    )


async def quotes(symbols: list[str]) -> dict[str, Any]:
    m = await _model()
    if m is None:
        return mock.mock_quotes(symbols)
    return await run_in_threadpool(m.quotes, data={"symbols": ",".join(symbols)})


async def option_chain(symbol: str, strikecount: int = 25, timestamp: str = "") -> dict[str, Any]:
    m = await _model()
    if m is None:
        return mock.mock_option_chain(symbol, strikecount)
    return await run_in_threadpool(
        m.optionchain,
        data={"symbol": symbol, "strikecount": strikecount, "timestamp": timestamp},
    )


async def history(symbol: str, resolution: str, range_from: str, range_to: str) -> dict[str, Any]:
    m = await _model()
    if m is None:
        return mock.mock_history(symbol, resolution, range_from, range_to)
    return await run_in_threadpool(
        m.history,
        data={
            "symbol": symbol, "resolution": resolution, "date_format": "1",
            "range_from": range_from, "range_to": range_to, "cont_flag": "1",
        },
    )


async def positions() -> dict[str, Any]:
    m = await _model()
    if m is None:
        return mock.mock_positions()
    return await run_in_threadpool(m.positions)


async def place_order(order: dict[str, Any]) -> dict[str, Any]:
    m = await _model()
    return await run_in_threadpool(m.place_order, data=order)


def build_socket(on_message) -> data_ws.FyersDataSocket:
    """Caller is responsible for managing the socket lifecycle."""
    return data_ws.FyersDataSocket(
        access_token=f"{settings.fyers_app_id}:{settings.fyers_app_id}",
        log_path="",
        litemode=False,
        write_to_file=False,
        reconnect=True,
        on_message=on_message,
    )

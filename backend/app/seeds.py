"""Pre-seeded watchlists for first-run onboarding."""
from __future__ import annotations
from app.store import store

WL_KEY = "watchlists"

PRESETS = {
    "Indian Indices": {
        "name": "Indian Indices",
        "symbols": [
            "NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX", "NSE:FINNIFTY-INDEX",
            "NSE:MIDCPNIFTY-INDEX", "BSE:SENSEX-INDEX",
        ],
    },
    "Bank Nifty Heavies": {
        "name": "Bank Nifty Heavies",
        "symbols": [
            "NSE:HDFCBANK-EQ", "NSE:ICICIBANK-EQ", "NSE:AXISBANK-EQ",
            "NSE:KOTAKBANK-EQ", "NSE:SBIN-EQ", "NSE:INDUSINDBK-EQ",
        ],
    },
    "Nifty IT": {
        "name": "Nifty IT",
        "symbols": [
            "NSE:TCS-EQ", "NSE:INFY-EQ", "NSE:HCLTECH-EQ",
            "NSE:WIPRO-EQ", "NSE:TECHM-EQ", "NSE:LTIM-EQ",
        ],
    },
    "F&O Liquid": {
        "name": "F&O Liquid",
        "symbols": [
            "NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ", "NSE:INFY-EQ",
            "NSE:TCS-EQ", "NSE:ICICIBANK-EQ", "NSE:ITC-EQ",
            "NSE:LT-EQ", "NSE:SBIN-EQ", "NSE:BHARTIARTL-EQ",
            "NSE:KOTAKBANK-EQ",
        ],
    },
    "Auto Sector": {
        "name": "Auto Sector",
        "symbols": [
            "NSE:MARUTI-EQ", "NSE:TATAMOTORS-EQ", "NSE:M&M-EQ",
            "NSE:BAJAJ-AUTO-EQ", "NSE:EICHERMOT-EQ", "NSE:HEROMOTOCO-EQ",
        ],
    },
}


async def seed_default_watchlists() -> None:
    existing = await store.hgetall_json(WL_KEY)
    for name, wl in PRESETS.items():
        if name not in existing:
            await store.hset_json(WL_KEY, name, wl)

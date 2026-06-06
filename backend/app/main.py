import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.routers import (
    auth, user_auth, options, analytics, watchlist, portfolio, scalping,
    timeseries, stream, orders, strategy, system, journal, notify, admin, chat, charts, telegram,
    backtest, billing, data_api,webhook_subs, rl,
)
from app.store import store
from app.db import init_db
from app import scheduler
from app.seeds import seed_default_watchlists
from app.auth_middleware import AuthMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.connect()
    await init_db()
    await scheduler.seed_tracked()
    await seed_default_watchlists()
    scheduler.start()
    yield
    scheduler.stop()
    await store.close()


app = FastAPI(
    title="Reyu.ai Trading Platform",
    version="0.3.0",
    description="**Reyu.ai** — Options trading platform for Indian markets.\n\n"
                "## Authentication\n\n"
                "Two methods are supported:\n"
                "- **Bearer JWT** — for browser sessions (login via `/api/user/login`)\n"
                "- **X-API-Key** — for B2B programmatic access (create keys at `/api/user/api-keys`)\n\n"
                "## Rate Limits (API Key consumers)\n\n"
                "| Tier  | Daily limit | Reset        |\n"
                "|-------|-------------|--------------|\n"
                "| Free  | 100         | UTC midnight |\n"
                "| Pro   | 10,000      | UTC midnight |\n"
                "| Algo  | Unlimited   | —            |\n\n"
                "Rate limit headers are included in responses:\n"
                "- `X-RateLimit-Limit` — daily quota\n"
                "- `X-RateLimit-Remaining` — requests left today\n"
                "- `X-RateLimit-Reset` — UTC epoch of next midnight\n\n"
                "## B2B Data API\n\n"
                "Programmatic consumers should use `/api/data/*` endpoints with an `X-API-Key` header.\n"
                "These mirror the read-only `/api/options/*` and `/api/ts/*` surfaces.\n\n"
                "## Webhook Events\n\n"
                "Subscribe to events at `/api/webhooks/subscriptions` (Pro/Algo tiers).\n"
                "Supported events: `PCR_THRESHOLD`, `BIAS_CHANGE`, `OI_SPIKE`, `ORDER_FILL`, `KILL_SWITCH`.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT access token from /api/user/login",
        },
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key from /api/user/api-keys — format: reyu_<random>",
        },
    }
    openapi_schema["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
    for path, methods in openapi_schema.get("paths", {}).items():
        if path.startswith("/api/data/"):
            for method, spec in methods.items():
                if "responses" in spec:
                    for code, resp in spec["responses"].items():
                        if code.startswith("2") or code == "429":
                            resp["headers"] = resp.get("headers", {})
                            resp["headers"]["X-RateLimit-Limit"] = {
                                "schema": {"type": "integer"},
                                "description": "Daily request quota for this key's tier",
                            }
                            resp["headers"]["X-RateLimit-Remaining"] = {
                                "schema": {"type": "integer"},
                                "description": "Requests remaining today",
                            }
                            resp["headers"]["X-RateLimit-Reset"] = {
                                "schema": {"type": "integer"},
                                "description": "UTC epoch of next midnight (when quota resets)",
                            }
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware — must be after CORS so preflight requests pass through
app.add_middleware(AuthMiddleware)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(user_auth.router, prefix="/api/user", tags=["user-auth"])
app.include_router(options.router, prefix="/api/options", tags=["options"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(scalping.router, prefix="/api/scalping", tags=["scalping"])
app.include_router(timeseries.router, prefix="/api/ts", tags=["timeseries"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(strategy.router, prefix="/api/strategy", tags=["strategy"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(journal.router, prefix="/api/journal", tags=["journal"])
app.include_router(notify.router, prefix="/api/notify", tags=["notify"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(charts.router, prefix="/api/chart", tags=["charts"])
app.include_router(telegram.router, prefix="/api/telegram", tags=["telegram"])
app.include_router(stream.router, tags=["stream"])
app.include_router(billing.router, prefix="/api/billing", tags=["billing"])
app.include_router(data_api.router, prefix="/api/data", tags=["data-api"])
app.include_router(webhook_subs.router, prefix="/api/webhooks", tags=["webhooks"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
app.include_router(rl.router, prefix="/api/rl", tags=["rl"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    auth, options, analytics, watchlist, portfolio, scalping,
    timeseries, stream, orders, strategy, system, journal, notify, admin,
)
from app.store import store
from app.db import init_db
from app import scheduler
from app.seeds import seed_default_watchlists

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


app = FastAPI(title="Reyu Trading Platform", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
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
app.include_router(stream.router, tags=["stream"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}

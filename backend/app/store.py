import json
import redis.asyncio as redis
from app.config import settings


class Store:
    """Thin Redis wrapper for tokens, watchlists, portfolios, and cached snapshots."""

    def __init__(self) -> None:
        self._r: redis.Redis | None = None

    async def connect(self) -> None:
        self._r = redis.from_url(settings.redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._r:
            await self._r.aclose()

    @property
    def r(self) -> redis.Redis:
        assert self._r is not None, "store not connected"
        return self._r

    async def set_json(self, key: str, value, ex: int | None = None) -> None:
        await self.r.set(key, json.dumps(value, default=str), ex=ex)

    async def get_json(self, key: str):
        v = await self.r.get(key)
        return json.loads(v) if v else None

    async def hset_json(self, key: str, field: str, value) -> None:
        await self.r.hset(key, field, json.dumps(value, default=str))

    async def hgetall_json(self, key: str) -> dict:
        raw = await self.r.hgetall(key)
        return {k: json.loads(v) for k, v in raw.items()}

    async def hdel(self, key: str, field: str) -> None:
        await self.r.hdel(key, field)


store = Store()

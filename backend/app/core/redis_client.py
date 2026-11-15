from typing import AsyncGenerator
import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logging import logger

redis_client: aioredis.Redis = None

async def init_redis():
    """Connect to Redis. On failure, leave redis_client as None so every
    optional Redis feature (embedding cache, answer cache) is skipped instead
    of each request waiting on a dead connection."""
    global redis_client
    client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        await client.ping()
    except Exception as e:
        logger.error(f"Failed to connect to Redis ({e}); Redis-backed caches are disabled.")
        redis_client = None
        try:
            await client.close()
        except Exception:
            pass
        raise
    redis_client = client
    logger.info("Successfully connected to Redis.")

async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    if redis_client is None:
        try:
            await init_redis()
        except Exception:
            pass
    yield redis_client

async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed.")

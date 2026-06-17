from typing import AsyncGenerator
import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logging import logger

redis_client: aioredis.Redis = None

async def init_redis():
    global redis_client
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )
        await redis_client.ping()
        logger.info("Successfully connected to Redis.")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {str(e)}")
        raise e

async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    if redis_client is None:
        await init_redis()
    yield redis_client

async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed.")

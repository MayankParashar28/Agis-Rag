import json
from typing import List, Dict, Any
from app.core.redis_client import get_redis
from app.core.logging import logger

class RedisChatMemory:
    def __init__(self):
        self.session_prefix = "session:"

    async def get_history(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves the last `limit` messages for a session.
        """
        try:
            async for redis in get_redis():
                key = f"{self.session_prefix}{session_id}"
                # Retrieve from list
                messages_json = await redis.lrange(key, -limit, -1)
                return [json.loads(msg) for msg in messages_json]
        except Exception as e:
            logger.error(f"Error fetching chat history from Redis: {str(e)}")
            return []

    async def add_message(self, session_id: str, message: Dict[str, Any]) -> None:
        """
        Adds a message to the session's list in Redis.
        """
        try:
            async for redis in get_redis():
                key = f"{self.session_prefix}{session_id}"
                await redis.rpush(key, json.dumps(message))
                # Set TTL to 7 days to auto-expire inactive sessions
                await redis.expire(key, 3600 * 24 * 7)
        except Exception as e:
            logger.error(f"Error adding message to Redis: {str(e)}")

    async def clear_history(self, session_id: str) -> None:
        """
        Clears history for a session.
        """
        try:
            async for redis in get_redis():
                key = f"{self.session_prefix}{session_id}"
                await redis.delete(key)
        except Exception as e:
            logger.error(f"Error deleting chat history in Redis: {str(e)}")

chat_memory = RedisChatMemory()

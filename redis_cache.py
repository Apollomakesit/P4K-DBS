import redis.asyncio as redis
from config import REDIS_URL

redis_client = redis.from_url(REDIS_URL)

async def set_online(player_id):
    await redis_client.set(player_id, "online", ex=60)

async def is_online(player_id):
    return await redis_client.get(player_id) == b"online"

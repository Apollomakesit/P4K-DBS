import aiohttp, asyncio
from datetime import datetime, timedelta
from sqlalchemy import select
from models import Player, History
from redis_cache import set_online
from config import BASE_URL, OFFLINE_CONFIRM_SECONDS, MAX_WORKERS

sem = asyncio.Semaphore(MAX_WORKERS)

async def scan_player(session, db, player_id):
    async with sem:
        async with session.get(f"{BASE_URL}/player/{player_id}") as r:
            data = await r.json()

    now = datetime.utcnow()
    online = data["status"] == "online"

    player = await db.get(Player, player_id)

    if online:
        if not player:
            player = Player(id=player_id, name=data["name"])
            db.add(player)

        player.is_online = True
        player.last_seen = now
        await set_online(player_id)

    else:
        if player and player.last_seen:
            if (now - player.last_seen).seconds > OFFLINE_CONFIRM_SECONDS:
                player.is_online = False

    db.add(History(player_id=player_id, snapshot=str(data)))
    await db.commit()

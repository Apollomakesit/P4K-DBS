import asyncio, aiohttp
from database import AsyncSessionLocal
from scanner import scan_player
from retention import cleanup

PLAYER_IDS = []

async def run():
    async with aiohttp.ClientSession() as session:
        while True:
            async with AsyncSessionLocal() as db:
                await asyncio.gather(
                    *[scan_player(session, db, pid) for pid in PLAYER_IDS]
                )
                await cleanup(db)
            await asyncio.sleep(15)

asyncio.run(run())

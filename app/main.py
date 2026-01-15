import asyncio
import aiohttp
import time
from database import init_db
from scanner import scan_player
from retention import cleanup
from config import SCAN_INTERVAL

PLAYER_IDS = []  # load from file / API / DB

async def scan_loop():
    async with aiohttp.ClientSession() as session:
        while True:
            tasks = [scan_player(session, pid) for pid in PLAYER_IDS]
            await asyncio.gather(*tasks)
            cleanup()
            await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    init_db()
    asyncio.run(scan_loop())

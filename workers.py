import asyncio
import aiohttp
from config import MAX_WORKERS, USER_AGENT, REQUEST_TIMEOUT

sem = asyncio.Semaphore(MAX_WORKERS)

async def fetch(session, url):
    async with sem:
        async with session.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

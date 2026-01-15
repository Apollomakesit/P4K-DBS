import aiohttp
import asyncio
from datetime import datetime, timedelta
from database import get_db
from workers import fetch
from config import BASE_URL, OFFLINE_CONFIRM_SECONDS

async def scan_player(session, player_id):
    url = f"{BASE_URL}/player/{player_id}"
    data = await fetch(session, url)

    now = datetime.utcnow()
    online = data.get("status") == "online"

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT last_seen FROM players WHERE id=?", (player_id,))
    row = cur.fetchone()

    if online:
        cur.execute("""
            INSERT INTO players (id, name, is_online, last_seen)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(id) DO UPDATE SET
                is_online=1,
                last_seen=excluded.last_seen
        """, (player_id, data["name"], now))

    else:
        if row:
            last_seen = datetime.fromisoformat(row["last_seen"])
            if (now - last_seen).seconds >= OFFLINE_CONFIRM_SECONDS:
                cur.execute(
                    "UPDATE players SET is_online=0 WHERE id=?",
                    (player_id,)
                )

    cur.execute(
        "INSERT INTO history (player_id, snapshot) VALUES (?, ?)",
        (player_id, str(data))
    )

    db.commit()

from fastapi import FastAPI
from sqlalchemy.future import select
from models import Player
from database import get_db

app = FastAPI()

@app.get("/players")
async def players(db=next(get_db())):
    res = await db.execute(select(Player))
    return res.scalars().all()

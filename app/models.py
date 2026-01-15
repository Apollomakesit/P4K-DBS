from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class Player(Base):
    __tablename__ = "players"
    id = Column(String, primary_key=True)
    name = Column(String)
    is_online = Column(Boolean, default=False)
    last_seen = Column(DateTime)

class History(Base):
    __tablename__ = "history"
    id = Column(Integer, primary_key=True)
    player_id = Column(String, ForeignKey("players.id"))
    snapshot = Column(String)
    recorded_at = Column(DateTime, default=datetime.utcnow)

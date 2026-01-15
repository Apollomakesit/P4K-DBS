from datetime import datetime, timedelta
from sqlalchemy import delete
from models import History
from config import DATA_RETENTION_DAYS

async def cleanup(db):
    cutoff = datetime.utcnow() - timedelta(days=DATA_RETENTION_DAYS)
    await db.execute(delete(History).where(History.recorded_at < cutoff))
    await db.commit()

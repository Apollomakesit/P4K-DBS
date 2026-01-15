from datetime import datetime, timedelta
from database import get_db
from config import DATA_RETENTION_DAYS

def cleanup():
    cutoff = datetime.utcnow() - timedelta(days=DATA_RETENTION_DAYS)
    db = get_db()
    db.execute(
        "DELETE FROM history WHERE recorded_at < ?",
        (cutoff,)
    )
    db.commit()

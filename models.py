from dataclasses import dataclass
from datetime import datetime

@dataclass
class Player:
    id: str
    name: str
    is_online: bool
    last_seen: datetime

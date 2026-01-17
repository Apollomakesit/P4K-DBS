import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class Database:
    """Enhanced database manager with indefinite storage"""
    
    def __init__(self, db_path: str = 'pro4kings.db'):
        self.db_path = db_path
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_database(self):
        """Initialize database with complete schema"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Players table with extended fields
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS players (
                    player_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    is_online BOOLEAN DEFAULT FALSE,
                    last_seen TIMESTAMP,
                    first_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    -- Profile fields
                    faction TEXT,
                    faction_rank TEXT,
                    job TEXT,
                    level INTEGER,
                    respect_points INTEGER,
                    warnings INTEGER,
                    played_hours REAL,
                    age_ic INTEGER,
                    phone_number TEXT,
                    vehicles_count INTEGER,
                    properties_count INTEGER,
                    
                    -- Metadata
                    total_actions INTEGER DEFAULT 0,
                    last_profile_update TIMESTAMP,
                    priority_update BOOLEAN DEFAULT FALSE,
                    
                    UNIQUE(username)
                )
            ''')
            
            # Actions table - INDEFINITE STORAGE (no automatic cleanup)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id TEXT,
                    player_name TEXT,
                    action_type TEXT NOT NULL,
                    action_detail TEXT,
                    
                    -- Item transfer fields
                    item_name TEXT,
                    item_quantity INTEGER,
                    target_player_id TEXT,
                    target_player_name TEXT,
                    
                    -- Warning fields
                    admin_id TEXT,
                    admin_name TEXT,
                    warning_count TEXT,
                    reason TEXT,
                    
                    -- Timestamp and raw data
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    raw_text TEXT,
                    
                    FOREIGN KEY (player_id) REFERENCES players(player_id)
                )
            ''')
            
            # Login/Logout events
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS login_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id TEXT NOT NULL,
                    player_name TEXT,
                    event_type TEXT NOT NULL CHECK(event_type IN ('login', 'logout')),
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    session_duration_seconds INTEGER,
                    
                    FOREIGN KEY (player_id) REFERENCES players(player_id)
                )
            ''')
            
            # Faction rank history
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rank_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id TEXT NOT NULL,
                    faction TEXT NOT NULL,
                    rank_name TEXT NOT NULL,
                    rank_obtained TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    rank_lost TIMESTAMP,
                    is_current BOOLEAN DEFAULT TRUE,
                    
                    FOREIGN KEY (player_id) REFERENCES players(player_id)
                )
            ''')
            
            # Profile change history
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS profile_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    FOREIGN KEY (player_id) REFERENCES players(player_id)
                )
            ''')
            
            # Banned players
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS banned_players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    admin TEXT,
                    reason TEXT,
                    duration TEXT,
                    ban_date TEXT,
                    expiry_date TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    UNIQUE(player_id, ban_date)
                )
            ''')
            
            # Online players snapshot
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS online_players (
                    player_id TEXT PRIMARY KEY,
                    player_name TEXT NOT NULL,
                    detected_online_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    FOREIGN KEY (player_id) REFERENCES players(player_id)
                )
            ''')
            
            # Scan progress for resumability
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scan_progress (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    last_scanned_player_id TEXT,
                    last_scan_timestamp TIMESTAMP,
                    total_players_scanned INTEGER DEFAULT 0,
                    scan_completed BOOLEAN DEFAULT FALSE
                )
            ''')
            
            # Create indexes for performance
            indexes = [
                'CREATE INDEX IF NOT EXISTS idx_actions_player ON actions(player_id)',
                'CREATE INDEX IF NOT EXISTS idx_actions_timestamp ON actions(timestamp)',
                'CREATE INDEX IF NOT EXISTS idx_actions_type ON actions(action_type)',
                'CREATE INDEX IF NOT EXISTS idx_login_events_player ON login_events(player_id)',
                'CREATE INDEX IF NOT EXISTS idx_login_events_timestamp ON login_events(timestamp)',
                'CREATE INDEX IF NOT EXISTS idx_players_online ON players(is_online)',
                'CREATE INDEX IF NOT EXISTS idx_players_faction ON players(faction)',
                'CREATE INDEX IF NOT EXISTS idx_players_level ON players(level)',
                'CREATE INDEX IF NOT EXISTS idx_players_priority ON players(priority_update)',
                'CREATE INDEX IF NOT EXISTS idx_rank_history_player ON rank_history(player_id)',
                'CREATE INDEX IF NOT EXISTS idx_rank_history_current ON rank_history(is_current)',
                'CREATE INDEX IF NOT EXISTS idx_profile_history_player ON profile_history(player_id)',
                'CREATE INDEX IF NOT EXISTS idx_banned_active ON banned_players(is_active)',
            ]
            
            for index_sql in indexes:
                cursor.execute(index_sql)
            
            conn.commit()
        
        logger.info("Database initialized successfully")
    
    def save_player_profile(self, profile) -> None:
        """Save/update player profile with change tracking"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get current values to detect changes
            cursor.execute('''
                SELECT faction, faction_rank, job, level, warnings, respect_points
                FROM players WHERE player_id = ?
            ''', (profile['player_id'],))
            old_data = cursor.fetchone()
            
            # Insert or update player
            cursor.execute('''
                INSERT INTO players (
                    player_id, username, is_online, last_seen,
                    faction, faction_rank, job, level, respect_points, warnings,
                    played_hours, age_ic, phone_number, vehicles_count, properties_count,
                    last_profile_update
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(player_id) DO UPDATE SET
                    username = excluded.username,
                    is_online = excluded.is_online,
                    last_seen = excluded.last_seen,
                    faction = excluded.faction,
                    faction_rank = excluded.faction_rank,
                    job = excluded.job,
                    level = excluded.level,
                    respect_points = excluded.respect_points,
                    warnings = excluded.warnings,
                    played_hours = excluded.played_hours,
                    age_ic = excluded.age_ic,
                    phone_number = excluded.phone_number,
                    vehicles_count = excluded.vehicles_count,
                    properties_count = excluded.properties_count,
                    last_profile_update = CURRENT_TIMESTAMP
            ''', (
                profile['player_id'],
                profile['player_name'],
                profile.get('is_online', False),
                profile.get('last_connection', datetime.now()),
                profile.get('faction'),
                profile.get('faction_rank'),
                profile.get('job'),
                profile.get('level'),
                profile.get('respect_points'),
                profile.get('warns'),
                profile.get('played_hours'),
                profile.get('age_ic'),
                profile.get('phone_number'),
                profile.get('vehicles_count'),
                profile.get('properties_count')
            ))
            
            # Track faction rank changes
            if old_data:
                old_faction = old_data['faction']
                old_rank = old_data['faction_rank']
                new_faction = profile.get('faction')
                new_rank = profile.get('faction_rank')
                
                # Check if rank changed
                if (old_faction != new_faction or old_rank != new_rank) and new_rank:
                    # Mark old rank as lost
                    if old_rank:
                        cursor.execute('''
                            UPDATE rank_history
                            SET rank_lost = CURRENT_TIMESTAMP, is_current = FALSE
                            WHERE player_id = ? AND is_current = TRUE
                        ''', (profile['player_id'],))
                    
                    # Add new rank
                    cursor.execute('''
                        INSERT INTO rank_history (player_id, faction, rank_name, is_current)
                        VALUES (?, ?, ?, TRUE)
                    ''', (profile['player_id'], new_faction, new_rank))
                
                # Track other field changes
                fields = ['faction', 'job', 'level', 'warnings', 'respect_points']
                new_values = [new_faction, profile.get('job'), profile.get('level'), 
                            profile.get('warns'), profile.get('respect_points')]
                
                for i, field in enumerate(fields):
                    old_val = str(old_data[i]) if old_data[i] is not None else None
                    new_val = str(new_values[i]) if new_values[i] is not None else None
                    
                    if old_val != new_val and new_val is not None:
                        cursor.execute('''
                            INSERT INTO profile_history (player_id, field_name, old_value, new_value)
                            VALUES (?, ?, ?, ?)
                        ''', (profile['player_id'], field, old_val, new_val))
            
            conn.commit()
    
    def save_action(self, action) -> None:
        """Save action to database (stored indefinitely)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO actions (
                    player_id, player_name, action_type, action_detail,
                    item_name, item_quantity, target_player_id, target_player_name,
                    admin_id, admin_name, warning_count, reason,
                    timestamp, raw_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                action.get('player_id'),
                action.get('player_name'),
                action['action_type'],
                action.get('action_detail'),
                action.get('item_name'),
                action.get('item_quantity'),
                action.get('target_player_id'),
                action.get('target_player_name'),
                action.get('admin_id'),
                action.get('admin_name'),
                action.get('warning_count'),
                action.get('reason'),
                action.get('timestamp', datetime.now()),
                action.get('raw_text')
            ))
            
            # Increment player action count
            if action.get('player_id'):
                cursor.execute('''
                    UPDATE players SET total_actions = total_actions + 1
                    WHERE player_id = ?
                ''', (action['player_id'],))
            
            conn.commit()
    
    def action_exists(self, timestamp: datetime, text: str) -> bool:
        """Check if action already exists"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 1 FROM actions
                WHERE timestamp = ? AND raw_text = ?
                LIMIT 1
            ''', (timestamp, text))
            return cursor.fetchone() is not None
    
    def save_login(self, player_id: str, player_name: str, timestamp: datetime) -> None:
        """Save login event"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO login_events (player_id, player_name, event_type, timestamp)
                VALUES (?, ?, 'login', ?)
            ''', (player_id, player_name, timestamp))
            conn.commit()
    
    def save_logout(self, player_id: str, timestamp: datetime) -> None:
        """Save logout event with session duration calculation"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Find last login
            cursor.execute('''
                SELECT timestamp FROM login_events
                WHERE player_id = ? AND event_type = 'login'
                ORDER BY timestamp DESC LIMIT 1
            ''', (player_id,))
            
            last_login = cursor.fetchone()
            session_duration = None
            
            if last_login:
                login_time = datetime.fromisoformat(last_login[0])
                session_duration = int((timestamp - login_time).total_seconds())
            
            cursor.execute('''
                INSERT INTO login_events (player_id, event_type, timestamp, session_duration_seconds)
                VALUES (?, 'logout', ?, ?)
            ''', (player_id, timestamp, session_duration))
            
            conn.commit()
    
    def update_online_players(self, online_players: List[Dict]) -> None:
        """Update online players snapshot (upsert, no deletion)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for player in online_players:
                cursor.execute('''
                    INSERT INTO online_players (player_id, player_name, detected_online_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(player_id) DO UPDATE SET
                        detected_online_at = CURRENT_TIMESTAMP
                ''', (player['player_id'], player['player_name']))
                
                # Also update main players table
                cursor.execute('''
                    UPDATE players
                    SET is_online = TRUE, last_seen = CURRENT_TIMESTAMP
                    WHERE player_id = ?
                ''', (player['player_id'],))
            
            conn.commit()
    
    def mark_player_for_update(self, player_id: str, player_name: str) -> None:
        """Mark player for priority profile update"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO players (player_id, username, priority_update)
                VALUES (?, ?, TRUE)
                ON CONFLICT(player_id) DO UPDATE SET
                    priority_update = TRUE
            ''', (player_id, player_name))
            conn.commit()
    
    def get_players_pending_update(self, limit: int = 100) -> List[str]:
        """Get player IDs pending profile update"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT player_id FROM players
                WHERE priority_update = TRUE
                ORDER BY last_profile_update ASC
                LIMIT ?
            ''', (limit,))
            return [row[0] for row in cursor.fetchall()]
    
    def reset_player_priority(self, player_id: str) -> None:
        """Reset player priority after update"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE players
                SET priority_update = FALSE
                WHERE player_id = ?
            ''', (player_id,))
            conn.commit()
    
    def get_current_online_players(self) -> List[Dict]:
        """Get currently online players"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT player_id, player_name
                FROM online_players
                ORDER BY detected_online_at DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_player_actions(self, identifier: str, days: int = 7) -> List[Dict]:
        """Get player actions by ID or name"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            cursor.execute('''
                SELECT * FROM actions
                WHERE (player_id = ? OR player_name LIKE ?)
                    AND timestamp >= ?
                ORDER BY timestamp DESC
            ''', (identifier, f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def save_banned_player(self, ban_data: Dict) -> None:
        """Save banned player info"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO banned_players (
                    player_id, player_name, admin, reason, duration,
                    ban_date, expiry_date, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, TRUE)
                ON CONFLICT(player_id, ban_date) DO UPDATE SET
                    is_active = TRUE,
                    last_checked = CURRENT_TIMESTAMP
            ''', (
                ban_data['player_id'],
                ban_data['player_name'],
                ban_data.get('admin'),
                ban_data.get('reason'),
                ban_data.get('duration'),
                ban_data.get('ban_date'),
                ban_data.get('expiry_date')
            ))
            conn.commit()
    
    def mark_expired_bans(self, current_ban_ids: set) -> None:
        """NEW METHOD: Mark bans as expired if they're no longer on the banlist"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all active bans
            cursor.execute('SELECT player_id FROM banned_players WHERE is_active = TRUE')
            active_bans = {row[0] for row in cursor.fetchall()}
            
            # Find expired bans (active in DB but not on current list)
            expired = active_bans - current_ban_ids
            
            if expired:
                placeholders = ','.join('?' * len(expired))
                cursor.execute(f'''
                    UPDATE banned_players
                    SET is_active = FALSE
                    WHERE player_id IN ({placeholders}) AND is_active = TRUE
                ''', list(expired))
                
                conn.commit()
                logger.info(f"Marked {len(expired)} bans as expired")
    
    def get_banned_players(self, include_expired: bool = False) -> List[Dict]:
        """Get banned players"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if include_expired:
                cursor.execute('SELECT * FROM banned_players ORDER BY detected_at DESC')
            else:
                cursor.execute('SELECT * FROM banned_players WHERE is_active = TRUE ORDER BY detected_at DESC')
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_player_by_exact_id(self, player_id: str) -> Optional[Dict]:
        """NEW METHOD: Get player by exact ID match (not fuzzy)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM players WHERE player_id = ?', (player_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_player_rank_history(self, player_id: str) -> List[Dict]:
        """Get player rank history"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM rank_history
                WHERE player_id = ?
                ORDER BY rank_obtained DESC
            ''', (player_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_recent_promotions(self, days: int = 7) -> List[Dict]:
        """Get recent rank promotions"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            cursor.execute('''
                SELECT 
                    r.*,
                    p.username as player_name
                FROM rank_history r
                INNER JOIN players p ON r.player_id = p.player_id
                WHERE r.rank_obtained >= ?
                ORDER BY r.rank_obtained DESC
            ''', (cutoff,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_player_gave(self, identifier: str, days: int = 7) -> List[Dict]:
        """Get items given by player"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            cursor.execute('''
                SELECT * FROM actions
                WHERE (player_id = ? OR player_name LIKE ?)
                    AND action_type = 'item_given'
                    AND timestamp >= ?
                ORDER BY timestamp DESC
            ''', (identifier, f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_player_received(self, identifier: str, days: int = 7) -> List[Dict]:
        """Get items received by player"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            cursor.execute('''
                SELECT * FROM actions
                WHERE (player_id = ? OR player_name LIKE ?)
                    AND action_type = 'item_received'
                    AND timestamp >= ?
                ORDER BY timestamp DESC
            ''', (identifier, f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_player_interactions(self, identifier: str, days: int = 7) -> List[Dict]:
        """Get all unique players interacted with"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            cursor.execute('''
                SELECT 
                    COALESCE(target_player_name, 'Unknown') as other_player,
                    COALESCE(target_player_id, 'N/A') as other_player_id,
                    COUNT(*) as interaction_count,
                    SUM(CASE WHEN action_type = 'item_given' THEN 1 ELSE 0 END) as gave_count,
                    SUM(CASE WHEN action_type = 'item_received' THEN 1 ELSE 0 END) as received_count
                FROM actions
                WHERE (player_id = ? OR player_name LIKE ?)
                    AND action_type IN ('item_given', 'item_received')
                    AND timestamp >= ?
                    AND target_player_name IS NOT NULL
                GROUP BY target_player_name, target_player_id
                ORDER BY interaction_count DESC
            ''', (identifier, f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_interactions_between(self, player1: str, player2: str, days: int = 7) -> List[Dict]:
        """Get interactions between two specific players"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            cursor.execute('''
                SELECT * FROM actions
                WHERE action_type IN ('item_given', 'item_received')
                    AND timestamp >= ?
                    AND (
                        ((player_id = ? OR player_name LIKE ?) AND (target_player_id = ? OR target_player_name LIKE ?))
                        OR
                        ((player_id = ? OR player_name LIKE ?) AND (target_player_id = ? OR target_player_name LIKE ?))
                    )
                ORDER BY timestamp DESC
            ''', (cutoff, player1, f'%{player1}%', player2, f'%{player2}%',
                  player2, f'%{player2}%', player1, f'%{player1}%'))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_player_sessions(self, identifier: str, days: int = 7) -> List[Dict]:
        """Get player login sessions"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            cursor.execute('''
                SELECT 
                    player_id,
                    player_name,
                    timestamp as login_time,
                    session_duration_seconds,
                    CASE 
                        WHEN session_duration_seconds IS NOT NULL 
                        THEN time(session_duration_seconds, 'unixepoch')
                        ELSE '🟢 Online acum'
                    END as duration
                FROM login_events
                WHERE (player_id = ? OR player_name LIKE ?)
                    AND event_type = 'login'
                    AND timestamp >= ?
                ORDER BY timestamp DESC
            ''', (identifier, f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_players_by_faction(self, faction_name: str) -> List[Dict]:
        """Get all players in a faction"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM players
                WHERE faction LIKE ?
                ORDER BY 
                    CASE 
                        WHEN faction_rank LIKE '%Leader%' THEN 1
                        WHEN faction_rank LIKE '%Co-Lider%' THEN 2
                        ELSE 3
                    END,
                    level DESC
            ''', (f'%{faction_name}%',))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_current_faction_ranks(self, faction_name: str) -> List[Dict]:
        """Get current ranks in a faction"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    p.player_id,
                    p.username as player_name,
                    p.faction,
                    p.faction_rank,
                    p.is_online,
                    CAST((julianday('now') - julianday(r.rank_obtained)) AS INTEGER) as days_in_rank
                FROM players p
                LEFT JOIN rank_history r ON p.player_id = r.player_id AND r.is_current = TRUE
                WHERE p.faction LIKE ?
                ORDER BY p.faction_rank, days_in_rank DESC
            ''', (f'%{faction_name}%',))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_players_by_rank(self, rank_name: str) -> List[Dict]:
        """Get all players with specific rank"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    p.*,
                    CAST((julianday('now') - julianday(r.rank_obtained)) AS INTEGER) as days_in_rank
                FROM players p
                INNER JOIN rank_history r ON p.player_id = r.player_id AND r.is_current = TRUE
                WHERE r.rank_name LIKE ?
                ORDER BY r.rank_obtained DESC
            ''', (f'%{rank_name}%',))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_players_with_warns(self, min_warns: int = 1) -> List[Dict]:
        """Get players with warnings"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM players
                WHERE warnings >= ?
                ORDER BY warnings DESC, last_seen DESC
            ''', (min_warns,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def search_player_by_name(self, name: str) -> List[Dict]:
        """Search players by name"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM players
                WHERE username LIKE ?
                ORDER BY is_online DESC, last_seen DESC
                LIMIT 20
            ''', (f'%{name}%',))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_player_last_connection(self, player_id: int) -> Optional[Dict]:
        """Get player's last connection info"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM players WHERE player_id = ?
            ''', (str(player_id),))
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_scan_progress(self) -> Dict:
        """Get scan progress stats"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM players')
            total_scanned = cursor.fetchone()[0]
            
            cursor.execute('SELECT * FROM scan_progress WHERE id = 1')
            progress = cursor.fetchone()
            
            # Estimate total (you can adjust this based on actual server player count)
            estimated_total = max(total_scanned, 10000)  # Adjust as needed
            
            return {
                'total_scanned': total_scanned,
                'total_target': estimated_total,
                'percentage': (total_scanned / estimated_total * 100) if estimated_total > 0 else 0,
                'last_scan': progress['last_scan_timestamp'] if progress else None
            }
    
    def is_initial_scan_complete(self) -> bool:
        """Check if initial scan is complete"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT scan_completed FROM scan_progress WHERE id = 1')
            result = cursor.fetchone()
            return result['scan_completed'] if result else False
    
    def save_scan_progress(self, last_player_id: str, total_scanned: int, completed: bool = False) -> None:
        """Save scan progress"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO scan_progress (id, last_scanned_player_id, last_scan_timestamp, total_players_scanned, scan_completed)
                VALUES (1, ?, CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_scanned_player_id = excluded.last_scanned_player_id,
                    last_scan_timestamp = CURRENT_TIMESTAMP,
                    total_players_scanned = excluded.total_players_scanned,
                    scan_completed = excluded.scan_completed
            ''', (last_player_id, total_scanned, completed))
            conn.commit()

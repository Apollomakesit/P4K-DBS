import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import logging
from contextlib import contextmanager
import time

logger = logging.getLogger(__name__)

class Database:
    """Enhanced database manager with retry logic and better error handling"""
    
    def __init__(self, db_path: str = 'pro4kings.db'):
        self.db_path = db_path
        self.init_database()
    
    @contextmanager
    def get_connection(self, retries: int = 3):
        """
        Context manager for database connections with retry logic
        
        Handles SQLITE_BUSY errors by retrying with exponential backoff
        """
        conn = None
        last_error = None
        
        for attempt in range(retries):
            try:
                # 🔥 Increased timeout from 30s to 60s
                conn = sqlite3.connect(self.db_path, timeout=60.0)
                conn.row_factory = sqlite3.Row
                
                # 🔥 Enable WAL mode for better concurrency
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA busy_timeout=60000')  # 60 second busy timeout
                
                yield conn
                conn.commit()
                return
                
            except sqlite3.OperationalError as e:
                last_error = e
                if 'database is locked' in str(e).lower() or 'busy' in str(e).lower():
                    if attempt < retries - 1:
                        wait_time = (2 ** attempt) * 0.1  # 0.1s, 0.2s, 0.4s
                        logger.warning(f"Database busy, retrying in {wait_time}s... (attempt {attempt + 1}/{retries})")
                        time.sleep(wait_time)
                        continue
                raise
                
            except Exception as e:
                last_error = e
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                raise
                
            finally:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
        
        # If we get here, all retries failed
        if last_error:
            logger.error(f"Database operation failed after {retries} attempts: {last_error}")
            raise last_error
    
    def init_database(self):
        """Initialize database with complete schema"""
        try:
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
                
                # Actions table - INDEFINITE STORAGE
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
            
            logger.info("✅ Database initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}", exc_info=True)
            raise
    
    def save_player_profile(self, profile) -> None:
        """Save/update player profile with change tracking"""
        try:
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
        except Exception as e:
            logger.error(f"Error saving player profile {profile.get('player_id')}: {e}", exc_info=True)
            raise
    
    def save_action(self, action) -> None:
        """Save action to database (stored indefinitely)"""
        try:
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
        except Exception as e:
            logger.error(f"Error saving action: {e}", exc_info=True)
            raise
    
    def action_exists(self, timestamp: datetime, text: str) -> bool:
        """Check if action already exists"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT 1 FROM actions
                    WHERE timestamp = ? AND raw_text = ?
                    LIMIT 1
                ''', (timestamp, text))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking action existence: {e}")
            return False
    
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
        """Update online players snapshot"""
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
        """Mark player for priority profile update
        
        🔥 FIX: Handles UNIQUE constraint on username properly
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 🔥 Check if username already exists with a different player_id
                cursor.execute('SELECT player_id FROM players WHERE username = ?', (player_name,))
                existing = cursor.fetchone()
                
                if existing and existing[0] != player_id:
                    # Username exists with different ID - this happens when:
                    # 1. Player was deleted and recreated with same name
                    # 2. Data inconsistency on server
                    # 3. Username was changed but we found both versions
                    logger.warning(
                        f"Username '{player_name}' exists with different ID. "
                        f"Existing: {existing[0]}, New: {player_id}. "
                        f"Updating existing record."
                    )
                    
                    # Update the existing record's player_id to the new one
                    cursor.execute('''
                        UPDATE players 
                        SET player_id = ?, priority_update = TRUE
                        WHERE username = ?
                    ''', (player_id, player_name))
                else:
                    # Safe to insert or update
                    cursor.execute('''
                        INSERT INTO players (player_id, username, priority_update)
                        VALUES (?, ?, TRUE)
                        ON CONFLICT(player_id) DO UPDATE SET
                            username = excluded.username,
                            priority_update = TRUE
                    ''', (player_id, player_name))
                
                conn.commit()
                
        except sqlite3.IntegrityError as e:
            # Additional safety net
            if 'UNIQUE constraint' in str(e):
                logger.error(
                    f"UNIQUE constraint error for player_id={player_id}, username={player_name}. "
                    f"Skipping this update. Error: {e}"
                )
            else:
                raise
        except Exception as e:
            logger.error(f"Error in mark_player_for_update: {e}", exc_info=True)
            raise
    
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
        """Get player actions - STRICT filtering"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            # Strategy 1: Try exact player_id match first
            if identifier.isdigit():
                cursor.execute('''
                    SELECT * FROM actions
                    WHERE player_id = ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (identifier, cutoff))
                results = cursor.fetchall()
                
                if results:
                    return [dict(row) for row in results]
            
            # Strategy 2: Fuzzy name match
            cursor.execute('''
                SELECT * FROM actions
                WHERE player_name LIKE ? AND timestamp >= ?
                ORDER BY timestamp DESC
            ''', (f'%{identifier}%', cutoff))
            
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
        """Mark bans as expired if they're no longer on the banlist"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all active bans
            cursor.execute('SELECT player_id FROM banned_players WHERE is_active = TRUE')
            active_bans = {row[0] for row in cursor.fetchall()}
            
            # Find expired bans
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
        """Get player by exact ID match"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM players WHERE player_id = ?', (player_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
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
    
    def get_scan_progress(self) -> Dict:
        """Get scan progress stats"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM players')
            total_scanned = cursor.fetchone()[0]
            
            cursor.execute('SELECT * FROM scan_progress WHERE id = 1')
            progress = cursor.fetchone()
            
            estimated_total = max(total_scanned, 10000)
            
            return {
                'total_scanned': total_scanned,
                'total_target': estimated_total,
                'percentage': (total_scanned / estimated_total * 100) if estimated_total > 0 else 0,
                'last_scan': progress['last_scan_timestamp'] if progress else None,
                'last_scanned_id': progress['last_scanned_player_id'] if progress else None
            }
    
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

import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import logging
from contextlib import contextmanager
import time
import asyncio

logger = logging.getLogger(__name__)

class Database:
    """Enhanced async-safe database manager with non-blocking operations"""
    
    def __init__(self, db_path: str = 'pro4kings.db'):
        self.db_path = db_path
        # Initialize database synchronously on startup (before event loop)
        self._init_database_sync()
    
    @contextmanager
    def get_connection(self, retries: int = 3):
        """
        Context manager for database connections with retry logic
        
        ⚠️ WARNING: This is SYNCHRONOUS and should only be called via asyncio.to_thread()
        """
        conn = None
        last_error = None
        
        for attempt in range(retries):
            try:
                # 🔥 Reduced timeout from 60s to 10s to prevent long blocks
                conn = sqlite3.connect(self.db_path, timeout=10.0)
                conn.row_factory = sqlite3.Row
                
                # 🔥 Enable WAL mode for better concurrency
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA busy_timeout=10000')  # 10 second busy timeout
                # 🔥 Optimize for speed
                conn.execute('PRAGMA synchronous=NORMAL')  # Faster than FULL, still safe with WAL
                conn.execute('PRAGMA cache_size=-64000')  # 64MB cache
                
                yield conn
                conn.commit()
                return
                
            except sqlite3.OperationalError as e:
                last_error = e
                if 'database is locked' in str(e).lower() or 'busy' in str(e).lower():
                    if attempt < retries - 1:
                        wait_time = (2 ** attempt) * 0.05  # 50ms, 100ms, 200ms
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
    
    def _init_database_sync(self):
        """Initialize database (called synchronously on startup)"""
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
                
                # Scan progress table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS scan_progress (
                        id INTEGER PRIMARY KEY CHECK(id = 1),
                        last_scanned_id INTEGER DEFAULT 0,
                        found_count INTEGER DEFAULT 0,
                        error_count INTEGER DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Initialize scan_progress if empty
                cursor.execute('SELECT COUNT(*) FROM scan_progress')
                if cursor.fetchone()[0] == 0:
                    cursor.execute('''
                        INSERT INTO scan_progress (id, last_scanned_id, found_count, error_count)
                        VALUES (1, 0, 0, 0)
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
    
    # 🔥 ASYNC WRAPPER: All public methods now use asyncio.to_thread()
    
    def _save_player_profile_sync(self, profile) -> None:
        """SYNC: Save/update player profile with change tracking"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get current values to detect changes
                cursor.execute('''
                    SELECT faction, faction_rank, job, level, warnings, respect_points
                    FROM players WHERE player_id = ?
                ''', (profile['player_id'],))
                old_data = cursor.fetchone()
                
                username = profile.get('player_name') or profile.get('username', f"Player_{profile['player_id']}")
                last_seen = profile.get('last_connection') or profile.get('last_seen', datetime.now())
                
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
                    username,
                    profile.get('is_online', False),
                    last_seen,
                    profile.get('faction'),
                    profile.get('faction_rank'),
                    profile.get('job'),
                    profile.get('level'),
                    profile.get('respect_points'),
                    profile.get('warns') or profile.get('warnings'),
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
                    
                    if (old_faction != new_faction or old_rank != new_rank) and new_rank:
                        if old_rank:
                            cursor.execute('''
                                UPDATE rank_history
                                SET rank_lost = CURRENT_TIMESTAMP, is_current = FALSE
                                WHERE player_id = ? AND is_current = TRUE
                            ''', (profile['player_id'],))
                        
                        cursor.execute('''
                            INSERT INTO rank_history (player_id, faction, rank_name, is_current)
                            VALUES (?, ?, ?, TRUE)
                        ''', (profile['player_id'], new_faction, new_rank))
                    
                    # Track other field changes
                    fields = ['faction', 'job', 'level', 'warnings', 'respect_points']
                    new_values = [new_faction, profile.get('job'), profile.get('level'), 
                                profile.get('warns') or profile.get('warnings'), profile.get('respect_points')]
                    
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
    
    async def save_player_profile(self, profile) -> None:
        """ASYNC: Save/update player profile"""
        await asyncio.to_thread(self._save_player_profile_sync, profile)
    
    def _update_scan_progress_sync(self, last_id: int, found: int, errors: int) -> None:
        """SYNC: Update scan progress"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE scan_progress 
                    SET last_scanned_id = ?, 
                        found_count = ?, 
                        error_count = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                ''', (last_id, found, errors))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating scan progress: {e}", exc_info=True)
    
    async def update_scan_progress(self, last_id: int, found: int, errors: int) -> None:
        """ASYNC: Update scan progress"""
        await asyncio.to_thread(self._update_scan_progress_sync, last_id, found, errors)
    
    def _get_scan_progress_sync(self) -> Optional[Dict]:
        """SYNC: Get scan progress"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM scan_progress WHERE id = 1')
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting scan progress: {e}")
            return None
    
    async def get_scan_progress(self) -> Optional[Dict]:
        """ASYNC: Get scan progress"""
        return await asyncio.to_thread(self._get_scan_progress_sync)
    
    def _save_action_sync(self, action) -> None:
        """SYNC: Save action to database"""
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
    
    async def save_action(self, action) -> None:
        """ASYNC: Save action to database"""
        await asyncio.to_thread(self._save_action_sync, action)
    
    def _action_exists_sync(self, timestamp: datetime, text: str) -> bool:
        """SYNC: Check if action exists"""
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
    
    async def action_exists(self, timestamp: datetime, text: str) -> bool:
        """ASYNC: Check if action exists"""
        return await asyncio.to_thread(self._action_exists_sync, timestamp, text)
    
    def _save_login_sync(self, player_id: str, player_name: str, timestamp: datetime) -> None:
        """SYNC: Save login event"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO login_events (player_id, player_name, event_type, timestamp)
                VALUES (?, ?, 'login', ?)
            ''', (player_id, player_name, timestamp))
            conn.commit()
    
    async def save_login(self, player_id: str, player_name: str, timestamp: datetime) -> None:
        """ASYNC: Save login event"""
        await asyncio.to_thread(self._save_login_sync, player_id, player_name, timestamp)
    
    def _save_logout_sync(self, player_id: str, timestamp: datetime) -> None:
        """🔥 OPTIMIZED SYNC: Save logout event - FAST VERSION"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 🔥 Single optimized query with subquery instead of separate SELECT
                cursor.execute('''
                    INSERT INTO login_events (player_id, event_type, timestamp, session_duration_seconds)
                    SELECT ?, 'logout', ?,
                           CAST((julianday(?) - julianday(timestamp)) * 86400 AS INTEGER)
                    FROM login_events
                    WHERE player_id = ? AND event_type = 'login'
                    ORDER BY timestamp DESC LIMIT 1
                ''', (player_id, timestamp, timestamp, player_id))
                
                # If no matching login found, insert without duration
                if cursor.rowcount == 0:
                    cursor.execute('''
                        INSERT INTO login_events (player_id, event_type, timestamp, session_duration_seconds)
                        VALUES (?, 'logout', ?, NULL)
                    ''', (player_id, timestamp))
                
                conn.commit()
        except Exception as e:
            logger.error(f"Error saving logout for {player_id}: {e}", exc_info=True)
            # Don't raise - this shouldn't crash the bot
    
    async def save_logout(self, player_id: str, timestamp: datetime) -> None:
        """🔥 ASYNC: Save logout event - NON-BLOCKING"""
        await asyncio.to_thread(self._save_logout_sync, player_id, timestamp)
    
    def _update_online_players_sync(self, online_players: List[Dict]) -> None:
        """🔥 OPTIMIZED SYNC: Batch update online players"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 🔥 Batch insert with executemany for speed
                cursor.executemany('''
                    INSERT INTO online_players (player_id, player_name, detected_online_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(player_id) DO UPDATE SET
                        detected_online_at = CURRENT_TIMESTAMP
                ''', [(p['player_id'], p['player_name']) for p in online_players])
                
                # 🔥 Batch update players table
                cursor.executemany('''
                    UPDATE players
                    SET is_online = TRUE, last_seen = CURRENT_TIMESTAMP
                    WHERE player_id = ?
                ''', [(p['player_id'],) for p in online_players])
                
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating online players: {e}", exc_info=True)
    
    async def update_online_players(self, online_players: List[Dict]) -> None:
        """ASYNC: Update online players snapshot"""
        await asyncio.to_thread(self._update_online_players_sync, online_players)
    
    def _mark_player_for_update_sync(self, player_id: str, player_name: str) -> None:
        """SYNC: Mark player for priority update"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('SELECT player_id FROM players WHERE username = ?', (player_name,))
                existing = cursor.fetchone()
                
                if existing and existing[0] != player_id:
                    logger.warning(
                        f"Username '{player_name}' exists with different ID. "
                        f"Existing: {existing[0]}, New: {player_id}. Updating existing record."
                    )
                    cursor.execute('''
                        UPDATE players 
                        SET player_id = ?, priority_update = TRUE
                        WHERE username = ?
                    ''', (player_id, player_name))
                else:
                    cursor.execute('''
                        INSERT INTO players (player_id, username, priority_update)
                        VALUES (?, ?, TRUE)
                        ON CONFLICT(player_id) DO UPDATE SET
                            username = excluded.username,
                            priority_update = TRUE
                    ''', (player_id, player_name))
                
                conn.commit()
                
        except sqlite3.IntegrityError as e:
            if 'UNIQUE constraint' in str(e):
                logger.error(f"UNIQUE constraint error for player_id={player_id}, username={player_name}. Skipping.")
            else:
                raise
        except Exception as e:
            logger.error(f"Error in mark_player_for_update: {e}", exc_info=True)
    
    async def mark_player_for_update(self, player_id: str, player_name: str) -> None:
        """ASYNC: Mark player for priority update"""
        await asyncio.to_thread(self._mark_player_for_update_sync, player_id, player_name)
    
    def _get_players_pending_update_sync(self, limit: int = 100) -> List[str]:
        """SYNC: Get player IDs pending update"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT player_id FROM players
                WHERE priority_update = TRUE
                ORDER BY last_profile_update ASC
                LIMIT ?
            ''', (limit,))
            return [row[0] for row in cursor.fetchall()]
    
    async def get_players_pending_update(self, limit: int = 100) -> List[str]:
        """ASYNC: Get player IDs pending update"""
        return await asyncio.to_thread(self._get_players_pending_update_sync, limit)
    
    def _reset_player_priority_sync(self, player_id: str) -> None:
        """SYNC: Reset player priority"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE players
                SET priority_update = FALSE
                WHERE player_id = ?
            ''', (player_id,))
            conn.commit()
    
    async def reset_player_priority(self, player_id: str) -> None:
        """ASYNC: Reset player priority"""
        await asyncio.to_thread(self._reset_player_priority_sync, player_id)
    
    def _get_current_online_players_sync(self) -> List[Dict]:
        """SYNC: Get currently online players"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT player_id, player_name
                FROM online_players
                ORDER BY detected_online_at DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    async def get_current_online_players(self) -> List[Dict]:
        """ASYNC: Get currently online players"""
        return await asyncio.to_thread(self._get_current_online_players_sync)
    
    def _get_player_actions_sync(self, identifier: str, days: int = 7) -> List[Dict]:
        """SYNC: Get player actions"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            if identifier.isdigit():
                cursor.execute('''
                    SELECT * FROM actions
                    WHERE player_id = ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (identifier, cutoff))
                results = cursor.fetchall()
                
                if results:
                    return [dict(row) for row in results]
            
            cursor.execute('''
                SELECT * FROM actions
                WHERE player_name LIKE ? AND timestamp >= ?
                ORDER BY timestamp DESC
            ''', (f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    async def get_player_actions(self, identifier: str, days: int = 7) -> List[Dict]:
        """ASYNC: Get player actions"""
        return await asyncio.to_thread(self._get_player_actions_sync, identifier, days)
    
    def _save_banned_player_sync(self, ban_data: Dict) -> None:
        """SYNC: Save banned player"""
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
    
    async def save_banned_player(self, ban_data: Dict) -> None:
        """ASYNC: Save banned player"""
        await asyncio.to_thread(self._save_banned_player_sync, ban_data)
    
    def _mark_expired_bans_sync(self, current_ban_ids: set) -> None:
        """SYNC: Mark expired bans"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT player_id FROM banned_players WHERE is_active = TRUE')
            active_bans = {row[0] for row in cursor.fetchall()}
            
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
    
    async def mark_expired_bans(self, current_ban_ids: set) -> None:
        """ASYNC: Mark expired bans"""
        await asyncio.to_thread(self._mark_expired_bans_sync, current_ban_ids)
    
    def _get_banned_players_sync(self, include_expired: bool = False) -> List[Dict]:
        """SYNC: Get banned players"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if include_expired:
                cursor.execute('SELECT * FROM banned_players ORDER BY detected_at DESC')
            else:
                cursor.execute('SELECT * FROM banned_players WHERE is_active = TRUE ORDER BY detected_at DESC')
            
            return [dict(row) for row in cursor.fetchall()]
    
    async def get_banned_players(self, include_expired: bool = False) -> List[Dict]:
        """ASYNC: Get banned players"""
        return await asyncio.to_thread(self._get_banned_players_sync, include_expired)
    
    def _get_player_by_exact_id_sync(self, player_id: str) -> Optional[Dict]:
        """SYNC: Get player by exact ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM players WHERE player_id = ?', (player_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    async def get_player_by_exact_id(self, player_id: str) -> Optional[Dict]:
        """ASYNC: Get player by exact ID"""
        return await asyncio.to_thread(self._get_player_by_exact_id_sync, player_id)
    
    def _search_player_by_name_sync(self, name: str) -> List[Dict]:
        """SYNC: Search players by name"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM players
                WHERE username LIKE ?
                ORDER BY is_online DESC, last_seen DESC
                LIMIT 20
            ''', (f'%{name}%',))
            
            return [dict(row) for row in cursor.fetchall()]
    
    async def search_player_by_name(self, name: str) -> List[Dict]:
        """ASYNC: Search players by name"""
        return await asyncio.to_thread(self._search_player_by_name_sync, name)
    
    def _save_scan_progress_sync(self, last_player_id: str, total_scanned: int, completed: bool = False) -> None:
        """SYNC: Save scan progress (legacy)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE scan_progress
                SET last_scanned_id = ?,
                    found_count = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
            ''', (last_player_id, total_scanned))
            conn.commit()
    
    async def save_scan_progress(self, last_player_id: str, total_scanned: int, completed: bool = False) -> None:
        """ASYNC: Save scan progress (legacy)"""
        await asyncio.to_thread(self._save_scan_progress_sync, last_player_id, total_scanned, completed)

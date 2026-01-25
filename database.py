import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import logging
from contextlib import contextmanager
import time
import asyncio
import os

logger = logging.getLogger(__name__)

class Database:
    """Enhanced async-safe database manager with proper CSV import support"""
    
    def __init__(self, db_path: str = None):
        # Railway Volume Support
        if db_path is None:
            if os.path.exists('/data'):
                db_path = '/data/pro4kings.db'
                logger.info("📦 Using Railway volume: /data/pro4kings.db")
            else:
                db_path = 'pro4kings.db'
                logger.info("💾 Using local database: pro4kings.db")
        
        self.db_path = db_path
        logger.info(f"📁 Database path: {self.db_path}")
        
        # Initialize database synchronously on startup
        self._init_database_sync()
    
    @contextmanager
    def get_connection(self, retries: int = 3):
        """Context manager for database connections with retry logic"""
        conn = None
        last_error = None
        
        for attempt in range(retries):
            try:
                conn = sqlite3.connect(self.db_path, timeout=10.0)
                conn.row_factory = sqlite3.Row
                
                # Enable WAL mode for better concurrency
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA busy_timeout=10000')
                conn.execute('PRAGMA synchronous=NORMAL')
                conn.execute('PRAGMA cache_size=-64000')
                
                yield conn
                conn.commit()
                return
                
            except sqlite3.OperationalError as e:
                last_error = e
                if 'database is locked' in str(e).lower() or 'busy' in str(e).lower():
                    if attempt < retries - 1:
                        wait_time = (2 ** attempt) * 0.05
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
        
        if last_error:
            logger.error(f"Database operation failed after {retries} attempts: {last_error}")
            raise last_error
    
    def _init_database_sync(self):
        """Initialize database with proper schema for CSV import"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # ✅ FIXED: Player profiles table - NO UNIQUE constraint on username
                # Multiple players CAN have the same name with different IDs
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS player_profiles (
                        player_id TEXT PRIMARY KEY,
                        username TEXT NOT NULL,
                        is_online BOOLEAN DEFAULT FALSE,
                        last_seen TIMESTAMP,
                        first_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        
                        -- Profile fields matching CSV
                        faction TEXT,
                        faction_rank TEXT,
                        job TEXT,
                        warnings INTEGER DEFAULT 0,
                        played_hours REAL DEFAULT 0,
                        age_ic INTEGER,
                        
                        -- Metadata
                        total_actions INTEGER DEFAULT 0,
                        last_profile_update TIMESTAMP,
                        priority_update BOOLEAN DEFAULT FALSE,
                        
                        -- CSV import tracking
                        imported_from_csv BOOLEAN DEFAULT FALSE,
                        csv_last_connection TIMESTAMP,
                        csv_check_priority INTEGER DEFAULT 0
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
                        
                        FOREIGN KEY (player_id) REFERENCES player_profiles(player_id)
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
                        
                        FOREIGN KEY (player_id) REFERENCES player_profiles(player_id)
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
                        
                        FOREIGN KEY (player_id) REFERENCES player_profiles(player_id)
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
                        
                        FOREIGN KEY (player_id) REFERENCES player_profiles(player_id)
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
                        
                        FOREIGN KEY (player_id) REFERENCES player_profiles(player_id)
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
                    'CREATE INDEX IF NOT EXISTS idx_actions_target ON actions(target_player_id)',
                    'CREATE INDEX IF NOT EXISTS idx_actions_timestamp ON actions(timestamp)',
                    'CREATE INDEX IF NOT EXISTS idx_actions_type ON actions(action_type)',
                    'CREATE INDEX IF NOT EXISTS idx_login_events_player ON login_events(player_id)',
                    'CREATE INDEX IF NOT EXISTS idx_login_events_timestamp ON login_events(timestamp)',
                    'CREATE INDEX IF NOT EXISTS idx_players_online ON player_profiles(is_online)',
                    'CREATE INDEX IF NOT EXISTS idx_players_faction ON player_profiles(faction)',
                    'CREATE INDEX IF NOT EXISTS idx_players_priority ON player_profiles(priority_update)',
                    'CREATE INDEX IF NOT EXISTS idx_players_username ON player_profiles(username)',  # ✅ Index for search, NOT unique
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
    
    # ========== CSV IMPORT METHODS ==========
    
    def _import_csv_profile_sync(self, csv_row: Dict) -> None:
        """
        Import a single profile from CSV
        CSV columns: player_id, player_name, last_connection, is_online, faction, 
                     faction_rank, warns, job, played_hours, age_ic, last_checked, check_priority
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Convert CSV data types
                player_id = str(csv_row.get('player_id', '')).strip()
                username = str(csv_row.get('player_name', '')).strip() or f"Player_{player_id}"
                
                # Handle timestamps
                last_connection = csv_row.get('last_connection')
                if isinstance(last_connection, str):
                    try:
                        last_connection = datetime.strptime(last_connection, '%Y-%m-%d %H:%M:%S')
                    except:
                        last_connection = None
                
                # Handle is_online - convert from string/int to boolean
                is_online_raw = csv_row.get('is_online', '0')
                is_online = str(is_online_raw).strip() == '1' or str(is_online_raw).lower() == 'true'
                
                # Handle nulls and convert types
                faction = csv_row.get('faction')
                if faction and (faction.lower() == 'null' or faction.strip() == ''):
                    faction = None
                    
                faction_rank = csv_row.get('faction_rank')
                if faction_rank and (faction_rank.lower() == 'null' or faction_rank.strip() == ''):
                    faction_rank = None
                
                job = csv_row.get('job', 'Somer')
                if job and (job.lower() == 'null' or job.strip() == ''):
                    job = 'Somer'
                
                try:
                    warnings = int(csv_row.get('warns', 0))
                except:
                    warnings = 0
                
                try:
                    played_hours = float(csv_row.get('played_hours', 0))
                except:
                    played_hours = 0.0
                
                try:
                    age_ic = int(csv_row.get('age_ic', 18))
                except:
                    age_ic = 18
                
                # ✅ FIXED: Use INSERT OR REPLACE to handle duplicates by player_id ONLY
                # This allows multiple players with same username but different IDs
                cursor.execute('''
                    INSERT INTO player_profiles (
                        player_id, username, is_online, last_seen,
                        faction, faction_rank, job, warnings,
                        played_hours, age_ic,
                        imported_from_csv, csv_last_connection, csv_check_priority,
                        last_profile_update, first_detected
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(player_id) DO UPDATE SET
                        username = excluded.username,
                        is_online = excluded.is_online,
                        last_seen = excluded.last_seen,
                        faction = COALESCE(excluded.faction, faction),
                        faction_rank = COALESCE(excluded.faction_rank, faction_rank),
                        job = COALESCE(excluded.job, job),
                        warnings = COALESCE(excluded.warnings, warnings),
                        played_hours = COALESCE(excluded.played_hours, played_hours),
                        age_ic = COALESCE(excluded.age_ic, age_ic),
                        imported_from_csv = TRUE,
                        csv_last_connection = excluded.csv_last_connection,
                        csv_check_priority = excluded.csv_check_priority,
                        last_profile_update = CURRENT_TIMESTAMP
                ''', (
                    player_id,
                    username,
                    is_online,
                    last_connection or datetime.now(),
                    faction,
                    faction_rank,
                    job,
                    warnings,
                    played_hours,
                    age_ic,
                    last_connection,
                    csv_row.get('check_priority', 0)
                ))
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"Error importing CSV profile {csv_row.get('player_id')}: {e}", exc_info=True)
            raise
    
    async def import_csv_profile(self, csv_row: Dict) -> None:
        """ASYNC: Import a single profile from CSV"""
        await asyncio.to_thread(self._import_csv_profile_sync, csv_row)
    
    # ========== PLAYER PROFILE METHODS ==========
    
    def _save_player_profile_sync(self, profile) -> None:
        """Save/update player profile with change tracking"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get current values to detect changes
                cursor.execute('''
                    SELECT faction, faction_rank, job, warnings
                    FROM player_profiles WHERE player_id = ?
                ''', (profile['player_id'],))
                old_data = cursor.fetchone()
                
                username = profile.get('player_name') or profile.get('username', f"Player_{profile['player_id']}")
                last_seen = profile.get('last_connection') or profile.get('last_seen', datetime.now())
                
                # ✅ FIXED: No check for duplicate usernames - they are allowed!
                cursor.execute('''
                    INSERT INTO player_profiles (
                        player_id, username, is_online, last_seen,
                        faction, faction_rank, job, warnings,
                        played_hours, age_ic,
                        last_profile_update
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(player_id) DO UPDATE SET
                        username = excluded.username,
                        is_online = excluded.is_online,
                        last_seen = excluded.last_seen,
                        faction = COALESCE(excluded.faction, faction),
                        faction_rank = COALESCE(excluded.faction_rank, faction_rank),
                        job = COALESCE(excluded.job, job),
                        warnings = COALESCE(excluded.warnings, warnings),
                        played_hours = COALESCE(excluded.played_hours, played_hours),
                        age_ic = COALESCE(excluded.age_ic, age_ic),
                        last_profile_update = CURRENT_TIMESTAMP
                ''', (
                    profile['player_id'],
                    username,
                    profile.get('is_online', False),
                    last_seen,
                    profile.get('faction'),
                    profile.get('faction_rank'),
                    profile.get('job'),
                    profile.get('warns') or profile.get('warnings'),
                    profile.get('played_hours'),
                    profile.get('age_ic')
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
                    fields = ['faction', 'job', 'warnings']
                    new_values = [new_faction, profile.get('job'), profile.get('warns') or profile.get('warnings')]
                    
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
    
    def _get_player_by_id_or_name_sync(self, identifier: str) -> Optional[Dict]:
        """
        Get player by ID or name
        Returns first match if multiple players have same name
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Try exact ID match first
            if identifier.isdigit():
                cursor.execute('SELECT * FROM player_profiles WHERE player_id = ?', (identifier,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
            
            # Search by username (case-insensitive)
            cursor.execute('''
                SELECT * FROM player_profiles
                WHERE LOWER(username) = LOWER(?)
                ORDER BY last_seen DESC
                LIMIT 1
            ''', (identifier,))
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    async def get_player_by_id_or_name(self, identifier: str) -> Optional[Dict]:
        """ASYNC: Get player by ID or name"""
        return await asyncio.to_thread(self._get_player_by_id_or_name_sync, identifier)
    
    def _get_all_players_with_name_sync(self, username: str) -> List[Dict]:
        """
        Get ALL players with a specific username (handles duplicates)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM player_profiles
                WHERE LOWER(username) = LOWER(?)
                ORDER BY last_seen DESC
            ''', (username,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    async def get_all_players_with_name(self, username: str) -> List[Dict]:
        """ASYNC: Get all players with specific username"""
        return await asyncio.to_thread(self._get_all_players_with_name_sync, username)
    
    # ========== ACTION TRACKING METHODS ==========
    
    def _save_action_sync(self, action) -> None:
        """Save action to database"""
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
                        UPDATE player_profiles SET total_actions = total_actions + 1
                        WHERE player_id = ?
                    ''', (action['player_id'],))
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"Error saving action: {e}", exc_info=True)
            raise
    
    async def save_action(self, action) -> None:
        """ASYNC: Save action to database"""
        await asyncio.to_thread(self._save_action_sync, action)
    
    def _get_player_actions_sync(self, identifier: str, days: int = 7) -> List[Dict]:
        """Get player actions - bidirectional (sender OR receiver)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            if identifier.isdigit():
                cursor.execute('''
                    SELECT * FROM actions
                    WHERE (player_id = ? OR target_player_id = ?) AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (identifier, identifier, cutoff))
            else:
                cursor.execute('''
                    SELECT * FROM actions
                    WHERE (player_name LIKE ? OR target_player_name LIKE ?) AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (f'%{identifier}%', f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    async def get_player_actions(self, identifier: str, days: int = 7) -> List[Dict]:
        """ASYNC: Get player actions"""
        return await asyncio.to_thread(self._get_player_actions_sync, identifier, days)
    
    # ========== STATS AND UTILITY METHODS ==========
    
    async def get_database_stats(self) -> Dict:
        """Get database statistics"""
        def _get_stats_sync():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('SELECT COUNT(*) FROM player_profiles')
                total_players = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM player_profiles WHERE imported_from_csv = TRUE')
                imported_players = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM actions')
                total_actions = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM online_players')
                online_count = cursor.fetchone()[0]
                
                return {
                    'total_players': total_players,
                    'imported_from_csv': imported_players,
                    'total_actions': total_actions,
                    'online_count': online_count
                }
        
        return await asyncio.to_thread(_get_stats_sync)
    
    async def get_player_by_exact_id(self, player_id: str) -> Optional[Dict]:
        """ASYNC: Get player by exact ID"""
        def _get_sync():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM player_profiles WHERE player_id = ?', (player_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        
        return await asyncio.to_thread(_get_sync)
    
    async def search_player_by_name(self, name: str) -> List[Dict]:
        """ASYNC: Search players by name (returns all matches)"""
        def _search_sync():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM player_profiles
                    WHERE username LIKE ?
                    ORDER BY last_seen DESC
                    LIMIT 50
                ''', (f'%{name}%',))
                
                return [dict(row) for row in cursor.fetchall()]
        
        return await asyncio.to_thread(_search_sync)
    
    # ========== REMAINING ASYNC WRAPPER METHODS ==========
    # (Keep all other existing methods with asyncio.to_thread() pattern)
    
    async def update_scan_progress(self, last_id: int, found: int, errors: int) -> None:
        """ASYNC: Update scan progress"""
        def _update_sync():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE scan_progress
                    SET last_scanned_id = ?, found_count = ?, error_count = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                ''', (last_id, found, errors))
                conn.commit()
        
        await asyncio.to_thread(_update_sync)
    
    async def get_scan_progress(self) -> Optional[Dict]:
        """ASYNC: Get scan progress"""
        def _get_sync():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM scan_progress WHERE id = 1')
                row = cursor.fetchone()
                return dict(row) if row else None
        
        return await asyncio.to_thread(_get_sync)
    
    async def update_online_players(self, online_players: List[Dict]) -> None:
        """ASYNC: Update online players snapshot"""
        def _update_sync():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Batch insert/update
                cursor.executemany('''
                    INSERT INTO online_players (player_id, player_name, detected_online_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(player_id) DO UPDATE SET
                        detected_online_at = CURRENT_TIMESTAMP
                ''', [(p['player_id'], p['player_name']) for p in online_players])
                
                # Update player_profiles
                cursor.executemany('''
                    UPDATE player_profiles
                    SET is_online = TRUE, last_seen = CURRENT_TIMESTAMP
                    WHERE player_id = ?
                ''', [(p['player_id'],) for p in online_players])
                
                conn.commit()
        
        await asyncio.to_thread(_update_sync)
    
    async def mark_player_for_update(self, player_id: str, player_name: str) -> None:
        """ASYNC: Mark player for priority update"""
        def _mark_sync():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO player_profiles (player_id, username, priority_update)
                    VALUES (?, ?, TRUE)
                    ON CONFLICT(player_id) DO UPDATE SET
                        username = excluded.username,
                        priority_update = TRUE
                ''', (player_id, player_name))
                conn.commit()
        
        await asyncio.to_thread(_mark_sync)
    
    async def get_players_pending_update(self, limit: int = 100) -> List[str]:
        """ASYNC: Get player IDs pending update"""
        def _get_sync():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT player_id FROM player_profiles
                    WHERE priority_update = TRUE
                    ORDER BY last_profile_update ASC
                    LIMIT ?
                ''', (limit,))
                return [row[0] for row in cursor.fetchall()]
        
        return await asyncio.to_thread(_get_sync)
    
    async def reset_player_priority(self, player_id: str) -> None:
        """ASYNC: Reset player priority"""
        def _reset_sync():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE player_profiles
                    SET priority_update = FALSE
                    WHERE player_id = ?
                ''', (player_id,))
                conn.commit()
        
        await asyncio.to_thread(_reset_sync)
    
    # Add remaining methods from original file as needed...
    # (get_faction_members, get_all_factions_with_counts, save_login, save_logout, etc.)

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
    """Enhanced async-safe database manager with non-blocking operations"""
    
    def __init__(self, db_path: str = None):
        # 🔥 Railway Volume Support: Use /data if available, otherwise default path
        if db_path is None:
            if os.path.exists('/data'):
                db_path = '/data/pro4kings.db'
                logger.info("📦 Using Railway volume: /data/pro4kings.db")
            else:
                db_path = 'pro4kings.db'
                logger.info("💾 Using local database: pro4kings.db")
        
        self.db_path = db_path
        logger.info(f"📁 Database path: {self.db_path}")
        
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
                    'CREATE INDEX IF NOT EXISTS idx_actions_target ON actions(target_player_id)',  # 🆕 NEW INDEX
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
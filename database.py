import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
import os

class Database:
    def __init__(self, db_path='sqlite:///pro4kings.db'):
        if db_path.startswith('sqlite:///'):
            self.db_path = db_path.replace('sqlite:///', '')
        else:
            self.db_path = db_path
            self.use_postgres = True
            return
        
        self.use_postgres = False
        self._init_db()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_db(self):
        """Initialize database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    text TEXT NOT NULL,
                    from_player TEXT,
                    from_id INTEGER,
                    to_player TEXT,
                    to_id INTEGER,
                    quantity INTEGER,
                    item TEXT,
                    action_type TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(timestamp, text)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS player_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL,
                    player_name TEXT NOT NULL,
                    login_time DATETIME NOT NULL,
                    logout_time DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS online_players (
                    player_id INTEGER PRIMARY KEY,
                    player_name TEXT NOT NULL,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS player_profiles (
                    player_id INTEGER PRIMARY KEY,
                    player_name TEXT NOT NULL,
                    last_connection DATETIME,
                    is_online BOOLEAN DEFAULT 0,
                    faction TEXT,
                    faction_rank TEXT,
                    warns INTEGER DEFAULT 0,
                    job TEXT,
                    played_hours REAL DEFAULT 0,
                    age_ic INTEGER,
                    last_checked DATETIME DEFAULT CURRENT_TIMESTAMP,
                    check_priority INTEGER DEFAULT 1
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rank_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL,
                    player_name TEXT NOT NULL,
                    faction TEXT NOT NULL,
                    rank_name TEXT NOT NULL,
                    rank_obtained DATETIME NOT NULL,
                    rank_lost DATETIME,
                    is_current BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (player_id) REFERENCES player_profiles(player_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_status (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_actions_timestamp ON actions(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_actions_from_player ON actions(from_player)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_actions_to_player ON actions(to_player)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_actions_from_id ON actions(from_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_actions_to_id ON actions(to_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_player_id ON player_sessions(player_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_login ON player_sessions(login_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_profiles_last_checked ON player_profiles(last_checked)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_profiles_faction ON player_profiles(faction)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_profiles_name ON player_profiles(player_name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_profiles_rank ON player_profiles(faction_rank)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_rank_history_player ON rank_history(player_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_rank_history_current ON rank_history(is_current)')
    
    def action_exists(self, timestamp, text):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM actions WHERE timestamp = ? AND text = ?', (timestamp, text))
            return cursor.fetchone() is not None
    
    def save_action(self, action):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO actions 
                (timestamp, text, from_player, from_id, to_player, to_id, quantity, item, action_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                action['timestamp'], action['text'], action.get('from_player'), action.get('from_id'),
                action.get('to_player'), action.get('to_id'), action.get('quantity'),
                action.get('item'), action.get('action_type')
            ))
    
    def save_login(self, player_id, player_name, login_time):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO player_sessions (player_id, player_name, login_time)
                VALUES (?, ?, ?)
            ''', (player_id, player_name, login_time))
    
    def save_logout(self, player_id, logout_time):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE player_sessions 
                SET logout_time = ?
                WHERE player_id = ? AND logout_time IS NULL
                ORDER BY login_time DESC
                LIMIT 1
            ''', (logout_time, player_id))
    
    def update_online_players(self, players):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM online_players')
            for player in players:
                cursor.execute('''
                    INSERT INTO online_players (player_id, player_name, last_seen)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (player['player_id'], player['player_name']))
    
    def get_current_online_players(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT player_id, player_name FROM online_players ORDER BY player_name')
            return [dict(row) for row in cursor.fetchall()]
    
    def save_player_profile(self, profile_data):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            player_id = profile_data['player_id']
            new_rank = profile_data.get('faction_rank')
            new_faction = profile_data.get('faction')
            
            cursor.execute('SELECT faction, faction_rank FROM player_profiles WHERE player_id = ?', (player_id,))
            old_profile = cursor.fetchone()
            
            if old_profile:
                old_faction = old_profile['faction']
                old_rank = old_profile['faction_rank']
                
                if old_rank != new_rank or old_faction != new_faction:
                    current_time = datetime.now()
                    
                    if old_rank and old_faction:
                        cursor.execute('''
                            UPDATE rank_history 
                            SET rank_lost = ?, is_current = 0
                            WHERE player_id = ? AND is_current = 1
                        ''', (current_time, player_id))
                        
                        cursor.execute('''
                            SELECT rank_obtained FROM rank_history 
                            WHERE player_id = ? AND rank_name = ? AND faction = ?
                            ORDER BY rank_obtained DESC LIMIT 1
                        ''', (player_id, old_rank, old_faction))
                        old_rank_data = cursor.fetchone()
                        
                        if old_rank_data:
                            duration = current_time - datetime.fromisoformat(old_rank_data['rank_obtained'])
                            print(f"📊 Rank change for {profile_data['player_name']}: {old_rank} → {new_rank or 'None'} (held {duration.days}d)")
                    
                    if new_rank and new_faction and new_faction != 'Civil':
                        cursor.execute('''
                            INSERT INTO rank_history 
                            (player_id, player_name, faction, rank_name, rank_obtained, is_current)
                            VALUES (?, ?, ?, ?, ?, 1)
                        ''', (player_id, profile_data['player_name'], new_faction, new_rank, current_time))
                        print(f"🎖️ New rank for {profile_data['player_name']}: {new_rank} in {new_faction}")
            else:
                if new_rank and new_faction and new_faction != 'Civil':
                    cursor.execute('''
                        INSERT INTO rank_history 
                        (player_id, player_name, faction, rank_name, rank_obtained, is_current)
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 1)
                    ''', (player_id, profile_data['player_name'], new_faction, new_rank))
            
            cursor.execute('''
                INSERT OR REPLACE INTO player_profiles 
                (player_id, player_name, last_connection, is_online, faction, faction_rank, warns, job, 
                 played_hours, age_ic, last_checked, check_priority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 
                    COALESCE((SELECT check_priority FROM player_profiles WHERE player_id = ?), 1))
            ''', (
                player_id, profile_data['player_name'], profile_data.get('last_connection'),
                profile_data.get('is_online', False), new_faction, new_rank, profile_data.get('warns', 0),
                profile_data.get('job'), profile_data.get('played_hours', 0),
                profile_data.get('age_ic'), player_id
            ))
    
    def mark_player_for_update(self, player_id, player_name=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO player_profiles (player_id, player_name, check_priority)
                VALUES (?, ?, 10)
            ''', (player_id, player_name or f'Player_{player_id}'))
            
            cursor.execute('''
                UPDATE player_profiles 
                SET check_priority = check_priority + 5
                WHERE player_id = ?
            ''', (player_id,))
    
    def get_players_pending_update(self, limit=100):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT player_id FROM player_profiles 
                WHERE check_priority > 5
                ORDER BY check_priority DESC, last_checked ASC
                LIMIT ?
            ''', (limit,))
            return [row['player_id'] for row in cursor.fetchall()]
    
    def reset_player_priority(self, player_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE player_profiles SET check_priority = 1 WHERE player_id = ?', (player_id,))
    
    # ============================================================================
    # NEW: UNIFIED QUERIES THAT SUPPORT BOTH ID AND NAME
    # ============================================================================
    
    def get_player_actions(self, identifier, days=7):
        """Get player actions by ID or name"""
        cutoff = datetime.now() - timedelta(days=days)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if identifier is numeric (ID) or string (name)
            if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
                player_id = int(identifier)
                cursor.execute('''
                    SELECT * FROM actions 
                    WHERE (from_id = ? OR to_id = ?) AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (player_id, player_id, cutoff))
            else:
                cursor.execute('''
                    SELECT * FROM actions 
                    WHERE (from_player LIKE ? OR to_player LIKE ?) AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (f'%{identifier}%', f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_player_gave(self, identifier, days=7):
        """Get what a player gave to others by ID or name"""
        cutoff = datetime.now() - timedelta(days=days)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
                player_id = int(identifier)
                cursor.execute('''
                    SELECT * FROM actions 
                    WHERE from_id = ? AND action_type = 'gave' AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (player_id, cutoff))
            else:
                cursor.execute('''
                    SELECT * FROM actions 
                    WHERE from_player LIKE ? AND action_type = 'gave' AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_player_received(self, identifier, days=7):
        """Get what a player received from others by ID or name"""
        cutoff = datetime.now() - timedelta(days=days)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
                player_id = int(identifier)
                cursor.execute('''
                    SELECT * FROM actions 
                    WHERE to_id = ? AND action_type = 'gave' AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (player_id, cutoff))
            else:
                cursor.execute('''
                    SELECT * FROM actions 
                    WHERE to_player LIKE ? AND action_type = 'gave' AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_player_sessions(self, identifier, days=7):
        """Get player sessions by ID or name"""
        cutoff = datetime.now() - timedelta(days=days)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
                player_id = int(identifier)
                cursor.execute('''
                    SELECT * FROM player_sessions 
                    WHERE player_id = ? AND login_time >= ?
                    ORDER BY login_time DESC
                ''', (player_id, cutoff))
            else:
                cursor.execute('''
                    SELECT * FROM player_sessions 
                    WHERE player_name LIKE ? AND login_time >= ?
                    ORDER BY login_time DESC
                ''', (f'%{identifier}%', cutoff))
            
            sessions = []
            for row in cursor.fetchall():
                session = dict(row)
                if session['logout_time']:
                    login = datetime.fromisoformat(session['login_time'])
                    logout = datetime.fromisoformat(session['logout_time'])
                    session['duration'] = logout - login
                else:
                    session['duration'] = 'Online now'
                sessions.append(session)
            
            return sessions
    
    def get_all_player_interactions(self, identifier, days=7):
        """Get ALL players that this player interacted with (gave to or received from)"""
        cutoff = datetime.now() - timedelta(days=days)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
                player_id = int(identifier)
                cursor.execute('''
                    SELECT 
                        CASE 
                            WHEN from_id = ? THEN to_player 
                            ELSE from_player 
                        END as other_player,
                        CASE 
                            WHEN from_id = ? THEN to_id 
                            ELSE from_id 
                        END as other_player_id,
                        COUNT(*) as interaction_count,
                        SUM(CASE WHEN from_id = ? THEN 1 ELSE 0 END) as gave_count,
                        SUM(CASE WHEN to_id = ? THEN 1 ELSE 0 END) as received_count
                    FROM actions 
                    WHERE (from_id = ? OR to_id = ?) 
                        AND action_type = 'gave' 
                        AND timestamp >= ?
                    GROUP BY other_player, other_player_id
                    ORDER BY interaction_count DESC
                ''', (player_id, player_id, player_id, player_id, player_id, player_id, cutoff))
            else:
                cursor.execute('''
                    SELECT 
                        CASE 
                            WHEN from_player LIKE ? THEN to_player 
                            ELSE from_player 
                        END as other_player,
                        CASE 
                            WHEN from_player LIKE ? THEN to_id 
                            ELSE from_id 
                        END as other_player_id,
                        COUNT(*) as interaction_count,
                        SUM(CASE WHEN from_player LIKE ? THEN 1 ELSE 0 END) as gave_count,
                        SUM(CASE WHEN to_player LIKE ? THEN 1 ELSE 0 END) as received_count
                    FROM actions 
                    WHERE (from_player LIKE ? OR to_player LIKE ?) 
                        AND action_type = 'gave' 
                        AND timestamp >= ?
                    GROUP BY other_player, other_player_id
                    ORDER BY interaction_count DESC
                ''', (f'%{identifier}%', f'%{identifier}%', f'%{identifier}%', f'%{identifier}%', 
                      f'%{identifier}%', f'%{identifier}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_interactions_between(self, player1, player2, days=7):
        """Get interactions between two players (supports both ID and name)"""
        cutoff = datetime.now() - timedelta(days=days)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Determine if identifiers are IDs or names
            p1_is_id = isinstance(player1, int) or (isinstance(player1, str) and player1.isdigit())
            p2_is_id = isinstance(player2, int) or (isinstance(player2, str) and player2.isdigit())
            
            if p1_is_id and p2_is_id:
                player1_id = int(player1)
                player2_id = int(player2)
                cursor.execute('''
                    SELECT * FROM actions 
                    WHERE action_type = 'gave'
                    AND ((from_id = ? AND to_id = ?)
                         OR (from_id = ? AND to_id = ?))
                    AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (player1_id, player2_id, player2_id, player1_id, cutoff))
            else:
                cursor.execute('''
                    SELECT * FROM actions 
                    WHERE action_type = 'gave'
                    AND ((from_player LIKE ? AND to_player LIKE ?)
                         OR (from_player LIKE ? AND to_player LIKE ?))
                    AND timestamp >= ?
                    ORDER BY timestamp DESC
                ''', (f'%{player1}%', f'%{player2}%', f'%{player2}%', f'%{player1}%', cutoff))
            
            return [dict(row) for row in cursor.fetchall()]
    
    # ============================================================================
    # EXISTING METHODS (unchanged)
    # ============================================================================
    
    def get_player_last_connection(self, player_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM player_profiles WHERE player_id = ?', (player_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def search_player_by_name(self, name):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM player_profiles 
                WHERE player_name LIKE ? 
                ORDER BY last_connection DESC
                LIMIT 50
            ''', (f'%{name}%',))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_players_by_faction(self, faction_name):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM player_profiles 
                WHERE faction LIKE ?
                ORDER BY last_connection DESC
            ''', (f'%{faction_name}%',))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_players_with_warns(self, min_warns=1):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM player_profiles 
                WHERE warns >= ?
                ORDER BY warns DESC, last_connection DESC
                LIMIT 100
            ''', (min_warns,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_player_rank_history(self, player_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM rank_history 
                WHERE player_id = ?
                ORDER BY rank_obtained DESC
            ''', (player_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_current_faction_ranks(self, faction_name):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.player_id, p.player_name, p.faction_rank, p.is_online,
                       r.rank_obtained,
                       julianday('now') - julianday(r.rank_obtained) as days_in_rank
                FROM player_profiles p
                LEFT JOIN rank_history r ON p.player_id = r.player_id AND r.is_current = 1
                WHERE p.faction LIKE ? AND p.faction_rank IS NOT NULL
                ORDER BY p.faction_rank, days_in_rank DESC
            ''', (f'%{faction_name}%',))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_players_by_rank(self, rank_name):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.*, 
                       r.rank_obtained,
                       julianday('now') - julianday(r.rank_obtained) as days_in_rank
                FROM player_profiles p
                JOIN rank_history r ON p.player_id = r.player_id AND r.is_current = 1
                WHERE p.faction_rank LIKE ?
                ORDER BY days_in_rank DESC
            ''', (f'%{rank_name}%',))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_recent_promotions(self, days=7):
        cutoff = datetime.now() - timedelta(days=days)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM rank_history 
                WHERE rank_obtained >= ?
                ORDER BY rank_obtained DESC
                LIMIT 50
            ''', (cutoff,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_scan_progress(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM player_profiles')
            count = cursor.fetchone()['count']
            return {
                'total_scanned': count,
                'total_target': 223797,
                'percentage': (count / 223797) * 100
            }
    
    def is_initial_scan_complete(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM system_status WHERE key = "initial_scan_complete"')
            row = cursor.fetchone()
            return row and row['value'] == 'true'
    
    def mark_scan_complete(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO system_status (key, value, updated_at)
                VALUES ('initial_scan_complete', 'true', CURRENT_TIMESTAMP)
            ''')
    
    def cleanup_old_data(self, days=30):
        cutoff = datetime.now() - timedelta(days=days)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM actions WHERE timestamp < ?', (cutoff,))
            actions_deleted = cursor.rowcount
            
            cursor.execute('DELETE FROM player_sessions WHERE login_time < ?', (cutoff,))
            sessions_deleted = cursor.rowcount
            
            cursor.execute('DELETE FROM rank_history WHERE rank_obtained < ? AND is_current = 0', (cutoff,))
            ranks_deleted = cursor.rowcount
            
            return actions_deleted + sessions_deleted + ranks_deleted

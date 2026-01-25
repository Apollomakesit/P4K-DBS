#!/usr/bin/env python3
"""Remove UNIQUE constraint on username"""
import sqlite3
import os

db_path = '/data/pro4kings.db' if os.path.exists('/data') else 'pro4kings.db'
print(f"Migrating database: {db_path}")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Create new table without UNIQUE constraint on username
cursor.execute('''
    CREATE TABLE IF NOT EXISTS player_profiles_new (
        player_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        is_online BOOLEAN DEFAULT FALSE,
        last_seen TIMESTAMP,
        first_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        faction TEXT,
        faction_rank TEXT,
        job TEXT,
        warnings INTEGER,
        played_hours REAL,
        age_ic INTEGER,
        total_actions INTEGER DEFAULT 0,
        last_profile_update TIMESTAMP,
        priority_update BOOLEAN DEFAULT FALSE
    )
''')

# Copy data
cursor.execute('''
    INSERT OR IGNORE INTO player_profiles_new 
    SELECT * FROM player_profiles
''')

# Drop old table and rename new one
cursor.execute('DROP TABLE player_profiles')
cursor.execute('ALTER TABLE player_profiles_new RENAME TO player_profiles')

# Recreate indexes
cursor.execute('CREATE INDEX IF NOT EXISTS idx_players_online ON player_profiles(is_online)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_players_faction ON player_profiles(faction)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_players_priority ON player_profiles(priority_update)')

conn.commit()
conn.close()

print("✅ Migration complete! UNIQUE constraint on username removed.")

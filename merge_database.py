#!/usr/bin/env python3
"""
Comprehensive database merger - FIXED VERSION (no database locking)
Reads from backup separately instead of using ATTACH DATABASE
"""
import sqlite3
import os
import sys
from datetime import datetime
import time

def merge_all_databases(volume_db_path='/data/pro4kings.db', 
                        backup_db_path='/app/backup_extracted/pro4kings.db'):
    """Merge all data sources into player_profiles table"""
    
    if not os.path.exists(volume_db_path):
        print(f"❌ Database not found at {volume_db_path}")
        return False
    
    try:
        conn = sqlite3.connect(volume_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        print("="*60)
        print("🔄 COMPREHENSIVE DATABASE MERGE")
        print("="*60)
        
        # Step 1: Check current state
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"\n📋 Existing tables: {', '.join(tables)}")
        
        has_players = 'players' in tables
        has_player_profiles = 'player_profiles' in tables
        
        players_count = 0
        if has_players:
            cursor.execute("SELECT COUNT(*) FROM players")
            players_count = cursor.fetchone()[0]
            print(f"📊 'players' table: {players_count:,} records")
        
        profiles_count = 0
        if has_player_profiles:
            cursor.execute("SELECT COUNT(*) FROM player_profiles")
            profiles_count = cursor.fetchone()[0]
            print(f"📊 'player_profiles' table: {profiles_count:,} records (BEFORE merge)")
        
        # Step 2: Create temporary table for merging
        print(f"\n🔄 Step 1: Creating temporary merge table...")
        cursor.execute("DROP TABLE IF EXISTS player_profiles_temp")
        
        # Create temp table with new schema
        cursor.execute('''
            CREATE TABLE player_profiles_temp (
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
        
        # Step 3: Import from backup database if it exists (SEPARATE CONNECTION)
        backup_imported = 0
        if os.path.exists(backup_db_path):
            print(f"\n🔄 Step 2: Importing from backup ({backup_db_path})...")
            
            # Open SEPARATE connection to backup (avoids locking issues)
            backup_conn = None
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    backup_conn = sqlite3.connect(backup_db_path, timeout=30.0)
                    backup_conn.row_factory = sqlite3.Row
                    backup_cursor = backup_conn.cursor()
                    break
                except sqlite3.OperationalError as e:
                    retry_count += 1
                    if retry_count < max_retries:
                        print(f"   ⚠️  Backup database busy, retrying in 2 seconds... (attempt {retry_count}/{max_retries})")
                        time.sleep(2)
                    else:
                        print(f"   ❌ Could not access backup database after {max_retries} attempts: {e}")
                        backup_conn = None
            
            if backup_conn:
                # Check if backup has player_profiles
                backup_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='player_profiles'")
                if backup_cursor.fetchone():
                    print("   📥 Reading records from backup...")
                    
                    # Read all records from backup
                    backup_cursor.execute('''
                        SELECT 
                            CAST(player_id AS TEXT) as player_id,
                            COALESCE(player_name, 'Player_' || player_id) as username,
                            COALESCE(is_online, 0) as is_online,
                            last_connection as last_seen,
                            CURRENT_TIMESTAMP as first_detected,
                            CASE WHEN faction IN ('Civil', 'Fără', 'None', '-', '', 'N/A') THEN NULL ELSE faction END as faction,
                            CASE WHEN faction_rank IN ('', '-', 'None', 'N/A') THEN NULL ELSE faction_rank END as faction_rank
                        FROM player_profiles
                    ''')
                    
                    backup_records = backup_cursor.fetchall()
                    print(f"   📥 Found {len(backup_records):,} records in backup")
                    
                    # Insert into temp table in batches
                    batch_size = 1000
                    for i in range(0, len(backup_records), batch_size):
                        batch = backup_records[i:i+batch_size]
                        cursor.executemany('''
                            INSERT OR REPLACE INTO player_profiles_temp (
                                player_id, username, is_online, last_seen, first_detected,
                                faction, faction_rank
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', [(r['player_id'], r['username'], r['is_online'], r['last_seen'],
                               r['first_detected'], r['faction'], r['faction_rank']) for r in batch])
                        
                        if (i + batch_size) % 10000 == 0:
                            print(f"   ⏳ Imported {i + batch_size:,} / {len(backup_records):,} records...")
                    
                    conn.commit()
                    backup_imported = len(backup_records)
                    print(f"   ✅ Imported {backup_imported:,} records from backup")
                
                backup_conn.close()
        else:
            print(f"\n⚠️  Backup database not found at {backup_db_path}")
        
        # Step 4: Merge from 'players' table if it exists
        players_merged = 0
        if has_players:
            print(f"\n🔄 Step 3: Merging from 'players' table...")
            cursor.execute('''
                INSERT OR REPLACE INTO player_profiles_temp (
                    player_id, username, is_online, last_seen, first_detected,
                    faction, faction_rank, job, warnings, played_hours, age_ic,
                    total_actions, last_profile_update, priority_update
                )
                SELECT 
                    player_id, username, is_online, last_seen, first_detected,
                    faction, faction_rank, job, warnings, played_hours, age_ic,
                    COALESCE(total_actions, 0), last_profile_update, COALESCE(priority_update, 0)
                FROM players
            ''')
            players_merged = cursor.rowcount
            print(f"   ✅ Merged {players_merged:,} records from 'players' table")
        
        # Step 5: Merge from existing 'player_profiles' table if it exists
        profiles_merged = 0
        if has_player_profiles:
            print(f"\n🔄 Step 4: Merging from 'player_profiles' table...")
            cursor.execute('''
                INSERT OR REPLACE INTO player_profiles_temp (
                    player_id, username, is_online, last_seen, first_detected,
                    faction, faction_rank, job, warnings, played_hours, age_ic,
                    total_actions, last_profile_update, priority_update
                )
                SELECT 
                    player_id, username, is_online, last_seen, first_detected,
                    faction, faction_rank, job, warnings, played_hours, age_ic,
                    COALESCE(total_actions, 0), last_profile_update, COALESCE(priority_update, 0)
                FROM player_profiles
            ''')
            profiles_merged = cursor.rowcount
            print(f"   ✅ Merged {profiles_merged:,} records from 'player_profiles' table")
        
        # Step 6: Replace old tables with merged data
        print(f"\n🔄 Step 5: Replacing tables with merged data...")
        
        if has_players:
            cursor.execute("DROP TABLE players")
            print("   ✅ Dropped legacy 'players' table")
        
        if has_player_profiles:
            cursor.execute("DROP TABLE player_profiles")
            print("   ✅ Dropped old 'player_profiles' table")
        
        cursor.execute("ALTER TABLE player_profiles_temp RENAME TO player_profiles")
        print("   ✅ Renamed temp table to 'player_profiles'")
        
        # Step 7: Recreate indexes
        print(f"\n🔄 Step 6: Recreating indexes...")
        indexes = [
            'CREATE INDEX IF NOT EXISTS idx_players_online ON player_profiles(is_online)',
            'CREATE INDEX IF NOT EXISTS idx_players_faction ON player_profiles(faction)',
            'CREATE INDEX IF NOT EXISTS idx_players_priority ON player_profiles(priority_update)',
        ]
        for index_sql in indexes:
            cursor.execute(index_sql)
        print("   ✅ Indexes created")
        
        # Commit the merge
        conn.commit()
        
        # Step 8: Verify final count
        cursor.execute("SELECT COUNT(*) FROM player_profiles")
        final_count = cursor.fetchone()[0]
        
        print(f"\n" + "="*60)
        print(f"✅ MERGE COMPLETE!")
        print(f"="*60)
        print(f"📊 Summary:")
        print(f"   Backup imported: {backup_imported:,}")
        print(f"   Players merged: {players_merged:,}")
        print(f"   Profiles merged: {profiles_merged:,}")
        print(f"   Final total: {final_count:,} records")
        print(f"="*60)
        
        conn.close()
        return final_count
        
    except Exception as e:
        print(f"❌ Merge failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    result = merge_all_databases()
    sys.exit(0 if result else 1)

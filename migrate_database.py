#!/usr/bin/env python3
"""
Database migration script to rename 'players' table to 'player_profiles'
Run this BEFORE starting the bot if you have an existing backup database
"""
import sqlite3
import sys
import os

def migrate_database(db_path):
    """Migrate players table to player_profiles"""
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check existing tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        all_tables = [row[0] for row in cursor.fetchall()]
        print(f"📋 Existing tables: {', '.join(all_tables)}")
        
        # Check if 'players' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='players'")
        has_players = cursor.fetchone() is not None
        
        # Check if 'player_profiles' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='player_profiles'")
        has_player_profiles = cursor.fetchone() is not None
        
        # Get counts before migration
        players_count = 0
        if has_players:
            cursor.execute("SELECT COUNT(*) FROM players")
            players_count = cursor.fetchone()[0]
            print(f"📊 'players' table has {players_count:,} records")
        
        player_profiles_count = 0
        if has_player_profiles:
            cursor.execute("SELECT COUNT(*) FROM player_profiles")
            player_profiles_count = cursor.fetchone()[0]
            print(f"📊 'player_profiles' table has {player_profiles_count:,} records")
        
        if has_players and not has_player_profiles:
            print(f"🔄 Migrating 'players' table ({players_count:,} records) to 'player_profiles'...")
            
            # Rename the table
            cursor.execute("ALTER TABLE players RENAME TO player_profiles")
            
            # Update indexes
            print("🔄 Recreating indexes for player_profiles...")
            cursor.execute("DROP INDEX IF EXISTS idx_players_online")
            cursor.execute("DROP INDEX IF EXISTS idx_players_priority")
            cursor.execute("DROP INDEX IF EXISTS idx_players_faction")
            cursor.execute("DROP INDEX IF EXISTS idx_players_level")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_players_online ON player_profiles(is_online)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_players_priority ON player_profiles(priority_update)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_players_faction ON player_profiles(faction)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_players_level ON player_profiles(level)")
            
            conn.commit()
            
            # Verify migration
            cursor.execute("SELECT COUNT(*) FROM player_profiles")
            new_count = cursor.fetchone()[0]
            print(f"✅ Migration complete! 'player_profiles' now has {new_count:,} records")
            
            if new_count != players_count:
                print(f"⚠️ WARNING: Record count mismatch! Expected {players_count:,}, got {new_count:,}")
            
        elif has_player_profiles and not has_players:
            print(f"✅ Database already migrated (player_profiles has {player_profiles_count:,} records)")
            
        elif has_players and has_player_profiles:
            print(f"⚠️ WARNING: Both 'players' ({players_count:,}) and 'player_profiles' ({player_profiles_count:,}) tables exist!")
            print("   Manual intervention required to merge data.")
            return False
            
        else:
            print("ℹ️  No migration needed (fresh database)")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    db_path = os.getenv('DATABASE_PATH', '/data/pro4kings.db')
    
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    print(f"📁 Database path: {db_path}")
    
    success = migrate_database(db_path)
    sys.exit(0 if success else 1)

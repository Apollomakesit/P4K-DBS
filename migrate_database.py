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
        
        # Check if 'players' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='players'")
        has_players = cursor.fetchone() is not None
        
        # Check if 'player_profiles' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='player_profiles'")
        has_player_profiles = cursor.fetchone() is not None
        
        if has_players and not has_player_profiles:
            print("🔄 Migrating 'players' table to 'player_profiles'...")
            
            # Rename the table
            cursor.execute("ALTER TABLE players RENAME TO player_profiles")
            
            # Update indexes
            print("🔄 Recreating indexes for player_profiles...")
            cursor.execute("DROP INDEX IF EXISTS idx_players_online")
            cursor.execute("DROP INDEX IF EXISTS idx_players_priority")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_players_online ON player_profiles(is_online)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_players_priority ON player_profiles(priority_update)")
            
            conn.commit()
            print("✅ Migration complete! 'players' table renamed to 'player_profiles'")
            
        elif has_player_profiles and not has_players:
            print("✅ Database already migrated (player_profiles table exists)")
            
        elif has_players and has_player_profiles:
            print("⚠️  WARNING: Both 'players' and 'player_profiles' tables exist!")
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

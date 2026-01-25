#!/usr/bin/env python3
"""
Migration Script: Remove UNIQUE constraint on username field

This script fixes the database schema to allow multiple players with the same
username but different player IDs.

PROBLEM:
- Original schema had UNIQUE(username) constraint
- Multiple players can have the same name with different IDs
- This was causing "Username exists with different ID" warnings

SOLUTION:
- Recreate player_profiles table without UNIQUE constraint on username
- Keep player_id as PRIMARY KEY (which is the correct unique identifier)
- Preserve all existing data
"""

import sqlite3
import os
import logging
from datetime import datetime
import shutil

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def migrate_database():
    """
    Migrate database to remove UNIQUE constraint on username
    """
    
    # Determine database path (same logic as Database class)
    if os.path.exists('/data'):
        db_path = '/data/pro4kings.db'
        logger.info("📦 Using Railway volume: /data/pro4kings.db")
    else:
        db_path = 'pro4kings.db'
        logger.info("💾 Using local database: pro4kings.db")
    
    if not os.path.exists(db_path):
        logger.error(f"❌ Database not found at {db_path}")
        return
    
    logger.info(f"\n" + "="*60)
    logger.info(f"🔧 Database Migration: Fix Username Constraint")
    logger.info(f"="*60)
    logger.info(f"Database: {db_path}")
    logger.info(f"="*60 + "\n")
    
    # Create backup
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger.info(f"💾 Creating backup: {backup_path}")
    shutil.copy2(db_path, backup_path)
    logger.info(f"✅ Backup created successfully\n")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='player_profiles'
        """)
        if not cursor.fetchone():
            logger.error("❌ player_profiles table not found!")
            conn.close()
            return
        
        # Get current row count
        cursor.execute("SELECT COUNT(*) FROM player_profiles")
        original_count = cursor.fetchone()[0]
        logger.info(f"📊 Original table has {original_count:,} rows\n")
        
        # Check for duplicate usernames
        cursor.execute("""
            SELECT username, COUNT(*) as count 
            FROM player_profiles 
            GROUP BY username 
            HAVING count > 1
            ORDER BY count DESC
            LIMIT 10
        """)
        duplicates = cursor.fetchall()
        if duplicates:
            logger.info("🔍 Found players with duplicate usernames:")
            for username, count in duplicates:
                logger.info(f"   '{username}': {count} players")
            logger.info(f"   ... (showing top 10)\n")
        else:
            logger.info("ℹ️ No duplicate usernames found (but fixing schema anyway)\n")
        
        logger.info("🔨 Creating new table without UNIQUE constraint...")
        
        # Create new table without UNIQUE constraint on username
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS player_profiles_new (
                player_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                is_online BOOLEAN DEFAULT FALSE,
                last_seen TIMESTAMP,
                first_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                -- Profile fields
                faction TEXT,
                faction_rank TEXT,
                job TEXT,
                warnings INTEGER,
                played_hours REAL,
                age_ic INTEGER,
                
                -- Metadata
                total_actions INTEGER DEFAULT 0,
                last_profile_update TIMESTAMP,
                priority_update BOOLEAN DEFAULT FALSE
            )
        ''')
        logger.info("✅ New table created\n")
        
        logger.info("🔄 Copying data from old table to new table...")
        # Copy all data from old table to new table
        cursor.execute('''
            INSERT INTO player_profiles_new
            SELECT * FROM player_profiles
        ''')
        rows_copied = cursor.rowcount
        logger.info(f"✅ Copied {rows_copied:,} rows\n")
        
        if rows_copied != original_count:
            logger.error(f"⚠️ WARNING: Row count mismatch! Original: {original_count:,}, Copied: {rows_copied:,}")
            logger.error("Migration aborted - check for errors")
            conn.rollback()
            conn.close()
            return
        
        logger.info("🗑️ Dropping old table...")
        # Drop old table
        cursor.execute('DROP TABLE player_profiles')
        logger.info("✅ Old table dropped\n")
        
        logger.info("♻️ Renaming new table...")
        # Rename new table
        cursor.execute('ALTER TABLE player_profiles_new RENAME TO player_profiles')
        logger.info("✅ Table renamed\n")
        
        logger.info("📚 Recreating indexes...")
        # Recreate indexes
        indexes = [
            'CREATE INDEX IF NOT EXISTS idx_players_online ON player_profiles(is_online)',
            'CREATE INDEX IF NOT EXISTS idx_players_faction ON player_profiles(faction)',
            'CREATE INDEX IF NOT EXISTS idx_players_priority ON player_profiles(priority_update)',
        ]
        
        for index_sql in indexes:
            cursor.execute(index_sql)
        logger.info(f"✅ Created {len(indexes)} indexes\n")
        
        # Verify final count
        cursor.execute("SELECT COUNT(*) FROM player_profiles")
        final_count = cursor.fetchone()[0]
        logger.info(f"📊 Final table has {final_count:,} rows\n")
        
        if final_count != original_count:
            logger.error(f"❌ ERROR: Row count mismatch! Original: {original_count:,}, Final: {final_count:,}")
            logger.error("Rolling back migration...")
            conn.rollback()
            conn.close()
            return
        
        # Commit all changes
        conn.commit()
        
        logger.info("="*60)
        logger.info("✅ MIGRATION COMPLETE!")
        logger.info("="*60)
        logger.info(f"\nChanges made:")
        logger.info("  ✓ Removed UNIQUE constraint on username field")
        logger.info("  ✓ All data preserved ({:,} rows)".format(final_count))
        logger.info("  ✓ Indexes recreated")
        logger.info(f"  ✓ Backup saved to: {backup_path}")
        logger.info("\nℹ️ Multiple players can now have the same username with different player_ids")
        logger.info("="*60 + "\n")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"\n❌ Migration failed: {e}", exc_info=True)
        logger.error(f"\n🔙 Restore from backup if needed: {backup_path}")

if __name__ == "__main__":
    migrate_database()

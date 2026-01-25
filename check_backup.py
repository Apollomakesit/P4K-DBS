#!/usr/bin/env python3
"""Check what's in the backup database"""
import sqlite3
import sys
import os

def check_database(db_path):
    print(f"📁 Checking database: {db_path}")
    print("="*60)
    
    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"📋 Tables found: {len(tables)}")
        for table in tables:
            print(f"   - {table}")
        
        print("\n" + "="*60)
        
        # Check both 'players' and 'player_profiles'
        for table_name in ['players', 'player_profiles']:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                print(f"✅ '{table_name}' has {count:,} records")
                
                # Show a sample row
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 1")
                sample = cursor.fetchone()
                if sample:
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = [col[1] for col in cursor.fetchall()]
                    print(f"   Sample record: {dict(zip(columns[:5], sample[:5]))}")
            except sqlite3.OperationalError:
                print(f"❌ '{table_name}' table does NOT exist")
        
        print("="*60)
        
        # Check actions table
        try:
            cursor.execute("SELECT COUNT(*) FROM actions")
            actions_count = cursor.fetchone()[0]
            print(f"📝 'actions' table has {actions_count:,} records")
        except:
            print("❌ 'actions' table does NOT exist")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    # Check the backup in the image
    print("\n🔍 CHECKING BACKUP IN IMAGE")
    check_database('/app/backup_extracted/pro4kings.db')
    
    print("\n\n🔍 CHECKING DATABASE IN VOLUME")
    check_database('/data/pro4kings.db')

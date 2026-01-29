#!/usr/bin/env python3
"""
Database Migration Script - Downloads backup from GitHub and migrates
"""
import sqlite3
import shutil
import os
import gzip
import urllib.request
from datetime import datetime

# GitHub raw file URL for your backup
GITHUB_BACKUP_URL = "https://github.com/Apollomakesit/P4K-DBS/raw/main/backup.db.gz"
TEMP_BACKUP_GZ = '/data/temp_backup_download.db.gz'      # Changed from /tmp
TEMP_BACKUP_DB = '/data/temp_backup_extracted.db'        # Changed from /tmp
CURRENT_DB = '/data/pro4kings.db'

def download_backup():
    """Download backup from GitHub"""
    print("\n📥 Downloading backup from GitHub...")
    print(f"   URL: {GITHUB_BACKUP_URL}")
    print(f"   Saving to: {TEMP_BACKUP_GZ}")
    
    try:
        # Ensure /data directory exists and is writable
        if not os.path.exists('/data'):
            os.makedirs('/data')
        
        urllib.request.urlretrieve(GITHUB_BACKUP_URL, TEMP_BACKUP_GZ)
        
        if not os.path.exists(TEMP_BACKUP_GZ):
            print(f"❌ File was not created at {TEMP_BACKUP_GZ}")
            return False
        
        size_mb = os.path.getsize(TEMP_BACKUP_GZ) / (1024 * 1024)
        print(f"✅ Downloaded {size_mb:.2f} MB")
        return True
    except Exception as e:
        print(f"❌ Download failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def extract_backup():
    """Extract gzipped backup"""
    print("\n📦 Extracting backup.db.gz...")
    
    try:
        if not os.path.exists(TEMP_BACKUP_GZ):
            print(f"❌ Compressed file not found: {TEMP_BACKUP_GZ}")
            return False
        
        with gzip.open(TEMP_BACKUP_GZ, 'rb') as f_in:
            with open(TEMP_BACKUP_DB, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        if not os.path.exists(TEMP_BACKUP_DB):
            print(f"❌ Extracted file was not created: {TEMP_BACKUP_DB}")
            return False
        
        size_mb = os.path.getsize(TEMP_BACKUP_DB) / (1024 * 1024)
        print(f"✅ Extracted {size_mb:.2f} MB")
        return True
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_schema(db_path):
    """Check database schema"""
    try:
        if not os.path.exists(db_path):
            return None, f"File not found: {db_path}"
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='player_profiles'")
        if not cursor.fetchone():
            conn.close()
            return None, "No player_profiles table"
        
        cursor.execute("PRAGMA table_info(player_profiles)")
        columns = [row[1] for row in cursor.fetchall()]
        
        cursor.execute("SELECT COUNT(*) FROM player_profiles")
        count = cursor.fetchone()[0]
        
        conn.close()
        
        # Check schema type
        has_old_schema = 'player_name' in columns and 'last_connection' in columns
        has_new_schema = 'username' in columns and 'last_seen' in columns
        
        if has_old_schema:
            return "OLD", f"OLD schema, {count:,} records"
        elif has_new_schema:
            return "NEW", f"NEW schema, {count:,} records"
        else:
            return "UNKNOWN", f"Unknown schema, {count:,} records"
    
    except Exception as e:
        return None, f"Error: {e}"

def migrate():
    """Main migration function"""
    print("=" * 80)
    print("🔄 DATABASE MIGRATION - GITHUB BACKUP")
    print("=" * 80)
    
    # Check if current database exists
    if not os.path.exists(CURRENT_DB):
        print(f"❌ Current database not found: {CURRENT_DB}")
        return False
    
    # Step 1: Download backup from GitHub
    if not download_backup():
        return False
    
    # Step 2: Extract backup
    if not extract_backup():
        print("\n🧹 Cleaning up downloaded file...")
        try:
            if os.path.exists(TEMP_BACKUP_GZ):
                os.remove(TEMP_BACKUP_GZ)
        except:
            pass
        return False
    
    # Step 3: Check schemas
    print("\n🔍 Checking database schemas...")
    
    old_schema, old_info = check_schema(TEMP_BACKUP_DB)
    print(f"   GitHub backup: {old_info}")
    
    if old_schema != "OLD":
        print("⚠️ GitHub backup doesn't have OLD schema - migration may not be needed!")
        if old_schema == "NEW":
            print("   This backup already uses the NEW schema.")
        cleanup_temp_files()
        return False
    
    current_schema, current_info = check_schema(CURRENT_DB)
    print(f"   Current database: {current_info}")
    
    if current_schema != "NEW":
        print("❌ Current database doesn't have NEW schema!")
        print("   This script expects your current database to use the NEW schema.")
        cleanup_temp_files()
        return False
    
    # Step 4: Create safety backup
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safety_backup = f'/data/pre_migration_backup_{timestamp}.db'
    
    print(f"\n📦 Creating safety backup of current database...")
    shutil.copy2(CURRENT_DB, safety_backup)
    backup_size = os.path.getsize(safety_backup) / (1024 * 1024)
    print(f"✅ Safety backup: {safety_backup} ({backup_size:.2f} MB)")
    
    print(f"\n💡 If migration fails, restore with:")
    print(f"   cp {safety_backup} {CURRENT_DB}")
    
    # Step 5: Connect to databases
    print("\n🔄 Starting migration...")
    
    conn_old = sqlite3.connect(TEMP_BACKUP_DB)
    conn_new = sqlite3.connect(CURRENT_DB)
    
    cur_old = conn_old.cursor()
    cur_new = conn_new.cursor()
    
    # Step 6: Get record count
    cur_old.execute("SELECT COUNT(*) FROM player_profiles")
    total = cur_old.fetchone()[0]
    print(f"📊 Migrating {total:,} records from GitHub backup...")
    
    # Step 7: Fetch all data
    cur_old.execute("""
        SELECT 
            player_id, player_name, last_connection, is_online, faction,
            faction_rank, warns, job, played_hours, age_ic,
            last_checked, check_priority
        FROM player_profiles
    """)
    
    # Step 8: Migrate with progress
    migrated = 0
    updated = 0
    errors = 0
    error_details = []
    
    print("-" * 80)
    
    for row in cur_old.fetchall():
        try:
            (player_id, player_name, last_connection, is_online, faction,
             faction_rank, warns, job, played_hours, age_ic,
             last_checked, check_priority) = row
            
            # Check if exists
            cur_new.execute("SELECT player_id FROM player_profiles WHERE player_id = ?", (player_id,))
            exists = cur_new.fetchone()
            
            # Insert or update
            cur_new.execute("""
                INSERT INTO player_profiles (
                    player_id, username, is_online, last_seen, first_detected,
                    faction, faction_rank, job, warnings, played_hours, age_ic,
                    total_actions, last_profile_update, priority_update
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET
                    username = excluded.username,
                    is_online = excluded.is_online,
                    last_seen = excluded.last_seen,
                    faction = excluded.faction,
                    faction_rank = excluded.faction_rank,
                    job = excluded.job,
                    warnings = excluded.warnings,
                    played_hours = excluded.played_hours,
                    age_ic = excluded.age_ic,
                    last_profile_update = excluded.last_profile_update,
                    priority_update = excluded.priority_update
            """, (
                player_id,           # player_id → player_id
                player_name,         # player_name → username
                is_online,           # is_online → is_online
                last_connection,     # last_connection → last_seen
                last_connection,     # last_connection → first_detected
                faction,             # faction → faction
                faction_rank,        # faction_rank → faction_rank
                job,                 # job → job
                warns,               # warns → warnings
                played_hours,        # played_hours → played_hours
                age_ic,              # age_ic → age_ic
                0,                   # total_actions (new column)
                last_checked,        # last_checked → last_profile_update
                check_priority       # check_priority → priority_update
            ))
            
            if exists:
                updated += 1
            else:
                migrated += 1
            
            # Progress update every 5000 records
            if (migrated + updated) % 5000 == 0:
                conn_new.commit()
                progress = (migrated + updated) * 100 // total
                print(f"  ⏳ {migrated + updated:,}/{total:,} ({progress}%) | New: {migrated:,} | Updated: {updated:,}")
        
        except Exception as e:
            errors += 1
            if errors <= 10:  # Store first 10 errors
                error_details.append(f"Player {player_id}: {str(e)[:100]}")
    
    # Final commit
    conn_new.commit()
    
    # Step 9: Verify
    cur_new.execute("SELECT COUNT(*) FROM player_profiles")
    final_count = cur_new.fetchone()[0]
    
    conn_old.close()
    conn_new.close()
    
    # Step 10: Cleanup temp files
    cleanup_temp_files()
    
    # Step 11: Results
    print("\n" + "=" * 80)
    print("✅ MIGRATION COMPLETE")
    print("=" * 80)
    print(f"📊 Results:")
    print(f"   Records from GitHub backup: {total:,}")
    print(f"   Final database count: {final_count:,}")
    print(f"   New records inserted: {migrated:,}")
    print(f"   Existing records updated: {updated:,}")
    print(f"   Errors: {errors}")
    
    if error_details:
        print(f"\n⚠️ First {len(error_details)} errors:")
        for err in error_details:
            print(f"   • {err}")
    
    print(f"\n📦 Safety backup location:")
    print(f"   {safety_backup}")
    
    if errors == 0:
        print(f"\n🎉 Perfect migration! All {total:,} records processed successfully!")
        print(f"\n💡 To save space, delete the safety backup:")
        print(f"   rm {safety_backup}")
    else:
        print(f"\n⚠️ Completed with {errors} errors - review before deleting backup")
    
    return True

def cleanup_temp_files():
    """Remove temporary files"""
    print("\n🧹 Cleaning up temporary files...")
    removed = 0
    for temp_file in [TEMP_BACKUP_GZ, TEMP_BACKUP_DB]:
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                print(f"   ✓ Removed {os.path.basename(temp_file)}")
                removed += 1
        except Exception as e:
            print(f"   ⚠️ Could not remove {os.path.basename(temp_file)}: {e}")
    
    if removed > 0:
        print(f"✅ Cleaned up {removed} temporary file(s)")

if __name__ == "__main__":
    try:
        print("\n⚠️  This will download backup from GitHub and migrate your database!")
        print(f"   GitHub: {GITHUB_BACKUP_URL}")
        print(f"   Target: {CURRENT_DB}")
        print()
        
        success = migrate()
        
        if not success:
            print("\n❌ Migration was not completed")
            exit(1)
        
        print("\n✅ Migration finished successfully!")
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Migration interrupted by user")
        cleanup_temp_files()
        exit(1)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        cleanup_temp_files()
        exit(1)

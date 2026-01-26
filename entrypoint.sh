#!/bin/bash

set -e

echo "🚀 Starting P4K Database Bot..."
echo "================================================"

# Create data directory if it doesn't exist
mkdir -p /data
mkdir -p /app/backup_extracted

# 🔍 CHECK BACKUP CONTENTS FIRST
if [ -f "/app/backup_extracted/pro4kings.db" ]; then
    echo "🔍 Checking backup database contents..."
    python /app/check_backup.py 2>/dev/null || echo "   (check_backup.py not available)"
fi

echo "================================================"
echo "📂 Checking for existing database..."

# Check if database exists in volume
if [ -f "/data/pro4kings.db" ]; then
    DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
    TABLE_COUNT=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "0")
    echo "✅ Database found in volume: /data/pro4kings.db ($DB_SIZE)"
    echo "   Total tables: $TABLE_COUNT"
else
    echo "⚠️  Database not found in volume"
    
    # Priority 1: Check if we have the extracted backup (from Docker build)
    if [ -f "/app/backup_extracted/pro4kings.db" ]; then
        echo "📦 Copying database from image to volume..."
        cp /app/backup_extracted/pro4kings.db /data/pro4kings.db
        DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
        echo "✅ Database copied to volume: /data/pro4kings.db ($DB_SIZE)"
    
    # Priority 2: Check if we need to extract backup.db.gz (Railway deployment)
    elif [ -f "/app/backup.db.gz" ]; then
        echo "📦 Extracting backup.db.gz..."
        gunzip -c /app/backup.db.gz > /data/pro4kings.db
        DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
        echo "✅ Database extracted to volume: /data/pro4kings.db ($DB_SIZE)"
    
    # Priority 3: Create fresh database (CSV import will populate it)
    else
        echo "⚠️  No backup found - will create fresh database"
        if [ -f "/app/player_profiles.csv" ]; then
            echo "📊 CSV file available for import"
        else
            echo "⚠️  No CSV file found - bot will start with empty database"
        fi
    fi
fi

# 🔥 COMPREHENSIVE DATABASE MERGE & MIGRATION
if [ -f "/data/pro4kings.db" ]; then
    echo "================================================"
    echo "🔍 Database analysis..."
    
    # Check for both old and new table schemas
    PLAYERS_COUNT=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM players;" 2>/dev/null || echo "0")
    PROFILES_COUNT=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM player_profiles;" 2>/dev/null || echo "0")
    ACTIONS_COUNT=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM actions;" 2>/dev/null || echo "0")
    
    echo "   'players' table: $PLAYERS_COUNT records (legacy schema)"
    echo "   'player_profiles' table: $PROFILES_COUNT records (current schema)"
    echo "   'actions' table: $ACTIONS_COUNT records"
    
    # Determine if we need to run merge
    NEEDS_MERGE=0
    
    # Case 1: Both tables exist (need merge)
    if [ "$PLAYERS_COUNT" -gt "0" ] && [ "$PROFILES_COUNT" -gt "0" ]; then
        echo "   ⚠️  Both schemas detected - merge required"
        NEEDS_MERGE=1
    
    # Case 2: Only legacy 'players' table exists (need migration)
    elif [ "$PLAYERS_COUNT" -gt "0" ] && [ "$PROFILES_COUNT" -eq "0" ]; then
        echo "   ⚠️  Legacy schema detected - migration required"
        NEEDS_MERGE=1
    
    # Case 3: We have backup with more data than current database
    elif [ -f "/app/backup_extracted/pro4kings.db" ]; then
        BACKUP_COUNT=$(sqlite3 /app/backup_extracted/pro4kings.db "SELECT COUNT(*) FROM player_profiles;" 2>/dev/null || echo "0")
        if [ "$BACKUP_COUNT" -gt "$PROFILES_COUNT" ]; then
            echo "   📦 Backup has more data ($BACKUP_COUNT vs $PROFILES_COUNT) - merge required"
            NEEDS_MERGE=1
        fi
    fi
    
    # Run merge if needed
    if [ "$NEEDS_MERGE" -eq "1" ]; then
        echo "================================================"
        echo "🔄 Running comprehensive database merge..."
        echo "   This will combine:"
        echo "   - Backup database (if available)"
        echo "   - Legacy 'players' table (if exists)"
        echo "   - Current 'player_profiles' table (if exists)"
        
        if [ -f "/app/merge_database.py" ]; then
            python /app/merge_database.py
            
            if [ $? -ne 0 ]; then
                echo "❌ Database merge failed! Trying fallback migration..."
                python /app/migrate_database.py /data/pro4kings.db
                
                if [ $? -ne 0 ]; then
                    echo "❌ Migration also failed! Check logs above."
                    exit 1
                fi
            fi
        else
            echo "⚠️  merge_database.py not found, using legacy migration..."
            python /app/migrate_database.py /data/pro4kings.db
            
            if [ $? -ne 0 ]; then
                echo "❌ Migration failed! Check logs above."
                exit 1
            fi
        fi
        
        # Verify merge/migration worked
        echo "================================================"
        echo "🔍 Post-merge verification..."
        FINAL_PROFILES=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM player_profiles;" 2>/dev/null || echo "0")
        REMAINING_PLAYERS=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM players;" 2>/dev/null || echo "0")
        
        echo "   'player_profiles' table: $FINAL_PROFILES records"
        echo "   'players' table: $REMAINING_PLAYERS records"
        
        if [ "$FINAL_PROFILES" -eq "0" ] && [ "$PLAYERS_COUNT" -gt "0" ]; then
            echo "❌ ERROR: Merge failed! No records in player_profiles"
            exit 1
        fi
        
        if [ "$REMAINING_PLAYERS" -gt "0" ]; then
            echo "   ℹ️  Legacy 'players' table still exists (will be cleaned up on next restart)"
        fi
        
        echo "✅ Merge successful! Database has $FINAL_PROFILES player profiles"
    else
        echo "   ✅ Database schema is current - no migration needed"
    fi
fi

# 🆕 CSV IMPORT (runs after merge to update with latest data)
if [ -f "/data/pro4kings.db" ] && [ -f "/app/player_profiles.csv" ]; then
    CURRENT_PROFILES=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM player_profiles;" 2>/dev/null || echo "0")
    
    echo "================================================"
    echo "📊 CSV Import Check..."
    echo "   Current database: $CURRENT_PROFILES records"
    echo "   CSV file: /app/player_profiles.csv"
    
    # Always run CSV import to update with latest data (it uses INSERT OR REPLACE)
    if [ -f "/app/import_csv_profiles.py" ]; then
        echo "🔄 Running CSV import (updates existing records with latest data)..."
        python /app/import_csv_profiles.py /app/player_profiles.csv
        
        if [ $? -eq 0 ]; then
            NEW_PROFILES=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM player_profiles;" 2>/dev/null || echo "0")
            echo "✅ CSV import complete! Database now has $NEW_PROFILES records"
        else
            echo "⚠️  CSV import failed - continuing with existing data"
        fi
    else
        echo "⚠️  import_csv_profiles.py not found - skipping CSV import"
    fi
fi

# 📊 Final database statistics
echo "================================================"
echo "📊 Final Database Status:"

if [ -f "/data/pro4kings.db" ]; then
    DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
    FINAL_PROFILES=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM player_profiles;" 2>/dev/null || echo "0")
    FINAL_ACTIONS=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM actions;" 2>/dev/null || echo "0")
    ONLINE_COUNT=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM player_profiles WHERE is_online = 1;" 2>/dev/null || echo "0")
    
    echo "   📁 Size: $DB_SIZE"
    echo "   📍 Path: /data/pro4kings.db"
    echo "   👥 Player Profiles: $FINAL_PROFILES"
    echo "   📝 Actions Logged: $FINAL_ACTIONS"
    echo "   🟢 Currently Online: $ONLINE_COUNT"
    
    if [ "$FINAL_PROFILES" -eq "0" ]; then
        echo "   ⚠️  WARNING: Database is empty! Bot will start with no player data"
    elif [ "$FINAL_PROFILES" -lt "1000" ]; then
        echo "   ⚠️  WARNING: Low player count ($FINAL_PROFILES) - expected 100K+"
    else
        echo "   ✅ Database ready for production!"
    fi
else
    echo "   ❌ Database file not found!"
    exit 1
fi

echo "================================================"
echo "🤖 Starting Discord bot..."
echo "================================================"

# Start the bot (use exec to replace shell process)
exec python bot.py

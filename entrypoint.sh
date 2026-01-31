#!/bin/bash

# Use lenient error handling - don't exit on non-critical errors
set +e

echo "🚀 Starting P4K Database Bot..."
echo "================================================"

# Create data directory if it doesn't exist
mkdir -p /data
mkdir -p /app/backup_extracted

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
    
    # Run migration if needed via bot.py's built-in migrate_db module
    if [ "$NEEDS_MERGE" -eq "1" ]; then
        echo "================================================"
        echo "🔄 Migration will be handled by bot.py on startup..."
        echo "   The migrate_db.py module will automatically:"
        echo "   - Download backup from GitHub (if needed)"
        echo "   - Migrate legacy 'players' table to 'player_profiles'"
        echo "   - Create migration flag file"
        
    else
        echo "   ✅ Database schema is current - no migration needed"
    fi
fi

# ℹ️ CSV IMPORT NOTE:
# CSV import is handled by bot.py via db.auto_import_csv_if_needed().
# This prevents re-importing the same data on every deployment.
# The flag file (.csv_imported) is created in /data/ to persist across restarts.
echo "================================================"
echo "ℹ️  CSV import will be handled by bot.py on first run (if needed)"

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
        echo "   CSV import will attempt to populate database on startup"
    elif [ "$FINAL_PROFILES" -lt "1000" ]; then
        echo "   ⚠️  WARNING: Low player count ($FINAL_PROFILES) - expected 100K+"
    else
        echo "   ✅ Database ready for production!"
    fi
else
    echo "   ⚠️  WARNING: Database file not found at /data/pro4kings.db!"
    echo "   Bot will create a new database on startup"
fi

echo "================================================"
echo "🌐 Starting Web Dashboard (background)..."
echo "================================================"

# Start dashboard on PORT (Railway provides this) or default 8080
DASHBOARD_PORT=${PORT:-8080}
export DASHBOARD_PORT
export DASHBOARD_HOST="0.0.0.0"

# Start dashboard in background
cd /app/dashboard
python run.py &
DASHBOARD_PID=$!
cd /app

echo "   🌐 Dashboard started on port $DASHBOARD_PORT (PID: $DASHBOARD_PID)"
echo "   📊 Dashboard URL: https://your-app.railway.app/"

echo "================================================"
echo "🤖 Starting Discord bot..."
echo "================================================"

# Enable strict error handling ONLY for the bot startup
set -e

# Function to cleanup background processes on exit
cleanup() {
    echo "🛑 Stopping dashboard..."
    kill $DASHBOARD_PID 2>/dev/null || true
}
trap cleanup EXIT

# Execute the bot (keeps running in foreground)
exec python /app/bot.py

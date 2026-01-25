#!/bin/bash
set -e

echo "🚀 Starting P4K Database Bot..."
echo "================================================"

# Create data directory if it doesn't exist
mkdir -p /data
mkdir -p /app/backup_extracted

echo "📂 Checking for existing database..."
# Check if database exists in volume
if [ -f "/data/pro4kings.db" ]; then
    DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
    RECORD_COUNT=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND (name='players' OR name='player_profiles');" 2>/dev/null || echo "0")
    echo "✅ Database found in volume: /data/pro4kings.db ($DB_SIZE)"
    echo "   Tables found: $RECORD_COUNT"
else
    echo "⚠️  Database not found in volume"

    # Check if we have the extracted backup (from Docker build)
    if [ -f "/app/backup_extracted/pro4kings.db" ]; then
        echo "📦 Copying database from image to volume..."
        cp /app/backup_extracted/pro4kings.db /data/pro4kings.db
        DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
        echo "✅ Database copied to volume: /data/pro4kings.db ($DB_SIZE)"
    # Check if we need to extract backup.db.gz (Railway deployment)
    elif [ -f "/app/backup.db.gz" ]; then
        echo "📦 Extracting backup.db.gz..."
        gunzip -c /app/backup.db.gz > /data/pro4kings.db
        DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
        echo "✅ Database extracted to volume: /data/pro4kings.db ($DB_SIZE)"
    else
        echo "⚠️  No backup found - bot will start with empty database"
    fi
fi

# 🔥 RUN DATABASE MIGRATION & VERIFICATION
if [ -f "/data/pro4kings.db" ]; then
    echo "================================================"
    echo "🔍 Pre-migration database check..."
    
    # Check for players table
    PLAYERS_COUNT=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM players;" 2>/dev/null || echo "0")
    PROFILES_COUNT=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM player_profiles;" 2>/dev/null || echo "0")
    
    echo "   'players' table records: $PLAYERS_COUNT"
    echo "   'player_profiles' table records: $PROFILES_COUNT"
    
    echo "================================================"
    echo "🔄 Running database migration..."
    python migrate_database.py /data/pro4kings.db
    
    if [ $? -ne 0 ]; then
        echo "❌ Migration failed! Check logs above."
        exit 1
    fi
    
    echo "================================================"
    echo "🔍 Post-migration verification..."
    
    # Verify migration worked
    FINAL_PROFILES=$(sqlite3 /data/pro4kings.db "SELECT COUNT(*) FROM player_profiles;" 2>/dev/null || echo "0")
    echo "   'player_profiles' table now has: $FINAL_PROFILES records"
    
    if [ "$FINAL_PROFILES" -eq "0" ] && [ "$PLAYERS_COUNT" -gt "0" ]; then
        echo "❌ ERROR: Migration failed! No records in player_profiles but had $PLAYERS_COUNT in players"
        exit 1
    fi
    
    if [ "$FINAL_PROFILES" -gt "0" ]; then
        echo "✅ Migration successful! Database ready with $FINAL_PROFILES player profiles"
    fi
fi

# Final database statistics
if [ -f "/data/pro4kings.db" ]; then
    echo "================================================"
    echo "📊 Final Database Statistics:"
    DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
    echo "   Size: $DB_SIZE"
    echo "   Path: /data/pro4kings.db"
    echo "   Player Profiles: $FINAL_PROFILES"
    echo "================================================"
fi

echo "🤖 Starting Discord bot..."
echo "================================================"

# Start the bot
exec python bot.py

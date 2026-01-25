#!/bin/bash
set -e

echo "🚀 Starting P4K Database Bot..."
echo "================================================"

# Create data directory if it doesn't exist
mkdir -p /data
mkdir -p /app/backup_extracted

# Check if database exists in volume
if [ -f "/data/pro4kings.db" ]; then
    DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
    echo "✅ Database found in volume: /data/pro4kings.db ($DB_SIZE)"
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

# Verify database file exists and is readable
if [ -f "/data/pro4kings.db" ]; then
    echo "================================================"
    echo "📊 Database Statistics:"
    DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
    echo "   Size: $DB_SIZE"
    echo "   Path: /data/pro4kings.db"
    echo "================================================"
fi

echo "🤖 Starting Discord bot..."
echo "================================================"

# Start the bot
exec python bot.py

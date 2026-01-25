#!/bin/bash
set -e

echo "🚀 Starting P4K Database Bot..."
echo "================================================"

# Create data directory if it doesn't exist
mkdir -p /data

# Check if database exists in volume
if [ -f "/data/pro4kings.db" ]; then
    DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
    echo "✅ Database found in volume: /data/pro4kings.db ($DB_SIZE)"
else
    echo "⚠️  Database not found in volume"

    # Check if we have the extracted backup
    if [ -f "/app/backup_extracted/pro4kings.db" ]; then
        echo "📦 Copying database from image to volume..."
        cp /app/backup_extracted/pro4kings.db /data/pro4kings.db
        DB_SIZE=$(du -h /data/pro4kings.db | cut -f1)
        echo "✅ Database copied to volume: /data/pro4kings.db ($DB_SIZE)"
    else
        echo "⚠️  No backup found - bot will start with empty database"
    fi
fi

echo "================================================"
echo "🤖 Starting Discord bot..."
echo "================================================"

# Start the bot
exec python bot.py

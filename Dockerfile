FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (minimal, no build tools unless needed)
RUN apt-get update && apt-get install -y \
    gzip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code (this copies everything that exists)
COPY . .

# Create directories for data, logs, and backup storage
RUN mkdir -p /data /app/logs /app/backup_extracted

# ============================================================================
# CONDITIONALLY EXTRACT DATABASE (only if file exists)
# ============================================================================
RUN if [ -f backup.db.gz ]; then \
        echo "📦 Extracting backup.db.gz to image..."; \
        gunzip -c backup.db.gz > /app/backup_extracted/pro4kings.db && \
        DB_SIZE=$(du -h /app/backup_extracted/pro4kings.db | cut -f1) && \
        echo "✅ Database extracted: /app/backup_extracted/pro4kings.db ($DB_SIZE)"; \
    else \
        echo "ℹ️  No backup.db.gz - database will be created at runtime"; \
    fi

# Check for CSV file (informational only, doesn't fail if missing)
RUN if [ -f player_profiles.csv ]; then \
        CSV_SIZE=$(du -h player_profiles.csv | cut -f1); \
        echo "📊 CSV file found: player_profiles.csv ($CSV_SIZE)"; \
    else \
        echo "ℹ️  No CSV file - bot will create empty database"; \
    fi

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/pro4kings.db \
    DASHBOARD_URL=https://p4k-dbs-production.up.railway.app/ \
    PYTHONDONTWRITEBYTECODE=1

# Healthcheck for Railway (optional but recommended)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Use entrypoint script for startup
ENTRYPOINT ["./entrypoint.sh"]

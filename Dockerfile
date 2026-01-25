FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including build tools for Brotli AND gzip
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    python3-dev \
    gzip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for data, logs, and backup storage
RUN mkdir -p /data /app/logs /app/backup_extracted

# ============================================================================
# EXTRACT DATABASE TO IMAGE (not to /data which will be overwritten by volume)
# ============================================================================
# Extract backup.db.gz to /app/backup_extracted/ (in the image, not in /data volume)
RUN if [ -f backup.db.gz ]; then \
        echo "📦 Extracting backup.db.gz to image..."; \
        gunzip -c backup.db.gz > /app/backup_extracted/pro4kings.db; \
        DB_SIZE=$(du -h /app/backup_extracted/pro4kings.db | cut -f1); \
        echo "✅ Database ready in image: /app/backup_extracted/pro4kings.db ($DB_SIZE)"; \
        ls -lh /app/backup_extracted/pro4kings.db; \
    else \
        echo "⚠️  backup.db.gz not found - bot will start with empty database"; \
    fi

# Make entrypoint and scripts executable
RUN chmod +x entrypoint.sh
COPY migrate_database.py /app/
COPY check_backup.py /app/
RUN chmod +x check_backup.py

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/data/pro4kings.db

# 🔥 USE ENTRYPOINT INSTEAD OF CMD (can't be overridden by Railway)
ENTRYPOINT ["./entrypoint.sh"]

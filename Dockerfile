FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including build tools for Brotli AND gzip
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    python3-dev \
    gzip \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for data and logs
RUN mkdir -p /data /app/logs

# ============================================================================
# EXTRACT DATABASE - THIS IS THE FIX!
# ============================================================================
# Extract backup.db.gz to /data/pro4kings.db if it exists
RUN if [ -f backup.db.gz ]; then \
        echo "📦 Extracting backup.db.gz..."; \
        gunzip -c backup.db.gz > /data/pro4kings.db; \
        echo "✅ Database ready: /data/pro4kings.db ($(du -h /data/pro4kings.db | cut -f1))"; \
        ls -lh /data/pro4kings.db; \
    else \
        echo "⚠️  backup.db.gz not found - bot will start with empty database"; \
    fi

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/data/pro4kings.db

# Run bot
CMD ["python", "bot.py"]

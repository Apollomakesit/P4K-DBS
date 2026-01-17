FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including build tools for Brotli
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    python3-dev \
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

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/data/pro4kings.db

# Run bot
CMD ["python", "bot.py"]

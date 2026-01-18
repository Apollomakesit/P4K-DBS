# Configuration Guide

Complete reference for all environment variables and configuration options.

---

## Quick Start

1. Copy `.env.example` to `.env`
2. Edit values in `.env`
3. For Railway: Set variables in **Variables** tab

---

## Required Configuration

### DISCORD_TOKEN

**Type**: String  
**Required**: Yes  
**Description**: Your Discord bot token

**How to get**:
1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Select your application
3. Go to **Bot** section
4. Click **Reset Token** and copy

**Example**:
```bash
DISCORD_TOKEN=MTE1NzM0ODk2NzY4MDY2NTY1Mg.GxYz-A.example_token_here
```

⚠️ **Never** share or commit your token!

### ADMIN_USER_IDS

**Type**: Comma-separated integers  
**Required**: No (but highly recommended)  
**Description**: Discord user IDs with admin access

**How to get**:
1. Enable Developer Mode in Discord settings
2. Right-click your username
3. Click "Copy User ID"

**Example**:
```bash
# Single admin
ADMIN_USER_IDS=123456789012345678

# Multiple admins
ADMIN_USER_IDS=123456789012345678,987654321098765432
```

**Admin commands**:
- `/cleanup_old_data`
- `/backup_database`
- All commands bypass cooldowns

---

## Database Configuration

### DATABASE_PATH

**Type**: String (file path)  
**Default**: `pro4kings.db`  
**Railway**: Use `/data/pro4kings.db`

**Description**: Path to SQLite database file

**Examples**:
```bash
# Railway (persistent volume)
DATABASE_PATH=/data/pro4kings.db

# Local development
DATABASE_PATH=./pro4kings.db

# Custom location
DATABASE_PATH=/var/lib/bot/database.db
```

### DATABASE_BACKUP_PATH

**Type**: String (directory path)  
**Default**: `/data/backups`

**Description**: Directory for database backups

**Example**:
```bash
DATABASE_BACKUP_PATH=/data/backups
```

---

## Task Intervals

Control how often background tasks run.

### SCRAPE_ACTIONS_INTERVAL

**Type**: Integer (seconds)  
**Default**: `30`  
**Range**: 10-300

**Description**: How often to scrape latest actions from homepage

**Recommendations**:
- **High traffic server**: `15` (more frequent)
- **Normal**: `30` (default)
- **Low resources**: `60` (less frequent)

### SCRAPE_ONLINE_INTERVAL

**Type**: Integer (seconds)  
**Default**: `60`  
**Range**: 30-600

**Description**: How often to check online players

### UPDATE_PROFILES_INTERVAL

**Type**: Integer (seconds)  
**Default**: `120`  
**Range**: 60-600

**Description**: How often to update player profiles

### CHECK_BANNED_INTERVAL

**Type**: Integer (seconds)  
**Default**: `3600` (1 hour)  
**Range**: 600-86400

**Description**: How often to check banned players list

### TASK_WATCHDOG_INTERVAL

**Type**: Integer (seconds)  
**Default**: `300` (5 minutes)  
**Range**: 120-600

**Description**: How often watchdog checks for crashed tasks

---

## Data Retention

Control how long data is kept before cleanup.

### ACTIONS_RETENTION_DAYS

**Type**: Integer (days)  
**Default**: `90`  
**Range**: 7-365

**Description**: How long to keep action records

**Storage impact**:
- 30 days: ~100 MB
- 90 days: ~300 MB
- 180 days: ~600 MB

### LOGIN_EVENTS_RETENTION_DAYS

**Type**: Integer (days)  
**Default**: `30`  
**Range**: 7-180

**Description**: How long to keep login/logout events

### PROFILE_HISTORY_RETENTION_DAYS

**Type**: Integer (days)  
**Default**: `180`  
**Range**: 30-730

**Description**: How long to keep profile change history

---

## Scraper Settings

### SCRAPER_MAX_CONCURRENT

**Type**: Integer  
**Default**: `5`  
**Range**: 1-20

**Description**: Maximum concurrent HTTP requests

**Recommendations**:
- **High-end server**: `10`
- **Normal**: `5`
- **Avoid rate limits**: `3`

⚠️ Higher values may trigger rate limiting

### SCRAPER_RATE_LIMIT

**Type**: Float (requests/second)  
**Default**: `25.0`  
**Range**: 5.0-100.0

**Description**: Target requests per second

**How it works**:
- Uses token bucket algorithm
- Allows bursts up to `SCRAPER_BURST_CAPACITY`
- Automatically throttles on errors

### SCRAPER_BURST_CAPACITY

**Type**: Integer  
**Default**: `50`  
**Range**: 10-200

**Description**: Maximum burst size for rate limiter

---

## Batch Sizes

### ACTIONS_FETCH_LIMIT

**Type**: Integer  
**Default**: `200`  
**Range**: 50-500

**Description**: Number of actions to fetch per scrape

### PROFILES_UPDATE_BATCH

**Type**: Integer  
**Default**: `200`  
**Range**: 50-500

**Description**: Number of profiles to update per batch

---

## Logging Configuration

### LOG_FILE_PATH

**Type**: String (file path)  
**Default**: `bot.log`

**Description**: Path to log file

### LOG_LEVEL

**Type**: String  
**Default**: `INFO`  
**Options**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

**Description**: Minimum log level to record

**When to use**:
- **DEBUG**: Troubleshooting issues
- **INFO**: Normal operation (recommended)
- **WARNING**: Production (less verbose)
- **ERROR**: Only errors

### LOG_MAX_BYTES

**Type**: Integer (bytes)  
**Default**: `10485760` (10 MB)  
**Range**: 1048576-104857600 (1-100 MB)

**Description**: Maximum log file size before rotation

### LOG_BACKUP_COUNT

**Type**: Integer  
**Default**: `5`  
**Range**: 1-20

**Description**: Number of old log files to keep

**Example**: With `LOG_BACKUP_COUNT=5`:
- `bot.log` (current)
- `bot.log.1` (previous)
- `bot.log.2`
- `bot.log.3`
- `bot.log.4`
- `bot.log.5` (oldest)

---

## Error Notifications

### ENABLE_ERROR_NOTIFICATIONS

**Type**: Boolean  
**Default**: `true`  
**Options**: `true`, `false`

**Description**: Enable Discord DM notifications for errors

**Notifications sent for**:
- Tasks that haven't run in expected timeframe
- Scraping failures (5+ consecutive)
- Background task errors (3+ consecutive)
- Database issues

### ERROR_NOTIFICATION_COOLDOWN

**Type**: Integer (seconds)  
**Default**: `300` (5 minutes)  
**Range**: 60-3600

**Description**: Minimum time between same error notifications

**Prevents spam**: Same error won't notify more than once per cooldown period

---

## Configuration Profiles

### Development Profile

```bash
# Faster updates, more verbose logging
SCRAPE_ACTIONS_INTERVAL=15
SCRAPE_ONLINE_INTERVAL=30
UPDATE_PROFILES_INTERVAL=60

LOG_LEVEL=DEBUG
LOG_MAX_BYTES=20971520

SCRAPER_MAX_CONCURRENT=10
SCRAPER_RATE_LIMIT=50.0
```

### Production Profile (Balanced)

```bash
# Default values - good balance
SCRAPE_ACTIONS_INTERVAL=30
SCRAPE_ONLINE_INTERVAL=60
UPDATE_PROFILES_INTERVAL=120

LOG_LEVEL=INFO
LOG_MAX_BYTES=10485760

SCRAPER_MAX_CONCURRENT=5
SCRAPER_RATE_LIMIT=25.0
```

### Production Profile (Conservative)

```bash
# Lower resource usage, avoid rate limits
SCRAPE_ACTIONS_INTERVAL=60
SCRAPE_ONLINE_INTERVAL=120
UPDATE_PROFILES_INTERVAL=300

LOG_LEVEL=WARNING
LOG_MAX_BYTES=5242880

SCRAPER_MAX_CONCURRENT=3
SCRAPER_RATE_LIMIT=10.0

ACTIONS_RETENTION_DAYS=30
LOGIN_EVENTS_RETENTION_DAYS=7
```

### High-Performance Profile

```bash
# Maximum speed (requires more resources)
SCRAPE_ACTIONS_INTERVAL=15
SCRAPE_ONLINE_INTERVAL=30
UPDATE_PROFILES_INTERVAL=60

SCRAPER_MAX_CONCURRENT=15
SCRAPER_RATE_LIMIT=75.0
SCRAPER_BURST_CAPACITY=100

ACTIONS_FETCH_LIMIT=500
PROFILES_UPDATE_BATCH=500
```

⚠️ May trigger rate limiting!

---

## Viewing Current Configuration

Use the `/config` Discord command to view current configuration:

```
/config
```

Shows:
- All active settings
- Current values
- Retention policies
- Task intervals
- Scraper settings

---

## Validation

The bot validates configuration on startup:

```bash
# Example validation errors
⚠️ Configuration issues:
- DISCORD_TOKEN is not set
- SCRAPER_MAX_CONCURRENT must be >= 1 (got 0)
```

**Check logs** for validation warnings.

---

## Best Practices

1. **Start with defaults**, adjust based on needs
2. **Monitor performance** with `/health` command
3. **Increase intervals** if hitting rate limits
4. **Enable notifications** for production
5. **Regular cleanup** to manage database size
6. **Backup before** changing major settings

---

## Troubleshooting

### Rate Limiting (503 errors)

**Reduce**:
```bash
SCRAPER_MAX_CONCURRENT=3
SCRAPER_RATE_LIMIT=10.0
```

### High Memory Usage

**Reduce**:
```bash
ACTIONS_FETCH_LIMIT=100
PROFILES_UPDATE_BATCH=100
```

### Slow Updates

**Increase**:
```bash
SCRAPER_MAX_CONCURRENT=10
UPDATE_PROFILES_INTERVAL=60
```

### Database Too Large

**Reduce retention**:
```bash
ACTIONS_RETENTION_DAYS=30
LOGIN_EVENTS_RETENTION_DAYS=7
```

Then run `/cleanup_old_data`

---

## Related Documentation

- [DEPLOYMENT.md](DEPLOYMENT.md) - Railway deployment guide
- [COMMANDS.md](COMMANDS.md) - Discord commands reference
- [README.md](README.md) - General overview

# Configuration Guide

Complete reference for all environment variables and configuration options for P4K-DBS.

---

## Quick Start

1. Copy `.env.example` to `.env`
2. Edit values in `.env`
3. For Railway: Set variables in **Variables** tab
4. Restart bot to apply changes

---

## Required Configuration

### DISCORD_TOKEN

**Type**: String  
**Required**: Yes  
**Description**: Your Discord bot token from Discord Developer Portal

**How to get**:
1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Select your application (or create new)
3. Go to **Bot** section
4. Click **Reset Token** and copy

**Example**:
```bash
DISCORD_TOKEN=MTE1NzM0ODk2NzY4MDY2NTY1Mg.GxYz-A.example_token_here
```

⚠️ **NEVER** share or commit your token!

---

### ADMIN_USER_IDS

**Type**: Comma-separated integers  
**Required**: No (but highly recommended)  
**Description**: Discord user IDs with admin access to restricted commands

**How to get your Discord User ID**:
1. Enable **Developer Mode** in Discord: Settings → Advanced → Developer Mode
2. Right-click your username
3. Click **"Copy User ID"**

**Examples**:
```bash
# Single admin
ADMIN_USER_IDS=123456789012345678

# Multiple admins (comma-separated)
ADMIN_USER_IDS=123456789012345678,987654321098765432,555666777888999000
```

**Admin-only commands**:
- `/cleanup_old_data` - Remove old data
- `/backup_database` - Create database backup

---

## Database Configuration

### DATABASE_PATH

**Type**: String (file path)  
**Default**: `data/pro4kings.db`  
**Railway Recommended**: `/data/pro4kings.db`

**Description**: Path to SQLite database file

**Examples**:
```bash
# Railway (persistent volume mounted at /data)
DATABASE_PATH=/data/pro4kings.db

# Local development
DATABASE_PATH=data/pro4kings.db

# Custom location
DATABASE_PATH=/var/lib/p4k/database.db
```

⚠️ **Railway Important**: Use `/data/` path with mounted volume or database will be lost on restart!

---

### DATABASE_BACKUP_PATH

**Type**: String (directory path)  
**Default**: `data/backups`

**Description**: Directory where `/backup_database` command stores backups

**Examples**:
```bash
# Railway
DATABASE_BACKUP_PATH=/data/backups

# Local
DATABASE_BACKUP_PATH=data/backups
```

---

## Task Intervals

Control how often background tasks run (in seconds).

### SCRAPE_ACTIONS_INTERVAL

**Type**: Integer (seconds)  
**Default**: `5`  
**Recommended Range**: 5-60

**Description**: How often to scrape latest actions from Pro4Kings homepage

**Recommendations**:
- **High priority server**: `5` (very frequent, current default)
- **Balanced**: `30` (good balance)
- **Low resources**: `60` (less frequent)

**Impact**:
- Lower = More up-to-date action data, more requests
- Higher = Less frequent updates, lower resource usage

```bash
SCRAPE_ACTIONS_INTERVAL=5
```

---

### SCRAPE_ONLINE_INTERVAL

**Type**: Integer (seconds)  
**Default**: `60`  
**Recommended Range**: 30-300

**Description**: How often to check online players and detect logins/logouts

```bash
SCRAPE_ONLINE_INTERVAL=60
```

---

### UPDATE_PROFILES_INTERVAL

**Type**: Integer (seconds)  
**Default**: `120` (2 minutes)  
**Recommended Range**: 60-600

**Description**: How often to update pending player profiles (faction, rank, stats)

```bash
UPDATE_PROFILES_INTERVAL=120
```

---

### CHECK_BANNED_INTERVAL

**Type**: Integer (seconds)  
**Default**: `3600` (1 hour)  
**Recommended Range**: 1800-86400

**Description**: How often to check banned players list

```bash
CHECK_BANNED_INTERVAL=3600
```

---

### TASK_WATCHDOG_INTERVAL

**Type**: Integer (seconds)  
**Default**: `300` (5 minutes)  
**Recommended Range**: 180-600

**Description**: How often watchdog checks for crashed tasks and restarts them

```bash
TASK_WATCHDOG_INTERVAL=300
```

---

## VIP Player Tracking

Monitor specific high-priority players with increased scan frequency.

### VIP_PLAYER_IDS

**Type**: Comma-separated player IDs  
**Default**: *(see .env.example for default list)*  
**Required**: No

**Description**: List of player IDs to track with higher priority. VIP actions are scanned separately to ensure important players' activity is always captured.

**Examples**:
```bash
# Track specific players
VIP_PLAYER_IDS=12345,67890,11111

# Empty to disable VIP tracking
VIP_PLAYER_IDS=

# Large VIP list
VIP_PLAYER_IDS=1,799,1207,9,64,100,14,69
```

**Use cases**:
- Server staff/admins
- Faction leaders
- Problem players requiring monitoring
- Players under investigation

---

### VIP_SCAN_INTERVAL

**Type**: Integer (seconds)  
**Default**: `10`  
**Recommended Range**: 5-60

**Description**: How often to scan actions for VIP players (independent of normal action scan)

```bash
VIP_SCAN_INTERVAL=10
```

**Note**: Only active if `VIP_PLAYER_IDS` is configured

---

## Online Player Priority Tracking

Automatically track all currently online players with higher priority.

### TRACK_ONLINE_PLAYERS_PRIORITY

**Type**: Boolean  
**Default**: `true`  
**Options**: `true`, `false`

**Description**: Enable automatic priority tracking for all online players. When enabled, actions from currently online players are scanned more frequently.

**Benefits**:
- Ensures active players' actions are captured immediately
- Useful during bot startup to capture current activity
- Helps preserve data for online players before initial scan completes

```bash
TRACK_ONLINE_PLAYERS_PRIORITY=true
```

---

### ONLINE_PLAYERS_SCAN_INTERVAL

**Type**: Integer (seconds)  
**Default**: `15`  
**Recommended Range**: 10-60

**Description**: How often to scan actions for all currently online players

```bash
ONLINE_PLAYERS_SCAN_INTERVAL=15
```

**Note**: Only active if `TRACK_ONLINE_PLAYERS_PRIORITY=true`

---

## Data Retention

Control how long data is kept before cleanup.

### ACTIONS_RETENTION_DAYS

**Type**: Integer (days)  
**Default**: `90`  
**Range**: 7-365

**Description**: How long to keep action records before `/cleanup_old_data` removes them

**Storage impact** (approximate):
- 30 days: ~50-100 MB
- 90 days: ~150-300 MB
- 180 days: ~300-600 MB
- 365 days: ~600-1200 MB

```bash
ACTIONS_RETENTION_DAYS=90
```

---

### LOGIN_EVENTS_RETENTION_DAYS

**Type**: Integer (days)  
**Default**: `30`  
**Range**: 7-180

**Description**: How long to keep login/logout event records

```bash
LOGIN_EVENTS_RETENTION_DAYS=30
```

---

### PROFILE_HISTORY_RETENTION_DAYS

**Type**: Integer (days)  
**Default**: `180`  
**Range**: 30-730

**Description**: How long to keep profile change history (faction changes, rank changes, etc.)

```bash
PROFILE_HISTORY_RETENTION_DAYS=180
```

---

## Scraper Settings

### SCRAPER_MAX_CONCURRENT

**Type**: Integer  
**Default**: `5`  
**Range**: 1-50

**Description**: Maximum concurrent HTTP requests to Pro4Kings website

**Recommendations**:
- **Aggressive**: `15-20` (fast, but may trigger rate limits)
- **Balanced**: `5-10` (recommended)
- **Conservative**: `3-5` (slower, avoids rate limits)

```bash
SCRAPER_MAX_CONCURRENT=5
```

⚠️ **Warning**: Higher values may trigger rate limiting (503 errors). Monitor `/health` for errors.

---

### SCRAPER_RATE_LIMIT

**Type**: Float (requests/second)  
**Default**: `10.0`  
**Range**: 5.0-50.0

**Description**: Target requests per second (uses token bucket algorithm)

**How it works**:
- Allows bursts up to `SCRAPER_BURST_CAPACITY`
- Automatically throttles on errors
- Self-adjusting on rate limit detection

> 🔥 **Note**: panel.pro4kings.ro has a 30-connection shared hosting limit. Values above 15 req/s may cause 503 errors.

```bash
SCRAPER_RATE_LIMIT=10.0
```

---

### SCRAPER_BURST_CAPACITY

**Type**: Integer  
**Default**: `20`  
**Range**: 10-100

**Description**: Maximum burst size for rate limiter (allows temporary spikes in requests)

> 🔥 **Note**: Reduced from 50 to prevent overloading shared hosting.

```bash
SCRAPER_BURST_CAPACITY=20
```

---

## Batch Sizes

### ACTIONS_FETCH_LIMIT

**Type**: Integer  
**Default**: `200`  
**Range**: 50-500

**Description**: Number of actions to fetch per scrape cycle from homepage

```bash
ACTIONS_FETCH_LIMIT=200
```

---

### PROFILES_UPDATE_BATCH

**Type**: Integer  
**Default**: `200`  
**Range**: 50-500

**Description**: Number of profiles to update per batch (affects memory usage)

```bash
PROFILES_UPDATE_BATCH=200
```

---

## Logging Configuration

### LOG_FILE_PATH

**Type**: String (file path)  
**Default**: `bot.log`

**Description**: Path to log file

```bash
LOG_FILE_PATH=bot.log
```

---

### LOG_LEVEL

**Type**: String  
**Default**: `INFO`  
**Options**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

**Description**: Minimum log level to record

**When to use**:
- **DEBUG**: Troubleshooting issues (very verbose)
- **INFO**: Normal operation (recommended)
- **WARNING**: Production (less verbose, only warnings and errors)
- **ERROR**: Only errors and critical issues

```bash
LOG_LEVEL=INFO
```

---

### LOG_MAX_BYTES

**Type**: Integer (bytes)  
**Default**: `10485760` (10 MB)  
**Range**: 1048576-104857600 (1-100 MB)

**Description**: Maximum log file size before rotation

```bash
LOG_MAX_BYTES=10485760
```

---

### LOG_BACKUP_COUNT

**Type**: Integer  
**Default**: `5`  
**Range**: 1-20

**Description**: Number of old log files to keep after rotation

**Example**: With `LOG_BACKUP_COUNT=5`:
- `bot.log` (current)
- `bot.log.1` (previous)
- `bot.log.2`
- `bot.log.3`
- `bot.log.4`
- `bot.log.5` (oldest)

```bash
LOG_BACKUP_COUNT=5
```

---

## Error Notifications

### ENABLE_ERROR_NOTIFICATIONS

**Type**: Boolean  
**Default**: `true`  
**Options**: `true`, `false`

**Description**: Enable Discord DM notifications to admins for critical errors

**Notifications sent for**:
- Tasks that haven't run in expected timeframe
- Scraping failures (5+ consecutive)
- Background task errors (3+ consecutive)
- Database connection issues

```bash
ENABLE_ERROR_NOTIFICATIONS=true
```

**Note**: Requires `ADMIN_USER_IDS` to be configured

---

### ERROR_NOTIFICATION_COOLDOWN

**Type**: Integer (seconds)  
**Default**: `300` (5 minutes)  
**Range**: 60-3600

**Description**: Minimum time between same error notifications (prevents spam)

```bash
ERROR_NOTIFICATION_COOLDOWN=300
```

---

## Configuration Profiles

### Development Profile

**Purpose**: Fast updates, verbose logging for testing

```bash
# Fast task intervals
SCRAPE_ACTIONS_INTERVAL=5
SCRAPE_ONLINE_INTERVAL=30
UPDATE_PROFILES_INTERVAL=60

# Verbose logging
LOG_LEVEL=DEBUG
LOG_MAX_BYTES=20971520

# Scraping (limited by server's 30-connection limit)
SCRAPER_MAX_CONCURRENT=5
SCRAPER_RATE_LIMIT=10.0

# Short retention for testing cleanup
ACTIONS_RETENTION_DAYS=7
LOGIN_EVENTS_RETENTION_DAYS=3
```

---

### Production - Balanced (Recommended)

**Purpose**: Good balance between performance and resource usage

```bash
# Balanced intervals
SCRAPE_ACTIONS_INTERVAL=5
SCRAPE_ONLINE_INTERVAL=60
UPDATE_PROFILES_INTERVAL=120
CHECK_BANNED_INTERVAL=3600

# VIP tracking
VIP_PLAYER_IDS=1,799,1207
VIP_SCAN_INTERVAL=10

# Online priority
TRACK_ONLINE_PLAYERS_PRIORITY=true
ONLINE_PLAYERS_SCAN_INTERVAL=15

# Standard logging
LOG_LEVEL=INFO
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5

# Moderate scraping (🔥 optimized for shared hosting)
SCRAPER_MAX_CONCURRENT=5
SCRAPER_RATE_LIMIT=10.0
SCRAPER_BURST_CAPACITY=20

# Standard retention
ACTIONS_RETENTION_DAYS=90
LOGIN_EVENTS_RETENTION_DAYS=30
PROFILE_HISTORY_RETENTION_DAYS=180
```

---

### Production - Conservative

**Purpose**: Lower resource usage, avoid rate limits (Railway free tier)

```bash
# Slower intervals
SCRAPE_ACTIONS_INTERVAL=30
SCRAPE_ONLINE_INTERVAL=120
UPDATE_PROFILES_INTERVAL=300
CHECK_BANNED_INTERVAL=7200

# Disable VIP/online priority to save resources
VIP_PLAYER_IDS=
TRACK_ONLINE_PLAYERS_PRIORITY=false

# Minimal logging
LOG_LEVEL=WARNING
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=3

# Conservative scraping
SCRAPER_MAX_CONCURRENT=3
SCRAPER_RATE_LIMIT=10.0
SCRAPER_BURST_CAPACITY=20

# Short retention to save space
ACTIONS_RETENTION_DAYS=30
LOGIN_EVENTS_RETENTION_DAYS=7
PROFILE_HISTORY_RETENTION_DAYS=60

# Smaller batches
ACTIONS_FETCH_LIMIT=100
PROFILES_UPDATE_BATCH=100
```

---

### Production - High Performance

**Purpose**: Maximum speed (requires more resources, Railway pro plan)

```bash
# Fast intervals
SCRAPE_ACTIONS_INTERVAL=5
SCRAPE_ONLINE_INTERVAL=30
UPDATE_PROFILES_INTERVAL=60

# Aggressive VIP/online tracking
VIP_PLAYER_IDS=1,799,1207,9,64,100,14
VIP_SCAN_INTERVAL=5
TRACK_ONLINE_PLAYERS_PRIORITY=true
ONLINE_PLAYERS_SCAN_INTERVAL=10

# Debug for monitoring
LOG_LEVEL=INFO
LOG_MAX_BYTES=20971520

# Aggressive scraping
SCRAPER_MAX_CONCURRENT=15
SCRAPER_RATE_LIMIT=75.0
SCRAPER_BURST_CAPACITY=100

# Large batches
ACTIONS_FETCH_LIMIT=500
PROFILES_UPDATE_BATCH=500

# Long retention
ACTIONS_RETENTION_DAYS=180
LOGIN_EVENTS_RETENTION_DAYS=90
PROFILE_HISTORY_RETENTION_DAYS=365
```

⚠️ **Warning**: May trigger rate limiting! Monitor closely.

---

## Viewing Current Configuration

Use `/config` command in Discord to view active configuration:

```
/config
```

Shows:
- All task intervals
- Scraper settings
- VIP and online priority status
- Data retention policies
- Batch sizes
- Logging configuration

---

## Configuration Validation

The bot validates configuration on startup and logs warnings for issues:

```bash
# Example validation output
✅ Environment verification passed
⚠️ Configuration issues: No ADMIN_USER_IDS configured (error notifications disabled)
```

**Check logs** (`bot.log`) for validation warnings.

---

## Best Practices

1. ✅ **Start with defaults**, adjust based on monitoring
2. ✅ **Monitor `/health`** regularly to check for errors
3. ✅ **Increase intervals** if hitting rate limits (503 errors)
4. ✅ **Enable admin notifications** for production
5. ✅ **Regular cleanup** to manage database size
6. ✅ **Backup before** changing major settings
7. ✅ **Test VIP tracking** with a few player IDs first
8. ✅ **Monitor scan speed** and adjust `SCRAPER_MAX_CONCURRENT` accordingly

---

## Troubleshooting

### Rate Limiting (503 errors)

**Symptoms**: `/health` shows high error count for scrape tasks

**Solution**:
```bash
SCRAPER_MAX_CONCURRENT=3
SCRAPER_RATE_LIMIT=10.0
SCRAPE_ACTIONS_INTERVAL=30
```

---

### High Memory Usage

**Symptoms**: Bot crashes or Railway shows high memory

**Solution**:
```bash
ACTIONS_FETCH_LIMIT=100
PROFILES_UPDATE_BATCH=100
SCRAPER_MAX_CONCURRENT=3
```

Then run `/cleanup_old_data`

---

### Slow Profile Updates

**Symptoms**: Player profiles not updating frequently enough

**Solution**:
```bash
UPDATE_PROFILES_INTERVAL=60
PROFILES_UPDATE_BATCH=300
SCRAPER_MAX_CONCURRENT=5  # Don't exceed 5 due to server limits
```

---

### Database Too Large

**Symptoms**: Railway volume full or slow queries

**Solution**:
1. Reduce retention:
```bash
ACTIONS_RETENTION_DAYS=30
LOGIN_EVENTS_RETENTION_DAYS=7
PROFILE_HISTORY_RETENTION_DAYS=60
```

2. Run cleanup:
```
/cleanup_old_data dry_run:false confirm:true
```

---

### Missing VIP Actions

**Symptoms**: VIP player actions not being captured

**Solution**:
1. Verify player IDs are correct
2. Check `/health` for VIP scan errors
3. Reduce interval:
```bash
VIP_SCAN_INTERVAL=5
```

---

## Related Documentation

- [COMMANDS.md](COMMANDS.md) - Discord commands reference
- [DEPLOYMENT.md](DEPLOYMENT.md) - Railway deployment guide
- [README.md](README.md) - Project overview
- `.env.example` - Example configuration file

---

**Last Updated**: January 26, 2026  
**Bot Version**: 2.0 (VIP & Online Priority Tracking)

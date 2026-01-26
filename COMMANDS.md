# Discord Commands Reference

Complete list of all available Discord slash commands for P4K-DBS.

---

## General Commands

### /health

**Description**: Check bot health status  
**Cooldown**: 10 seconds  
**Permissions**: Everyone

**Shows**:
- Background task status and last run times
- Task error counts
- Memory usage
- Database connection status
- Player and action counts

**Example**:
```
/health
```

**Output**:
```
🏋️ Bot Health Status

Background Tasks:
🟢 scrape_actions
   Last run: 15s ago
   Errors: 0

🟢 scrape_online_players
   Last run: 45s ago
   Errors: 0

🟢 scrape_vip_actions
   Last run: 8s ago
   Errors: 0

Memory Usage:
Current: 127.3 MB

Database:
✅ Connected
Actions: 57,588
Players: 186,906
```

---

### /config

**Description**: Display current bot configuration  
**Cooldown**: 30 seconds  
**Permissions**: Everyone

**Shows**:
- Database paths
- Task intervals (actions, online, profiles, bans, watchdog)
- Data retention policies
- Scraper settings (workers, rate limits)
- VIP player tracking status
- Online player priority status
- Batch sizes
- Logging configuration

**Example**:
```
/config
```

---

### /stats

**Description**: Show database statistics  
**Cooldown**: 10 seconds  
**Permissions**: Everyone

**Shows**:
- Total players tracked
- Total actions recorded
- Currently online player count
- Actions in last 24 hours
- Logins today
- Active bans count

**Example**:
```
/stats
```

**Output**:
```
📊 Database Statistics

👥 Total Players: 186,906
📝 Total Actions: 57,588
🟢 Online Now: 299
📈 Actions (24h): 2,341
🔑 Logins Today: 847
🚫 Active Bans: 12
```

---

## Player Commands

### /player

**Description**: Get complete player profile and stats  
**Cooldown**: 5 seconds  
**Permissions**: Everyone

**Parameters**:
- `identifier` (required): Player ID or name

**Shows**:
- Username and player ID
- Online status and last seen
- Faction and rank
- Job
- Warnings (X/3)
- Played hours
- Age (IC)
- Total actions logged
- Recent actions (last 7 days)
- First detected date

**Examples**:
```
/player identifier:12345
/player identifier:John_Doe
/player identifier:John  (searches by name)
```

**Output**:
```
🟢 John_Doe
Player ID: 12345

Status: Online
Faction: LSPD - Officer II
Job: Taxi Driver
Warnings: 🟢 0/3
Played Hours: 247.5h
Age (IC): 25

📊 Total Actions: 1,234
📝 Actions (7d): 89

First Detected: 2025-11-15
```

---

### /search

**Description**: Search players by name  
**Cooldown**: 10 seconds  
**Permissions**: Everyone

**Parameters**:
- `query` (required): Search term (minimum 2 characters)

**Features**:
- Partial name matching
- Case-insensitive
- Shows up to 10 results
- Displays online status, faction, and level

**Examples**:
```
/search query:John
/search query:Smith
/search query:Do
```

**Output**:
```
🔍 Search Results for 'John'
Found 23 player(s)

John_Doe (ID: 12345)
🟢 Online
├ Faction: LSPD
└ Level: 15

Johnny_B (ID: 67890)
⚪ Offline
├ Faction: No faction
└ Level: 3

Showing 10 of 23 results
```

---

### /actions

**Description**: View player's recent actions with pagination  
**Cooldown**: 30 seconds  
**Permissions**: Everyone

**Parameters**:
- `identifier` (required): Player ID or name
- `days` (optional): Days to look back (default: 7, max: 30)

**Features**:
- Automatic deduplication of duplicate actions
- Interactive pagination (10 actions per page)
- Shows action type, timestamp, and details
- Displays duplicate count when applicable

**Examples**:
```
/actions identifier:12345
/actions identifier:John_Doe days:14
/actions identifier:John days:30
```

**Output**:
```
📝 Actions for John_Doe
Last 7 days • 45 unique action(s) (67 total including duplicates)

warning_received - 2026-01-18 14:30
├ Player: John_Doe (12345)
└ Detail: Avertisment 1/3 de la Admin_Name

item_given - 2026-01-18 12:15 ×3
├ Player: John_Doe (12345)
└ Detail: Dat Materials către Jane_Smith

Page 1/5 • Use buttons to navigate
[◀️ Previous] [Next ▶️]
```

---

### /sessions

**Description**: View player's gaming sessions  
**Cooldown**: 10 seconds  
**Permissions**: Everyone

**Parameters**:
- `identifier` (required): Player ID or name
- `days` (optional): Days to look back (default: 7, max: 30)

**Shows**:
- Login/logout times
- Session durations
- Total playtime in period
- Up to 10 most recent sessions

**Examples**:
```
/sessions identifier:12345
/sessions identifier:John_Doe days:30
```

---

### /rank_history

**Description**: View player's faction rank history  
**Cooldown**: 10 seconds  
**Permissions**: Everyone

**Parameters**:
- `identifier` (required): Player ID or name

**Shows**:
- All rank changes
- Faction names
- Date obtained
- Duration in each rank
- Current rank highlighted

**Examples**:
```
/rank_history identifier:12345
/rank_history identifier:John_Doe
```

---

## Faction Commands

### /faction

**Description**: List all members of a faction with pagination  
**Cooldown**: 30 seconds  
**Permissions**: Everyone

**Parameters**:
- `faction_name` (required): Name of faction

**Features**:
- Shows all faction members
- Displays ranks
- Shows online status
- Paginated (20 members per page)
- Interactive navigation buttons

**Examples**:
```
/faction faction_name:LSPD
/faction faction_name:Ballas
/faction faction_name:FBI
```

**Output**:
```
👥 LSPD
Showing 1-20 of 47 member(s)

John_Doe (12345)
🟢 Officer II

Jane_Smith (67890)
⚪ Detective

Page 1/3 • Use buttons to navigate
[◀️ Previous] [Next ▶️]
```

---

### /factionlist

**Description**: List all factions sorted by member count  
**Cooldown**: 30 seconds  
**Permissions**: Everyone

**Shows**:
- All factions
- Member counts
- Online member counts
- Sorted by size (descending)
- Up to 25 factions shown

**Example**:
```
/factionlist
```

---

### /promotions

**Description**: View recent faction promotions  
**Cooldown**: 30 seconds  
**Permissions**: Everyone

**Parameters**:
- `days` (optional): Days to look back (default: 7, max: 30)

**Shows**:
- Recent rank changes
- Player names
- Old rank → New rank
- Faction name
- Dates

**Examples**:
```
/promotions
/promotions days:30
```

---

## Ban Commands

### /bans

**Description**: View banned players  
**Cooldown**: 30 seconds  
**Permissions**: Everyone

**Parameters**:
- `show_expired` (optional): Include expired bans (default: false)

**Shows**:
- Banned players
- Ban reasons
- Admin who banned
- Ban duration
- Active/expired status
- Up to 15 bans shown

**Examples**:
```
/bans
/bans show_expired:true
```

---

## Online Commands

### /online

**Description**: View currently online players  
**Cooldown**: 10 seconds  
**Permissions**: Everyone

**Shows**:
- All online players
- Player names and IDs
- Up to 20 players shown

**Example**:
```
/online
```

---

## Scan Commands

### /scan start

**Description**: Start database scan with concurrent workers  
**Cooldown**: None  
**Permissions**: Everyone

**Parameters**:
- `start_id` (optional): Starting player ID (default: 1)
- `end_id` (optional): Ending player ID (default: 100000)

**Features**:
- Concurrent worker system for maximum speed
- Configurable batch sizes and workers
- Real-time progress tracking
- Auto-saves found players to database
- Pause/resume capability

**Examples**:
```
/scan start start_id:1 end_id:100000
/scan start start_id:50000 end_id:60000
```

**Output**:
```
🚀 Concurrent Database Scan Started
Scanning player IDs 1 to 100,000

Using 5 concurrent workers for maximum speed!

Use /scan status to monitor progress with real-time auto-refresh!

⚙️ Batch Size: 50 IDs
👷 Max Workers: 10
🔀 Concurrent Batches: 5
⏱️ Wave Delay: 0.05s
⚡ Expected Speed: ~150.0 IDs/s
📊 Total IDs: 100,000
🕐 Est. Time: 11m
```

---

### /scan status

**Description**: View real-time scan progress (auto-refreshing every 3 seconds)  
**Cooldown**: None  
**Permissions**: Everyone

**Shows**:
- Current scan progress percentage
- IDs scanned and remaining
- Current highest ID processed
- Scan speed (IDs/second)
- Estimated time remaining
- Found players count
- Error count
- Worker configuration
- Progress bar visualization

**Example**:
```
/scan status
```

**Output**:
```
🔄 Scan Status: Running
Progress: 45.2% (45,234/100,000 IDs)
Range: 1 → 100,000

📍 Current Highest ID: 45,234
⚡ Speed: 127.45 IDs/s
⏱️ ETA: 7m 8s
✅ Found: 8,932
❌ Errors: 42
⏲️ Elapsed: 5m 55s

🔧 Workers: 10 workers × 5 concurrent batches

Progress Bar:
█████████░░░░░░░░░░░ 45.2%

🔄 Auto-refreshing every 3 seconds | Use /scan pause or /scan cancel
```

---

### /scan pause

**Description**: Pause ongoing scan  
**Cooldown**: None  
**Permissions**: Everyone

**Example**:
```
/scan pause
```

---

### /scan resume

**Description**: Resume paused scan  
**Cooldown**: None  
**Permissions**: Everyone

**Example**:
```
/scan resume
```

---

### /scan cancel

**Description**: Cancel ongoing scan  
**Cooldown**: None  
**Permissions**: Everyone

**Shows**:
- Final statistics (found, errors, total scanned)
- Average scan speed

**Example**:
```
/scan cancel
```

---

### /scanconfig

**Description**: View or modify scan configuration  
**Cooldown**: None  
**Permissions**: Everyone

**Parameters** (all optional):
- `batch_size`: Number of IDs per batch (10-100)
- `workers`: Max concurrent HTTP requests (10-50)
- `wave_delay`: Delay between batches in seconds (0.01-1.0)
- `concurrent_batches`: Number of batches to process simultaneously (1-10)

**Examples**:
```
# View current configuration
/scanconfig

# Ultra Fast preset (~150 IDs/s)
/scanconfig batch_size:100 workers:30 wave_delay:0.05 concurrent_batches:8

# Balanced preset (~40 IDs/s)
/scanconfig batch_size:50 workers:15 wave_delay:0.1 concurrent_batches:3

# Safe preset (~15 IDs/s)
/scanconfig batch_size:30 workers:10 wave_delay:0.2 concurrent_batches:2
```

**Output**:
```
⚙️ Scan Configuration - Concurrent Worker System

Current Configuration:

📦 Batch Size: 50 IDs per batch
👷 Max Workers: 15 HTTP requests
🔀 Concurrent Batches: 3 workers
⏱️ Wave Delay: 0.1s per worker
⚡ Expected Speed: ~40.0 IDs/second

📋 Recommended Presets:
Ultra Fast: /scanconfig 100 30 0.05 8 (~150 IDs/s)
Aggressive: /scanconfig 50 20 0.05 5 (~80 IDs/s)
Balanced: /scanconfig 50 15 0.1 3 (~40 IDs/s)
Safe: /scanconfig 30 10 0.2 2 (~15 IDs/s)

💡 More concurrent batches = faster scanning | Adjust if you get rate limited
```

---

## Admin Commands

⚠️ These commands require admin permissions (ADMIN_USER_IDS environment variable)

### /cleanup_old_data

**Description**: Remove old data based on retention policy  
**Cooldown**: 300 seconds (5 minutes)  
**Permissions**: Admin only

**Parameters**:
- `dry_run` (optional): Preview without deleting (default: true)
- `confirm` (optional): Must be true to actually delete (default: false)

**Safety Features**:
- Requires both `dry_run=false` AND `confirm=true` to delete
- Shows preview of what will be deleted
- Uses configured retention policies from environment

**Examples**:
```
# Preview what will be deleted
/cleanup_old_data
/cleanup_old_data dry_run:true

# Actually delete old data
/cleanup_old_data dry_run:false confirm:true
```

**Output**:
```
🗑️ DRY RUN - Data Cleanup Preview
No data was deleted. Set dry_run=false confirm=true to execute.

Old Actions (90+ days): 12,847 records
Old Login Events (30+ days): 45,231 records
Old Profile History (180+ days): 3,421 records
```

---

### /backup_database

**Description**: Create timestamped database backup  
**Cooldown**: 300 seconds (5 minutes)  
**Permissions**: Admin only

**Creates**:
- Timestamped backup file (pro4kings_backup_YYYYMMDD_HHMMSS.db)
- Stored in configured backup directory
- Shows file size and total backup count

**Example**:
```
/backup_database
```

**Output**:
```
✅ Database Backup Created

Backup File:
pro4kings_backup_20260126_052400.db

Size: 198.45 MB
Location: /data/backups

Total backups: 12
```

---

## Prefix Commands

### !p4k sync

**Description**: Force sync slash commands (emergency use only)  
**Type**: Prefix command (not slash)  
**Permissions**: Everyone

**When to use**:
- Slash commands not appearing
- After bot restart
- After code updates

**Example**:
```
!p4k sync
```

**Output**:
```
🔄 Sincronizare forțată comenzi slash...
✅ Succes! Sincronizate 18 comenzi:
• /health: Check bot health status
• /config: Display current configuration
• /stats: Show database statistics
...
```

---

## Command Cooldowns

| Command | Cooldown | Notes |
|---------|----------|-------|
| `/health` | 10s | Status check |
| `/config` | 30s | Configuration display |
| `/stats` | 10s | Database stats |
| `/player` | 5s | Profile lookup |
| `/search` | 10s | Name search |
| `/actions` | 30s | Action history |
| `/sessions` | 10s | Session history |
| `/rank_history` | 10s | Rank changes |
| `/faction` | 30s | Member list |
| `/factionlist` | 30s | All factions |
| `/promotions` | 30s | Recent promotions |
| `/bans` | 30s | Ban list |
| `/online` | 10s | Online players |
| `/scan start` | None | Start scan |
| `/scan status` | None | Scan progress |
| `/scan pause` | None | Pause scan |
| `/scan resume` | None | Resume scan |
| `/scan cancel` | None | Cancel scan |
| `/scanconfig` | None | Scan settings |
| `/cleanup_old_data` | 300s | Admin only |
| `/backup_database` | 300s | Admin only |

---

## Pagination Features

Commands with pagination support:
- `/actions` - 10 actions per page
- `/faction` - 20 members per page

**Controls**:
- ◀️ **Previous**: Go to previous page
- ▶️ **Next**: Go to next page

**Features**:
- Buttons auto-disable after 3 minutes
- Only command author can use buttons
- Page indicator shows current position

---

## Error Messages

### Common Errors

**Cooldown**:
```
⏳ This command is on cooldown. Try again in 15 seconds.
```

**Permission Denied**:
```
❌ Access Denied
This command is restricted to bot administrators.
```

**Not Found**:
```
🔍 Not Found
No player found with identifier: John
```

**No Data**:
```
📝 No Actions
John_Doe has no recorded actions in the last 7 days.
```

**Scan Already Running**:
```
❌ A scan is already in progress! Use /scan status to check progress or /scan cancel to stop it.
```

---

## Tips & Best Practices

### Efficient Player Lookup

```
# Fastest - Search by exact ID
/player identifier:12345

# Search by partial name
/search query:John
# Then use exact ID from results
/player identifier:12345
```

### Monitoring Bot Health

```
# Quick health check
/health

# View configuration
/config

# Check database size and activity
/stats
```

### Database Scanning

```
# 1. Configure scan speed based on resources
/scanconfig batch_size:50 workers:15 wave_delay:0.1 concurrent_batches:3

# 2. Start scan
/scan start start_id:1 end_id:100000

# 3. Monitor progress (auto-refreshes)
/scan status

# 4. Pause if needed (e.g., high server load)
/scan pause

# 5. Resume when ready
/scan resume
```

### Database Maintenance

```
# 1. Check current size
/stats

# 2. Create backup before cleanup
/backup_database

# 3. Preview what will be deleted
/cleanup_old_data dry_run:true

# 4. Execute cleanup
/cleanup_old_data dry_run:false confirm:true

# 5. Verify new size
/stats
```

---

## Related Documentation

- [CONFIGURATION.md](CONFIGURATION.md) - Environment variables and settings
- [DEPLOYMENT.md](DEPLOYMENT.md) - Railway deployment guide
- [README.md](README.md) - Project overview

---

**Last Updated**: January 26, 2026  
**Bot Version**: 2.0 (Concurrent Scan System)

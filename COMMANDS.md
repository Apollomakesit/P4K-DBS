# Discord Commands Reference

Complete list of all available Discord slash commands.

---

## General Commands

### /health

**Description**: Check bot health status  
**Cooldown**: 10 seconds  
**Permissions**: Everyone

**Shows**:
- Background task status
- Last run times
- Error counts
- Memory usage
- Database status
- Scraper status

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

Memory Usage:
Current: 127.3 MB

Database:
✅ Connected
Actions: 45,231
Players: 12,847
```

---

### /config

**Description**: Display current configuration  
**Cooldown**: 30 seconds  
**Permissions**: Everyone

**Shows**:
- Database paths
- Task intervals
- Data retention policies
- Scraper settings
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
- Online player count
- Recent activity

**Example**:
```
/stats
```

---

## Player Commands

### /player

**Description**: Get complete player profile  
**Cooldown**: 5 seconds  
**Permissions**: Everyone

**Parameters**:
- `identifier` (required): Player ID or name

**Shows**:
- Username and ID
- Online status
- Faction and rank
- Level and respect
- Warnings
- Played hours
- Last seen

**Examples**:
```
/player identifier:12345
/player identifier:John_Doe
```

---

### /search

**Description**: Search players by name  
**Cooldown**: 10 seconds  
**Permissions**: Everyone

**Parameters**:
- `query` (required): Search term (minimum 2 characters)

**Features**:
- Fuzzy matching
- Paginated results (10 per page)
- Shows online status
- Sorted by online first

**Examples**:
```
/search query:John
/search query:Smith
```

**Output**:
```
Players matching 'John' (Page 1/3)

John_Doe (ID: 12345)
├ Status: 🟢 Online
├ Faction: LSPD
└ Level: 45

John_Smith (ID: 67890)
├ Status: ⚪ Offline
├ Faction: No faction
└ Level: 12

[⏮️] [◀️] [▶️] [⏭️] [🗑️]
```

---

### /actions

**Description**: Get player's recent actions  
**Cooldown**: 30 seconds  
**Permissions**: Everyone

**Parameters**:
- `identifier` (required): Player ID or name
- `days` (optional): Days to look back (default: 7, max: 30)

**Shows**:
- All actions performed
- Timestamps
- Action details
- Paginated (10 per page)

**Examples**:
```
/actions identifier:12345
/actions identifier:John_Doe days:14
```

**Output**:
```
Actions for John_Doe (7 days) (Page 1/8)

warning_received - 2026-01-18 14:30
├ Player: John_Doe (12345)
└ Detail: Avertisment 1/3 de la Admin_Name

item_given - 2026-01-18 12:15
├ Player: John_Doe (12345)
└ Detail: Dat Materials către Jane_Smith
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
- Total playtime

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
- Promotion/demotion dates
- Time in each rank
- Current rank

**Examples**:
```
/rank_history identifier:12345
/rank_history identifier:John_Doe
```

---

## Faction Commands

### /faction

**Description**: List all members of a faction  
**Cooldown**: 30 seconds  
**Permissions**: Everyone

**Parameters**:
- `faction_name` (required): Name of faction

**Shows**:
- All members
- Ranks
- Levels
- Online status
- Paginated

**Examples**:
```
/faction faction_name:LSPD
/faction faction_name:Ballas
```

---

### /promotions

**Description**: Recent faction promotions  
**Cooldown**: 30 seconds  
**Permissions**: Everyone

**Parameters**:
- `days` (optional): Days to look back (default: 7, max: 30)

**Shows**:
- Recent rank changes
- Player names
- Old and new ranks
- Timestamps

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
- Duration
- Expiry date
- Paginated

**Examples**:
```
/bans
/bans show_expired:true
```

---

## Online Commands

### /online

**Description**: Current online players  
**Cooldown**: 10 seconds  
**Permissions**: Everyone

**Shows**:
- All online players
- Player IDs
- Last seen times
- Paginated

**Example**:
```
/online
```

---

## Admin Commands

⚠️ These commands require admin permissions (ADMIN_USER_IDS)

### /cleanup_old_data

**Description**: Remove old data based on retention policy  
**Cooldown**: 300 seconds (5 minutes)  
**Permissions**: Admin only

**Parameters**:
- `dry_run` (optional): Preview without deleting (default: true)
- `confirm` (optional): Must be true to actually delete (default: false)

**Safety**:
- Requires both `dry_run=false` AND `confirm=true` to delete
- Shows preview first
- Uses configured retention policies

**Examples**:
```
# Preview what will be deleted
/cleanup_old_data dry_run:true

# Actually delete (requires confirmation)
/cleanup_old_data dry_run:false confirm:true
```

**Output**:
```
🗑️ CLEANUP EXECUTED - Data Cleanup

Actions
Deleted: 45,231
Retention: 90 days

Login Events
Deleted: 128,492
Retention: 30 days

Profile History
Deleted: 8,721
Retention: 180 days

✅ Cleanup completed successfully
```

---

### /backup_database

**Description**: Create database backup  
**Cooldown**: 300 seconds (5 minutes)  
**Permissions**: Admin only

**Creates**:
- Timestamped backup file
- Stored in configured backup directory
- Shows file size and location

**Example**:
```
/backup_database
```

**Output**:
```
✅ Database Backup Created

Backup File
pro4kings_backup_20260118_170000.db

Size
127.45 MB

Location
/data/backups

Total backups: 8
```

**Best practices**:
- Backup before cleanup
- Backup before major updates
- Keep recent backups
- Test restore process

---

## Debug Commands

### !p4k sync

**Description**: Force sync slash commands (emergency)  
**Type**: Prefix command (not slash)  
**Permissions**: Everyone

**When to use**:
- Slash commands not showing
- After bot restart
- After adding new commands

**Example**:
```
!p4k sync
```

**Output**:
```
🔄 Sincronizare forțată comenzi slash...
✅ Succes! Sincronizate 25 comenzi
```

---

## Command Cooldowns

| Command | Cooldown | Admin Bypass |
|---------|----------|-------------|
| `/health` | 10s | Yes |
| `/config` | 30s | Yes |
| `/stats` | 10s | Yes |
| `/player` | 5s | Yes |
| `/search` | 10s | Yes |
| `/actions` | 30s | Yes |
| `/sessions` | 10s | Yes |
| `/rank_history` | 10s | Yes |
| `/faction` | 30s | Yes |
| `/promotions` | 30s | Yes |
| `/bans` | 30s | Yes |
| `/online` | 10s | Yes |
| `/cleanup_old_data` | 300s | No |
| `/backup_database` | 300s | No |

**Note**: Admin users bypass most cooldowns, except safety-critical commands.

---

## Pagination Controls

Commands with multiple results use pagination:

- ⏮️ **First Page**: Jump to first page
- ◀️ **Previous**: Go to previous page
- ▶️ **Next**: Go to next page
- ⏭️ **Last Page**: Jump to last page
- 🗑️ **Delete**: Delete the message

**Auto-disable**: Buttons disable after 3 minutes of inactivity

---

## Error Messages

### Common Errors

**Cooldown**:
```
⏳ This command is on cooldown. Try again in 25 seconds.
```

**Permission Denied**:
```
❌ Access Denied
This command is restricted to bot administrators.
```

**Database Busy**:
```
⏳ Database Busy

The database is currently processing other operations.
Please try again in a few moments.
```

**Not Found**:
```
🔍 Not Found

The requested resource could not be found.
Please check your input and try again.
```

---

## Tips & Tricks

### Efficient Searching

```
# Search by partial name
/search query:John

# Search by ID (exact)
/player identifier:12345

# Get recent activity
/actions identifier:12345 days:7
```

### Monitoring

```
# Quick health check
/health

# Detailed stats
/stats

# Current configuration
/config
```

### Maintenance

```
# 1. Check database size
/stats

# 2. Create backup
/backup_database

# 3. Preview cleanup
/cleanup_old_data dry_run:true

# 4. Execute cleanup
/cleanup_old_data dry_run:false confirm:true

# 5. Verify
/stats
```

---

## Related Documentation

- [DEPLOYMENT.md](DEPLOYMENT.md) - Railway deployment
- [CONFIGURATION.md](CONFIGURATION.md) - Environment variables
- [README.md](README.md) - General overview

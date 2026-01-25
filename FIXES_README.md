# Database and CSV Import Fixes

## 🐞 Issues Fixed

### Issue 1: Username Conflict Warning

**Problem:**
```
WARNING:database:Username 'Razvan' exists with different ID. Existing: 167047, New: 213767. Updating existing record.
```

**Root Cause:**
- The database schema had a `UNIQUE(username)` constraint
- The code was treating usernames as unique identifiers
- **Multiple players can have the same name with different player IDs**
- This caused the system to incorrectly update existing player records when it found duplicate names

**Solution:**
1. ✅ Removed `UNIQUE(username)` constraint from the schema
2. ✅ Fixed `_mark_player_for_update_sync()` to only use `player_id` as the unique identifier
3. ✅ Fixed SQL syntax error (trailing comma in CREATE TABLE statement)

### Issue 2: Imported CSV Data Not Visible

**Problem:**
- Data imported from `player_profiles.csv` was not showing up in `/stats` command

**Root Cause:**
- CSV had extra columns (`last_checked`, `check_priority`) that weren't in the database schema
- Import script wasn't properly handling these extra columns
- Potential database path mismatch between import script and bot

**Solution:**
1. ✅ Updated `import_csv_profiles.py` to handle extra CSV columns
2. ✅ Added validation to check for missing required columns
3. ✅ Added better error handling and logging
4. ✅ Import script now explicitly ignores `last_checked` and `check_priority` columns

---

## 📝 CSV Column Mapping

### CSV Columns (12 columns)
```
player_id, player_name, last_connection, is_online, 
faction, faction_rank, warns, job, played_hours, age_ic,
last_checked, check_priority
```

### Database Schema (14 columns)
```sql
CREATE TABLE player_profiles (
    player_id TEXT PRIMARY KEY,              -- From CSV: player_id
    username TEXT NOT NULL,                  -- From CSV: player_name
    is_online BOOLEAN DEFAULT FALSE,         -- From CSV: is_online
    last_seen TIMESTAMP,                     -- From CSV: last_connection
    first_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Profile fields
    faction TEXT,                            -- From CSV: faction
    faction_rank TEXT,                       -- From CSV: faction_rank
    job TEXT,                                -- From CSV: job
    warnings INTEGER,                        -- From CSV: warns
    played_hours REAL,                       -- From CSV: played_hours
    age_ic INTEGER,                          -- From CSV: age_ic
    
    -- Metadata (auto-generated)
    total_actions INTEGER DEFAULT 0,
    last_profile_update TIMESTAMP,
    priority_update BOOLEAN DEFAULT FALSE
)
```

### Ignored CSV Columns
- ❌ `last_checked` - Not used (handled by `last_profile_update` in DB)
- ❌ `check_priority` - Not used (handled by `priority_update` in DB)

### Previously Removed Columns
These columns were removed from the schema in a previous update:
- ❌ `level`
- ❌ `respect_points`
- ❌ `phone_number`
- ❌ `vehicles_count`
- ❌ `properties_count`

---

## 🚀 How to Apply Fixes

### Option 1: Fresh Start (New Database)

If you don't have important data yet:

```bash
# 1. Delete old database
rm pro4kings.db
# Or on Railway:
rm /data/pro4kings.db

# 2. Restart bot (it will create new database with correct schema)
python bot.py

# 3. Import CSV data
python import_csv_profiles.py player_profiles.csv
```

### Option 2: Migrate Existing Database (Preserves All Data)

If you have existing data to preserve:

```bash
# 1. Stop the bot first!
# CTRL+C or kill the process

# 2. Run migration script (creates automatic backup)
python migrate_fix_username_constraint.py

# 3. Import/re-import CSV data
python import_csv_profiles.py player_profiles.csv

# 4. Restart bot
python bot.py
```

### On Railway

If deployed on Railway:

```bash
# 1. SSH into Railway container
railway run bash

# 2. Run migration
python migrate_fix_username_constraint.py

# 3. Import CSV
python import_csv_profiles.py player_profiles.csv

# 4. Exit and redeploy
exit
```

Or trigger a redeploy to automatically use the new code.

---

## ✅ Verification

After applying fixes, verify everything works:

### 1. Check Import Success
```bash
python import_csv_profiles.py player_profiles.csv
```

You should see:
```
✅ Import complete!

📊 Statistics:
   Imported: 186,607
   Skipped: 0
   Errors: 0
   Success rate: 100%
```

### 2. Check Bot Stats Command

In Discord:
```
/stats
```

You should see the correct player count:
```
📊 Database Statistics

👥 Total Players: 186,607
📝 Total Actions: ...
🟢 Online Now: ...
```

### 3. Test Duplicate Usernames

Search for a common name:
```
/search Razvan
```

You should see multiple players with the same name but different IDs:
```
🔍 Search Results for 'Razvan'
Found 3 player(s)

Razvan (ID: 167047)
⚪ Offline
├ Faction: Politia Romana
└ Level: 45

Razvan (ID: 213767)
⚪ Offline
├ Faction: Civil
└ Level: 12

Razvan (ID: 98234)
🟢 Online
├ Faction: DIS
└ Level: 67
```

### 4. Check Logs

No more warnings like:
```
❌ WARNING:database:Username 'Razvan' exists with different ID. Existing: 167047, New: 213767. Updating existing record.
```

---

## 📚 Files Changed

### Modified Files

1. **[database.py](https://github.com/Apollomakesit/P4K-DBS/blob/main/database.py)**
   - ✅ Removed trailing comma in CREATE TABLE statement (line 70)
   - ✅ Removed `UNIQUE(username)` constraint
   - ✅ Fixed `_mark_player_for_update_sync()` method

2. **[import_csv_profiles.py](https://github.com/Apollomakesit/P4K-DBS/blob/main/import_csv_profiles.py)**
   - ✅ Added validation for required CSV columns
   - ✅ Added handling for extra CSV columns
   - ✅ Improved error handling and logging
   - ✅ Added row number tracking for errors

### New Files

3. **[migrate_fix_username_constraint.py](https://github.com/Apollomakesit/P4K-DBS/blob/main/migrate_fix_username_constraint.py)** (NEW)
   - ✅ Migration script to fix existing databases
   - ✅ Automatically creates backup before migration
   - ✅ Preserves all existing data
   - ✅ Validates data integrity

4. **[FIXES_README.md](https://github.com/Apollomakesit/P4K-DBS/blob/main/FIXES_README.md)** (NEW)
   - ✅ This documentation file

---

## 🔍 Technical Details

### Why Player ID is the Unique Identifier

**Player ID (`player_id`):**
- ✅ Guaranteed unique by the game server
- ✅ Never changes for a player
- ✅ Used in all game systems and URLs
- ✅ **This is the PRIMARY KEY**

**Username (`username`):**
- ❌ Can be changed by players
- ❌ Multiple players can have the same name
- ❌ Not guaranteed to be unique
- ❌ **Should NOT be a unique constraint**

### Database Schema Rules

```sql
-- ✅ CORRECT
player_id TEXT PRIMARY KEY,    -- Unique identifier
username TEXT NOT NULL,        -- Can have duplicates

-- ❌ INCORRECT (old schema)
player_id TEXT PRIMARY KEY,
username TEXT NOT NULL,
UNIQUE(username)  -- ❌ This was causing the problem!
```

---

## 🐛 Known Limitations

1. **Import Speed**: Large CSV files (186K+ rows) take 5-10 minutes
   - This is normal - the script logs progress every 100 rows
   - Don't interrupt the import process

2. **Faction Names**: CSV uses "Civil" for players without a faction
   - Import script automatically converts this to `NULL`
   - Same for empty strings, "None", "-", "Fără", "N/A"

3. **Date Formats**: CSV must use `YYYY-MM-DD HH:MM:SS` format
   - Example: `2026-01-13 12:15:57`
   - Invalid dates will use current timestamp

---

## 🆘 Support

If you encounter any issues:

1. Check the logs for error messages
2. Verify CSV file format matches expected columns
3. Ensure database path is correct (`/data/pro4kings.db` on Railway)
4. Check that bot and import script use the same database file

### Common Issues

**Issue: "Database is locked"**
- **Cause**: Bot is running while trying to import
- **Solution**: Stop the bot before running import/migration

**Issue: "CSV columns don't match"**
- **Cause**: CSV file has different column names
- **Solution**: Check CSV headers match: `player_id, player_name, last_connection, ...`

**Issue: "/stats shows 0 players"**
- **Cause**: Import script and bot using different database files
- **Solution**: Check paths - bot uses `/data/pro4kings.db` on Railway

---

## 📝 Changelog

### 2026-01-25 - Database Schema & Import Fixes

**Fixed:**
- ✅ Removed UNIQUE constraint on username field
- ✅ Fixed SQL syntax error (trailing comma)
- ✅ Fixed `_mark_player_for_update_sync()` to handle duplicate usernames
- ✅ Updated CSV import to handle extra columns
- ✅ Improved import error handling and logging

**Added:**
- ➕ Migration script for existing databases
- ➕ Comprehensive documentation
- ➕ CSV column validation

**Changed:**
- 🔄 Import script now explicitly lists expected vs actual CSV columns
- 🔄 Better logging with row numbers for debugging

---

## 🔗 Related Documentation

- [DATA_IMPORT_GUIDE.md](DATA_IMPORT_GUIDE.md) - Original import guide
- [SCHEMA_UPDATE_GUIDE.md](SCHEMA_UPDATE_GUIDE.md) - Schema changes history
- [README.md](README.md) - Main project documentation

---

**Last Updated:** 2026-01-25  
**Fix Version:** 1.0  
**Status:** ✅ Complete and Tested

# 🚀 Quick Import Guide - Fix Your 264 Player Issue

## Current Situation

❌ **Problem:** Only 264 players in database, expected ~225,000  
✅ **Solution:** Import your `player_profiles.csv` backup

---

## Your Database Schema (19 columns)

```
player_profiles table:
1. player_id (TEXT) - PRIMARY KEY
2. username (TEXT) - NOT NULL  
3. is_online (BOOLEAN)
4. last_seen (TIMESTAMP)
5. first_detected (TIMESTAMP)
6. faction (TEXT)
7. faction_rank (TEXT)
8. job (TEXT)
9. level (INTEGER)
10. respect_points (INTEGER)
11. warnings (INTEGER)
12. played_hours (REAL)
13. age_ic (INTEGER)
14. phone_number (TEXT)
15. vehicles_count (INTEGER)
16. properties_count (INTEGER)
17. total_actions (INTEGER)
18. last_profile_update (TIMESTAMP)
19. priority_update (BOOLEAN)
```

## Your CSV Has (10 columns)

```csv
player_id, player_name, last_connection, is_online, faction, 
faction_rank, warns, job, played_hours, age_ic
```

### Field Mappings

| CSV Column | Database Column | Notes |
|------------|----------------|-------|
| `player_id` | `player_id` | Primary key |
| `player_name` | `username` | NOT NULL |
| `last_connection` | `last_seen` | Datetime |
| `is_online` | `is_online` | Boolean |
| `faction` | `faction` | "Civil" filtered out |
| `faction_rank` | `faction_rank` | |
| `warns` | `warnings` | Integer |
| `job` | `job` | |
| `played_hours` | `played_hours` | Float |
| `age_ic` | `age_ic` | Integer |

**Missing fields** (will be set to NULL): `level`, `respect_points`, `phone_number`, `vehicles_count`, `properties_count`

---

## 📝 Step-by-Step Import

### Step 1: Prepare CSV File

1. Upload your `player_profiles.csv` to your Railway deployment:
   - Via Railway CLI: `railway run bash` then upload file
   - Or add to your repo and redeploy

2. Verify file format:
   ```bash
   head -n 2 player_profiles.csv
   ```
   
   Should show:
   ```
   player_id<TAB>player_name<TAB>last_connection<TAB>...
   1<TAB>M1NJA<TAB>2026-01-13 12:15:57<TAB>...
   ```

### Step 2: Run Import Script

**On Railway:**
```bash
# SSH into your Railway container
railway run bash

# Navigate to app directory (if needed)
cd /app

# Run import
python import_csv_profiles.py player_profiles.csv
```

**Locally (for testing):**
```bash
python import_csv_profiles.py player_profiles.csv
```

### Step 3: Monitor Progress

You'll see:
```
================================================================
📥 CSV Player Profile Importer
================================================================
CSV File: player_profiles.csv
Working Directory: /app
================================================================

INFO - Detected delimiter: TAB
INFO - CSV columns detected: ['player_id', 'player_name', ...]
INFO - 📊 Starting import...

INFO - ✓ Imported 1,000 profiles...
INFO - ✓ Imported 2,000 profiles...
...
INFO - ✓ Imported 186,000 profiles...

================================================================
✅ Import complete!

📊 Statistics:
   Imported: 186,607
   Skipped: 0
   Errors: 0
   Success rate: 100%
================================================================

💾 Database now has:
   Total players: 186,871
   Total actions: 54,968
   Currently online: 1,374

🏛️ Top 10 Factions by member count:
   1. Politia Romana: 823 members (45 online)
   2. Creep: 612 members (32 online)
   ...
```

### Step 4: Verify Import

Check `/stats` command in Discord:
```
/stats
```

Should now show:
```
📊 Pro4Kings Database Statistics
👥 Total Players: 186,871  ✅ (was 264)
📋 Total Actions: 54,968
🔥 Actions (24h): 48,415
...
```

---

## ⚠️ Troubleshooting

### Issue: "File not found"

**Solution:**
```bash
# Check current directory
pwd

# List files
ls -la

# If CSV is elsewhere, provide full path
python import_csv_profiles.py /data/player_profiles.csv
```

### Issue: "UnicodeDecodeError"

**Solution:** Ensure CSV is UTF-8 encoded
```bash
# Check file encoding
file -i player_profiles.csv

# Convert if needed (on Linux)
iconv -f ISO-8859-1 -t UTF-8 player_profiles.csv > player_profiles_utf8.csv
```

### Issue: "Database is locked"

**Solution:** Bot is running - import while bot is stopped, or use the import during low activity

### Issue: Many "Skipped" entries

**Cause:** Rows with empty `player_id` or `player_name`  
**Solution:** Check CSV for data quality issues

---

## 🔄 After Import

### Update Faction Ranks (Optional)

If your CSV is missing `faction_rank` data:

```bash
# Update faction ranks for first 100 players (test)
python update_faction_ranks.py 100

# If successful, update all
python update_faction_ranks.py
```

### Restart Bot

After import, restart your bot:
```bash
# On Railway
railway restart

# Or manually restart the container
```

The startup logs should now show:
```
INFO - 👥 Total Players: 186,871  ✅
INFO - 📋 Total Actions: 54,968
```

---

## 📊 Expected Results

| Metric | Before Import | After Import |
|--------|--------------|-------------|
| Total Players | 264 | ~186,607 |
| Players Table | 1,669 | (unchanged) |
| player_profiles | 264 | ~186,607 |
| Factions Visible | Few | All |
| `/stats` command | Shows 264 | Shows 186,607 |

---

## 🎯 Next Steps

1. ✅ Import CSV (this guide)
2. ✅ Verify `/stats` shows correct count
3. ✅ Test `/player <name>` command
4. ✅ Test `/faction <name>` command  
5. 🔄 Optional: Update faction ranks for accuracy
6. 🔄 Optional: Set up daily faction rank updates

---

## 📝 Notes

- Import uses `INSERT ... ON CONFLICT` - **safe to run multiple times**
- Existing data won't be duplicated
- Updates will overwrite if player_id already exists
- "Civil" faction is automatically filtered out (set to NULL)
- Special characters in names (like ✓®) are fully supported

You're all set! 🎉

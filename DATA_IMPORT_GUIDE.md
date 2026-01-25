# Data Import & Faction Rank Update Guide

This guide explains how to import your CSV player data and update faction ranks for players.

## Overview

You have successfully extracted `player_profiles.csv` from your backup database. This guide covers:

1. ✅ Importing the CSV data into your bot's database
2. ✅ Updating faction rank information by scraping player profiles
3. ✅ Scraping faction statistics from the factions page

---

## Step 1: Import CSV Data

### Prepare Your CSV File

1. Place your `player_profiles.csv` file in the root directory of your repository
2. Ensure it has UTF-8 encoding to support special characters like `samy✓®`

### Expected CSV Format

Your CSV should have these columns:
```csv
player_id,player_name,last_connection,is_online,faction,warns,job,played_hours,age_ic
```

**Note:** The `faction_rank` column is missing - that's okay! We'll populate it in Step 2.

### Run the Import Script

```bash
python import_csv_profiles.py
```

Or specify a custom CSV file:

```bash
python import_csv_profiles.py path/to/your_file.csv
```

### What Happens:

- ✅ Reads your CSV file with UTF-8 encoding (handles special characters)
- ✅ Parses datetime fields (`last_connection`)
- ✅ Filters out "Civil" faction players (sets faction to `None`)
- ✅ Saves all profiles to the database
- ✅ Shows progress every 100 profiles
- ✅ Displays final statistics

### Example Output:

```
INFO - CSV columns detected: ['player_id', 'player_name', 'last_connection', ...]
INFO - Imported 100 profiles...
INFO - Imported 200 profiles...
INFO - ✅ Import complete! Imported: 186607, Errors: 0
INFO - Database now has 186607 total players
```

---

## Step 2: Update Faction Ranks

Now that you have player data, update the missing `faction_rank` field by scraping individual profiles.

### Run the Faction Rank Update Script

**Update all faction players:**
```bash
python update_faction_ranks.py
```

**Update only first 100 players (for testing):**
```bash
python update_faction_ranks.py 100
```

### What Happens:

1. ✅ Queries database for all players in factions (excludes "Civil")
2. ✅ Groups players by faction for better visibility
3. ✅ Scrapes player profiles in batches of 50
4. ✅ Extracts `faction_rank` from each profile
5. ✅ Updates the database with the rank information
6. ✅ Shows detailed progress and statistics

### Example Output:

```
📊 Found 5234 players in factions
🎯 Will update 5234 players

📋 Players by faction:
  Politia Romana: 823 players
  Creep: 612 players
  DIS: 543 players
  ...

🔄 Processing batch 1/105
   Players 1-50 of 5234
   ✅ M1NJA (Politia Romana): Comisar
   ✅ Petrut (Creep): Member
   ⚠️  Zet (Creep): No rank found

📈 Progress: 50/5234 (0%)
   Updated: 48 | No rank: 2 | Errors: 0

...

✅ Faction rank update complete!

📊 Final Statistics:
   Total processed: 5234
   Successfully updated: 4987
   No rank found: 217
   Errors: 30
   Success rate: 95%
```

### Performance Notes:

- Uses 5 concurrent workers (conservative to avoid 503 errors)
- Processes 50 players per batch
- 1 second delay between batches
- Typical speed: ~200-300 players per minute
- Full scan of 5000 players: ~20-25 minutes

---

## Step 3: Scrape Faction Statistics (Optional)

Get faction member counts from the `/factions` page.

### Using the Scraper Directly

```python
import asyncio
from scraper import Pro4KingsScraper

async def test_factions():
    async with Pro4KingsScraper() as scraper:
        factions = await scraper.get_factions_info()
        
        print(f"Found {len(factions)} factions:\n")
        for faction in factions:
            print(f"  {faction['faction_name']}: {faction['member_count']} members")

asyncio.run(test_factions())
```

### Example Output:

```
Found 15 factions:

  Politia Romana: 823 members
  Creep: 612 members
  DIS: 543 members
  Sindicat: 421 members
  MG-13: 389 members
  ...
```

### Integration with Bot

You can add this to your bot's startup routine or create a scheduled task:

```python
# In bot.py or a new background task
@tasks.loop(hours=24)
async def update_faction_stats():
    """Update faction member counts every 24 hours"""
    async with Pro4KingsScraper() as scraper:
        factions = await scraper.get_factions_info()
        # Store in database or use for validation
        logger.info(f"Updated faction stats: {len(factions)} factions")
```

---

## Troubleshooting

### CSV Import Issues

**Problem:** `UnicodeDecodeError`
- **Solution:** Ensure CSV is UTF-8 encoded. Open in a text editor and save as UTF-8.

**Problem:** Missing columns
- **Solution:** Check CSV headers match expected format. The script will log detected columns.

**Problem:** Dates not parsing
- **Solution:** Ensure `last_connection` uses format `YYYY-MM-DD HH:MM:SS`

### Faction Rank Update Issues

**Problem:** Too many 503 errors
- **Solution:** The script uses conservative settings (5 workers). If you still get errors:
  ```python
  # In update_faction_ranks.py, line 61:
  async with Pro4KingsScraper(max_concurrent=3) as scraper:  # Reduce to 3
  ```

**Problem:** Rank not found for many players
- **Solution:** This is normal if:
  - Player profiles don't display rank
  - Player has default rank (Member, Rank 1, etc.)
  - Website structure changed
  
**Problem:** Script crashes mid-run
- **Solution:** Run with limited players first to test:
  ```bash
  python update_faction_ranks.py 50  # Test with 50 players
  ```

---

## Best Practices

### 🔄 Regular Updates

1. **Initial Import:** Run CSV import once to populate database
2. **Daily Faction Ranks:** Update faction ranks daily or weekly
3. **Faction Stats:** Scrape faction page stats every 24h on bot restart

### ⏱️ Scheduling

Add to your deployment environment (Railway, etc.):

```bash
# Run faction rank update weekly (cron job)
0 2 * * 0 cd /app && python update_faction_ranks.py
```

Or use bot commands:
```python
@commands.command()
@commands.has_permissions(administrator=True)
async def update_ranks(ctx):
    """Update faction ranks (Admin only)"""
    await ctx.send("🔄 Starting faction rank update...")
    # Run update_faction_ranks() async
    await ctx.send("✅ Update complete!")
```

### 🛡️ Data Validation

After import, verify data:

```python
from database import Database
import asyncio

async def verify_data():
    db = Database()
    stats = await db.get_database_stats()
    
    print(f"Total players: {stats['total_players']}")
    
    # Check faction distribution
    factions = await db.get_all_factions_with_counts()
    print(f"\nFactions with members:")
    for f in factions[:10]:
        print(f"  {f['faction_name']}: {f['member_count']} members")

asyncio.run(verify_data())
```

---

## Summary

✅ **Created Scripts:**
1. `import_csv_profiles.py` - Import CSV player data
2. `update_faction_ranks.py` - Update faction ranks from profiles
3. `scraper.py` - Enhanced with `get_factions_info()` method

✅ **Workflow:**
```
Extract CSV → Import to DB → Update Ranks → Scrape Faction Stats
```

✅ **Features:**
- Handles special characters in player names
- Filters out "Civil" faction
- Batch processing for efficiency
- Detailed progress tracking
- Error handling and retry logic
- Conservative rate limiting

You're all set! 🎉

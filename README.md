# P4K Database Bot

🤖 Advanced Discord bot for monitoring and tracking Pro4Kings Roleplay server data

## Features

✅ **Player Monitoring**
- Track online/offline status in real-time
- Monitor player actions from homepage
- Complete player profiles with stats
- Faction membership tracking with rank history

✅ **Action Tracking**
- Item transfers between players
- Chest deposits/withdrawals
- Admin warnings and reasons
- Vehicle/property transactions

✅ **Ban Management**
- Automatic ban list monitoring
- Ban expiry detection
- Admin and reason tracking

✅ **Session Tracking**
- Login/logout detection
- Session duration calculation
- Playing time statistics

## Installation

### Prerequisites
```bash
python 3.11+
sqlite3
discord.py
httpx
beautifulsoup4
```

### Setup

1. **Clone repository**
```bash
git clone https://github.com/Apollomakesit/P4K-DBS.git
cd P4K-DBS
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment**
```bash
export DISCORD_TOKEN="your_bot_token_here"
export DATABASE_PATH="pro4kings.db"  # Optional, defaults to pro4kings.db
```

4. **Run initial scan (IMPORTANT)**

Before starting the bot, you need to populate the database with player profiles:

```bash
python initial_scan.py
```

This will:
- Scan player IDs from 1 to 230,000
- Use 20 concurrent workers for speed (~2 hours)
- Skip non-existent player IDs automatically
- Save progress and can be resumed if interrupted
- Retry failed requests with exponential backoff

**Note**: The bot only tracks online players and players from actions. To have a complete database of ALL players, you must run the initial scan.

5. **Start the bot**
```bash
python bot.py
```

## Discord Commands

### Player Information
- `/player <id_or_name>` - Complete player profile
- `/search <name>` - Search players by name
- `/actions <id_or_name> [days]` - Player's recent actions
- `/sessions <id_or_name> [days]` - Player's gaming sessions
- `/rank_history <id_or_name>` - Faction rank history

### Faction Commands
- `/faction <faction_name>` - List all faction members
- `/promotions [days]` - Recent faction promotions

### Ban Commands
- `/bans [show_expired]` - View banned players

### General
- `/online` - Current online players
- `/stats` - Database statistics

## How It Works

### Background Tasks

1. **Action Scraper** (30s interval)
   - Monitors homepage for latest actions
   - Extracts player IDs from "Jucatorul Name(ID)" format
   - Marks players for profile updates

2. **Online Players** (60s interval)
   - Fetches /online page
   - Detects logins/logouts
   - Updates player status

3. **Profile Updater** (2min interval)
   - Updates profiles for active players
   - Fetches 200 profiles per cycle
   - Tracks faction, rank, level, warns, etc.

4. **Ban Checker** (1h interval)
   - Monitors /banlist page
   - Marks expired bans automatically
   - Tracks ban reasons and admins

### Database Schema

- **players** - Player profiles and stats
- **player_actions** - All player actions
- **player_sessions** - Login/logout tracking
- **rank_history** - Faction rank changes
- **online_players** - Current online snapshot
- **banned_players** - Ban records
- **scan_queue** - Profile update priorities

## Architecture

```
├── bot.py              # Discord bot with slash commands
├── database.py         # SQLite database wrapper
├── scraper.py          # Web scraping with async httpx
├── initial_scan.py     # Bulk profile scanner
└── pro4kings.db        # SQLite database
```

## Performance

- **Initial Scan**: ~2 hours for 230K player IDs (20 workers)
- **Bot Response**: <1 second for most commands
- **Memory Usage**: ~50-100MB
- **Database Size**: ~500MB after full scan

## Troubleshooting

### "Nu am găsit acțiuni pentru X"
- The player profile hasn't been scanned yet
- Run `/player <id>` to fetch their profile
- Or run `initial_scan.py` to scan all players

### "Nu am găsit membri în facțiunea X"
- Player profiles need to be scanned first
- Run `initial_scan.py` to populate the database
- The bot only tracks online players automatically

### Profile updates failing
- Check logs for rate limiting (503 errors)
- The scraper has exponential backoff built-in
- Restart the bot if needed - progress is saved

### Initial scan stopped
- Run `python initial_scan.py` again
- It will resume from where it left off
- Check `scan_progress.json` for status

## Important Notes

⚠️ **Rate Limiting**: The server may rate limit requests. The bot handles this with:
- Exponential backoff on 503 errors
- Configurable delays between requests
- Semaphore-based concurrency control

⚠️ **Database Growth**: The database will grow over time. Consider:
- Regular backups
- Pruning old actions (>30 days)
- Monitoring disk space

⚠️ **Initial Scan Required**: The bot does NOT automatically scan all players. You MUST run `initial_scan.py` to populate the database with historical player data.

## Version History

### v2.1 (January 2026)
- ✅ Fixed player search to prioritize ID lookups
- ✅ Added rank history tracking
- ✅ Added ban management with expiry detection
- ✅ Added recent promotions command
- ✅ Improved action parsing
- ✅ Better error handling and logging

### v2.0 (January 2026)
- Initial release with full monitoring
- Real-time action tracking
- Session management
- Faction tracking

## Contributing

Pull requests welcome! Please:
1. Test your changes thoroughly
2. Update documentation
3. Follow existing code style
4. Add comments for complex logic

## License

MIT License - See LICENSE file

## Credits

Developed by Apollo for Pro4Kings community

---

**Need help?** Open an issue on GitHub or contact Apollo on Discord
# Copilot Instructions for P4K-DBS

## Project Overview
- **Purpose:** Advanced Discord bot for monitoring and tracking Pro4Kings Roleplay server data.
- **Core Components:**
  - `bot.py`: Discord bot entrypoint, defines slash commands and orchestrates workflows.
  - `database.py`: SQLite wrapper, manages all persistent data (players, actions, sessions, bans, etc).
  - `scraper.py`: Async web scraper for homepage, online, and banlist data.
  - `initial_scan.py`: Bulk scanner to populate the database with all player profiles (must be run before bot usage for full data).

## Data Flow & Architecture
- **Scraping:**
  - `scraper.py` fetches and parses data from web endpoints at regular intervals (see README for task schedule).
  - Extracted data is written to the database via `database.py`.
- **Bot Commands:**
  - All Discord commands in `bot.py` read from the database, never scrape directly.
  - Player and faction data is always served from the local database for speed.
- **Initial Scan:**
  - `initial_scan.py` must be run to populate the database with all player profiles (IDs 1-230,000).
  - Scan is resumable and uses 20 concurrent workers for speed.

## Developer Workflows
- **Setup:**
  - Install dependencies: `pip install -r requirements.txt`
  - Set environment variables: `DISCORD_TOKEN`, `DATABASE_PATH` (optional)
  - Run `python initial_scan.py` before starting the bot for a complete database.
- **Run Bot:**
  - `python bot.py` (after initial scan)
- **Debugging:**
  - Logs are printed to stdout; check for rate limiting or scraping errors.
  - If initial scan is interrupted, rerun `python initial_scan.py` to resume.

## Project Conventions
- **Database is source of truth** for all bot commands—never scrape on-demand.
- **Concurrency:** Async scraping uses semaphores to avoid rate limits; exponential backoff on 503 errors.
- **Player data is only complete after initial scan**; otherwise, only online/active players are tracked.
- **Profile updates** are scheduled and batched (see README for intervals).
- **All commands are implemented as Discord slash commands** in `bot.py`.

## Integration Points
- **Discord API:** via `discord.py` (see `requirements.txt`)
- **Web scraping:** via `httpx` and `beautifulsoup4`
- **Database:** SQLite, schema managed in `database.py`

## Examples & Patterns
- To add a new command: define a new slash command in `bot.py` and ensure it reads from the database.
- To add a new data field: update `database.py` schema and scraping logic in `scraper.py`.
- For bulk data updates: use `initial_scan.py` pattern (concurrent, resumable, idempotent).

## References
- See [README.md](../README.md) for full setup, command list, and troubleshooting.
- Key files: `bot.py`, `database.py`, `scraper.py`, `initial_scan.py`, `requirements.txt`

---

If you are unsure about a workflow or data flow, check the README or the relevant script for examples. When in doubt, prefer reading from the database and following the established async scraping and command patterns.

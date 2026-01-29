# Copilot Instructions for P4K-DBS

## Big picture
- This is a Discord bot that scrapes Pro4Kings web pages, stores everything in SQLite, and serves slash commands from the database only. Scraping and command handling are intentionally separated.
- Core files: [bot.py](../bot.py) (startup + background tasks), [commands.py](../commands.py) (slash commands & UI views), [scraper.py](../scraper.py) (async web scraping), [database.py](../database.py) (SQLite access), [initial_scan.py](../initial_scan.py) (bulk bootstrap).

## Data flow & background tasks
- `bot.py` schedules recurring tasks for actions, online players, profile updates, bans, VIP/online-priority actions, and a watchdog. Tasks call `Pro4KingsScraper` and persist via `Database`.
- `commands.py` only reads from the database; **never scrape on-demand**.
- `scraper.py` uses `aiohttp` with a TokenBucket rate limiter, semaphores, and adaptive delays on 503/429.
- `initial_scan.py` is a resumable bulk scan (state in `scan_state.json`) using `batch_get_profiles()` for throughput.

## Developer workflows
- Setup: `pip install -r requirements.txt`; set `DISCORD_TOKEN` and (optional) `DATABASE_PATH`.
- Run once for a full DB: `python initial_scan.py` (resumable; do not kill if possible).
- Start bot: `python bot.py`.
- First startup migration: `bot.py` runs `migrate_db.migrate()` once and writes `/data/.migration_done`.

## Project conventions
- Database is the source of truth; all reads in `commands.py` go through `Database` in [database.py](../database.py).
- SQLite is configured for WAL and short busy timeouts; use `Database` methods rather than raw sqlite calls.
- Config comes from [config.py](../config.py); prefer `Config.*` values (intervals, rate limits, batch sizes, retention).

## Integrations
- Discord: `discord.py` slash commands and views live in [commands.py](../commands.py); `bot.py` wires them.
- Web scraping: `aiohttp` + `beautifulsoup4` against `https://panel.pro4kings.ro`.
- Storage: SQLite at `data/pro4kings.db` or `/data/pro4kings.db` when a Railway volume exists.

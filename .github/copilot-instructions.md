# Copilot Instructions for P4K-DBS

## Big picture
P4K-DBS is a **multi-component system** with intentional separation of concerns:

1. **Discord Bot** ([bot.py](../bot.py), [commands.py](../commands.py)) - Scrapes Pro4Kings web pages on background schedules, stores to SQLite, serves slash commands from database only (no on-demand scraping).
2. **Flask Dashboard** ([dashboard/app.py](../dashboard/app.py)) - Web UI (https://p4k-dbs-production.up.railway.app) with Flask REST API endpoints. Features event-driven profile auto-refresh using background thread pool.
3. **Shared SQLite Database** - WAL mode enables concurrent access by both bot and dashboard.
4. **Pro4KingsScraper** - Async module providing `get_player_profile()` integration point (used by both components).

Core files: [bot.py](../bot.py) (startup + background tasks), [commands.py](../commands.py) (slash commands), [dashboard/app.py](../dashboard/app.py) (Flask API + auto-refresh), [scraper.py](../scraper.py) (async scraping), [database.py](../database.py) (SQLite wrapper).

## Data flow & background tasks

**Discord Bot** ([bot.py](../bot.py)):
- Schedules recurring tasks: actions (5s), online players (60s), profile updates (2min), bans (1h), VIP actions (10min), watchdog (5min).
- Tasks call `Pro4KingsScraper` and persist via `Database.save_*()` methods.
- `commands.py` only reads from database; **never scrapes on-demand** in command handlers.

**Flask Dashboard** ([dashboard/app.py](../dashboard/app.py)):
- **Event-driven auto-refresh system** (lines 117-290): 4 trigger endpoints queue profile refreshes when accessed.
- Trigger endpoints: `/api/player/<id>`, `/api/faction/<name>`, `/api/online`, `/api/actions`.
- When endpoint accessed, if profile stale (>24h), queues refresh with `queue_profile_refresh(player_id, priority=True)`.
- Background ThreadPoolExecutor (3 workers) processes queue independently, fetches fresh profiles via `Pro4KingsScraper`, writes to SQLite.
- **Pattern**: Requests return immediately with available data + `'stale_profiles_queued'` metric; no blocking on scraper calls.

**Scraper** ([scraper.py](../scraper.py)):
- Uses `aiohttp` with TokenBucket rate limiter, adaptive delays on 503/429 errors.
- `batch_get_profiles()` fetches multiple profiles concurrently for efficiency.

**Bulk Bootstrap** ([initial_scan.py](../initial_scan.py)):
- Resumable scan (state in `scan_state.json`) using 8 workers, 200-ID batches.
- Scans 1-230K player IDs, skips 404s, retries 503s with backoff.

## Developer workflows
- Setup: `pip install -r requirements.txt`; set `DISCORD_TOKEN` and (optional) `DATABASE_PATH`.
- Discord bot: `python bot.py`; runs `migrate_db.migrate()` on first startup.
- Dashboard: `cd dashboard && python app.py`; Flask development server on `http://localhost:5000`.
- Initial scan: `python initial_scan.py` (resumable; don't kill if possible).
- Verify syntax: `python -m py_compile dashboard/app.py` before testing.
- Test auto-refresh: `curl -X POST http://localhost:5000/api/refresh-profile/183933` (manual) or `curl http://localhost:5000/api/refresh-status` (status).
- Feature toggle: `ENABLE_PROFILE_REFRESH=false` disables entire refresh system without code changes.

## Project conventions
- **Database is source of truth**: All reads via `Database` methods in [database.py](../database.py); no raw sqlite queries in Flask/bot code.
- **SQLite WAL + busy timeout**: Configured in [database.py](../database.py) for concurrent access; use `get_connection()` context manager.
- **Configuration**: Centralized in [config.py](../config.py); prefer `Config.*` values over hardcoded constants.
- **Event-driven queueing, not sync scraping**: When you need fresh data in Flask, queue a refresh via `queue_profile_refresh()` rather than blocking on scraper.
- **Async/sync bridge**: Dashboard uses `asyncio.run_until_complete()` to call async `Pro4KingsScraper` from sync Flask context.
- **Batch rate limiting**: Multiple refresh requests queued per endpoint call; individually queued items are deduplicated.
- **Feature toggles**: All new refresh features guarded by `if not PROFILE_REFRESH_ENABLED: return`; allows disabling without code changes.

## Integrations
- **Discord**: `discord.py` v2 slash commands/views in [commands.py](../commands.py); `bot.py` registers and wires commands.
- **Flask**: REST API endpoints in [dashboard/app.py](../dashboard/app.py); triggers auto-refresh on 4 endpoints.
- **Web scraping**: `aiohttp` + `beautifulsoup4` against `https://panel.pro4kings.ro` via `Pro4KingsScraper` in [scraper.py](../scraper.py).
- **Storage**: SQLite at `data/pro4kings.db` (local) or `/data/pro4kings.db` (Railway persistent volume); shared between bot + dashboard.
- **External API**: Both components call `Pro4KingsScraper.get_player_profile(player_id)` for fresh profiles (async).

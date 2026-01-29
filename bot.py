#!/usr/bin/env python3
"""
Pro4Kings Discord Bot - Database Monitor & Command Interface
"""

import discord
from discord.ext import commands, tasks
import os
import signal
import sys
from datetime import datetime, timedelta
from database import Database
from scraper import Pro4KingsScraper
from config import Config
import asyncio
import logging
import re
import tracemalloc
import psutil

import os
from datetime import datetime


async def run_migration_once():
    """Auto-run migration on first startup"""
    flag_file = "/data/.migration_done"

    if os.path.exists(flag_file):
        print("✅ Migration already completed")
        return

    print("\n" + "=" * 80)
    print("🔄 FIRST-TIME DATABASE MIGRATION")
    print("=" * 80)

    try:
        import migrate_db

        success = migrate_db.migrate()

        if success:
            with open(flag_file, "w") as f:
                f.write(f"Completed: {datetime.now()}\n")
            print("✅ Migration done!")
        else:
            print("⚠️ Migration incomplete, will retry on next restart")
    except Exception as e:
        print(f"⚠️ Migration error: {e}")
        import traceback

        traceback.print_exc()


# 🔥 SET UP LOGGING FIRST (before using logger)
tracemalloc.start()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

# 🔥 Validate configuration on startup
config_issues = Config.validate()
if config_issues:
    logger.error("❌ Configuration validation failed:")
    for issue in config_issues:
        logger.error(f"   • {issue}")
    if "DISCORD_TOKEN is not set" in config_issues:
        logger.error("❌ CRITICAL: Cannot start without DISCORD_TOKEN!")
        sys.exit(1)
    else:
        logger.warning("⚠️ Bot will start but some features may not work correctly")
else:
    logger.info("✅ Configuration validated successfully")

# Display configuration
logger.info(f"\n{'='*60}")
logger.info("📋 LOADED CONFIGURATION")
logger.info(f"{'='*60}")
logger.info(f"• VIP Players: {len(Config.VIP_PLAYER_IDS)}")
logger.info(f"• VIP Scan Interval: {Config.VIP_SCAN_INTERVAL}s")
logger.info(
    f"• Online Priority Tracking: {'Enabled' if Config.TRACK_ONLINE_PLAYERS_PRIORITY else 'Disabled'}"
)
logger.info(f"• Online Scan Interval: {Config.ONLINE_PLAYERS_SCAN_INTERVAL}s")
logger.info(f"• Scraper Workers: {Config.SCRAPER_MAX_CONCURRENT}")
logger.info(f"• Database: {Config.DATABASE_PATH}")
logger.info(f"{'='*60}\n")

# Global variables
COMMANDS_SYNCED = False
SYNC_LOCK = asyncio.Lock()
SCAN_IN_PROGRESS = False

SCAN_STATS = {
    "start_time": None,
    "scanned": 0,
    "found": 0,
    "errors": 0,
    "current_id": 0,
    "last_saved_id": 0,
}

TASK_HEALTH = {
    "scrape_actions": {"last_run": None, "is_running": False, "error_count": 0},
    "scrape_online_players": {"last_run": None, "is_running": False, "error_count": 0},
    "update_pending_profiles": {
        "last_run": None,
        "is_running": False,
        "error_count": 0,
    },
    "check_banned_players": {"last_run": None, "is_running": False, "error_count": 0},
    "update_missing_faction_ranks": {
        "last_run": None,
        "is_running": False,
        "error_count": 0,
    },
    "scrape_vip_actions": {"last_run": None, "is_running": False, "error_count": 0},
    "scrape_online_priority_actions": {
        "last_run": None,
        "is_running": False,
        "error_count": 0,
    },
    "cleanup_stale_data": {"last_run": None, "is_running": False, "error_count": 0},
    "task_watchdog": {"last_run": None, "is_running": False, "error_count": 0},
}

SHUTDOWN_REQUESTED = False

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!p4k ", intents=intents)

# Initialize database
db = Database(Config.DATABASE_PATH)
scraper: Pro4KingsScraper | None = None


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully"""
    global SHUTDOWN_REQUESTED
    logger.info(f"\n🛑 Shutdown signal received ({sig}), cleaning up...")
    SHUTDOWN_REQUESTED = True

    # Cancel all background tasks
    if scrape_actions.is_running():
        scrape_actions.cancel()
    if scrape_online_players.is_running():
        scrape_online_players.cancel()
    if update_pending_profiles.is_running():
        update_pending_profiles.cancel()
    if check_banned_players.is_running():
        check_banned_players.cancel()
    if scrape_vip_actions.is_running():
        scrape_vip_actions.cancel()
    if scrape_online_priority_actions.is_running():
        scrape_online_priority_actions.cancel()
    if cleanup_stale_data.is_running():
        cleanup_stale_data.cancel()
    if task_watchdog.is_running():
        task_watchdog.cancel()

    logger.info("✅ Background tasks stopped")

    # Properly close the scraper before shutting down
    async def cleanup_and_shutdown():
        if scraper:
            try:
                logger.info("🧹 Closing scraper client session...")
                await scraper.__aexit__(None, None, None)
                logger.info("✅ Scraper closed successfully")
            except Exception as e:
                logger.error(f"Error closing scraper: {e}")
        await bot.close()

    asyncio.create_task(cleanup_and_shutdown())


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def verify_environment():
    """Verify environment and dependencies"""
    issues = []

    db_path = Config.DATABASE_PATH
    db_dir = os.path.dirname(db_path) or "."

    if not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"✅ Created database directory: {db_dir}")
        except Exception as e:
            issues.append(f"Cannot create database directory {db_dir}: {e}")

    if not os.access(db_dir, os.W_OK):
        issues.append(f"Database directory {db_dir} is not writable!")

    if not Config.DISCORD_TOKEN:
        issues.append("DISCORD_TOKEN environment variable not set!")

    try:
        memory = psutil.virtual_memory()
        logger.info(
            f"📊 System: {memory.total / 1024**3:.1f}GB RAM, {memory.available / 1024**3:.1f}GB available"
        )
    except:
        pass

    if issues:
        logger.error("❌ ENVIRONMENT ISSUES:")
        for issue in issues:
            logger.error(f"   - {issue}")
        return False

    logger.info("✅ Environment verification passed")
    return True


async def get_or_recreate_scraper(max_concurrent=None):
    """Get or recreate scraper instance"""
    global scraper

    if max_concurrent and scraper and scraper.max_concurrent != max_concurrent:
        logger.info(
            f"🔄 Recreating scraper with max_concurrent={max_concurrent} (was {scraper.max_concurrent})"
        )
        try:
            await scraper.__aexit__(None, None, None)
        except:
            pass
        scraper = None

    if scraper is None:
        concurrent = max_concurrent if max_concurrent else Config.SCRAPER_MAX_CONCURRENT
        logger.info(f"🔄 Creating new scraper instance (max_concurrent={concurrent})...")
        scraper = Pro4KingsScraper(max_concurrent=concurrent)
        await scraper.__aenter__()
        logger.info(f"✅ Scraper initialized with {concurrent} workers")

    if scraper.client and scraper.client.closed:
        logger.warning("⚠️ Scraper client was closed, recreating...")
        try:
            await scraper.__aexit__(None, None, None)
        except:
            pass
        concurrent = max_concurrent if max_concurrent else Config.SCRAPER_MAX_CONCURRENT
        scraper = Pro4KingsScraper(max_concurrent=concurrent)
        await scraper.__aenter__()

    return scraper


# Import and setup slash commands
try:
    from commands import setup_commands

    setup_commands(bot, db, get_or_recreate_scraper)
    logger.info("✅ Slash commands module loaded")
except ImportError as e:
    logger.warning(f"⚠️ Could not import commands module: {e}")
    logger.warning("⚠️ Bot will run without slash commands")


@bot.event
async def on_ready():
    # Run migration automatically (only once)
    await run_migration_once()
    """Bot ready event"""
    global COMMANDS_SYNCED

    logger.info(f"✅ {bot.user} is now running!")

    if not verify_environment():
        logger.error("❌ Environment verification failed! Bot may not work correctly.")

    # 🔥 AUTO-IMPORT CSV DATA ON FIRST RUN (for Railway persistence)
    try:
        from import_on_startup import auto_import_on_startup

        await auto_import_on_startup()
    except ImportError:
        logger.debug("No import_on_startup module found, skipping CSV import")
    except Exception as e:
        logger.error(f"Error during CSV auto-import: {e}", exc_info=True)
        logger.warning("⚠️ Continuing without CSV import - database may be empty")

    await log_database_startup_info()
    await inspect_database_tables()

    # Sync slash commands
    async with SYNC_LOCK:
        if not COMMANDS_SYNCED:
            try:
                logger.info("🔄 Syncing slash commands...")
                synced = await bot.tree.sync()
                logger.info(f"✅ Synced {len(synced)} slash commands:")
                for cmd in synced:
                    logger.info(f"   - /{cmd.name}: {cmd.description}")
                COMMANDS_SYNCED = True
            except Exception as e:
                logger.error(f"❌ Failed to sync commands: {e}", exc_info=True)

    # Start background tasks
    if not scrape_actions.is_running():
        scrape_actions.start()
        logger.info(
            f"✓ Started: scrape_actions ({Config.SCRAPE_ACTIONS_INTERVAL}s interval)"
        )

    if not scrape_online_players.is_running():
        scrape_online_players.start()
        logger.info(
            f"✓ Started: scrape_online_players ({Config.SCRAPE_ONLINE_INTERVAL}s interval)"
        )

    if not update_pending_profiles.is_running():
        update_pending_profiles.start()
        logger.info(
            f"✓ Started: update_pending_profiles ({Config.UPDATE_PROFILES_INTERVAL}s interval)"
        )

    if not check_banned_players.is_running():
        check_banned_players.start()
        logger.info(
            f"✓ Started: check_banned_players ({Config.CHECK_BANNED_INTERVAL}s interval)"
        )

    if not update_missing_faction_ranks.is_running():
        update_missing_faction_ranks.start()
        logger.info("✓ Started: update_missing_faction_ranks (60min interval)")

    if Config.VIP_PLAYER_IDS and not scrape_vip_actions.is_running():
        scrape_vip_actions.start()
        logger.info(
            f"💎 Started: scrape_vip_actions ({Config.VIP_SCAN_INTERVAL}s interval, {len(Config.VIP_PLAYER_IDS)} VIP players)"
        )

    if (
        Config.TRACK_ONLINE_PLAYERS_PRIORITY
        and not scrape_online_priority_actions.is_running()
    ):
        scrape_online_priority_actions.start()
        logger.info(
            f"🟢 Started: scrape_online_priority_actions ({Config.ONLINE_PLAYERS_SCAN_INTERVAL}s interval)"
        )

    if not cleanup_stale_data.is_running():
        cleanup_stale_data.start()
        logger.info("✓ Started: cleanup_stale_data (10min interval)")

    if not task_watchdog.is_running():
        task_watchdog.start()
        logger.info(
            f"✓ Started: task_watchdog ({Config.TASK_WATCHDOG_INTERVAL}s interval)"
        )

    logger.info("🚀 All systems operational!")
    print(f'\n{"="*60}')
    print(f"✅ {bot.user} is ONLINE and monitoring Pro4Kings!")
    if Config.VIP_PLAYER_IDS:
        print(f"💎 VIP Tracking: {len(Config.VIP_PLAYER_IDS)} priority players")
    if Config.TRACK_ONLINE_PLAYERS_PRIORITY:
        print(
            f"🟢 Online Priority: Enabled ({Config.ONLINE_PLAYERS_SCAN_INTERVAL}s scan interval)"
        )
    print(f'{"="*60}\n')


async def log_database_startup_info():
    """Log database information on startup"""
    try:
        db_path = db.db_path
        logger.info("=" * 60)
        logger.info("📊 DATABASE STARTUP INFORMATION")
        logger.info("=" * 60)

        # File info
        if os.path.exists(db_path):
            file_size = os.path.getsize(db_path) / (1024 * 1024)  # MB
            logger.info(f"📁 Database file: {db_path}")
            logger.info(f"💾 File size: {file_size:.2f} MB")
        else:
            logger.warning(f"⚠️ Database file not found: {db_path}")
            return

        # Get stats
        stats = await db.get_database_stats()
        total_players = stats.get("total_players", 0)
        total_actions = stats.get("total_actions", 0)
        online_count = stats.get("online_count", 0)

        logger.info(f"👥 Total Players: {total_players:,}")
        logger.info(f"📝 Total Actions: {total_actions:,}")
        logger.info(f"🟢 Online Now: {online_count:,}")

        # Recent activity
        actions_24h = await db.get_actions_count_last_24h()
        logins_today = await db.get_logins_count_today()
        banned_count = await db.get_active_bans_count()

        logger.info(f"📈 Actions (24h): {actions_24h:,}")
        logger.info(f"🔑 Logins Today: {logins_today:,}")
        logger.info(f"🚫 Active Bans: {banned_count:,}")

        # Check if data was imported
        if total_players == 0:
            logger.warning("⚠️ WARNING: No players in database!")
        elif total_players < 1000:
            logger.warning(f"⚠️ WARNING: Only {total_players:,} players found!")
        else:
            logger.info(
                f"✅ Database successfully loaded with {total_players:,} players!"
            )

        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ Error logging database info: {e}", exc_info=True)


async def inspect_database_tables():
    """Inspect database tables to debug import issues"""
    try:
        import sqlite3

        logger.info("=" * 60)
        logger.info("🔍 DATABASE TABLE INSPECTION")
        logger.info("=" * 60)

        def _inspect_sync():
            conn = sqlite3.connect(db.db_path)
            cursor = conn.cursor()

            # Get all tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            logger.info(f"📋 Found {len(tables)} tables:")
            for table in tables:
                logger.info(f"   - {table}")

            # Check for both 'players' and 'player_profiles'
            for table_name in ["players", "player_profiles"]:
                cursor.execute(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"
                )
                if cursor.fetchone():
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    logger.info(f"✅ '{table_name}' table exists with {count:,} records")
                else:
                    logger.info(f"❌ '{table_name}' table does NOT exist")

            # Get player_profiles schema
            if "player_profiles" in tables:
                cursor.execute("PRAGMA table_info(player_profiles)")
                columns = cursor.fetchall()
                logger.info(f"📊 player_profiles schema ({len(columns)} columns):")
                for col in columns[:5]:  # Show first 5 columns
                    logger.info(f"   - {col[1]} ({col[2]})")

            conn.close()

        await asyncio.to_thread(_inspect_sync)
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ Error inspecting database: {e}", exc_info=True)


# ============================================================================
# BACKGROUND TASKS
# ============================================================================


@tasks.loop(minutes=10)
async def cleanup_stale_data():
    """Cleanup stale online player entries every 10 minutes"""
    if SHUTDOWN_REQUESTED:
        return

    TASK_HEALTH["cleanup_stale_data"]["last_run"] = datetime.now()
    TASK_HEALTH["cleanup_stale_data"]["is_running"] = True

    try:
        removed = await db.cleanup_stale_online_players(minutes=5)
        if removed > 0:
            logger.info(
                f"🧹 Cleaned up {removed} stale online entries (older than 5 min)"
            )
        TASK_HEALTH["cleanup_stale_data"]["error_count"] = 0
    except Exception as e:
        TASK_HEALTH["cleanup_stale_data"]["error_count"] += 1
        logger.error(f"❌ Error in cleanup task: {e}", exc_info=True)
    finally:
        TASK_HEALTH["cleanup_stale_data"]["is_running"] = False


@cleanup_stale_data.before_loop
async def before_cleanup_stale_data():
    await bot.wait_until_ready()
    logger.info("✓ cleanup_stale_data task ready")


@cleanup_stale_data.error
async def cleanup_stale_data_error(_loop, error):
    logger.error(f"❌ cleanup_stale_data task error: {error}", exc_info=error)
    TASK_HEALTH["cleanup_stale_data"]["error_count"] += 1


@tasks.loop(seconds=Config.TASK_WATCHDOG_INTERVAL)
async def task_watchdog():
    """Monitor task health and restart crashed tasks"""
    if SHUTDOWN_REQUESTED:
        return

    TASK_HEALTH["task_watchdog"]["last_run"] = datetime.now()
    TASK_HEALTH["task_watchdog"]["is_running"] = True

    try:
        now = datetime.now()
        issues = []

        # Check scrape_actions
        if TASK_HEALTH["scrape_actions"]["last_run"]:
            elapsed = (now - TASK_HEALTH["scrape_actions"]["last_run"]).total_seconds()
            max_delay = (
                Config.SCRAPE_ACTIONS_INTERVAL
                * Config.TASK_HEALTH_CHECK_MULTIPLIER.get("scrape_actions", 4)
            )
            if elapsed > max_delay:
                if not TASK_HEALTH["scrape_actions"]["is_running"]:
                    issues.append(f"scrape_actions hasn't run in {elapsed:.0f}s")
                    if not scrape_actions.is_running():
                        logger.warning("🔄 Restarting crashed task: scrape_actions")
                        scrape_actions.restart()

        # Check scrape_online_players
        if TASK_HEALTH["scrape_online_players"]["last_run"]:
            elapsed = (
                now - TASK_HEALTH["scrape_online_players"]["last_run"]
            ).total_seconds()
            max_delay = (
                Config.SCRAPE_ONLINE_INTERVAL
                * Config.TASK_HEALTH_CHECK_MULTIPLIER.get("scrape_online_players", 3)
            )
            if elapsed > max_delay:
                if not TASK_HEALTH["scrape_online_players"]["is_running"]:
                    issues.append(f"scrape_online_players hasn't run in {elapsed:.0f}s")
                    if not scrape_online_players.is_running():
                        logger.warning(
                            "🔄 Restarting crashed task: scrape_online_players"
                        )
                        scrape_online_players.restart()

        # Check update_pending_profiles
        if TASK_HEALTH["update_pending_profiles"]["last_run"]:
            elapsed = (
                now - TASK_HEALTH["update_pending_profiles"]["last_run"]
            ).total_seconds()
            max_delay = (
                Config.UPDATE_PROFILES_INTERVAL
                * Config.TASK_HEALTH_CHECK_MULTIPLIER.get("update_pending_profiles", 3)
            )
            if elapsed > max_delay:
                if not TASK_HEALTH["update_pending_profiles"]["is_running"]:
                    issues.append(
                        f"update_pending_profiles hasn't run in {elapsed:.0f}s"
                    )
                    if not update_pending_profiles.is_running():
                        logger.warning(
                            "🔄 Restarting crashed task: update_pending_profiles"
                        )
                        update_pending_profiles.restart()

        # Check VIP actions task
        if Config.VIP_PLAYER_IDS and TASK_HEALTH["scrape_vip_actions"]["last_run"]:
            elapsed = (
                now - TASK_HEALTH["scrape_vip_actions"]["last_run"]
            ).total_seconds()
            max_delay = (
                Config.VIP_SCAN_INTERVAL
                * Config.TASK_HEALTH_CHECK_MULTIPLIER.get("scrape_vip_actions", 5)
            )
            if elapsed > max_delay:
                if not TASK_HEALTH["scrape_vip_actions"]["is_running"]:
                    issues.append(f"scrape_vip_actions hasn't run in {elapsed:.0f}s")
                    if not scrape_vip_actions.is_running():
                        logger.warning("🔄 Restarting crashed task: scrape_vip_actions")
                        scrape_vip_actions.restart()

        # Check online priority task
        if (
            Config.TRACK_ONLINE_PLAYERS_PRIORITY
            and TASK_HEALTH["scrape_online_priority_actions"]["last_run"]
        ):
            elapsed = (
                now - TASK_HEALTH["scrape_online_priority_actions"]["last_run"]
            ).total_seconds()
            max_delay = (
                Config.ONLINE_PLAYERS_SCAN_INTERVAL
                * Config.TASK_HEALTH_CHECK_MULTIPLIER.get(
                    "scrape_online_priority_actions", 5
                )
            )
            if elapsed > max_delay:
                if not TASK_HEALTH["scrape_online_priority_actions"]["is_running"]:
                    issues.append(
                        f"scrape_online_priority_actions hasn't run in {elapsed:.0f}s"
                    )
                    if not scrape_online_priority_actions.is_running():
                        logger.warning(
                            "🔄 Restarting crashed task: scrape_online_priority_actions"
                        )
                        scrape_online_priority_actions.restart()

        if issues:
            logger.warning(f"⚠️ Task health issues detected: {', '.join(issues)}")
        else:
            logger.debug("✅ All background tasks healthy")

        TASK_HEALTH["task_watchdog"]["error_count"] = 0

    except Exception as e:
        TASK_HEALTH["task_watchdog"]["error_count"] += 1
        logger.error(f"❌ Error in task_watchdog: {e}", exc_info=True)
    finally:
        TASK_HEALTH["task_watchdog"]["is_running"] = False


@task_watchdog.before_loop
async def before_task_watchdog():
    await bot.wait_until_ready()
    await asyncio.sleep(120)  # Wait 2 minutes before first check


@tasks.loop(seconds=Config.SCRAPE_ACTIONS_INTERVAL)
async def scrape_actions():
    """Scrape latest player actions from the panel"""
    if SHUTDOWN_REQUESTED:
        return

    TASK_HEALTH["scrape_actions"]["last_run"] = datetime.now()
    TASK_HEALTH["scrape_actions"]["is_running"] = True

    try:
        scraper_instance = await get_or_recreate_scraper()
        logger.info("🔍 Fetching latest actions...")
        actions = await scraper_instance.get_latest_actions(
            limit=Config.ACTIONS_FETCH_LIMIT
        )

        if not actions:
            logger.warning("⚠️ No actions retrieved this cycle")
            TASK_HEALTH["scrape_actions"]["error_count"] += 1
            return

        new_count = 0
        new_player_ids = set()

        for action in actions:
            action_dict = {
                "player_id": action.player_id,
                "player_name": action.player_name,
                "action_type": action.action_type,
                "action_detail": action.action_detail,
                "item_name": action.item_name,
                "item_quantity": action.item_quantity,
                "target_player_id": action.target_player_id,
                "target_player_name": action.target_player_name,
                "admin_id": action.admin_id,
                "admin_name": action.admin_name,
                "warning_count": action.warning_count,
                "reason": action.reason,
                "timestamp": action.timestamp,
                "raw_text": action.raw_text,
            }

            if not await db.action_exists(action.timestamp, action.raw_text):
                await db.save_action(action_dict)
                new_count += 1

                if action.player_id:
                    player_name = action.player_name or f"Player_{action.player_id}"
                    new_player_ids.add((action.player_id, player_name))
                    await db.mark_player_for_update(action.player_id, player_name)

                if action.target_player_id:
                    target_name = (
                        action.target_player_name
                        or f"Player_{action.target_player_id}"
                    )
                    new_player_ids.add((action.target_player_id, target_name))
                    await db.mark_player_for_update(
                        action.target_player_id, target_name
                    )

        if new_count > 0:
            logger.info(
                f"✅ Saved {new_count} new actions, marked {len(new_player_ids)} players for update"
            )
            TASK_HEALTH["scrape_actions"]["error_count"] = 0
        else:
            logger.info(f"ℹ️ No new actions (checked {len(actions)} entries)")

    except Exception as e:
        TASK_HEALTH["scrape_actions"]["error_count"] += 1
        logger.error(
            f"❌ Error in scrape_actions (count: {TASK_HEALTH['scrape_actions']['error_count']}): {e}",
            exc_info=True,
        )

        if TASK_HEALTH["scrape_actions"]["error_count"] >= 5:
            logger.warning("⚠️ Too many errors, recreating scraper client...")
            global scraper
            try:
                if scraper:
                    await scraper.__aexit__(None, None, None)
            except:
                pass
            scraper = None
            TASK_HEALTH["scrape_actions"]["error_count"] = 0

    finally:
        TASK_HEALTH["scrape_actions"]["is_running"] = False


@scrape_actions.before_loop
async def before_scrape_actions():
    await bot.wait_until_ready()
    logger.info("✓ scrape_actions task ready")


@scrape_actions.error
async def scrape_actions_error(_loop, error):
    logger.error(f"❌ scrape_actions task error: {error}", exc_info=error)
    TASK_HEALTH["scrape_actions"]["error_count"] += 1


@tasks.loop(seconds=Config.VIP_SCAN_INTERVAL)
async def scrape_vip_actions():
    """Scrape actions for VIP players"""
    if SHUTDOWN_REQUESTED:
        return

    if not Config.VIP_PLAYER_IDS:
        return

    TASK_HEALTH["scrape_vip_actions"]["last_run"] = datetime.now()
    TASK_HEALTH["scrape_vip_actions"]["is_running"] = True

    try:
        scraper_instance = await get_or_recreate_scraper()
        vip_ids = set(Config.VIP_PLAYER_IDS)
        vip_actions = await scraper_instance.get_vip_actions(
            vip_ids, limit=Config.ACTIONS_FETCH_LIMIT
        )

        if vip_actions:
            new_count = 0
            new_player_ids = set()

            for action in vip_actions:
                action_dict = {
                    "player_id": action.player_id,
                    "player_name": action.player_name,
                    "action_type": action.action_type,
                    "action_detail": action.action_detail,
                    "item_name": action.item_name,
                    "item_quantity": action.item_quantity,
                    "target_player_id": action.target_player_id,
                    "target_player_name": action.target_player_name,
                    "admin_id": action.admin_id,
                    "admin_name": action.admin_name,
                    "warning_count": action.warning_count,
                    "reason": action.reason,
                    "timestamp": action.timestamp,
                    "raw_text": action.raw_text,
                }

                if not await db.action_exists(action.timestamp, action.raw_text):
                    await db.save_action(action_dict)
                    new_count += 1

                    if action.player_id:
                        player_name = action.player_name or f"Player_{action.player_id}"
                        new_player_ids.add((action.player_id, player_name))
                        await db.mark_player_for_update(action.player_id, player_name)

                    if action.target_player_id:
                        target_name = (
                            action.target_player_name
                            or f"Player_{action.target_player_id}"
                        )
                        new_player_ids.add((action.target_player_id, target_name))
                        await db.mark_player_for_update(
                            action.target_player_id, target_name
                        )

            if new_count > 0:
                logger.info(
                    f"💎 VIP Scan: {new_count} new VIP actions saved, {len(new_player_ids)} players marked for update"
                )
                TASK_HEALTH["scrape_vip_actions"]["error_count"] = 0

    except Exception as e:
        TASK_HEALTH["scrape_vip_actions"]["error_count"] += 1
        logger.error(
            f"❌ VIP scan failed (count: {TASK_HEALTH['scrape_vip_actions']['error_count']}): {e}",
            exc_info=True,
        )

    finally:
        TASK_HEALTH["scrape_vip_actions"]["is_running"] = False


@scrape_vip_actions.before_loop
async def before_scrape_vip_actions():
    await bot.wait_until_ready()
    logger.info("💎 scrape_vip_actions task ready")


@scrape_vip_actions.error
async def scrape_vip_actions_error(_loop, error):
    logger.error(f"❌ scrape_vip_actions task error: {error}", exc_info=error)
    TASK_HEALTH["scrape_vip_actions"]["error_count"] += 1


@tasks.loop(seconds=Config.ONLINE_PLAYERS_SCAN_INTERVAL)
async def scrape_online_priority_actions():
    """Scrape actions for currently online players"""
    if SHUTDOWN_REQUESTED:
        return

    if not Config.TRACK_ONLINE_PLAYERS_PRIORITY:
        return

    TASK_HEALTH["scrape_online_priority_actions"]["last_run"] = datetime.now()
    TASK_HEALTH["scrape_online_priority_actions"]["is_running"] = True

    try:
        online_players = await db.get_current_online_players()
        if not online_players:
            return

        online_ids = set(player["player_id"] for player in online_players)
        scraper_instance = await get_or_recreate_scraper()
        online_actions = await scraper_instance.get_online_player_actions(
            online_ids, limit=Config.ACTIONS_FETCH_LIMIT
        )

        if online_actions:
            new_count = 0
            new_player_ids = set()

            for action in online_actions:
                action_dict = {
                    "player_id": action.player_id,
                    "player_name": action.player_name,
                    "action_type": action.action_type,
                    "action_detail": action.action_detail,
                    "item_name": action.item_name,
                    "item_quantity": action.item_quantity,
                    "target_player_id": action.target_player_id,
                    "target_player_name": action.target_player_name,
                    "admin_id": action.admin_id,
                    "admin_name": action.admin_name,
                    "warning_count": action.warning_count,
                    "reason": action.reason,
                    "timestamp": action.timestamp,
                    "raw_text": action.raw_text,
                }

                if not await db.action_exists(action.timestamp, action.raw_text):
                    await db.save_action(action_dict)
                    new_count += 1

                    if action.player_id:
                        player_name = action.player_name or f"Player_{action.player_id}"
                        new_player_ids.add((action.player_id, player_name))
                        await db.mark_player_for_update(action.player_id, player_name)

                    if action.target_player_id:
                        target_name = (
                            action.target_player_name
                            or f"Player_{action.target_player_id}"
                        )
                        new_player_ids.add((action.target_player_id, target_name))
                        await db.mark_player_for_update(
                            action.target_player_id, target_name
                        )

            if new_count > 0:
                logger.info(
                    f"🟢 Online Priority: {new_count} new actions saved for {len(online_ids)} online players"
                )
                TASK_HEALTH["scrape_online_priority_actions"]["error_count"] = 0

    except Exception as e:
        TASK_HEALTH["scrape_online_priority_actions"]["error_count"] += 1
        logger.error(
            f"❌ Online priority scan failed (count: {TASK_HEALTH['scrape_online_priority_actions']['error_count']}): {e}",
            exc_info=True,
        )

    finally:
        TASK_HEALTH["scrape_online_priority_actions"]["is_running"] = False


@scrape_online_priority_actions.before_loop
async def before_scrape_online_priority_actions():
    await bot.wait_until_ready()
    logger.info("🟢 scrape_online_priority_actions task ready")


@scrape_online_priority_actions.error
async def scrape_online_priority_actions_error(_loop, error):
    logger.error(
        f"❌ scrape_online_priority_actions task error: {error}", exc_info=error
    )
    TASK_HEALTH["scrape_online_priority_actions"]["error_count"] += 1


@tasks.loop(seconds=Config.SCRAPE_ONLINE_INTERVAL)
async def scrape_online_players():
    """Scrape currently online players and detect logins/logouts"""
    if SHUTDOWN_REQUESTED:
        return

    TASK_HEALTH["scrape_online_players"]["last_run"] = datetime.now()
    TASK_HEALTH["scrape_online_players"]["is_running"] = True

    try:
        scraper_instance = await get_or_recreate_scraper()
        online_players = await scraper_instance.get_online_players()
        current_time = datetime.now()

        previous_online = await db.get_current_online_players()
        previous_ids = {p["player_id"] for p in previous_online}
        current_ids = {p["player_id"] for p in online_players}

        new_logins = current_ids - previous_ids

        for player in online_players:
            if player["player_id"] in new_logins:
                await db.save_login(
                    player["player_id"], player["player_name"], current_time
                )
                await db.mark_player_for_update(
                    player["player_id"], player["player_name"]
                )
                logger.info(
                    f"🟢 Login detected: {player['player_name']} ({player['player_id']})"
                )

        logouts = previous_ids - current_ids
        for player_id in logouts:
            await db.save_logout(player_id, current_time)
            logger.info(f"🔴 Logout detected: Player {player_id}")

        await db.update_online_players(online_players)

        for player in online_players:
            await db.mark_player_for_update(player["player_id"], player["player_name"])

        if new_logins or logouts:
            logger.info(
                f"👥 Online: {len(online_players)} | New: {len(new_logins)} | Left: {len(logouts)}"
            )
        else:
            logger.info(f"👥 Online players: {len(online_players)}")

        TASK_HEALTH["scrape_online_players"]["error_count"] = 0

    except Exception as e:
        TASK_HEALTH["scrape_online_players"]["error_count"] += 1
        logger.error(f"✗ Error scraping online players: {e}", exc_info=True)

    finally:
        TASK_HEALTH["scrape_online_players"]["is_running"] = False


@scrape_online_players.before_loop
async def before_scrape_online_players():
    await bot.wait_until_ready()
    logger.info("✓ scrape_online_players task ready")


@scrape_online_players.error
async def scrape_online_players_error(_loop, error):
    logger.error(f"❌ scrape_online_players task error: {error}", exc_info=error)
    TASK_HEALTH["scrape_online_players"]["error_count"] += 1


@tasks.loop(seconds=Config.UPDATE_PROFILES_INTERVAL)
async def update_pending_profiles():
    """Update profiles of players marked for priority update"""
    if SHUTDOWN_REQUESTED:
        return

    TASK_HEALTH["update_pending_profiles"]["last_run"] = datetime.now()
    TASK_HEALTH["update_pending_profiles"]["is_running"] = True

    try:
        scraper_instance = await get_or_recreate_scraper()
        pending_ids = await db.get_players_pending_update(
            limit=Config.PROFILES_UPDATE_BATCH
        )

        if not pending_ids:
            return

        logger.info(f"🔄 Updating {len(pending_ids)} pending profiles...")
        results = await scraper_instance.batch_get_profiles(pending_ids)

        for profile in results:
            profile_dict = {
                "player_id": profile.player_id,
                "player_name": profile.username,
                "is_online": profile.is_online,
                "last_connection": profile.last_seen,
                "faction": profile.faction,
                "faction_rank": profile.faction_rank,
                "job": profile.job,
                "warns": profile.warnings,
                "played_hours": profile.played_hours,
                "age_ic": profile.age_ic,
            }
            await db.save_player_profile(profile_dict)
            await db.reset_player_priority(profile.player_id)

        logger.info(f"✓ Updated {len(results)}/{len(pending_ids)} profiles")
        TASK_HEALTH["update_pending_profiles"]["error_count"] = 0

    except Exception as e:
        TASK_HEALTH["update_pending_profiles"]["error_count"] += 1
        logger.error(f"✗ Error updating profiles: {e}", exc_info=True)

    finally:
        TASK_HEALTH["update_pending_profiles"]["is_running"] = False


@update_pending_profiles.before_loop
async def before_update_pending_profiles():
    await bot.wait_until_ready()
    logger.info("✓ update_pending_profiles task ready")


@update_pending_profiles.error
async def update_pending_profiles_error(_loop, error):
    logger.error(f"❌ update_pending_profiles task error: {error}", exc_info=error)
    TASK_HEALTH["update_pending_profiles"]["error_count"] += 1


@tasks.loop(minutes=60)
async def update_missing_faction_ranks():
    """Target players with factions but no faction_rank for updates"""
    if SHUTDOWN_REQUESTED:
        return

    TASK_HEALTH["update_missing_faction_ranks"]["last_run"] = datetime.now()
    TASK_HEALTH["update_missing_faction_ranks"]["is_running"] = True

    try:

        def _get_missing_ranks():
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT player_id
                    FROM player_profiles
                    WHERE faction IS NOT NULL
                    AND faction != ''
                    AND (faction_rank IS NULL OR faction_rank = '')
                    LIMIT 50
                """
                )
                return [row[0] for row in cursor.fetchall()]

        player_ids = await asyncio.to_thread(_get_missing_ranks)

        if player_ids:
            logger.info(
                f"🎯 Targeting {len(player_ids)} players with missing faction ranks"
            )
            for player_id in player_ids:
                await db.mark_player_for_update(player_id, f"Player_{player_id}")

        TASK_HEALTH["update_missing_faction_ranks"]["error_count"] = 0

    except Exception as e:
        TASK_HEALTH["update_missing_faction_ranks"]["error_count"] += 1
        logger.error(f"Error in update_missing_faction_ranks: {e}", exc_info=True)

    finally:
        TASK_HEALTH["update_missing_faction_ranks"]["is_running"] = False


@update_missing_faction_ranks.before_loop
async def before_update_missing_faction_ranks():
    await bot.wait_until_ready()
    logger.info("✓ update_missing_faction_ranks task ready")


@update_missing_faction_ranks.error
async def update_missing_faction_ranks_error(_loop, error):
    logger.error(f"❌ update_missing_faction_ranks task error: {error}", exc_info=error)
    TASK_HEALTH["update_missing_faction_ranks"]["error_count"] += 1


@tasks.loop(seconds=Config.CHECK_BANNED_INTERVAL)
async def check_banned_players():
    """Check and update banned players list"""
    if SHUTDOWN_REQUESTED:
        return

    TASK_HEALTH["check_banned_players"]["last_run"] = datetime.now()
    TASK_HEALTH["check_banned_players"]["is_running"] = True

    try:
        scraper_instance = await get_or_recreate_scraper()
        banned = await scraper_instance.get_banned_players()
        current_ban_ids = {ban["player_id"] for ban in banned if ban.get("player_id")}

        for ban_data in banned:
            await db.save_banned_player(ban_data)

        await db.mark_expired_bans(current_ban_ids)
        logger.info(f"✓ Updated {len(banned)} banned players")
        TASK_HEALTH["check_banned_players"]["error_count"] = 0

    except Exception as e:
        TASK_HEALTH["check_banned_players"]["error_count"] += 1
        logger.error(f"✗ Error checking banned players: {e}", exc_info=True)

    finally:
        TASK_HEALTH["check_banned_players"]["is_running"] = False


@check_banned_players.before_loop
async def before_check_banned_players():
    await bot.wait_until_ready()
    logger.info("✓ check_banned_players task ready")


@check_banned_players.error
async def check_banned_players_error(_loop, error):
    logger.error(f"❌ check_banned_players task error: {error}", exc_info=error)
    TASK_HEALTH["check_banned_players"]["error_count"] += 1


# ============================================================================
# COMMANDS
# ============================================================================


@bot.command(name="sync")
async def force_sync(ctx):
    """Force sync slash commands"""
    global COMMANDS_SYNCED
    try:
        await ctx.send("🔄 **Sincronizare forțată comenzi slash...**")
        COMMANDS_SYNCED = False
        synced = await bot.tree.sync()
        COMMANDS_SYNCED = True
        cmd_list = "\n".join([f"• `/{cmd.name}`: {cmd.description}" for cmd in synced])
        await ctx.send(f"✅ **Succes! Sincronizate {len(synced)} comenzi:**\n{cmd_list}")
        logger.info(f"✅ Force sync completed by {ctx.author}: {len(synced)} commands")
    except Exception as e:
        await ctx.send(f"❌ **Eroare la sincronizare**: {str(e)}")
        logger.error(f"Force sync error: {e}", exc_info=True)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    TOKEN = Config.DISCORD_TOKEN

    if not TOKEN:
        logger.error("❌ ERROR: DISCORD_TOKEN not found in environment variables!")
        exit(1)

    logger.info("🚀 Starting Pro4Kings Database Bot...")

    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        logger.info("\n👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
    finally:
        logger.info("🛑 Bot shutdown complete")

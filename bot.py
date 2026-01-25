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

from commands import setup_commands

tracemalloc.start()

COMMANDS_SYNCED = False
SYNC_LOCK = asyncio.Lock()

SCAN_IN_PROGRESS = False
SCAN_STATS = {
    'start_time': None,
    'scanned': 0,
    'found': 0,
    'errors': 0,
    'current_id': 0,
    'last_saved_id': 0
}

TASK_HEALTH = {
    'scrape_actions': {'last_run': None, 'error_count': 0, 'is_running': False},
    'scrape_online_players': {'last_run': None, 'error_count': 0, 'is_running': False},
    'update_pending_profiles': {'last_run': None, 'error_count': 0, 'is_running': False},
    'check_banned_players': {'last_run': None, 'error_count': 0, 'is_running': False},
    'scrape_vip_actions': {'last_run': None, 'error_count': 0, 'is_running': False},
    'scrape_online_priority_actions': {'last_run': None, 'error_count': 0, 'is_running': False}
}

SHUTDOWN_REQUESTED = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!p4k ', intents=intents)

db = Database(os.getenv('DATABASE_PATH', 'pro4kings.db'))
scraper = None

def signal_handler(sig, frame):
    global SHUTDOWN_REQUESTED
    logger.info(f"\n🛑 Shutdown signal received ({sig}), cleaning up...")
    SHUTDOWN_REQUESTED = True
    
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
    
    logger.info("✅ Background tasks stopped")
    asyncio.create_task(bot.close())

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def verify_environment():
    issues = []
    
    db_path = os.getenv('DATABASE_PATH', 'pro4kings.db')
    db_dir = os.path.dirname(db_path) or '.'
    
    if not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"✅ Created database directory: {db_dir}")
        except Exception as e:
            issues.append(f"Cannot create database directory {db_dir}: {e}")
    
    if not os.access(db_dir, os.W_OK):
        issues.append(f"Database directory {db_dir} is not writable!")
    
    if not os.getenv('DISCORD_TOKEN'):
        issues.append("DISCORD_TOKEN environment variable not set!")
    
    try:
        memory = psutil.virtual_memory()
        logger.info(f"📊 System: {memory.total / 1024**3:.1f}GB RAM, {memory.available / 1024**3:.1f}GB available")
    except:
        pass
    
    if issues:
        logger.error("❌ ENVIRONMENT ISSUES:")
        for issue in issues:
            logger.error(f"  - {issue}")
        return False
    
    logger.info("✅ Environment verification passed")
    return True

async def get_or_recreate_scraper(max_concurrent=None):
    global scraper
    
    if max_concurrent and scraper and scraper.max_concurrent != max_concurrent:
        logger.info(f"🔄 Recreating scraper with max_concurrent={max_concurrent} (was {scraper.max_concurrent})")
        try:
            await scraper.__aexit__(None, None, None)
        except:
            pass
        scraper = None
    
    if scraper is None:
        concurrent = max_concurrent if max_concurrent else 5
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
        concurrent = max_concurrent if max_concurrent else 5
        scraper = Pro4KingsScraper(max_concurrent=concurrent)
        await scraper.__aenter__()
    
    return scraper

setup_commands(bot, db, get_or_recreate_scraper)
logger.info("✅ Slash commands module loaded")

@bot.event
async def on_ready():
    global COMMANDS_SYNCED
    
    logger.info(f'✅ {bot.user} is now running!')
    
    if not verify_environment():
        logger.error("❌ Environment verification failed! Bot may not work correctly.")
    await log_database_startup_info()
    await inspect_database_tables()
    
    async with SYNC_LOCK:
        if not COMMANDS_SYNCED:
            try:
                logger.info("🔄 Syncing slash commands...")
                synced = await bot.tree.sync()
                logger.info(f"✅ Synced {len(synced)} slash commands:")
                for cmd in synced:
                    logger.info(f"  - /{cmd.name}: {cmd.description}")
                COMMANDS_SYNCED = True
            except Exception as e:
                logger.error(f"❌ Failed to sync commands: {e}", exc_info=True)
    
    if not scrape_actions.is_running():
        scrape_actions.start()
        logger.info('✓ Started: scrape_actions (30s interval)')
    
    if not scrape_online_players.is_running():
        scrape_online_players.start()
        logger.info('✓ Started: scrape_online_players (60s interval)')
    
    if not update_pending_profiles.is_running():
        update_pending_profiles.start()
        logger.info('✓ Started: update_pending_profiles (2min interval)')
    
    if not check_banned_players.is_running():
        check_banned_players.start()
        logger.info('✓ Started: check_banned_players (1h interval)')
    
    if Config.VIP_PLAYER_IDS and not scrape_vip_actions.is_running():
        scrape_vip_actions.start()
        logger.info(f'💎 Started: scrape_vip_actions ({Config.VIP_SCAN_INTERVAL}s interval, {len(Config.VIP_PLAYER_IDS)} VIP players)')
    
    if Config.TRACK_ONLINE_PLAYERS_PRIORITY and not scrape_online_priority_actions.is_running():
        scrape_online_priority_actions.start()
        logger.info(f'🟢 Started: scrape_online_priority_actions ({Config.ONLINE_PLAYERS_SCAN_INTERVAL}s interval)')
    
    if not task_watchdog.is_running():
        task_watchdog.start()
        logger.info('✓ Started: task_watchdog (5min interval)')
    
    logger.info('🚀 All systems operational!')
    print(f'\n{"="*60}')
    print(f'✅ {bot.user} is ONLINE and monitoring Pro4Kings!')
    if Config.VIP_PLAYER_IDS:
        print(f'💎 VIP Tracking: {len(Config.VIP_PLAYER_IDS)} priority players')
    if Config.TRACK_ONLINE_PLAYERS_PRIORITY:
        print(f'🟢 Online Priority: Enabled ({Config.ONLINE_PLAYERS_SCAN_INTERVAL}s scan interval)')
    print(f'{"="*60}\n')

async def log_database_startup_info():
    """Log database information on startup"""
    try:
        import os
        
        db_path = db.db_path
        logger.info("="*60)
        logger.info("📊 DATABASE STARTUP INFORMATION")
        logger.info("="*60)
        
        # File info
        if os.path.exists(db_path):
            file_size = os.path.getsize(db_path) / (1024 * 1024)  # MB
            logger.info(f"📁 Database file: {db_path}")
            logger.info(f"💾 File size: {file_size:.2f} MB")
        else:
            logger.warning(f"⚠️  Database file not found: {db_path}")
            return
        
        # Get stats
        stats = await db.get_database_stats()
        total_players = stats.get('total_players', 0)
        total_actions = stats.get('total_actions', 0)
        online_count = stats.get('online_count', 0)
        
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
            logger.warning("⚠️  WARNING: No players in database!")
            logger.warning("⚠️  If you expected imported data, check:")
            logger.warning("⚠️    1. Was backup.db.gz extracted?")
            logger.warning("⚠️    2. Did migration script run?")
            logger.warning("⚠️    3. Check entrypoint.sh logs above")
        elif total_players < 1000:
            logger.warning(f"⚠️  WARNING: Only {total_players:,} players found!")
            logger.warning(f"⚠️  Expected ~225,000 from backup import")
        else:
            logger.info(f"✅ Database successfully loaded with {total_players:,} players!")
        
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"❌ Error logging database info: {e}", exc_info=True)


async def inspect_database_tables():
    """Inspect database tables to debug import issues"""
    try:
        import sqlite3
        
        logger.info("="*60)
        logger.info("🔍 DATABASE TABLE INSPECTION")
        logger.info("="*60)
        
        def _inspect_sync():
            conn = sqlite3.connect(db.db_path)
            cursor = conn.cursor()
            
            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row[0] for row in cursor.fetchall()]
            
            logger.info(f"📋 Found {len(tables)} tables:")
            for table in tables:
                logger.info(f"   - {table}")
            
            # Check for both 'players' and 'player_profiles'
            for table_name in ['players', 'player_profiles']:
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                if cursor.fetchone():
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    logger.info(f"✅ '{table_name}' table exists with {count:,} records")
                else:
                    logger.info(f"❌ '{table_name}' table does NOT exist")
            
            # Get player_profiles schema
            if 'player_profiles' in tables:
                cursor.execute("PRAGMA table_info(player_profiles)")
                columns = cursor.fetchall()
                logger.info(f"📊 player_profiles schema ({len(columns)} columns):")
                for col in columns[:5]:  # Show first 5 columns
                    logger.info(f"   - {col[1]} ({col[2]})")
            
            conn.close()
        
        await asyncio.to_thread(_inspect_sync)
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"❌ Error inspecting database: {e}", exc_info=True)

@tasks.loop(minutes=5)
async def task_watchdog():
    if SHUTDOWN_REQUESTED:
        return
    
    now = datetime.now()
    issues = []
    
    if TASK_HEALTH['scrape_actions']['last_run']:
        elapsed = (now - TASK_HEALTH['scrape_actions']['last_run']).total_seconds()
        if elapsed > 120:
            issues.append("scrape_actions hasn't run in 2+ minutes")
            if not scrape_actions.is_running():
                logger.warning("🔄 Restarting crashed task: scrape_actions")
                scrape_actions.restart()
    
    if TASK_HEALTH['scrape_online_players']['last_run']:
        elapsed = (now - TASK_HEALTH['scrape_online_players']['last_run']).total_seconds()
        if elapsed > 180:
            issues.append("scrape_online_players hasn't run in 3+ minutes")
            if not scrape_online_players.is_running():
                logger.warning("🔄 Restarting crashed task: scrape_online_players")
                scrape_online_players.restart()
    
    if TASK_HEALTH['update_pending_profiles']['last_run']:
        elapsed = (now - TASK_HEALTH['update_pending_profiles']['last_run']).total_seconds()
        if elapsed > 360:
            issues.append("update_pending_profiles hasn't run in 6+ minutes")
            if not update_pending_profiles.is_running():
                logger.warning("🔄 Restarting crashed task: update_pending_profiles")
                update_pending_profiles.restart()
    
    if Config.VIP_PLAYER_IDS and TASK_HEALTH['scrape_vip_actions']['last_run']:
        elapsed = (now - TASK_HEALTH['scrape_vip_actions']['last_run']).total_seconds()
        max_interval = Config.VIP_SCAN_INTERVAL * 5
        if elapsed > max_interval:
            issues.append(f"scrape_vip_actions hasn't run in {elapsed:.0f}s")
            if not scrape_vip_actions.is_running():
                logger.warning("🔄 Restarting crashed task: scrape_vip_actions")
                scrape_vip_actions.restart()
    
    if Config.TRACK_ONLINE_PLAYERS_PRIORITY and TASK_HEALTH['scrape_online_priority_actions']['last_run']:
        elapsed = (now - TASK_HEALTH['scrape_online_priority_actions']['last_run']).total_seconds()
        max_interval = Config.ONLINE_PLAYERS_SCAN_INTERVAL * 5
        if elapsed > max_interval:
            issues.append(f"scrape_online_priority_actions hasn't run in {elapsed:.0f}s")
            if not scrape_online_priority_actions.is_running():
                logger.warning("🔄 Restarting crashed task: scrape_online_priority_actions")
                scrape_online_priority_actions.restart()
    
    if issues:
        logger.warning(f"⚠️ Task health issues detected: {', '.join(issues)}")
    else:
        logger.info("✅ All background tasks healthy")

@task_watchdog.before_loop
async def before_task_watchdog():
    await bot.wait_until_ready()
    await asyncio.sleep(120)

@tasks.loop(seconds=30)
async def scrape_actions():
    if SHUTDOWN_REQUESTED:
        return
    
    TASK_HEALTH['scrape_actions']['last_run'] = datetime.now()
    TASK_HEALTH['scrape_actions']['is_running'] = True
    
    try:
        scraper_instance = await get_or_recreate_scraper()
        
        logger.info("🔍 Fetching latest actions...")
        actions = await scraper_instance.get_latest_actions(limit=200)
        
        if not actions:
            logger.warning("⚠️ No actions retrieved this cycle")
            TASK_HEALTH['scrape_actions']['error_count'] += 1
            return
        
        new_count = 0
        new_player_ids = set()
        
        for action in actions:
            action_dict = {
                'player_id': action.player_id,
                'player_name': action.player_name,
                'action_type': action.action_type,
                'action_detail': action.action_detail,
                'item_name': action.item_name,
                'item_quantity': action.item_quantity,
                'target_player_id': action.target_player_id,
                'target_player_name': action.target_player_name,
                'admin_id': action.admin_id,
                'admin_name': action.admin_name,
                'warning_count': action.warning_count,
                'reason': action.reason,
                'timestamp': action.timestamp,
                'raw_text': action.raw_text
            }
            
            if not await db.action_exists(action.timestamp, action.raw_text):
                await db.save_action(action_dict)
                new_count += 1
                
                if action.player_id:
                    new_player_ids.add((action.player_id, action.player_name))
                    await db.mark_player_for_update(action.player_id, action.player_name)
                
                if action.target_player_id:
                    new_player_ids.add((action.target_player_id, action.target_player_name))
                    await db.mark_player_for_update(action.target_player_id, action.target_player_name)
        
        if new_count > 0:
            logger.info(f"✅ Saved {new_count} new actions, marked {len(new_player_ids)} players for update")
            TASK_HEALTH['scrape_actions']['error_count'] = 0
        else:
            logger.info(f"ℹ️  No new actions (checked {len(actions)} entries)")
            
    except Exception as e:
        TASK_HEALTH['scrape_actions']['error_count'] += 1
        logger.error(f"❌ Error in scrape_actions (count: {TASK_HEALTH['scrape_actions']['error_count']}): {e}", exc_info=True)
        
        if TASK_HEALTH['scrape_actions']['error_count'] >= 5:
            logger.warning("⚠️ Too many errors, recreating scraper client...")
            global scraper
            try:
                if scraper:
                    await scraper.__aexit__(None, None, None)
            except:
                pass
            scraper = None
            TASK_HEALTH['scrape_actions']['error_count'] = 0
    
    finally:
        TASK_HEALTH['scrape_actions']['is_running'] = False

@scrape_actions.before_loop
async def before_scrape_actions():
    await bot.wait_until_ready()
    logger.info("✓ scrape_actions task ready")

@scrape_actions.error
async def scrape_actions_error(error):
    logger.error(f"❌ scrape_actions task error: {error}", exc_info=error)
    TASK_HEALTH['scrape_actions']['error_count'] += 1

@tasks.loop(seconds=Config.VIP_SCAN_INTERVAL)
async def scrape_vip_actions():
    if SHUTDOWN_REQUESTED:
        return
    
    if not Config.VIP_PLAYER_IDS:
        return
    
    TASK_HEALTH['scrape_vip_actions']['last_run'] = datetime.now()
    TASK_HEALTH['scrape_vip_actions']['is_running'] = True
    
    try:
        scraper_instance = await get_or_recreate_scraper()
        vip_ids = set(Config.VIP_PLAYER_IDS)
        
        vip_actions = await scraper_instance.get_vip_actions(vip_ids, limit=200)
        
        if vip_actions:
            new_count = 0
            new_player_ids = set()
            
            for action in vip_actions:
                action_dict = {
                    'player_id': action.player_id,
                    'player_name': action.player_name,
                    'action_type': action.action_type,
                    'action_detail': action.action_detail,
                    'item_name': action.item_name,
                    'item_quantity': action.item_quantity,
                    'target_player_id': action.target_player_id,
                    'target_player_name': action.target_player_name,
                    'admin_id': action.admin_id,
                    'admin_name': action.admin_name,
                    'warning_count': action.warning_count,
                    'reason': action.reason,
                    'timestamp': action.timestamp,
                    'raw_text': action.raw_text
                }
                
                if not await db.action_exists(action.timestamp, action.raw_text):
                    await db.save_action(action_dict)
                    new_count += 1
                    
                    if action.player_id:
                        new_player_ids.add((action.player_id, action.player_name))
                        await db.mark_player_for_update(action.player_id, action.player_name)
                    
                    if action.target_player_id:
                        new_player_ids.add((action.target_player_id, action.target_player_name))
                        await db.mark_player_for_update(action.target_player_id, action.target_player_name)
            
            if new_count > 0:
                logger.info(f"💎 VIP Scan: {new_count} new VIP actions saved, {len(new_player_ids)} players marked for update")
            
        TASK_HEALTH['scrape_vip_actions']['error_count'] = 0
        
    except Exception as e:
        TASK_HEALTH['scrape_vip_actions']['error_count'] += 1
        logger.error(f"❌ VIP scan failed (count: {TASK_HEALTH['scrape_vip_actions']['error_count']}): {e}", exc_info=True)
    
    finally:
        TASK_HEALTH['scrape_vip_actions']['is_running'] = False

@scrape_vip_actions.before_loop
async def before_scrape_vip_actions():
    await bot.wait_until_ready()
    logger.info("💎 scrape_vip_actions task ready")

@scrape_vip_actions.error
async def scrape_vip_actions_error(error):
    logger.error(f"❌ scrape_vip_actions task error: {error}", exc_info=error)
    TASK_HEALTH['scrape_vip_actions']['error_count'] += 1

@tasks.loop(seconds=Config.ONLINE_PLAYERS_SCAN_INTERVAL)
async def scrape_online_priority_actions():
    if SHUTDOWN_REQUESTED:
        return
    
    if not Config.TRACK_ONLINE_PLAYERS_PRIORITY:
        return
    
    TASK_HEALTH['scrape_online_priority_actions']['last_run'] = datetime.now()
    TASK_HEALTH['scrape_online_priority_actions']['is_running'] = True
    
    try:
        online_players = await db.get_current_online_players()
        if not online_players:
            return
        
        online_ids = set(player['player_id'] for player in online_players)
        
        scraper_instance = await get_or_recreate_scraper()
        
        online_actions = await scraper_instance.get_online_player_actions(online_ids, limit=200)
        
        if online_actions:
            new_count = 0
            new_player_ids = set()
            
            for action in online_actions:
                action_dict = {
                    'player_id': action.player_id,
                    'player_name': action.player_name,
                    'action_type': action.action_type,
                    'action_detail': action.action_detail,
                    'item_name': action.item_name,
                    'item_quantity': action.item_quantity,
                    'target_player_id': action.target_player_id,
                    'target_player_name': action.target_player_name,
                    'admin_id': action.admin_id,
                    'admin_name': action.admin_name,
                    'warning_count': action.warning_count,
                    'reason': action.reason,
                    'timestamp': action.timestamp,
                    'raw_text': action.raw_text
                }
                
                if not await db.action_exists(action.timestamp, action.raw_text):
                    await db.save_action(action_dict)
                    new_count += 1
                    
                    if action.player_id:
                        new_player_ids.add((action.player_id, action.player_name))
                        await db.mark_player_for_update(action.player_id, action.player_name)
                    
                    if action.target_player_id:
                        new_player_ids.add((action.target_player_id, action.target_player_name))
                        await db.mark_player_for_update(action.target_player_id, action.target_player_name)
            
            if new_count > 0:
                logger.info(f"🟢 Online Priority: {new_count} new actions saved for {len(online_ids)} online players")
            
        TASK_HEALTH['scrape_online_priority_actions']['error_count'] = 0
        
    except Exception as e:
        TASK_HEALTH['scrape_online_priority_actions']['error_count'] += 1
        logger.error(f"❌ Online priority scan failed (count: {TASK_HEALTH['scrape_online_priority_actions']['error_count']}): {e}", exc_info=True)
    
    finally:
        TASK_HEALTH['scrape_online_priority_actions']['is_running'] = False

@scrape_online_priority_actions.before_loop
async def before_scrape_online_priority_actions():
    await bot.wait_until_ready()
    logger.info("🟢 scrape_online_priority_actions task ready")

@scrape_online_priority_actions.error
async def scrape_online_priority_actions_error(error):
    logger.error(f"❌ scrape_online_priority_actions task error: {error}", exc_info=error)
    TASK_HEALTH['scrape_online_priority_actions']['error_count'] += 1

@tasks.loop(seconds=60)
async def scrape_online_players():
    if SHUTDOWN_REQUESTED:
        return
    
    TASK_HEALTH['scrape_online_players']['last_run'] = datetime.now()
    TASK_HEALTH['scrape_online_players']['is_running'] = True
    
    try:
        scraper_instance = await get_or_recreate_scraper()
        
        online_players = await scraper_instance.get_online_players()
        current_time = datetime.now()
        
        previous_online = await db.get_current_online_players()
        previous_ids = {p['player_id'] for p in previous_online}
        current_ids = {p['player_id'] for p in online_players}
        
        new_logins = current_ids - previous_ids
        for player in online_players:
            if player['player_id'] in new_logins:
                await db.save_login(player['player_id'], player['player_name'], current_time)
                await db.mark_player_for_update(player['player_id'], player['player_name'])
                logger.info(f"🟢 Login detected: {player['player_name']} ({player['player_id']})")
        
        logouts = previous_ids - current_ids
        for player_id in logouts:
            await db.save_logout(player_id, current_time)
            logger.info(f"🔴 Logout detected: Player {player_id}")
        
        await db.update_online_players(online_players)
        
        for player in online_players:
            await db.mark_player_for_update(player['player_id'], player['player_name'])
        
        if new_logins or logouts:
            logger.info(f"👥 Online: {len(online_players)} | New: {len(new_logins)} | Left: {len(logouts)}")
        else:
            logger.info(f"👥 Online players: {len(online_players)}")
        
        TASK_HEALTH['scrape_online_players']['error_count'] = 0
        
    except Exception as e:
        TASK_HEALTH['scrape_online_players']['error_count'] += 1
        logger.error(f"✗ Error scraping online players: {e}", exc_info=True)
    
    finally:
        TASK_HEALTH['scrape_online_players']['is_running'] = False

@scrape_online_players.error
async def scrape_online_players_error(error):
    logger.error(f"❌ scrape_online_players task error: {error}", exc_info=error)
    TASK_HEALTH['scrape_online_players']['error_count'] += 1

@tasks.loop(minutes=2)
async def update_pending_profiles():
    if SHUTDOWN_REQUESTED:
        return
    
    TASK_HEALTH['update_pending_profiles']['last_run'] = datetime.now()
    TASK_HEALTH['update_pending_profiles']['is_running'] = True
    
    try:
        scraper_instance = await get_or_recreate_scraper()
        
        pending_ids = await db.get_players_pending_update(limit=200)
        
        if not pending_ids:
            return
        
        logger.info(f"🔄 Updating {len(pending_ids)} pending profiles...")
        
        results = await scraper_instance.batch_get_profiles(pending_ids)
        
        for profile in results:
            profile_dict = {
                'player_id': profile.player_id,
                'player_name': profile.username,
                'is_online': profile.is_online,
                'last_connection': profile.last_seen,
                'faction': profile.faction,
                'faction_rank': profile.faction_rank,
                'job': profile.job,
                'level': profile.level,
                'respect_points': profile.respect_points,
                'warns': profile.warnings,
                'played_hours': profile.played_hours,
                'age_ic': profile.age_ic,
                'phone_number': profile.phone_number,
                'vehicles_count': profile.vehicles_count,
                'properties_count': profile.properties_count
            }
            await db.save_player_profile(profile_dict)
            await db.reset_player_priority(profile.player_id)
        
        logger.info(f"✓ Updated {len(results)}/{len(pending_ids)} profiles")
        TASK_HEALTH['update_pending_profiles']['error_count'] = 0
        
    except Exception as e:
        TASK_HEALTH['update_pending_profiles']['error_count'] += 1
        logger.error(f"✗ Error updating profiles: {e}", exc_info=True)
    
    finally:
        TASK_HEALTH['update_pending_profiles']['is_running'] = False

@update_pending_profiles.error
async def update_pending_profiles_error(error):
    logger.error(f"❌ update_pending_profiles task error: {error}", exc_info=error)
    TASK_HEALTH['update_pending_profiles']['error_count'] += 1

@tasks.loop(hours=1)
async def update_missing_faction_ranks():
    """Target players with factions but no faction_rank for updates"""
    while True:
        try:
            # Query players with faction but no faction_rank
            def _get_missing_ranks():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT player_id 
                        FROM player_profiles 
                        WHERE faction IS NOT NULL 
                        AND faction != '' 
                        AND (faction_rank IS NULL OR faction_rank = '')
                        LIMIT 50
                    ''')
                    return [row[0] for row in cursor.fetchall()]
            
            player_ids = await asyncio.to_thread(_get_missing_ranks)
            
            if player_ids:
                logger.info(f"🎯 Targeting {len(player_ids)} players with missing faction ranks")
                for player_id in player_ids:
                    await db.mark_player_for_update(player_id, f"Player_{player_id}")
            
            # Run every 10 minutes
            await asyncio.sleep(600)
            
        except Exception as e:
            logger.error(f"Error in update_missing_faction_ranks: {e}")
            await asyncio.sleep(60)
async def check_banned_players():
    if SHUTDOWN_REQUESTED:
        return
    
    TASK_HEALTH['check_banned_players']['last_run'] = datetime.now()
    TASK_HEALTH['check_banned_players']['is_running'] = True
    
    try:
        scraper_instance = await get_or_recreate_scraper()
        
        banned = await scraper_instance.get_banned_players()
        current_ban_ids = {ban['player_id'] for ban in banned if ban.get('player_id')}
        
        for ban_data in banned:
            await db.save_banned_player(ban_data)
        
        await db.mark_expired_bans(current_ban_ids)
        
        logger.info(f"✓ Updated {len(banned)} banned players")
        TASK_HEALTH['check_banned_players']['error_count'] = 0
        
    except Exception as e:
        TASK_HEALTH['check_banned_players']['error_count'] += 1
        logger.error(f"✗ Error checking banned players: {e}", exc_info=True)
    
    finally:
        TASK_HEALTH['check_banned_players']['is_running'] = False
@check_banned_players.error
async def check_banned_players_error(error):
    logger.error(f"❌ check_banned_players task error: {error}", exc_info=error)
    TASK_HEALTH['check_banned_players']['error_count'] += 1

@bot.command(name='sync')
async def force_sync(ctx):
    global COMMANDS_SYNCED
    
    try:
        await ctx.send("🔄 **Sincronizare forțată comenzi slash...**")
        
        COMMANDS_SYNCED = False
        synced = await bot.tree.sync()
        COMMANDS_SYNCED = True
        
        cmd_list = "\n".join([f"• `/{cmd.name}`: {cmd.description}" for cmd in synced])
        
        await ctx.send(
            f"✅ **Succes! Sincronizate {len(synced)} comenzi:**\n{cmd_list}"
        )
        
        logger.info(f"✅ Force sync completed by {ctx.author}: {len(synced)} commands")
        
    except Exception as e:
        await ctx.send(f"❌ **Eroare la sincronizare**: {str(e)}")
        logger.error(f"Force sync error: {e}", exc_info=True)

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
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

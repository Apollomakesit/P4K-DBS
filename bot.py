import discord
from discord.ext import commands, tasks
import os
import signal
import sys
from datetime import datetime, timedelta
from database import Database
from scraper import Pro4KingsScraper
import asyncio
import logging
import re
import tracemalloc
import psutil

# 🔥 Import all slash commands
from commands import setup_commands
from faction_commands import setup_faction_commands

# 🔥 Start memory tracking
tracemalloc.start()

# Discord command sync tracking
COMMANDS_SYNCED = False
SYNC_LOCK = asyncio.Lock()

# Scan status tracking
SCAN_IN_PROGRESS = False
SCAN_STATS = {
    'start_time': None,
    'scanned': 0,
    'found': 0,
    'errors': 0,
    'current_id': 0,
    'last_saved_id': 0
}

# 🔥 Task health tracking
TASK_HEALTH = {
    'scrape_actions': {'last_run': None, 'error_count': 0, 'is_running': False},
    'scrape_online_players': {'last_run': None, 'error_count': 0, 'is_running': False},
    'update_pending_profiles': {'last_run': None, 'error_count': 0, 'is_running': False},
    'check_banned_players': {'last_run': None, 'error_count': 0, 'is_running': False}
}

# 🔥 Graceful shutdown flag
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

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!p4k ', intents=intents)

# Initialize database and scraper
db = Database(os.getenv('DATABASE_PATH', 'pro4kings.db'))
scraper = None  # Will be initialized in setup_hook

# 🔥 GRACEFUL SHUTDOWN HANDLER
def signal_handler(sig, frame):
    """Handle shutdown signals gracefully"""
    global SHUTDOWN_REQUESTED
    logger.info(f"\n🛑 Shutdown signal received ({sig}), cleaning up...")
    SHUTDOWN_REQUESTED = True
    
    # Stop background tasks
    if scrape_actions.is_running():
        scrape_actions.cancel()
    if scrape_online_players.is_running():
        scrape_online_players.cancel()
    if update_pending_profiles.is_running():
        update_pending_profiles.cancel()
    if check_banned_players.is_running():
        check_banned_players.cancel()
    
    logger.info("✅ Background tasks stopped")
    
    # Close bot
    asyncio.create_task(bot.close())

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# 🔥 VERIFY VOLUME MOUNT ON STARTUP
def verify_environment():
    """Verify Railway environment is properly configured"""
    issues = []
    
    # Check database directory
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
    
    # Check Discord token
    if not os.getenv('DISCORD_TOKEN'):
        issues.append("DISCORD_TOKEN environment variable not set!")
    
    # Log system info
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

# ============================================================================
# 🔥 SCRAPER CLIENT MANAGEMENT
# ============================================================================

async def get_or_recreate_scraper():
    """Get scraper instance, recreate if needed"""
    global scraper
    
    if scraper is None:
        logger.info("🔄 Creating new scraper instance...")
        scraper = Pro4KingsScraper(max_concurrent=5)
        await scraper.__aenter__()
    
    # Check if client is still valid
    if scraper.client and scraper.client.is_closed:
        logger.warning("⚠️ Scraper client was closed, recreating...")
        try:
            await scraper.__aexit__(None, None, None)
        except:
            pass
        scraper = Pro4KingsScraper(max_concurrent=5)
        await scraper.__aenter__()
    
    return scraper

# ============================================================================
# 🔥 REGISTER ALL SLASH COMMANDS
# ============================================================================

setup_commands(bot, db, get_or_recreate_scraper)
logger.info("✅ Core commands module loaded")

setup_faction_commands(bot, db)
logger.info("✅ Faction commands module loaded")

@bot.event
async def on_ready():
    """Bot startup with proper slash command registration"""
    global COMMANDS_SYNCED
    
    logger.info(f'✅ {bot.user} is now running!')
    
    # Verify environment
    if not verify_environment():
        logger.error("❌ Environment verification failed! Bot may not work correctly.")
    
    # Sync slash commands (only once)
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
    
    # Start monitoring tasks
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
    
    # 🔥 Start task watchdog
    if not task_watchdog.is_running():
        task_watchdog.start()
        logger.info('✓ Started: task_watchdog (5min interval)')
    
    logger.info('🚀 All systems operational!')
    print(f'\n{"="*60}')
    print(f'✅ {bot.user} is ONLINE and monitoring Pro4Kings!')
    print(f'{"="*60}\n')

# ============================================================================
# 🔥 TASK WATCHDOG - Detects and restarts crashed tasks
# ============================================================================

@tasks.loop(minutes=5)
async def task_watchdog():
    """Monitor background tasks and restart if crashed"""
    if SHUTDOWN_REQUESTED:
        return
    
    now = datetime.now()
    issues = []
    
    # Check scrape_actions (should run every 30s)
    if TASK_HEALTH['scrape_actions']['last_run']:
        elapsed = (now - TASK_HEALTH['scrape_actions']['last_run']).total_seconds()
        if elapsed > 120:  # No run in 2 minutes
            issues.append("scrape_actions hasn't run in 2+ minutes")
            if not scrape_actions.is_running():
                logger.warning("🔄 Restarting crashed task: scrape_actions")
                scrape_actions.restart()
    
    # Check scrape_online_players (should run every 60s)
    if TASK_HEALTH['scrape_online_players']['last_run']:
        elapsed = (now - TASK_HEALTH['scrape_online_players']['last_run']).total_seconds()
        if elapsed > 180:  # No run in 3 minutes
            issues.append("scrape_online_players hasn't run in 3+ minutes")
            if not scrape_online_players.is_running():
                logger.warning("🔄 Restarting crashed task: scrape_online_players")
                scrape_online_players.restart()
    
    # Check update_pending_profiles (should run every 2min)
    if TASK_HEALTH['update_pending_profiles']['last_run']:
        elapsed = (now - TASK_HEALTH['update_pending_profiles']['last_run']).total_seconds()
        if elapsed > 360:  # No run in 6 minutes
            issues.append("update_pending_profiles hasn't run in 6+ minutes")
            if not update_pending_profiles.is_running():
                logger.warning("🔄 Restarting crashed task: update_pending_profiles")
                update_pending_profiles.restart()
    
    if issues:
        logger.warning(f"⚠️ Task health issues detected: {', '.join(issues)}")
    else:
        logger.info("✅ All background tasks healthy")

@task_watchdog.before_loop
async def before_task_watchdog():
    await bot.wait_until_ready()
    # Wait 2 minutes before first check
    await asyncio.sleep(120)

# ============================================================================
# BACKGROUND MONITORING TASKS WITH ERROR RECOVERY
# ============================================================================

@tasks.loop(seconds=30)
async def scrape_actions():
    """Scrape latest actions - WITH ENHANCED ERROR HANDLING"""
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
            
            # Check for duplicates using timestamp AND raw_text
            if not db.action_exists(action.timestamp, action.raw_text):
                db.save_action(action_dict)
                new_count += 1
                
                # Mark players for update
                if action.player_id:
                    new_player_ids.add((action.player_id, action.player_name))
                    db.mark_player_for_update(action.player_id, action.player_name)
                
                if action.target_player_id:
                    new_player_ids.add((action.target_player_id, action.target_player_name))
                    db.mark_player_for_update(action.target_player_id, action.target_player_name)
        
        if new_count > 0:
            logger.info(f"✅ Saved {new_count} new actions, marked {len(new_player_ids)} players for update")
            TASK_HEALTH['scrape_actions']['error_count'] = 0  # Reset on success
        else:
            logger.info(f"ℹ️  No new actions (checked {len(actions)} entries)")
            
    except Exception as e:
        TASK_HEALTH['scrape_actions']['error_count'] += 1
        logger.error(f"❌ Error in scrape_actions (count: {TASK_HEALTH['scrape_actions']['error_count']}): {e}", exc_info=True)
        
        # If too many errors, recreate scraper
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
    """Wait for bot to be ready"""
    await bot.wait_until_ready()
    logger.info("✓ scrape_actions task ready")

@scrape_actions.error
async def scrape_actions_error(error):
    """Handle task loop errors"""
    logger.error(f"❌ scrape_actions task error: {error}", exc_info=error)
    TASK_HEALTH['scrape_actions']['error_count'] += 1


@tasks.loop(seconds=60)
async def scrape_online_players():
    """
    Scrape online players every 60 seconds
    """
    if SHUTDOWN_REQUESTED:
        return
    
    TASK_HEALTH['scrape_online_players']['last_run'] = datetime.now()
    TASK_HEALTH['scrape_online_players']['is_running'] = True
    
    try:
        scraper_instance = await get_or_recreate_scraper()
        
        online_players = await scraper_instance.get_online_players()
        current_time = datetime.now()
        
        previous_online = db.get_current_online_players()
        previous_ids = {p['player_id'] for p in previous_online}
        current_ids = {p['player_id'] for p in online_players}
        
        new_logins = current_ids - previous_ids
        for player in online_players:
            if player['player_id'] in new_logins:
                db.save_login(player['player_id'], player['player_name'], current_time)
                db.mark_player_for_update(player['player_id'], player['player_name'])
                logger.info(f"🟢 Login detected: {player['player_name']} ({player['player_id']})")
        
        logouts = previous_ids - current_ids
        for player_id in logouts:
            db.save_logout(player_id, current_time)
            logger.info(f"🔴 Logout detected: Player {player_id}")
        
        db.update_online_players(online_players)
        
        for player in online_players:
            db.mark_player_for_update(player['player_id'], player['player_name'])
        
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
    """Update profiles for detected players - 200 per run"""
    if SHUTDOWN_REQUESTED:
        return
    
    TASK_HEALTH['update_pending_profiles']['last_run'] = datetime.now()
    TASK_HEALTH['update_pending_profiles']['is_running'] = True
    
    try:
        scraper_instance = await get_or_recreate_scraper()
        
        pending_ids = db.get_players_pending_update(limit=200)
        
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
            db.save_player_profile(profile_dict)
            db.reset_player_priority(profile.player_id)
        
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
async def check_banned_players():
    """Check banned players list hourly"""
    if SHUTDOWN_REQUESTED:
        return
    
    TASK_HEALTH['check_banned_players']['last_run'] = datetime.now()
    TASK_HEALTH['check_banned_players']['is_running'] = True
    
    try:
        scraper_instance = await get_or_recreate_scraper()
        
        banned = await scraper_instance.get_banned_players()
        current_ban_ids = {ban['player_id'] for ban in banned if ban.get('player_id')}
        
        for ban_data in banned:
            db.save_banned_player(ban_data)
        
        db.mark_expired_bans(current_ban_ids)
        
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

# ============================================================================
# PREFIX COMMAND FOR EMERGENCY COMMAND SYNC
# ============================================================================

@bot.command(name='sync')
async def force_sync(ctx):
    """EMERGENCY: Force sync slash commands"""
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

# ============================================================================
# RUN BOT
# ============================================================================

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

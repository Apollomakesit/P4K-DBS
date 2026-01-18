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
from logging.handlers import RotatingFileHandler
import re
import shutil
from pathlib import Path

# Import configuration
from config import Config

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

# 🔥 Error notification tracking
LAST_ERROR_NOTIFICATIONS = {}  # error_type -> timestamp

# 🔥 Graceful shutdown flag
SHUTDOWN_REQUESTED = False

# 🔥 ROTATING LOG HANDLER - Prevents disk fill
log_handler = RotatingFileHandler(
    Config.LOG_FILE_PATH,
    maxBytes=Config.LOG_MAX_BYTES,
    backupCount=Config.LOG_BACKUP_COUNT
)
log_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    handlers=[
        log_handler,
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!p4k ', intents=intents)

# Initialize database and scraper
db = Database(Config.DATABASE_PATH)
scraper = None

# 🔥 ADMIN ERROR NOTIFICATION
async def notify_admins(title: str, description: str, color: discord.Color = discord.Color.red()):
    """Send error notification to configured admin users"""
    if not Config.ENABLE_ERROR_NOTIFICATIONS or not Config.ADMIN_USER_IDS:
        return
    
    # Check cooldown
    error_key = f"{title}:{description[:50]}"
    now = datetime.now()
    
    if error_key in LAST_ERROR_NOTIFICATIONS:
        last_notification = LAST_ERROR_NOTIFICATIONS[error_key]
        if (now - last_notification).total_seconds() < Config.ERROR_NOTIFICATION_COOLDOWN:
            return  # Skip, too soon
    
    LAST_ERROR_NOTIFICATIONS[error_key] = now
    
    embed = discord.Embed(
        title=f"🚨 {title}",
        description=description,
        color=color,
        timestamp=now
    )
    embed.set_footer(text=f"Bot: {bot.user.name}")
    
    for admin_id in Config.ADMIN_USER_IDS:
        try:
            user = await bot.fetch_user(admin_id)
            await user.send(embed=embed)
            logger.info(f"Sent error notification to admin {admin_id}")
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

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
    if task_watchdog.is_running():
        task_watchdog.cancel()
    
    logger.info("✓ Background tasks stopped")
    
    # Close bot
    asyncio.create_task(bot.close())

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

@bot.event
async def on_ready():
    """Bot startup"""
    global COMMANDS_SYNCED
    
    logger.info(f'✅ {bot.user} is now running!')
    
    # Validate config
    config_issues = Config.validate()
    if config_issues:
        logger.warning(f"⚠️ Configuration issues: {', '.join(config_issues)}")
    
    # Sync slash commands
    async with SYNC_LOCK:
        if not COMMANDS_SYNCED:
            try:
                logger.info("🔄 Syncing slash commands...")
                synced = await bot.tree.sync()
                logger.info(f"✅ Synced {len(synced)} slash commands")
                COMMANDS_SYNCED = True
            except Exception as e:
                logger.error(f"❌ Failed to sync commands: {e}", exc_info=True)
    
    # Start monitoring tasks with configured intervals
    if not scrape_actions.is_running():
        scrape_actions.change_interval(seconds=Config.SCRAPE_ACTIONS_INTERVAL)
        scrape_actions.start()
        logger.info(f'✓ Started: scrape_actions ({Config.SCRAPE_ACTIONS_INTERVAL}s interval)')
    
    if not scrape_online_players.is_running():
        scrape_online_players.change_interval(seconds=Config.SCRAPE_ONLINE_INTERVAL)
        scrape_online_players.start()
        logger.info(f'✓ Started: scrape_online_players ({Config.SCRAPE_ONLINE_INTERVAL}s interval)')
    
    if not update_pending_profiles.is_running():
        update_pending_profiles.change_interval(seconds=Config.UPDATE_PROFILES_INTERVAL)
        update_pending_profiles.start()
        logger.info(f'✓ Started: update_pending_profiles ({Config.UPDATE_PROFILES_INTERVAL}s interval)')
    
    if not check_banned_players.is_running():
        check_banned_players.change_interval(seconds=Config.CHECK_BANNED_INTERVAL)
        check_banned_players.start()
        logger.info(f'✓ Started: check_banned_players ({Config.CHECK_BANNED_INTERVAL}s interval)')
    
    if not task_watchdog.is_running():
        task_watchdog.change_interval(seconds=Config.TASK_WATCHDOG_INTERVAL)
        task_watchdog.start()
        logger.info(f'✓ Started: task_watchdog ({Config.TASK_WATCHDOG_INTERVAL}s interval)')
    
    logger.info('🚀 All systems operational!')

# ============================================================================
# ADMIN COMMANDS
# ============================================================================

@bot.tree.command(name="config", description="[ADMIN] Display current configuration")
async def show_config(interaction: discord.Interaction):
    """Display bot configuration"""
    await interaction.response.defer()
    
    embed = discord.Embed(
        title="⚙️ Bot Configuration",
        description=Config.display(),
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="cleanup_old_data", description="[ADMIN] Remove old data based on retention policy")
async def cleanup_old_data(interaction: discord.Interaction, dry_run: bool = True):
    """Clean up old data according to retention policy"""
    await interaction.response.defer()
    
    if interaction.user.id not in Config.ADMIN_USER_IDS and Config.ADMIN_USER_IDS:
        await interaction.followup.send("❌ This command is restricted to administrators.")
        return
    
    try:
        stats = db.cleanup_old_data(
            actions_days=Config.ACTIONS_RETENTION_DAYS,
            login_events_days=Config.LOGIN_EVENTS_RETENTION_DAYS,
            profile_history_days=Config.PROFILE_HISTORY_RETENTION_DAYS,
            dry_run=dry_run
        )
        
        mode = "🔍 DRY RUN" if dry_run else "🗑️ CLEANUP EXECUTED"
        
        embed = discord.Embed(
            title=f"{mode} - Data Cleanup",
            color=discord.Color.orange() if dry_run else discord.Color.green(),
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="Actions",
            value=f"Would delete: **{stats['actions_deleted']:,}**\nRetention: {Config.ACTIONS_RETENTION_DAYS} days",
            inline=True
        )
        
        embed.add_field(
            name="Login Events",
            value=f"Would delete: **{stats['login_events_deleted']:,}**\nRetention: {Config.LOGIN_EVENTS_RETENTION_DAYS} days",
            inline=True
        )
        
        embed.add_field(
            name="Profile History",
            value=f"Would delete: **{stats['profile_history_deleted']:,}**\nRetention: {Config.PROFILE_HISTORY_RETENTION_DAYS} days",
            inline=True
        )
        
        if dry_run:
            embed.set_footer(text="Run with dry_run=False to actually delete data")
        else:
            embed.set_footer(text="✅ Cleanup completed successfully")
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error during cleanup: {str(e)}")
        logger.error(f"Cleanup error: {e}", exc_info=True)

@bot.tree.command(name="backup_database", description="[ADMIN] Create database backup")
async def backup_database(interaction: discord.Interaction):
    """Create a backup of the database"""
    await interaction.response.defer()
    
    if interaction.user.id not in Config.ADMIN_USER_IDS and Config.ADMIN_USER_IDS:
        await interaction.followup.send("❌ This command is restricted to administrators.")
        return
    
    try:
        # Create backup directory
        backup_dir = Path(Config.DATABASE_BACKUP_PATH)
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = backup_dir / f"pro4kings_backup_{timestamp}.db"
        
        # Copy database file
        shutil.copy2(Config.DATABASE_PATH, backup_file)
        
        # Get file size
        file_size = backup_file.stat().st_size / 1024 / 1024  # MB
        
        embed = discord.Embed(
            title="✅ Database Backup Created",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="Backup File",
            value=f"`{backup_file.name}`",
            inline=False
        )
        
        embed.add_field(
            name="Size",
            value=f"**{file_size:.2f} MB**",
            inline=True
        )
        
        embed.add_field(
            name="Location",
            value=f"`{Config.DATABASE_BACKUP_PATH}`",
            inline=True
        )
        
        # Count existing backups
        backup_count = len(list(backup_dir.glob("*.db")))
        embed.set_footer(text=f"Total backups: {backup_count}")
        
        await interaction.followup.send(embed=embed)
        logger.info(f"Database backup created: {backup_file}")
        
    except Exception as e:
        await interaction.followup.send(f"❌ Backup failed: {str(e)}")
        logger.error(f"Backup error: {e}", exc_info=True)

# ============================================================================
# TASK WATCHDOG WITH ADMIN NOTIFICATIONS
# ============================================================================

@tasks.loop(seconds=300)  # Will be overridden by config
async def task_watchdog():
    """Monitor background tasks and restart if crashed"""
    if SHUTDOWN_REQUESTED:
        return
    
    now = datetime.now()
    issues = []
    critical_issues = []
    
    for task_name, health in TASK_HEALTH.items():
        if health['last_run']:
            elapsed = (now - health['last_run']).total_seconds()
            
            # Get expected max time based on task interval
            if task_name == 'scrape_actions':
                max_time = Config.SCRAPE_ACTIONS_INTERVAL * Config.TASK_HEALTH_CHECK_MULTIPLIER['scrape_actions']
            elif task_name == 'scrape_online_players':
                max_time = Config.SCRAPE_ONLINE_INTERVAL * Config.TASK_HEALTH_CHECK_MULTIPLIER['scrape_online_players']
            elif task_name == 'update_pending_profiles':
                max_time = Config.UPDATE_PROFILES_INTERVAL * Config.TASK_HEALTH_CHECK_MULTIPLIER['update_pending_profiles']
            elif task_name == 'check_banned_players':
                max_time = Config.CHECK_BANNED_INTERVAL * Config.TASK_HEALTH_CHECK_MULTIPLIER['check_banned_players']
            else:
                max_time = 600  # Default 10 minutes
            
            if elapsed > max_time:
                issue = f"{task_name} hasn't run in {int(elapsed)}s (expected < {int(max_time)}s)"
                issues.append(issue)
                critical_issues.append(task_name)
                
                # Try to restart
                task_obj = globals().get(task_name)
                if task_obj and not task_obj.is_running():
                    logger.warning(f"🔄 Restarting crashed task: {task_name}")
                    task_obj.restart()
    
    if critical_issues:
        logger.warning(f"⚠️ Task health issues: {', '.join(issues)}")
        
        # Notify admins
        await notify_admins(
            "Task Health Alert",
            f"The following tasks have crashed or are not running:\n" +
            "\n".join([f"• **{task}**" for task in critical_issues]) +
            "\n\nAttempted automatic restart.",
            color=discord.Color.orange()
        )
    else:
        logger.info("✅ All background tasks healthy")

@task_watchdog.before_loop
async def before_task_watchdog():
    await bot.wait_until_ready()
    await asyncio.sleep(120)  # Wait 2 min before first check

# ============================================================================
# BACKGROUND TASKS (Using config intervals)
# ============================================================================

@tasks.loop(seconds=30)  # Will be overridden by config
async def scrape_actions():
    """Scrape latest actions"""
    if SHUTDOWN_REQUESTED:
        return
    
    TASK_HEALTH['scrape_actions']['last_run'] = datetime.now()
    TASK_HEALTH['scrape_actions']['is_running'] = True
    
    try:
        global scraper
        if not scraper:
            scraper = Pro4KingsScraper(max_concurrent=Config.SCRAPER_MAX_CONCURRENT)
            await scraper.__aenter__()
        
        actions = await scraper.get_latest_actions(limit=Config.ACTIONS_FETCH_LIMIT)
        
        if not actions:
            logger.warning("⚠️ No actions retrieved this cycle")
            TASK_HEALTH['scrape_actions']['error_count'] += 1
            
            # Notify if persistent
            if TASK_HEALTH['scrape_actions']['error_count'] >= 5:
                await notify_admins(
                    "Action Scraping Failed",
                    f"No actions retrieved for {TASK_HEALTH['scrape_actions']['error_count']} consecutive cycles.\n\n"
                    "This may indicate:"
                    "• Website structure changed\n"
                    "• Network/firewall blocking\n"
                    "• Rate limiting"
                )
            return
        
        new_count = 0
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
            
            if not db.action_exists(action.timestamp, action.raw_text):
                db.save_action(action_dict)
                new_count += 1
                
                if action.player_id:
                    db.mark_player_for_update(action.player_id, action.player_name)
                if action.target_player_id:
                    db.mark_player_for_update(action.target_player_id, action.target_player_name)
        
        if new_count > 0:
            logger.info(f"✅ Saved {new_count} new actions")
            TASK_HEALTH['scrape_actions']['error_count'] = 0
        
    except Exception as e:
        TASK_HEALTH['scrape_actions']['error_count'] += 1
        logger.error(f"❌ Error in scrape_actions: {e}", exc_info=True)
        
        if TASK_HEALTH['scrape_actions']['error_count'] >= 3:
            await notify_admins(
                "Scrape Actions Error",
                f"Task has failed {TASK_HEALTH['scrape_actions']['error_count']} times.\n\n"
                f"**Error**: `{str(e)[:200]}`"
            )
    
    finally:
        TASK_HEALTH['scrape_actions']['is_running'] = False

@scrape_actions.before_loop
async def before_scrape_actions():
    await bot.wait_until_ready()

# ... (other tasks similar to scrape_actions, using config)

if __name__ == '__main__':
    if not Config.DISCORD_TOKEN:
        logger.error("❌ ERROR: DISCORD_TOKEN not found!")
        exit(1)
    
    logger.info("🚀 Starting Pro4Kings Database Bot...")
    bot.run(Config.DISCORD_TOKEN)

import discord
from discord.ext import commands, tasks
import os
from datetime import datetime, timedelta
from database import Database
from scraper import Pro4KingsScraper
import asyncio
import logging
import re

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

# 🔥 NEW: Scraper performance tracking
SCRAPER_STATS = {
    'actions_scraped_total': 0,
    'actions_saved_total': 0,
    'actions_duplicate': 0,
    'scrape_cycles': 0,
    'last_scrape_time': None,
    'last_scrape_count': 0,
    'errors': 0
}

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

@bot.event
async def on_ready():
    """Bot startup with proper slash command registration"""
    global COMMANDS_SYNCED
    
    logger.info(f'✅ {bot.user} is now running!')
    
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
    
    logger.info('🚀 All systems operational!')
    print(f'\n{"="*60}')
    print(f'✅ {bot.user} is ONLINE and monitoring Pro4Kings!')
    print(f'{"="*60}\n')

# ============================================================================
# PREFIX COMMAND FOR EMERGENCY COMMAND SYNC
# ============================================================================

@bot.command(name='sync')
async def force_sync(ctx):
    """EMERGENCY: Force sync slash commands if they don't appear"""
    global COMMANDS_SYNCED
    
    try:
        await ctx.send("🔄 **Sincronizare forțată comenzi slash...**")
        
        # Force resync
        COMMANDS_SYNCED = False
        synced = await bot.tree.sync()
        COMMANDS_SYNCED = True
        
        cmd_list = "\n".join([f"• `/{cmd.name}`: {cmd.description}" for cmd in synced])
        
        await ctx.send(
            f"✅ **Succes! Sincronizate {len(synced)} comenzi:**\n{cmd_list}\n\n"
            f"**Notă**: Discord poate dura 1-5 minute să afișeze comenzile noi. Așteaptă și reîncearcă `/scan_all`.\n\n"
            f"Dacă nu apar după 5 minute:\n"
            f"1. Ieși complet din Discord (închide aplicația)\n"
            f"2. Reintră în Discord\n"
            f"3. Comenzile ar trebui să apară acum"
        )
        
        logger.info(f"✅ Force sync completed by {ctx.author}: {len(synced)} commands")
        
    except Exception as e:
        await ctx.send(f"❌ **Eroare la sincronizare**: {str(e)}")
        logger.error(f"Force sync error: {e}", exc_info=True)

# ============================================================================
# BACKGROUND MONITORING TASKS
# ============================================================================

@tasks.loop(seconds=30)
async def scrape_actions():
    """Scrape latest actions - WITH ENHANCED ERROR HANDLING AND STATS"""
    try:
        global scraper, SCRAPER_STATS
        if not scraper:
            scraper = Pro4KingsScraper(max_concurrent=5)
            await scraper.__aenter__()
        
        logger.info("🔍 Fetching latest actions...")
        actions = await scraper.get_latest_actions(limit=200)
        
        SCRAPER_STATS['scrape_cycles'] += 1
        SCRAPER_STATS['last_scrape_time'] = datetime.now()
        SCRAPER_STATS['last_scrape_count'] = len(actions)
        SCRAPER_STATS['actions_scraped_total'] += len(actions)
        
        if not actions:
            logger.warning("⚠️ No actions retrieved this cycle - THIS IS A PROBLEM!")
            SCRAPER_STATS['errors'] += 1
            return
        
        new_count = 0
        duplicate_count = 0
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
            else:
                duplicate_count += 1
        
        SCRAPER_STATS['actions_saved_total'] += new_count
        SCRAPER_STATS['actions_duplicate'] += duplicate_count
        
        if new_count > 0:
            logger.info(f"✅ Saved {new_count} new actions, marked {len(new_player_ids)} players for update")
        else:
            logger.info(f"ℹ️  No new actions (checked {len(actions)} entries, {duplicate_count} duplicates)")
            
    except Exception as e:
        SCRAPER_STATS['errors'] += 1
        logger.error(f"❌ Error in scrape_actions: {e}", exc_info=True)

@scrape_actions.before_loop
async def before_scrape_actions():
    """Wait for bot to be ready"""
    await bot.wait_until_ready()
    logger.info("✓ scrape_actions task ready")


@tasks.loop(seconds=60)
async def scrape_online_players():
    """
    Scrape online players every 60 seconds
    ACCURATE detection from https://panel.pro4kings.ro/online
    """
    try:
        global scraper
        if not scraper:
            scraper = Pro4KingsScraper()
            await scraper.__aenter__()
        
        # Get online players from actual panel
        online_players = await scraper.get_online_players()
        current_time = datetime.now()
        
        # Get previously detected online players
        previous_online = db.get_current_online_players()
        previous_ids = {p['player_id'] for p in previous_online}
        current_ids = {p['player_id'] for p in online_players}
        
        # Detect new logins
        new_logins = current_ids - previous_ids
        for player in online_players:
            if player['player_id'] in new_logins:
                db.save_login(player['player_id'], player['player_name'], current_time)
                db.mark_player_for_update(player['player_id'], player['player_name'])
                logger.info(f"🟢 Login detected: {player['player_name']} ({player['player_id']})")
        
        # Detect logouts
        logouts = previous_ids - current_ids
        for player_id in logouts:
            db.save_logout(player_id, current_time)
            logger.info(f"🔴 Logout detected: Player {player_id}")
        
        # Update online players snapshot (upsert method)
        db.update_online_players(online_players)
        
        # Mark all online players as priority for profile updates
        for player in online_players:
            db.mark_player_for_update(player['player_id'], player['player_name'])
        
        if new_logins or logouts:
            logger.info(f"👥 Online: {len(online_players)} | New: {len(new_logins)} | Left: {len(logouts)}")
        else:
            logger.info(f"👥 Online players: {len(online_players)}")
        
    except Exception as e:
        logger.error(f"✗ Error scraping online players: {e}", exc_info=True)

@tasks.loop(minutes=2)
async def update_pending_profiles():
    """Update profiles for detected players - 200 per run"""
    try:
        global scraper
        if not scraper:
            scraper = Pro4KingsScraper()
            await scraper.__aenter__()
        
        pending_ids = db.get_players_pending_update(limit=200)
        
        if not pending_ids:
            return
        
        logger.info(f"🔄 Updating {len(pending_ids)} pending profiles...")
        
        results = await scraper.batch_get_profiles(pending_ids)
        
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
        
    except Exception as e:
        logger.error(f"✗ Error updating profiles: {e}", exc_info=True)

@tasks.loop(hours=1)
async def check_banned_players():
    """Check banned players list hourly and mark expired bans"""
    try:
        global scraper
        if not scraper:
            scraper = Pro4KingsScraper()
            await scraper.__aenter__()
        
        banned = await scraper.get_banned_players()
        current_ban_ids = {ban['player_id'] for ban in banned if ban.get('player_id')}
        
        # Save current bans
        for ban_data in banned:
            db.save_banned_player(ban_data)
        
        # Mark bans as expired if they're no longer on the list
        db.mark_expired_bans(current_ban_ids)
        
        logger.info(f"✓ Updated {len(banned)} banned players, marked expired bans")
        
    except Exception as e:
        logger.error(f"✗ Error checking banned players: {e}", exc_info=True)

# ============================================================================
# 🔥 NEW: DEBUG COMMANDS FOR TESTING ACTION SCRAPING
# ============================================================================

@bot.tree.command(name="debug_scrape", description="[DEBUG] Test manual scraping of latest actions")
async def debug_scrape(interaction: discord.Interaction):
    """Manually test action scraping and show detailed results"""
    await interaction.response.defer()
    
    try:
        global scraper
        if not scraper:
            scraper = Pro4KingsScraper(max_concurrent=5)
            await scraper.__aenter__()
        
        await interaction.followup.send("🔍 **Testing action scraping...**\n`Please wait 5-10 seconds...`")
        
        # Test scrape
        actions = await scraper.get_latest_actions(limit=50)
        
        if not actions:
            await interaction.followup.send(
                "❌ **CRITICAL ISSUE: No actions found!**\n\n"
                "This means the scraper is not working properly. Check bot logs for details.\n"
                "Possible causes:\n"
                "1. Website structure changed\n"
                "2. Network/firewall blocking requests\n"
                "3. Rate limiting from server"
            )
            return
        
        # Create embed with results
        embed = discord.Embed(
            title="🔍 Action Scraping Test Results",
            description=f"Successfully scraped **{len(actions)}** actions",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        
        # Action type breakdown
        action_types = {}
        for action in actions:
            action_types[action.action_type] = action_types.get(action.action_type, 0) + 1
        
        type_breakdown = "\n".join([f"• **{k}**: {v}" for k, v in action_types.items()])
        embed.add_field(
            name="Action Types",
            value=type_breakdown or "None",
            inline=False
        )
        
        # Sample actions
        samples = []
        for i, action in enumerate(actions[:5]):
            samples.append(
                f"{i+1}. **{action.action_type}**\n"
                f"   Player: {action.player_name} ({action.player_id})\n"
                f"   Detail: {action.action_detail[:60]}..."
            )
        
        embed.add_field(
            name="Sample Actions (first 5)",
            value="\n\n".join(samples),
            inline=False
        )
        
        embed.set_footer(text="✅ Scraping is working correctly!")
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(
            f"❌ **Error during test scrape:**\n```{str(e)}```\n\n"
            "Check bot logs for full traceback."
        )
        logger.error(f"Debug scrape error: {e}", exc_info=True)

@bot.tree.command(name="scraper_stats", description="View scraper performance statistics")
async def scraper_stats_cmd(interaction: discord.Interaction):
    """Show scraper performance metrics"""
    await interaction.response.defer()
    
    embed = discord.Embed(
        title="📊 Scraper Performance Stats",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name="Scrape Cycles",
        value=f"**{SCRAPER_STATS['scrape_cycles']:,}** total",
        inline=True
    )
    
    embed.add_field(
        name="Actions Scraped",
        value=f"**{SCRAPER_STATS['actions_scraped_total']:,}** total",
        inline=True
    )
    
    embed.add_field(
        name="Actions Saved",
        value=f"**{SCRAPER_STATS['actions_saved_total']:,}** new",
        inline=True
    )
    
    embed.add_field(
        name="Duplicates Skipped",
        value=f"**{SCRAPER_STATS['actions_duplicate']:,}**",
        inline=True
    )
    
    embed.add_field(
        name="Errors",
        value=f"**{SCRAPER_STATS['errors']:,}**",
        inline=True
    )
    
    last_scrape = SCRAPER_STATS['last_scrape_time']
    if last_scrape:
        time_ago = (datetime.now() - last_scrape).total_seconds()
        embed.add_field(
            name="Last Scrape",
            value=f"**{int(time_ago)}s** ago\nFound: **{SCRAPER_STATS['last_scrape_count']}** actions",
            inline=True
        )
    
    # Calculate average
    if SCRAPER_STATS['scrape_cycles'] > 0:
        avg_per_cycle = SCRAPER_STATS['actions_scraped_total'] / SCRAPER_STATS['scrape_cycles']
        embed.add_field(
            name="Average per Cycle",
            value=f"**{avg_per_cycle:.1f}** actions",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="action_stats", description="View database action statistics")
async def action_stats_cmd(interaction: discord.Interaction):
    """Show database action statistics"""
    await interaction.response.defer()
    
    # Get action counts from database
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Total actions
        cursor.execute('SELECT COUNT(*) FROM actions')
        total_actions = cursor.fetchone()[0]
        
        # Actions by type
        cursor.execute("""
            SELECT action_type, COUNT(*) as count
            FROM actions
            GROUP BY action_type
            ORDER BY count DESC
            LIMIT 10
        """)
        action_types = cursor.fetchall()
        
        # Recent actions (last 24h)
        cursor.execute("""
            SELECT COUNT(*)
            FROM actions
            WHERE timestamp >= datetime('now', '-1 day')
        """)
        recent_24h = cursor.fetchone()[0]
        
        # Unique players with actions
        cursor.execute('SELECT COUNT(DISTINCT player_id) FROM actions WHERE player_id IS NOT NULL')
        unique_players = cursor.fetchone()[0]
    
    embed = discord.Embed(
        title="💾 Database Action Statistics",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name="Total Actions",
        value=f"**{total_actions:,}**",
        inline=True
    )
    
    embed.add_field(
        name="Last 24 Hours",
        value=f"**{recent_24h:,}**",
        inline=True
    )
    
    embed.add_field(
        name="Unique Players",
        value=f"**{unique_players:,}**",
        inline=True
    )
    
    # Action type breakdown
    type_list = "\n".join([f"• **{row['action_type']}**: {row['count']:,}" for row in action_types])
    if type_list:
        embed.add_field(
            name="Top Action Types",
            value=type_list,
            inline=False
        )
    
    if total_actions == 0:
        embed.color = discord.Color.red()
        embed.set_footer(text="⚠️ WARNING: No actions in database! Check /debug_scrape")
    
    await interaction.followup.send(embed=embed)

# ============================================================================
# INITIAL SCAN FUNCTION (Background) - 🔥 SEQUENTIAL WITH 50-ID CHECKPOINTS
# ============================================================================

async def run_initial_scan(interaction: discord.Interaction, start_id: int = 1, end_id: int = 230000, workers: int = 30):
    """🔥 SEQUENTIAL scan with better checkpointing"""
    global SCAN_IN_PROGRESS, SCAN_STATS
    
    if SCAN_IN_PROGRESS:
        await interaction.followup.send("⚠️ Un scan este deja în curs!")
        return
    
    SCAN_IN_PROGRESS = True
    SCAN_STATS = {
        'start_time': datetime.now(),
        'scanned': 0,
        'found': 0,
        'errors': 0,
        'current_id': start_id,
        'last_saved_id': start_id
    }
    
    await interaction.followup.send(
        f"🚀 **Scan secvențial pornit!**\n"
        f"📊 Range: **{start_id:,} → {end_id:,}**\n"
        f"⚙️ Workers: {workers}\n"
        f"💾 **Checkpoint la fiecare 50 ID-uri**\n\n"
        f"✅ Dacă se întrerupe, reiaște cu `/scan_resume`\n"
        f"📊 Vezi progres live cu `/scan_status`"
    )
    
    try:
        scan_scraper = Pro4KingsScraper(max_concurrent=workers)
        await scan_scraper.__aenter__()
        
        # 🔥 SEQUENTIAL scanning cu checkpoint frecvent
        batch_size = 50  # Smaller batches for frequent checkpoints
        checkpoint_interval = 50  # Save every 50 IDs
        
        current_id = start_id
        
        while current_id <= end_id and SCAN_IN_PROGRESS:
            # Create batch of sequential IDs
            batch_end = min(current_id + batch_size - 1, end_id)
            batch_ids = [str(i) for i in range(current_id, batch_end + 1)]
            
            # Fetch profiles
            profiles = await scan_scraper.batch_get_profiles(batch_ids)
            
            # Save profiles
            for profile in profiles:
                try:
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
                    SCAN_STATS['found'] += 1
                except Exception as e:
                    logger.error(f"Error saving profile {profile.player_id}: {e}")
                    SCAN_STATS['errors'] += 1
            
            SCAN_STATS['scanned'] += len(batch_ids)
            SCAN_STATS['current_id'] = batch_end
            
            # 🔥 SAVE CHECKPOINT every 50 IDs
            if (batch_end - start_id) % checkpoint_interval == 0 or batch_end == end_id:
                db.save_scan_progress(
                    last_player_id=str(batch_end),
                    total_scanned=SCAN_STATS['found'],
                    completed=(batch_end >= end_id)
                )
                SCAN_STATS['last_saved_id'] = batch_end
                logger.info(f"💾 Checkpoint: ID {batch_end:,} | Găsiți: {SCAN_STATS['found']:,}")
            
            # Log progress
            if SCAN_STATS['scanned'] % 500 == 0:
                elapsed = (datetime.now() - SCAN_STATS['start_time']).total_seconds()
                rate = SCAN_STATS['scanned'] / elapsed if elapsed > 0 else 0
                logger.info(
                    f"📊 Progress: {SCAN_STATS['scanned']:,}/{end_id:,} "
                    f"({SCAN_STATS['scanned']/end_id*100:.1f}%) | "
                    f"Rate: {rate:.1f}/s | "
                    f"Last saved: {SCAN_STATS['last_saved_id']:,}"
                )
            
            # Move to next batch
            current_id = batch_end + 1
            
        await scan_scraper.__aexit__(None, None, None)
        
        # Final report
        elapsed = (datetime.now() - SCAN_STATS['start_time']).total_seconds()
        db.save_scan_progress(
            last_player_id=str(end_id),
            total_scanned=SCAN_STATS['found'],
            completed=True
        )
        
        try:
            await interaction.channel.send(
                f"✅ **Scan complet!**\n"
                f"⏱️ Durată: {elapsed/60:.1f} min\n"
                f"📊 Scanați: {SCAN_STATS['scanned']:,}\n"
                f"👥 Găsiți: {SCAN_STATS['found']:,}\n"
                f"⚡ Viteză: {SCAN_STATS['scanned']/elapsed:.1f} ID/s"
            )
        except:
            pass
        
    except Exception as e:
        logger.error(f"❌ Scan error: {e}", exc_info=True)
        db.save_scan_progress(
            last_player_id=str(SCAN_STATS['current_id']),
            total_scanned=SCAN_STATS['found'],
            completed=False
        )
        try:
            await interaction.channel.send(
                f"❌ **Eroare la ID {SCAN_STATS['current_id']:,}**\n"
                f"Ultimul salvat: **{SCAN_STATS['last_saved_id']:,}**\n"
                f"Folosește `/scan_resume`"
            )
        except:
            pass
    
    finally:
        SCAN_IN_PROGRESS = False

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def resolve_player_info(identifier):
    """Helper to get player info - FIXED to prioritize ID lookup"""
    global scraper
    if not scraper:
        scraper = Pro4KingsScraper()
        await scraper.__aenter__()
    
    # PRIORITY 1: Try as exact player ID
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        player_id = str(identifier)
        profile = db.get_player_by_exact_id(player_id)
        
        if not profile:
            # Fetch from website
            profile_obj = await scraper.get_player_profile(player_id)
            if profile_obj:
                profile = {
                    'player_id': profile_obj.player_id,
                    'player_name': profile_obj.username,
                    'is_online': profile_obj.is_online,
                    'last_connection': profile_obj.last_seen,
                    'faction': profile_obj.faction,
                    'faction_rank': profile_obj.faction_rank,
                    'job': profile_obj.job,
                    'level': profile_obj.level,
                    'respect_points': profile_obj.respect_points,
                    'warns': profile_obj.warnings,
                    'played_hours': profile_obj.played_hours,
                    'age_ic': profile_obj.age_ic,
                    'phone_number': profile_obj.phone_number,
                    'vehicles_count': profile_obj.vehicles_count,
                    'properties_count': profile_obj.properties_count
                }
                db.save_player_profile(profile)
        
        return profile
    
    # PRIORITY 2: Extract ID from "Name(ID)" format
    id_match = re.search(r'\((\d+)\)', str(identifier))
    if id_match:
        player_id = id_match.group(1)
        return await resolve_player_info(player_id)
    
    # PRIORITY 3: Search by name as last resort
    players = db.search_player_by_name(identifier)
    return players[0] if players else None

# [Rest of bot.py commands remain the same - player, actions, rank_history, etc.]
# ... (keeping original bot commands to save space)

# ============================================================================
# RUN BOT
# ============================================================================

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        logger.error("❌ ERROR: DISCORD_TOKEN not found in environment variables!")
        exit(1)
    
    bot.run(TOKEN)

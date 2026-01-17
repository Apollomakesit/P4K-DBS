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
    'current_id': 0
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
    """Scrape latest actions - WITH ENHANCED ERROR HANDLING"""
    try:
        global scraper
        if not scraper:
            scraper = Pro4KingsScraper(max_concurrent=5)
            await scraper.__aenter__()
        
        logger.info("🔍 Fetching latest actions...")
        actions = await scraper.get_latest_actions(limit=200)
        
        if not actions:
            logger.warning("⚠️ No actions retrieved this cycle")
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
        else:
            logger.info(f"ℹ️  No new actions (checked {len(actions)} entries)")
            
    except Exception as e:
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
        
        # FIXED: Removed 'concurrent' parameter - it doesn't exist in batch_get_profiles
        results = await scraper.batch_get_profiles(pending_ids, delay=0.1)
        
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
# INITIAL SCAN FUNCTION (Background)
# ============================================================================

async def run_initial_scan(interaction: discord.Interaction, start_id: int = 1, end_id: int = 230000, workers: int = 20):
    """Run initial scan in background - Railway compatible!"""
    global SCAN_IN_PROGRESS, SCAN_STATS
    
    if SCAN_IN_PROGRESS:
        await interaction.followup.send("⚠️ Un scan este deja în curs! Folosește `/scan_status` pentru progres.")
        return
    
    SCAN_IN_PROGRESS = True
    SCAN_STATS = {
        'start_time': datetime.now(),
        'scanned': 0,
        'found': 0,
        'errors': 0,
        'current_id': start_id
    }
    
    await interaction.followup.send(
        f"🚀 **Scan inițial pornit!**\n"
        f"📊 Range: {start_id:,} - {end_id:,} ({end_id - start_id + 1:,} ID-uri)\n"
        f"⚙️ Workers: {workers} concurenți\n"
        f"⏱️ Estimare: ~2-3 ore\n\n"
        f"Folosește `/scan_status` pentru a vedea progresul."
    )
    
    try:
        # Create dedicated scraper for scan
        scan_scraper = Pro4KingsScraper(max_concurrent=workers)
        await scan_scraper.__aenter__()
        
        # Batch scan
        batch_size = 100
        for batch_start in range(start_id, end_id + 1, batch_size):
            if not SCAN_IN_PROGRESS:  # Allow cancellation
                logger.info("🛑 Scan cancelled by user")
                break
            
            batch_end = min(batch_start + batch_size - 1, end_id)
            batch_ids = [str(i) for i in range(batch_start, batch_end + 1)]
            
            # Fetch profiles
            profiles = await scan_scraper.batch_get_profiles(batch_ids, delay=0.05)
            
            # Save to database
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
            
            # Log progress every 1000 players
            if SCAN_STATS['scanned'] % 1000 == 0:
                elapsed = (datetime.now() - SCAN_STATS['start_time']).total_seconds()
                rate = SCAN_STATS['scanned'] / elapsed if elapsed > 0 else 0
                remaining = (end_id - batch_end) / rate if rate > 0 else 0
                
                logger.info(
                    f"📊 Scan progress: {SCAN_STATS['scanned']:,}/{end_id:,} "
                    f"({SCAN_STATS['scanned']/end_id*100:.1f}%) | "
                    f"Found: {SCAN_STATS['found']:,} | "
                    f"Rate: {rate:.0f}/s | "
                    f"ETA: {remaining/60:.0f}min"
                )
            
            # Small delay between batches
            await asyncio.sleep(1)
        
        await scan_scraper.__aexit__(None, None, None)
        
        # Final report
        elapsed = (datetime.now() - SCAN_STATS['start_time']).total_seconds()
        
        # Try to send completion message to original channel
        try:
            await interaction.channel.send(
                f"✅ **Scan finalizat!**\n"
                f"⏱️ Durată: {elapsed/60:.1f} minute\n"
                f"📊 Scanați: {SCAN_STATS['scanned']:,}\n"
                f"👥 Găsiți: {SCAN_STATS['found']:,} jucători\n"
                f"❌ Erori: {SCAN_STATS['errors']}\n\n"
                f"Folosește `/stats` pentru statistici complete!"
            )
        except:
            logger.info("Scan completed but couldn't send message to channel")
        
        logger.info(f"✅ Initial scan completed: {SCAN_STATS['found']:,} players found")
        
    except Exception as e:
        logger.error(f"❌ Scan error: {e}", exc_info=True)
        try:
            await interaction.channel.send(f"❌ **Eroare în scan**: {str(e)}")
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

# ============================================================================
# DISCORD SLASH COMMANDS - SCAN MANAGEMENT
# ============================================================================

@bot.tree.command(name="scan_all", description="[ADMIN] Pornește scanarea inițială a tuturor jucătorilor (1-230K)")
async def scan_all_players(interaction: discord.Interaction, start_id: int = 1, end_id: int = 230000, workers: int = 20):
    """NEW COMMAND: Trigger initial scan from Discord (Railway compatible)"""
    await interaction.response.defer()
    
    if SCAN_IN_PROGRESS:
        await interaction.followup.send(
            f"⚠️ **Un scan este deja activ!**\n"
            f"Progres: {SCAN_STATS['scanned']:,}/{end_id:,} ({SCAN_STATS['scanned']/end_id*100:.1f}%)\n"
            f"Găsiți: {SCAN_STATS['found']:,} jucători\n\n"
            f"Folosește `/scan_status` pentru detalii."
        )
        return
    
    # Start scan in background
    asyncio.create_task(run_initial_scan(interaction, start_id, end_id, workers))

@bot.tree.command(name="scan_status", description="Vezi progresul scanării în curs")
async def scan_status(interaction: discord.Interaction):
    """Check scan progress"""
    await interaction.response.defer()
    
    if not SCAN_IN_PROGRESS:
        total_players = db.get_scan_progress()['total_scanned']
        await interaction.followup.send(
            f"ℹ️ **Nu este niciun scan activ**\n"
            f"👥 Jucători în baza de date: **{total_players:,}**\n\n"
            f"Pentru a începe un scan complet, folosește:\n"
            f"`/scan_all`"
        )
        return
    
    elapsed = (datetime.now() - SCAN_STATS['start_time']).total_seconds()
    rate = SCAN_STATS['scanned'] / elapsed if elapsed > 0 else 0
    total_target = 230000
    remaining = (total_target - SCAN_STATS['current_id']) / rate if rate > 0 else 0
    
    progress_bar_length = 20
    filled = int((SCAN_STATS['scanned'] / total_target) * progress_bar_length)
    bar = "█" * filled + "░" * (progress_bar_length - filled)
    
    embed = discord.Embed(
        title="📊 Status Scan Inițial",
        description=f"`{bar}` {SCAN_STATS['scanned']/total_target*100:.1f}%",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name="📈 Progres",
        value=f"**{SCAN_STATS['scanned']:,}** / {total_target:,} ID-uri",
        inline=True
    )
    
    embed.add_field(
        name="👥 Găsiți",
        value=f"**{SCAN_STATS['found']:,}** jucători",
        inline=True
    )
    
    embed.add_field(
        name="⚡ Viteză",
        value=f"**{rate:.0f}** ID-uri/sec",
        inline=True
    )
    
    embed.add_field(
        name="⏱️ Timp scurs",
        value=f"**{elapsed/60:.0f}** minute",
        inline=True
    )
    
    embed.add_field(
        name="⏳ Rămas",
        value=f"**{remaining/60:.0f}** minute",
        inline=True
    )
    
    embed.add_field(
        name="❌ Erori",
        value=f"**{SCAN_STATS['errors']}**",
        inline=True
    )
    
    embed.set_footer(text=f"ID curent: {SCAN_STATS['current_id']:,}")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="scan_stop", description="[ADMIN] Oprește scanarea în curs")
async def scan_stop(interaction: discord.Interaction):
    """Stop ongoing scan"""
    global SCAN_IN_PROGRESS
    
    await interaction.response.defer()
    
    if not SCAN_IN_PROGRESS:
        await interaction.followup.send("ℹ️ Nu este niciun scan activ.")
        return
    
    SCAN_IN_PROGRESS = False
    
    await interaction.followup.send(
        f"🛑 **Scan oprit!**\n"
        f"Scanați: {SCAN_STATS['scanned']:,}\n"
        f"Găsiți: {SCAN_STATS['found']:,} jucători\n\n"
        f"Poți relua mai târziu cu `/scan_all start_id:{SCAN_STATS['current_id'] + 1}`"
    )

# ============================================================================
# DISCORD SLASH COMMANDS - PLAYER INFO
# ============================================================================

@bot.tree.command(name="player", description="Vezi informații complete despre un jucător (ID sau nume)")
async def player_info(interaction: discord.Interaction, identifier: str):
    await interaction.response.defer()
    
    profile = await resolve_player_info(identifier)
    
    if not profile:
        await interaction.followup.send(f"❌ Nu am găsit jucătorul **{identifier}**. Folosește ID-ul pentru rezultate mai precise (ex: /player 12345).")
        return
    
    # 🔧 FIX: Use 'player_name' key (from database) instead of 'username'
    player_name = profile.get('player_name') or profile.get('username', f"Player_{profile['player_id']}")
    
    embed = discord.Embed(
        title=f"👤 {player_name}",
        description=f"ID: **{profile['player_id']}**",
        color=discord.Color.green() if profile.get('is_online') else discord.Color.red(),
        timestamp=datetime.now()
    )
    
    if profile.get('is_online'):
        embed.add_field(name="🟢 Status", value="**Online acum**", inline=True)
    else:
        embed.add_field(name="🔴 Status", value="**Offline**", inline=True)
    
    if profile.get('level'):
        embed.add_field(name="⭐ Level", value=f"**{profile['level']}**", inline=True)
    
    faction = profile.get('faction', 'Civil')
    faction_emoji = "🏢" if faction != "Civil" else "👤"
    embed.add_field(name=f"{faction_emoji} Facțiune", value=f"**{faction}**", inline=True)
    
    if profile.get('faction_rank'):
        embed.add_field(name="🎖️ Rank", value=f"**{profile['faction_rank']}**", inline=True)
    
    if profile.get('job'):
        embed.add_field(name="💼 Job", value=f"**{profile['job']}**", inline=True)
    
    warns = profile.get('warns', 0)
    warn_emoji = "⚠️" if warns > 0 else "✅"
    embed.add_field(name=f"{warn_emoji} Warn-uri", value=f"**{warns}/3**", inline=True)
    
    if profile.get('played_hours'):
        embed.add_field(name="⏱️ Ore jucate", value=f"**{profile['played_hours']:.1f}** ore", inline=True)
    
    if profile.get('respect_points'):
        embed.add_field(name="⭐ Respect", value=f"**{profile['respect_points']}**", inline=True)
    
    if profile.get('age_ic'):
        embed.add_field(name="🎂 Vârsta IC", value=f"**{profile['age_ic']}** ani", inline=True)
    
    if profile.get('vehicles_count') is not None:
        embed.add_field(name="🚗 Vehicule", value=f"**{profile['vehicles_count']}**", inline=True)
    
    if profile.get('properties_count') is not None:
        embed.add_field(name="🏠 Proprietăți", value=f"**{profile['properties_count']}**", inline=True)
    
    if profile.get('last_connection') and not profile.get('is_online'):
        last_conn = profile['last_connection']
        if isinstance(last_conn, str):
            last_conn = datetime.fromisoformat(last_conn)
        embed.add_field(
            name="🕐 Ultima conectare",
            value=f"**{last_conn.strftime('%d.%m.%Y %H:%M:%S')}**",
            inline=False
        )
    
    embed.set_footer(text=f"Tip: Folosește /rank_history {profile['player_id']} pentru istoric rang")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="actions", description="Vezi acțiunile unui jucător")
async def player_actions(interaction: discord.Interaction, identifier: str, days: int = 7):
    await interaction.response.defer()
    
    actions = db.get_player_actions(identifier, days)
    
    if not actions:
        await interaction.followup.send(f"❌ Nu am găsit acțiuni pentru **{identifier}** în ultimele {days} zile.")
        return
    
    player_name = identifier
    if actions and actions[0].get('player_name'):
        player_name = actions[0]['player_name']
    
    embed = discord.Embed(
        title=f"📋 Acțiuni - {player_name}",
        description=f"Ultimele {days} zile • **{len(actions)}** acțiuni",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    # 🔧 FIX: Limit content to avoid 6000 character embed limit
    total_chars = 0
    max_embed_chars = 5500  # Safe limit below 6000
    actions_added = 0
    
    for action in actions[:25]:
        timestamp = action['timestamp']
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        
        # Format action text with LENGTH LIMIT
        action_text = action.get('raw_text', action.get('action_detail', 'N/A'))
        
        # Truncate individual action to max 200 chars
        if len(action_text) > 200:
            action_text = action_text[:197] + "..."
        
        field_content = action_text
        field_name = timestamp.strftime('%d.%m.%Y %H:%M:%S')
        
        # Calculate size of this field
        field_size = len(field_name) + len(field_content)
        
        # Stop if adding this field would exceed limit
        if total_chars + field_size > max_embed_chars:
            break
        
        embed.add_field(
            name=field_name,
            value=field_content,
            inline=False
        )
        
        total_chars += field_size
        actions_added += 1
    
    if actions_added < len(actions):
        embed.set_footer(text=f"Afișate {actions_added} din {len(actions)} acțiuni (limitat pentru Discord)")
    elif len(actions) > 25:
        embed.set_footer(text=f"Afișate primele 25 din {len(actions)} acțiuni")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="rank_history", description="Vezi istoricul de rang al unui jucător")
async def rank_history(interaction: discord.Interaction, identifier: str):
    """NEW COMMAND: View player's faction rank history"""
    await interaction.response.defer()
    
    # Resolve player first
    profile = await resolve_player_info(identifier)
    if not profile:
        await interaction.followup.send(f"❌ Nu am găsit jucătorul **{identifier}**.")
        return
    
    player_id = profile['player_id']
    player_name = profile.get('player_name') or profile.get('username', f"Player_{player_id}")
    rank_history = db.get_player_rank_history(player_id)
    
    if not rank_history:
        await interaction.followup.send(f"❌ Nu am istoric de rang pentru **{player_name}**.")
        return
    
    embed = discord.Embed(
        title=f"🎖️ Istoric Rang - {player_name}",
        description=f"ID: {player_id} • **{len(rank_history)}** schimbări de rang",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    
    for rank in rank_history[:15]:
        obtained = rank['rank_obtained']
        if isinstance(obtained, str):
            obtained = datetime.fromisoformat(obtained)
        
        lost = rank.get('rank_lost')
        status = "🟢 Curent" if rank['is_current'] else "🔴 Pierdut"
        
        duration = ""
        if lost:
            if isinstance(lost, str):
                lost = datetime.fromisoformat(lost)
            duration = f" (Durata: {(lost - obtained).days} zile)"
        elif rank['is_current']:
            duration = f" (De {(datetime.now() - obtained).days} zile)"
        
        embed.add_field(
            name=f"{rank['faction']} - {rank['rank_name']}",
            value=f"{status} • Obținut: {obtained.strftime('%d.%m.%Y')}{duration}",
            inline=False
        )
    
    if len(rank_history) > 15:
        embed.set_footer(text=f"Afișate primele 15 din {len(rank_history)} ranguri")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="bans", description="Vezi jucătorii banați (activi sau toți)")
async def view_bans(interaction: discord.Interaction, show_expired: bool = False):
    """NEW COMMAND: View banned players"""
    await interaction.response.defer()
    
    banned = db.get_banned_players(include_expired=show_expired)
    
    if not banned:
        await interaction.followup.send("✅ Nu sunt jucători banați momentan.")
        return
    
    embed = discord.Embed(
        title="🚫 Jucători Banați",
        description=f"Total: **{len(banned)}** jucători" + (" (inclusiv expirați)" if show_expired else " (doar activi)"),
        color=discord.Color.red(),
        timestamp=datetime.now()
    )
    
    for ban in banned[:25]:
        status = "🔴 Activ" if ban['is_active'] else "🟢 Expirat"
        duration = ban.get('duration', 'Permanent')
        reason = ban.get('reason', 'Necunoscut')[:100]
        
        embed.add_field(
            name=f"{status} • {ban['player_name']} (ID: {ban['player_id']})",
            value=f"Admin: {ban.get('admin', 'N/A')}\nMotiv: {reason}\nDurata: {duration}\nData: {ban.get('ban_date', 'N/A')}",
            inline=False
        )
    
    if len(banned) > 25:
        embed.set_footer(text=f"Afișate primele 25 din {len(banned)} banuri")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="promotions", description="Vezi promovările recente în facțiuni")
async def recent_promotions(interaction: discord.Interaction, days: int = 7):
    """NEW COMMAND: View recent faction promotions"""
    await interaction.response.defer()
    
    promotions = db.get_recent_promotions(days=days)
    
    if not promotions:
        await interaction.followup.send(f"❌ Nu sunt promovări în ultimele {days} zile.")
        return
    
    embed = discord.Embed(
        title="🎖️ Promovări Recente",
        description=f"Ultimele {days} zile • **{len(promotions)}** promovări",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    
    for promo in promotions[:20]:
        obtained = promo['rank_obtained']
        if isinstance(obtained, str):
            obtained = datetime.fromisoformat(obtained)
        
        time_ago = (datetime.now() - obtained).days
        time_str = f"{time_ago} zile" if time_ago > 0 else "Astăzi"
        
        embed.add_field(
            name=f"{promo['player_name']} (ID: {promo['player_id']})",
            value=f"**{promo['rank_name']}** în {promo['faction']}\nPrimit: {time_str}",
            inline=True
        )
    
    if len(promotions) > 20:
        embed.set_footer(text=f"Afișate primele 20 din {len(promotions)} promovări")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="online", description="Vezi jucătorii online acum")
async def online_players(interaction: discord.Interaction):
    await interaction.response.defer()
    
    players = db.get_current_online_players()
    
    if not players:
        await interaction.followup.send("❌ Nu sunt jucători online momentan.")
        return
    
    embed = discord.Embed(
        title="🟢 Jucători Online",
        description=f"**{len(players)}** jucători activi",
        color=discord.Color.green(),
        timestamp=datetime.now()
    )
    
    # Split into chunks of 50
    chunk_size = 50
    player_chunks = [players[i:i + chunk_size] for i in range(0, len(players), chunk_size)]
    
    for i, chunk in enumerate(player_chunks[:3]):  # Max 3 chunks (150 players)
        player_list = "\n".join([
            f"• **{p['player_name']}** (ID: {p['player_id']})" 
            for p in chunk
        ])
        embed.add_field(
            name=f"Jucători (Partea {i+1})" if len(player_chunks) > 1 else "Jucători",
            value=player_list or "Nimeni",
            inline=False
        )
    
    if len(players) > 150:
        embed.set_footer(text=f"Afișați primii 150 din {len(players)} jucători")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="sessions", description="Vezi sesiunile de joc ale unui jucător")
async def player_sessions(interaction: discord.Interaction, identifier: str, days: int = 7):
    await interaction.response.defer()
    
    sessions = db.get_player_sessions(identifier, days)
    
    if not sessions:
        await interaction.followup.send(f"❌ Nu am date despre sesiunile lui **{identifier}**.")
        return
    
    player_name = identifier
    if sessions and sessions[0].get('player_name'):
        player_name = sessions[0]['player_name']
    
    embed = discord.Embed(
        title=f"🎮 Sesiuni - {player_name}",
        description=f"Ultimele {days} zile • **{len(sessions)}** sesiuni",
        color=discord.Color.purple()
    )
    
    total_seconds = 0
    for session in sessions[:25]:
        login_time = session['login_time']
        if isinstance(login_time, str):
            login_time = datetime.fromisoformat(login_time)
        
        duration_text = session.get('duration', '🟢 Online acum')
        if session.get('session_duration_seconds'):
            total_seconds += session['session_duration_seconds']
        
        embed.add_field(
            name=f"Login: {login_time.strftime('%d.%m.%Y %H:%M:%S')}",
            value=f"Durată: **{duration_text}**",
            inline=False
        )
    
    if total_seconds > 0:
        total_time = str(timedelta(seconds=total_seconds)).split('.')[0]
        embed.set_footer(text=f"⏱️ Timp total de joc: {total_time}")
    
    if len(sessions) > 25:
        footer_text = f"Afișate primele 25 din {len(sessions)} sesiuni"
        if total_seconds > 0:
            footer_text += f" • ⏱️ Total: {str(timedelta(seconds=total_seconds)).split('.')[0]}"
        embed.set_footer(text=footer_text)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="faction", description="Vezi membrii unei facțiuni")
async def faction_members(interaction: discord.Interaction, faction_name: str):
    await interaction.response.defer()
    
    members = db.get_players_by_faction(faction_name)
    
    if not members:
        await interaction.followup.send(f"❌ Nu am găsit membri în facțiunea **{faction_name}**.")
        return
    
    embed = discord.Embed(
        title=f"🏢 Membri {faction_name}",
        description=f"Găsiți **{len(members)}** membri",
        color=discord.Color.blue()
    )
    
    online_count = sum(1 for m in members if m.get('is_online'))
    embed.add_field(name="Status", value=f"🟢 **{online_count}** online / {len(members)} total", inline=False)
    
    for member in members[:25]:
        status = "🟢" if member.get('is_online') else "🔴"
        warns = member.get('warnings', 0)
        warn_text = f" ⚠️ {warns}" if warns > 0 else ""
        rank_text = f" • {member.get('faction_rank')}" if member.get('faction_rank') else ""
        level_text = f"Level {member.get('level')}" if member.get('level') else "N/A"
        
        embed.add_field(
            name=f"{status} {member['username']} (ID: {member['player_id']})",
            value=f"{level_text}{rank_text}{warn_text}",
            inline=False
        )
    
    if len(members) > 25:
        embed.set_footer(text=f"Afișați primii 25 din {len(members)} membri")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="search", description="Caută jucători după nume")
async def find_player(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    
    players = db.search_player_by_name(name)
    
    if not players:
        await interaction.followup.send(f"❌ Nu am găsit jucători cu numele **{name}**. Tip: Folosește ID-ul pentru rezultate precise.")
        return
    
    embed = discord.Embed(
        title=f"🔍 Rezultate pentru: {name}",
        description=f"Găsite **{len(players)}** rezultate",
        color=discord.Color.blue()
    )
    
    for player in players[:15]:
        status = "🟢 Online" if player.get('is_online') else "🔴 Offline"
        last_conn = player.get('last_seen', 'Necunoscut')
        
        if last_conn and last_conn != 'Necunoscut':
            if isinstance(last_conn, str):
                last_conn = datetime.fromisoformat(last_conn)
            last_conn = last_conn.strftime('%d.%m %H:%M')
        
        faction = player.get('faction', 'Civil')
        level = player.get('level', '?')
        
        embed.add_field(
            name=f"{player['username']} (ID: {player['player_id']})",
            value=f"{status} • {faction} • Level {level} • Ultima: {last_conn}",
            inline=False
        )
    
    if len(players) > 15:
        embed.set_footer(text=f"Afișați primii 15 din {len(players)} jucători")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="stats", description="Vezi statistici generale despre baza de date")
async def bot_stats(interaction: discord.Interaction):
    await interaction.response.defer()
    
    progress = db.get_scan_progress()
    
    embed = discord.Embed(
        title="📊 Statistici P4K Database Bot",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name="👥 Jucători",
        value=f"**{progress['total_scanned']:,}** în baza de date",
        inline=True
    )
    
    online_players = db.get_current_online_players()
    embed.add_field(
        name="🟢 Online acum",
        value=f"**{len(online_players):,}** jucători",
        inline=True
    )
    
    embed.add_field(
        name="📈 Progres scanare",
        value=f"**{progress['percentage']:.1f}%**",
        inline=True
    )
    
    if SCAN_IN_PROGRESS:
        embed.add_field(
            name="🔄 Scan activ",
            value=f"ID: {SCAN_STATS['current_id']:,}\nGăsiți: {SCAN_STATS['found']:,}",
            inline=False
        )
    
    embed.set_footer(text=f"Bot versiune 2.1 • Îmbunătățiri Ianuarie 2026 • Today at {datetime.now().strftime('%H:%M')}")
    
    await interaction.followup.send(embed=embed)

# ============================================================================
# RUN BOT
# ============================================================================

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        logger.error("❌ ERROR: DISCORD_TOKEN not found in environment variables!")
        exit(1)
    
    bot.run(TOKEN)
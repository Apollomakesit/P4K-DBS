import discord
from discord.ext import commands, tasks
import os
from datetime import datetime, timedelta
from database import Database
from scraper import Pro4KingsScraper
import asyncio
import logging

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
    logger.info(f'✅ {bot.user} is now running!')
    await bot.tree.sync()
    
    # Start monitoring tasks
    scrape_actions.start()
    scrape_online_players.start()
    update_pending_profiles.start()
    check_banned_players.start()
    
    logger.info('🚀 All monitoring tasks started!')
    print(f'✅ {bot.user} is online and monitoring!')

@bot.event
async def on_close():
    """Cleanup when bot shuts down"""
    if scraper:
        await scraper.__aexit__(None, None, None)
    logger.info('👋 Bot shutting down')

# ============================================================================
# BACKGROUND MONITORING TASKS
# ============================================================================

@tasks.loop(seconds=30)
async def scrape_actions():
    """Scrape latest actions every 30 seconds - INDEFINITE STORAGE"""
    try:
        global scraper
        if not scraper:
            scraper = Pro4KingsScraper()
            await scraper.__aenter__()
        
        actions = await scraper.get_latest_actions(limit=200)
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
            
            if not db.action_exists(action.timestamp, action.raw_text):
                db.save_action(action_dict)
                new_count += 1
                
                # Mark players for profile update
                if action.player_id:
                    new_player_ids.add((action.player_id, action.player_name))
                    db.mark_player_for_update(action.player_id, action.player_name)
                
                if action.target_player_id:
                    new_player_ids.add((action.target_player_id, action.target_player_name))
                    db.mark_player_for_update(action.target_player_id, action.target_player_name)
        
        if new_count > 0:
            logger.info(f"✓ Saved {new_count} new actions, marked {len(new_player_ids)} players for update")
            
    except Exception as e:
        logger.error(f"✗ Error scraping actions: {e}", exc_info=True)

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
        
        # Batch fetch profiles
        results = await scraper.batch_get_profiles(pending_ids, delay=0.1, concurrent=25)
        
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
    """Check banned players list hourly"""
    try:
        global scraper
        if not scraper:
            scraper = Pro4KingsScraper()
            await scraper.__aenter__()
        
        banned = await scraper.get_banned_players()
        
        for ban_data in banned:
            db.save_banned_player(ban_data)
        
        logger.info(f"✓ Updated {len(banned)} banned players")
        
    except Exception as e:
        logger.error(f"✗ Error checking banned players: {e}", exc_info=True)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def resolve_player_info(identifier):
    """Helper to get player info from ID or name"""
    global scraper
    if not scraper:
        scraper = Pro4KingsScraper()
        await scraper.__aenter__()
    
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        player_id = str(identifier)
        profile = db.get_player_last_connection(player_id)
        
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
    else:
        players = db.search_player_by_name(identifier)
        return players[0] if players else None

# ============================================================================
# DISCORD SLASH COMMANDS - PLAYER INFO
# ============================================================================

@bot.tree.command(name="player", description="Vezi informații complete despre un jucător (ID sau nume)")
async def player_info(interaction: discord.Interaction, identifier: str):
    await interaction.response.defer()
    
    profile = await resolve_player_info(identifier)
    
    if not profile:
        await interaction.followup.send(f"❌ Nu am găsit jucătorul **{identifier}**.")
        return
    
    embed = discord.Embed(
        title=f"👤 {profile['player_name']}",
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
    
    for action in actions[:25]:
        timestamp = action['timestamp']
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        
        # Format action text
        action_text = action.get('raw_text', action.get('action_detail', 'N/A'))
        if len(action_text) > 1024:
            action_text = action_text[:1020] + "..."
        
        embed.add_field(
            name=timestamp.strftime('%d.%m.%Y %H:%M:%S'),
            value=action_text,
            inline=False
        )
    
    if len(actions) > 25:
        embed.set_footer(text=f"Afișate primele 25 din {len(actions)} acțiuni")
    
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
        await interaction.followup.send(f"❌ Nu am găsit jucători cu numele **{name}**.")
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
    
    embed.set_footer(text=f"Bot versiune 2.0 • Stocare indefinită activată")
    
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

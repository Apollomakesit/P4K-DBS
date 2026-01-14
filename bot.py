import discord
from discord.ext import commands, tasks
import os
from datetime import datetime, timedelta
from database import Database
from scraper import Pro4KingsScraper

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

db = Database(os.getenv('DATABASE_URL', 'sqlite:///pro4kings.db'))
scraper = Pro4KingsScraper()

@bot.event
async def on_ready():
    print(f'✅ {bot.user} is now running!')
    await bot.tree.sync()
    scrape_actions.start()
    scrape_online_players.start()
    update_pending_profiles.start()
    cleanup_old_data.start()
    print('🚀 All monitoring tasks started!')

# ============================================================================
# BACKGROUND MONITORING TASKS
# ============================================================================

@tasks.loop(minutes=2)
async def scrape_actions():
    """Scrape latest actions every 2 minutes"""
    try:
        actions = await scraper.get_latest_actions()
        new_player_ids = set()
        
        for action in actions:
            if not db.action_exists(action['timestamp'], action['text']):
                db.save_action(action)
                print(f"✓ New action: {action['text'][:60]}...")
                
                # Mark players for profile update
                if action.get('from_id'):
                    new_player_ids.add((action['from_id'], action.get('from_player')))
                if action.get('to_id'):
                    new_player_ids.add((action['to_id'], action.get('to_player')))
        
        # Mark all detected players for profile update
        for player_id, player_name in new_player_ids:
            db.mark_player_for_update(player_id, player_name)
        
        if new_player_ids:
            print(f"📝 Marked {len(new_player_ids)} players for profile update")
            
    except Exception as e:
        print(f"✗ Error scraping actions: {e}")

@tasks.loop(minutes=2)
async def scrape_online_players():
    """Scrape online players every 2 minutes (handles 500+ players efficiently)"""
    try:
        online_players = await scraper.get_online_players()
        current_time = datetime.now()
        
        previous_online = db.get_current_online_players()
        previous_ids = {p['player_id'] for p in previous_online}
        current_ids = {p['player_id'] for p in online_players}
        
        # Detect logins
        new_logins = current_ids - previous_ids
        for player in online_players:
            if player['player_id'] in new_logins:
                db.save_login(player['player_id'], player['player_name'], current_time)
                db.mark_player_for_update(player['player_id'], player['player_name'])
                print(f"✓ Login: {player['player_name']} (ID: {player['player_id']})")
        
        # Detect logouts
        logouts = previous_ids - current_ids
        for player_id in logouts:
            db.save_logout(player_id, current_time)
            player_name = next((p['player_name'] for p in previous_online if p['player_id'] == player_id), 'Unknown')
            print(f"✓ Logout: {player_name} (ID: {player_id})")
        
        db.update_online_players(online_players)
        
        # Mark currently online players for profile update
        for player in online_players:
            db.mark_player_for_update(player['player_id'], player['player_name'])
        
        print(f"👥 Online: {len(online_players)} players | New: {len(new_logins)} | Left: {len(logouts)}")
        
    except Exception as e:
        print(f"✗ Error scraping online players: {e}")

@tasks.loop(minutes=3)
async def update_pending_profiles():
    """Update profiles for detected players (100 profiles per run = ~33 profiles/minute)"""
    try:
        pending_ids = db.get_players_pending_update(limit=100)
        
        if not pending_ids:
            return
        
        print(f"🔄 Updating {len(pending_ids)} pending profiles...")
        results = await scraper.batch_get_profiles(pending_ids, delay=0.5)
        
        for result in results:
            db.save_player_profile(result)
            db.reset_player_priority(result['player_id'])
        
        print(f"✓ Updated {len(results)} profiles with full data")
        
    except Exception as e:
        print(f"✗ Error updating pending profiles: {e}")

@tasks.loop(hours=6)
async def cleanup_old_data():
    """Delete data older than 30 days"""
    try:
        deleted = db.cleanup_old_data(days=30)
        print(f"🗑️ Cleaned up {deleted} old records")
    except Exception as e:
        print(f"✗ Error cleaning data: {e}")

# ============================================================================
# DISCORD COMMANDS - PLAYER INFO
# ============================================================================

@bot.tree.command(name="player_info", description="Vezi informații complete despre un jucător")
async def player_info(interaction: discord.Interaction, player_id: int):
    await interaction.response.defer()
    
    profile = db.get_player_last_connection(player_id)
    
    if not profile:
        profile_data = await scraper.get_player_profile(player_id)
        
        if not profile_data:
            await interaction.followup.send(f"❌ Nu am găsit jucătorul cu ID **{player_id}**.")
            return
        
        db.save_player_profile(profile_data)
        profile = profile_data
    
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
    
    faction = profile.get('faction', 'Necunoscut')
    faction_emoji = "🏢" if faction != "Civil" else "👤"
    embed.add_field(name=f"{faction_emoji} Facțiune", value=f"**{faction}**", inline=True)
    
    rank = profile.get('faction_rank')
    if rank:
        rank_history = db.get_player_rank_history(player_id)
        if rank_history and rank_history[0].get('is_current'):
            rank_obtained = rank_history[0].get('rank_obtained')
            if rank_obtained:
                if isinstance(rank_obtained, str):
                    rank_obtained = datetime.fromisoformat(rank_obtained)
                duration = datetime.now() - rank_obtained
                days = duration.days
                embed.add_field(name="🎖️ Rank Facțiune", value=f"**{rank}**\n*De {days} zile*", inline=True)
            else:
                embed.add_field(name="🎖️ Rank Facțiune", value=f"**{rank}**", inline=True)
        else:
            embed.add_field(name="🎖️ Rank Facțiune", value=f"**{rank}**", inline=True)
    
    job = profile.get('job', 'Necunoscut')
    embed.add_field(name="💼 Job", value=f"**{job}**", inline=True)
    
    warns = profile.get('warns', 0)
    warn_emoji = "⚠️" if warns > 0 else "✅"
    embed.add_field(name=f"{warn_emoji} Warn-uri", value=f"**{warns}/3**", inline=True)
    
    hours = profile.get('played_hours', 0)
    embed.add_field(name="⏱️ Ore jucate", value=f"**{hours}** ore", inline=True)
    
    age = profile.get('age_ic', 'N/A')
    embed.add_field(name="🎂 Vârsta IC", value=f"**{age}** ani", inline=True)
    
    if profile.get('last_connection'):
        last_conn = profile['last_connection']
        if isinstance(last_conn, str):
            last_conn = datetime.fromisoformat(last_conn)
        embed.add_field(
            name="🕐 Ultima conectare",
            value=f"**{last_conn.strftime('%d.%m.%Y %H:%M:%S')}**",
            inline=False
        )
    
    if profile.get('last_checked'):
        last_check = profile['last_checked']
        if isinstance(last_check, str):
            last_check = datetime.fromisoformat(last_check)
        embed.set_footer(text=f"Ultima actualizare: {last_check.strftime('%d.%m.%Y %H:%M:%S')}")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="player_last_seen", description="Vezi ultima conectare a unui jucător")
async def player_last_seen(interaction: discord.Interaction, player_id: int):
    await interaction.response.defer()
    
    profile = db.get_player_last_connection(player_id)
    
    if not profile:
        profile_data = await scraper.get_player_profile(player_id)
        if not profile_data:
            await interaction.followup.send(f"❌ Nu am găsit jucătorul cu ID **{player_id}**.")
            return
        db.save_player_profile(profile_data)
        profile = profile_data
    
    embed = discord.Embed(
        title=f"👤 {profile['player_name']}",
        description=f"ID: **{profile['player_id']}**",
        color=discord.Color.green() if profile.get('is_online') else discord.Color.red()
    )
    
    if profile.get('is_online'):
        embed.add_field(name="Status", value="🟢 **Online acum**", inline=False)
    elif profile.get('last_connection'):
        last_conn = profile['last_connection']
        if isinstance(last_conn, str):
            last_conn = datetime.fromisoformat(last_conn)
        embed.add_field(
            name="Ultima conectare",
            value=f"**{last_conn.strftime('%d.%m.%Y %H:%M:%S')}**",
            inline=False
        )
    else:
        embed.add_field(name="Status", value="❓ Informație nedisponibilă", inline=False)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="find_player", description="Caută jucători după nume")
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
        last_conn = player.get('last_connection', 'Necunoscut')
        if last_conn and last_conn != 'Necunoscut':
            if isinstance(last_conn, str):
                last_conn = datetime.fromisoformat(last_conn)
            last_conn = last_conn.strftime('%d.%m %H:%M')
        
        embed.add_field(
            name=f"{player['player_name']} (ID: {player['player_id']})",
            value=f"{status} • Ultima: {last_conn}",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

# ============================================================================
# DISCORD COMMANDS - PLAYER ACTIONS
# ============================================================================

@bot.tree.command(name="player_actions", description="Vezi toate acțiunile unui jucător")
async def player_actions(interaction: discord.Interaction, player_name: str, days: int = 7):
    await interaction.response.defer()
    
    actions = db.get_player_actions(player_name, days)
    
    if not actions:
        await interaction.followup.send(f"❌ Nu am găsit acțiuni pentru **{player_name}** în ultimele {days} zile.")
        return
    
    embed = discord.Embed(
        title=f"📋 Acțiuni - {player_name}",
        description=f"Ultimele {days} zile • {len(actions)} acțiuni",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    for action in actions[:25]:
        timestamp = action['timestamp']
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        embed.add_field(
            name=timestamp.strftime('%d.%m.%Y %H:%M:%S'),
            value=action['text'][:1024],
            inline=False
        )
    
    if len(actions) > 25:
        embed.set_footer(text=f"Afișate primele 25 din {len(actions)} acțiuni")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="player_gave", description="Vezi ce a dat un jucător altora")
async def player_gave(interaction: discord.Interaction, player_name: str, days: int = 7):
    await interaction.response.defer()
    
    interactions = db.get_player_gave(player_name, days)
    
    if not interactions:
        await interaction.followup.send(f"❌ **{player_name}** nu a dat nimic în ultimele {days} zile.")
        return
    
    embed = discord.Embed(
        title=f"📤 Iteme Date de {player_name}",
        description=f"Ultimele {days} zile",
        color=discord.Color.green()
    )
    
    for item in interactions[:25]:
        timestamp = item['timestamp']
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        embed.add_field(
            name=f"→ {item['to_player']}",
            value=f"**{item['quantity']}x** {item['item']}\n{timestamp.strftime('%d.%m %H:%M')}",
            inline=True
        )
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="player_received", description="Vezi ce a primit un jucător")
async def player_received(interaction: discord.Interaction, player_name: str, days: int = 7):
    await interaction.response.defer()
    
    interactions = db.get_player_received(player_name, days)
    
    if not interactions:
        await interaction.followup.send(f"❌ **{player_name}** nu a primit nimic în ultimele {days} zile.")
        return
    
    embed = discord.Embed(
        title=f"📥 Iteme Primite de {player_name}",
        description=f"Ultimele {days} zile",
        color=discord.Color.orange()
    )
    
    for item in interactions[:25]:
        timestamp = item['timestamp']
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        embed.add_field(
            name=f"← {item['from_player']}",
            value=f"**{item['quantity']}x** {item['item']}\n{timestamp.strftime('%d.%m %H:%M')}",
            inline=True
        )
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="player_interactions", description="Vezi interacțiunile între doi jucători")
async def player_interactions(interaction: discord.Interaction, player1: str, player2: str, days: int = 7):
    await interaction.response.defer()
    
    interactions = db.get_interactions_between(player1, player2, days)
    
    if not interactions:
        await interaction.followup.send(f"❌ Nu am găsit interacțiuni între **{player1}** și **{player2}**.")
        return
    
    embed = discord.Embed(
        title=f"🔄 Interacțiuni",
        description=f"**{player1}** ↔ **{player2}**\nUltimele {days} zile",
        color=discord.Color.gold()
    )
    
    for item in interactions[:25]:
        timestamp = item['timestamp']
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        direction = f"**{item['from_player']}** → **{item['to_player']}**"
        embed.add_field(
            name=direction,
            value=f"**{item['quantity']}x** {item['item']}\n{timestamp.strftime('%d.%m %H:%M')}",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

# ============================================================================
# DISCORD COMMANDS - SESSIONS
# ============================================================================

@bot.tree.command(name="player_sessions", description="Vezi sesiunile de joc")
async def player_sessions(interaction: discord.Interaction, player_name: str, days: int = 7):
    await interaction.response.defer()
    
    sessions = db.get_player_sessions(player_name, days)
    
    if not sessions:
        await interaction.followup.send(f"❌ Nu am date despre sesiunile lui **{player_name}**.")
        return
    
    embed = discord.Embed(
        title=f"🎮 Sesiuni - {player_name}",
        description=f"Ultimele {days} zile",
        color=discord.Color.purple()
    )
    
    total_time = timedelta()
    for session in sessions[:25]:
        login_time = session['login_time']
        if isinstance(login_time, str):
            login_time = datetime.fromisoformat(login_time)
            
        duration = session.get('duration', '🟢 Online acum')
        if isinstance(duration, timedelta):
            total_time += duration
            duration_str = str(duration).split('.')[0]
        else:
            duration_str = duration
        
        embed.add_field(
            name=f"Login: {login_time.strftime('%d.%m.%Y %H:%M:%S')}",
            value=f"Durată: **{duration_str}**",
            inline=False
        )
    
    if total_time.total_seconds() > 0:
        embed.set_footer(text=f"⏱️ Timp total de joc: {str(total_time).split('.')[0]}")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="online_players", description="Vezi jucătorii online acum")
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
    
    player_list = "\n".join([f"• **{p['player_name']}** (ID: {p['player_id']})" for p in players[:50]])
    embed.add_field(name="Jucători", value=player_list or "Nimeni", inline=False)
    
    if len(players) > 50:
        embed.set_footer(text=f"Afișați primii 50 din {len(players)} jucători")
    
    await interaction.followup.send(embed=embed)

# ============================================================================
# DISCORD COMMANDS - FACTIONS & RANKS
# ============================================================================

@bot.tree.command(name="faction_members", description="Vezi membrii unei facțiuni")
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
    
    for member in members[:25]:
        status = "🟢" if member.get('is_online') else "🔴"
        warns = member.get('warns', 0)
        warn_text = f" ⚠️ {warns}" if warns > 0 else ""
        rank_text = f" • Rank: {member.get('faction_rank')}" if member.get('faction_rank') else ""
        
        embed.add_field(
            name=f"{status} {member['player_name']} (ID: {member['player_id']})",
            value=f"Job: **{member.get('job', 'N/A')}** • Ore: **{member.get('played_hours', 0)}**{rank_text}{warn_text}",
            inline=False
        )
    
    if len(members) > 25:
        embed.set_footer(text=f"Afișați primii 25 din {len(members)} membri")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="rank_history", description="Vezi istoricul rank-urilor")
async def rank_history(interaction: discord.Interaction, player_id: int):
    await interaction.response.defer()
    
    history = db.get_player_rank_history(player_id)
    
    if not history:
        await interaction.followup.send(f"❌ Nu am găsit istoric de rank-uri pentru ID **{player_id}**.")
        return
    
    player_name = history[0]['player_name']
    
    embed = discord.Embed(
        title=f"🎖️ Istoric Rank-uri - {player_name}",
        description=f"ID: **{player_id}**",
        color=discord.Color.gold()
    )
    
    for entry in history[:15]:
        rank_obtained = entry['rank_obtained']
        if isinstance(rank_obtained, str):
            rank_obtained = datetime.fromisoformat(rank_obtained)
        
        rank_lost = entry.get('rank_lost')
        if rank_lost:
            if isinstance(rank_lost, str):
                rank_lost = datetime.fromisoformat(rank_lost)
            duration = rank_lost - rank_obtained
            days = duration.days
            status = f"✓ Deținut {days} zile"
            date_range = f"{rank_obtained.strftime('%d.%m.%Y')} - {rank_lost.strftime('%d.%m.%Y')}"
        else:
            duration = datetime.now() - rank_obtained
            days = duration.days
            status = f"🟢 Curent ({days} zile)"
            date_range = f"Din {rank_obtained.strftime('%d.%m.%Y')}"
        
        embed.add_field(
            name=f"{entry['rank_name']} - {entry['faction']}",
            value=f"{status}\n*{date_range}*",
            inline=False
        )
    
    if len(history) > 15:
        embed.set_footer(text=f"Afișate primele 15 din {len(history)} rank-uri")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="faction_ranks", description="Vezi rank-urile dintr-o facțiune")
async def faction_ranks(interaction: discord.Interaction, faction_name: str):
    await interaction.response.defer()
    
    ranks = db.get_current_faction_ranks(faction_name)
    
    if not ranks:
        await interaction.followup.send(f"❌ Nu am găsit rank-uri în facțiunea **{faction_name}**.")
        return
    
    embed = discord.Embed(
        title=f"🎖️ Rank-uri {faction_name}",
        description=f"**{len(ranks)}** membri cu rank",
        color=discord.Color.blue()
    )
    
    from collections import defaultdict
    by_rank = defaultdict(list)
    for member in ranks:
        rank = member['faction_rank'] or 'Fără rank'
        by_rank[rank].append(member)
    
    for rank_name, members in sorted(by_rank.items(), reverse=True):
        member_list = []
        for member in members[:10]:
            status = "🟢" if member.get('is_online') else "🔴"
            days = int(member.get('days_in_rank', 0))
            member_list.append(f"{status} **{member['player_name']}** *(de {days}d)*")
        
        embed.add_field(
            name=f"📊 {rank_name}",
            value="\n".join(member_list) or "Nimeni",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="players_with_rank", description="Vezi jucătorii cu un anumit rank")
async def players_with_rank(interaction: discord.Interaction, rank_name: str):
    await interaction.response.defer()
    
    players = db.get_players_by_rank(rank_name)
    
    if not players:
        await interaction.followup.send(f"❌ Nu am găsit jucători cu rank-ul **{rank_name}**.")
        return
    
    embed = discord.Embed(
        title=f"🎖️ Rank: {rank_name}",
        description=f"**{len(players)}** jucători",
        color=discord.Color.purple()
    )
    
    for player in players[:25]:
        status = "🟢" if player.get('is_online') else "🔴"
        days = int(player.get('days_in_rank', 0))
        faction = player.get('faction', 'N/A')
        
        embed.add_field(
            name=f"{status} {player['player_name']} (ID: {player['player_id']})",
            value=f"**{faction}** • De **{days}** zile",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="recent_promotions", description="Vezi promovările recente")
async def recent_promotions(interaction: discord.Interaction, days: int = 7):
    await interaction.response.defer()
    
    promotions = db.get_recent_promotions(days)
    
    if not promotions:
        await interaction.followup.send(f"❌ Nu am găsit promovări în ultimele **{days}** zile.")
        return
    
    embed = discord.Embed(
        title=f"🎖️ Promovări Recente",
        description=f"Ultimele {days} zile • **{len(promotions)}** schimbări",
        color=discord.Color.green()
    )
    
    for promo in promotions[:25]:
        rank_obtained = promo['rank_obtained']
        if isinstance(rank_obtained, str):
            rank_obtained = datetime.fromisoformat(rank_obtained)
        
        time_ago = datetime.now() - rank_obtained
        if time_ago.days > 0:
            time_str = f"acum {time_ago.days} zile"
        elif time_ago.seconds // 3600 > 0:
            time_str = f"acum {time_ago.seconds // 3600} ore"
        else:
            time_str = f"acum {time_ago.seconds // 60} minute"
        
        status = "🟢 Curent" if promo.get('is_current') else "🔴 Pierdut"
        
        embed.add_field(
            name=f"{promo['player_name']} → {promo['rank_name']}",
            value=f"**{promo['faction']}** • {status}\n*{time_str}*",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="warned_players", description="Vezi jucătorii cu warn-uri")
async def warned_players(interaction: discord.Interaction, min_warns: int = 1):
    await interaction.response.defer()
    
    players = db.get_players_with_warns(min_warns)
    
    if not players:
        await interaction.followup.send(f"❌ Nu am găsit jucători cu minimum **{min_warns}** warn-uri.")
        return
    
    embed = discord.Embed(
        title=f"⚠️ Jucători cu Warn-uri",
        description=f"Minimum **{min_warns}** warn-uri • {len(players)} jucători",
        color=discord.Color.orange()
    )
    
    for player in players[:25]:
        status = "🟢" if player.get('is_online') else "🔴"
        warns = player.get('warns', 0)
        faction = player.get('faction', 'Civil')
        
        embed.add_field(
            name=f"{status} {player['player_name']} (ID: {player['player_id']})",
            value=f"⚠️ **{warns}/3** warns • {faction}",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

# ============================================================================
# DISCORD COMMANDS - SYSTEM
# ============================================================================

@bot.tree.command(name="scan_progress", description="Vezi progresul scanării inițiale")
async def scan_progress(interaction: discord.Interaction):
    await interaction.response.defer()
    
    progress = db.get_scan_progress()
    is_complete = db.is_initial_scan_complete()
    
    embed = discord.Embed(
        title="📊 Progres Scanare Profiluri",
        color=discord.Color.green() if is_complete else discord.Color.blue()
    )
    
    embed.add_field(
        name="Profiluri scanate",
        value=f"**{progress['total_scanned']:,}** / {progress['total_target']:,}",
        inline=False
    )
    
    embed.add_field(
        name="Progres",
        value=f"**{progress['percentage']:.2f}%**",
        inline=False
    )
    
    if is_complete:
        embed.add_field(
            name="Status",
            value="✅ **Scanare inițială completă**\nBotul monitorizează doar jucătorii activi acum.",
            inline=False
        )
    else:
        remaining = progress['total_target'] - progress['total_scanned']
        embed.add_field(
            name="Status",
            value=f"⏳ **Scanare în curs**\n{remaining:,} profiluri rămase",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="update_player_now", description="Actualizează profilul unui jucător")
async def update_player_now(interaction: discord.Interaction, player_id: int):
    await interaction.response.defer()
    
    profile = await scraper.get_player_profile(player_id)
    
    if not profile:
        await interaction.followup.send(f"❌ Nu am putut accesa profilul ID **{player_id}**.")
        return
    
    db.save_player_profile(profile)
    
    embed = discord.Embed(
        title=f"✅ Profil actualizat: {profile['player_name']}",
        description=f"ID: **{profile['player_id']}**",
        color=discord.Color.green()
    )
    
    embed.add_field(name="Facțiune", value=profile.get('faction', 'N/A'), inline=True)
    embed.add_field(name="Rank", value=profile.get('faction_rank', 'N/A'), inline=True)
    embed.add_field(name="Job", value=profile.get('job', 'N/A'), inline=True)
    embed.add_field(name="Warns", value=f"{profile.get('warns', 0)}/3", inline=True)
    embed.add_field(name="Ore jucate", value=str(profile.get('played_hours', 0)), inline=True)
    
    if profile.get('is_online'):
        embed.add_field(name="Status", value="🟢 **Online acum**", inline=False)
    elif profile.get('last_connection'):
        embed.add_field(
            name="Ultima conectare",
            value=f"**{profile['last_connection'].strftime('%d.%m.%Y %H:%M:%S')}**",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("❌ ERROR: DISCORD_TOKEN not found in environment variables!")
        exit(1)
    bot.run(TOKEN)

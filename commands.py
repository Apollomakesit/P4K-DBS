"""Discord Slash Commands for Pro4Kings Database Bot"""
import discord
from discord import app_commands
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

async def resolve_player_info(db, scraper, identifier):
    """Helper to get player info by ID or name"""
    import re
    
    # Try as direct ID first
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        player_id = str(identifier)
        profile = db.get_player_by_exact_id(player_id)
        
        if not profile:
            # Fetch from website
            profile_obj = await scraper.get_player_profile(player_id)
            if profile_obj:
                profile = {
                    'player_id': profile_obj.player_id,
                    'username': profile_obj.username,
                    'is_online': profile_obj.is_online,
                    'last_seen': profile_obj.last_seen,
                    'faction': profile_obj.faction,
                    'faction_rank': profile_obj.faction_rank,
                    'job': profile_obj.job,
                    'level': profile_obj.level,
                    'respect_points': profile_obj.respect_points,
                    'warnings': profile_obj.warnings,
                    'played_hours': profile_obj.played_hours,
                    'age_ic': profile_obj.age_ic,
                    'phone_number': profile_obj.phone_number
                }
                db.save_player_profile(profile)
        
        return profile
    
    # Try extracting ID from format "Name (123)"
    id_match = re.search(r'\((\d+)\)', str(identifier))
    if id_match:
        player_id = id_match.group(1)
        return await resolve_player_info(db, scraper, player_id)
    
    # Search by name
    players = db.search_player_by_name(identifier)
    return players[0] if players else None

def format_last_seen(last_seen_dt):
    """Format last seen time in human readable format"""
    if not last_seen_dt:
        return "Never"
    
    if isinstance(last_seen_dt, str):
        try:
            last_seen_dt = datetime.fromisoformat(last_seen_dt)
        except:
            return "Unknown"
    
    if not isinstance(last_seen_dt, datetime):
        return "Unknown"
    
    time_diff = datetime.now() - last_seen_dt
    seconds = int(time_diff.total_seconds())
    
    if seconds < 60:
        return "Just now"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    else:
        days = seconds // 86400
        if days == 1:
            return "Yesterday"
        elif days < 7:
            return f"{days}d ago"
        elif days < 30:
            weeks = days // 7
            return f"{weeks}w ago"
        else:
            months = days // 30
            return f"{months}mo ago"

def setup_commands(bot, db, scraper_getter):
    """Setup all slash commands for the bot
    
    Args:
        bot: Discord bot instance
        db: Database instance
        scraper_getter: Async function that returns scraper instance
    """
    
    # ========================================================================
    # PLAYER PROFILE COMMAND
    # ========================================================================
    
    @bot.tree.command(name="player", description="View detailed player profile")
    @app_commands.describe(identifier="Player ID or name")
    async def player_command(interaction: discord.Interaction, identifier: str):
        """View player profile"""
        await interaction.response.defer()
        
        try:
            scraper = await scraper_getter()
            player = await resolve_player_info(db, scraper, identifier)
            
            if not player:
                await interaction.followup.send(f"❌ **Player not found:** `{identifier}`")
                return
            
            # Create embed
            embed = discord.Embed(
                title=f"👤 {player['username']}",
                description=f"**ID:** {player['player_id']}",
                color=discord.Color.green() if player.get('is_online') else discord.Color.greyple(),
                timestamp=datetime.now()
            )
            
            # Status
            status = "🟢 Online" if player.get('is_online') else "⚫ Offline"
            if player.get('last_seen'):
                last_seen = player['last_seen']
                if isinstance(last_seen, str):
                    try:
                        last_seen = datetime.fromisoformat(last_seen)
                    except:
                        pass
                if isinstance(last_seen, datetime):
                    time_diff = datetime.now() - last_seen
                    if time_diff.total_seconds() < 300:
                        status = "🟢 Online"
                    else:
                        status = f"⚫ {format_last_seen(last_seen)}"
            
            embed.add_field(name="Status", value=status, inline=True)
            
            # Level & Respect
            if player.get('level'):
                embed.add_field(name="Level", value=f"🎖️ {player['level']}", inline=True)
            if player.get('respect_points'):
                embed.add_field(name="Respect", value=f"⭐ {player['respect_points']}", inline=True)
            
            # Faction
            if player.get('faction') and player['faction'] not in ['Civil', 'Fără', 'None', '-']:
                faction_text = player['faction']
                if player.get('faction_rank'):
                    faction_text += f" - {player['faction_rank']}"
                embed.add_field(name="Faction", value=f"🛡️ {faction_text}", inline=False)
            
            # Job
            if player.get('job'):
                embed.add_field(name="Job", value=f"💼 {player['job']}", inline=True)
            
            # Playtime
            if player.get('played_hours'):
                hours = player['played_hours']
                embed.add_field(name="Playtime", value=f"⏱️ {hours:.1f}h", inline=True)
            
            # Warnings
            if player.get('warnings') is not None:
                warns_emoji = "⚠️" if player['warnings'] > 0 else "✅"
                embed.add_field(name="Warnings", value=f"{warns_emoji} {player['warnings']}/3", inline=True)
            
            # Age IC
            if player.get('age_ic'):
                embed.add_field(name="Age IC", value=f"🎂 {player['age_ic']}", inline=True)
            
            # Phone
            if player.get('phone_number'):
                embed.add_field(name="Phone", value=f"📱 {player['phone_number']}", inline=True)
            
            embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in player command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ========================================================================
    # PLAYER ACTIONS COMMAND
    # ========================================================================
    
    @bot.tree.command(name="actions", description="View player recent actions")
    @app_commands.describe(
        player="Player ID or name",
        days="Number of days to look back (default: 7)"
    )
    async def actions_command(
        interaction: discord.Interaction, 
        player: str, 
        days: int = 7
    ):
        """View player actions"""
        await interaction.response.defer()
        
        try:
            scraper = await scraper_getter()
            player_info = await resolve_player_info(db, scraper, player)
            
            if not player_info:
                await interaction.followup.send(f"❌ **Player not found:** `{player}`")
                return
            
            player_id = player_info['player_id']
            player_name = player_info['username']
            
            actions = db.get_player_actions(player_id, days=days)
            
            if not actions:
                embed = discord.Embed(
                    title=f"📊 {player_name} - No Recent Actions",
                    description=f"No actions found in the last {days} days.",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Group actions by type
            action_types = {}
            for action in actions:
                atype = action['action_type']
                if atype not in action_types:
                    action_types[atype] = []
                action_types[atype].append(action)
            
            embed = discord.Embed(
                title=f"📊 {player_name} - Recent Actions",
                description=f"Found {len(actions)} actions in the last {days} days",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            # Add fields for each action type
            for atype, type_actions in sorted(action_types.items())[:10]:
                action_emoji = {
                    'warning_received': '⚠️',
                    'chest_deposit': '📦',
                    'chest_withdraw': '📤',
                    'item_given': '🎁',
                    'item_received': '💰',
                    'money_withdraw': '💵',
                    'vehicle_bought': '🚗',
                    'vehicle_sold': '🔑',
                    'property_bought': '🏠',
                    'property_sold': '🏘️'
                }.get(atype, '📌')
                
                # Show last 3 of this type
                recent = type_actions[:3]
                details = []
                for act in recent:
                    timestamp = act.get('timestamp', 'Unknown')
                    if isinstance(timestamp, str):
                        try:
                            timestamp = datetime.fromisoformat(timestamp)
                        except:
                            pass
                    if isinstance(timestamp, datetime):
                        time_str = timestamp.strftime('%m/%d %H:%M')
                    else:
                        time_str = 'Unknown'
                    
                    detail = act.get('action_detail', 'No details')[:50]
                    details.append(f"`{time_str}` {detail}")
                
                field_value = "\n".join(details)
                if len(type_actions) > 3:
                    field_value += f"\n*...and {len(type_actions) - 3} more*"
                
                embed.add_field(
                    name=f"{action_emoji} {atype.replace('_', ' ').title()} ({len(type_actions)})",
                    value=field_value,
                    inline=False
                )
            
            embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in actions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ========================================================================
    # ONLINE PLAYERS COMMAND
    # ========================================================================
    
    @bot.tree.command(name="online", description="View currently online players")
    async def online_command(interaction: discord.Interaction):
        """List online players"""
        await interaction.response.defer()
        
        try:
            online_players = db.get_current_online_players()
            
            if not online_players:
                embed = discord.Embed(
                    title="🟢 Online Players",
                    description="No players currently online.",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title=f"🟢 Online Players ({len(online_players)})",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            # Split into chunks of 25 (Discord field limit)
            chunks = [online_players[i:i + 25] for i in range(0, len(online_players), 25)]
            
            for i, chunk in enumerate(chunks[:3]):  # Max 3 chunks = 75 players
                player_list = "\n".join(
                    [f"`{p['player_id']:>6}` {p['player_name']}" for p in chunk]
                )
                embed.add_field(
                    name=f"Players {i*25+1}-{min((i+1)*25, len(online_players))}",
                    value=player_list,
                    inline=False
                )
            
            if len(online_players) > 75:
                embed.add_field(
                    name="...",
                    value=f"And {len(online_players) - 75} more players",
                    inline=False
                )
            
            embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in online command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ========================================================================
    # SEARCH COMMAND
    # ========================================================================
    
    @bot.tree.command(name="search", description="Search for players by name")
    @app_commands.describe(name="Player name to search for")
    async def search_command(interaction: discord.Interaction, name: str):
        """Search for players"""
        await interaction.response.defer()
        
        try:
            results = db.search_player_by_name(name)
            
            if not results:
                await interaction.followup.send(f"❌ **No players found matching:** `{name}`")
                return
            
            embed = discord.Embed(
                title=f"🔍 Search Results for '{name}'",
                description=f"Found {len(results)} player(s)",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            # Show up to 20 results
            for player in results[:20]:
                status = "🟢" if player.get('is_online') else "⚫"
                faction = player.get('faction', 'N/A')
                if faction in ['Civil', 'Fără', 'None', '-']:
                    faction = 'Civil'
                level = player.get('level', '?')
                
                player_info = f"{status} **ID:** {player['player_id']}\n🎖️ Level {level} | 🛡️ {faction}"
                
                embed.add_field(
                    name=player['username'],
                    value=player_info,
                    inline=True
                )
            
            if len(results) > 20:
                embed.add_field(
                    name="...",
                    value=f"And {len(results) - 20} more results. Try a more specific search.",
                    inline=False
                )
            
            embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in search command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ========================================================================
    # BANNED PLAYERS COMMAND
    # ========================================================================
    
    @bot.tree.command(name="banned", description="View list of banned players")
    async def banned_command(interaction: discord.Interaction):
        """View banned players"""
        await interaction.response.defer()
        
        try:
            banned = db.get_banned_players(include_expired=False)
            
            if not banned:
                embed = discord.Embed(
                    title="🚫 Banned Players",
                    description="No active bans.",
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title=f"🚫 Banned Players ({len(banned)})",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            
            # Show up to 20 bans
            for ban in banned[:20]:
                player_name = ban.get('player_name', 'Unknown')
                admin = ban.get('admin', 'Unknown')
                reason = ban.get('reason', 'No reason')[:100]
                duration = ban.get('duration', 'Unknown')
                ban_date = ban.get('ban_date', 'Unknown')
                
                ban_info = f"**Admin:** {admin}\n**Reason:** {reason}\n**Duration:** {duration}\n**Date:** {ban_date}"
                
                embed.add_field(
                    name=f"🚫 {player_name} (ID: {ban.get('player_id', '?')})",
                    value=ban_info,
                    inline=False
                )
            
            if len(banned) > 20:
                embed.add_field(
                    name="...",
                    value=f"And {len(banned) - 20} more active bans.",
                    inline=False
                )
            
            embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in banned command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ========================================================================
    # STATS COMMAND
    # ========================================================================
    
    @bot.tree.command(name="stats", description="View database statistics")
    async def stats_command(interaction: discord.Interaction):
        """View database stats"""
        await interaction.response.defer()
        
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get counts
                cursor.execute("SELECT COUNT(*) FROM players")
                player_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM actions")
                action_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM players WHERE is_online = TRUE")
                online_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM banned_players WHERE is_active = TRUE")
                banned_count = cursor.fetchone()[0]
                
                # Get recent activity
                cursor.execute("""
                    SELECT COUNT(*) FROM actions 
                    WHERE timestamp >= datetime('now', '-24 hours')
                """)
                actions_24h = cursor.fetchone()[0]
                
                # Top faction
                cursor.execute("""
                    SELECT faction, COUNT(*) as count 
                    FROM players 
                    WHERE faction IS NOT NULL AND faction NOT IN ('Civil', 'Fără', 'None', '-')
                    GROUP BY faction 
                    ORDER BY count DESC 
                    LIMIT 1
                """)
                top_faction_row = cursor.fetchone()
                top_faction = f"{top_faction_row[0]} ({top_faction_row[1]} members)" if top_faction_row else "N/A"
            
            embed = discord.Embed(
                title="📊 Database Statistics",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="👥 Players",
                value=f"**Total:** {player_count:,}\n**Online:** {online_count:,}\n**Banned:** {banned_count:,}",
                inline=True
            )
            
            embed.add_field(
                name="📊 Actions",
                value=f"**Total:** {action_count:,}\n**Last 24h:** {actions_24h:,}",
                inline=True
            )
            
            embed.add_field(
                name="🛡️ Top Faction",
                value=top_faction,
                inline=True
            )
            
            embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in stats command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ========================================================================
    # FACTIONS COMMAND - COMPREHENSIVE FACTION OVERVIEW
    # ========================================================================
    
    @bot.tree.command(name="factions", description="View factions, members, and activity rankings")
    @app_commands.describe(faction_name="Specific faction to view (optional)")
    async def factions_command(interaction: discord.Interaction, faction_name: str = None):
        """View comprehensive faction information with activity tracking"""
        await interaction.response.defer()
        
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # If specific faction requested
                if faction_name:
                    # Get faction members
                    cursor.execute("""
                        SELECT player_id, username, faction, faction_rank, is_online, last_seen, level, respect_points
                        FROM players
                        WHERE faction LIKE ? AND faction NOT IN ('Civil', 'Fără', 'None', '-')
                        ORDER BY 
                            CASE 
                                WHEN faction_rank LIKE '%Lider%' THEN 1
                                WHEN faction_rank LIKE '%Sublider%' THEN 2
                                WHEN faction_rank LIKE '%6%' THEN 3
                                WHEN faction_rank LIKE '%5%' THEN 4
                                WHEN faction_rank LIKE '%4%' THEN 5
                                WHEN faction_rank LIKE '%3%' THEN 6
                                WHEN faction_rank LIKE '%2%' THEN 7
                                WHEN faction_rank LIKE '%1%' THEN 8
                                ELSE 9
                            END,
                            is_online DESC,
                            level DESC
                    """, (f'%{faction_name}%',))
                    
                    members = cursor.fetchall()
                    
                    if not members:
                        await interaction.followup.send(f"❌ **Faction not found:** `{faction_name}`")
                        return
                    
                    # Get faction activity (last 7 days)
                    player_ids = [m['player_id'] for m in members]
                    placeholders = ','.join('?' * len(player_ids))
                    cursor.execute(f"""
                        SELECT COUNT(*) FROM actions
                        WHERE player_id IN ({placeholders})
                        AND timestamp >= datetime('now', '-7 days')
                    """, player_ids)
                    activity_count = cursor.fetchone()[0]
                    
                    # Get action breakdown by type
                    cursor.execute(f"""
                        SELECT action_type, COUNT(*) as count
                        FROM actions
                        WHERE player_id IN ({placeholders})
                        AND timestamp >= datetime('now', '-7 days')
                        GROUP BY action_type
                        ORDER BY count DESC
                        LIMIT 5
                    """, player_ids)
                    top_actions = cursor.fetchall()
                    
                    # Create detailed faction embed
                    faction_display_name = members[0]['faction']
                    online_members = [m for m in members if m['is_online']]
                    offline_members = [m for m in members if not m['is_online']]
                    
                    embed = discord.Embed(
                        title=f"🛡️ {faction_display_name}",
                        description=f"**Total Members:** {len(members)} | **Online:** {len(online_members)} | **Activity (7d):** {activity_count:,} actions",
                        color=discord.Color.gold(),
                        timestamp=datetime.now()
                    )
                    
                    # Online members
                    if online_members:
                        online_list = []
                        for member in online_members[:15]:  # Max 15 to avoid hitting limits
                            rank = member['faction_rank'] or 'No Rank'
                            level = member['level'] or '?'
                            online_list.append(f"🟢 `{member['player_id']:>6}` **{member['username']}**\n   ├─ {rank} | Lvl {level}")
                        
                        embed.add_field(
                            name=f"🟢 Online Members ({len(online_members)})",
                            value="\n".join(online_list) if online_list else "None",
                            inline=False
                        )
                    
                    # Offline members (show last 10)
                    if offline_members:
                        offline_list = []
                        for member in offline_members[:10]:
                            rank = member['faction_rank'] or 'No Rank'
                            level = member['level'] or '?'
                            last_seen = format_last_seen(member['last_seen'])
                            offline_list.append(f"⚫ `{member['player_id']:>6}` **{member['username']}**\n   ├─ {rank} | Lvl {level} | Last: {last_seen}")
                        
                        remaining = len(offline_members) - 10
                        if remaining > 0:
                            offline_list.append(f"\n*...and {remaining} more offline members*")
                        
                        embed.add_field(
                            name=f"⚫ Offline Members ({len(offline_members)})",
                            value="\n".join(offline_list) if offline_list else "None",
                            inline=False
                        )
                    
                    # Top action types
                    if top_actions:
                        action_list = []
                        for action in top_actions:
                            action_emoji = {
                                'warning_received': '⚠️',
                                'chest_deposit': '📦',
                                'chest_withdraw': '📤',
                                'item_given': '🎁',
                                'item_received': '💰'
                            }.get(action['action_type'], '📌')
                            action_list.append(f"{action_emoji} {action['action_type'].replace('_', ' ').title()}: {action['count']:,}")
                        
                        embed.add_field(
                            name="📊 Top Actions (7 days)",
                            value="\n".join(action_list),
                            inline=False
                        )
                    
                    embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
                    await interaction.followup.send(embed=embed)
                    return
                
                # Get all factions with statistics
                cursor.execute("""
                    SELECT 
                        faction,
                        COUNT(*) as total_members,
                        SUM(CASE WHEN is_online = 1 THEN 1 ELSE 0 END) as online_members,
                        AVG(level) as avg_level,
                        SUM(respect_points) as total_respect
                    FROM players
                    WHERE faction IS NOT NULL AND faction NOT IN ('Civil', 'Fără', 'None', '-')
                    GROUP BY faction
                    ORDER BY total_members DESC
                """)
                
                factions = cursor.fetchall()
                
                if not factions:
                    embed = discord.Embed(
                        title="🛡️ Server Factions",
                        description="No faction data available.",
                        color=discord.Color.orange()
                    )
                    await interaction.followup.send(embed=embed)
                    return
                
                # Calculate activity for all factions (last 7 days)
                faction_activity = {}
                for faction_row in factions:
                    faction_name_db = faction_row['faction']
                    cursor.execute("""
                        SELECT COUNT(*) FROM actions a
                        JOIN players p ON a.player_id = p.player_id
                        WHERE p.faction = ?
                        AND a.timestamp >= datetime('now', '-7 days')
                    """, (faction_name_db,))
                    faction_activity[faction_name_db] = cursor.fetchone()[0]
                
                # Create main factions overview embed
                embed = discord.Embed(
                    title="🛡️ Server Factions Overview",
                    description=f"Total factions: {len(factions)}\n\nUse `/factions <faction_name>` for detailed member roster and actions",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                
                # Top 10 factions by member count
                top_factions = factions[:10]
                
                faction_list = []
                for i, faction_row in enumerate(top_factions, 1):
                    fname = faction_row['faction']
                    total = faction_row['total_members']
                    online = faction_row['online_members']
                    avg_lvl = faction_row['avg_level'] or 0
                    activity = faction_activity.get(fname, 0)
                    
                    rank_emoji = {1: '🥇', 2: '🥈', 3: '🥉'}.get(i, f'{i}.')
                    
                    faction_list.append(
                        f"{rank_emoji} **{fname}**\n"
                        f"   👥 {total} members | 🟢 {online} online\n"
                        f"   🎖️ Avg Lvl {avg_lvl:.1f} | 📊 {activity:,} actions (7d)"
                    )
                
                embed.add_field(
                    name="🏆 Top Factions by Size",
                    value="\n\n".join(faction_list),
                    inline=False
                )
                
                # Most active factions (by total actions)
                active_factions = sorted(
                    [(fname, faction_activity[fname], next(f['total_members'] for f in factions if f['faction'] == fname)) 
                     for fname in faction_activity.keys()],
                    key=lambda x: x[1],
                    reverse=True
                )[:5]
                
                if active_factions:
                    activity_list = []
                    for i, (fname, actions, members) in enumerate(active_factions, 1):
                        activity_per_member = actions / members if members > 0 else 0
                        activity_list.append(
                            f"{i}. **{fname}** - {actions:,} actions ({activity_per_member:.1f} per member)"
                        )
                    
                    embed.add_field(
                        name="🔥 Most Active Factions (7 days)",
                        value="\n".join(activity_list),
                        inline=False
                    )
                
                # Calculate average online rate per faction
                online_rate_factions = []
                for faction_row in factions:
                    fname = faction_row['faction']
                    total = faction_row['total_members']
                    online = faction_row['online_members']
                    online_rate = (online / total * 100) if total > 0 else 0
                    if total >= 5:  # Only consider factions with 5+ members
                        online_rate_factions.append((fname, online_rate, online, total))
                
                # Sort by online rate
                online_rate_factions.sort(key=lambda x: x[1], reverse=True)
                
                if online_rate_factions[:5]:
                    online_rate_list = []
                    for i, (fname, rate, online, total) in enumerate(online_rate_factions[:5], 1):
                        online_rate_list.append(
                            f"{i}. **{fname}** - {rate:.1f}% ({online}/{total} online)"
                        )
                    
                    embed.add_field(
                        name="⚡ Highest Online Activity Rate",
                        value="\n".join(online_rate_list),
                        inline=False
                    )
                
                embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error in factions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    logger.info("✅ All slash commands registered (including /factions)")

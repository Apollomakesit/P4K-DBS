"""Discord commands for faction management and statistics"""
import discord
from discord import app_commands
from datetime import datetime, timedelta
import logging
from faction_queries import FactionQueries

logger = logging.getLogger(__name__)

def format_time_ago(last_seen):
    """Format last seen time into human readable string"""
    if not last_seen:
        return "Never"
    
    if isinstance(last_seen, str):
        try:
            last_seen = datetime.fromisoformat(last_seen)
        except:
            return "Unknown"
    
    if not isinstance(last_seen, datetime):
        return "Unknown"
    
    time_diff = datetime.now() - last_seen
    seconds = time_diff.total_seconds()
    
    if seconds < 300:  # 5 minutes
        return "🟢 Online"
    elif seconds < 3600:  # 1 hour
        return f"{int(seconds / 60)}m ago"
    elif seconds < 86400:  # 24 hours
        return f"{int(seconds / 3600)}h ago"
    elif seconds < 604800:  # 7 days
        return f"{int(seconds / 86400)}d ago"
    elif seconds < 2592000:  # 30 days
        return f"{int(seconds / 604800)}w ago"
    else:
        return f"{int(seconds / 2592000)}mo ago"

def setup_faction_commands(bot, db):
    """Setup faction-related commands
    
    Args:
        bot: Discord bot instance
        db: Database instance
    """
    
    faction_queries = FactionQueries(db)
    
    # ========================================================================
    # FACTION DETAIL COMMAND
    # ========================================================================
    
    @bot.tree.command(name="faction", description="View detailed faction information")
    @app_commands.describe(name="Faction name")
    async def faction_command(interaction: discord.Interaction, name: str):
        """View detailed faction info with members and ranks"""
        await interaction.response.defer()
        
        try:
            # Get all factions to find closest match
            all_factions = faction_queries.get_all_factions()
            
            # Find exact or partial match
            faction_name = None
            for faction in all_factions:
                if faction.lower() == name.lower():
                    faction_name = faction
                    break
                elif name.lower() in faction.lower():
                    faction_name = faction
                    break
            
            if not faction_name:
                available = ", ".join(all_factions[:10])
                await interaction.followup.send(
                    f"❌ **Faction not found:** `{name}`\n\n"
                    f"📝 **Available factions:** {available}"
                )
                return
            
            # Get faction members
            members = faction_queries.get_faction_members(faction_name)
            stats = faction_queries.get_faction_stats(faction_name, days=7)
            rank_dist = faction_queries.get_faction_rank_distribution(faction_name)
            
            # Create main embed
            embed = discord.Embed(
                title=f"🛡️ {faction_name}",
                description=f"**Total Members:** {stats['total_members']} | **Online:** {stats['online_count']} 🟢",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            # Stats field
            stats_text = (
                f"🎖️ **Avg Level:** {stats['avg_level']:.1f} (Max: {stats['max_level']})\n"
                f"⏱️ **Avg Playtime:** {stats['avg_playtime']:.1f}h\n"
                f"📊 **Activity Rate:** {stats['activity_rate']:.1f}%\n"
                f"📈 **Recent Actions:** {stats['recent_actions']} (7d)"
            )
            embed.add_field(name="📊 Statistics", value=stats_text, inline=False)
            
            # Rank distribution
            if rank_dist:
                rank_text = []
                for rank, data in sorted(rank_dist.items(), key=lambda x: (
                    {'Lider': 1, 'Sublider': 2, 'Rang 6': 3, 'Rang 5': 4, 
                     'Rang 4': 5, 'Rang 3': 6, 'Rang 2': 7, 'Rang 1': 8}.get(x[0], 9)
                )):
                    online_indicator = f" (🟢 {data['online']})"
                    rank_text.append(f"**{rank}:** {data['total']}{online_indicator}")
                
                embed.add_field(
                    name="🏆 Rank Distribution",
                    value="\n".join(rank_text[:8]) if rank_text else "No rank data",
                    inline=True
                )
            
            # Online members (up to 15)
            if members['online']:
                online_list = []
                for member in members['online'][:15]:
                    rank = member['faction_rank'] or '?'
                    level = member['level'] or '?'
                    online_list.append(f"🟢 **{member['username']}** - {rank} (Lv{level})")
                
                online_text = "\n".join(online_list)
                if len(members['online']) > 15:
                    online_text += f"\n*...and {len(members['online']) - 15} more online*"
                
                embed.add_field(
                    name=f"🟢 Online Members ({len(members['online'])})",
                    value=online_text,
                    inline=False
                )
            else:
                embed.add_field(
                    name="🟢 Online Members",
                    value="*No members currently online*",
                    inline=False
                )
            
            # Offline members (up to 10 most recent)
            if members['offline']:
                offline_list = []
                for member in members['offline'][:10]:
                    rank = member['faction_rank'] or '?'
                    level = member['level'] or '?'
                    last_seen = format_time_ago(member['last_seen'])
                    offline_list.append(f"⚫ **{member['username']}** - {rank} (Lv{level}) - {last_seen}")
                
                offline_text = "\n".join(offline_list)
                if len(members['offline']) > 10:
                    offline_text += f"\n*...and {len(members['offline']) - 10} more offline*"
                
                embed.add_field(
                    name=f"⚫ Recent Offline Members (Top 10)",
                    value=offline_text,
                    inline=False
                )
            
            embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in faction command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ========================================================================
    # LIST ALL FACTIONS COMMAND
    # ========================================================================
    
    @bot.tree.command(name="factions", description="List all factions with basic stats")
    async def factions_command(interaction: discord.Interaction):
        """List all factions on the server"""
        await interaction.response.defer()
        
        try:
            all_factions = faction_queries.get_all_factions()
            
            if not all_factions:
                await interaction.followup.send("❌ **No factions found in database**")
                return
            
            embed = discord.Embed(
                title=f"🛡️ All Factions ({len(all_factions)})",
                description="Click a faction name to view details with `/faction <name>`",
                color=discord.Color.gold(),
                timestamp=datetime.now()
            )
            
            # Get stats for each faction
            faction_data = []
            for faction in all_factions:
                stats = faction_queries.get_faction_stats(faction, days=7)
                faction_data.append({
                    'name': faction,
                    'total': stats['total_members'],
                    'online': stats['online_count'],
                    'actions': stats['recent_actions']
                })
            
            # Sort by total members
            faction_data.sort(key=lambda x: x['total'], reverse=True)
            
            # Create fields (max 3 columns of factions)
            chunk_size = (len(faction_data) + 2) // 3  # Divide into 3 columns
            chunks = [faction_data[i:i + chunk_size] for i in range(0, len(faction_data), chunk_size)]
            
            for i, chunk in enumerate(chunks):
                faction_list = []
                for data in chunk:
                    online_emoji = "🟢" if data['online'] > 0 else "⚫"
                    faction_list.append(
                        f"{online_emoji} **{data['name']}**\n"
                        f"   Members: {data['total']} | Online: {data['online']}\n"
                        f"   Actions (7d): {data['actions']}"
                    )
                
                embed.add_field(
                    name=f"Factions {i*chunk_size+1}-{min((i+1)*chunk_size, len(faction_data))}",
                    value="\n\n".join(faction_list),
                    inline=True
                )
            
            embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in factions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ========================================================================
    # FACTION ACTIVITY RANKING COMMAND
    # ========================================================================
    
    @bot.tree.command(name="factiontop", description="Top most active factions ranked by activity")
    @app_commands.describe(days="Days to analyze (default: 7)")
    async def factiontop_command(interaction: discord.Interaction, days: int = 7):
        """Rank factions by activity"""
        await interaction.response.defer()
        
        try:
            if days < 1 or days > 30:
                await interaction.followup.send("❌ **Days must be between 1 and 30**")
                return
            
            rankings = faction_queries.get_faction_activity_ranking(days=days, limit=15)
            
            if not rankings:
                await interaction.followup.send("❌ **No faction activity data found**")
                return
            
            embed = discord.Embed(
                title=f"🏆 Top Active Factions (Last {days} days)",
                description=(
                    "**Activity Score** = Actions + (Active Members × 10) + (Online × 5)\n"
                    "Higher score = more active faction"
                ),
                color=discord.Color.gold(),
                timestamp=datetime.now()
            )
            
            # Medal emojis for top 3
            medals = {
                0: "🥇",  # 1st place
                1: "🥈",  # 2nd place
                2: "🥉"   # 3rd place
            }
            
            # Create ranking list
            for i, faction in enumerate(rankings):
                medal = medals.get(i, f"{i+1}.") if i < 3 else f"**{i+1}.**"
                
                # Calculate activity bar
                max_score = rankings[0]['activity_score']
                bar_length = int((faction['activity_score'] / max_score) * 10)
                activity_bar = "█" * bar_length + "░" * (10 - bar_length)
                
                field_value = (
                    f"{activity_bar}\n"
                    f"👥 **Members:** {faction['total_members']} | "
                    f"🟢 **Online:** {faction['online_now']} | "
                    f"✨ **Active:** {faction['active_members']}\n"
                    f"📊 **Actions:** {faction['total_actions']} | "
                    f"🎖️ **Avg Level:** {faction['avg_level']:.1f}\n"
                    f"📈 **Activity Rate:** {faction['activity_rate']:.1f}% | "
                    f"🎯 **Score:** {faction['activity_score']:.0f}"
                )
                
                embed.add_field(
                    name=f"{medal} {faction['faction']}",
                    value=field_value,
                    inline=False
                )
            
            # Add summary statistics
            total_members = sum(f['total_members'] for f in rankings)
            total_actions = sum(f['total_actions'] for f in rankings)
            
            embed.add_field(
                name="📊 Overall Statistics",
                value=(
                    f"**Total Members (Top 15):** {total_members}\n"
                    f"**Total Actions:** {total_actions}\n"
                    f"**Avg Actions/Faction:** {total_actions / len(rankings):.0f}"
                ),
                inline=False
            )
            
            embed.set_footer(text=f"Pro4Kings Database • Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in factiontop command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ========================================================================
    # FACTION ACTIONS COMMAND
    # ========================================================================
    
    @bot.tree.command(name="factionactions", description="View recent actions by faction members")
    @app_commands.describe(
        faction="Faction name",
        days="Days to look back (default: 7)"
    )
    async def factionactions_command(
        interaction: discord.Interaction, 
        faction: str, 
        days: int = 7
    ):
        """View faction member actions"""
        await interaction.response.defer()
        
        try:
            # Find faction
            all_factions = faction_queries.get_all_factions()
            faction_name = None
            
            for f in all_factions:
                if f.lower() == faction.lower() or faction.lower() in f.lower():
                    faction_name = f
                    break
            
            if not faction_name:
                await interaction.followup.send(f"❌ **Faction not found:** `{faction}`")
                return
            
            actions = faction_queries.get_faction_recent_actions(faction_name, days=days, limit=30)
            
            if not actions:
                embed = discord.Embed(
                    title=f"📊 {faction_name} - No Recent Actions",
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
                title=f"📊 {faction_name} - Recent Actions",
                description=f"Found {len(actions)} actions in the last {days} days",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            # Add fields for each action type (max 10 types)
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
                }.get(atype, '📌')
                
                # Show last 3 of this type
                recent = type_actions[:3]
                details = []
                for act in recent:
                    player = act['player_name']
                    rank = act.get('faction_rank', '?')
                    timestamp = act.get('timestamp', 'Unknown')
                    if isinstance(timestamp, str):
                        try:
                            timestamp = datetime.fromisoformat(timestamp).strftime('%m/%d %H:%M')
                        except:
                            timestamp = 'Unknown'
                    
                    detail = act.get('action_detail', '')[:40]
                    details.append(f"`{timestamp}` **{player}** ({rank}): {detail}")
                
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
            logger.error(f"Error in factionactions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    logger.info("✅ Faction commands registered")

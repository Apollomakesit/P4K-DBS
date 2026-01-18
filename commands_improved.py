"""Example improved commands using safety utilities"""
import discord
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional
import logging

from discord_utils import (
    cooldown,
    require_admin,
    create_paginated_embeds,
    send_paginated,
    UserFriendlyError,
    safe_defer,
    QueryLimits
)

logger = logging.getLogger(__name__)

# ============================================================================
# EXAMPLE: PLAYER ACTIONS COMMAND (WITH PAGINATION)
# ============================================================================

@cooldown(seconds=30)
async def player_actions_safe(interaction: discord.Interaction, identifier: str, days: int = 7):
    """
    Get player actions with pagination and safety features
    
    Args:
        interaction: Discord interaction
        identifier: Player ID or name
        days: Number of days to look back (max 30)
    """
    await safe_defer(interaction)
    
    try:
        # Validate input
        days = min(days, 30)  # Cap at 30 days
        
        # Get actions with limit
        from database import Database
        db = Database()
        
        # Apply query limit
        actions = db.get_player_actions(identifier, days=days)
        
        if not actions:
            embed = discord.Embed(
                title="🔍 Player Actions",
                description=f"No actions found for **{identifier}** in the last {days} days.",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed)
            return
        
        # Limit results
        if len(actions) > QueryLimits.MAX_ACTIONS:
            actions = actions[:QueryLimits.MAX_ACTIONS]
            truncated = True
        else:
            truncated = False
        
        # Format actions
        def format_action(action):
            timestamp = action['timestamp']
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)
            
            time_str = timestamp.strftime('%Y-%m-%d %H:%M')
            
            return (
                f"**{action['action_type']}** - {time_str}\n"
                f"├ Player: {action['player_name']} ({action['player_id']})\n"
                f"└ Detail: {action['action_detail'] or 'N/A'}"
            )
        
        # Create paginated embeds
        title = f"Actions for {identifier} ({days} days)"
        if truncated:
            title += f" [Limited to {QueryLimits.MAX_ACTIONS} results]"
        
        embeds = create_paginated_embeds(
            items=actions,
            items_per_page=QueryLimits.ACTIONS_PER_PAGE,
            title=title,
            formatter=format_action,
            color=discord.Color.blue()
        )
        
        await send_paginated(interaction, embeds)
        
    except Exception as e:
        logger.error(f"Error in player_actions: {e}", exc_info=True)
        error_msg = UserFriendlyError.format(e)
        await interaction.followup.send(error_msg, ephemeral=True)

# ============================================================================
# EXAMPLE: ADMIN CLEANUP COMMAND (WITH PROPER CHECKS)
# ============================================================================

@require_admin()
@cooldown(seconds=300, admin_bypass=False)  # 5 min cooldown even for admins
async def cleanup_old_data_safe(
    interaction: discord.Interaction,
    dry_run: bool = True,
    confirm: bool = False
):
    """
    Clean up old data with safety checks
    
    Args:
        interaction: Discord interaction
        dry_run: If True, only show what would be deleted
        confirm: Must be True to actually delete (safety)
    """
    await safe_defer(interaction)
    
    try:
        from database import Database
        from config import Config
        
        db = Database()
        
        # Safety check: require confirmation for actual deletion
        if not dry_run and not confirm:
            embed = discord.Embed(
                title="⚠️ Confirmation Required",
                description=(
                    "You are about to permanently delete old data.\n\n"
                    "To proceed, run the command again with:\n"
                    "`dry_run=False` and `confirm=True`"
                ),
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Perform cleanup
        stats = db.cleanup_old_data(
            actions_days=Config.ACTIONS_RETENTION_DAYS,
            login_events_days=Config.LOGIN_EVENTS_RETENTION_DAYS,
            profile_history_days=Config.PROFILE_HISTORY_RETENTION_DAYS,
            dry_run=dry_run
        )
        
        mode = "🔍 DRY RUN" if dry_run else "🗑️ CLEANUP EXECUTED"
        color = discord.Color.orange() if dry_run else discord.Color.green()
        
        embed = discord.Embed(
            title=f"{mode} - Data Cleanup",
            color=color,
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="Actions",
            value=f"{('Would delete' if dry_run else 'Deleted')}: **{stats['actions_deleted']:,}**\nRetention: {Config.ACTIONS_RETENTION_DAYS} days",
            inline=True
        )
        
        embed.add_field(
            name="Login Events",
            value=f"{('Would delete' if dry_run else 'Deleted')}: **{stats['login_events_deleted']:,}**\nRetention: {Config.LOGIN_EVENTS_RETENTION_DAYS} days",
            inline=True
        )
        
        embed.add_field(
            name="Profile History",
            value=f"{('Would delete' if dry_run else 'Deleted')}: **{stats['profile_history_deleted']:,}**\nRetention: {Config.PROFILE_HISTORY_RETENTION_DAYS} days",
            inline=True
        )
        
        if dry_run:
            embed.set_footer(text="Run with dry_run=False and confirm=True to actually delete data")
        else:
            embed.set_footer(text="✅ Cleanup completed successfully")
        
        await interaction.followup.send(embed=embed)
        
        # Log admin action
        logger.info(
            f"Cleanup {'simulated' if dry_run else 'executed'} by "
            f"{interaction.user.name} ({interaction.user.id}): "
            f"{stats['actions_deleted']} actions, {stats['login_events_deleted']} login events, "
            f"{stats['profile_history_deleted']} profile history"
        )
        
    except Exception as e:
        logger.error(f"Error in cleanup_old_data: {e}", exc_info=True)
        error_msg = UserFriendlyError.format(e)
        await interaction.followup.send(error_msg, ephemeral=True)

# ============================================================================
# EXAMPLE: SEARCH PLAYERS COMMAND (WITH LIMITS)
# ============================================================================

@cooldown(seconds=10)
async def search_players_safe(interaction: discord.Interaction, query: str):
    """
    Search players by name with result limiting
    
    Args:
        interaction: Discord interaction
        query: Search query
    """
    await safe_defer(interaction)
    
    try:
        # Validate query length
        if len(query) < 2:
            await interaction.followup.send(
                "⚠️ Search query must be at least 2 characters long.",
                ephemeral=True
            )
            return
        
        from database import Database
        db = Database()
        
        # Search with limit
        players = db.search_player_by_name(query)
        
        if not players:
            embed = discord.Embed(
                title="🔍 Player Search",
                description=f"No players found matching **{query}**",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed)
            return
        
        # Format players
        def format_player(player):
            online_status = "🟢 Online" if player.get('is_online') else "⚪ Offline"
            faction = player.get('faction') or 'No faction'
            level = player.get('level') or 'N/A'
            
            return (
                f"**{player['username']}** (ID: {player['player_id']})\n"
                f"├ Status: {online_status}\n"
                f"├ Faction: {faction}\n"
                f"└ Level: {level}"
            )
        
        embeds = create_paginated_embeds(
            items=players,
            items_per_page=QueryLimits.PLAYERS_PER_PAGE,
            title=f"Players matching '{query}'",
            formatter=format_player,
            color=discord.Color.blue()
        )
        
        await send_paginated(interaction, embeds)
        
    except Exception as e:
        logger.error(f"Error in search_players: {e}", exc_info=True)
        error_msg = UserFriendlyError.format(e)
        await interaction.followup.send(error_msg, ephemeral=True)

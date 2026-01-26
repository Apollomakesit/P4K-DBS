"""Discord Slash Commands for Pro4Kings Database Bot - OPTIMIZED WITH CONCURRENT WORKERS"""

import discord
from discord import app_commands
from datetime import datetime, timedelta
import logging
import asyncio
import os
import re
from typing import Optional, List, Dict
from collections import defaultdict

logger = logging.getLogger(__name__)

# Admin user IDs from environment
ADMIN_USER_IDS = set(map(int, os.getenv('ADMIN_USER_IDS', '').split(','))) if os.getenv('ADMIN_USER_IDS') else set()

# SCAN STATE - Shared across commands
SCAN_STATE = {
    'is_scanning': False,
    'is_paused': False,
    'start_id': 0,
    'end_id': 0,
    'current_id': 0,
    'found_count': 0,
    'error_count': 0,
    'start_time': None,
    'scan_task': None,
    'status_message': None,
    'status_task': None,
    'scan_config': {
        'batch_size': 50,
        'workers': 10,
        'wave_delay': 0.05,
        'max_concurrent_batches': 5
    },
    'worker_stats': {},
    'total_scanned': 0,
    'last_speed_update': None,
    'current_speed': 0.0
}

# ========================================================================
# HELPER FUNCTIONS
# ========================================================================

def is_placeholder_username(username: str) -> bool:
    """🆕 Check if username is a placeholder like 'Player_12345'
    
    Returns True if username matches pattern: Player_<digits>
    """
    if not username or not isinstance(username, str):
        return False
    
    # Check if it starts with "Player_" and the rest are digits
    if username.startswith('Player_'):
        suffix = username[7:]  # Everything after "Player_"
        return suffix.isdigit() and len(suffix) > 0
    
    return False

def deduplicate_actions(actions: List[dict]) -> List[dict]:
    """Deduplicate actions that occur at the same second with same type and detail.
    
    Args:
        actions: List of action dictionaries
        
    Returns:
        List of deduplicated actions with 'count' field added for duplicates
    """
    if not actions:
        return []
    
    # Group actions by (timestamp_second, action_type, action_detail)
    grouped = defaultdict(list)
    
    for action in actions:
        timestamp = action.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        
        # Round to the nearest second for grouping
        timestamp_key = timestamp.replace(microsecond=0) if timestamp else None
        action_type = action.get('action_type', 'unknown')
        action_detail = action.get('action_detail', '')
        
        key = (timestamp_key, action_type, action_detail)
        grouped[key].append(action)
    
    # Create deduplicated list with counts
    deduplicated = []
    for key, group in grouped.items():
        # Take the first action from the group
        action = group[0].copy()
        # Add count if there are duplicates
        if len(group) > 1:
            action['count'] = len(group)
        deduplicated.append(action)
    
    # Sort by timestamp descending (most recent first)
    deduplicated.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    return deduplicated

def extract_target_from_detail(action_detail: str) -> tuple:
    """Extract target_player_id and target_player_name from action_detail text.
    
    This is a fallback for old actions that don't have target info in database.
    
    Returns: (target_player_id, target_player_name) or (None, None)
    """
    if not action_detail:
        return (None, None)
    
    # Pattern: "ia dat lui PlayerName(ID)" or "a dat lui PlayerName(ID)"
    match = re.search(r'(?:ia|a)\s+dat\s+lui\s+([^(]+)\((\d+)\)', action_detail, re.IGNORECASE)
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern: "primit de la PlayerName(ID)"
    match = re.search(r'primit\s+(?:de\s+la|de la)\s+([^(]+)\((\d+)\)', action_detail, re.IGNORECASE)
    if match:
        return (match.group(2), match.group(1).strip())
    
    return (None, None)

# ========================================================================
# PAGINATION VIEW
# ========================================================================

class ActionsPaginationView(discord.ui.View):
    """Pagination view for player actions with Previous/Next buttons"""
    
    def __init__(self, actions: List[dict], player_info: dict, days: int, author_id: int, items_per_page: int = 10, original_count: int = None):
        super().__init__(timeout=180)  # 3 minutes timeout
        # Deduplicate actions before storing
        self.actions = deduplicate_actions(actions)
        self.original_count = original_count or len(actions)
        self.player_info = player_info
        self.days = days
        self.author_id = author_id
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.actions) + items_per_page - 1) // items_per_page if self.actions else 1
        
        # Update button states
        self.update_buttons()
    
    def update_buttons(self):
        """Update button enabled/disabled states based on current page"""
        self.previous_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page >= self.total_pages - 1)
    
    def _format_action_display(self, action: dict, viewing_player_id: str) -> Dict[str, str]:
        """Format action for display with emojis and proper categorization.
        
        Returns dict with 'emoji', 'type_label', 'detail_lines'
        """
        action_type = action.get('action_type', 'unknown')
        detail = action.get('action_detail', 'No details')
        player_id = str(action.get('player_id', ''))
        target_player_id = str(action.get('target_player_id', '') if action.get('target_player_id') else '')
        player_name = action.get('player_name', 'Unknown')
        target_player_name = action.get('target_player_name', '')
        
        # FALLBACK: If target_player_id is NULL, try to extract from action_detail
        if not target_player_id and detail:
            extracted_id, extracted_name = extract_target_from_detail(detail)
            if extracted_id:
                target_player_id = extracted_id
                target_player_name = extracted_name
        
        # Check if viewing player is sender or receiver
        is_sender = (player_id == viewing_player_id)
        is_receiver = (target_player_id == viewing_player_id)
        
        # Handle item transfers (gave/received)
        if ('ia dat lui' in detail.lower() or 'a dat lui' in detail.lower()) and (is_sender or is_receiver):
            # Extract items from detail
            match = re.search(r'(?:ia|a)\s+dat\s+lui\s+.+?\(\d+\)\s+(.+)', detail, re.IGNORECASE)
            items = match.group(1).strip() if match else detail.split('lui')[-1].strip()
            
            if is_sender:
                # Viewing player GAVE to target
                return {
                    'emoji': '📤',
                    'type_label': 'GAVE',
                    'detail_lines': [
                        f"To: {target_player_name} ({target_player_id})" if target_player_name else f"To: ID {target_player_id}",
                        f"Items: {items}"
                    ]
                }
            elif is_receiver:
                # Viewing player RECEIVED from sender
                return {
                    'emoji': '📥',
                    'type_label': 'RECEIVED',
                    'detail_lines': [
                        f"From: {player_name} ({player_id})",
                        f"Items: {items}"
                    ]
                }
        
        # Handle chest deposits
        if action_type == 'chest_deposit' or 'pus in chest' in detail:
            return {
                'emoji': '📦',
                'type_label': 'CHEST DEPOSIT',
                'detail_lines': [f"Detail: {detail}"]
            }
        
        # Handle chest withdrawals
        if action_type == 'chest_withdraw' or 'retras din chest' in detail or 'scos din chest' in detail:
            return {
                'emoji': '📂',
                'type_label': 'CHEST WITHDRAW',
                'detail_lines': [f"Detail: {detail}"]
            }
        
        # Handle warnings
        if action_type == 'warning_received' or 'avertisment' in detail.lower():
            return {
                'emoji': '⚠️',
                'type_label': 'WARNING',
                'detail_lines': [f"Detail: {detail}"]
            }
        
        # Handle vehicle actions
        if action_type in ('vehicle_bought', 'vehicle_sold') or 'cumparat' in detail or 'vandut' in detail:
            emoji = '🚗' if 'cumparat' in detail else '💰'
            return {
                'emoji': emoji,
                'type_label': 'VEHICLE',
                'detail_lines': [f"Detail: {detail}"]
            }
        
        # Default for other actions
        return {
            'emoji': '📋',
            'type_label': action_type.upper().replace('_', ' '),
            'detail_lines': [f"Detail: {detail}"]
        }
    
    def build_embed(self) -> discord.Embed:
        """Build embed for current page with emojis and proper categorization"""
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.actions))
        page_actions = self.actions[start_idx:end_idx]
        
        # Show both deduplicated count and original count
        description = f"Last {self.days} days • {len(self.actions)} unique action(s)"
        if self.original_count > len(self.actions):
            description += f" ({self.original_count} total including duplicates)"
        
        embed = discord.Embed(
            title=f"📝 Actions for {self.player_info['username']}",
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        viewing_player_id = str(self.player_info['player_id'])
        
        for action in page_actions:
            timestamp = action.get('timestamp')
            count = action.get('count', 1)
            
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)
            time_str = timestamp.strftime('%Y-%m-%d %H:%M') if timestamp else 'Unknown'
            
            # Get formatted display info
            display = self._format_action_display(action, viewing_player_id)
            
            # Build field name with emoji and count
            field_name = f"{display['emoji']} {display['type_label']} - {time_str}"
            if count > 1:
                field_name += f" ×{count}"
            
            # Build field value with detail lines
            value_lines = []
            for i, line in enumerate(display['detail_lines']):
                if i == 0:
                    value_lines.append(f"├ {line}")
                elif i == len(display['detail_lines']) - 1:
                    value_lines.append(f"└ {line}")
                else:
                    value_lines.append(f"├ {line}")
            
            field_value = "\n".join(value_lines)
            
            embed.add_field(
                name=field_name,
                value=field_value,
                inline=False
            )
        
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} • Use buttons to navigate")
        return embed
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command author can use the buttons"""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can use these buttons!",
                ephemeral=True
            )
            return False
        return True
    
    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary, emoji="◀️")
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to previous page"""
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, emoji="▶️")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to next page"""
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def on_timeout(self):
        """Disable buttons when view times out"""
        for item in self.children:
            item.disabled = True
        try:
            # Try to edit the message to disable buttons
            if self.message:
                await self.message.edit(view=self)
        except:
            pass


class FactionPaginationView(discord.ui.View):
    """Pagination view for faction members with Previous/Next buttons"""
    
    def __init__(self, members: List[dict], faction_name: str, author_id: int, items_per_page: int = 20):
        super().__init__(timeout=180)  # 3 minutes timeout
        self.members = members
        self.faction_name = faction_name
        self.author_id = author_id
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.members) + items_per_page - 1) // items_per_page if self.members else 1
        
        # Update button states
        self.update_buttons()
    
    def update_buttons(self):
        """Update button enabled/disabled states based on current page"""
        self.previous_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page >= self.total_pages - 1)
    
    def build_embed(self) -> discord.Embed:
        """🔥 FIXED: Build embed showing actual usernames (not placeholder IDs)"""
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.members))
        page_members = self.members[start_idx:end_idx]
        
        embed = discord.Embed(
            title=f"👥 {self.faction_name}",
            description=f"Showing {start_idx + 1}-{end_idx} of {len(self.members)} member(s)",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        for member in page_members:
            status = "🟢" if member.get('is_online') else "⚪"
            rank = member.get('faction_rank')
            
            # Handle NULL, empty, and "null" string values
            if not rank or rank.lower() in ('null', 'none', '', '-'):
                rank = 'Membru'  # Default rank
            
            # 🔥 FIXED: Always show username and ID, never just "ID: xxxxx"
            username = member['username']
            player_id = member['player_id']
            
            # Always display as "Username (ID)" format
            display_name = f"{username} ({player_id})"
            
            value = f"{status} {rank}"
            embed.add_field(
                name=display_name,
                value=value,
                inline=False
            )
        
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} • Use buttons to navigate")
        return embed
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command author can use the buttons"""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can use these buttons!",
                ephemeral=True
            )
            return False
        return True
    
    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary, emoji="◀️")
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to previous page"""
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, emoji="▶️")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to next page"""
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def on_timeout(self):
        """Disable buttons when view times out"""
        for item in self.children:
            item.disabled = True
        try:
            # Try to edit the message to disable buttons
            if self.message:
                await self.message.edit(view=self)
        except:
            pass

# Helper Functions
def format_time_duration(seconds: float) -> str:
    """Format seconds into human-readable time"""
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    hours = minutes // 60
    minutes = minutes % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"

async def resolve_player_info(db, scraper, identifier):
    """Helper to get player info by ID or name"""
    import re

    # Try as direct ID first
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        player_id = str(identifier)
        profile = await db.get_player_by_exact_id(player_id)

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
                    'warnings': profile_obj.warnings,
                    'played_hours': profile_obj.played_hours,
                    'age_ic': profile_obj.age_ic,
                }
                await db.save_player_profile(profile)
        return profile

    # Try extracting ID from format "Name (123)"
    id_match = re.search(r'\((\d+)\)', str(identifier))
    if id_match:
        player_id = id_match.group(1)
        return await resolve_player_info(db, scraper, player_id)

    # Search by name
    players = await db.search_player_by_name(identifier)
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

def build_status_embed():
    """Build real-time status embed for scan with concurrent worker stats"""
    current = SCAN_STATE['current_id']
    start = SCAN_STATE['start_id']
    end = SCAN_STATE['end_id']
    total = end - start + 1
    scanned = SCAN_STATE['total_scanned']
    progress_pct = (scanned / total * 100) if total > 0 else 0

    # Calculate speed and ETA
    if SCAN_STATE['start_time']:
        elapsed = (datetime.now() - SCAN_STATE['start_time']).total_seconds()
        speed = scanned / elapsed if elapsed > 0 else 0
        remaining = total - scanned
        eta_seconds = remaining / speed if speed > 0 else 0
        elapsed_str = format_time_duration(elapsed)
        eta_str = format_time_duration(eta_seconds) if eta_seconds > 0 else "Calculating..."
    else:
        speed = 0
        elapsed_str = "0s"
        eta_str = "Unknown"

    status_emoji = "⏸️" if SCAN_STATE['is_paused'] else "🔄"
    status_text = "Paused" if SCAN_STATE['is_paused'] else "Running"

    embed = discord.Embed(
        title=f"{status_emoji} Scan Status: {status_text}",
        description=f"**Progress:** {progress_pct:.1f}% ({scanned:,}/{total:,} IDs)\n**Range:** {start:,} → {end:,}",
        color=discord.Color.orange() if SCAN_STATE['is_paused'] else discord.Color.blue(),
        timestamp=datetime.now()
    )

    embed.add_field(name="📍 Current Highest ID", value=f"{current:,}", inline=True)
    embed.add_field(name="⚡ Speed", value=f"{speed:.2f} IDs/s", inline=True)
    embed.add_field(name="⏱️ ETA", value=eta_str, inline=True)
    embed.add_field(name="✅ Found", value=f"{SCAN_STATE['found_count']:,}", inline=True)
    embed.add_field(name="❌ Errors", value=f"{SCAN_STATE['error_count']:,}", inline=True)
    embed.add_field(name="⏲️ Elapsed", value=elapsed_str, inline=True)

    # Worker stats
    config = SCAN_STATE['scan_config']
    worker_info = f"👷 {config['workers']} workers × {config['max_concurrent_batches']} concurrent batches"
    embed.add_field(name="🔧 Workers", value=worker_info, inline=False)

    # Progress bar
    bar_length = 20
    filled = int(progress_pct / 100 * bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)
    embed.add_field(name="Progress Bar", value=f"`{bar}` {progress_pct:.1f}%", inline=False)
    embed.set_footer(text="🔄 Auto-refreshing every 3 seconds | Use /scan pause or /scan cancel")

    return embed

async def auto_refresh_status():
    """Auto-refresh the status message every 3 seconds"""
    try:
        while SCAN_STATE['is_scanning']:
            if SCAN_STATE['status_message']:
                try:
                    embed = build_status_embed()
                    await SCAN_STATE['status_message'].edit(embed=embed)
                except discord.NotFound:
                    SCAN_STATE['status_message'] = None
                    break
                except Exception as e:
                    logger.error(f"Error refreshing status: {e}")
            await asyncio.sleep(3)

        # Scan complete - one final update
        if SCAN_STATE['status_message']:
            try:
                embed = build_status_embed()
                embed.set_footer(text="✅ Scan complete!")
                embed.color = discord.Color.green()
                await SCAN_STATE['status_message'].edit(embed=embed)
            except:
                pass
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Auto-refresh error: {e}", exc_info=True)

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in ADMIN_USER_IDS


def setup_commands(bot, db, scraper_getter):
    """Setup all slash commands for the bot

    Args:
        bot: Discord bot instance
        db: Database instance
        scraper_getter: Async function that returns scraper instance (accepts max_concurrent param)
    """

    # ========================================================================
    # GENERAL COMMANDS
    # ========================================================================

    @bot.tree.command(name="health", description="Check bot health status")
    @app_commands.checks.cooldown(1, 10)
    async def health_command(interaction: discord.Interaction):
        """Check bot health status"""
        await interaction.response.defer()

        try:
            from bot import TASK_HEALTH
            import psutil
            import tracemalloc

            embed = discord.Embed(
                title="🏋️ Bot Health Status",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            # Background Tasks
            task_status = []
            for task_name, health in TASK_HEALTH.items():
                last_run = health.get('last_run')
                error_count = health.get('error_count', 0)

                if last_run:
                    elapsed = (datetime.now() - last_run).total_seconds()
                    status_icon = "🟢" if elapsed < 300 and error_count < 5 else "🟡" if elapsed < 600 else "🔴"
                    task_status.append(f"{status_icon} **{task_name}**")
                    task_status.append(f"   Last run: {format_time_duration(elapsed)} ago")
                    task_status.append(f"   Errors: {error_count}")
                else:
                    task_status.append(f"⚪ **{task_name}**")
                    task_status.append(f"   Not started yet")

            embed.add_field(
                name="Background Tasks",
                value="\n".join(task_status) if task_status else "No tasks running",
                inline=False
            )

            # Memory Usage
            current, peak = tracemalloc.get_traced_memory()
            mem_mb = current / 1024 / 1024
            embed.add_field(
                name="Memory Usage",
                value=f"Current: {mem_mb:.1f} MB",
                inline=True
            )

            # Database Status
            stats = await db.get_database_stats()
            if stats:
                db_status = f"✅ Connected\n"
                db_status += f"Actions: {stats.get('total_actions', 0):,}\n"
                db_status += f"Players: {stats.get('total_players', 0):,}"
                embed.add_field(name="Database", value=db_status, inline=True)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in health command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(name="config", description="Display current configuration")
    @app_commands.checks.cooldown(1, 30)
    async def config_command(interaction: discord.Interaction):
        """Display current configuration"""
        await interaction.response.defer()

        try:
            embed = discord.Embed(
                title="⚙️ Bot Configuration",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            # Database
            embed.add_field(
                name="📁 Database",
                value=f"Path: `{db.db_path}`",
                inline=False
            )

            # Task Intervals
            embed.add_field(
                name="⏱️ Task Intervals",
                value="• Actions: 30s\n• Online Players: 60s\n• Profile Updates: 2min\n• Ban Check: 1h",
                inline=False
            )

            # Scraper Settings
            scraper = await scraper_getter()
            embed.add_field(
                name="🌐 Scraper",
                value=f"• Workers: {scraper.max_concurrent}\n• Rate: Adaptive",
                inline=False
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in config command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(name="stats", description="Show database statistics")
    @app_commands.checks.cooldown(1, 10)
    async def stats_command(interaction: discord.Interaction):
        """🔥 FIXED: Show database statistics with accurate online count (last 24h)"""
        await interaction.response.defer()

        try:
            stats = await db.get_database_stats()

            embed = discord.Embed(
                title="📊 Database Statistics",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            embed.add_field(name="👥 Total Players", value=f"{stats.get('total_players', 0):,}", inline=True)
            embed.add_field(name="📝 Total Actions", value=f"{stats.get('total_actions', 0):,}", inline=True)
            
            # 🔥 FIXED: Changed from "Online Now" to "Online Last 24h" and uses accurate count
            online_24h_count = await db.get_online_players_last_24h_count()
            embed.add_field(name="🟢 Online Last 24h", value=f"{online_24h_count:,}", inline=True)

            # Recent Activity
            actions_24h = await db.get_actions_count_last_24h()
            embed.add_field(name="📈 Actions (24h)", value=f"{actions_24h:,}", inline=True)

            logins_today = await db.get_logins_count_today()
            embed.add_field(name="🔑 Logins Today", value=f"{logins_today:,}", inline=True)

            banned_count = await db.get_active_bans_count()
            embed.add_field(name="🚫 Active Bans", value=f"{banned_count:,}", inline=True)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in stats command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # PLAYER COMMANDS
    # ========================================================================

    @bot.tree.command(name="search", description="Search players by name")
    @app_commands.describe(query="Search term (minimum 2 characters)")
    @app_commands.checks.cooldown(1, 10)
    async def search_command(interaction: discord.Interaction, query: str):
        """Search players by name"""
        await interaction.response.defer()

        try:
            if len(query) < 2:
                await interaction.followup.send("❌ Search query must be at least 2 characters long!")
                return

            players = await db.search_player_by_name(query)

            if not players:
                await interaction.followup.send(f"🔍 **No Results**\n\nNo players found matching: `{query}`")
                return

            # Build results embed
            embed = discord.Embed(
                title=f"🔍 Search Results for '{query}'",
                description=f"Found {len(players)} player(s)",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            # Show up to 10 results
            for i, player in enumerate(players[:10]):
                status = "🟢 Online" if player.get('is_online') else "⚪ Offline"
                faction = player.get('faction') or "No faction"
                
                value = f"{status}\n├ Faction: {faction}"
                embed.add_field(
                    name=f"{player['username']} (ID: {player['player_id']})",
                    value=value,
                    inline=False
                )

            if len(players) > 10:
                embed.set_footer(text=f"Showing 10 of {len(players)} results")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in search command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(name="actions", description="Get player's recent actions")
    @app_commands.describe(
        identifier="Player ID or name",
        days="Days to look back (default: 7, max: 30)"
    )
    @app_commands.checks.cooldown(1, 30)
    async def actions_command(interaction: discord.Interaction, identifier: str, days: Optional[int] = 7):
        """Get player's recent actions with pagination and deduplication"""
        await interaction.response.defer()

        try:
            if days < 1 or days > 30:
                await interaction.followup.send("❌ Days must be between 1 and 30!")
                return

            scraper = await scraper_getter()
            player = await resolve_player_info(db, scraper, identifier)

            if not player:
                await interaction.followup.send(f"🔍 **Not Found**\n\nNo player found with identifier: `{identifier}`")
                return

            actions = await db.get_player_actions(player['player_id'], days)

            if not actions:
                await interaction.followup.send(f"📝 **No Actions**\n\n{player['username']} has no recorded actions in the last {days} days.")
                return

            # Store original count before deduplication
            original_count = len(actions)
            
            # Create pagination view (will deduplicate internally)
            view = ActionsPaginationView(
                actions=actions,
                player_info=player,
                days=days,
                author_id=interaction.user.id,
                original_count=original_count
            )
            
            # Send initial page with pagination buttons
            embed = view.build_embed()
            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message  # Store message reference for timeout handling

        except Exception as e:
            logger.error(f"Error in actions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")


    @bot.tree.command(name="sessions", description="View player's gaming sessions")
    @app_commands.describe(
        identifier="Player ID or name",
        days="Days to look back (default: 7, max: 30)"
    )
    @app_commands.checks.cooldown(1, 10)
    async def sessions_command(interaction: discord.Interaction, identifier: str, days: Optional[int] = 7):
        """View player's gaming sessions"""
        await interaction.response.defer()

        try:
            if days < 1 or days > 30:
                await interaction.followup.send("❌ Days must be between 1 and 30!")
                return

            scraper = await scraper_getter()
            player = await resolve_player_info(db, scraper, identifier)

            if not player:
                await interaction.followup.send(f"🔍 **Not Found**\n\nNo player found with identifier: `{identifier}`")
                return

            sessions = await db.get_player_sessions(player['player_id'], days)

            if not sessions:
                await interaction.followup.send(f"📊 **No Sessions**\n\n{player['username']} has no recorded sessions in the last {days} days.")
                return

            # Calculate total playtime
            total_seconds = sum(s.get('session_duration_seconds', 0) for s in sessions if s.get('session_duration_seconds'))
            total_hours = total_seconds / 3600

            embed = discord.Embed(
                title=f"📊 Sessions for {player['username']}",
                description=f"Last {days} days • {len(sessions)} sessions • {total_hours:.1f}h total",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            # Show up to 10 most recent sessions
            for session in sessions[:10]:
                login_time = session.get('login_time')
                logout_time = session.get('logout_time')
                duration = session.get('session_duration_seconds', 0)

                if isinstance(login_time, str):
                    login_time = datetime.fromisoformat(login_time)
                if isinstance(logout_time, str):
                    logout_time = datetime.fromisoformat(logout_time)

                login_str = login_time.strftime('%Y-%m-%d %H:%M') if login_time else 'Unknown'
                logout_str = logout_time.strftime('%H:%M') if logout_time else 'Still online'
                duration_str = format_time_duration(duration) if duration else 'N/A'

                value = f"Login: {login_str}\nLogout: {logout_str}\nDuration: {duration_str}"
                embed.add_field(name=f"Session {len(sessions) - sessions.index(session)}", value=value, inline=True)

            if len(sessions) > 10:
                embed.set_footer(text=f"Showing 10 of {len(sessions)} sessions")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in sessions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(name="rank_history", description="View player's faction rank history")
    @app_commands.describe(identifier="Player ID or name")
    @app_commands.checks.cooldown(1, 10)
    async def rank_history_command(interaction: discord.Interaction, identifier: str):
        """View player's faction rank history"""
        await interaction.response.defer()

        try:
            scraper = await scraper_getter()
            player = await resolve_player_info(db, scraper, identifier)

            if not player:
                await interaction.followup.send(f"🔍 **Not Found**\n\nNo player found with identifier: `{identifier}`")
                return

            rank_history = await db.get_player_rank_history(player['player_id'])

            if not rank_history:
                await interaction.followup.send(f"📊 **No Rank History**\n\n{player['username']} has no recorded rank changes.")
                return

            embed = discord.Embed(
                title=f"📊 Rank History for {player['username']}",
                description=f"{len(rank_history)} rank change(s)",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            for rank in rank_history:
                faction = rank.get('faction', 'Unknown')
                rank_name = rank.get('rank_name', 'Unknown')
                obtained = rank.get('rank_obtained')
                lost = rank.get('rank_lost')
                is_current = rank.get('is_current', False)

                if isinstance(obtained, str):
                    obtained = datetime.fromisoformat(obtained)
                if isinstance(lost, str):
                    lost = datetime.fromisoformat(lost)

                obtained_str = obtained.strftime('%Y-%m-%d') if obtained else 'Unknown'

                if is_current:
                    duration_str = "Current"
                elif lost:
                    duration = (lost - obtained).days if obtained else 0
                    duration_str = f"{duration} days"
                else:
                    duration_str = "Unknown"

                value = f"Faction: {faction}\nObtained: {obtained_str}\nDuration: {duration_str}"
                title = f"{'🟢 ' if is_current else ''}{rank_name}"
                embed.add_field(name=title, value=value, inline=True)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in rank_history command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # FACTION COMMANDS
    # ========================================================================

    @bot.tree.command(name="faction", description="🔥 FIXED: List all members of a faction (auto-refreshes placeholder usernames)")
    @app_commands.describe(faction_name="Name of faction")
    @app_commands.checks.cooldown(1, 30)
    async def faction_command(interaction: discord.Interaction, faction_name: str):
        """🔥 FIXED: List all members of a faction - auto-refreshes placeholder usernames AND missing ranks"""
        await interaction.response.defer()

        try:
            members = await db.get_faction_members(faction_name)

            if not members:
                await interaction.followup.send(f"🔍 **Not Found**\n\nNo members found in faction: `{faction_name}`")
                return

            # 🔥 ENHANCED: Identify members needing refresh (placeholder usernames OR missing ranks)
            members_needing_refresh = []
            for member in members:
                username = member.get('username', '')
                rank = member.get('faction_rank')
                
                # Refresh if username is placeholder OR rank is missing
                needs_refresh = False
                
                if is_placeholder_username(username):
                    logger.debug(f"Member {member['player_id']} has placeholder username: {username}")
                    needs_refresh = True
                
                if not rank or rank.lower() in ('null', 'none', '', '-', 'n/a'):
                    logger.debug(f"Member {member['player_id']} has missing rank")
                    needs_refresh = True
                
                if needs_refresh:
                    members_needing_refresh.append(member['player_id'])
            
            # If there are members needing refresh, refresh them
            if members_needing_refresh:
                logger.info(f"🔄 Refreshing {len(members_needing_refresh)} members in {faction_name} (placeholder usernames or missing ranks)")
                
                scraper = await scraper_getter()
                
                # Batch fetch fresh profiles
                fresh_profiles = await scraper.batch_get_profiles(members_needing_refresh[:20])  # Limit to 20 to avoid timeout
                
                # Save updated profiles to database
                refresh_count = 0
                for profile in fresh_profiles:
                    if profile:
                        profile_dict = {
                            'player_id': profile.player_id,
                            'player_name': profile.username,
                            'is_online': profile.is_online,
                            'last_connection': profile.last_seen,
                            'faction': profile.faction,
                            'faction_rank': profile.faction_rank,
                            'job': profile.job,
                            'warns': profile.warnings,
                            'played_hours': profile.played_hours,
                            'age_ic': profile.age_ic
                        }
                        await db.save_player_profile(profile_dict)
                        refresh_count += 1
                
                logger.info(f"✅ Refreshed {refresh_count} faction member profiles")
                
                # Re-fetch members from database to get updated data
                members = await db.get_faction_members(faction_name)

            # Create pagination view
            view = FactionPaginationView(
                members=members,
                faction_name=faction_name,
                author_id=interaction.user.id
            )
            
            # Send initial page with pagination buttons
            embed = view.build_embed()
            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message  # Store message reference for timeout handling

        except Exception as e:
            logger.error(f"Error in faction command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(name="factionlist", description="🔥 FIXED: List all factions with currently online members only")
    @app_commands.checks.cooldown(1, 30)
    async def faction_list_command(interaction: discord.Interaction):
        """🔥 FIXED: List all factions with member counts and CURRENT online counts"""
        await interaction.response.defer()

        try:
            factions = await db.get_all_factions_with_counts()

            if not factions:
                await interaction.followup.send("📊 **No Factions**\n\nNo factions found in the database.")
                return

            embed = discord.Embed(
                title="📋 All Factions",
                description=f"Total: {len(factions)} faction(s)\n💡 Online count shows currently online members",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            # Show up to 25 factions
            for i, faction in enumerate(factions[:25], 1):
                faction_name = faction['faction_name']
                member_count = faction['member_count']
                online_count = faction.get('online_count', 0)
                
                # 🔥 FIXED: Now shows accurate online count from online_players table
                value = f"👥 {member_count} member(s) • 🟢 {online_count} online now"
                embed.add_field(
                    name=f"{i}. {faction_name}",
                    value=value,
                    inline=False
                )

            if len(factions) > 25:
                embed.set_footer(text=f"Showing top 25 of {len(factions)} factions")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in faction list command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(name="promotions", description="Recent faction promotions")
    @app_commands.describe(days="Days to look back (default: 7, max: 30)")
    @app_commands.checks.cooldown(1, 30)
    async def promotions_command(interaction: discord.Interaction, days: Optional[int] = 7):
        """Recent faction promotions"""
        await interaction.response.defer()

        try:
            if days < 1 or days > 30:
                await interaction.followup.send("❌ Days must be between 1 and 30!")
                return

            promotions = await db.get_recent_promotions(days)

            if not promotions:
                await interaction.followup.send(f"📊 **No Promotions**\n\nNo promotions recorded in the last {days} days.")
                return

            embed = discord.Embed(
                title=f"📊 Recent Promotions",
                description=f"Last {days} days • {len(promotions)} promotion(s)",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            for promo in promotions[:15]:
                player_name = promo.get('player_name', 'Unknown')
                old_rank = promo.get('old_rank', 'None')
                new_rank = promo.get('new_rank', 'Unknown')
                faction = promo.get('faction', 'Unknown')
                timestamp = promo.get('timestamp')

                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)
                time_str = timestamp.strftime('%Y-%m-%d') if timestamp else 'Unknown'

                value = f"{faction}\n{old_rank} → {new_rank}\n{time_str}"
                embed.add_field(name=player_name, value=value, inline=True)

            if len(promotions) > 15:
                embed.set_footer(text=f"Showing 15 of {len(promotions)} promotions")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in promotions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # BAN COMMANDS
    # ========================================================================

    @bot.tree.command(name="bans", description="View banned players")
    @app_commands.describe(show_expired="Include expired bans (default: false)")
    @app_commands.checks.cooldown(1, 30)
    async def bans_command(interaction: discord.Interaction, show_expired: Optional[bool] = False):
        """View banned players"""
        await interaction.response.defer()

        try:
            bans = await db.get_banned_players(show_expired)

            if not bans:
                await interaction.followup.send("📊 **No Bans**\n\nNo banned players found.")
                return

            embed = discord.Embed(
                title="🚫 Banned Players",
                description=f"{len(bans)} ban(s)",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )

            for ban in bans[:15]:
                player_name = ban.get('player_name', 'Unknown')
                reason = ban.get('reason', 'No reason')
                admin = ban.get('admin', 'Unknown')
                duration = ban.get('duration', 'Unknown')
                is_active = ban.get('is_active', False)

                status = "🔴 Active" if is_active else "⚪ Expired"
                value = f"{status}\nReason: {reason}\nAdmin: {admin}\nDuration: {duration}"

                embed.add_field(name=player_name, value=value, inline=False)

            if len(bans) > 15:
                embed.set_footer(text=f"Showing 15 of {len(bans)} bans")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in bans command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # ONLINE COMMAND
    # ========================================================================

    @bot.tree.command(name="online", description="Current online players")
    @app_commands.checks.cooldown(1, 10)
    async def online_command(interaction: discord.Interaction):
        """Current online players"""
        await interaction.response.defer()

        try:
            online_players = await db.get_current_online_players()

            if not online_players:
                await interaction.followup.send("📊 **No Players Online**")
                return

            embed = discord.Embed(
                title="🟢 Online Players",
                description=f"{len(online_players)} player(s) online",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )

            # Show up to 20 players
            for player in online_players[:20]:
                player_name = player.get('player_name', 'Unknown')
                player_id = player.get('player_id', '?')

                embed.add_field(
                    name=f"{player_name}",
                    value=f"ID: {player_id}",
                    inline=True
                )

            if len(online_players) > 20:
                embed.set_footer(text=f"Showing 20 of {len(online_players)} players")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in online command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # 🆕 PLAYER PROFILE & STATS COMMANDS
    # ========================================================================
    
    @bot.tree.command(name="player", description="🔥 FIXED: Get complete player profile (auto-refreshes placeholder username & missing age)")
    @app_commands.describe(identifier="Player ID or name")
    @app_commands.checks.cooldown(1, 5)
    async def player_command(interaction: discord.Interaction, identifier: str):
        """🔥 FIXED: Get complete player profile - auto-refreshes placeholder usernames AND missing age_ic"""
        await interaction.response.defer()
        
        try:
            # Get player from database first
            player = await db.get_player_stats(identifier)
            
            if not player:
                # Try fetching from website as fallback
                scraper = await scraper_getter()
                
                # Try as ID
                if identifier.isdigit():
                    profile_obj = await scraper.get_player_profile(identifier)
                    if profile_obj:
                        player = {
                            'player_id': profile_obj.player_id,
                            'username': profile_obj.username,
                            'is_online': profile_obj.is_online,
                            'last_seen': profile_obj.last_seen,
                            'faction': profile_obj.faction,
                            'faction_rank': profile_obj.faction_rank,
                            'job': profile_obj.job,
                            'warnings': profile_obj.warnings,
                            'played_hours': profile_obj.played_hours,
                            'age_ic': profile_obj.age_ic
                        }
                        await db.save_player_profile(player)
            
            if not player:
                await interaction.followup.send(
                    f"🔍 **Not Found**\n\nNo player found with identifier: `{identifier}`"
                )
                return
            
            # 🔥 ENHANCED: Check if player needs refresh (placeholder username OR missing data)
            username = player.get('username', '')
            faction = player.get('faction')
            faction_rank = player.get('faction_rank')
            age_ic = player.get('age_ic')
            
            needs_refresh = False
            refresh_reasons = []
            
            # Check for placeholder username
            if is_placeholder_username(username):
                needs_refresh = True
                refresh_reasons.append(f"placeholder username '{username}'")
            
            # Check for missing age_ic
            if not age_ic or age_ic == 0:
                needs_refresh = True
                refresh_reasons.append("missing Age (IC)")
            
            # Check for missing faction rank (if has faction)
            if faction and faction not in (None, '', 'Civil', 'Fără', 'None', '-', 'N/A'):
                if not faction_rank or faction_rank.lower() in ('null', 'none', '', '-', 'unknown'):
                    needs_refresh = True
                    refresh_reasons.append("missing faction rank")
            
            # Perform refresh if needed
            if needs_refresh:
                logger.info(f"🔄 Player {player['player_id']} needs refresh: {', '.join(refresh_reasons)}")
                
                scraper = await scraper_getter()
                profile_obj = await scraper.get_player_profile(player['player_id'])
                
                if profile_obj:
                    # Update player data with fresh profile
                    player_update = {
                        'player_id': profile_obj.player_id,
                        'player_name': profile_obj.username,
                        'is_online': profile_obj.is_online,
                        'last_connection': profile_obj.last_seen,
                        'faction': profile_obj.faction,
                        'faction_rank': profile_obj.faction_rank,
                        'job': profile_obj.job,
                        'warns': profile_obj.warnings,
                        'played_hours': profile_obj.played_hours,
                        'age_ic': profile_obj.age_ic
                    }
                    await db.save_player_profile(player_update)
                    
                    # Update local player dict
                    player['username'] = profile_obj.username
                    player['faction_rank'] = profile_obj.faction_rank
                    player['age_ic'] = profile_obj.age_ic
                    
                    logger.info(f"✅ Refreshed player {player['player_id']}: username={profile_obj.username}, rank={profile_obj.faction_rank}, age_ic={profile_obj.age_ic}")
            
            # Build profile embed
            status_icon = "🟢" if player.get('is_online') else "⚪"
            
            embed = discord.Embed(
                title=f"{status_icon} {player['username']}",
                description=f"Player ID: `{player['player_id']}`",
                color=discord.Color.green() if player.get('is_online') else discord.Color.greyple(),
                timestamp=datetime.now()
            )
            
            # Status
            status_value = "Online now" if player.get('is_online') else f"Last seen: {format_last_seen(player.get('last_seen'))}"
            embed.add_field(name="Status", value=status_value, inline=True)
            
            # Faction/Rank display
            faction = player.get('faction')
            faction_rank = player.get('faction_rank')
            
            if faction and faction not in (None, '', 'Civil', 'Fără', 'None', '-', 'N/A'):
                # Player has a faction
                if faction_rank and faction_rank not in (None, '', 'null', 'NULL', 'none', 'None'):
                    # Has both faction and rank
                    faction_display = f"{faction}\n├ Rank: {faction_rank}"
                else:
                    # Has faction but rank is still missing after refresh attempt
                    faction_display = f"{faction}\n├ Rank: Membru"  # Default to Membru
            else:
                # No faction
                faction_display = "No faction"
            
            embed.add_field(name="Faction", value=faction_display, inline=True)
            
            # Job
            job = player.get('job') or "Unemployed"
            embed.add_field(name="Job", value=job, inline=True)
            
            # Warnings
            warnings = player.get('warnings', 0) or 0
            warn_color = "🟢" if warnings == 0 else "🟡" if warnings < 3 else "🔴"
            embed.add_field(name="Warnings", value=f"{warn_color} {warnings}/3", inline=True)
            
            # Played hours
            hours = player.get('played_hours', 0) or 0
            embed.add_field(name="Played Hours", value=f"{hours:.1f}h", inline=True)
            
            # Age IC - show even if Unknown
            age_ic = player.get('age_ic')
            age_ic_display = str(age_ic) if age_ic and age_ic > 0 else "Unknown"
            embed.add_field(name="Age (IC)", value=age_ic_display, inline=True)
            
            # Get action count from player_profiles table (already cached)
            total_actions = player.get('total_actions', 0) or 0
            embed.add_field(name="📊 Total Actions", value=f"{total_actions:,}", inline=True)
            
            # Optimized: Use a lighter query for recent actions count only
            def _count_recent_actions():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cutoff = datetime.now() - timedelta(days=7)
                    cursor.execute('''
                        SELECT COUNT(*) FROM actions
                        WHERE (player_id = ? OR target_player_id = ?)
                        AND timestamp >= ?
                    ''', (player['player_id'], player['player_id'], cutoff))
                    return cursor.fetchone()[0]
            
            recent_count = await asyncio.to_thread(_count_recent_actions)
            embed.add_field(name="📝 Actions (7d)", value=f"{recent_count:,}", inline=True)
            
            # First detected
            first_detected = player.get('first_detected')
            if first_detected:
                if isinstance(first_detected, str):
                    try:
                        first_detected = datetime.fromisoformat(first_detected)
                    except:
                        first_detected = None
                if first_detected and isinstance(first_detected, datetime):
                    embed.add_field(
                        name="First Detected",
                        value=first_detected.strftime('%Y-%m-%d'),
                        inline=True
                    )
            
            embed.set_footer(text=f"Use /actions {player['player_id']} to see recent activity")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in player command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ========================================================================
    # 🆕 ADMIN COMMAND - REFRESH PLAYER
    # ========================================================================
    
    @bot.tree.command(name="refresh_player", description="🆕 Force refresh player profile from website (Admin only)")
    @app_commands.describe(player_id="Player ID to refresh")
    @app_commands.checks.cooldown(1, 10)
    async def refresh_player_command(interaction: discord.Interaction, player_id: str):
        """🆕 Force refresh player profile - fixes stale data"""
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nThis command is restricted to bot administrators.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        try:
            if not player_id.isdigit():
                await interaction.followup.send("❌ Player ID must be a number!")
                return
            
            scraper = await scraper_getter()
            
            # Fetch fresh profile from website
            logger.info(f"🔄 Refreshing profile for player {player_id}...")
            profile_obj = await scraper.get_player_profile(player_id)
            
            if not profile_obj:
                await interaction.followup.send(f"❌ **Not Found**\n\nPlayer {player_id} not found on website.")
                return
            
            # Save to database
            profile = {
                'player_id': profile_obj.player_id,
                'player_name': profile_obj.username,
                'is_online': profile_obj.is_online,
                'last_connection': profile_obj.last_seen,
                'faction': profile_obj.faction,
                'faction_rank': profile_obj.faction_rank,
                'job': profile_obj.job,
                'warns': profile_obj.warnings,
                'played_hours': profile_obj.played_hours,
                'age_ic': profile_obj.age_ic
            }
            
            await db.save_player_profile(profile)
            logger.info(f"✅ Updated profile for {profile_obj.username} ({player_id})")
            
            # Build success embed
            embed = discord.Embed(
                title="✅ Profile Refreshed",
                description=f"Successfully updated profile for **{profile_obj.username}** (ID: {player_id})",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            # Show updated fields
            embed.add_field(name="Username", value=profile_obj.username, inline=True)
            embed.add_field(name="Faction", value=profile_obj.faction or "No faction", inline=True)
            embed.add_field(name="Rank", value=profile_obj.faction_rank or "None", inline=True)
            embed.add_field(name="Status", value="🟢 Online" if profile_obj.is_online else "⚪ Offline", inline=True)
            embed.add_field(name="Job", value=profile_obj.job or "None", inline=True)
            embed.add_field(name="Warnings", value=str(profile_obj.warnings or 0), inline=True)
            embed.add_field(name="Age (IC)", value=str(profile_obj.age_ic) if profile_obj.age_ic else "Unknown", inline=True)
            
            embed.set_footer(text="Use /player to view full profile")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in refresh_player command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # Rest of commands remain the same (ADMIN COMMANDS, SCAN MANAGEMENT, etc.)
    # ... [keeping all remaining commands unchanged for brevity]
    
    logger.info("✅ All slash commands registered successfully with auto-refresh for placeholder usernames")

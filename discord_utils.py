"""Discord utility functions for safe command handling"""
import discord
from discord import ui
from discord.ext import commands
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable, Any
import logging
from functools import wraps

logger = logging.getLogger(__name__)

# ============================================================================
# COMMAND COOLDOWNS
# ============================================================================


class CooldownTracker:
    """Track command cooldowns per user"""

    def __init__(self):
        self.cooldowns: Dict[str, Dict[int, datetime]] = {}

    def is_on_cooldown(
        self, command_name: str, user_id: int, cooldown_seconds: int
    ) -> tuple[bool, int]:
        """
        Check if user is on cooldown for command

        Returns:
            (is_on_cooldown, seconds_remaining)
        """
        if command_name not in self.cooldowns:
            self.cooldowns[command_name] = {}

        if user_id not in self.cooldowns[command_name]:
            return False, 0

        last_use = self.cooldowns[command_name][user_id]
        elapsed = (datetime.now() - last_use).total_seconds()

        if elapsed < cooldown_seconds:
            remaining = int(cooldown_seconds - elapsed)
            return True, remaining

        return False, 0

    def set_cooldown(self, command_name: str, user_id: int):
        """Mark command as used by user"""
        if command_name not in self.cooldowns:
            self.cooldowns[command_name] = {}

        self.cooldowns[command_name][user_id] = datetime.now()

    def reset_cooldown(self, command_name: str, user_id: int):
        """Reset cooldown for user (admin override)"""
        if command_name in self.cooldowns and user_id in self.cooldowns[command_name]:
            del self.cooldowns[command_name][user_id]


# Global cooldown tracker
cooldown_tracker = CooldownTracker()


def cooldown(seconds: int = 60, admin_bypass: bool = True):
    """Decorator to add cooldown to slash commands"""

    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *args, **kwargs):
            from config import Config

            # Admin bypass
            if (
                admin_bypass
                and Config.ADMIN_USER_IDS
                and interaction.user.id in Config.ADMIN_USER_IDS
            ):
                return await func(interaction, *args, **kwargs)

            # Check cooldown
            on_cooldown, remaining = cooldown_tracker.is_on_cooldown(
                func.__name__, interaction.user.id, seconds
            )

            if on_cooldown:
                await interaction.response.send_message(
                    f"⏳ This command is on cooldown. Try again in **{remaining}** seconds.",
                    ephemeral=True,
                )
                return

            # Set cooldown and execute
            cooldown_tracker.set_cooldown(func.__name__, interaction.user.id)
            return await func(interaction, *args, **kwargs)

        return wrapper

    return decorator


# ============================================================================
# PERMISSION CHECKS
# ============================================================================


class PermissionError(Exception):
    """Raised when user lacks permissions"""

    pass


def is_admin(user_id: int, admin_ids: List[int]) -> bool:
    """
    Check if user is admin

    If no admins configured, first user becomes admin (safety feature)
    """
    if not admin_ids:
        logger.warning("No admin users configured! All users have admin access.")
        return True  # Fallback: no restrictions if not configured

    return user_id in admin_ids


def require_admin():
    """Decorator to require admin permissions"""

    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *args, **kwargs):
            from config import Config

            if not is_admin(interaction.user.id, Config.ADMIN_USER_IDS):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n"
                    "This command is restricted to bot administrators.",
                    ephemeral=True,
                )
                logger.warning(
                    f"Unauthorized admin command attempt: {func.__name__} by "
                    f"{interaction.user.name} ({interaction.user.id})"
                )
                raise PermissionError(f"User {interaction.user.id} is not an admin")

            return await func(interaction, *args, **kwargs)

        return wrapper

    return decorator


# ============================================================================
# PAGINATION
# ============================================================================


class PaginationView(ui.View):
    """Interactive pagination with buttons"""

    def __init__(self, embeds: List[discord.Embed], timeout: int = 180):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.current_page = 0
        self.total_pages = len(embeds)

        # Update button states
        self._update_buttons()

    def _update_buttons(self):
        """Enable/disable buttons based on current page"""
        self.first_page.disabled = self.current_page == 0
        self.prev_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page >= self.total_pages - 1
        self.last_page.disabled = self.current_page >= self.total_pages - 1

    @ui.button(label="⏮️", style=discord.ButtonStyle.gray)
    async def first_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = 0
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.embeds[self.current_page], view=self
        )

    @ui.button(label="◀️", style=discord.ButtonStyle.primary)
    async def prev_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = max(0, self.current_page - 1)
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.embeds[self.current_page], view=self
        )

    @ui.button(label="▶️", style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.embeds[self.current_page], view=self
        )

    @ui.button(label="⏭️", style=discord.ButtonStyle.gray)
    async def last_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = self.total_pages - 1
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.embeds[self.current_page], view=self
        )

    @ui.button(label="🗑️", style=discord.ButtonStyle.danger)
    async def delete_message(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.message.delete()
        self.stop()

    async def on_timeout(self):
        """Disable buttons when view times out"""
        for item in self.children:
            item.disabled = True


def create_paginated_embeds(
    items: List[Any],
    items_per_page: int,
    title: str,
    formatter: Callable[[Any], str],
    color: discord.Color = discord.Color.blue(),
    thumbnail_url: Optional[str] = None,
) -> List[discord.Embed]:
    """
    Create paginated embeds from items

    Args:
        items: List of items to paginate
        items_per_page: Number of items per page
        title: Base title for embeds
        formatter: Function to format each item as string
        color: Embed color
        thumbnail_url: Optional thumbnail for embeds

    Returns:
        List of Discord embeds
    """
    if not items:
        embed = discord.Embed(
            title=title, description="No results found.", color=discord.Color.orange()
        )
        return [embed]

    embeds = []
    total_pages = (len(items) + items_per_page - 1) // items_per_page

    for page in range(total_pages):
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(items))
        page_items = items[start_idx:end_idx]

        embed = discord.Embed(
            title=f"{title} (Page {page + 1}/{total_pages})",
            color=color,
            timestamp=datetime.now(),
        )

        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)

        description_parts = []
        for item in page_items:
            description_parts.append(formatter(item))

        embed.description = "\n\n".join(description_parts)

        embed.set_footer(
            text=f"Showing {start_idx + 1}-{end_idx} of {len(items)} results"
        )

        embeds.append(embed)

    return embeds


async def send_paginated(
    interaction: discord.Interaction,
    embeds: List[discord.Embed],
    ephemeral: bool = False,
):
    """
    Send paginated embeds with navigation buttons

    Args:
        interaction: Discord interaction
        embeds: List of embeds to paginate
        ephemeral: Whether message should be ephemeral
    """
    if len(embeds) == 1:
        # Single page, no pagination needed
        await interaction.followup.send(embed=embeds[0], ephemeral=ephemeral)
    else:
        # Multiple pages, add pagination
        view = PaginationView(embeds)
        await interaction.followup.send(embed=embeds[0], view=view, ephemeral=ephemeral)


# ============================================================================
# ERROR HANDLING
# ============================================================================


class UserFriendlyError:
    """Convert technical errors to user-friendly messages"""

    ERROR_MESSAGES = {
        "database is locked": (
            "⏳ **Database Busy**\n"
            "The database is currently processing other operations. "
            "Please try again in a few moments."
        ),
        "timeout": (
            "⏱️ **Operation Timed Out**\n"
            "This operation took too long to complete. "
            "Try narrowing your search criteria or contact an administrator."
        ),
        "connection": (
            "🔌 **Connection Error**\n"
            "Unable to connect to external service. "
            "The issue may be temporary - please try again later."
        ),
        "not found": (
            "🔍 **Not Found**\n"
            "The requested resource could not be found. "
            "Please check your input and try again."
        ),
        "permission": (
            "🔒 **Permission Denied**\n"
            "You don't have permission to perform this action. "
            "Contact an administrator if you believe this is an error."
        ),
        "rate limit": (
            "🚦 **Rate Limited**\n"
            "Too many requests. Please wait a moment before trying again."
        ),
    }

    @classmethod
    def format(cls, error: Exception) -> str:
        """
        Convert exception to user-friendly message

        Args:
            error: Exception to format

        Returns:
            User-friendly error message
        """
        error_str = str(error).lower()

        # Check for known error patterns
        for pattern, message in cls.ERROR_MESSAGES.items():
            if pattern in error_str:
                return message

        # Generic error message
        return (
            "❌ **An Error Occurred**\n"
            "Something went wrong while processing your request. "
            f"Please try again or contact an administrator.\n\n"
            f"*Technical details: {str(error)[:100]}*"
        )


async def safe_defer(interaction: discord.Interaction, ephemeral: bool = False):
    """
    Safely defer interaction response

    Handles cases where interaction is already responded to
    """
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)
    except discord.errors.InteractionResponded:
        pass  # Already responded
    except Exception as e:
        logger.error(f"Error deferring interaction: {e}")


async def safe_send(
    interaction: discord.Interaction,
    content: str = None,
    embed: discord.Embed = None,
    ephemeral: bool = False,
    view: ui.View = None,
):
    """
    Safely send response, handling both initial response and followup

    Args:
        interaction: Discord interaction
        content: Message content
        embed: Embed to send
        ephemeral: Whether message should be ephemeral
        view: View with components
    """
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                content=content, embed=embed, ephemeral=ephemeral, view=view
            )
        else:
            await interaction.followup.send(
                content=content, embed=embed, ephemeral=ephemeral, view=view
            )
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        # Try followup as last resort
        try:
            await interaction.followup.send(
                content="❌ An error occurred while sending the response.",
                ephemeral=True,
            )
        except:
            pass


# ============================================================================
# QUERY LIMITING
# ============================================================================


class QueryLimits:
    """Safe query limits to prevent database overload"""

    # Maximum results per query type
    MAX_ACTIONS = 1000
    MAX_PLAYERS = 500
    MAX_LOGIN_EVENTS = 500
    MAX_PROFILE_HISTORY = 200

    # Items per page for pagination
    ACTIONS_PER_PAGE = 10
    PLAYERS_PER_PAGE = 10
    LOGIN_EVENTS_PER_PAGE = 15

    @classmethod
    def apply_limit(cls, query: str, limit_type: str) -> str:
        """
        Add LIMIT clause to SQL query if not present

        Args:
            query: SQL query
            limit_type: Type of query ('actions', 'players', etc.)

        Returns:
            Query with LIMIT clause
        """
        if "LIMIT" in query.upper():
            return query  # Already has limit

        limits = {
            "actions": cls.MAX_ACTIONS,
            "players": cls.MAX_PLAYERS,
            "login_events": cls.MAX_LOGIN_EVENTS,
            "profile_history": cls.MAX_PROFILE_HISTORY,
        }

        limit = limits.get(limit_type, 100)
        return f"{query.rstrip(';')} LIMIT {limit}"

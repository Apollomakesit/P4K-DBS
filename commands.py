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
from config import Config

logger = logging.getLogger(__name__)

# SCAN STATE - Shared across commands
SCAN_STATE = {
    "is_scanning": False,
    "is_paused": False,
    "start_id": 0,
    "end_id": 0,
    "current_id": 0,
    "found_count": 0,
    "error_count": 0,
    "start_time": None,
    "scan_task": None,
    "status_message": None,
    "status_task": None,
    "scan_config": {
        "batch_size": 50,
        "workers": 10,
        "wave_delay": 0.05,
        "max_concurrent_batches": 5,
    },
    "worker_stats": {},
    "total_scanned": 0,
    "last_speed_update": None,
    "current_speed": 0.0,
}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def is_placeholder_username(username: str) -> bool:
    """🆕 Check if username is a placeholder like 'Player_12345'

    Returns True if username matches pattern: Player_<digits>
    """
    if not username or not isinstance(username, str):
        return False

    # Check if it starts with "Player_" and the rest are digits
    if username.startswith("Player_"):
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
        timestamp = action.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        # Round to the nearest second for grouping
        timestamp_key = timestamp.replace(microsecond=0) if timestamp else None
        action_type = action.get("action_type", "unknown")
        action_detail = action.get("action_detail", "")

        key = (timestamp_key, action_type, action_detail)
        grouped[key].append(action)

    # Create deduplicated list with counts
    deduplicated = []
    for key, group in grouped.items():
        # Take the first action from the group
        action = group[0].copy()
        # Add count if there are duplicates
        if len(group) > 1:
            action["count"] = len(group)
        deduplicated.append(action)

    # Sort by timestamp descending (most recent first)
    deduplicated.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return deduplicated


def extract_target_from_detail(action_detail: str) -> tuple:
    """Extract target_player_id and target_player_name from action_detail text.

    This is a fallback for old actions that don't have target info in database.

    Returns: (target_player_id, target_player_name) or (None, None)
    """
    if not action_detail:
        return (None, None)

    # Pattern: "ia dat lui PlayerName(ID)" or "a dat lui PlayerName(ID)"
    match = re.search(
        r"(?:ia|a)\s+dat\s+lui\s+([^(]+)\((\d+)\)", action_detail, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())

    # Pattern: "primit de la PlayerName(ID)"
    match = re.search(
        r"primit\s+(?:de\s+la|de la)\s+([^(]+)\((\d+)\)", action_detail, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())

    return (None, None)


# ============================================================================
# PAGINATION VIEWS
# ============================================================================


class ActionsPaginationView(discord.ui.View):
    """Pagination view for player actions with Previous/Next buttons"""

    def __init__(
        self,
        actions: List[dict],
        player_info: dict,
        days: int,
        author_id: int,
        items_per_page: int = 10,
        original_count: Optional[int] = None,
    ):
        super().__init__(timeout=180)  # 3 minutes timeout
        # Deduplicate actions before storing
        self.actions = deduplicate_actions(actions)
        self.original_count = original_count or len(actions)
        self.player_info = player_info
        self.days = days
        self.author_id = author_id
        self.items_per_page = items_per_page
        self.current_page = 0
        self.message: Optional[discord.Message] = None  # Store message reference
        self.total_pages = (
            (len(self.actions) + items_per_page - 1) // items_per_page
            if self.actions
            else 1
        )

        # Update button states
        self.update_buttons()

    def update_buttons(self):
        """Update button enabled/disabled states based on current page"""
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    def _format_player_ref(self, name: Optional[str], player_id: str) -> str:
        """Format player reference as Name(ID) or just (ID) if name missing"""
        if name and name.strip() and not name.startswith("Player_"):
            return f"{name.strip()}({player_id})"
        return f"({player_id})"

    def _format_action_display(
        self, action: dict, viewing_player_id: str
    ) -> Dict[str, str | List[str]]:
        """Format action for display with emojis and proper categorization.
        
        🔥 ENHANCED: Shows bidirectional actions with full Name(ID) format for all parties.

        Returns dict with 'emoji', 'type_label', 'detail_lines'
        """
        action_type = action.get("action_type", "unknown")
        detail = action.get("action_detail", "No details")
        player_id = str(action.get("player_id", ""))
        target_player_id = str(
            action.get("target_player_id", "") if action.get("target_player_id") else ""
        )
        player_name = action.get("player_name", "")
        target_player_name = action.get("target_player_name", "")
        item_name = action.get("item_name", "")
        item_quantity = action.get("item_quantity")

        # FALLBACK: If target_player_id is NULL, try to extract from action_detail
        if not target_player_id and detail:
            extracted_id, extracted_name = extract_target_from_detail(detail)
            if extracted_id:
                target_player_id = extracted_id
                target_player_name = extracted_name or target_player_name

        # Format player references as Name(ID)
        sender_ref = self._format_player_ref(player_name, player_id) if player_id else "Unknown"
        receiver_ref = self._format_player_ref(target_player_name, target_player_id) if target_player_id else ""

        # Check if viewing player is sender or receiver
        is_sender = player_id == viewing_player_id
        is_receiver = target_player_id == viewing_player_id

        # ============================================================================
        # ITEM TRANSFERS (gave/received)
        # ============================================================================
        if action_type in ("item_given", "item_received") or (
            "ia dat lui" in detail.lower() or "a dat lui" in detail.lower()
        ):
            # Build items string
            if item_name and item_quantity:
                items_str = f"{item_quantity}x {item_name}"
            elif item_name:
                items_str = item_name
            else:
                # Extract items from detail as fallback
                match = re.search(r":\s*(.+?)$", detail)
                items_str = match.group(1).strip() if match else "items"

            if is_sender:
                # Viewing player GAVE to target
                return {
                    "emoji": "📤",
                    "type_label": "ITEM GIVEN",
                    "detail_lines": [
                        f"{sender_ref} i-a dat lui {receiver_ref}: {items_str}",
                    ],
                }
            elif is_receiver:
                # Viewing player RECEIVED from sender
                return {
                    "emoji": "📥",
                    "type_label": "ITEM RECEIVED",
                    "detail_lines": [
                        f"{sender_ref} i-a dat lui {receiver_ref}: {items_str}",
                    ],
                }
            else:
                # Neither sender nor receiver (shouldn't happen but fallback)
                return {
                    "emoji": "📦",
                    "type_label": "ITEM TRANSFER",
                    "detail_lines": [
                        f"{sender_ref} i-a dat lui {receiver_ref}: {items_str}",
                    ],
                }

        # ============================================================================
        # MONEY TRANSFERS
        # ============================================================================
        if action_type == "money_transfer" or "transferat" in detail.lower():
            # Extract amount from detail
            amount_match = re.search(r"([\d.,]+)\s*\$", detail)
            amount = amount_match.group(1) if amount_match else "?"

            if is_sender:
                # Viewing player SENT money
                return {
                    "emoji": "💸",
                    "type_label": "MONEY SENT",
                    "detail_lines": [
                        f"{sender_ref} i-a transferat {amount}$ lui {receiver_ref}",
                    ],
                }
            elif is_receiver:
                # Viewing player RECEIVED money
                return {
                    "emoji": "💰",
                    "type_label": "MONEY RECEIVED",
                    "detail_lines": [
                        f"{sender_ref} i-a transferat {amount}$ lui {receiver_ref}",
                    ],
                }
            else:
                return {
                    "emoji": "💸",
                    "type_label": "MONEY TRANSFER",
                    "detail_lines": [
                        f"{sender_ref} i-a transferat {amount}$ lui {receiver_ref}",
                    ],
                }

        # ============================================================================
        # MONEY DEPOSIT/WITHDRAW
        # ============================================================================
        if action_type == "money_deposit" or "depozitat" in detail.lower():
            return {
                "emoji": "🏦",
                "type_label": "MONEY DEPOSIT",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        if action_type == "money_withdraw" or "retras suma" in detail.lower():
            return {
                "emoji": "🏧",
                "type_label": "MONEY WITHDRAW",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        # ============================================================================
        # CHEST DEPOSITS/WITHDRAWALS
        # ============================================================================
        if action_type == "chest_deposit" or "pus in chest" in detail.lower():
            return {
                "emoji": "📦",
                "type_label": "CHEST DEPOSIT",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        if action_type == "chest_withdraw" or "retras din chest" in detail.lower():
            return {
                "emoji": "📂",
                "type_label": "CHEST WITHDRAW",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        # ============================================================================
        # CONTRACTS / VEHICLE TRANSFERS
        # ============================================================================
        if action_type in ("contract", "vehicle_contract") or "contract" in detail.lower():
            vehicle = item_name or "Vehicle"

            if is_sender:
                # Viewing player GAVE vehicle
                return {
                    "emoji": "📝",
                    "type_label": "CONTRACT GIVEN",
                    "detail_lines": [
                        f"{sender_ref} → {receiver_ref}",
                        f"Vehicle: {vehicle}",
                    ],
                }
            elif is_receiver:
                # Viewing player RECEIVED vehicle
                return {
                    "emoji": "📝",
                    "type_label": "CONTRACT RECEIVED",
                    "detail_lines": [
                        f"{sender_ref} → {receiver_ref}",
                        f"Vehicle: {vehicle}",
                    ],
                }
            else:
                return {
                    "emoji": "📝",
                    "type_label": "CONTRACT",
                    "detail_lines": [
                        f"{sender_ref} → {receiver_ref}",
                        f"Vehicle: {vehicle}",
                    ],
                }

        # ============================================================================
        # TRADES
        # ============================================================================
        if action_type == "trade" or "trade" in detail.lower():
            if is_sender or is_receiver:
                return {
                    "emoji": "🤝",
                    "type_label": "TRADE",
                    "detail_lines": [
                        f"{sender_ref} ↔ {receiver_ref}",
                        f"Detail: {detail}",
                    ],
                }
            return {
                "emoji": "🤝",
                "type_label": "TRADE",
                "detail_lines": [f"Detail: {detail}"],
            }

        # ============================================================================
        # ADMIN ACTIONS (warnings, bans, jails)
        # ============================================================================
        if action_type == "warning_received" or "avertisment" in detail.lower():
            admin_ref = self._format_player_ref(action.get("admin_name"), action.get("admin_id", "")) if action.get("admin_id") else "Admin"
            reason = action.get("reason", "")
            return {
                "emoji": "⚠️",
                "type_label": "WARNING",
                "detail_lines": [
                    f"{sender_ref} a primit avertisment de la {admin_ref}",
                    f"Motiv: {reason}" if reason else "",
                ],
            }

        if action_type == "ban_received":
            admin_ref = self._format_player_ref(action.get("admin_name"), action.get("admin_id", "")) if action.get("admin_id") else "Admin"
            reason = action.get("reason", "")
            return {
                "emoji": "🔨",
                "type_label": "BAN",
                "detail_lines": [
                    f"{sender_ref} a fost banat de {admin_ref}",
                    f"Motiv: {reason}" if reason else "",
                ],
            }

        if action_type == "admin_jail":
            admin_ref = self._format_player_ref(action.get("admin_name"), action.get("admin_id", "")) if action.get("admin_id") else "Admin"
            return {
                "emoji": "🔒",
                "type_label": "ADMIN JAIL",
                "detail_lines": [f"{sender_ref} - {detail}"],
            }

        if action_type == "admin_unjail":
            admin_ref = self._format_player_ref(action.get("admin_name"), action.get("admin_id", "")) if action.get("admin_id") else "Admin"
            return {
                "emoji": "🔓",
                "type_label": "UNJAIL",
                "detail_lines": [f"{sender_ref} - {detail}"],
            }

        if action_type == "admin_unban":
            return {
                "emoji": "✅",
                "type_label": "UNBAN",
                "detail_lines": [f"{sender_ref} - {detail}"],
            }

        if action_type == "kill_character":
            return {
                "emoji": "💀",
                "type_label": "KILL CHARACTER",
                "detail_lines": [f"{sender_ref} - {detail}"],
            }

        # ============================================================================
        # VEHICLE ACTIONS (buy/sell)
        # ============================================================================
        if action_type == "vehicle_bought" or "cumparat" in detail.lower():
            return {
                "emoji": "🚗",
                "type_label": "VEHICLE BOUGHT",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        if action_type == "vehicle_sold" or "vandut" in detail.lower():
            return {
                "emoji": "💰",
                "type_label": "VEHICLE SOLD",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        if action_type == "vehicle_scrapped":
            return {
                "emoji": "🗑️",
                "type_label": "VEHICLE SCRAPPED",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        # ============================================================================
        # PROPERTY ACTIONS
        # ============================================================================
        if action_type == "property_bought":
            return {
                "emoji": "🏠",
                "type_label": "PROPERTY BOUGHT",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        if action_type == "property_sold":
            return {
                "emoji": "🏠",
                "type_label": "PROPERTY SOLD",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        # ============================================================================
        # OTHER SPECIFIC ACTIONS
        # ============================================================================
        if action_type == "gambling_win":
            return {
                "emoji": "🎰",
                "type_label": "GAMBLING WIN",
                "detail_lines": [f"{sender_ref} vs {receiver_ref}: {detail}" if receiver_ref else f"{sender_ref}: {detail}"],
            }

        if action_type == "bank_heist_delivery":
            return {
                "emoji": "💵",
                "type_label": "BANK HEIST",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        if action_type == "license_plate_sale":
            return {
                "emoji": "🔢",
                "type_label": "LICENSE PLATE SALE",
                "detail_lines": [f"{sender_ref} → {receiver_ref}: {detail}" if receiver_ref else f"{sender_ref}: {detail}"],
            }

        if action_type == "house_safe_withdraw":
            return {
                "emoji": "🏠",
                "type_label": "SAFE WITHDRAW",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        if action_type == "house_safe_deposit":
            return {
                "emoji": "🏠",
                "type_label": "SAFE DEPOSIT",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        if action_type == "item_sold":
            return {
                "emoji": "🛒",
                "type_label": "ITEM SOLD",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        if action_type == "faction_kicked":
            return {
                "emoji": "👢",
                "type_label": "FACTION KICKED",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        if action_type == "mute_received":
            return {
                "emoji": "🔇",
                "type_label": "MUTE",
                "detail_lines": [f"{sender_ref}: {detail}"],
            }

        # ============================================================================
        # DEFAULT FALLBACK
        # ============================================================================
        # For unknown/other action types, still try to show player info
        type_label = action_type.upper().replace("_", " ") if action_type else "ACTION"
        if player_id:
            return {
                "emoji": "📋",
                "type_label": type_label,
                "detail_lines": [f"{sender_ref}: {detail}"],
            }
        
        return {
            "emoji": "📋",
            "type_label": type_label,
            "detail_lines": [f"Detail: {detail}"],
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
            timestamp=datetime.now(),
        )

        viewing_player_id = str(self.player_info["player_id"])

        for action in page_actions:
            timestamp = action.get("timestamp")
            count = action.get("count", 1)

            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)
            time_str = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else "Unknown"

            # Get formatted display info
            display = self._format_action_display(action, viewing_player_id)

            # Build field name with emoji and count
            field_name = f"{display['emoji']} {display['type_label']} - {time_str}"
            if count > 1:
                field_name += f" ×{count}"

            # Build field value with detail lines
            value_lines = []
            for i, line in enumerate(display["detail_lines"]):
                if i == 0:
                    value_lines.append(f"├ {line}")
                elif i == len(display["detail_lines"]) - 1:
                    value_lines.append(f"└ {line}")
                else:
                    value_lines.append(f"├ {line}")

            field_value = "\n".join(value_lines)

            embed.add_field(name=field_name, value=field_value, inline=False)

        embed.set_footer(
            text=f"Page {self.current_page + 1}/{self.total_pages} • Use buttons to navigate"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command author can use the buttons"""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can use these buttons!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary, emoji="◀️")
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to previous page"""
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, emoji="▶️")
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to next page"""
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        """Disable buttons when view times out"""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            # Try to edit the message to disable buttons
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass


class FactionPaginationView(discord.ui.View):
    """Pagination view for faction members with Previous/Next buttons"""

    def __init__(
        self,
        members: List[dict],
        faction_name: str,
        author_id: int,
        items_per_page: int = 20,
    ):
        super().__init__(timeout=180)  # 3 minutes timeout
        self.members = members
        self.faction_name = faction_name
        self.author_id = author_id
        self.items_per_page = items_per_page
        self.current_page = 0
        self.message: Optional[discord.Message] = None  # Store message reference
        self.total_pages = (
            (len(self.members) + items_per_page - 1) // items_per_page
            if self.members
            else 1
        )

        # Update button states
        self.update_buttons()

    def update_buttons(self):
        """Update button enabled/disabled states based on current page"""
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        """🔥 FIXED: Build embed showing actual usernames with ACCURATE online status"""
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.members))
        page_members = self.members[start_idx:end_idx]

        # Count online members for description
        online_count = sum(
            1 for m in self.members if m.get("is_currently_online", 0) == 1
        )

        embed = discord.Embed(
            title=f"👥 {self.faction_name}",
            description=f"Showing {start_idx + 1}-{end_idx} of {len(self.members)} member(s) • 🟢 {online_count} online",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        for member in page_members:
            # 🔥 FIX: Use is_online field from JOIN query (returns 1 for online, 0 for offline)
            is_online = member.get("is_currently_online", 0) == 1
            status = "🟢" if is_online else "🔴"
            rank = member.get("faction_rank")

            # Handle NULL, empty, and "null" string values
            if not rank or rank.lower() in ("null", "none", "", "-"):
                rank = "Membru"  # Default rank

            # 🔥 FIXED: Always show username and ID, never just "ID: xxxxx"
            username = member["username"]
            player_id = member["player_id"]

            # Always display as "Username (ID)" format
            display_name = f"{username} ({player_id})"

            value = f"{status} {rank}"
            embed.add_field(name=display_name, value=value, inline=False)

        embed.set_footer(
            text=f"Page {self.current_page + 1}/{self.total_pages} • Use buttons to navigate"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command author can use the buttons"""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can use these buttons!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary, emoji="◀️")
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to previous page"""
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, emoji="▶️")
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to next page"""
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        """Disable buttons when view times out"""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            # Try to edit the message to disable buttons
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass


class OnlinePaginationView(discord.ui.View):
    """🆕 Pagination view for online players with Previous/Next buttons"""

    def __init__(
        self,
        players: List[dict],
        author_id: int,
        faction_map: Dict[str, str],
        items_per_page: int = 20,
    ):
        super().__init__(timeout=180)  # 3 minutes timeout
        self.players = players
        self.author_id = author_id
        self.faction_map = faction_map  # Pre-fetched faction data
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (
            (len(self.players) + items_per_page - 1) // items_per_page
            if self.players
            else 1
        )
        self.message: Optional[discord.Message] = None
        self.update_buttons()

    def update_buttons(self):
        """Update button enabled/disabled states based on current page"""
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        """Build embed for current page"""
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.players))
        page_players = self.players[start_idx:end_idx]

        embed = discord.Embed(
            title="🟢 Online Players",
            description=f"**Total:** {len(self.players)} players online",
            color=discord.Color.green(),
            timestamp=datetime.now(),
        )

        for player in page_players:
            player_name = player.get("player_name", "Unknown")
            player_id = player.get("player_id", "?")

            # Use pre-fetched faction data (no DB access needed)
            faction = self.faction_map.get(str(player_id), "Unknown")

            embed.add_field(
                name=f"🟢 {player_name} ({player_id})",
                value=f"Faction: {faction}",
                inline=True,
            )

        embed.set_footer(
            text=f"Page {self.current_page + 1}/{self.total_pages} • Showing {start_idx + 1}-{end_idx} of {len(self.players)}"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command author can use the buttons"""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can use these buttons!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to previous page"""
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to next page"""
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        """Disable buttons when view times out"""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass


class AdminHistoryPaginationView(discord.ui.View):
    """🆕 Pagination view for admin actions (warnings, bans, jails) across ALL players"""

    # Action type emojis and labels
    TYPE_EMOJIS = {
        "warning_received": "⚠️",
        "ban_received": "🔨",
        "admin_jail": "🔒",
        "admin_unjail": "🔓",
        "admin_unban": "✅",
        "mute_received": "🔇",
        "faction_kicked": "👢",
        "kill_character": "💀",
    }

    def __init__(
        self,
        actions: List[dict],
        author_id: int,
        days: int,
        action_type_filter: Optional[str] = None,
        items_per_page: int = 10,
    ):
        super().__init__(timeout=180)  # 3 minutes timeout
        self.actions = actions
        self.author_id = author_id
        self.days = days
        self.action_type_filter = action_type_filter
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (
            (len(self.actions) + items_per_page - 1) // items_per_page
            if self.actions
            else 1
        )
        self.message: Optional[discord.Message] = None
        self.update_buttons()

    def update_buttons(self):
        """Update button enabled/disabled states based on current page"""
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        """Build embed for current page"""
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.actions))
        page_actions = self.actions[start_idx:end_idx]

        filter_text = f" ({self.action_type_filter.replace('_', ' ').title()})" if self.action_type_filter else ""
        
        embed = discord.Embed(
            title=f"👮 Admin Actions Log{filter_text}",
            description=f"**Total:** {len(self.actions):,} admin actions in last {self.days} days",
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )

        for action in page_actions:
            action_type = action.get("action_type", "unknown")
            emoji = self.TYPE_EMOJIS.get(action_type, "📋")
            type_label = action_type.replace("_", " ").title()
            
            # Get player info (the one who RECEIVED the action)
            player_name = action.get("player_name") or f"ID:{action.get('player_id', '?')}"
            player_id = action.get("player_id", "?")
            
            # Get admin info
            admin_name = action.get("admin_name") or "Unknown Admin"
            
            # Get timestamp
            timestamp = action.get("timestamp")
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp)
                except:
                    timestamp = None
            time_str = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else "?"
            
            # Get reason
            reason = action.get("reason") or action.get("action_detail", "No reason specified")
            if len(reason) > 80:
                reason = reason[:77] + "..."

            embed.add_field(
                name=f"{emoji} {type_label} - {time_str}",
                value=(
                    f"**Player:** {player_name} ({player_id})\n"
                    f"**Admin:** {admin_name}\n"
                    f"**Reason:** {reason}"
                ),
                inline=False,
            )

        embed.set_footer(
            text=f"Page {self.current_page + 1}/{self.total_pages} • Use buttons to navigate"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command author can use the buttons"""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can use these buttons!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to previous page"""
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to next page"""
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        """Disable buttons when view times out"""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass


class PromotionsPaginationView(discord.ui.View):
    """🆕 Pagination view for faction promotions"""

    def __init__(
        self,
        promotions: List[dict],
        author_id: int,
        days: int,
        items_per_page: int = 10,
    ):
        super().__init__(timeout=180)
        self.promotions = promotions
        self.author_id = author_id
        self.days = days
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (
            (len(self.promotions) + items_per_page - 1) // items_per_page
            if self.promotions
            else 1
        )
        self.message: Optional[discord.Message] = None
        self.update_buttons()

    def update_buttons(self):
        """Update button enabled/disabled states based on current page"""
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        """Build embed for current page"""
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.promotions))
        page_promotions = self.promotions[start_idx:end_idx]

        embed = discord.Embed(
            title="📊 Recent Promotions",
            description=f"**Total:** {len(self.promotions)} promotion(s) in last {self.days} days",
            color=discord.Color.gold(),
            timestamp=datetime.now(),
        )

        for promo in page_promotions:
            player_name = promo.get("player_name", "Unknown")
            player_id = promo.get("player_id", "?")
            old_rank = promo.get("old_rank", "None")
            new_rank = promo.get("new_rank", "Unknown")
            faction = promo.get("faction", "Unknown")
            timestamp = promo.get("timestamp")

            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp)
                except:
                    timestamp = None
            time_str = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else "Unknown"

            embed.add_field(
                name=f"⬆️ {player_name} ({player_id})",
                value=(
                    f"**Faction:** {faction}\n"
                    f"**Rank:** {old_rank} → **{new_rank}**\n"
                    f"**Date:** {time_str}"
                ),
                inline=False,
            )

        embed.set_footer(
            text=f"Page {self.current_page + 1}/{self.total_pages} • Use buttons to navigate"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can use these buttons!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass


class BansPaginationView(discord.ui.View):
    """🆕 Pagination view for banned players with played hours and faction"""

    def __init__(
        self,
        bans: List[dict],
        author_id: int,
        show_expired: bool = False,
        items_per_page: int = 10,
    ):
        super().__init__(timeout=180)
        self.bans = bans
        self.author_id = author_id
        self.show_expired = show_expired
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (
            (len(self.bans) + items_per_page - 1) // items_per_page
            if self.bans
            else 1
        )
        self.message: Optional[discord.Message] = None
        self.update_buttons()

    def update_buttons(self):
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.bans))
        page_bans = self.bans[start_idx:end_idx]

        active_count = sum(1 for b in self.bans if b.get("is_active", True))
        
        embed = discord.Embed(
            title="🚫 Banned Players",
            description=f"**Total:** {len(self.bans)} ban(s) • **Active:** {active_count}",
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )

        for ban in page_bans:
            player_name = ban.get("player_name", "Unknown")
            player_id = ban.get("player_id", "?")
            reason = ban.get("reason", "No reason")
            admin = ban.get("admin", "Unknown")
            duration = ban.get("duration", "Unknown")
            is_active = ban.get("is_active", True)
            played_hours = ban.get("played_hours", 0)
            faction = ban.get("faction") or "No faction"
            ban_date = ban.get("ban_date", "?")

            # Truncate long reasons
            if reason and len(reason) > 60:
                reason = reason[:57] + "..."

            status = "🔴 Active" if is_active else "⚪ Expired"
            hours_str = f"{played_hours:.1f}h" if played_hours else "N/A"
            
            embed.add_field(
                name=f"{status} {player_name} ({player_id})",
                value=(
                    f"**Reason:** {reason}\n"
                    f"**Admin:** {admin} • **Duration:** {duration}\n"
                    f"**Ore jucate:** {hours_str} • **Facțiune:** {faction}\n"
                    f"**Ban date:** {ban_date}"
                ),
                inline=False,
            )

        embed.set_footer(
            text=f"Page {self.current_page + 1}/{self.total_pages} • Use buttons to navigate"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can use these buttons!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
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
    # Try as direct ID first
    if isinstance(identifier, int) or (
        isinstance(identifier, str) and identifier.isdigit()
    ):
        player_id = str(identifier)
        profile = await db.get_player_by_exact_id(player_id)

        if not profile:
            # Fetch from website
            profile_obj = await scraper.get_player_profile(player_id)
            if profile_obj:
                profile = {
                    "player_id": profile_obj.player_id,
                    "username": profile_obj.username,
                    "is_online": profile_obj.is_online,
                    "last_seen": profile_obj.last_seen,
                    "faction": profile_obj.faction,
                    "faction_rank": profile_obj.faction_rank,
                    "job": profile_obj.job,
                    "warnings": profile_obj.warnings,
                    "played_hours": profile_obj.played_hours,
                    "age_ic": profile_obj.age_ic,
                }
                await db.save_player_profile(profile)
        return profile

    # Try extracting ID from format "Name (123)"
    id_match = re.search(r"\((\d+)\)", str(identifier))
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
    current = SCAN_STATE["current_id"]
    start = SCAN_STATE["start_id"]
    end = SCAN_STATE["end_id"]
    total = end - start + 1
    scanned = SCAN_STATE["total_scanned"]
    progress_pct = (scanned / total * 100) if total > 0 else 0

    # Calculate speed and ETA
    if SCAN_STATE["start_time"]:
        elapsed = (datetime.now() - SCAN_STATE["start_time"]).total_seconds()
        speed = scanned / elapsed if elapsed > 0 else 0
        remaining = total - scanned
        eta_seconds = remaining / speed if speed > 0 else 0
        elapsed_str = format_time_duration(elapsed)
        eta_str = (
            format_time_duration(eta_seconds) if eta_seconds > 0 else "Calculating..."
        )
    else:
        speed = 0
        elapsed_str = "0s"
        eta_str = "Unknown"

    status_emoji = "⏸️" if SCAN_STATE["is_paused"] else "🔄"
    status_text = "Paused" if SCAN_STATE["is_paused"] else "Running"

    embed = discord.Embed(
        title=f"{status_emoji} Scan Status: {status_text}",
        description=f"**Progress:** {progress_pct:.1f}% ({scanned:,}/{total:,} IDs)\n**Range:** {start:,} → {end:,}",
        color=discord.Color.orange()
        if SCAN_STATE["is_paused"]
        else discord.Color.blue(),
        timestamp=datetime.now(),
    )

    embed.add_field(name="📍 Current Highest ID", value=f"{current:,}", inline=True)
    embed.add_field(name="⚡ Speed", value=f"{speed:.2f} IDs/s", inline=True)
    embed.add_field(name="⏱️ ETA", value=eta_str, inline=True)
    embed.add_field(name="✅ Found", value=f"{SCAN_STATE['found_count']:,}", inline=True)
    embed.add_field(
        name="❌ Errors", value=f"{SCAN_STATE['error_count']:,}", inline=True
    )
    embed.add_field(name="⏲️ Elapsed", value=elapsed_str, inline=True)

    # Worker stats
    config = SCAN_STATE["scan_config"]
    worker_info = f"👷 {config['workers']} workers × {config['max_concurrent_batches']} concurrent batches"
    embed.add_field(name="🔧 Workers", value=worker_info, inline=False)

    # Progress bar
    bar_length = 20
    filled = int(progress_pct / 100 * bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)
    embed.add_field(
        name="Progress Bar", value=f"`{bar}` {progress_pct:.1f}%", inline=False
    )
    embed.set_footer(
        text="🔄 Auto-refreshing every 3 seconds | Use /scan pause or /scan cancel"
    )

    return embed


async def auto_refresh_status():
    """Auto-refresh the status message every 3 seconds"""
    try:
        while SCAN_STATE["is_scanning"]:
            if SCAN_STATE["status_message"]:
                try:
                    embed = build_status_embed()
                    await SCAN_STATE["status_message"].edit(embed=embed)
                except discord.NotFound:
                    SCAN_STATE["status_message"] = None
                    break
                except Exception as e:
                    logger.error(f"Error refreshing status: {e}")
            await asyncio.sleep(3)

        # Scan complete - one final update
        if SCAN_STATE["status_message"]:
            try:
                embed = build_status_embed()
                embed.set_footer(text="✅ Scan complete!")
                embed.color = discord.Color.green()
                await SCAN_STATE["status_message"].edit(embed=embed)
            except:
                pass
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Auto-refresh error: {e}", exc_info=True)


def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in Config.ADMIN_USER_IDS


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
                timestamp=datetime.now(),
            )

            # Background Tasks
            task_status = []
            for task_name, health in TASK_HEALTH.items():
                last_run = health.get("last_run")
                error_count = health.get("error_count", 0)

                if last_run:
                    elapsed = (datetime.now() - last_run).total_seconds()
                    status_icon = (
                        "🟢"
                        if elapsed < 300 and error_count < 5
                        else "🟡"
                        if elapsed < 600
                        else "🔴"
                    )
                    task_status.append(f"{status_icon} **{task_name}**")
                    task_status.append(
                        f"   Last run: {format_time_duration(elapsed)} ago"
                    )
                    task_status.append(f"   Errors: {error_count}")
                else:
                    task_status.append(f"⚪ **{task_name}**")
                    task_status.append(f"   Not started yet")

            embed.add_field(
                name="Background Tasks",
                value="\n".join(task_status) if task_status else "No tasks running",
                inline=False,
            )

            # Memory Usage
            current, peak = tracemalloc.get_traced_memory()
            mem_mb = current / 1024 / 1024
            embed.add_field(
                name="Memory Usage", value=f"Current: {mem_mb:.1f} MB", inline=True
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

    # ========================================================================
    # ADMIN COMMANDS
    # ========================================================================

    @bot.tree.command(
        name="cleanup", description="[ADMIN] Cleanup old database records"
    )
    async def cleanup_db(interaction: discord.Interaction):
        """Cleanup old database records (dry run first)"""

        # Permission check - restrict to server admins
        member = interaction.user
        if (
            not isinstance(member, discord.Member)
            or not member.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "❌ You need Administrator permissions to use this command!",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            # First show what would be deleted (dry run)
            dry_results = await db.cleanup_old_data(dry_run=True)

            embed = discord.Embed(
                title="🧹 Database Cleanup Preview",
                description="These records would be deleted:",
                color=discord.Color.orange(),
            )

            total = 0
            for table, count in dry_results.items():
                embed.add_field(
                    name=f"📋 {table}", value=f"{count:,} records", inline=True
                )
                total += count

            embed.set_footer(
                text=f"Total: {total:,} records • Use '/cleanup confirm' to proceed"
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")

    @bot.tree.command(
        name="cleanup_confirm", description="[ADMIN] Actually perform database cleanup"
    )
    async def cleanup_db_confirm(interaction: discord.Interaction):
        """Actually perform the cleanup"""

        member = interaction.user
        if (
            not isinstance(member, discord.Member)
            or not member.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "❌ You need Administrator permissions!", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            # Perform actual cleanup
            results = await db.cleanup_old_data(dry_run=False)

            embed = discord.Embed(
                title="✅ Database Cleanup Complete",
                description="Successfully deleted old records:",
                color=discord.Color.green(),
            )

            total = 0
            for table, count in results.items():
                embed.add_field(
                    name=f"📋 {table}", value=f"{count:,} deleted", inline=True
                )
                total += count

            embed.set_footer(text=f"Total deleted: {total:,} records")

            await interaction.followup.send(embed=embed)
            logger.info(
                f"✅ Database cleanup performed by {interaction.user}: {total:,} records deleted"
            )

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")
            logger.error(f"Cleanup error: {e}", exc_info=True)

    @bot.tree.command(name="memory", description="Show bot memory usage and statistics")
    async def memory_stats(interaction: discord.Interaction):
        """Display memory usage statistics"""
        try:
            import tracemalloc
            import psutil
            import os

            # Memory tracing
            current, peak = tracemalloc.get_traced_memory()

            # System memory
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            sys_mem = psutil.virtual_memory()

            embed = discord.Embed(
                title="📊 Bot Memory Statistics",
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )

            embed.add_field(
                name="🔍 Traced Memory",
                value=f"Current: {current / 1024**2:.2f} MB\nPeak: {peak / 1024**2:.2f} MB",
                inline=True,
            )

            embed.add_field(
                name="💾 Process Memory",
                value=f"RSS: {mem_info.rss / 1024**2:.2f} MB\nVMS: {mem_info.vms / 1024**2:.2f} MB",
                inline=True,
            )

            embed.add_field(
                name="🖥️ System Memory",
                value=f"Used: {sys_mem.percent}%\nAvailable: {sys_mem.available / 1024**3:.2f} GB",
                inline=True,
            )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error getting memory stats: {e}", ephemeral=True
            )

    @bot.tree.command(
        name="cleanup_old_data",
        description="Remove old data based on retention policy (Admin only)",
    )
    @app_commands.describe(
        dry_run="Preview without deleting (default: true)",
        confirm="Must be true to actually delete (default: false)",
    )
    @app_commands.checks.cooldown(1, 300)
    async def cleanup_command(
        interaction: discord.Interaction,
        dry_run: Optional[bool] = True,
        confirm: Optional[bool] = False,
    ):
        """Remove old data based on retention policy"""
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nThis command is restricted to bot administrators.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            # Safety check
            if not dry_run and not confirm:
                await interaction.followup.send(
                    "⚠️ **Safety Check**\n\nTo actually delete data, you must set both `dry_run=false` AND `confirm=true`"
                )
                return

            # Perform cleanup
            results = await db.cleanup_old_data(dry_run=dry_run)

            if dry_run:
                embed = discord.Embed(
                    title="🗑️ DRY RUN - Data Cleanup Preview",
                    description="No data was deleted. Set `dry_run=false confirm=true` to execute.",
                    color=discord.Color.orange(),
                    timestamp=datetime.now(),
                )
            else:
                embed = discord.Embed(
                    title="🗑️ CLEANUP EXECUTED - Data Cleanup",
                    description="✅ Data has been deleted.",
                    color=discord.Color.green(),
                    timestamp=datetime.now(),
                )

            # Show what would be/was deleted
            for category, count in results.items():
                embed.add_field(name=category, value=f"{count:,} records", inline=True)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in cleanup command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(
        name="backup_database", description="Create database backup (Admin only)"
    )
    @app_commands.checks.cooldown(1, 300)
    async def backup_command(interaction: discord.Interaction):
        """Create database backup"""
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nThis command is restricted to bot administrators.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            import shutil
            from pathlib import Path

            # Create backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = Path("backups")
            backup_dir.mkdir(exist_ok=True)

            backup_path = backup_dir / f"pro4kings_backup_{timestamp}.db"
            shutil.copy2(db.db_path, backup_path)

            # Get file size
            file_size = backup_path.stat().st_size / (1024 * 1024)  # MB

            embed = discord.Embed(
                title="✅ Database Backup Created",
                color=discord.Color.green(),
                timestamp=datetime.now(),
            )

            embed.add_field(name="Backup File", value=backup_path.name, inline=False)
            embed.add_field(name="Size", value=f"{file_size:.2f} MB", inline=True)
            embed.add_field(name="Location", value=str(backup_dir), inline=True)

            # Count total backups
            backup_count = len(list(backup_dir.glob("*.db")))
            embed.set_footer(text=f"Total backups: {backup_count}")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in backup command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # SCAN MANAGEMENT COMMANDS - WITH CONCURRENT WORKERS
    # ========================================================================

    scan_group = app_commands.Group(name="scan", description="Database scan management")

    @scan_group.command(
        name="start", description="Start initial database scan with concurrent workers"
    )
    @app_commands.describe(
        start_id="Starting player ID (default: 1)",
        end_id="Ending player ID (default: 100000)",
    )
    async def scan_start(
        interaction: discord.Interaction, start_id: int = 1, end_id: int = 100000
    ):
        """Start database scan with true concurrent workers"""
        await interaction.response.defer()

        try:
            if SCAN_STATE["is_scanning"]:
                await interaction.followup.send(
                    "❌ **A scan is already in progress!** Use `/scan status` to check progress or `/scan cancel` to stop it."
                )
                return

            if start_id < 1 or end_id < start_id:
                await interaction.followup.send(
                    "❌ **Invalid ID range!** Start must be >= 1 and end must be >= start."
                )
                return

            # Initialize scan state
            SCAN_STATE["is_scanning"] = True
            SCAN_STATE["is_paused"] = False
            SCAN_STATE["start_id"] = start_id
            SCAN_STATE["end_id"] = end_id
            SCAN_STATE["current_id"] = start_id
            SCAN_STATE["found_count"] = 0
            SCAN_STATE["error_count"] = 0
            SCAN_STATE["total_scanned"] = 0
            SCAN_STATE["start_time"] = datetime.now()
            SCAN_STATE["status_message"] = None
            SCAN_STATE["worker_stats"] = {}
            SCAN_STATE["last_speed_update"] = datetime.now()
            SCAN_STATE["current_speed"] = 0.0

            # Concurrent worker implementation
            async def run_scan_with_workers():
                try:
                    config = SCAN_STATE["scan_config"]
                    workers = config["workers"]
                    batch_size = config["batch_size"]
                    max_concurrent_batches = config["max_concurrent_batches"]

                    logger.info(
                        f"🔧 Initializing scraper with {workers} max concurrent for scan..."
                    )
                    scraper = await scraper_getter(max_concurrent=workers)
                    logger.info(
                        f"✅ Scraper ready with {scraper.max_concurrent} workers"
                    )

                    total_ids = end_id - start_id + 1
                    logger.info(
                        f"🚀 Starting CONCURRENT scan: IDs {start_id}-{end_id} ({total_ids:,} total)"
                    )
                    logger.info(
                        f"⚙️ Config: batch={batch_size}, workers={workers}, concurrent_batches={max_concurrent_batches}, delay={config['wave_delay']}s"
                    )

                    # Create all batches upfront
                    all_player_ids = [str(i) for i in range(start_id, end_id + 1)]
                    all_batches = [
                        all_player_ids[i : i + batch_size]
                        for i in range(0, len(all_player_ids), batch_size)
                    ]
                    logger.info(
                        f"📦 Created {len(all_batches)} batches of {batch_size} IDs each"
                    )

                    # Process batches with concurrent workers
                    batch_queue = asyncio.Queue()
                    for batch in all_batches:
                        await batch_queue.put(batch)

                    # Worker function
                    async def worker(worker_id: int):
                        worker_found = 0
                        worker_errors = 0
                        worker_scanned = 0

                        while not batch_queue.empty():
                            # Check pause/cancel
                            while SCAN_STATE["is_paused"]:
                                await asyncio.sleep(1)

                            if not SCAN_STATE["is_scanning"]:
                                break

                            try:
                                batch_ids = await asyncio.wait_for(
                                    batch_queue.get(), timeout=1.0
                                )
                            except asyncio.TimeoutError:
                                continue

                            try:
                                # Fetch profiles for this batch
                                profiles = await scraper.batch_get_profiles(batch_ids)

                                # Save profiles to database
                                for profile in profiles:
                                    if profile:
                                        profile_dict = {
                                            "player_id": profile.player_id,
                                            "player_name": profile.username,
                                            "is_online": profile.is_online,
                                            "last_connection": profile.last_seen,
                                            "faction": profile.faction,
                                            "faction_rank": profile.faction_rank,
                                            "job": profile.job,
                                            "warns": profile.warnings,
                                            "played_hours": profile.played_hours,
                                            "age_ic": profile.age_ic,
                                        }
                                        await db.save_player_profile(profile_dict)
                                        worker_found += 1
                                        SCAN_STATE["found_count"] += 1

                                worker_scanned += len(batch_ids)
                                SCAN_STATE["total_scanned"] += len(batch_ids)

                                # Update current_id to highest processed
                                max_id = max([int(pid) for pid in batch_ids])
                                if max_id > SCAN_STATE["current_id"]:
                                    SCAN_STATE["current_id"] = max_id

                                # Log progress periodically
                                if worker_scanned % (batch_size * 5) == 0:
                                    logger.info(
                                        f"Worker {worker_id}: Scanned {worker_scanned:,} | Found {worker_found:,} | Errors {worker_errors}"
                                    )

                                # Add wave delay
                                await asyncio.sleep(config["wave_delay"])

                            except Exception as e:
                                logger.error(f"Worker {worker_id} batch error: {e}")
                                worker_errors += len(batch_ids)
                                SCAN_STATE["error_count"] += len(batch_ids)
                                SCAN_STATE["total_scanned"] += len(batch_ids)

                        # Worker complete
                        SCAN_STATE["worker_stats"][worker_id] = {
                            "scanned": worker_scanned,
                            "found": worker_found,
                            "errors": worker_errors,
                        }
                        logger.info(
                            f"✅ Worker {worker_id} complete: {worker_scanned:,} scanned, {worker_found:,} found, {worker_errors} errors"
                        )

                    # Start concurrent workers
                    worker_tasks = [
                        asyncio.create_task(worker(i))
                        for i in range(max_concurrent_batches)
                    ]

                    logger.info(
                        f"👷 Started {max_concurrent_batches} concurrent workers"
                    )

                    # Wait for all workers to complete
                    await asyncio.gather(*worker_tasks)

                    # Scan complete
                    SCAN_STATE["is_scanning"] = False
                    elapsed = (
                        datetime.now() - SCAN_STATE["start_time"]
                    ).total_seconds()
                    avg_speed = (
                        SCAN_STATE["total_scanned"] / elapsed if elapsed > 0 else 0
                    )
                    logger.info(
                        f"✅ Scan complete! Found {SCAN_STATE['found_count']:,} players in {format_time_duration(elapsed)} (avg: {avg_speed:.2f} IDs/s)"
                    )

                except Exception as e:
                    logger.error(f"❌ Scan error: {e}", exc_info=True)
                    SCAN_STATE["is_scanning"] = False
                    SCAN_STATE["error_count"] += 1

            # Start scan in background
            SCAN_STATE["scan_task"] = asyncio.create_task(run_scan_with_workers())

            # Wait a moment to ensure scan task started
            await asyncio.sleep(0.5)

            # Verify scan is actually running
            if not SCAN_STATE["is_scanning"]:
                await interaction.followup.send(
                    "❌ **Failed to start scan!** Check bot logs for errors."
                )
                return

            # Show expected speed based on current settings
            config = SCAN_STATE["scan_config"]
            # Calculate expected speed with concurrent workers
            expected_speed_per_worker = config["batch_size"] / (
                config["wave_delay"] + 0.5
            )
            expected_total_speed = (
                expected_speed_per_worker * config["max_concurrent_batches"]
            )

            embed = discord.Embed(
                title="🚀 Concurrent Database Scan Started",
                description=f"Scanning player IDs {start_id:,} to {end_id:,}\n\nUsing **{config['max_concurrent_batches']} concurrent workers** for maximum speed!\n\nUse `/scan status` to monitor progress with **real-time auto-refresh**!",
                color=discord.Color.green(),
                timestamp=datetime.now(),
            )

            embed.add_field(
                name="⚙️ Batch Size", value=f"{config['batch_size']} IDs", inline=True
            )
            embed.add_field(
                name="👷 Max Workers", value=str(config["workers"]), inline=True
            )
            embed.add_field(
                name="🔀 Concurrent Batches",
                value=str(config["max_concurrent_batches"]),
                inline=True,
            )
            embed.add_field(
                name="⏱️ Wave Delay", value=f"{config['wave_delay']}s", inline=True
            )
            embed.add_field(
                name="⚡ Expected Speed",
                value=f"~{expected_total_speed:.1f} IDs/s",
                inline=True,
            )
            embed.add_field(
                name="📊 Total IDs", value=f"{end_id - start_id + 1:,}", inline=True
            )

            eta = (
                (end_id - start_id + 1) / expected_total_speed
                if expected_total_speed > 0
                else 0
            )
            embed.add_field(
                name="🕐 Est. Time", value=format_time_duration(eta), inline=True
            )
            embed.set_footer(text="Tip: Use /scanconfig to adjust speed settings")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error starting scan: {e}", exc_info=True)
            SCAN_STATE["is_scanning"] = False
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @scan_group.command(
        name="status", description="View real-time scan progress (auto-refreshing)"
    )
    async def scan_status(interaction: discord.Interaction):
        """Check scan status with auto-refresh"""
        await interaction.response.defer()

        try:
            if not SCAN_STATE["is_scanning"] and not SCAN_STATE["is_paused"]:
                await interaction.followup.send(
                    "ℹ️ **No scan in progress.** Use `/scan start <start_id> <end_id>` to begin scanning."
                )
                return

            # Build and send initial embed
            embed = build_status_embed()
            message = await interaction.followup.send(embed=embed)

            # Store message and start auto-refresh
            SCAN_STATE["status_message"] = message

            # Cancel old refresh task if exists
            if SCAN_STATE["status_task"] and not SCAN_STATE["status_task"].done():
                SCAN_STATE["status_task"].cancel()

            # Start new refresh task
            SCAN_STATE["status_task"] = asyncio.create_task(auto_refresh_status())

        except Exception as e:
            logger.error(f"Error checking scan status: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @scan_group.command(name="pause", description="Pause ongoing scan")
    async def scan_pause(interaction: discord.Interaction):
        """Pause scan"""
        await interaction.response.defer()

        try:
            if not SCAN_STATE["is_scanning"]:
                await interaction.followup.send("❌ **No scan in progress!**")
                return

            if SCAN_STATE["is_paused"]:
                await interaction.followup.send(
                    "⏸️ **Scan is already paused!** Use `/scan resume` to continue."
                )
                return

            SCAN_STATE["is_paused"] = True
            await interaction.followup.send(
                "⏸️ **Scan paused!** Use `/scan resume` to continue or `/scan cancel` to stop."
            )

        except Exception as e:
            logger.error(f"Error pausing scan: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @scan_group.command(name="resume", description="Resume paused scan")
    async def scan_resume(interaction: discord.Interaction):
        """Resume scan"""
        await interaction.response.defer()

        try:
            if not SCAN_STATE["is_scanning"]:
                await interaction.followup.send("❌ **No scan in progress!**")
                return

            if not SCAN_STATE["is_paused"]:
                await interaction.followup.send("ℹ️ **Scan is already running!**")
                return

            SCAN_STATE["is_paused"] = False
            await interaction.followup.send(
                "▶️ **Scan resumed!** Use `/scan status` to check progress."
            )

        except Exception as e:
            logger.error(f"Error resuming scan: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @scan_group.command(name="cancel", description="Cancel ongoing scan")
    async def scan_cancel(interaction: discord.Interaction):
        """Cancel scan"""
        await interaction.response.defer()

        try:
            if not SCAN_STATE["is_scanning"]:
                await interaction.followup.send("❌ **No scan in progress!**")
                return

            SCAN_STATE["is_scanning"] = False
            SCAN_STATE["is_paused"] = False

            if SCAN_STATE["scan_task"]:
                SCAN_STATE["scan_task"].cancel()
            if SCAN_STATE["status_task"]:
                SCAN_STATE["status_task"].cancel()

            embed = discord.Embed(
                title="🛑 Scan Cancelled",
                description=f"Scan stopped at ID {SCAN_STATE['current_id']:,}",
                color=discord.Color.red(),
                timestamp=datetime.now(),
            )

            embed.add_field(
                name="✅ Found",
                value=f"{SCAN_STATE['found_count']:,} players",
                inline=True,
            )
            embed.add_field(
                name="❌ Errors", value=f"{SCAN_STATE['error_count']:,}", inline=True
            )
            embed.add_field(
                name="📊 Total Scanned",
                value=f"{SCAN_STATE['total_scanned']:,}",
                inline=True,
            )

            if SCAN_STATE["start_time"]:
                elapsed = (datetime.now() - SCAN_STATE["start_time"]).total_seconds()
                avg_speed = SCAN_STATE["total_scanned"] / elapsed if elapsed > 0 else 0
                embed.add_field(
                    name="⚡ Avg Speed", value=f"{avg_speed:.2f} IDs/s", inline=True
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error cancelling scan: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    bot.tree.add_command(scan_group)

    # ========================================================================
    # SCAN CONFIG COMMAND - ENHANCED FOR CONCURRENT WORKERS
    # ========================================================================

    @bot.tree.command(
        name="scanconfig", description="View or modify scan configuration"
    )
    @app_commands.describe(
        batch_size="Number of IDs to scan per batch (10-100)",
        workers="Number of max concurrent HTTP requests (10-50)",
        wave_delay="Delay between batches in seconds (0.01-1.0)",
        concurrent_batches="Number of batches to process simultaneously (1-10)",
    )
    async def scanconfig_command(
        interaction: discord.Interaction,
        batch_size: Optional[int] = None,
        workers: Optional[int] = None,
        wave_delay: Optional[float] = None,
        concurrent_batches: Optional[int] = None,
    ):
        """Configure scan parameters for concurrent processing"""
        await interaction.response.defer()

        try:
            # Update config if parameters provided
            updated = []

            if batch_size is not None:
                if 10 <= batch_size <= 100:
                    SCAN_STATE["scan_config"]["batch_size"] = batch_size
                    updated.append(f"Batch size: {batch_size}")
                else:
                    await interaction.followup.send(
                        "❌ **Batch size must be between 10 and 100!**"
                    )
                    return

            if workers is not None:
                if 1 <= workers <= 50:
                    SCAN_STATE["scan_config"]["workers"] = workers
                    updated.append(f"Workers: {workers}")
                else:
                    await interaction.followup.send(
                        "❌ **Workers must be between 1 and 50!**"
                    )
                    return

            if wave_delay is not None:
                if 0.01 <= wave_delay <= 1.0:
                    SCAN_STATE["scan_config"]["wave_delay"] = wave_delay
                    updated.append(f"Wave delay: {wave_delay}s")
                else:
                    await interaction.followup.send(
                        "❌ **Wave delay must be between 0.01 and 1.0 seconds!**"
                    )
                    return

            if concurrent_batches is not None:
                if 1 <= concurrent_batches <= 10:
                    SCAN_STATE["scan_config"][
                        "max_concurrent_batches"
                    ] = concurrent_batches
                    updated.append(f"Concurrent batches: {concurrent_batches}")
                else:
                    await interaction.followup.send(
                        "❌ **Concurrent batches must be between 1 and 10!**"
                    )
                    return

            # Create embed
            embed = discord.Embed(
                title="⚙️ Scan Configuration - Concurrent Worker System",
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )

            if updated:
                embed.description = (
                    "**✅ Updated:** "
                    + ", ".join(updated)
                    + "\n\n⚠️ *Changes apply to NEW scans only!*"
                )
            else:
                embed.description = "**Current Configuration:**"

            config = SCAN_STATE["scan_config"]
            embed.add_field(
                name="📦 Batch Size",
                value=f"{config['batch_size']} IDs per batch",
                inline=True,
            )
            embed.add_field(
                name="👷 Max Workers",
                value=f"{config['workers']} HTTP requests",
                inline=True,
            )
            embed.add_field(
                name="🔀 Concurrent Batches",
                value=f"{config['max_concurrent_batches']} workers",
                inline=True,
            )
            embed.add_field(
                name="⏱️ Wave Delay",
                value=f"{config['wave_delay']}s per worker",
                inline=True,
            )

            # Calculate expected speed with concurrent workers
            speed_per_worker = config["batch_size"] / (config["wave_delay"] + 0.5)
            total_speed = speed_per_worker * config["max_concurrent_batches"]
            embed.add_field(
                name="⚡ Expected Speed",
                value=f"~{total_speed:.1f} IDs/second",
                inline=True,
            )

            # Add preset recommendations
            embed.add_field(
                name="📋 Recommended Presets",
                value=(
                    "**Ultra Fast:** `/scanconfig 100 30 0.05 8` (~150 IDs/s)\n"
                    "**Aggressive:** `/scanconfig 50 20 0.05 5` (~80 IDs/s)\n"
                    "**Balanced:** `/scanconfig 50 15 0.1 3` (~40 IDs/s)\n"
                    "**Safe:** `/scanconfig 30 10 0.2 2` (~15 IDs/s)"
                ),
                inline=False,
            )

            embed.set_footer(
                text="💡 More concurrent batches = faster scanning | Adjust if you get rate limited"
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in scanconfig command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    logger.info(
        "✅ All slash commands registered successfully with concurrent worker support"
    )

    @bot.tree.command(name="config", description="Display current configuration")
    @app_commands.checks.cooldown(1, 30)
    async def config_command(interaction: discord.Interaction):
        """Display current configuration"""
        await interaction.response.defer()

        try:
            embed = discord.Embed(
                title="⚙️ Bot Configuration",
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )

            # Database
            embed.add_field(
                name="📁 Database", value=f"Path: `{db.db_path}`", inline=False
            )

            # Task Intervals
            embed.add_field(
                name="⏱️ Task Intervals",
                value="• Actions: 30s\n• Online Players: 60s\n• Profile Updates: 2min\n• Ban Check: 1h",
                inline=False,
            )

            # Scraper Settings
            scraper = await scraper_getter()
            embed.add_field(
                name="🌐 Scraper",
                value=f"• Workers: {scraper.max_concurrent}\n• Rate: Adaptive",
                inline=False,
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
                timestamp=datetime.now(),
            )

            embed.add_field(
                name="👥 Total Players",
                value=f"{stats.get('total_players', 0):,}",
                inline=True,
            )
            embed.add_field(
                name="📝 Total Actions",
                value=f"{stats.get('total_actions', 0):,}",
                inline=True,
            )

            # 🔥 FIXED: Changed from "Online Now" to "Online Last 24h" and uses accurate count
            online_24h_count = await db.get_online_players_last_24h_count()
            embed.add_field(
                name="🟢 Online Last 24h", value=f"{online_24h_count:,}", inline=True
            )

            # Recent Activity
            actions_24h = await db.get_actions_count_last_24h()
            embed.add_field(
                name="📈 Actions (24h)", value=f"{actions_24h:,}", inline=True
            )

            logins_today = await db.get_logins_count_today()
            embed.add_field(
                name="🔑 Logins Today", value=f"{logins_today:,}", inline=True
            )

            banned_count = await db.get_active_bans_count()
            embed.add_field(
                name="🚫 Active Bans", value=f"{banned_count:,}", inline=True
            )

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
                await interaction.followup.send(
                    "❌ Search query must be at least 2 characters long!"
                )
                return

            players = await db.search_player_by_name(query)

            if not players:
                await interaction.followup.send(
                    f"🔍 **No Results**\n\nNo players found matching: `{query}`"
                )
                return

            # Build results embed
            embed = discord.Embed(
                title=f"🔍 Search Results for '{query}'",
                description=f"Found {len(players)} player(s)",
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )

            # Show up to 10 results
            for i, player in enumerate(players[:10]):
                status = "🟢 Online" if player.get("is_online") else "⚪ Offline"
                faction = player.get("faction") or "No faction"

                value = f"{status}\n├ Faction: {faction}"
                embed.add_field(
                    name=f"{player['username']} (ID: {player['player_id']})",
                    value=value,
                    inline=False,
                )

            if len(players) > 10:
                embed.set_footer(text=f"Showing 10 of {len(players)} results")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in search command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(name="actions", description="Get player's recent actions")
    @app_commands.describe(
        identifier="Player ID or name", days="Days to look back (default: 7, max: 30)"
    )
    @app_commands.checks.cooldown(1, 30)
    async def actions_command(
        interaction: discord.Interaction, identifier: str, days: int = 7
    ):
        """Get player's recent actions with pagination and deduplication"""
        await interaction.response.defer()

        try:
            if days < 1 or days > 30:
                await interaction.followup.send("❌ Days must be between 1 and 30!")
                return

            scraper = await scraper_getter()
            player = await resolve_player_info(db, scraper, identifier)

            if not player:
                await interaction.followup.send(
                    f"🔍 **Not Found**\n\nNo player found with identifier: `{identifier}`"
                )
                return

            actions = await db.get_player_actions(player["player_id"], days)

            if not actions:
                await interaction.followup.send(
                    f"📝 **No Actions**\n\n{player['username']} has no recorded actions in the last {days} days."
                )
                return

            # Store original count before deduplication
            original_count = len(actions)

            # Create pagination view (will deduplicate internally)
            view = ActionsPaginationView(
                actions=actions,
                player_info=player,
                days=days,
                author_id=interaction.user.id,
                original_count=original_count,
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
        identifier="Player ID or name", days="Days to look back (default: 7, max: 30)"
    )
    @app_commands.checks.cooldown(1, 10)
    async def sessions_command(
        interaction: discord.Interaction, identifier: str, days: int = 7
    ):
        """View player's gaming sessions"""
        await interaction.response.defer()

        try:
            if days < 1 or days > 30:
                await interaction.followup.send("❌ Days must be between 1 and 30!")
                return

            scraper = await scraper_getter()
            player = await resolve_player_info(db, scraper, identifier)

            if not player:
                await interaction.followup.send(
                    f"🔍 **Not Found**\n\nNo player found with identifier: `{identifier}`"
                )
                return

            sessions = await db.get_player_sessions(player["player_id"], days)

            if not sessions:
                await interaction.followup.send(
                    f"📊 **No Sessions**\n\n{player['username']} has no recorded sessions in the last {days} days."
                )
                return

            # Calculate total playtime
            total_seconds = sum(
                s.get("session_duration_seconds", 0)
                for s in sessions
                if s.get("session_duration_seconds")
            )
            total_hours = total_seconds / 3600

            embed = discord.Embed(
                title=f"📊 Sessions for {player['username']}",
                description=f"Last {days} days • {len(sessions)} sessions • {total_hours:.1f}h total",
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )

            # Show up to 10 most recent sessions
            for session in sessions[:10]:
                login_time = session.get("login_time")
                logout_time = session.get("logout_time")
                duration = session.get("session_duration_seconds", 0)

                if isinstance(login_time, str):
                    login_time = datetime.fromisoformat(login_time)
                if isinstance(logout_time, str):
                    logout_time = datetime.fromisoformat(logout_time)

                login_str = (
                    login_time.strftime("%Y-%m-%d %H:%M") if login_time else "Unknown"
                )
                logout_str = (
                    logout_time.strftime("%H:%M") if logout_time else "Still online"
                )
                duration_str = format_time_duration(duration) if duration else "N/A"

                value = f"Login: {login_str}\nLogout: {logout_str}\nDuration: {duration_str}"
                embed.add_field(
                    name=f"Session {len(sessions) - sessions.index(session)}",
                    value=value,
                    inline=True,
                )

            if len(sessions) > 10:
                embed.set_footer(text=f"Showing 10 of {len(sessions)} sessions")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in sessions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(
        name="rank_history", description="View player's faction rank history"
    )
    @app_commands.describe(identifier="Player ID or name")
    @app_commands.checks.cooldown(1, 10)
    async def rank_history_command(interaction: discord.Interaction, identifier: str):
        """View player's faction rank history"""
        await interaction.response.defer()

        try:
            scraper = await scraper_getter()
            player = await resolve_player_info(db, scraper, identifier)

            if not player:
                await interaction.followup.send(
                    f"🔍 **Not Found**\n\nNo player found with identifier: `{identifier}`"
                )
                return

            rank_history = await db.get_player_rank_history(player["player_id"])

            if not rank_history:
                await interaction.followup.send(
                    f"📊 **No Rank History**\n\n{player['username']} has no recorded rank changes."
                )
                return

            embed = discord.Embed(
                title=f"📊 Rank History for {player['username']}",
                description=f"{len(rank_history)} rank change(s)",
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )

            for rank in rank_history:
                faction = rank.get("faction", "Unknown")
                rank_name = rank.get("rank_name", "Unknown")
                obtained = rank.get("rank_obtained")
                lost = rank.get("rank_lost")
                is_current = rank.get("is_current", False)

                if isinstance(obtained, str):
                    obtained = datetime.fromisoformat(obtained)
                if isinstance(lost, str):
                    lost = datetime.fromisoformat(lost)

                obtained_str = obtained.strftime("%Y-%m-%d") if obtained else "Unknown"

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

    @bot.tree.command(
        name="faction",
        description="🔥 FIXED: List all members of a faction (auto-refreshes placeholder usernames)",
    )
    @app_commands.describe(faction_name="Name of faction")
    @app_commands.checks.cooldown(1, 30)
    async def faction_command(interaction: discord.Interaction, faction_name: str):
        """🔥 FIXED: List all members of a faction - auto-refreshes placeholder usernames AND missing ranks"""
        await interaction.response.defer()

        try:
            members = await db.get_faction_members(faction_name)

            if not members:
                await interaction.followup.send(
                    f"🔍 **Not Found**\n\nNo members found in faction: `{faction_name}`"
                )
                return

            # 🔥 ENHANCED: Identify members needing refresh (placeholder usernames OR missing ranks)
            members_needing_refresh = []
            for member in members:
                username = member.get("username", "")
                rank = member.get("faction_rank")

                # Refresh if username is placeholder OR rank is missing
                needs_refresh = False

                if is_placeholder_username(username):
                    logger.debug(
                        f"Member {member['player_id']} has placeholder username: {username}"
                    )
                    needs_refresh = True

                if not rank or rank.lower() in ("null", "none", "", "-", "n/a"):
                    logger.debug(f"Member {member['player_id']} has missing rank")
                    needs_refresh = True

                if needs_refresh:
                    members_needing_refresh.append(member["player_id"])

            # If there are members needing refresh, refresh them
            if members_needing_refresh:
                logger.info(
                    f"🔄 Refreshing {len(members_needing_refresh)} members in {faction_name} (placeholder usernames or missing ranks)"
                )

                scraper = await scraper_getter()

                # Batch fetch fresh profiles
                fresh_profiles = await scraper.batch_get_profiles(
                    members_needing_refresh[:100]
                )  # Limit to 100 to avoid timeout

                # Save updated profiles to database
                refresh_count = 0
                for profile in fresh_profiles:
                    if profile:
                        profile_dict = {
                            "player_id": profile.player_id,
                            "player_name": profile.username,
                            "is_online": profile.is_online,
                            "last_connection": profile.last_seen,
                            "faction": profile.faction,
                            "faction_rank": profile.faction_rank,
                            "job": profile.job,
                            "warns": profile.warnings,
                            "played_hours": profile.played_hours,
                            "age_ic": profile.age_ic,
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
                author_id=interaction.user.id,
            )

            # Send initial page with pagination buttons
            embed = view.build_embed()
            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message  # Store message reference for timeout handling

        except Exception as e:
            logger.error(f"Error in faction command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(
        name="factionlist",
        description="🔥 FIXED: List all factions with currently online members only",
    )
    @app_commands.checks.cooldown(1, 30)
    async def faction_list_command(interaction: discord.Interaction):
        """🔥 FIXED: List all factions with member counts and CURRENT online counts"""
        await interaction.response.defer()

        try:
            factions = await db.get_all_factions_with_counts()

            if not factions:
                await interaction.followup.send(
                    "📊 **No Factions**\n\nNo factions found in the database."
                )
                return

            embed = discord.Embed(
                title="📋 All Factions",
                description=f"Total: {len(factions)} faction(s)\n💡 Online count shows currently online members",
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )

            # Show up to 25 factions
            for i, faction in enumerate(factions[:25], 1):
                faction_name = faction["faction_name"]
                member_count = faction["member_count"]
                online_count = faction.get("online_count", 0)

                # 🔥 FIXED: Now shows accurate online count from online_players table
                value = f"👥 {member_count} member(s) • 🟢 {online_count} online now"
                embed.add_field(name=f"{i}. {faction_name}", value=value, inline=False)

            if len(factions) > 25:
                embed.set_footer(text=f"Showing top 25 of {len(factions)} factions")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in faction list command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(name="promotions", description="Recent faction promotions with pagination")
    @app_commands.describe(days="Days to look back (default: 7, max: 30)")
    @app_commands.checks.cooldown(1, 30)
    async def promotions_command(interaction: discord.Interaction, days: int = 7):
        """Recent faction promotions with pagination"""
        await interaction.response.defer()

        try:
            if days < 1 or days > 30:
                await interaction.followup.send("❌ Days must be between 1 and 30!")
                return

            promotions = await db.get_recent_promotions(days)

            if not promotions:
                await interaction.followup.send(
                    f"📊 **No Promotions**\n\nNo promotions recorded in the last {days} days."
                )
                return

            # Create pagination view
            view = PromotionsPaginationView(
                promotions=promotions,
                author_id=interaction.user.id,
                days=days,
            )

            # Send initial page with pagination buttons
            embed = view.build_embed()
            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message  # Store message reference for timeout handling

        except Exception as e:
            logger.error(f"Error in promotions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # BAN COMMANDS
    # ========================================================================

    @bot.tree.command(name="bans", description="View banned players with pagination")
    @app_commands.describe(
        show_expired="Include expired bans (default: false)",
        refresh="Fetch fresh ban data from website (default: false)"
    )
    @app_commands.checks.cooldown(1, 30)
    async def bans_command(
        interaction: discord.Interaction, 
        show_expired: Optional[bool] = False,
        refresh: Optional[bool] = False
    ):
        """View banned players with pagination, played hours, and faction info"""
        await interaction.response.defer()

        try:
            # Optionally refresh ban data from website
            if refresh:
                await interaction.followup.send("🔄 Fetching fresh ban data from all pages...")
                scraper = await scraper_getter()
                fresh_bans = await scraper.get_banned_players_all_pages()
                
                # Save to database
                for ban_data in fresh_bans:
                    await db.save_banned_player(ban_data)
                
                logger.info(f"✅ Refreshed {len(fresh_bans)} bans from website")

            bans = await db.get_banned_players_with_details(show_expired)

            if not bans:
                await interaction.followup.send(
                    "📊 **No Bans**\n\nNo banned players found."
                )
                return

            # Create pagination view
            view = BansPaginationView(
                bans=bans,
                author_id=interaction.user.id,
                show_expired=bool(show_expired),
            )

            # Send initial page with pagination buttons
            embed = view.build_embed()
            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message  # Store message reference for timeout handling

        except Exception as e:
            logger.error(f"Error in bans command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # ONLINE COMMAND
    # ========================================================================

    @bot.tree.command(
        name="online", description="🆕 Current online players with pagination"
    )
    @app_commands.checks.cooldown(1, 10)
    async def online_command(interaction: discord.Interaction):
        """Current online players with pagination support"""
        await interaction.response.defer()

        try:
            online_players = await db.get_current_online_players()

            if not online_players:
                await interaction.followup.send("📊 **No Players Online**")
                return

            # 🔥 Pre-fetch all faction data for online players (async)
            def _get_factions_sync():
                faction_map = {}
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    player_ids = [
                        p.get("player_id") for p in online_players if p.get("player_id")
                    ]
                    if player_ids:
                        placeholders = ",".join("?" * len(player_ids))
                        cursor.execute(
                            f"SELECT player_id, faction FROM player_profiles WHERE player_id IN ({placeholders})",
                            player_ids,
                        )
                        for row in cursor.fetchall():
                            faction_map[str(row["player_id"])] = (
                                row["faction"] or "Unknown"
                            )
                return faction_map

            faction_map = await asyncio.to_thread(_get_factions_sync)

            # 🆕 Create pagination view for handling 500+ players
            view = OnlinePaginationView(
                players=online_players,
                author_id=interaction.user.id,
                faction_map=faction_map,
            )

            embed = view.build_embed()
            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message  # Store message reference for timeout handling

        except Exception as e:
            logger.error(f"Error in online command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # 🆕 PLAYER PROFILE & STATS COMMANDS
    # ========================================================================

    @bot.tree.command(
        name="player",
        description="🔥 FIXED: Get complete player profile (auto-refreshes placeholder username & missing age)",
    )
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
                            "player_id": profile_obj.player_id,
                            "username": profile_obj.username,
                            "is_online": profile_obj.is_online,
                            "last_seen": profile_obj.last_seen,
                            "faction": profile_obj.faction,
                            "faction_rank": profile_obj.faction_rank,
                            "job": profile_obj.job,
                            "warnings": profile_obj.warnings,
                            "played_hours": profile_obj.played_hours,
                            "age_ic": profile_obj.age_ic,
                        }
                        await db.save_player_profile(player)

            if not player:
                await interaction.followup.send(
                    f"🔍 **Not Found**\n\nNo player found with identifier: `{identifier}`"
                )
                return

            # 🔥 ENHANCED: Check if player needs refresh (placeholder username OR missing data)
            username = player.get("username", "")
            faction = player.get("faction")
            faction_rank = player.get("faction_rank")
            age_ic = player.get("age_ic")

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
            if faction and faction not in (
                None,
                "",
                "Civil",
                "Fără",
                "None",
                "-",
                "N/A",
            ):
                if not faction_rank or faction_rank.lower() in (
                    "null",
                    "none",
                    "",
                    "-",
                    "unknown",
                ):
                    needs_refresh = True
                    refresh_reasons.append("missing faction rank")

            # Perform refresh if needed
            if needs_refresh:
                logger.info(
                    f"🔄 Player {player['player_id']} needs refresh: {', '.join(refresh_reasons)}"
                )

                scraper = await scraper_getter()
                profile_obj = await scraper.get_player_profile(player["player_id"])

                if profile_obj:
                    # Update player data with fresh profile
                    player_update = {
                        "player_id": profile_obj.player_id,
                        "player_name": profile_obj.username,
                        "is_online": profile_obj.is_online,
                        "last_connection": profile_obj.last_seen,
                        "faction": profile_obj.faction,
                        "faction_rank": profile_obj.faction_rank,
                        "job": profile_obj.job,
                        "warns": profile_obj.warnings,
                        "played_hours": profile_obj.played_hours,
                        "age_ic": profile_obj.age_ic,
                    }
                    await db.save_player_profile(player_update)

                    # Update local player dict
                    player["username"] = profile_obj.username
                    player["faction_rank"] = profile_obj.faction_rank
                    player["age_ic"] = profile_obj.age_ic

                    logger.info(
                        f"✅ Refreshed player {player['player_id']}: username={profile_obj.username}, rank={profile_obj.faction_rank}, age_ic={profile_obj.age_ic}"
                    )

            # 🔥 FIX: Check if player is CURRENTLY online from online_players table
            def check_is_online():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cutoff = datetime.now() - timedelta(minutes=2)
                    cursor.execute(
                        "SELECT 1 FROM online_players WHERE player_id = ? AND detected_online_at > ?",
                        (player["player_id"], cutoff),
                    )
                    return cursor.fetchone() is not None

            is_currently_online = await asyncio.to_thread(check_is_online)

            # Build profile embed with ACCURATE online status
            status_icon = "🟢" if is_currently_online else "🔴"

            embed = discord.Embed(
                title=f"{status_icon} {player['username']}",
                description=f"Player ID: `{player['player_id']}`",
                color=discord.Color.green()
                if is_currently_online
                else discord.Color.greyple(),
                timestamp=datetime.now(),
            )

            # Status with accurate online check
            status_value = (
                "🟢 **Online now**"
                if is_currently_online
                else f"🔴 **Last seen:** {format_last_seen(player.get('last_seen'))}"
            )
            embed.add_field(name="Status", value=status_value, inline=True)

            # Faction/Rank display
            faction = player.get("faction")
            faction_rank = player.get("faction_rank")

            if faction and faction not in (
                None,
                "",
                "Civil",
                "Fără",
                "None",
                "-",
                "N/A",
            ):
                # Player has a faction
                if faction_rank and faction_rank not in (
                    None,
                    "",
                    "null",
                    "NULL",
                    "none",
                    "None",
                ):
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
            job = player.get("job") or "Unemployed"
            embed.add_field(name="Job", value=job, inline=True)

            # Warnings
            warnings = player.get("warnings", 0) or 0
            warn_color = "🟢" if warnings == 0 else "🟡" if warnings < 3 else "🔴"
            embed.add_field(
                name="Warnings", value=f"{warn_color} {warnings}/3", inline=True
            )

            # Played hours
            hours = player.get("played_hours", 0) or 0
            embed.add_field(name="Played Hours", value=f"{hours:.1f}h", inline=True)

            # Age IC - show even if Unknown
            age_ic = player.get("age_ic")
            age_ic_display = str(age_ic) if age_ic and age_ic > 0 else "Unknown"
            embed.add_field(name="Age (IC)", value=age_ic_display, inline=True)

            # Get action count from player_profiles table (already cached)
            total_actions = player.get("total_actions", 0) or 0
            embed.add_field(
                name="📊 Total Actions", value=f"{total_actions:,}", inline=True
            )

            # Optimized: Use a lighter query for recent actions count only
            def _count_recent_actions():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cutoff = datetime.now() - timedelta(days=7)
                    cursor.execute(
                        """
                        SELECT COUNT(*) FROM actions
                        WHERE (player_id = ? OR target_player_id = ?)
                        AND timestamp >= ?
                    """,
                        (player["player_id"], player["player_id"], cutoff),
                    )
                    return cursor.fetchone()[0]

            recent_count = await asyncio.to_thread(_count_recent_actions)
            embed.add_field(
                name="📝 Actions (7d)", value=f"{recent_count:,}", inline=True
            )

            # First detected
            first_detected = player.get("first_detected")
            if first_detected:
                if isinstance(first_detected, str):
                    try:
                        first_detected = datetime.fromisoformat(first_detected)
                    except:
                        first_detected = None
                if first_detected and isinstance(first_detected, datetime):
                    embed.add_field(
                        name="First Detected",
                        value=first_detected.strftime("%Y-%m-%d"),
                        inline=True,
                    )

            embed.set_footer(
                text=f"Use /actions {player['player_id']} to see recent activity"
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in player command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # 🆕 ADMIN COMMAND - REFRESH PLAYER
    # ========================================================================

    @bot.tree.command(
        name="refresh_player",
        description="🆕 Force refresh player profile from website (Admin only)",
    )
    @app_commands.describe(player_id="Player ID to refresh")
    @app_commands.checks.cooldown(1, 10)
    async def refresh_player_command(interaction: discord.Interaction, player_id: str):
        """🆕 Force refresh player profile - fixes stale data"""
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nThis command is restricted to bot administrators.",
                ephemeral=True,
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
                await interaction.followup.send(
                    f"❌ **Not Found**\n\nPlayer {player_id} not found on website."
                )
                return

            # Save to database
            profile = {
                "player_id": profile_obj.player_id,
                "player_name": profile_obj.username,
                "is_online": profile_obj.is_online,
                "last_connection": profile_obj.last_seen,
                "faction": profile_obj.faction,
                "faction_rank": profile_obj.faction_rank,
                "job": profile_obj.job,
                "warns": profile_obj.warnings,
                "played_hours": profile_obj.played_hours,
                "age_ic": profile_obj.age_ic,
            }

            await db.save_player_profile(profile)
            logger.info(f"✅ Updated profile for {profile_obj.username} ({player_id})")

            # Build success embed
            embed = discord.Embed(
                title="✅ Profile Refreshed",
                description=f"Successfully updated profile for **{profile_obj.username}** (ID: {player_id})",
                color=discord.Color.green(),
                timestamp=datetime.now(),
            )

            # Show updated fields
            embed.add_field(name="Username", value=profile_obj.username, inline=True)
            embed.add_field(
                name="Faction", value=profile_obj.faction or "No faction", inline=True
            )
            embed.add_field(
                name="Rank", value=profile_obj.faction_rank or "None", inline=True
            )
            embed.add_field(
                name="Status",
                value="🟢 Online" if profile_obj.is_online else "⚪ Offline",
                inline=True,
            )
            embed.add_field(name="Job", value=profile_obj.job or "None", inline=True)
            embed.add_field(
                name="Warnings", value=str(profile_obj.warnings or 0), inline=True
            )
            embed.add_field(
                name="Age (IC)",
                value=str(profile_obj.age_ic) if profile_obj.age_ic else "Unknown",
                inline=True,
            )

            embed.set_footer(text="Use /player to view full profile")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in refresh_player command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # 🆕 UNKNOWN ACTIONS COMMAND - Find unrecognized action patterns
    # ========================================================================

    @bot.tree.command(
        name="unknownactions",
        description="🆕 List unrecognized action patterns in database (Admin only)",
    )
    @app_commands.describe(
        limit="Max number of patterns to show (default: 20, max: 100)",
        export="Export all patterns to a text file (default: false)"
    )
    @app_commands.checks.cooldown(1, 30)
    async def unknown_actions_command(
        interaction: discord.Interaction, limit: int = 20, export: bool = False
    ):
        """🆕 List action patterns that weren't recognized by the parser"""
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nThis command is restricted to bot administrators.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            # Clamp limit to reasonable range
            limit = max(1, min(limit, 500))
            
            # Query unknown/other actions from database
            def _get_unknown_patterns():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT action_type, action_detail, raw_text, COUNT(*) as count
                        FROM actions 
                        WHERE action_type IN ('unknown', 'other')
                        GROUP BY raw_text
                        ORDER BY count DESC
                        LIMIT ?
                    """,
                        (limit,),
                    )
                    return [dict(row) for row in cursor.fetchall()]

            patterns = await asyncio.to_thread(_get_unknown_patterns)

            if not patterns:
                await interaction.followup.send(
                    "✅ **No unknown patterns!**\n\nAll actions in the database are recognized."
                )
                return

            # Calculate total unknown actions
            def _get_total_unknown():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT COUNT(*) FROM actions WHERE action_type IN ('unknown', 'other')"
                    )
                    return cursor.fetchone()[0]

            total_unknown = await asyncio.to_thread(_get_total_unknown)

            # If export requested, create a text file
            if export:
                import io
                
                content = f"UNRECOGNIZED ACTION PATTERNS REPORT\n"
                content += f"Generated: {datetime.now()}\n"
                content += f"Total unrecognized: {total_unknown:,}\n"
                content += f"Unique patterns shown: {len(patterns)}\n"
                content += "=" * 80 + "\n\n"
                
                for i, pattern in enumerate(patterns, 1):
                    raw_text = pattern.get("raw_text", "")
                    count = pattern.get("count", 0)
                    action_type = pattern.get("action_type", "unknown")
                    
                    content += f"[{i}] Type: {action_type} | Count: {count}\n"
                    content += f"    Raw: {raw_text}\n"
                    content += "-" * 80 + "\n"
                
                # Create file attachment
                file = discord.File(
                    io.BytesIO(content.encode('utf-8')), 
                    filename=f"unknown_patterns_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                )
                
                await interaction.followup.send(
                    f"📄 **Exported {len(patterns)} patterns** ({total_unknown:,} total unrecognized actions)",
                    file=file
                )
                return

            embed = discord.Embed(
                title="⚠️ Unrecognized Action Patterns",
                description=f"Found **{total_unknown:,}** unrecognized actions\nShowing top {len(patterns)} unique patterns:\n\n💡 Use `/unknownactions export:true limit:100` for full export",
                color=discord.Color.orange(),
                timestamp=datetime.now(),
            )

            for i, pattern in enumerate(patterns[:10], 1):  # Show max 10 in embed
                raw_text = pattern.get("raw_text", "")[:100]
                count = pattern.get("count", 0)
                action_type = pattern.get("action_type", "unknown")

                embed.add_field(
                    name=f"{i}. [{action_type}] ×{count}",
                    value=f"```{raw_text}...```" if len(pattern.get("raw_text", "")) > 100 else f"```{raw_text}```",
                    inline=False,
                )

            embed.set_footer(
                text="💡 Use these patterns to add new action type parsers in scraper.py"
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in unknown_actions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    @bot.tree.command(
        name="actionstats",
        description="🆕 Show action type statistics from database",
    )
    @app_commands.checks.cooldown(1, 30)
    async def action_stats_command(interaction: discord.Interaction):
        """🆕 Show breakdown of action types in database"""
        await interaction.response.defer()

        try:
            def _get_action_stats():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT action_type, COUNT(*) as count
                        FROM actions
                        GROUP BY action_type
                        ORDER BY count DESC
                    """
                    )
                    return [dict(row) for row in cursor.fetchall()]

            stats = await asyncio.to_thread(_get_action_stats)

            if not stats:
                await interaction.followup.send("📊 **No actions in database yet.**")
                return

            total = sum(s["count"] for s in stats)

            embed = discord.Embed(
                title="📊 Action Type Statistics",
                description=f"**Total Actions:** {total:,}",
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )

            # Group into recognized vs unrecognized
            recognized = []
            unrecognized = []
            for s in stats:
                if s["action_type"] in ("unknown", "other"):
                    unrecognized.append(s)
                else:
                    recognized.append(s)

            # Recognized actions
            if recognized:
                rec_text = "\n".join(
                    [f"• **{s['action_type']}**: {s['count']:,}" for s in recognized[:12]]
                )
                embed.add_field(
                    name=f"✅ Recognized ({sum(s['count'] for s in recognized):,})",
                    value=rec_text,
                    inline=False,
                )

            # Unrecognized actions
            if unrecognized:
                unrec_total = sum(s["count"] for s in unrecognized)
                unrec_pct = (unrec_total / total * 100) if total > 0 else 0
                unrec_text = "\n".join(
                    [f"• **{s['action_type']}**: {s['count']:,}" for s in unrecognized]
                )
                embed.add_field(
                    name=f"⚠️ Unrecognized ({unrec_total:,} = {unrec_pct:.1f}%)",
                    value=unrec_text,
                    inline=False,
                )
            else:
                embed.add_field(
                    name="✅ All Recognized!",
                    value="No unknown or other action types found.",
                    inline=False,
                )

            embed.set_footer(text="Use /unknownactions to see specific patterns")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in action_stats command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # 🆕 ADMIN HISTORY COMMAND - View ALL admin actions with pagination
    # ========================================================================

    @bot.tree.command(
        name="adminhistory",
        description="🆕 View all admin actions (warnings, bans, jails) with pagination",
    )
    @app_commands.describe(
        days="Days to look back (default: 30, max: 365)",
        action_type="Filter by action type (optional)"
    )
    @app_commands.choices(action_type=[
        app_commands.Choice(name="⚠️ Warnings", value="warning_received"),
        app_commands.Choice(name="🔨 Bans", value="ban_received"),
        app_commands.Choice(name="🔒 Admin Jail", value="admin_jail"),
        app_commands.Choice(name="🔓 Admin Unjail", value="admin_unjail"),
        app_commands.Choice(name="✅ Unbans", value="admin_unban"),
        app_commands.Choice(name="🔇 Mutes", value="mute_received"),
        app_commands.Choice(name="👢 Faction Kicks", value="faction_kicked"),
        app_commands.Choice(name="💀 Kill Character", value="kill_character"),
    ])
    @app_commands.checks.cooldown(1, 10)
    async def admin_history_command(
        interaction: discord.Interaction, 
        days: int = 30,
        action_type: Optional[str] = None
    ):
        """View all admin actions (warnings, bans, jails, mutes, etc.) across ALL players"""
        await interaction.response.defer()

        try:
            if days < 1 or days > 365:
                await interaction.followup.send("❌ Days must be between 1 and 365!")
                return

            # All admin action types
            admin_action_types = (
                'warning_received', 'ban_received', 'admin_jail', 'admin_unjail',
                'admin_unban', 'mute_received', 'faction_kicked', 'kill_character'
            )

            def _get_all_admin_actions():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cutoff = datetime.now() - timedelta(days=days)
                    
                    if action_type:
                        # Filter by specific action type
                        cursor.execute("""
                            SELECT * FROM actions
                            WHERE action_type = ?
                            AND timestamp >= ?
                            ORDER BY timestamp DESC
                            LIMIT 500
                        """, (action_type, cutoff))
                    else:
                        # All admin action types
                        type_placeholders = ",".join("?" * len(admin_action_types))
                        cursor.execute(f"""
                            SELECT * FROM actions
                            WHERE action_type IN ({type_placeholders})
                            AND timestamp >= ?
                            ORDER BY timestamp DESC
                            LIMIT 500
                        """, (*admin_action_types, cutoff))
                    
                    return [dict(row) for row in cursor.fetchall()]

            admin_actions = await asyncio.to_thread(_get_all_admin_actions)

            if not admin_actions:
                filter_text = f" of type '{action_type.replace('_', ' ')}'" if action_type else ""
                await interaction.followup.send(
                    f"✅ **No admin actions found{filter_text} in the last {days} days!**"
                )
                return

            # Create pagination view
            view = AdminHistoryPaginationView(
                actions=admin_actions,
                author_id=interaction.user.id,
                days=days,
                action_type_filter=action_type,
            )

            # Send initial page with pagination buttons
            embed = view.build_embed()
            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message

        except Exception as e:
            logger.error(f"Error in admin_history command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # 🆕 LEGACY ACTIONS COMMAND - View/analyze legacy_multi_action entries
    # ========================================================================

    @bot.tree.command(
        name="legacyactions",
        description="🆕 View legacy multi-action entries that couldn't be parsed (Admin only)",
    )
    @app_commands.describe(
        limit="Max entries to show (default: 20, max: 100)",
        player_id="Filter by player ID (optional)"
    )
    @app_commands.checks.cooldown(1, 30)
    async def legacy_actions_command(
        interaction: discord.Interaction,
        limit: int = 20,
        player_id: Optional[str] = None
    ):
        """View legacy_multi_action entries - these are old concatenated actions"""
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nThis command is restricted to bot administrators.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            limit = max(1, min(limit, 100))
            
            def _get_legacy_actions():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    if player_id:
                        cursor.execute("""
                            SELECT id, player_id, raw_text, timestamp
                            FROM actions 
                            WHERE action_type = 'legacy_multi_action'
                            AND player_id = ?
                            ORDER BY timestamp DESC
                            LIMIT ?
                        """, (player_id, limit))
                    else:
                        cursor.execute("""
                            SELECT id, player_id, raw_text, timestamp
                            FROM actions 
                            WHERE action_type = 'legacy_multi_action'
                            ORDER BY timestamp DESC
                            LIMIT ?
                        """, (limit,))
                    
                    return [dict(row) for row in cursor.fetchall()]

            def _get_total_count():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT COUNT(*) FROM actions WHERE action_type = 'legacy_multi_action'"
                    )
                    return cursor.fetchone()[0]

            legacy_actions = await asyncio.to_thread(_get_legacy_actions)
            total_count = await asyncio.to_thread(_get_total_count)

            if not legacy_actions:
                await interaction.followup.send(
                    "✅ **No legacy actions found!**\n\nAll actions have been properly categorized."
                )
                return

            embed = discord.Embed(
                title="📜 Legacy Multi-Action Entries",
                description=(
                    f"**Total:** {total_count:,} legacy entries in database\n"
                    f"**Showing:** {len(legacy_actions)}\n\n"
                    "⚠️ These entries contain multiple actions concatenated together from the old scraper. "
                    "They can't be cleanly separated but are preserved for reference."
                ),
                color=discord.Color.greyple(),
                timestamp=datetime.now(),
            )

            # Show first few entries
            for i, action in enumerate(legacy_actions[:10], 1):
                raw_text = action.get("raw_text", "")[:150]
                pid = action.get("player_id", "?")
                
                embed.add_field(
                    name=f"#{i} - Player {pid}",
                    value=f"```{raw_text}...```" if len(action.get("raw_text", "")) > 150 else f"```{raw_text}```",
                    inline=False,
                )

            embed.set_footer(
                text="💡 These entries are from the old scraper and cannot be automatically split. "
                     "They're preserved for manual reference if needed."
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in legacy_actions command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    # ========================================================================
    # 🆕 DELETE LEGACY COMMAND - Remove legacy_multi_action entries (Admin only)
    # ========================================================================

    @bot.tree.command(
        name="deletelegacy",
        description="🗑️ Delete legacy_multi_action entries from database (Admin only)",
    )
    @app_commands.describe(
        confirm="Type 'DELETE' to confirm deletion"
    )
    @app_commands.checks.cooldown(1, 300)
    async def delete_legacy_command(
        interaction: discord.Interaction,
        confirm: str = ""
    ):
        """Delete all legacy_multi_action entries - they're garbage data anyway"""
        if not is_admin(interaction.user.id):
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nThis command is restricted to bot administrators.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            def _get_count():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT COUNT(*) FROM actions WHERE action_type = 'legacy_multi_action'"
                    )
                    return cursor.fetchone()[0]

            count = await asyncio.to_thread(_get_count)

            if count == 0:
                await interaction.followup.send(
                    "✅ **No legacy actions to delete!**\n\nDatabase is already clean."
                )
                return

            if confirm != "DELETE":
                await interaction.followup.send(
                    f"⚠️ **Confirmation Required**\n\n"
                    f"This will permanently delete **{count:,}** legacy_multi_action entries.\n\n"
                    f"These entries are garbage data from the old scraper (multiple actions concatenated together) "
                    f"and cannot be properly parsed.\n\n"
                    f"To confirm, run:\n`/deletelegacy confirm:DELETE`"
                )
                return

            # Actually delete
            def _delete_legacy():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "DELETE FROM actions WHERE action_type = 'legacy_multi_action'"
                    )
                    deleted = cursor.rowcount
                    conn.commit()
                    return deleted

            deleted = await asyncio.to_thread(_delete_legacy)

            await interaction.followup.send(
                f"✅ **Deleted {deleted:,} legacy_multi_action entries!**\n\n"
                f"Database has been cleaned of garbage concatenated data."
            )
            logger.info(f"🗑️ Admin {interaction.user} deleted {deleted:,} legacy_multi_action entries")

        except Exception as e:
            logger.error(f"Error in delete_legacy command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")

    logger.info(
        "✅ All slash commands registered successfully with auto-refresh for placeholder usernames"
    )

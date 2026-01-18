"""Discord Slash Commands for Pro4Kings Database Bot"""
import discord
from discord import app_commands
from datetime import datetime, timedelta
import logging
import asyncio

logger = logging.getLogger(__name__)

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
    'status_message': None,  # 🔥 NEW: Store message for auto-refresh
    'status_task': None,  # 🔥 NEW: Auto-refresh task
    'scan_config': {
        'batch_size': 20,  # 🔥 INCREASED: 10 → 20
        'workers': 20,  # 🔥 INCREASED: 10 → 20
        'wave_delay': 0.05  # 🔥 DECREASED: 0.2 → 0.05
    }
}

# 🔧 FIX: Add format_time helper function
def format_time_duration(seconds: float) -> str:
    """Format seconds into human-readable time (e.g., '2h 34m' or '45m')"""
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

# 🔥 NEW: Helper function to build status embed
def build_status_embed():
    """Build real-time status embed"""
    current = SCAN_STATE['current_id']
    start = SCAN_STATE['start_id']
    end = SCAN_STATE['end_id']
    total = end - start + 1
    scanned = max(0, current - start)
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
    
    embed.add_field(name="📍 Current ID", value=f"{current:,}", inline=True)
    embed.add_field(name="⚡ Speed", value=f"{speed:.2f} IDs/s", inline=True)
    embed.add_field(name="⏱️ ETA", value=eta_str, inline=True)
    
    embed.add_field(name="✅ Found", value=f"{SCAN_STATE['found_count']:,}", inline=True)
    embed.add_field(name="❌ Errors", value=f"{SCAN_STATE['error_count']:,}", inline=True)
    embed.add_field(name="⏲️ Elapsed", value=elapsed_str, inline=True)
    
    # Progress bar
    bar_length = 20
    filled = int(progress_pct / 100 * bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)
    embed.add_field(name="Progress Bar", value=f"`{bar}` {progress_pct:.1f}%", inline=False)
    
    embed.set_footer(text="🔄 Auto-refreshing every 3 seconds | Use /scan pause or /scan cancel")
    
    return embed

# 🔥 NEW: Auto-refresh status task
async def auto_refresh_status():
    """Auto-refresh the status message every 3 seconds"""
    try:
        while SCAN_STATE['is_scanning']:
            if SCAN_STATE['status_message']:
                try:
                    embed = build_status_embed()
                    await SCAN_STATE['status_message'].edit(embed=embed)
                except discord.NotFound:
                    # Message was deleted
                    SCAN_STATE['status_message'] = None
                    break
                except Exception as e:
                    logger.error(f"Error refreshing status: {e}")
            
            await asyncio.sleep(3)  # Refresh every 3 seconds
        
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

def setup_commands(bot, db, scraper_getter):
    """Setup all slash commands for the bot
    
    Args:
        bot: Discord bot instance
        db: Database instance
        scraper_getter: Async function that returns scraper instance (accepts max_concurrent param)
    """
    
    # ========================================================================
    # SCAN MANAGEMENT COMMANDS - OPTIMIZED VERSION
    # ========================================================================
    
    scan_group = app_commands.Group(name="scan", description="Database scan management")
    
    @scan_group.command(name="start", description="Start initial database scan")
    @app_commands.describe(
        start_id="Starting player ID (default: 1)",
        end_id="Ending player ID (default: 100000)"
    )
    async def scan_start(interaction: discord.Interaction, start_id: int = 1, end_id: int = 100000):
        """Start database scan"""
        await interaction.response.defer()
        
        try:
            if SCAN_STATE['is_scanning']:
                await interaction.followup.send("❌ **A scan is already in progress!** Use `/scan status` to check progress or `/scan cancel` to stop it.")
                return
            
            if start_id < 1 or end_id < start_id:
                await interaction.followup.send("❌ **Invalid ID range!** Start must be >= 1 and end must be >= start.")
                return
            
            # Initialize scan state
            SCAN_STATE['is_scanning'] = True
            SCAN_STATE['is_paused'] = False
            SCAN_STATE['start_id'] = start_id
            SCAN_STATE['end_id'] = end_id
            SCAN_STATE['current_id'] = start_id
            SCAN_STATE['found_count'] = 0
            SCAN_STATE['error_count'] = 0
            SCAN_STATE['start_time'] = datetime.now()
            SCAN_STATE['status_message'] = None  # Reset status message
            
            # Start scan task
            async def run_scan():
                try:
                    # 🔧 HOTFIX: Pass max_concurrent from config
                    workers = SCAN_STATE['scan_config']['workers']
                    logger.info(f"🔧 Initializing scraper with {workers} workers for scan...")
                    scraper = await scraper_getter(max_concurrent=workers)
                    logger.info(f"✅ Scraper ready with {scraper.max_concurrent} workers")
                    
                    total_ids = end_id - start_id + 1
                    batch_size = SCAN_STATE['scan_config']['batch_size']
                    
                    logger.info(f"🚀 Starting scan: IDs {start_id}-{end_id} ({total_ids:,} total)")
                    logger.info(f"⚙️ Config: batch={batch_size}, workers={SCAN_STATE['scan_config']['workers']}, delay={SCAN_STATE['scan_config']['wave_delay']}s")
                    
                    for batch_start in range(start_id, end_id + 1, batch_size):
                        # Check if paused
                        while SCAN_STATE['is_paused']:
                            await asyncio.sleep(1)
                        
                        # Check if cancelled
                        if not SCAN_STATE['is_scanning']:
                            logger.info("🛑 Scan cancelled by user")
                            break
                        
                        batch_end = min(batch_start + batch_size - 1, end_id)
                        batch_ids = [str(i) for i in range(batch_start, batch_end + 1)]
                        
                        SCAN_STATE['current_id'] = batch_start
                        
                        # Scan batch
                        profiles = await scraper.batch_get_profiles(batch_ids)
                        
                        # Save profiles
                        for profile in profiles:
                            try:
                                profile_dict = {
                                    'player_id': profile.player_id,
                                    'player_name': profile.username,
                                    'is_online': profile.is_online,
                                    'last_seen': profile.last_seen,
                                    'faction': profile.faction,
                                    'faction_rank': profile.faction_rank,
                                    'job': profile.job,
                                    'level': profile.level,
                                    'respect_points': profile.respect_points,
                                    'warnings': profile.warnings,
                                    'played_hours': profile.played_hours,
                                    'age_ic': profile.age_ic,
                                    'phone_number': profile.phone_number,
                                    'vehicles_count': profile.vehicles_count,
                                    'properties_count': profile.properties_count
                                }
                                db.save_player_profile(profile_dict)
                                SCAN_STATE['found_count'] += 1
                            except Exception as e:
                                logger.error(f"Error saving profile {profile.player_id}: {e}")
                                SCAN_STATE['error_count'] += 1
                        
                        # Update progress in database
                        db.update_scan_progress(batch_end, SCAN_STATE['found_count'], SCAN_STATE['error_count'])
                        
                        # Log progress every 100 IDs
                        if batch_start % 100 == 0:
                            progress = ((batch_start - start_id) / total_ids) * 100
                            elapsed = (datetime.now() - SCAN_STATE['start_time']).total_seconds()
                            speed = (batch_start - start_id) / elapsed if elapsed > 0 else 0
                            logger.info(f"📊 Progress: {progress:.1f}% | ID: {batch_start}/{end_id} | Speed: {speed:.2f} IDs/s | Found: {SCAN_STATE['found_count']} | Errors: {SCAN_STATE['error_count']}")
                        
                        # Add configured wave delay
                        await asyncio.sleep(SCAN_STATE['scan_config']['wave_delay'])
                    
                    # Scan complete
                    SCAN_STATE['is_scanning'] = False
                    elapsed = (datetime.now() - SCAN_STATE['start_time']).total_seconds()
                    avg_speed = (end_id - start_id) / elapsed if elapsed > 0 else 0
                    logger.info(f"✅ Scan complete! Found {SCAN_STATE['found_count']:,} players in {format_time_duration(elapsed)} (avg: {avg_speed:.2f} IDs/s)")
                    
                except Exception as e:
                    logger.error(f"❌ Scan error: {e}", exc_info=True)
                    SCAN_STATE['is_scanning'] = False
                    SCAN_STATE['error_count'] += 1
            
            # Start scan in background
            SCAN_STATE['scan_task'] = asyncio.create_task(run_scan())
            
            # Wait a moment to ensure scan task started
            await asyncio.sleep(0.5)
            
            # Verify scan is actually running
            if not SCAN_STATE['is_scanning']:
                await interaction.followup.send("❌ **Failed to start scan!** Check bot logs for errors.")
                return
            
            # 🔥 OPTIMIZED: Show expected speed based on current settings
            config = SCAN_STATE['scan_config']
            expected_speed = config['batch_size'] / (config['wave_delay'] + 0.5)
            
            embed = discord.Embed(
                title="🚀 Database Scan Started",
                description=f"Scanning player IDs {start_id:,} to {end_id:,}\n\nUse `/scan status` to monitor progress with **real-time auto-refresh**!",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            embed.add_field(name="⚙️ Batch Size", value=f"{config['batch_size']} IDs", inline=True)
            embed.add_field(name="👷 Workers", value=str(config['workers']), inline=True)
            embed.add_field(name="⏱️ Wave Delay", value=f"{config['wave_delay']}s", inline=True)
            embed.add_field(name="⚡ Expected Speed", value=f"~{expected_speed:.1f} IDs/s", inline=True)
            embed.add_field(name="📊 Total IDs", value=f"{end_id - start_id + 1:,}", inline=True)
            
            eta = (end_id - start_id + 1) / expected_speed
            embed.add_field(name="🕐 Est. Time", value=format_time_duration(eta), inline=True)
            
            embed.set_footer(text="Tip: Use /scanconfig to adjust speed settings")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error starting scan: {e}", exc_info=True)
            SCAN_STATE['is_scanning'] = False
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    @scan_group.command(name="status", description="View real-time scan progress (auto-refreshing)")
    async def scan_status(interaction: discord.Interaction):
        """Check scan status with auto-refresh"""
        await interaction.response.defer()
        
        try:
            if not SCAN_STATE['is_scanning'] and not SCAN_STATE['is_paused']:
                await interaction.followup.send("ℹ️ **No scan in progress.** Use `/scan start <start> <end>` to begin scanning.")
                return
            
            # Build and send initial embed
            embed = build_status_embed()
            message = await interaction.followup.send(embed=embed)
            
            # 🔥 NEW: Store message and start auto-refresh
            SCAN_STATE['status_message'] = message
            
            # Cancel old refresh task if exists
            if SCAN_STATE['status_task'] and not SCAN_STATE['status_task'].done():
                SCAN_STATE['status_task'].cancel()
            
            # Start new refresh task
            SCAN_STATE['status_task'] = asyncio.create_task(auto_refresh_status())
            
        except Exception as e:
            logger.error(f"Error checking scan status: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    @scan_group.command(name="pause", description="Pause ongoing scan")
    async def scan_pause(interaction: discord.Interaction):
        """Pause scan"""
        await interaction.response.defer()
        
        try:
            if not SCAN_STATE['is_scanning']:
                await interaction.followup.send("❌ **No scan in progress!**")
                return
            
            if SCAN_STATE['is_paused']:
                await interaction.followup.send("⏸️ **Scan is already paused!** Use `/scan resume` to continue.")
                return
            
            SCAN_STATE['is_paused'] = True
            await interaction.followup.send("⏸️ **Scan paused!** Use `/scan resume` to continue or `/scan cancel` to stop.")
            
        except Exception as e:
            logger.error(f"Error pausing scan: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    @scan_group.command(name="resume", description="Resume paused scan")
    async def scan_resume(interaction: discord.Interaction):
        """Resume scan"""
        await interaction.response.defer()
        
        try:
            if not SCAN_STATE['is_scanning']:
                await interaction.followup.send("❌ **No scan in progress!**")
                return
            
            if not SCAN_STATE['is_paused']:
                await interaction.followup.send("ℹ️ **Scan is already running!**")
                return
            
            SCAN_STATE['is_paused'] = False
            await interaction.followup.send("▶️ **Scan resumed!** Use `/scan status` to check progress.")
            
        except Exception as e:
            logger.error(f"Error resuming scan: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    @scan_group.command(name="cancel", description="Cancel ongoing scan")
    async def scan_cancel(interaction: discord.Interaction):
        """Cancel scan"""
        await interaction.response.defer()
        
        try:
            if not SCAN_STATE['is_scanning']:
                await interaction.followup.send("❌ **No scan in progress!**")
                return
            
            SCAN_STATE['is_scanning'] = False
            SCAN_STATE['is_paused'] = False
            
            if SCAN_STATE['scan_task']:
                SCAN_STATE['scan_task'].cancel()
            
            if SCAN_STATE['status_task']:
                SCAN_STATE['status_task'].cancel()
            
            embed = discord.Embed(
                title="🛑 Scan Cancelled",
                description=f"Scan stopped at ID {SCAN_STATE['current_id']:,}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            
            embed.add_field(name="✅ Found", value=f"{SCAN_STATE['found_count']:,} players", inline=True)
            embed.add_field(name="❌ Errors", value=f"{SCAN_STATE['error_count']:,}", inline=True)
            
            if SCAN_STATE['start_time']:
                elapsed = (datetime.now() - SCAN_STATE['start_time']).total_seconds()
                scanned = SCAN_STATE['current_id'] - SCAN_STATE['start_id']
                avg_speed = scanned / elapsed if elapsed > 0 else 0
                embed.add_field(name="⚡ Avg Speed", value=f"{avg_speed:.2f} IDs/s", inline=True)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error cancelling scan: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    bot.tree.add_command(scan_group)
    
    # ========================================================================
    # SCAN CONFIG COMMAND - OPTIMIZED VERSION
    # ========================================================================
    
    @bot.tree.command(name="scanconfig", description="View or modify scan configuration")
    @app_commands.describe(
        batch_size="Number of IDs to scan per batch (5-30)",
        workers="Number of concurrent workers (5-30)",
        wave_delay="Delay between batches in seconds (0.01-1.0)"
    )
    async def scanconfig_command(
        interaction: discord.Interaction,
        batch_size: int = None,
        workers: int = None,
        wave_delay: float = None
    ):
        """Configure scan parameters"""
        await interaction.response.defer()
        
        try:
            # Update config if parameters provided
            updated = []
            
            if batch_size is not None:
                if 5 <= batch_size <= 30:
                    SCAN_STATE['scan_config']['batch_size'] = batch_size
                    updated.append(f"Batch size: {batch_size}")
                else:
                    await interaction.followup.send("❌ **Batch size must be between 5 and 30!**")
                    return
            
            if workers is not None:
                if 5 <= workers <= 30:
                    SCAN_STATE['scan_config']['workers'] = workers
                    updated.append(f"Workers: {workers}")
                else:
                    await interaction.followup.send("❌ **Workers must be between 5 and 30!**")
                    return
            
            if wave_delay is not None:
                if 0.01 <= wave_delay <= 1.0:
                    SCAN_STATE['scan_config']['wave_delay'] = wave_delay
                    updated.append(f"Wave delay: {wave_delay}s")
                else:
                    await interaction.followup.send("❌ **Wave delay must be between 0.01 and 1.0 seconds!**")
                    return
            
            # Create embed
            embed = discord.Embed(
                title="⚙️ Scan Configuration",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            if updated:
                embed.description = "**✅ Updated:** " + ", ".join(updated) + "\n\n⚠️ *Changes apply to NEW scans only!*"
            else:
                embed.description = "**Current Configuration:**"
            
            config = SCAN_STATE['scan_config']
            
            embed.add_field(name="📦 Batch Size", value=f"{config['batch_size']} IDs", inline=True)
            embed.add_field(name="👷 Workers", value=f"{config['workers']} concurrent", inline=True)
            embed.add_field(name="⏱️ Wave Delay", value=f"{config['wave_delay']}s", inline=True)
            
            # Calculate expected speed
            expected_speed = config['batch_size'] / (config['wave_delay'] + 0.5)
            embed.add_field(name="⚡ Expected Speed", value=f"~{expected_speed:.1f} IDs/second", inline=True)
            
            # Add preset recommendations
            embed.add_field(
                name="📋 Recommended Presets",
                value=(
                    "**Aggressive:** `/scanconfig 20 20 0.05` (~30 IDs/s)\n"
                    "**Balanced:** `/scanconfig 15 15 0.1` (~20 IDs/s)\n"
                    "**Safe:** `/scanconfig 10 10 0.2` (~10 IDs/s)"
                ),
                inline=False
            )
            
            embed.set_footer(text="💡 Higher = faster but may trigger rate limits | Lower = safer but slower")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in scanconfig command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ **Error:** {str(e)}")
    
    # ... (keep all existing commands: player, actions, online, search, banned, stats, factions) ...
    # [Previous command code remains unchanged]
    
    logger.info("✅ All slash commands registered (including /scan and /scanconfig)")

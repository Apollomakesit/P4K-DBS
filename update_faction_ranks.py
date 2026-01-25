#!/usr/bin/env python3
"""
Update faction ranks for all players in actual factions (not "Civil")
This script scans player profiles and updates their faction_rank in the database
"""

import asyncio
import logging
from database import Database
from scraper import Pro4KingsScraper
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def update_faction_ranks(batch_size: int = 50, max_players: int = None):
    """
    Update faction ranks for players in actual factions
    
    Args:
        batch_size: Number of players to process in each batch
        max_players: Maximum number of players to update (None = all)
    """
    
    db = Database()
    
    # Get all players in factions (not Civil)
    def _get_faction_players():
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT player_id, username, faction
                FROM player_profiles
                WHERE faction IS NOT NULL 
                AND faction != '' 
                AND faction != 'Civil'
                AND faction != 'Fără'
                ORDER BY last_profile_update ASC NULLS FIRST
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    faction_players = await asyncio.to_thread(_get_faction_players)
    
    if not faction_players:
        logger.warning("No players found in factions!")
        return
    
    total_players = len(faction_players)
    if max_players:
        faction_players = faction_players[:max_players]
    
    logger.info(f"📊 Found {total_players} players in factions")
    logger.info(f"🎯 Will update {len(faction_players)} players")
    
    # Group by faction for better logging
    from collections import defaultdict
    by_faction = defaultdict(list)
    for player in faction_players:
        by_faction[player['faction']].append(player)
    
    logger.info(f"\n📋 Players by faction:")
    for faction, players in sorted(by_faction.items(), key=lambda x: len(x[1]), reverse=True):
        logger.info(f"  {faction}: {len(players)} players")
    
    updated = 0
    errors = 0
    no_rank_found = 0
    
    async with Pro4KingsScraper(max_concurrent=5) as scraper:  # Conservative: 5 workers
        for i in range(0, len(faction_players), batch_size):
            batch = faction_players[i:i + batch_size]
            player_ids = [p['player_id'] for p in batch]
            
            logger.info(f"\n🔄 Processing batch {i//batch_size + 1}/{(len(faction_players) + batch_size - 1)//batch_size}")
            logger.info(f"   Players {i+1}-{min(i+batch_size, len(faction_players))} of {len(faction_players)}")
            
            # Fetch profiles in batch
            profiles = await scraper.batch_get_profiles(player_ids)
            
            for profile in profiles:
                try:
                    if profile.faction_rank:
                        # Update player profile with faction_rank
                        profile_dict = {
                            'player_id': profile.player_id,
                            'player_name': profile.username,
                            'faction': profile.faction,
                            'faction_rank': profile.faction_rank,
                            'job': profile.job,
                            'level': profile.level,
                            'warns': profile.warnings,
                            'respect_points': profile.respect_points,
                            'played_hours': profile.played_hours,
                            'age_ic': profile.age_ic,
                            'last_connection': profile.last_seen,
                            'is_online': profile.is_online
                        }
                        
                        await db.save_player_profile(profile_dict)
                        updated += 1
                        logger.info(f"   ✅ {profile.username} ({profile.faction}): {profile.faction_rank}")
                    else:
                        no_rank_found += 1
                        logger.warning(f"   ⚠️  {profile.username} ({profile.faction}): No rank found")
                        
                except Exception as e:
                    errors += 1
                    logger.error(f"   ❌ Error updating {profile.player_id}: {e}")
            
            # Progress update
            progress = min(i + batch_size, len(faction_players))
            logger.info(f"\n📈 Progress: {progress}/{len(faction_players)} ({progress*100//len(faction_players)}%)")
            logger.info(f"   Updated: {updated} | No rank: {no_rank_found} | Errors: {errors}")
            
            # Small delay between batches
            if i + batch_size < len(faction_players):
                await asyncio.sleep(1)
    
    logger.info(f"\n" + "="*60)
    logger.info(f"✅ Faction rank update complete!")
    logger.info(f"\n📊 Final Statistics:")
    logger.info(f"   Total processed: {len(faction_players)}")
    logger.info(f"   Successfully updated: {updated}")
    logger.info(f"   No rank found: {no_rank_found}")
    logger.info(f"   Errors: {errors}")
    logger.info(f"   Success rate: {updated*100//len(faction_players) if faction_players else 0}%")


if __name__ == "__main__":
    # Parse command line arguments
    batch_size = 50
    max_players = None
    
    if len(sys.argv) > 1:
        try:
            max_players = int(sys.argv[1])
            logger.info(f"Limiting to {max_players} players")
        except ValueError:
            logger.error("Usage: python update_faction_ranks.py [max_players]")
            sys.exit(1)
    
    asyncio.run(update_faction_ranks(batch_size=batch_size, max_players=max_players))

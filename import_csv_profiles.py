#!/usr/bin/env python3
"""
Import player_profiles.csv into the database
Handles special characters in player names
Maps CSV columns to cleaned database schema (14 columns)
"""

import csv
import sys
from datetime import datetime
from database import Database
import logging
import asyncio
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def import_csv_profiles(csv_file_path: str = 'player_profiles.csv'):
    """
    Import player profiles from CSV file
    
    CSV Columns (10): player_id, player_name, last_connection, is_online, 
                      faction, faction_rank, warns, job, played_hours, age_ic
    
    DB Schema (14):   player_id, username, is_online, last_seen, first_detected,
                      faction, faction_rank, job, warnings,
                      played_hours, age_ic,
                      total_actions, last_profile_update, priority_update
                      
    🔥 REMOVED: level, respect_points, phone_number, vehicles_count, properties_count
    """
    
    db = Database()
    imported = 0
    updated = 0
    errors = 0
    skipped = 0
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
            # Read first line to detect format
            first_line = csvfile.readline()
            csvfile.seek(0)
            
            # Determine delimiter (comma or tab)
            delimiter = '\t' if '\t' in first_line else ','
            logger.info(f"Detected delimiter: {'TAB' if delimiter == '\t' else 'COMMA'}")
            
            # Parse the CSV
            reader = csv.DictReader(csvfile, delimiter=delimiter)
            
            logger.info(f"CSV columns detected: {reader.fieldnames}")
            logger.info(f"\n📊 Starting import...\n")
            
            for row in reader:
                try:
                    # Get player_id - required field
                    player_id = row.get('player_id', '').strip()
                    if not player_id:
                        skipped += 1
                        continue
                    
                    # Parse datetime fields
                    last_connection = None
                    if row.get('last_connection'):
                        try:
                            last_connection = datetime.strptime(
                                row['last_connection'].strip(), 
                                '%Y-%m-%d %H:%M:%S'
                            )
                        except ValueError:
                            logger.warning(f"Could not parse date for player {player_id}: {row.get('last_connection')}")
                            last_connection = datetime.now()
                    
                    # Get faction - filter out "Civil"
                    faction = row.get('faction', '').strip()
                    if faction in ['Civil', 'Fără', 'None', '-', '']:
                        faction = None
                    
                    # 🔥 UPDATED: Build profile dict matching NEW 14-column schema (removed 5 fields)
                    profile = {
                        # CSV -> DB field mappings
                        'player_id': player_id,
                        'player_name': row.get('player_name', '').strip(),  # Maps to 'username' in DB
                        'last_connection': last_connection or datetime.now(),  # Maps to 'last_seen'
                        'is_online': bool(int(row.get('is_online', 0))),
                        'faction': faction,
                        'faction_rank': row.get('faction_rank', '').strip() or None,
                        'warns': int(row.get('warns', 0)) if row.get('warns', '').strip() else 0,  # Maps to 'warnings'
                        'job': row.get('job', '').strip() or None,
                        'played_hours': float(row.get('played_hours', 0)) if row.get('played_hours', '').strip() else None,
                        'age_ic': int(row.get('age_ic', 0)) if row.get('age_ic', '').strip() else None,
                        
                        # NO LONGER SENDING: level, respect_points, phone_number, vehicles_count, properties_count
                    }
                    
                    # Skip if no player_name
                    if not profile['player_name']:
                        skipped += 1
                        logger.warning(f"Skipping player {player_id}: No player_name")
                        continue
                    
                    # Save to database (uses save_player_profile which handles INSERT/UPDATE)
                    await db.save_player_profile(profile)
                    imported += 1
                    
                    # Progress logging
                    if imported % 1000 == 0:
                        logger.info(f"✓ Imported {imported:,} profiles...")
                    elif imported % 100 == 0 and imported < 1000:
                        logger.info(f"✓ Imported {imported} profiles...")
                        
                except ValueError as e:
                    errors += 1
                    logger.error(f"Value error on row {imported + errors}: {e}")
                    continue
                except Exception as e:
                    errors += 1
                    logger.error(f"Error importing row {imported + errors}: {e}")
                    if errors <= 5:  # Show first 5 errors in detail
                        logger.error(f"Problematic row: {row}")
                    continue
        
        logger.info(f"\n" + "="*60)
        logger.info(f"✅ Import complete!")
        logger.info(f"\n📊 Statistics:")
        logger.info(f"   Imported: {imported:,}")
        logger.info(f"   Skipped: {skipped:,}")
        logger.info(f"   Errors: {errors:,}")
        logger.info(f"   Success rate: {imported*100//(imported+errors+skipped) if (imported+errors+skipped) > 0 else 0}%")
        logger.info(f"="*60)
        
        # Show database stats
        stats = await db.get_database_stats()
        logger.info(f"\n💾 Database now has:")
        logger.info(f"   Total players: {stats['total_players']:,}")
        logger.info(f"   Total actions: {stats['total_actions']:,}")
        logger.info(f"   Currently online: {stats['online_count']:,}")
        
        # Show faction distribution
        logger.info(f"\n🏛️ Top 10 Factions by member count:")
        factions = await db.get_all_factions_with_counts()
        for i, faction in enumerate(factions[:10], 1):
            logger.info(f"   {i}. {faction['faction_name']}: {faction['member_count']} members ({faction['online_count']} online)")
        
    except FileNotFoundError:
        logger.error(f"❌ File not found: {csv_file_path}")
        logger.error("Make sure player_profiles.csv is in the same directory as this script")
        logger.error(f"Current working directory: {os.getcwd()}")
    except Exception as e:
        logger.error(f"❌ Error during import: {e}", exc_info=True)


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'player_profiles.csv'
    
    logger.info(f"\n" + "="*60)
    logger.info(f"📥 CSV Player Profile Importer")
    logger.info(f"="*60)
    logger.info(f"CSV File: {csv_path}")
    logger.info(f"Working Directory: {os.getcwd()}")
    logger.info(f"="*60 + "\n")
    
    asyncio.run(import_csv_profiles(csv_path))

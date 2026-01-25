#!/usr/bin/env python3
"""
Import player_profiles.csv into the database
Handles special characters in player names
Maps CSV columns to cleaned database schema (14 columns)

CSV Columns: player_id, player_name, last_connection, is_online, 
             faction, faction_rank, warns, job, played_hours, age_ic,
             last_checked, check_priority
             
DB Schema:   player_id, username, is_online, last_seen, first_detected,
             faction, faction_rank, job, warnings,
             played_hours, age_ic,
             total_actions, last_profile_update, priority_update
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
    
    CSV Columns (12): player_id, player_name, last_connection, is_online, 
                      faction, faction_rank, warns, job, played_hours, age_ic,
                      last_checked, check_priority
    
    DB Schema (14):   player_id, username, is_online, last_seen, first_detected,
                      faction, faction_rank, job, warnings,
                      played_hours, age_ic,
                      total_actions, last_profile_update, priority_update
                      
    🔥 NOTE: last_checked and check_priority from CSV are ignored
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
            delimiter = '\t' if first_line.count('\t') > first_line.count(',') else ','
            delimiter_name = 'TAB' if delimiter == '\t' else 'COMMA'
            logger.info(f"Detected delimiter: {delimiter_name}")


            
            # Parse the CSV
            reader = csv.DictReader(csvfile, delimiter=delimiter)
            
            logger.info(f"CSV columns detected: {reader.fieldnames}")
            
            # Verify expected columns are present
            expected_cols = ['player_id', 'player_name', 'last_connection', 'is_online', 
                           'faction', 'faction_rank', 'warns', 'job', 'played_hours', 'age_ic']
            missing_cols = [col for col in expected_cols if col not in reader.fieldnames]
            if missing_cols:
                logger.error(f"❌ Missing required columns: {missing_cols}")
                return
            
            # Log extra columns that will be ignored
            extra_cols = [col for col in reader.fieldnames if col not in expected_cols]
            if extra_cols:
                logger.info(f"ℹ️ Extra CSV columns (will be ignored): {extra_cols}")
            
            logger.info(f"\n📊 Starting import...\n")
            
            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                try:
                    # Get player_id - required field
                    player_id = row.get('player_id', '').strip()
                    if not player_id:
                        skipped += 1
                        logger.debug(f"Row {row_num}: Skipped - no player_id")
                        continue
                    
                    # Get player_name - required field
                    player_name = row.get('player_name', '').strip()
                    if not player_name:
                        skipped += 1
                        logger.warning(f"Row {row_num}: Skipped player {player_id} - no player_name")
                        continue
                    
                    # Parse datetime fields
                    last_connection = None
                    if row.get('last_connection'):
                        try:
                            last_connection = datetime.strptime(
                                row['last_connection'].strip(), 
                                '%Y-%m-%d %H:%M:%S'
                            )
                        except ValueError as e:
                            logger.warning(f"Row {row_num}: Could not parse date for player {player_id}: {row.get('last_connection')} - using current time")
                            last_connection = datetime.now()
                    else:
                        last_connection = datetime.now()
                    
                    # Get faction - filter out "Civil" and empty values
                    faction = row.get('faction', '').strip()
                    if faction in ['Civil', 'Fără', 'None', '-', '', 'N/A']:
                        faction = None
                    
                    # Get faction_rank
                    faction_rank = row.get('faction_rank', '').strip()
                    if faction_rank in ['', '-', 'None', 'N/A']:
                        faction_rank = None
                    
                    # Get job
                    job = row.get('job', '').strip()
                    if job in ['', '-', 'None', 'N/A']:
                        job = None
                    
                    # Parse integer fields with error handling
                    try:
                        warns = int(row.get('warns', 0)) if row.get('warns', '').strip() else 0
                    except ValueError:
                        logger.warning(f"Row {row_num}: Invalid warns value for player {player_id}: {row.get('warns')} - using 0")
                        warns = 0
                    
                    try:
                        is_online = bool(int(row.get('is_online', 0)))
                    except ValueError:
                        logger.warning(f"Row {row_num}: Invalid is_online value for player {player_id}: {row.get('is_online')} - using False")
                        is_online = False
                    
                    # Parse float/int fields
                    try:
                        played_hours = float(row.get('played_hours', 0)) if row.get('played_hours', '').strip() else None
                    except ValueError:
                        logger.warning(f"Row {row_num}: Invalid played_hours value for player {player_id}: {row.get('played_hours')} - using None")
                        played_hours = None
                    
                    try:
                        age_ic = int(row.get('age_ic', 0)) if row.get('age_ic', '').strip() else None
                    except ValueError:
                        logger.warning(f"Row {row_num}: Invalid age_ic value for player {player_id}: {row.get('age_ic')} - using None")
                        age_ic = None
                    
                    # 🔥 Build profile dict matching NEW 14-column schema
                    # NOTE: last_checked and check_priority from CSV are ignored
                    profile = {
                        # CSV -> DB field mappings
                        'player_id': player_id,
                        'player_name': player_name,  # Maps to 'username' in DB
                        'last_connection': last_connection,  # Maps to 'last_seen'
                        'is_online': is_online,
                        'faction': faction,
                        'faction_rank': faction_rank,
                        'warns': warns,  # Maps to 'warnings'
                        'job': job,
                        'played_hours': played_hours,
                        'age_ic': age_ic,
                        
                        # NO LONGER SENDING: level, respect_points, phone_number, vehicles_count, properties_count
                        # IGNORED FROM CSV: last_checked, check_priority (handled by DB automatically)
                    }
                    
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
                    logger.error(f"Row {row_num}: Value error - {e}")
                    if errors <= 10:  # Show first 10 errors in detail
                        logger.error(f"Problematic row: {row}")
                    continue
                except Exception as e:
                    errors += 1
                    logger.error(f"Row {row_num}: Unexpected error - {e}")
                    if errors <= 10:  # Show first 10 errors in detail
                        logger.error(f"Problematic row: {row}")
                    continue
        
        logger.info(f"\n" + "="*60)
        logger.info(f"✅ Import complete!")
        logger.info(f"\n📊 Statistics:")
        logger.info(f"   Imported: {imported:,}")
        logger.info(f"   Skipped: {skipped:,} (no player_id or player_name)")
        logger.info(f"   Errors: {errors:,}")
        total_processed = imported + errors + skipped
        success_rate = (imported * 100 // total_processed) if total_processed > 0 else 0
        logger.info(f"   Success rate: {success_rate}%")
        logger.info(f"="*60)
        
        # Show database stats
        stats = await db.get_database_stats()
        logger.info(f"\n💾 Database now has:")
        logger.info(f"   Total players: {stats['total_players']:,}")
        logger.info(f"   Total actions: {stats['total_actions']:,}")
        logger.info(f"   Currently online: {stats['online_count']:,}")
        
        # Show faction distribution
        logger.info(f"\n🏘️ Top 10 Factions by member count:")
        factions = await db.get_all_factions_with_counts()
        for i, faction in enumerate(factions[:10], 1):
            logger.info(f"   {i}. {faction['faction_name']}: {faction['member_count']} members ({faction['online_count']} online)")
        
    except FileNotFoundError:
        logger.error(f"❌ File not found: {csv_file_path}")
        logger.error("Make sure player_profiles.csv is in the same directory as this script")
        logger.error(f"Current working directory: {os.getcwd()}")
        logger.error(f"Files in current directory: {os.listdir('.')}")
    except Exception as e:
        logger.error(f"❌ Error during import: {e}", exc_info=True)


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'player_profiles.csv'
    
    logger.info(f"\n" + "="*60)
    logger.info(f"📥 CSV Player Profile Importer")
    logger.info(f"="*60)
    logger.info(f"CSV File: {csv_path}")
    logger.info(f"Working Directory: {os.getcwd()}")
    logger.info(f"Database Path: {Database().db_path}")
    logger.info(f"="*60 + "\n")
    
    asyncio.run(import_csv_profiles(csv_path))

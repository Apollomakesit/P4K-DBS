#!/usr/bin/env python3
"""
Import player_profiles.csv into the database
Handles special characters in player names
"""

import csv
import sys
from datetime import datetime
from database import Database
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def import_csv_profiles(csv_file_path: str = 'player_profiles.csv'):
    """Import player profiles from CSV file"""
    
    db = Database()
    imported = 0
    errors = 0
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
            # Try to auto-detect the delimiter
            sample = csvfile.read(1024)
            csvfile.seek(0)
            
            # Parse the CSV
            reader = csv.DictReader(csvfile)
            
            logger.info(f"CSV columns detected: {reader.fieldnames}")
            
            for row in reader:
                try:
                    # Parse datetime fields
                    last_connection = None
                    if row.get('last_connection'):
                        try:
                            last_connection = datetime.strptime(
                                row['last_connection'], 
                                '%Y-%m-%d %H:%M:%S'
                            )
                        except:
                            logger.warning(f"Could not parse last_connection: {row.get('last_connection')}")
                    
                    # Build profile dict
                    profile = {
                        'player_id': row.get('player_id', '').strip(),
                        'player_name': row.get('player_name', '').strip(),
                        'last_connection': last_connection or datetime.now(),
                        'is_online': bool(int(row.get('is_online', 0))),
                        'faction': row.get('faction', '').strip() if row.get('faction') != 'Civil' else None,
                        'faction_rank': None,  # Will be filled by faction scraper
                        'warns': int(row.get('warns', 0)) if row.get('warns') else 0,
                        'job': row.get('job', '').strip(),
                        'played_hours': float(row.get('played_hours', 0)) if row.get('played_hours') else None,
                        'age_ic': int(row.get('age_ic', 0)) if row.get('age_ic') else None,
                    }
                    
                    # Skip if no player_id
                    if not profile['player_id']:
                        continue
                    
                    # Save to database
                    await db.save_player_profile(profile)
                    imported += 1
                    
                    if imported % 100 == 0:
                        logger.info(f"Imported {imported} profiles...")
                        
                except Exception as e:
                    errors += 1
                    logger.error(f"Error importing row: {e}, Row: {row}")
                    continue
        
        logger.info(f"✅ Import complete! Imported: {imported}, Errors: {errors}")
        
        # Show stats
        stats = await db.get_database_stats()
        logger.info(f"Database now has {stats['total_players']} total players")
        
    except FileNotFoundError:
        logger.error(f"❌ File not found: {csv_file_path}")
        logger.error("Make sure player_profiles.csv is in the same directory as this script")
    except Exception as e:
        logger.error(f"❌ Error during import: {e}", exc_info=True)


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'player_profiles.csv'
    asyncio.run(import_csv_profiles(csv_path))

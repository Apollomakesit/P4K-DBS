#!/usr/bin/env python3
"""
Auto-import player_profiles.csv on first startup if database is empty
This ensures data persists across Railway redeployments
"""
import os
import asyncio
import logging
from database import Database

logger = logging.getLogger(__name__)

async def should_import_csv(db: Database) -> bool:
    """Check if we should import CSV (database is empty or very small)"""
    try:
        stats = await db.get_database_stats()
        total_players = stats.get('total_players', 0)
        
        # Import if we have fewer than 1000 players
        # (expected ~225k from CSV)
        if total_players < 1000:
            logger.info(f"📊 Current database has only {total_players:,} players")
            logger.info("📊 Will import CSV to populate database...")
            return True
        else:
            logger.info(f"📊 Database already has {total_players:,} players - skipping import")
            return False
    except Exception as e:
        logger.error(f"Error checking database stats: {e}")
        return False

async def import_csv_profiles_wrapper(csv_file_path: str = 'player_profiles.csv'):
    """Import player profiles from CSV file"""
    try:
        # Import the actual import function
        import sys
        import importlib.util
        
        # Load import_csv_profiles.py
        spec = importlib.util.spec_from_file_location("import_csv", csv_file_path.replace('.csv', '.py'))
        if spec and spec.loader:
            import_csv = importlib.util.module_from_spec(spec)
            sys.modules["import_csv"] = import_csv
            spec.loader.exec_module(import_csv)
            await import_csv.import_csv_profiles(csv_file_path)
        else:
            # Fallback to direct import
            from import_csv_profiles import import_csv_profiles
            await import_csv_profiles(csv_file_path)
    except Exception as e:
        logger.error(f"Error importing CSV: {e}", exc_info=True)
        raise

async def auto_import_on_startup():
    """Import CSV automatically on startup if needed"""
    try:
        logger.info("="*60)
        logger.info("🔍 CHECKING IF CSV IMPORT IS NEEDED")
        logger.info("="*60)
        
        db = Database()
        
        # Check if import is needed
        if not await should_import_csv(db):
            logger.info("✅ Database already populated, skipping CSV import")
            return
        
        # Check if CSV file exists in multiple locations
        csv_paths = [
            'player_profiles.csv',
            '/app/player_profiles.csv',
            os.path.join(os.path.dirname(__file__), 'player_profiles.csv'),
            '/data/player_profiles.csv'
        ]
        
        csv_file = None
        for path in csv_paths:
            if os.path.exists(path):
                csv_file = path
                break
        
        if not csv_file:
            logger.warning("⚠️ player_profiles.csv not found, skipping import")
            logger.warning(f"⚠️ Searched locations:")
            for path in csv_paths:
                logger.warning(f"   - {path}")
            logger.warning("⚠️ Database will start with current data - use /scan to add more")
            return
        
        logger.info("="*60)
        logger.info(f"🔄 IMPORTING PLAYER PROFILES FROM {csv_file}")
        logger.info("="*60)
        
        # Use the existing import function
        from import_csv_profiles import import_csv_profiles
        await import_csv_profiles(csv_file)
        
        # Verify import
        stats = await db.get_database_stats()
        logger.info("="*60)
        logger.info("✅ CSV IMPORT COMPLETED SUCCESSFULLY!")
        logger.info(f"📊 Database now has {stats.get('total_players', 0):,} players")
        logger.info("="*60)
        
    except Exception as e:
        logger.error("="*60)
        logger.error(f"❌ ERROR DURING AUTO-IMPORT: {e}")
        logger.error("="*60)
        logger.error("Full traceback:", exc_info=True)
        logger.warning("⚠️ Continuing with current database state...")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    asyncio.run(auto_import_on_startup())

async def should_import_csv(db: Database) -> bool:
    """Check if we should import CSV (database is empty or very small)"""
    try:
        # Check if import has already been done
        import_flag = '/data/.csv_imported' if os.path.exists('/data') else '.csv_imported'
        if os.path.exists(import_flag):
            logger.info("📊 CSV already imported (flag file exists) - skipping")
            return False
        
        stats = await db.get_database_stats()
        total_players = stats.get('total_players', 0)
        
        if total_players < 1000:
            logger.info(f"📊 Current database has only {total_players:,} players")
            logger.info("📊 Will import CSV to populate database...")
            return True
        else:
            logger.info(f"📊 Database already has {total_players:,} players - skipping import")
            # Create flag file to prevent future imports
            with open(import_flag, 'w') as f:
                f.write(f"Import completed at {datetime.now()}\n")
            return False
    except Exception as e:
        logger.error(f"Error checking database stats: {e}")
        return False

import asyncio
import sys
import os
from datetime import datetime
import json
import logging
from typing import List, Dict
from database import Database
from scraper import Pro4KingsScraper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('initial_scan.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

SCAN_STATE_FILE = 'scan_state.json'
DB_PATH = os.getenv('DATABASE_PATH', 'pro4kings.db')

class InitialScanner:
    """
    Ultra-fast initial scanner with:
    - Progress tracking and resumability
    - Concurrent scraping (50+ workers)
    - Real-time database updates
    - Smart player ID discovery
    """
    
    def __init__(self, db_path: str = DB_PATH, max_concurrent: int = 50):
        self.db = Database(db_path)
        self.max_concurrent = max_concurrent
        self.scan_state = self.load_scan_state()
        self.stats = {
            'total_players': 0,
            'players_scanned': 0,
            'players_skipped': 0,
            'online_found': 0,
            'offline_found': 0,
            'actions_recorded': 0,
            'start_time': None,
            'end_time': None,
            'errors': 0
        }
    
    def load_scan_state(self) -> Dict:
        """Load previous scan state if exists"""
        if os.path.exists(SCAN_STATE_FILE):
            try:
                with open(SCAN_STATE_FILE, 'r') as f:
                    state = json.load(f)
                logger.info(f"Loaded scan state: {state['scanned_count']} players already scanned")
                return state
            except Exception as e:
                logger.error(f"Error loading scan state: {e}")
        
        return {
            'last_player_id': None,
            'scanned_player_ids': [],
            'scanned_count': 0,
            'last_update': None,
            'completed': False
        }
    
    def save_scan_state(self):
        """Save current scan state for resumability"""
        self.scan_state['last_update'] = datetime.now().isoformat()
        try:
            with open(SCAN_STATE_FILE, 'w') as f:
                json.dump(self.scan_state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving scan state: {e}")
    
    async def process_player_profile(self, profile):
        """Process and save player profile to database"""
        try:
            if not profile:
                return
            
            profile_dict = {
                'player_id': profile.player_id,
                'player_name': profile.username,
                'is_online': profile.is_online,
                'last_connection': profile.last_seen,
                'faction': profile.faction,
                'faction_rank': profile.faction_rank,
                'job': profile.job,
                'level': profile.level,
                'respect_points': profile.respect_points,
                'warns': profile.warnings,
                'played_hours': profile.played_hours,
                'age_ic': profile.age_ic,
                'phone_number': profile.phone_number,
                'vehicles_count': profile.vehicles_count,
                'properties_count': profile.properties_count
            }
            
            # Save profile
            self.db.save_player_profile(profile_dict)
            
            # Update statistics
            self.stats['players_scanned'] += 1
            if profile.is_online:
                self.stats['online_found'] += 1
                # Add login event for online players
                self.db.save_login(profile.player_id, profile.username, datetime.now())
            else:
                self.stats['offline_found'] += 1
            
            # Update scan state
            self.scan_state['scanned_player_ids'].append(profile.player_id)
            self.scan_state['last_player_id'] = profile.player_id
            self.scan_state['scanned_count'] += 1
            
            # Save state periodically (every 50 players)
            if self.stats['players_scanned'] % 50 == 0:
                self.save_scan_state()
                self.db.save_scan_progress(
                    profile.player_id,
                    self.stats['players_scanned'],
                    False
                )
                self.print_progress()
            
        except Exception as e:
            logger.error(f"Error processing player {profile.player_id if profile else 'unknown'}: {e}")
            self.stats['errors'] += 1
    
    def print_progress(self):
        """Print current progress"""
        elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
        rate = self.stats['players_scanned'] / elapsed if elapsed > 0 else 0
        
        progress_bar = self.get_progress_bar(self.stats['players_scanned'], self.stats['total_players'])
        
        logger.info(f"""
╔════════════════════════════════════════════╗
║           SCAN PROGRESS                    ║
╠════════════════════════════════════════════╣
║ Players: {self.stats['players_scanned']:,} / {self.stats['total_players']:,} {progress_bar}
║ Online: {self.stats['online_found']:,}
║ Offline: {self.stats['offline_found']:,}
║ Errors: {self.stats['errors']:,}
║ Rate: {rate:.1f} players/sec
║ Elapsed: {elapsed:.0f}s ({elapsed/60:.1f} min)
╚════════════════════════════════════════════╝
        """)
    
    def get_progress_bar(self, current, total, length=20):
        """Generate ASCII progress bar"""
        if total == 0:
            return "[" + "=" * length + "]"
        
        filled = int((current / total) * length)
        bar = "=" * filled + "-" * (length - filled)
        percentage = (current / total) * 100
        return f"[{bar}] {percentage:.1f}%"
    
    async def discover_player_ids(self, scraper: Pro4KingsScraper) -> List[str]:
        """
        Discover all player IDs from various sources:
        1. Online players list
        2. Recent actions (extract IDs from actions)
        3. Sequential ID scanning (try ranges)
        """
        discovered_ids = set()
        
        logger.info("Phase 1: Discovering player IDs from online list...")
        online_players = await scraper.get_online_players()
        for player in online_players:
            discovered_ids.add(player['player_id'])
        logger.info(f"✓ Found {len(discovered_ids)} IDs from online players")
        
        logger.info("Phase 2: Discovering player IDs from recent actions...")
        actions = await scraper.get_latest_actions(limit=500)
        for action in actions:
            if action.player_id:
                discovered_ids.add(action.player_id)
            if action.target_player_id:
                discovered_ids.add(action.target_player_id)
        logger.info(f"✓ Total unique IDs: {len(discovered_ids)}")
        
        logger.info("Phase 3: Scanning ID range (this may take a while)...")
        # Most servers have sequential or semi-sequential IDs
        # Try to find valid ID ranges by sampling
        
        if discovered_ids:
            numeric_ids = [int(pid) for pid in discovered_ids if pid.isdigit()]
            if numeric_ids:
                min_id = min(numeric_ids)
                max_id = max(numeric_ids)
                logger.info(f"Detected ID range: {min_id} to {max_id}")
                
                # Sample every 100th ID to find the actual range
                sample_tasks = []
                sample_step = 100
                
                for test_id in range(max(1, min_id - 5000), max_id + 5000, sample_step):
                    sample_tasks.append(str(test_id))
                    if len(sample_tasks) >= 100:  # Limit sampling
                        break
                
                logger.info(f"Sampling {len(sample_tasks)} IDs to detect active range...")
                sample_results = await scraper.batch_get_profiles(sample_tasks, delay=0.05, concurrent=50)
                
                for profile in sample_results:
                    if profile:
                        discovered_ids.add(profile.player_id)
                
                logger.info(f"✓ After sampling: {len(discovered_ids)} unique IDs")
        
        return sorted(list(discovered_ids), key=lambda x: int(x) if x.isdigit() else 999999)
    
    async def scan_all_players(self):
        """
        Perform ultra-fast initial scan of all players
        - Uses concurrent workers
        - Saves progress for resumability
        """
        self.stats['start_time'] = datetime.now()
        logger.info("=" * 60)
        logger.info("STARTING ULTRA-FAST INITIAL SCAN")
        logger.info("=" * 60)
        
        async with Pro4KingsScraper(max_concurrent=self.max_concurrent) as scraper:
            # Step 1: Discover all player IDs
            logger.info("Phase 1: Discovering all player IDs...")
            all_player_ids = await self.discover_player_ids(scraper)
            self.stats['total_players'] = len(all_player_ids)
            logger.info(f"✓ Found {len(all_player_ids):,} total player IDs")
            
            # Step 2: Filter out already scanned players (for resume)
            scanned_set = set(self.scan_state['scanned_player_ids'])
            remaining_ids = [pid for pid in all_player_ids if pid not in scanned_set]
            
            if len(remaining_ids) < len(all_player_ids):
                logger.info(f"Resuming scan: {len(scanned_set):,} players already scanned")
                logger.info(f"Remaining: {len(remaining_ids):,} players")
            
            # Step 3: Scrape in optimized batches
            logger.info(f"\nPhase 2: Scraping {len(remaining_ids):,} players with {self.max_concurrent} workers...")
            
            batch_size = 100
            for i in range(0, len(remaining_ids), batch_size):
                batch = remaining_ids[i:i + batch_size]
                
                logger.info(f"Processing batch {i//batch_size + 1}/{(len(remaining_ids)-1)//batch_size + 1}...")
                profiles = await scraper.batch_get_profiles(batch, delay=0.1, concurrent=self.max_concurrent)
                
                for profile in profiles:
                    await self.process_player_profile(profile)
                
                # Small delay between batches
                await asyncio.sleep(0.5)
            
            # Finalize
            self.stats['end_time'] = datetime.now()
            self.scan_state['completed'] = True
            self.save_scan_state()
            self.db.save_scan_progress(
                self.scan_state['last_player_id'],
                self.stats['players_scanned'],
                True
            )
            
            self.print_final_report()
    
    def print_final_report(self):
        """Print final scan report"""
        elapsed = (self.stats['end_time'] - self.stats['start_time']).total_seconds()
        rate = self.stats['players_scanned'] / elapsed if elapsed > 0 else 0
        
        logger.info("\n" + "=" * 60)
        logger.info("SCAN COMPLETED!")
        logger.info("=" * 60)
        logger.info(f"""
╔════════════════════════════════════════════╗
║              FINAL REPORT                  ║
╠════════════════════════════════════════════╣
║ Total Players Found: {self.stats['total_players']:,}
║ Players Scanned: {self.stats['players_scanned']:,}
║ Players Skipped: {self.stats['players_skipped']:,}
║ Online Players: {self.stats['online_found']:,}
║ Offline Players: {self.stats['offline_found']:,}
║ Errors: {self.stats['errors']:,}
║
║ Time Taken: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)
║ Average Rate: {rate:.2f} players/second
║
║ Start Time: {self.stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}
║ End Time: {self.stats['end_time'].strftime('%Y-%m-%d %H:%M:%S')}
╚════════════════════════════════════════════╝
        """)
        logger.info("\n✅ All data has been saved to the database")
        logger.info(f"   Database: {DB_PATH}")
        logger.info("\n🚀 You can now start the bot with: python bot.py")

async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Ultra-fast initial scan of Pro4Kings players')
    parser.add_argument('--workers', type=int, default=50,
                        help='Number of concurrent workers (default: 50)')
    parser.add_argument('--reset', action='store_true',
                        help='Reset scan state and start from scratch')
    parser.add_argument('--db', type=str, default=DB_PATH,
                        help=f'Database path (default: {DB_PATH})')
    
    args = parser.parse_args()
    
    # Reset scan state if requested
    if args.reset and os.path.exists(SCAN_STATE_FILE):
        os.remove(SCAN_STATE_FILE)
        logger.info("Scan state reset")
    
    # Create scanner and run
    scanner = InitialScanner(db_path=args.db, max_concurrent=args.workers)
    
    try:
        await scanner.scan_all_players()
    except KeyboardInterrupt:
        logger.info("\n\n⚠️ Scan interrupted by user")
        logger.info("Progress has been saved. Run again to resume.")
        scanner.save_scan_state()
    except Exception as e:
        logger.error(f"\n\n❌ Fatal error: {e}", exc_info=True)
        scanner.save_scan_state()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())

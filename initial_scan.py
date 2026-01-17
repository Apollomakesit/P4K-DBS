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
START_ID = 1
END_ID = 230000

class FastScanner:
    """
    Optimized scanner: 230,000 profiles in ~2 hours
    Strategy: 20 concurrent workers, smart rate limiting
    """
    
    def __init__(self, db_path: str = DB_PATH, workers: int = 20):
        self.db = Database(db_path)
        self.workers = workers
        self.scan_state = self.load_scan_state()
        self.stats = {
            'total_scanned': 0,
            'found': 0,
            'not_found': 0,
            'errors': 0,
            'retries_503': 0,
            'start_time': None,
            'end_time': None
        }
        self.stats_lock = asyncio.Lock()
        self.backoff_level = 0  # Global backoff when 503 occurs
        self.backoff_lock = asyncio.Lock()
    
    def load_scan_state(self) -> Dict:
        """Load previous scan state"""
        if os.path.exists(SCAN_STATE_FILE):
            try:
                with open(SCAN_STATE_FILE, 'r') as f:
                    state = json.load(f)
                logger.info(f"Resuming from ID {state.get('last_id', START_ID)}")
                return state
            except Exception as e:
                logger.error(f"Error loading scan state: {e}")
        
        return {
            'last_id': START_ID - 1,
            'completed': False,
            'found_count': 0
        }
    
    def save_scan_state(self, last_id: int):
        """Save scan progress"""
        self.scan_state['last_id'] = last_id
        self.scan_state['completed'] = (last_id >= END_ID)
        self.scan_state['found_count'] = self.stats['found']
        try:
            with open(SCAN_STATE_FILE, 'w') as f:
                json.dump(self.scan_state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving scan state: {e}")
    
    async def increase_backoff(self):
        """Increase global backoff when 503 occurs"""
        async with self.backoff_lock:
            self.backoff_level = min(self.backoff_level + 1, 5)
            logger.warning(f"⚠️ Increasing backoff level to {self.backoff_level}")
    
    async def decrease_backoff(self):
        """Gradually decrease backoff when things are stable"""
        async with self.backoff_lock:
            if self.backoff_level > 0:
                self.backoff_level -= 1
    
    async def get_backoff_delay(self) -> float:
        """Get current backoff delay"""
        return 0.2 * (1.5 ** self.backoff_level)  # Exponential: 0.2, 0.3, 0.45, 0.67, 1.0, 1.5
    
    async def worker(self, worker_id: int, scraper: Pro4KingsScraper, player_ids: List[str]):
        """Worker coroutine to process player IDs"""
        for player_id in player_ids:
            try:
                # Get current backoff delay
                delay = await self.get_backoff_delay()
                
                profile = await scraper.get_player_profile(player_id)
                
                if profile:
                    # Save to database
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
                    self.db.save_player_profile(profile_dict)
                    
                    async with self.stats_lock:
                        self.stats['found'] += 1
                    
                    # Decrease backoff on success
                    if self.stats['total_scanned'] % 100 == 0:
                        await self.decrease_backoff()
                else:
                    async with self.stats_lock:
                        self.stats['not_found'] += 1
                
                async with self.stats_lock:
                    self.stats['total_scanned'] += 1
                
                # Rate limiting
                await asyncio.sleep(delay)
                
            except Exception as e:
                if '503' in str(e):
                    async with self.stats_lock:
                        self.stats['retries_503'] += 1
                    await self.increase_backoff()
                    logger.warning(f"Worker {worker_id}: 503 error, backing off...")
                    await asyncio.sleep(5)  # Extra delay on 503
                else:
                    async with self.stats_lock:
                        self.stats['errors'] += 1
                    logger.error(f"Worker {worker_id}: Error on ID {player_id}: {e}")
                    await asyncio.sleep(1)
    
    async def scan_parallel(self):
        """
        Parallel scan with dynamic rate limiting
        Target: ~2 hours for 230,000 profiles
        """
        self.stats['start_time'] = datetime.now()
        start_id = self.scan_state['last_id'] + 1
        
        logger.info("=" * 60)
        logger.info(f"FAST PARALLEL PROFILE SCANNER")
        logger.info(f"Range: {start_id:,} to {END_ID:,} ({END_ID - start_id + 1:,} profiles)")
        logger.info(f"Workers: {self.workers}")
        logger.info(f"Target Time: ~2 hours")
        logger.info("=" * 60)
        
        # Generate list of IDs to scan
        player_ids = [str(i) for i in range(start_id, END_ID + 1)]
        
        # Split IDs among workers
        chunk_size = len(player_ids) // self.workers
        id_chunks = [
            player_ids[i * chunk_size:(i + 1) * chunk_size if i < self.workers - 1 else None]
            for i in range(self.workers)
        ]
        
        async with Pro4KingsScraper(max_concurrent=self.workers) as scraper:
            # Progress reporting task
            progress_task = asyncio.create_task(self.report_progress(start_id))
            
            # Create worker tasks
            worker_tasks = [
                asyncio.create_task(self.worker(i, scraper, id_chunks[i]))
                for i in range(self.workers)
            ]
            
            try:
                # Wait for all workers to complete
                await asyncio.gather(*worker_tasks)
            except KeyboardInterrupt:
                logger.info("\n⚠️ Scan interrupted by user")
                for task in worker_tasks:
                    task.cancel()
                progress_task.cancel()
                raise
            finally:
                progress_task.cancel()
                self.save_scan_state(start_id + self.stats['total_scanned'])
        
        self.stats['end_time'] = datetime.now()
        self.save_scan_state(END_ID)
        self.print_final_report()
    
    async def report_progress(self, start_id: int):
        """Background task to report progress"""
        last_count = 0
        last_time = datetime.now()
        
        while True:
            await asyncio.sleep(30)  # Report every 30 seconds
            
            current_time = datetime.now()
            current_count = self.stats['total_scanned']
            
            # Calculate rate
            time_diff = (current_time - last_time).total_seconds()
            count_diff = current_count - last_count
            current_rate = count_diff / time_diff if time_diff > 0 else 0
            
            # Calculate overall stats
            elapsed = (current_time - self.stats['start_time']).total_seconds()
            overall_rate = current_count / elapsed if elapsed > 0 else 0
            
            # Calculate ETA
            remaining = END_ID - (start_id + current_count)
            eta_seconds = remaining / overall_rate if overall_rate > 0 else 0
            eta_hours = eta_seconds / 3600
            eta_minutes = (eta_seconds % 3600) / 60
            
            # Progress percentage
            progress = (current_count / (END_ID - start_id + 1)) * 100
            
            logger.info(f"""
╔════════════════════════════════════════════════════════════╗
║ PROGRESS: {progress:.1f}% ({current_count:,}/{END_ID - start_id + 1:,})
║ Found: {self.stats['found']:,} | Not Found: {self.stats['not_found']:,}
║ Errors: {self.stats['errors']:,} | 503 Retries: {self.stats['retries_503']:,}
║ 
║ Rate: {current_rate:.1f}/s (current) | {overall_rate:.1f}/s (avg)
║ Backoff Level: {self.backoff_level}/5
║ 
║ ETA: {int(eta_hours)}h {int(eta_minutes)}m
║ Elapsed: {int(elapsed/3600)}h {int((elapsed%3600)/60)}m
╚════════════════════════════════════════════════════════════╝
            """)
            
            last_count = current_count
            last_time = current_time
            
            # Save progress
            self.save_scan_state(start_id + current_count)
    
    def print_final_report(self):
        """Print final report"""
        elapsed = (self.stats['end_time'] - self.stats['start_time']).total_seconds()
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ SCAN COMPLETED!")
        logger.info("=" * 60)
        logger.info(f"""
Total Scanned: {self.stats['total_scanned']:,}
Found (exists): {self.stats['found']:,}
Not Found (404): {self.stats['not_found']:,}
Errors: {self.stats['errors']:,}
503 Retries: {self.stats['retries_503']:,}

Time: {int(elapsed/3600)}h {int((elapsed%3600)/60)}m
Average Rate: {self.stats['total_scanned']/elapsed:.2f} profiles/sec

Database now contains {self.stats['found']:,} player profiles!
        """)

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Fast scanner for Pro4Kings profiles')
    parser.add_argument('--workers', type=int, default=20,
                        help='Number of concurrent workers (default: 20)')
    parser.add_argument('--reset', action='store_true',
                        help='Reset scan state and start from ID 1')
    
    args = parser.parse_args()
    
    if args.reset and os.path.exists(SCAN_STATE_FILE):
        os.remove(SCAN_STATE_FILE)
        logger.info("Scan state reset")
    
    scanner = FastScanner(workers=args.workers)
    
    try:
        await scanner.scan_parallel()
    except KeyboardInterrupt:
        logger.info("\n\n⚠️ Scan interrupted - progress saved")
        logger.info(f"Run again to resume from ID {scanner.scan_state['last_id']}")
    except Exception as e:
        logger.error(f"\n\n❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os
from database import Database
from scraper import Pro4KingsScraper
from datetime import datetime

async def main():
    db = Database(os.getenv('DATABASE_URL', 'sqlite:///pro4kings.db'))
    scraper = Pro4KingsScraper()
    
    # Configuration for fast scanning
    MAX_PLAYER_ID = 223797
    CONCURRENT_WORKERS = 20  # 20 concurrent requests
    BATCH_SIZE = 100  # Process 100 IDs per batch
    DELAY_BETWEEN_BATCHES = 0.1  # Minimal delay
    SAVE_INTERVAL = 1000  # Save progress every 1000 profiles
    
    # Get last scanned ID to resume from
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(player_id) as last_id FROM player_profiles')
        result = cursor.fetchone()
        start_id = result['last_id'] + 1 if result['last_id'] else 1
    
    print(f"🚀 Starting fast scan from ID {start_id} to {MAX_PLAYER_ID}")
    print(f"⚙️ Using {CONCURRENT_WORKERS} concurrent workers")
    print(f"📊 Expected rate: ~1000 players/minute\n")
    
    total_scanned = 0
    total_found = 0
    start_time = datetime.now()
    
    for batch_start in range(start_id, MAX_PLAYER_ID + 1, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, MAX_PLAYER_ID + 1)
        player_ids = list(range(batch_start, batch_end))
        
        # Fetch profiles with high concurrency
        profiles = await scraper.batch_get_profiles(
            player_ids, 
            delay=0.05,  # Very short delay between batches
            concurrent=CONCURRENT_WORKERS
        )
        
        # Save valid profiles
        valid_profiles = [p for p in profiles if p]
        for profile in valid_profiles:
            db.save_player_profile(profile)
            total_found += 1
        
        total_scanned += len(player_ids)
        
        # Progress reporting
        if total_scanned % SAVE_INTERVAL == 0 or batch_end >= MAX_PLAYER_ID:
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = total_scanned / elapsed * 60 if elapsed > 0 else 0
            progress_pct = (total_scanned / MAX_PLAYER_ID) * 100
            
            print(f"📊 Progress: {total_scanned:,}/{MAX_PLAYER_ID:,} ({progress_pct:.2f}%)")
            print(f"✓ Valid profiles found: {total_found:,}")
            print(f"⚡ Scan rate: {rate:.0f} players/minute")
            print(f"⏱️ Elapsed: {elapsed/60:.1f} minutes")
            
            # Estimate time remaining
            if rate > 0:
                remaining = MAX_PLAYER_ID - total_scanned
                eta_minutes = remaining / rate
                print(f"🕐 ETA: {eta_minutes:.1f} minutes\n")
        
        # Small delay between batches
        await asyncio.sleep(DELAY_BETWEEN_BATCHES)
    
    # Mark scan as complete
    db.mark_scan_complete()
    
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n✅ Initial scan complete!")
    print(f"📊 Total scanned: {total_scanned:,} IDs")
    print(f"✓ Valid profiles: {total_found:,}")
    print(f"⏱️ Total time: {elapsed/60:.1f} minutes")
    print(f"⚡ Average rate: {total_scanned / elapsed * 60:.0f} players/minute")

if __name__ == '__main__':
    asyncio.run(main())

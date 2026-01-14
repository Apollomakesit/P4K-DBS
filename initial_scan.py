import asyncio
from scraper import Pro4KingsScraper
from database import Database
import os

async def fast_initial_scan(start_id=1, end_id=223797, batch_size=50, concurrent=20):
    """
    Fast initial scan using concurrent workers
    
    Args:
        start_id: Starting player ID
        end_id: Ending player ID
        batch_size: Number of profiles to fetch before saving
        concurrent: Number of concurrent requests
    """
    db = Database(os.getenv('DATABASE_URL', 'sqlite:///pro4kings.db'))
    scraper = Pro4KingsScraper()
    
    print(f"🚀 Starting fast initial scan from ID {start_id} to {end_id}")
    print(f"⚙️ Settings: batch_size={batch_size}, concurrent={concurrent}")
    
    total_scanned = 0
    total_found = 0
    
    # Process in large batches
    for batch_start in range(start_id, end_id + 1, batch_size):
        batch_end = min(batch_start + batch_size, end_id + 1)
        player_ids = list(range(batch_start, batch_end))
        
        print(f"\n📦 Processing batch: {batch_start} to {batch_end-1}")
        
        # Fetch profiles with concurrent workers
        results = await scraper.batch_get_profiles(player_ids, delay=0.1, concurrent=concurrent)
        
        # Save to database
        for profile in results:
            if profile:
                db.save_player_profile(profile)
                total_found += 1
        
        total_scanned += len(player_ids)
        
        progress = (total_scanned / (end_id - start_id + 1)) * 100
        print(f"✅ Batch complete: Found {len(results)}/{len(player_ids)} profiles")
        print(f"📊 Progress: {total_scanned:,}/{end_id-start_id+1:,} ({progress:.2f}%) | Found: {total_found:,} profiles")
        
        # Short delay between batches
        await asyncio.sleep(0.5)
    
    # Mark scan as complete
    db.mark_scan_complete()
    print(f"\n🎉 Initial scan complete!")
    print(f"📈 Total scanned: {total_scanned:,} IDs")
    print(f"✅ Total found: {total_found:,} profiles")
    print(f"📊 Success rate: {(total_found/total_scanned)*100:.2f}%")

if __name__ == '__main__':
    # Run the scan
    # Adjust parameters based on your needs:
    # - Higher concurrent = faster but more server load
    # - Lower delay = faster but might hit rate limits
    asyncio.run(fast_initial_scan(
        start_id=1,
        end_id=223797,
        batch_size=100,     # Fetch 100 profiles per batch
        concurrent=20       # 20 concurrent requests
    ))

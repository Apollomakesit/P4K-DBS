import asyncio
from initial_scan import BulkProfileScraper
from database import Database
import os

async def resume_scan():
    db = Database(os.getenv('DATABASE_URL', 'sqlite:///pro4kings.db'))
    
    progress = db.get_scan_progress()
    print(f"Current progress: {progress['total_scanned']}/{progress['total_target']} profiles")
    print(f"Percentage: {progress['percentage']:.1f}%")
    print()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(player_id) as max_id FROM player_profiles')
        result = cursor.fetchone()
        start_id = result['max_id'] + 1 if result['max_id'] else 1
    
    print(f"Resuming from ID: {start_id}")
    print()
    
    scraper = BulkProfileScraper(num_workers=30)
    await scraper.scan_all_profiles(start_id=start_id, end_id=223797)
    
    db.mark_scan_complete()
    print("\n✅ Initial scan marked as complete!")

if __name__ == '__main__':
    asyncio.run(resume_scan())

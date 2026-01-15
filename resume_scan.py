import asyncio
from scraper import Pro4KingsScraper
from database import Database
from initial_scan import main as scan_main
import os

async def resume_scan():
    """Resume scan from where it left off"""
    db = Database(os.getenv('DATABASE_URL', 'sqlite:///pro4kings.db'))
    scraper = Pro4KingsScraper()
    
    # Get current progress
    progress = db.get_scan_progress()
    print(f"📊 Current progress: {progress['total_scanned']:,} profiles scanned")
    
    # Find the highest ID scanned
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(player_id) as max_id FROM player_profiles')
        result = cursor.fetchone()
        last_id = result['max_id'] if result and result['max_id'] else 0
    
    print(f"🔄 Resuming from ID: {last_id + 1}")
    
    # Import and run fast scanner
    from initial_scan import fast_initial_scan
    await fast_initial_scan(
        start_id=last_id + 1,
        end_id=223797,
        batch_size=100,
        concurrent=20
    )

if __name__ == '__main__':
    print("🔄 Resuming initial scan from last saved progress...")
    print("💡 The scan will automatically continue from where it left off\n")
    asyncio.run(scan_main())


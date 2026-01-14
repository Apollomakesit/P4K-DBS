import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime
import re
from database import Database
import os

class BulkProfileScraper:
    def __init__(self, num_workers=30):
        self.base_url = "https://panel.pro4kings.ro/profile"
        self.num_workers = num_workers
        self.db = Database(os.getenv('DATABASE_URL', 'sqlite:///pro4kings.db'))
        self.total_scraped = 0
        self.total_failed = 0
        
    async def get_player_profile(self, player_id, session):
        url = f"{self.base_url}/{player_id}"
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 404:
                    return None
                    
                if response.status != 200:
                    return None
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                name_elem = soup.select_one('h4.card-title')
                if not name_elem:
                    return None
                
                player_name = name_elem.get_text(strip=True)
                player_name = re.sub(r'^\s*[•●]\s*', '', player_name)
                player_name = re.sub(r'\s*\(Online\)|\(Offline\)', '', player_name, flags=re.IGNORECASE)
                
                is_online = bool(name_elem.find('i', class_='text-success'))
                
                table = soup.find('table', class_='table')
                if not table:
                    return None
                
                last_connection = None
                faction = None
                faction_rank = None
                warns = None
                job = None
                played_hours = None
                age_ic = None
                
                for row in table.find_all('tr'):
                    header = row.find('th')
                    data_cell = row.find('td')
                    
                    if not header or not data_cell:
                        continue
                    
                    header_text = header.get_text(strip=True)
                    data_text = data_cell.get_text(strip=True)
                    
                    if 'Ultima conectare' in header_text:
                        try:
                            last_connection = datetime.strptime(data_text, '%d/%m/%Y %H:%M:%S')
                        except:
                            pass
                    elif 'Facțiune' in header_text or 'Factiune' in header_text:
                        if 'Rank' not in header_text:
                            faction = data_text
                    elif 'Rank Facțiune' in header_text or 'Rank Factiune' in header_text:
                        rank_link = data_cell.find('a')
                        faction_rank = rank_link.get_text(strip=True) if rank_link else data_text
                        if faction_rank:
                            faction_rank = ' '.join(faction_rank.split())
                    elif 'Warn' in header_text:
                        try:
                            warns = int(re.search(r'\d+', data_text).group())
                        except:
                            warns = 0
                    elif 'Job' in header_text:
                        job = data_text
                    elif 'Ore jucate' in header_text:
                        try:
                            played_hours = int(re.search(r'\d+', data_text).group())
                        except:
                            played_hours = 0
                    elif 'Vârsta IC' in header_text or 'Varsta IC' in header_text:
                        try:
                            age_ic = int(re.search(r'\d+', data_text).group())
                        except:
                            pass
                
                return {
                    'player_id': player_id,
                    'player_name': player_name,
                    'last_connection': last_connection,
                    'is_online': is_online,
                    'faction': faction,
                    'faction_rank': faction_rank,
                    'warns': warns,
                    'job': job,
                    'played_hours': played_hours,
                    'age_ic': age_ic
                }
        except:
            return None
    
    async def worker(self, worker_id, queue):
        connector = aiohttp.TCPConnector(limit_per_host=10)
        async with aiohttp.ClientSession(connector=connector) as session:
            while True:
                try:
                    player_id = await queue.get()
                    
                    if player_id is None:
                        queue.task_done()
                        break
                    
                    result = await self.get_player_profile(player_id, session)
                    
                    if result:
                        self.db.save_player_profile(result)
                        self.total_scraped += 1
                        
                        if self.total_scraped % 100 == 0:
                            print(f"[Worker {worker_id}] ✓ {self.total_scraped} profiles scraped")
                    else:
                        self.total_failed += 1
                    
                    queue.task_done()
                    await asyncio.sleep(0.3)
                    
                except Exception as e:
                    queue.task_done()
    
    async def scan_all_profiles(self, start_id=1, end_id=223797):
        print(f"🚀 Starting initial scan: ID {start_id} to {end_id}")
        print(f"👷 Using {self.num_workers} concurrent workers")
        print(f"⏱️  Estimated time: ~{((end_id - start_id + 1) * 0.3) / self.num_workers / 3600:.1f} hours")
        print()
        
        queue = asyncio.Queue()
        for player_id in range(start_id, end_id + 1):
            await queue.put(player_id)
        
        for _ in range(self.num_workers):
            await queue.put(None)
        
        start_time = datetime.now()
        workers = [asyncio.create_task(self.worker(i + 1, queue)) for i in range(self.num_workers)]
        
        await queue.join()
        await asyncio.gather(*workers)
        
        duration = datetime.now() - start_time
        
        print()
        print("=" * 60)
        print("✅ INITIAL SCAN COMPLETE!")
        print(f"✓ Successfully scraped: {self.total_scraped} profiles")
        print(f"✗ Failed/Not found: {self.total_failed} profiles")
        print(f"⏱️  Duration: {duration}")
        print(f"⚡ Average speed: {self.total_scraped / duration.total_seconds():.1f} profiles/second")
        print("=" * 60)

async def main():
    scraper = BulkProfileScraper(num_workers=30)
    await scraper.scan_all_profiles(start_id=1, end_id=223797)

if __name__ == '__main__':
    print("=" * 60)
    print("PRO4KINGS INITIAL PROFILE SCAN")
    print("=" * 60)
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Scan interrupted by user")

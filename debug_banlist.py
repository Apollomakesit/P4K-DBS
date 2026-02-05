#!/usr/bin/env python3
"""Debug banlist HTML structure"""
import asyncio
from scraper import Pro4KingsScraper
from bs4 import BeautifulSoup

async def main():
    async with Pro4KingsScraper(max_concurrent=1) as scraper:
        html = await scraper.fetch_page(f"{scraper.base_url}/banlist?pageBanList=1&search=")
        
        if not html:
            print("Failed to fetch")
            return
        
        # Save to file
        with open('/tmp/banlist.html', 'w') as f:
            f.write(html)
        print("Saved to /tmp/banlist.html")
        
        # Parse
        soup = BeautifulSoup(html, 'lxml')
        tables = soup.find_all('table')
        print(f"Found {len(tables)} tables")
        
        for i, table in enumerate(tables):
            print(f"\nTable {i+1}: class={table.get('class')}")
            rows = table.find_all('tr')
            print(f"  Rows: {len(rows)}")
            if rows:
                print(f"  First row cells: {len(rows[0].find_all(['td', 'th']))}")

asyncio.run(main())

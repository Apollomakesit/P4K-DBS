#!/usr/bin/env python3
"""
Debug script to inspect banlist HTML structure
"""

import asyncio
import sys
from bs4 import BeautifulSoup
from scraper import Pro4KingsScraper

async def debug_banlist():
    print("🔍 Fetching banlist HTML to inspect structure...")
    
    async with Pro4KingsScraper(max_concurrent=1) as scraper:
        url = f"{scraper.base_url}/banlist?pageBanList=1&search="
        print(f"Fetching: {url}")
        
        html = await scraper.fetch_page(url)
        
        if not html:
            print("❌ Failed to fetch HTML")
            return
        
        # Save HTML to file for inspection
        with open('/tmp/banlist.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print("✅ Saved HTML to /tmp/banlist.html")
        
        # Parse and analyze
        soup = BeautifulSoup(html, 'lxml')
        
        # Look for tables
        tables = soup.find_all('table')
        print(f"\n📊 Found {len(tables)} table(s)")
        
        for i, table in enumerate(tables):
            print(f"\nTable {i+1}:")
            print(f"  Classes: {table.get('class', [])}")
            print(f"  ID: {table.get('id', 'none')}")
            
            rows = table.find_all('tr')
            print(f"  Rows: {len(rows)}")
            
            if rows:
                # Show first row (likely header)
                first_row = rows[0]
                headers = [th.get_text(strip=True) for th in first_row.find_all(['th', 'td'])]
                print(f"  Headers/First row: {headers}")
                
                # Show second row (first data row)
                if len(rows) > 1:
                    second_row = rows[1]
                    cells = [td.get_text(strip=True)[:50] for td in second_row.find_all('td')]
                    print(f"  First data row: {cells}")
        
        # Look for divs that might contain ban info
        ban_divs = soup.find_all('div', class_=lambda x: x and 'ban' in x.lower() if x else False)
        print(f"\n📦 Found {len(ban_divs)} div(s) with 'ban' in class name")
        
        # Look for cards
        cards = soup.find_all('div', class_=lambda x: x and 'card' in x.lower() if x else False)
        print(f"📦 Found {len(cards)} div(s) with 'card' in class name")
        
        # Show page title
        title = soup.find('title')
        if title:
            print(f"\n📄 Page title: {title.get_text(strip=True)}")
        
        # Look for main content area
        main_content = soup.find('main') or soup.find('div', class_='content')
        if main_content:
            print(f"\n📄 Main content area found")
            # Print first 500 chars
            text = main_content.get_text(strip=True)[:500]
            print(f"  Content preview: {text}")

if __name__ == "__main__":
    asyncio.run(debug_banlist())

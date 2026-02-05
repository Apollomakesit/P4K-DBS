#!/usr/bin/env python3
"""
Test banned players scraper to verify it can fetch from the website
"""

import asyncio
import sys
from scraper import Pro4KingsScraper


async def test_banned_scraper():
    print("🔍 Testing banned players scraper...")

    async with Pro4KingsScraper(max_concurrent=5) as scraper:
        print("📄 Fetching banned players from all pages...")
        banned = await scraper.get_banned_players_all_pages()

        print(f"\n✅ Found {len(banned)} total banned players")

        if banned:
            print(f"\n📋 First 5 bans:")
            for ban in banned[:5]:
                print(f"  - {ban.get('player_name')} (ID: {ban.get('player_id')})")
                print(f"    Admin: {ban.get('admin')}")
                print(f"    Reason: {ban.get('reason')}")
                print(f"    Duration: {ban.get('duration')}")
                print(f"    Ban Date: {ban.get('ban_date')}")
                print()

        # Check for active vs expired
        active_count = len([b for b in banned if b.get("player_id")])
        print(f"\n📊 Stats:")
        print(f"  Total bans: {len(banned)}")
        print(f"  With player_id: {active_count}")

        return banned


if __name__ == "__main__":
    banned = asyncio.run(test_banned_scraper())
    sys.exit(0 if banned else 1)

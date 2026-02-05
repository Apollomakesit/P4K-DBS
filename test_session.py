#!/usr/bin/env python3
"""Test if we need session/cookies to access banlist"""
import asyncio
import aiohttp
from scraper import Pro4KingsScraper


async def test_with_session():
    async with Pro4KingsScraper(max_concurrent=1) as scraper:
        # First visit main page to set cookies
        print("1. Visiting main page...")
        main_html = await scraper.fetch_page(f"{scraper.base_url}/")

        if main_html:
            print(f"   ✓ Got main page ({len(main_html)} bytes)")

        # Now try banlist
        print("\n2. Visiting banlist page...")
        await asyncio.sleep(2)  # Wait a bit

        banlist_html = await scraper.fetch_page(
            f"{scraper.base_url}/banlist?pageBanList=1&search="
        )

        if banlist_html:
            print(f"   ✓ Got banlist ({len(banlist_html)} bytes)")

            # Check content
            if "Un moment" in banlist_html:
                print("   ⚠️  Still getting challenge page")
            elif "<table" in banlist_html:
                print("   ✓ Has table!")
                # Save for inspection
                with open("/tmp/banlist2.html", "w") as f:
                    f.write(banlist_html)
                print("   Saved to /tmp/banlist2.html")
            else:
                print("   ⚠️  Unknown content")
                with open("/tmp/banlist2.html", "w") as f:
                    f.write(banlist_html)


asyncio.run(test_with_session())

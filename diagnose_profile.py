#!/usr/bin/env python3
"""
Diagnostic script to inspect HTML structure from Pro4Kings profile page
Run this to debug scraper issues with username and age_ic extraction
"""
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re

async def diagnose_profile(player_id: str = "155733"):
    """Fetch and analyze profile HTML structure"""
    url = f"https://panel.pro4kings.ro/profile/{player_id}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
    }

    timeout = aiohttp.ClientTimeout(total=15, connect=5)

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as client:
        try:
            async with client.get(url, ssl=False) as response:
                print(f"Status: {response.status}")

                if response.status != 200:
                    print(f"ERROR: Got status {response.status}")
                    return

                html = await response.text()
                print(f"HTML length: {len(html)} characters\n")

                soup = BeautifulSoup(html, "lxml")

                # Analyze title structure
                print("=" * 50)
                print("TITLE ANALYSIS (USERNAME):")
                print("=" * 50)

                card_titles = soup.select("h4.card-title")
                print(f"Found {len(card_titles)} h4.card-title elements")
                for i, ct in enumerate(card_titles[:3]):
                    print(f"\n[{i}] h4.card-title:")
                    print(f"  Full HTML: {ct}")
                    print(f"  Text: {ct.get_text(strip=True)}")
                    font_tag = ct.find("font")
                    if font_tag:
                        print(f"  Font tag: {font_tag}")
                        print(f"  Font text: {font_tag.get_text(strip=True)}")

                # Try all .card-title
                all_titles = soup.select(".card-title")
                print(f"\nFound {len(all_titles)} .card-title elements")
                for i, ct in enumerate(all_titles[:3]):
                    print(f"\n[{i}] .card-title:")
                    print(f"  Tag: {ct.name}")
                    print(f"  Text: {ct.get_text(strip=True)}")

                # Analyze table structure for Age IC
                print("\n" + "=" * 50)
                print("TABLE ANALYSIS (ALL PROFILE DATA):")
                print("=" * 50)

                table_headers = soup.find_all("th", attrs={"scope": "row"})
                print(f"Found {len(table_headers)} th[scope=row] elements")

                for i, th in enumerate(table_headers):
                    key = th.get_text(strip=True)
                    td = th.find_next_sibling("td")
                    val = td.get_text(strip=True) if td else "N/A"
                    print(f"  [{i}] {key}: {val}")

                # Look for age specifically
                print("\n" + "=" * 50)
                print("SEARCHING FOR AGE/VÂRSTA:")
                print("=" * 50)

                age_patterns = [
                    re.compile(r"v[aă]rst[aă].*ic", re.IGNORECASE),
                    re.compile(r"age.*ic", re.IGNORECASE),
                    re.compile(r"v[aă]rst[aă]", re.IGNORECASE),
                ]

                for pattern in age_patterns:
                    matches = soup.find_all(text=pattern)
                    print(f"\nPattern {pattern.pattern}: {len(matches)} matches")
                    for match in matches[:3]:
                        parent = match.parent
                        print(f"  Found in <{parent.name}>: {match}")
                        if parent.name == "th":
                            td = parent.find_next_sibling("td")
                            if td:
                                print(f"    Value: {td.get_text(strip=True)}")

                # Save sample HTML for inspection
                print("\n" + "=" * 50)
                print("SAVING SAMPLE HTML")
                print("=" * 50)

                with open("profile_sample.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("✅ Saved to: profile_sample.html")

                # Show first 500 chars of body
                body = soup.find("body")
                if body:
                    body_text = body.get_text()[:500]
                    print(f"\nBody preview (first 500 chars):\n{body_text}")

        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(diagnose_profile())

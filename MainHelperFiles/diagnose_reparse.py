"""Diagnostic script to test the reparse flow directly"""

import asyncio
import sys
from datetime import datetime
from database import Database
from scraper import Pro4KingsScraper
from config import Config


async def diagnose_reparse():
    """Test reparse flow with actual database data"""

    # Initialize database
    db = Database(Config.DATABASE_PATH)
    db.migrate()

    # Get some unknown actions from database
    print("🔍 Querying database for unknown actions...")
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, player_id, player_name, action_type, action_detail,
                   timestamp, raw_text, item_name, item_quantity,
                   target_player_id, target_player_name,
                   admin_id, admin_name, warning_count, reason
            FROM actions
            WHERE action_type IN ('unknown', 'other', 'legacy_multi_action')
            LIMIT 20
        """
        )

        unknown_actions = [dict(row) for row in cursor.fetchall()]

    if not unknown_actions:
        print("❌ No unknown actions in database!")
        return

    print(f"✅ Found {len(unknown_actions)} unknown actions\n")
    print("=" * 80)

    # Initialize scraper
    print("\n📡 Initializing scraper...")
    async with Pro4KingsScraper(max_concurrent=1) as scraper:
        reparsed = 0
        still_unknown = 0

        for i, action in enumerate(unknown_actions, 1):
            raw_text = action.get("raw_text")
            timestamp = action.get("timestamp")
            action_id = action.get("id")

            if not raw_text:
                print(f"  [{i}] ❌ Action {action_id}: No raw_text field!")
                still_unknown += 1
                continue

            # Parse timestamp
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp)
                except:
                    timestamp = datetime.now()

            print(f"\n  [{i}] Action ID: {action_id}")
            print(f"      Current type: {action.get('action_type')}")
            print(f"      Raw text: {raw_text[:100]}...")

            # Try to parse
            try:
                parsed = scraper._parse_action_text(raw_text, timestamp)

                if not parsed:
                    print(f"      ❌ Parser returned None")
                    still_unknown += 1
                    continue

                new_type = parsed.action_type

                if new_type in ("unknown", "other", "legacy_multi_action"):
                    print(f"      ⚠️  Re-parsed to '{new_type}' (still unknown)")
                    still_unknown += 1
                else:
                    print(f"      ✅ Re-parsed to '{new_type}'")
                    reparsed += 1

            except Exception as e:
                print(f"      ❌ Error: {e}")
                still_unknown += 1

        print("\n" + "=" * 80)
        print(f"\n📊 SUMMARY:")
        print(f"  ✅ Successfully re-parsed: {reparsed}/{len(unknown_actions)}")
        print(f"  ⚠️  Still unknown: {still_unknown}/{len(unknown_actions)}")

        if reparsed == 0 and len(unknown_actions) > 0:
            print("\n🔴 WARNING: No actions were successfully re-parsed!")
            print("   This suggests the scraper patterns need updating.")
        elif reparsed > 0:
            print(
                f"\n✅ SUCCESS: {reparsed} actions can be re-parsed with current patterns!"
            )


if __name__ == "__main__":
    asyncio.run(diagnose_reparse())

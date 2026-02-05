#!/usr/bin/env python3
"""
Re-parse Unknown Actions Migration Script

This script re-parses actions that were previously categorized as 'unknown', 'other',
or 'legacy_multi_action' using the latest scraper patterns. When new parsing methods
are added to scraper.py, run this to automatically recategorize old actions.

Usage:
    python reparse_unknown_actions.py                # Dry run (preview)
    python reparse_unknown_actions.py --execute      # Actually update database
    python reparse_unknown_actions.py --type unknown # Only reparse 'unknown' type
"""

import asyncio
import sys
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from database import Database
from scraper import Pro4KingsScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("reparse_unknown.log"), logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "data/pro4kings.db")


class UnknownActionsReparser:
    """Re-parse unknown actions using updated scraper patterns"""

    def __init__(self, db_path: str = DB_PATH):
        self.db = Database(db_path)
        self.stats = {
            "total_unknown": 0,
            "re_parsed": 0,
            "still_unknown": 0,
            "errors": 0,
            "by_new_type": {},
        }

    async def get_unknown_actions(
        self, action_type_filter: Optional[str] = None
    ) -> List[Dict]:
        """Get all unknown/other/legacy actions from database"""

        def _get_unknown_sync():
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                if action_type_filter:
                    cursor.execute(
                        """
                        SELECT id, player_id, player_name, action_type, action_detail,
                               timestamp, raw_text
                        FROM actions
                        WHERE action_type = ?
                        ORDER BY timestamp DESC
                    """,
                        (action_type_filter,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, player_id, player_name, action_type, action_detail,
                               timestamp, raw_text
                        FROM actions
                        WHERE action_type IN ('unknown', 'other', 'legacy_multi_action')
                        ORDER BY timestamp DESC
                    """
                    )

                return [dict(row) for row in cursor.fetchall()]

        return await asyncio.to_thread(_get_unknown_sync)

    async def reparse_action(
        self, action: Dict, scraper: Pro4KingsScraper
    ) -> Optional[Dict]:
        """Re-parse a single action using current scraper logic"""
        try:
            raw_text = action.get("raw_text")
            timestamp = action.get("timestamp")

            if not raw_text:
                logger.warning(f"Action {action['id']} has no raw_text - skipping")
                return None

            # Parse timestamp if string
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp)
                except:
                    timestamp = datetime.now()

            # Use scraper's _parse_action_text method
            parsed = scraper._parse_action_text(raw_text, timestamp)

            if not parsed:
                return None

            # Check if action type changed from unknown/other
            old_type = action.get("action_type")
            new_type = parsed.action_type

            if new_type in ("unknown", "other", "legacy_multi_action"):
                # Still unknown - no improvement
                return None

            if new_type == old_type:
                # Same type - no change needed
                return None

            # Successfully re-parsed to a recognized type!
            return {
                "id": action["id"],
                "old_type": old_type,
                "new_type": new_type,
                "player_id": parsed.player_id,
                "player_name": parsed.player_name,
                "action_detail": parsed.action_detail,
                "item_name": parsed.item_name,
                "item_quantity": parsed.item_quantity,
                "target_player_id": parsed.target_player_id,
                "target_player_name": parsed.target_player_name,
                "admin_id": parsed.admin_id,
                "admin_name": parsed.admin_name,
                "warning_count": parsed.warning_count,
                "reason": parsed.reason,
            }

        except Exception as e:
            logger.error(f"Error re-parsing action {action.get('id')}: {e}")
            self.stats["errors"] += 1
            return None

    async def update_action_in_db(self, update_data: Dict) -> bool:
        """Update action in database with new parsed data"""

        def _update_sync():
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        UPDATE actions
                        SET action_type = ?,
                            player_id = ?,
                            player_name = ?,
                            action_detail = ?,
                            item_name = ?,
                            item_quantity = ?,
                            target_player_id = ?,
                            target_player_name = ?,
                            admin_id = ?,
                            admin_name = ?,
                            warning_count = ?,
                            reason = ?
                        WHERE id = ?
                    """,
                        (
                            update_data["new_type"],
                            update_data["player_id"],
                            update_data["player_name"],
                            update_data["action_detail"],
                            update_data["item_name"],
                            update_data["item_quantity"],
                            update_data["target_player_id"],
                            update_data["target_player_name"],
                            update_data["admin_id"],
                            update_data["admin_name"],
                            update_data["warning_count"],
                            update_data["reason"],
                            update_data["id"],
                        ),
                    )

                    conn.commit()
                    return True

            except Exception as e:
                logger.error(f"Error updating action {update_data['id']}: {e}")
                return False

        return await asyncio.to_thread(_update_sync)

    async def run(
        self, dry_run: bool = True, action_type_filter: Optional[str] = None
    ) -> Dict:
        """Run the re-parsing process"""
        logger.info("=" * 60)
        logger.info("🔄 RE-PARSING UNKNOWN ACTIONS")
        logger.info("=" * 60)

        if dry_run:
            logger.info("🔍 DRY RUN MODE - No database changes will be made")
        else:
            logger.info("✅ EXECUTE MODE - Database will be updated")

        if action_type_filter:
            logger.info(f"📋 Filter: Only re-parsing '{action_type_filter}' actions")
        else:
            logger.info("📋 Filter: All unknown/other/legacy actions")

        logger.info("=" * 60)

        # Get all unknown actions
        unknown_actions = await self.get_unknown_actions(action_type_filter)
        self.stats["total_unknown"] = len(unknown_actions)

        if not unknown_actions:
            logger.info("✅ No unknown actions found - database is clean!")
            return self.stats

        logger.info(f"Found {len(unknown_actions)} unknown actions to re-parse")

        # Create scraper instance for parsing only (no network requests)
        async with Pro4KingsScraper(max_concurrent=1) as scraper:
            updates_to_apply = []

            for i, action in enumerate(unknown_actions, 1):
                if i % 100 == 0:
                    logger.info(f"Progress: {i}/{len(unknown_actions)}...")

                update_data = await self.reparse_action(action, scraper)

                if update_data:
                    updates_to_apply.append(update_data)

                    # Track stats
                    new_type = update_data["new_type"]
                    self.stats["by_new_type"][new_type] = (
                        self.stats["by_new_type"].get(new_type, 0) + 1
                    )
                    self.stats["re_parsed"] += 1

                    if i <= 10:  # Show first 10 examples
                        logger.info(
                            f"✅ Re-parsed: {update_data['old_type']} → {update_data['new_type']}"
                        )
                        logger.info(
                            f"   Detail: {update_data['action_detail'][:80]}..."
                        )
                else:
                    self.stats["still_unknown"] += 1

            # Apply updates if not dry run
            if not dry_run and updates_to_apply:
                logger.info(
                    f"\n🔄 Applying {len(updates_to_apply)} updates to database..."
                )

                for update_data in updates_to_apply:
                    await self.update_action_in_db(update_data)

                logger.info("✅ Database updated successfully!")
            elif dry_run and updates_to_apply:
                logger.info(
                    f"\n💡 DRY RUN: Would update {len(updates_to_apply)} actions"
                )
                logger.info("   Run with --execute to apply changes")

        self.print_summary()
        return self.stats

    def print_summary(self):
        """Print summary statistics"""
        logger.info("\n" + "=" * 60)
        logger.info("📊 RE-PARSING SUMMARY")
        logger.info("=" * 60)

        logger.info(f"Total unknown actions processed: {self.stats['total_unknown']:,}")
        logger.info(f"Successfully re-parsed: {self.stats['re_parsed']:,}")
        logger.info(f"Still unknown: {self.stats['still_unknown']:,}")
        logger.info(f"Errors: {self.stats['errors']:,}")

        if self.stats["by_new_type"]:
            logger.info("\n📈 Re-categorized by type:")
            for action_type, count in sorted(
                self.stats["by_new_type"].items(), key=lambda x: x[1], reverse=True
            ):
                logger.info(f"   • {action_type}: {count:,}")

        recognition_rate = (
            (self.stats["re_parsed"] / self.stats["total_unknown"] * 100)
            if self.stats["total_unknown"] > 0
            else 0
        )
        logger.info(f"\n✅ Recognition rate: {recognition_rate:.1f}%")
        logger.info("=" * 60)


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Re-parse unknown actions with updated scraper patterns"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually update database (default is dry run)",
    )
    parser.add_argument(
        "--type",
        type=str,
        choices=["unknown", "other", "legacy_multi_action"],
        help="Only re-parse specific action type",
    )
    args = parser.parse_args()

    reparser = UnknownActionsReparser()

    try:
        await reparser.run(dry_run=not args.execute, action_type_filter=args.type)
    except KeyboardInterrupt:
        logger.info("\n⚠️ Re-parsing interrupted by user")
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

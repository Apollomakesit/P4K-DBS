#!/usr/bin/env python3
"""
Migrate old actions to use new categorized action types.

This script re-parses all actions with action_type 'unknown', 'other', or 'legacy_multi_action'
using the updated _parse_action_text method from scraper.py.

Usage:
    python migrate_actions.py [--dry-run] [--batch-size 1000]
    
Options:
    --dry-run       Preview changes without updating database
    --batch-size    Number of actions to process per batch (default: 1000)
"""

import sqlite3
import os
import sys
import argparse
from datetime import datetime
from collections import defaultdict
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper import Pro4KingsScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_db_path():
    """Get database path (Railway or local)"""
    # Check environment variable first
    env_path = os.getenv("DATABASE_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    
    # Railway volume path
    if os.path.exists("/data/pro4kings.db"):
        return "/data/pro4kings.db"
    
    # Local development paths
    if os.path.exists("data/pro4kings.db"):
        return "data/pro4kings.db"
    if os.path.exists("pro4kings.db"):
        return "pro4kings.db"
    
    # For Railway shell, try common paths
    for path in ["/app/data/pro4kings.db", "/data/pro4kings.db"]:
        if os.path.exists(path):
            return path
    
    raise FileNotFoundError(
        "Database not found!\n"
        "This script must be run on Railway where the database exists.\n"
        "Use: railway run python migrate_actions.py"
    )


def migrate_actions(dry_run: bool = False, batch_size: int = 1000):
    """Migrate old actions to new categorized types"""
    
    db_path = get_db_path()
    logger.info(f"📁 Database: {db_path}")
    
    # Create scraper instance for parsing
    # 🔥 OPTIMIZED: Conservative limits for shared hosting
    scraper = Pro4KingsScraper(
        max_concurrent=int(os.getenv("SCRAPER_MAX_CONCURRENT", "5")),
        rate_limit=float(os.getenv("SCRAPER_RATE_LIMIT", "10.0")),  # Reduced from 25
        burst_capacity=int(os.getenv("SCRAPER_BURST_CAPACITY", "20")),  # Reduced from 50
    )
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get count of actions to migrate
    cursor.execute("""
        SELECT COUNT(*) FROM actions 
        WHERE action_type IN ('unknown', 'other')
    """)
    total_count = cursor.fetchone()[0]
    
    if total_count == 0:
        logger.info("✅ No actions to migrate!")
        conn.close()
        return
    
    logger.info(f"📊 Found {total_count:,} actions to migrate")
    
    # Statistics
    stats = defaultdict(int)
    stats['total'] = total_count
    stats['processed'] = 0
    stats['updated'] = 0
    stats['unchanged'] = 0
    stats['errors'] = 0
    
    # Track new action types
    type_changes = defaultdict(int)
    
    # Process in batches
    offset = 0
    batch_num = 0
    
    while offset < total_count:
        batch_num += 1
        
        # Fetch batch
        cursor.execute("""
            SELECT id, player_id, player_name, action_type, action_detail,
                   item_name, item_quantity, target_player_id, target_player_name,
                   admin_id, admin_name, warning_count, reason, timestamp, raw_text
            FROM actions 
            WHERE action_type IN ('unknown', 'other')
            ORDER BY id
            LIMIT ? OFFSET ?
        """, (batch_size, offset))
        
        actions = cursor.fetchall()
        
        if not actions:
            break
        
        logger.info(f"📦 Processing batch {batch_num} ({len(actions)} actions, offset {offset:,}/{total_count:,})")
        
        updates = []
        
        for action in actions:
            stats['processed'] += 1
            
            raw_text = action['raw_text']
            if not raw_text:
                stats['unchanged'] += 1
                continue
            
            # Parse using new patterns
            timestamp = action['timestamp']
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp)
                except:
                    timestamp = datetime.now()
            elif timestamp is None:
                timestamp = datetime.now()
            
            try:
                parsed = scraper._parse_action_text(raw_text, timestamp)
                
                if parsed and parsed.action_type not in ('unknown', 'other'):
                    # Action was successfully re-categorized
                    type_changes[parsed.action_type] += 1
                    
                    updates.append({
                        'id': action['id'],
                        'action_type': parsed.action_type,
                        'action_detail': parsed.action_detail,
                        'player_id': parsed.player_id or action['player_id'],
                        'player_name': parsed.player_name or action['player_name'],
                        'item_name': parsed.item_name,
                        'item_quantity': parsed.item_quantity,
                        'target_player_id': parsed.target_player_id,
                        'target_player_name': parsed.target_player_name,
                        'admin_id': parsed.admin_id,
                        'admin_name': parsed.admin_name,
                        'reason': parsed.reason,
                    })
                    stats['updated'] += 1
                else:
                    stats['unchanged'] += 1
                    
            except Exception as e:
                logger.error(f"Error parsing action {action['id']}: {e}")
                stats['errors'] += 1
        
        # Apply updates if not dry run
        if not dry_run and updates:
            for update in updates:
                cursor.execute("""
                    UPDATE actions SET
                        action_type = ?,
                        action_detail = ?,
                        player_id = ?,
                        player_name = ?,
                        item_name = ?,
                        item_quantity = ?,
                        target_player_id = ?,
                        target_player_name = ?,
                        admin_id = ?,
                        admin_name = ?,
                        reason = ?
                    WHERE id = ?
                """, (
                    update['action_type'],
                    update['action_detail'],
                    update['player_id'],
                    update['player_name'],
                    update['item_name'],
                    update['item_quantity'],
                    update['target_player_id'],
                    update['target_player_name'],
                    update['admin_id'],
                    update['admin_name'],
                    update['reason'],
                    update['id'],
                ))
            
            conn.commit()
            logger.info(f"   ✅ Updated {len(updates)} actions in batch {batch_num}")
        
        offset += batch_size
        
        # Progress report every 5 batches
        if batch_num % 5 == 0:
            pct = (stats['processed'] / total_count) * 100
            logger.info(f"   📈 Progress: {pct:.1f}% ({stats['processed']:,}/{total_count:,})")
    
    conn.close()
    
    # Final report
    print("\n" + "=" * 60)
    print("📊 MIGRATION REPORT")
    print("=" * 60)
    print(f"{'Mode:':<25} {'DRY RUN (no changes made)' if dry_run else 'LIVE (changes applied)'}")
    print(f"{'Total to migrate:':<25} {stats['total']:,}")
    print(f"{'Processed:':<25} {stats['processed']:,}")
    print(f"{'Successfully updated:':<25} {stats['updated']:,}")
    print(f"{'Unchanged:':<25} {stats['unchanged']:,}")
    print(f"{'Errors:':<25} {stats['errors']:,}")
    print()
    print("📋 New Action Types Applied:")
    print("-" * 40)
    for action_type, count in sorted(type_changes.items(), key=lambda x: -x[1]):
        print(f"  {action_type:<25} {count:,}")
    print("=" * 60)
    
    return stats


def main():
    parser = argparse.ArgumentParser(description="Migrate old actions to new categorized types")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without updating database")
    parser.add_argument("--batch-size", type=int, default=1000, help="Actions per batch (default: 1000)")
    args = parser.parse_args()
    
    logger.info("🚀 Starting action migration...")
    
    if args.dry_run:
        logger.info("⚠️  DRY RUN MODE - No changes will be made")
    
    migrate_actions(dry_run=args.dry_run, batch_size=args.batch_size)
    
    logger.info("✅ Migration complete!")


if __name__ == "__main__":
    main()

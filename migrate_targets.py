#!/usr/bin/env python3
"""
Migrate actions to populate missing target_player_id and target_player_name.

This script extracts target player information from raw_text or action_detail
for actions that are missing target_player_id but contain target info.

Usage:
    python migrate_targets.py [--dry-run] [--batch-size 1000] [--limit 10000]
    
Options:
    --dry-run       Preview changes without updating database
    --batch-size    Number of actions to process per batch (default: 1000)
    --limit         Maximum number of actions to process (default: all)
    --stats-only    Only show statistics, don't process anything
"""

import sqlite3
import os
import sys
import argparse
from datetime import datetime
from collections import defaultdict
import logging
import re

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_db_path():
    """Get database path (Railway or local)"""
    env_path = os.getenv("DATABASE_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    
    if os.path.exists("/data/pro4kings.db"):
        return "/data/pro4kings.db"
    if os.path.exists("data/pro4kings.db"):
        return "data/pro4kings.db"
    if os.path.exists("pro4kings.db"):
        return "pro4kings.db"
    
    for path in ["/app/data/pro4kings.db", "/data/pro4kings.db"]:
        if os.path.exists(path):
            return path
    
    raise FileNotFoundError("Database not found!")


def extract_target_from_text(text: str) -> tuple:
    """Extract target_player_id and target_player_name from action text.
    
    Handles multiple patterns:
    1. "ia dat lui PlayerName(ID)" - item given
    2. "a transferat suma de X$ lui PlayerName(ID)" - money transfer
    3. "primit de la PlayerName(ID)" - item received (sender is target)
    4. "Contract Player1(ID) -> Player2(ID)" - contracts
    5. "Trade intre Player1(ID) si Player2(ID)" - trades
    
    Returns: (target_player_id, target_player_name) or (None, None)
    """
    if not text:
        return (None, None)
    
    # Pattern 1: "ia dat lui PlayerName(ID)" or "a dat lui PlayerName(ID)"
    match = re.search(
        r"(?:i-?a|a)\s+dat\s+lui\s+([^(]+)\((\d+)\)", text, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 2: "ia transferat suma de X$ lui PlayerName(ID)"
    match = re.search(
        r"transferat\s+(?:suma\s+de\s+)?[\d.,]+\s*\$?\s*(?:lui|jucatorului)\s+([^(]+)\((\d+)\)", 
        text, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 3: "primit de la PlayerName(ID)" - the SENDER is extracted as "target"
    # In this case, target is who gave the items
    match = re.search(
        r"primit\s+(?:de\s+la|de la)\s+([^(]+)\((\d+)\)", text, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 4: Contract with arrow "Contract Player1(ID) -> Player2(ID)"
    match = re.search(
        r"Contract\s+[^(]+\(\d+\)\s*(?:->|→)\s*([^(]+)\((\d+)\)", text, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 5: Contract simple "Contract Player1(ID) Player2(ID)"
    match = re.search(
        r"Contract\s+[^(]+\(\d+\)\s+([^(]+)\((\d+)\)", text, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 6: Trade "Tradeul dintre jucatorii Player1(ID) si Player2(ID)"
    match = re.search(
        r"Trade.*?[^(]+\(\d+\)\s+si\s+([^(]+)\((\d+)\)", text, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 7: Warning from admin "administratorul PlayerName(ID)"
    match = re.search(
        r"administratorul\s+([^(]+)\((\d+)\)", text, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 8: License plate sale "Vanzarea de placute dintre jucatorii Player1(ID) si Player2(ID)"
    match = re.search(
        r"Vanzarea\s+de\s+placute.*?jucatorii\s+[^(]+\(\d+\)\s+si\s+([^(]+)\((\d+)\)", 
        text, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 9: Gambling "a castigat impotriva lui PlayerName(ID)"
    match = re.search(
        r"castigat\s+(?:impotriva\s+lui\s+)?([^(]+)\((\d+)\)", text, re.IGNORECASE
    )
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 10: "lui (ID)" without name (just ID in parentheses after "lui")
    match = re.search(
        r"lui\s+\((\d+)\)", text, re.IGNORECASE
    )
    if match:
        return (match.group(1), None)
    
    return (None, None)


def show_statistics(cursor) -> dict:
    """Show current database statistics for target fields"""
    stats = {}
    
    # Total actions
    cursor.execute("SELECT COUNT(*) FROM actions")
    stats['total'] = cursor.fetchone()[0]
    
    # Actions with target_player_id
    cursor.execute("SELECT COUNT(*) FROM actions WHERE target_player_id IS NOT NULL")
    stats['has_target_id'] = cursor.fetchone()[0]
    
    # Actions without target_player_id
    cursor.execute("SELECT COUNT(*) FROM actions WHERE target_player_id IS NULL")
    stats['missing_target_id'] = cursor.fetchone()[0]
    
    # Actions with potential targets in text (rough estimate)
    cursor.execute("""
        SELECT COUNT(*) FROM actions 
        WHERE target_player_id IS NULL 
        AND (raw_text LIKE '%lui %(%' OR raw_text LIKE '%de la %(%')
    """)
    stats['potential_targets'] = cursor.fetchone()[0]
    
    # Break down by action type
    cursor.execute("""
        SELECT action_type, COUNT(*) as cnt 
        FROM actions 
        WHERE target_player_id IS NULL 
        GROUP BY action_type 
        ORDER BY cnt DESC 
        LIMIT 10
    """)
    stats['missing_by_type'] = [(row[0], row[1]) for row in cursor.fetchall()]
    
    return stats


def migrate_targets(dry_run: bool = False, batch_size: int = 1000, limit: int = None, stats_only: bool = False):
    """Migrate actions to populate missing target fields"""
    
    db_path = get_db_path()
    logger.info(f"📁 Database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Show statistics
    stats = show_statistics(cursor)
    
    logger.info("\n" + "=" * 60)
    logger.info("📊 CURRENT DATABASE STATISTICS")
    logger.info("=" * 60)
    logger.info(f"Total actions: {stats['total']:,}")
    logger.info(f"With target_player_id: {stats['has_target_id']:,} ({stats['has_target_id']/stats['total']*100:.1f}%)")
    logger.info(f"Missing target_player_id: {stats['missing_target_id']:,} ({stats['missing_target_id']/stats['total']*100:.1f}%)")
    logger.info(f"Potential targets in text: {stats['potential_targets']:,} (estimate)")
    
    logger.info("\n📋 Missing targets by action type:")
    for action_type, count in stats['missing_by_type']:
        logger.info(f"   {action_type}: {count:,}")
    
    if stats_only:
        conn.close()
        return
    
    # Get actions that might have extractable targets
    # Focus on action types that typically have targets
    target_action_types = [
        'item_given', 'item_received', 'money_transfer', 
        'contract', 'vehicle_contract', 'trade',
        'warning_received', 'ban_received', 'admin_jail', 'admin_unjail',
        'mute_received', 'gambling_win', 'license_plate_sale',
        'unknown', 'other'
    ]
    
    type_placeholders = ','.join('?' * len(target_action_types))
    
    count_query = f"""
        SELECT COUNT(*) FROM actions 
        WHERE target_player_id IS NULL
        AND action_type IN ({type_placeholders})
    """
    cursor.execute(count_query, target_action_types)
    total_to_process = cursor.fetchone()[0]
    
    if limit:
        total_to_process = min(total_to_process, limit)
    
    if total_to_process == 0:
        logger.info("\n✅ No actions need target migration!")
        conn.close()
        return
    
    logger.info(f"\n🔄 Will process up to {total_to_process:,} actions")
    if dry_run:
        logger.info("⚠️  DRY RUN MODE - No changes will be made")
    
    # Processing stats
    migration_stats = defaultdict(int)
    migration_stats['total'] = total_to_process
    migration_stats['processed'] = 0
    migration_stats['updated'] = 0
    migration_stats['no_target_found'] = 0
    migration_stats['errors'] = 0
    
    # Track updates by action type
    updates_by_type = defaultdict(int)
    
    # Sample of extracted data for preview
    samples = []
    
    # Process in batches
    offset = 0
    batch_num = 0
    total_processed = 0
    
    while total_processed < total_to_process:
        batch_num += 1
        
        current_batch_size = min(batch_size, total_to_process - total_processed)
        
        # Fetch batch
        fetch_query = f"""
            SELECT id, player_id, player_name, action_type, action_detail, raw_text
            FROM actions 
            WHERE target_player_id IS NULL
            AND action_type IN ({type_placeholders})
            ORDER BY id
            LIMIT ? OFFSET ?
        """
        cursor.execute(fetch_query, (*target_action_types, current_batch_size, offset))
        
        actions = cursor.fetchall()
        
        if not actions:
            break
        
        logger.info(f"📦 Batch {batch_num}: Processing {len(actions)} actions (total: {total_processed:,}/{total_to_process:,})")
        
        updates = []
        
        for action in actions:
            migration_stats['processed'] += 1
            total_processed += 1
            
            # Try to extract target from raw_text first, then action_detail
            raw_text = action['raw_text']
            action_detail = action['action_detail']
            
            target_id, target_name = extract_target_from_text(raw_text)
            
            # Fallback to action_detail if raw_text didn't work
            if not target_id and action_detail:
                target_id, target_name = extract_target_from_text(action_detail)
            
            if target_id:
                # Don't update if target is same as player (self-actions)
                if target_id == action['player_id']:
                    migration_stats['no_target_found'] += 1
                    continue
                
                updates.append({
                    'id': action['id'],
                    'target_player_id': target_id,
                    'target_player_name': target_name,
                })
                migration_stats['updated'] += 1
                updates_by_type[action['action_type']] += 1
                
                # Collect samples for preview
                if len(samples) < 10:
                    samples.append({
                        'action_type': action['action_type'],
                        'player': f"{action['player_name']}({action['player_id']})",
                        'target': f"{target_name}({target_id})" if target_name else f"({target_id})",
                        'raw_text': raw_text[:80] + "..." if raw_text and len(raw_text) > 80 else raw_text,
                    })
            else:
                migration_stats['no_target_found'] += 1
        
        # Apply updates if not dry run
        if not dry_run and updates:
            for update in updates:
                try:
                    cursor.execute("""
                        UPDATE actions 
                        SET target_player_id = ?, target_player_name = ?
                        WHERE id = ?
                    """, (update['target_player_id'], update['target_player_name'], update['id']))
                except Exception as e:
                    logger.error(f"Error updating action {update['id']}: {e}")
                    migration_stats['errors'] += 1
            
            conn.commit()
            logger.info(f"   ✅ Applied {len(updates)} updates")
        
        offset += len(actions)
        
        # Limit check
        if limit and total_processed >= limit:
            break
    
    # Final commit
    if not dry_run:
        conn.commit()
    
    conn.close()
    
    # Print report
    logger.info("\n" + "=" * 60)
    if dry_run:
        logger.info("📊 DRY RUN RESULTS (no changes made)")
    else:
        logger.info("📊 MIGRATION RESULTS")
    logger.info("=" * 60)
    logger.info(f"Total processed: {migration_stats['processed']:,}")
    logger.info(f"Updated with target info: {migration_stats['updated']:,}")
    logger.info(f"No target found in text: {migration_stats['no_target_found']:,}")
    logger.info(f"Errors: {migration_stats['errors']:,}")
    
    if updates_by_type:
        logger.info("\n📋 Updates by action type:")
        for action_type, count in sorted(updates_by_type.items(), key=lambda x: -x[1]):
            logger.info(f"   {action_type}: {count:,}")
    
    if samples:
        logger.info("\n📝 Sample extractions:")
        for i, sample in enumerate(samples, 1):
            logger.info(f"\n   [{i}] {sample['action_type']}")
            logger.info(f"       Player: {sample['player']}")
            logger.info(f"       Target: {sample['target']}")
            logger.info(f"       Text: {sample['raw_text']}")
    
    if dry_run:
        logger.info("\n⚠️  To apply these changes, run without --dry-run")
    else:
        logger.info("\n✅ Migration complete!")


def main():
    parser = argparse.ArgumentParser(description="Migrate target player info into actions table")
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Preview changes without updating database"
    )
    parser.add_argument(
        "--batch-size", 
        type=int, 
        default=1000, 
        help="Number of actions per batch (default: 1000)"
    )
    parser.add_argument(
        "--limit", 
        type=int, 
        default=None, 
        help="Maximum actions to process (default: all)"
    )
    parser.add_argument(
        "--stats-only", 
        action="store_true", 
        help="Only show statistics, don't process"
    )
    
    args = parser.parse_args()
    
    try:
        migrate_targets(
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            limit=args.limit,
            stats_only=args.stats_only
        )
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\n\n⚠️ Migration interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

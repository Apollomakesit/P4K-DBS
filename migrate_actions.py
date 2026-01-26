#!/usr/bin/env python3
"""
Migration script to extract target_player_id and target_player_name from existing actions.
This fixes actions that were scraped before the regex was fixed.
"""

import sqlite3
import re
import os
from datetime import datetime

def get_db_path():
    """Get database path (same logic as database.py)"""
    if os.path.exists('/data'):
        return '/data/pro4kings.db'
    return 'pro4kings.db'

def extract_target_from_detail(action_detail: str, raw_text: str = None) -> tuple:
    """
    Extract target_player_id and target_player_name from action_detail or raw_text.
    
    Returns: (target_player_id, target_player_name) or (None, None)
    """
    text = action_detail or raw_text or ""
    
    # Pattern 1: "ia dat lui PlayerName(ID)" - for item transfers
    match = re.search(r'(?:ia|a)\s+dat\s+lui\s+([^(]+)\((\d+)\)', text, re.IGNORECASE)
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 2: "primit de la PlayerName(ID)" - for received items
    match = re.search(r'primit\s+(?:de\s+la|de la)\s+([^(]+)\((\d+)\)', text, re.IGNORECASE)
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern 3: Look in raw_text if action_detail didn't match
    if raw_text and raw_text != action_detail:
        # Try "Jucatorul X(Y) ia dat lui Z(W)"
        match = re.search(r'(?:ia|a)\s+dat\s+lui\s+([^(]+)\((\d+)\)', raw_text, re.IGNORECASE)
        if match:
            return (match.group(2), match.group(1).strip())
    
    return (None, None)

def migrate_actions():
    """Migrate existing actions to extract target player information"""
    db_path = get_db_path()
    print(f"📁 Using database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Get all actions that have NULL target_player_id but contain "ia dat lui" or "dat lui" in detail
        print("\n🔍 Finding actions with missing target player info...")
        cursor.execute("""
            SELECT id, player_id, player_name, action_type, action_detail, raw_text
            FROM actions
            WHERE target_player_id IS NULL
            AND (
                action_detail LIKE '%ia dat lui%'
                OR action_detail LIKE '%a dat lui%'
                OR action_detail LIKE '%primit de la%'
                OR raw_text LIKE '%ia dat lui%'
                OR raw_text LIKE '%a dat lui%'
                OR raw_text LIKE '%primit de la%'
            )
        """)
        
        actions_to_update = cursor.fetchall()
        print(f"✅ Found {len(actions_to_update)} actions to process\n")
        
        if len(actions_to_update) == 0:
            print("✨ No actions need updating!")
            return
        
        updated_count = 0
        failed_count = 0
        
        for action in actions_to_update:
            action_id = action['id']
            action_detail = action['action_detail']
            raw_text = action['raw_text']
            
            # Extract target info
            target_id, target_name = extract_target_from_detail(action_detail, raw_text)
            
            if target_id and target_name:
                # Update the action
                cursor.execute("""
                    UPDATE actions
                    SET target_player_id = ?,
                        target_player_name = ?
                    WHERE id = ?
                """, (target_id, target_name, action_id))
                
                updated_count += 1
                if updated_count % 100 == 0:
                    print(f"  ⏳ Processed {updated_count} actions...")
            else:
                failed_count += 1
                if failed_count <= 5:  # Show first 5 failures for debugging
                    print(f"  ⚠️  Could not extract from: {action_detail[:80]}...")
        
        conn.commit()
        
        print(f"\n✅ Migration complete!")
        print(f"   📊 Updated: {updated_count} actions")
        print(f"   ⚠️  Failed: {failed_count} actions")
        
        # Verify the update
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM actions
            WHERE target_player_id IS NOT NULL
        """)
        total_with_target = cursor.fetchone()['count']
        print(f"   📈 Total actions with target info: {total_with_target}")
        
    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        conn.rollback()
        raise
    
    finally:
        conn.close()

if __name__ == "__main__":
    print("="*60)
    print("🔧 P4K-DBS Action Migration Tool")
    print("="*60)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    migrate_actions()
    
    print()
    print(f"⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

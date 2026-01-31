#!/usr/bin/env python3
"""Diagnostic script to investigate player 280's data"""

import sqlite3
from datetime import datetime

DB_PATH = "/data/pro4kings.db"

def main():
    print("=" * 60)
    print("DIAGNOSTIC: Player 280 (Vaispar)")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Check player profile
    print("\n📋 PLAYER PROFILE:")
    cursor.execute("SELECT * FROM player_profiles WHERE player_id = '280'")
    row = cursor.fetchone()
    if row:
        print(f"  Username: {row['username']}")
        print(f"  Faction: {row['faction']}")
        print(f"  Is Online: {row['is_online']}")
        print(f"  Last Seen: {row['last_seen']}")
        print(f"  First Detected: {row['first_detected']}")
        print(f"  Total Actions: {row['total_actions']}")
    else:
        print("  NOT FOUND")
    
    # 2. Check ban status
    print("\n🚫 BAN STATUS:")
    cursor.execute("SELECT * FROM banned_players WHERE player_id = '280'")
    bans = cursor.fetchall()
    if bans:
        for ban in bans:
            print(f"  Admin: {ban['admin']}")
            print(f"  Reason: {ban['reason']}")
            print(f"  Duration: {ban['duration']}")
            print(f"  Ban Date: {ban['ban_date']}")
            print(f"  Expiry: {ban['expiry_date']}")
            print(f"  Is Active: {ban['is_active']}")
    else:
        print("  NO BANS FOUND")
    
    # 3. Check login events
    print("\n🔑 LOGIN EVENTS (last 10):")
    cursor.execute("""
        SELECT * FROM login_events 
        WHERE player_id = '280' 
        ORDER BY timestamp DESC 
        LIMIT 10
    """)
    events = cursor.fetchall()
    if events:
        for event in events:
            print(f"  {event['event_type']}: {event['timestamp']} (duration: {event['session_duration_seconds']}s)")
    else:
        print("  NO LOGIN EVENTS")
    
    # 4. Check recent actions WHERE player_id = 280
    print("\n📝 ACTIONS AS PLAYER (player_id = 280, last 10):")
    cursor.execute("""
        SELECT id, action_type, action_detail, target_player_id, target_player_name, timestamp 
        FROM actions 
        WHERE player_id = '280' 
        ORDER BY timestamp DESC 
        LIMIT 10
    """)
    actions = cursor.fetchall()
    if actions:
        for action in actions:
            print(f"  [{action['id']}] {action['action_type']}: {action['action_detail'][:60]}... @ {action['timestamp']}")
            if action['target_player_id']:
                print(f"        Target: {action['target_player_name']} ({action['target_player_id']})")
    else:
        print("  NO ACTIONS AS PLAYER")
    
    # 5. Check actions WHERE target_player_id = 280
    print("\n📥 ACTIONS AS TARGET (target_player_id = 280, last 10):")
    cursor.execute("""
        SELECT id, player_id, player_name, action_type, action_detail, timestamp 
        FROM actions 
        WHERE target_player_id = '280' 
        ORDER BY timestamp DESC 
        LIMIT 10
    """)
    target_actions = cursor.fetchall()
    if target_actions:
        for action in target_actions:
            print(f"  [{action['id']}] {action['action_type']}: {action['action_detail'][:60]}...")
            print(f"        From: {action['player_name']} ({action['player_id']}) @ {action['timestamp']}")
    else:
        print("  NO ACTIONS AS TARGET")
    
    # 6. Check if online_players has entry
    print("\n🟢 ONLINE PLAYERS TABLE:")
    cursor.execute("SELECT * FROM online_players WHERE player_id = '280'")
    online = cursor.fetchone()
    if online:
        print(f"  Detected online at: {online['detected_online_at']}")
    else:
        print("  NOT IN ONLINE_PLAYERS TABLE")
    
    # 7. Check for actions mentioning player 280 in raw_text or action_detail
    print("\n🔍 ACTIONS MENTIONING '(280)' IN TEXT:")
    cursor.execute("""
        SELECT id, player_id, player_name, action_type, substr(action_detail, 1, 80) as detail, timestamp 
        FROM actions 
        WHERE (action_detail LIKE '%(280)%' OR raw_text LIKE '%(280)%')
        AND player_id != '280'
        AND (target_player_id IS NULL OR target_player_id != '280')
        ORDER BY timestamp DESC 
        LIMIT 10
    """)
    mentions = cursor.fetchall()
    if mentions:
        for m in mentions:
            print(f"  [{m['id']}] Player: {m['player_name']}({m['player_id']}) | Type: {m['action_type']}")
            print(f"        Detail: {m['detail']}...")
            print(f"        Time: {m['timestamp']}")
    else:
        print("  NO UNLINKED MENTIONS FOUND")
    
    conn.close()
    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")

if __name__ == "__main__":
    main()

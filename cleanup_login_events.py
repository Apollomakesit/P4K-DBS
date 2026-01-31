#!/usr/bin/env python3
"""
Cleanup Login Events - Fix duplicate logout detections

Problem: 1.3M logouts vs 23K logins (57x ratio!)
This is caused by the bot detecting "logout" events repeatedly for the same player.

Solution:
For each player, we process events chronologically:
1. A valid session is: LOGIN -> (optional time) -> LOGOUT
2. If we see consecutive LOGOUTs (no LOGIN in between), keep only the FIRST one
3. If we see consecutive LOGINs (no LOGOUT in between), keep only the LAST one
4. Recalculate session durations based on cleaned data

After cleanup, logouts should be slightly LESS than logins (since online players haven't logged out yet).
"""

import sqlite3
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_db_path():
    """Get database path"""
    # Check environment variable first (Railway sets this)
    env_path = os.getenv("DATABASE_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # Railway volume mount
    if os.path.exists("/data/pro4kings.db"):
        return "/data/pro4kings.db"

    # Local development
    if os.path.exists("data/pro4kings.db"):
        return "data/pro4kings.db"

    # Fallback
    return os.getenv("DATABASE_PATH", "/data/pro4kings.db")


def analyze_login_events(conn):
    """Analyze current state of login_events table"""
    cursor = conn.cursor()

    # Get total counts
    cursor.execute("SELECT event_type, COUNT(*) FROM login_events GROUP BY event_type")
    counts = dict(cursor.fetchall())

    login_count = counts.get("login", 0)
    logout_count = counts.get("logout", 0)

    logger.info("=" * 60)
    logger.info("CURRENT STATE ANALYSIS")
    logger.info("=" * 60)
    logger.info(f"Total LOGINs:  {login_count:,}")
    logger.info(f"Total LOGOUTs: {logout_count:,}")
    logger.info(
        f"Ratio: {logout_count/login_count:.1f}x more logouts"
        if login_count > 0
        else "No logins"
    )

    # Get unique players
    cursor.execute("SELECT COUNT(DISTINCT player_id) FROM login_events")
    unique_players = cursor.fetchone()[0]
    logger.info(f"Unique players with events: {unique_players:,}")

    # Find players with most consecutive logouts (worst offenders)
    cursor.execute(
        """
        WITH consecutive AS (
            SELECT 
                player_id,
                event_type,
                timestamp,
                LAG(event_type) OVER (PARTITION BY player_id ORDER BY timestamp) as prev_event
            FROM login_events
        )
        SELECT player_id, COUNT(*) as consecutive_logouts
        FROM consecutive
        WHERE event_type = 'logout' AND prev_event = 'logout'
        GROUP BY player_id
        ORDER BY consecutive_logouts DESC
        LIMIT 10
    """
    )

    worst_offenders = cursor.fetchall()
    if worst_offenders:
        logger.info("\nTop 10 players with most duplicate logouts:")
        for player_id, count in worst_offenders:
            logger.info(f"  Player {player_id}: {count:,} duplicate logouts")

    return login_count, logout_count


def identify_duplicates(conn, dry_run=True):
    """
    Identify duplicate events to delete.

    Rules:
    1. If consecutive events are both LOGOUT, keep only the FIRST one (delete later ones)
    2. If consecutive events are both LOGIN, keep only the LAST one (delete earlier ones)

    Returns: List of event IDs to delete
    """
    cursor = conn.cursor()

    logger.info("\nIdentifying duplicate events...")

    # Find duplicate LOGOUTs (consecutive logouts - keep first, delete rest)
    cursor.execute(
        """
        WITH ordered_events AS (
            SELECT 
                id,
                player_id,
                event_type,
                timestamp,
                LAG(event_type) OVER (PARTITION BY player_id ORDER BY timestamp) as prev_event,
                LAG(id) OVER (PARTITION BY player_id ORDER BY timestamp) as prev_id
            FROM login_events
        )
        SELECT id, player_id, timestamp
        FROM ordered_events
        WHERE event_type = 'logout' AND prev_event = 'logout'
    """
    )

    duplicate_logouts = cursor.fetchall()
    logout_ids_to_delete = [row[0] for row in duplicate_logouts]

    logger.info(
        f"Found {len(logout_ids_to_delete):,} duplicate LOGOUT events to delete"
    )

    # Find duplicate LOGINs (consecutive logins - keep last, delete earlier ones)
    cursor.execute(
        """
        WITH ordered_events AS (
            SELECT 
                id,
                player_id,
                event_type,
                timestamp,
                LEAD(event_type) OVER (PARTITION BY player_id ORDER BY timestamp) as next_event,
                LEAD(id) OVER (PARTITION BY player_id ORDER BY timestamp) as next_id
            FROM login_events
        )
        SELECT id, player_id, timestamp
        FROM ordered_events
        WHERE event_type = 'login' AND next_event = 'login'
    """
    )

    duplicate_logins = cursor.fetchall()
    login_ids_to_delete = [row[0] for row in duplicate_logins]

    logger.info(f"Found {len(login_ids_to_delete):,} duplicate LOGIN events to delete")

    all_ids_to_delete = set(logout_ids_to_delete + login_ids_to_delete)
    logger.info(f"Total events to delete: {len(all_ids_to_delete):,}")

    return list(all_ids_to_delete)


def delete_duplicates(conn, ids_to_delete, batch_size=10000):
    """Delete duplicate events in batches"""
    cursor = conn.cursor()

    total = len(ids_to_delete)
    deleted = 0

    logger.info(f"\nDeleting {total:,} duplicate events in batches of {batch_size}...")

    for i in range(0, total, batch_size):
        batch = ids_to_delete[i : i + batch_size]
        placeholders = ",".join("?" * len(batch))
        cursor.execute(f"DELETE FROM login_events WHERE id IN ({placeholders})", batch)
        deleted += cursor.rowcount

        if (i + batch_size) % 50000 == 0 or i + batch_size >= total:
            conn.commit()
            progress = min(i + batch_size, total)
            logger.info(
                f"  Progress: {progress:,}/{total:,} ({progress/total*100:.1f}%)"
            )

    conn.commit()
    logger.info(f"✅ Deleted {deleted:,} duplicate events")
    return deleted


def recalculate_session_durations(conn):
    """
    Recalculate session_duration_seconds for all logout events.

    For each logout, find the most recent login for that player before the logout,
    and calculate the duration.
    """
    cursor = conn.cursor()

    logger.info("\nRecalculating session durations...")

    # Update session durations using a correlated subquery
    cursor.execute(
        """
        UPDATE login_events
        SET session_duration_seconds = (
            SELECT CAST((julianday(login_events.timestamp) - julianday(prev_login.timestamp)) * 86400 AS INTEGER)
            FROM login_events AS prev_login
            WHERE prev_login.player_id = login_events.player_id
            AND prev_login.event_type = 'login'
            AND prev_login.timestamp < login_events.timestamp
            ORDER BY prev_login.timestamp DESC
            LIMIT 1
        )
        WHERE event_type = 'logout'
    """
    )

    updated = cursor.rowcount
    conn.commit()

    logger.info(f"✅ Updated session durations for {updated:,} logout events")

    # Verify the update
    cursor.execute(
        """
        SELECT 
            COUNT(*) as total_logouts,
            COUNT(session_duration_seconds) as with_duration,
            AVG(session_duration_seconds) / 3600 as avg_hours,
            MAX(session_duration_seconds) / 3600 as max_hours
        FROM login_events
        WHERE event_type = 'logout'
    """
    )

    stats = cursor.fetchone()
    logger.info(f"  Logouts with duration: {stats[1]:,}/{stats[0]:,}")
    logger.info(
        f"  Average session: {stats[2]:.2f} hours"
        if stats[2]
        else "  No durations calculated"
    )
    logger.info(f"  Max session: {stats[3]:.2f} hours" if stats[3] else "")

    return updated


def verify_cleanup(conn):
    """Verify the cleanup was successful"""
    cursor = conn.cursor()

    logger.info("\n" + "=" * 60)
    logger.info("POST-CLEANUP VERIFICATION")
    logger.info("=" * 60)

    # Get new counts
    cursor.execute("SELECT event_type, COUNT(*) FROM login_events GROUP BY event_type")
    counts = dict(cursor.fetchall())

    login_count = counts.get("login", 0)
    logout_count = counts.get("logout", 0)

    logger.info(f"Total LOGINs:  {login_count:,}")
    logger.info(f"Total LOGOUTs: {logout_count:,}")

    if login_count > 0:
        ratio = logout_count / login_count
        logger.info(f"Ratio: {ratio:.2f}x")

        if ratio < 1.0:
            logger.info("✅ HEALTHY: Logouts < Logins (some players still online)")
        elif ratio <= 1.1:
            logger.info("✅ HEALTHY: Logouts ≈ Logins (within 10%)")
        else:
            logger.warning(f"⚠️ Still have {ratio:.1f}x more logouts than logins")

    # Check for any remaining consecutive duplicates
    cursor.execute(
        """
        WITH ordered_events AS (
            SELECT 
                event_type,
                LAG(event_type) OVER (PARTITION BY player_id ORDER BY timestamp) as prev_event
            FROM login_events
        )
        SELECT COUNT(*) FROM ordered_events
        WHERE (event_type = 'logout' AND prev_event = 'logout')
           OR (event_type = 'login' AND prev_event = 'login')
    """
    )

    remaining_duplicates = cursor.fetchone()[0]
    if remaining_duplicates == 0:
        logger.info("✅ No remaining duplicate consecutive events!")
    else:
        logger.warning(f"⚠️ Still have {remaining_duplicates:,} potential duplicates")

    # Get sample of valid sessions
    cursor.execute(
        """
        SELECT 
            player_id,
            session_duration_seconds / 3600.0 as hours
        FROM login_events
        WHERE event_type = 'logout' AND session_duration_seconds IS NOT NULL
        ORDER BY timestamp DESC
        LIMIT 5
    """
    )

    logger.info("\nSample recent sessions:")
    for row in cursor.fetchall():
        logger.info(f"  Player {row[0]}: {row[1]:.2f} hours")

    return login_count, logout_count


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Cleanup duplicate login/logout events"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Analyze only, don't delete"
    )
    parser.add_argument(
        "--confirm", action="store_true", help="Actually perform the cleanup"
    )
    args = parser.parse_args()

    db_path = get_db_path()
    logger.info(f"Database: {db_path}")

    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")

    try:
        # Step 1: Analyze current state
        login_count, logout_count = analyze_login_events(conn)

        # Step 2: Identify duplicates
        ids_to_delete = identify_duplicates(conn)

        if not ids_to_delete:
            logger.info("\n✅ No duplicates found! Data is already clean.")
            return

        if args.dry_run or not args.confirm:
            logger.info("\n" + "=" * 60)
            logger.info("DRY RUN - No changes made")
            logger.info("=" * 60)
            logger.info(f"Would delete {len(ids_to_delete):,} duplicate events")
            logger.info(f"Expected final counts:")
            expected_logouts = logout_count - sum(
                1 for _ in ids_to_delete if True
            )  # Approximate
            logger.info(f"  Logins: ~{login_count:,}")
            logger.info(f"  Logouts: ~{logout_count - len(ids_to_delete):,}")
            logger.info("\nTo perform cleanup, run with --confirm")
            return

        # Step 3: Delete duplicates
        logger.info("\n" + "=" * 60)
        logger.info("PERFORMING CLEANUP")
        logger.info("=" * 60)

        deleted = delete_duplicates(conn, ids_to_delete)

        # Step 4: Recalculate session durations
        recalculate_session_durations(conn)

        # Step 5: Verify
        verify_cleanup(conn)

        logger.info("\n✅ Cleanup complete!")

    finally:
        conn.close()


if __name__ == "__main__":
    main()

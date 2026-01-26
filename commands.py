"""Discord Slash Commands for Pro4Kings Database Bot - OPTIMIZED WITH CONCURRENT WORKERS"""

import discord
from discord import app_commands
from datetime import datetime, timedelta
import logging
import asyncio
import os
import re
from typing import Optional, List, Dict
from collections import defaultdict

logger = logging.getLogger(__name__)

# Admin user IDs from environment
ADMIN_USER_IDS = set(map(int, os.getenv('ADMIN_USER_IDS', '').split(','))) if os.getenv('ADMIN_USER_IDS') else set()

# SCAN STATE - Shared across commands
SCAN_STATE = {
    'is_scanning': False,
    'is_paused': False,
    'start_id': 0,
    'end_id': 0,
    'current_id': 0,
    'found_count': 0,
    'error_count': 0,
    'start_time': None,
    'scan_task': None,
    'status_message': None,
    'status_task': None,
    'scan_config': {
        'batch_size': 50,
        'workers': 10,
        'wave_delay': 0.05,
        'max_concurrent_batches': 5
    },
    'worker_stats': {},
    'total_scanned': 0,
    'last_speed_update': None,
    'current_speed': 0.0
}

# ========================================================================
# HELPER FUNCTIONS
# ========================================================================

def deduplicate_actions(actions: List[dict]) -> List[dict]:
    """Deduplicate actions that occur at the same second with same type and detail.
    
    Args:
        actions: List of action dictionaries
        
    Returns:
        List of deduplicated actions with 'count' field added for duplicates
    """
    if not actions:
        return []
    
    # Group actions by (timestamp_second, action_type, action_detail)
    grouped = defaultdict(list)
    
    for action in actions:
        timestamp = action.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        
        # Round to the nearest second for grouping
        timestamp_key = timestamp.replace(microsecond=0) if timestamp else None
        action_type = action.get('action_type', 'unknown')
        action_detail = action.get('action_detail', '')
        
        key = (timestamp_key, action_type, action_detail)
        grouped[key].append(action)
    
    # Create deduplicated list with counts
    deduplicated = []
    for key, group in grouped.items():
        # Take the first action from the group
        action = group[0].copy()
        # Add count if there are duplicates
        if len(group) > 1:
            action['count'] = len(group)
        deduplicated.append(action)
    
    # Sort by timestamp descending (most recent first)
    deduplicated.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    return deduplicated

def extract_target_from_detail(action_detail: str) -> tuple:
    """Extract target_player_id and target_player_name from action_detail text.
    
    This is a fallback for old actions that don't have target info in database.
    
    Returns: (target_player_id, target_player_name) or (None, None)
    """
    if not action_detail:
        return (None, None)
    
    # Pattern: "ia dat lui PlayerName(ID)" or "a dat lui PlayerName(ID)"
    match = re.search(r'(?:ia|a)\s+dat\s+lui\s+([^(]+)\((\d+)\)', action_detail, re.IGNORECASE)
    if match:
        return (match.group(2), match.group(1).strip())
    
    # Pattern: "primit de la PlayerName(ID)"
    match = re.search(r'primit\s+(?:de\s+la|de la)\s+([^(]+)\((\d+)\)', action_detail, re.IGNORECASE)
    if match:
        return (match.group(2), match.group(1).strip())
    
    return (None, None)

# Continue with rest of file...
[File truncated due to length - contains all pagination views, helper functions, and commands including admin commands]
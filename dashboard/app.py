#!/usr/bin/env python3
"""
Pro4Kings Web Dashboard - Real-time monitoring interface
Runs alongside the Discord bot on a separate port
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

@app.after_request
def add_no_cache_headers(response):
    """Disable caching for API responses to keep dashboard fresh."""
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Database path - same as bot (shared database)
def get_db_path():
    """Get database path - works both on Railway and locally"""
    # Railway volume mount
    if os.path.exists("/data"):
        return "/data/pro4kings.db"
    
    # Environment variable override
    env_path = os.getenv("DATABASE_PATH")
    if env_path:
        return env_path
    
    # Local development - check parent directory (since we're in dashboard/)
    parent_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pro4kings.db")
    if os.path.exists(parent_path):
        return parent_path
    
    # Fallback to relative path
    return "data/pro4kings.db"

def get_db_connection():
    """Get database connection with row factory"""
    conn = sqlite3.connect(get_db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _parse_timestamp(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None

def _format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def _time_ago(dt: datetime) -> str:
    if not dt:
        return ""
    diff = (datetime.now() - dt).total_seconds()
    if diff < 60:
        return "Just now"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    return f"{int(diff // 86400)}d ago"

def _normalize_action(action: dict) -> dict:
    ts = _parse_timestamp(action.get("timestamp"))
    if ts:
        action["timestamp_display"] = _format_timestamp(ts)
        action["time_ago"] = _time_ago(ts)
    else:
        action["timestamp_display"] = ""
        action["time_ago"] = ""
    return action

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/api/stats')
def api_stats():
    """Get overall database statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Total players
        cursor.execute("SELECT COUNT(*) FROM player_profiles")
        total_players = cursor.fetchone()[0]
        
        # Total actions
        cursor.execute("SELECT COUNT(*) FROM actions")
        total_actions = cursor.fetchone()[0]
        
        # Currently online (from online_players table, last 5 min)
        cutoff = datetime.now() - timedelta(minutes=5)
        cursor.execute("SELECT COUNT(*) FROM online_players WHERE detected_online_at >= ?", (cutoff,))
        online_now = cursor.fetchone()[0]
        
        # Actions in last 24h
        cutoff_24h = datetime.now() - timedelta(hours=24)
        cursor.execute("SELECT COUNT(*) FROM actions WHERE timestamp >= ?", (cutoff_24h,))
        actions_24h = cursor.fetchone()[0]
        
        # Logins today
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cursor.execute("SELECT COUNT(*) FROM login_events WHERE event_type = 'login' AND timestamp >= ?", (today,))
        logins_today = cursor.fetchone()[0]
        
        # Active bans
        cursor.execute("SELECT COUNT(*) FROM banned_players WHERE is_active = TRUE")
        active_bans = cursor.fetchone()[0]
        
        # Total factions
        cursor.execute("SELECT COUNT(DISTINCT faction) FROM player_profiles WHERE faction IS NOT NULL AND faction != ''")
        total_factions = cursor.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            'total_players': total_players,
            'total_actions': total_actions,
            'online_now': online_now,
            'actions_24h': actions_24h,
            'logins_today': logins_today,
            'active_bans': active_bans,
            'total_factions': total_factions,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/online')
def api_online():
    """Get currently online players"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cutoff = datetime.now() - timedelta(minutes=5)
        
        cursor.execute("""
            SELECT 
                o.player_id,
                o.player_name,
                o.detected_online_at,
                p.faction,
                p.faction_rank,
                p.played_hours
            FROM online_players o
            LEFT JOIN player_profiles p ON o.player_id = p.player_id
            WHERE o.detected_online_at >= ?
            ORDER BY o.detected_online_at DESC
        """, (cutoff,))
        
        players = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'count': len(players),
            'players': players
        })
    except Exception as e:
        logger.error(f"Error getting online players: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/actions')
def api_actions():
    """Get recent actions with optional filters"""
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
        action_type = request.args.get('type', None)
        player_id = request.args.get('player_id', None)
        player_query = request.args.get('player', None)
        per_page = min(int(request.args.get('per_page', limit)), 100)
        page = max(int(request.args.get('page', 1)), 1)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM actions WHERE 1=1"
        params = []
        
        if action_type:
            query += " AND action_type = ?"
            params.append(action_type)
        
        if player_id:
            query += " AND (player_id = ? OR target_player_id = ?)"
            params.extend([player_id, player_id])

        if player_query:
            query += " AND (player_name LIKE ? OR target_player_name LIKE ? OR player_id = ? OR target_player_id = ?)"
            like_query = f"%{player_query}%"
            params.extend([like_query, like_query, player_query, player_query])
        
        count_query = f"SELECT COUNT(*) FROM ({query}) AS filtered"
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()[0]

        offset = (page - 1) * per_page
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([per_page, offset])
        
        cursor.execute(query, params)
        actions = [_normalize_action(dict(row)) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'count': len(actions),
            'total_count': total_count,
            'total_pages': max(1, (total_count + per_page - 1) // per_page),
            'page': page,
            'per_page': per_page,
            'actions': actions
        })
    except Exception as e:
        logger.error(f"Error getting actions: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/action-types')
def api_action_types():
    """Get all action types with counts"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT action_type, COUNT(*) as count
            FROM actions
            GROUP BY action_type
            ORDER BY count DESC
        """)
        
        types = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({'types': types})
    except Exception as e:
        logger.error(f"Error getting action types: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/player/<player_id>')
def api_player(player_id):
    """Get player profile and recent activity"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get profile
        cursor.execute("SELECT * FROM player_profiles WHERE player_id = ?", (player_id,))
        profile = cursor.fetchone()
        
        if not profile:
            conn.close()
            return jsonify({'error': 'Player not found'}), 404
        
        profile_dict = dict(profile)
        
        # Check if currently online
        cutoff = datetime.now() - timedelta(minutes=5)
        cursor.execute("SELECT 1 FROM online_players WHERE player_id = ? AND detected_online_at >= ?", (player_id, cutoff))
        profile_dict['is_currently_online'] = cursor.fetchone() is not None
        
        # Get recent actions (last 7 days)
        cutoff_7d = datetime.now() - timedelta(days=7)
        cursor.execute("""
            SELECT * FROM actions 
            WHERE (player_id = ? OR target_player_id = ?)
            AND timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT 50
        """, (player_id, player_id, cutoff_7d))
        actions = [_normalize_action(dict(row)) for row in cursor.fetchall()]
        
        # Get recent sessions
        cursor.execute("""
            SELECT * FROM login_events 
            WHERE player_id = ?
            ORDER BY timestamp DESC
            LIMIT 20
        """, (player_id,))
        sessions = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'profile': profile_dict,
            'actions': actions,
            'sessions': sessions
        })
    except Exception as e:
        logger.error(f"Error getting player {player_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search')
def api_search():
    """Search players by name"""
    try:
        query = request.args.get('q', '').strip()
        if len(query) < 2:
            return jsonify({'error': 'Query must be at least 2 characters'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cutoff = datetime.now() - timedelta(minutes=5)
        
        cursor.execute("""
            SELECT 
                p.player_id,
                p.username,
                p.faction,
                p.faction_rank,
                p.played_hours,
                p.last_seen,
                CASE WHEN o.detected_online_at >= ? THEN 1 ELSE 0 END as is_currently_online
            FROM player_profiles p
            LEFT JOIN online_players o ON p.player_id = o.player_id
            WHERE p.username LIKE ?
            ORDER BY is_currently_online DESC, p.last_seen DESC
            LIMIT 25
        """, (cutoff, f"%{query}%",))
        
        players = [dict(row) for row in cursor.fetchall()]
        for player in players:
            player["is_online"] = bool(player.get("is_currently_online"))
        conn.close()
        
        return jsonify({
            'count': len(players),
            'players': players
        })
    except Exception as e:
        logger.error(f"Error searching: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/factions')
def api_factions():
    """Get all factions with member counts"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cutoff = datetime.now() - timedelta(minutes=5)
        
        cursor.execute("""
            SELECT 
                p.faction as name,
                COUNT(DISTINCT p.player_id) as member_count,
                COUNT(DISTINCT CASE WHEN o.detected_online_at >= ? THEN o.player_id ELSE NULL END) as online_count
            FROM player_profiles p
            LEFT JOIN online_players o ON p.player_id = o.player_id
            WHERE p.faction IS NOT NULL AND p.faction != '' 
            AND p.faction NOT IN ('Civil', 'Fără', 'None', '-', 'N/A')
            GROUP BY p.faction
            ORDER BY member_count DESC
        """, (cutoff,))
        
        factions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'count': len(factions),
            'factions': factions
        })
    except Exception as e:
        logger.error(f"Error getting factions: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/faction/<faction_name>')
def api_faction(faction_name):
    """Get faction members"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cutoff = datetime.now() - timedelta(minutes=5)
        
        cursor.execute("""
            SELECT 
                p.*,
                CASE WHEN o.detected_online_at >= ? THEN 1 ELSE 0 END as is_currently_online
            FROM player_profiles p
            LEFT JOIN online_players o ON p.player_id = o.player_id
            WHERE p.faction = ?
            ORDER BY is_currently_online DESC, p.faction_rank, p.last_seen DESC
        """, (cutoff, faction_name))
        
        members = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'faction': faction_name,
            'count': len(members),
            'members': members
        })
    except Exception as e:
        logger.error(f"Error getting faction {faction_name}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/bans')
def api_bans():
    """Get banned players"""
    try:
        include_expired = request.args.get('expired', 'false').lower() == 'true'
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if include_expired:
            cursor.execute("""
                SELECT b.*, p.played_hours, p.faction
                FROM banned_players b
                LEFT JOIN player_profiles p ON b.player_id = p.player_id
                ORDER BY b.detected_at DESC
            """)
        else:
            cursor.execute("""
                SELECT b.*, p.played_hours, p.faction
                FROM banned_players b
                LEFT JOIN player_profiles p ON b.player_id = p.player_id
                WHERE b.is_active = TRUE
                ORDER BY b.detected_at DESC
            """)
        
        bans = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'count': len(bans),
            'bans': bans
        })
    except Exception as e:
        logger.error(f"Error getting bans: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/activity-chart')
def api_activity_chart():
    """Get hourly activity data for charts (last 24 hours)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get hourly action counts for last 24 hours
        data = []
        now = datetime.now()
        
        for i in range(24, 0, -1):
            hour_start = now - timedelta(hours=i)
            hour_end = now - timedelta(hours=i-1)
            
            cursor.execute("""
                SELECT COUNT(*) FROM actions 
                WHERE timestamp >= ? AND timestamp < ?
            """, (hour_start, hour_end))
            count = cursor.fetchone()[0]
            
            data.append({
                'hour': hour_start.strftime('%H:%M'),
                'actions': count
            })
        
        conn.close()
        
        return jsonify({'data': data})
    except Exception as e:
        logger.error(f"Error getting activity chart: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin-actions')
def api_admin_actions():
    """Get recent admin actions (warnings, bans, jails)"""
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        admin_types = ('warning_received', 'ban_received', 'admin_jail', 'admin_unjail', 
                       'admin_unban', 'mute_received', 'faction_kicked', 'kill_character')
        placeholders = ','.join('?' * len(admin_types))
        
        cursor.execute(f"""
            SELECT * FROM actions 
            WHERE action_type IN ({placeholders})
            ORDER BY timestamp DESC
            LIMIT ?
        """, (*admin_types, limit))
        
        actions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'count': len(actions),
            'actions': actions
        })
    except Exception as e:
        logger.error(f"Error getting admin actions: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/promotions')
def api_promotions():
    """Get recent faction promotions (rank changes)"""
    try:
        days = min(int(request.args.get('days', 7)), 90)
        limit = min(int(request.args.get('limit', 100)), 500)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cutoff = datetime.now() - timedelta(days=days)
        
        cursor.execute("""
            SELECT 
                p.player_id,
                p.username as player_name,
                ph.old_value as old_rank,
                ph.new_value as new_rank,
                p.faction,
                ph.changed_at as timestamp
            FROM profile_history ph
            JOIN player_profiles p ON p.player_id = ph.player_id
            WHERE ph.field_name = 'faction_rank' 
            AND ph.changed_at >= ?
            ORDER BY ph.changed_at DESC
            LIMIT ?
        """, (cutoff, limit))
        
        promotions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'count': len(promotions),
            'days': days,
            'promotions': promotions
        })
    except Exception as e:
        logger.error(f"Error getting promotions: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/heists')
def api_heists():
    """Get bank heist deliveries with player faction info"""
    try:
        days = min(int(request.args.get('days', 30)), 90)
        limit = min(int(request.args.get('limit', 100)), 500)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cutoff = datetime.now() - timedelta(days=days)
        
        cursor.execute("""
            SELECT 
                a.player_id,
                a.player_name,
                a.action_type,
                a.action_detail,
                a.timestamp,
                p.faction,
                p.faction_rank
            FROM actions a
            LEFT JOIN player_profiles p ON a.player_id = p.player_id
            WHERE a.action_type = 'bank_heist_delivery'
            AND a.timestamp >= ?
            ORDER BY a.timestamp DESC
            LIMIT ?
        """, (cutoff, limit))
        
        heists = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'count': len(heists),
            'days': days,
            'heists': heists
        })
    except Exception as e:
        logger.error(f"Error getting heists: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/rank-history/<player_id>')
def api_rank_history(player_id):
    """Get player's faction rank history"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get rank history
        cursor.execute("""
            SELECT * FROM rank_history 
            WHERE player_id = ? 
            ORDER BY rank_obtained DESC
        """, (player_id,))
        
        history = [dict(row) for row in cursor.fetchall()]
        
        # Get player name
        cursor.execute("SELECT username FROM player_profiles WHERE player_id = ?", (player_id,))
        row = cursor.fetchone()
        player_name = row['username'] if row else f"Player_{player_id}"
        
        conn.close()
        
        return jsonify({
            'player_id': player_id,
            'player_name': player_name,
            'count': len(history),
            'history': history
        })
    except Exception as e:
        logger.error(f"Error getting rank history for {player_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<player_id>')
def api_sessions(player_id):
    """Get player's detailed session history with first/last login info"""
    try:
        days = min(int(request.args.get('days', 7)), 90)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get player name
        cursor.execute("SELECT username FROM player_profiles WHERE player_id = ?", (player_id,))
        row = cursor.fetchone()
        player_name = row['username'] if row else f"Player_{player_id}"
        
        # Get first ever login
        cursor.execute("""
            SELECT timestamp FROM login_events
            WHERE player_id = ? AND event_type = 'login'
            ORDER BY timestamp ASC
            LIMIT 1
        """, (player_id,))
        row = cursor.fetchone()
        first_login = row['timestamp'] if row else None
        
        # Get last login
        cursor.execute("""
            SELECT timestamp FROM login_events
            WHERE player_id = ? AND event_type = 'login'
            ORDER BY timestamp DESC
            LIMIT 1
        """, (player_id,))
        row = cursor.fetchone()
        last_login = row['timestamp'] if row else None
        
        # Count total logins
        cursor.execute("""
            SELECT COUNT(*) as count FROM login_events
            WHERE player_id = ? AND event_type = 'login'
        """, (player_id,))
        total_logins = cursor.fetchone()['count']
        
        # Get recent sessions (login/logout pairs) with duration
        cutoff = datetime.now() - timedelta(days=days)
        
        cursor.execute("""
            WITH ordered_events AS (
                SELECT 
                    id,
                    event_type,
                    timestamp,
                    session_duration_seconds,
                    ROW_NUMBER() OVER (ORDER BY timestamp ASC) as rn
                FROM login_events
                WHERE player_id = ?
                AND timestamp >= ?
            ),
            logouts_with_prev AS (
                SELECT 
                    o.rn as logout_rn,
                    o.timestamp as logout_time,
                    o.session_duration_seconds,
                    COALESCE(
                        (SELECT MAX(p.rn) FROM ordered_events p 
                         WHERE p.event_type = 'logout' AND p.rn < o.rn),
                        0
                    ) as prev_logout_rn
                FROM ordered_events o
                WHERE o.event_type = 'logout'
            )
            SELECT 
                (SELECT MIN(e.timestamp) 
                 FROM ordered_events e 
                 WHERE e.event_type = 'login' 
                 AND e.rn > lwp.prev_logout_rn 
                 AND e.rn < lwp.logout_rn) as login_time,
                lwp.logout_time,
                lwp.session_duration_seconds
            FROM logouts_with_prev lwp
            WHERE (SELECT MIN(e.timestamp) 
                   FROM ordered_events e 
                   WHERE e.event_type = 'login' 
                   AND e.rn > lwp.prev_logout_rn 
                   AND e.rn < lwp.logout_rn) IS NOT NULL
            ORDER BY lwp.logout_time DESC
            LIMIT 100
        """, (player_id, cutoff))
        
        sessions = [dict(row) for row in cursor.fetchall()]
        
        # Calculate total playtime from sessions
        total_seconds = sum(s.get('session_duration_seconds', 0) or 0 for s in sessions)
        total_hours = total_seconds / 3600
        
        conn.close()
        
        return jsonify({
            'player_id': player_id,
            'player_name': player_name,
            'first_login': first_login,
            'last_login': last_login,
            'total_logins': total_logins,
            'days': days,
            'session_count': len(sessions),
            'total_hours': round(total_hours, 2),
            'sessions': sessions
        })
    except Exception as e:
        logger.error(f"Error getting sessions for {player_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/faction-actions/<faction_name>')
def api_faction_actions(faction_name):
    """Get all actions for players in a specific faction"""
    try:
        days = min(int(request.args.get('days', 7)), 30)
        limit = min(int(request.args.get('limit', 200)), 500)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cutoff = datetime.now() - timedelta(days=days)
        
        # Get all player IDs in this faction
        cursor.execute("""
            SELECT player_id FROM player_profiles WHERE faction = ?
        """, (faction_name,))
        faction_player_ids = [row['player_id'] for row in cursor.fetchall()]
        
        if not faction_player_ids:
            conn.close()
            return jsonify({
                'faction': faction_name,
                'count': 0,
                'actions': []
            })
        
        # Get all actions for these players
        placeholders = ','.join('?' * len(faction_player_ids))
        cursor.execute(f"""
            SELECT 
                a.*,
                p.faction,
                p.faction_rank
            FROM actions a
            LEFT JOIN player_profiles p ON a.player_id = p.player_id
            WHERE a.player_id IN ({placeholders})
            AND a.timestamp >= ?
            ORDER BY a.timestamp DESC
            LIMIT ?
        """, (*faction_player_ids, cutoff, limit))
        
        actions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'faction': faction_name,
            'days': days,
            'member_count': len(faction_player_ids),
            'count': len(actions),
            'actions': actions
        })
    except Exception as e:
        logger.error(f"Error getting faction actions for {faction_name}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/unknown-actions')
def api_unknown_actions():
    """Get unrecognized action patterns for analysis"""
    try:
        limit = min(int(request.args.get('limit', 50)), 500)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get unique unknown patterns with counts
        cursor.execute("""
            SELECT action_type, action_detail, raw_text, COUNT(*) as count
            FROM actions 
            WHERE action_type IN ('unknown', 'other')
            GROUP BY raw_text
            ORDER BY count DESC
            LIMIT ?
        """, (limit,))
        
        patterns = [dict(row) for row in cursor.fetchall()]
        
        # Get total count
        cursor.execute("""
            SELECT COUNT(*) as total FROM actions 
            WHERE action_type IN ('unknown', 'other')
        """)
        total = cursor.fetchone()['total']
        
        conn.close()
        
        return jsonify({
            'total_unknown': total,
            'unique_patterns': len(patterns),
            'patterns': patterns
        })
    except Exception as e:
        logger.error(f"Error getting unknown actions: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/action-stats')
def api_action_stats():
    """Get action type statistics breakdown"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT action_type, COUNT(*) as count
            FROM actions
            GROUP BY action_type
            ORDER BY count DESC
        """)
        
        stats = [dict(row) for row in cursor.fetchall()]
        total = sum(s['count'] for s in stats)
        
        # Separate recognized vs unrecognized
        recognized = [s for s in stats if s['action_type'] not in ('unknown', 'other')]
        unrecognized = [s for s in stats if s['action_type'] in ('unknown', 'other')]
        
        recognized_count = sum(s['count'] for s in recognized)
        unrecognized_count = sum(s['count'] for s in unrecognized)
        
        conn.close()
        
        return jsonify({
            'total_actions': total,
            'recognized_count': recognized_count,
            'unrecognized_count': unrecognized_count,
            'recognition_rate': round((recognized_count / total * 100), 2) if total > 0 else 0,
            'by_type': stats
        })
    except Exception as e:
        logger.error(f"Error getting action stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/scan-progress')
def api_scan_progress():
    """Get initial scan progress (admin info)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM scan_progress WHERE id = 1")
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return jsonify({'error': 'No scan progress data'}), 404
        
        progress = dict(row)
        conn.close()
        
        return jsonify(progress)
    except Exception as e:
        logger.error(f"Error getting scan progress: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/profile-history/<player_id>')
def api_profile_history(player_id):
    """Get player's profile change history"""
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM profile_history
            WHERE player_id = ?
            ORDER BY changed_at DESC
            LIMIT ?
        """, (player_id, limit))
        
        history = [dict(row) for row in cursor.fetchall()]
        
        # Get player name
        cursor.execute("SELECT username FROM player_profiles WHERE player_id = ?", (player_id,))
        row = cursor.fetchone()
        player_name = row['username'] if row else f"Player_{player_id}"
        
        conn.close()
        
        return jsonify({
            'player_id': player_id,
            'player_name': player_name,
            'count': len(history),
            'history': history
        })
    except Exception as e:
        logger.error(f"Error getting profile history for {player_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/login-activity')
def api_login_activity():
    """Get login/logout activity for specified time period"""
    try:
        hours = min(int(request.args.get('hours', 24)), 168)  # Max 7 days
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cutoff = datetime.now() - timedelta(hours=hours)
        
        # Get hourly login/logout counts
        data = []
        now = datetime.now()
        
        for i in range(hours, 0, -1):
            hour_start = now - timedelta(hours=i)
            hour_end = now - timedelta(hours=i-1)
            
            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN event_type = 'login' THEN 1 ELSE 0 END) as logins,
                    SUM(CASE WHEN event_type = 'logout' THEN 1 ELSE 0 END) as logouts
                FROM login_events 
                WHERE timestamp >= ? AND timestamp < ?
            """, (hour_start, hour_end))
            
            row = cursor.fetchone()
            data.append({
                'hour': hour_start.strftime('%Y-%m-%d %H:00'),
                'logins': row['logins'] or 0,
                'logouts': row['logouts'] or 0
            })
        
        conn.close()
        
        return jsonify({
            'hours': hours,
            'data': data
        })
    except Exception as e:
        logger.error(f"Error getting login activity: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    port = int(os.getenv('DASHBOARD_PORT', 5000))
    debug = os.getenv('DASHBOARD_DEBUG', 'false').lower() == 'true'
    
    logger.info(f"🌐 Starting Pro4Kings Web Dashboard on port {port}")
    logger.info(f"📁 Database: {get_db_path()}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)

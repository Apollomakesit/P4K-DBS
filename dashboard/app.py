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
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        actions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'count': len(actions),
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
        actions = [dict(row) for row in cursor.fetchall()]
        
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
        
        cursor.execute("""
            SELECT player_id, username, faction, faction_rank, played_hours, is_online, last_seen
            FROM player_profiles
            WHERE username LIKE ?
            ORDER BY is_online DESC, last_seen DESC
            LIMIT 25
        """, (f"%{query}%",))
        
        players = [dict(row) for row in cursor.fetchall()]
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

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    port = int(os.getenv('DASHBOARD_PORT', 5000))
    debug = os.getenv('DASHBOARD_DEBUG', 'false').lower() == 'true'
    
    logger.info(f"🌐 Starting Pro4Kings Web Dashboard on port {port}")
    logger.info(f"📁 Database: {get_db_path()}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)

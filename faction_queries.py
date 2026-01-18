"""Database queries specifically for faction data analysis"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class FactionQueries:
    """Extended database queries for faction analysis"""
    
    def __init__(self, db):
        self.db = db
    
    def get_all_factions(self) -> List[str]:
        """Get list of all factions excluding civilians"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT faction 
                FROM players 
                WHERE faction IS NOT NULL 
                AND faction NOT IN ('Civil', 'Fără', 'None', '-', '')
                AND faction != ''
                ORDER BY faction
            """)
            return [row[0] for row in cursor.fetchall()]
    
    def get_faction_members(self, faction_name: str) -> Dict:
        """Get all members of a faction with online/offline split"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get online members
            cursor.execute("""
                SELECT 
                    player_id,
                    username,
                    faction_rank,
                    level,
                    respect_points,
                    warnings,
                    played_hours,
                    last_seen,
                    is_online
                FROM players
                WHERE faction = ? AND is_online = TRUE
                ORDER BY 
                    CASE faction_rank
                        WHEN 'Lider' THEN 1
                        WHEN 'Sublider' THEN 2
                        WHEN 'Rang 6' THEN 3
                        WHEN 'Rang 5' THEN 4
                        WHEN 'Rang 4' THEN 5
                        WHEN 'Rang 3' THEN 6
                        WHEN 'Rang 2' THEN 7
                        WHEN 'Rang 1' THEN 8
                        ELSE 9
                    END,
                    level DESC
            """, (faction_name,))
            online_members = [dict(row) for row in cursor.fetchall()]
            
            # Get offline members
            cursor.execute("""
                SELECT 
                    player_id,
                    username,
                    faction_rank,
                    level,
                    respect_points,
                    warnings,
                    played_hours,
                    last_seen,
                    is_online
                FROM players
                WHERE faction = ? AND (is_online = FALSE OR is_online IS NULL)
                ORDER BY last_seen DESC
                LIMIT 50
            """, (faction_name,))
            offline_members = [dict(row) for row in cursor.fetchall()]
            
            return {
                'online': online_members,
                'offline': offline_members,
                'total': len(online_members) + len(offline_members)
            }
    
    def get_faction_stats(self, faction_name: str, days: int = 7) -> Dict:
        """Get faction activity statistics"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            # Total members
            cursor.execute("""
                SELECT COUNT(*) FROM players
                WHERE faction = ?
            """, (faction_name,))
            total_members = cursor.fetchone()[0]
            
            # Online members
            cursor.execute("""
                SELECT COUNT(*) FROM players
                WHERE faction = ? AND is_online = TRUE
            """, (faction_name,))
            online_count = cursor.fetchone()[0]
            
            # Average level
            cursor.execute("""
                SELECT AVG(level), MAX(level)
                FROM players
                WHERE faction = ? AND level IS NOT NULL
            """, (faction_name,))
            level_stats = cursor.fetchone()
            avg_level = level_stats[0] or 0
            max_level = level_stats[1] or 0
            
            # Recent actions count
            cursor.execute("""
                SELECT COUNT(DISTINCT a.id)
                FROM actions a
                JOIN players p ON a.player_id = p.player_id
                WHERE p.faction = ? AND a.timestamp >= ?
            """, (faction_name, cutoff))
            recent_actions = cursor.fetchone()[0]
            
            # Active members (had actions in last 7 days)
            cursor.execute("""
                SELECT COUNT(DISTINCT p.player_id)
                FROM players p
                JOIN actions a ON p.player_id = a.player_id
                WHERE p.faction = ? AND a.timestamp >= ?
            """, (faction_name, cutoff))
            active_members = cursor.fetchone()[0]
            
            # Average playtime
            cursor.execute("""
                SELECT AVG(played_hours)
                FROM players
                WHERE faction = ? AND played_hours IS NOT NULL
            """, (faction_name,))
            avg_playtime = cursor.fetchone()[0] or 0
            
            return {
                'total_members': total_members,
                'online_count': online_count,
                'avg_level': avg_level,
                'max_level': max_level,
                'recent_actions': recent_actions,
                'active_members': active_members,
                'avg_playtime': avg_playtime,
                'activity_rate': (active_members / total_members * 100) if total_members > 0 else 0
            }
    
    def get_faction_activity_ranking(self, days: int = 7, limit: int = 10) -> List[Dict]:
        """Rank factions by activity"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            cursor.execute("""
                SELECT 
                    p.faction,
                    COUNT(DISTINCT p.player_id) as total_members,
                    COUNT(DISTINCT CASE WHEN p.is_online THEN p.player_id END) as online_now,
                    COUNT(DISTINCT a.player_id) as active_members,
                    COUNT(a.id) as total_actions,
                    AVG(p.level) as avg_level,
                    AVG(p.played_hours) as avg_playtime,
                    -- Activity score: combines actions, active members, and online presence
                    (
                        COUNT(a.id) * 1.0 +                                    -- Raw actions
                        COUNT(DISTINCT a.player_id) * 10.0 +                   -- Unique active members (weighted 10x)
                        COUNT(DISTINCT CASE WHEN p.is_online THEN p.player_id END) * 5.0  -- Online members (weighted 5x)
                    ) as activity_score
                FROM players p
                LEFT JOIN actions a ON p.player_id = a.player_id AND a.timestamp >= ?
                WHERE p.faction IS NOT NULL 
                AND p.faction NOT IN ('Civil', 'Fără', 'None', '-', '')
                AND p.faction != ''
                GROUP BY p.faction
                HAVING total_members > 0
                ORDER BY activity_score DESC
                LIMIT ?
            """, (cutoff, limit))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'faction': row[0],
                    'total_members': row[1],
                    'online_now': row[2],
                    'active_members': row[3],
                    'total_actions': row[4],
                    'avg_level': row[5] or 0,
                    'avg_playtime': row[6] or 0,
                    'activity_score': row[7],
                    'activity_rate': (row[3] / row[1] * 100) if row[1] > 0 else 0
                })
            
            return results
    
    def get_faction_recent_actions(self, faction_name: str, days: int = 7, limit: int = 50) -> List[Dict]:
        """Get recent actions by faction members"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            cursor.execute("""
                SELECT 
                    a.*,
                    p.faction_rank
                FROM actions a
                JOIN players p ON a.player_id = p.player_id
                WHERE p.faction = ? AND a.timestamp >= ?
                ORDER BY a.timestamp DESC
                LIMIT ?
            """, (faction_name, cutoff, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_faction_online_history(self, faction_name: str, days: int = 7) -> Dict:
        """Get faction online player history"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days)
            
            # Get unique login events
            cursor.execute("""
                SELECT 
                    DATE(l.timestamp) as date,
                    COUNT(DISTINCT l.player_id) as unique_logins,
                    AVG(l.session_duration_seconds) / 3600.0 as avg_session_hours
                FROM login_events l
                JOIN players p ON l.player_id = p.player_id
                WHERE p.faction = ? 
                AND l.event_type = 'login'
                AND l.timestamp >= ?
                GROUP BY DATE(l.timestamp)
                ORDER BY date DESC
            """, (faction_name, cutoff))
            
            daily_logins = []
            for row in cursor.fetchall():
                daily_logins.append({
                    'date': row[0],
                    'unique_logins': row[1],
                    'avg_session_hours': row[2] or 0
                })
            
            # Calculate average daily online
            avg_daily_logins = sum(d['unique_logins'] for d in daily_logins) / len(daily_logins) if daily_logins else 0
            
            return {
                'daily_logins': daily_logins,
                'avg_daily_logins': avg_daily_logins
            }
    
    def get_faction_rank_distribution(self, faction_name: str) -> Dict:
        """Get distribution of ranks within faction"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    faction_rank,
                    COUNT(*) as count,
                    COUNT(CASE WHEN is_online THEN 1 END) as online_count
                FROM players
                WHERE faction = ?
                GROUP BY faction_rank
                ORDER BY 
                    CASE faction_rank
                        WHEN 'Lider' THEN 1
                        WHEN 'Sublider' THEN 2
                        WHEN 'Rang 6' THEN 3
                        WHEN 'Rang 5' THEN 4
                        WHEN 'Rang 4' THEN 5
                        WHEN 'Rang 3' THEN 6
                        WHEN 'Rang 2' THEN 7
                        WHEN 'Rang 1' THEN 8
                        ELSE 9
                    END
            """, (faction_name,))
            
            distribution = {}
            for row in cursor.fetchall():
                rank = row[0] or 'Unknown'
                distribution[rank] = {
                    'total': row[1],
                    'online': row[2]
                }
            
            return distribution

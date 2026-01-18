"""Configuration management with environment variables"""
import os
from typing import Optional

class Config:
    """Centralized configuration with environment variable support"""
    
    # Discord
    DISCORD_TOKEN: str = os.getenv('DISCORD_TOKEN', '')
    ADMIN_USER_IDS: list[int] = [
        int(uid.strip()) 
        for uid in os.getenv('ADMIN_USER_IDS', '').split(',') 
        if uid.strip().isdigit()
    ]
    
    # Database
    DATABASE_PATH: str = os.getenv('DATABASE_PATH', '/data/pro4kings.db')
    DATABASE_BACKUP_PATH: str = os.getenv('DATABASE_BACKUP_PATH', '/data/backups')
    
    # Scraper Settings
    SCRAPER_MAX_CONCURRENT: int = int(os.getenv('SCRAPER_MAX_CONCURRENT', '5'))
    SCRAPER_RATE_LIMIT: float = float(os.getenv('SCRAPER_RATE_LIMIT', '25.0'))  # requests/sec
    SCRAPER_BURST_CAPACITY: int = int(os.getenv('SCRAPER_BURST_CAPACITY', '50'))
    
    # Task Intervals (in seconds)
    SCRAPE_ACTIONS_INTERVAL: int = int(os.getenv('SCRAPE_ACTIONS_INTERVAL', '30'))
    SCRAPE_ONLINE_INTERVAL: int = int(os.getenv('SCRAPE_ONLINE_INTERVAL', '60'))
    UPDATE_PROFILES_INTERVAL: int = int(os.getenv('UPDATE_PROFILES_INTERVAL', '120'))  # 2 min
    CHECK_BANNED_INTERVAL: int = int(os.getenv('CHECK_BANNED_INTERVAL', '3600'))  # 1 hour
    TASK_WATCHDOG_INTERVAL: int = int(os.getenv('TASK_WATCHDOG_INTERVAL', '300'))  # 5 min
    
    # Data Retention (in days)
    ACTIONS_RETENTION_DAYS: int = int(os.getenv('ACTIONS_RETENTION_DAYS', '90'))  # Keep 3 months
    LOGIN_EVENTS_RETENTION_DAYS: int = int(os.getenv('LOGIN_EVENTS_RETENTION_DAYS', '30'))  # Keep 1 month
    PROFILE_HISTORY_RETENTION_DAYS: int = int(os.getenv('PROFILE_HISTORY_RETENTION_DAYS', '180'))  # Keep 6 months
    
    # Batch Sizes
    ACTIONS_FETCH_LIMIT: int = int(os.getenv('ACTIONS_FETCH_LIMIT', '200'))
    PROFILES_UPDATE_BATCH: int = int(os.getenv('PROFILES_UPDATE_BATCH', '200'))
    
    # Logging
    LOG_FILE_PATH: str = os.getenv('LOG_FILE_PATH', 'bot.log')
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_MAX_BYTES: int = int(os.getenv('LOG_MAX_BYTES', '10485760'))  # 10 MB
    LOG_BACKUP_COUNT: int = int(os.getenv('LOG_BACKUP_COUNT', '5'))  # Keep 5 old logs
    
    # Error Notifications
    ENABLE_ERROR_NOTIFICATIONS: bool = os.getenv('ENABLE_ERROR_NOTIFICATIONS', 'true').lower() == 'true'
    ERROR_NOTIFICATION_COOLDOWN: int = int(os.getenv('ERROR_NOTIFICATION_COOLDOWN', '300'))  # 5 min between same error
    
    # Health Checks
    TASK_HEALTH_CHECK_MULTIPLIER: dict = {
        'scrape_actions': 4,  # Alert if no run in 4x interval (2 minutes)
        'scrape_online_players': 3,  # Alert if no run in 3x interval (3 minutes)
        'update_pending_profiles': 3,  # Alert if no run in 3x interval (6 minutes)
        'check_banned_players': 2  # Alert if no run in 2x interval (2 hours)
    }
    
    @classmethod
    def validate(cls) -> list[str]:
        """Validate configuration and return list of issues"""
        issues = []
        
        if not cls.DISCORD_TOKEN:
            issues.append("DISCORD_TOKEN is not set")
        
        if not cls.ADMIN_USER_IDS:
            issues.append("No ADMIN_USER_IDS configured (error notifications disabled)")
        
        if cls.SCRAPER_MAX_CONCURRENT < 1:
            issues.append(f"SCRAPER_MAX_CONCURRENT must be >= 1 (got {cls.SCRAPER_MAX_CONCURRENT})")
        
        if cls.SCRAPER_RATE_LIMIT < 1:
            issues.append(f"SCRAPER_RATE_LIMIT must be >= 1 (got {cls.SCRAPER_RATE_LIMIT})")
        
        return issues
    
    @classmethod
    def display(cls) -> str:
        """Return formatted configuration display"""
        return f"""**Configuration:**

**Database:**
• Path: `{cls.DATABASE_PATH}`
• Backup: `{cls.DATABASE_BACKUP_PATH}`

**Task Intervals:**
• Scrape Actions: {cls.SCRAPE_ACTIONS_INTERVAL}s
• Scrape Online: {cls.SCRAPE_ONLINE_INTERVAL}s
• Update Profiles: {cls.UPDATE_PROFILES_INTERVAL}s
• Check Banned: {cls.CHECK_BANNED_INTERVAL}s
• Watchdog: {cls.TASK_WATCHDOG_INTERVAL}s

**Data Retention:**
• Actions: {cls.ACTIONS_RETENTION_DAYS} days
• Login Events: {cls.LOGIN_EVENTS_RETENTION_DAYS} days
• Profile History: {cls.PROFILE_HISTORY_RETENTION_DAYS} days

**Scraper:**
• Max Concurrent: {cls.SCRAPER_MAX_CONCURRENT}
• Rate Limit: {cls.SCRAPER_RATE_LIMIT} req/s
• Burst Capacity: {cls.SCRAPER_BURST_CAPACITY}

**Batch Sizes:**
• Actions Fetch: {cls.ACTIONS_FETCH_LIMIT}
• Profile Updates: {cls.PROFILES_UPDATE_BATCH}

**Logging:**
• File: `{cls.LOG_FILE_PATH}`
• Level: {cls.LOG_LEVEL}
• Max Size: {cls.LOG_MAX_BYTES / 1024 / 1024:.1f} MB
• Backups: {cls.LOG_BACKUP_COUNT}

**Notifications:**
• Error Alerts: {'✅ Enabled' if cls.ENABLE_ERROR_NOTIFICATIONS else '❌ Disabled'}
• Admins: {len(cls.ADMIN_USER_IDS)} configured
• Cooldown: {cls.ERROR_NOTIFICATION_COOLDOWN}s
"""

# Initialize and validate on import
_issues = Config.validate()
if _issues:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Configuration issues: {', '.join(_issues)}")

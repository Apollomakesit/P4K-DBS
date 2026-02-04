"""Configuration management with environment variables"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _safe_int(key: str, default: int) -> int:
    """Safely parse int from env var with fallback"""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        logger.warning(f"Invalid {key} env var, using default: {default}")
        return default


def _safe_float(key: str, default: float) -> float:
    """Safely parse float from env var with fallback"""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        logger.warning(f"Invalid {key} env var, using default: {default}")
        return default


class Config:
    """Centralized configuration with environment variable support"""

    # Discord
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    ADMIN_USER_IDS: list[int] = [
        int(uid.strip())
        for uid in os.getenv("ADMIN_USER_IDS", "").split(",")
        if uid.strip().isdigit()
    ]

    # Database (relative paths for portability)
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/pro4kings.db")
    DATABASE_BACKUP_PATH: str = os.getenv("DATABASE_BACKUP_PATH", "data/backups")

    # Scraper Settings
    # 🔥 OPTIMIZED: Based on testing panel.pro4kings.ro (30 connection limit shared hosting)
    # Tests showed 5 workers at ~20 req/s sustained works, but we use conservative limits
    SCRAPER_MAX_CONCURRENT: int = _safe_int("SCRAPER_MAX_CONCURRENT", 5)
    SCRAPER_RATE_LIMIT: float = _safe_float("SCRAPER_RATE_LIMIT", 10.0)  # requests/sec (reduced from 25)
    SCRAPER_BURST_CAPACITY: int = _safe_int("SCRAPER_BURST_CAPACITY", 20)  # reduced from 50

    # VIP Player Tracking - Monitor specific high-priority players
    # DISABLED - general actions scraper now covers all actions
    VIP_PLAYER_IDS: list[str] = [
        pid.strip()
        for pid in os.getenv(
            "VIP_PLAYER_IDS",
            "",  # Empty list - disabled
        ).split(",")
        if pid.strip()
    ]
    VIP_SCAN_INTERVAL: int = _safe_int(
        "VIP_SCAN_INTERVAL", 600
    )  # Scan VIP actions every 10m

    # Online Player Priority - Automatically track all currently online players
    # DISABLED - general actions scraper already covers online player actions
    TRACK_ONLINE_PLAYERS_PRIORITY: bool = (
        os.getenv("TRACK_ONLINE_PLAYERS_PRIORITY", "false").lower() == "true"
    )
    ONLINE_PLAYERS_SCAN_INTERVAL: int = _safe_int(
        "ONLINE_PLAYERS_SCAN_INTERVAL", 60
    )  # Scan online players' actions every 1m

    # Task Intervals (in seconds)
    SCRAPE_ACTIONS_INTERVAL: int = _safe_int("SCRAPE_ACTIONS_INTERVAL", 5)
    SCRAPE_ONLINE_INTERVAL: int = _safe_int("SCRAPE_ONLINE_INTERVAL", 60)
    UPDATE_PROFILES_INTERVAL: int = _safe_int("UPDATE_PROFILES_INTERVAL", 120)  # 2 min
    CHECK_BANNED_INTERVAL: int = _safe_int("CHECK_BANNED_INTERVAL", 7200)  # 2 hours
    TASK_WATCHDOG_INTERVAL: int = _safe_int("TASK_WATCHDOG_INTERVAL", 300)  # 5 min

    # Data Retention (in days)
    ACTIONS_RETENTION_DAYS: int = _safe_int(
        "ACTIONS_RETENTION_DAYS", 90
    )  # Keep 3 months
    LOGIN_EVENTS_RETENTION_DAYS: int = _safe_int(
        "LOGIN_EVENTS_RETENTION_DAYS", 30
    )  # Keep 1 month
    PROFILE_HISTORY_RETENTION_DAYS: int = _safe_int(
        "PROFILE_HISTORY_RETENTION_DAYS", 180
    )  # Keep 6 months

    # Batch Sizes
    ACTIONS_FETCH_LIMIT: int = _safe_int("ACTIONS_FETCH_LIMIT", 200)
    PROFILES_UPDATE_BATCH: int = _safe_int("PROFILES_UPDATE_BATCH", 200)

    # Logging
    LOG_FILE_PATH: str = os.getenv("LOG_FILE_PATH", "bot.log")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_MAX_BYTES: int = _safe_int("LOG_MAX_BYTES", 10485760)  # 10 MB
    LOG_BACKUP_COUNT: int = _safe_int("LOG_BACKUP_COUNT", 5)  # Keep 5 old logs

    # Error Notifications
    ENABLE_ERROR_NOTIFICATIONS: bool = (
        os.getenv("ENABLE_ERROR_NOTIFICATIONS", "true").lower() == "true"
    )
    ERROR_NOTIFICATION_COOLDOWN: int = _safe_int(
        "ERROR_NOTIFICATION_COOLDOWN", 300
    )  # 5 min between same error

    # Health Checks
    TASK_HEALTH_CHECK_MULTIPLIER: dict = {
        "scrape_actions": 4,  # Alert if no run in 4x interval (2 minutes)
        "scrape_online_players": 3,  # Alert if no run in 3x interval (3 minutes)
        "update_pending_profiles": 3,  # Alert if no run in 3x interval (6 minutes)
        "check_banned_players": 2,  # Alert if no run in 2x interval (2 hours)
        "scrape_vip_actions": 5,  # Alert if no run in 5x interval (50 seconds for VIP)
        "scrape_online_priority_actions": 5,  # Alert if no run in 5x interval (75 seconds for online)
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
            issues.append(
                f"SCRAPER_MAX_CONCURRENT must be >= 1 (got {cls.SCRAPER_MAX_CONCURRENT})"
            )

        if cls.SCRAPER_RATE_LIMIT < 1:
            issues.append(
                f"SCRAPER_RATE_LIMIT must be >= 1 (got {cls.SCRAPER_RATE_LIMIT})"
            )

        return issues

    @classmethod
    def display(cls) -> str:
        """Return formatted configuration display"""
        vip_count = len(cls.VIP_PLAYER_IDS)
        vip_display = (
            f"\n• VIP Players: {vip_count} configured" if vip_count > 0 else ""
        )
        vip_interval_display = (
            f"\n• VIP Scan Interval: {cls.VIP_SCAN_INTERVAL}s" if vip_count > 0 else ""
        )

        online_tracking = ""
        if cls.TRACK_ONLINE_PLAYERS_PRIORITY:
            online_tracking = f"\n• Online Player Priority: ✅ Enabled ({cls.ONLINE_PLAYERS_SCAN_INTERVAL}s interval)"

        return f"""**Configuration:**

**Database:**
• Path: `{cls.DATABASE_PATH}`
• Backup: `{cls.DATABASE_BACKUP_PATH}`

**Task Intervals:**
• Scrape Actions: {cls.SCRAPE_ACTIONS_INTERVAL}s{vip_interval_display}{online_tracking}
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
• Burst Capacity: {cls.SCRAPER_BURST_CAPACITY}{vip_display}

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
    logger.warning(f"Configuration issues: {', '.join(_issues)}")

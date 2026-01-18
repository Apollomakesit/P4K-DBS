import httpx
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Tuple
import re
import logging
import random
import time
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class PlayerAction:
    """Player action data"""
    player_id: Optional[str]
    player_name: Optional[str]
    action_type: str
    action_detail: str
    item_name: Optional[str] = None
    item_quantity: Optional[int] = None
    target_player_id: Optional[str] = None
    target_player_name: Optional[str] = None
    admin_id: Optional[str] = None
    admin_name: Optional[str] = None
    warning_count: Optional[str] = None
    reason: Optional[str] = None
    timestamp: datetime = None
    raw_text: str = None

@dataclass
class PlayerProfile:
    """Complete player profile"""
    player_id: str
    username: str
    is_online: bool
    last_seen: datetime
    faction: Optional[str] = None
    faction_rank: Optional[str] = None
    job: Optional[str] = None
    level: Optional[int] = None
    respect_points: Optional[int] = None
    warnings: Optional[int] = None
    played_hours: Optional[float] = None
    age_ic: Optional[int] = None
    phone_number: Optional[str] = None
    vehicles_count: Optional[int] = None
    properties_count: Optional[int] = None
    profile_data: Dict = field(default_factory=dict)

class TokenBucketRateLimiter:
    """Rate limiter care permite burst-uri controlate"""
    def __init__(self, rate: float = 40.0, capacity: int = 60):
        """
        🔥 OPTIMIZED: Crescut la 40 req/s, capacity 60
        rate: request-uri pe secundă permise
        capacity: dimensiunea burst-ului maxim
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.time()
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Așteaptă până când un token devine disponibil"""
        async with self.lock:
            now = time.time()
            # Adaugă token-uri noi bazat pe timp trecut
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            # Așteaptă dacă nu sunt token-uri disponibile
            if self.tokens < 1.0:
                wait_time = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
            else:
                self.tokens -= 1.0

class Pro4KingsScraper:
    """Enhanced scraper optimized for fast scanning with intelligent rate limiting"""
    
    def __init__(self, base_url: str = "https://panel.pro4kings.ro", max_concurrent: int = 20):
        self.base_url = base_url
        self.max_concurrent = max_concurrent  # 🔥 INCREASED: 10 → 20
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.client: Optional[httpx.AsyncClient] = None
        
        # 🔥 OPTIMIZED RATE LIMITER
        self.rate_limiter = TokenBucketRateLimiter(
            rate=40.0,       # 🔥 Crescut de la 25 la 40 request-uri/secundă
            capacity=60      # 🔥 Crescut de la 50 la 60 pentru burst mai mare
        )
        
        # Track 503 errors pentru adaptive throttling
        self.error_503_count = 0
        self.success_count = 0
        self.adaptive_delay = 0.01  # 🔥 Redus de la 20ms la 10ms
        
        # 🔥 ACTION SCRAPING STATS
        self.action_scraping_stats = {
            'total_attempts': 0,
            'successful_parses': 0,
            'failed_parses': 0,
            'total_actions_found': 0
        }
        
        self.last_request_time = {}  # Track per-worker
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ro-RO,ro;q=0.9,en;q=0.8',
        }
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=15.0,
            limits=httpx.Limits(
                max_connections=self.max_concurrent * 2,
                max_keepalive_connections=self.max_concurrent
            ),
            follow_redirects=True,
            verify=False
        )
        logger.info(f"✓ HTTP client initialized ({self.max_concurrent} workers, rate: {self.rate_limiter.rate} req/s)")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.client:
            await self.client.aclose()
    
    async def fetch_page(self, url: str, retries: int = 3) -> Optional[str]:
        """Fetch cu rate limiting și adaptive throttling"""
        
        # 🔥 AȘTEAPTĂ RATE LIMITER
        await self.rate_limiter.acquire()
        
        # Adaugă jitter (randomizare) pentru a evita sincronizarea
        jitter = random.uniform(0, 0.01)  # 🔥 Redus de la 20ms la 10ms
        await asyncio.sleep(self.adaptive_delay + jitter)
        
        async with self.semaphore:
            for attempt in range(retries):
                try:
                    response = await self.client.get(url)
                    
                    if response.status_code == 200:
                        # Success - reduce delay
                        self.success_count += 1
                        if self.success_count >= 50 and self.adaptive_delay > 0.01:
                            self.adaptive_delay *= 0.95  # Reduce delay cu 5%
                            self.success_count = 0
                        return response.text
                        
                    elif response.status_code == 404:
                        return None
                        
                    elif response.status_code == 503:
                        # 🔥 ADAPTIVE THROTTLING
                        self.error_503_count += 1
                        self.adaptive_delay = min(1.0, self.adaptive_delay * 1.5)
                        
                        wait_time = min(10, 2 ** attempt)
                        logger.warning(f"503 - backing off {wait_time}s (delay now: {self.adaptive_delay:.2f}s)")
                        await asyncio.sleep(wait_time)
                        
                        # Dacă prea multe 503, reduce drastic viteza
                        if self.error_503_count >= 10:
                            logger.error(f"❌ Prea multe 503! Reducem viteza...")
                            await asyncio.sleep(5)
                            self.error_503_count = 0
                        
                        if attempt < retries - 1:
                            continue
                        raise Exception("503 Service Unavailable")
                        
                    elif response.status_code == 429:
                        wait_time = min(15, 5 * (2 ** attempt))
                        logger.warning(f"429 Rate Limited - waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        if attempt < retries - 1:
                            await asyncio.sleep(1)
                            continue
                        return None
                            
                except httpx.TimeoutException:
                    if attempt < retries - 1:
                        await asyncio.sleep(0.5)
                        continue
                    return None
                except Exception as e:
                    if '503' in str(e):
                        raise
                    if attempt < retries - 1:
                        await asyncio.sleep(0.5)
                        continue
                    return None
        return None
    
    # [Keep all other methods from scraper.py unchanged - get_online_players, get_latest_actions, parse_action_entry, get_player_profile, get_banned_players]
    # Only modify batch_get_profiles:
    
    async def batch_get_profiles(self, player_ids: List[str]) -> List[PlayerProfile]:
        """🔥 OPTIMIZED: Batch fetch cu wave pattern mai rapid"""
        results = []
        
        # 🔥 OPTIMIZED: Wave size crescut de la 10 la 20, delay redus de la 0.2s la 0.05s
        wave_size = 20  # 🔥 Crescut de la 10 la 20
        wave_delay = 0.05  # 🔥 Redus de la 0.2s la 0.05s
        
        for i in range(0, len(player_ids), wave_size):
            wave = player_ids[i:i + wave_size]
            
            # Lansează valul în paralel
            tasks = [self.get_player_profile(pid) for pid in wave]
            wave_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in wave_results:
                if isinstance(result, PlayerProfile):
                    results.append(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error: {result}")
            
            # Delay între valuri
            if i + wave_size < len(player_ids):
                await asyncio.sleep(wave_delay)
        
        return results

    # [Keep get_player_profile, get_online_players, get_latest_actions, get_banned_players, parse_action_entry methods unchanged]

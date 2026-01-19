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
    
    def __init__(self, base_url: str = "https://panel.pro4kings.ro", max_concurrent: int = 50):
        self.base_url = base_url
        self.max_concurrent = max_concurrent  # 🔥 INCREASED: 10 → 50
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.client: Optional[httpx.AsyncClient] = None
        
        # 🔥 OPTIMIZED RATE LIMITER
        self.rate_limiter = TokenBucketRateLimiter(
            rate=60.0,       # 🔥 Crescut de la 25 la 60 request-uri/secundă
            capacity=100      # 🔥 Crescut de la 50 la 100 pentru burst mai mare
        )
        
        # Track 503 errors pentru adaptive throttling
        self.error_503_count = 0
        self.success_count = 0
        self.adaptive_delay = 0.005  # 🔥 Redus de la 20ms 
        
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
    
    async def get_player_profile(self, player_id: str) -> Optional[PlayerProfile]:
        """Get complete player profile"""
        profile_url = f"{self.base_url}/profile/{player_id}"
        html = await self.fetch_page(profile_url)
        
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        
        try:
            username_elem = soup.select_one('.profile-username, .player-name, h1, h2, h3')
            username = username_elem.get_text(strip=True) if username_elem else f"Player_{player_id}"
            
            is_online = bool(soup.select_one('.online-indicator, .status-online, .badge-success, .text-success'))
            
            last_seen = datetime.now()
            last_conn_text = soup.find(text=re.compile(r'Ultima.*conectare|Last.*connection', re.IGNORECASE))
            if last_conn_text:
                parent = last_conn_text.find_parent(['div', 'span', 'td', 'dd'])
                if parent:
                    time_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', parent.get_text())
                    if time_match:
                        try:
                            last_seen = datetime.strptime(time_match.group(1), '%Y-%m-%d %H:%M:%S')
                        except:
                            pass
            
            profile_data = {}
            
            info_rows = soup.select('tr')
            for row in info_rows:
                cells = row.select('td, th')
                if len(cells) == 2:
                    key = cells[0].get_text(strip=True).lower()
                    val = cells[1].get_text(strip=True)
                    if key and val:
                        profile_data[key] = val
            
            faction = None
            faction_rank = None
            job = None
            level = None
            respect_points = None
            warnings = None
            played_hours = None
            age_ic = None
            phone_number = None
            
            for key, val in profile_data.items():
                if any(x in key for x in ['fac', 'factiune', 'faction']):
                    if val and val not in ['Civil', 'Fără', 'None', '-']:
                        faction = val
                        break
            
            for key, val in profile_data.items():
                if any(x in key for x in ['rank facțiune', 'rank factiune', 'faction rank', 'rang', 'rank']):
                    if val and val not in ['-', 'None', 'Fără']:
                        faction_rank = val
                        break
            
            if faction and not faction_rank:
                for key, val in profile_data.items():
                    if 'rank' in key and val and val != '-':
                        faction_rank = val
                        break
            
            for key, val in profile_data.items():
                if any(x in key for x in ['job', 'meserie']):
                    job = val
                    break
            
            for key, val in profile_data.items():
                if any(x in key for x in ['level', 'nivel']):
                    level_match = re.search(r'(\d+)', val)
                    if level_match:
                        level = int(level_match.group(1))
                        break
            
            for key, val in profile_data.items():
                if any(x in key for x in ['respect', 'puncte']):
                    resp_match = re.search(r'(\d+)', val)
                    if resp_match:
                        respect_points = int(resp_match.group(1))
                        break
            
            for key, val in profile_data.items():
                if any(x in key for x in ['warn', 'avertis']):
                    warn_match = re.search(r'(\d+)', val)
                    if warn_match:
                        warnings = int(warn_match.group(1))
                        break
            
            for key, val in profile_data.items():
                if any(x in key for x in ['ore jucate', 'ore', 'hours']):
                    hours_match = re.search(r'([\d\.]+)', val)
                    if hours_match:
                        played_hours = float(hours_match.group(1))
                        break
            
            for key, val in profile_data.items():
                if any(x in key for x in ['varsta', 'age', 'ani']):
                    age_match = re.search(r'(\d+)', val)
                    if age_match:
                        age_ic = int(age_match.group(1))
                        break
            
            for key, val in profile_data.items():
                if any(x in key for x in ['telefon', 'phone', 'numar']):
                    phone_match = re.search(r'(\d+)', val)
                    if phone_match:
                        phone_number = phone_match.group(1)
                        break
            
            return PlayerProfile(
                player_id=player_id,
                username=username,
                is_online=is_online,
                last_seen=last_seen,
                faction=faction,
                faction_rank=faction_rank,
                job=job,
                level=level,
                respect_points=respect_points,
                warnings=warnings,
                played_hours=played_hours,
                age_ic=age_ic,
                phone_number=phone_number,
                vehicles_count=None,
                properties_count=None,
                profile_data=profile_data
            )
            
        except Exception as e:
            logger.error(f"Error parsing profile for player {player_id}: {e}")
            return None
    
    async def batch_get_profiles(self, player_ids: List[str]) -> List[PlayerProfile]:
        """🔥 HIGHLY OPTIMIZED: Parallel fetching with larger waves"""
        results = []
        
        # 🔥 SOLUTION: Increase wave size to match or exceed max_concurrent
        wave_size = 50  # Changed from 20 to 50 
        wave_delay = 0.02  # Changed from 0.05 to 0.02s
        
        for i in range(0, len(player_ids), wave_size):
            wave = player_ids[i:i + wave_size]
            
            tasks = [self.get_player_profile(pid) for pid in wave]
            wave_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in wave_results:
                if isinstance(result, PlayerProfile):
                    results.append(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error: {result}")
            
            if i + wave_size < len(player_ids):
                await asyncio.sleep(wave_delay)
        
        return results

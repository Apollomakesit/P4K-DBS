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
    def __init__(self, rate: float = 30.0, capacity: int = 60):
        """
        🔥 OPTIMIZED: Crescut la 30 req/s, capacity 60
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
    
    def __init__(self, base_url: str = "https://panel.pro4kings.ro", max_concurrent: int = 15):
        self.base_url = base_url
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.client: Optional[httpx.AsyncClient] = None
        
        # 🔥 OPTIMIZED RATE LIMITER
        self.rate_limiter = TokenBucketRateLimiter(
            rate=30.0,       # 🔥 Crescut la 30 request-uri/secundă
            capacity=60      # 🔥 Crescut la 60 pentru burst mai mare
        )
        
        # Track 503 errors pentru adaptive throttling
        self.error_503_count = 0
        self.success_count = 0
        self.adaptive_delay = 0.01  # 🔥 Redus la 10ms
        
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
    
    # ... (keep all other methods unchanged: get_online_players, get_latest_actions, parse_action_entry, get_player_profile, get_banned_players) ...
    
    async def batch_get_profiles(self, player_ids: List[str]) -> List[PlayerProfile]:
        """🔥 HIGHLY OPTIMIZED: Batch fetch cu wave pattern 10x mai rapid"""
        results = []
        
        # 🔥 OPTIMIZED: Wave size crescut de la 10 la 30, delay redus de la 0.2s la 0.05s
        wave_size = 30  # 🔥 CRESCUT: 10 → 30 (3x mai multe IDs per wave)
        wave_delay = 0.05  # 🔥 REDUS: 0.2s → 0.05s (4x mai rapid)
        
        logger.info(f"⚡ Starting batch scan: {len(player_ids)} IDs, {wave_size} IDs/wave, {wave_delay}s delay")
        
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
            
            # Log progress
            if (i // wave_size) % 10 == 0:  # Every 10 waves
                logger.info(f"⚡ Progress: {i + len(wave)}/{len(player_ids)} IDs scanned")
            
            # Delay între valuri (MULT MAI SCURT)
            if i + wave_size < len(player_ids):
                await asyncio.sleep(wave_delay)
        
        logger.info(f"✅ Batch complete: {len(results)}/{len(player_ids)} profiles found")
        return results

    async def get_online_players(self) -> List[Dict]:
        """Get all online players with pagination"""
        all_players = []
        page = 1
        
        while True:
            url = f"{self.base_url}/online?pageOnline={page}" if page > 1 else f"{self.base_url}/online"
            logger.info(f"Fetching online players page {page}...")
            
            html = await self.fetch_page(url)
            if not html:
                break
            
            soup = BeautifulSoup(html, 'html.parser')
            player_rows = soup.select('table tr, .player-row, .online-player')
            
            if not player_rows or len(player_rows) <= 1:
                break
            
            page_players = []
            for row in player_rows[1:]:
                try:
                    link = row.select_one('a[href*="/profile/"]')
                    if link:
                        href = link.get('href', '')
                        id_match = re.search(r'/profile/(\d+)', href)
                        if id_match:
                            player_id = id_match.group(1)
                            player_name = link.get_text(strip=True)
                            page_players.append({
                                'player_id': player_id,
                                'player_name': player_name,
                                'is_online': True,
                                'last_seen': datetime.now()
                            })
                    
                    if not link:
                        cells = row.select('td')
                        if len(cells) >= 2:
                            player_id = cells[0].get_text(strip=True)
                            player_name = cells[1].get_text(strip=True)
                            if player_id.isdigit():
                                page_players.append({
                                    'player_id': player_id,
                                    'player_name': player_name,
                                    'is_online': True,
                                    'last_seen': datetime.now()
                                })
                except Exception as e:
                    logger.error(f"Error parsing player row: {e}")
                    continue
            
            if not page_players:
                break
            
            all_players.extend(page_players)
            logger.info(f"Found {len(page_players)} players on page {page} (total: {len(all_players)})")
            
            next_link = soup.select_one('a[href*="pageOnline=' + str(page + 1) + '"]')
            if not next_link:
                break
            
            page += 1
            await asyncio.sleep(0.5)
        
        logger.info(f"Total online players found: {len(all_players)}")
        return all_players

    async def get_latest_actions(self, limit: int = 200) -> List[PlayerAction]:
        """Get latest actions from homepage"""
        self.action_scraping_stats['total_attempts'] += 1
        
        url = f"{self.base_url}/"
        html = await self.fetch_page(url)
        
        if not html:
            logger.error("❌ Failed to fetch homepage!")
            self.action_scraping_stats['failed_parses'] += 1
            return []
        
        soup = BeautifulSoup(html, 'lxml')
        actions = []
        
        # Find action list
        all_lists = soup.find_all(['ul', 'ol', 'div'])
        candidate_lists = []
        
        for lst in all_lists:
            items = lst.find_all(['li', 'div'], recursive=False)
            if len(items) >= 5:
                candidate_lists.append((lst, items))
        
        # Score lists
        best_list = None
        best_score = 0
        
        for lst, items in candidate_lists:
            score = 0
            for item in items[:10]:
                text = item.get_text()
                if any(verb in text for verb in ['a primit', 'a dat', 'a pus', 'a retras', 'a scos']):
                    score += 10
                if 'Jucatorul' in text or 'jucatorul' in text:
                    score += 5
                if re.search(r'\(\d+\)', text):
                    score += 3
                if any(kw in text for kw in ['Conectați', 'Banați', 'JUCATE', 'Server']):
                    score -= 50
            
            if score > best_score:
                best_score = score
                best_list = (lst, items)
        
        if best_list and best_score > 0:
            lst, items = best_list
            for entry in items[:limit * 2]:
                text = entry.get_text(strip=True)
                if len(text) < 40 or 'Jucatorul' not in text:
                    continue
                action = self.parse_action_entry(entry)
                if action:
                    actions.append(action)
                    if len(actions) >= limit:
                        break
        
        if actions:
            self.action_scraping_stats['successful_parses'] += 1
            self.action_scraping_stats['total_actions_found'] += len(actions)
        else:
            self.action_scraping_stats['failed_parses'] += 1
        
        return actions

    def parse_action_entry(self, entry) -> Optional[PlayerAction]:
        """Parse action entry"""
        try:
            text = entry.get_text(strip=True)
            if not text or len(text) < 15:
                return None
            
            text = ' '.join(text.split())
            timestamp = datetime.now()
            
            # Try various patterns
            warning_match = re.search(
                r'Jucatorul\s+([^\(]+)\s*\((\d+)\)\s+a\s+primit\s+un\s+avertisment',
                text, re.IGNORECASE
            )
            if warning_match:
                return PlayerAction(
                    player_id=warning_match.group(2),
                    player_name=warning_match.group(1).strip(),
                    action_type='warning_received',
                    action_detail='Avertisment primit',
                    timestamp=timestamp,
                    raw_text=text
                )
            
            generic_match = re.search(
                r'Jucatorul\s+([^\(]+)\s*\((\d+)\)\s+(.+?)(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)',
                text, re.IGNORECASE
            )
            if generic_match:
                return PlayerAction(
                    player_id=generic_match.group(2),
                    player_name=generic_match.group(1).strip(),
                    action_type='other',
                    action_detail=generic_match.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )
            
            return None
        except Exception as e:
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
            for key, val in profile_data.items():
                if any(x in key for x in ['fac', 'factiune', 'faction']):
                    if val and val not in ['Civil', 'Fără', 'None', '-']:
                        faction = val
                        break
            
            return PlayerProfile(
                player_id=player_id,
                username=username,
                is_online=is_online,
                last_seen=last_seen,
                faction=faction,
                faction_rank=None,
                job=None,
                level=None,
                respect_points=None,
                warnings=None,
                played_hours=None,
                age_ic=None,
                phone_number=None,
                vehicles_count=None,
                properties_count=None,
                profile_data=profile_data
            )
        except Exception as e:
            logger.error(f"Error parsing profile for player {player_id}: {e}")
            return None

    async def get_banned_players(self) -> List[Dict]:
        """Get banned players from banlist"""
        url = f"{self.base_url}/banlist"
        html = await self.fetch_page(url)
        
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        banned = []
        
        ban_rows = soup.select('table tr, .ban-row, .banned-player')
        
        for row in ban_rows[1:]:
            try:
                cells = row.select('td')
                if len(cells) >= 6:
                    player_link = cells[1].select_one('a[href*="/profile/"]')
                    player_id = None
                    if player_link:
                        id_match = re.search(r'/profile/(\d+)', player_link.get('href', ''))
                        if id_match:
                            player_id = id_match.group(1)
                    
                    banned.append({
                        'player_id': player_id or cells[0].get_text(strip=True),
                        'player_name': cells[1].get_text(strip=True),
                        'admin': cells[2].get_text(strip=True),
                        'reason': cells[3].get_text(strip=True),
                        'duration': cells[4].get_text(strip=True),
                        'ban_date': cells[5].get_text(strip=True),
                        'expiry_date': cells[6].get_text(strip=True) if len(cells) > 6 else None
                    })
            except Exception as e:
                logger.error(f"Error parsing ban row: {e}")
                continue
        
        return banned

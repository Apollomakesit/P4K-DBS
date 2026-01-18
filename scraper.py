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
    def __init__(self, rate: float = 25.0, capacity: int = 50):
        """
        🔥 OPTIMIZED: Crescut la 25 req/s, capacity 50
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
    
    def __init__(self, base_url: str = "https://panel.pro4kings.ro", max_concurrent: int = 10):
        self.base_url = base_url
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.client: Optional[httpx.AsyncClient] = None
        
        # 🔥 OPTIMIZED RATE LIMITER
        self.rate_limiter = TokenBucketRateLimiter(
            rate=25.0,       # 🔥 Crescut la 25 request-uri/secundă
            capacity=50      # 🔥 Crescut la 50 pentru burst mai mare
        )
        
        # Track 503 errors pentru adaptive throttling
        self.error_503_count = 0
        self.success_count = 0
        self.adaptive_delay = 0.02  # 🔥 Redus la 20ms
        
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
        jitter = random.uniform(0, 0.02)  # 🔥 Redus de la 50ms la 20ms
        await asyncio.sleep(self.adaptive_delay + jitter)
        
        async with self.semaphore:
            for attempt in range(retries):
                try:
                    response = await self.client.get(url)
                    
                    if response.status_code == 200:
                        # Success - reduce delay
                        self.success_count += 1
                        if self.success_count >= 50 and self.adaptive_delay > 0.02:
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
        """🔥 COMPLETELY REWRITTEN: Direct, simple, effective action scraping"""
        url = f"{self.base_url}/"
        html = await self.fetch_page(url)
        
        if not html:
            logger.error("❌ Failed to fetch homepage!")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        actions = []
        
        logger.info("🔍 Searching for action entries...")
        
        # 🔥 STRATEGY 1: Find ALL list items on the page
        all_list_items = soup.find_all('li')
        logger.info(f"📋 Found {len(all_list_items)} total <li> elements")
        
        action_candidates = []
        
        for li in all_list_items:
            text = li.get_text(strip=True)
            
            # Filter: Must contain "Jucatorul" or "jucatorul"
            if 'ucatorul' not in text.lower():
                continue
            
            # Filter: Must be long enough (real actions are detailed)
            if len(text) < 40:
                continue
            
            # Filter: Must contain action verbs
            if not any(verb in text for verb in ['a primit', 'a dat', 'a pus', 'a scos', 'a retras', 'a cumparat', 'a vandut']):
                continue
            
            # Filter: Must NOT be homepage stats
            if any(stat in text for stat in ['Server', 'Conectați', 'Banați', 'JUCATE']):
                continue
            
            action_candidates.append(li)
        
        logger.info(f"✅ Found {len(action_candidates)} potential action entries")
        
        # Parse each candidate
        for li in action_candidates[:limit]:
            action = self.parse_action_entry(li)
            if action:
                actions.append(action)
                logger.debug(f"✓ Parsed: {action.action_type} - {action.player_name}")
        
        # 🔥 STRATEGY 2: If no actions found, try alternative selectors
        if len(actions) == 0:
            logger.warning("⚠️ No actions found with primary strategy, trying alternatives...")
            
            # Try divs with class containing "action" or "activity"
            action_divs = soup.find_all('div', class_=re.compile(r'action|activity', re.IGNORECASE))
            logger.info(f"Found {len(action_divs)} divs with action/activity classes")
            
            for div in action_divs[:50]:
                text = div.get_text(strip=True)
                if 'ucatorul' in text.lower() and len(text) > 40:
                    action = self.parse_action_entry(div)
                    if action:
                        actions.append(action)
        
        if len(actions) == 0:
            logger.error(f"❌ NO ACTIONS FOUND! This is a critical issue.")
            logger.error(f"📄 Page has {len(soup.find_all())} total HTML elements")
            logger.error(f"📋 Examined {len(action_candidates)} candidate elements")
            
            # Debug: Show a sample of page content
            sample_text = soup.get_text()[:500]
            logger.error(f"📝 Page sample: {sample_text}...")
        else:
            logger.info(f"✅ Successfully extracted {len(actions)} actions from homepage")
        
        return actions
    
    def parse_action_entry(self, entry) -> Optional[PlayerAction]:
        """Enhanced action parser with MORE patterns"""
        try:
            text = entry.get_text(strip=True)
            if not text or len(text) < 15:
                return None
            
            text = ' '.join(text.split())
            
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', text)
            timestamp = datetime.now()
            if timestamp_match:
                try:
                    timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
                except:
                    pass
            
            # Pattern 1: Warning received
            warning_match = re.search(
                r'Jucatorul\s+([^\(]+)\s*\((\d+)\)\s+a\s+primit\s+un\s+avertisment\s+\((\d+/\d+)\)[,\s]+de\s+la\s+administratorul\s+\[([^\]]+)\]\s+([^\(]+)\s*\((\d+)\)[,\s]+motiv[:\s]+(.+?)(?=\d{4}-\d{2}-\d{2}|$)',
                text,
                re.IGNORECASE
            )
            if warning_match:
                return PlayerAction(
                    player_id=warning_match.group(2),
                    player_name=warning_match.group(1).strip(),
                    action_type='warning_received',
                    action_detail=f"Avertisment {warning_match.group(3)} de la {warning_match.group(5).strip()}",
                    admin_id=warning_match.group(6),
                    admin_name=warning_match.group(5).strip(),
                    warning_count=warning_match.group(3),
                    reason=warning_match.group(7).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # Pattern 2: Chest deposit/withdraw
            chest_match = re.search(
                r'Jucatorul\s+([^\(]+)\s*\((\d+)\)\s+a\s+(pus\s+in|scos\s+din)\s+chest.*?(\d+)x\s+([^\d]+?)(?=\d{4}-\d{2}-\d{2}|$)',
                text,
                re.IGNORECASE
            )
            if chest_match:
                action_type = 'chest_deposit' if 'pus' in chest_match.group(3).lower() else 'chest_withdraw'
                return PlayerAction(
                    player_id=chest_match.group(2),
                    player_name=chest_match.group(1).strip(),
                    action_type=action_type,
                    action_detail=f"{chest_match.group(3)} chest",
                    item_name=chest_match.group(5).strip(),
                    item_quantity=int(chest_match.group(4)),
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # Pattern 3: Item given
            gave_match = re.search(
                r'Jucatorul\s+([^\(]+)\s*\((\d+)\)\s+a\s+dat\s+lui\s+([^\(]+)\s*\((\d+)\)\s+(\d+)x\s+([^\d]+?)(?=\d{4}-\d{2}-\d{2}|$)',
                text,
                re.IGNORECASE
            )
            if gave_match:
                return PlayerAction(
                    player_id=gave_match.group(2),
                    player_name=gave_match.group(1).strip(),
                    action_type='item_given',
                    action_detail=f"Dat {gave_match.group(6).strip()} către {gave_match.group(3).strip()}",
                    item_name=gave_match.group(6).strip(),
                    item_quantity=int(gave_match.group(5)),
                    target_player_id=gave_match.group(4),
                    target_player_name=gave_match.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # Pattern 4: Item received
            received_match = re.search(
                r'Jucatorul\s+([^\(]+)\s*\((\d+)\)\s+a\s+primit\s+de\s+la\s+([^\(]+)\s*\((\d+)\)\s+(\d+)x\s+([^\d]+?)(?=\d{4}-\d{2}-\d{2}|$)',
                text,
                re.IGNORECASE
            )
            if received_match:
                return PlayerAction(
                    player_id=received_match.group(2),
                    player_name=received_match.group(1).strip(),
                    action_type='item_received',
                    action_detail=f"Primit {received_match.group(6).strip()} de la {received_match.group(3).strip()}",
                    item_name=received_match.group(6).strip(),
                    item_quantity=int(received_match.group(5)),
                    target_player_id=received_match.group(4),
                    target_player_name=received_match.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # Pattern 5: Money withdrawal
            withdraw_match = re.search(
                r'Jucatorul\s+([^\(]+)\s*\((\d+)\)\s+a\s+retras\s+suma\s+de\s+([\d\.,]+)\$',
                text,
                re.IGNORECASE
            )
            if withdraw_match:
                return PlayerAction(
                    player_id=withdraw_match.group(2),
                    player_name=withdraw_match.group(1).strip(),
                    action_type='money_withdraw',
                    action_detail=f"Retragere {withdraw_match.group(3)}$",
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # Pattern 6: Vehicle purchase/sale
            vehicle_match = re.search(
                r'Jucatorul\s+([^\(]+)\s*\((\d+)\)\s+a\s+(cumparat|vandut)\s+(.+?)(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)',
                text,
                re.IGNORECASE
            )
            if vehicle_match:
                action_type = 'vehicle_bought' if 'cumparat' in vehicle_match.group(3).lower() else 'vehicle_sold'
                return PlayerAction(
                    player_id=vehicle_match.group(2),
                    player_name=vehicle_match.group(1).strip(),
                    action_type=action_type,
                    action_detail=vehicle_match.group(4).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # Pattern 7: Property purchase/sale  
            property_match = re.search(
                r'Jucatorul\s+([^\(]+)\s*\((\d+)\)\s+a\s+(cumparat|vandut)\s+(casa|afacere|proprietate).*?(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)',
                text,
                re.IGNORECASE
            )
            if property_match:
                action_type = 'property_bought' if 'cumparat' in property_match.group(3).lower() else 'property_sold'
                return PlayerAction(
                    player_id=property_match.group(2),
                    player_name=property_match.group(1).strip(),
                    action_type=action_type,
                    action_detail=f"{property_match.group(3)} {property_match.group(4)}",
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # Pattern 8: Generic player action
            generic_match = re.search(
                r'Jucatorul\s+([^\(]+)\s*\((\d+)\)\s+(.+?)(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)',
                text,
                re.IGNORECASE
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
            logger.error(f"Error parsing action: {e} | Text: {text[:100] if 'text' in locals() else 'N/A'}")
            return None
    
    async def get_player_profile(self, player_id: str) -> Optional[PlayerProfile]:
        """Get complete player profile with FIXED last_seen parsing"""
        profile_url = f"{self.base_url}/profile/{player_id}"
        html = await self.fetch_page(profile_url)
        
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        
        try:
            username_elem = soup.select_one('.profile-username, .player-name, h1, h2, h3')
            username = username_elem.get_text(strip=True) if username_elem else f"Player_{player_id}"
            
            is_online = bool(soup.select_one('.online-indicator, .status-online, .badge-success, .text-success'))
            
            # 🔧 FIX: Parse actual "Ultima conectare" field BEFORE defaulting to now()
            last_seen = None
            
            # Method 1: Search for "Ultima conectare" label
            last_conn_patterns = [
                r'Ultima.*conectare[:\s]*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})',
                r'Ultima.*conectare[:\s]*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
                r'Last.*connection[:\s]*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})',
                r'Last.*connection[:\s]*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'
            ]
            
            page_text = soup.get_text()
            for pattern in last_conn_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    time_str = match.group(1)
                    try:
                        # Try DD/MM/YYYY format
                        if '/' in time_str:
                            last_seen = datetime.strptime(time_str, '%d/%m/%Y %H:%M:%S')
                        # Try YYYY-MM-DD format
                        else:
                            last_seen = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                        break
                    except Exception as e:
                        continue
            
            # Method 2: Search in table rows
            if not last_seen:
                info_rows = soup.select('tr')
                for row in info_rows:
                    cells = row.select('td, th')
                    if len(cells) == 2:
                        key = cells[0].get_text(strip=True).lower()
                        if any(x in key for x in ['ultima', 'last', 'conectare', 'connection']):
                            val = cells[1].get_text(strip=True)
                            time_match = re.search(r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}|\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', val)
                            if time_match:
                                try:
                                    time_str = time_match.group(1)
                                    if '/' in time_str:
                                        last_seen = datetime.strptime(time_str, '%d/%m/%Y %H:%M:%S')
                                    else:
                                        last_seen = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                                    break
                                except:
                                    continue
            
            # Default to now ONLY if parsing completely failed
            if not last_seen:
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
            
            dt_elements = soup.select('dt')
            for dt in dt_elements:
                dd = dt.find_next_sibling('dd')
                if dd:
                    key = dt.get_text(strip=True).lower()
                    val = dd.get_text(strip=True)
                    profile_data[key] = val
            
            labels = soup.select('.label, .key, .field-label, strong')
            for label in labels:
                key_text = label.get_text(strip=True).lower().rstrip(':')
                value_elem = label.find_next_sibling(['span', 'div', 'p'])
                if not value_elem:
                    parent = label.find_parent(['div', 'li', 'tr'])
                    if parent:
                        value_elem = parent.find(['span', 'div', 'p'], recursive=False)
                
                if value_elem:
                    val = value_elem.get_text(strip=True)
                    if val and val != key_text:
                        profile_data[key_text] = val
            
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
                if any(x in key for x in ['job', 'meserie', 'ocupatie', 'occupation']):
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
                if any(x in key for x in ['ore jucate', 'ore', 'hours', 'timp']):
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
            
            vehicles_count = None
            properties_count = None
            
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
                vehicles_count=vehicles_count,
                properties_count=properties_count,
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
    
    async def batch_get_profiles(self, player_ids: List[str]) -> List[PlayerProfile]:
        """🔥 OPTIMIZED: Batch fetch cu wave pattern mai rapid"""
        results = []
        
        # 🔥 OPTIMIZED: Wave size crescut de la 5 la 10, delay redus de la 0.5s la 0.2s
        wave_size = 10  # 🔥 Crescut de la 5 la 10
        wave_delay = 0.2  # 🔥 Redus de la 0.5 la 0.2
        
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

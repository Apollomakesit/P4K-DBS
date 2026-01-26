#!/usr/bin/env python3
"""
Pro4Kings Scraper - ULTRA SAFE Version with TokenBucket Rate Limiter
Minimum 1 worker support for maximum 503 error protection
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Tuple
import logging
import time
import random
from dataclasses import dataclass, field
import re

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
    """Complete player profile - CLEANED UP (removed 5 deprecated fields)"""
    player_id: str
    username: str
    is_online: bool
    last_seen: datetime
    faction: Optional[str] = None
    faction_rank: Optional[str] = None
    job: Optional[str] = None
    warnings: Optional[int] = None
    played_hours: Optional[float] = None
    age_ic: Optional[int] = None
    profile_data: Dict = field(default_factory=dict)


class TokenBucketRateLimiter:
    """Rate limiter that allows controlled bursts"""

    def __init__(self, rate: float = 10.0, capacity: int = 20):
        """
        rate: requests per second allowed
        capacity: maximum burst size
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.time()
        self.lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a token becomes available"""
        async with self.lock:
            now = time.time()

            # Add new tokens based on elapsed time
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now

            # Wait if no tokens available
            if self.tokens < 1.0:
                wait_time = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
            else:
                self.tokens -= 1.0


class Pro4KingsScraper:
    """Ultra-safe scraper with TokenBucket rate limiting - supports 1-50 workers"""

    def __init__(
        self,
        base_url: str = "https://panel.pro4kings.ro",
        max_concurrent: int = 10  # Default: 10 workers
    ):
        self.base_url = base_url
        self.max_concurrent = max(1, max_concurrent)  # ✅ Minimum 1 worker for ultra-safe scanning
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        self.client: Optional[aiohttp.ClientSession] = None

        # TokenBucket: Smooth request distribution
        self.rate_limiter = TokenBucketRateLimiter(
            rate=max(10.0, self.max_concurrent * 1.5),  # Scale with workers
            capacity=max(20, self.max_concurrent * 3)   # Allow some bursting
        )

        self.error_503_count = 0
        self.success_count = 0
        self.adaptive_delay = 0.0  # Start with no delay, adapts if 503s occur

        self.action_scraping_stats = {
            'total_attempts': 0,
            'successful_parses': 0,
            'failed_parses': 0,
            'total_actions_found': 0
        }

        self.last_request_time = {}
        self.request_times = []
        self.consecutive_503 = 0

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ro-RO,ro;q=0.9,en;q=0.8',
        }

    async def __aenter__(self):
        """Async context manager entry"""
        timeout = aiohttp.ClientTimeout(total=15, connect=5)
        connector = aiohttp.TCPConnector(
            limit=max(10, self.max_concurrent * 2),
            limit_per_host=max(10, self.max_concurrent * 2),
            ttl_dns_cache=300,
            force_close=False,
            enable_cleanup_closed=True
        )

        self.client = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=self.headers
        )

        logger.info(f"✓ HTTP client initialized ({self.max_concurrent} workers, {self.rate_limiter.rate:.1f} req/s)")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.client:
            await self.client.close()
            await asyncio.sleep(0.1)

    async def fetch_page(self, url: str, retries: int = 3) -> Optional[str]:
        """Fetch page with TokenBucket rate limiting and adaptive throttling"""
        async with self.semaphore:
            # ✅ Apply TokenBucket rate limiting
            await self.rate_limiter.acquire()

            # ✅ Add jitter to avoid request synchronization (0-10ms)
            jitter = random.uniform(0, 0.01)
            await asyncio.sleep(jitter)

            # ✅ Apply adaptive delay only if it's set (increases with 503 errors)
            if self.adaptive_delay > 0:
                await asyncio.sleep(self.adaptive_delay)

            for attempt in range(retries):
                start_time = time.time()
                try:
                    async with self.client.get(url, ssl=False) as response:
                        elapsed = time.time() - start_time
                        self.request_times.append(elapsed)
                        if len(self.request_times) > 100:
                            self.request_times.pop(0)

                        if response.status == 200:
                            self.consecutive_503 = 0
                            self.success_count += 1

                            # Reduce delay if many successes
                            if self.success_count >= 50 and self.adaptive_delay > 0.01:
                                self.adaptive_delay = max(0, self.adaptive_delay * 0.9)
                                self.success_count = 0

                            return await response.text()

                        elif response.status == 404:
                            return None

                        elif response.status == 503:
                            self.error_503_count += 1
                            self.consecutive_503 += 1

                            if self.consecutive_503 >= 3:
                                self.adaptive_delay = min(2.0, self.adaptive_delay + 0.3)
                                logger.warning(f"Multiple 503s - delay now: {self.adaptive_delay:.2f}s")
                            else:
                                self.adaptive_delay = min(1.0, self.adaptive_delay + 0.1)

                            wait_time = min(10, 2 ** attempt)

                            if self.error_503_count >= 10:
                                logger.error("Too many 503s! Backing off...")
                                await asyncio.sleep(5)
                                self.error_503_count = 0

                            if attempt < retries - 1:
                                await asyncio.sleep(wait_time)
                                continue
                            raise Exception("503 Service Unavailable")

                        elif response.status == 429:
                            wait_time = min(15, 5 * (2 ** attempt))
                            logger.warning(f"429 Rate Limited - waiting {wait_time}s")
                            self.adaptive_delay = min(2.0, self.adaptive_delay + 0.5)
                            await asyncio.sleep(wait_time)
                            continue

                        else:
                            if attempt < retries - 1:
                                await asyncio.sleep(1)
                                continue
                            return None

                except asyncio.TimeoutError:
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
        """🔥 ENHANCED: Get player profile with improved username and age_ic extraction for VIP players"""
        profile_url = f"{self.base_url}/profile/{player_id}"
        html = await self.fetch_page(profile_url)

        if not html:
            return None

        soup = BeautifulSoup(html, 'lxml')

        try:
            # 🔥 ENHANCED USERNAME EXTRACTION - Try multiple selectors including VIP-specific ones
            username = None
            username_selectors = [
                '.profile-username',
                '.player-name',
                '.player-name-display',  # 🆕 Added for VIP players
                '.username',              # 🆕 Added for VIP players
                '.name-field',            # 🆕 Added for VIP players
                'h1',
                'h2',
                'h3'
                '.profile-header h1',
                '.profile-header h2',
                '.card-title',
                '.player-info .name',
                '[data-username]',  # Sometimes stored as data attribute
            ]
            
            for selector in username_selectors:
                username_elem = soup.select_one(selector)
                if username_elem:
                    text = username_elem.get_text(strip=True)
                    # Skip if it's just the ID or a title/label
                    if text and text != player_id and not text.lower().startswith('profil') and len(text) > 1:
                        username = text
                        logger.debug(f"Found username '{username}' with selector '{selector}' for player {player_id}")
                        break
            
            # 🆕 FALLBACK: If no username found, try finding any bold/strong text that's not a label
            if not username:
                bold_elements = soup.select('strong, b')
                for elem in bold_elements:
                    text = elem.get_text(strip=True)
                    # Look for name-like text (alphabetic, not too short, not a common label)
                    if text and len(text) >= 3 and any(c.isalpha() for c in text):
                        if not any(keyword in text.lower() for keyword in ['id', 'profil', 'player', 'nume', 'name', 'ultima', 'status']):
                            username = text
                            logger.debug(f"Found username '{username}' from bold text for player {player_id}")
                            break
            
            # Final fallback
            if not username:
                username = f"Player_{player_id}"
                logger.warning(f"⚠️ Could not extract username for player {player_id}, using placeholder")

            is_online = bool(soup.select_one('.online-indicator, .status-online, .badge-success, .text-success'))
            last_seen = datetime.now()

            last_conn_text = soup.find(text=re.compile(r'Ultima.*conectare|Last.*connection', re.IGNORECASE))
            if last_conn_text:
                parent = last_conn_text.find_parent(['div', 'span', 'td', 'dd'])
                if parent:
                    time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', parent.get_text())
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

            dt_elements = soup.select('dt')
            for dt in dt_elements:
                dd = dt.find_next_sibling('dd')
                if dd:
                    key = dt.get_text(strip=True).lower()
                    val = dd.get_text(strip=True)
                    profile_data[key] = val

            labels = soup.select('.label, .key, .field-label, strong')
            for label in labels:
                keytext = label.get_text(strip=True).lower().rstrip(':')
                value_elem = label.find_next_sibling(['span', 'div', 'p'])
                if not value_elem:
                    parent = label.find_parent(['div', 'li', 'tr'])
                    if parent:
                        value_elem = parent.find(['span', 'div', 'p'], recursive=False)
                if value_elem:
                    val = value_elem.get_text(strip=True)
                    if val and val != '—':
                        profile_data[keytext] = val

            # Extract fields that still exist in database
            faction = None
            faction_rank = None
            job = None
            warnings = None
            played_hours = None
            age_ic = None

            for key, val in profile_data.items():
                if any(x in key for x in ['fac', 'facțiune', 'faction']):
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
                if any(x in key for x in ['job', 'meserie', 'ocupație', 'occupation']):
                    job = val
                    break

            for key, val in profile_data.items():
                if any(x in key for x in ['warn', 'avertis']):
                    warn_match = re.search(r'(\d+)', val)
                    if warn_match:
                        warnings = int(warn_match.group(1))
                    break

            for key, val in profile_data.items():
                if any(x in key for x in ['ore jucate', 'ore', 'hours', 'timp']):
                    hours_match = re.search(r'([\d.]+)', val)
                    if hours_match:
                        played_hours = float(hours_match.group(1))
                    break

            # 🔥 ENHANCED AGE_IC EXTRACTION
            for key, val in profile_data.items():
                if any(x in key for x in ['varsta', 'vârstă', 'age', 'ani']):
                    age_match = re.search(r'(\d+)', val)
                    if age_match:
                        age_ic = int(age_match.group(1))
                        logger.debug(f"Found age_ic {age_ic} from key '{key}' for player {player_id}")
                        break
            
            # 🆕 FALLBACK: Search entire page text for age patterns if not found in profile_data
            if not age_ic:
                page_text = soup.get_text()
                # Look for patterns like "Varsta: 25" or "Age IC: 30" or "25 ani"
                age_patterns = [
                    r'Vârstă[:\s]+(\d+)',
                    r'Varsta[:\s]+(\d+)',
                    r'Age[:\s]+\(?IC\)?[:\s]+(\d+)',
                    r'Age[:\s]+(\d+)',
                    r'(\d+)\s+ani',
                ]
                
                for pattern in age_patterns:
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        potential_age = int(match.group(1))
                        # Sanity check - age should be reasonable (18-99 for IC age)
                        if 18 <= potential_age <= 99:
                            age_ic = potential_age
                            logger.debug(f"Found age_ic {age_ic} using fallback pattern '{pattern}' for player {player_id}")
                            break
            
            if not age_ic:
                logger.warning(f"⚠️ Could not extract age_ic for player {player_id}")

            return PlayerProfile(
                player_id=player_id,
                username=username,
                is_online=is_online,
                last_seen=last_seen,
                faction=faction,
                faction_rank=faction_rank,
                job=job,
                warnings=warnings,
                played_hours=played_hours,
                age_ic=age_ic,
                profile_data=profile_data
            )

        except Exception as e:
            logger.error(f"Error parsing profile for player {player_id}: {e}")
            return None

    async def batch_get_profiles(self, player_ids: List[str]) -> List[PlayerProfile]:
        """Batch fetch profiles with configurable wave size"""
        results = []
        # Scale wave size with worker count (minimum 10, maximum 50)
        wave_size = min(50, max(10, self.max_concurrent * 5))
        wave_delay = 0.05  # 50ms between waves

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

    async def get_factions_info(self) -> List[Dict]:
        """🆕 Get faction information from /factions page"""
        url = f"{self.base_url}/factions"
        logger.info(f"Fetching faction data from {url}...")
        
        html = await self.fetch_page(url)
        if not html:
            logger.error("Failed to fetch factions page!")
            return []
        
        soup = BeautifulSoup(html, 'lxml')
        factions = []
        
        # Try multiple selectors to find faction data
        # Common patterns: table rows, cards, divs with faction info
        
        # Try table format first
        faction_rows = soup.select('table tr')
        if len(faction_rows) > 1:  # Has header + data
            logger.info(f"Found {len(faction_rows)-1} faction rows in table")
            
            for row in faction_rows[1:]:  # Skip header
                try:
                    cells = row.select('td')
                    if len(cells) >= 2:
                        # Extract faction name and member count
                        faction_name = cells[0].get_text(strip=True)
                        
                        # Look for member count (usually numeric)
                        member_count = 0
                        for cell in cells[1:]:
                            text = cell.get_text(strip=True)
                            count_match = re.search(r'(\d+)', text)
                            if count_match:
                                member_count = int(count_match.group(1))
                                break
                        
                        if faction_name and faction_name not in ['Civil', '-', 'Fără']:
                            factions.append({
                                'faction_name': faction_name,
                                'member_count': member_count,
                                'scraped_at': datetime.now()
                            })
                            
                except Exception as e:
                    logger.error(f"Error parsing faction row: {e}")
                    continue
        
        # Try card/div format if table didn't work
        if not factions:
            faction_cards = soup.select('.faction, .faction-card, .faction-info')
            logger.info(f"Found {len(faction_cards)} faction cards")
            
            for card in faction_cards:
                try:
                    faction_name = None
                    member_count = 0
                    
                    # Look for faction name
                    name_elem = card.select_one('h2, h3, h4, .faction-name, .name')
                    if name_elem:
                        faction_name = name_elem.get_text(strip=True)
                    
                    # Look for member count
                    count_text = card.get_text()
                    count_matches = re.findall(r'(\d+)\s*(?:membr|member|players|jucători)', count_text, re.IGNORECASE)
                    if count_matches:
                        member_count = int(count_matches[0])
                    
                    if faction_name and faction_name not in ['Civil', '-', 'Fără']:
                        factions.append({
                            'faction_name': faction_name,
                            'member_count': member_count,
                            'scraped_at': datetime.now()
                        })
                        
                except Exception as e:
                    logger.error(f"Error parsing faction card: {e}")
                    continue
        
        logger.info(f"✅ Scraped {len(factions)} factions")
        return factions
    
    async def get_latest_actions(self, limit: int = 200) -> List[PlayerAction]:
        """Get latest actions - enhanced with multiple detection methods"""
        url = f"{self.base_url}/"
        html = await self.fetch_page(url)

        if not html:
            logger.error("Failed to fetch homepage for actions!")
            return []

        soup = BeautifulSoup(html, 'lxml')
        actions = []

        activity_keywords = ['Activitate', 'Ultimele', 'acțiuni', 'actiuni', 'Recent']
        possible_sections = []

        for keyword in activity_keywords:
            headings = soup.find_all(text=re.compile(keyword, re.IGNORECASE))
            for heading in headings:
                parent = heading.find_parent(['div', 'section', 'article', 'main'])
                if parent:
                    possible_sections.append(parent)

        all_lists = soup.find_all(['ul', 'ol', 'div'], class_=re.compile(r'activity|actions|feed|timeline', re.IGNORECASE))
        possible_sections.extend(all_lists)

        direct_selectors = [
            '#activity', '#actions', '#latest-actions', '#recent-activity',
            '.activity', '.actions', '.recent-actions', '.latest-actions',
            '.activity-feed', '.action-log', '.player-actions'
        ]
        for selector in direct_selectors:
            elem = soup.select_one(selector)
            if elem:
                possible_sections.append(elem)

        all_text_containers = soup.find_all(['ul', 'ol', 'div', 'table'])
        for container in all_text_containers:
            text = container.get_text()
            if text.count('Jucatorul') >= 3 or text.count('jucatorul') >= 3:
                possible_sections.append(container)

        for section in possible_sections:
            if not section:
                continue

            entries = section.find_all(['li', 'tr', 'div'], recursive=True)
            for entry in entries:
                text = entry.get_text(strip=True)
                if len(text) < 20:
                    continue
                if 'Jucatorul' not in text and 'jucatorul' not in text:
                    continue

                action = self.parse_action_entry(entry)
                if action:
                    actions.append(action)
                    if len(actions) >= limit:
                        break

            if len(actions) > 0:
                logger.info(f"Found actions in section: {section.name} (class: {section.get('class')})")
                break

        if len(actions) == 0:
            logger.error("NO ACTIONS FOUND! Debugging HTML structure:")
            logger.error(f"Total 'Jucatorul' mentions: {soup.get_text().count('Jucatorul')}")
            logger.error(f"Possible sections found: {len(possible_sections)}")

            all_text = soup.get_text()
            lines = all_text.split('\n')
            for line in lines:
                if 'Jucatorul' in line and len(line) > 20:
                    fake_elem = BeautifulSoup(f'<div>{line}</div>', 'lxml').div
                    action = self.parse_action_entry(fake_elem)
                    if action:
                        actions.append(action)

        self.action_scraping_stats['total_attempts'] += 1
        self.action_scraping_stats['total_actions_found'] += len(actions)

        logger.info(f"Parsed {len(actions)} actions from homepage")
        return actions[:limit]

    def parse_action_entry(self, entry) -> Optional[PlayerAction]:
        """🔥 FIXED: Enhanced action parser with correct patterns for 'ia dat lui' and chest actions"""
        try:
            text = entry.get_text(strip=True)
            if not text or len(text) < 15:
                return None

            text = ' '.join(text.split())

            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', text)
            timestamp = datetime.now()
            if timestamp_match:
                try:
                    timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
                except:
                    pass

            # Warning pattern
            warning_match = re.search(
                r'Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+primit\s+un\s+avertisment,\s+de\s+la\s+administratorul\s+([^(]+)\((\d+)\)\s*,\s*motiv:\s*(.+?)(?=\d{4}-\d{2}-\d{2}|$)',
                text,
                re.IGNORECASE
            )
            if warning_match:
                return PlayerAction(
                    player_id=warning_match.group(2),
                    player_name=warning_match.group(1).strip(),
                    action_type="warning_received",
                    action_detail=f"Avertisment de la {warning_match.group(3).strip()}",
                    admin_id=warning_match.group(4),
                    admin_name=warning_match.group(3).strip(),
                    warning_count=None,
                    reason=warning_match.group(5).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )

            # 🔥 FIXED: Chest withdraw pattern - matches "a retras din chest"
            chest_withdraw_match = re.search(
                r'Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+retras\s+din\s+chest\s*\(id\s+([^)]+)\)\s*,\s*(\d+)x\s+(.+?)(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)',
                text,
                re.IGNORECASE
            )
            if chest_withdraw_match:
                chest_id = chest_withdraw_match.group(3)
                quantity = chest_withdraw_match.group(4)
                item_name = chest_withdraw_match.group(5).strip().rstrip('.')
                
                return PlayerAction(
                    player_id=chest_withdraw_match.group(2),
                    player_name=chest_withdraw_match.group(1).strip(),
                    action_type="chest_withdraw",
                    action_detail=f"a retras din chest(id {chest_id}), {quantity}x {item_name}.",
                    item_name=item_name,
                    item_quantity=int(quantity),
                    timestamp=timestamp,
                    raw_text=text
                )

            # 🔥 FIXED: Chest deposit pattern - matches "pus in chest"
            chest_deposit_match = re.search(
                r'Jucatorul\s+([^(]+)\((\d+)\)\s+a?\s*pus\s+in\s+chest\s*\(id\s+([^)]+)\)\s*,\s*(\d+)x\s+(.+?)(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)',
                text,
                re.IGNORECASE
            )
            if chest_deposit_match:
                chest_id = chest_deposit_match.group(3)
                quantity = chest_deposit_match.group(4)
                item_name = chest_deposit_match.group(5).strip().rstrip('.')
                
                return PlayerAction(
                    player_id=chest_deposit_match.group(2),
                    player_name=chest_deposit_match.group(1).strip(),
                    action_type="chest_deposit",
                    action_detail=f"pus in chest(id {chest_id}), {quantity}x {item_name}.",
                    item_name=item_name,
                    item_quantity=int(quantity),
                    timestamp=timestamp,
                    raw_text=text
                )

            # 🔥 FIXED: Item given pattern - matches "ia dat lui" (not "a dat lui")
            gave_match = re.search(
                r'Jucatorul\s+([^(]+)\((\d+)\)\s+(?:i)?a\s+dat\s+lui\s+([^(]+)\((\d+)\)\s+(.+?)(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)',
                text,
                re.IGNORECASE
            )
            if gave_match:
                # Extract items (everything after the target player info)
                items_text = gave_match.group(5).strip()
                # Remove leading comma if present
                items_text = items_text.lstrip(', ')
                
                return PlayerAction(
                    player_id=gave_match.group(2),
                    player_name=gave_match.group(1).strip(),
                    action_type="item_given",
                    action_detail=f"ia dat lui {gave_match.group(3).strip()}({gave_match.group(4)}) {items_text}",
                    item_name=items_text,
                    item_quantity=None,  # Quantity is in items_text
                    target_player_id=gave_match.group(4),
                    target_player_name=gave_match.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )

            # Item received pattern
            received_match = re.search(
                r'Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+primit\s+de\s+la\s+([^(]+)\((\d+)\)\s+x(\d+)\s+(.+?)(?=\d{4}-\d{2}-\d{2}|$)',
                text,
                re.IGNORECASE
            )
            if received_match:
                return PlayerAction(
                    player_id=received_match.group(2),
                    player_name=received_match.group(1).strip(),
                    action_type="item_received",
                    action_detail=f"Primit {received_match.group(6).strip()} de la {received_match.group(3).strip()}",
                    item_name=received_match.group(6).strip(),
                    item_quantity=int(received_match.group(5)),
                    target_player_id=received_match.group(4),
                    target_player_name=received_match.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )

            # Vehicle pattern
            vehicle_match = re.search(
                r'Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+(cumparat|vandut)\s+(.+?)(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)',
                text,
                re.IGNORECASE
            )
            if vehicle_match:
                action_type = "vehicle_bought" if "cumparat" in vehicle_match.group(3).lower() else "vehicle_sold"
                return PlayerAction(
                    player_id=vehicle_match.group(2),
                    player_name=vehicle_match.group(1).strip(),
                    action_type=action_type,
                    action_detail=vehicle_match.group(4).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )

            # Property pattern
            property_match = re.search(
                r'Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+(cumparat|vandut)\s+(casa|afacere|proprietate)\s*(.+?)(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)',
                text,
                re.IGNORECASE
            )
            if property_match:
                action_type = "property_bought" if "cumparat" in property_match.group(3).lower() else "property_sold"
                return PlayerAction(
                    player_id=property_match.group(2),
                    player_name=property_match.group(1).strip(),
                    action_type=action_type,
                    action_detail=f"{property_match.group(3)} {property_match.group(4)}",
                    timestamp=timestamp,
                    raw_text=text
                )

            # Generic pattern for any other "Jucatorul" action
            generic_match = re.search(
                r'Jucatorul\s+([^(]+)\((\d+)\)\s+(.+?)(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)',
                text,
                re.IGNORECASE
            )
            if generic_match:
                return PlayerAction(
                    player_id=generic_match.group(2),
                    player_name=generic_match.group(1).strip(),
                    action_type="other",
                    action_detail=generic_match.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )

            # Fallback for unmatched "jucatorul" mentions
            if 'jucatorul' in text.lower():
                return PlayerAction(
                    player_id=None,
                    player_name=None,
                    action_type="unknown",
                    action_detail=text[:200],
                    timestamp=timestamp,
                    raw_text=text
                )

            return None

        except Exception as e:
            logger.error(f"Error parsing action: {e}, Text: {text[:100] if text else 'NA'}")
            return None

    def is_vip_action(self, action: PlayerAction, vip_ids: Set[str]) -> bool:
        """Check if action involves any VIP player"""
        if not action:
            return False

        if action.player_id and action.player_id in vip_ids:
            return True

        if action.target_player_id and action.target_player_id in vip_ids:
            return True

        if action.admin_id and action.admin_id in vip_ids:
            return True

        return False

    async def get_vip_actions(self, vip_ids: Set[str], limit: int = 200) -> List[PlayerAction]:
        """Get latest actions filtered for VIP players only"""
        all_actions = await self.get_latest_actions(limit)
        vip_actions = [action for action in all_actions if self.is_vip_action(action, vip_ids)]
        logger.info(f"Found {len(vip_actions)} VIP actions out of {len(all_actions)} total")
        return vip_actions

    def is_online_action(self, action: PlayerAction, online_ids: Set[str]) -> bool:
        """Check if action involves any currently online player"""
        if not action:
            return False

        if action.player_id and action.player_id in online_ids:
            return True

        if action.target_player_id and action.target_player_id in online_ids:
            return True

        if action.admin_id and action.admin_id in online_ids:
            return True

        return False

    async def get_online_player_actions(self, online_ids: Set[str], limit: int = 200) -> List[PlayerAction]:
        """Get latest actions filtered for currently online players only"""
        all_actions = await self.get_latest_actions(limit)
        online_actions = [action for action in all_actions if self.is_online_action(action, online_ids)]
        logger.info(f"Found {len(online_actions)} online player actions out of {len(all_actions)} total")
        return online_actions

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

            soup = BeautifulSoup(html, 'lxml')
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

            next_link = soup.select_one(f'a[href*="pageOnline={page + 1}"]')
            if not next_link:
                break

            page += 1
            await asyncio.sleep(0.5)

        logger.info(f"Total online players found: {len(all_players)}")
        return all_players

    async def get_banned_players(self) -> List[Dict]:
        """Get banned players from banlist"""
        url = f"{self.base_url}/banlist"
        html = await self.fetch_page(url)

        if not html:
            return []

        soup = BeautifulSoup(html, 'lxml')
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


async def main():
    """Example usage"""
    async with Pro4KingsScraper() as scraper:
        actions = await scraper.get_latest_actions(limit=100)
        print(f"Found {len(actions)} actions")

        online = await scraper.get_online_players()
        print(f"Found {len(online)} online players")

        profile = await scraper.get_player_profile("1")
        if profile:
            print(f"Profile: {profile.username}")
        
        # Test faction scraping
        factions = await scraper.get_factions_info()
        print(f"Found {len(factions)} factions")
        for faction in factions:
            print(f"  - {faction['faction_name']}: {faction['member_count']} members")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Pro4Kings Scraper - Optimized version with TokenBucket Rate Limiter
AGGRESSIVE SETTINGS for 7-8 profiles/s
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
    """Rate limiter that allows controlled bursts"""

    def __init__(self, rate: float = 80.0, capacity: int = 120):
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
    """Enhanced scraper optimized for fast scanning with intelligent rate limiting"""

    def __init__(
        self,
        base_url: str = "https://panel.pro4kings.ro",
        max_concurrent: int = 50  # ⚡ AGGRESSIVE: 50 workers
    ):
        self.base_url = base_url
        self.max_concurrent = max(20, max_concurrent)  # ⚡ Minimum 20 (not 10)
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        self.client: Optional[aiohttp.ClientSession] = None

        # ⚡ AGGRESSIVE TokenBucket: 80 req/s with 120 burst capacity
        self.rate_limiter = TokenBucketRateLimiter(
            rate=80.0,      # 80 requests per second
            capacity=120    # Allow bursts up to 120
        )

        self.error_503_count = 0
        self.success_count = 0
        self.adaptive_delay = 0.0  # ⚡ Start with NO delay

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
            limit=100,  # ⚡ AGGRESSIVE: 100 connections
            limit_per_host=50,  # ⚡ AGGRESSIVE: 50 per host
            ttl_dns_cache=300,
            force_close=False,
            enable_cleanup_closed=True
        )

        self.client = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=self.headers
        )

        logger.info(f"✓ HTTP client initialized ({self.max_concurrent} workers, {self.rate_limiter.rate} req/s)")
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

            # ✅ Add jitter to avoid request synchronization
            jitter = random.uniform(0, 0.01)  # 0-10ms random jitter
            await asyncio.sleep(jitter)

            # ⚡ ONLY apply adaptive delay if it's set (not forced minimum)
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
        """Get complete player profile with improved faction rank detection"""
        profile_url = f"{self.base_url}/profile/{player_id}"
        html = await self.fetch_page(profile_url)

        if not html:
            return None

        soup = BeautifulSoup(html, 'lxml')

        try:
            username_elem = soup.select_one('.profile-username, .player-name, h1, h2, h3')
            username = username_elem.get_text(strip=True) if username_elem else f"Player_{player_id}"

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
                    hours_match = re.search(r'([\d.]+)', val)
                    if hours_match:
                        played_hours = float(hours_match.group(1))
                    break

            for key, val in profile_data.items():
                if any(x in key for x in ['varsta', 'vârstă', 'age', 'ani']):
                    age_match = re.search(r'(\d+)', val)
                    if age_match:
                        age_ic = int(age_match.group(1))
                    break

            for key, val in profile_data.items():
                if any(x in key for x in ['telefon', 'phone', 'număr']):
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

    async def batch_get_profiles(self, player_ids: List[str]) -> List[PlayerProfile]:
        """⚡ AGGRESSIVE: Parallel fetching with large waves"""
        results = []
        wave_size = 50  # ⚡ AGGRESSIVE: 50 profiles per wave
        wave_delay = 0.02  # ⚡ AGGRESSIVE: Only 20ms between waves

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

        self.action_scraping_stats['total_attempts'] += 1
        self.action_scraping_stats['total_actions_found'] += len(actions)
        logger.info(f"Parsed {len(actions)} actions from homepage")

        return actions[:limit]

    def parse_action_entry(self, entry) -> Optional[PlayerAction]:
        """Enhanced action parser with multiple patterns"""
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

            warning_match = re.search(
                r'Jucatorul\s+(\w+)\s+\((\d+)\)\s+a\s+primit\s+un\s+avertisment.*?de\s+la\s+administratorul\s+(\w+)\s+\((\d+)\).*?motiv:?\s*(.+?)(?:\d{4}-\d{2}-\d{2}|$)',
                text, re.IGNORECASE
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

            chest_match = re.search(
                r'Jucatorul\s+(\w+)\s+\((\d+)\)\s+a\s+(pus\s+in|scos\s+din)\s+chest(?:\s+ID\s+)?([^x]*)\s+x(\d+)\s+(.+?)(?:\d{4}-\d{2}-\d{2}|$)',
                text, re.IGNORECASE
            )
            if chest_match:
                action_type = "chest_deposit" if "pus in" in chest_match.group(3).lower() else "chest_withdraw"
                full_detail = f"{chest_match.group(3)} chest {chest_match.group(4) or ''} x{chest_match.group(5)} {chest_match.group(6).strip()}"

                return PlayerAction(
                    player_id=chest_match.group(2),
                    player_name=chest_match.group(1).strip(),
                    action_type=action_type,
                    action_detail=full_detail,
                    item_name=chest_match.group(6).strip(),
                    item_quantity=int(chest_match.group(5)),
                    timestamp=timestamp,
                    raw_text=text
                )

            gave_match = re.search(
                r'Jucatorul\s+(\w+)\s+\((\d+)\)\s+a\s+dat\s+lui\s+(\w+)\s+\((\d+)\)\s+x(\d+)\s+(.+?)(?:\d{4}-\d{2}-\d{2}|$)',
                text, re.IGNORECASE
            )
            if gave_match:
                return PlayerAction(
                    player_id=gave_match.group(2),
                    player_name=gave_match.group(1).strip(),
                    action_type="item_given",
                    action_detail=f"Dat {gave_match.group(6).strip()} către {gave_match.group(3).strip()}",
                    item_name=gave_match.group(6).strip(),
                    item_quantity=int(gave_match.group(5)),
                    target_player_id=gave_match.group(4),
                    target_player_name=gave_match.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )

            received_match = re.search(
                r'Jucatorul\s+(\w+)\s+\((\d+)\)\s+a\s+primit\s+de\s+la\s+(\w+)\s+\((\d+)\)\s+x(\d+)\s+(.+?)(?:\d{4}-\d{2}-\d{2}|$)',
                text, re.IGNORECASE
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

            vehicle_match = re.search(
                r'Jucatorul\s+(\w+)\s+\((\d+)\)\s+a\s+(cumparat|vandut)\s+(.+?)(?:\d{4}-\d{2}-\d{2}|Jucatorul)',
                text, re.IGNORECASE
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

            property_match = re.search(
                r'Jucatorul\s+(\w+)\s+\((\d+)\)\s+a\s+(cumparat|vandut)\s+(casa|afacere|proprietate)\s+(.+?)(?:\d{4}-\d{2}-\d{2}|Jucatorul)',
                text, re.IGNORECASE
            )
            if property_match:
                action_type = "property_bought" if "cumparat" in property_match.group(3).lower() else "property_sold"
                return PlayerAction(
                    player_id=property_match.group(2),
                    player_name=property_match.group(1).strip(),
                    action_type=action_type,
                    action_detail=f"{property_match.group(3)} {property_match.group(4)} {property_match.group(5)}",
                    timestamp=timestamp,
                    raw_text=text
                )

            generic_match = re.search(
                r'Jucatorul\s+(\w+)\s+\((\d+)\)\s+(.+?)(?:\d{4}-\d{2}-\d{2}|Jucatorul)',
                text, re.IGNORECASE
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
            logger.error(f"Error parsing action ({e}): Text: {text[:100] if text else 'N/A'}")
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


if __name__ == "__main__":
    asyncio.run(main())

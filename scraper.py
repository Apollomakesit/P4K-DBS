#!/usr/bin/env python3
"""
Pro4Kings Scraper - ULTRA SAFE Version with TokenBucket Rate Limiter
Minimum 1 worker support for maximum 503 error protection

🔥 ENHANCED: Now supports JavaScript-protected pages using cloudscraper
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

# 🔥 NEW: Cloudscraper for JavaScript challenge bypass (Cloudflare, etc.)
try:
    import cloudscraper

    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False
    logging.warning(
        "⚠️ Cloudscraper not installed - banlist scraping may fail on protected pages"
    )

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
    timestamp: Optional[datetime] = None
    raw_text: Optional[str] = None


@dataclass
class PlayerProfile:
    """Complete player profile - CLEANED UP (removed deprecated fields)"""

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
    """Ultra-safe scraper with TokenBucket rate limiting - supports 1-50 workers

    🔥 OPTIMIZED for panel.pro4kings.ro shared hosting:
    - Server has 30 connection limit (shared with other users)
    - Tests showed 5 workers at ~20 req/s sustained works
    - Using conservative 10 req/s default to avoid 503 errors
    """

    def __init__(
        self,
        base_url: str = "https://panel.pro4kings.ro",
        max_concurrent: int = 5,  # Default: 5 workers (reduced from 10)
        rate_limit: Optional[float] = None,
        burst_capacity: Optional[int] = None,
    ):
        self.base_url = base_url
        self.max_concurrent = max(
            1, max_concurrent
        )  # ✅ Minimum 1 worker for ultra-safe scanning
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        self.client: Optional[aiohttp.ClientSession] = None

        # TokenBucket: Smooth request distribution
        # 🔥 OPTIMIZED: Conservative defaults for shared hosting
        effective_rate = (
            rate_limit if rate_limit is not None else min(10.0, self.max_concurrent * 2)
        )
        effective_capacity = (
            burst_capacity
            if burst_capacity is not None
            else min(20, self.max_concurrent * 4)
        )
        effective_rate = max(0.1, float(effective_rate))
        effective_capacity = max(1, int(effective_capacity))
        self.rate_limiter = TokenBucketRateLimiter(
            rate=effective_rate,
            capacity=effective_capacity,
        )

        self.error_503_count = 0
        self.success_count = 0
        self.adaptive_delay = 0.0  # Start with no delay, adapts if 503s occur

        self.action_scraping_stats = {
            "total_attempts": 0,
            "successful_parses": 0,
            "failed_parses": 0,
            "total_actions_found": 0,
        }

        self.last_request_time = {}
        self.request_times = []
        self.consecutive_503 = 0

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
        }

    async def __aenter__(self):
        """Async context manager entry"""
        timeout = aiohttp.ClientTimeout(total=15, connect=5)

        # 🔥 ENHANCED: Use CookieJar to persist cookies across requests (for challenge bypass)
        cookie_jar = aiohttp.CookieJar(
            unsafe=True
        )  # unsafe=True allows cookies for all domains

        connector = aiohttp.TCPConnector(
            limit=max(10, self.max_concurrent * 2),
            limit_per_host=max(10, self.max_concurrent * 2),
            ttl_dns_cache=300,
            force_close=False,
            enable_cleanup_closed=True,
        )

        self.client = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=self.headers,
            cookie_jar=cookie_jar,  # 🔥 Enable cookie persistence
        )

        logger.info(
            f"✓ HTTP client initialized ({self.max_concurrent} workers, {self.rate_limiter.rate:.1f} req/s)"
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.client:
            await self.client.close()
            await asyncio.sleep(0.1)

    async def fetch_page(self, url: str, retries: int = 3) -> Optional[str]:
        """Fetch page with TokenBucket rate limiting and adaptive throttling

        🔥 ENHANCED: Handles "Un moment, vă rog..." JavaScript challenge by waiting and retrying
        """
        if self.client is None:
            logger.error("HTTP client not initialized! Call __aenter__ first.")
            return None

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
                            html = await response.text()

                            # 🔥 DETECT JAVASCRIPT CHALLENGE: "Un moment, vă rog..."
                            if "Un moment, vă rog" in html or "Un moment" in html[:500]:
                                if attempt < retries - 1:
                                    wait_time = (
                                        7  # Wait 7 seconds (page says 5, add buffer)
                                    )
                                    logger.info(
                                        f"🔄 Challenge page detected, waiting {wait_time}s..."
                                    )
                                    await asyncio.sleep(wait_time)
                                    continue  # Retry the request
                                else:
                                    logger.warning(
                                        f"⚠️ Challenge page still present after {retries} attempts"
                                    )
                                    return None

                            self.consecutive_503 = 0
                            self.success_count += 1

                            # Reduce delay if many successes
                            if self.success_count >= 50 and self.adaptive_delay > 0.01:
                                self.adaptive_delay = max(0, self.adaptive_delay * 0.9)
                                self.success_count = 0

                            return html

                        elif response.status == 404:
                            return None

                        elif response.status == 503:
                            self.error_503_count += 1
                            self.consecutive_503 += 1

                            if self.consecutive_503 >= 3:
                                self.adaptive_delay = min(
                                    2.0, self.adaptive_delay + 0.3
                                )
                                logger.warning(
                                    f"Multiple 503s - delay now: {self.adaptive_delay:.2f}s"
                                )
                            else:
                                self.adaptive_delay = min(
                                    1.0, self.adaptive_delay + 0.1
                                )

                            wait_time = min(10, 2**attempt)

                            if self.error_503_count >= 10:
                                logger.error("Too many 503s! Backing off...")
                                await asyncio.sleep(5)
                                self.error_503_count = 0

                            if attempt < retries - 1:
                                await asyncio.sleep(wait_time)
                                continue
                            raise Exception("503 Service Unavailable")

                        elif response.status == 429:
                            wait_time = min(15, 5 * (2**attempt))
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
                    if "503" in str(e):
                        raise
                    if attempt < retries - 1:
                        await asyncio.sleep(0.5)
                        continue
                    return None

        return None

    async def get_player_profile(self, player_id: str) -> Optional[PlayerProfile]:
        """🔥 ENHANCED: Get player profile - specifically for Pro4Kings HTML structure"""
        profile_url = f"{self.base_url}/profile/{player_id}"
        html = await self.fetch_page(profile_url)
        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")

        try:
            # 🔥 SPECIFIC USERNAME EXTRACTION for Pro4Kings structure
            username = None

            # Method 1: Find h4.card-title and extract from font tag
            card_title = soup.select_one("h4.card-title")
            if card_title:
                # Look specifically for font tag inside card-title
                font_tag = card_title.find("font")
                if font_tag:
                    username = font_tag.get_text(strip=True)
                    logger.debug(
                        f"Found username '{username}' in h4.card-title > font for player {player_id}"
                    )
                else:
                    # Fallback: get all text but remove icon
                    for icon in card_title.find_all(["i", "svg"]):
                        icon.decompose()
                    username = card_title.get_text(strip=True)
                    logger.debug(
                        f"Found username '{username}' in h4.card-title (no font) for player {player_id}"
                    )

            # Method 2: Try .card-title without h4 restriction
            if not username or username == player_id:
                card_title_any = soup.select_one(".card-title")
                if card_title_any:
                    font_tag = card_title_any.find("font")
                    if font_tag:
                        username = font_tag.get_text(strip=True)
                        logger.debug(
                            f"Found username '{username}' in .card-title > font for player {player_id}"
                        )

            # Method 3: Look for any font tag with style="vertical-align: middle;"
            if not username or username == player_id:
                font_with_style = soup.find("font", style=re.compile(r"vertical-align"))
                if font_with_style:
                    username = font_with_style.get_text(strip=True)
                    logger.debug(
                        f"Found username '{username}' in font[style] for player {player_id}"
                    )

            # Method 4: Generic selectors
            if not username or username == player_id:
                username_selectors = [
                    ".profile-username",
                    ".player-name",
                    ".username",
                    "h1",
                    "h2",
                    "h3",
                ]
                for selector in username_selectors:
                    username_elem = soup.select_one(selector)
                    if username_elem:
                        text = username_elem.get_text(strip=True)
                        if text and text != player_id and len(text) > 1:
                            username = text
                            logger.debug(
                                f"Found username '{username}' with selector '{selector}' for player {player_id}"
                            )
                            break

            # Final validation and fallback
            if not username or username == player_id or len(username) < 2:
                username = f"Player_{player_id}"
                logger.warning(
                    f"⚠️ Could not extract username for player {player_id}, using placeholder"
                )

            # Online status
            is_online = bool(
                soup.find(
                    "i", class_=re.compile(r"text-success|fa-circle.*text-success")
                )
            )
            if not is_online:
                is_online = bool(soup.find(text=re.compile(r"Online", re.IGNORECASE)))

            last_seen = datetime.now()

            # Parse last connection time
            last_conn_cell = soup.find(
                "th",
                text=re.compile(r"Ultima.*conectare|Last.*connection", re.IGNORECASE),
            )
            if last_conn_cell:
                td = last_conn_cell.find_next_sibling("td")
                if td:
                    time_text = td.get_text(strip=True)
                    # Format: 25/01/2026 16:06:15
                    time_match = re.search(
                        r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})", time_text
                    )
                    if time_match:
                        try:
                            last_seen = datetime.strptime(
                                time_match.group(1), "%d/%m/%Y %H:%M:%S"
                            )
                            logger.debug(
                                f"Parsed last_seen: {last_seen} for player {player_id}"
                            )
                        except Exception as e:
                            logger.debug(f"Could not parse datetime: {e}")

            profile_data = {}

            # 🔥 PARSE TABLE DATA - specific to Pro4Kings structure
            # Find all <th scope="row"> elements
            table_headers = soup.find_all("th", attrs={"scope": "row"})
            for th in table_headers:
                key = th.get_text(strip=True).lower()
                # Get the corresponding td (next sibling)
                td = th.find_next_sibling("td")
                if td:
                    val = td.get_text(strip=True)
                    if val and val not in ["—", "-", ""]:
                        profile_data[key] = val
                        logger.debug(f"Profile data: {key} = {val}")

            # Extract specific fields
            faction = None
            faction_rank = None
            job = None
            warnings = None
            played_hours = None
            age_ic = None

            # Faction extraction
            for key, val in profile_data.items():
                if any(x in key for x in ["facțiune", "factiune", "fac", "faction"]):
                    if val and val not in ["Civil", "Fără", "Fara", "None", "-"]:
                        faction = val
                        logger.debug(f"Found faction: {faction}")
                        break

            # Faction rank extraction
            for key, val in profile_data.items():
                if any(
                    x in key for x in ["rank facțiune", "rank factiune", "rank", "rang"]
                ):
                    if val and val not in ["-", "None", "Fără", "Fara"]:
                        faction_rank = val
                        logger.debug(f"Found faction_rank: {faction_rank}")
                        break

            # Job extraction
            for key, val in profile_data.items():
                if "job" in key or "meserie" in key:
                    job = val
                    logger.debug(f"Found job: {job}")
                    break

            # Warnings extraction
            for key, val in profile_data.items():
                if "warn" in key or "avertis" in key:
                    warn_match = re.search(r"(\d+)", val)
                    if warn_match:
                        warnings = int(warn_match.group(1))
                        logger.debug(f"Found warnings: {warnings}")
                        break

            # Played hours extraction
            for key, val in profile_data.items():
                if any(x in key for x in ["ore jucate", "ore", "hours"]):
                    hours_match = re.search(r"([\d.]+)", val)
                    if hours_match:
                        played_hours = float(hours_match.group(1))
                        logger.debug(f"Found played_hours: {played_hours}")
                        break

            # 🔥 AGE IC EXTRACTION - handle Romanian characters properly
            # Look for keys containing age-related terms
            for key, val in profile_data.items():
                # Normalize key for comparison (remove diacritics)
                key_normalized = (
                    key.replace("ă", "a").replace("â", "a").replace("î", "i")
                )
                if any(
                    x in key_normalized
                    for x in ["varsta", "vârsta", "age", "varsta ic", "age ic"]
                ):
                    age_match = re.search(r"(\d+)", val)
                    if age_match:
                        potential_age = int(age_match.group(1))
                        if 18 <= potential_age <= 99:
                            age_ic = potential_age
                            logger.debug(
                                f"Found age_ic {age_ic} from key '{key}' = '{val}' for player {player_id}"
                            )
                            break

            # Direct search for "Vârsta IC" table row
            if not age_ic:
                age_th = soup.find(
                    "th", text=re.compile(r"V[aâă]rst[aă].*IC", re.IGNORECASE)
                )
                if age_th:
                    age_td = age_th.find_next_sibling("td")
                    if age_td:
                        age_text = age_td.get_text(strip=True)
                        age_match = re.search(r"(\d+)", age_text)
                        if age_match:
                            potential_age = int(age_match.group(1))
                            if 18 <= potential_age <= 99:
                                age_ic = potential_age
                                logger.debug(
                                    f"Found age_ic {age_ic} from direct th search for player {player_id}"
                                )

            if not age_ic:
                logger.warning(f"⚠️ Could not extract age_ic for player {player_id}")
                logger.debug(f"Profile data keys: {list(profile_data.keys())}")

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
                profile_data=profile_data,
            )

        except Exception as e:
            logger.error(
                f"Error parsing profile for player {player_id}: {e}", exc_info=True
            )
            return None

    async def batch_get_profiles(self, player_ids: List[str]) -> List[PlayerProfile]:
        """Batch fetch profiles with configurable wave size"""
        results = []
        # 🔥 OPTIMIZED: Reduced wave size and increased delay for shared hosting
        wave_size = min(25, max(10, self.max_concurrent * 3))  # Reduced from 50
        wave_delay = 0.1  # 100ms between waves (was 50ms)

        for i in range(0, len(player_ids), wave_size):
            wave = player_ids[i : i + wave_size]
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

        soup = BeautifulSoup(html, "lxml")
        factions = []

        # Try multiple selectors to find faction data
        # Common patterns: table rows, cards, divs with faction info

        # Try table format first
        faction_rows = soup.select("table tr")
        if len(faction_rows) > 1:  # Has header + data
            logger.info(f"Found {len(faction_rows)-1} faction rows in table")

            for row in faction_rows[1:]:  # Skip header
                try:
                    cells = row.select("td")
                    if len(cells) >= 2:
                        # Extract faction name and member count
                        faction_name = cells[0].get_text(strip=True)

                        # Look for member count (usually numeric)
                        member_count = 0
                        for cell in cells[1:]:
                            text = cell.get_text(strip=True)
                            count_match = re.search(r"(\d+)", text)
                            if count_match:
                                member_count = int(count_match.group(1))
                                break

                        if faction_name and faction_name not in ["Civil", "-", "Fără"]:
                            factions.append(
                                {
                                    "faction_name": faction_name,
                                    "member_count": member_count,
                                    "scraped_at": datetime.now(),
                                }
                            )

                except Exception as e:
                    logger.error(f"Error parsing faction row: {e}")
                    continue

        # Try card/div format if table didn't work
        if not factions:
            faction_cards = soup.select(".faction, .faction-card, .faction-info")
            logger.info(f"Found {len(faction_cards)} faction cards")

            for card in faction_cards:
                try:
                    faction_name = None
                    member_count = 0

                    # Look for faction name
                    name_elem = card.select_one("h2, h3, h4, .faction-name, .name")
                    if name_elem:
                        faction_name = name_elem.get_text(strip=True)

                    # Look for member count
                    count_text = card.get_text()
                    count_matches = re.findall(
                        r"(\d+)\s*(?:membr|member|players|jucători)",
                        count_text,
                        re.IGNORECASE,
                    )
                    if count_matches:
                        member_count = int(count_matches[0])

                    if faction_name and faction_name not in ["Civil", "-", "Fără"]:
                        factions.append(
                            {
                                "faction_name": faction_name,
                                "member_count": member_count,
                                "scraped_at": datetime.now(),
                            }
                        )

                except Exception as e:
                    logger.error(f"Error parsing faction card: {e}")
                    continue

        logger.info(f"✅ Scraped {len(factions)} factions")
        return factions

    async def get_latest_actions(self, limit: int = 200) -> List[PlayerAction]:
        """🔥 REWRITTEN: Get latest actions using precise Pro4Kings HTML structure.

        The Pro4Kings homepage has a specific structure:
        - Card with h4 "Ultimele acțiuni"
        - div.list-group.list-group-custom containing action items
        - Each action is a div.list-group-item with:
          - p.mb-1 containing the action text
          - small > div containing timestamp (YYYY-MM-DD HH:MM:SS)
        """
        url = f"{self.base_url}/"
        html = await self.fetch_page(url)

        if not html:
            logger.error("Failed to fetch homepage for actions!")
            return []

        soup = BeautifulSoup(html, "lxml")
        actions = []
        seen_raw_texts = set()  # Dedupe within same scrape

        # 🔥 METHOD 1: Find the "Ultimele acțiuni" card directly
        actions_header = soup.find(
            "h4", text=re.compile(r"Ultimele\s*acț", re.IGNORECASE)
        )
        if actions_header:
            # Find the parent card
            card = actions_header.find_parent("div", class_="card")
            if card:
                # Find all list-group-item elements
                action_items = card.find_all("div", class_="list-group-item")
                logger.info(
                    f"Found {len(action_items)} action items in Ultimele acțiuni card"
                )

                for item in action_items:
                    # Extract action text from p.mb-1
                    p_tag = item.find("p", class_="mb-1")
                    if not p_tag:
                        continue
                    action_text = p_tag.get_text(strip=True)

                    # Extract timestamp from small > div
                    timestamp = None
                    small_tag = item.find("small")
                    if small_tag:
                        time_match = re.search(
                            r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
                            small_tag.get_text(),
                        )
                        if time_match:
                            try:
                                timestamp = datetime.strptime(
                                    time_match.group(1), "%Y-%m-%d %H:%M:%S"
                                )
                            except ValueError:
                                timestamp = datetime.now()

                    if not timestamp:
                        timestamp = datetime.now()

                    # Dedupe by raw text within this scrape
                    if action_text in seen_raw_texts:
                        continue
                    seen_raw_texts.add(action_text)

                    # Parse the action
                    action = self._parse_action_text(action_text, timestamp)
                    if action:
                        actions.append(action)

        # 🔥 METHOD 2: Fallback - find list-group-custom directly
        if not actions:
            list_group = soup.find("div", class_="list-group-custom")
            if list_group:
                action_items = list_group.find_all("div", class_="list-group-item")
                logger.info(
                    f"Fallback: Found {len(action_items)} items in list-group-custom"
                )

                for item in action_items:
                    p_tag = item.find("p", class_="mb-1")
                    if not p_tag:
                        continue
                    action_text = p_tag.get_text(strip=True)

                    timestamp = None
                    small_tag = item.find("small")
                    if small_tag:
                        time_match = re.search(
                            r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
                            small_tag.get_text(),
                        )
                        if time_match:
                            try:
                                timestamp = datetime.strptime(
                                    time_match.group(1), "%Y-%m-%d %H:%M:%S"
                                )
                            except ValueError:
                                timestamp = datetime.now()

                    if not timestamp:
                        timestamp = datetime.now()

                    if action_text in seen_raw_texts:
                        continue
                    seen_raw_texts.add(action_text)

                    action = self._parse_action_text(action_text, timestamp)
                    if action:
                        actions.append(action)

        if not actions:
            logger.warning(
                "No actions found with precise selectors, page structure may have changed"
            )
        else:
            logger.info(f"✅ Scraped {len(actions)} unique actions from homepage")

        self.action_scraping_stats["total_attempts"] += 1
        self.action_scraping_stats["total_actions_found"] += len(actions)

        return actions[:limit]

    def _parse_action_text(
        self, text: str, timestamp: datetime
    ) -> Optional[PlayerAction]:
        """🔥 COMPREHENSIVE: Parse action text into PlayerAction with ALL patterns.

        Patterns supported:
        1. Money deposit - "a depozitat suma de X$ (taxa Y$)"
        2. Money withdrawal - "a retras suma de X$ (taxa Y$)"
        3. Money transfer - "ia transferat suma de X$ lui Player(ID)"
        4. Chest deposit - "a pus in chest(id X), Nx Item"
        5. Chest withdraw - "a retras din chest(id X), Nx Item"
        6. Item given - "ia dat lui Player(ID) items"
        7. Item received - "a primit de la Player(ID) Nx Item"
        8. Contract with arrow - "Contract Player1(ID) -> Player2(ID)"
        9. Contract with exchange - "Contract Player1(ID) Player2(ID). ('ID1' [Item], 'ID2' [Money$"
        10. Warning received
        11. Trade completed
        12. Property bought/sold
        13. Vehicle bought/sold
        14. Legacy multi-action (from old scraper)
        15. Generic Jucatorul action
        16. Catch-all unknown
        """
        if not text or len(text) < 10:
            return None

        # Clean up text
        text = " ".join(text.split())

        # 🔥 DETECT LEGACY MULTI-ACTION: Old scraper captured multiple actions concatenated
        # Pattern: "Ultimele acțiuniJucatorul..." or multiple "Jucatorul...ProfilJucatorul..."
        if (
            "Ultimele acțiuni" in text
            or text.count("Jucatorul") > 1
            or "ProfilJucatorul" in text
        ):
            # This is legacy garbage - mark as such but still save it
            first_id_match = re.search(r"\((\d+)\)", text)
            return PlayerAction(
                player_id=first_id_match.group(1) if first_id_match else None,
                player_name=None,
                action_type="legacy_multi_action",
                action_detail="[Legacy] Multiple concatenated actions from old scraper",
                timestamp=timestamp,
                raw_text=text,
            )

        # ============================================================================
        # ID-ONLY PATTERNS: Handle "Jucatorul (ID)" with no name
        # These must be checked BEFORE regular patterns
        # ============================================================================

        # 🔥 ID-ONLY PATTERN A: Chest deposit - "Jucatorul (ID) a pus in chest..."
        chest_deposit_idonly = re.search(
            r"Jucatorul\s+\((\d+)\)\s+a\s+pus\s+in\s+chest\s*\(id\s+([^)]+)\)\s*,\s*(\d+)x\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if chest_deposit_idonly:
            return PlayerAction(
                player_id=chest_deposit_idonly.group(1),
                player_name=None,
                action_type="chest_deposit",
                action_detail=f"Pus in chest({chest_deposit_idonly.group(2)}): {chest_deposit_idonly.group(3)}x {chest_deposit_idonly.group(4).strip()}",
                item_name=chest_deposit_idonly.group(4).strip().rstrip("."),
                item_quantity=int(chest_deposit_idonly.group(3)),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 ID-ONLY PATTERN B: Chest withdraw - "Jucatorul (ID) a retras din chest..."
        chest_withdraw_idonly = re.search(
            r"Jucatorul\s+\((\d+)\)\s+a\s+retras\s+din\s+chest\s*\(id\s+([^)]+)\)\s*,\s*(\d+)x\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if chest_withdraw_idonly:
            return PlayerAction(
                player_id=chest_withdraw_idonly.group(1),
                player_name=None,
                action_type="chest_withdraw",
                action_detail=f"Retras din chest({chest_withdraw_idonly.group(2)}): {chest_withdraw_idonly.group(3)}x {chest_withdraw_idonly.group(4).strip()}",
                item_name=chest_withdraw_idonly.group(4).strip().rstrip("."),
                item_quantity=int(chest_withdraw_idonly.group(3)),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 ID-ONLY PATTERN C: Item given - "Jucatorul (ID) ia dat lui Name(ID) Nx Item"
        gave_idonly = re.search(
            r"Jucatorul\s+\((\d+)\)\s+i?a\s+dat\s+lui\s+(.+?)\((\d+)\)\s+(\d+)x\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if gave_idonly:
            return PlayerAction(
                player_id=gave_idonly.group(1),
                player_name=None,
                action_type="item_given",
                action_detail=f"Dat lui {gave_idonly.group(2).strip()}: {gave_idonly.group(4)}x {gave_idonly.group(5).strip()}",
                item_name=gave_idonly.group(5).strip().rstrip("."),
                item_quantity=int(gave_idonly.group(4)),
                target_player_id=gave_idonly.group(3),
                target_player_name=gave_idonly.group(2).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 ID-ONLY PATTERN D: Money withdrawal - "Jucatorul (ID) a retras suma de X$ (taxa Y$)"
        withdraw_idonly = re.search(
            r"Jucatorul\s+\((\d+)\)\s+a\s+retras\s+suma\s+de\s+([\d.,]+)\$\s*\(taxa\s+([\d.,]+)\$\)",
            text,
            re.IGNORECASE,
        )
        if withdraw_idonly:
            return PlayerAction(
                player_id=withdraw_idonly.group(1),
                player_name=None,
                action_type="money_withdraw",
                action_detail=f"Retras {withdraw_idonly.group(2)}$ (taxa {withdraw_idonly.group(3)}$)",
                timestamp=timestamp,
                raw_text=text,
            )

        # ============================================================================
        # FLEXIBLE PATTERNS: Handle names with no space, emails, brackets, etc.
        # These use .+? to match ANY name format
        # ============================================================================

        # 🔥 FLEXIBLE PATTERN A: Chest deposit/withdraw - handles ALL name formats including no-space emails
        # Matches: "Jucatorul[email protected](ID)", "Jucatorul Name(ID)", "Jucatorul Dark (tag)(ID)"
        chest_flexible = re.search(
            r"Jucatorul\s*(.+?)\((\d+)\)\s+a\s+(pus\s+in|retras\s+din)\s+chest\s*\(id\s+([^)]+)\)\s*,\s*(\d+)x\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if chest_flexible:
            action_type = (
                "chest_deposit"
                if "pus" in chest_flexible.group(3)
                else "chest_withdraw"
            )
            action_verb = "Pus in" if "pus" in chest_flexible.group(3) else "Retras din"
            player_name = (
                chest_flexible.group(1).strip()
                if chest_flexible.group(1).strip()
                else None
            )
            return PlayerAction(
                player_id=chest_flexible.group(2),
                player_name=player_name,
                action_type=action_type,
                action_detail=f"{action_verb} chest({chest_flexible.group(4)}): {chest_flexible.group(5)}x {chest_flexible.group(6).strip()}",
                item_name=chest_flexible.group(6).strip().rstrip("."),
                item_quantity=int(chest_flexible.group(5)),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 FLEXIBLE PATTERN B: Item given - handles ALL name formats
        gave_flexible = re.search(
            r"Jucatorul\s*(.+?)\((\d+)\)\s+i?a\s+dat\s+lui\s+(.+?)\((\d+)\)\s+(\d+)x\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if gave_flexible:
            sender_name = (
                gave_flexible.group(1).strip()
                if gave_flexible.group(1).strip()
                else None
            )
            return PlayerAction(
                player_id=gave_flexible.group(2),
                player_name=sender_name,
                action_type="item_given",
                action_detail=f"Dat lui {gave_flexible.group(3).strip()}: {gave_flexible.group(5)}x {gave_flexible.group(6).strip()}",
                item_name=gave_flexible.group(6).strip().rstrip("."),
                item_quantity=int(gave_flexible.group(5)),
                target_player_id=gave_flexible.group(4),
                target_player_name=gave_flexible.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 FLEXIBLE PATTERN C: Item sold - "[ID]name" format with no space before "a vandut"
        item_sold_flexible = re.search(
            r"Jucatorul\s+\[(\d+)\](.+?)a\s+vandut\s+x?(\d+)\s+(.+?)\s+pentru\s+suma\s+de\s+\$?([\d.,]+)",
            text,
            re.IGNORECASE,
        )
        if item_sold_flexible:
            return PlayerAction(
                player_id=item_sold_flexible.group(1),
                player_name=item_sold_flexible.group(2).strip(),
                action_type="item_sold",
                action_detail=f"Vândut {item_sold_flexible.group(3)}x {item_sold_flexible.group(4).strip()} pentru {item_sold_flexible.group(5)}$",
                item_name=item_sold_flexible.group(4).strip(),
                item_quantity=int(item_sold_flexible.group(3)),
                timestamp=timestamp,
                raw_text=text,
            )

        # ============================================================================
        # ADMIN ACTION PATTERNS
        # ============================================================================

        # 🔥 ADMIN PATTERN A: Kill Character - "Administratorul Name(ID) ia dat KILL CHARACTER jucatorului Name(ID)"
        kill_char_match = re.search(
            r"Administratorul\s+(.+?)\((\d+)\)\s+i?a\s+dat\s+KILL\s+CHARACTER\s+jucatorului\s+(.+?)\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if kill_char_match:
            return PlayerAction(
                player_id=kill_char_match.group(4),  # Target player
                player_name=kill_char_match.group(3).strip(),
                action_type="kill_character",
                action_detail=f"Kill Character de la {kill_char_match.group(1).strip()}",
                admin_id=kill_char_match.group(2),
                admin_name=kill_char_match.group(1).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 ADMIN PATTERN B: Deban - "a fost debanat de catre administratorul Name(ID)"
        deban_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+fost\s+debanat\s+de\s+catre\s+administratorul\s+(.+?)\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if deban_match:
            return PlayerAction(
                player_id=deban_match.group(2),
                player_name=deban_match.group(1).strip(),
                action_type="admin_unban",
                action_detail=f"Debanat de {deban_match.group(3).strip()}",
                admin_id=deban_match.group(4),
                admin_name=deban_match.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 ADMIN PATTERN C: Ban alt format - handles "(de)" in duration like "30 (de) zi(le)"
        ban_alt_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+fost\s+banat\s+de\s+catre\s+admin(?:ul)?\s+(.+?)\((\d+)\)\s*,\s*durata\s+(.+?)\s*,\s*motiv\s+['\"]?(.+?)['\"]?(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if ban_alt_match:
            return PlayerAction(
                player_id=ban_alt_match.group(2),
                player_name=ban_alt_match.group(1).strip(),
                action_type="ban_received",
                action_detail=f"Ban de la {ban_alt_match.group(3).strip()}: {ban_alt_match.group(6).strip()} ({ban_alt_match.group(5)})",
                admin_id=ban_alt_match.group(4),
                admin_name=ban_alt_match.group(3).strip(),
                reason=ban_alt_match.group(6).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # ============================================================================
        # REGULAR PATTERNS: "Jucatorul Name(ID)" format
        # ============================================================================

        # 🔥 PATTERN 1: Money deposit - "a depozitat suma de X$ (taxa Y$)" (now handles "(de)" in amount)
        deposit_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+depozitat\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$\s*\(taxa\s+([\d.,]+)\$\)",
            text,
            re.IGNORECASE,
        )
        if deposit_match:
            amount = deposit_match.group(3)
            tax = deposit_match.group(4)
            return PlayerAction(
                player_id=deposit_match.group(2),
                player_name=deposit_match.group(1).strip(),
                action_type="money_deposit",
                action_detail=f"Depozitat {amount}$ (taxa {tax}$)",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 2: Money withdrawal - "a retras suma de X$ (taxa Y$)" (now handles "(de)" in amount)
        withdraw_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+retras\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$\s*\(taxa\s+([\d.,]+)\$\)",
            text,
            re.IGNORECASE,
        )
        if withdraw_match:
            amount = withdraw_match.group(3)
            tax = withdraw_match.group(4)
            return PlayerAction(
                player_id=withdraw_match.group(2),
                player_name=withdraw_match.group(1).strip(),
                action_type="money_withdraw",
                action_detail=f"Retras {amount}$ (taxa {tax}$)",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 3: Money transfer - "ia transferat suma de X$ lui Player(ID)" (now handles "(de)" in amount)
        transfer_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+i?a\s+transferat\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$?\s*lui\s+([^(]+)\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if transfer_match:
            return PlayerAction(
                player_id=transfer_match.group(2),
                player_name=transfer_match.group(1).strip(),
                action_type="money_transfer",
                action_detail=f"Transferat {transfer_match.group(3)}$ lui {transfer_match.group(4).strip()}",
                target_player_id=transfer_match.group(5),
                target_player_name=transfer_match.group(4).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 ID-ONLY DEPOSIT PATTERN: "Jucatorul (ID) a depozitat..." with no name
        # Example: "Jucatorul (221001) a depozitat suma de 2.781.647$ (taxa 27.816$)."
        deposit_idonly = re.search(
            r"Jucatorul\s+\((\d+)\)\s+a\s+depozitat\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$\s*\(taxa\s+([\d.,]+)\$\)",
            text,
            re.IGNORECASE,
        )
        if deposit_idonly:
            return PlayerAction(
                player_id=deposit_idonly.group(1),
                player_name=None,
                action_type="money_deposit",
                action_detail=f"Depozitat {deposit_idonly.group(2)}$ (taxa {deposit_idonly.group(3)}$)",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 FLEXIBLE PATTERN FOR DEPOSIT: Handles names with spaces/tags/parentheses like "sasuke (192)"
        # Example: "Jucatorul sasuke (192)(209261) a depozitat suma de 131.000.000$ (taxa 1.310.000$)."
        deposit_flexible = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+depozitat\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$\s*\(taxa\s+([\d.,]+)\$\)",
            text,
            re.IGNORECASE,
        )
        if deposit_flexible:
            amount = deposit_flexible.group(3)
            tax = deposit_flexible.group(4)
            return PlayerAction(
                player_id=deposit_flexible.group(2),
                player_name=deposit_flexible.group(1).strip(),
                action_type="money_deposit",
                action_detail=f"Depozitat {amount}$ (taxa {tax}$)",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 FLEXIBLE PATTERN FOR WITHDRAWAL: Handles names with spaces/tags/parentheses
        # Example: "Jucatorul Some Name (tag)(123) a retras suma de X$ (taxa Y$)."
        withdraw_flexible = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+retras\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$\s*\(taxa\s+([\d.,]+)\$\)",
            text,
            re.IGNORECASE,
        )
        if withdraw_flexible:
            amount = withdraw_flexible.group(3)
            tax = withdraw_flexible.group(4)
            return PlayerAction(
                player_id=withdraw_flexible.group(2),
                player_name=withdraw_flexible.group(1).strip(),
                action_type="money_withdraw",
                action_detail=f"Retras {amount}$ (taxa {tax}$)",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 4: Chest deposit - "a pus in chest(id X), Nx Item"
        chest_deposit_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+pus\s+in\s+chest\s*\(id\s+([^)]+)\)\s*,\s*(\d+)x\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if chest_deposit_match:
            return PlayerAction(
                player_id=chest_deposit_match.group(2),
                player_name=chest_deposit_match.group(1).strip(),
                action_type="chest_deposit",
                action_detail=f"Pus in chest({chest_deposit_match.group(3)}): {chest_deposit_match.group(4)}x {chest_deposit_match.group(5).strip()}",
                item_name=chest_deposit_match.group(5).strip().rstrip("."),
                item_quantity=int(chest_deposit_match.group(4)),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 5: Chest withdraw - "a retras din chest(id X), Nx Item"
        chest_withdraw_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+retras\s+din\s+chest\s*\(id\s+([^)]+)\)\s*,\s*(\d+)x\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if chest_withdraw_match:
            return PlayerAction(
                player_id=chest_withdraw_match.group(2),
                player_name=chest_withdraw_match.group(1).strip(),
                action_type="chest_withdraw",
                action_detail=f"Retras din chest({chest_withdraw_match.group(3)}): {chest_withdraw_match.group(4)}x {chest_withdraw_match.group(5).strip()}",
                item_name=chest_withdraw_match.group(5).strip().rstrip("."),
                item_quantity=int(chest_withdraw_match.group(4)),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 6: Item given - "ia dat lui" Player(ID) items (flexible: handles Nx items or just items)
        gave_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+i?a\s+dat\s+lui\s+([^(]+)\((\d+)\)\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if gave_match:
            items_text = gave_match.group(5).strip().rstrip(".")
            # Try to extract quantity if present
            qty_match = re.match(r"(\d+)x\s+(.+)", items_text)
            item_qty = int(qty_match.group(1)) if qty_match else None
            item_name = qty_match.group(2) if qty_match else items_text

            return PlayerAction(
                player_id=gave_match.group(2),
                player_name=gave_match.group(1).strip(),
                action_type="item_given",
                action_detail=f"Dat lui {gave_match.group(3).strip()}: {items_text}",
                item_name=item_name,
                item_quantity=item_qty,
                target_player_id=gave_match.group(4),
                target_player_name=gave_match.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 7: Item received - "a primit de la Player(ID) Nx Item"
        received_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+primit\s+de\s+la\s+([^(]+)\((\d+)\)\s+(\d+)x\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if received_match:
            return PlayerAction(
                player_id=received_match.group(2),
                player_name=received_match.group(1).strip(),
                action_type="item_received",
                action_detail=f"Primit de la {received_match.group(3).strip()}: {received_match.group(5)}x {received_match.group(6).strip()}",
                item_name=received_match.group(6).strip().rstrip("."),
                item_quantity=int(received_match.group(5)),
                target_player_id=received_match.group(4),
                target_player_name=received_match.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 8: Contract with arrow - "Contract Player1(ID) -> Player2(ID)"
        contract_arrow_match = re.search(
            r"Contract\s+([^(]+)\((\d+)\)\s*(?:->|→)\s*([^(]+)\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if contract_arrow_match:
            # Try to extract vehicle info after the last parenthesis
            remainder = text.split(")")[-1].strip() if ")" in text else ""
            vehicle_info = remainder.strip(".' ") if remainder else "Vehicle transfer"
            return PlayerAction(
                player_id=contract_arrow_match.group(2),
                player_name=contract_arrow_match.group(1).strip(),
                action_type="vehicle_contract",
                action_detail=f"Contract către {contract_arrow_match.group(3).strip()}: {vehicle_info}",
                item_name=vehicle_info if vehicle_info != "Vehicle transfer" else None,
                target_player_id=contract_arrow_match.group(4),
                target_player_name=contract_arrow_match.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 9: Contract with exchange details - "Contract Player1(ID) Player2(ID). ('ID1' [Item], 'ID2' [Money$"
        # Example: "Contract Cozeix(153455) anq790(222483). ('153455' [Brioso, ], '222483' [10.000.000$"
        contract_exchange_match = re.search(
            r"Contract\s+([^(]+)\((\d+)\)\s+([^(]+)\((\d+)\)\s*\.\s*\('(\d+)'\s*\[([^\]]*)\],?\s*'(\d+)'\s*\[([^\]]*)",
            text,
            re.IGNORECASE,
        )
        if contract_exchange_match:
            player1_name = contract_exchange_match.group(1).strip()
            player1_id = contract_exchange_match.group(2)
            player2_name = contract_exchange_match.group(3).strip()
            player2_id = contract_exchange_match.group(4)
            offer1_id = contract_exchange_match.group(5)
            offer1_items = contract_exchange_match.group(6).strip().rstrip(", ")
            offer2_id = contract_exchange_match.group(7)
            offer2_items = contract_exchange_match.group(8).strip().rstrip(", $")

            # Determine who gave what
            if offer1_id == player1_id:
                player1_gave = offer1_items or "items"
                player1_received = offer2_items or "items"
            else:
                player1_gave = offer2_items or "items"
                player1_received = offer1_items or "items"

            return PlayerAction(
                player_id=player1_id,
                player_name=player1_name,
                action_type="vehicle_contract",
                action_detail=f"Contract cu {player2_name}: Dat [{player1_gave}] → Primit [{player1_received}]",
                item_name=player1_gave,
                target_player_id=player2_id,
                target_player_name=player2_name,
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 9b: Simpler contract format - "Contract Player1(ID) Player2(ID)."
        contract_simple_match = re.search(
            r"Contract\s+([^(]+)\((\d+)\)\s+([^(]+)\((\d+)\)", text, re.IGNORECASE
        )
        if contract_simple_match:
            # Try to extract any details after
            remainder = text[contract_simple_match.end() :].strip()
            detail = remainder[:100] if remainder else "Vehicle transfer"
            return PlayerAction(
                player_id=contract_simple_match.group(2),
                player_name=contract_simple_match.group(1).strip(),
                action_type="vehicle_contract",
                action_detail=f"Contract cu {contract_simple_match.group(3).strip()}: {detail}",
                target_player_id=contract_simple_match.group(4),
                target_player_name=contract_simple_match.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 10: Warning received
        warning_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+primit\s+(?:un\s+)?avertisment.*?(?:administratorul|admin)\s+([^(]+)\((\d+)\).*?motiv:\s*(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if warning_match:
            return PlayerAction(
                player_id=warning_match.group(2),
                player_name=warning_match.group(1).strip(),
                action_type="warning_received",
                action_detail=f"Avertisment de la {warning_match.group(3).strip()}",
                admin_id=warning_match.group(4),
                admin_name=warning_match.group(3).strip(),
                reason=warning_match.group(5).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 11: Trade completed - "Tradeul dintre jucatorii Player1(ID) si Player2(ID) a fost finalizat"
        trade_match = re.search(
            r"Tradeul\s+dintre\s+jucatorii\s+([^(]+)\((\d+)\)\s+si\s+([^(]+)\((\d+)\)\s+a\s+fost\s+finalizat\.?\s*\(([^)]+)\)",
            text,
            re.IGNORECASE,
        )
        if trade_match:
            trade_details = trade_match.group(5)
            return PlayerAction(
                player_id=trade_match.group(2),
                player_name=trade_match.group(1).strip(),
                action_type="trade",
                action_detail=f"Trade cu {trade_match.group(3).strip()}: {trade_details}",
                target_player_id=trade_match.group(4),
                target_player_name=trade_match.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 12: Property bought/sold
        property_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+(cumparat|vandut)\s+(casa|afacere|proprietate)\s*(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if property_match:
            action_type = (
                "property_bought"
                if "cumparat" in property_match.group(3).lower()
                else "property_sold"
            )
            return PlayerAction(
                player_id=property_match.group(2),
                player_name=property_match.group(1).strip(),
                action_type=action_type,
                action_detail=f"{property_match.group(3)} {property_match.group(4)} {property_match.group(5).strip()}",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 13: Vehicle bought/sold (generic)
        vehicle_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+(cumparat|vandut)\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if vehicle_match:
            action_type = (
                "vehicle_bought"
                if "cumparat" in vehicle_match.group(3).lower()
                else "vehicle_sold"
            )
            return PlayerAction(
                player_id=vehicle_match.group(2),
                player_name=vehicle_match.group(1).strip(),
                action_type=action_type,
                action_detail=f"{vehicle_match.group(3)} {vehicle_match.group(4).strip()}",
                item_name=vehicle_match.group(4).strip().rstrip("."),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 14: Mute received - "a primit mute de la administratorul..."
        mute_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+primit\s+mute\s+de\s+la\s+administratorul\s+([^(]+)\((\d+)\)\s*,\s*motiv\s+(.+?)(?:,\s*timp|$)",
            text,
            re.IGNORECASE,
        )
        if mute_match:
            return PlayerAction(
                player_id=mute_match.group(2),
                player_name=mute_match.group(1).strip(),
                action_type="mute_received",
                action_detail=f"Mute de la {mute_match.group(3).strip()}: {mute_match.group(5).strip()}",
                admin_id=mute_match.group(4),
                admin_name=mute_match.group(3).strip(),
                reason=mute_match.group(5).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 15: Ban received - "a fost banat de catre adminul..."
        ban_match = re.search(
            r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+fost\s+banat\s+de\s+catre\s+admin(?:ul)?\s+([^(]+)\((\d+)\)\s*,\s*durata\s+(.+?)\s*,\s*motiv\s+['\"]?(.+?)['\"]?(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if ban_match:
            return PlayerAction(
                player_id=ban_match.group(2),
                player_name=ban_match.group(1).strip(),
                action_type="ban_received",
                action_detail=f"Ban de la {ban_match.group(3).strip()}: {ban_match.group(6).strip()} ({ban_match.group(5)})",
                admin_id=ban_match.group(4),
                admin_name=ban_match.group(3).strip(),
                reason=ban_match.group(6).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 16: Bank heist delivery - "a livrat bani de la banca(Bank (Location)) jefuita si a primit..."
        # Bank names have nested parentheses like "Fleeca Bank (Alta)" so we match up to "))"
        heist_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+livrat\s+bani\s+de\s+la\s+banca\s*\((.+?)\)\)\s*jefuita\s+si\s+a\s+primit\s+([\d.,]+)",
            text,
            re.IGNORECASE,
        )
        if heist_match:
            return PlayerAction(
                player_id=heist_match.group(2),
                player_name=heist_match.group(1).strip(),
                action_type="bank_heist_delivery",
                action_detail=f"Livrat bani de la {heist_match.group(3)}): {heist_match.group(4)}$",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 17: License plate sale - "Vanzarea de placute dintre jucatorii Player1(ID) si Player2(ID) a fost finalizata..."
        # More flexible pattern to handle various name formats
        plate_sale_match = re.search(
            r"Vanzarea\s+de\s+placute\s+dintre\s+jucatorii\s+(.+?)\((\d+)\)\s+si\s+(.+?)\((\d+)\)\s+a\s+fost\s+finalizata",
            text,
            re.IGNORECASE,
        )
        if plate_sale_match:
            player1_name = plate_sale_match.group(1).strip()
            player1_id = plate_sale_match.group(2)
            player2_name = plate_sale_match.group(3).strip()
            player2_id = plate_sale_match.group(4)

            # Try to extract plate number and vehicle from the rest of text
            plate_match = re.search(r"inmatriculare\s+\(([^)]+)\)", text)
            plate_number = plate_match.group(1) if plate_match else "?"

            vehicle_match = re.search(r"pe\s+vehiculul\s+([^,]+)", text)
            vehicle = vehicle_match.group(1).strip() if vehicle_match else "vehicul"

            # Find who gave the plate (the one mentioned in "[ID] Name a oferit")
            giver_match = re.search(r"\[(\d+)\]\s+([^\s]+)\s+a\s+oferit", text)
            if giver_match and giver_match.group(1) == player1_id:
                giver_id, giver_name = player1_id, player1_name
                receiver_id, receiver_name = player2_id, player2_name
            else:
                giver_id, giver_name = player2_id, player2_name
                receiver_id, receiver_name = player1_id, player1_name

            return PlayerAction(
                player_id=giver_id,
                player_name=giver_name,
                action_type="license_plate_sale",
                action_detail=f"Vândut plăcuță ({plate_number}) lui {receiver_name} pe {vehicle}",
                item_name=f"Plăcuță: {plate_number}",
                target_player_id=receiver_id,
                target_player_name=receiver_name,
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 18: Admin jail - "a primit admin jail X (de) checkpointuri de la administratorul..."
        jail_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+primit\s+admin\s+jail\s+(\d+)\s*(?:\(de\))?\s*checkpointuri\s+de\s+la\s+administratorul\s+(.+?)\((\d+)\)\s*,\s*motiv\s+['\"]?(.+?)['\"]?(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if jail_match:
            return PlayerAction(
                player_id=jail_match.group(2),
                player_name=jail_match.group(1).strip(),
                action_type="admin_jail",
                action_detail=f"Jail {jail_match.group(3)} CP de la {jail_match.group(4).strip()}: {jail_match.group(6).strip()}",
                admin_id=jail_match.group(5),
                admin_name=jail_match.group(4).strip(),
                reason=jail_match.group(6).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 19: Gambling win - "a castigat impotriva lui Player meciul de barbut/slots/etc"
        gambling_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+castigat\s+(?:impotriva\s+lui\s+)?(.+?)\((\d+)\)\s+(?:meciul\s+de\s+)?(\w+)[\s,]+(\d[\d.,]*)\$?",
            text,
            re.IGNORECASE,
        )
        if gambling_match:
            game_type = gambling_match.group(5)
            amount = gambling_match.group(6)
            return PlayerAction(
                player_id=gambling_match.group(2),
                player_name=gambling_match.group(1).strip(),
                action_type="gambling_win",
                action_detail=f"Câștigat {game_type} vs {gambling_match.group(3).strip()}: {amount}$",
                target_player_id=gambling_match.group(4),
                target_player_name=gambling_match.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 20: House safe withdrawal - "a retras suma de X$ din seiful casei nr. Y"
        house_safe_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+retras\s+suma\s+de\s+([\d.,]+)\$\s*din\s+seiful\s+casei\s+nr\.\s*(\d+)",
            text,
            re.IGNORECASE,
        )
        if house_safe_match:
            return PlayerAction(
                player_id=house_safe_match.group(2),
                player_name=house_safe_match.group(1).strip(),
                action_type="house_safe_withdraw",
                action_detail=f"Retras {house_safe_match.group(3)}$ din seif casa #{house_safe_match.group(4)}",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 21: House safe deposit - "a depozitat suma de X$ in seiful casei nr. Y"
        house_safe_deposit_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+depozitat\s+suma\s+de\s+([\d.,]+)\$\s*in\s+seiful\s+casei\s+nr\.\s*(\d+)",
            text,
            re.IGNORECASE,
        )
        if house_safe_deposit_match:
            return PlayerAction(
                player_id=house_safe_deposit_match.group(2),
                player_name=house_safe_deposit_match.group(1).strip(),
                action_type="house_safe_deposit",
                action_detail=f"Depozitat {house_safe_deposit_match.group(3)}$ in seif casa #{house_safe_deposit_match.group(4)}",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 22: Item sold (marketplace) - "[ID] Name a vandut xN Item pentru suma de $X"
        item_sold_match = re.search(
            r"\[(\d+)\]\s+([^\[]+?)\s+a\s+vandut\s+x?(\d+)\s+(.+?)\s+pentru\s+suma\s+de\s+\$?([\d.,]+)",
            text,
            re.IGNORECASE,
        )
        if item_sold_match:
            return PlayerAction(
                player_id=item_sold_match.group(1),
                player_name=item_sold_match.group(2).strip(),
                action_type="item_sold",
                action_detail=f"Vândut {item_sold_match.group(3)}x {item_sold_match.group(4).strip()} pentru {item_sold_match.group(5)}$",
                item_name=item_sold_match.group(4).strip(),
                item_quantity=int(item_sold_match.group(3)),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 23: Money transfer to "jucatorului" (different format) - "ia transferat suma de X$ jucatorului Name (ID)"
        transfer_alt_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+i?a\s+transferat\s+suma\s+de\s+([\d.,]+)\s*\$?\s*jucatorului\s+(.+?)\s+\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if transfer_alt_match:
            return PlayerAction(
                player_id=transfer_alt_match.group(2),
                player_name=transfer_alt_match.group(1).strip(),
                action_type="money_transfer",
                action_detail=f"Transferat {transfer_alt_match.group(3)}$ lui {transfer_alt_match.group(4).strip()}",
                target_player_id=transfer_alt_match.group(5),
                target_player_name=transfer_alt_match.group(4).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 24: Money transfer alt format 2 - "jucatorului Name(ID)" (no space before paren)
        transfer_alt2_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+i?a\s+transferat\s+suma\s+de\s+([\d.,]+)\s*\$?\s*jucatorului\s+(.+?)\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if transfer_alt2_match:
            return PlayerAction(
                player_id=transfer_alt2_match.group(2),
                player_name=transfer_alt2_match.group(1).strip(),
                action_type="money_transfer",
                action_detail=f"Transferat {transfer_alt2_match.group(3)}$ lui {transfer_alt2_match.group(4).strip()}",
                target_player_id=transfer_alt2_match.group(5),
                target_player_name=transfer_alt2_match.group(4).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 25: Vehicle scrapped/remated - "a dat la remat masina Vehicle(ID) pentru suma de X$"
        remat_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+dat\s+la\s+remat\s+masina\s+(.+?)\((\d+)\)\s+pentru\s+suma\s+de\s+([\d.,]+)\$",
            text,
            re.IGNORECASE,
        )
        if remat_match:
            return PlayerAction(
                player_id=remat_match.group(2),
                player_name=remat_match.group(1).strip(),
                action_type="vehicle_scrapped",
                action_detail=f"Remat {remat_match.group(3).strip()} pentru {remat_match.group(5)}$",
                item_name=remat_match.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 26: Kicked from faction - "a fost dat afara de catre Admin(ID), motiv..."
        kicked_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+fost\s+dat\s+afara\s+de\s+catre\s+(.+?)\((\d+)\)\s*,\s*motiv\s+['\"]?(.+?)['\"]?(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if kicked_match:
            return PlayerAction(
                player_id=kicked_match.group(2),
                player_name=kicked_match.group(1).strip(),
                action_type="faction_kicked",
                action_detail=f"Dat afară de {kicked_match.group(3).strip()}: {kicked_match.group(5).strip()}",
                admin_id=kicked_match.group(4),
                admin_name=kicked_match.group(3).strip(),
                reason=kicked_match.group(5).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 27: Unjail - "a primit unjail de la administratorul Admin(ID)"
        unjail_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+primit\s+unjail\s+de\s+la\s+administratorul\s+(.+?)\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if unjail_match:
            return PlayerAction(
                player_id=unjail_match.group(2),
                player_name=unjail_match.group(1).strip(),
                action_type="admin_unjail",
                action_detail=f"Unjail de la {unjail_match.group(3).strip()}",
                admin_id=unjail_match.group(4),
                admin_name=unjail_match.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 28: Warning alt format - "a primit un avertisment (X/3), de la administratorul"
        warning_alt_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+primit\s+un\s+avertisment\s+\((\d+)/3\)\s*,\s*de\s+la\s+administratorul\s+(.+?)\((\d+)\)\s*,\s*motiv\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if warning_alt_match:
            return PlayerAction(
                player_id=warning_alt_match.group(2),
                player_name=warning_alt_match.group(1).strip(),
                action_type="warning_received",
                action_detail=f"Avertisment ({warning_alt_match.group(3)}/3) de la {warning_alt_match.group(4).strip()}: {warning_alt_match.group(6).strip()}",
                warning_count=warning_alt_match.group(3),
                admin_id=warning_alt_match.group(5),
                admin_name=warning_alt_match.group(4).strip(),
                reason=warning_alt_match.group(6).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 29: Item given to ID only (no name) - "ia dat lui (ID) Nx Item"
        gave_id_only_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+i?a\s+dat\s+lui\s+\((\d+)\)\s+(\d+)x\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if gave_id_only_match:
            return PlayerAction(
                player_id=gave_id_only_match.group(2),
                player_name=gave_id_only_match.group(1).strip(),
                action_type="item_given",
                action_detail=f"Dat lui ID:{gave_id_only_match.group(3)}: {gave_id_only_match.group(4)}x {gave_id_only_match.group(5).strip()}",
                item_name=gave_id_only_match.group(5).strip().rstrip("."),
                item_quantity=int(gave_id_only_match.group(4)),
                target_player_id=gave_id_only_match.group(3),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 30: Item given with nested parentheses in name - handles "! Name (tag)(ID)"
        # Example: "ia dat lui ! Montana (585)(160273) 2x Armura"
        gave_nested_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+i?a\s+dat\s+lui\s+(.+?)\((\d+)\)\s+(\d+)x\s+(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if gave_nested_match:
            return PlayerAction(
                player_id=gave_nested_match.group(2),
                player_name=gave_nested_match.group(1).strip(),
                action_type="item_given",
                action_detail=f"Dat lui {gave_nested_match.group(3).strip()}: {gave_nested_match.group(5)}x {gave_nested_match.group(6).strip()}",
                item_name=gave_nested_match.group(6).strip().rstrip("."),
                item_quantity=int(gave_nested_match.group(5)),
                target_player_id=gave_nested_match.group(4),
                target_player_name=gave_nested_match.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # ============================================================================
        # NEW PATTERNS: Handle edge cases from /unknownactions report
        # ============================================================================

        # 🔥 NEW PATTERN A: Bank heist with SIMPLE bank name (no nested parens)
        # Example: "Jucatorul iBuyPower Aleksey(152166) a livrat bani de la banca(Blaine County Savings) jefuita si a primit 14.728.305 bani murdari si 1x Moneda sindicat."
        heist_simple_match = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+livrat\s+bani\s+de\s+la\s+banca\s*\(([^)]+)\)\s*jefuita\s+si\s+a\s+primit\s+([\d.,]+)\s*bani\s+murdari",
            text,
            re.IGNORECASE,
        )
        if heist_simple_match:
            return PlayerAction(
                player_id=heist_simple_match.group(2),
                player_name=heist_simple_match.group(1).strip(),
                action_type="bank_heist_delivery",
                action_detail=f"Livrat bani de la {heist_simple_match.group(3)}: {heist_simple_match.group(4)} bani murdari",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN B: Money withdrawal with nested parentheses in name
        # Example: "Jucatorul King pt voi ! (fotomodelu)(218539) a retras suma de 422.779$ (taxa 4.227$)."
        # The key is to match the LAST (ID) before " a retras"
        withdraw_nested_name = re.search(
            r"Jucatorul\s+(.+)\((\d+)\)\s+a\s+retras\s+suma\s+de\s+([\d.,]+)\$\s*\(taxa\s+([\d.,]+)\$\)",
            text,
            re.IGNORECASE,
        )
        if withdraw_nested_name:
            return PlayerAction(
                player_id=withdraw_nested_name.group(2),
                player_name=withdraw_nested_name.group(1).strip(),
                action_type="money_withdraw",
                action_detail=f"Retras {withdraw_nested_name.group(3)}$ (taxa {withdraw_nested_name.group(4)}$)",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN C: ID-only ban - "Jucatorul (ID) a fost banat..."
        # Example: "Jucatorul (224833) a fost banat de catre adminul Fane(300), durata 1 (de) zi(le), motiv 'Blacklist'."
        ban_id_only_match = re.search(
            r"Jucatorul\s+\((\d+)\)\s+a\s+fost\s+banat\s+de\s+catre\s+admin(?:ul)?\s+(.+?)\((\d+)\)\s*,\s*durata\s+(.+?)\s*,\s*motiv\s+['\"]?(.+?)['\"]?(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if ban_id_only_match:
            return PlayerAction(
                player_id=ban_id_only_match.group(1),
                player_name=None,
                action_type="ban_received",
                action_detail=f"Ban de la {ban_id_only_match.group(2).strip()}: {ban_id_only_match.group(5).strip()} ({ban_id_only_match.group(4)})",
                admin_id=ban_id_only_match.group(3),
                admin_name=ban_id_only_match.group(2).strip(),
                reason=ban_id_only_match.group(5).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN D: Admin warning removal - "Administratorul Name(ID) ia scos un avertisment jucatorului Name(ID)"
        # Example: "Administratorul Tipic(184) ia scos un avertisment jucatorului defuse (199104)."
        warning_removal_match = re.search(
            r"Administratorul\s+(.+?)\((\d+)\)\s+i?a\s+scos\s+un\s+avertisment\s+jucatorului\s+(.+?)\s*\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if warning_removal_match:
            return PlayerAction(
                player_id=warning_removal_match.group(4),
                player_name=warning_removal_match.group(3).strip(),
                action_type="warning_removed",
                action_detail=f"Avertisment scos de {warning_removal_match.group(1).strip()}",
                admin_id=warning_removal_match.group(2),
                admin_name=warning_removal_match.group(1).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN E: Money transfer with fancy names (tags in parens) - NO "Jucatorul" prefix
        # Example: "King pt voi ! (fotomodelu) (218539) ia transferat suma de 500.000 (de) $ lui Alina (126059) [IN MANA]"
        # Handles both with space and without space after "lui" for email-like targets
        transfer_fancy_name = re.search(
            r"^(.+?)\s+\((\d+)\)\s+i?a\s+transferat\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$?\s*lui\s*([^\s(]+(?:\s+[^(]*)?|[^\s(]+@[^\s(]+)\s*\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if transfer_fancy_name:
            target_name = transfer_fancy_name.group(4).strip()
            return PlayerAction(
                player_id=transfer_fancy_name.group(2),
                player_name=transfer_fancy_name.group(1).strip(),
                action_type="money_transfer",
                action_detail=f"Transferat {transfer_fancy_name.group(3)}$ lui {target_name}",
                target_player_id=transfer_fancy_name.group(5),
                target_player_name=target_name,
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN E: Money transfer with ID-ONLY sender - "(ID) ia transferat..."
        # Example: "(76985) ia transferat suma de 94.226 (de) $ lui VARZARU (223077) [IN MANA]"
        transfer_id_only_sender = re.search(
            r"^\((\d+)\)\s+i?a\s+transferat\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$?\s*lui\s+(.+?)\s*\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if transfer_id_only_sender:
            return PlayerAction(
                player_id=transfer_id_only_sender.group(1),
                player_name=None,
                action_type="money_transfer",
                action_detail=f"Transferat {transfer_id_only_sender.group(2)}$ lui {transfer_id_only_sender.group(3).strip()}",
                target_player_id=transfer_id_only_sender.group(4),
                target_player_name=transfer_id_only_sender.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # ============================================================================
        # FALLBACK PATTERNS - Moved to end so specific patterns are checked first
        # ============================================================================

        # 🔥 NEW PATTERN F: Contract with email-like names - handles "email@domain(ID)" format
        # Example: "Contract[email protected](137592) Mihai(137922). ('137592' [Bravado Harger 69, ], '137922' [])"
        contract_email_name = re.search(
            r"Contract\s+([^\s(]+@[^\s(]+)\((\d+)\)\s+(.+?)\((\d+)\)\.",
            text,
            re.IGNORECASE,
        )
        if contract_email_name:
            return PlayerAction(
                player_id=contract_email_name.group(2),
                player_name=contract_email_name.group(1),
                action_type="vehicle_contract",
                action_detail=f"Contract cu {contract_email_name.group(3).strip()}: Vehicle transfer",
                target_player_id=contract_email_name.group(4),
                target_player_name=contract_email_name.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN G: Bank heist with fancy player names (with tags)
        # Example: "Jucatorul King pt voi ! (fotomodelu)(218539) a livrat bani de la banca(Blaine County Savings)"
        heist_fancy_name = re.search(
            r"Jucatorul\s+(.+)\((\d+)\)\s+a\s+livrat\s+bani\s+de\s+la\s+banca\s*\(([^)]+)\)\s*jefuita\s+si\s+a\s+primit\s+([\d.,]+)\s*bani\s+murdari",
            text,
            re.IGNORECASE,
        )
        if heist_fancy_name:
            return PlayerAction(
                player_id=heist_fancy_name.group(2),
                player_name=heist_fancy_name.group(1).strip(),
                action_type="bank_heist_delivery",
                action_detail=f"Livrat bani de la {heist_fancy_name.group(3)}: {heist_fancy_name.group(4)} bani murdari",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN H: Money deposit by email-like username (no space before paren)
        # Example: "Jucatorul[email protected](137592) a depozitat suma de 61.000.000$ (taxa 610.000$)."
        deposit_email = re.search(
            r"Jucatorul\s*([^\s(]+@[^\s(]+)\((\d+)\)\s+a\s+depozitat\s+suma\s+de\s+([\d.,]+)\$\s*\(taxa\s+([\d.,]+)\$\)",
            text,
            re.IGNORECASE,
        )
        if deposit_email:
            return PlayerAction(
                player_id=deposit_email.group(2),
                player_name=deposit_email.group(1),
                action_type="money_deposit",
                action_detail=f"Depozitat {deposit_email.group(3)}$ (taxa {deposit_email.group(4)}$)",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN I: Money transfer with email-like username
        # Handles both bracketed [email@protected] and normal email@protected formats
        # Example: "Mihai (137922) ia transferat suma de 7.500.000 (de) $ lui[email protected](137592) [IN MANA]"
        transfer_email_target = re.search(
            r"^(.+?)\s+\((\d+)\)\s+i?a\s+transferat\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$?\s*lui\s*(\[[^\]]+\]|[^\s(]+@[^\s(]+)\s*\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if transfer_email_target:
            email_name = transfer_email_target.group(4).strip(
                "[]"
            )  # Remove brackets if present
            return PlayerAction(
                player_id=transfer_email_target.group(2),
                player_name=transfer_email_target.group(1).strip(),
                action_type="money_transfer",
                action_detail=f"Transferat {transfer_email_target.group(3)}$ lui {email_name}",
                target_player_id=transfer_email_target.group(5),
                target_player_name=email_name,
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN J: Trade with detailed exchange info (already somewhat covered but with better parsing)
        # Example: "Tradeul dintre jucatorii Chirila(373) si (136629) a fost finalizat. ('373' [1x Sandwich Cu Sunca, ], '136629' [90.000.000$, ])"
        trade_detailed = re.search(
            r"Tradeul\s+dintre\s+jucatorii\s+([^(]+)\((\d+)\)\s+si\s+([^(]*)\((\d+)\)\s+a\s+fost\s+finalizat",
            text,
            re.IGNORECASE,
        )
        if trade_detailed:
            player1_name = trade_detailed.group(1).strip()
            player1_id = trade_detailed.group(2)
            player2_name = (
                trade_detailed.group(3).strip()
                if trade_detailed.group(3).strip()
                else None
            )
            player2_id = trade_detailed.group(4)

            # Extract what was exchanged from the detail part if present
            exchange_detail = ""
            exchange_match = re.findall(r"'(\d+)'\s*\[([^\]]+)\]", text)
            if exchange_match:
                for ex_id, ex_items in exchange_match:
                    if ex_id == player1_id:
                        exchange_detail = f"Gave: {ex_items.strip().rstrip(', ')}"
                        break

            return PlayerAction(
                player_id=player1_id,
                player_name=player1_name,
                action_type="trade",
                action_detail=f"Trade cu {player2_name or 'ID:' + player2_id}: {exchange_detail}",
                target_player_id=player2_id,
                target_player_name=player2_name,
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN E: Money transfer with ID-ONLY sender - "(ID) ia transferat..."
        # Example: "(76985) ia transferat suma de 94.226 (de) $ lui VARZARU (223077) [IN MANA]"
        transfer_id_only_sender = re.search(
            r"^\((\d+)\)\s+i?a\s+transferat\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$?\s*lui\s+(.+?)\s*\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if transfer_id_only_sender:
            return PlayerAction(
                player_id=transfer_id_only_sender.group(1),
                player_name=None,
                action_type="money_transfer",
                action_detail=f"Transferat {transfer_id_only_sender.group(2)}$ lui {transfer_id_only_sender.group(3).strip()}",
                target_player_id=transfer_id_only_sender.group(4),
                target_player_name=transfer_id_only_sender.group(3).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN K: House/Property purchase
        # Example: "Jucatorul Ioan Glont(56894) a achizictionat Casa Nr. 95 de la jucatorul cu ID 173608 pentru suma de 500.000.000$."
        property_purchase = re.search(
            r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+achizit?ionat\s+(.+?)\s+de\s+la\s+jucatorul\s+cu\s+ID\s+(\d+)\s+pentru\s+suma\s+de\s+([\d.,]+)\$",
            text,
            re.IGNORECASE,
        )
        if property_purchase:
            return PlayerAction(
                player_id=property_purchase.group(2),
                player_name=property_purchase.group(1).strip(),
                action_type="property_bought",
                action_detail=f"a achizitionat {property_purchase.group(3)}: {property_purchase.group(5)}$ de la ID {property_purchase.group(4)}",
                target_player_id=property_purchase.group(4),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN L: Faction kick/expulsion
        # Example: "Jucatorul (149788) a fost dat afara de catre NepotuP4K(2446), motiv 'schimba numele'."
        faction_kick = re.search(
            r"Jucatorul\s+(?:(.+?)\s+)?\((\d+)\)\s+a\s+fost\s+dat\s+afara\s+de\s+catre\s+(.+?)\((\d+)\)\s*,\s*motiv\s+['\"]([^'\"]+)['\"]",
            text,
            re.IGNORECASE,
        )
        if faction_kick:
            return PlayerAction(
                player_id=faction_kick.group(2),
                player_name=faction_kick.group(1),
                action_type="faction_kicked",
                action_detail=f"dat afara de {faction_kick.group(3).strip()}: {faction_kick.group(5)}",
                admin_id=faction_kick.group(4),
                admin_name=faction_kick.group(3).strip(),
                reason=faction_kick.group(5),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN M: Admin warning removal (slightly different format)
        # Example: "Administratorul Tipic(184) ia scos un avertisment jucatorului defuse (199104)."
        admin_warning = re.search(
            r"Administratorul\s+(.+?)\((\d+)\)\s+i?a\s+scos\s+un\s+avertisment\s+jucatorului\s+(.+?)\s*\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if admin_warning:
            return PlayerAction(
                player_id=admin_warning.group(4),
                player_name=admin_warning.group(3).strip(),
                action_type="warning_removed",
                action_detail=f"Avertisment scos de {admin_warning.group(1).strip()}",
                admin_id=admin_warning.group(2),
                admin_name=admin_warning.group(1).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN N: Vehicle contract - simple format
        # Example: "Contract Mihai(137922) (137592). ('137922' [], '137592' [Bravado Harger 69, ])"
        contract_simple = re.search(
            r"Contract\s+(.+?)\((\d+)\)\s+\((\d+)\)\.", text, re.IGNORECASE
        )
        if contract_simple:
            return PlayerAction(
                player_id=contract_simple.group(2),
                player_name=contract_simple.group(1).strip(),
                action_type="vehicle_contract",
                action_detail=f"Contract cu ID {contract_simple.group(3)}: Vehicle transfer",
                target_player_id=contract_simple.group(3),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN O: Trade with minimal info (player IDs only)
        # Example: "Tradeul dintre jucatorii D4N1(202518) si sasuke (192)(209261) a fost finalizat..."
        # This handles cases where second player has a tag like "sasuke (192)"
        trade_with_tag = re.search(
            r"Tradeul\s+dintre\s+jucatorii\s+([^(]+)\((\d+)\)\s+si\s+([^(]+)\s*(?:\(\d+\))?\s*\((\d+)\)\s+a\s+fost\s+finalizat",
            text,
            re.IGNORECASE,
        )
        if trade_with_tag:
            player1_name = trade_with_tag.group(1).strip()
            player1_id = trade_with_tag.group(2)
            player2_name_raw = trade_with_tag.group(3).strip()
            # Remove any trailing tag like " (192)" from player2 name
            player2_name = re.sub(r"\s*\(\d+\)\s*$", "", player2_name_raw).strip()
            player2_id = trade_with_tag.group(4)

            return PlayerAction(
                player_id=player1_id,
                player_name=player1_name,
                action_type="trade",
                action_detail=f"Trade cu {player2_name}",
                target_player_id=player2_id,
                target_player_name=player2_name,
                timestamp=timestamp,
                raw_text=text,
            )

        # This pattern is now handled by the improved transfer_fancy_name pattern above

        # 🔥 NEW PATTERN Q: Deposit with email-style username (no space before parenthesis)
        # Handles both bracketed [email@protected] and normal email@protected formats
        # Example: "Jucatorul[email protected](137592) a depozitat suma de 61.000.000$ (taxa 610.000$)."
        deposit_email_nospace = re.search(
            r"Jucatorul\s*(\[[^\]]+\]|[^\s(]+@[^\s(]+)\((\d+)\)\s+a\s+depozitat\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$\s*\(taxa\s+([\d.,]+)\$\)",
            text,
            re.IGNORECASE,
        )
        if deposit_email_nospace:
            email_name = deposit_email_nospace.group(1).strip(
                "[]"
            )  # Remove brackets if present
            return PlayerAction(
                player_id=deposit_email_nospace.group(2),
                player_name=email_name,
                action_type="money_deposit",
                action_detail=f"Depozitat {deposit_email_nospace.group(3)}$ (taxa {deposit_email_nospace.group(4)}$)",
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN R: Contract with email-style player name (simpler approach)
        # Handles both: "Contract[email protected](ID) Name(ID)" and "Contract Name(ID)[email@domain](ID)"
        #  Also handles bracketed [email@domain], normal email@domain, and regular names
        # Example: "Contract[email protected](137592) Mihai(137922)." or "Contract Mihai(137922)[email protected](137592)."
        contract_email_simple = re.search(
            r"Contract\s*(.+?)\((\d+)\)\s*(\[[^\]]+\]|[^\s(]+@[^\s(]+|[\w\s]+)?\s*\((\d+)\)",
            text,
            re.IGNORECASE,
        )
        if contract_email_simple:
            player1_name = (
                contract_email_simple.group(1).strip().strip("[]")
                if contract_email_simple.group(1)
                else None
            )
            player1_id = contract_email_simple.group(2)
            player2_name_or_email = contract_email_simple.group(3)
            player2_id = contract_email_simple.group(4)

            # If player2_name_or_email is None, it might be just "(ID)" after player1
            if player2_name_or_email:
                player2_name = player2_name_or_email.strip().strip("[]")
            else:
                player2_name = None

            return PlayerAction(
                player_id=player1_id,
                player_name=player1_name,
                action_type="vehicle_contract",
                action_detail=f"Contract cu {player2_name or 'ID:'+player2_id}: Vehicle transfer",
                target_player_id=player2_id,
                target_player_name=player2_name,
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 NEW PATTERN S: Contract with ID-only first player
        # Example: "Contract (131960) Crissu(168172). ('131960' [Issi Weeny XC, ], '168172' [])"
        contract_idonly_first = re.search(
            r"Contract\s+\((\d+)\)\s+(.+?)\((\d+)\)(?:\.|$)", text, re.IGNORECASE
        )
        if contract_idonly_first:
            # Extract exchange details if present
            exchange_detail = ""
            exchange_match = re.findall(r"'(\d+)'\s*\[([^\]]*)\]", text)
            if exchange_match and contract_idonly_first.group(1) in [
                ex[0] for ex in exchange_match
            ]:
                for ex_id, ex_items in exchange_match:
                    if ex_id == contract_idonly_first.group(1):
                        exchange_detail = f"Gave: {ex_items.strip().rstrip(', ')}"
                        break

            return PlayerAction(
                player_id=contract_idonly_first.group(1),
                player_name=None,
                action_type="vehicle_contract",
                action_detail=f"Contract cu {contract_idonly_first.group(2).strip()}: {exchange_detail or 'Vehicle transfer'}",
                target_player_id=contract_idonly_first.group(3),
                target_player_name=contract_idonly_first.group(2).strip(),
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 31: Any "Jucatorul" action not matched above - use GREEDY name match
        # This is now placed AFTER all specific patterns so they have priority
        # Changed from [^(]+ to .+ to handle names with parentheses like "King pt voi ! (tag)"
        generic_match = re.search(
            r"Jucatorul\s+(.+)\((\d+)\)\s+(.+?)(?:\.|$)", text, re.IGNORECASE
        )
        if generic_match:
            action_text = generic_match.group(3).strip()
            return PlayerAction(
                player_id=generic_match.group(2),
                player_name=generic_match.group(1).strip(),
                action_type="other",
                action_detail=action_text[:200],
                timestamp=timestamp,
                raw_text=text,
            )

        # 🔥 PATTERN 34: CATCH-ALL - Save ANY action text even if no patterns match
        if len(text) >= 10:
            logger.debug(
                f"⚠️ Unrecognized action pattern saved as 'unknown': {text[:80]}..."
            )
            return PlayerAction(
                player_id=None,
                player_name=None,
                action_type="unknown",
                action_detail=text[:200],
                timestamp=timestamp,
                raw_text=text,
            )

        return None

    def parse_action_entry(self, entry) -> Optional[PlayerAction]:
        """🔥 FIXED: Enhanced action parser with correct patterns for 'ia dat lui' and chest actions"""
        try:
            text = entry.get_text(strip=True)
            if not text or len(text) < 15:
                return None

            text = " ".join(text.split())

            timestamp_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
            timestamp = datetime.now()
            if timestamp_match:
                try:
                    timestamp = datetime.strptime(
                        timestamp_match.group(1), "%Y-%m-%d %H:%M:%S"
                    )
                except:
                    pass

            # Warning pattern
            warning_match = re.search(
                r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+primit\s+un\s+avertisment,\s+de\s+la\s+administratorul\s+([^(]+)\((\d+)\)\s*,\s*motiv:\s*(.+?)(?=\d{4}-\d{2}-\d{2}|$)",
                text,
                re.IGNORECASE,
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
                    raw_text=text,
                )

            # 🔥 FIXED: Chest withdraw pattern - matches "a retras din chest"
            chest_withdraw_match = re.search(
                r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+retras\s+din\s+chest\s*\(id\s+([^)]+)\)\s*,\s*(\d+)x\s+(.+?)(?=\d{4}-\d{2}-\d{2}|Jucatorul|$)",
                text,
                re.IGNORECASE,
            )
            if chest_withdraw_match:
                chest_id = chest_withdraw_match.group(3)
                quantity = chest_withdraw_match.group(4)
                item_name = chest_withdraw_match.group(5).strip().rstrip(".")

                return PlayerAction(
                    player_id=chest_withdraw_match.group(2),
                    player_name=chest_withdraw_match.group(1).strip(),
                    action_type="chest_withdraw",
                    action_detail=f"a retras din chest(id {chest_id}), {quantity}x {item_name}.",
                    item_name=item_name,
                    item_quantity=int(quantity),
                    timestamp=timestamp,
                    raw_text=text,
                )

            # FIXED: Chest deposit pattern - matches "pus in chest"
            chestdepositmatch = re.search(
                r"Jucatorul\s+([^\(]+)\((\d+)\)\s+a\s+pus\s+in\s+chest\s+#(\d+),\s+x(\d+)\s+(.+?)\.\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+Jucatorul",
                text,
                re.IGNORECASE,
            )
            if chestdepositmatch:
                chestid = chestdepositmatch.group(3)
                quantity = chestdepositmatch.group(4)
                itemname = chestdepositmatch.group(5).strip().rstrip(".")
                return PlayerAction(
                    player_id=chestdepositmatch.group(2),
                    player_name=chestdepositmatch.group(1).strip(),
                    action_type="chest_deposit",
                    action_detail=f"pus in chest #{chestid}, {quantity}x {itemname}.",
                    item_name=itemname,
                    item_quantity=int(quantity),
                    timestamp=timestamp,
                    raw_text=text,
                )

            # FIXED: Chest withdraw pattern - matches a retras din chest
            # Consolidated pattern with lookahead to handle both with and without trailing period
            chestwithdrawmatch = re.search(
                r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+retras\s+din\s+chest\(id\s+([^)]+)\),\s+(\d+)x\s+(.+?)(?:\.(?=\s|$)|(?=\d{4}-\d{2}-\d{2}|Jucatorul|$))",
                text,
                re.IGNORECASE,
            )
            if chestwithdrawmatch:
                chestid = chestwithdrawmatch.group(3)
                quantity = chestwithdrawmatch.group(4)
                itemname = chestwithdrawmatch.group(5).strip().rstrip(".")
                return PlayerAction(
                    player_id=chestwithdrawmatch.group(2),
                    player_name=chestwithdrawmatch.group(1).strip(),
                    action_type="chest_withdraw",
                    action_detail=f"a retras din chest(id {chestid}), {quantity}x {itemname}.",
                    item_name=itemname,
                    item_quantity=int(quantity),
                    timestamp=timestamp,
                    raw_text=text,
                )

            # Item received pattern
            receivedmatch = re.search(
                r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+primit\s+de\s+la\s+([^(]+)\((\d+)\)\s+(\d+)x\s+(.+?)\.",
                text,
                re.IGNORECASE,
            )
            if receivedmatch:
                return PlayerAction(
                    player_id=receivedmatch.group(2),
                    player_name=receivedmatch.group(1).strip(),
                    action_type="item_received",
                    action_detail=f"Primit {receivedmatch.group(6).strip()} de la {receivedmatch.group(3).strip()}",
                    item_name=receivedmatch.group(6).strip(),
                    item_quantity=int(receivedmatch.group(5)),
                    target_player_id=receivedmatch.group(4),
                    target_player_name=receivedmatch.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text,
                )

            # FIXED: Item given pattern - matches i-a dat lui not a dat lui
            gavematch = re.search(
                r"Jucatorul\s+([^(]+)\((\d+)\)\s+i-a\s+dat\s+lui\s+([^(]+)\((\d+)\)\s+(.+?)\.",
                text,
                re.IGNORECASE,
            )
            if gavematch:
                itemstext = gavematch.group(5).strip()
                itemstext = itemstext.lstrip(",")
                return PlayerAction(
                    player_id=gavematch.group(2),
                    player_name=gavematch.group(1).strip(),
                    action_type="item_given",
                    action_detail=f"i-a dat lui {gavematch.group(3).strip()}({gavematch.group(4)}) {itemstext}",
                    item_name=itemstext,
                    item_quantity=None,
                    target_player_id=gavematch.group(4),
                    target_player_name=gavematch.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text,
                )

            # Property pattern
            propertymatch = re.search(
                r"Jucatorul\s+([^(]+)\((\d+)\)\s+(a\s+cumparat|a\s+vandut)\s+(casa|afacere|proprietate)(.+?)\.",
                text,
                re.IGNORECASE,
            )
            if propertymatch:
                actiontype = (
                    "property_bought"
                    if "cumparat" in propertymatch.group(3).lower()
                    else "property_sold"
                )
                return PlayerAction(
                    player_id=propertymatch.group(2),
                    player_name=propertymatch.group(1).strip(),
                    action_type=actiontype,
                    action_detail=f"{propertymatch.group(3)} {propertymatch.group(4)}",
                    timestamp=timestamp,
                    raw_text=text,
                )

            # Vehicle pattern
            vehiclematch = re.search(
                r"Jucatorul\s+([^(]+)\((\d+)\)\s+(a\s+cumparat|a\s+vandut)(.+?)\.",
                text,
                re.IGNORECASE,
            )
            if vehiclematch:
                actiontype = (
                    "vehicle_bought"
                    if "cumparat" in vehiclematch.group(3).lower()
                    else "vehicle_sold"
                )
                return PlayerAction(
                    player_id=vehiclematch.group(2),
                    player_name=vehiclematch.group(1).strip(),
                    action_type=actiontype,
                    action_detail=vehiclematch.group(4).strip(),
                    timestamp=timestamp,
                    raw_text=text,
                )

            # Contract pattern for vehicle transfers
            contractmatch = re.search(
                r"Contract\s+([^(]+)\((\d+)\)\s+->\s+([^(]+)\((\d+)\)",
                text,
                re.IGNORECASE,
            )
            if contractmatch:
                fromname = contractmatch.group(1).strip()
                fromid = contractmatch.group(2)
                toname = contractmatch.group(3).strip()
                toid = contractmatch.group(4)

                vehiclematch = re.search(r"(.+?)\.", text)
                vehicleinfo = vehiclematch.group(1) if vehiclematch else "Vehicle"

                return PlayerAction(
                    player_id=fromid,
                    player_name=fromname,
                    action_type="contract",
                    action_detail=f"Contract with {toname}({toid}) {vehicleinfo}",
                    item_name=vehicleinfo,
                    item_quantity=None,
                    target_player_id=toid,
                    target_player_name=toname,
                    timestamp=timestamp,
                    raw_text=text,
                )

            # Warning pattern
            warningmatch = re.search(
                r"Jucatorul\s+([^(]+)\((\d+)\)\s+a\s+primit\s+un\s+avertisment\s+de\s+la\s+administratorul\s+([^(]+)\((\d+)\)\s*,\s*motiv:\s*(.+?)(?=\d{4}-\d{2}-\d{2}|$)",
                text,
                re.IGNORECASE,
            )
            if warningmatch:
                return PlayerAction(
                    player_id=warningmatch.group(2),
                    player_name=warningmatch.group(1).strip(),
                    action_type="warning_received",
                    action_detail=f"Avertisment de la {warningmatch.group(3).strip()}",
                    admin_id=warningmatch.group(4),
                    admin_name=warningmatch.group(3).strip(),
                    warning_count=None,
                    reason=warningmatch.group(5).strip(),
                    timestamp=timestamp,
                    raw_text=text,
                )

            # OTHER - Admin jail pattern
            if "admin jail" in text.lower():
                adminjailmatch = re.search(
                    r"a\s+primit\s+admin\s+jail\s+(.+?)\s+checkpoints.+?administratorul\s+([^(]+)\((\d+)\)\s*,\s*motiv:\s*(.+?)\.",
                    text,
                    re.IGNORECASE,
                )
                if adminjailmatch:
                    playermatch = re.search(
                        r"Jucatorul\s+([^(]+)\((\d+)\)", text, re.IGNORECASE
                    )
                    if playermatch:
                        return PlayerAction(
                            player_id=playermatch.group(2),
                            player_name=playermatch.group(1).strip(),
                            action_type="admin_jail",
                            action_detail=f"Admin jail {adminjailmatch.group(1)} checkpoints, reason: {adminjailmatch.group(4)}",
                            admin_id=adminjailmatch.group(3),
                            admin_name=adminjailmatch.group(2).strip(),
                            reason=adminjailmatch.group(4),
                            timestamp=timestamp,
                            raw_text=text,
                        )

            # Fallback for unmatched jucatorul mentions
            if "jucatorul" in text.lower():
                return PlayerAction(
                    player_id=None,
                    player_name=None,
                    action_type="unknown",
                    action_detail=text[:200],
                    timestamp=timestamp,
                    raw_text=text,
                )

            return None

        except Exception as e:
            logger.error(
                f"Error parsing action: {e}, Text: {text[:100] if text else 'NA'}"
            )
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

    async def get_vip_actions(
        self, vip_ids: Set[str], limit: int = 200
    ) -> List[PlayerAction]:
        """Get latest actions filtered for VIP players only"""
        all_actions = await self.get_latest_actions(limit)
        vip_actions = [
            action for action in all_actions if self.is_vip_action(action, vip_ids)
        ]
        logger.info(
            f"Found {len(vip_actions)} VIP actions out of {len(all_actions)} total"
        )
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

    async def get_online_player_actions(
        self, online_ids: Set[str], limit: int = 200
    ) -> List[PlayerAction]:
        """Get latest actions filtered for currently online players only"""
        all_actions = await self.get_latest_actions(limit)
        online_actions = [
            action
            for action in all_actions
            if self.is_online_action(action, online_ids)
        ]
        logger.info(
            f"Found {len(online_actions)} online player actions out of {len(all_actions)} total"
        )
        return online_actions

    async def get_online_players(self) -> List[Dict]:
        """Get all online players with pagination"""
        all_players = []
        page = 1

        while True:
            url = (
                f"{self.base_url}/online?pageOnline={page}"
                if page > 1
                else f"{self.base_url}/online"
            )
            logger.info(f"Fetching online players page {page}...")

            html = await self.fetch_page(url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")
            player_rows = soup.select("table tr, .player-row, .online-player")

            if not player_rows or len(player_rows) <= 1:
                break

            page_players = []
            for row in player_rows[1:]:
                try:
                    link = row.select_one('a[href*="/profile/"]')
                    if link:
                        href = link.get("href", "")
                        id_match = re.search(r"/profile/(\d+)", href)
                        if id_match:
                            player_id = id_match.group(1)
                            player_name = link.get_text(strip=True)
                            page_players.append(
                                {
                                    "player_id": player_id,
                                    "player_name": player_name,
                                    "is_online": True,
                                    "last_seen": datetime.now(),
                                }
                            )

                    if not link:
                        cells = row.select("td")
                        if len(cells) >= 2:
                            player_id = cells[0].get_text(strip=True)
                            player_name = cells[1].get_text(strip=True)
                            if player_id.isdigit():
                                page_players.append(
                                    {
                                        "player_id": player_id,
                                        "player_name": player_name,
                                        "is_online": True,
                                        "last_seen": datetime.now(),
                                    }
                                )

                except Exception as e:
                    logger.error(f"Error parsing player row: {e}")
                    continue

            if not page_players:
                break

            all_players.extend(page_players)
            logger.info(
                f"Found {len(page_players)} players on page {page} (total: {len(all_players)})"
            )

            next_link = soup.select_one(f'a[href*="pageOnline={page + 1}"]')
            if not next_link:
                break

            page += 1
            await asyncio.sleep(0.5)

        logger.info(f"Total online players found: {len(all_players)}")
        return all_players

    async def get_banned_players(self) -> List[Dict]:
        """Get banned players from banlist (first page only - legacy)"""
        url = f"{self.base_url}/banlist"
        html = await self.fetch_page(url)

        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        banned = []

        ban_rows = soup.select("table tr, .ban-row, .banned-player")
        for row in ban_rows[1:]:
            try:
                cells = row.select("td")
                if len(cells) >= 6:
                    player_link = cells[1].select_one('a[href*="/profile/"]')
                    player_id = None
                    if player_link:
                        href = player_link.get("href", "")
                        id_match = re.search(r"/profile/(\d+)", str(href))
                        if id_match:
                            player_id = id_match.group(1)

                    banned.append(
                        {
                            "player_id": player_id or cells[0].get_text(strip=True),
                            "player_name": cells[1].get_text(strip=True),
                            "admin": cells[2].get_text(strip=True),
                            "reason": cells[3].get_text(strip=True),
                            "duration": cells[4].get_text(strip=True),
                            "ban_date": cells[5].get_text(strip=True),
                            "expiry_date": cells[6].get_text(strip=True)
                            if len(cells) > 6
                            else None,
                        }
                    )

            except Exception as e:
                logger.error(f"Error parsing ban row: {e}")
                continue

        return banned

    async def get_banned_players_all_pages(self) -> List[Dict]:
        """🆕 Get ALL banned players from ALL pages with played_hours and faction

        🔥 ENHANCED: Uses cloudscraper to bypass JavaScript challenge on banlist pages

        Iterates through https://panel.pro4kings.ro/banlist?pageBanList=1,2,3...
        until an empty page is found.
        """
        if not CLOUDSCRAPER_AVAILABLE:
            logger.error(
                "❌ Cloudscraper not available - cannot scrape banlist (install with: pip install cloudscraper)"
            )
            return []

        all_bans = []
        page = 1
        max_pages = 100  # Safety limit

        logger.info("🔍 Starting full banlist scrape with cloudscraper...")

        # Create cloudscraper session (handles JavaScript challenges automatically)
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )

        try:
            while page <= max_pages:
                url = f"{self.base_url}/banlist?pageBanList={page}&search="
                logger.info(f"📄 Fetching banlist page {page}...")

                try:
                    # Use cloudscraper's sync get method in an executor to make it async
                    def fetch_with_cloudscraper():
                        response = scraper.get(url, timeout=30)
                        return response.text if response.status_code == 200 else None

                    # Run in executor to avoid blocking
                    html = await asyncio.get_event_loop().run_in_executor(
                        None, fetch_with_cloudscraper
                    )

                    if not html:
                        logger.warning(f"Failed to fetch page {page}, stopping")
                        break

                    # Check if still getting challenge page
                    if "Un moment" in html:
                        logger.warning(
                            f"⚠️ Challenge still present on page {page}, retrying..."
                        )
                        await asyncio.sleep(5)  # Wait longer
                        html = await asyncio.get_event_loop().run_in_executor(
                            None, fetch_with_cloudscraper
                        )

                        if not html or "Un moment" in html:
                            logger.warning(
                                f"Failed to bypass challenge on page {page}, stopping"
                            )
                            break

                    soup = BeautifulSoup(html, "lxml")

                    # Find the ban table
                    ban_table = soup.select_one("table")
                    if not ban_table:
                        logger.info(f"No table found on page {page}, stopping")
                        break

                    ban_rows = ban_table.select("tr")
                    if len(ban_rows) <= 1:  # Only header row
                        logger.info(f"No data rows on page {page}, stopping")
                        break

                    page_bans = []
                    for row in ban_rows[1:]:  # Skip header
                        try:
                            cells = row.select("td")
                            if len(cells) < 6:
                                continue

                            # Extract player ID and name from link
                            player_link = cells[1].select_one('a[href*="/profile/"]')
                            player_id = None
                            player_name = cells[1].get_text(strip=True)

                            if player_link:
                                href = player_link.get("href", "")
                                id_match = re.search(r"/profile/(\d+)", str(href))
                                if id_match:
                                    player_id = id_match.group(1)

                            # Try to get player_id from first cell if not in link
                            if not player_id:
                                first_cell_text = cells[0].get_text(strip=True)
                                if first_cell_text.isdigit():
                                    player_id = first_cell_text

                            ban_data = {
                                "player_id": player_id,
                                "player_name": player_name,
                                "admin": cells[2].get_text(strip=True)
                                if len(cells) > 2
                                else None,
                                "reason": cells[3].get_text(strip=True)
                                if len(cells) > 3
                                else None,
                                "duration": cells[4].get_text(strip=True)
                                if len(cells) > 4
                                else None,
                                "ban_date": cells[5].get_text(strip=True)
                                if len(cells) > 5
                                else None,
                                "expiry_date": cells[6].get_text(strip=True)
                                if len(cells) > 6
                                else None,
                            }

                            page_bans.append(ban_data)

                        except Exception as e:
                            logger.error(f"Error parsing ban row on page {page}: {e}")
                            continue

                    if not page_bans:
                        logger.info(f"No bans parsed on page {page}, stopping")
                        break

                    all_bans.extend(page_bans)
                    logger.info(
                        f"✅ Page {page}: Found {len(page_bans)} bans (total: {len(all_bans)})"
                    )

                    # Check for next page link in the HTML
                    next_link = soup.select_one(f'a[href*="pageBanList={page + 1}"]')
                    if not next_link:
                        logger.info(
                            f"No next page link found after page {page}, stopping"
                        )
                        break

                    page += 1
                    await asyncio.sleep(2)  # Rate limiting between pages

                except Exception as e:
                    logger.error(f"Error fetching page {page}: {e}")
                    break

        finally:
            # Close cloudscraper session
            scraper.close()

        logger.info(
            f"🏁 Banlist scrape complete: {len(all_bans)} total bans from {page} pages"
        )

        # Now fetch played_hours and faction for each banned player using regular scraper
        if all_bans:
            player_ids = [b["player_id"] for b in all_bans if b.get("player_id")]
            logger.info(f"🔄 Fetching profiles for {len(player_ids)} banned players...")

            # Batch fetch profiles to get played_hours and faction
            profiles = await self.batch_get_profiles(
                player_ids[:500]
            )  # Limit to 500 to avoid timeout

            # Create lookup dict
            profile_lookup = {}
            for profile in profiles:
                if profile:
                    profile_lookup[profile.player_id] = {
                        "played_hours": profile.played_hours,
                        "faction": profile.faction,
                    }

            # Enrich ban data with profile info
            for ban in all_bans:
                player_id = ban.get("player_id")
                if player_id and player_id in profile_lookup:
                    ban["played_hours"] = profile_lookup[player_id].get(
                        "played_hours", 0
                    )
                    ban["faction"] = profile_lookup[player_id].get("faction")
                else:
                    ban["played_hours"] = None
                    ban["faction"] = None

            logger.info(f"✅ Enriched {len(profile_lookup)} bans with profile data")

        return all_bans


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

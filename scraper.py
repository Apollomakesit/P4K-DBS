import aiohttp
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Tuple
import re
import logging
from dataclasses import dataclass

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
    profile_data: Dict = None

class Pro4KingsScraper:
    """Enhanced scraper for panel.pro4kings.ro"""
    
    def __init__(self, base_url: str = "https://panel.pro4kings.ro", max_concurrent: int = 50):
        self.base_url = base_url
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.session: Optional[aiohttp.ClientSession] = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
        }
    
    async def __aenter__(self):
        """Async context manager entry"""
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=50, ttl_dns_cache=300)
        timeout = aiohttp.ClientTimeout(total=60, connect=20, sock_read=30)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=self.headers,
            trust_env=True
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
            await asyncio.sleep(0.25)  # Give time for connections to close
    
    async def fetch_page(self, url: str, retries: int = 3) -> Optional[str]:
        """Fetch page with retry logic and rate limiting"""
        async with self.semaphore:
            for attempt in range(retries):
                try:
                    async with self.session.get(url, allow_redirects=True, ssl=False) as response:
                        if response.status == 200:
                            return await response.text(encoding='utf-8')
                        elif response.status == 429:  # Rate limited
                            wait_time = 2 ** attempt
                            logger.warning(f"Rate limited, waiting {wait_time}s")
                            await asyncio.sleep(wait_time)
                            continue
                        elif response.status == 404:
                            logger.warning(f"Page not found: {url}")
                            return None
                        else:
                            logger.warning(f"Status {response.status} for {url}")
                            if attempt < retries - 1:
                                await asyncio.sleep(1)
                                continue
                            return None
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout on {url}, attempt {attempt + 1}/{retries}")
                    if attempt < retries - 1:
                        await asyncio.sleep(2)
                        continue
                    return None
                except Exception as e:
                    logger.error(f"Error fetching {url}: {e}")
                    if attempt < retries - 1:
                        await asyncio.sleep(1)
                        continue
                    return None
        return None
    
    async def get_online_players(self) -> List[Dict]:
        """
        Get all online players from https://panel.pro4kings.ro/online
        Handles pagination: /online?pageOnline=1, /online?pageOnline=2, etc.
        """
        all_players = []
        page = 1
        
        while True:
            url = f"{self.base_url}/online?pageOnline={page}" if page > 1 else f"{self.base_url}/online"
            logger.info(f"Fetching online players page {page}...")
            
            html = await self.fetch_page(url)
            if not html:
                break
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Find online players table/list
            # Adjust selectors based on actual HTML structure
            player_rows = soup.select('table tr, .player-row, .online-player')
            
            if not player_rows or len(player_rows) <= 1:  # No more players (header row only)
                break
            
            page_players = []
            for row in player_rows[1:]:  # Skip header
                try:
                    # Extract player ID and name
                    # Method 1: From profile link
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
                    
                    # Method 2: From table cells
                    if not link:
                        cells = row.select('td')
                        if len(cells) >= 2:
                            # Typically: ID | Name | Level | etc
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
            
            # Check for next page link
            next_link = soup.select_one('a[href*="pageOnline=' + str(page + 1) + '"]')
            if not next_link:
                break
            
            page += 1
            await asyncio.sleep(0.5)  # Rate limiting between pages
        
        logger.info(f"Total online players found: {len(all_players)}")
        return all_players
    
    async def get_latest_actions(self, limit: int = 100) -> List[PlayerAction]:
        """
        Get latest actions from https://panel.pro4kings.ro/ 
        From "Ultimele acțiuni" section (lower right)
        """
        url = f"{self.base_url}/"
        html = await self.fetch_page(url)
        
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find "Ultimele acțiuni" section
        actions_section = soup.find(text=re.compile(r'Ultimele.*ac.*iuni', re.IGNORECASE))
        if actions_section:
            actions_container = actions_section.find_parent(['div', 'section', 'table'])
        else:
            # Try alternative selectors
            actions_container = soup.select_one('#ultimele-actiuni, .latest-actions, .recent-actions')
        
        if not actions_container:
            logger.warning("Could not find 'Ultimele acțiuni' section")
            return []
        
        # Find all action entries
        action_entries = actions_container.select('li, tr, .action-item, .activity-row')
        actions = []
        
        for entry in action_entries[:limit]:
            action = self.parse_action_entry(entry)
            if action:
                actions.append(action)
        
        logger.info(f"Parsed {len(actions)} actions from homepage")
        return actions
    
    def parse_action_entry(self, entry) -> Optional[PlayerAction]:
        """
        Parse individual action entry
        Examples:
        - "Jucatorul TechnegruFULL(137703) a primit un avertisment (2/3), de la administratorul [A605] Nea Daly(804), motiv 200.  2026-01-17 02:26:54"
        - "Jucatorul PANDA(219847) a pus in chest(id u219847vehtiptruck), 200x Seminte Plante.  2026-01-17 02:26:55"
        - "Jucatorul John(12345) a dat lui Mike(67890) 50x Wood.  2026-01-17 02:25:00"
        """
        try:
            text = entry.get_text(strip=True)
            if not text:
                return None
            
            # Extract timestamp (format: YYYY-MM-DD HH:MM:SS)
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', text)
            timestamp = datetime.now()
            if timestamp_match:
                try:
                    timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
                except:
                    pass
            
            # Pattern 1: Warning received
            # "Jucatorul PlayerName(ID) a primit un avertisment (2/3), de la administratorul [AdminTag] AdminName(AdminID), motiv Reason"
            warning_match = re.search(
                r'Jucatorul\s+([^\(]+)\((\d+)\)\s+a primit un avertisment\s+\((\d+/\d+)\),\s+de la administratorul\s+\[([^\]]+)\]\s+([^\(]+)\((\d+)\),\s+motiv\s+(.+?)(?=\s+\d{4}|$)',
                text,
                re.IGNORECASE
            )
            if warning_match:
                return PlayerAction(
                    player_id=warning_match.group(2),
                    player_name=warning_match.group(1).strip(),
                    action_type='warning_received',
                    action_detail=f"Primit avertisment {warning_match.group(3)}",
                    admin_id=warning_match.group(6),
                    admin_name=warning_match.group(5).strip(),
                    warning_count=warning_match.group(3),
                    reason=warning_match.group(7).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # Pattern 2: Chest interaction
            # "Jucatorul PlayerName(ID) a pus in chest(id chestid), 200x Item Name"
            chest_match = re.search(
                r'Jucatorul\s+([^\(]+)\((\d+)\)\s+a (pus in|scos din)\s+chest\([^\)]+\),\s+(\d+)x\s+(.+?)(?=\s+\d{4}|$)',
                text,
                re.IGNORECASE
            )
            if chest_match:
                action_type = 'chest_deposit' if 'pus' in chest_match.group(3) else 'chest_withdraw'
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
            
            # Pattern 3: Item transfer (gave to player)
            # "Jucatorul PlayerName1(ID1) a dat lui PlayerName2(ID2) 50x Item"
            gave_match = re.search(
                r'Jucatorul\s+([^\(]+)\((\d+)\)\s+a dat lui\s+([^\(]+)\((\d+)\)\s+(\d+)x\s+(.+?)(?=\s+\d{4}|$)',
                text,
                re.IGNORECASE
            )
            if gave_match:
                return PlayerAction(
                    player_id=gave_match.group(2),
                    player_name=gave_match.group(1).strip(),
                    action_type='item_given',
                    action_detail=f"Dat către {gave_match.group(3).strip()}",
                    item_name=gave_match.group(6).strip(),
                    item_quantity=int(gave_match.group(5)),
                    target_player_id=gave_match.group(4),
                    target_player_name=gave_match.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # Pattern 4: Item received
            # "Jucatorul PlayerName2(ID2) a primit de la PlayerName1(ID1) 50x Item"
            received_match = re.search(
                r'Jucatorul\s+([^\(]+)\((\d+)\)\s+a primit de la\s+([^\(]+)\((\d+)\)\s+(\d+)x\s+(.+?)(?=\s+\d{4}|$)',
                text,
                re.IGNORECASE
            )
            if received_match:
                return PlayerAction(
                    player_id=received_match.group(2),
                    player_name=received_match.group(1).strip(),
                    action_type='item_received',
                    action_detail=f"Primit de la {received_match.group(3).strip()}",
                    item_name=received_match.group(6).strip(),
                    item_quantity=int(received_match.group(5)),
                    target_player_id=received_match.group(4),
                    target_player_name=received_match.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # Pattern 5: Generic player action
            # "Jucatorul PlayerName(ID) action description"
            generic_match = re.search(r'Jucatorul\s+([^\(]+)\((\d+)\)\s+(.+?)(?=\s+\d{4}|$)', text, re.IGNORECASE)
            if generic_match:
                return PlayerAction(
                    player_id=generic_match.group(2),
                    player_name=generic_match.group(1).strip(),
                    action_type='other',
                    action_detail=generic_match.group(3).strip(),
                    timestamp=timestamp,
                    raw_text=text
                )
            
            # If no pattern matches, store as raw action
            return PlayerAction(
                player_id=None,
                player_name=None,
                action_type='unknown',
                action_detail=text,
                timestamp=timestamp,
                raw_text=text
            )
            
        except Exception as e:
            logger.error(f"Error parsing action entry: {e}")
            return None
    
    async def get_player_profile(self, player_id: str) -> Optional[PlayerProfile]:
        """
        Get complete player profile from https://panel.pro4kings.ro/profile/{player_id}
        Includes both "Profil" and "Proprietăți" tabs
        """
        # Main profile page
        profile_url = f"{self.base_url}/profile/{player_id}#home"
        html = await self.fetch_page(profile_url)
        
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        
        try:
            # Extract username
            username_elem = soup.select_one('.profile-username, .player-name, h1, h2')
            username = username_elem.get_text(strip=True) if username_elem else f"Player_{player_id}"
            
            # Check if player is online (look for online indicator)
            is_online = bool(soup.select_one('.online-indicator, .status-online, .badge-success')) or \
                       'online' in soup.get_text().lower()[:1000]
            
            # Extract last connection
            last_seen = datetime.now()
            last_conn_elem = soup.find(text=re.compile(r'Ultima.*conectare|Last.*connection', re.IGNORECASE))
            if last_conn_elem:
                parent = last_conn_elem.find_parent(['div', 'span', 'td'])
                if parent:
                    time_text = parent.get_text()
                    time_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', time_text)
                    if time_match:
                        try:
                            last_seen = datetime.strptime(time_match.group(1), '%Y-%m-%d %H:%M:%S')
                        except:
                            pass
            
            # Extract profile data
            profile_data = {}
            
            # Method 1: Parse infobox/profile table
            info_rows = soup.select('.profile-info tr, .player-stats tr, .info-row')
            for row in info_rows:
                label = row.select_one('th, .label, .key')
                value = row.select_one('td, .value, .val')
                if label and value:
                    key = label.get_text(strip=True).lower()
                    val = value.get_text(strip=True)
                    profile_data[key] = val
            
            # Method 2: Parse definition lists
            dt_elements = soup.select('dt')
            for dt in dt_elements:
                dd = dt.find_next_sibling('dd')
                if dd:
                    key = dt.get_text(strip=True).lower()
                    val = dd.get_text(strip=True)
                    profile_data[key] = val
            
            # Extract specific fields
            faction = None
            faction_rank = None
            job = None
            level = None
            respect_points = None
            warnings = None
            played_hours = None
            age_ic = None
            phone_number = None
            
            # Faction
            for key, val in profile_data.items():
                if 'fac' in key or 'factiune' in key:
                    faction = val
                    break
            if not faction:
                faction_elem = soup.select_one('.faction, .factiune')
                if faction_elem:
                    faction = faction_elem.get_text(strip=True)
            
            # Faction Rank
            for key, val in profile_data.items():
                if 'rank' in key or 'rang' in key:
                    faction_rank = val
                    break
            
            # Job
            for key, val in profile_data.items():
                if 'job' in key or 'meserie' in key or 'ocupatie' in key:
                    job = val
                    break
            
            # Level
            for key, val in profile_data.items():
                if 'level' in key or 'nivel' in key:
                    level_match = re.search(r'\d+', val)
                    if level_match:
                        level = int(level_match.group())
                    break
            
            # Respect Points
            for key, val in profile_data.items():
                if 'respect' in key or 'puncte' in key:
                    resp_match = re.search(r'\d+', val)
                    if resp_match:
                        respect_points = int(resp_match.group())
                    break
            
            # Warnings
            for key, val in profile_data.items():
                if 'warn' in key or 'avertis' in key:
                    warn_match = re.search(r'(\d+)', val)
                    if warn_match:
                        warnings = int(warn_match.group(1))
                    break
            
            # Played Hours
            for key, val in profile_data.items():
                if 'ore' in key or 'hours' in key or 'timp' in key:
                    hours_match = re.search(r'([\d\.]+)', val)
                    if hours_match:
                        played_hours = float(hours_match.group(1))
                    break
            
            # Age IC
            for key, val in profile_data.items():
                if 'varsta' in key or 'age' in key or 'ani' in key:
                    age_match = re.search(r'(\d+)', val)
                    if age_match:
                        age_ic = int(age_match.group(1))
                    break
            
            # Phone Number
            for key, val in profile_data.items():
                if 'telefon' in key or 'phone' in key or 'numar' in key:
                    phone_match = re.search(r'(\d+)', val)
                    if phone_match:
                        phone_number = phone_match.group(1)
                    break
            
            # Get properties count (from "Proprietăți" tab)
            properties_url = f"{self.base_url}/profile/{player_id}#profile"
            props_html = await self.fetch_page(properties_url)
            vehicles_count = None
            properties_count = None
            
            if props_html:
                props_soup = BeautifulSoup(props_html, 'html.parser')
                
                # Count vehicles
                vehicles_section = props_soup.find(text=re.compile(r'Vehicule|Vehicles', re.IGNORECASE))
                if vehicles_section:
                    vehicles_parent = vehicles_section.find_parent(['div', 'section'])
                    if vehicles_parent:
                        vehicle_items = vehicles_parent.select('.vehicle-item, tr, li')
                        vehicles_count = len(vehicle_items)
                
                # Count properties
                properties_section = props_soup.find(text=re.compile(r'Proprietăți|Properties', re.IGNORECASE))
                if properties_section:
                    props_parent = properties_section.find_parent(['div', 'section'])
                    if props_parent:
                        prop_items = props_parent.select('.property-item, tr, li')
                        properties_count = len(prop_items)
            
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
    
    async def get_faction_members(self) -> Dict[str, List[Dict]]:
        """Get all factions and their member counts from https://panel.pro4kings.ro/factions"""
        url = f"{self.base_url}/factions"
        html = await self.fetch_page(url)
        
        if not html:
            return {}
        
        soup = BeautifulSoup(html, 'html.parser')
        factions = {}
        
        # Find faction list/table
        faction_rows = soup.select('table tr, .faction-row, .faction-item')
        
        for row in faction_rows[1:]:  # Skip header
            try:
                cells = row.select('td')
                if len(cells) >= 2:
                    faction_name = cells[0].get_text(strip=True)
                    member_count = cells[1].get_text(strip=True)
                    count_match = re.search(r'(\d+)', member_count)
                    if count_match:
                        factions[faction_name] = {
                            'name': faction_name,
                            'member_count': int(count_match.group(1))
                        }
            except Exception as e:
                logger.error(f"Error parsing faction row: {e}")
                continue
        
        return factions
    
    async def get_online_staff(self) -> List[Dict]:
        """Get online staff from https://panel.pro4kings.ro/staff"""
        url = f"{self.base_url}/staff"
        html = await self.fetch_page(url)
        
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        staff = []
        
        # Find online staff indicators
        online_section = soup.select('.staff-online, .online-staff')
        for elem in online_section:
            name_elem = elem.select_one('.staff-name, .admin-name')
            rank_elem = elem.select_one('.staff-rank, .admin-rank')
            
            if name_elem:
                staff.append({
                    'name': name_elem.get_text(strip=True),
                    'rank': rank_elem.get_text(strip=True) if rank_elem else 'Unknown',
                    'is_online': True
                })
        
        return staff
    
    async def get_banned_players(self) -> List[Dict]:
        """
        Get banned players from https://panel.pro4kings.ro/banlist
        Returns: ID / Jucător / Admin / Motiv / Durată / Dată primire / Dată expirare
        """
        url = f"{self.base_url}/banlist"
        html = await self.fetch_page(url)
        
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        banned = []
        
        # Find ban list table
        ban_rows = soup.select('table tr, .ban-row, .banned-player')
        
        for row in ban_rows[1:]:  # Skip header
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
    
    async def batch_get_profiles(self, player_ids: List[str], delay: float = 0.1, 
                                 concurrent: int = 25) -> List[PlayerProfile]:
        """Batch fetch player profiles with controlled concurrency"""
        results = []
        semaphore = asyncio.Semaphore(concurrent)
        
        async def fetch_with_limit(pid):
            async with semaphore:
                profile = await self.get_player_profile(pid)
                if delay > 0:
                    await asyncio.sleep(delay)
                return profile
        
        tasks = [fetch_with_limit(pid) for pid in player_ids]
        profiles = await asyncio.gather(*tasks, return_exceptions=True)
        
        for profile in profiles:
            if isinstance(profile, PlayerProfile):
                results.append(profile)
            elif isinstance(profile, Exception):
                logger.error(f"Error in batch: {profile}")
        
        return results

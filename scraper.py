import httpx
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
    """Enhanced scraper optimized for fast scanning"""
    
    def __init__(self, base_url: str = "https://panel.pro4kings.ro", max_concurrent: int = 20):
        self.base_url = base_url
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.client: Optional[httpx.AsyncClient] = None
        self.request_delay = 0.2  # 200ms base delay (fast!)
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
            timeout=15.0,  # Faster timeout
            limits=httpx.Limits(
                max_connections=self.max_concurrent * 2,
                max_keepalive_connections=self.max_concurrent
            ),
            follow_redirects=True,
            verify=False
        )
        logger.info(f"✓ HTTP client initialized ({self.max_concurrent} workers)")
        return self
    
    async def fetch_page(self, url: str, retries: int = 2) -> Optional[str]:  # Only 2 retries
        """Fetch page with minimal delay for speed"""
        async with self.semaphore:
            for attempt in range(retries):
                try:
                    response = await self.client.get(url)
                    
                    if response.status_code == 200:
                        return response.text
                    elif response.status_code == 404:
                        return None  # Profile doesn't exist - fast skip
                    elif response.status_code == 503:
                        # Server overloaded - this is critical
                        wait_time = 3 * (2 ** attempt)
                        logger.warning(f"503 Service Unavailable - backing off {wait_time}s")
                        await asyncio.sleep(wait_time)
                        raise Exception("503 Service Unavailable")  # Propagate to trigger global backoff
                    elif response.status_code == 429:
                        wait_time = 5 * (2 ** attempt)
                        logger.warning(f"429 Rate Limited - waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        if attempt < retries - 1:
                            await asyncio.sleep(0.5)
                            continue
                        return None
                        
                except httpx.TimeoutException:
                    if attempt < retries - 1:
                        await asyncio.sleep(0.5)
                        continue
                    return None
                except Exception as e:
                    if '503' in str(e):
                        raise  # Re-raise 503 to trigger backoff
                    if attempt < retries - 1:
                        await asyncio.sleep(0.5)
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
            player_rows = soup.select('table tr, .player-row, .online-player')
            
            if not player_rows or len(player_rows) <= 1:
                break
            
            page_players = []
            for row in player_rows[1:]:  # Skip header
                try:
                    # Extract player ID and name
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
            await asyncio.sleep(0.5)
        
        logger.info(f"Total online players found: {len(all_players)}")
        return all_players
    
    async def get_latest_actions(self, limit: int = 200) -> List[PlayerAction]:
        """
        CRITICAL: Get latest actions - THIS IS THE PRIMARY FUNCTION
        Enhanced with multiple detection methods
        """
        url = f"{self.base_url}/"
        html = await self.fetch_page(url)
    
        if not html:
            logger.error("❌ Failed to fetch homepage for actions!")
            return []
    
        soup = BeautifulSoup(html, 'lxml')  # Use lxml parser for better performance
        actions = []
    
        # STRATEGY 1: Find by common Romanian text patterns
        activity_keywords = ['Activitate', 'Ultimele', 'acțiuni', 'actiuni', 'Recent']
        possible_sections = []
    
        for keyword in activity_keywords:
            headings = soup.find_all(text=re.compile(keyword, re.IGNORECASE))
            for heading in headings:
                parent = heading.find_parent(['div', 'section', 'article', 'main'])
                if parent:
                    possible_sections.append(parent)
    
        # STRATEGY 2: Find lists with player action patterns
        all_lists = soup.find_all(['ul', 'ol', 'div'], class_=re.compile(r'activity|actions|feed|timeline', re.IGNORECASE))
        possible_sections.extend(all_lists)
    
        # STRATEGY 3: Find by common class/id patterns
        direct_selectors = [
            '#activity', '#actions', '#latest-actions', '#recent-activity',
            '.activity', '.actions', '.recent-actions', '.latest-actions',
            '.activity-feed', '.action-log', '.player-actions'
        ]
        for selector in direct_selectors:
            elem = soup.select_one(selector)
            if elem:
                possible_sections.append(elem)
    
        # STRATEGY 4: Find any list containing "Jucatorul" text (player actions)
        all_text_containers = soup.find_all(['ul', 'ol', 'div', 'table'])
        for container in all_text_containers:
            text = container.get_text()
            # Check if it contains multiple player actions
            if text.count('Jucatorul') >= 3 or text.count('jucatorul') >= 3:
                possible_sections.append(container)
    
        # Try each potential section
        for section in possible_sections:
            if not section:
                continue
        
            # Extract action entries from this section
            entries = section.find_all(['li', 'tr', 'div'], recursive=True)
        
            for entry in entries:
                text = entry.get_text(strip=True)
            
                # Skip if too short or doesn't contain player action markers
                if len(text) < 20:
                    continue
                if 'Jucatorul' not in text and 'jucatorul' not in text:
                    continue
            
                # Parse the action
                action = self.parse_action_entry(entry)
                if action:
                    actions.append(action)
                
                    # Stop if we have enough
                    if len(actions) >= limit:
                    break
            
            # If we found actions in this section, stop searching
            if len(actions) > 0:
                logger.info(f"✓ Found actions in section: {section.name} (class: {section.get('class')})")
                break
    
        if len(actions) == 0:
            logger.error("❌ NO ACTIONS FOUND! Debugging HTML structure:")
            logger.error(f"Total 'Jucatorul' mentions: {soup.get_text().count('Jucatorul')}")
            logger.error(f"Possible sections found: {len(possible_sections)}")
        
            # Last resort: Find ALL text containing "Jucatorul" and try to parse
            all_text = soup.get_text()
            lines = all_text.split('\n')
            for line in lines:
                if 'Jucatorul' in line and len(line) > 20:
                    # Create a fake element with this text
                    fake_elem = BeautifulSoup(f'<div>{line}</div>', 'lxml').div
                    action = self.parse_action_entry(fake_elem)
                    if action:
                        actions.append(action)
    
        logger.info(f"✓ Parsed {len(actions)} actions from homepage")
        return actions[:limit]

    
def parse_action_entry(self, entry) -> Optional[PlayerAction]:
    """Enhanced action parser with MORE patterns"""
    try:
        text = entry.get_text(strip=True)
        if not text or len(text) < 15:
            return None
        
        # Clean up text
        text = ' '.join(text.split())  # Remove extra whitespace
        
        # Extract timestamp
        timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', text)
        timestamp = datetime.now()
        if timestamp_match:
            try:
                timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
            except:
                pass
        
        # Pattern 1: Warning received (most common admin action)
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
        
        # Pattern 3: Item given to another player
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
        
        # Pattern 4: Item received from another player
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
        
        # Pattern 5: Vehicle purchase/sale
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
        
        # Pattern 6: Property purchase/sale  
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
        
        # Pattern 7: Generic player action (catch-all)
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
        
        # If no pattern matched but contains "Jucatorul", store as unknown
        if 'jucatorul' in text.lower():
            return PlayerAction(
                player_id=None,
                player_name=None,
                action_type='unknown',
                action_detail=text[:200],  # Limit length
                timestamp=timestamp,
                raw_text=text
            )
        
        return None
        
    except Exception as e:
        logger.error(f"Error parsing action: {e} | Text: {text[:100]}")
        return None

    
    async def get_player_profile(self, player_id: str) -> Optional[PlayerProfile]:
        """Get complete player profile"""
        profile_url = f"{self.base_url}/profile/{player_id}#home"
        html = await self.fetch_page(profile_url)
        
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        
        try:
            username_elem = soup.select_one('.profile-username, .player-name, h1, h2')
            username = username_elem.get_text(strip=True) if username_elem else f"Player_{player_id}"
            
            is_online = bool(soup.select_one('.online-indicator, .status-online, .badge-success')) or \
                       'online' in soup.get_text().lower()[:1000]
            
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
            
            profile_data = {}
            
            info_rows = soup.select('.profile-info tr, .player-stats tr, .info-row')
            for row in info_rows:
                label = row.select_one('th, .label, .key')
                value = row.select_one('td, .value, .val')
                if label and value:
                    key = label.get_text(strip=True).lower()
                    val = value.get_text(strip=True)
                    profile_data[key] = val
            
            dt_elements = soup.select('dt')
            for dt in dt_elements:
                dd = dt.find_next_sibling('dd')
                if dd:
                    key = dt.get_text(strip=True).lower()
                    val = dd.get_text(strip=True)
                    profile_data[key] = val
            
            # Extract fields (same logic as before)
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
                if 'fac' in key or 'factiune' in key:
                    faction = val
                    break
            
            for key, val in profile_data.items():
                if 'rank' in key or 'rang' in key:
                    faction_rank = val
                    break
            
            for key, val in profile_data.items():
                if 'job' in key or 'meserie' in key:
                    job = val
                    break
            
            for key, val in profile_data.items():
                if 'level' in key or 'nivel' in key:
                    level_match = re.search(r'\d+', val)
                    if level_match:
                        level = int(level_match.group())
                    break
            
            for key, val in profile_data.items():
                if 'respect' in key or 'puncte' in key:
                    resp_match = re.search(r'\d+', val)
                    if resp_match:
                        respect_points = int(resp_match.group())
                    break
            
            for key, val in profile_data.items():
                if 'warn' in key or 'avertis' in key:
                    warn_match = re.search(r'(\d+)', val)
                    if warn_match:
                        warnings = int(warn_match.group(1))
                    break
            
            for key, val in profile_data.items():
                if 'ore' in key or 'hours' in key or 'timp' in key:
                    hours_match = re.search(r'([\d\.]+)', val)
                    if hours_match:
                        played_hours = float(hours_match.group(1))
                    break
            
            for key, val in profile_data.items():
                if 'varsta' in key or 'age' in key:
                    age_match = re.search(r'(\d+)', val)
                    if age_match:
                        age_ic = int(age_match.group(1))
                    break
            
            for key, val in profile_data.items():
                if 'telefon' in key or 'phone' in key:
                    phone_match = re.search(r'(\d+)', val)
                    if phone_match:
                        phone_number = phone_match.group(1)
                    break
            
            # Get properties
            properties_url = f"{self.base_url}/profile/{player_id}#profile"
            props_html = await self.fetch_page(properties_url)
            vehicles_count = None
            properties_count = None
            
            if props_html:
                props_soup = BeautifulSoup(props_html, 'html.parser')
                
                vehicles_section = props_soup.find(text=re.compile(r'Vehicule|Vehicles', re.IGNORECASE))
                if vehicles_section:
                    vehicles_parent = vehicles_section.find_parent(['div', 'section'])
                    if vehicles_parent:
                        vehicle_items = vehicles_parent.select('.vehicle-item, tr, li')
                        vehicles_count = len(vehicle_items)
                
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
        """Get all factions and their member counts"""
        url = f"{self.base_url}/factions"
        html = await self.fetch_page(url)
        
        if not html:
            return {}
        
        soup = BeautifulSoup(html, 'html.parser')
        factions = {}
        
        faction_rows = soup.select('table tr, .faction-row, .faction-item')
        
        for row in faction_rows[1:]:
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
        """Get online staff"""
        url = f"{self.base_url}/staff"
        html = await self.fetch_page(url)
        
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        staff = []
        
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





import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime
import re
import asyncio

class Pro4KingsScraper:
    def __init__(self):
        self.base_url = "https://panel.pro4kings.ro"
        self.actions_url = self.base_url
        self.online_url = f"{self.base_url}/online"
        self.profile_url = f"{self.base_url}/profile"
        
    async def get_latest_actions(self):
        """Scrape the 'Ultimele acțiuni' section from homepage"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.actions_url, timeout=15) as response:
                    if response.status != 200:
                        print(f"Error: Status {response.status}")
                        return []
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    actions = []
                    
                    # Find all text that contains "Jucatorul" or "Jucătorul"
                    # The actions appear in the HTML as text nodes
                    all_text = soup.get_text()
                    
                    # Split by common delimiters and process each potential action
                    lines = all_text.split('\n')
                    
                    for i, line in enumerate(lines):
                        line = line.strip()
                        
                        # Check if this line contains an action
                        if not ('Jucatorul' in line or 'Jucătorul' in line):
                            continue
                        
                        # Look for timestamp in the same line or next line
                        timestamp = None
                        text = line
                        
                        # Pattern 1: Timestamp in same line
                        timestamp_match = re.search(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', text)
                        if timestamp_match:
                            timestamp_str = timestamp_match.group(0)
                            try:
                                timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                            except:
                                pass
                        
                        # Pattern 2: Check next line for timestamp
                        if not timestamp and i + 1 < len(lines):
                            next_line = lines[i + 1].strip()
                            timestamp_match = re.search(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', next_line)
                            if timestamp_match:
                                timestamp_str = timestamp_match.group(0)
                                try:
                                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                                    # Combine text with timestamp line for full context
                                    text = f"{text} {next_line}"
                                except:
                                    pass
                        
                        if not timestamp:
                            timestamp = datetime.now()
                        
                        # Clean up text
                        text = re.sub(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', '', text).strip()
                        text = re.sub(r'[🕐⏰🕑🕒🕓🕔🕕🕖🕗🕘🕙🕚🕛]', '', text).strip()
                        text = re.sub(r'\s+', ' ', text)
                        
                        # Skip if text is too short
                        if len(text) < 20:
                            continue
                        
                        # Parse the action
                        parsed = self._parse_action(text)
                        
                        if parsed.get('from_id'):  # Only save if we got valid data
                            actions.append({
                                'timestamp': timestamp,
                                'text': text,
                                'from_player': parsed.get('from_player'),
                                'from_id': parsed.get('from_id'),
                                'to_player': parsed.get('to_player'),
                                'to_id': parsed.get('to_id'),
                                'quantity': parsed.get('quantity'),
                                'item': parsed.get('item'),
                                'action_type': parsed.get('action_type')
                            })
                            print(f"✓ Parsed action: {parsed.get('from_player')}({parsed.get('from_id')}) -> {parsed.get('action_type')}")
                    
                    return actions
            except Exception as e:
                print(f"Error scraping actions: {e}")
                import traceback
                traceback.print_exc()
                return []
    
    def _parse_action(self, text):
        """Parse action text to extract structured data"""
        result = {
            'from_player': None,
            'from_id': None,
            'to_player': None,
            'to_id': None,
            'quantity': None,
            'item': None,
            'action_type': None
        }
        
        # Extract "from" player: Jucatorul NAME(ID) or Jucătorul NAME(ID)
        # Handle special characters in names
        from_match = re.search(r'Juc[aă]torul\s+(.+?)\((\d+)\)', text, re.IGNORECASE)
        if from_match:
            result['from_player'] = from_match.group(1).strip()
            result['from_id'] = int(from_match.group(2))
        
        # Determine action type and extract "to" player
        if 'dat lui' in text or 'a dat lui' in text or 'ia dat lui' in text:
            result['action_type'] = 'gave'
            # Extract receiver: lui NAME(ID)
            to_match = re.search(r'lui\s+(.+?)\((\d+)\)', text)
            if to_match:
                result['to_player'] = to_match.group(1).strip()
                result['to_id'] = int(to_match.group(2))
        elif 'retras din' in text or 'a retras din' in text:
            result['action_type'] = 'withdrew'
        elif 'depus' in text or 'a pus' in text:
            result['action_type'] = 'deposited'
        elif 'livrat' in text or 'a livrat' in text:
            result['action_type'] = 'delivered'
        elif 'primit' in text or 'a primit' in text:
            result['action_type'] = 'received'
        
        # Extract quantity and item: NUMBER + "x" + ITEM or NUMBER + ITEM
        # Examples: "1316180x Bani Murdari", "1x Ketamina", "8.686.625 bani murdari"
        item_patterns = [
            r'(\d[\d\.,]*)\s*x\s+([^\.]+?)(?=\s+si\s+|\.|$)',  # "1316180x Bani Murdari"
            r'(\d[\d\.,]*)\s+([a-zA-Z][^\.]+?)(?=\s+si\s+|\.|$)',  # "8.686.625 bani murdari"
        ]
        
        for pattern in item_patterns:
            item_match = re.search(pattern, text)
            if item_match:
                try:
                    quantity_str = item_match.group(1).replace('.', '').replace(',', '')
                    result['quantity'] = int(quantity_str)
                    result['item'] = item_match.group(2).strip()
                    break
                except:
                    pass
        
        return result
    
    async def get_online_players(self):
        """Scrape ALL pages of online players with pagination"""
        all_players = []
        page = 1
        
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    url = f"{self.online_url}?pageOnline={page}"
                    async with session.get(url, timeout=15) as response:
                        if response.status != 200:
                            print(f"Error fetching page {page}: Status {response.status}")
                            break
                        
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Find player table
                        player_elements = soup.select('table tbody tr')
                        
                        # If no players found on this page, we've reached the end
                        if not player_elements:
                            break
                        
                        page_players = []
                        for elem in player_elements:
                            try:
                                # Get all columns
                                cols = elem.find_all('td')
                                if len(cols) < 2:
                                    continue
                                
                                # First column: ID
                                id_elem = cols[0]
                                # Second column: Name (with link)
                                name_elem = cols[1].find('a')
                                
                                if not name_elem:
                                    continue
                                
                                player_name = name_elem.get_text(strip=True)
                                
                                # Extract ID from href (profile/ID)
                                player_id = None
                                if name_elem.get('href') and '/profile/' in name_elem['href']:
                                    try:
                                        player_id = int(name_elem['href'].split('/profile/')[-1])
                                    except:
                                        pass
                                
                                # Fallback: try to get ID from first column
                                if not player_id:
                                    try:
                                        player_id = int(id_elem.get_text(strip=True))
                                    except:
                                        continue
                                
                                if player_id and player_name:
                                    page_players.append({
                                        'player_name': player_name,
                                        'player_id': player_id
                                    })
                            except Exception as e:
                                continue
                        
                        # If no players extracted, stop
                        if not page_players:
                            break
                        
                        all_players.extend(page_players)
                        print(f"✓ Scraped page {page}: {len(page_players)} players (Total: {len(all_players)})")
                        
                        page += 1
                        
                        # Rate limiting - don't hammer the server
                        await asyncio.sleep(0.3)
                        
                except Exception as e:
                    print(f"Error on page {page}: {e}")
                    break
        
        print(f"🎯 Total online players scraped: {len(all_players)} across {page-1} pages")
        return all_players
    
    async def get_player_profile(self, player_id):
        """Scrape individual player profile with all fields"""
        url = f"{self.profile_url}/{player_id}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=15) as response:
                    if response.status == 404:
                        return None
                        
                    if response.status != 200:
                        return None
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Get player name from header
                    name_elem = soup.select_one('h4.card-title')
                    if not name_elem:
                        return None
                    
                    player_name = name_elem.get_text(strip=True)
                    # Clean up name
                    player_name = re.sub(r'^\s*[•●]\s*', '', player_name)
                    
                    # FIXED: Better online status detection
                    is_online = False
                    
                    # Check in name element for "(Online)" text
                    if '(Online)' in player_name or 'Online' in name_elem.get_text():
                        is_online = True
                    
                    # Check for green indicator icon
                    if name_elem.find('i', class_='text-success'):
                        is_online = True
                    
                    # Check for badge with "Online" text
                    online_badge = soup.find('span', class_='badge', string=re.compile(r'Online', re.IGNORECASE))
                    if online_badge:
                        is_online = True
                    
                    # Clean up name (remove status indicators)
                    player_name = re.sub(r'\s*\(Online\)|\(Offline\)', '', player_name, flags=re.IGNORECASE).strip()
                    
                    # Get profile table
                    table = soup.find('table', class_='table')
                    if not table:
                        return None
                    
                    # Initialize fields
                    last_connection = None
                    faction = None
                    faction_rank = None
                    warns = None
                    job = None
                    played_hours = None
                    age_ic = None
                    
                    # Parse table rows
                    for row in table.find_all('tr'):
                        header = row.find('th')
                        data_cell = row.find('td')
                        
                        if not header or not data_cell:
                            continue
                        
                        header_text = header.get_text(strip=True)
                        data_text = data_cell.get_text(strip=True)
                        
                        if 'Ultima conectare' in header_text:
                            try:
                                last_connection = datetime.strptime(data_text, '%d/%m/%Y %H:%M:%S')
                            except:
                                last_connection = None
                        
                        elif 'Facțiune' in header_text or 'Factiune' in header_text:
                            if 'Rank' not in header_text:
                                faction = data_text if data_text else 'Civil'
                        
                        elif 'Rank Facțiune' in header_text or 'Rank Factiune' in header_text:
                            rank_link = data_cell.find('a')
                            if rank_link:
                                faction_rank = rank_link.get_text(strip=True)
                            else:
                                faction_rank = data_text
                            if faction_rank:
                                faction_rank = ' '.join(faction_rank.split())
                        
                        elif 'Warn' in header_text:
                            try:
                                warns = int(re.search(r'\d+', data_text).group())
                            except:
                                warns = 0
                        
                        elif 'Job' in header_text:
                            job = data_text if data_text else 'Fără job'
                        
                        elif 'Ore jucate' in header_text:
                            try:
                                # Extract number (could be float like 21932.2)
                                hours_match = re.search(r'[\d\.]+', data_text)
                                if hours_match:
                                    played_hours = float(hours_match.group())
                            except:
                                played_hours = 0
                        
                        elif 'Vârsta IC' in header_text or 'Varsta IC' in header_text:
                            try:
                                age_ic = int(re.search(r'\d+', data_text).group())
                            except:
                                age_ic = None
                    
                    return {
                        'player_id': player_id,
                        'player_name': player_name,
                        'last_connection': last_connection,
                        'is_online': is_online,
                        'faction': faction,
                        'faction_rank': faction_rank,
                        'warns': warns,
                        'job': job,
                        'played_hours': played_hours,
                        'age_ic': age_ic
                    }
            except asyncio.TimeoutError:
                return None
            except Exception as e:
                print(f"Error scraping profile {player_id}: {e}")
                return None
    
    async def batch_get_profiles(self, player_ids, delay=0.3, concurrent=10):
        """Get multiple profiles with concurrent requests"""
        results = []
        
        # Process in batches for better performance
        for i in range(0, len(player_ids), concurrent):
            batch = player_ids[i:i + concurrent]
            
            # Fetch batch concurrently
            tasks = [self.get_player_profile(pid) for pid in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in batch_results:
                if result and not isinstance(result, Exception):
                    results.append(result)
            
            if (i + concurrent) % 50 == 0:
                print(f"✓ Scraped {min(i + concurrent, len(player_ids))}/{len(player_ids)} profiles")
            
            # Delay between batches
            if i + concurrent < len(player_ids):
                await asyncio.sleep(delay)
        
        return results

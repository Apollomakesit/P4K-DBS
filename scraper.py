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
                    
                    # Find the "Ultimele acțiuni" section
                    actions_section = soup.find('div', class_='card') or soup.find('div', string=re.compile(r'Ultimele.*ac.*iuni', re.IGNORECASE))
                    
                    if not actions_section:
                        # Try alternative selectors
                        actions_section = soup
                    
                    # Look for action items - they typically appear in list format or as text blocks
                    action_elements = actions_section.find_all(['li', 'div', 'p'], recursive=True)
                    
                    for elem in action_elements:
                        text = elem.get_text(strip=True)
                        
                        # Check if this is an action (contains "Jucatorul" or "Jucătorul")
                        if not ('Jucatorul' in text or 'Jucătorul' in text):
                            continue
                        
                        # Extract timestamp in format: 2026-01-14 21:47:14
                        timestamp = None
                        timestamp_match = re.search(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', text)
                        
                        if timestamp_match:
                            try:
                                timestamp_str = timestamp_match.group(0)
                                timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                                # Remove timestamp from text
                                text = text.replace(timestamp_str, '').strip()
                            except:
                                timestamp = datetime.now()
                        else:
                            # Try alternative timestamp formats
                            timestamp_elem = elem.find('time')
                            if timestamp_elem:
                                timestamp_str = timestamp_elem.get('datetime') or timestamp_elem.get_text(strip=True)
                                try:
                                    timestamp = datetime.strptime(timestamp_str, '%d/%m/%Y %H:%M:%S')
                                except:
                                    try:
                                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                    except:
                                        timestamp = datetime.now()
                            else:
                                timestamp = datetime.now()
                        
                        # Clean up text (remove clock emoji and extra whitespace)
                        text = re.sub(r'[🕐⏰🕑🕒🕓🕔🕕🕖🕗🕘🕙🕚🕛]', '', text).strip()
                        
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
        
        # Extract "from" player: Jucatorul NAME(ID)
        from_match = re.search(r'Juc[aă]torul\s+([^\(]+)\((\d+)\)', text, re.IGNORECASE)
        if from_match:
            result['from_player'] = from_match.group(1).strip()
            result['from_id'] = int(from_match.group(2))
        
        # Determine action type and extract "to" player
        if 'dat lui' in text or 'a dat lui' in text or 'ia dat lui' in text:
            result['action_type'] = 'gave'
            to_match = re.search(r'lui\s+([^\(]+)\((\d+)\)', text)
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
        
        # Extract quantity and item: 1316180x Bani Murdari or 1x Ketamina
        item_match = re.search(r'(\d+)x?\s+([^\.]+)', text)
        if item_match:
            result['quantity'] = int(item_match.group(1).replace('x', ''))
            result['item'] = item_match.group(2).strip()
        
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
                                # Get ID from first column
                                id_elem = elem.select_one('td:first-child')
                                if not id_elem:
                                    continue
                                
                                # Get name from link in second column
                                name_elem = elem.select_one('td:nth-child(2) a')
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
                        await asyncio.sleep(0.5)
                        
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
                    player_name = re.sub(r'\s*\(Online\)|\(Offline\)', '', player_name, flags=re.IGNORECASE)
                    
                    # Check online status
                    is_online = False
                    if name_elem.find('i', class_='text-success') or soup.find(text=re.compile(r'Online', re.IGNORECASE)):
                        is_online = True
                    
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
    
    async def batch_get_profiles(self, player_ids, delay=0.5):
        """Get multiple profiles with delay between requests"""
        results = []
        for i, player_id in enumerate(player_ids):
            result = await self.get_player_profile(player_id)
            if result:
                results.append(result)
            
            if (i + 1) % 50 == 0:
                print(f"✓ Scraped {i + 1}/{len(player_ids)} profiles")
            
            await asyncio.sleep(delay)
        
        return results

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
        """Scrape the 'Ultimele acțiuni' section"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.actions_url, timeout=15) as response:
                    if response.status != 200:
                        print(f"Error: Status {response.status}")
                        return []
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    actions = []
                    action_elements = soup.select('li')
                    
                    for elem in action_elements:
                        text = elem.get_text(strip=True)
                        
                        if 'Jucatorul' in text or 'Jucătorul' in text:
                            timestamp_elem = elem.find('time') or elem.find(class_='timestamp') or elem.find('small')
                            
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
                            
                            parsed = self._parse_action(text)
                            
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
        
        from_match = re.search(r'Juc[aă]torul\s+(\w+)\((\d+)\)', text)
        if from_match:
            result['from_player'] = from_match.group(1)
            result['from_id'] = int(from_match.group(2))
        
        if 'dat lui' in text or 'a dat lui' in text or 'ia dat lui' in text:
            result['action_type'] = 'gave'
            to_match = re.search(r'lui\s+(\w+)\((\d+)\)', text)
            if to_match:
                result['to_player'] = to_match.group(1)
                result['to_id'] = int(to_match.group(2))
        elif 'retras din' in text or 'a retras din' in text:
            result['action_type'] = 'withdrew'
        elif 'depus' in text or 'a pus' in text:
            result['action_type'] = 'deposited'
        
        item_match = re.search(r'(\d+)x?\s+(.+?)(?:\.|$)', text)
        if item_match:
            result['quantity'] = int(item_match.group(1))
            result['item'] = item_match.group(2).strip()
        
        return result
    
    async def get_online_players(self):
        """Scrape the online players page"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.online_url, timeout=15) as response:
                    if response.status != 200:
                        print(f"Error: Status {response.status}")
                        return []
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    players = []
                    player_elements = soup.select('table tbody tr')
                    
                    for elem in player_elements:
                        name_elem = elem.select_one('td:first-child')
                        
                        if name_elem:
                            player_name = name_elem.get_text(strip=True)
                            player_id = None
                            
                            link = elem.find('a', href=True)
                            if link and '/profile/' in link['href']:
                                try:
                                    player_id = int(link['href'].split('/profile/')[-1])
                                except:
                                    pass
                            
                            if not player_id:
                                id_match = re.search(r'\((\d+)\)', player_name)
                                if id_match:
                                    player_id = int(id_match.group(1))
                                    player_name = re.sub(r'\(\d+\)', '', player_name).strip()
                            
                            if player_id:
                                players.append({
                                    'player_name': player_name,
                                    'player_id': player_id
                                })
                    
                    return players
            except Exception as e:
                print(f"Error scraping online players: {e}")
                return []
    
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
                    
                    name_elem = soup.select_one('h4.card-title')
                    if not name_elem:
                        return None
                    
                    player_name = name_elem.get_text(strip=True)
                    player_name = re.sub(r'^\s*[•●]\s*', '', player_name)
                    player_name = re.sub(r'\s*\(Online\)|\(Offline\)', '', player_name, flags=re.IGNORECASE)
                    
                    is_online = False
                    if name_elem.find('i', class_='text-success'):
                        is_online = True
                    
                    table = soup.find('table', class_='table')
                    if not table:
                        return None
                    
                    last_connection = None
                    faction = None
                    faction_rank = None
                    warns = None
                    job = None
                    played_hours = None
                    age_ic = None
                    
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
                                faction = data_text
                        
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
                            job = data_text
                        
                        elif 'Ore jucate' in header_text:
                            try:
                                played_hours = int(re.search(r'\d+', data_text).group())
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

# Pro4Kings Database Bot 🎮

Advanced Discord bot for monitoring and tracking Pro4Kings server players with **indefinite action storage**, accurate online/offline detection, and fast resumable scanning.

## ✨ Features

### Core Features
- ✅ **Accurate Online/Offline Detection** - Real-time monitoring from `panel.pro4kings.ro/online`
- ✅ **Indefinite Action Storage** - All player actions saved permanently with timestamps
- ✅ **Fast Resumable Scanning** - Initial scan can be paused and resumed
- ✅ **Priority Monitoring** - Online players checked more frequently
- ✅ **Complete Player Profiles** - Faction, rank, job, level, warnings, vehicles, properties
- ✅ **Login/Logout Tracking** - Session duration calculation
- ✅ **Faction Rank History** - Track promotions and demotions
- ✅ **Item Transfer Tracking** - Who gave what to whom
- ✅ **Warning System Monitoring** - Track player warnings (including 3/3 bans)
- ✅ **Banned Players List** - Monitor ban list for changes
- ✅ **Staff Activity** - Track online administrators

### What Gets Tracked
1. **Player Actions** (Indefinite storage):
   - Item transfers (given/received)
   - Chest interactions
   - Warnings received
   - All actions from "Ultimele acțiuni"

2. **Player Profiles**:
   - Faction and rank
   - Job and level
   - Warnings (0/3, 1/3, 2/3, 3/3)
   - Played hours
   - Vehicles count
   - Properties count
   - Respect points
   - Age IC

3. **Login Activity**:
   - Login timestamps
   - Logout timestamps
   - Session duration
   - Last seen

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Discord Bot Token ([Get one here](https://discord.com/developers/applications))

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/YourUsername/P4K-DBS.git
cd P4K-DBS

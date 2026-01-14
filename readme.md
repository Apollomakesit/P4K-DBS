# 🤖 Pro4Kings Monitor Bot

Complete Discord bot for monitoring **panel.pro4kings.ro** with real-time player tracking, faction management, and comprehensive statistics.

## ✨ Features

### 📊 Player Monitoring
- ✅ Real-time action tracking ("Ultimele acțiuni")
- ✅ Login/logout session tracking
- ✅ Online player monitoring (500+ players supported)
- ✅ Complete profile data (faction, rank, warns, job, hours, IC age)
- ✅ Player-to-player transaction history
- ✅ 30-day data retention with automatic cleanup

### 🎖️ Faction & Rank Tracking
- ✅ Automatic faction rank monitoring
- ✅ Complete rank history (promotions/demotions)
- ✅ Rank duration tracking
- ✅ Recent promotion notifications
- ✅ Faction member lists with stats

### ⚡ Performance
- ✅ **100 profiles/3min** = ~2000 profiles/hour (handles 500+ daily active players easily!)
- ✅ Smart priority system (active players updated first)
- ✅ Efficient batching and concurrent scraping
- ✅ SQLite database (lightweight, no external DB needed)

## 🚀 Quick Start

### 1. Prerequisites

```bash
# Clone repository
git clone <your-repo-url>
cd pro4kings-monitor

# Install dependencies
pip install -r requirements.txt

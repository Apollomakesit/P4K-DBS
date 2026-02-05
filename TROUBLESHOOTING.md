# Troubleshooting Guide

## Issue: Banned Players List Empty / Not Matching Website

### Root Cause

Pro4Kings panel (https://panel.pro4kings.ro) has implemented **site-wide anti-bot JavaScript protection** that prevents automated scraping. This affects:
- `/ban list` - Banned players page
- `/` - Main page with actions
- `/profile/*` - Player profiles  
- `/online` - Online players

All pages return a JavaScript challenge ("Un moment, vă rog...") that requires:
1. JavaScript execution in a real browser
2. A 5-second timeout and page reload
3. Cookie/session persistence

## Current Status ⚠️

**The scraper cannot bypass this protection without browser automation.** 

Simple HTTP clients (aiohttp, requests, cloudscraper) fail because they cannot execute JavaScript.

## Solutions

### Option 1: Deploy with Playwright (Recommended for Production)

Install Playwright with system dependencies:

```bash
pip install playwright
playwright install chromium
playwright install-deps chromium  # Requires sudo/root access
```

The scraper already has Playwright support coded - it just needs the browser installed.

**For Railway/Docker deployment**: Add to `Dockerfile`:

```dockerfile
# Install Playwright and Chromium
RUN pip install playwright && \
    playwright install chromium && \
    playwright install-deps chromium
```

### Option 2: Manual Browser Session (Development Workaround)

1. Open browser with developer tools
2. Visit `https://panel.pro4kings.ro/banlist`
3. Wait for challenge to complete
4. Export cookies using browser extension (e.g., "Cookie-Editor")  
5. Use cookies in scraper session

### Option 3: Alternative Ban Detection

The bot already detects bans from action feed:
- When `ban_received` actions are scraped, they're auto-added to `banned_players` table
- Limitation: Only works if action scraping is functional

### Option 4: Contact Server Admins

Request:
- API access for ban data
- Whitelist bot's IP address
- Disable protection for specific user-agent

## Testing Protection Status

```python
import cloudscraper

scraper = cloudscraper.create_scraper()
response = scraper.get("https://panel.pro4kings.ro/")

if "Un moment" in response.text:
    print("❌ Protection active")
else:
    print("✅ Scraping possible")
```

## Deployment Checklist

For production deployment where scraping must work:

- [ ] Install Playwright: `pip install playwright`
- [ ] Install Chromium: `playwright install chromium`  
- [ ] Install system deps: `playwright install-deps chromium` (needs root)
- [ ] Test banlist scraping: `python test_bans_scraper.py`
- [ ] Verify dashboard shows ban data
- [ ] Monitor bot logs for scraping errors

## Current Workaround in Code

The scraper has fallback logic:
1. Try with cloudscraper (fast, works if no protection)
2. If challenge detected, try Playwright (slower, requires browser)
3. If not available, log error and return empty list

## Questions?

If you're deploying on Railway, Heroku, or Docker, ensure the Dockerfile includes Playwright dependencies. For local development in Codespaces/devcontainers, you may need to manually install system packages or use a Docker setup with pre-installed browsers.

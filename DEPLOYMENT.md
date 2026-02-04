# Railway Deployment Guide

## Prerequisites

1. **Railway Account**: Sign up at [railway.app](https://railway.app)
2. **Discord Bot Token**: Create bot at [discord.com/developers](https://discord.com/developers/applications)
3. **GitHub Account**: Fork or clone this repository

---

## Step 1: Create Railway Project

### 1.1 New Project

1. Go to [railway.app/dashboard](https://railway.app/dashboard)
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Choose **"Apollomakesit/P4K-DBS"** (or your fork)
5. Click **"Deploy Now"**

### 1.2 Add Volume for Database

**CRITICAL**: Without a volume, your database will be deleted on every restart!

1. In your project, click **"New"** → **"Volume"**
2. Set **Mount Path**: `/data`
3. Click **"Add Volume"**
4. Railway will restart your service automatically

---

## Step 2: Configure Environment Variables

### 2.1 Required Variables

1. In your project, click on your service
2. Go to **"Variables"** tab
3. Add these **required** variables:

```bash
# REQUIRED
DISCORD_TOKEN=your_bot_token_here

# REQUIRED - Your Discord user ID
ADMIN_USER_IDS=your_user_id

# REQUIRED - Use volume path
DATABASE_PATH=/data/pro4kings.db
DATABASE_BACKUP_PATH=/data/backups
```

### 2.2 Get Your Discord User ID

1. Open Discord
2. Go to **Settings** → **Advanced** → Enable **"Developer Mode"**
3. Right-click your username anywhere
4. Click **"Copy User ID"**
5. Paste as `ADMIN_USER_IDS` value

### 2.3 Get Discord Bot Token

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click your application (or create new)
3. Go to **"Bot"** section
4. Click **"Reset Token"** → Copy token
5. Paste as `DISCORD_TOKEN` value

**NEVER** share your bot token publicly!

### 2.4 Optional Variables

See [CONFIGURATION.md](CONFIGURATION.md) for all available options.

---

## Step 3: Enable Bot Permissions

### 3.1 Bot Intents

1. In Discord Developer Portal, go to **"Bot"** section
2. Enable these **Privileged Gateway Intents**:
   - ✅ **Presence Intent** (optional)
   - ✅ **Server Members Intent** (optional)
   - ✅ **Message Content Intent** (required)
3. Click **"Save Changes"**

### 3.2 Invite Bot to Server

1. Go to **"OAuth2"** → **"URL Generator"**
2. Select **Scopes**:
   - ☑️ `bot`
   - ☑️ `applications.commands`
3. Select **Bot Permissions**:
   - ☑️ `Send Messages`
   - ☑️ `Embed Links`
   - ☑️ `Use Slash Commands`
   - ☑️ `Read Message History`
4. Copy generated URL
5. Open in browser and invite to your server

---

## Step 4: Deploy and Verify

### 4.1 Check Deployment

1. In Railway, go to **"Deployments"** tab
2. Click latest deployment
3. Check logs for:
```
✅ {BotName} is now running!
✅ Environment verification passed
✅ Synced X slash commands
🚀 All systems operational!
```

### 4.2 Test in Discord

Run these commands to verify:

```
/health
# Should show all systems operational

/config
# Should show current configuration

/stats
# Should show database stats (may be 0 initially)
```

### 4.3 Common Issues

#### Bot shows offline
- Check `DISCORD_TOKEN` is correct
- Verify bot has Message Content Intent enabled
- Check Railway logs for errors

#### "Interaction Failed" errors
- Bot hasn't registered slash commands yet (wait 5 minutes)
- Try running `!p4k sync` in Discord
- Restart Railway service

#### Database keeps resetting
- Volume not mounted! Go back to Step 1.2
- Verify `DATABASE_PATH=/data/pro4kings.db`

#### 503 or rate limit errors
- Normal, bot has retry logic
- Reduce `SCRAPER_MAX_CONCURRENT` to 3
- Increase intervals (double all values)

---

## Step 5: Monitor and Maintain

### 5.1 Regular Monitoring

**Weekly**:
```
/health
# Check all tasks are running

/stats
# Verify data is accumulating
```

**Monthly**:
```
/backup_database
# Create backup before cleanup

/cleanup_old_data dry_run:true
# Preview what will be deleted

/cleanup_old_data dry_run:false confirm:true
# Actually delete old data
```

### 5.2 Railway Dashboard

1. **Metrics**: Monitor CPU, RAM, network usage
2. **Logs**: Check for errors or warnings
3. **Volume**: Monitor disk space usage

### 5.3 Alerts Setup

If you set `ADMIN_USER_IDS`, you'll receive Discord DMs when:
- Tasks crash and restart
- Scraping fails repeatedly
- Database errors occur

---

## Step 6: Advanced Configuration

### 6.1 Performance Tuning

> 🔥 **Note**: panel.pro4kings.ro has a 30-connection shared hosting limit. Don't exceed these values.

**For faster scraping** (more Railway resources, but respect server limits):
```bash
SCRAPER_MAX_CONCURRENT=5
SCRAPER_RATE_LIMIT=10.0
SCRAPE_ACTIONS_INTERVAL=15
```

**For lower resources** (hobby plan):
```bash
SCRAPER_MAX_CONCURRENT=3
SCRAPER_RATE_LIMIT=8.0
SCRAPE_ACTIONS_INTERVAL=60
```

### 6.2 Data Retention

**Keep less data** (save space):
```bash
ACTIONS_RETENTION_DAYS=30
LOGIN_EVENTS_RETENTION_DAYS=7
PROFILE_HISTORY_RETENTION_DAYS=60
```

**Keep more data** (more history):
```bash
ACTIONS_RETENTION_DAYS=180
LOGIN_EVENTS_RETENTION_DAYS=90
PROFILE_HISTORY_RETENTION_DAYS=365
```

### 6.3 Logging

**Debug mode** (troubleshooting):
```bash
LOG_LEVEL=DEBUG
LOG_MAX_BYTES=20971520  # 20 MB
LOG_BACKUP_COUNT=10
```

**Production mode** (normal):
```bash
LOG_LEVEL=INFO
LOG_MAX_BYTES=10485760  # 10 MB
LOG_BACKUP_COUNT=5
```

---

## Troubleshooting

### Bot Crashes on Startup

**Check logs for**:
```bash
# Missing token
❌ ERROR: DISCORD_TOKEN not found!
# Solution: Add DISCORD_TOKEN variable

# Database directory not writable
❌ Database directory /data is not writable!
# Solution: Check volume mount

# Invalid token
❌ 401 Unauthorized
# Solution: Reset token in Discord Developer Portal
```

### High Memory Usage

1. Check `/health` for memory stats
2. Reduce batch sizes:
```bash
ACTIONS_FETCH_LIMIT=100
PROFILES_UPDATE_BATCH=100
```
3. Run cleanup:
```bash
/cleanup_old_data dry_run:false confirm:true
```

### Slow Response Times

1. Check Railway metrics for CPU/RAM
2. Increase task intervals:
```bash
SCRAPE_ACTIONS_INTERVAL=60
UPDATE_PROFILES_INTERVAL=300
```
3. Consider upgrading Railway plan

### Database Corruption

1. Check logs for errors
2. Restore from backup:
```bash
# In Railway CLI
railway run cp /data/backups/pro4kings_backup_*.db /data/pro4kings.db
```
3. Restart service

---

## Cost Estimation

### Railway Pricing (as of 2026)

**Hobby Plan** (Free):
- $5 credit/month
- ~500 hours runtime
- ~1 GB database
- **Sufficient for small servers**

**Pro Plan** ($20/month):
- Unlimited runtime
- Larger volumes
- Better performance
- **Recommended for large servers**

**Estimated Usage**:
- CPU: ~5-10% average
- RAM: ~100-200 MB
- Network: ~1-2 GB/month
- Disk: ~500 MB database + logs

---

## Security Best Practices

1. **Never commit `.env` file** to Git
2. **Rotate bot token** every 6 months
3. **Limit admin users** to trusted individuals only
4. **Enable 2FA** on Discord account
5. **Monitor logs** for unauthorized access attempts
6. **Regular backups** before major changes

---

## Next Steps

After successful deployment:

1. Read [COMMANDS.md](COMMANDS.md) for all available commands
2. Read [CONFIGURATION.md](CONFIGURATION.md) for tuning options
3. Join our Discord for support (link in README)
4. Star the repository if you find it useful!

---

## Support

- **Issues**: [GitHub Issues](https://github.com/Apollomakesit/P4K-DBS/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Apollomakesit/P4K-DBS/discussions)
- **Discord**: Check README for link

---

**Deployment complete!** 🎉

Your bot should now be running 24/7 on Railway, automatically monitoring Pro4Kings and tracking all player activity.

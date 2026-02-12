# Ark - Railway Deployment Guide

**Last Updated**: 2026-02-10
**Status**: Production deployment working ✅

## Quick Deploy

```bash
# Make changes locally
git add .
git commit -m "Your changes"
git push

# Railway auto-deploys in ~30 seconds
```

## Architecture

**Production Setup:**
```
Railway Container
└── launcher.py (main process)
    ├── Bot Thread (main) - Slack Socket Mode listener
    └── Scheduler Thread (daemon) - Reminder checker (every 30s)
```

**Key Files:**
- `bot.py` - Slack event listener (mentions + DMs)
- `scheduler.py` - Reminder checker loop
- `launcher.py` - Starts both as threads
- `railway.toml` - Railway deployment config
- `Procfile` - Alternative start command (overridden by railway.toml)

## Railway Configuration

### railway.toml (CRITICAL)

```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "python launcher.py"  # MUST be launcher.py, not bot.py
healthcheckPath = ""
restartPolicyType = "always"
```

**⚠️ WARNING**: `railway.toml` overrides `Procfile`. If you change start command, update railway.toml.

### Environment Variables (Railway Dashboard)

Required:
- `SLACK_BOT_TOKEN` - Bot User OAuth Token (starts with xoxb-)
- `SLACK_APP_TOKEN` - App-Level Token for Socket Mode (starts with xapp-)
- `SLACK_SIGNING_SECRET` - From Basic Information page
- `ANTHROPIC_API_KEY` - Claude API key

**IMPORTANT**: Railway UI adds trailing newlines when pasting - code must `.strip()` all env vars.

## Deployment Checklist

### Before First Deploy

- [ ] Create Railway project
- [ ] Connect GitHub repo (`stanfinance1/ark-bot`)
- [ ] Add all environment variables (with .strip() in code)
- [ ] Enable auto-deploy on push
- [ ] Verify `railway.toml` uses `launcher.py`

### After Deploy

- [ ] Check logs show: "Starting Ark with bot and scheduler..."
- [ ] Check logs show: "Scheduler thread started"
- [ ] Check logs show: "Ark is online. Listening for messages."
- [ ] Check logs show: "Ark reminder scheduler starting..."
- [ ] Test bot responds to @mention
- [ ] Test bot responds to DM
- [ ] Create test reminder for 1 minute - verify it fires

### Troubleshooting Deploy

**Scheduler not starting?**
```bash
# Check Railway logs - should see:
2026-02-10 22:33:10,244 [INFO] Starting Ark with bot and scheduler...
2026-02-10 22:33:10,244 [INFO] Scheduler thread started
2026-02-10 22:33:10,244 [INFO] Starting bot in main thread...
2026-02-10 22:33:10,518 [INFO] Ark is online. Listening for messages.
2026-02-10 22:33:11,019 [INFO] Ark reminder scheduler starting... (timezone: America/Los_Angeles)
```

If missing scheduler messages:
1. Check `railway.toml` startCommand is `launcher.py` not `bot.py`
2. Check `launcher.py` uses threading not multiprocessing
3. Verify Railway rebuilt after pushing changes

**Bot not responding?**
1. Check Slack App has "Messages Tab" enabled in App Home
2. Check environment variables are set correctly
3. Check Socket Mode is enabled
4. Check bot is invited to channels where it's mentioned

**Reminders not firing?**
1. Verify scheduler is running (see logs above)
2. Check reminder timezone matches user expectations
3. Check Railway logs for "Found X due reminder(s)" when reminder should fire
4. Verify reminder time hasn't passed yet

## Architecture Decisions

### Why Threading Instead of Multiprocessing?

**Problem**: Railway doesn't support multiprocessing well
- Processes fail silently
- No good way to share state
- Memory/CPU restrictions

**Solution**: Use threading
- Scheduler runs as daemon thread (dies with main thread)
- Bot runs in main thread (blocks forever)
- Both share same Python process
- Works reliably on Railway

### Why launcher.py Instead of bot.py?

**Need**: Run two tasks concurrently (bot listener + reminder scheduler)

**Options considered:**
1. ❌ Two Railway services - costs 2x, overkill
2. ❌ Multiprocessing - doesn't work on Railway
3. ✅ Threading in launcher.py - simple, works, free

**Implementation**:
```python
# launcher.py
scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()
run_bot()  # Blocks forever in main thread
```

## Common Gotchas

### 1. railway.toml vs Procfile

**Precedence**: `railway.toml` > `Procfile` > Auto-detection

If you have both files, Railway uses railway.toml. The Procfile is ignored.

### 2. Environment Variable Newlines

Railway UI adds `\n` when pasting secrets. Always:
```python
token = os.environ["SLACK_BOT_TOKEN"].strip()  # MUST .strip()
```

### 3. Timezones

Railway runs in UTC. All datetime operations must use:
```python
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo("America/Los_Angeles"))
```

Never use `datetime.now()` without timezone for user-facing times.

### 4. Daemon Threads

Daemon threads automatically exit when main thread exits. Perfect for scheduler:
```python
thread = threading.Thread(target=task, daemon=True)  # Will exit when bot exits
```

Non-daemon threads would prevent clean shutdown.

## Monitoring

### Health Checks

Railway logs every startup message. After deploy, verify:
1. Container starts without errors
2. Both threads start (see logs above)
3. Bot connects to Slack successfully
4. Scheduler begins checking loop

### Ongoing Monitoring

Check Railway logs periodically for:
- Crashes/restarts (should be rare)
- Rate limit warnings from Claude API
- Failed reminder sends
- Database errors

### Costs

- Railway: ~$5/month (Hobby plan)
- Claude API: ~$0.015 per message (Sonnet 4.5)
- Total: ~$5-10/month depending on usage

## Rollback Procedure

If deploy breaks:
```bash
# Find last working commit
git log

# Revert to working version
git reset --hard <commit-hash>
git push --force

# Railway will auto-deploy the old version
```

**Better approach**: Test locally first
```bash
# Run locally before pushing
python launcher.py

# Should see both bot and scheduler start
# Test in Slack before deploying
```

## Related Documentation

- **Task Log**: `task-logs/2026-02-10/task-011-ark-scheduler-fix-railway-deployment.md`
- **Memory**: `MEMORY.md` - Critical lessons learned section
- **Code**: All files in `claude-only/ark/`

---

**Last successful deploy**: 2026-02-10 (commit `bce0c24`)
**Current version**: Reminders working, multi-timezone support, threading architecture

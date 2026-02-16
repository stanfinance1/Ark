# Deploying Business Intelligence Tools to Ark (Railway)

**Date**: 02.16.2026
**Changes**: Added 3 new API tools for Shopify, Meta Ads, and SKIO real-time metrics

## What Was Added

### New Tools (3 total):
1. **get_shopify_metrics** - Fetch real-time Shopify sales data
   - Metrics: Orders, Gross Sales, Net Sales, AOV, Discounts, Returns
   - Timeframes: today, yesterday, this_week, last_week, this_month, last_month, last_7_days, last_30_days

2. **get_meta_ads_performance** - Fetch Meta Ads campaign performance
   - Metrics: Spend, Impressions, Clicks, Conversions, CPA, CTR, CPC, CPM
   - Timeframes: today, yesterday, last_7d, last_14d, last_30d, this_month, last_month
   - Includes performance indicators (vs $45 target CPA, $55 warning threshold)

3. **get_skio_health** - Fetch subscription health metrics
   - Metrics: Active/Cancelled/Paused subs, Churn rate, Avg cycles, Churn scores
   - Optional: Top 10 high-risk subscribers (churn score > 0.7)

### Files Modified:
- `tools.py` - Added 3 tool definitions + 3 execution functions (~200 lines)
- `config.py` - Updated system prompt to mention new BI capabilities

### Requirements:
- All dependencies already in `requirements.txt` (python-dotenv, requests)
- API credentials already in `.env` file (SHOPIFY_*, META_*, SKIO_API_KEY)

## Deployment Steps

### Option 1: Git Push (Recommended)
```bash
cd /c/Users/stan/OneDrive/Desktop/Agentic\ Workflows/claude-only/ark

# Stage changes
git add tools.py config.py

# Commit
git commit -m "Add business intelligence tools: Shopify, Meta Ads, SKIO APIs"

# Push to Railway (triggers auto-deploy)
git push origin main
```

### Option 2: Railway CLI
```bash
# Install Railway CLI (if not already)
npm install -g @railway/cli

# Login
railway login

# Link project
cd /c/Users/stan/OneDrive/Desktop/Agentic\ Workflows/claude-only/ark
railway link

# Deploy
railway up
```

### Option 3: Railway Dashboard
1. Go to https://railway.app/dashboard
2. Open `ark-bot` project
3. Go to **Deployments** tab
4. Click **Deploy** → **Redeploy from GitHub**

## Testing After Deployment

In Slack, test each tool:

1. **Shopify Metrics**:
   - "What are our Shopify sales today?"
   - "How many orders did we get this week?"
   - "Show me revenue for last month"

2. **Meta Ads Performance**:
   - "How are our Meta ads performing?"
   - "What's our current CPA?"
   - "Show me ad spend for the last 7 days"

3. **SKIO Health**:
   - "How many active subscribers do we have?"
   - "What's our churn rate?"
   - "Show me subscription health"
   - "Who's at high risk of churning?" (includes churn risk list)

## Expected Results

Ark should now respond with real-time data directly from the APIs, formatted like this:

```
=== SHOPIFY METRICS (TODAY) ===
Period: 2026-02-16 00:00 to 2026-02-16 15:30

Orders:        12
Gross Sales:   $567.89
Discounts:    -$45.00
Returns:      -$0.00
Net Sales:     $522.89
Shipping:     +$60.00
Taxes:        +$45.67
Total Sales:   $628.56
AOV (Avg):     $43.57
```

## Rollback (if needed)

If the deployment causes issues:

```bash
# Revert the commit
git revert HEAD

# Push to trigger rollback
git push origin main
```

Or use Railway Dashboard → Deployments → Rollback to previous deployment.

## Environment Variables

All required API credentials are already set in Railway:
- `SHOPIFY_CLIENT_ID`
- `SHOPIFY_CLIENT_SECRET`
- `SHOPIFY_STORE`
- `META_ACCESS_TOKEN`
- `META_AD_ACCOUNT_ID`
- `SKIO_API_KEY`

To verify: Railway Dashboard → ark-bot → Variables tab

## Notes

- The new tools use the same .env file as the local tools (claude-only/.env)
- Token caching is built-in for Shopify (24-hour expiry, auto-refresh)
- Meta Ads token expires periodically - refresh in Meta Business Suite when needed
- All tools have error handling and return user-friendly error messages
- No new dependencies needed - all packages already in requirements.txt

# Heroku Scheduler Setup

## Required Add-ons
1. **Heroku Postgres** (hobby-dev free tier)
2. **Heroku Scheduler** (free tier)

## Environment Variables
Set these in Heroku dashboard:
- `FLASK_ENV=production`
- `DATABASE_URL` (auto-set by Postgres add-on)

## Scheduler Jobs

### Daily Data Refresh (6am CDT = 11am UTC)
```bash
python scripts/daily_update.py && python scripts/update_model_stats.py
```
- Schedule: Daily at 11:00 AM UTC
- Description: Fetch NBA stats and update model evaluations

### Hourly PrizePicks Refresh
```bash
python scripts/fetch_data.py && python scripts/update_model_stats.py
```
- Schedule: Every hour at :00 minutes
- Description: Update PrizePicks lines and recompute predictions

## Setup Commands
```bash
# Create app
heroku create your-app-name

# Add Postgres
heroku addons:create heroku-postgresql:hobby-dev

# Add Scheduler
heroku addons:create heroku-scheduler

# Deploy
git push heroku main

# Setup scheduler jobs in Heroku dashboard
```

## Differences from Render
- No automatic cron job configuration via YAML
- Must manually configure jobs in Heroku Scheduler dashboard
- Free tier includes 1 dyno (web) + scheduler jobs
- Postgres hobby-dev is free (no 90-day limit)

#!/bin/bash
echo "Updating Database..."
python3 scripts/daily_update.py

echo "Ensuring no duplicate entries..."
python3 scripts/dedup.py

echo "📡 Fetching PrizePicksdata..."
python3 scripts/fetch_data.py

echo "📤 Pushing to GitHub..."
git add data/
git diff --staged --quiet || git commit -m "chore: refresh data"
git push

echo "✅ Done."

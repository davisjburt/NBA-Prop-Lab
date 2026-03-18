#!/bin/bash

echo "📡 Fetching data..."
python3 scripts/fetch_data.py

echo "📤 Pushing to GitHub..."
git add data/
git diff --staged --quiet || git commit -m "chore: refresh data"
git push

echo "✅ Done."

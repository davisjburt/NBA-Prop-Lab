#!/usr/bin/env bash
set -euo pipefail

# Load .env if present so we get RENDER_DEPLOY_HOOK_URL, etc.
if [ -f .env ]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

echo "Updating database..."
python3 scripts/daily_update.py

echo "Ensuring no duplicate entries..."
python3 scripts/dedup.py

echo "📡 Fetching PrizePicks data..."
python3 scripts/fetch_data.py

echo "📤 Pushing to GitHub..."
git add data/

# Only commit if there are staged changes
if ! git diff --staged --quiet; then
  git commit -m "chore: refresh data"
  git push
else
  echo "No changes to commit."
fi

echo "🚀 Triggering Render deploy..."

if [ -z "${RENDER_DEPLOY_HOOK_URL:-}" ]; then
  echo "RENDER_DEPLOY_HOOK_URL is not set. Skipping deploy."
else
  # Render deploy hook: simple GET/POST is enough
  curl -fsS "$RENDER_DEPLOY_HOOK_URL" \
    && echo "Render deploy triggered." \
    || echo "Failed to trigger Render deploy."
fi

echo "✅ Done."

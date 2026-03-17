"""
scripts/fetch_data.py
---------------------
Fetches external API data and writes it to data/*.json so the Flask app
never needs to make outbound calls at request time.

Called by GitHub Actions on a schedule. The three output files are
committed back to the repo and read by props.py at runtime.
"""

import json, os, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.nba_fetcher import fetch_opponent_defense, fetch_todays_matchups
from app.services.prizepicks import fetch_prizepicks_lines

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)


def write(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"✅  Wrote {filename} ({len(data)} entries)")


errors = []

print("📡  Fetching opponent defense stats...")
try:
    defense = fetch_opponent_defense()
    write("opponent_defense.json", defense)
except Exception as e:
    print(f"❌  fetch_opponent_defense failed: {e}")
    errors.append("opponent_defense")

print("📡  Fetching today's matchups...")
try:
    matchups = fetch_todays_matchups()
    write("todays_matchups.json", matchups)
except Exception as e:
    print(f"❌  fetch_todays_matchups failed: {e}")
    errors.append("todays_matchups")

print("📡  Fetching PrizePicks lines...")
try:
    lines = fetch_prizepicks_lines()
    write("prizepicks_lines.json", lines)
except Exception as e:
    print(f"❌  fetch_prizepicks_lines failed: {e}")
    errors.append("prizepicks_lines")

if errors:
    print(f"\n⚠️  {len(errors)} fetch(es) failed: {', '.join(errors)}")
    print("Existing data files are preserved — app will serve stale data.")
    sys.exit(1)

print("\n🏁  All data files refreshed.")
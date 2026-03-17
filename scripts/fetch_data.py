"""
scripts/fetch_data.py
---------------------
Runs on your laptop. Fetches external data, queries the DB, does all the
heavy computation, and writes pre-computed JSON files to data/.

Render just reads these files and returns them instantly — zero computation,
zero timeout risk.

Files written:
  data/prizepicks_results.json   ← full PrizePicks board with confidence scores
  data/prizepicks_parlays.json   ← pre-computed 2 and 3-leg parlays
  data/trending.json             ← hot streaks + top hitters
  data/opponent_defense.json     ← raw NBA opponent defense stats
  data/todays_matchups.json      ← today's game matchups
"""

import json, os, sys
from itertools import combinations
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)


def write(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    count = len(data) if isinstance(data, (list, dict)) else "?"
    print(f"✅  Wrote {filename} ({count} entries)")


errors = []

# ── Step 1: Fetch external API data ──────────────────────────────────────────

from app.services.nba_fetcher import fetch_opponent_defense, fetch_todays_matchups
from app.services.prizepicks import fetch_prizepicks_lines

print("📡  Fetching opponent defense stats...")
try:
    opp_defense = fetch_opponent_defense()
    write("opponent_defense.json", opp_defense)
except Exception as e:
    print(f"❌  fetch_opponent_defense failed: {e}")
    opp_defense = {}
    errors.append("opponent_defense")

print("📡  Fetching today's matchups...")
try:
    todays_matchups = fetch_todays_matchups()
    write("todays_matchups.json", todays_matchups)
except Exception as e:
    print(f"❌  fetch_todays_matchups failed: {e}")
    todays_matchups = {}
    errors.append("todays_matchups")

print("📡  Fetching PrizePicks lines...")
try:
    pp_lines = fetch_prizepicks_lines()
    write("prizepicks_lines.json", pp_lines)
except Exception as e:
    print(f"❌  fetch_prizepicks_lines failed: {e}")
    pp_lines = []
    errors.append("prizepicks_lines")


# ── Step 2: Load DB data ──────────────────────────────────────────────────────

print("\n🗄️   Loading player data from DB...")

from app import create_app
from app.models.models import Player, PlayerGameStat
from app.services.hit_rate import (
    hit_rate, hit_rate_combo, COMBO_STATS,
    calculate_streak, extract_opponent, clean_avg,
    matchup_multiplier, confidence_score
)
from app.services.prizepicks import normalize
import pandas as pd

app = create_app()

SINGLE_STATS = ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]
STAT_LABELS = {
    "pts": "Points",   "reb": "Rebounds",    "ast": "Assists",
    "stl": "Steals",   "blk": "Blocks",      "fg3m": "3PM",
    "tov": "Turnovers","pr":  "PTS+REB",      "pa":  "PTS+AST",
    "ra":  "REB+AST",  "pra": "PTS+REB+AST", "sa":  "STL+AST",
    "bs":  "BLK+STL"
}


def round_to_half(val):
    return round(val * 2) / 2


def rows_to_df(rows):
    return pd.DataFrame([{
        "date": str(r.date), "matchup": r.matchup, "location": r.location,
        "pts": r.pts, "reb": r.reb, "ast": r.ast,
        "stl": r.stl, "blk": r.blk, "fg3m": r.fg3m, "tov": r.tov
    } for r in rows])


with app.app_context():
    print("   Loading players...")
    all_players = Player.query.all()
    print(f"   Loading game stats for {len(all_players)} players...")
    all_stats = PlayerGameStat.query.order_by(PlayerGameStat.date.desc()).all()
    print(f"   Loaded {len(all_stats)} game stat rows")

    stats_by_player = defaultdict(list)
    for s in all_stats:
        stats_by_player[s.player_id].append(s)

    player_map = {normalize(p.name): p for p in all_players}


    # ── Step 3: Compute PrizePicks results ───────────────────────────────────

    print("\n⚙️   Computing PrizePicks results...")

    def find_player(name_key):
        if name_key in player_map:
            return player_map[name_key]
        for key, player in player_map.items():
            if name_key in key or key in name_key:
                return player
        return None

    pp_results = []

    if pp_lines:
        for entry in pp_lines:
            player = find_player(entry["name_key"])
            if not player:
                continue
            rows = stats_by_player.get(player.id, [])
            if not rows:
                continue

            df   = rows_to_df(rows)
            stat = entry["stat"]
            line = entry["line"]

            team_abbr  = (entry.get("team") or player.team_abbr or "").upper()
            today_game = todays_matchups.get(team_abbr)

            if today_game:
                opponent_abbr    = today_game["opponent"]
                current_location = today_game["location"]
            else:
                opponent_abbr    = extract_opponent(rows[0].matchup)
                current_location = rows[0].location

            if stat in COMBO_STATS:
                cols         = COMBO_STATS[stat]
                values       = df[cols].sum(axis=1).tolist()
                primary_stat = cols[0]
            elif stat in df.columns:
                values       = df[stat].tolist()
                primary_stat = stat
            else:
                continue

            avg_l5     = clean_avg(values, n=5)
            avg_l10    = clean_avg(values, n=10)
            avg_season = clean_avg(values)

            hr_l5     = hit_rate_combo(df, stat, line, last_n=5)  if stat in COMBO_STATS else hit_rate(df, stat, line, last_n=5)
            hr_l10    = hit_rate_combo(df, stat, line, last_n=10) if stat in COMBO_STATS else hit_rate(df, stat, line, last_n=10)
            hr_season = hit_rate_combo(df, stat, line)            if stat in COMBO_STATS else hit_rate(df, stat, line)

            if "error" in hr_l10:
                continue

            edge   = round(avg_l5 - line, 1) if avg_l5 is not None else None
            streak = hr_l10.get("streak", {"count": 0, "type": "none"})
            mult   = matchup_multiplier(opponent_abbr, primary_stat, opp_defense)

            home_df = df[df["location"] == "Home"]
            away_df = df[df["location"] == "Road"]
            if stat in COMBO_STATS:
                cols    = COMBO_STATS[stat]
                home_hr = (home_df[cols].sum(axis=1) > line).mean() if not home_df.empty else 0.5
                away_hr = (away_df[cols].sum(axis=1) > line).mean() if not away_df.empty else 0.5
            else:
                home_hr = (home_df[stat] > line).mean() if not home_df.empty else 0.5
                away_hr = (away_df[stat] > line).mean() if not away_df.empty else 0.5

            home_away_bonus = 0.0
            if current_location == "Home" and home_hr > away_hr + 0.05:
                home_away_bonus = 1.0
            elif current_location == "Road" and away_hr > home_hr + 0.05:
                home_away_bonus = 1.0

            conf = confidence_score(
                hit_rate_l5     = hr_l5.get("hit_rate")     if "error" not in hr_l5     else None,
                hit_rate_l10    = hr_l10.get("hit_rate"),
                hit_rate_season = hr_season.get("hit_rate") if "error" not in hr_season else None,
                edge            = edge,
                matchup_mult    = mult,
                streak_count    = streak["count"],
                streak_type     = streak["type"],
                home_away_bonus = home_away_bonus,
            )

            pp_results.append({
                "id":              player.id,
                "name":            player.name,
                "team":            player.team_abbr,
                "position":        player.position,
                "stat":            stat,
                "label":           entry["pp_stat_label"],
                "odds_type":       entry.get("odds_type", "standard"),
                "line":            line,
                "hit_rate":        hr_l10["hit_rate"],
                "hit_rate_l5":     hr_l5.get("hit_rate")     if "error" not in hr_l5     else None,
                "hit_rate_season": hr_season.get("hit_rate") if "error" not in hr_season else None,
                "avg_l5":          avg_l5,
                "avg_l10":         avg_l10,
                "avg_season":      avg_season,
                "edge":            edge,
                "hits":            hr_l10["hits"],
                "sample":          hr_l10["sample"],
                "matchup_mult":    mult,
                "opponent":        opponent_abbr,
                "location":        current_location,
                "streak":          streak,
                "confidence":      conf,
            })

        pp_results.sort(key=lambda x: x["confidence"], reverse=True)

    write("prizepicks_results.json", pp_results)


    # ── Step 4: Compute parlays ───────────────────────────────────────────────

    print("⚙️   Computing parlays...")

    candidates = [p for p in pp_results if p["confidence"] >= 65 and p["odds_type"] == "standard"][:30]

    def correlation_penalty(a, b):
        return 0.85 if a["team"] == b["team"] else 1.0

    parlays_2 = []
    for a, b in combinations(candidates, 2):
        penalty = correlation_penalty(a, b)
        score   = round((a["confidence"] + b["confidence"]) / 2 * penalty, 1)
        parlays_2.append({"legs": [a, b], "score": score, "correlated": penalty < 1.0})

    parlays_3 = []
    for a, b, c in combinations(candidates, 3):
        penalty = min(correlation_penalty(a, b), correlation_penalty(b, c), correlation_penalty(a, c))
        score   = round((a["confidence"] + b["confidence"] + c["confidence"]) / 3 * penalty, 1)
        parlays_3.append({"legs": [a, b, c], "score": score, "correlated": penalty < 1.0})

    parlays_2.sort(key=lambda x: x["score"], reverse=True)
    parlays_3.sort(key=lambda x: x["score"], reverse=True)

    write("prizepicks_parlays.json", {"two_leg": parlays_2[:10], "three_leg": parlays_3[:10]})


    # ── Step 5: Compute trending ──────────────────────────────────────────────

    print("⚙️   Computing trending...")

    hot_streaks = []
    top_hitters = []

    for player in all_players:
        rows = stats_by_player.get(player.id, [])[:20]
        if len(rows) < 3:
            continue
        df = rows_to_df(rows)

        for stat in SINGLE_STATS:
            values = df[stat].tolist()
            line   = round_to_half(df[stat].head(5).mean())
            if line <= 0:
                continue
            streak = calculate_streak(values, line)
            hr     = hit_rate(df, stat, line, last_n=10)
            if "error" in hr:
                continue
            base = {
                "id": player.id, "name": player.name,
                "team": player.team_abbr, "position": player.position,
                "stat": stat, "label": STAT_LABELS[stat],
                "line": line, "avg": round(df[stat].mean(), 1),
                "hit_rate": hr["hit_rate"], "sample": hr["sample"], "hits": hr["hits"],
            }
            if streak["type"] == "hit" and streak["count"] >= 3:
                hot_streaks.append({**base, "streak": streak["count"]})
            if hr["hit_rate"] >= 0.70 and hr["sample"] >= 5:
                top_hitters.append(base)

        for combo, cols in COMBO_STATS.items():
            df2              = df.copy()
            df2["combo_val"] = df2[cols].sum(axis=1)
            line   = round_to_half(df2["combo_val"].head(5).mean())
            if line <= 0:
                continue
            streak = calculate_streak(df2["combo_val"].tolist(), line)
            hr     = hit_rate_combo(df, combo, line, last_n=10)
            if "error" in hr:
                continue
            base = {
                "id": player.id, "name": player.name,
                "team": player.team_abbr, "position": player.position,
                "stat": combo, "label": STAT_LABELS[combo],
                "line": line, "avg": hr["avg"],
                "hit_rate": hr["hit_rate"], "sample": hr["sample"], "hits": hr["hits"],
            }
            if streak["type"] == "hit" and streak["count"] >= 3:
                hot_streaks.append({**base, "streak": streak["count"]})
            if hr["hit_rate"] >= 0.70 and hr["sample"] >= 5:
                top_hitters.append(base)

    hot_streaks.sort(key=lambda x: x["streak"], reverse=True)
    top_hitters.sort(key=lambda x: x["hit_rate"], reverse=True)

    write("trending.json", {"hot_streaks": hot_streaks[:30], "top_hitters": top_hitters[:30]})


# ── Done ──────────────────────────────────────────────────────────────────────

if errors:
    print(f"\n⚠️  {len(errors)} fetch(es) failed: {', '.join(errors)}")

print("\n🏁  All done. Run ./refresh.sh to commit and push.")
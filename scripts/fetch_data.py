"""
scripts/fetch_data.py
---------------------
Fetches external data, queries the DB, does all the heavy computation,
and writes pre-computed JSON files to data/.

Files written:
  data/prizepicks_results.json   ← full PrizePicks board with confidence scores
  data/prizepicks_parlays.json   ← pre-computed 2 and 3-leg parlays
  data/trending.json             ← hot streaks + top hitters
  data/opponent_defense.json     ← raw NBA opponent defense stats
  data/todays_matchups.json      ← today's game matchups
  data/moneylines.json           ← tonight's game predictions  ← NEW
"""

from pathlib import Path
import json
import os
import sys
from itertools import combinations
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_PATH = Path(DATA_DIR)

errors: list[str] = []


def write_safe(filename, data):
    """Write JSON atomically: only replace file if write succeeds."""
    path = DATA_PATH / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, default=str)
    tmp.replace(path)
    count = len(data) if isinstance(data, (list, dict)) else "?"
    print(f"✅  Wrote {filename} ({count} entries)")


def main():
    global errors

    # ── Step 1: Fetch external API data ──────────────────────────────────────
    from app.services.nba_fetcher import (
        fetch_opponent_defense,
        fetch_todays_matchups,
        fetch_team_records,
        fetch_h2h_season,
        fetch_injuries,
    )
    from app.services.prizepicks import (
        fetch_prizepicks_lines,
        PrizePicksError,
    )

    print("📡  Fetching opponent defense stats...")
    try:
        opp_defense = fetch_opponent_defense()
        write_safe("opponent_defense.json", opp_defense)
    except Exception as e:
        print(f"❌  fetch_opponent_defense failed: {e}")
        opp_defense = {}
        errors.append("opponent_defense")

    print("📡  Fetching today's matchups...")
    try:
        todays_matchups = fetch_todays_matchups()
        write_safe("todays_matchups.json", todays_matchups)
    except Exception as e:
        print(f"❌  fetch_todays_matchups failed: {e}")
        todays_matchups = {}
        errors.append("todays_matchups")

    print("📡  Fetching team records...")
    try:
        team_records = fetch_team_records()
        write_safe("team_records.json", team_records)
    except Exception as e:
        print(f"❌  fetch_team_records failed: {e}")
        team_records = {}
        errors.append("team_records")

    print("📡  Fetching H2H data...")
    try:
        h2h_data = fetch_h2h_season()
        write_safe("h2h_data.json", h2h_data)
    except Exception as e:
        print(f"❌  fetch_h2h_season failed: {e}")
        h2h_data = {}
        errors.append("h2h_data")

    print("📡  Fetching injury report...")
    try:
        injuries_raw = fetch_injuries()
    except Exception as e:
        print(f"❌  fetch_injuries failed: {e}")
        injuries_raw = []
        errors.append("injuries")

    print("📡  Fetching PrizePicks lines...")
    pp_lines = None
    try:
        pp_lines = fetch_prizepicks_lines()
        write_safe("prizepicks_lines.json", pp_lines)
    except PrizePicksError as e:
        msg = str(e)
        if "403" in msg:
            print(
                "⚠️  fetch_prizepicks_lines got 403 (likely blocked). "
                "Keeping existing file."
            )
            errors.append("prizepicks_lines_403")
            pp_lines = None
        else:
            print(f"❌  fetch_prizepicks_lines failed (hard): {e}")
            errors.append("prizepicks_lines")
            raise
    except Exception as e:
        print(f"❌  fetch_prizepicks_lines failed (unexpected): {e}")
        errors.append("prizepicks_lines")
        raise

    # ── Step 2: Load DB data ────────────────────────────────────────────────
    print("\n🗄️   Loading player data from DB...")

    from app import create_app
    from app.models.models import (
        Player,
        PlayerGameStat,
        ModelPropEval,
        ModelMoneylineEval,
        db,
    )
    import datetime

    from app.services.hit_rate import (
        hit_rate,
        hit_rate_combo,
        COMBO_STATS,
        calculate_streak,
        extract_opponent,
        clean_avg,
        matchup_multiplier,
        confidence_score,
    )
    from app.services.prizepicks import normalize
    from app.services.moneyline import compute_game_prediction
    import pandas as pd

    app = create_app()

    SINGLE_STATS = ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]
    STAT_LABELS = {
        "pts": "Points",   "reb": "Rebounds", "ast": "Assists",
        "stl": "Steals",   "blk": "Blocks",   "fg3m": "3PM",
        "tov": "Turnovers","pr":  "PTS+REB",   "pa":  "PTS+AST",
        "ra":  "REB+AST",  "pra": "PTS+REB+AST","sa": "STL+AST",
        "bs":  "BLK+STL",
    }

    def round_to_half(val):
        return round(val * 2) / 2

    def rows_to_df(rows):
        return pd.DataFrame([{
            "date": str(r.date), "matchup": r.matchup,
            "location": r.location, "min": r.min,
            "pts": r.pts, "reb": r.reb, "ast": r.ast,
            "stl": r.stl, "blk": r.blk, "fg3m": r.fg3m, "tov": r.tov,
        } for r in rows])

    with app.app_context():
        print("   Loading players...")
        all_players = Player.query.all()
        print(f"   Loading game stats for {len(all_players)} players...")
        all_stats = PlayerGameStat.query.order_by(
            PlayerGameStat.date.desc()
        ).all()
        print(f"   Loaded {len(all_stats)} game stat rows")

        stats_by_player = defaultdict(list)
        for s in all_stats:
            stats_by_player[s.player_id].append(s)

        player_map = {normalize(p.name): p for p in all_players}

        # ── Step 3: Enrich injuries with player avg pts ───────────────────
        print("\n⚙️   Enriching injury data with player averages...")
        player_pts_avg: dict[str, float] = {}
        for player in all_players:
            rows = stats_by_player.get(player.id, [])[:20]
            if rows:
                pts_vals = [r.pts for r in rows if r.pts is not None]
                if pts_vals:
                    import numpy as np
                    player_pts_avg[normalize(player.name)] = round(
                        float(np.mean(pts_vals)), 1
                    )

        injuries_enriched = []
        for inj in injuries_raw:
            name_key = normalize(inj["player_name"])

            # Fill team_abbr from DB if missing/blank
            player = player_map.get(name_key)
            if player and not inj.get("team_abbr"):
                inj["team_abbr"] = (player.team_abbr or "").upper()

            inj["player_avg_pts"] = player_pts_avg.get(name_key)
            injuries_enriched.append(inj)


        write_safe("injuries.json", injuries_enriched)

        # ── Step 4: Compute moneylines ────────────────────────────────────
        print("\n⚙️   Computing moneylines...")
        moneylines = []

        # Build unique game list from today's matchups
        seen_games = set()
        for team_abbr, info in todays_matchups.items():
            home = team_abbr if info["location"] == "Home" else info["opponent"]
            away = info["opponent"] if info["location"] == "Home" else team_abbr
            key  = f"{home}_{away}"
            if key in seen_games:
                continue
            seen_games.add(key)

            # H2H lookup
            h2h_key  = "_".join(sorted([home, away]))
            h2h_wins = h2h_data.get(h2h_key, {})
            h2h_dict = {
                "home_wins": h2h_wins.get(home, 0),
                "away_wins": h2h_wins.get(away, 0),
            }

            prediction = compute_game_prediction(
                home_abbr=home,
                away_abbr=away,
                team_stats=team_records,
                injuries=injuries_enriched,
                h2h=h2h_dict,
            )

            # Attach injury lists for display
            home_injuries = [
                i for i in injuries_enriched
                if i["team_abbr"].upper() == home.upper()
            ]
            away_injuries = [
                i for i in injuries_enriched
                if i["team_abbr"].upper() == away.upper()
            ]

            # Attach team record display info
            home_rec = team_records.get(home, {})
            away_rec = team_records.get(away, {})

            moneylines.append({
                **prediction,
                "home_team_name": home_rec.get("team_name", home),
                "away_team_name": away_rec.get("team_name", away),
                "home_w_pct":     home_rec.get("w_pct", 0.5),
                "away_w_pct":     away_rec.get("w_pct", 0.5),
                "home_w_l10":     home_rec.get("w_l10", 0),
                "home_l_l10":     home_rec.get("l_l10", 0),
                "away_w_l10":     away_rec.get("w_l10", 0),
                "away_l_l10":     away_rec.get("l_l10", 0),
                "home_injuries":  home_injuries,
                "away_injuries":  away_injuries,
                "h2h":            h2h_dict,
            })

        # Sort by confidence gap (biggest spread = most predictable)
        moneylines.sort(
            key=lambda x: abs(x["win_prob_home"] - 50),
            reverse=True
        )
        write_safe("moneylines.json", moneylines)

                # ── Log moneyline predictions for model statistics ────────────────
        today = datetime.date.today()
        ModelMoneylineEval.query.filter_by(date=today).delete()

        for g in moneylines:
            m = ModelMoneylineEval(
                date=today,
                home_abbr=g["home"],
                away_abbr=g["away"],
                predicted_winner=g["predicted_winner"],
                win_prob_home=g["win_prob_home"],
                win_prob_away=g["win_prob_away"],
                spread=g["spread"],
            )
            db.session.add(m)

        db.session.commit()


        # ── Step 5: Compute PrizePicks results ────────────────────────────
        print("\n⚙️   Computing PrizePicks results...")

        def find_player(name_key):
            if name_key in player_map:
                return player_map[name_key]
            for key, player in player_map.items():
                if name_key in key or key in name_key:
                    return player
            return None

        pp_results = []

        if pp_lines is not None:
            for entry in pp_lines:
                player = find_player(entry["name_key"])
                if not player:
                    continue
                rows = stats_by_player.get(player.id, [])
                if not rows:
                    continue

                df = rows_to_df(rows)
                stat = entry["stat"]
                line = entry["line"]

                team_abbr   = (entry.get("team") or player.team_abbr or "").upper()
                today_game  = todays_matchups.get(team_abbr)

                if today_game:
                    opponent_abbr    = today_game["opponent"]
                    current_location = today_game["location"]
                else:
                    opponent_abbr    = extract_opponent(rows[0].matchup)
                    current_location = rows[0].location

                if stat in COMBO_STATS:
                    cols   = COMBO_STATS[stat]
                    values = df[cols].sum(axis=1).tolist()
                    primary_stat = cols[0]
                elif stat in df.columns:
                    values = df[stat].tolist()
                    primary_stat = stat
                else:
                    continue

                avg_l5     = clean_avg(values, n=5)
                avg_l10    = clean_avg(values, n=10)
                avg_season = clean_avg(values)

                min_values    = df["min"].tolist()
                min_l5        = clean_avg(min_values, n=5)
                min_l10       = clean_avg(min_values, n=10)
                min_season    = clean_avg(min_values)
                minutes_ratio = None
                if min_l5 is not None and min_season not in (None, 0):
                    minutes_ratio = min_l5 / min_season

                hr_l5     = (hit_rate_combo(df, stat, line, last_n=5)
                             if stat in COMBO_STATS
                             else hit_rate(df, stat, line, last_n=5))
                hr_l10    = (hit_rate_combo(df, stat, line, last_n=10)
                             if stat in COMBO_STATS
                             else hit_rate(df, stat, line, last_n=10))
                hr_season = (hit_rate_combo(df, stat, line)
                             if stat in COMBO_STATS
                             else hit_rate(df, stat, line))

                if "error" in hr_l10:
                    continue

                edge   = round(avg_l5 - line, 1) if avg_l5 is not None else None
                streak = hr_l10.get("streak", {"count": 0, "type": "none"})
                mult   = matchup_multiplier(opponent_abbr, primary_stat, opp_defense)

                home_df = df[df["location"] == "Home"]
                away_df = df[df["location"] == "Road"]
                if stat in COMBO_STATS:
                    cols    = COMBO_STATS[stat]
                    home_hr = ((home_df[cols].sum(axis=1) > line).mean()
                               if not home_df.empty else 0.5)
                    away_hr = ((away_df[cols].sum(axis=1) > line).mean()
                               if not away_df.empty else 0.5)
                else:
                    home_hr = ((home_df[stat] > line).mean()
                               if not home_df.empty else 0.5)
                    away_hr = ((away_df[stat] > line).mean()
                               if not away_df.empty else 0.5)

                home_away_bonus = 0.0
                if current_location == "Home" and home_hr > away_hr + 0.05:
                    home_away_bonus = 1.0
                elif current_location == "Road" and away_hr > home_hr + 0.05:
                    home_away_bonus = 1.0

                conf = confidence_score(
                    hit_rate_l5=hr_l5.get("hit_rate") if "error" not in hr_l5 else None,
                    hit_rate_l10=hr_l10.get("hit_rate"),
                    hit_rate_season=hr_season.get("hit_rate") if "error" not in hr_season else None,
                    edge=edge,
                    matchup_mult=mult,
                    streak_count=streak["count"],
                    streak_type=streak["type"],
                    home_away_bonus=home_away_bonus,
                    minutes_avg_l5=min_l5,
                    minutes_avg_season=min_season,
                )

                pp_results.append({
                    "id": player.id,
                    "name": player.name,
                    "team": player.team_abbr,
                    "position": player.position,
                    "stat": stat,
                    "label": entry["pp_stat_label"],
                    "odds_type": entry.get("odds_type", "standard"),
                    "line": line,
                    "hit_rate": hr_l10["hit_rate"],
                    "hit_rate_l5": hr_l5.get("hit_rate") if "error" not in hr_l5 else None,
                    "hit_rate_season": hr_season.get("hit_rate") if "error" not in hr_season else None,
                    "avg_l5": avg_l5,
                    "avg_l10": avg_l10,
                    "avg_season": avg_season,
                    "edge": edge,
                    "hits": hr_l10["hits"],
                    "sample": hr_l10["sample"],
                    "matchup_mult": mult,
                    "opponent": opponent_abbr,
                    "location": current_location,
                    "streak": streak,
                    "confidence": conf,
                    "minutes_l5": min_l5,
                    "minutes_l10": min_l10,
                    "minutes_season": min_season,
                    "minutes_ratio": minutes_ratio,
                })

            pp_results.sort(key=lambda x: x["confidence"], reverse=True)

        write_safe("prizepicks_results.json", pp_results)

                # ── Log top prop picks for model statistics ───────────────────────
        today = datetime.date.today()
        ModelPropEval.query.filter_by(date=today).delete()

        by_stat: dict[str, list] = defaultdict(list)
        for p in pp_results:
            by_stat[p["stat"]].append(p)

        for stat, rows in by_stat.items():
            rows.sort(key=lambda x: x["confidence"], reverse=True)
            for row in rows[:10]:
                m = ModelPropEval(
                    date=today,
                    player_id=row["id"],
                    player_name=row["name"],
                    team_abbr=row["team"],
                    stat=stat,
                    line=row["line"],
                    confidence=row["confidence"],
                )
                db.session.add(m)

        db.session.commit()


        # ── Step 6: Compute parlays ───────────────────────────────────────
        print("⚙️   Computing parlays...")

        candidates = [
            p for p in pp_results
            if p["confidence"] >= 65 and p["odds_type"] == "standard"
        ][:30]

        def correlation_penalty(a, b):
            return 0.85 if a["team"] == b["team"] else 1.0

        parlays_2 = []
        for a, b in combinations(candidates, 2):
            penalty = correlation_penalty(a, b)
            score   = round((a["confidence"] + b["confidence"]) / 2 * penalty, 1)
            parlays_2.append({"legs": [a, b], "score": score, "correlated": penalty < 1.0})

        parlays_3 = []
        for a, b, c in combinations(candidates, 3):
            penalty = min(
                correlation_penalty(a, b),
                correlation_penalty(b, c),
                correlation_penalty(a, c),
            )
            score = round((a["confidence"] + b["confidence"] + c["confidence"]) / 3 * penalty, 1)
            parlays_3.append({"legs": [a, b, c], "score": score, "correlated": penalty < 1.0})

        parlays_2.sort(key=lambda x: x["score"], reverse=True)
        parlays_3.sort(key=lambda x: x["score"], reverse=True)

        write_safe(
            "prizepicks_parlays.json",
            {"two_leg": parlays_2[:10], "three_leg": parlays_3[:10]},
        )

        # ── Step 7: Compute trending ──────────────────────────────────────
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
                    "stat": stat, "label": STAT_LABELS[stat], "line": line,
                    "avg": round(df[stat].mean(), 1),
                    "hit_rate": hr["hit_rate"],
                    "sample": hr["sample"], "hits": hr["hits"],
                }
                if streak["type"] == "hit" and streak["count"] >= 3:
                    hot_streaks.append({**base, "streak": streak["count"]})
                if hr["hit_rate"] >= 0.70 and hr["sample"] >= 5:
                    top_hitters.append(base)

            for combo, cols in COMBO_STATS.items():
                df2 = df.copy()
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
                    "stat": combo, "label": STAT_LABELS[combo], "line": line,
                    "avg": hr["avg"], "hit_rate": hr["hit_rate"],
                    "sample": hr["sample"], "hits": hr["hits"],
                }
                if streak["type"] == "hit" and streak["count"] >= 3:
                    hot_streaks.append({**base, "streak": streak["count"]})
                if hr["hit_rate"] >= 0.70 and hr["sample"] >= 5:
                    top_hitters.append(base)

        hot_streaks.sort(key=lambda x: x["streak"], reverse=True)
        top_hitters.sort(key=lambda x: x["hit_rate"], reverse=True)

        write_safe("trending.json", {
            "hot_streaks": hot_streaks[:30],
            "top_hitters": top_hitters[:30],
        })

    # ── Done ────────────────────────────────────────────────────────────────
    if errors:
        print(f"\n⚠️  {len(errors)} fetch(es) failed: {', '.join(errors)}")

    print("\n🏁  All done.")


if __name__ == "__main__":
    import traceback
    print("Starting fetch_data job")
    try:
        main()
        print("fetch_data completed successfully")
    except Exception as e:
        print("fetch_data FAILED:", e)
        traceback.print_exc()
        raise
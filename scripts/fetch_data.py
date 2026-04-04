"""
scripts/fetch_data.py
---------------------
Fetches external data, queries the DB, does all the heavy computation,
and writes pre-computed JSON files to data/. Model evaluation tables are
not written here; hydration + Heroku sync happen in update_model_stats and
sync_to_heroku after JSON is finalized.

Files written:
  data/prizepicks_results.json   ← props only for teams on today's NBA scoreboard (US Eastern day)
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

from app.config import load_env  # noqa: E402

load_env()

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

    for stale in ("model_prop_eval_sync.json", "model_moneyline_eval_sync.json"):
        stale_path = DATA_PATH / stale
        if stale_path.is_file():
            stale_path.unlink()
            print(
                f"🗑️  Removed stale {stale} "
                "(recreated by update_model_stats before Heroku sync)."
            )

    # ── Step 1: Fetch external API data ──────────────────────────────────────
    from app.services.nba_fetcher import (
        fetch_opponent_defense,
        fetch_todays_matchups,
        fetch_team_records,
        fetch_h2h_season,
        fetch_injuries,
    )
    from app.services.prizepicks import PrizePicksError
    from app.services.props_sources import fetch_all_props_lines

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

    print("📡  Fetching player prop lines (PrizePicks + optional DraftKings)...")
    pp_lines = None
    try:
        pp_lines, provider_results = fetch_all_props_lines()
        ok_sources = [r.source for r in provider_results if not r.error]
        bad_sources = [f"{r.source}({r.error})" for r in provider_results if r.error]
        if ok_sources:
            print(f"✅  Prop providers ok: {', '.join(ok_sources)}")
        if bad_sources:
            print(f"⚠️  Prop providers failed: {', '.join(bad_sources)}")
        write_safe("prizepicks_lines.json", pp_lines)
    except PrizePicksError as e:
        msg = str(e)
        if "403" in msg:
            print(
                "⚠️  PrizePicks lines got 403 (likely blocked). "
                "Keeping existing file."
            )
            errors.append("prizepicks_lines_403")
            pp_lines = None
        else:
            print(f"❌  PrizePicks lines failed (hard): {e}")
            errors.append("prizepicks_lines")
            raise
    except Exception as e:
        print(f"❌  fetch_all_props_lines failed (unexpected): {e}")
        errors.append("prizepicks_lines")
        raise

    # ── Step 2: Load DB data ────────────────────────────────────────────────
    print("\n🗄️   Loading player data from DB...")

    from app import create_app
    from app.models.models import (
        Player,
        PlayerGameStat,
        db,
    )
    import datetime

    from app.services.hit_rate import (
        hit_rate,
        hit_rate_combo,
        COMBO_STATS,
        clean_avg,
        league_avg_by_stat,
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
        league_avgs_opp = league_avg_by_stat(opp_defense)

        # Model eval tables (model_prop_eval / model_moneyline_eval) are written only
        # after resolution in update_model_stats → JSON → sync_to_heroku.

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

        # ── Step 5: Compute PrizePicks results ────────────────────────────
        print(
            "\n⚙️   Computing PrizePicks results (in-memory; model_eval DB sync comes later)..."
        )

        def find_player(name_key):
            if name_key in player_map:
                return player_map[name_key]
            for key, player in player_map.items():
                if name_key in key or key in name_key:
                    return player
            return None

        pp_results = []
        player_df_cache = {}
        player_rows_cache = {}
        player_home_away_cache: dict[int, tuple] = {}

        if pp_lines is not None:
            total_pp = len(pp_lines)
            built_rows = 0
            missing_player = 0
            missing_rows = 0
            skipped_bad_stat = 0
            skipped_not_today = 0

            print(f"   Processing {total_pp} PrizePicks lines...")
            if not todays_matchups:
                print(
                    "   ⚠️  No teams on today's NBA scoreboard — "
                    "skipping all lines (avoid yesterday's matchups)."
                )

            for i, entry in enumerate(pp_lines, start=1):
                if i % 50 == 0 or i == total_pp:
                    print(
                        f"   ⏳ PrizePicks results: {i}/{total_pp} "
                        f"({i * 100 // total_pp}%) | built={built_rows} "
                        f"missing_player={missing_player} missing_rows={missing_rows} "
                        f"bad_stat={skipped_bad_stat}"
                    )

                player = find_player(entry["name_key"])
                if not player:
                    missing_player += 1
                    continue

                if player.id not in player_rows_cache:
                    player_rows_cache[player.id] = stats_by_player.get(player.id, [])
                rows = player_rows_cache[player.id]

                if not rows:
                    missing_rows += 1
                    continue

                if player.id not in player_df_cache:
                    df_new = rows_to_df(rows)
                    player_df_cache[player.id] = df_new
                    player_home_away_cache[player.id] = (
                        df_new.loc[df_new["location"] == "Home"],
                        df_new.loc[df_new["location"] == "Road"],
                    )
                df = player_df_cache[player.id]
                home_df, away_df = player_home_away_cache[player.id]

                stat = entry["stat"]
                line = entry["line"]

                team_abbr = (entry.get("team") or player.team_abbr or "").upper()
                if not todays_matchups or team_abbr not in todays_matchups:
                    skipped_not_today += 1
                    continue

                today_game = todays_matchups[team_abbr]
                opponent_abbr = today_game["opponent"]
                current_location = today_game["location"]

                if stat in COMBO_STATS:
                    cols = COMBO_STATS[stat]
                    values = df[cols].sum(axis=1).tolist()
                    primary_stat = cols[0]
                elif stat in df.columns:
                    values = df[stat].tolist()
                    primary_stat = stat
                else:
                    skipped_bad_stat += 1
                    continue

                avg_l5 = clean_avg(values, n=5)
                avg_l10 = clean_avg(values, n=10)
                avg_season = clean_avg(values)

                min_values = df["min"].tolist()
                min_l5 = clean_avg(min_values, n=5)
                min_l10 = clean_avg(min_values, n=10)
                min_season = clean_avg(min_values)

                minutes_ratio = None
                if min_l5 is not None and min_season not in (None, 0):
                    minutes_ratio = min_l5 / min_season

                hr_l5 = (
                    hit_rate_combo(df, stat, line, last_n=5, include_games=False)
                    if stat in COMBO_STATS
                    else hit_rate(df, stat, line, last_n=5, include_games=False)
                )
                hr_l10 = (
                    hit_rate_combo(df, stat, line, last_n=10, include_games=False)
                    if stat in COMBO_STATS
                    else hit_rate(df, stat, line, last_n=10, include_games=False)
                )
                hr_season = (
                    hit_rate_combo(df, stat, line, include_games=False)
                    if stat in COMBO_STATS
                    else hit_rate(df, stat, line, include_games=False)
                )

                if "error" in hr_l10:
                    continue

                edge = round(avg_l5 - line, 1) if avg_l5 is not None else None
                streak = hr_l10.get("streak", {"count": 0, "type": "none"})
                mult = matchup_multiplier(
                    opponent_abbr, primary_stat, opp_defense, league_avgs_opp
                )

                if stat in COMBO_STATS:
                    cols = COMBO_STATS[stat]
                    home_hr = (
                        (home_df[cols].sum(axis=1) > line).mean()
                        if not home_df.empty else 0.5
                    )
                    away_hr = (
                        (away_df[cols].sum(axis=1) > line).mean()
                        if not away_df.empty else 0.5
                    )
                else:
                    home_hr = (
                        (home_df[stat] > line).mean()
                        if not home_df.empty else 0.5
                    )
                    away_hr = (
                        (away_df[stat] > line).mean()
                        if not away_df.empty else 0.5
                    )

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

                book_src = (entry.get("source") or "prizepicks").lower()
                pp_results.append({
                    "id": player.id,
                    "name": player.name,
                    "team": player.team_abbr,
                    "position": player.position,
                    "stat": stat,
                    "label": entry["pp_stat_label"],
                    "source": book_src,
                    "book": entry.get("book", book_src),
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
                built_rows += 1

            print(
                f"   ✅ Finished PrizePicks loop | built={built_rows} "
                f"missing_player={missing_player} missing_rows={missing_rows} "
                f"bad_stat={skipped_bad_stat} not_on_todays_slate={skipped_not_today}"
            )

            pp_results.sort(key=lambda x: x["confidence"], reverse=True)

        write_safe("prizepicks_results.json", pp_results)

        # # ── Log top prop picks for model statistics ───────────────────────
        # today = datetime.date.today()
        # db.session.execute(
        #     db.text("TRUNCATE TABLE model_prop_eval RESTART IDENTITY CASCADE")
        # )
        # db.session.commit()
        #
        # MAX_PER_STAT = 25
        #
        # by_stat: dict[str, list] = defaultdict(list)
        # for p in pp_results:
        #     by_stat[p["stat"]].append(p)
        #
        # for stat, rows in by_stat.items():
        #     rows.sort(key=lambda x: x["confidence"], reverse=True)
        #     for row in rows[:MAX_PER_STAT]:
        #         m = ModelPropEval(
        #             date=today,
        #             player_id=row["id"],
        #             player_name=row["name"],
        #             team_abbr=row["team"],
        #             stat=stat,
        #             line=row["line"],
        #             confidence=row["confidence"],
        #         )
        #         db.session.add(m)
        #
        # db.session.commit()

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

        # ── Step 7: Compute trending (entire section commented out) ───────────────
        print("⏭️   Skipping trending compute (section commented out).")
        write_safe("trending.json", {"hot_streaks": [], "top_hitters": []})

        # skip_trending = os.getenv("SKIP_TRENDING", "").strip().lower() in {
        #     "1", "true", "yes", "y", "on"
        # }
        # if skip_trending:
        #     print("⏭️   Skipping trending compute (SKIP_TRENDING enabled).")
        #     write_safe("trending.json", {"hot_streaks": [], "top_hitters": []})
        # else:
        #     print("⚙️   Computing trending...")
        #
        #     hot_streaks = []
        #     top_hitters = []
        #
        #     total_players = len(all_players)
        #     for idx, player in enumerate(all_players, start=1):
        #         if idx % 100 == 0 or idx == total_players:
        #             print(f"   ⏳ Trending progress: {idx}/{total_players}")
        #         rows = stats_by_player.get(player.id, [])[:20]
        #         if len(rows) < 3:
        #             continue
        #
        #         if player.id in player_df_cache:
        #             df = player_df_cache[player.id]
        #         else:
        #             df = rows_to_df(rows)
        #             player_df_cache[player.id] = df
        #
        #         for stat in SINGLE_STATS:
        #             series = df[stat]
        #             line = round_to_half(series.head(5).mean())
        #             if line <= 0:
        #                 continue
        #             sample_series = series.head(10)
        #             sample = len(sample_series)
        #             if sample == 0:
        #                 continue
        #             hits = int((sample_series > line).sum())
        #             hr_rate = round(hits / sample, 3)
        #             streak = calculate_streak(series.tolist(), line)
        #             base = {
        #                 "id": player.id, "name": player.name,
        #                 "team": player.team_abbr, "position": player.position,
        #                 "stat": stat, "label": STAT_LABELS[stat], "line": line,
        #                 "avg": round(series.mean(), 1),
        #                 "hit_rate": hr_rate,
        #                 "sample": sample, "hits": hits,
        #             }
        #             if streak["type"] == "hit" and streak["count"] >= 3:
        #                 hot_streaks.append({**base, "streak": streak["count"]})
        #             if hr_rate >= 0.70 and sample >= 5:
        #                 top_hitters.append(base)
        #
        #         for combo, cols in COMBO_STATS.items():
        #             combo_series = df[cols].sum(axis=1)
        #             line = round_to_half(combo_series.head(5).mean())
        #             if line <= 0:
        #                 continue
        #             sample_series = combo_series.head(10)
        #             sample = len(sample_series)
        #             if sample == 0:
        #                 continue
        #             hits = int((sample_series > line).sum())
        #             hr_rate = round(hits / sample, 3)
        #             avg_val = round(combo_series.mean(), 1)
        #             streak = calculate_streak(combo_series.tolist(), line)
        #             base = {
        #                 "id": player.id, "name": player.name,
        #                 "team": player.team_abbr, "position": player.position,
        #                 "stat": combo, "label": STAT_LABELS[combo], "line": line,
        #                 "avg": avg_val, "hit_rate": hr_rate,
        #                 "sample": sample, "hits": hits,
        #             }
        #             if streak["type"] == "hit" and streak["count"] >= 3:
        #                 hot_streaks.append({**base, "streak": streak["count"]})
        #             if hr_rate >= 0.70 and sample >= 5:
        #                 top_hitters.append(base)
        #
        #     hot_streaks.sort(key=lambda x: x["streak"], reverse=True)
        #     top_hitters.sort(key=lambda x: x["hit_rate"], reverse=True)
        #
        #     write_safe("trending.json", {
        #         "hot_streaks": hot_streaks[:30],
        #         "top_hitters": top_hitters[:30],
        #     })

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
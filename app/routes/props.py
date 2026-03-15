from flask import Blueprint, jsonify, request
from app.models.models import db, Player, PlayerGameStat
from app.services.hit_rate import (
    hit_rate, hit_rate_combo, COMBO_STATS,
    calculate_streak, extract_opponent, clean_avg,
    matchup_multiplier, confidence_score
)
from app.services.prizepicks import fetch_prizepicks_lines, normalize
from app.services.nba_fetcher import fetch_opponent_defense, fetch_todays_matchups
import pandas as pd

props_bp = Blueprint("props", __name__, url_prefix="/api")

SINGLE_STATS = ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]
STAT_LABELS  = {
    "pts": "Points",   "reb": "Rebounds",    "ast": "Assists",
    "stl": "Steals",   "blk": "Blocks",      "fg3m": "3PM",
    "tov": "Turnovers","pr":  "PTS+REB",      "pa":  "PTS+AST",
    "ra":  "REB+AST",  "pra": "PTS+REB+AST", "sa":  "STL+AST",
    "bs":  "BLK+STL"
}

def rows_to_df(rows):
    return pd.DataFrame([{
        "date": str(r.date), "matchup": r.matchup, "location": r.location,
        "pts": r.pts, "reb": r.reb, "ast": r.ast,
        "stl": r.stl, "blk": r.blk, "fg3m": r.fg3m, "tov": r.tov
    } for r in rows])

def round_to_half(val):
    return round(val * 2) / 2

# ── Module-level caches ──
_opp_defense_cache   = {}
_todays_matchup_cache = {}

def get_opp_defense():
    global _opp_defense_cache
    if not _opp_defense_cache:
        try:
            _opp_defense_cache = fetch_opponent_defense()
            print(f"✅ Defense cache loaded for {len(_opp_defense_cache)} teams")
        except Exception as e:
            print(f"❌ fetch_opponent_defense failed: {e}")
            _opp_defense_cache = {}
    return _opp_defense_cache

def get_todays_matchups():
    global _todays_matchup_cache
    if not _todays_matchup_cache:
        try:
            _todays_matchup_cache = fetch_todays_matchups()
        except Exception as e:
            print(f"❌ fetch_todays_matchups failed: {e}")
            _todays_matchup_cache = {}
    return _todays_matchup_cache

# ── Player routes ──

@props_bp.route("/players")
def all_players():
    players = Player.query.order_by(Player.name).all()
    return jsonify([{"id": p.id, "name": p.name, "team": p.team_abbr, "position": p.position} for p in players])

@props_bp.route("/players/<int:player_id>")
def get_player(player_id):
    p = db.session.get(Player, player_id)
    if not p:
        return jsonify({"error": "Player not found"}), 404
    return jsonify({"id": p.id, "name": p.name, "team": p.team_abbr, "position": p.position})

@props_bp.route("/players/<int:player_id>/averages")
def player_averages(player_id):
    rows = PlayerGameStat.query.filter_by(player_id=player_id) \
        .order_by(PlayerGameStat.date.desc()).limit(5).all()
    if not rows:
        return jsonify({"error": "No data"}), 404
    df   = rows_to_df(rows)
    cols = ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]
    avgs = {col: round_to_half(df[col].mean()) for col in cols}
    for combo, combo_cols in COMBO_STATS.items():
        avgs[combo] = round_to_half(df[combo_cols].sum(axis=1).mean())
    return jsonify(avgs)

@props_bp.route("/players/<int:player_id>/opponents")
def player_opponents(player_id):
    rows = PlayerGameStat.query.filter_by(player_id=player_id).all()
    if not rows:
        return jsonify([])
    opponents = sorted(set(extract_opponent(r.matchup) for r in rows))
    return jsonify(opponents)

@props_bp.route("/players/<int:player_id>/props")
def player_props(player_id):
    stat     = request.args.get("stat", "pts")
    line     = float(request.args.get("line", 20.5))
    last_n   = request.args.get("last_n", type=int)
    location = request.args.get("location")
    opponent = request.args.get("opponent")
    rows = PlayerGameStat.query.filter_by(player_id=player_id) \
        .order_by(PlayerGameStat.date.desc()).all()
    if not rows:
        return jsonify({"error": "No data found for this player"}), 404
    df     = rows_to_df(rows)
    result = hit_rate(df, stat, line, last_n=last_n, location=location, opponent=opponent)
    return jsonify(result)

@props_bp.route("/players/<int:player_id>/combo")
def player_combo(player_id):
    combo    = request.args.get("combo", "pra")
    line     = float(request.args.get("line", 40.5))
    last_n   = request.args.get("last_n", type=int)
    location = request.args.get("location")
    opponent = request.args.get("opponent")
    rows = PlayerGameStat.query.filter_by(player_id=player_id) \
        .order_by(PlayerGameStat.date.desc()).all()
    if not rows:
        return jsonify({"error": "No data found for this player"}), 404
    df     = rows_to_df(rows)
    result = hit_rate_combo(df, combo, line, last_n=last_n, location=location, opponent=opponent)
    return jsonify(result)

@props_bp.route("/players/<int:player_id>/logs")
def player_logs(player_id):
    rows = PlayerGameStat.query.filter_by(player_id=player_id) \
        .order_by(PlayerGameStat.date.desc()).all()
    return jsonify(rows_to_df(rows).to_dict(orient="records"))

# ── Discover / Trending ──

@props_bp.route("/discover")
def discover():
    stat     = request.args.get("stat", "pts")
    line     = float(request.args.get("line", 20.5))
    last_n   = request.args.get("last_n", type=int)
    is_combo = stat in COMBO_STATS
    players  = Player.query.all()
    results  = []
    for player in players:
        rows = PlayerGameStat.query.filter_by(player_id=player.id) \
            .order_by(PlayerGameStat.date.desc()).all()
        if not rows:
            continue
        df    = rows_to_df(rows)
        stats = hit_rate_combo(df, stat, line, last_n=last_n) if is_combo \
            else hit_rate(df, stat, line, last_n=last_n)
        if "error" in stats:
            continue
        stats.pop("games", None)
        stats.pop("streak", None)
        results.append({"id": player.id, "name": player.name,
                         "team": player.team_abbr, "position": player.position, **stats})
    results.sort(key=lambda x: x["hit_rate"], reverse=True)
    return jsonify(results)

@props_bp.route("/trending")
def trending():
    players     = Player.query.all()
    hot_streaks = []
    top_hitters = []
    for player in players:
        rows = PlayerGameStat.query.filter_by(player_id=player.id) \
            .order_by(PlayerGameStat.date.desc()).limit(20).all()
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
            df2            = df.copy()
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
    return jsonify({"hot_streaks": hot_streaks[:30], "top_hitters": top_hitters[:30]})

# ── PrizePicks ──

@props_bp.route("/prizepicks")
def prizepicks():
    pp_lines = fetch_prizepicks_lines()
    if not pp_lines:
        return jsonify({"error": "Could not fetch PrizePicks data"}), 502

    opp_defense      = get_opp_defense()
    todays_matchups  = get_todays_matchups()  # real today's schedule

    all_players = Player.query.all()
    name_map    = {normalize(p.name): p for p in all_players}

    def find_player(name_key):
        if name_key in name_map:
            return name_map[name_key]
        for key, player in name_map.items():
            if name_key in key or key in name_key:
                return player
        return None

    results = []
    for entry in pp_lines:
        player = find_player(entry["name_key"])
        if not player:
            continue
        rows = PlayerGameStat.query.filter_by(player_id=player.id) \
            .order_by(PlayerGameStat.date.desc()).all()
        if not rows:
            continue

        df   = rows_to_df(rows)
        stat = entry["stat"]
        line = entry["line"]

        # ── Today's real matchup from NBA schedule ──
        team_abbr  = (entry.get("team") or player.team_abbr or "").upper()
        today_game = todays_matchups.get(team_abbr)
        if today_game:
            opponent_abbr    = today_game["opponent"]
            current_location = today_game["location"]
        else:
            # Fallback to most recent logged game
            opponent_abbr    = extract_opponent(rows[0].matchup)
            current_location = rows[0].location

        # ── Stat values ──
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

        # ── Home/away bonus ──
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

        results.append({
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

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return jsonify(results)

@props_bp.route("/prizepicks/parlays")
def prizepicks_parlays():
    from itertools import combinations

    pp_lines = fetch_prizepicks_lines()
    if not pp_lines:
        return jsonify({"error": "Could not fetch PrizePicks data"}), 502

    opp_defense     = get_opp_defense()
    todays_matchups = get_todays_matchups()
    all_players     = Player.query.all()
    name_map        = {normalize(p.name): p for p in all_players}

    def find_player(name_key):
        if name_key in name_map:
            return name_map[name_key]
        for key, player in name_map.items():
            if name_key in key or key in name_key:
                return player
        return None

    # Build ranked list inline (avoids HTTP self-call)
    from flask import current_app
    with current_app.test_request_context():
        ranked_resp = prizepicks()
        ranked = ranked_resp.get_json()

    if isinstance(ranked, dict) and "error" in ranked:
        return jsonify(ranked), 502

    candidates = [p for p in ranked if p["confidence"] >= 65 and p["odds_type"] == "standard"][:30]

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

    return jsonify({"two_leg": parlays_2[:10], "three_leg": parlays_3[:10]})

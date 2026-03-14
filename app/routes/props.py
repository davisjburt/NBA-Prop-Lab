from flask import Blueprint, jsonify, request
from app.models.models import db, Player, PlayerGameStat
from app.services.hit_rate import (
    hit_rate, hit_rate_combo, COMBO_STATS,
    calculate_streak, extract_opponent, clean_avg
)
from app.services.prizepicks import fetch_prizepicks_lines, normalize
import pandas as pd

props_bp = Blueprint("props", __name__, url_prefix="/api")

SINGLE_STATS = ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]
STAT_LABELS  = {
    "pts": "Points",    "reb": "Rebounds",   "ast": "Assists",
    "stl": "Steals",    "blk": "Blocks",     "fg3m": "3PM",
    "tov": "Turnovers", "pr":  "PTS+REB",    "pa":   "PTS+AST",
    "ra":  "REB+AST",   "pra": "PTS+REB+AST","sa":   "STL+AST",
    "bs":  "BLK+STL"
}


def rows_to_df(rows):
    return pd.DataFrame([{
        "date":    str(r.date), "matchup": r.matchup, "location": r.location,
        "pts":     r.pts,       "reb":     r.reb,      "ast":      r.ast,
        "stl":     r.stl,       "blk":     r.blk,      "fg3m":     r.fg3m,
        "tov":     r.tov
    } for r in rows])


def round_to_half(val):
    return round(val * 2) / 2


@props_bp.route("/players")
def all_players():
    players = Player.query.order_by(Player.name).all()
    return jsonify([{
        "id": p.id, "name": p.name,
        "team": p.team_abbr, "position": p.position
    } for p in players])


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
    avgs = {}
    for col in cols:
        avgs[col] = round_to_half(df[col].mean())
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


@props_bp.route("/discover")
def discover():
    stat   = request.args.get("stat", "pts")
    line   = float(request.args.get("line", 20.5))
    last_n = request.args.get("last_n", type=int)

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

        stats.pop("games",  None)
        stats.pop("streak", None)

        results.append({
            "id": player.id, "name": player.name,
            "team": player.team_abbr, "position": player.position,
            **stats
        })

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
                "id":       player.id,       "name":     player.name,
                "team":     player.team_abbr, "position": player.position,
                "stat":     stat,            "label":    STAT_LABELS[stat],
                "line":     line,            "avg":      round(df[stat].mean(), 1),
                "hit_rate": hr["hit_rate"],  "sample":   hr["sample"],
                "hits":     hr["hits"],
            }

            if streak["type"] == "hit" and streak["count"] >= 3:
                hot_streaks.append({**base, "streak": streak["count"]})
            if hr["hit_rate"] >= 0.70 and hr["sample"] >= 5:
                top_hitters.append(base)

        for combo, cols in COMBO_STATS.items():
            df2              = df.copy()
            df2["combo_val"] = df2[cols].sum(axis=1)
            line             = round_to_half(df2["combo_val"].head(5).mean())
            if line <= 0:
                continue

            streak = calculate_streak(df2["combo_val"].tolist(), line)
            hr     = hit_rate_combo(df, combo, line, last_n=10)
            if "error" in hr:
                continue

            base = {
                "id":       player.id,       "name":     player.name,
                "team":     player.team_abbr, "position": player.position,
                "stat":     combo,           "label":    STAT_LABELS[combo],
                "line":     line,            "avg":      hr["avg"],
                "hit_rate": hr["hit_rate"],  "sample":   hr["sample"],
                "hits":     hr["hits"],
            }

            if streak["type"] == "hit" and streak["count"] >= 3:
                hot_streaks.append({**base, "streak": streak["count"]})
            if hr["hit_rate"] >= 0.70 and hr["sample"] >= 5:
                top_hitters.append(base)

    hot_streaks.sort(key=lambda x: x["streak"],   reverse=True)
    top_hitters.sort(key=lambda x: x["hit_rate"],  reverse=True)

    return jsonify({"hot_streaks": hot_streaks[:30], "top_hitters": top_hitters[:30]})


@props_bp.route("/prizepicks")
def prizepicks():
    pp_lines = fetch_prizepicks_lines()
    if not pp_lines:
        return jsonify({"error": "Could not fetch PrizePicks data"}), 502

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

        if stat in COMBO_STATS:
            cols   = COMBO_STATS[stat]
            values = df[cols].sum(axis=1).tolist()
        elif stat in df.columns:
            values = df[stat].tolist()
        else:
            continue

        avg_l5     = clean_avg(values, n=5)
        avg_l10    = clean_avg(values, n=10)
        avg_season = clean_avg(values)

        hr = hit_rate_combo(df, stat, line, last_n=10) if stat in COMBO_STATS \
             else hit_rate(df, stat, line, last_n=10)

        if "error" in hr:
            continue

        edge = round(avg_l5 - line, 1) if avg_l5 is not None else None

        results.append({
    "id":         player.id,
    "name":       player.name,
    "team":       player.team_abbr,
    "position":   player.position,
    "stat":       stat,
    "label":      entry["pp_stat_label"],
    "odds_type":  entry.get("odds_type", "standard"),   # ← make sure this line exists
    "line":       line,
    "hit_rate":   hr["hit_rate"],
    "avg_l5":     avg_l5,
    "avg_l10":    avg_l10,
    "avg_season": avg_season,
    "edge":       edge,
    "hits":       hr["hits"],
    "sample":     hr["sample"],
})


    results.sort(key=lambda x: x["hit_rate"], reverse=True)
    return jsonify(results)

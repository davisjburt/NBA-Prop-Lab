import json, os
from flask import Blueprint, jsonify, request
from app.models.models import db, Player, PlayerGameStat
from app.services.hit_rate import (
    hit_rate, hit_rate_combo, COMBO_STATS,
    calculate_streak, extract_opponent
)
import pandas as pd

props_bp = Blueprint("props", __name__, url_prefix="/api")

_BASE     = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.normpath(os.path.join(_BASE, "..", "..", "data"))


def _load_json(filename, fallback):
    path = os.path.join(_DATA_DIR, filename)
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Could not load {filename}: {e}")
        return fallback


def rows_to_df(rows):
    return pd.DataFrame([{
        "date": str(r.date), "matchup": r.matchup, "location": r.location,
        "pts": r.pts, "reb": r.reb, "ast": r.ast,
        "stl": r.stl, "blk": r.blk, "fg3m": r.fg3m, "tov": r.tov
    } for r in rows])


def round_to_half(val):
    return round(val * 2) / 2


# ── Player routes ─────────────────────────────────────────────────────────────

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


# ── Discover ──────────────────────────────────────────────────────────────────

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
            .order_by(PlayerGameStat.date.desc()).limit(20).all()
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


# ── Pre-computed endpoints ─────────────────────────────────────────────────────

@props_bp.route("/trending")
def trending():
    return jsonify(_load_json("trending.json", {"hot_streaks": [], "top_hitters": []}))


@props_bp.route("/prizepicks")
def prizepicks():
    data = _load_json("prizepicks_results.json", None)
    if data is None:
        return jsonify({"error": "PrizePicks data not yet available."}), 503
    return jsonify(data)


@props_bp.route("/prizepicks/parlays")
def prizepicks_parlays():
    data = _load_json("prizepicks_parlays.json", None)
    if data is None:
        return jsonify({"error": "Parlay data not yet available."}), 503
    return jsonify(data)


@props_bp.route("/moneylines")
def moneylines():
    data = _load_json("moneylines.json", [])
    # Ensure we always return a list (frontend expects an array)
    if not isinstance(data, list):
        data = []
    return jsonify(data)

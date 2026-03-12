from flask import Blueprint, jsonify, request
from app.models.models import Player, PlayerGameStat
from app.services.hit_rate import hit_rate
import pandas as pd

props_bp = Blueprint("props", __name__, url_prefix="/api")

@props_bp.route("/players/<int:player_id>/props")
def player_props(player_id):
    stat     = request.args.get("stat", "pts")
    line     = float(request.args.get("line", 20.5))
    last_n   = request.args.get("last_n", type=int)
    location = request.args.get("location")

    rows = PlayerGameStat.query.filter_by(player_id=player_id) \
               .order_by(PlayerGameStat.date.desc()).all()

    if not rows:
        return jsonify({"error": "No data found for this player"}), 404

    df = pd.DataFrame([{
        "date": str(r.date), "matchup": r.matchup, "location": r.location,
        "pts": r.pts, "reb": r.reb, "ast": r.ast,
        "stl": r.stl, "blk": r.blk, "fg3m": r.fg3m, "tov": r.tov
    } for r in rows])

    result = hit_rate(df, stat, line, last_n=last_n, location=location)
    result["games"] = df.head(last_n or 10)[["date", "matchup", stat]].to_dict(orient="records")
    return jsonify(result)

@props_bp.route("/players/<int:player_id>/logs")
def player_logs(player_id):
    rows = PlayerGameStat.query.filter_by(player_id=player_id) \
               .order_by(PlayerGameStat.date.desc()).all()
    return jsonify([{
        "date": str(r.date), "matchup": r.matchup, "location": r.location,
        "pts": r.pts, "reb": r.reb, "ast": r.ast,
        "stl": r.stl, "blk": r.blk, "fg3m": r.fg3m, "tov": r.tov
    } for r in rows])

@props_bp.route("/discover")
def discover():
    stat   = request.args.get("stat", "pts")
    line   = float(request.args.get("line", 20.5))
    last_n = request.args.get("last_n", type=int)

    players = Player.query.all()
    results = []

    for player in players:
        rows = PlayerGameStat.query.filter_by(player_id=player.id) \
                   .order_by(PlayerGameStat.date.desc()).all()
        if not rows:
            continue

        df = pd.DataFrame([{
            "date": str(r.date), "matchup": r.matchup, "location": r.location,
            "pts": r.pts, "reb": r.reb, "ast": r.ast,
            "stl": r.stl, "blk": r.blk, "fg3m": r.fg3m, "tov": r.tov
        } for r in rows])

        stats = hit_rate(df, stat, line, last_n=last_n)
        if "error" in stats:
            continue

        results.append({
            "id":       player.id,
            "name":     player.name,
            "team":     player.team_abbr,
            "position": player.position,
            **stats
        })

    results.sort(key=lambda x: x["hit_rate"], reverse=True)
    return jsonify(results)

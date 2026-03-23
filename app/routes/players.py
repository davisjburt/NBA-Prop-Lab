from flask import Blueprint, jsonify, render_template, redirect
from app.models.models import Player

players_bp = Blueprint("players", __name__, url_prefix="/")

@players_bp.route("/")
def index():
    return render_template("index.html")

@players_bp.route("/player/<int:player_id>")
def player_page(player_id):
    return render_template("player.html", player_id=player_id)

@players_bp.route("/explore")
def explore_page():
    return render_template("explore.html")

@players_bp.route("/prizepicks")
def prizepicks_page():
    return render_template("prizepicks.html")

@players_bp.route("/moneylines")
def moneylines_page():
    return render_template("moneylines.html")

# Keep old URLs working
@players_bp.route("/discover")
def discover_redirect():
    return redirect("/explore")

@players_bp.route("/trending")
def trending_redirect():
    return redirect("/explore")

@players_bp.route("/parlays")
def parlays_page():
    return render_template("parlays.html")

@players_bp.route("/api/players")
def get_players():
    players = Player.query.order_by(Player.name).all()
    return jsonify([{
        "id": p.id, "name": p.name,
        "team": p.team_abbr, "position": p.position
    } for p in players])

@players_bp.route("/api/players/<int:player_id>")
def get_player(player_id):
    p = Player.query.get_or_404(player_id)
    return jsonify({
        "id": p.id, "name": p.name,
        "team": p.team_abbr, "position": p.position
    })

@players_bp.route("/model-stats")
def model_stats_page():
    return render_template("model-stats.html")

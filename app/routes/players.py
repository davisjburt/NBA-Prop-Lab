from flask import Blueprint, jsonify, render_template
from app.models.models import Player

players_bp = Blueprint("players", __name__, url_prefix="/")

@players_bp.route("/")
def index():
    return render_template("index.html")

@players_bp.route("/player/<int:player_id>")
def player_page(player_id):
    return render_template("player.html", player_id=player_id)

@players_bp.route("/discover")
def discover_page():
    return render_template("discover.html")

@players_bp.route("/trending")
def trending_page():
    return render_template("trending.html")

@players_bp.route("/api/players")
def get_players():
    players = Player.query.order_by(Player.name).all()
    return jsonify([{
        "id": p.id,
        "name": p.name,
        "team": p.team_abbr,
        "position": p.position
    } for p in players])

@players_bp.route("/api/players/<int:player_id>")
def get_player(player_id):
    p = Player.query.get_or_404(player_id)
    return jsonify({
        "id": p.id,
        "name": p.name,
        "team": p.team_abbr,
        "position": p.position
    })

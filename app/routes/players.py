from flask import Blueprint, render_template, redirect

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


@players_bp.route("/model-stats")
def model_stats_page():
    return render_template("model-stats.html")


@players_bp.route("/settings")
def settings_page():
    return render_template("settings.html")

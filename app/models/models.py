from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Player(db.Model):
    __tablename__ = "players"
    id        = db.Column(db.Integer, primary_key=True)  # NBA player_id
    name      = db.Column(db.String, nullable=False)
    team_abbr = db.Column(db.String(5))
    position  = db.Column(db.String(5))
    games     = db.relationship("PlayerGameStat", backref="player", lazy=True)

class Game(db.Model):
    __tablename__ = "games"
    id        = db.Column(db.Integer, primary_key=True)  # NBA game_id
    date      = db.Column(db.Date, nullable=False)
    home_team = db.Column(db.String(5))
    away_team = db.Column(db.String(5))

class PlayerGameStat(db.Model):
    __tablename__ = "player_game_stats"
    id        = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    game_id   = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=True)
    date      = db.Column(db.Date)
    matchup   = db.Column(db.String(20))
    location  = db.Column(db.String(4))   # "Home" or "Road"
    min       = db.Column(db.Float)
    pts       = db.Column(db.Float)
    reb       = db.Column(db.Float)
    ast       = db.Column(db.Float)
    stl       = db.Column(db.Float)
    blk       = db.Column(db.Float)
    fg3m      = db.Column(db.Float)
    tov       = db.Column(db.Float)

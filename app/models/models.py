from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()

class Player(db.Model):
    __tablename__ = "players"

    id        = db.Column(db.Integer, primary_key=True)
    name      = db.Column(db.String,  nullable=False)
    team_abbr = db.Column(db.String)
    position  = db.Column(db.String)
    stats     = db.relationship("PlayerGameStat", backref="player", lazy=True)

class PlayerGameStat(db.Model):
    __tablename__  = "player_game_stats"
    __table_args__ = (UniqueConstraint("player_id", "date", name="uq_player_date"),)

    id        = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    date      = db.Column(db.Date,    nullable=False)
    matchup   = db.Column(db.String)
    location  = db.Column(db.String)
    min       = db.Column(db.Float)
    pts       = db.Column(db.Float)
    reb       = db.Column(db.Float)
    ast       = db.Column(db.Float)
    stl       = db.Column(db.Float)
    blk       = db.Column(db.Float)
    fg3m      = db.Column(db.Float)
    tov       = db.Column(db.Float)

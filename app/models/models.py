from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
from datetime import datetime


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


class ModelPropEval(db.Model):
    __tablename__ = "model_prop_eval"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, index=True)

    player_id = db.Column(db.Integer, db.ForeignKey("players.id"))
    player_name = db.Column(db.String)
    team_abbr = db.Column(db.String(4))

    stat = db.Column(db.String(8))          # "pts", "reb", "pra", etc.
    line = db.Column(db.Float)
    confidence = db.Column(db.Float)

    result_value = db.Column(db.Float, nullable=True)
    hit = db.Column(db.Boolean, nullable=True)  # null until resolved

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)


class ModelMoneylineEval(db.Model):
    __tablename__ = "model_moneyline_eval"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, index=True)

    home_abbr = db.Column(db.String(4))
    away_abbr = db.Column(db.String(4))

    predicted_winner = db.Column(db.String(4))
    win_prob_home = db.Column(db.Float)
    win_prob_away = db.Column(db.Float)
    spread = db.Column(db.Float)

    actual_winner = db.Column(db.String(4), nullable=True)
    margin = db.Column(db.Float, nullable=True)   # home_score - away_score
    correct = db.Column(db.Boolean, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

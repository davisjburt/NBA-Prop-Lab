"""
scripts/update_model_stats.py
-----------------------------
Resolves stored model predictions (props + moneylines) against
actual outcomes in PlayerGameStat.
"""

import os
import sys
from datetime import date

# Ensure app package is importable when running as a script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models.models import (
    db,
    Player,
    PlayerGameStat,
    ModelPropEval,
    ModelMoneylineEval,
)


def resolve_props(today: date) -> None:
    pending_props = ModelPropEval.query.filter(
        ModelPropEval.date < today,
        ModelPropEval.hit.is_(None),
    ).all()
    print(f"Resolving {len(pending_props)} prop picks...")

    for m in pending_props:
        rows = PlayerGameStat.query.filter_by(
            player_id=m.player_id,
            date=m.date,
        ).all()
        if not rows:
            continue

        row = rows[0]
        val = getattr(row, m.stat, None)
        if val is None:
            continue

        m.result_value = float(val)
        m.hit = bool(val > m.line)


def team_score_for(game_date: date, team_abbr: str) -> float:
    """Sum points for a team on a given date using Player.team_abbr."""
    rows = (
        db.session.query(PlayerGameStat)
        .join(Player, PlayerGameStat.player_id == Player.id)
        .filter(
            PlayerGameStat.date == game_date,
            Player.team_abbr == team_abbr,
        )
        .all()
    )
    return sum(r.pts or 0 for r in rows)


def resolve_moneylines(today: date) -> None:
    pending_games = ModelMoneylineEval.query.filter(
        ModelMoneylineEval.date < today,
        ModelMoneylineEval.correct.is_(None),
    ).all()
    print(f"Resolving {len(pending_games)} moneyline games...")

    for g in pending_games:
        home_score = team_score_for(g.date, g.home_abbr)
        away_score = team_score_for(g.date, g.away_abbr)

        # If we have no stats for either team, skip
        if home_score == 0 and away_score == 0:
            continue

        margin = home_score - away_score
        g.margin = float(margin)
        g.actual_winner = g.home_abbr if margin > 0 else g.away_abbr
        g.correct = (g.actual_winner == g.predicted_winner)


def main() -> None:
    app = create_app()
    with app.app_context():
        today = date.today()

        resolve_props(today)
        resolve_moneylines(today)

        db.session.commit()
        print("Done updating model stats.")


if __name__ == "__main__":
    main()

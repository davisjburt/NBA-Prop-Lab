"""
scripts/update_model_stats.py
-----------------------------
Resolves stored model predictions (props + moneylines) against
actual outcomes in PlayerGameStat.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models.models import (
    db,
    PlayerGameStat,
    ModelPropEval,
    ModelMoneylineEval,
)


def main():
    app = create_app()
    with app.app_context():
        today = date.today()

        # ── Resolve prop picks ───────────────────────────────────────────
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

        # ── Resolve moneylines ───────────────────────────────────────────
        pending_games = ModelMoneylineEval.query.filter(
            ModelMoneylineEval.date < today,
            ModelMoneylineEval.correct.is_(None),
        ).all()
        print(f"Resolving {len(pending_games)} moneyline games...")

        for g in pending_games:
            home_rows = PlayerGameStat.query.filter_by(
                team_abbr=g.home_abbr,
                date=g.date,
            ).all()
            away_rows = PlayerGameStat.query.filter_by(
                team_abbr=g.away_abbr,
                date=g.date,
            ).all()
            if not home_rows or not away_rows:
                continue

            home_score = sum(r.pts or 0 for r in home_rows)
            away_score = sum(r.pts or 0 for r in away_rows)
            margin = home_score - away_score
            g.margin = float(margin)
            g.actual_winner = g.home_abbr if margin > 0 else g.away_abbr
            g.correct = (g.actual_winner == g.predicted_winner)

        db.session.commit()
        print("Done updating model stats.")


if __name__ == "__main__":
    main()

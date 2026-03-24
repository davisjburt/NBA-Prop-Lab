"""
scripts/update_model_stats.py
-----------------------------
Resolves stored model predictions (props + moneylines) against
actual outcomes in PlayerGameStat, and writes aggregated model
stats JSON files for use by the frontend.
"""

import os
import sys
import json
from pathlib import Path
from datetime import date, timedelta

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
from sqlalchemy import desc

DATA_DIR = Path(os.path.join(os.path.dirname(__file__), "..", "data"))


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


def build_window_summary(window_days: int) -> dict:
    """Aggregate moneylines + props and sample recent bets for a window."""
    end = date.today()
    start = end - timedelta(days=window_days)

    # Moneylines summary
    ml_q = ModelMoneylineEval.query.filter(
        ModelMoneylineEval.date >= start,
        ModelMoneylineEval.date < end,
        ModelMoneylineEval.correct.isnot(None),
    )
    ml_bets = ml_q.count()
    ml_hits = ml_q.filter_by(correct=True).count()
    ml_hit_rate = (ml_hits / ml_bets) if ml_bets else None

    moneylines = {
        "bets": ml_bets,
        "hits": ml_hits,
        "hit_rate": ml_hit_rate,
    }

    # Props aggregated by stat
    props_q = ModelPropEval.query.filter(
        ModelPropEval.date >= start,
        ModelPropEval.date < end,
        ModelPropEval.hit.isnot(None),
    )

    buckets: dict[str, dict[str, int]] = {}
    for p in props_q:
        bucket = buckets.setdefault(p.stat, {"bets": 0, "hits": 0})
        bucket["bets"] += 1
        if p.hit:
            bucket["hits"] += 1

    props: list[dict] = []
    for stat, agg in buckets.items():
        bets = agg["bets"]
        hits = agg["hits"]
        hit_rate = hits / bets if bets else None
        props.append(
            {"stat": stat, "bets": bets, "hits": hits, "hit_rate": hit_rate}
        )

    props.sort(key=lambda x: (x["hit_rate"] or 0), reverse=True)

    # Overall props across all stats
    total_bets = sum(p["bets"] for p in props)
    total_hits = sum(p["hits"] for p in props)
    prop_hit_rate = (total_hits / total_bets) if total_bets else None
    prop_overall = {
        "bets": total_bets,
        "hits": total_hits,
        "hit_rate": prop_hit_rate,
    }

    # Recent individual props
    sample_props_q = (
        ModelPropEval.query.filter(
            ModelPropEval.date >= start,
            ModelPropEval.date < end,
            ModelPropEval.hit.isnot(None),
        )
        .order_by(desc(ModelPropEval.date), desc(ModelPropEval.confidence))
        .limit(50)
    )
    sample_props = [
        {
            "date": p.date.isoformat(),
            "player_name": p.player_name,
            "team_abbr": p.team_abbr,
            "stat": p.stat,
            "line": p.line,
            "hit": p.hit,
            "confidence": p.confidence,
        }
        for p in sample_props_q
    ]

    # Recent individual moneylines
    sample_ml_q = (
        ModelMoneylineEval.query.filter(
            ModelMoneylineEval.date >= start,
            ModelMoneylineEval.date < end,
            ModelMoneylineEval.correct.isnot(None),
        )
        .order_by(desc(ModelMoneylineEval.date), desc(ModelMoneylineEval.win_prob_home))
        .limit(50)
    )
    sample_moneylines = [
        {
            "date": g.date.isoformat(),
            "home_abbr": g.home_abbr,
            "away_abbr": g.away_abbr,
            "predicted_winner": g.predicted_winner,
            "actual_winner": g.actual_winner,
            "correct": g.correct,
            "margin": g.margin,
            "win_prob_home": g.win_prob_home,
            "win_prob_away": g.win_prob_away,
        }
        for g in sample_ml_q
    ]

    return {
        "moneylines": moneylines,
        "props": props,
        "prop_overall": prop_overall,
        "sample_props": sample_props,
        "sample_moneylines": sample_moneylines,
    }


def write_model_stats_json() -> None:
    """Write model stats JSON files for 7/30/90-day windows."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    windows = {
        7: "model_stats_7.json",
        30: "model_stats_30.json",
        90: "model_stats_90.json",
    }

    for days, fname in windows.items():
        summary = build_window_summary(days)
        path = DATA_DIR / fname
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w") as f:
            json.dump(summary, f, indent=2, default=str)
        tmp.replace(path)
        print(f"Wrote model stats for last {days} days to {fname}")


def main() -> None:
    app = create_app()
    with app.app_context():
        today = date.today()

        resolve_props(today)
        resolve_moneylines(today)

        # Persist DB changes first
        db.session.commit()
        print("Done updating model stats (DB).")

        # Then write JSON snapshots for frontend / Render
        write_model_stats_json()


if __name__ == "__main__":
    main()

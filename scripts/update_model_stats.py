"""
scripts/update_model_stats.py
-----------------------------
Rebuilds today's model-eval slate from fetch_data JSON, resolves outcomes
against PlayerGameStat, updates the local DB for historical summaries, writes
model_*_eval_sync.json for sync_to_heroku, and writes model_stats_*.json.
"""

import os
import sys
import json
from collections import defaultdict
from pathlib import Path
from datetime import date

# Ensure app package is importable when running as a script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import load_env  # noqa: E402

load_env()

from app import create_app
from app.models.models import (
    db,
    Player,
    PlayerGameStat,
    ModelPropEval,
    ModelMoneylineEval,
)
from sqlalchemy import func

from app.services.hit_rate import COMBO_STATS
from app.services.model_summary import build_outcomes_summary

DATA_DIR = Path(os.path.join(os.path.dirname(__file__), "..", "data"))

MAX_PER_STAT = 25


def _read_json_list(path: Path) -> list | None:
    if not path.exists():
        return None
    with path.open() as f:
        data = json.load(f)
    return data if isinstance(data, list) else None


def _write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, default=str)
    tmp.replace(path)


def hydrate_today_from_json(today: date) -> None:
    """
    Replace today's model_prop_eval / model_moneyline_eval rows using the same
    shaping as fetch_data used to insert (top N per stat from prizepicks_results).
    """
    ml_raw = _read_json_list(DATA_DIR / "moneylines.json") or []
    pp_raw = _read_json_list(DATA_DIR / "prizepicks_results.json") or []

    ModelPropEval.query.filter(ModelPropEval.date == today).delete(
        synchronize_session=False
    )
    ModelMoneylineEval.query.filter(ModelMoneylineEval.date == today).delete(
        synchronize_session=False
    )

    for g in ml_raw:
        db.session.add(
            ModelMoneylineEval(
                date=today,
                home_abbr=g["home"],
                away_abbr=g["away"],
                predicted_winner=g["predicted_winner"],
                win_prob_home=g["win_prob_home"],
                win_prob_away=g["win_prob_away"],
                spread=g["spread"],
            )
        )

    by_stat: dict[str, list] = defaultdict(list)
    for row in pp_raw:
        by_stat[row["stat"]].append(row)
    for stat, rows in by_stat.items():
        rows.sort(key=lambda x: x["confidence"], reverse=True)
        for row in rows[:MAX_PER_STAT]:
            db.session.add(
                ModelPropEval(
                    date=today,
                    player_id=row["id"],
                    player_name=row["name"],
                    team_abbr=row["team"],
                    stat=stat,
                    line=float(row["line"]),
                    confidence=float(row["confidence"]),
                )
            )

    db.session.commit()
    print(
        f"Hydrated model eval for {today} from JSON "
        f"({len(ml_raw)} moneylines, {len(pp_raw)} prop board rows → top {MAX_PER_STAT}/stat in DB)."
    )


def write_model_eval_sync_json(today: date) -> None:
    """Full rows (including resolution fields) for Heroku Postgres sync."""
    props = ModelPropEval.query.filter(ModelPropEval.date == today).all()
    mls = ModelMoneylineEval.query.filter(ModelMoneylineEval.date == today).all()

    prop_payload = [
        {
            "date": p.date.isoformat(),
            "player_id": p.player_id,
            "player_name": p.player_name,
            "team_abbr": p.team_abbr,
            "stat": p.stat,
            "line": p.line,
            "confidence": p.confidence,
            "result_value": p.result_value,
            "hit": p.hit,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        for p in props
    ]
    ml_payload = [
        {
            "date": g.date.isoformat(),
            "home_abbr": g.home_abbr,
            "away_abbr": g.away_abbr,
            "predicted_winner": g.predicted_winner,
            "win_prob_home": g.win_prob_home,
            "win_prob_away": g.win_prob_away,
            "spread": g.spread,
            "actual_winner": g.actual_winner,
            "margin": g.margin,
            "correct": g.correct,
            "created_at": g.created_at.isoformat() if g.created_at else None,
            "updated_at": g.updated_at.isoformat() if g.updated_at else None,
        }
        for g in mls
    ]

    _write_json_atomic(DATA_DIR / "model_prop_eval_sync.json", prop_payload)
    _write_json_atomic(DATA_DIR / "model_moneyline_eval_sync.json", ml_payload)
    print(
        f"Wrote model_prop_eval_sync.json ({len(prop_payload)} rows) and "
        f"model_moneyline_eval_sync.json ({len(ml_payload)} rows)."
    )


def _actual_stat_value(row: PlayerGameStat, stat: str) -> float | None:
    """Single-column stats or combo sums (pra, pr, …) from PlayerGameStat columns."""
    if stat in COMBO_STATS:
        total = 0.0
        for col in COMBO_STATS[stat]:
            v = getattr(row, col, None)
            if v is None:
                return None
            total += float(v)
        return total
    v = getattr(row, stat, None)
    return float(v) if v is not None else None


def resolve_props(today: date) -> None:
    # Include today so same-day slates resolve once daily_update has box scores.
    # Rows without PlayerGameStat for that date are skipped until data exists.
    pending_props = ModelPropEval.query.filter(
        ModelPropEval.date <= today,
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
        val = _actual_stat_value(row, m.stat)
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
            func.upper(Player.team_abbr) == team_abbr.strip().upper(),
        )
        .all()
    )
    return sum(r.pts or 0 for r in rows)


def resolve_moneylines(today: date) -> None:
    pending_games = ModelMoneylineEval.query.filter(
        ModelMoneylineEval.date <= today,
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


def write_model_stats_json() -> None:
    """Write model stats JSON files for 7/30/90-day windows."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    windows = {
        7: "model_stats_7.json",
        30: "model_stats_30.json",
        90: "model_stats_90.json",
    }

    for days, fname in windows.items():
        summary = build_outcomes_summary(days)
        path = DATA_DIR / fname
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w") as f:
            json.dump(summary, f, indent=2, default=str)
        tmp.replace(path)
        print(f"Wrote model stats for last {days} days to {fname}")

    all_path = DATA_DIR / "model_stats_all.json"
    tmp_all = all_path.with_suffix(all_path.suffix + ".tmp")
    summary_all = build_outcomes_summary(None)
    with tmp_all.open("w") as f:
        json.dump(summary_all, f, indent=2, default=str)
    tmp_all.replace(all_path)
    print("Wrote model stats (all logged outcomes) to model_stats_all.json")


def main() -> None:
    app = create_app()
    with app.app_context():
        today = date.today()

        hydrate_today_from_json(today)

        resolve_props(today)
        resolve_moneylines(today)

        db.session.commit()
        print("Done updating model stats (local DB).")

        write_model_eval_sync_json(today)
        write_model_stats_json()


if __name__ == "__main__":
    main()

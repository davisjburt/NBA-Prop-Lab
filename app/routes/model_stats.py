# app/routes/model_stats.py

from datetime import date, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import desc

from app.models.models import db, ModelPropEval, ModelMoneylineEval


model_stats_bp = Blueprint("model_stats", __name__, url_prefix="/api")


@model_stats_bp.route("/model_outcomes")
def model_outcomes():
    # Parse & clamp window
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30
    if days not in (7, 30, 90):
        days = 30

    end = date.today()
    start = end - timedelta(days=days)

    # ── Moneylines summary ─────────────────────────────────────────────
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

    # ── Props aggregated by stat ──────────────────────────────────────
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
            {
                "stat": stat,
                "bets": bets,
                "hits": hits,
                "hit_rate": hit_rate,
            }
        )

    props.sort(key=lambda x: (x["hit_rate"] or 0), reverse=True)

    # ── Recent individual props (sample) ──────────────────────────────
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

    # ── Recent individual moneylines (sample) ─────────────────────────
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

    return jsonify(
        {
            "moneylines": moneylines,
            "props": props,
            "sample_props": sample_props,
            "sample_moneylines": sample_moneylines,
        }
    )

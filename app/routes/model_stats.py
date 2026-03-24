# app/routes/model_stats.py

from datetime import date, timedelta
from flask import Blueprint, jsonify, request

from app.models.models import db, ModelPropEval, ModelMoneylineEval

model_stats_bp = Blueprint("model_stats", __name__, url_prefix="/api")


@model_stats_bp.route("/model_outcomes")
def model_outcomes():
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30
    if days not in (7, 30, 90):
        days = 30

    end = date.today()
    start = end - timedelta(days=days)

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

    buckets = {}
    for p in props_q:
        b = buckets.setdefault(p.stat, {"bets": 0, "hits": 0})
        b["bets"] += 1
        if p.hit:
            b["hits"] += 1

    props = []
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

    return jsonify({"moneylines": moneylines, "props": props})

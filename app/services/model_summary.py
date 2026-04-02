"""Aggregated model outcomes (props + moneylines) for API and batch JSON writes."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import desc

from app.models.models import ModelMoneylineEval, ModelPropEval


def build_outcomes_summary(window_days: int | None) -> dict:
    """
    Aggregate resolved props and moneylines.

    window_days: rolling window ending today (inclusive), or None for all logged history.
    """
    end = date.today()
    start: date | None = (
        end - timedelta(days=window_days) if window_days is not None else None
    )

    # Moneylines
    ml_q = ModelMoneylineEval.query.filter(
        ModelMoneylineEval.date <= end,
        ModelMoneylineEval.correct.isnot(None),
    )
    if start is not None:
        ml_q = ml_q.filter(ModelMoneylineEval.date >= start)

    ml_bets = ml_q.count()
    ml_hits = ml_q.filter_by(correct=True).count()
    ml_hit_rate = (ml_hits / ml_bets) if ml_bets else None

    moneylines = {
        "bets": ml_bets,
        "hits": ml_hits,
        "hit_rate": ml_hit_rate,
    }

    # Props by stat
    props_q = ModelPropEval.query.filter(
        ModelPropEval.date <= end,
        ModelPropEval.hit.isnot(None),
    )
    if start is not None:
        props_q = props_q.filter(ModelPropEval.date >= start)

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

    total_bets = sum(p["bets"] for p in props)
    total_hits = sum(p["hits"] for p in props)
    prop_hit_rate = (total_hits / total_bets) if total_bets else None
    prop_overall = {
        "bets": total_bets,
        "hits": total_hits,
        "hit_rate": prop_hit_rate,
    }

    sample_props_base = ModelPropEval.query.filter(
        ModelPropEval.date <= end,
        ModelPropEval.hit.isnot(None),
    )
    if start is not None:
        sample_props_base = sample_props_base.filter(ModelPropEval.date >= start)

    sample_props_q = sample_props_base.order_by(
        desc(ModelPropEval.date), desc(ModelPropEval.confidence)
    ).limit(50)

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

    sample_ml_base = ModelMoneylineEval.query.filter(
        ModelMoneylineEval.date <= end,
        ModelMoneylineEval.correct.isnot(None),
    )
    if start is not None:
        sample_ml_base = sample_ml_base.filter(ModelMoneylineEval.date >= start)

    sample_ml_q = sample_ml_base.order_by(
        desc(ModelMoneylineEval.date), desc(ModelMoneylineEval.win_prob_home)
    ).limit(50)

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

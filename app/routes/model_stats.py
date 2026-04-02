# app/routes/model_stats.py

from flask import Blueprint, jsonify, request

from app.services.model_summary import build_outcomes_summary

model_stats_bp = Blueprint("model_stats", __name__, url_prefix="/api")


@model_stats_bp.route("/model_outcomes")
def model_outcomes():
    try:
        days = int(request.args.get("days", 0))
    except ValueError:
        days = 0
    if days not in (0, 7, 30, 90):
        days = 0

    window = None if days == 0 else days
    summary = build_outcomes_summary(window)
    return jsonify(summary)

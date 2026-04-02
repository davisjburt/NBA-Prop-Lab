# app/routes/model_stats.py

import json
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

from app.services.model_summary import build_outcomes_summary

DATA_DIR = Path(os.path.join(os.path.dirname(__file__), "..", "..", "data"))

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
    json_name = "model_stats_all.json" if days == 0 else f"model_stats_{days}.json"
    json_path = DATA_DIR / json_name

    # Prefer precomputed JSON when it has resolved bets. Empty JSON should not hide DB.
    if json_path.exists():
        with json_path.open() as f:
            snapshot = json.load(f)
        po = snapshot.get("prop_overall") or {}
        ml = snapshot.get("moneylines") or {}
        if (po.get("bets") or 0) > 0 or (ml.get("bets") or 0) > 0:
            return jsonify(snapshot)

    summary = build_outcomes_summary(window)
    return jsonify(summary)

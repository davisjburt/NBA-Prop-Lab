"""
scripts/archive/recover_model_history_from_git.py
--------------------------------------------------
Best-effort recovery of model eval history from git-tracked JSON snapshots.

It replays historical versions of:
  - data/prizepicks_results.json
  - data/moneylines.json
using each commit's calendar date (%cs) as the slate date.

Usage:
  # Preview only
  python scripts/archive/recover_model_history_from_git.py

  # One command: replay + resolve + model_stats / sync JSON
  python scripts/archive/recover_model_history_from_git.py --apply --finish
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.config import load_env  # noqa: E402

load_env()

from app import create_app  # noqa: E402
from app.models.models import ModelMoneylineEval, ModelPropEval, db  # noqa: E402
from scripts.update_model_stats import resolve_moneylines, resolve_props  # noqa: E402

MAX_PER_STAT = 25
PP_PATH = "data/prizepicks_results.json"
ML_PATH = "data/moneylines.json"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UPDATE_STATS_SCRIPT = REPO_ROOT / "scripts" / "update_model_stats.py"


def _run_git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL)


def _git_json(commit: str, relpath: str):
    try:
        raw = _run_git(["show", f"{commit}:{relpath}"])
    except subprocess.CalledProcessError:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _commits_for_path(relpath: str) -> list[str]:
    out = _run_git(["rev-list", "--reverse", "HEAD", "--", relpath]).strip()
    return [x for x in out.splitlines() if x]


def _commit_date(commit: str) -> dt.date:
    return dt.date.fromisoformat(_run_git(["show", "-s", "--format=%cs", commit]).strip())


def _build_prop_rows_for_date(slate_date: dt.date, pp_rows: list[dict]) -> list[dict]:
    by_stat: dict[str, list] = defaultdict(list)
    for row in pp_rows:
        stat = row.get("stat")
        if not stat:
            continue
        by_stat[stat].append(row)

    out: list[dict] = []
    for stat, rows in by_stat.items():
        rows.sort(key=lambda x: float(x.get("confidence", 0) or 0), reverse=True)
        for row in rows[:MAX_PER_STAT]:
            try:
                out.append(
                    {
                        "date": slate_date,
                        "player_id": int(row["id"]),
                        "player_name": str(row["name"]),
                        "team_abbr": str(row.get("team") or ""),
                        "stat": str(stat),
                        "line": float(row["line"]),
                        "confidence": float(row.get("confidence", 0) or 0),
                    }
                )
            except Exception:
                continue
    return out


def _build_ml_rows_for_date(slate_date: dt.date, moneylines: list[dict]) -> list[dict]:
    out: list[dict] = []
    for g in moneylines:
        try:
            out.append(
                {
                    "date": slate_date,
                    "home_abbr": str(g["home"]),
                    "away_abbr": str(g["away"]),
                    "predicted_winner": str(g["predicted_winner"]),
                    "win_prob_home": float(g["win_prob_home"]),
                    "win_prob_away": float(g["win_prob_away"]),
                    "spread": float(g["spread"]),
                }
            )
        except Exception:
            continue
    return out


def collect_replay_plan() -> list[dict]:
    commits = sorted(set(_commits_for_path(PP_PATH) + _commits_for_path(ML_PATH)))
    plan: list[dict] = []
    for sha in commits:
        slate_date = _commit_date(sha)
        pp_raw = _git_json(sha, PP_PATH) or []
        ml_raw = _git_json(sha, ML_PATH) or []
        if not isinstance(pp_raw, list):
            pp_raw = []
        if not isinstance(ml_raw, list):
            ml_raw = []
        plan.append(
            {
                "sha": sha,
                "date": slate_date,
                "prop_rows": _build_prop_rows_for_date(slate_date, pp_raw),
                "ml_rows": _build_ml_rows_for_date(slate_date, ml_raw),
            }
        )
    return plan


def summarize_plan(plan: list[dict]) -> None:
    unique_dates = sorted({p["date"] for p in plan if p["prop_rows"] or p["ml_rows"]})
    prop_rows = sum(len(p["prop_rows"]) for p in plan)
    ml_rows = sum(len(p["ml_rows"]) for p in plan)
    print(f"Commits scanned: {len(plan)}")
    print(f"Unique dates with usable snapshots: {len(unique_dates)}")
    if unique_dates:
        print(f"Date range: {unique_dates[0]} -> {unique_dates[-1]}")
    print(f"Rows to replay: {prop_rows} props, {ml_rows} moneylines")


def apply_plan(
    plan: list[dict],
    *,
    do_resolve: bool,
    silent_no_resolve: bool = False,
) -> None:
    applied_dates = 0
    inserted_props = 0
    inserted_mls = 0

    # Later commits for the same date should win.
    grouped: dict[dt.date, dict] = {}
    for p in plan:
        if p["prop_rows"] or p["ml_rows"]:
            grouped[p["date"]] = p

    for slate_date in sorted(grouped):
        p = grouped[slate_date]
        ModelPropEval.query.filter(ModelPropEval.date == slate_date).delete(
            synchronize_session=False
        )
        ModelMoneylineEval.query.filter(ModelMoneylineEval.date == slate_date).delete(
            synchronize_session=False
        )

        for row in p["prop_rows"]:
            db.session.add(ModelPropEval(**row))
        for row in p["ml_rows"]:
            db.session.add(ModelMoneylineEval(**row))

        inserted_props += len(p["prop_rows"])
        inserted_mls += len(p["ml_rows"])
        applied_dates += 1

        db.session.commit()
        print(
            f"  Applied {slate_date}: {len(p['prop_rows'])} props, "
            f"{len(p['ml_rows'])} moneylines",
            flush=True,
        )

    print(
        f"Inserted snapshots across {applied_dates} dates "
        f"({inserted_props} props, {inserted_mls} moneylines).",
        flush=True,
    )

    if not do_resolve:
        if not silent_no_resolve:
            print(
                "Skipped resolve. Run: python scripts/update_model_stats.py --skip-hydrate",
                flush=True,
            )
        return

    # Resolve outcomes for all historical unresolved rows.
    today = dt.date.today()
    print("Resolving props + moneylines (batched; may take 1–2 min)...", flush=True)
    resolve_props(today)
    resolve_moneylines(today)
    db.session.commit()
    print("Resolved historical outcomes where box-score data exists.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply replay to DB and resolve outcomes.",
    )
    parser.add_argument(
        "--finish",
        action="store_true",
        help=(
            "After replay, run update_model_stats.py --skip-hydrate "
            "(batched resolve + model_stats_*.json + model_*_eval_sync.json)."
        ),
    )
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="Only insert replayed rows; use --finish or run update_model_stats.py --skip-hydrate yourself.",
    )
    args = parser.parse_args()
    if args.finish and not args.apply:
        parser.error("--finish requires --apply")

    plan = collect_replay_plan()
    summarize_plan(plan)
    if not args.apply:
        print("\nDry run only. Re-run with --apply to write to DB.")
        return 0

    # --finish: resolve + JSON only in update_model_stats (single code path).
    do_inline_resolve = not args.no_resolve and not args.finish

    app = create_app()
    with app.app_context():
        apply_plan(
            plan,
            do_resolve=do_inline_resolve,
            silent_no_resolve=bool(args.finish),
        )

    if args.finish:
        print(
            f"Running {UPDATE_STATS_SCRIPT.name} --skip-hydrate ...",
            flush=True,
        )
        subprocess.check_call(
            [sys.executable, str(UPDATE_STATS_SCRIPT), "--skip-hydrate"],
            cwd=str(REPO_ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


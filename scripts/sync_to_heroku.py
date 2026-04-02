"""
scripts/sync_to_heroku.py
-------------------------
Bulk-syncs model_moneyline_eval and model_prop_eval to Heroku Postgres.

Prefers data/model_*_eval_sync.json (written after resolution in
update_model_stats). If those files are missing, falls back to
moneylines.json + prizepicks_results.json (predictions only).

Usage:
  python scripts/sync_to_heroku.py
"""

from pathlib import Path
import datetime
import json
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

sys.path.insert(0, str(BASE_DIR))

from app.config import load_env  # noqa: E402

load_env()


def _resolve_sync_database_url() -> str:
    """Heroku first; fall back to DATABASE_URL. Skips empty strings."""
    for key in ("HEROKU_DATABASE_URL", "DATABASE_URL"):
        raw = os.environ.get(key)
        if raw and str(raw).strip():
            url = str(raw).strip()
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            return url
    raise RuntimeError(
        "Set HEROKU_DATABASE_URL or DATABASE_URL in .env (non-empty)."
    )


DATABASE_URL = _resolve_sync_database_url()


def load_json(filename: str):
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    with path.open("r") as f:
        return json.load(f)


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_date(val) -> datetime.date:
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    return datetime.date.fromisoformat(str(val))


def _parse_dt(val):
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val
    s = str(val).replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(s)


def sync_moneylines(cur):
    now = _utcnow()
    sync_path = DATA_DIR / "model_moneyline_eval_sync.json"

    if sync_path.exists():
        with sync_path.open() as f:
            payload = json.load(f)
        if not isinstance(payload, list):
            raise ValueError("model_moneyline_eval_sync.json must be a JSON array")
        if not payload:
            today = datetime.date.today()
            cur.execute("DELETE FROM model_moneyline_eval WHERE date = %s", (today,))
            print("✅ Moneyline sync: empty payload — cleared today's date (UTC fallback)")
            return
        sync_date = _parse_date(payload[0]["date"])
        cur.execute(
            "DELETE FROM model_moneyline_eval WHERE date = %s",
            (sync_date,),
        )
        rows = [
            (
                _parse_date(g["date"]),
                g["home_abbr"],
                g["away_abbr"],
                g["predicted_winner"],
                g["win_prob_home"],
                g["win_prob_away"],
                g["spread"],
                g.get("actual_winner"),
                g.get("margin"),
                g.get("correct"),
                _parse_dt(g.get("created_at")) or now,
                _parse_dt(g.get("updated_at")) or now,
            )
            for g in payload
        ]
        label = "model_moneyline_eval_sync.json"
    else:
        today = datetime.date.today()
        moneylines = load_json("moneylines.json")
        cur.execute("DELETE FROM model_moneyline_eval WHERE date = %s", (today,))
        rows = [
            (
                today,
                g["home"],
                g["away"],
                g["predicted_winner"],
                g["win_prob_home"],
                g["win_prob_away"],
                g["spread"],
                None,
                None,
                None,
                now,
                now,
            )
            for g in moneylines
        ]
        label = "moneylines.json (fallback)"

    if rows:
        execute_values(
            cur,
            """
            INSERT INTO model_moneyline_eval (
                date,
                home_abbr,
                away_abbr,
                predicted_winner,
                win_prob_home,
                win_prob_away,
                spread,
                actual_winner,
                margin,
                correct,
                created_at,
                updated_at
            ) VALUES %s
            """,
            rows,
        )

    print(f"✅ Synced {len(rows)} moneyline rows ({label})")


def sync_props(cur):
    now = _utcnow()
    sync_path = DATA_DIR / "model_prop_eval_sync.json"

    if sync_path.exists():
        with sync_path.open() as f:
            payload = json.load(f)
        if not isinstance(payload, list):
            raise ValueError("model_prop_eval_sync.json must be a JSON array")
        if not payload:
            today = datetime.date.today()
            cur.execute("DELETE FROM model_prop_eval WHERE date = %s", (today,))
            print("✅ Prop sync: empty payload — cleared today's date (UTC fallback)")
            return
        sync_date = _parse_date(payload[0]["date"])
        cur.execute("DELETE FROM model_prop_eval WHERE date = %s", (sync_date,))
        rows_to_insert = [
            (
                _parse_date(r["date"]),
                r["player_id"],
                r["player_name"],
                r["team_abbr"],
                r["stat"],
                r["line"],
                r["confidence"],
                r.get("result_value"),
                r.get("hit"),
                _parse_dt(r.get("created_at")) or now,
                _parse_dt(r.get("updated_at")) or now,
            )
            for r in payload
        ]
        label = "model_prop_eval_sync.json"
    else:
        today = datetime.date.today()
        pp_results = load_json("prizepicks_results.json")
        cur.execute("DELETE FROM model_prop_eval WHERE date = %s", (today,))

        max_per_stat = 25
        by_stat = {}
        for row in pp_results:
            stat = row["stat"]
            by_stat.setdefault(stat, []).append(row)

        rows_to_insert = []
        for stat, rows in by_stat.items():
            rows.sort(key=lambda x: x["confidence"], reverse=True)
            for row in rows[:max_per_stat]:
                rows_to_insert.append(
                    (
                        today,
                        row["id"],
                        row["name"],
                        row["team"],
                        stat,
                        row["line"],
                        row["confidence"],
                        None,
                        None,
                        now,
                        now,
                    )
                )
        label = "prizepicks_results.json (fallback)"

    if rows_to_insert:
        execute_values(
            cur,
            """
            INSERT INTO model_prop_eval (
                date,
                player_id,
                player_name,
                team_abbr,
                stat,
                line,
                confidence,
                result_value,
                hit,
                created_at,
                updated_at
            ) VALUES %s
            """,
            rows_to_insert,
        )

    print(f"✅ Synced {len(rows_to_insert)} prop rows ({label})")


def main():
    print("🔌 Connecting to Heroku Postgres...")
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            sync_moneylines(cur)
            sync_props(cur)

        conn.commit()
        print("🏁 Heroku sync complete")
    except Exception as e:
        conn.rollback()
        print(f"❌ Sync failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
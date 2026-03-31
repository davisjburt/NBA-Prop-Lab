"""
scripts/sync_to_heroku.py
-------------------------
Reads locally generated JSON files from data/ and bulk-syncs the
derived model tables to Heroku Postgres.

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
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


def load_json(filename: str):
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    with path.open("r") as f:
        return json.load(f)


def sync_moneylines(cur):
    today = datetime.date.today()
    now = datetime.datetime.now()

    moneylines = load_json("moneylines.json")

    cur.execute("TRUNCATE TABLE model_moneyline_eval RESTART IDENTITY CASCADE")

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

    print(f"✅ Synced {len(rows)} moneyline rows")


def sync_props(cur):
    today = datetime.date.today()
    pp_results = load_json("prizepicks_results.json")

    cur.execute("TRUNCATE TABLE model_prop_eval RESTART IDENTITY CASCADE")

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
                )
            )

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
                confidence
            ) VALUES %s
            """,
            rows_to_insert,
        )

    print(f"✅ Synced {len(rows_to_insert)} prop rows")


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
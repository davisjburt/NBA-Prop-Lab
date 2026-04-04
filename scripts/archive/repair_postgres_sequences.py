"""
Repair PostgreSQL SERIAL sequences after CSV/SQLite→Postgres imports.

When rows are inserted with explicit ids, nextval() can fall behind MAX(id),
causing primary-key collisions. daily_update then hits IntegrityError, rolls
back, and appears to leave everything “up to date.”

Usage (same DATABASE_URL / .env as the app):
  python scripts/archive/repair_postgres_sequences.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app.config import load_env  # noqa: E402
from app import create_app  # noqa: E402
from app.models.models import db  # noqa: E402

load_env()

# Tables with single integer PK column "id" backed by sequence {table}_id_seq
TABLES = (
    "players",
    "player_game_stats",
    "model_prop_eval",
    "model_moneyline_eval",
)


def main() -> None:
    app = create_app()
    with app.app_context():
        dialect = db.engine.dialect.name
        if dialect != "postgresql":
            print(f"Skipping (database is {dialect}, not postgresql).")
            return

        insp = inspect(db.engine)
        for table in TABLES:
            if not insp.has_table(table):
                print(f"⚠️  Table missing: {table}")
                continue
            pk = insp.get_pk_constraint(table)
            cols = pk.get("constrained_columns") or []
            if cols != ["id"]:
                print(f"⚠️  Skip {table}: unexpected PK {cols}")
                continue
            seq = f"{table}_id_seq"
            mx = db.session.execute(
                text(f'SELECT COALESCE(MAX(id), 1) FROM "{table}"')
            ).scalar()
            # true => next nextval() returns mx + 1
            db.session.execute(
                text("SELECT setval(:seq, :mx, true)"),
                {"seq": seq, "mx": int(mx)},
            )
            db.session.commit()
            last = db.session.execute(text(f"SELECT last_value FROM {seq}")).scalar()
            print(f"✅  {table}: MAX(id)={mx}, {seq}.last_value={last}")


if __name__ == "__main__":
    main()

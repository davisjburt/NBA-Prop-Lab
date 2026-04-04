"""
scripts/archive/check_model_history.py
----------------------------------------
Quick DB sanity check for model history.

Shows:
- active DATABASE_URL target (masked),
- total and resolved row counts,
- min/max dates,
- most recent dates with row counts.
"""

import os
import sys

from sqlalchemy import func

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.config import load_env  # noqa: E402

load_env()

from app import create_app  # noqa: E402
from app.models.models import db, ModelMoneylineEval, ModelPropEval  # noqa: E402


def _mask_db_url(url: str) -> str:
    if not url:
        return "(empty)"
    if "@" in url:
        left, right = url.rsplit("@", 1)
        if "://" in left:
            scheme, creds = left.split("://", 1)
            if ":" in creds:
                user = creds.split(":", 1)[0]
                return f"{scheme}://{user}:***@{right}"
    return url


def _print_table_summary(name: str, model, resolved_col: str) -> None:
    total = db.session.query(func.count(model.id)).scalar() or 0
    resolved = (
        db.session.query(func.count(model.id))
        .filter(getattr(model, resolved_col).isnot(None))
        .scalar()
        or 0
    )
    min_date, max_date = (
        db.session.query(func.min(model.date), func.max(model.date)).one()
    )
    recent = (
        db.session.query(model.date, func.count(model.id))
        .group_by(model.date)
        .order_by(model.date.desc())
        .limit(10)
        .all()
    )

    print(f"\n{name}")
    print(f"  total rows:    {total}")
    print(f"  resolved rows: {resolved}")
    print(f"  date range:    {min_date} -> {max_date}")
    print("  recent dates:  " + (", ".join(f"{d}:{c}" for d, c in recent) or "(none)"))


def main() -> int:
    db_url = os.environ.get("DATABASE_URL", "")
    print("DATABASE_URL:", _mask_db_url(db_url))

    app = create_app()
    with app.app_context():
        _print_table_summary("model_prop_eval", ModelPropEval, "hit")
        _print_table_summary("model_moneyline_eval", ModelMoneylineEval, "correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


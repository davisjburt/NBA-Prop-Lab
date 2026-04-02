import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import load_env  # noqa: E402

load_env()

from app import create_app
from app.models.models import db, PlayerGameStat

def dedup():
    app = create_app()
    with app.app_context():
        seen    = set()
        deleted = 0
        rows    = PlayerGameStat.query.order_by(PlayerGameStat.id).all()
        for row in rows:
            key = (row.player_id, str(row.date))
            if key in seen:
                db.session.delete(row)
                deleted += 1
            else:
                seen.add(key)
        db.session.commit()
        print(f"✅ Removed {deleted} duplicate rows.")

if __name__ == "__main__":
    dedup()

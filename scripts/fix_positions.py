import sys, os, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models.models import db, Player
from nba_api.stats.endpoints import commonplayerinfo

def normalize_position(pos_str):
    pos_str = pos_str.strip().lower()
    mapping = {
        "point guard":    "PG", "shooting guard":  "SG",
        "small forward":  "SF", "power forward":   "PF",
        "center":         "C",  "guard-forward":   "SG",
        "forward-guard":  "SF", "forward-center":  "PF",
        "center-forward": "C",  "guard":            "G",
        "forward":        "F",
    }
    return mapping.get(pos_str, pos_str[:3].upper())

def fix():
    app = create_app()
    with app.app_context():
        players = Player.query.all()
        total   = len(players)
        for i, p in enumerate(players):
            print(f"[{i+1}/{total}] {p.name}", end=" ... ", flush=True)
            try:
                time.sleep(0.6)
                info = commonplayerinfo.CommonPlayerInfo(player_id=p.id)
                df   = info.get_data_frames()[0]
                p.position  = normalize_position(df["POSITION"].iloc[0])
                p.team_abbr = df["TEAM_ABBREVIATION"].iloc[0] or "N/A"
                db.session.commit()
                print(f"✅ {p.position}")
            except Exception as e:
                db.session.rollback()
                print(f"❌ {e}")

if __name__ == "__main__":
    fix()

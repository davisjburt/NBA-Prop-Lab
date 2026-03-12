import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models.models import db, Player, PlayerGameStat
from app.services.nba_fetcher import fetch_game_logs
from nba_api.stats.static import players
import time

SEASON = "2024-25"

# Add any players you want to seed here: (player_id, name, team, position)
PLAYERS_TO_SEED = [
    (203999, "Nikola Jokic",    "DEN", "C"),
    (1629029, "Ja Morant",      "MEM", "PG"),
    (1628384, "Jayson Tatum",   "BOS", "SF"),
    (2544,    "LeBron James",   "LAL", "SF"),
    (203507,  "Giannis Antetokounmpo", "MIL", "PF"),
]

def seed():
    app = create_app()
    with app.app_context():
        for player_id, name, team, position in PLAYERS_TO_SEED:
            # Upsert player
            player = Player.query.get(player_id)
            if not player:
                player = Player(id=player_id, name=name, team_abbr=team, position=position)
                db.session.add(player)
                db.session.commit()
                print(f"Added player: {name}")
            else:
                print(f"Player already exists: {name}")

            # Fetch and insert game logs
            print(f"  Fetching logs for {name}...")
            try:
                df = fetch_game_logs(player_id, season=SEASON)
                new_rows = 0
                for _, row in df.iterrows():
                    exists = PlayerGameStat.query.filter_by(
                        player_id=player_id, date=row["date"]
                    ).first()
                    if not exists:
                        stat = PlayerGameStat(
                            player_id=player_id,
                            date=row["date"],
                            matchup=row["matchup"],
                            location=row["location"],
                            min=row["min"],  pts=row["pts"],  reb=row["reb"],
                            ast=row["ast"],  stl=row["stl"],  blk=row["blk"],
                            fg3m=row["fg3m"],tov=row["tov"]
                        )
                        db.session.add(stat)
                        new_rows += 1
                db.session.commit()
                print(f"  ✅ {new_rows} new game logs added for {name}")
            except Exception as e:
                print(f"  ❌ Error fetching {name}: {e}")
            time.sleep(1)

if __name__ == "__main__":
    seed()

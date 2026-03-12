import sys, os, time
from datetime import date, timedelta
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models.models import db, Player, PlayerGameStat
from app.services.nba_fetcher import fetch_game_logs
from sqlalchemy.exc import IntegrityError

SEASON = "2025-26"

def update():
    app = create_app()
    yesterday = date.today() - timedelta(days=1)
    print(f"Running daily update for {yesterday}...\n")

    with app.app_context():
        players = Player.query.all()
        total   = len(players)
        updated = 0

        for i, player in enumerate(players):
            print(f"[{i+1}/{total}] {player.name}", end=" ... ", flush=True)
            try:
                df = fetch_game_logs(player.id, season=SEASON)
                if df.empty:
                    print("no games")
                    continue

                new_rows = 0
                for _, row in df.iterrows():
                    try:
                        db.session.add(PlayerGameStat(
                            player_id=player.id,
                            date=row["date"],      matchup=row["matchup"],
                            location=row["location"], min=row["min"],
                            pts=row["pts"],         reb=row["reb"],
                            ast=row["ast"],         stl=row["stl"],
                            blk=row["blk"],         fg3m=row["fg3m"],
                            tov=row["tov"]
                        ))
                        db.session.flush()
                        new_rows += 1
                    except IntegrityError:
                        db.session.rollback()

                db.session.commit()
                if new_rows:
                    print(f"✅ {new_rows} new games")
                    updated += 1
                else:
                    print("up to date")

            except Exception as e:
                db.session.rollback()
                print(f"❌ {e}")

            time.sleep(0.8)

        print(f"\n✅ Update complete — {updated} players refreshed.")

if __name__ == "__main__":
    update()

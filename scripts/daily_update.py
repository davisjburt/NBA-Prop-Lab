import sys, os, time
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models.models import db, Player, PlayerGameStat
from app.services.nba_fetcher import fetch_game_logs
from sqlalchemy.exc import IntegrityError

SEASON      = "2025-26"
MAX_WORKERS = 2

def update_player(player_id, player_name, last_logged, app):
    time.sleep(0.5)
    with app.app_context():
        try:
            df = fetch_game_logs(player_id, season=SEASON)
            if df.empty:
                return player_name, 0, None

            # Only insert rows newer than what we already have
            if last_logged:
                df = df[df["date"] > last_logged]

            if df.empty:
                return player_name, 0, None

            new_rows = 0
            for _, row in df.iterrows():
                try:
                    db.session.add(PlayerGameStat(
                        player_id=player_id,
                        date=row["date"],         matchup=row["matchup"],
                        location=row["location"],  min=row["min"],
                        pts=row["pts"],            reb=row["reb"],
                        ast=row["ast"],            stl=row["stl"],
                        blk=row["blk"],            fg3m=row["fg3m"],
                        tov=row["tov"]
                    ))
                    db.session.flush()
                    new_rows += 1
                except IntegrityError:
                    db.session.rollback()

            db.session.commit()
            return player_name, new_rows, None
        except Exception as e:
            db.session.rollback()
            return player_name, 0, str(e)

def update():
    app = create_app()
    print(f"Running update (catching up all missed games)...\n")

    with app.app_context():
        players = Player.query.all()

        # Build list of (player_id, name, last_logged_date)
        player_list = []
        for p in players:
            latest = db.session.query(db.func.max(PlayerGameStat.date)) \
                        .filter_by(player_id=p.id).scalar()
            player_list.append((p.id, p.name, latest))

    total   = len(player_list)
    updated = 0
    skipped = 0

    print(f"Checking {total} players for new games...\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(update_player, pid, name, last, app): name
            for pid, name, last in player_list
        }
        done = 0
        for future in as_completed(futures):
            name, new_rows, error = future.result()
            done += 1
            if error:
                print(f"[{done}/{total}] {name} ... ❌ {error}")
            elif new_rows:
                print(f"[{done}/{total}] {name} ... ✅ {new_rows} new games")
                updated += 1
            else:
                skipped += 1
                if skipped % 50 == 0:
                    print(f"  ... {skipped} players up to date so far")

    print(f"\n✅ Update complete — {updated} players had new games, {skipped} were already up to date.")

if __name__ == "__main__":
    update()

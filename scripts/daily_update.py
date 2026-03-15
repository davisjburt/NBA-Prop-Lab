import sys, os, time
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models.models import db, Player, PlayerGameStat
from app.services.nba_fetcher import fetch_game_logs
from sqlalchemy.exc import IntegrityError

SEASON      = "2025-26"
MAX_WORKERS = 2
DEBUG_PLAYERS = {"Shai Gilgeous-Alexander"}  # add any other names here to debug

def update_player(player_id, player_name, last_logged, app):
    time.sleep(0.5)
    with app.app_context():
        try:
            df = fetch_game_logs(player_id, season=SEASON)

            # ── DEBUG ──────────────────────────────────────────────
            if player_name in DEBUG_PLAYERS:
                print(f"\n{'='*50}")
                print(f"DEBUG: {player_name}")
                print(f"  last_logged type : {type(last_logged)}")
                print(f"  last_logged value: {last_logged}")
                if df.empty:
                    print(f"  fetch result     : EMPTY DATAFRAME")
                else:
                    print(f"  df row count     : {len(df)}")
                    print(f"  df['date'] dtype : {df['date'].dtype}")
                    print(f"  df['date'] sample: {df['date'].head(3).tolist()}")
                    print(f"  date[0] type     : {type(df['date'].iloc[0])}")
                print(f"{'='*50}\n")
            # ──────────────────────────────────────────────────────

            if df.empty:
                return player_name, 0, "empty dataframe from API"

            # Normalize dates to datetime.date
            df["date"] = pd.to_datetime(df["date"]).dt.date

            if last_logged:
                last_logged = last_logged.date() \
                    if hasattr(last_logged, "date") else last_logged
                df = df[df["date"] > last_logged]

                if player_name in DEBUG_PLAYERS:
                    print(f"DEBUG {player_name}: {len(df)} rows after date filter (> {last_logged})\n")

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
    print("Running update (catching up all missed games)...\n")

    with app.app_context():
        players = Player.query.all()
        player_list = []
        for p in players:
            latest = db.session.query(db.func.max(PlayerGameStat.date)) \
                        .filter_by(player_id=p.id).scalar()
            player_list.append((p.id, p.name, latest))

        with_data    = [(pid, n, l) for pid, n, l in player_list if l]
        without_data = [(pid, n, l) for pid, n, l in player_list if not l]
        if with_data:
            most_recent = max(l for _, _, l in with_data)
            print(f"📅 Most recent game in DB : {most_recent}")
        print(f"📊 {len(with_data)} players have data, {len(without_data)} have none\n")

    total   = len(player_list)
    updated = 0
    skipped = 0

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
                    print(f"  ({skipped} players up to date so far...)")

    print(f"\n✅ Done — {updated} players updated, {skipped} already up to date.")

if __name__ == "__main__":
    update()

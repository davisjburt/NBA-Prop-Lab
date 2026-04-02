"""
scripts/daily_update.py
-----------------------
Headless version of the daily updater for GitHub Actions.
Reads DATABASE_URL from environment (set as a GitHub Actions secret).
Ingests box scores into player_game_stats (required for fetch_data /
update_model_stats). Derived model_eval rows are JSON-only until
update_model_stats + sync_to_heroku. No GUI — pure Python.

If every player shows “no new games” but the NBA API has newer box scores,
PostgreSQL PK sequences may be behind MAX(id) (common after a DB import).
Run: python scripts/repair_postgres_sequences.py
"""

import sys, os, time, random
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import load_env  # noqa: E402

load_env()

SEASON      = "2025-26"
MAX_WORKERS = 2   # keep low — nba_api rate-limits aggressively


def run():
    from app import create_app
    from app.models.models import db, Player, PlayerGameStat
    from app.services.nba_fetcher import fetch_game_logs
    from nba_api.stats.endpoints import leaguegamelog
    from nba_api.stats.static import teams as nba_teams
    from sqlalchemy.exc import IntegrityError
    import pandas as pd

    app = create_app()

    print("⏳  Loading player list...")
    with app.app_context():
        players    = Player.query.all()
        player_map = {}
        for p in players:
            if p.team_abbr:
                player_map.setdefault(p.team_abbr.upper(), []).append(p)

        global_last = db.session.query(
            db.func.max(PlayerGameStat.date)
        ).scalar()

        # Batch query latest logged date per player (faster than N queries).
        latest_rows = (
            db.session.query(
                PlayerGameStat.player_id,
                db.func.max(PlayerGameStat.date).label("latest_date"),
            )
            .group_by(PlayerGameStat.player_id)
            .all()
        )
        last_logged_map = {row.player_id: row.latest_date for row in latest_rows}
        for p in players:
            last_logged_map.setdefault(p.id, None)

    print(f"✅  Loaded {len(players)} players")
    print(f"📅  Last logged game: {global_last or 'None'}\n")
    print("🔍  Finding teams with new games...")

    try:
        time.sleep(0.6)
        game_log = leaguegamelog.LeagueGameLog(
            season=SEASON,
            season_type_all_star="Regular Season",
            date_from_nullable=str(global_last) if global_last else "",
            timeout=30
        )
        gdf        = game_log.get_data_frames()[0]
        id_to_abbr = {str(t["id"]): t["abbreviation"] for t in nba_teams.get_teams()}
        active_teams = set(
            id_to_abbr.get(str(int(tid)), "")
            for tid in gdf["TEAM_ID"].unique()
            if id_to_abbr.get(str(int(tid)))
        )
        print(f"🏀  {len(active_teams)} teams with new games: {', '.join(sorted(active_teams))}\n")
    except Exception as e:
        print(f"⚠️  Could not filter by team — checking all players ({e})")
        active_teams = set(player_map.keys())

    with app.app_context():
        candidates      = []
        skipped_upfront = 0
        for p in players:
            team = (p.team_abbr or "").upper()
            if team in active_teams:
                candidates.append((p.id, p.name, last_logged_map[p.id]))
            else:
                skipped_upfront += 1

    total = len(candidates)
    print(f"⚡  Skipping {skipped_upfront} players on idle teams")
    print(f"✅  Checking {total} players on active teams\n")

    updated = 0
    errors  = 0
    skipped = skipped_upfront
    done    = 0

    def update_player(player_id, player_name, last_logged):
        time.sleep(0.5 + random.uniform(0, 0.2))
        with app.app_context():
            try:
                df = fetch_game_logs(player_id, season=SEASON)
                if df.empty:
                    return player_name, 0, None

                df["date"] = pd.to_datetime(df["date"]).dt.date
                if last_logged:
                    last_logged_d = last_logged.date() if hasattr(last_logged, "date") else last_logged
                    df = df[df["date"] > last_logged_d]

                if df.empty:
                    return player_name, 0, None

                new_rows = 0
                for _, row in df.iterrows():
                    try:
                        db.session.add(PlayerGameStat(
                            player_id=player_id,
                            date=row["date"],          matchup=row["matchup"],
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

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(update_player, pid, name, last): name
            for pid, name, last in candidates
        }
        for future in as_completed(futures):
            name, new_rows, error = future.result()
            done += 1

            if error:
                errors  += 1
                print(f"❌  [{done}/{total}] {name} — {error[:80]}")
            elif new_rows:
                updated += 1
                print(f"✅  [{done}/{total}] {name} — +{new_rows} game{'s' if new_rows > 1 else ''}")
            else:
                skipped += 1
                # Only print every 10 skips to keep logs readable
                if skipped % 10 == 0:
                    print(f"⏭️   {skipped} players skipped so far...")

    print(f"\n🏁  Done — {updated} updated · {skipped} skipped · {errors} errors")

    # Exit with error code if there were any errors, so Actions marks the run as failed
    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    run()
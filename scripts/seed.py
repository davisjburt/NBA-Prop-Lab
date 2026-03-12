import sys, os, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models.models import db, Player, PlayerGameStat
from app.services.nba_fetcher import fetch_game_logs
from nba_api.stats.static import players as nba_players
from nba_api.stats.endpoints import commonplayerinfo

SEASON = "2025-26"

def get_team_and_position(player_id):
    try:
        time.sleep(0.6)
        info = commonplayerinfo.CommonPlayerInfo(player_id=player_id)
        df = info.get_data_frames()[0]
        team = df["TEAM_ABBREVIATION"].iloc[0]
        pos  = df["POSITION"].iloc[0].split("-")[0].strip()[:3]
        return team or "N/A", pos or "N/A"
    except:
        return "N/A", "N/A"

def seed():
    app = create_app()
    all_players = nba_players.get_active_players()
    total = len(all_players)
    print(f"Found {total} active players. Starting seed...\n")

    with app.app_context():
        for i, p in enumerate(all_players):
            player_id = p["id"]
            name      = p["full_name"]
            print(f"[{i+1}/{total}] {name}", end=" ... ", flush=True)

            # Skip if already has stats for this season
            existing_stats = PlayerGameStat.query.filter_by(player_id=player_id).first()
            if existing_stats:
                print("skipped (already seeded)")
                continue

            # Fetch team/position
            team, pos = get_team_and_position(player_id)

            # Upsert player using merge (handles both insert and update)
            player = db.session.get(Player, player_id)
            if not player:
                player = Player(id=player_id, name=name, team_abbr=team, position=pos)
                db.session.add(player)
            else:
                player.team_abbr = team
                player.position  = pos
            
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"❌ player upsert failed: {e}")
                continue

            # Fetch game logs
            try:
                df = fetch_game_logs(player_id, season=SEASON)
                if df.empty:
                    print("no games")
                    continue
                for _, row in df.iterrows():
                    db.session.add(PlayerGameStat(
                        player_id=player_id,
                        date=row["date"],      matchup=row["matchup"],
                        location=row["location"], min=row["min"],
                        pts=row["pts"],         reb=row["reb"],
                        ast=row["ast"],         stl=row["stl"],
                        blk=row["blk"],         fg3m=row["fg3m"],
                        tov=row["tov"]
                    ))
                db.session.commit()
                print(f"✅ {len(df)} games")
            except Exception as e:
                db.session.rollback()
                print(f"❌ {e}")

            time.sleep(0.8)

    print("\n✅ Seed complete!")

if __name__ == "__main__":
    seed()

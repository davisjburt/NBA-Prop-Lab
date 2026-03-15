from nba_api.stats.endpoints import playergamelog, leaguedashteamstats, scoreboardv2
from nba_api.stats.static import players, teams as nba_teams
import pandas as pd
import datetime, time, random

SEASON = "2025-26"

def fetch_all_players() -> pd.DataFrame:
    time.sleep(0.6)
    all_players = players.get_active_players()
    return pd.DataFrame(all_players)[["id", "full_name"]]

def fetch_game_logs(player_id: int, season: str = SEASON) -> pd.DataFrame:
    for attempt in range(3):
        try:
            time.sleep(0.6 + random.uniform(0, 0.4))
            logs = playergamelog.PlayerGameLog(
                player_id=player_id,
                season=season,
                season_type_all_star="Regular Season",
                timeout=30
            )
            df = logs.get_data_frames()[0]
            if df.empty:
                if attempt < 2:
                    time.sleep(2 ** attempt + random.uniform(1, 2))
                    continue
                return pd.DataFrame()
            df = df.rename(columns={
                "GAME_DATE": "date",  "MATCHUP": "matchup",
                "MIN":       "min",   "PTS":     "pts",
                "REB":       "reb",   "AST":     "ast",
                "STL":       "stl",   "BLK":     "blk",
                "FG3M":      "fg3m",  "TOV":     "tov"
            })
            df["location"] = df["matchup"].apply(lambda x: "Home" if "vs." in x else "Road")
            df["date"]     = pd.to_datetime(df["date"]).dt.date
            return df[["date", "matchup", "location", "min", "pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]]
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt + 1)
            else:
                raise e
    return pd.DataFrame()

def fetch_opponent_defense(season: str = SEASON) -> dict:
    time.sleep(0.6)
    stats = leaguedashteamstats.LeagueDashTeamStats(
        season=season,
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Opponent",
        per_mode_detailed="PerGame",
        timeout=30
    )
    df = stats.get_data_frames()[0]
    if df.empty:
        return {}

    id_to_abbr = {t["id"]: t["abbreviation"] for t in nba_teams.get_teams()}

    result = {}
    for _, row in df.iterrows():
        abbr = id_to_abbr.get(int(row["TEAM_ID"]))
        if not abbr:
            continue
        result[abbr] = {
            "opp_pts":  row.get("OPP_PTS"),
            "opp_reb":  row.get("OPP_REB"),
            "opp_ast":  row.get("OPP_AST"),
            "opp_stl":  row.get("OPP_STL"),
            "opp_blk":  row.get("OPP_BLK"),
            "opp_tov":  row.get("OPP_TOV"),
            "opp_fg3m": row.get("OPP_FG3M"),
        }

    print(f"✅ Opponent defense loaded for {len(result)} teams")
    return result

def fetch_todays_matchups() -> dict:
    """
    Returns dict of team_abbr -> {"opponent": abbr, "location": "Home"/"Road"}
    using today's NBA scoreboard.
    """
    try:
        time.sleep(0.6)
        id_to_abbr = {t["id"]: t["abbreviation"] for t in nba_teams.get_teams()}
        today = datetime.date.today().strftime("%m/%d/%Y")
        board = scoreboardv2.ScoreboardV2(game_date=today, day_offset=0, timeout=15)
        games = board.get_data_frames()[0]  # GameHeader

        matchups = {}
        for _, row in games.iterrows():
            home_id = int(row["HOME_TEAM_ID"])
            away_id = int(row["VISITOR_TEAM_ID"])
            home    = id_to_abbr.get(home_id)
            away    = id_to_abbr.get(away_id)
            if home and away:
                matchups[home] = {"opponent": away, "location": "Home"}
                matchups[away] = {"opponent": home, "location": "Road"}

        print(f"✅ Today's matchups loaded: {list(matchups.keys())}")
        return matchups
    except Exception as e:
        print(f"⚠️  fetch_todays_matchups failed: {e}")
        return {}

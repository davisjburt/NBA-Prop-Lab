from nba_api.stats.endpoints import playergamelog, leaguedashteamstats
from nba_api.stats.static import players
import pandas as pd
import time, random

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
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df[["date", "matchup", "location", "min", "pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]]
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt + 1)
            else:
                raise e
    return pd.DataFrame()

def fetch_opponent_defense(season: str = SEASON) -> dict:
    """
    Returns a dict keyed by team abbreviation with allowed-per-game stats.
    Used to compute matchup difficulty multipliers.
    """
    time.sleep(0.6)
    stats = leaguedashteamstats.LeagueDashTeamStats(
        season=season,
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Opponent",
        per_mode_simple="PerGame",
        timeout=30
    )
    df = stats.get_data_frames()[0]
    df = df.rename(columns={
        "TEAM_ABBREVIATION": "team",
        "OPP_PTS":  "opp_pts",
        "OPP_REB":  "opp_reb",
        "OPP_AST":  "opp_ast",
        "OPP_STL":  "opp_stl",
        "OPP_BLK":  "opp_blk",
        "OPP_TOV":  "opp_tov",
        "OPP_FG3M": "opp_fg3m",
    })
    keep = ["team", "opp_pts", "opp_reb", "opp_ast", "opp_stl", "opp_blk", "opp_tov", "opp_fg3m"]
    available = [c for c in keep if c in df.columns]
    df = df[available]
    return df.set_index("team").to_dict(orient="index")

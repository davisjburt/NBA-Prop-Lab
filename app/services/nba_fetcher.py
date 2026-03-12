from nba_api.stats.endpoints import playergamelog, playerindex
import pandas as pd
import time

def fetch_all_players() -> pd.DataFrame:
    time.sleep(0.6)
    from nba_api.stats.static import players
    all_players = players.get_active_players()
    return pd.DataFrame(all_players)[["id", "full_name", "team_abbreviation" if "team_abbreviation" in pd.DataFrame(all_players).columns else "id"]]

def fetch_game_logs(player_id: int, season: str = "2024-25") -> pd.DataFrame:
    time.sleep(0.6)
    logs = playergamelog.PlayerGameLog(
        player_id=player_id,
        season=season,
        season_type_all_star="Regular Season"
    )
    df = logs.get_data_frames()[0]
    df = df.rename(columns={
        "GAME_DATE": "date", "MATCHUP": "matchup",
        "MIN": "min",  "PTS": "pts",  "REB": "reb",
        "AST": "ast",  "STL": "stl",  "BLK": "blk",
        "FG3M": "fg3m","TOV": "tov"
    })
    df["location"] = df["matchup"].apply(lambda x: "Home" if "vs." in x else "Road")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[["date", "matchup", "location", "min", "pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]]

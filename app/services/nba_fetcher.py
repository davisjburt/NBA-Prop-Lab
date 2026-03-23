"""
app/services/nba_fetcher.py
---------------------------
Wraps nba_api with rate-limit-safe sleep delays and retry logic.
Added in v2: fetch_team_records, fetch_h2h_season, fetch_injuries.
"""

from nba_api.stats.endpoints import (
    playergamelog,
    leaguedashteamstats,
    scoreboardv2,
    teamgamelog,
    leaguegamelog,
)
from nba_api.stats.static import players, teams as nba_teams
import pandas as pd
import datetime
import time
import random
import requests

SEASON = "2025-26"

# ── Existing helpers ──────────────────────────────────────────────────────


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
                timeout=30,
            )
            df = logs.get_data_frames()[0]
            if df.empty:
                if attempt < 2:
                    time.sleep(2**attempt + random.uniform(1, 2))
                    continue
                return pd.DataFrame()
            df = df.rename(
                columns={
                    "GAME_DATE": "date",
                    "MATCHUP": "matchup",
                    "MIN": "min",
                    "PTS": "pts",
                    "REB": "reb",
                    "AST": "ast",
                    "STL": "stl",
                    "BLK": "blk",
                    "FG3M": "fg3m",
                    "TOV": "tov",
                }
            )
            df["location"] = df["matchup"].apply(
                lambda x: "Home" if "vs." in x else "Road"
            )
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df[
                [
                    "date",
                    "matchup",
                    "location",
                    "min",
                    "pts",
                    "reb",
                    "ast",
                    "stl",
                    "blk",
                    "fg3m",
                    "tov",
                ]
            ]
        except Exception as e:
            if attempt < 2:
                time.sleep(2**attempt + 1)
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
        timeout=30,
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
            "opp_pts": row.get("OPP_PTS"),
            "opp_reb": row.get("OPP_REB"),
            "opp_ast": row.get("OPP_AST"),
            "opp_stl": row.get("OPP_STL"),
            "opp_blk": row.get("OPP_BLK"),
            "opp_tov": row.get("OPP_TOV"),
            "opp_fg3m": row.get("OPP_FG3M"),
        }
    print(f"✅ Opponent defense loaded for {len(result)} teams")
    return result


def fetch_todays_matchups() -> dict:
    """
    Returns dict of team_abbr -> {"opponent": abbr, "location": "Home"/"Road"}
    """
    try:
        time.sleep(0.6)
        id_to_abbr = {t["id"]: t["abbreviation"] for t in nba_teams.get_teams()}
        today = datetime.date.today().strftime("%m/%d/%Y")
        board = scoreboardv2.ScoreboardV2(
            game_date=today, day_offset=0, timeout=15
        )
        games = board.get_data_frames()[0]

        matchups = {}
        for _, row in games.iterrows():
            home_id = int(row["HOME_TEAM_ID"])
            away_id = int(row["VISITOR_TEAM_ID"])
            home = id_to_abbr.get(home_id)
            away = id_to_abbr.get(away_id)
            if home and away:
                matchups[home] = {"opponent": away, "location": "Home"}
                matchups[away] = {"opponent": home, "location": "Road"}

        print(f"✅ Today's matchups loaded: {list(matchups.keys())}")
        return matchups
    except Exception as e:
        print(f"⚠️  fetch_todays_matchups failed: {e}")
        return {}

# ── New: team records & advanced stats ───────────────────────────────────


def fetch_team_records(season: str = SEASON) -> dict:
    """
    Returns per-team dict with season + last-10-game stats.
    Keys per team: w_pct, net_rtg, off_rtg, def_rtg, pts_avg,
                   home_w_pct, road_w_pct, w_pct_l10, w_l10, l_l10
    """
    print("📡  Fetching team records (season stats)...")
    id_to_abbr = {t["id"]: t["abbreviation"] for t in nba_teams.get_teams()}
    result: dict[str, dict] = {}

    # Season base stats
    try:
        time.sleep(0.6)
        base = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            season_type_all_star="Regular Season",
            measure_type_detailed_defense="Base",
            per_mode_detailed="PerGame",
            timeout=30,
        )
        df_base = base.get_data_frames()[0]
        for _, row in df_base.iterrows():
            abbr = id_to_abbr.get(int(row["TEAM_ID"]))
            if not abbr:
                continue
            result[abbr] = {
                "team_name": row.get("TEAM_NAME", abbr),
                "w_pct": round(float(row.get("W_PCT", 0.5)), 3),
                "pts_avg": round(float(row.get("PTS", 110.0)), 1),
                "net_rtg": 0.0,
                "off_rtg": 0.0,
                "def_rtg": 0.0,
                "home_w_pct": 0.5,
                "road_w_pct": 0.5,
                "w_pct_l10": 0.5,
            }
    except Exception as e:
        print(f"⚠️  fetch_team_records base failed: {e}")

    # Advanced (net/off/def ratings)
    try:
        time.sleep(0.8)
        adv = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            season_type_all_star="Regular Season",
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="PerGame",
            timeout=30,
        )
        df_adv = adv.get_data_frames()[0]
        for _, row in df_adv.iterrows():
            abbr = id_to_abbr.get(int(row["TEAM_ID"]))
            if not abbr or abbr not in result:
                continue
            result[abbr]["net_rtg"] = round(
                float(row.get("NET_RATING", 0.0)), 2
            )
            result[abbr]["off_rtg"] = round(
                float(row.get("OFF_RATING", 113.0)), 2
            )
            result[abbr]["def_rtg"] = round(
                float(row.get("DEF_RATING", 113.0)), 2
            )
    except Exception as e:
        print(f"⚠️  fetch_team_records advanced failed: {e}")

    # Home splits
    try:
        time.sleep(0.8)
        home_s = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            season_type_all_star="Regular Season",
            measure_type_detailed_defense="Base",
            per_mode_detailed="PerGame",
            location_nullable="Home",
            timeout=30,
        )
        df_home = home_s.get_data_frames()[0]
        for _, row in df_home.iterrows():
            abbr = id_to_abbr.get(int(row["TEAM_ID"]))
            if abbr and abbr in result:
                result[abbr]["home_w_pct"] = round(
                    float(row.get("W_PCT", 0.5)), 3
                )
    except Exception as e:
        print(f"⚠️  fetch_team_records home splits failed: {e}")

    # Road splits
    try:
        time.sleep(0.8)
        road_s = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            season_type_all_star="Regular Season",
            measure_type_detailed_defense="Base",
            per_mode_detailed="PerGame",
            location_nullable="Road",
            timeout=30,
        )
        df_road = road_s.get_data_frames()[0]
        for _, row in df_road.iterrows():
            abbr = id_to_abbr.get(int(row["TEAM_ID"]))
            if abbr and abbr in result:
                result[abbr]["road_w_pct"] = round(
                    float(row.get("W_PCT", 0.5)), 3
                )
    except Exception as e:
        print(f"⚠️  fetch_team_records road splits failed: {e}")

    # Last-10 form
    try:
        time.sleep(0.8)
        l10 = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            season_type_all_star="Regular Season",
            measure_type_detailed_defense="Base",
            per_mode_detailed="PerGame",
            last_n_games=10,
            timeout=30,
        )
        df_l10 = l10.get_data_frames()[0]
        for _, row in df_l10.iterrows():
            abbr = id_to_abbr.get(int(row["TEAM_ID"]))
            if abbr and abbr in result:
                result[abbr]["w_pct_l10"] = round(
                    float(row.get("W_PCT", 0.5)), 3
                )
                result[abbr]["w_l10"] = int(row.get("W", 0))
                result[abbr]["l_l10"] = int(row.get("L", 0))
    except Exception as e:
        print(f"⚠️  fetch_team_records L10 failed: {e}")

    print(f"✅ Team records loaded for {len(result)} teams")
    return result


def fetch_h2h_season(season: str = SEASON) -> dict:
    """
    Returns dict keyed by "ABBR1_ABBR2" (sorted) → {winner_abbr: win_count}
    for head-to-head wins between any two teams this season.
    """
    print("📡  Fetching H2H game log...")
    id_to_abbr = {t["id"]: t["abbreviation"] for t in nba_teams.get_teams()}
    h2h: dict[str, dict] = {}

    try:
        time.sleep(0.8)
        gl = leaguegamelog.LeagueGameLog(
            season=season,
            season_type_all_star="Regular Season",
            timeout=30,
        )
        df = gl.get_data_frames()[0]
        wins = df[df["WL"] == "W"]
        for _, row in wins.iterrows():
            winner = id_to_abbr.get(int(row["TEAM_ID"]), "")
            matchup = str(row.get("MATCHUP", ""))
            parts = (
                matchup.replace("vs.", "vs")
                .replace("@", "vs")
                .split("vs")
            )
            if len(parts) != 2:
                continue
            t1 = parts[0].strip().upper()
            t2 = parts[1].strip().upper()
            key = "_".join(sorted([t1, t2]))
            if key not in h2h:
                h2h[key] = {}
            h2h[key][winner] = h2h[key].get(winner, 0) + 1
    except Exception as e:
        print(f"⚠️  fetch_h2h_season failed: {e}")

    print(f"✅ H2H data computed for {len(h2h)} matchups")
    return h2h

# ── Injuries ──────────────────────────────────────────────────────────────


def fetch_injuries() -> list[dict]:
    """
    Fetch today's NBA injury report from ESPN's public injuries endpoint.

    Returns list of dicts:
      team_abbr, player_name, status, reason, player_avg_pts (None initially)

    Always returns a list (possibly empty) and never raises.
    """
    print("📡  Fetching injury report (ESPN only)...")

    # Map full team names → abbreviations
    name_to_abbr = {
        t["full_name"].lower(): t["abbreviation"]
        for t in nba_teams.get_teams()
    }
    extra = {
        "la clippers": "LAC",
        "la lakers": "LAL",
        "golden state": "GSW",
        "new york": "NYK",
        "oklahoma city": "OKC",
        "san antonio": "SAS",
        "new orleans": "NOP",
        "portland": "POR",
    }
    name_to_abbr.update(extra)

    def normalize_team(raw: str) -> str:
        low = (raw or "").lower().strip()
        if low in name_to_abbr:
            return name_to_abbr[low]
        for k, v in name_to_abbr.items():
            if k in low or low in k:
                return v
        return (raw or "").upper()[:3]

    results: list[dict] = []

    try:
        time.sleep(0.5)
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            print(f"⚠️  ESPN injury endpoint returned {resp.status_code}")
            print("⚠️  No injury data available — proceeding without injuries")
            return []

        data = resp.json()
        for team in data.get("injuries", []):
            team_info = team.get("team", {})
            team_name = team_info.get("displayName") or team_info.get("name") or ""
            team_abbr = normalize_team(team_name)

            for item in team.get("injuries", []):
                athlete = item.get("athlete", {})
                status_raw = str(item.get("status", "")).lower().strip()
                if status_raw in ("", "available", "not yet submitted", "probable"):
                    continue
                results.append({
                    "team_abbr":      team_abbr,
                    "player_name":    athlete.get("displayName", "").strip(),
                    "status":         status_raw,
                    "reason":         item.get("details", "") or "",
                    "player_avg_pts": None,
                })

        print(f"✅ Injuries loaded via ESPN: {len(results)} entries")
        return results

    except Exception as e:
        print(f"⚠️  ESPN injury fetch failed: {e}")
        print("⚠️  No injury data available — proceeding without injuries")
        return []



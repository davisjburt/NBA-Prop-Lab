"""
app/services/prizepicks.py
--------------------------
Fetches NBA player prop lines directly from the PrizePicks public
projections JSON endpoint. No API key required.

How it works:
  1. Calls https://api.prizepicks.com/projections with NBA params
  2. Parses the JSON payload (same structure as the old app XHR)
  3. Normalizes player names, teams, and odds_type
  4. Returns a list of dicts in the exact shape fetch_data.py expects
"""

import json
import unicodedata
import time
from typing import List, Dict

import requests

# ---------------------------------------------------------------------------
# Stat label -> internal key mapping
# ---------------------------------------------------------------------------

STAT_MAP = {
    "Points":        "pts",
    "Rebounds":      "reb",
    "Assists":       "ast",
    "Steals":        "stl",
    "Blocked Shots": "blk",
    "3-Pt Made":     "fg3m",
    "Turnovers":     "tov",
    "Pts+Rebs+Asts": "pra",
    "Pts+Rebs":      "pr",
    "Pts+Asts":      "pa",
    "Rebs+Asts":     "ra",
    "Blks+Stls":     "bs",
}

TEAM_NORMALIZE = {
    "atlanta hawks":          "ATL",
    "boston celtics":         "BOS",
    "brooklyn nets":          "BKN",
    "charlotte hornets":      "CHA",
    "chicago bulls":          "CHI",
    "cleveland cavaliers":    "CLE",
    "dallas mavericks":       "DAL",
    "denver nuggets":         "DEN",
    "detroit pistons":        "DET",
    "golden state warriors":  "GSW",
    "houston rockets":        "HOU",
    "indiana pacers":         "IND",
    "los angeles clippers":   "LAC",
    "la clippers":            "LAC",
    "los angeles lakers":     "LAL",
    "la lakers":              "LAL",
    "memphis grizzlies":      "MEM",
    "miami heat":             "MIA",
    "milwaukee bucks":        "MIL",
    "minnesota timberwolves": "MIN",
    "new orleans pelicans":   "NOP",
    "new york knicks":        "NYK",
    "oklahoma city thunder":  "OKC",
    "orlando magic":          "ORL",
    "philadelphia 76ers":     "PHI",
    "phoenix suns":           "PHX",
    "portland trail blazers": "POR",
    "sacramento kings":       "SAC",
    "san antonio spurs":      "SAS",
    "toronto raptors":        "TOR",
    "utah jazz":              "UTA",
    "washington wizards":     "WAS",
}

# ---------------------------------------------------------------------------
# HTTP config for PrizePicks projections API
# ---------------------------------------------------------------------------

PP_URL = "https://api.prizepicks.com/projections"

PP_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Origin": "https://app.prizepicks.com",
    "Referer": "https://app.prizepicks.com/",
    "Connection": "keep-alive",
}


PP_PARAMS = {
    "league_id": 7,       # NBA
    "per_page": 250,      # large enough for full board
    "single_stat": "true"
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name or "")
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


def normalize_team(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    if len(raw) <= 4 and raw.isupper():
        return raw
    return TEAM_NORMALIZE.get(raw.lower(), raw.upper())


def normalize_odds_type(raw: str) -> str:
    if not raw:
        return "standard"
    low = raw.lower()
    if "goblin" in low:
        return "goblin"
    if "demon" in low:
        return "demon"
    return "standard"


# ---------------------------------------------------------------------------
# Parse the /projections JSON payload (same structure as the old API)
# ---------------------------------------------------------------------------


def _parse_projections_json(data: dict) -> List[Dict]:
    """
    Parse the PrizePicks projections JSON into a flat list of prop lines
    that fetch_data.py can consume.
    """
    players: Dict[str, Dict] = {}

    for item in data.get("included", []):
        if item.get("type") == "new_player":
            attr = item.get("attributes", {})
            players[item["id"]] = {
                "name":     attr.get("display_name", ""),
                "team":     attr.get("team", ""),
                "position": attr.get("position", ""),
            }

    lines: List[Dict] = []

    for proj in data.get("data", []):
        attr = proj.get("attributes", {})

        pp_stat = attr.get("stat_type", "")
        line = attr.get("line_score")
        odds_type_raw = attr.get("odds_type", "")

        player_rel = (
            proj.get("relationships", {})
            .get("new_player", {})
            .get("data", {})
        )
        player_id = player_rel.get("id")
        player = players.get(player_id, {})

        stat = STAT_MAP.get(pp_stat)

        if not stat or line is None or not player:
            continue

        lines.append({
            "name":          player["name"],
            "name_key":      normalize(player["name"]),
            "team":          normalize_team(player.get("team", "")),
            "position":      player.get("position", ""),
            "stat":          stat,
            "pp_stat_label": pp_stat,
            "line":          float(line),
            "odds_type":     normalize_odds_type(odds_type_raw),
        })

    return lines


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fetch_prizepicks_lines() -> List[Dict]:
    """
    Fetch PrizePicks NBA prop lines using their public projections JSON
    endpoint. No headless browser required.

    Returns:
        List[dict]: Each entry has keys:
          - name
          - name_key
          - team
          - position
          - stat
          - pp_stat_label
          - line
          - odds_type
    """
    try:
        print("  [PP] Hitting projections API...")
        resp = requests.get(
            PP_URL,
            headers=PP_HEADERS,
            params=PP_PARAMS,
            timeout=15,
        )
        print("  [PP] Status:", resp.status_code)


        if resp.status_code != 200:
            print(f"  [PP] HTTP {resp.status_code} from projections endpoint")
            return []

        data = resp.json()
        lines = _parse_projections_json(data)
        print(f"  [PP] API fetched {len(lines)} lines from projections endpoint")
        return lines

    except requests.Timeout:
        print("  [PP] Projections API timed out")
        return []
    except Exception as e:
        print(f"  [PP] Projections API error: {e}")
        return []

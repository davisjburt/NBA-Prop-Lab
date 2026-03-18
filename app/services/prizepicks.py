import requests
import unicodedata

PP_URL = "https://api.prizepicks.com/projections"
HEADERS = {
    "Accept":          "application/json; charset=UTF-8",
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer":         "https://app.prizepicks.com/",
    "Accept-Language": "en-US,en;q=0.9",
}

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
    # Long-form names → NBA abbreviations (used only when PP returns full names)
    "atlanta hawks": "ATL",
    "boston celtics": "BOS",
    "brooklyn nets": "BKN",
    "charlotte hornets": "CHA",
    "chicago bulls": "CHI",
    "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL",
    "denver nuggets": "DEN",
    "detroit pistons": "DET",
    "golden state warriors": "GSW",
    "houston rockets": "HOU",
    "indiana pacers": "IND",
    "los angeles clippers": "LAC",
    "la clippers": "LAC",
    "los angeles lakers": "LAL",
    "la lakers": "LAL",
    "memphis grizzlies": "MEM",
    "miami heat": "MIA",
    "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN",
    "new orleans pelicans": "NOP",
    "new york knicks": "NYK",
    "oklahoma city thunder": "OKC",
    "orlando magic": "ORL",
    "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX",
    "portland trail blazers": "POR",
    "sacramento kings": "SAC",
    "san antonio spurs": "SAS",
    "toronto raptors": "TOR",
    "utah jazz": "UTA",
    "washington wizards": "WAS",
}


def normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name or "")
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


def normalize_odds_type(raw):
    if not raw:
        return "standard"
    low = raw.lower()
    if "goblin" in low:
        return "goblin"
    if "demon" in low:
        return "demon"
    return "standard"


def normalize_team(raw: str) -> str:
    """
    PrizePicks sometimes returns abbreviations (OKC, MIA) and sometimes full names.
    - If it's already a short all-caps code, trust it.
    - Otherwise map long names via TEAM_NORMALIZE.
    """
    if not raw:
        return ""
    raw_stripped = raw.strip()
    # Already an abbreviation like OKC, MIA, DEN
    if len(raw_stripped) <= 4 and raw_stripped.isupper():
        return raw_stripped
    key = raw_stripped.lower()
    if key in TEAM_NORMALIZE:
        return TEAM_NORMALIZE[key]
    return raw_stripped.upper()


def fetch_prizepicks_lines():
    try:
        resp = requests.get(
            PP_URL,
            headers=HEADERS,
            params={"league_id": 7, "per_page": 250, "single_stat": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"PrizePicks fetch error: {e}")
        return []

    players = {}
    for item in data.get("included", []):
        if item.get("type") == "new_player":
            attr = item["attributes"]
            players[item["id"]] = {
                "name":     attr.get("display_name", ""),
                "team":     attr.get("team", ""),
                "position": attr.get("position", ""),
            }

    lines = []
    for proj in data.get("data", []):
        attr       = proj.get("attributes", {})
        pp_stat    = attr.get("stat_type", "")
        line       = attr.get("line_score")
        odds_type  = normalize_odds_type(attr.get("odds_type"))
        player_rel = proj.get("relationships", {}).get("new_player", {}).get("data", {})
        player_id  = player_rel.get("id")
        player     = players.get(player_id, {})

        stat = STAT_MAP.get(pp_stat)
        if not stat or not line or not player:
            continue

        raw_team = player.get("team") or ""
        team_abbr = normalize_team(raw_team)

        lines.append({
            "name":          player["name"],
            "name_key":      normalize(player["name"]),
            "team":          team_abbr,
            "position":      player["position"],
            "stat":          stat,
            "pp_stat_label": pp_stat,
            "line":          float(line),
            "odds_type":     odds_type,
        })

    return lines
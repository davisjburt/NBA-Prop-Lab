import requests
import unicodedata

PP_URL  = "https://api.prizepicks.com/projections"
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

def normalize(name):
    nfkd = unicodedata.normalize("NFKD", name)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()

def normalize_odds_type(raw):
    if not raw:
        return "standard"
    if "goblin" in raw.lower():
        return "goblin"
    if "demon" in raw.lower():
        return "demon"
    return "standard"

def fetch_prizepicks_lines():
    try:
        resp = requests.get(
            PP_URL,
            headers=HEADERS,
            params={"league_id": 7, "per_page": 250, "single_stat": "true"},
            timeout=10
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

        lines.append({
            "name":          player["name"],
            "name_key":      normalize(player["name"]),
            "team":          player["team"],
            "position":      player["position"],
            "stat":          stat,
            "pp_stat_label": pp_stat,
            "line":          float(line),
            "odds_type":     odds_type,
        })

    return lines

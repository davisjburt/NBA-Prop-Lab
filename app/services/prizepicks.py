"""
app/services/prizepicks.py
--------------------------
Fetches NBA player prop lines from The Odds API and normalises them into
the same shape that fetch_data.py expects.

Cost: 1 request (events list) + 1 request per game = ~10 requests/day.
Free tier: 500 requests/month -> ~50 full runs/month.

Set your key in a .env file at the repo root:
  ODDS_API_KEY=your_key_here
Get a free key at https://the-odds-api.com
"""

import os
import unicodedata
import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# OddsAPI constants
# ---------------------------------------------------------------------------
_BASE   = "https://api.the-odds-api.com/v4"
_SPORT  = "basketball_nba"
_REGION = "us"

# All markets passed as ONE comma-joined string per event call = 1 request/game
_MARKETS = (
    "player_points,"
    "player_rebounds,"
    "player_assists,"
    "player_steals,"
    "player_blocks,"
    "player_threes,"
    "player_turnovers,"
    "player_points_rebounds_assists,"
    "player_points_rebounds,"
    "player_points_assists,"
    "player_rebounds_assists,"
    "player_blocks_steals"
)

# OddsAPI market key -> (internal stat key, human label)
_MARKET_MAP = {
    "player_points":                  ("pts",  "Points"),
    "player_rebounds":                ("reb",  "Rebounds"),
    "player_assists":                 ("ast",  "Assists"),
    "player_steals":                  ("stl",  "Steals"),
    "player_blocks":                  ("blk",  "Blocked Shots"),
    "player_threes":                  ("fg3m", "3-Pt Made"),
    "player_turnovers":               ("tov",  "Turnovers"),
    "player_points_rebounds_assists": ("pra",  "Pts+Rebs+Asts"),
    "player_points_rebounds":         ("pr",   "Pts+Rebs"),
    "player_points_assists":          ("pa",   "Pts+Asts"),
    "player_rebounds_assists":        ("ra",   "Rebs+Asts"),
    "player_blocks_steals":           ("bs",   "Blks+Stls"),
}

# Best bookmaker proxy for PrizePicks lines
_BOOKMAKER = "draftkings"

TEAM_NORMALIZE = {
    "atlanta hawks":         "ATL",
    "boston celtics":        "BOS",
    "brooklyn nets":         "BKN",
    "charlotte hornets":     "CHA",
    "chicago bulls":         "CHI",
    "cleveland cavaliers":   "CLE",
    "dallas mavericks":      "DAL",
    "denver nuggets":        "DEN",
    "detroit pistons":       "DET",
    "golden state warriors": "GSW",
    "houston rockets":       "HOU",
    "indiana pacers":        "IND",
    "los angeles clippers":  "LAC",
    "la clippers":           "LAC",
    "los angeles lakers":    "LAL",
    "la lakers":             "LAL",
    "memphis grizzlies":     "MEM",
    "miami heat":            "MIA",
    "milwaukee bucks":       "MIL",
    "minnesota timberwolves":"MIN",
    "new orleans pelicans":  "NOP",
    "new york knicks":       "NYK",
    "oklahoma city thunder": "OKC",
    "orlando magic":         "ORL",
    "philadelphia 76ers":    "PHI",
    "phoenix suns":          "PHX",
    "portland trail blazers":"POR",
    "sacramento kings":      "SAC",
    "san antonio spurs":     "SAS",
    "toronto raptors":       "TOR",
    "utah jazz":             "UTA",
    "washington wizards":    "WAS",
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


def _get_api_key() -> str:
    key = os.getenv("ODDS_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "ODDS_API_KEY not set. Add it to your .env file:\n"
            "  ODDS_API_KEY=your_key_here\n"
            "Get a free key at https://the-odds-api.com"
        )
    return key


# ---------------------------------------------------------------------------
# API calls  (1 request for events list + 1 per game)
# ---------------------------------------------------------------------------

def _fetch_events(api_key: str) -> list[dict]:
    """Return today's NBA events from the OddsAPI."""
    resp = requests.get(
        f"{_BASE}/sports/{_SPORT}/events",
        params={"apiKey": api_key, "dateFormat": "iso"},
        timeout=15,
    )
    resp.raise_for_status()
    remaining = resp.headers.get("x-requests-remaining", "?")
    used      = resp.headers.get("x-requests-used", "?")
    print(f"  [OddsAPI] {len(resp.json())} game(s) today | "
          f"quota used: {used} / {int(used)+int(remaining) if used != '?' and remaining != '?' else '500'}")
    return resp.json()


def _fetch_event_props(api_key: str, event: dict) -> list[dict]:
    """
    Fetch ALL markets for one event in a single API call (1 request).
    Returns a flat list of normalised prop dicts.
    """
    event_id   = event["id"]
    home_team  = normalize_team(event.get("home_team", ""))
    away_team  = normalize_team(event.get("away_team", ""))

    try:
        resp = requests.get(
            f"{_BASE}/sports/{_SPORT}/events/{event_id}/odds",
            params={
                "apiKey":     api_key,
                "regions":    _REGION,
                "markets":    _MARKETS,   # all 12 markets in one shot
                "oddsFormat": "american",
            },
            timeout=20,
        )
        resp.raise_for_status()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (404, 422):
            return []   # props not yet posted for this game
        raise

    data  = resp.json()
    lines = []

    for bookmaker in data.get("bookmakers", []):
        if bookmaker["key"] != _BOOKMAKER:
            continue

        for market in bookmaker.get("markets", []):
            mkt_key = market["key"]
            if mkt_key not in _MARKET_MAP:
                continue
            stat, label = _MARKET_MAP[mkt_key]

            # Group by player: {player_name: {"over": outcome, "under": outcome}}
            by_player: dict[str, dict] = {}
            for outcome in market.get("outcomes", []):
                # OddsAPI puts the player name in "description" for props
                pname = outcome.get("description") or outcome.get("name", "")
                if not pname:
                    continue
                by_player.setdefault(pname, {})
                by_player[pname][outcome["name"].lower()] = outcome

            for pname, sides in by_player.items():
                over = sides.get("over")
                if not over or over.get("point") is None:
                    continue

                lines.append({
                    "name":          pname,
                    "name_key":      normalize(pname),
                    "team":          "",        # resolved from DB in fetch_data.py
                    "position":      "",
                    "stat":          stat,
                    "pp_stat_label": label,
                    "line":          float(over["point"]),
                    "odds_type":     "standard",
                    "_home_team":    home_team,
                    "_away_team":    away_team,
                })
        break  # only need one bookmaker

    return lines


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_prizepicks_lines() -> list[dict]:
    """
    Fetch today's NBA player prop lines from The Odds API.
    Cost: 1 (events) + N (one per game) requests.
    Returns the same list shape as the old PrizePicks scraper.
    """
    try:
        api_key = _get_api_key()
    except EnvironmentError as e:
        print(f"  [OddsAPI] {e}")
        return []

    try:
        events = _fetch_events(api_key)
    except Exception as e:
        print(f"  [OddsAPI] Failed to fetch events: {e}")
        return []

    if not events:
        print("  [OddsAPI] No NBA games today.")
        return []

    all_lines: list[dict] = []
    seen: set[tuple]      = set()   # deduplicate (name_key, stat)

    for event in events:
        matchup = f"{normalize_team(event.get('away_team',''))} @ {normalize_team(event.get('home_team',''))}"
        try:
            props = _fetch_event_props(api_key, event)
        except Exception as e:
            print(f"  [OddsAPI] {matchup} error: {e}")
            continue

        added = 0
        for line in props:
            key = (line["name_key"], line["stat"])
            if key not in seen:
                seen.add(key)
                all_lines.append(line)
                added += 1

        print(f"  [OddsAPI] {matchup}: {added} lines")

    print(f"  [OddsAPI] Total: {len(all_lines)} prop lines across {len(events)} game(s)")
    return all_lines

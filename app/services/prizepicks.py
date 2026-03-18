"""
app/services/prizepicks.py
--------------------------
Fetches NBA player prop lines from The Odds API and normalises them into
the same shape that fetch_data.py expects from the old PrizePicks scraper:

  [
    {
      "name":          str,   # display name  e.g. "LeBron James"
      "name_key":      str,   # normalised key e.g. "lebron james"
      "team":          str,   # NBA abbr       e.g. "LAL"
      "position":      str,   # "" (OddsAPI doesn't supply position)
      "stat":          str,   # internal key   e.g. "pts"
      "pp_stat_label": str,   # human label    e.g. "Points"
      "line":          float, # over/under line
      "odds_type":     str,   # always "standard" from OddsAPI
    },
    ...
  ]

Set your key in a .env file at the repo root:
  ODDS_API_KEY=your_key_here

Free tier: 500 requests/month  https://the-odds-api.com
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

# Maps OddsAPI market keys -> our internal stat keys + human labels
# Only markets that the free tier exposes for NBA are listed.
_MARKET_MAP = {
    "player_points":              ("pts",  "Points"),
    "player_rebounds":            ("reb",  "Rebounds"),
    "player_assists":             ("ast",  "Assists"),
    "player_steals":              ("stl",  "Steals"),
    "player_blocks":              ("blk",  "Blocked Shots"),
    "player_threes":              ("fg3m", "3-Pt Made"),
    "player_turnovers":           ("tov",  "Turnovers"),
    "player_points_rebounds_assists": ("pra", "Pts+Rebs+Asts"),
    "player_points_rebounds":     ("pr",   "Pts+Rebs"),
    "player_points_assists":      ("pa",   "Pts+Asts"),
    "player_rebounds_assists":    ("ra",   "Rebs+Asts"),
    "player_blocks_steals":       ("bs",   "Blks+Stls"),
}

# Bookmaker to use for line values (PrizePicks is DFS, not a sportsbook;
# we use DraftKings as the closest proxy for their lines).
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
    """Return ASCII-lowercased, stripped version of a player name."""
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
# OddsAPI fetching
# ---------------------------------------------------------------------------

def _fetch_today_event_ids(api_key: str) -> list[str]:
    """
    Return a list of today's NBA event IDs from the OddsAPI events endpoint.
    """
    url = f"{_BASE}/sports/{_SPORT}/events"
    resp = requests.get(
        url,
        params={"apiKey": api_key, "dateFormat": "iso"},
        timeout=15,
    )
    resp.raise_for_status()
    events = resp.json()
    print(f"  [OddsAPI] {len(events)} event(s) found today")
    return [e["id"] for e in events]


def _fetch_props_for_event(
    api_key: str,
    event_id: str,
    markets: list[str],
) -> list[dict]:
    """
    Fetch player prop odds for a single event and return a flat list of
    normalised line dicts ready for fetch_data.py.
    """
    url = f"{_BASE}/sports/{_SPORT}/events/{event_id}/odds"
    try:
        resp = requests.get(
            url,
            params={
                "apiKey":   api_key,
                "regions":  _REGION,
                "markets":  ",".join(markets),
                "oddsFormat": "american",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.HTTPError as e:
        # 422 means no props available for this event yet — skip silently
        if e.response is not None and e.response.status_code == 422:
            return []
        raise

    data = resp.json()
    lines = []

    for bookmaker in data.get("bookmakers", []):
        if bookmaker["key"] != _BOOKMAKER:
            continue
        for market in bookmaker.get("markets", []):
            mkt_key = market["key"]
            if mkt_key not in _MARKET_MAP:
                continue
            stat, label = _MARKET_MAP[mkt_key]

            # Group outcomes by player name so we can find the over line
            player_outcomes: dict[str, dict] = {}
            for outcome in market.get("outcomes", []):
                pname = outcome.get("description") or outcome.get("name", "")
                if not pname:
                    continue
                if pname not in player_outcomes:
                    player_outcomes[pname] = {}
                player_outcomes[pname][outcome["name"].lower()] = outcome

            for pname, sides in player_outcomes.items():
                over = sides.get("over")
                if not over or over.get("point") is None:
                    continue
                line_val = float(over["point"])

                # Derive team from home_team / away_team on the event
                home_team = normalize_team(data.get("home_team", ""))
                away_team = normalize_team(data.get("away_team", ""))
                # OddsAPI doesn't tell us which team the player is on —
                # leave team as "" and let fetch_data.py resolve via DB
                team = ""

                lines.append({
                    "name":          pname,
                    "name_key":      normalize(pname),
                    "team":          team,
                    "position":      "",
                    "stat":          stat,
                    "pp_stat_label": label,
                    "line":          line_val,
                    "odds_type":     "standard",
                    # Store home/away for optional downstream use
                    "_home_team":    home_team,
                    "_away_team":    away_team,
                })
        break  # only need DraftKings

    return lines


# ---------------------------------------------------------------------------
# Public entry point (called by fetch_data.py)
# ---------------------------------------------------------------------------

def fetch_prizepicks_lines() -> list[dict]:
    """
    Fetch today's NBA player prop lines from The Odds API.
    Returns a list in the same shape as the old PrizePicks scraper so the
    rest of fetch_data.py works without any changes.
    """
    try:
        api_key = _get_api_key()
    except EnvironmentError as e:
        print(f"  [OddsAPI] {e}")
        return []

    markets = list(_MARKET_MAP.keys())

    try:
        event_ids = _fetch_today_event_ids(api_key)
    except Exception as e:
        print(f"  [OddsAPI] Failed to fetch events: {e}")
        return []

    if not event_ids:
        print("  [OddsAPI] No NBA games today.")
        return []

    all_lines: list[dict] = []
    seen: set[tuple] = set()  # deduplicate (name_key, stat)

    for event_id in event_ids:
        try:
            event_lines = _fetch_props_for_event(api_key, event_id, markets)
        except Exception as e:
            print(f"  [OddsAPI] Event {event_id} error: {e}")
            continue

        for line in event_lines:
            key = (line["name_key"], line["stat"])
            if key not in seen:
                seen.add(key)
                all_lines.append(line)

    print(f"  [OddsAPI] Fetched {len(all_lines)} prop lines across {len(event_ids)} game(s)")
    return all_lines

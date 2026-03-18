import json
import unicodedata
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

PP_URL = "https://api.prizepicks.com/projections"

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
    "atlanta hawks":        "ATL",
    "boston celtics":       "BOS",
    "brooklyn nets":        "BKN",
    "charlotte hornets":    "CHA",
    "chicago bulls":        "CHI",
    "cleveland cavaliers":  "CLE",
    "dallas mavericks":     "DAL",
    "denver nuggets":       "DEN",
    "detroit pistons":      "DET",
    "golden state warriors":"GSW",
    "houston rockets":      "HOU",
    "indiana pacers":       "IND",
    "los angeles clippers": "LAC",
    "la clippers":          "LAC",
    "los angeles lakers":   "LAL",
    "la lakers":            "LAL",
    "memphis grizzlies":    "MEM",
    "miami heat":           "MIA",
    "milwaukee bucks":      "MIL",
    "minnesota timberwolves":"MIN",
    "new orleans pelicans": "NOP",
    "new york knicks":      "NYK",
    "oklahoma city thunder":"OKC",
    "orlando magic":        "ORL",
    "philadelphia 76ers":   "PHI",
    "phoenix suns":         "PHX",
    "portland trail blazers":"POR",
    "sacramento kings":     "SAC",
    "san antonio spurs":    "SAS",
    "toronto raptors":      "TOR",
    "utah jazz":            "UTA",
    "washington wizards":   "WAS",
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
    if not raw:
        return ""
    raw_stripped = raw.strip()
    if len(raw_stripped) <= 4 and raw_stripped.isupper():
        return raw_stripped
    key = raw_stripped.lower()
    if key in TEAM_NORMALIZE:
        return TEAM_NORMALIZE[key]
    return raw_stripped.upper()


def _build_driver():
    """Return a headless Chrome WebDriver that looks like a real browser."""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def _parse_response(data: dict) -> list:
    """Extract lines list from the PrizePicks projections JSON."""
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
        stat       = STAT_MAP.get(pp_stat)

        if not stat or not line or not player:
            continue

        raw_team  = player.get("team") or ""
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


def fetch_prizepicks_lines() -> list:
    """
    Fetch PrizePicks NBA projections using a headless Chrome browser so that
    Cloudflare / anti-bot checks pass (plain requests.get returns 403).
    """
    url = f"{PP_URL}?league_id=7&per_page=250&single_stat=true"
    driver = None
    try:
        driver = _build_driver()

        # 1) Warm the session on the main app page first
        driver.get("https://app.prizepicks.com/")
        time.sleep(3)

        # 2) Now hit the API endpoint directly
        driver.get(url)
        time.sleep(2)

        # The browser renders the JSON as plain text inside <body> / <pre>
        body_text = driver.find_element("tag name", "body").text
        data = json.loads(body_text)
        lines = _parse_response(data)
        print(f"  PrizePicks: fetched {len(lines)} lines via headless browser")
        return lines

    except Exception as e:
        print(f"PrizePicks fetch error: {e}")
        return []
    finally:
        if driver:
            driver.quit()

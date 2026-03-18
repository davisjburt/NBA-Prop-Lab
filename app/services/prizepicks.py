"""
app/services/prizepicks.py
--------------------------
Scrapes NBA player prop lines directly from the PrizePicks web app
using Playwright (headless Chromium). No API key required.

Install once:
  pip install playwright
  playwright install chromium

The scraper:
  1. Loads app.prizepicks.com in a headless browser (passes bot checks)
  2. Waits for the NBA league tab and clicks it
  3. Waits for prop cards to render
  4. Intercepts the /projections XHR that fires during page load
     (faster + more reliable than scraping the DOM)
  5. Falls back to DOM scraping if XHR intercept misses

Returns the same list shape that fetch_data.py expects.
"""

import json
import unicodedata
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

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

def _parse_projections_json(data: dict) -> list[dict]:
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
        odds_type  = normalize_odds_type(attr.get("odds_type", ""))
        player_rel = proj.get("relationships", {}).get("new_player", {}).get("data", {})
        player_id  = player_rel.get("id")
        player     = players.get(player_id, {})
        stat       = STAT_MAP.get(pp_stat)

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
            "odds_type":     odds_type,
        })
    return lines


# ---------------------------------------------------------------------------
# DOM scrape fallback — parses rendered prop cards
# ---------------------------------------------------------------------------

def _scrape_dom(page) -> list[dict]:
    """
    Fallback: scrape prop cards directly from the rendered DOM.
    PrizePicks renders each prop as a <li> card containing:
      - player name
      - stat type label
      - line value
    """
    lines = []
    try:
        # Wait for at least one prop card to appear
        page.wait_for_selector("li.projection", timeout=15000)
        cards = page.query_selector_all("li.projection")
        print(f"  [PP] DOM: found {len(cards)} prop cards")

        for card in cards:
            try:
                name_el  = card.query_selector(".name")
                stat_el  = card.query_selector(".stat-type, .market-name, [class*='stat']")
                line_el  = card.query_selector(".score, .line-score, [class*='score']")
                team_el  = card.query_selector(".team-name, [class*='team']")
                odds_el  = card.query_selector(".odds-type, [class*='goblin'], [class*='demon']")

                name     = name_el.inner_text().strip()  if name_el  else ""
                pp_stat  = stat_el.inner_text().strip()  if stat_el  else ""
                line_txt = line_el.inner_text().strip()  if line_el  else ""
                team_raw = team_el.inner_text().strip()  if team_el  else ""
                odds_raw = odds_el.inner_text().strip()  if odds_el  else ""

                stat = STAT_MAP.get(pp_stat)
                if not stat or not name or not line_txt:
                    continue

                lines.append({
                    "name":          name,
                    "name_key":      normalize(name),
                    "team":          normalize_team(team_raw),
                    "position":      "",
                    "stat":          stat,
                    "pp_stat_label": pp_stat,
                    "line":          float(line_txt),
                    "odds_type":     normalize_odds_type(odds_raw),
                })
            except Exception:
                continue
    except PlaywrightTimeout:
        print("  [PP] DOM scrape timed out waiting for prop cards")
    return lines


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_prizepicks_lines() -> list[dict]:
    """
    Fetch PrizePicks NBA prop lines using a headless Playwright browser.
    Strategy:
      1. Intercept the /projections XHR that fires when the page loads
         -> parse the JSON directly (same payload as the old API)
      2. If intercept gets 0 results, fall back to DOM scraping
    """
    intercepted: list[dict] = []
    xhr_done = {"fired": False}

    def handle_response(response):
        if "prizepicks.com/projections" in response.url and not xhr_done["fired"]:
            try:
                data  = response.json()
                lines = _parse_projections_json(data)
                if lines:
                    intercepted.extend(lines)
                    xhr_done["fired"] = True
                    print(f"  [PP] XHR intercepted: {len(lines)} lines")
            except Exception as e:
                print(f"  [PP] XHR parse error: {e}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = context.new_page()

        # Strip webdriver fingerprint
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Attach response listener before navigation
        page.on("response", handle_response)

        print("  [PP] Loading app.prizepicks.com...")
        try:
            page.goto("https://app.prizepicks.com/", wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeout:
            print("  [PP] Page load timed out")
            browser.close()
            return []

        # Give SPA time to boot and fire XHR calls
        time.sleep(6)

        if intercepted:
            browser.close()
            return intercepted

        # XHR intercept missed — try clicking the NBA league tab then DOM scrape
        print("  [PP] XHR miss, attempting NBA tab click + DOM scrape...")
        try:
            # Look for an NBA league selector button
            nba_btn = page.query_selector(
                "button:has-text('NBA'), "
                "[data-league='NBA'], "
                "li:has-text('NBA')"
            )
            if nba_btn:
                nba_btn.click()
                time.sleep(3)
        except Exception as e:
            print(f"  [PP] NBA tab click error: {e}")

        lines = _scrape_dom(page)
        browser.close()

        if not lines:
            print("  [PP] Both XHR intercept and DOM scrape returned 0 lines")
            print("  [PP] PrizePicks may be down or blocking headless browsers")

        return lines

# NBA Prop Lab

A full-stack NBA player prop analysis tool built with Flask and SQLite/Postgres. Pulls live player game logs from the NBA API, scrapes PrizePicks prop lines, computes hit rates and confidence scores, and presents everything in a clean web UI across five pages: Home, Player, Explore, PrizePicks, and Parlays.

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [File Reference](#file-reference)
- [Routes and API Endpoints](#routes-and-api-endpoints)
- [Data Flow](#data-flow)
- [Database Schema](#database-schema)
- [Local Setup](#local-setup)
- [Environment Variables](#environment-variables)
- [Running the App](#running-the-app)
- [Refreshing Data](#refreshing-data)
- [Deployment on Render](#deployment-on-render)
- [Scheduled Jobs](#scheduled-jobs)
- [Troubleshooting](#troubleshooting)

---

## Overview

NBA Prop Lab has two independent systems that work together:

1. **The Flask web app** reads from a SQLite/Postgres database and pre-computed JSON files. Zero computation at request time so pages load instantly.
2. **The data pipeline** consists of two Python scripts that run on a schedule or manually. They pull from the NBA API and PrizePicks, write results into the DB and data/\*.json files, which the Flask app reads.

---

## How It Works

    NBA API ──────────────────► daily_update.py ──► players table
                                                   ► player_game_stats table

    PrizePicks API ────────────► fetch_data.py ───► data/prizepicks_lines.json
                                                   ► data/prizepicks_results.json
                                                   ► data/prizepicks_parlays.json
                                                   ► data/trending.json
                                                   ► data/opponent_defense.json
                                                   ► data/todays_matchups.json

    Flask app (run.py) ────────► reads DB + JSON ─► HTML pages + JSON API

---

## Project Structure

    NBA-Prop-Lab/
    │
    ├── app/
    │   ├── __init__.py             # App factory: create_app()
    │   ├── config.py               # Config class — reads env vars
    │   ├── models/
    │   │   └── models.py           # SQLAlchemy ORM: Player, PlayerGameStat
    │   ├── routes/
    │   │   ├── players.py          # Page routes + player list API (prefix="/")
    │   │   └── props.py            # Stats + data API (prefix="/api")
    │   ├── services/
    │   │   ├── hit_rate.py         # Hit rate, streaks, combo stat math
    │   │   ├── nba_fetcher.py      # NBA API wrapper
    │   │   └── prizepicks.py       # PrizePicks public API scraper
    │   ├── templates/
    │   │   ├── base_drawer.html    # Shared nav drawer layout
    │   │   ├── index.html          # Home page
    │   │   ├── player.html         # Player detail page
    │   │   ├── explore.html        # Explore all players by stat/line
    │   │   ├── prizepicks.html     # PrizePicks board
    │   │   └── parlays.html        # Parlay suggestions
    │   └── static/
    │       ├── css/                # Stylesheets
    │       ├── Milker.otf          # Custom font
    │       └── proplab.svg         # Logo
    │
    ├── data/                       # JSON files written by scripts, read by Flask
    │   ├── opponent_defense.json
    │   ├── todays_matchups.json
    │   ├── prizepicks_lines.json
    │   ├── prizepicks_results.json
    │   ├── prizepicks_parlays.json
    │   └── trending.json
    │
    ├── scripts/
    │   ├── daily_update.py         # NBA API → DB (run daily at 6am)
    │   ├── fetch_data.py           # PrizePicks + compute → JSON (run hourly)
    │   ├── dedup.py                # Remove duplicate game stat rows
    │   ├── fix_positions.py        # Backfill missing player positions
    │   └── seed.py                 # One-time: populate players table
    │
    ├── .github/workflows/          # GitHub Actions CI/CD
    ├── run.py                      # Dev server entrypoint (port 5002)
    ├── render.yaml                 # Render deploy config (web + 2 cron jobs)
    ├── requirements.txt            # Python deps
    ├── refresh.sh                  # Local: fetch_data.py + git commit + push
    └── .python-version             # pyenv version pin

---

## File Reference

### app/**init**.py

Flask application factory. Called by run.py in dev and gunicorn in production.

- Creates Flask instance
- Loads config from app.config.Config
- Initializes SQLAlchemy with db.init_app(app)
- Registers players_bp and props_bp blueprints
- Runs db.create_all() to auto-create tables on first boot

### app/config.py

Reads environment variables with safe local defaults.

Variable | Default | Purpose
DATABASE_URL | sqlite:///prop_lab.db | DB connection string
SECRET_KEY | dev-secret-key | Flask session signing

### app/models/models.py

Player — players table
Column | Type | Notes
id | Integer PK | NBA API player ID
name | String | Full display name
team_abbr | String | e.g. LAL, BOS
position | String | e.g. G, F, C

PlayerGameStat — player_game_stats table
Column | Type | Notes
id | Integer PK | Auto-increment
player_id | FK | → players.id
date | Date | Game date
matchup | String | e.g. LAL vs. GSW
location | String | Home or Road
min | Float | Minutes played
pts | Float | Points
reb | Float | Rebounds
ast | Float | Assists
stl | Float | Steals
blk | Float | Blocks
fg3m | Float | 3-pointers made
tov | Float | Turnovers

Unique constraint on (player_id, date) prevents duplicate game entries.

### app/routes/players.py

Blueprint prefix="/". Serves all HTML pages and the /api/players listing.

### app/routes/props.py

Blueprint prefix="/api". All stat computation and data endpoints.

- Pre-computed endpoints (trending, prizepicks, parlays) read data/\*.json — no DB hit
- Per-player endpoints query the DB live and run hit rate math on the fly

### app/services/hit_rate.py

Core analytics engine. Operates purely on pandas DataFrames, no DB access.

Functions:

- hit_rate(df, stat, line, last_n, location, opponent) — hit rate %, average, streak, game log
- hit_rate_combo(df, combo, line, ...) — same for combo stats
- calculate_streak(values, line) — consecutive over/under streak from most recent game
- clean_series(values) — IQR outlier removal for cleaner averages
- extract_opponent(matchup) — parses "LAL vs. GSW" into "GSW"

COMBO_STATS:
pr = pts + reb
pa = pts + ast
ra = reb + ast
pra = pts + reb + ast
bs = blk + stl
sa = stl + ast

### app/services/nba_fetcher.py

Wraps nba_api with rate-limit-safe sleep delays and 3-attempt retry logic.

Functions:

- fetch_all_players() — all active NBA players as a DataFrame
- fetch_game_logs(player_id, season) — full season game log with retry/backoff
- fetch_opponent_defense() — team-level defensive stats for all 30 teams
- fetch_todays_matchups() — list of team abbreviations playing today

### app/services/prizepicks.py

Fetches PrizePicks NBA prop lines from their public projections JSON API. No browser or API key needed.

Endpoint: https://api.prizepicks.com/projections?league_id=7&per_page=250&single_stat=true

Uses browser-like headers (Origin, Referer, Accept-Language, Connection) to avoid 403 blocks.
Retry logic: 3 attempts, exponential backoff (2s, 4s, 8s).
Retries on 429/5xx. Returns [] immediately on other 4xx errors.

Stat label mapping:
Points → pts Rebounds → reb Assists → ast
Steals → stl Blocked Shots → blk 3-Pt Made → fg3m
Turnovers → tov Pts+Rebs+Asts → pra Pts+Rebs → pr
Pts+Asts → pa Rebs+Asts → ra Blks+Stls → bs

Odds types normalized: goblin / demon / standard

### scripts/daily_update.py

Headless daily DB updater. Reads DATABASE_URL from environment. Designed for cron or GitHub Actions.

Steps:

1. Load all players from DB
2. Find most recent logged game date per player
3. Fetch new game logs from NBA API for missing dates
4. Upsert PlayerGameStat rows (IntegrityError handled for duplicates)
5. ThreadPoolExecutor(max_workers=2) parallelizes NBA API calls safely

Run once per day at 6am after the previous night's games post to the NBA API.

### scripts/fetch_data.py

Main hourly refresh. Reads the DB, writes JSON. Never modifies DB directly.

Steps:

1. fetch_opponent_defense() → data/opponent_defense.json
2. fetch_todays_matchups() → data/todays_matchups.json
3. fetch_prizepicks_lines() → data/prizepicks_lines.json
4. Load all players + game stats from DB into memory
5. Compute hit rate, confidence score, average, streak per PP line
6. Write enriched results → data/prizepicks_results.json
7. Compute top 2-leg and 3-leg parlays by confidence
   → data/prizepicks_parlays.json
8. Compute hot streaks + top hitters
   → data/trending.json

### scripts/seed.py

One-time bootstrap. Populates the players table from the NBA API.
Must be run before daily_update.py on a fresh install.

### scripts/dedup.py

Removes duplicate rows from player_game_stats where (player_id, date) appears more than once.
Safe to run any time.

### scripts/fix_positions.py

Backfills missing position values in the players table by re-querying the NBA API.

### refresh.sh

Local convenience wrapper for manual data refreshes:
python3 scripts/fetch_data.py
git add data/
git diff --staged --quiet || git commit -m "chore: refresh data"
git push

### run.py

Development entrypoint. Calls create_app() and starts Flask on port 5002 with debug=True.

---

## Routes and API Endpoints

### Page Routes (prefix="/")

URL | Template | Description
GET / | index.html | Home page
GET /player/<id> | player.html | Individual player detail
GET /explore | explore.html | Explore all players by stat and line
GET /prizepicks | prizepicks.html | PrizePicks board with confidence scores
GET /parlays | parlays.html | Pre-computed parlay suggestions
GET /discover | redirect | Legacy URL → /explore
GET /trending | redirect | Legacy URL → /explore

### JSON API (prefix="/api")

Endpoint | Params | Returns
GET /api/players | — | [{id, name, team, position}]
GET /api/players/<id> | — | Single player object
GET /api/players/<id>/averages | — | Last 5 game averages all stats + combos
GET /api/players/<id>/opponents | — | Sorted list of unique opponents faced
GET /api/players/<id>/props | stat, line, last_n, location, opponent | Hit rate result for a single stat
GET /api/players/<id>/combo | combo, line, last_n, location, opponent | Hit rate result for a combo stat
GET /api/players/<id>/logs | — | Full game log as JSON array
GET /api/discover | stat, line, last_n | All players sorted by hit rate
GET /api/trending | — | {hot_streaks, top_hitters}
GET /api/prizepicks | — | Full enriched PrizePicks board
GET /api/prizepicks/parlays | — | Top parlay combinations

---

## Data Flow

First-time setup:
python3 scripts/seed.py
NBA API → players table (530 players)

Daily at 6am CDT:
python3 scripts/daily_update.py
NBA API → player_game_stats table
Only fetches games newer than the last logged date per player

Every hour:
python3 scripts/fetch_data.py
PrizePicks API → prizepicks_lines.json
NBA API → opponent_defense.json, todays_matchups.json
DB (read only) + hit_rate.py → prizepicks_results.json
prizepicks_results.json → prizepicks_parlays.json, trending.json

At request time (Flask):
Page routes → render HTML template (no computation)
/api/players/<id>/props → query DB → hit_rate() → return JSON
/api/prizepicks → read prizepicks_results.json → return JSON
/api/trending → read trending.json → return JSON

---

## Database Schema

Tables created automatically by db.create_all() on first boot.

players
id INTEGER PRIMARY KEY (NBA API player ID)
name VARCHAR NOT NULL
team_abbr VARCHAR
position VARCHAR

player_game_stats
id INTEGER PRIMARY KEY AUTOINCREMENT
player_id INTEGER NOT NULL REFERENCES players(id)
date DATE NOT NULL
matchup VARCHAR
location VARCHAR
min FLOAT
pts FLOAT
reb FLOAT
ast FLOAT
stl FLOAT
blk FLOAT
fg3m FLOAT
tov FLOAT
UNIQUE (player_id, date)

---

## Local Setup

Prerequisites:

- Python 3.11+
- pip
- Git
- (Optional) pyenv for version management

Steps:

1. Clone the repo
   git clone https://github.com/davisjburt/NBA-Prop-Lab.git
   cd NBA-Prop-Lab

2. Create and activate a virtual environment
   python3 -m venv venv
   source venv/bin/activate

3. Install dependencies
   pip install -r requirements.txt

4. Seed the database (first time only)
   python3 scripts/seed.py

5. Run the initial daily update to populate game stats
   python3 scripts/daily
   =======
   🏀 NBA Prop Lab

A blazing-fast, full-stack NBA player prop analysis tool. NBA Prop Lab pulls live player game logs from the NBA API, scrapes PrizePicks prop lines, computes hit rates and confidence scores, and presents actionable insights across a clean web UI.

The application is built with Flask, Pandas, and SQLite/Postgres, utilizing a decoupled architecture to ensure page loads and API responses are nearly instantaneous.

📑 Table of Contents

Overview & Architecture

Tech Stack

Project Structure

Local Setup & Installation

Data Pipeline Scripts

Routes and API Endpoints

Database Schema

Deployment on Render

Troubleshooting

🏛 Overview & Architecture

NBA Prop Lab features two independent systems that work seamlessly together. By decoupling the heavy data processing from the web server, the user interface remains incredibly fast.

The Data Pipeline (Background): Python scripts run on a schedule (via cron or Render background jobs) to pull data from the NBA API and PrizePicks. They update the relational database and pre-compute complex hit-rate analytics, saving the results as static JSON files.

The Web Application (Foreground): The Flask app serves HTML templates and API endpoints by strictly reading from the pre-computed JSON files and querying the database without performing heavy math at request time.

Data Flow Diagram

NBA API ──────────────────► daily_update.py ──► DB: players table
► DB: player_game_stats table

PrizePicks API ───────────► fetch_data.py ────► data/prizepicks_lines.json
► data/prizepicks_results.json
► data/prizepicks_parlays.json
► data/trending.json
► data/opponent_defense.json
► data/todays_matchups.json

Flask app (run.py) ───────► reads DB + JSON ──► HTML pages + JSON API

🛠 Tech Stack

Backend: Python 3.11+, Flask, SQLAlchemy

Data Processing: Pandas, ThreadPoolExecutor

Database: SQLite (Local) / PostgreSQL (Production)

External APIs: nba_api package, PrizePicks Public Projections API

Frontend: HTML/CSS (Jinja2 Templates), Custom Font (Milker.otf)

📂 Project Structure

NBA-Prop-Lab/
├── app/
│ ├── **init**.py # App factory: create_app()
│ ├── config.py # Config class (reads env vars)
│ ├── models/
│ │ └── models.py # SQLAlchemy ORM (Player, PlayerGameStat)
│ ├── routes/
│ │ ├── players.py # Page routes + player list API (prefix="/")
│ │ └── props.py # Stats + data API (prefix="/api")
│ ├── services/
│ │ ├── hit_rate.py # Hit rate, streaks, combo stat math (Pandas)
│ │ ├── nba_fetcher.py # NBA API wrapper with retry logic
│ │ └── prizepicks.py # PrizePicks public API scraper
│ ├── templates/ # Jinja2 HTML views
│ └── static/ # CSS, Fonts, and Logos
├── data/ # JSON files written by scripts, read by Flask
├── scripts/
│ ├── daily_update.py # NBA API → DB (run daily)
│ ├── fetch_data.py # PrizePicks + compute → JSON (run hourly)
│ ├── dedup.py # Removes duplicate game stat rows
│ ├── fix_positions.py # Backfills missing player positions
│ └── seed.py # One-time DB bootstrap for players
├── render.yaml # Render deploy config (web + cron jobs)
├── requirements.txt # Python dependencies
├── refresh.sh # Local helper: fetch data + git push
└── run.py # Dev server entrypoint

💻 Local Setup & Installation

Prerequisites: Python 3.11+ and Git.

1. Clone the repository:

git clone [https://github.com/davisjburt/NBA-Prop-Lab.git](https://github.com/davisjburt/NBA-Prop-Lab.git)
cd NBA-Prop-Lab

2. Create and activate a virtual environment:

python3 -m venv venv
source venv/bin/activate # On Windows use: venv\Scripts\activate

3. Install dependencies:

pip install -r requirements.txt

4. Seed the database (First time only):
   Populates the players table with all active NBA players.

python3 scripts/seed.py

5. Run the initial daily update:
   Fetches game logs for all players to populate the player_game_stats table.

python3 scripts/daily_update.py

6. Generate pre-computed JSON data:
   Scrapes PrizePicks and computes hit rates.

python3 scripts/fetch_data.py

7. Start the Flask development server:

python3 run.py

The app will be available at http://127.0.0.1:5002.

⚙️ Data Pipeline Scripts

To keep your local or production environment up to date, these scripts handle the heavy lifting.

seed.py: Run once on a fresh install. Grabs ~530 active players from the NBA API.

daily_update.py: Designed to run daily at 6:00 AM. Finds the most recent logged game date per player and fetches new logs from the NBA API. Parallelized with ThreadPoolExecutor.

fetch_data.py: Designed to run hourly. Scrapes PrizePicks lines, pulls opponent defense rankings, calculates hit rates/streaks/parlays via hit_rate.py, and writes everything to the data/ directory.

dedup.py: Utility to remove accidental duplicate rows in player_game_stats.

fix_positions.py: Utility to backfill missing position values (G, F, C).

refresh.sh: A convenient bash wrapper that runs fetch_data.py, commits the updated JSON files, and pushes to Git.

🌐 Routes and API Endpoints

UI Routes (/)

Method

Route

Template

Description

GET

/

index.html

Home page

GET

/player/<id>

player.html

Individual player detail and game logs

GET

/explore

explore.html

Explore all players filtered by stat and line

GET

/prizepicks

prizepicks.html

PrizePicks board sorted by confidence scores

GET

/parlays

parlays.html

Pre-computed algorithmic parlay suggestions

(Note: /discover and /trending automatically redirect to /explore)

JSON API Endpoints (/api)

Method

Endpoint

Query Params

Returns

GET

/api/players

—

[{id, name, team, position}]

GET

/api/players/<id>

—

Single player object

GET

/api/players/<id>/averages

—

Last 5 game averages (base + combo stats)

GET

/api/players/<id>/opponents

—

Sorted list of unique opponents faced

GET

/api/players/<id>/props

stat, line, last_n, location, opponent

Hit rate result for a single stat

GET

/api/players/<id>/combo

combo, line, last_n, location, opponent

Hit rate result for a combo stat (e.g. PRA)

GET

/api/players/<id>/logs

—

Full game log as a JSON array

GET

/api/discover

stat, line, last_n

All players sorted by hit rate

GET

/api/trending

—

{hot_streaks, top_hitters}

GET

/api/prizepicks

—

Full enriched PrizePicks board

GET

/api/prizepicks/parlays

—

Top 2-leg and 3-leg parlay combinations

Combo Stats Supported: pr (Pts+Reb), pa (Pts+Ast), ra (Reb+Ast), pra (Pts+Reb+Ast), bs (Blk+Stl), sa (Stl+Ast).

🗄 Database Schema

The database relies on SQLAlchemy and uses standard relational patterns. Tables are auto-created on the first boot via db.create_all().

players table
| Column | Type | Notes |
| :--- | :--- | :--- |
| id | Integer (PK) | NBA API player ID |
| name | String | Full display name |
| team_abbr | String | e.g., LAL, BOS |
| position | String | e.g., G, F, C |

player_game_stats table
| Column | Type | Notes |
| :--- | :--- | :--- |
| id | Integer (PK) | Auto-increment ID |
| player_id | Integer (FK) | References players.id |
| date | Date | Game date |
| matchup | String | e.g., "LAL vs. GSW" |
| location | String | "Home" or "Road" |
| min, pts, reb, ast, stl, blk, fg3m, tov | Float | Base game stats |

Note: A unique constraint exists on (player_id, date) to prevent duplicate game entries.

🚀 Deployment on Render

This project is configured for one-click deployment via Render using the provided render.yaml Blueprint.

Connect your GitHub repository to Render.

Go to Blueprints -> New Blueprint Instance and select this repo.

Render will automatically read render.yaml and provision:

Web Service: The Flask frontend/API.

PostgreSQL Database: Production database replacing SQLite.

Cron Jobs: Background tasks mapped to daily_update.py and fetch_data.py.

Environment Variables: Ensure DATABASE_URL, SECRET_KEY, and FLASK_ENV are appropriately set in your Render dashboard.

🚑 Troubleshooting

The UI loads but the boards/tables are completely empty:
Your app cannot find the JSON files in the /data directory. Run python3 scripts/fetch_data.py to generate them.

Missing or outdated game stats:
Run python3 scripts/daily_update.py to fetch the latest NBA game logs. If players were recently drafted/traded, re-run seed.py and fix_positions.py.

Hit rate math looks wrong / Duplicate game logs:
If the database constraint was bypassed, run python3 scripts/dedup.py to clean up the player_game_stats table.

NBA API Timeout / Rate Limit Errors (429):
The nba_fetcher.py service uses exponential backoff. If you are continually rate-limited by the NBA API, pause scripts for 15-30 minutes and try again.

> > > > > > > 5a6f83e (readme)

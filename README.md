# NBA Prop Lab

A full-stack NBA player prop analysis tool built with **Flask** and **SQLite/Postgres**. It pulls player game logs from the NBA API, ingests PrizePicks (and optional book) prop lines, computes hit rates and confidence scores, and serves a fast UI: **Players**, **Player Props**, **Parlays**, **Moneylines**, and **Model Stats**. The **`/explore`** page still exists (legacy redirects point there), but it is **not shown in the main navigation**.

---

## Table of Contents

- [Overview](#overview)
- [Model evaluation pipeline](#model-evaluation-pipeline)
- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Scripts reference](#scripts-reference)
- [Routes and API](#routes-and-api)
- [Data flow](#data-flow)
- [Database schema](#database-schema)
- [Local setup](#local-setup)
- [Environment variables](#environment-variables)
- [Running the app](#running-the-app)
- [Refreshing data](#refreshing-data)
- [Recovery and history](#recovery-and-history)
- [Deployment on Render](#deployment-on-render)
- [Scheduled jobs](#scheduled-jobs)
- [Troubleshooting](#troubleshooting)

---

## Overview

Two systems work together:

1. **Flask web app** — Reads precomputed JSON under `data/` and queries the DB for player logs and model-eval tables. Heavy math runs in batch scripts, not per HTTP request.
2. **Data pipeline** — Scripts fetch NBA and prop-board data, write **`data/*.json` first**, then hydrate/resolve **model evaluation** rows in the DB, then optionally push model tables to **Heroku Postgres** via `sync_to_heroku.py`.

**Box scores** (`player_game_stats`) are still written directly by `daily_update.py` — that ingestion step is separate from the model-eval JSON-first flow.

---

## Model evaluation pipeline

End-to-end order used by `./refresh.sh`:

| Step | Script | What happens |
|------|--------|----------------|
| 1 | `daily_update.py` | NBA API → `players` / `player_game_stats` |
| 2 | `dedup.py` | Remove duplicate `(player_id, date)` rows if any |
| 3 | `fetch_data.py` | Fetches props, computes board → **`moneylines.json`**, **`prizepicks_results.json`**, etc. **Does not** insert into `model_prop_eval` / `model_moneyline_eval`. |
| 4 | `update_model_stats.py` | Rebuilds **today’s** slate from JSON, resolves hits vs `player_game_stats`, writes **`model_prop_eval_sync.json`**, **`model_moneyline_eval_sync.json`**, **`model_stats_*.json`** |
| 5 | `sync_to_heroku.py` | Bulk INSERT into Postgres using sync JSON (full columns including resolved fields when present) |

The **Model Stats** page calls **`GET /api/model_outcomes?days=…`**, which aggregates from the **live database** (`build_outcomes_summary`), not from stale snapshot files.

---

## How it works

```
NBA API ───────────────► daily_update.py ──► players, player_game_stats

External props APIs ─────► fetch_data.py ──► data/*.json (board + context files)

update_model_stats.py ──► model_prop_eval, model_moneyline_eval (local DB)
                       ──► data/model_*_eval_sync.json, model_stats_*.json

sync_to_heroku.py ──────► Heroku Postgres (model tables)

Flask (run.py) ─────────► reads DB + data/*.json ──► pages + /api
```

---

## Project structure

```
NBA-Prop-Lab/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── models/models.py          # Player, PlayerGameStat, ModelPropEval, ModelMoneylineEval
│   ├── routes/
│   │   ├── players.py            # HTML routes (/, /player, /prizepicks, /moneylines, /model-stats, …)
│   │   ├── props.py              # /api/* data (props, moneylines JSON, legacy model_stats)
│   │   └── model_stats.py        # GET /api/model_outcomes
│   ├── services/                 # hit_rate, nba_fetcher, prizepicks, moneyline, model_summary, …
│   ├── templates/                # index, player, prizepicks, parlays, moneylines, model-stats, explore, …
│   └── static/
├── data/                         # JSON outputs + sync snapshots (git-tracked where applicable)
├── scripts/
│   ├── daily_update.py
│   ├── fetch_data.py
│   ├── update_model_stats.py     # hydrate today, resolve, write stats + sync JSON
│   ├── sync_to_heroku.py         # Postgres bulk sync from sync JSON (fallback: prizepicks/moneylines JSON)
│   ├── dedup.py
│   ├── seed.py
│   ├── check_model_history.py    # DB row counts / date ranges for model tables
│   └── recover_model_history_from_git.py  # replay history from git snapshots (optional)
├── refresh.sh                    # Full local pipeline + git push
├── run.py                        # Dev server (port 5002)
├── requirements.txt
└── render.yaml
```

---

## Scripts reference

| Script | Purpose |
|--------|---------|
| `seed.py` | One-time: populate `players` from NBA API |
| `daily_update.py` | Incremental box scores → `player_game_stats` |
| `dedup.py` | Remove duplicate game stat rows |
| `fetch_data.py` | Fetches lines + computes enriched board → `data/*.json` (no model-eval table writes) |
| `update_model_stats.py` | Hydrate today from JSON, resolve props/moneylines, write `model_stats_*.json` and `model_*_eval_sync.json`. **`--skip-hydrate`**: skip replacing today from JSON (e.g. after git recovery). |
| `sync_to_heroku.py` | Push `model_prop_eval` / `model_moneyline_eval` to Postgres (`HEROKU_DATABASE_URL` or `DATABASE_URL`) |
| `check_model_history.py` | Print masked `DATABASE_URL`, counts, and date ranges for model tables |
| `recover_model_history_from_git.py` | Replay `data/prizepicks_results.json` / `data/moneylines.json` from git history into model tables. **`--apply --finish`**: replay + run `update_model_stats.py --skip-hydrate` in one shot |

---

## Routes and API

### Page routes (`/`)

| Method | Path | Template | Notes |
|--------|------|----------|--------|
| GET | `/` | `index.html` | Player grid |
| GET | `/player/<id>` | `player.html` | Player detail |
| GET | `/prizepicks` | `prizepicks.html` | Props board |
| GET | `/parlays` | `parlays.html` | Parlays |
| GET | `/moneylines` | `moneylines.html` | Game predictions |
| GET | `/model-stats` | `model-stats.html` | Model outcomes |
| GET | `/explore` | `explore.html` | Still reachable; **not linked in nav** |
| GET | `/discover`, `/trending` | redirect | → `/explore` |

### JSON API (`/api`)

| Endpoint | Notes |
|----------|--------|
| `GET /api/players` | Player list |
| `GET /api/players/<id>/…` | Averages, props, combo, logs, etc. |
| `GET /api/prizepicks`, `/api/prizepicks/parlays` | From `data/*.json` |
| `GET /api/moneylines` | From `moneylines.json` |
| `GET /api/model_outcomes?days=0|7|30|90` | Aggregated model stats (DB-backed) |
| `GET /api/model_stats?days=…` | Legacy aggregate endpoint (still in `props.py`) |

---

## Data flow

**First-time**

1. `python3 scripts/seed.py`
2. `python3 scripts/daily_update.py`
3. `python3 scripts/fetch_data.py`
4. `python3 scripts/update_model_stats.py`

**Ongoing** — use `./refresh.sh` (see below) or the same steps manually.

---

## Database schema

Auto-created via `db.create_all()`:

- **`players`** — NBA player id, name, team, position  
- **`player_game_stats`** — One row per player per game; unique `(player_id, date)`  
- **`model_prop_eval`** — Tracked prop picks (date, player, stat, line, confidence, `result_value`, `hit`)  
- **`model_moneyline_eval`** — Game picks (teams, probs, `actual_winner`, `margin`, `correct`)

---

## Local setup

- Python **3.11+**
- `git`, `pip`

```bash
git clone https://github.com/davisjburt/NBA-Prop-Lab.git
cd NBA-Prop-Lab
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 scripts/seed.py
python3 scripts/daily_update.py
python3 scripts/fetch_data.py
python3 scripts/update_model_stats.py
python3 run.py
```

App: **http://127.0.0.1:5002**

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | SQLAlchemy URL (SQLite locally, Postgres in production) |
| `HEROKU_DATABASE_URL` | Optional; `refresh.sh` switches to this for `sync_to_heroku.py` |
| `LOCAL_DATABASE_URL` | Used when `USE_LOCAL_DATABASE=1` in `refresh.sh` to point compute at a local DB |
| `SECRET_KEY` | Flask session signing |
| `SKIP_TRENDING` | Set in `refresh.sh` to skip trending computation in `fetch_data` |

Define these in a `.env` file (see `app/config.py`) or export them in your shell.

---

## Running the app

```bash
source venv/bin/activate
python3 run.py
```

---

## Refreshing data

**Recommended:** from repo root, with `.env` loaded:

```bash
chmod +x refresh.sh
./refresh.sh
```

This runs: `daily_update` → `dedup` → `fetch_data` (with `SKIP_TRENDING=1`) → `update_model_stats` → `sync_to_heroku` (if `HEROKU_DATABASE_URL` is set) → `git add data/` → commit/push when there are changes.

---

## Recovery and history

- **`scripts/check_model_history.py`** — Inspect whether resolved rows exist and which date range is present.
- **`scripts/recover_model_history_from_git.py`** — Best-effort rebuild of `model_*_eval` rows from historical **`data/prizepicks_results.json`** and **`data/moneylines.json`** committed in git (one row per commit date).  
  **One-shot:**  
  `python3 scripts/recover_model_history_from_git.py --apply --finish`  

This does **not** replace a full Postgres backup; it only replays what exists in git history.

---

## Deployment on Render

Use the repo’s `render.yaml` Blueprint: web service + Postgres + cron jobs as defined there. Set `DATABASE_URL`, `SECRET_KEY`, and `FLASK_ENV` in the Render dashboard.

---

## Scheduled jobs

Cron or Render schedulers typically run `daily_update.py` and/or `fetch_data.py` on a schedule. Align them with `./refresh.sh` if you want parity with local full refresh.

---

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| Empty props / moneylines JSON | Run `fetch_data.py`; check PrizePicks/API errors in the console |
| Model Stats shows no graded outcomes | Run `daily_update.py` so `player_game_stats` exists for game dates, then `update_model_stats.py`. Use the same `DATABASE_URL` as the app. |
| Heroku model tables out of date | Run `sync_to_heroku.py` with `DATABASE_URL` pointing at Heroku (or set `HEROKU_DATABASE_URL` and use `refresh.sh`) |
| Duplicate game logs | `python3 scripts/dedup.py` |
| Postgres sequence errors after import | `python3 scripts/repair_postgres_sequences.py` (if present) |
| NBA API 429 | Back off 15–30 minutes; `daily_update` uses throttling |

---

## License / contributing

See repository defaults; update this section if you add a formal license.

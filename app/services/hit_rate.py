import numpy as np

COMBO_STATS = {
    "pr":  ["pts", "reb"],
    "pa":  ["pts", "ast"],
    "ra":  ["reb", "ast"],
    "pra": ["pts", "reb", "ast"],
    "sa":  ["stl", "ast"],
    "bs":  ["blk", "stl"],
}

STAT_OPP_KEY = {
    "pts":  "opp_pts",
    "reb":  "opp_reb",
    "ast":  "opp_ast",
    "stl":  "opp_stl",
    "blk":  "opp_blk",
    "tov":  "opp_tov",
    "fg3m": "opp_fg3m",
}

def extract_opponent(matchup):
    parts = matchup.strip().replace("vs.", "vs").split()
    return parts[-1] if parts else "???"

def calculate_streak(values, line):
    if not values:
        return {"count": 0, "type": "none"}
    streak_type = "hit" if values[0] > line else "miss"
    count = 0
    for v in values:
        if (v > line) == (streak_type == "hit"):
            count += 1
        else:
            break
    return {"count": count, "type": streak_type}

def clean_series(values):
    if len(values) < 4:
        return values
    arr = np.array(values, dtype=float)
    q1, q3 = np.percentile(arr, 25), np.percentile(arr, 75)
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    cleaned = arr[(arr >= lower) & (arr <= upper)]
    return cleaned.tolist() if len(cleaned) >= 3 else values

def clean_avg(values, n=None):
    vals = values[:n] if n else values
    if not vals:
        return None
    return round(float(np.mean(clean_series(vals))), 1)

def league_avg_by_stat(opp_defense: dict) -> dict[str, float]:
    """Precompute league mean per stat for matchup_multiplier (called once per fetch)."""
    if not opp_defense:
        return {}
    out: dict[str, float] = {}
    for stat, opp_key in STAT_OPP_KEY.items():
        vals = [v[opp_key] for v in opp_defense.values() if opp_key in v]
        out[stat] = float(np.mean(vals)) if vals else 0.0
    return out


def matchup_multiplier(
    opponent_abbr,
    stat,
    opp_defense: dict,
    league_avgs: dict[str, float] | None = None,
) -> float:
    """
    Returns a multiplier > 1.0 if opponent allows more than league avg for this stat,
    < 1.0 if they allow less. Neutral = 1.0.
    Stat is e.g. 'pts', combo stats use primary component.
    Pass league_avgs from league_avg_by_stat(opp_defense) to avoid O(teams) work per line.
    """
    if not opp_defense or not opponent_abbr:
        return 1.0
    opp_key = STAT_OPP_KEY.get(stat)
    if not opp_key:
        return 1.0
    team_data = opp_defense.get(opponent_abbr.upper())
    if not team_data or opp_key not in team_data:
        return 1.0
    opp_val = team_data[opp_key]
    if league_avgs is not None:
        league_avg = league_avgs.get(stat, 0.0)
    else:
        league_avg = float(np.mean([v[opp_key] for v in opp_defense.values() if opp_key in v]))
    if league_avg == 0:
        return 1.0
    return round(opp_val / league_avg, 3)

def confidence_score(
    hit_rate_l5,
    hit_rate_l10,
    hit_rate_season,
    edge,
    matchup_mult,
    streak_count,
    streak_type,
    home_away_bonus=0.0,
    minutes_avg_l5=None,
    minutes_avg_season=None,
):
    """
    Composite 0–100 confidence score.
    Weights: L5 hit rate (35%), L10 (25%), season (15%), edge (10%), matchup (10%), streak (5%)
    """
    hr_l5     = (hit_rate_l5     or 0) * 35
    hr_l10    = (hit_rate_l10    or 0) * 25
    hr_season = (hit_rate_season or 0) * 15

    # Edge: normalize +/- 5 range → 0–10 pts
    edge_score = 0
    if edge is not None:
        edge_clamped = max(-5, min(5, edge))
        edge_score = ((edge_clamped + 5) / 10) * 10

    # Matchup: mult 0.8–1.2 → 0–10 pts
    matchup_score = max(0, min(10, (matchup_mult - 0.8) / 0.4 * 10))

    # Streak bonus: up to +/-5 pts
    streak_score = 0
    if streak_type == "hit":
        streak_score = min(5, streak_count)
    elif streak_type == "miss":
        streak_score = -min(5, streak_count)

    raw = (
        hr_l5
        + hr_l10
        + hr_season
        + edge_score
        + matchup_score
        + streak_score
        + (home_away_bonus * 5)
    )

    # Minutes-based adjustments (v1)
    if minutes_avg_l5 is not None and minutes_avg_season not in (None, 0):
        r = minutes_avg_l5 / minutes_avg_season

        # Penalty for very low recent minutes
        if minutes_avg_l5 < 20:
            raw -= 8

        # Penalty if recent minutes are much lower than season
        if r < 0.75:
            raw -= 7

        # Small bonus for high, stable minutes
        if minutes_avg_l5 > 32 and r > 0.9:
            raw += 4

    return round(max(0, min(100, raw)), 1)

def hit_rate(
    df,
    stat,
    line,
    last_n=None,
    location=None,
    opponent=None,
    include_games=True,
):
    subset = df
    if location:
        subset = subset[subset["location"] == location]
    if opponent:
        subset = subset[subset["matchup"].str.contains(opponent, case=False, na=False)]
    if last_n:
        subset = subset.head(last_n)
    if subset.empty:
        return {"error": "No data matching filters"}

    hits  = (subset[stat] > line).sum()
    total = len(subset)

    result = {
        "stat":     stat,
        "line":     line,
        "sample":   total,
        "hits":     int(hits),
        "hit_rate": round(hits / total, 3),
        "avg":      round(subset[stat].mean(), 1),
        "max":      round(subset[stat].max(), 1),
        "min":      round(subset[stat].min(), 1),
        "streak":   calculate_streak(subset[stat].tolist(), line),
    }
    if include_games:
        result["games"] = subset[["date", "matchup", stat]].to_dict(orient="records")
    return result


def hit_rate_combo(
    df,
    combo,
    line,
    last_n=None,
    location=None,
    opponent=None,
    include_games=True,
):
    if combo not in COMBO_STATS:
        return {"error": f"Unknown combo: {combo}"}
    subset = df
    if location:
        subset = subset[subset["location"] == location]
    if opponent:
        subset = subset[subset["matchup"].str.contains(opponent, case=False, na=False)]
    if last_n:
        subset = subset.head(last_n)
    if subset.empty:
        return {"error": "No data matching filters"}
    cols = COMBO_STATS[combo]
    combo_total = subset[cols].sum(axis=1)
    hits  = (combo_total > line).sum()
    total = len(subset)
    result = {
        "stat":       combo.upper(),
        "components": "+".join(c.upper() for c in cols),
        "line":       line,
        "sample":     total,
        "hits":       int(hits),
        "hit_rate":   round(hits / total, 3),
        "avg":        round(combo_total.mean(), 1),
        "max":        round(combo_total.max(), 1),
        "min":        round(combo_total.min(), 1),
        "streak":     calculate_streak(combo_total.tolist(), line),
    }
    if include_games:
        games_subset = subset[["date", "matchup"] + cols].copy()
        games_subset["combo_total"] = combo_total
        result["games"] = games_subset.to_dict(orient="records")
    return result

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

def matchup_multiplier(opponent_abbr, stat, opp_defense: dict) -> float:
    """
    Returns a multiplier > 1.0 if opponent allows more than league avg for this stat,
    < 1.0 if they allow less. Neutral = 1.0.
    Stat is e.g. 'pts', combo stats use primary component.
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
    league_avg = float(np.mean([v[opp_key] for v in opp_defense.values() if opp_key in v]))
    if league_avg == 0:
        return 1.0
    return round(opp_val / league_avg, 3)

def confidence_score(hit_rate_l5, hit_rate_l10, hit_rate_season, edge, matchup_mult, streak_count, streak_type, home_away_bonus=0.0):
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

    # Streak bonus: up to 5 pts
    streak_score = 0
    if streak_type == "hit":
        streak_score = min(5, streak_count)
    elif streak_type == "miss":
        streak_score = -min(5, streak_count)

    raw = hr_l5 + hr_l10 + hr_season + edge_score + matchup_score + streak_score + (home_away_bonus * 5)
    return round(max(0, min(100, raw)), 1)

def hit_rate(df, stat, line, last_n=None, location=None, opponent=None):
    subset = df.copy()
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
    return {
        "stat":     stat,
        "line":     line,
        "sample":   total,
        "hits":     int(hits),
        "hit_rate": round(hits / total, 3),
        "avg":      round(subset[stat].mean(), 1),
        "max":      round(subset[stat].max(), 1),
        "min":      round(subset[stat].min(), 1),
        "streak":   calculate_streak(subset[stat].tolist(), line),
        "games":    subset[["date", "matchup", stat]].to_dict(orient="records"),
    }

def hit_rate_combo(df, combo, line, last_n=None, location=None, opponent=None):
    if combo not in COMBO_STATS:
        return {"error": f"Unknown combo: {combo}"}
    subset = df.copy()
    if location:
        subset = subset[subset["location"] == location]
    if opponent:
        subset = subset[subset["matchup"].str.contains(opponent, case=False, na=False)]
    if last_n:
        subset = subset.head(last_n)
    if subset.empty:
        return {"error": "No data matching filters"}
    cols = COMBO_STATS[combo]
    subset = subset.copy()
    subset["combo_total"] = subset[cols].sum(axis=1)
    hits  = (subset["combo_total"] > line).sum()
    total = len(subset)
    return {
        "stat":       combo.upper(),
        "components": "+".join(c.upper() for c in cols),
        "line":       line,
        "sample":     total,
        "hits":       int(hits),
        "hit_rate":   round(hits / total, 3),
        "avg":        round(subset["combo_total"].mean(), 1),
        "max":        round(subset["combo_total"].max(), 1),
        "min":        round(subset["combo_total"].min(), 1),
        "streak":     calculate_streak(subset["combo_total"].tolist(), line),
        "games":      subset[["date", "matchup"] + cols + ["combo_total"]].to_dict(orient="records"),
    }

COMBO_STATS = {
    "pr":  ["pts", "reb"],
    "pa":  ["pts", "ast"],
    "ra":  ["reb", "ast"],
    "pra": ["pts", "reb", "ast"],
    "sa":  ["stl", "ast"],
    "bs":  ["blk", "stl"],
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

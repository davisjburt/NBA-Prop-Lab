def hit_rate(df, stat: str, line: float, last_n: int = None, location: str = None) -> dict:
    subset = df.copy()

    if location:
        subset = subset[subset["location"] == location]
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
    }

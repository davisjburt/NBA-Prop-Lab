"""
app/services/moneyline.py
--------------------------
Computes win probability and point-spread estimates for tonight's NBA games.

Factors (weighted):
  1. Recent form — W% last 10 games              (25%)
  2. Season net rating (off_rtg - def_rtg)        (20%)
  3. Home court advantage                         (15%)
  4. Head-to-head record this season              (10%)
  5. Opponent defensive rating                    (10%)
  6. Injury impact (Out/Questionable/Doubtful)    (20%)
"""

from __future__ import annotations
import math
from typing import Dict, Any, Optional


# ── Injury status weights ──────────────────────────────────────────────────
# How many team-points-per-game we shave off when a player is unavailable.
# We multiply by the player's share of team scoring.
INJURY_IMPACT = {
    "out":         1.00,   # full loss
    "doubtful":    0.75,
    "questionable":0.35,
    "available":   0.00,   # listed but available — no penalty
    "probable":    0.05,
}

HOME_COURT_PTS = 3.0          # historical NBA home-court advantage in points
LEAGUE_AVG_ORTG = 113.0       # approx 2024-25 league average offensive rating
LEAGUE_AVG_NET  = 0.0         # by definition


def _sigmoid(x: float) -> float:
    """Map a real number to (0, 1)."""
    return 1.0 / (1.0 + math.exp(-x))


def _injury_pts_lost(
    injuries: list[dict],
    team_abbr: str,
    team_avg_pts: float,
) -> float:
    """
    Estimate points lost due to injuries for a given team.

    injuries: list of dicts with keys: team_abbr, player_name, status,
              player_avg_pts (injected by fetch layer).
    team_avg_pts: team's season scoring average.
    """
    lost = 0.0
    for inj in injuries:
        if inj.get("team_abbr", "").upper() != team_abbr.upper():
            continue
        status = inj.get("status", "").lower()
        weight = INJURY_IMPACT.get(status, 0.0)
        if weight == 0.0:
            continue
        # Use individual player avg if available, else assume 5% of team pts
        player_pts = inj.get("player_avg_pts") or (team_avg_pts * 0.05)
        lost += weight * player_pts
    return round(lost, 1)


def compute_game_prediction(
    home_abbr: str,
    away_abbr: str,
    team_stats: Dict[str, Dict],   # keyed by team abbr
    injuries: list[dict],
    h2h: Optional[Dict] = None,    # {"home_wins": int, "away_wins": int}
) -> Dict[str, Any]:
    """
    Returns a prediction dict for a single game.

    team_stats[abbr] should contain:
        w_pct_l10, net_rtg, off_rtg, def_rtg, pts_avg,
        home_w_pct, road_w_pct
    """
    home = team_stats.get(home_abbr, {})
    away = team_stats.get(away_abbr, {})

    # ── 1. Recent form (W% last 10) ───────────────────────────────────────
    home_form = home.get("w_pct_l10", 0.5)
    away_form = away.get("w_pct_l10", 0.5)
    form_edge = (home_form - away_form) * 25        # max ±25 pts

    # ── 2. Season net rating ──────────────────────────────────────────────
    home_net = home.get("net_rtg", 0.0)
    away_net = away.get("net_rtg", 0.0)
    net_edge  = (home_net - away_net) * 1.5         # ≈ ±15 pts for big gap

    # ── 3. Home court advantage ───────────────────────────────────────────
    home_advantage = 7.5                             # ~7.5 raw score pts

    # ── 4. H2H this season ───────────────────────────────────────────────
    h2h_edge = 0.0
    if h2h:
        total = h2h.get("home_wins", 0) + h2h.get("away_wins", 0)
        if total > 0:
            h2h_rate = h2h.get("home_wins", 0) / total
            h2h_edge = (h2h_rate - 0.5) * 10       # max ±5 pts

    # ── 5. Opponent defensive rating ─────────────────────────────────────
    # Home team scores against away team's defense
    away_def = away.get("def_rtg", LEAGUE_AVG_ORTG)
    home_def = home.get("def_rtg", LEAGUE_AVG_ORTG)
    # Better defense = lower def_rtg
    def_edge = (away_def - home_def) * 0.5          # max ~±10 pts

    # ── 6. Injury adjustment ─────────────────────────────────────────────
    home_pts_avg = home.get("pts_avg", 113.0)
    away_pts_avg = away.get("pts_avg", 113.0)
    home_inj_loss = _injury_pts_lost(injuries, home_abbr, home_pts_avg)
    away_inj_loss = _injury_pts_lost(injuries, away_abbr, away_pts_avg)
    inj_edge = (away_inj_loss - home_inj_loss) * 1.2   # penalize the injured side

    # ── Composite score ───────────────────────────────────────────────────
    raw_score = (
        form_edge
        + net_edge
        + home_advantage
        + h2h_edge
        + def_edge
        + inj_edge
    )

    # Convert to win probability via sigmoid (scale so ±20 pts ≈ 73/27%)
    win_prob_home = round(_sigmoid(raw_score / 12) * 100, 1)
    win_prob_away = round(100 - win_prob_home, 1)

    # Estimated point spread (positive = home favored)
    spread = round(raw_score * 0.18, 1)   # empirical scale

    # Predicted score (rough)
    home_score_est = round(
        home_pts_avg
        - home_inj_loss
        + (away_def - LEAGUE_AVG_ORTG) * -0.25
        + (HOME_COURT_PTS * 0.5),
        1,
    )
    away_score_est = round(
        away_pts_avg
        - away_inj_loss
        + (home_def - LEAGUE_AVG_ORTG) * -0.25,
        1,
    )

    predicted_winner = home_abbr if win_prob_home >= 50 else away_abbr

    # ── Factor breakdown for UI ───────────────────────────────────────────
    factors = {
        "form":      round(form_edge, 1),
        "net_rtg":   round(net_edge, 1),
        "home_court":round(home_advantage, 1),
        "h2h":       round(h2h_edge, 1),
        "defense":   round(def_edge, 1),
        "injuries":  round(inj_edge, 1),
    }

    return {
        "home": home_abbr,
        "away": away_abbr,
        "predicted_winner": predicted_winner,
        "win_prob_home": win_prob_home,
        "win_prob_away": win_prob_away,
        "spread": spread,                       # home spread (- means home favored)
        "home_score_est": home_score_est,
        "away_score_est": away_score_est,
        "factors": factors,
        # Team context
        "home_net_rtg":  home.get("net_rtg"),
        "away_net_rtg":  away.get("net_rtg"),
        "home_form":     round(home_form * 100, 1),
        "away_form":     round(away_form * 100, 1),
        "home_inj_loss": home_inj_loss,
        "away_inj_loss": away_inj_loss,
    }
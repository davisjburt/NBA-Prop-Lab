"""
app/services/props_sources.py
-----------------------------
Provider-style props aggregation with fail-safe adapters.

Currently supports:
  - PrizePicks (existing endpoint)
  - DraftKings Sportsbook (public event-group endpoint, best-effort parser)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import os
import re
import time

import requests

from app.services.prizepicks import (
    PrizePicksError,
    fetch_prizepicks_lines,
    normalize,
)


@dataclass
class ProviderResult:
    source: str
    lines: list[dict]
    error: str | None = None


class DraftKingsError(Exception):
    pass


DK_EVENT_GROUP_NBA = "42648"
DK_URL_TMPL = (
    "https://sportsbook.draftkings.com/sites/US-SB/api/v5/eventgroups/{event_group}"
)
DK_LEAGUE_PAGE_URL = "https://sportsbook.draftkings.com/leagues/basketball/nba"
DK_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://sportsbook.draftkings.com/",
}

# Common DK labels to internal stat keys
DK_STAT_MAP = {
    "Points": "pts",
    "Rebounds": "reb",
    "Assists": "ast",
    "Steals": "stl",
    "Blocks": "blk",
    "3-Pointers Made": "fg3m",
    "Three Pointers Made": "fg3m",
    "Turnovers": "tov",
    "Pts + Rebs + Asts": "pra",
    "Pts + Rebs": "pr",
    "Pts + Asts": "pa",
    "Rebs + Asts": "ra",
    "Blks + Stls": "bs",
}


def _normalize_lines(lines: list[dict], source: str) -> list[dict]:
    normalized: list[dict] = []
    for row in lines:
        if not row.get("name") or not row.get("stat"):
            continue
        out = dict(row)
        out.setdefault("name_key", normalize(row["name"]))
        out.setdefault("team", "")
        out.setdefault("position", "")
        out.setdefault("odds_type", "standard")
        out["source"] = source
        normalized.append(out)
    return normalized


def _iter_dk_outcomes(payload: dict):
    # DK payload shape can drift; this traversal is intentionally defensive.
    event_group = payload.get("eventGroup", {})
    for category in event_group.get("offerCategories", []):
        category_name = category.get("name", "")
        # Keep only player-prop categories
        if "player" not in category_name.lower():
            continue
        for sub_desc in category.get("offerSubcategoryDescriptors", []):
            sub_name = sub_desc.get("name", "")
            offers = sub_desc.get("offerSubcategory", {}).get("offers", [])
            for offer_group in offers:
                for offer in offer_group:
                    outcomes = offer.get("outcomes", [])
                    for outcome in outcomes:
                        yield sub_name, offer, outcome


def _parse_dk_lines(payload: dict) -> list[dict]:
    lines: list[dict] = []
    for sub_name, offer, outcome in _iter_dk_outcomes(payload):
        stat_key = DK_STAT_MAP.get(sub_name) or DK_STAT_MAP.get(offer.get("label", ""))
        if not stat_key:
            continue

        participant = (
            outcome.get("participant")
            or outcome.get("participantName")
            or outcome.get("label")
            or ""
        )
        if not participant:
            continue

        # Only track over lines for parity with current app behavior.
        side_label = (outcome.get("label") or "").lower()
        if side_label and "over" not in side_label:
            continue

        line_val = outcome.get("line")
        if line_val is None:
            continue

        try:
            parsed_line = float(line_val)
        except (TypeError, ValueError):
            continue

        lines.append(
            {
                "name": participant,
                "stat": stat_key,
                "pp_stat_label": sub_name or offer.get("label") or stat_key,
                "line": parsed_line,
                "odds_type": "standard",
                "book": "draftkings",
            }
        )
    return lines


def _discover_dk_event_groups() -> list[str]:
    """
    Best-effort discovery from the public NBA league page.
    This helps when DK rotates event group ids.
    """
    try:
        resp = requests.get(DK_LEAGUE_PAGE_URL, headers=DK_HEADERS, timeout=20)
        if resp.status_code != 200:
            return []
        html = resp.text
        ids = re.findall(r'"eventGroupId"\s*:\s*(\d+)', html)
        # Preserve order while de-duping
        seen: set[str] = set()
        out: list[str] = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out
    except Exception:
        return []


def _dk_endpoint_candidates(event_group_ids: list[str]) -> list[tuple[str, dict]]:
    base_urls = [
        "https://sportsbook.draftkings.com/sites/US-SB/api/v5/eventgroups/{id}",
        "https://sportsbook-nash-usmi.draftkings.com/sites/US-MI-SB/api/v5/eventgroups/{id}",
        "https://sportsbook-nash-uspa.draftkings.com/sites/US-PA-SB/api/v5/eventgroups/{id}",
        "https://sportsbook-nash-usnj.draftkings.com/sites/US-NJ-SB/api/v5/eventgroups/{id}",
    ]
    params_options = [
        {"format": "json"},
        {"format": "json", "isAjax": "true"},
        {"format": "json", "includePromotions": "false"},
    ]
    candidates: list[tuple[str, dict]] = []
    for eg in event_group_ids:
        for tmpl in base_urls:
            url = tmpl.format(id=eg)
            for params in params_options:
                candidates.append((url, params))
    return candidates


def fetch_draftkings_lines() -> list[dict]:
    configured = os.getenv("DRAFTKINGS_EVENT_GROUP", "").strip()
    discovered = _discover_dk_event_groups()
    event_groups = []
    for eg in [configured, DK_EVENT_GROUP_NBA, *discovered]:
        if eg and eg not in event_groups:
            event_groups.append(eg)

    attempts = _dk_endpoint_candidates(event_groups)
    max_attempts = int(os.getenv("DRAFTKINGS_MAX_ATTEMPTS", "6"))
    per_req_timeout = int(os.getenv("DRAFTKINGS_TIMEOUT_SECONDS", "8"))
    total_budget = int(os.getenv("DRAFTKINGS_TOTAL_BUDGET_SECONDS", "20"))
    errors: list[str] = []
    started = time.perf_counter()

    for idx, (url, params) in enumerate(attempts[:max_attempts], start=1):
        if time.perf_counter() - started > total_budget:
            errors.append("budget_exceeded")
            break
        try:
            print(f"  [DraftKings] attempt {idx}/{min(len(attempts), max_attempts)}...")
            resp = requests.get(
                url, headers=DK_HEADERS, params=params, timeout=per_req_timeout
            )
            if resp.status_code != 200:
                errors.append(f"{resp.status_code}@{url}")
                continue
            payload = resp.json()
            lines = _parse_dk_lines(payload)
            if not lines:
                errors.append(f"empty@{url}")
                continue
            print(
                f"  [DraftKings] success via endpoint {idx}/"
                f"{min(len(attempts), max_attempts)}"
            )
            return _normalize_lines(lines, source="draftkings")
        except Exception as e:
            errors.append(f"err@{url}:{e}")
            continue

    # Keep message concise while still useful for debugging.
    short = "; ".join(errors[:4])
    if len(errors) > 4:
        short += f"; ... ({len(errors)} attempts)"
    raise DraftKingsError(f"DraftKings fetch failed: {short}")


def _run_provider(name: str, fn: Callable[[], list[dict]]) -> ProviderResult:
    try:
        lines = fn()
        print(f"  [{name}] fetched {len(lines)} lines")
        return ProviderResult(source=name, lines=lines)
    except Exception as e:  # keep pipeline resilient
        print(f"  [{name}] failed: {e}")
        return ProviderResult(source=name, lines=[], error=str(e))


def fetch_all_props_lines() -> tuple[list[dict], list[ProviderResult]]:
    """
    Returns merged lines + per-provider results.
    PrizePicks is required if present; DK is additive and optional.
    """
    providers: list[tuple[str, Callable[[], list[dict]]]] = [
        ("PrizePicks", fetch_prizepicks_lines),
    ]
    if os.getenv("ENABLE_DRAFTKINGS", "1").strip().lower() not in {"0", "false", "off", "no"}:
        providers.append(("DraftKings", fetch_draftkings_lines))

    results = [_run_provider(name, fn) for name, fn in providers]

    # Keep behavior predictable: if PrizePicks hard fails, preserve old exception semantics.
    pp_result = next((r for r in results if r.source == "PrizePicks"), None)
    if pp_result and pp_result.error:
        raise PrizePicksError(pp_result.error)

    merged: list[dict] = []
    seen: set[tuple] = set()
    for res in results:
        for row in res.lines:
            key = (
                row.get("source", ""),
                row.get("name_key"),
                row.get("stat"),
                row.get("line"),
                row.get("odds_type", "standard"),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)

    return merged, results

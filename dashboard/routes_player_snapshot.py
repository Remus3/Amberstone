"""GET /api/player-snapshot - DB-pure Home player-snapshot model (read-only).

Feeds the Home player-snapshot card (spec docs/superpowers/specs/
2026-07-04-player-snapshot-card-design.md). Assembles the normalized model
from core.player_gpi (self-relative GPI over a time window) plus a net-new
tag heuristic. No Riot API, no Claude. Rank/level/name are NOT here (they are
LCU-live, merged client-side from /api/home/summary); this route stays
rewind_history.db-pure and deterministic.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs, urlparse

from core import player_gpi

log = logging.getLogger(__name__)

# axis key -> (high word / strong, low word / weak). Spec 4.6.
_TAG_WORDS: dict[str, tuple[str, str]] = {
    "aggression": ("Aggressive", "Passive"),
    "farming": ("Strong Farmer", "Weak Farm"),
    "vision": ("Vision Control", "Visionless"),
    "objectives": ("Objective Focused", "Objective Shy"),
    "survival": ("Survivor", "Gank Prone"),
    "tempo": ("Snowballer", "Slow Starter"),
    "versatility": ("Generalist", "One-Trick"),
    "consistency": ("Consistent", "Streaky"),
}


def _derive_snapshot_tags(gpi: dict) -> list[dict]:
    """Three tags in [strong, neutral, weak] order (spec 4.6)."""
    strong_key = gpi.get("strongest_axis") or "aggression"
    weak_key = gpi.get("weakest_axis") or "farming"
    axes = {a["key"]: a for a in gpi.get("axes", [])}
    versat = (axes.get("versatility") or {}).get("score") or 0.0
    consist = (axes.get("consistency") or {}).get("score") or 0.0
    shape_key = "versatility" if versat >= consist else "consistency"
    shape_score = versat if shape_key == "versatility" else consist
    # High word when the shape axis reads at/above its midpoint, else low word;
    # either way it is a descriptor, never a weakness.
    shape_label = _TAG_WORDS[shape_key][0 if shape_score >= 50.0 else 1]
    return [
        {"label": _TAG_WORDS[strong_key][0], "tone": "strong"},
        {"label": shape_label, "tone": "neutral"},
        {"label": _TAG_WORDS[weak_key][1], "tone": "weak"},
    ]


_MODES = {"sr", "aram", "arena"}


def _band(value: float) -> str:
    if value >= 65.0:
        return "good"
    if value >= 35.0:
        return "ok"
    return "poor"


def _mean(*vals: float) -> float:
    return round(sum(vals) / len(vals), 1)


def _fmt_kda(gpi: dict) -> str:
    # kda_mean is surfaced by compute_gpi (Task 2); "-" only when absent.
    km = gpi.get("kda_mean")
    return f"{km:.2f}" if km is not None else "-"


def _top_champ(gpi: dict):
    tm = gpi.get("this_match") or {}
    return tm.get("champion_id")   # most-recent played; window-mode == self


def _build_snapshot_model(gpi: dict, mode: str, hours: int) -> dict:
    axes = {a["key"]: a for a in gpi.get("axes", [])}
    window_n = int(gpi.get("window_n") or 0)
    insufficient = gpi.get("confidence") == "insufficient"
    empty = insufficient or window_n == 0
    label = f"{mode.upper()} last {hours}h"

    def _score(k):
        return float((axes.get(k) or {}).get("score") or 0.0)

    if empty:
        return {
            "header": {"name": None, "rank_tier": None, "rank_lp": None,
                       "level": None, "streak": gpi.get("win_streak"),
                       "champion_id": None, "result": None},
            "dial": {"value": 0, "band": "poor", "label": label},
            "minis": [], "bars": [], "tags": [],
            "profile_ref": {"mode": mode, "window": f"{hours}h", "match_id": None},
            "confidence": "insufficient" if insufficient else "low",
            "sample_n": window_n, "empty": True,
        }

    overall = float(gpi.get("overall") or 0.0)
    wr = gpi.get("win_rate")
    kp = gpi.get("kp_pct")
    minis = [
        {"key": "kda", "value": _fmt_kda(gpi), "provenance": "source_truth"},
        {"key": "winrate",
         "value": f"{round(100.0 * wr)}%" if wr is not None else "-",
         "provenance": "source_truth"},
        {"key": "kp", "value": f"{round(kp)}%" if kp is not None else "-",
         "provenance": "inferred"},
    ]
    bars = [
        {"key": "income", "label": "INCOME",
         "score": _mean(_score("farming"), _score("tempo")), "provenance": "source_truth"},
        {"key": "combat", "label": "COMBAT",
         "score": _score("aggression"), "provenance": "source_truth"},
        {"key": "objectives", "label": "OBJECTIVES",
         "score": _score("objectives"), "provenance": "source_truth"},
        {"key": "vision", "label": "VISION",
         "score": _score("vision"), "provenance": "source_truth"},
    ]
    return {
        "header": {"name": None, "rank_tier": None, "rank_lp": None, "level": None,
                   "streak": gpi.get("win_streak"), "champion_id": _top_champ(gpi),
                   "result": None},
        "dial": {"value": round(overall), "band": _band(overall), "label": label},
        "minis": minis, "bars": bars, "tags": _derive_snapshot_tags(gpi),
        "profile_ref": {"mode": mode, "window": f"{hours}h", "match_id": None},
        "confidence": gpi.get("confidence") or "low",
        "sample_n": window_n, "empty": False,
    }


def _serve_player_snapshot(h) -> None:
    # Parsed before the try so the except fallback labels the degraded model
    # with the actually-requested mode, not a hardcoded "sr".
    mode = "sr"
    hours = 24
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        mode = (qs.get("mode") or ["sr"])[0].strip().lower()
        if mode not in _MODES:
            mode = "sr"
        try:
            hours = max(1, int((qs.get("hours") or ["24"])[0]))
        except (TypeError, ValueError):
            hours = 24
        import time
        since = int(time.time() * 1000) - hours * 3600_000
        gpi = player_gpi.compute_gpi(mode=mode, since_ts=since)
        model = _build_snapshot_model(gpi, mode, hours)
        h._send(200, json.dumps(model).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/player-snapshot: %s", exc)
        # Never leak raw error text; return a friendly empty model.
        empty = {"header": {}, "dial": {"value": 0, "band": "poor", "label": "-"},
                 "minis": [], "bars": [], "tags": [],
                 "profile_ref": {"mode": mode, "window": f"{hours}h", "match_id": None},
                 "confidence": "insufficient", "sample_n": 0, "empty": True}
        try:
            h._send(200, json.dumps(empty).encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _equals(p: str):
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/player-snapshot"), _serve_player_snapshot),
]

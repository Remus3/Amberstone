"""GET /api/player-snapshot - DB-pure Home player-snapshot model (read-only).

Feeds the Home player-snapshot card (spec docs/superpowers/specs/
2026-07-04-player-snapshot-card-design.md). Assembles the normalized model
from core.player_gpi (self-relative GPI over a time window) plus a net-new
tag heuristic. No Riot API, no Claude. Rank/level/name are NOT here (they are
LCU-live, merged client-side from /api/home/summary); this route stays
rewind_history.db-pure and deterministic.

Query parameters (both optional, both validated here - the trust boundary):
  mode   sr | aram | arena (case-insensitive); anything else reads as sr.
  hours  ASCII digits only, clamped to 1..MAX_HOURS; anything else reads as
         the 24 h default.

Never raises a computation error at the caller: a failure inside the model
build is logged WITH its traceback and answered 200 with the friendly
degraded model (``degraded: true``, DEGRADED_LABEL, never the raw error), so
the card keeps its reserved slot. A client that hangs up mid-response
(OSError on the write) is not a route failure: it is logged at debug and the
socket is not written to a second time.
"""
from __future__ import annotations

import json
import logging
import re
import time
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

# Spec 4.6: only the 6 RELATIVE skill axes may fill the strong (green) and
# weak (red) slots; the two shape axes are a playstyle descriptor (neutral
# slot only) - a one-trick reads low on versatility by choice, not weakness.
_SHAPE_AXES = ("versatility", "consistency")
_RELATIVE_TAG_AXES = frozenset(_TAG_WORDS) - frozenset(_SHAPE_AXES)

_MODES = {"sr", "aram", "arena"}

DEFAULT_HOURS = 24
# One year. Bounds the window a request can ask for, so a 40-digit ``hours``
# is not echoed back into the card label and the window start stays a sane
# epoch timestamp.
MAX_HOURS = 24 * 365
_HOURS_RE = re.compile(r"[0-9]+")

# The text the card shows when the model could not be built. Identical to
# the client's own failed-fetch fallback (web/js/main.js _renderHomeSnapshot)
# so the operator sees one message for both failure paths.
DEGRADED_LABEL = "coaching paused - retrying"


def _axis_scores(gpi: dict) -> dict[str, dict]:
    """``{axis key: axis dict}`` over the well-formed entries of gpi['axes']."""
    out: dict[str, dict] = {}
    for a in gpi.get("axes") or ():
        if isinstance(a, dict) and isinstance(a.get("key"), str):
            out[a["key"]] = a
    return out


def _derive_snapshot_tags(gpi: dict) -> list[dict]:
    """Tags in [strong, neutral, weak] order (spec 4.6).

    Normally three. A slot is OMITTED rather than invented when its axis is
    missing, unknown or a shape axis. A FLAT profile drops both the strong
    and the weak slot: compute_gpi's max() and min() name the same axis only
    when every relative axis ties, and that is the norm whenever the window
    holds the whole history (the mean midrank percentile of a full set is
    exactly 50), which used to tag the first axis "Aggressive" and "Passive"
    at once.
    """
    strong_key = gpi.get("strongest_axis")
    weak_key = gpi.get("weakest_axis")
    if strong_key == weak_key:
        strong_key = weak_key = None
    axes = _axis_scores(gpi)
    versat = (axes.get("versatility") or {}).get("score") or 0.0
    consist = (axes.get("consistency") or {}).get("score") or 0.0
    shape_key = "versatility" if versat >= consist else "consistency"
    shape_score = versat if shape_key == "versatility" else consist
    # High word when the shape axis reads at/above its midpoint, else low word;
    # either way it is a descriptor, never a weakness.
    shape_label = _TAG_WORDS[shape_key][0 if shape_score >= 50.0 else 1]
    tags: list[dict] = []
    if strong_key in _RELATIVE_TAG_AXES:
        tags.append({"label": _TAG_WORDS[strong_key][0], "tone": "strong"})
    tags.append({"label": shape_label, "tone": "neutral"})
    if weak_key in _RELATIVE_TAG_AXES:
        tags.append({"label": _TAG_WORDS[weak_key][1], "tone": "weak"})
    return tags


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


def _window_confidence(gpi: dict, window_n: int) -> str:
    """Confidence of the snapshot WINDOW.

    compute_gpi grades ``confidence`` on min(window, full history), which is
    "high" for any operator with 10+ games ever, even when the requested
    24 h window holds one game. The snapshot describes the window, so it is
    "high" only when compute_gpi says so AND the window itself holds at least
    MIN_GAMES games (spec section 6: a low sample renders the low hint).
    """
    conf = gpi.get("confidence") or "low"
    if conf == "high" and window_n < player_gpi.MIN_GAMES:
        return "low"
    return conf


def _build_snapshot_model(gpi: dict, mode: str, hours: int) -> dict:
    axes = _axis_scores(gpi)
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
        "confidence": _window_confidence(gpi, window_n),
        "sample_n": window_n, "empty": False,
    }


def _degraded_model(mode: str, hours: int) -> dict:
    """The friendly model served when the real one could not be built."""
    return {
        "header": {"name": None, "rank_tier": None, "rank_lp": None,
                   "level": None, "streak": None, "champion_id": None,
                   "result": None},
        "dial": {"value": 0, "band": "poor", "label": DEGRADED_LABEL},
        "minis": [], "bars": [], "tags": [],
        "profile_ref": {"mode": mode, "window": f"{hours}h", "match_id": None},
        "confidence": "insufficient", "sample_n": 0, "empty": True,
        "degraded": True,
    }


def _parse_query(path: str) -> tuple[str, int]:
    """Validated ``(mode, hours)`` from the request path. Never raises."""
    qs = parse_qs(urlparse(path).query or "")
    mode = ((qs.get("mode") or ["sr"])[0] or "").strip().lower()
    if mode not in _MODES:
        mode = "sr"
    raw = ((qs.get("hours") or [""])[0] or "").strip()
    # ASCII digits only: int() would also take "1_2", "+5" and non-ASCII
    # digits, none of which the card ever sends. A digit run longer than
    # MAX_HOURS can be is clamped without int() (which refuses 4300+ digits).
    if _HOURS_RE.fullmatch(raw):
        hours = MAX_HOURS if len(raw) > 9 else min(MAX_HOURS, max(1, int(raw)))
    else:
        hours = DEFAULT_HOURS
    return mode, hours


def _send_json(h, payload: dict) -> None:
    """Write ``payload``; a client that already hung up is not an error."""
    try:
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except OSError as exc:
        log.debug("api/player-snapshot: client gone before the reply: %s", exc)


def _serve_player_snapshot(h) -> None:
    # Defaults first, so the degraded model below is labelled with the
    # requested mode/window whenever the query itself parsed.
    mode, hours = "sr", DEFAULT_HOURS
    try:
        mode, hours = _parse_query(h.path)
        since = int(time.time() * 1000) - hours * 3_600_000
        gpi = player_gpi.compute_gpi(mode=mode, since_ts=since)
        model = _build_snapshot_model(gpi, mode, hours)
    except Exception:  # route trust boundary; logged with traceback
        log.warning("api/player-snapshot: model build failed; serving the "
                    "degraded model", exc_info=True)
        model = _degraded_model(mode, hours)
    _send_json(h, model)


def _equals(p: str):
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/player-snapshot"), _serve_player_snapshot),
]

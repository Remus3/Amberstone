# arch: cc_conditional pressure panel backend | section=dashboard | frozen=no
"""GET /api/cc-conditional-pressure - ally vs enemy CONDITIONAL CC balance.

FIRST DASHBOARD UI CONSUMER of ``cc_conditional`` and the 5th overall
consumer of the ``cc_conditional`` ecosystem. Prior consumers (engine
math chain) shipped at ENGINE 1.38.0 + 1.39.0:

  1. cc_pressure (DIRECT, ENGINE 1.38.0, item 142 Slice A):
     ``compute_cc_pressure(champion, mode, include_conditional=False)``
     gains the opt-in kwarg. The CcPressureResult dataclass exposes
     ``conditional_cc_seconds`` (post-tenacity probability-weighted
     contribution) + ``conditional_entries`` (canonical Q-W-E-R tuple).
  2. compute_ehp (INDIRECT, ENGINE 1.39.0, item 143 Slice A):
     threads ``include_conditional`` through to per-enemy
     ``compute_cc_pressure`` calls so the EHP scorer's
     ``cc_blended_ehp`` field can reflect conditional CC.
  3. compute_hybrid (INDIRECT, ENGINE 1.39.0, item 143 Slice B):
     threads ``include_conditional`` to ALL 3 internal ``compute_ehp``
     call sites via the ``**_ehp_kwargs`` gating pattern.

This route is the FIRST DASHBOARD UI surface for the conditional CC
axis. It surfaces a champ-select chip comparing ally vs enemy
conditional CC seconds. The math is intentionally SYMMETRIC mirror of
``routes_cc_blended_ehp_threat.py`` (item 140 Slice A) but reads the
conditional contribution directly from ``CcPressureResult`` rather
than going through the EHP scorer - the conditional CC axis is a
SEPARATE signal from the cc_blended_ehp axis (the EHP axis blends
unconditional CC into a single number; this chip surfaces the
probability-weighted CONDITIONAL contribution standalone).

Request shape:
  GET /api/cc-conditional-pressure?ally=<champ,champ,...>
                                  &enemy=<champ,champ,...>
                                  [&mode=ARAM]

  ally   : comma-separated canonical DDragon ids ("Brand", "Mordekaiser",
           "TwistedFate"). Blank entries are silently skipped before
           handing to compute_cc_pressure (which itself fail-softs on
           unknown champions, mirrors per-spell registry contract).
  enemy  : symmetric.
  mode   : SR | ARAM | KIWI | ARENA | BRAWL. Defaults ARAM (the chip
           mounts during champ-select and ARAM/Mayhem is where
           aramTenacity actually shifts the post-tenacity conditional
           contribution).

Response shape:
  {
    "ok":                       true,
    "mode":                     "ARAM",
    "ally_conditional_cc_s":    <float>,  # avg per ally
    "enemy_conditional_cc_s":   <float>,  # avg per enemy
    "ratio":                    <ally/enemy float>,
    "tier":                     "good" | "warn" | "bad",
    "ally_total_cc_seconds":    <float>,  # summed across ally roster
    "enemy_total_cc_seconds":   <float>,  # summed across enemy roster
    "elapsed_ms":               <int>,
    "cached":                   <bool>
  }

Note: ``ally_conditional_cc_s`` + ``enemy_conditional_cc_s`` are
averages (sum / count) to mirror routes_cc_blended_ehp_threat. The
``ally_total_cc_seconds`` + ``enemy_total_cc_seconds`` fields carry
the summed values for tier-decision transparency.

Failure modes:
  - 400  ally OR enemy param literally missing (parse_qs returns no
         key for it).
  - 200  ok=false reason="no_champions" when BOTH sides resolve to
         zero usable champions (blanks / empty inputs).
  - 200  ok=true ratio=1.0 tier="warn" when total_cc_seconds is 0.0
         on both sides (no registered conditional CC threat). The
         per-side averages are still 0.0 + surfaced for transparency.
  - 503  cc_pressure import fails (DS engine unreachable).

SYMMETRIC CONSTRUCTION (load-bearing semantic, mirrors item 140):
  - The ALLY side averages conditional_cc_seconds across each ALLY
    champion (enemy conditional CC erodes ally fight effectiveness).
  - The ENEMY side averages conditional_cc_seconds across each ENEMY
    champion (ally conditional CC erodes enemy fight effectiveness).
  - Ratio is ally_avg / enemy_avg.
  - tier=good when ratio >= 1.05 - ENEMY carries MORE conditional CC
    threat to land on us (follow-up window for us; their CC will
    stick longer than ours conditionally). Wait - that's backwards
    for a defensive read.
  - Re-read: the chip surfaces who has MORE conditional CC THREAT.
    The convention here is the SAME as routes_cc_blended_ehp_threat:
    HIGHER ally number = GOOD for ally (we weather their CC better).
    For routes_cc_blended_ehp_threat that meant: ally has higher
    cc_blended_ehp = ally weathers better.
  - For this chip: a HIGH ally_conditional_cc_s means ally's CONDITIONAL
    CC on enemies is high; we're feeding the enemy roster's CC totals
    to ally side, so ratio>1 means OUR (ally) CC threat exceeds
    THEIRS, which is GOOD for us. The chip's framing matches.

Tier bands:
  ratio >= 1.05      -> "good"  (our conditional CC threat exceeds theirs)
  0.95 <= ratio < 1.05 -> "warn"  (even balance)
  ratio < 0.95       -> "bad"   (their conditional CC threat exceeds ours)

5-min TTL in-process cache keyed on (sorted_ally_tuple,
sorted_enemy_tuple, mode). Mode-aware so ARAM and SR don't share
cache slots. Mirrors ``routes_cc_blended_ehp_threat`` discipline.

Don't-redo:
  * SYMMETRIC CONSTRUCTION is load-bearing. ALLY side feeds the
    ENEMY roster as the contributing source set, vice versa. Do NOT
    collapse to same-side feeds (would invert the threat-balance
    signal per the item 140 don't-redo).
  * Default mode is ARAM (chip mounts during champ-select where
    ARAM/Mayhem is the most common mode whose tenacity shifts the
    conditional CC contribution). SR + Arena still compute cleanly
    at identity tenacity.
  * Tier bands 1.05 / 0.95 mirror routes_cc_blended_ehp_threat
    exactly. Do NOT vary without retuning the panel tests AND
    keeping the two chips visually coherent.
  * cc_conditional ecosystem now has 5 consumers in production:
    cc_pressure direct + compute_ehp indirect + compute_hybrid
    indirect + (parallel slice) coach prompt + THIS dashboard UI.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors routes_cc_blended_ehp_threat exactly.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

# Tier band thresholds. Mirrors routes_cc_blended_ehp_threat exactly.
# See module docstring "Tier bands". Do not change without updating
# the test that pins these values.
_TIER_GOOD_THRESHOLD = 1.05
_TIER_BAD_THRESHOLD = 0.95

# Mode whitelist. The cc-pressure aggregator is mode-agnostic but
# aramTenacity only applies on ARAM-family modes. The dashboard chip
# defaults to ARAM because that's where the signal actually lives;
# SR / Arena / Brawl still compute cleanly (identity tenacity).
_DEFAULT_MODE = "ARAM"
_VALID_MODES = frozenset(("SR", "ARAM", "KIWI", "ARENA", "BRAWL"))


def _parse_champ_list(raw: str) -> list[str]:
    """Split a comma-separated DDragon-id list, strip blanks.

    Unknown ids (those not in the cc_pressure / cc_conditional
    registries) are NOT filtered here - compute_cc_pressure fail-softs
    on them per its contract (returns 0.0 conditional_cc_seconds). We
    only drop literal blanks here so "Brand,,Mordekaiser" doesn't
    carry a phantom entry into the average denominator.
    """
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        s = part.strip()
        if s:
            out.append(s)
    return out


def _tier_for(ratio: float) -> str:
    if ratio >= _TIER_GOOD_THRESHOLD:
        return "good"
    if ratio < _TIER_BAD_THRESHOLD:
        return "bad"
    return "warn"


def _cache_key(ally: list[str], enemy: list[str], mode: str) -> tuple:
    return (
        tuple(sorted(ally)),
        tuple(sorted(enemy)),
        mode,
    )


def _side_conditional(roster: list[str], mode: str) -> tuple[float, float, int]:
    """Compute (avg, total, scored_count) of conditional_cc_seconds for one side.

    Each champion in ``roster`` is scored via
    ``compute_cc_pressure(champion, mode, include_conditional=True)``.
    Unknown / blank entries silently contribute 0.0 (mirrors the
    cc_pressure fail-soft contract; the empty result returns
    ``conditional_cc_seconds=0.0``).

    Returns (avg, total, scored_count). When roster is empty, returns
    (0.0, 0.0, 0). When ALL entries score 0 (no registered conditional
    CC on any champ), the result is still (0.0, 0.0, len(roster)) - the
    chip rendering layer interprets total=0.0 on both sides as warn.
    """
    if not roster:
        return (0.0, 0.0, 0)
    from agents.daemon_slayer.cc_pressure import compute_cc_pressure

    values: list[float] = []
    for champ in roster:
        try:
            r = compute_cc_pressure(champ, mode, include_conditional=True)
        except Exception as exc:
            # Defensive belt-and-braces - cc_pressure already fail-softs
            # on unknown champions but a snapshot load failure would
            # raise; log + skip silently per the route's contract.
            log.debug(
                "cc-conditional-pressure: compute_cc_pressure(%s, %s) "
                "failed: %s", champ, mode, exc,
            )
            continue
        values.append(float(getattr(r, "conditional_cc_seconds", 0.0) or 0.0))

    if not values:
        return (0.0, 0.0, 0)
    total = sum(values)
    avg = total / len(values)
    return (avg, total, len(values))


def _compute(allies: list[str], enemies: list[str], mode: str) -> dict:
    """Build the response payload from scratch (no cache).

    The math (see module docstring): both sides score the
    ``conditional_cc_seconds`` field via
    ``compute_cc_pressure(include_conditional=True)``. Ally + enemy
    sides are computed independently; the chip then ratios + tiers.
    """
    ally_avg, ally_total, ally_scored = _side_conditional(allies, mode)
    enemy_avg, enemy_total, enemy_scored = _side_conditional(enemies, mode)

    if ally_scored == 0 and enemy_scored == 0:
        return {
            "ok":     False,
            "mode":   mode,
            "reason": "no_champions",
        }

    # When BOTH sides have zero registered conditional CC, the ratio
    # is not informative (no conditional CC threat on the table); the
    # chip should render in the neutral warn tier. This is the symmetric
    # identity contract pinned by MathTests::test_zero_cc_both_sides...
    if ally_total == 0.0 and enemy_total == 0.0:
        ratio = 1.0
        tier = "warn"
    elif enemy_avg == 0.0:
        # Ally has conditional CC, enemy has none. Ally CC threat
        # exceeds enemy's by definition; surface a saturated good
        # tier with a sentinel high ratio (clamp at a large finite
        # number rather than inf so JSON serialises cleanly).
        ratio = float("inf") if ally_avg > 0.0 else 1.0
        # Clamp inf to a large finite value for JSON safety (chip
        # renders the ratio as-is; an inf would NaN in JS).
        if ratio == float("inf"):
            ratio = 1e9
        tier = "good"
    elif ally_avg == 0.0:
        # Enemy has conditional CC, ally has none. Enemy CC threat
        # exceeds ours.
        ratio = 0.0
        tier = "bad"
    else:
        ratio = ally_avg / enemy_avg
        tier = _tier_for(ratio)

    return {
        "ok":                      True,
        "mode":                    mode,
        "ally_conditional_cc_s":   ally_avg,
        "enemy_conditional_cc_s":  enemy_avg,
        "ratio":                   ratio,
        "tier":                    tier,
        "ally_total_cc_seconds":   ally_total,
        "enemy_total_cc_seconds":  enemy_total,
    }


def _serve_cc_conditional_pressure(h) -> None:
    """GET /api/cc-conditional-pressure handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        # keep_blank_values=True so we can distinguish "param literally
        # absent" (400) from "param present but empty" (200 ok=false
        # reason=no_champions). Default parse_qs collapses empty-valued
        # keys which would conflate the two cases.
        if "ally" not in qs or "enemy" not in qs:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "ally and enemy params required",
            }).encode("utf-8"), "application/json")
            return

        ally_raw = (qs.get("ally") or [""])[0].strip()
        enemy_raw = (qs.get("enemy") or [""])[0].strip()
        mode_raw = (qs.get("mode") or [_DEFAULT_MODE])[0].strip()
        mode = mode_raw.upper() if mode_raw else _DEFAULT_MODE
        if mode not in _VALID_MODES:
            mode = _DEFAULT_MODE

        ally_ids = _parse_champ_list(ally_raw)
        enemy_ids = _parse_champ_list(enemy_raw)

        # Both sides empty after parse -> no usable input.
        if not ally_ids and not enemy_ids:
            payload = {
                "ok":         False,
                "mode":       mode,
                "reason":     "no_champions",
                "elapsed_ms": int((time.time() - t0) * 1000),
                "cached":     False,
            }
            h._send(200, json.dumps(payload).encode("utf-8"),
                    "application/json")
            return

        key = _cache_key(ally_ids, enemy_ids, mode)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        try:
            payload = _compute(ally_ids, enemy_ids, mode)
        except ImportError as exc:
            log.warning("api/cc-conditional-pressure import: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:
            log.warning("api/cc-conditional-pressure compute: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine compute failed",
            }).encode("utf-8"), "application/json")
            return

        if payload.get("ok"):
            with _CACHE_LOCK:
                cacheable = dict(payload)
                _CACHE[key] = (now, cacheable)

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        h._send(200, json.dumps(payload).encode("utf-8"),
                "application/json")

    except Exception as exc:
        log.warning("api/cc-conditional-pressure: %s", exc)
        try:
            h._send(500, json.dumps({
                "ok": False, "error": str(exc)[:200],
            }).encode("utf-8"), "application/json")
        except Exception:
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/cc-conditional-pressure"), _serve_cc_conditional_pressure),
]

POST_ROUTES: list = []

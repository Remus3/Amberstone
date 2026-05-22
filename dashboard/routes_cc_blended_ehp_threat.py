# arch: cc_blended_ehp threat panel backend | section=dashboard | frozen=no
"""GET /api/cc-blended-ehp-threat - ally vs enemy CC-blended EHP balance.

FIRST DASHBOARD UI CONSUMER of ``cc_blended_ehp`` (closes item 139
carry (a)). The field had 3 prior consumers when this slice shipped:

  1. Engine math (item 137 commit 99164e8):
     ``agents.daemon_slayer.ehp.compute_ehp(enemy_champions=())``
     returns ``EhpResult.cc_blended_ehp`` - the blended_ehp value
     after a multiplicative CC-discount derived from
     ``compute_cc_pressure`` summed across the enemy roster.
  2. Coach prompt (item 138 Slice A commit 738c005):
     ``core.cc_blended_ehp_context.cc_blended_ehp_impact_line()``
     renders a single prompt line summarising the same number.
  3. DS scorer (item 139 Slice A commit 0523511):
     ``agents.daemon_slayer.hybrid.compute_hybrid(enemy_champions=())``
     swaps ``beta * blended_ehp`` for ``beta * cc_blended_ehp``
     inside the hybrid_score scalar.

This route is the FIRST DASHBOARD UI surface - a small champ-select
threat-tag chip that compares ally-team vs enemy-team cc_blended_ehp
ratios. For ALLY side, enemy CC erodes ally EHP, so we compute
``cc_blended_ehp`` for each ally with the ENEMY roster fed in as
``enemy_champions``. Symmetrically, for ENEMY side we feed the ALLY
roster (their CC erodes enemy EHP). The ratio
``ally_avg / enemy_avg`` is the load-bearing comparison: > 1.05
means ally CC weathers better (good); < 0.95 means enemy CC erodes
us more (bad); in between is warn (even).

Request shape:
  GET /api/cc-blended-ehp-threat?ally=<champ,champ,...>
                                &enemy=<champ,champ,...>
                                [&mode=ARAM]

  ally   : comma-separated canonical DDragon ids ("Annie", "Garen",
           "MonkeyKing"). Blank entries and unknown champions are
           silently skipped (mirrors compute_ehp's fail-soft
           contract on enemy_champions and compute_cc_pressure).
  enemy  : symmetric.
  mode   : SR | ARAM | KIWI | ARENA | BRAWL. Defaults ARAM (the
           panel surfaces during champ-select and ARAM/Mayhem are
           the modes where aramTenacity actually shifts the CC
           pressure value - SR is identity).

Response shape:
  {
    "ok":                       true,
    "mode":                     "ARAM",
    "ally_avg_cc_blended_ehp":  <float>,
    "enemy_avg_cc_blended_ehp": <float>,
    "ratio":                    <ally/enemy float>,
    "tier":                     "good" | "warn" | "bad",
    "ally_total_cc_seconds":    <float>,   # operator CC summed
    "enemy_total_cc_seconds":   <float>,
    "elapsed_ms":               <int>,
    "cached":                   <bool>
  }

Failure modes:
  - 400  ally OR enemy param literally missing (parse_qs returns
         no key)
  - 200  ok=false reason="no_champions" when BOTH sides resolve
         to zero usable champions (blanks / unknowns silently
         skipped on each side; empty inputs return early)
  - 200  ok=true ratio=1.0 tier="warn" when total_cc_seconds is
         0.0 on both sides (no registered CC threat - the chip
         shows even/no-threat). The averages are still computed
         and surfaced for caller transparency.
  - 503  DS data snapshot fails to import / load.

Tier bands:
  ratio >= 1.05      -> "good"  (ally CC weathers better)
  0.95 <= ratio < 1.05 -> "warn"  (even balance)
  ratio < 0.95       -> "bad"   (enemy CC erodes us more)

5-min TTL in-process cache keyed on (sorted_ally_tuple,
sorted_enemy_tuple, mode). Mirrors routes_post_game_rubric +
routes_ban_suggest 5-min TTL discipline.

Don't-redo:
  * Default mode is ARAM because the dashboard chip mounts during
    champ-select where ARAM/Mayhem are the modes whose tenacity
    actually moves the needle; SR can still be requested via
    explicit mode=SR.
  * The route deliberately uses canonical DDragon ids in the
    query string (not numeric DDragon keys). This matches the
    cc_pressure registry shape exactly and avoids a
    numeric-id->slug resolution step on the hot path. The frontend
    chip resolves ``CHAMPS.byId[numeric_id]`` once at render time.
  * Symmetric construction is the contract: ally side fed enemy
    roster in enemy_champions; enemy side fed ally roster. Do NOT
    feed the same-side roster (would compute self-vs-self which
    is meaningless for the comparison).
  * tier bands 1.05 / 0.95 are operator-tunable midpoints (sit
    next to the engine's _CC_EFFECTIVENESS_FACTOR=0.5 +
    _FIGHT_WINDOW_S=6.0 calibration constants). Do NOT change
    without retuning the panel tests too.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors routes_post_game_rubric / routes_ban_suggest.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

# Lazy DS snapshot (mirrors routes_spike_curve._load_snapshot pattern).
_SNAPSHOT = None
_SNAPSHOT_LOCK = threading.Lock()

# Tier band thresholds. See module docstring "Tier bands". Do not change
# without updating the test that pins these.
_TIER_GOOD_THRESHOLD = 1.05
_TIER_BAD_THRESHOLD = 0.95

# Default per-champ level + items for the dashboard chip. Champ-select
# is pre-game, so we score at a mid-game proxy (level 11, 0 items) -
# the comparison is roster-vs-roster, not full-build vs full-build.
_DEFAULT_LEVEL = 11

# Mode whitelist. The cc-pressure aggregator is mode-agnostic but
# aramTenacity only applies on ARAM-family modes. The dashboard chip
# defaults to ARAM because that's where the signal actually lives;
# SR / Arena / Brawl still compute cleanly (identity tenacity).
_DEFAULT_MODE = "ARAM"
_VALID_MODES = frozenset(("SR", "ARAM", "KIWI", "ARENA", "BRAWL"))


def _load_snapshot():
    """Lazy DataSnapshot load mirroring routes_spike_curve."""
    global _SNAPSHOT
    if _SNAPSHOT is not None:
        return _SNAPSHOT
    with _SNAPSHOT_LOCK:
        if _SNAPSHOT is not None:
            return _SNAPSHOT
        from agents.daemon_slayer.data_loader import DataSnapshot
        _SNAPSHOT = DataSnapshot.load()
        return _SNAPSHOT


def _parse_champ_list(raw: str) -> list[str]:
    """Split a comma-separated DDragon-id list, strip blanks.

    Unknown ids (those not in the snapshot or not in the CC pressure
    registry) are NOT filtered here - the underlying compute_ehp +
    compute_cc_pressure silently skip them per their fail-soft
    contracts. We only drop literal blanks here so an "Annie,,Garen"
    input doesn't carry a phantom entry.
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


def _compute_side_avg(snapshot, allies: list[str], enemies: list[str],
                      mode: str) -> tuple[float, float, int]:
    """Compute the average cc_blended_ehp + total CC seconds for one side.

    Each champ in ``allies`` is scored via compute_ehp with ``enemies``
    threaded into enemy_champions. The summed enemy_cc_pressure_s is
    identical across all allies on the same side (compute_cc_pressure
    only depends on enemies + mode) - we still pull it from the first
    successful result for transparency.

    Returns (avg_cc_blended_ehp, total_cc_seconds, scored_count).
    Returns (0.0, 0.0, 0) when zero allies score successfully.
    """
    if not allies:
        return (0.0, 0.0, 0)
    from agents.daemon_slayer.ehp import compute_ehp

    values: list[float] = []
    total_cc_s = 0.0
    seen_cc = False
    for champ in allies:
        try:
            r = compute_ehp(
                snapshot,
                champ,
                level=_DEFAULT_LEVEL,
                item_ids=(),
                mode=mode,
                enemy_ad_share=0.5,
                enemy_ap_share=0.5,
                enemy_champions=enemies,
            )
        except Exception as exc:
            # Unknown champion / registry miss - skip silently
            # (compute_ehp's fail-soft contract is the source of
            # truth; we mirror it).
            log.debug(
                "cc-blended-ehp-threat: compute_ehp(%s, %s) failed: %s",
                champ, mode, exc,
            )
            continue
        values.append(float(getattr(r, "cc_blended_ehp", 0.0) or 0.0))
        if not seen_cc:
            total_cc_s = float(getattr(r, "enemy_cc_pressure_s", 0.0) or 0.0)
            seen_cc = True

    if not values:
        return (0.0, 0.0, 0)
    avg = sum(values) / len(values)
    return (avg, total_cc_s, len(values))


def _compute(allies: list[str], enemies: list[str], mode: str) -> dict:
    """Build the response payload from scratch (no cache).

    The math (see module docstring):
      ALLY side  - cc_blended_ehp averaged across allies, with the
                   ENEMY roster fed as enemy_champions (their CC
                   erodes our EHP).
      ENEMY side - mirror: cc_blended_ehp averaged across enemies,
                   with the ALLY roster fed as enemy_champions.

    The ratio + tier follow.
    """
    snapshot = _load_snapshot()

    ally_avg, ally_total_cc, ally_scored = _compute_side_avg(
        snapshot, allies, enemies, mode,
    )
    enemy_avg, enemy_total_cc, enemy_scored = _compute_side_avg(
        snapshot, enemies, allies, mode,
    )

    if ally_scored == 0 and enemy_scored == 0:
        return {
            "ok":        False,
            "mode":      mode,
            "reason":    "no_champions",
        }

    # Tier + ratio. If either side has no scored champs, the ratio is
    # not meaningful - fall back to a neutral tier so the panel renders
    # cleanly without lying about balance.
    if ally_avg <= 0.0 or enemy_avg <= 0.0:
        ratio = 1.0
        tier = "warn"
    elif ally_total_cc == 0.0 and enemy_total_cc == 0.0:
        # No registered CC on either side - cc_blended_ehp == blended_ehp
        # by the identity contract; the ratio still reflects raw EHP
        # which is informative, but we clamp the tier to "warn" because
        # the chip's whole point is CC threat balance.
        ratio = ally_avg / enemy_avg if enemy_avg > 0.0 else 1.0
        tier = "warn"
    else:
        ratio = ally_avg / enemy_avg
        tier = _tier_for(ratio)

    return {
        "ok":                       True,
        "mode":                     mode,
        "ally_avg_cc_blended_ehp":  ally_avg,
        "enemy_avg_cc_blended_ehp": enemy_avg,
        "ratio":                    ratio,
        "tier":                     tier,
        "ally_total_cc_seconds":    ally_total_cc,
        "enemy_total_cc_seconds":   enemy_total_cc,
    }


def _serve_cc_blended_ehp_threat(h) -> None:
    """GET /api/cc-blended-ehp-threat handler."""
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
            log.warning("api/cc-blended-ehp-threat compute import: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:
            log.warning("api/cc-blended-ehp-threat compute: %s", exc)
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
        log.warning("api/cc-blended-ehp-threat: %s", exc)
        try:
            h._send(500, json.dumps({
                "ok": False, "error": str(exc)[:200],
            }).encode("utf-8"), "application/json")
        except Exception:
            pass


def _reset_caches() -> None:
    """Test-only: clear response + snapshot caches."""
    global _SNAPSHOT
    with _CACHE_LOCK:
        _CACHE.clear()
    with _SNAPSHOT_LOCK:
        _SNAPSHOT = None


GET_ROUTES = [
    (equals("/api/cc-blended-ehp-threat"), _serve_cc_blended_ehp_threat),
]

POST_ROUTES: list = []

# arch: ds-shape SHAPED-EMPHASIS preview backend | section=dashboard | frozen=no
"""GET /api/ds-shape - shaped archetype-emphasis preview (OQ14).

Read-only, pure. Threads the ALREADY-SHIPPED primitive
``core.shaper.apply_shaper`` over a per-champion baseline emphasis triple
(damage / survivability / utility) to show how the three operator knobs
re-weight the mix. NO engine math, NO ENGINE_VERSION bump, NO DS engine
:8860 call, NO DataSnapshot - just the shaper transform on a weight dict.

The BASELINE triple comes from the REAL per-champion archetype table
``agents/daemon_slayer/archetype_weights.json`` (the same alpha/beta pairs
the bruiser hybrid scorer uses). ``[alpha, beta]`` there is
``[DPS/damage weight, EHP/survivability weight]``. We map it to::

    baseline = {"damage": alpha, "survivability": beta, "utility": 0.0}

The literal keys ``"damage"`` / ``"survivability"`` / ``"utility"`` are
mandatory: ``apply_shaper`` classifies axes by substring match on the dict
keys, so a non-literal key would be passed through unchanged.

The SHAPED triple is::

    shaped = apply_shaper(baseline, ShaperState(dmg, surv, util))

with each knob an int clamped to [-2, +2]. ``apply_shaper`` renormalizes
so the shaped fractions sum to ~1.0.

Request shape:
  GET /api/ds-shape?champion=<id>[&damage=<int>][&survivability=<int>]
      [&utility=<int>]

  champion       : canonical DDragon id ("Darius", "Jinx"). REQUIRED; the
                   client pre-resolves display -> id. Blank -> 400.
  damage         : int knob, clamped [-2, 2]. Blank / non-numeric -> 0.
  survivability  : int knob, clamped [-2, 2]. Blank / non-numeric -> 0.
  utility        : int knob, clamped [-2, 2]. Blank / non-numeric -> 0.

Response 200 JSON:
  {
    "ok":              true,
    "champion":        "Darius",
    "archetype_source":"champion" | "default",
    "knobs":           {"damage": 1, "survivability": 0, "utility": 0},
    "baseline":        {"damage": 0.65, "survivability": 0.35, "utility": 0.0},
    "shaped":          {"damage": <f>, "survivability": <f>, "utility": <f>},
    "baseline_pct":    {"damage": 65, "survivability": 35, "utility": 0},
    "shaped_pct":      {"damage": <int>, "survivability": <int>, "utility": <int>},
    "elapsed_ms":      <int>
  }
  ``*_pct`` = round(fraction * 100) as int (fractions already sum ~1.0).
  ``archetype_source`` = "champion" if the id is in the table else "default".

Failure modes:
  - 400  champion param literally missing OR present-but-blank.
  - 500  graceful ``{ok:false,"error":str(exc)[:200]}`` on any unexpected
         exception (never surfaces a raw traceback to the UI).
"""
from __future__ import annotations

import json
import logging
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# Knob clamp bounds. core.shaper exports NUDGE_STEP/WEIGHT_MIN/WEIGHT_MAX
# only (not the knob int bounds), so the [-2, 2] range is pinned here to
# match ShaperState's own KNOB_MIN/KNOB_MAX construction guard.
_KNOB_MIN = -2
_KNOB_MAX = 2


def _parse_knob(raw: str) -> int:
    """Parse a knob to int, clamp [-2, 2]; blank / non-numeric -> 0."""
    if raw is None:
        return 0
    s = raw.strip()
    if not s:
        return 0
    try:
        v = int(float(s))
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(_KNOB_MIN, min(_KNOB_MAX, v))


def _to_pct(triple: dict) -> dict:
    """round(fraction * 100) as int per axis (fractions sum ~1.0)."""
    return {k: int(round(float(v) * 100)) for k, v in triple.items()}


def _serve_ds_shape(h) -> None:
    """GET /api/ds-shape handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        champion = (qs.get("champion") or [""])[0].strip()
        if not champion:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "champion param required",
            }).encode("utf-8"), "application/json")
            return

        knob_damage = _parse_knob((qs.get("damage") or [""])[0])
        knob_surv = _parse_knob((qs.get("survivability") or [""])[0])
        knob_util = _parse_knob((qs.get("utility") or [""])[0])

        from agents.daemon_slayer.hybrid import _load_archetype_weights
        from core.shaper import ShaperState, apply_shaper

        table = _load_archetype_weights()
        champions = table.get("champions") or {}
        default_pair = table.get("default") or [0.5, 0.5]
        if champion in champions:
            pair = champions[champion]
            archetype_source = "champion"
        else:
            pair = default_pair
            archetype_source = "default"
        alpha = float(pair[0])
        beta = float(pair[1])

        # Literal axis keys are REQUIRED - apply_shaper classifies by substring.
        baseline = {"damage": alpha, "survivability": beta, "utility": 0.0}
        shaped = apply_shaper(
            baseline,
            ShaperState(
                damage_nudge=knob_damage,
                survivability_nudge=knob_surv,
                utility_nudge=knob_util,
            ),
        )

        payload = {
            "ok":               True,
            "champion":         champion,
            "archetype_source": archetype_source,
            "knobs": {
                "damage":        knob_damage,
                "survivability": knob_surv,
                "utility":       knob_util,
            },
            "baseline":     {k: float(v) for k, v in baseline.items()},
            "shaped":       {k: float(v) for k, v in shaped.items()},
            "baseline_pct": _to_pct(baseline),
            "shaped_pct":   _to_pct(shaped),
            "elapsed_ms":   int((time.time() - t0) * 1000),
        }
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")

    except Exception as exc:  # noqa: BLE001
        log.warning("api/ds-shape: %s", exc)
        try:
            h._send(500, json.dumps({
                "ok": False, "error": str(exc)[:200],
            }).encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES = [
    (equals("/api/ds-shape"), _serve_ds_shape),
]

POST_ROUTES: list = []

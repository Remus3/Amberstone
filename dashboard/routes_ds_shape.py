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

    baseline = {"damage": a, "survivability": b, "utility": 0.0}

where ``(a, b)`` is the pair normalized to sum 1.0 (every shipped row
already does). A row that is not two finite, non-negative, non-bool
numbers with a positive sum is MALFORMED: it is logged and the table's
default pair is used instead (``archetype_source`` = "default"); a
malformed default falls back to ``[0.5, 0.5]``. A malformed row never
turns into a 500 and never emits a bare NaN token (RM-1447).

The literal keys ``"damage"`` / ``"survivability"`` / ``"utility"`` are
mandatory: ``apply_shaper`` classifies axes by substring match on the dict
keys, so a non-literal key would be passed through unchanged.

The SHAPED triple is ``apply_shaper(baseline, ShaperState(dmg, surv,
util))`` with each knob an int clamped to the shaper's own
``[KNOB_MIN, KNOB_MAX]`` = [-2, +2]; ``apply_shaper`` renormalizes so the
shaped fractions sum to ~1.0. The route adds ONE rule on top: no axis
ever moves against its own knob - a negative knob never ends its axis
ABOVE baseline and a positive one never BELOW it. ``apply_shaper`` alone
breaks that: it floors a nudged axis at ``WEIGHT_MIN`` (0.05), so a
negative utility knob lifted utility 0 -> 5 pct (utility is always 0.0
here), and its renormalization can push an axis the wrong way when
several knobs move. Such an axis is HELD at its baseline and the others
are re-shaped into the remaining share (``_shape``; RM-1447). An axis
whose knob is 0 floats with the renormalization.

Request shape:
  GET /api/ds-shape?champion=<name>[&damage=<int>][&survivability=<int>]
      [&utility=<int>]

  champion       : canonical DDragon id ("Darius", "LeeSin") OR a Live
                   Client display name ("Lee Sin", "Wukong") - the live
                   caller (web/js/panels/ds_shaper.js) sends the display
                   name verbatim, so the route resolves it through
                   ``core.archetype_picks.canonical_champion_id`` (an
                   unknown name passes through unchanged). REQUIRED.
                   Blank -> 400; longer than ``_MAX_CHAMPION_LEN`` or
                   carrying a non-printable character -> 400.
  damage         : int knob, clamped [-2, 2]. Blank / non-numeric -> 0.
  survivability  : int knob, clamped [-2, 2]. Blank / non-numeric -> 0.
  utility        : int knob, clamped [-2, 2]. Blank / non-numeric -> 0.

Response 200 JSON:
  {
    "ok":              true,
    "champion":        "Darius",     # the RESOLVED id
    "archetype_source":"champion" | "default",
    "knobs":           {"damage": 1, "survivability": 0, "utility": 0},
    "baseline":        {"damage": 0.65, "survivability": 0.35, "utility": 0.0},
    "shaped":          {"damage": <f>, "survivability": <f>, "utility": <f>},
    "baseline_pct":    {"damage": 65, "survivability": 35, "utility": 0},
    "shaped_pct":      {"damage": <int>, "survivability": <int>, "utility": <int>},
    "elapsed_ms":      <int>
  }
  ``*_pct`` = round(fraction * 100) as int per axis (fractions sum ~1.0,
  so the three ints may sum to 99 or 101). ``archetype_source`` =
  "champion" if the resolved id has a well-formed row, else "default".
  ``elapsed_ms`` is measured on a monotonic counter, never the wall clock.

Failure modes:
  - 400  champion param missing, blank, over-long or non-printable.
  - 500  graceful ``{ok:false,"error":<fixed line ending "see logs">}`` on
         any unexpected exception; the cause is logged, never sent (RM-835).
"""
from __future__ import annotations

import json
import logging
import math
import time
from urllib.parse import parse_qs, urlparse

from core.shaper import KNOB_MAX as _KNOB_MAX
from core.shaper import KNOB_MIN as _KNOB_MIN
from dashboard._dispatch import equals
from dashboard._errors import send_error

log = logging.getLogger("rc.web_dashboard")

# The longest DDragon display name is well under 20 characters; 64 leaves
# headroom for any future name while bounding what the route echoes back.
_MAX_CHAMPION_LEN = 64
_AXES = ("damage", "survivability", "utility")
_BALANCED = (0.5, 0.5)
# Float slack for the knob-direction check (shaped fractions are ~1e-16 noisy).
_EPS = 1e-12


def _parse_knob(raw: str) -> int:
    """Parse a knob to int, clamp [KNOB_MIN, KNOB_MAX]; blank / non-numeric -> 0."""
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
    return {k: round(float(v) * 100) for k, v in triple.items()}


def _bad_request(h, msg: str) -> None:
    h._send(400, json.dumps({"ok": False, "error": msg}).encode("utf-8"),
            "application/json")


def _valid_pair(pair) -> tuple[float, float] | None:
    """Return ``pair`` normalized to sum 1.0, or None when malformed.

    Well-formed = a 2-item list / tuple of finite, non-negative, non-bool
    numbers with a positive sum.
    """
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    vals = []
    for v in pair:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        f = float(v)
        if not math.isfinite(f) or f < 0.0:
            return None
        vals.append(f)
    total = vals[0] + vals[1]
    if total <= 0.0:
        return None
    return vals[0] / total, vals[1] / total


def _baseline_pair(table, champion: str) -> tuple[float, float, str]:
    """``(alpha, beta, archetype_source)`` for ``champion``; never raises."""
    if not isinstance(table, dict):
        log.warning("ds-shape: archetype table is a %s, not an object - "
                    "using the balanced pair", type(table).__name__)
        table = {}
    champions = table.get("champions")
    if not isinstance(champions, dict):
        if champions is not None:
            log.warning("ds-shape: archetype table 'champions' is a %s, not "
                        "an object - using the default pair",
                        type(champions).__name__)
        champions = {}
    if champion in champions:
        pair = _valid_pair(champions[champion])
        if pair is not None:
            return pair[0], pair[1], "champion"
        log.warning("ds-shape: archetype row for %s is malformed - using the "
                    "default pair", champion)
    default = table.get("default")
    pair = _valid_pair(default)
    if pair is None:
        if default is not None:
            log.warning("ds-shape: archetype default pair is malformed - "
                        "using the balanced pair")
        pair = _BALANCED
    return pair[0], pair[1], "default"


def _against_knob(knob: int, shaped: float, base: float) -> bool:
    """True when ``shaped`` moved off ``base`` against the knob's sign."""
    if knob < 0:
        return shaped > base + _EPS
    if knob > 0:
        return shaped < base - _EPS
    return False


def _shape(baseline: dict, knobs: dict) -> dict:
    """Apply the shaper; no axis ever moves against its own knob.

    ``apply_shaper`` floors a nudged axis at WEIGHT_MIN and caps it at
    WEIGHT_MAX, then renormalizes the whole dict - so a negative knob can
    still RAISE its axis (a 0.0 utility floored to 0.05; a row near the
    floor; two negative knobs where the other drops further) and a positive
    one can LOWER it. Such an axis is HELD at its baseline (raised
    negative-knob axes first) and the rest are re-shaped and scaled into
    the remaining share, until none is left. Terminates: the held set only
    grows and there are three axes. ``apply_shaper`` is consumed by THIS
    route only, so the rule defines the preview without diverging from any
    ranking path.
    """
    from core.shaper import ShaperState, apply_shaper

    state = ShaperState(
        damage_nudge=knobs["damage"],
        survivability_nudge=knobs["survivability"],
        utility_nudge=knobs["utility"],
    )
    held: set = set()
    while True:
        free = {ax: baseline[ax] for ax in _AXES if ax not in held}
        if not free:
            return {ax: float(baseline[ax]) for ax in _AXES}
        shaped_free = apply_shaper(free, state)
        share = 1.0 - sum(baseline[ax] for ax in held)
        total = sum(shaped_free.values())
        scale = share / total if total > 0.0 else 0.0
        shaped = {ax: float(baseline[ax]) if ax in held
                  else float(shaped_free[ax]) * scale for ax in _AXES}
        wrong = {ax for ax in free
                 if _against_knob(knobs[ax], shaped[ax], baseline[ax])}
        if not wrong:
            return shaped
        # Hold the RAISED negative-knob axes first: they are the clamp
        # artifacts, and holding them alone often frees a positive knob's
        # axis to rise again (damage +1 with utility -2) - holding both in
        # one pass would cancel the positive knob for nothing.
        raised = {ax for ax in wrong if knobs[ax] < 0}
        held |= raised or wrong


def _serve_ds_shape(h) -> None:
    """GET /api/ds-shape handler."""
    t0 = time.perf_counter()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        raw_champion = (qs.get("champion") or [""])[0].strip()
        if not raw_champion:
            _bad_request(h, "champion param required")
            return
        if (len(raw_champion) > _MAX_CHAMPION_LEN
                or not raw_champion.isprintable()):
            _bad_request(h, "champion param invalid")
            return

        knobs = {
            "damage":        _parse_knob((qs.get("damage") or [""])[0]),
            "survivability": _parse_knob((qs.get("survivability") or [""])[0]),
            "utility":       _parse_knob((qs.get("utility") or [""])[0]),
        }

        from agents.daemon_slayer.hybrid import _load_archetype_weights
        from core.archetype_picks import canonical_champion_id

        # The live caller sends the Live Client DISPLAY name; the table is
        # keyed by canonical DDragon id. Unknown names pass through.
        champion = canonical_champion_id(raw_champion) or raw_champion
        alpha, beta, archetype_source = _baseline_pair(
            _load_archetype_weights(), champion)

        # Literal axis keys are REQUIRED - apply_shaper classifies by substring.
        baseline = {"damage": alpha, "survivability": beta, "utility": 0.0}
        shaped = _shape(baseline, knobs)

        payload = {
            "ok":               True,
            "champion":         champion,
            "archetype_source": archetype_source,
            "knobs":            knobs,
            "baseline":         baseline,
            "shaped":           shaped,
            "baseline_pct":     _to_pct(baseline),
            "shaped_pct":       _to_pct(shaped),
            "elapsed_ms":       int((time.perf_counter() - t0) * 1000),
        }
        # allow_nan=False: a non-finite value is a 500, never a bare NaN token.
        h._send(200, json.dumps(payload, allow_nan=False).encode("utf-8"),
                "application/json")

    except Exception as exc:  # noqa: BLE001
        # RM-835: a fixed line, never str(exc); send_error logs the cause
        # once, scrubbed, with its type name.
        try:
            send_error(h, exc, public_msg="ds-shape failed - see logs",
                       fields={"ok": False})
        except Exception:
            log.debug("ds-shape: the error reply could not be sent",
                      exc_info=True)


GET_ROUTES = [
    (equals("/api/ds-shape"), _serve_ds_shape),
]

POST_ROUTES: list = []

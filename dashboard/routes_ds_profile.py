# arch: DS champion-profile aggregate backend | section=dashboard | frozen=no
"""GET /api/ds-profile - a champion "profile" radar over eight DS scorers.

Thin, additive, read-only dashboard wire that aggregates eight EXISTING pure
per-champion DS scorers - mobility / sustain / scaling / waveclear /
threatrange / zonecontrol / objdamage / extendedduel - into one ordered
"profile" for the locked champ. NO engine math change, NO new dependency, NO
schema lift; every scorer fn is pure, never raises, and returns a dataclass
with a ``.to_dict()``. This route only reads their headline scalars and a
couple of guaranteed breakdown fields, then normalises each axis to a 0-100
percentile against the leaguewide per-axis max.

Mirrors the discipline of routes_ds_sweep.py exactly: the same
StubHandler-compatible ``_send`` contract, the 5-min response cache
(``_CACHE`` / ``_CACHE_TTL_S`` / ``_CACHE_LOCK``), the numeric-DDragon-key ->
slug resolver (``_load_id_to_slug`` / ``_resolve_champion``), the ImportError
-> 503 / compute-Exception -> 503 fail-soft, and the ``_reset_caches()`` test
hook.

Request shape:
  GET /api/ds-profile?champion=<slug-or-numeric>[&mode=SR]

  champion : canonical DDragon id ("Vayne") OR numeric LCU key (67).
             Numeric keys are resolved to the slug via the DDragon map.
  mode     : SR | ARAM | ARENA | BRAWL. Defaults SR, uppercased. Carried on
             the result for parity; the four scorers are target-independent so
             mode does not change the numbers today.

Response shape (ok):
  {
    "ok": true,
    "champion": "Vayne",
    "mode": "SR",
    "axes": [
      {"key":"mobility","label":"Mobility","score":<float r2>,"pct":<int>,
       "tier":"LOW|MED|HIGH","detail":<str>},
      {"key":"sustain", ...},
      {"key":"scaling", ...,"slope":<float r2>,"trajectory":"UP|EVEN|DOWN"},
      {"key":"waveclear", ...,"ranged_shove":<bool>},
      {"key":"threatrange", ...,"is_artillery":<bool>},
      {"key":"zonecontrol", ...,"controls_terrain":<bool>},
      {"key":"objdamage", ...,"pressures_structures":<bool>},
      {"key":"extendedduel", ...,"ramps":<bool>}
    ],
    "elapsed_ms": <int>,
    "cached": <bool>
  }

  axes is an ORDERED list (mobility, sustain, scaling, waveclear,
  threatrange, zonecontrol, objdamage, extendedduel). Each axis:
    score = headline scalar rounded to 2.
    pct   = round(min(score / axis_max, 1.0) * 100), where axis_max is the MAX
            headline across ALL registered champions (computed once, lazily,
            module-global). axis_max is floored at a tiny epsilon so a degenerate
            axis cannot div-by-zero; axis_max <= 0 yields pct = 0.
    tier  = pct >= 66 HIGH, pct >= 33 MED, else LOW.
    detail= a short, defensively-derived label from GUARANTEED fields only
            (fallback "-"): the dominant spell/source kind for mobility/sustain,
            a trajectory phrase for scaling, top_kind for waveclear, top_band
            for threatrange, top_kind for zonecontrol/objdamage/extendedduel.
  scaling additionally carries slope (round 2) + trajectory; waveclear carries
  ranged_shove. The four added axes each carry one extra bool flag:
  threatrange is_artillery, zonecontrol controls_terrain, objdamage
  pressures_structures, extendedduel ramps.

Failure modes (mirror routes_ds_sweep):
  - 400  champion param missing / blank.
  - 200  ok=false reason=no_profile axes=[] when the resolved champion has ZERO
         entries across ALL eight scorers (every headline == 0 AND every result
         carries empty spells/sources). Unknown champion lands here.
  - 503  ImportError or any compute Exception (raw text logged; body carries
         a generic degraded-mode message, never the raw trace).

5-min TTL in-process cache keyed (champion, mode). cached flag + elapsed_ms on
every 200. _reset_caches() clears the response cache (the leaguewide axis-max
cache is immutable engine data and is intentionally not cleared).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors routes_ds_sweep / routes_cooldown_watch.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

# Floor for a per-axis maximum so the pct normalisation never divides by zero
# on a degenerate / all-empty axis.
_AXIS_MAX_EPSILON = 1e-9

# Tier cut-points on the 0-100 pct scale.
_TIER_HIGH = 66
_TIER_MED = 33

# Scaling slope -> trajectory band. A clearly positive slope "scales up", a
# clearly negative one "falls off"; the band in between is "even".
_SLOPE_UP = 0.15
_SLOPE_DOWN = -0.15

# Ordered axis specs: (key, label). The response axes list follows this order.
_AXIS_ORDER: tuple[tuple[str, str], ...] = (
    ("mobility", "Mobility"),
    ("sustain", "Sustain"),
    ("scaling", "Scaling"),
    ("waveclear", "Waveclear"),
    ("threatrange", "Range"),
    ("zonecontrol", "Zone"),
    ("objdamage", "Objective"),
    ("extendedduel", "Duel"),
)

# Lazy DDragon id->slug map + leaguewide per-axis max. Both re-resolved on first
# call after a process restart so a fresh data_pipeline pull picks up. Same
# single-process pattern as routes_ds_sweep.
_ID_TO_SLUG: dict[int, str] | None = None
_ID_MAP_LOCK = threading.Lock()

_AXIS_MAX: dict[str, float] | None = None
_AXIS_MAX_LOCK = threading.Lock()


def _load_id_to_slug() -> dict[int, str]:
    """DDragon ``key`` (int) -> ``id`` (slug, e.g. 'Vayne'). Mirrors
    routes_ds_sweep._load_id_to_slug; fail-soft to {} on any error."""
    global _ID_TO_SLUG
    if _ID_TO_SLUG is not None:
        return _ID_TO_SLUG
    with _ID_MAP_LOCK:
        if _ID_TO_SLUG is not None:
            return _ID_TO_SLUG
        mapping: dict[int, str] = {}
        try:
            path = (
                Path(__file__).resolve().parent.parent
                / "data" / "meta" / "ddragon_champions.json"
            )
            raw = json.loads(path.read_text(encoding="utf-8"))
            data = raw.get("data", raw)
            for entry in data.values():
                if not isinstance(entry, dict):
                    continue
                key = entry.get("key")
                slug = entry.get("id")
                if not (key and slug):
                    continue
                try:
                    mapping[int(key)] = str(slug)
                except (TypeError, ValueError):
                    continue
        except Exception as exc:  # noqa: BLE001
            log.warning("ds-profile: id_to_slug load failed: %s", exc)
        _ID_TO_SLUG = mapping
        return mapping


def _all_slugs() -> list[str]:
    """Every registered champion slug (the DDragon ``id`` values), the same
    source routes_ds_sweep resolves numerics from. Used once to compute the
    leaguewide per-axis max."""
    return sorted(set(_load_id_to_slug().values()))


def _resolve_champion(raw: str) -> str:
    """Accept either a slug or a numeric LCU key; return the slug.

    A purely-numeric token is resolved via the DDragon id->slug map (so the
    frontend may pass cs.my_champion directly). A non-numeric token is taken as
    a slug verbatim. An unresolvable numeric falls through as the original
    string (the four scorers then fail-soft to an empty profile -> no_profile).
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if s.isdigit():
        slug = _load_id_to_slug().get(int(s))
        return slug or s
    return s


def _compute_results(champion: str, mode: str):
    """Run the eight pure scorers once for one champion. Returns an 8-tuple of
    their result dataclasses in _AXIS_ORDER sequence (mobility, sustain,
    scaling, waveclear, threatrange, zonecontrol, objdamage, extendedduel)."""
    from agents.daemon_slayer.extendedduel import compute_extendedduel
    from agents.daemon_slayer.mobility import compute_mobility
    from agents.daemon_slayer.objdamage import compute_objdamage
    from agents.daemon_slayer.scaling import compute_scaling
    from agents.daemon_slayer.sustain import compute_sustain
    from agents.daemon_slayer.threatrange import compute_threatrange
    from agents.daemon_slayer.waveclear import compute_waveclear
    from agents.daemon_slayer.zonecontrol import compute_zonecontrol

    return (
        compute_mobility(champion, mode),
        compute_sustain(champion, mode),
        compute_scaling(champion, mode),
        compute_waveclear(champion, mode),
        compute_threatrange(champion, mode),
        compute_zonecontrol(champion, mode),
        compute_objdamage(champion, mode),
        compute_extendedduel(champion, mode),
    )


def _headlines(results) -> dict[str, float]:
    """Per-axis headline scalar from the eight result dataclasses."""
    mob, sus, scl, wav, thr, zon, obj, duel = results
    return {
        "mobility": float(mob.total_mobility_score),
        "sustain": float(sus.total_sustain_score),
        "scaling": float(scl.scaling_score),
        "waveclear": float(wav.waveclear_score),
        "threatrange": float(thr.threatrange_score),
        "zonecontrol": float(zon.zonecontrol_score),
        "objdamage": float(obj.objdamage_score),
        "extendedduel": float(duel.duel_score),
    }


def _axis_maxima() -> dict[str, float]:
    """Leaguewide MAX headline per axis across every registered champion.

    Computed ONCE, lazily, then cached module-global - the registries are
    immutable engine data for a process lifetime. Each axis max is floored at a
    tiny epsilon so the pct normalisation can never divide by zero.
    """
    global _AXIS_MAX
    if _AXIS_MAX is not None:
        return _AXIS_MAX
    with _AXIS_MAX_LOCK:
        if _AXIS_MAX is not None:
            return _AXIS_MAX
        maxima = {key: _AXIS_MAX_EPSILON for key, _ in _AXIS_ORDER}
        for slug in _all_slugs():
            heads = _headlines(_compute_results(slug, "SR"))
            for key in maxima:
                if heads[key] > maxima[key]:
                    maxima[key] = heads[key]
        _AXIS_MAX = maxima
        return maxima


def _pct(score: float, axis_max: float) -> int:
    """0-100 percentile of ``score`` against the leaguewide axis max."""
    if axis_max <= 0:
        return 0
    return round(min(score / axis_max, 1.0) * 100)


def _tier(pct: int) -> str:
    if pct >= _TIER_HIGH:
        return "HIGH"
    if pct >= _TIER_MED:
        return "MED"
    return "LOW"


def _dominant_kind(spells) -> str:
    """Lowercased kind of the highest-``weighted_units`` spell/source entry;
    ``"-"`` when the breakdown list is empty. Defensive: only the guaranteed
    ``kind`` / ``weighted_units`` fields are read."""
    if not spells:
        return "-"
    try:
        top = max(spells, key=lambda s: s.weighted_units)
        return str(top.kind).lower() or "-"
    except (ValueError, AttributeError):
        return "-"


def _trajectory(slope: float) -> str:
    if slope > _SLOPE_UP:
        return "UP"
    if slope < _SLOPE_DOWN:
        return "DOWN"
    return "EVEN"


def _scaling_phrase(trajectory: str) -> str:
    if trajectory == "UP":
        return "scales up"
    if trajectory == "DOWN":
        return "falls off"
    return "even"


def _build_axes(results, maxima: dict[str, float]) -> list[dict]:
    """Assemble the ordered axes list from the four results + leaguewide maxima.

    Each axis carries the common (key,label,score,pct,tier,detail) block;
    scaling adds slope+trajectory, waveclear adds ranged_shove.
    """
    mob, sus, scl, wav, thr, zon, obj, duel = results
    heads = _headlines(results)
    labels = dict(_AXIS_ORDER)

    def base(key: str, detail: str) -> dict:
        score = heads[key]
        pct = _pct(score, maxima.get(key, _AXIS_MAX_EPSILON))
        return {
            "key": key,
            "label": labels[key],
            "score": round(score, 2),
            "pct": pct,
            "tier": _tier(pct),
            "detail": detail,
        }

    axes: list[dict] = []
    axes.append(base("mobility", _dominant_kind(mob.spells)))
    axes.append(base("sustain", _dominant_kind(sus.spells)))

    trajectory = _trajectory(float(scl.scaling_slope))
    scaling_axis = base("scaling", _scaling_phrase(trajectory))
    scaling_axis["slope"] = round(float(scl.scaling_slope), 2)
    scaling_axis["trajectory"] = trajectory
    axes.append(scaling_axis)

    top_kind = str(wav.top_kind) if wav.top_kind else "-"
    waveclear_axis = base("waveclear", top_kind)
    waveclear_axis["ranged_shove"] = bool(wav.ranged_shove)
    axes.append(waveclear_axis)

    threatrange_axis = base("threatrange", (thr.top_band or "-").lower())
    threatrange_axis["is_artillery"] = bool(thr.is_artillery)
    axes.append(threatrange_axis)

    zonecontrol_axis = base("zonecontrol", (zon.top_kind or "-").lower())
    zonecontrol_axis["controls_terrain"] = bool(zon.controls_terrain)
    axes.append(zonecontrol_axis)

    objdamage_axis = base("objdamage", (obj.top_kind or "-").lower())
    objdamage_axis["pressures_structures"] = bool(obj.pressures_structures)
    axes.append(objdamage_axis)

    extendedduel_axis = base("extendedduel", (duel.top_kind or "-").lower())
    extendedduel_axis["ramps"] = bool(duel.ramps)
    axes.append(extendedduel_axis)

    return axes


def _is_empty_profile(results) -> bool:
    """True when the champion has ZERO entries across ALL eight scorers - every
    headline is 0 AND every breakdown list is empty. This is the no_profile
    branch (an unknown champion lands here too)."""
    mob, sus, scl, wav, thr, zon, obj, duel = results
    heads = _headlines(results)
    if any(v != 0 for v in heads.values()):
        return False
    return (not mob.spells and not sus.spells
            and not scl.sources and not wav.sources
            and not thr.sources and not zon.sources
            and not obj.sources and not duel.sources)


def _compute(champion: str, mode: str) -> dict:
    """Build the response payload from scratch (no cache)."""
    results = _compute_results(champion, mode)
    if _is_empty_profile(results):
        return {
            "ok": False,
            "reason": "no_profile",
            "champion": champion,
            "mode": mode,
            "axes": [],
        }
    return {
        "ok": True,
        "champion": champion,
        "mode": mode,
        "axes": _build_axes(results, _axis_maxima()),
    }


def _serve_ds_profile(h) -> None:
    """GET /api/ds-profile handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        if "champion" not in qs:
            h._send(400, json.dumps({
                "ok": False,
                "error": "champion param required",
            }).encode("utf-8"), "application/json")
            return

        champ_raw = (qs.get("champion") or [""])[0].strip()
        champion = _resolve_champion(champ_raw)
        if not champion:
            h._send(400, json.dumps({
                "ok": False,
                "error": "champion param required",
            }).encode("utf-8"), "application/json")
            return

        mode = (qs.get("mode") or ["SR"])[0].upper().strip() or "SR"

        key = (champion, mode)
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
            payload = _compute(champion, mode)
        except ImportError as exc:
            log.warning("api/ds-profile import: %s", exc)
            h._send(503, json.dumps({
                "ok": False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:  # noqa: BLE001
            # Raw exception text stays in the log; the UI gets the same
            # generic degraded-mode message as the sibling routes.
            log.warning("api/ds-profile compute: %s", exc)
            h._send(503, json.dumps({
                "ok": False,
                "error": "DS engine compute failed",
            }).encode("utf-8"), "application/json")
            return

        with _CACHE_LOCK:
            _CACHE[key] = (now, dict(payload))

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        h._send(200, json.dumps(payload).encode("utf-8"),
                "application/json")

    except Exception as exc:  # noqa: BLE001
        log.warning("api/ds-profile: %s", exc)
        try:
            h._send(500, json.dumps({
                "ok": False, "error": str(exc)[:200],
            }).encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _reset_caches() -> None:
    """Test-only: clear the response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/ds-profile"), _serve_ds_profile),
]

POST_ROUTES: list = []

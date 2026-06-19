# arch: power-curve sparkline backend | section=dashboard | frozen=no
"""GET /api/spike-curve - per-minute team power curves for 0..40.

UX research recommended a "Spike Curve Sparkline" panel (aggregator-C-style
power curve) that visualises ally-team vs enemy-team combat strength
across game minutes 0-40. This module is the backend half - it does NOT
render anything; the frontend panel is a separate follow-up.

Request shape:
  GET /api/spike-curve?ally=ID,ID,ID,ID,ID&enemy=ID,ID,ID,ID,ID[&mode=SR]

  ally, enemy : exactly 5 numeric champion ids each (LCU / DDragon key).
  mode        : SR | ARAM | ARENA | BRAWL. Defaults SR.

Response shape:
  {
    "ok":   true,
    "mode": "SR",
    "ally":  [{"minute": 0, "power": 12.3}, ... 41 entries],
    "enemy": [{"minute": 0, "power": 14.1}, ... 41 entries],
    "peaks": {"ally": 23, "enemy": 17},   # first minute crossing 85% of max
    "cache_key": "...",
    "cached":    false,
    "elapsed_ms": 17
  }

Scoring (cite DS):
  Each champion contributes a per-minute power curve. The scorer is
  ARCHETYPE-resolved via ``core.archetype_picks.get_archetype_for``:

    carry     -> agents.daemon_slayer.dps.compute_dps        .weighted_dps
    mage      -> agents.daemon_slayer.ability_dps.compute_ability_dps
                  .total_ability_dps
    assassin  -> agents.daemon_slayer.burst.compute_burst_damage
                  .total_burst_damage
    tank      -> agents.daemon_slayer.ehp.compute_ehp        .blended_ehp
    bruiser   -> agents.daemon_slayer.hybrid.compute_hybrid  .hybrid_score
    enchanter -> agents.daemon_slayer.hps.compute_hps        .total_throughput
    (fallback)-> compute_dps.weighted_dps

  At each minute m in [0..40]:
    level         = min(18, max(1, 1 + int(m*0.45)))
    gold_proxy    = m * gold_per_min  (SR=380, ARAM=470, ARENA=380, BRAWL=380)
    items_built   = sum(1 for t in (8,15,22,29,35,40) if m >= t)
    item_ids      = canonical first-6 archetype build, trimmed to items_built
    target_armor / target_mr / target_max_hp = fixed credible-fight stats
                  (mode-aware; SR uses 100/50/2500 as the "average enemy
                  mid-game body").

  Each champion's RAW power values are normalized to its own max-of-curve
  so the units are comparable across archetypes (tank EHP vs carry DPS
  have very different magnitudes). The TEAM power at minute m is the SUM
  of the 5 normalized per-champ values at that minute. peaks.<side> =
  argmax of team curve.

Caching:
  - Per-(champ_id, mode, archetype, items-tuple) curve cached 24h in
    ``_CHAMP_CURVE_CACHE``. 41 floats per entry; 172 champs x 4 modes
    bound the memory footprint.
  - Per-(sorted_ally_ids, sorted_enemy_ids, mode) full response cached
    5min in ``_RESPONSE_CACHE``. Survives multiple panel polls during a
    single CS session.

Failure modes:
  - len(ally) != 5 or len(enemy) != 5 -> 400
  - any champion id not resolvable to a DS-known slug -> 400
  - DS snapshot load failure -> 503
"""
from __future__ import annotations

import hashlib
import json
from dashboard._errors import send_error
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# Cache lifetimes
_RESPONSE_TTL_S = 300       # 5 minutes for full team-vs-team responses
_CHAMP_CURVE_TTL_S = 86400  # 24 hours for individual champ curves

# Mode -> (gold per minute, target_armor, target_mr, target_max_hp).
# Fixed "credible mid-game enemy body" target stats so that the curve is
# items-and-level driven (not target-armor scaling). The numbers are the
# rough average enemy-team stats at minute 20 from
# ``coach_integration.enemy_stats.compute_enemy_stats``.
_MODE_PROFILE: dict[str, tuple[int, float, float, float]] = {
    "SR":    (380, 100.0, 50.0, 2500.0),
    "ARAM":  (470, 110.0, 55.0, 2700.0),
    "ARENA": (380, 120.0, 60.0, 3000.0),
    "BRAWL": (380, 100.0, 50.0, 2500.0),
}

# Item-completion checkpoints. Roughly "first item by minute 8, sixth
# item by minute 40" - matches the 380g/min SR baseline (~3000g for first
# mythic, then 3200g per major thereafter).
_ITEM_COMPLETE_MINUTES: tuple[int, ...] = (8, 15, 22, 29, 35, 40)

# Canonical per-archetype 6-item builds. Chosen as "stat-rich" cores so
# the curve doesn't get artificially zeroed by a niche pick. These are
# placeholder canonical builds; refinement to per-champion canonical
# builds is a follow-on UX iteration (would compose on
# ``coach_integration.archetype_dispatch``). All ids verified present in
# the 16.10.1 DS snapshot.
_ARCHETYPE_BUILDS: dict[str, tuple[str, ...]] = {
    "carry":     ("3094", "3031", "3072", "3036", "3046", "3026"),
    "mage":      ("6655", "3157", "3020", "3089", "3135", "3116"),
    "assassin":  ("6691", "3142", "3814", "3036", "3179", "3026"),
    "tank":      ("3068", "3742", "3110", "3193", "3083", "3001"),
    "bruiser":   ("6630", "3742", "3071", "3053", "3026", "3193"),
    "enchanter": ("3504", "3011", "3107", "3222", "3050", "3001"),
}
_FALLBACK_ARCHETYPE = "carry"

# Per-archetype scorer routing. Lazy-imported to keep cold-start cheap
# (DS imports are non-trivial - ~30ms each).
_SCORERS: dict[str, str] = {
    "carry":     "dps",
    "mage":      "ability_dps",
    "assassin":  "burst",
    "tank":      "ehp",
    "bruiser":   "hybrid",
    "enchanter": "hps",
}

# Caches. Keyed dicts under module-level locks - same single-process
# pattern as dashboard.builders.
_RESPONSE_CACHE: dict[str, tuple[float, dict]] = {}
_RESPONSE_LOCK = threading.Lock()

_CHAMP_CURVE_CACHE: dict[str, tuple[float, tuple[float, ...]]] = {}
_CHAMP_CURVE_LOCK = threading.Lock()

# Lazy snapshot + id->slug map. Re-resolved on first call after a process
# restart so a fresh data_pipeline pull picks up.
_SNAPSHOT = None
_SNAPSHOT_LOAD_LOCK = threading.Lock()
_ID_TO_SLUG: dict[int, str] | None = None
_ID_MAP_LOCK = threading.Lock()


def _load_snapshot():
    global _SNAPSHOT
    if _SNAPSHOT is not None:
        return _SNAPSHOT
    with _SNAPSHOT_LOAD_LOCK:
        if _SNAPSHOT is not None:
            return _SNAPSHOT
        from agents.daemon_slayer.data_loader import DataSnapshot
        _SNAPSHOT = DataSnapshot.load()
        return _SNAPSHOT


def _load_id_to_slug() -> dict[int, str]:
    """DDragon ``key`` (int) -> ``id`` (slug, e.g. 'Garen')."""
    global _ID_TO_SLUG
    if _ID_TO_SLUG is not None:
        return _ID_TO_SLUG
    with _ID_MAP_LOCK:
        if _ID_TO_SLUG is not None:
            return _ID_TO_SLUG
        from pathlib import Path
        mapping: dict[int, str] = {}
        try:
            path = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"
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
            log.warning("spike-curve: id_to_slug load failed: %s", exc)
        _ID_TO_SLUG = mapping
        return mapping


def _resolve_archetype(slug: str) -> str:
    """Look up the canonical archetype primary for ``slug`` via the
    project's existing override-aware resolver. Falls back to ``carry``
    when the resolver returns an unmapped or unsupported value."""
    try:
        from core.archetype_picks import get_archetype_for
        entry = get_archetype_for(slug) or {}
        primary = str(entry.get("primary") or "").lower().strip()
        if primary in _ARCHETYPE_BUILDS:
            return primary
    except Exception as exc:  # noqa: BLE001
        log.debug("spike-curve: archetype resolve failed for %s: %s", slug, exc)
    return _FALLBACK_ARCHETYPE


def _items_at_minute(minute: int) -> int:
    """How many of the 6-item build are 'complete' by ``minute``."""
    n = 0
    for thresh in _ITEM_COMPLETE_MINUTES:
        if minute >= thresh:
            n += 1
    return n


def _level_at_minute(minute: int) -> int:
    """Rough operator-side level curve. min=1 at m=0, ~level 18 by m~37."""
    return min(18, max(1, 1 + int(minute * 0.45)))


def _score_one(snapshot, scorer: str, slug: str, level: int,
               item_ids: tuple[str, ...], mode: str,
               target_armor: float, target_mr: float,
               target_max_hp: float) -> float:
    """Dispatch one (scorer, slug, level, items) tuple and return the
    headline scalar. Each scorer's value attribute is documented in the
    module header. Returns 0.0 on any KeyError / scorer-internal failure
    so one bad champ doesn't sink the whole curve."""
    try:
        if scorer == "dps":
            from agents.daemon_slayer.dps import compute_dps
            r = compute_dps(snapshot, slug, level=level, item_ids=item_ids,
                            mode=mode, target_armor=target_armor,
                            target_mr=target_mr, target_max_hp=target_max_hp)
            return float(getattr(r, "weighted_dps", 0.0) or 0.0)
        if scorer == "ability_dps":
            from agents.daemon_slayer.ability_dps import compute_ability_dps
            r = compute_ability_dps(snapshot, slug, level=level,
                                    item_ids=item_ids, mode=mode,
                                    target_armor=target_armor,
                                    target_mr=target_mr,
                                    target_max_hp=target_max_hp)
            return float(getattr(r, "total_ability_dps", 0.0) or 0.0)
        if scorer == "burst":
            from agents.daemon_slayer.burst import compute_burst_damage
            r = compute_burst_damage(snapshot, slug, level=level,
                                     item_ids=item_ids, mode=mode,
                                     target_armor=target_armor,
                                     target_mr=target_mr,
                                     target_max_hp=target_max_hp)
            return float(getattr(r, "total_burst_damage", 0.0) or 0.0)
        if scorer == "ehp":
            from agents.daemon_slayer.ehp import compute_ehp
            r = compute_ehp(snapshot, slug, level=level, item_ids=item_ids,
                            mode=mode, enemy_ad_share=0.5, enemy_ap_share=0.5)
            return float(getattr(r, "blended_ehp", 0.0) or 0.0)
        if scorer == "hybrid":
            from agents.daemon_slayer.hybrid import compute_hybrid
            r = compute_hybrid(snapshot, slug, level=level, item_ids=item_ids,
                               mode=mode, target_armor=target_armor,
                               target_mr=target_mr, target_max_hp=target_max_hp)
            return float(getattr(r, "hybrid_score", 0.0) or 0.0)
        if scorer == "hps":
            from agents.daemon_slayer.hps import compute_hps
            r = compute_hps(snapshot, slug, level=level, item_ids=item_ids,
                            mode=mode)
            return float(getattr(r, "total_throughput", 0.0) or 0.0)
    except Exception as exc:  # noqa: BLE001
        log.debug("spike-curve: %s scorer failed for %s lvl %d items=%s: %s",
                  scorer, slug, level, item_ids, exc)
    return 0.0


def _champ_curve_cache_key(slug: str, archetype: str, mode: str) -> str:
    """The per-champ curve depends on (slug, archetype, mode) - items + level
    schedules are derived from those. Build profile chosen by archetype."""
    return f"{slug}|{archetype}|{mode}"


def _build_champ_curve(slug: str, archetype: str, mode: str) -> tuple[float, ...]:
    """Compute the 41-entry power curve for one champ as a FRACTION of
    that champ's fully-built end-game potential.

    Reference value = scorer(level=18, full 6 items, mode-fixed enemy
    body). Each minute's power = scorer(level_at_m, items_at_m) /
    reference. So power is unitless 0..1+; a champ at level 12 with 3
    items might hit 0.55 (55% of its level-18 6-item potential).

    The shape of the curve differs by archetype because the scorers
    weight level + items differently. Carry items front-load DPS: at
    item 2 a carry is already at ~50%+ of final DPS. Tank items
    interact multiplicatively with level (HP * resists), so a tank at
    level 12 with 2 items is closer to 30% of final EHP. Result: carries
    cross 85% earlier than tanks - the 'carry spikes earlier than tank'
    semantic that ``_peak_minute`` keys off.

    Cached 24h per (slug, archetype, mode).
    """
    cache_key = _champ_curve_cache_key(slug, archetype, mode)
    now = time.time()
    with _CHAMP_CURVE_LOCK:
        cached = _CHAMP_CURVE_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _CHAMP_CURVE_TTL_S:
            return cached[1]

    snapshot = _load_snapshot()
    scorer = _SCORERS.get(archetype, "dps")
    build = _ARCHETYPE_BUILDS.get(archetype, _ARCHETYPE_BUILDS[_FALLBACK_ARCHETYPE])
    _gpm, t_armor, t_mr, t_hp = _MODE_PROFILE.get(mode, _MODE_PROFILE["SR"])

    # Reference value: fully-built level-18 build. The denominator that
    # makes the curve a 'fraction of end-game potential'. Falls back to
    # 1.0 if the reference scorer returns 0 (degenerate champ / scorer
    # combo) to avoid div-by-zero - the curve will be all zeros in that
    # case, which is the right degenerate render anyway.
    reference = _score_one(snapshot, scorer, slug, 18, tuple(build), mode,
                           t_armor, t_mr, t_hp)
    if reference <= 0.0:
        reference = 1.0

    curve: list[float] = []
    for minute in range(0, 41):
        level = _level_at_minute(minute)
        n_items = _items_at_minute(minute)
        used = tuple(build[:n_items])
        val = _score_one(snapshot, scorer, slug, level, used, mode,
                         t_armor, t_mr, t_hp)
        curve.append(val / reference)
    out = tuple(curve)
    with _CHAMP_CURVE_LOCK:
        _CHAMP_CURVE_CACHE[cache_key] = (now, out)
    return out


def _team_curve(champ_ids: tuple[int, ...], mode: str, id_to_slug: dict[int, str]) -> list[dict]:
    """5-champion team curve: for each minute, the sum of per-champ
    fraction-of-end-game-potential. Returns 41 ``{minute, power}`` dicts.

    Each champ's curve is already 0..~1.0 (fraction of its level-18
    fully-built reference) - see :func:`_build_champ_curve`. So a team
    of 5 champs each at 80% of their end-game potential scores 5 * 0.8
    = 4.0. A team fully built at minute 40 caps at ~5.0.

    The shape differs by archetype mix because the underlying scorer
    differs: carries front-load (items 1-2 = big chunk of final DPS);
    tanks back-load (level + items both required for max EHP).
    """
    summed = [0.0] * 41
    for cid in champ_ids:
        slug = id_to_slug.get(int(cid))
        if not slug:
            # Should never reach here - caller validates IDs first.
            continue
        archetype = _resolve_archetype(slug)
        curve = _build_champ_curve(slug, archetype, mode)
        for i in range(41):
            summed[i] += curve[i]
    return [{"minute": i, "power": round(summed[i], 4)} for i in range(41)]


_PEAK_THRESHOLD = 0.70


def _peak_minute(curve: list[dict]) -> int:
    """The team's 'spike' minute - the FIRST minute the curve crosses
    70% of its own maximum. This is the aggregator C power-spike semantic:
    not 'when does the team stop growing' (that's always the last
    minute, since stat accumulation is monotonic), but 'when has the
    team come ONLINE enough to fight'.

    Carries cross 70% early - core mythic + first crit item already
    deliver ~70% of late-game DPS by minute 22-29. Tanks need both full
    level scaling AND items 3-4 stacked before they cross 70% blended
    EHP, which lands later. So ``peaks.ally`` vs ``peaks.enemy`` is a
    meaningful 'who wins early vs late fights' signal.

    Threshold 0.70 picked to separate the carry (mid-game spike) vs tank
    (late-game spike) curves cleanly given the fraction-of-end-game
    reference normalization in :func:`_build_champ_curve` - tighter
    thresholds collapse both crossings into the m38-40 plateau.

    Falls back to argmax when the curve is degenerate (all zeros, etc.).
    """
    if not curve:
        return 0
    max_p = 0.0
    for entry in curve:
        v = float(entry.get("power", 0.0))
        if v > max_p:
            max_p = v
    if max_p <= 0.0:
        return 0
    threshold = max_p * _PEAK_THRESHOLD
    for entry in curve:
        if float(entry.get("power", 0.0)) >= threshold:
            return int(entry.get("minute", 0))
    return int(curve[-1].get("minute", 0))


def _parse_csv_ids(raw: str) -> list[int]:
    """Parse '1,2,3' -> [1,2,3]. Drops blanks; raises ValueError on
    non-int tokens so the caller can 400 cleanly rather than silently
    truncating the team."""
    if not raw:
        return []
    out: list[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        out.append(int(tok))  # raises ValueError on garbage; caller catches
    return out


def _response_cache_key(ally_ids: list[int], enemy_ids: list[int], mode: str) -> str:
    """Cache key for the full team-vs-team response. Order-insensitive on
    team membership (sort each side) so 'ally=1,2,3,4,5' and
    'ally=5,4,3,2,1' hit the same cache entry."""
    a = tuple(sorted(ally_ids))
    e = tuple(sorted(enemy_ids))
    raw = f"{a}|{e}|{mode}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _serve_spike_curve(h) -> None:
    """GET /api/spike-curve - the route entry point."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        try:
            ally_ids = _parse_csv_ids((qs.get("ally") or [""])[0])
            enemy_ids = _parse_csv_ids((qs.get("enemy") or [""])[0])
        except ValueError:
            h._send(400, json.dumps({
                "ok": False, "error": "ally / enemy must be comma-separated ints"
            }).encode(), "application/json")
            return

        if len(ally_ids) != 5 or len(enemy_ids) != 5:
            h._send(400, json.dumps({
                "ok": False,
                "error": "ally and enemy must each have exactly 5 champion ids",
                "ally_count": len(ally_ids), "enemy_count": len(enemy_ids),
            }).encode(), "application/json")
            return

        mode_raw = (qs.get("mode") or ["SR"])[0].upper().strip() or "SR"
        if mode_raw not in _MODE_PROFILE:
            h._send(400, json.dumps({
                "ok": False, "error": f"unsupported mode {mode_raw!r}",
                "supported": sorted(_MODE_PROFILE.keys()),
            }).encode(), "application/json")
            return
        mode = mode_raw

        id_to_slug = _load_id_to_slug()
        if not id_to_slug:
            h._send(503, json.dumps({
                "ok": False, "error": "champion id->slug map unavailable",
            }).encode(), "application/json")
            return

        # Validate every champion id resolves. Surface ALL unknowns in one
        # response so a typo in slot 3 doesn't trickle through five retries.
        unknown_ally = [c for c in ally_ids if int(c) not in id_to_slug]
        unknown_enemy = [c for c in enemy_ids if int(c) not in id_to_slug]
        if unknown_ally or unknown_enemy:
            h._send(400, json.dumps({
                "ok": False, "error": "unknown champion id(s)",
                "unknown_ally": unknown_ally, "unknown_enemy": unknown_enemy,
            }).encode(), "application/json")
            return

        # Try the response-level cache. If a hit, the call is purely a
        # dict copy + freshen-timestamp - 100x faster than re-running
        # the 10 champ curves.
        cache_key = _response_cache_key(ally_ids, enemy_ids, mode)
        now = time.time()
        with _RESPONSE_LOCK:
            cached = _RESPONSE_CACHE.get(cache_key)
            if cached and (now - cached[0]) < _RESPONSE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        # Make sure the DS snapshot is loadable; surface a 503 if not so
        # the panel can render a sensible "engine offline" banner.
        try:
            _load_snapshot()
        except Exception as exc:  # noqa: BLE001
            # Raw exception text stays in the log; the UI gets a generic
            # degraded-mode message (never the raw error string).
            log.warning("spike-curve: snapshot load failed: %s", exc)
            h._send(503, json.dumps({
                "ok": False, "error": "DS engine unavailable",
            }).encode(), "application/json")
            return

        ally_curve = _team_curve(tuple(ally_ids), mode, id_to_slug)
        enemy_curve = _team_curve(tuple(enemy_ids), mode, id_to_slug)

        payload = {
            "ok":    True,
            "mode":  mode,
            "ally":  ally_curve,
            "enemy": enemy_curve,
            "peaks": {
                "ally":  _peak_minute(ally_curve),
                "enemy": _peak_minute(enemy_curve),
            },
            "cache_key":  cache_key,
            "cached":     False,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }

        with _RESPONSE_LOCK:
            _RESPONSE_CACHE[cache_key] = (now, payload)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/spike-curve: %s", exc)
        try:
            send_error(h, exc)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------
# Test helpers. Exposed at module level so tests can clear caches between
# runs without poking at private state.
# --------------------------------------------------------------------


def _reset_caches() -> None:
    """Test-only: clear both response + per-champ caches."""
    with _RESPONSE_LOCK:
        _RESPONSE_CACHE.clear()
    with _CHAMP_CURVE_LOCK:
        _CHAMP_CURVE_CACHE.clear()


GET_ROUTES = [
    (equals("/api/spike-curve"), _serve_spike_curve),
]

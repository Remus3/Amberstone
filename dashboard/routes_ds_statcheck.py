"""GET /api/ds-statcheck - statcheck stat-sandbox panel (competitor lift #5).

A "stat sandbox" for the LOCKED champion: the operator edits the TARGET stats
(enemy armor / MR / max HP / bonus HP) and the level, and the panel shows the
resolved CHAMPION stat block (AD / attack speed / crit / AP / HP / armor / MR
from the build) plus the engine DPS number computed against that what-if target.
This is the in-process sibling of ``routes_ds_knobs`` / ``routes_ds_sweep`` /
``routes_ds_combo``: it READS the existing engine math (no ENGINE_VERSION bump,
no DS :8893 restart) and serves on the same :8888 dashboard.

It wraps ``agents.daemon_slayer.dps.compute_dps`` for the champ's current build
(the item list passed by the panel; itemless if none) at the operator-set target
stats.  ``compute_dps`` accepts the champion NAME/slug string as ``champion_id``
and resolves it internally via ``build_champion`` (the sibling routes pass the
name straight through; ``DataSnapshot`` has no separate id-resolution method - it
exposes ``champion`` / ``champions`` only).  A blank target stat (armor / MR)
resolves to the auto enemy-stat curve via
``coach_integration.enemy_stats.compute_enemy_stats`` and the source ("auto" vs
"override") is echoed per stat, mirroring ``routes_ds_knobs._resolve_knobs``.

What DpsResult exposes (verified live against agents/daemon_slayer/dps.py - the
resolved champion stat block lives in ``DpsResult.stats`` as a dict, NOT as
top-level attributes; there is NO ``ttk_seconds`` field on DpsResult):
  * ``weighted_dps``       -> the headline DPS number (selected phase, weighted)
  * ``stats``              -> resolved champ stat dict (ad / ap / as / crit / hp
                              / mp / armor / mr / attackrange / ms / ...)
  * ``avg_attack_dmg``     -> per-hit avg post-armor + mode (vs the what-if target)
  * ``raw_attack_dps``     -> AD * AS * crit avg, no scenario / no resists
  * ``per_attack_on_hit_damage`` -> amortized on-hit proc damage per AA
  * ``mode_multiplier``    -> aramDamageDealt or 1.0
  * ``phase`` / ``phase_dps``    -> auto-selected rotation phase + all 3 phases
  * ``champion_name``      -> canonical resolved name (echoed back as champion)

v1 honest contract: the CHAMPION-side stats (AD / attack speed / crit / AP) are
DISPLAYED read-only - they are the resolved stat block from the build, not
editable.  Making them editable would require an engine stat-injection argument
that ``compute_dps`` does not expose, so champion-stat editing is out of scope
for v1.  The sandbox knobs are the TARGET (enemy) stats only.

Fail-soft contract mirrors the sibling routes:
  * 400 when ``champion`` missing/blank
  * 200 ok=false when the champ name does not resolve (compute_dps raises
        KeyError "Unknown champion id" inside the engine)
  * 503 when the engine import/compute throws an unexpected error
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("rc.web_dashboard")

# ----------------------------------------------------------------------------
# lazy engine handles (memoized; populated on first successful import)
# ----------------------------------------------------------------------------
_SNAPSHOT: Any = None
_DPS_FN: Callable[..., Any] | None = None

_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL_S = 300.0
_CACHE_LOCK = threading.Lock()

_DEFAULT_LEVEL = 11
_MIN_LEVEL = 1
_MAX_LEVEL = 18


def _reset_caches() -> None:
    """Test hook - clear memoized engine handles + response cache."""
    global _SNAPSHOT, _DPS_FN
    _SNAPSHOT = None
    _DPS_FN = None
    with _CACHE_LOCK:
        _CACHE.clear()


def _load_engine() -> tuple[Any, Callable[..., Any]]:
    """Import + memoize the DS engine handles.  Raises on failure (-> 503)."""
    global _SNAPSHOT, _DPS_FN
    if _DPS_FN is None or _SNAPSHOT is None:
        from agents.daemon_slayer.data_loader import DataSnapshot
        from agents.daemon_slayer.dps import compute_dps

        _SNAPSHOT = DataSnapshot.load()
        _DPS_FN = compute_dps
    return _SNAPSHOT, _DPS_FN


def _first(qs: dict, key: str) -> str:
    v = qs.get(key)
    if not v:
        return ""
    return (v[0] or "").strip()


def _as_float(raw: str) -> float | None:
    """Parse an optional float; None on blank / garbage / non-finite.

    Non-finite values (nan / inf) are rejected: nan poisons the cache key
    (nan != nan -> every request recomputes + inserts a fresh entry) and
    both serialize to non-standard JSON (NaN / Infinity) that browser
    JSON.parse rejects.
    """
    if raw == "":
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _as_int(raw: str) -> int | None:
    """Parse an optional int; None on blank / garbage / non-finite.

    OverflowError covers int(float('inf')) which previously escaped the
    handler entirely (no outer try) and dropped the connection.
    """
    if raw == "":
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return None


def _clamp_level(raw: str) -> int:
    """Parse the champion level; clamp [1, 18]; fall to default 11.

    Mirrors routes_ds_knobs._parse_level. The engine's clamp_level RAISES
    ValueError on out-of-range input (agents/daemon_slayer/stats.py:126),
    which the unknown-champion (KeyError, ValueError) handler would then
    mislabel as "unknown champion" - clamp before the engine sees it.
    """
    n = _as_int(raw)
    if n is None:
        return _DEFAULT_LEVEL
    return max(_MIN_LEVEL, min(_MAX_LEVEL, n))


def _parse_items(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated id list into a tuple of clean string ids."""
    if not raw:
        return ()
    out: list[str] = []
    for chunk in raw.split(","):
        s = chunk.strip()
        if s:
            out.append(s)
    return tuple(out)


def _resolve_targets(
    mode: str,
    level: int,
    armor: float | None,
    mr: float | None,
) -> dict:
    """Resolve blank armor/MR to the auto enemy-stat curve.  Echo the source."""
    armor_source = "override" if armor is not None else "auto"
    mr_source = "override" if mr is not None else "auto"
    if armor is None or mr is None:
        try:
            from coach_integration.enemy_stats import compute_enemy_stats

            es = compute_enemy_stats(mode.lower(), level=float(level))
            if armor is None:
                armor = float(getattr(es, "armor", 0.0) or 0.0)
            if mr is None:
                mr = float(getattr(es, "mr", 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            if armor is None:
                armor = 0.0
            if mr is None:
                mr = 0.0
    return {
        "armor": armor,
        "mr": mr,
        "armor_source": armor_source,
        "mr_source": mr_source,
    }


def _shape_stats(res: Any) -> dict:
    """Normalize the resolved DpsResult champion stat block into JSON-safe rows.

    Reads ``DpsResult.stats`` (the resolved stat dict) for the champion-side
    numbers plus the top-level mitigation/damage fields the engine surfaces.
    Does NOT invent fields - every key is verified against the dps.py source.
    """
    sd = getattr(res, "stats", {}) or {}

    def _sf(name: str) -> float | None:
        v = sd.get(name)
        try:
            return None if v is None else round(float(v), 2)
        except (TypeError, ValueError):
            return None

    def _tf(name: str) -> float | None:
        v = getattr(res, name, None)
        try:
            return None if v is None else round(float(v), 2)
        except (TypeError, ValueError):
            return None

    return {
        # champion-side resolved stat block (from DpsResult.stats dict)
        "ad": _sf("ad"),
        "ap": _sf("ap"),
        "attack_speed": _sf("as"),
        "crit_chance": _sf("crit"),
        "hp": _sf("hp"),
        "mp": _sf("mp"),
        "armor": _sf("armor"),
        "mr": _sf("mr"),
        # top-level damage breakdown (against the what-if target)
        "avg_attack_dmg": _tf("avg_attack_dmg"),
        "raw_attack_dps": _tf("raw_attack_dps"),
        "per_attack_on_hit_damage": _tf("per_attack_on_hit_damage"),
        "mode_multiplier": _tf("mode_multiplier"),
    }


def _serve_ds_statcheck(handler: Any) -> None:
    t0 = time.perf_counter()
    try:
        parsed = urlparse(handler.path)
        qs = parse_qs(parsed.query)
        champion = _first(qs, "champion")
        if not champion:
            _send(handler, 400, {"ok": False, "error": "champion required"})
            return

        mode = (_first(qs, "mode") or "SR").upper()
        level = _clamp_level(_first(qs, "level"))
        items = _parse_items(_first(qs, "items"))
        armor = _as_float(_first(qs, "target_armor"))
        mr = _as_float(_first(qs, "target_mr"))
        hp = _as_float(_first(qs, "target_hp"))
        bonus_hp = _as_float(_first(qs, "target_bonus_hp"))

        ckey = (
            champion.lower(),
            mode,
            tuple(sorted(items)),
            armor,
            mr,
            hp,
            bonus_hp,
            level,
        )
        now = time.monotonic()
        with _CACHE_LOCK:
            hit = _CACHE.get(ckey)
        if hit is not None and (now - hit[0]) < _CACHE_TTL_S:
            payload = dict(hit[1])
            payload["cached"] = True
            payload["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            _send(handler, 200, payload)
            return

        try:
            snap, dps_fn = _load_engine()
        except Exception as exc:  # pragma: no cover - import guard  # noqa: BLE001
            log.warning("api/ds-statcheck engine load: %s", exc)
            _send(handler, 503, {"ok": False, "error": "DS engine unavailable"})
            return

        targets = _resolve_targets(mode, level, armor, mr)
        try:
            res = dps_fn(
                snap,
                champion_id=champion,
                level=level,
                item_ids=items,
                mode=mode,
                target_armor=targets["armor"],
                target_mr=targets["mr"],
                target_max_hp=(hp if hp is not None else 0.0),
                target_bonus_hp=(bonus_hp if bonus_hp is not None else 0.0),
            )
        except (KeyError, ValueError) as exc:
            # unknown champion name (engine lookup miss) - fail soft, not 503
            _send(
                handler,
                200,
                {"ok": False, "error": f"unknown champion: {champion}",
                 "champion": champion, "detail": str(exc)[:120]},
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("api/ds-statcheck compute: %s", exc)
            _send(handler, 503, {"ok": False, "error": "DS engine compute failed"})
            return

        stats = _shape_stats(res)
        weighted = getattr(res, "weighted_dps", None)
        payload = {
            "ok": True,
            "champion": getattr(res, "champion_name", champion) or champion,
            "inputs": {
                "target_armor": targets["armor"],
                "target_mr": targets["mr"],
                "target_hp": (hp if hp is not None else 0.0),
                "target_bonus_hp": (bonus_hp if bonus_hp is not None else 0.0),
                "level": level,
                "mode": mode,
                "items": list(items),
                "armor_source": targets["armor_source"],
                "mr_source": targets["mr_source"],
            },
            "stats": stats,
            "dps": (None if weighted is None else round(float(weighted), 2)),
            "phase": getattr(res, "phase", None),
            "count": sum(1 for v in stats.values() if v is not None),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "cached": False,
        }

        with _CACHE_LOCK:
            _CACHE[ckey] = (now, payload)
        _send(handler, 200, payload)
    except Exception as exc:  # noqa: BLE001
        # Outer guard mirrors the sibling routes: a handler exception must
        # never escape into the HTTP server (pre-fix an OverflowError from
        # a non-finite query param dropped the connection with no response).
        log.warning("api/ds-statcheck: %s", exc)
        try:
            _send(handler, 500, {"ok": False, "error": "internal error"})
        except Exception:  # noqa: BLE001
            pass


def _send(handler: Any, code: int, body: dict) -> None:
    raw = json.dumps(body).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    try:
        handler.wfile.write(raw)
    except Exception:  # noqa: BLE001
        pass


def _equals(path: str) -> Callable[[str], bool]:
    def _m(p: str) -> bool:
        return urlparse(p).path == path

    return _m


GET_ROUTES = [(_equals("/api/ds-statcheck"), _serve_ds_statcheck)]
POST_ROUTES: list = []

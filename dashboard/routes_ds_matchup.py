# arch: DS 1v1 matchup backend | section=dashboard | frozen=no
"""GET /api/ds-matchup - a 1v1 head-to-head trade verdict over two champions.

Thin, additive, read-only dashboard wire that surfaces the EXISTING 1v1
matchup engine (POST /v2/matchup on the DS server :8893) through the
already-shipped ``core.daemon_slayer_client.matchup`` client. NO engine math
change, NO ENGINE_VERSION bump, NO new dependency, NO schema lift; the client
returns a raw MatchupResult dict (or None when the engine is down) and this
route reshapes it into a small, defensively-derived JSON payload.

Mirrors the discipline of routes_ds_profile.py exactly: the same
StubHandler-compatible ``_send`` contract, the 5-min response cache
(``_CACHE`` / ``_CACHE_TTL_S`` / ``_CACHE_LOCK``), the numeric-DDragon-key ->
slug resolver (``_load_id_to_slug`` / ``_resolve_champion``), fail-soft errors,
and the ``_reset_caches()`` test hook.

Request shape:
  GET /api/ds-matchup?champ_a=<slug-or-numeric>&champ_b=<slug-or-numeric>
                      [&level_a=N][&level_b=N][&mode=SR]

  champ_a / champ_b : canonical DDragon id ("Vayne") OR numeric LCU key (67).
                      Both REQUIRED. Numeric keys are resolved to the slug via
                      the DDragon map.
  level_a / level_b : optional int, default 1, clamped to [1, 18].
  mode              : SR | ARAM | ARENA | BRAWL. Defaults SR, uppercased.

Response shape (ok):
  {
    "ok": true,
    "champ_a": "Vayne", "champ_b": "Lux",
    "level_a": 1, "level_b": 1, "mode": "SR",
    "verdict": "all_in|trade|back_off|even",
    "net_swing": <float r3>,            # [-1, 1], + = champ_a favored
    "swing_pct": <int 0-100>,           # (net_swing + 1) / 2 * 100, rounded
    "favored": "A" | "B" | "even",      # A if net_swing >= 0.05, B if <= -0.05
    "pct_a_removed": <float r3>, "pct_b_removed": <float r3>,
    "dmg_a_to_b": <float r1>, "dmg_b_to_a": <float r1>,
    "a_can_full_combo": <bool>, "b_can_full_combo": <bool>,
    "notes": [<str>, ...],
    "elapsed_ms": <int>, "cached": <bool>
  }

Failure modes (mirror routes_ds_profile):
  - 400  champ_a or champ_b param missing / blank.
  - 503  the engine is unreachable (the client returned None); logged warning.
  - 200  ok=false reason=no_matchup when the engine responded with a non-dict
         or a dict lacking the "verdict" key (defensive - never leaks a partial
         shape as ok=true).
  - 500  any unexpected top-level exception (body str(exc)[:200]).

5-min TTL in-process cache keyed (champ_a, champ_b, level_a, level_b, mode).
cached flag + elapsed_ms on every 200. _reset_caches() clears the response
cache.
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

# 5-min response TTL mirrors routes_ds_profile / routes_ds_sweep.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

# Level clamp bounds.
_LEVEL_MIN = 1
_LEVEL_MAX = 18

# net_swing band for the favored verdict. A clearly positive swing favors A, a
# clearly negative one favors B; the band in between is "even".
_FAVOR_BAND = 0.05

# Lazy DDragon id->slug map. Re-resolved on first call after a process restart
# so a fresh data_pipeline pull picks up. Same single-process pattern as
# routes_ds_profile.
_ID_TO_SLUG: dict[int, str] | None = None
_ID_MAP_LOCK = threading.Lock()


def _load_id_to_slug() -> dict[int, str]:
    """DDragon ``key`` (int) -> ``id`` (slug, e.g. 'Vayne'). Mirrors
    routes_ds_profile._load_id_to_slug; fail-soft to {} on any error."""
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
            log.warning("ds-matchup: id_to_slug load failed: %s", exc)
        _ID_TO_SLUG = mapping
        return mapping


def _resolve_champion(raw: str) -> str:
    """Accept either a slug or a numeric LCU key; return the slug.

    A purely-numeric token is resolved via the DDragon id->slug map (so the
    frontend may pass cs.my_champion directly). A non-numeric token is taken as
    a slug verbatim. An unresolvable numeric falls through as the original
    string (the engine then fails-soft to no_matchup).
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if s.isdigit():
        slug = _load_id_to_slug().get(int(s))
        return slug or s
    return s


def _clamp_level(raw: str) -> int:
    """Parse an optional level token, default 1, clamp to [1, 18]."""
    try:
        lvl = int(raw)
    except (TypeError, ValueError):
        return _LEVEL_MIN
    return max(_LEVEL_MIN, min(_LEVEL_MAX, lvl))


def _favored(net_swing: float) -> str:
    if net_swing >= _FAVOR_BAND:
        return "A"
    if net_swing <= -_FAVOR_BAND:
        return "B"
    return "even"


def _compute(champ_a: str, champ_b: str, level_a: int,
             level_b: int, mode: str):
    """Call the matchup client and reshape the raw result. Returns:

      - None                      when the engine is unreachable (-> 503).
      - {"ok": False, ...}        for a non-dict / no-verdict result
                                  (-> 200 no_matchup).
      - {"ok": True, ...}         the shaped payload (-> 200).

    Imported patchably (module attribute) so tests can monkeypatch
    ``core.daemon_slayer_client.matchup``.
    """
    from core import daemon_slayer_client

    result = daemon_slayer_client.matchup(
        champ_a, champ_b,
        level_a=level_a, level_b=level_b, mode=mode,
    )
    if result is None:
        return None
    if not isinstance(result, dict) or "verdict" not in result:
        return {
            "ok": False,
            "reason": "no_matchup",
            "champ_a": champ_a,
            "champ_b": champ_b,
            "mode": mode,
        }

    net_swing = float(result.get("net_swing", 0.0))
    notes = result.get("notes") or []
    return {
        "ok": True,
        "champ_a": champ_a,
        "champ_b": champ_b,
        "level_a": level_a,
        "level_b": level_b,
        "mode": mode,
        "verdict": str(result.get("verdict", "even")),
        "net_swing": round(net_swing, 3),
        "swing_pct": round((net_swing + 1.0) / 2.0 * 100),
        "favored": _favored(net_swing),
        "pct_a_removed": round(float(result.get("pct_a_removed", 0.0)), 3),
        "pct_b_removed": round(float(result.get("pct_b_removed", 0.0)), 3),
        "dmg_a_to_b": round(float(result.get("dmg_a_to_b", 0.0)), 1),
        "dmg_b_to_a": round(float(result.get("dmg_b_to_a", 0.0)), 1),
        "a_can_full_combo": bool(result.get("a_can_full_combo", False)),
        "b_can_full_combo": bool(result.get("b_can_full_combo", False)),
        "notes": [str(n) for n in notes],
    }


def _serve_ds_matchup(h) -> None:
    """GET /api/ds-matchup handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)

        champ_a = _resolve_champion((qs.get("champ_a") or [""])[0])
        champ_b = _resolve_champion((qs.get("champ_b") or [""])[0])
        if not champ_a or not champ_b:
            h._send(400, json.dumps({
                "ok": False,
                "error": "champ_a and champ_b params required",
            }).encode("utf-8"), "application/json")
            return

        level_a = _clamp_level((qs.get("level_a") or ["1"])[0])
        level_b = _clamp_level((qs.get("level_b") or ["1"])[0])
        mode = (qs.get("mode") or ["SR"])[0].upper().strip() or "SR"

        key = (champ_a, champ_b, level_a, level_b, mode)
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
            payload = _compute(champ_a, champ_b, level_a, level_b, mode)
        except Exception as exc:  # noqa: BLE001
            # Raw exception text stays in the log; the UI gets the same
            # generic degraded-mode message as the sibling routes.
            log.warning("api/ds-matchup compute: %s", exc)
            h._send(503, json.dumps({
                "ok": False,
                "error": "DS engine compute failed",
            }).encode("utf-8"), "application/json")
            return

        if payload is None:
            log.warning("api/ds-matchup: DS engine unavailable (%s vs %s)",
                        champ_a, champ_b)
            h._send(503, json.dumps({
                "ok": False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return

        with _CACHE_LOCK:
            _CACHE[key] = (now, dict(payload))

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        h._send(200, json.dumps(payload).encode("utf-8"),
                "application/json")

    except Exception as exc:  # noqa: BLE001
        log.warning("api/ds-matchup: %s", exc)
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
    (equals("/api/ds-matchup"), _serve_ds_matchup),
]

POST_ROUTES: list = []

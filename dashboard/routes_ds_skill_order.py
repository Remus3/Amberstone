# arch: DS ability max-order backend | section=dashboard | frozen=no
"""GET /api/ds-skill-order - a champion's ability MAX ORDER for champ-select.

Presentation-only lift over EXISTING local data. The DS champions.json snapshot
already ships an 18-element per-champion level-up array at
``data[<slug>]["lolmath"]["skill_order"]`` (e.g. Aatrox = ["Q","E","W","Q",...]);
this route reads it directly, collapses it to a three-basic MAX ORDER
(e.g. "Q > E > W") plus the ult level-ups, and hands it to the champ-select
panel. NO engine math, NO new dependency, NO schema lift, NO DS scorer import.

Mirrors the discipline of routes_ds_profile.py exactly: the same
StubHandler-compatible ``_send`` contract, the 5-min response cache
(``_CACHE`` / ``_CACHE_TTL_S`` / ``_CACHE_LOCK``), the numeric-DDragon-key ->
slug resolver (``_load_id_to_slug`` / ``_resolve_champion``), the ImportError
-> 503 / compute-Exception -> 503 fail-soft, and the ``_reset_caches()`` test
hook. It differs by NOT importing any DS scorer - it reads the champions.json
snapshot straight off disk (resolved via data/daemon_slayer/current.txt),
cached lazily module-global with its own lock.

Request shape:
  GET /api/ds-skill-order?champion=<slug-or-numeric>[&mode=SR]

  champion : canonical DDragon id ("Aatrox") OR numeric LCU key (266).
             Numeric keys are resolved to the slug via the DDragon map.
  mode     : SR | ARAM | ARENA | BRAWL. Defaults SR, uppercased. Carried on
             the result for parity only - skill order is mode-independent.

Collapse algorithm (deterministic):
  Given the 18-element array of "Q"/"W"/"E"/"R":
    max_order    = the three basics Q, W, E ordered by the LEVEL (1-based
                   index+1) at which each reaches its 5th (max) point, ascending;
                   tie-break by first-appearance index ascending. A basic that
                   never reaches 5 points sorts LAST (large sentinel).
    max_order_str= the three joined with " > " (ASCII), e.g. "Q > E > W".
    ult_levels   = the 1-based levels where the array element == "R"
                   (normally [6, 11, 16]).

Response shape (ok):
  {
    "ok": true,
    "champion": "Aatrox",
    "mode": "SR",
    "skill_order": [<18 strings>],
    "max_order": ["Q","E","W"],
    "max_order_str": "Q > E > W",
    "ult_levels": [6, 11, 16],
    "elapsed_ms": <int>,
    "cached": <bool>
  }

Failure modes (mirror routes_ds_profile):
  - 400  champion param missing / blank.
  - 200  ok=false reason=no_skill_order skill_order=[] when the resolved
         champion is unknown or has no 18-element array. Unknown champion lands
         here.
  - 503  ImportError or any compute Exception (raw text logged; body carries
         a generic degraded-mode message, never the raw trace).

5-min TTL in-process cache keyed (champion, mode). cached flag + elapsed_ms on
every 200. _reset_caches() clears the response cache + the loaded snapshot
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

# The three basic abilities, in the canonical Q/W/E order. A basic reaches
# "max" at its 5th point; an ult (R) is excluded from max_order.
_BASICS = ("Q", "W", "E")
_MAX_POINTS = 5

# Sentinel level for a basic that never reaches 5 points - sorts it LAST.
_NEVER_MAX = 10 ** 6

# Lazy DDragon id->slug map + loaded champions.json snapshot. Both re-resolved
# on first call after a process restart so a fresh data pull picks up. Same
# single-process pattern as routes_ds_profile.
_ID_TO_SLUG: dict[int, str] | None = None
_ID_MAP_LOCK = threading.Lock()

_CHAMPIONS: dict | None = None
_CHAMPIONS_LOCK = threading.Lock()


def _load_id_to_slug() -> dict[int, str]:
    """DDragon ``key`` (int) -> ``id`` (slug, e.g. 'Aatrox'). Mirrors
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
            log.warning("ds-skill-order: id_to_slug load failed: %s", exc)
        _ID_TO_SLUG = mapping
        return mapping


def _load_champions() -> dict:
    """Load the DS champions.json snapshot for the current patch, lazily.

    Resolves the patch from data/daemon_slayer/current.txt, reads
    data/daemon_slayer/<patch>/champions.json and returns its ``["data"]``
    map (slug -> champion doc). Cached module-global; fail-soft to {} on any
    error (a missing / malformed snapshot yields no_skill_order downstream)."""
    global _CHAMPIONS
    if _CHAMPIONS is not None:
        return _CHAMPIONS
    with _CHAMPIONS_LOCK:
        if _CHAMPIONS is not None:
            return _CHAMPIONS
        data: dict = {}
        try:
            root = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"
            patch = (root / "current.txt").read_text(encoding="utf-8").strip()
            path = root / patch / "champions.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            data = raw.get("data", {}) or {}
            if not isinstance(data, dict):
                data = {}
        except Exception as exc:  # noqa: BLE001
            log.warning("ds-skill-order: champions.json load failed: %s", exc)
            data = {}
        _CHAMPIONS = data
        return data


def _resolve_champion(raw: str) -> str:
    """Accept either a slug or a numeric LCU key; return the slug.

    A purely-numeric token is resolved via the DDragon id->slug map (so the
    frontend may pass cs.my_champion directly). A non-numeric token is taken as
    a slug verbatim. An unresolvable numeric falls through as the original
    string (which then misses the snapshot -> no_skill_order)."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.isdigit():
        slug = _load_id_to_slug().get(int(s))
        return slug or s
    return s


def _skill_order_for(champion: str) -> list[str]:
    """The 18-element level-up array for one slug, or [] when absent/malformed.

    Reads data[<slug>]["lolmath"]["skill_order"]; validates it is a length-18
    list of basic/ult letters. Anything else fail-softs to []."""
    doc = _load_champions().get(champion)
    if not isinstance(doc, dict):
        return []
    lm = doc.get("lolmath")
    if not isinstance(lm, dict):
        return []
    so = lm.get("skill_order")
    if not isinstance(so, list) or len(so) != 18:
        return []
    out = [str(x) for x in so]
    if any(x not in ("Q", "W", "E", "R") for x in out):
        return []
    return out


def _fifth_point_level(skill_order: list[str], letter: str) -> int:
    """1-based level at which ``letter`` reaches its 5th (max) point, or the
    _NEVER_MAX sentinel when it never does."""
    count = 0
    for i, x in enumerate(skill_order):
        if x == letter:
            count += 1
            if count == _MAX_POINTS:
                return i + 1
    return _NEVER_MAX


def _first_index(skill_order: list[str], letter: str) -> int:
    """0-based first-appearance index of ``letter``, or a large sentinel when
    it never appears (used only as a tie-break)."""
    for i, x in enumerate(skill_order):
        if x == letter:
            return i
    return _NEVER_MAX


def _collapse(skill_order: list[str]) -> tuple[list[str], str, list[int]]:
    """Collapse the 18-element array into (max_order, max_order_str, ult_levels).

    max_order = Q/W/E ordered by 5th-point level ascending, tie-broken by
    first-appearance index ascending. max_order_str joins them with " > ".
    ult_levels are the 1-based levels where the element == "R"."""
    max_order = sorted(
        _BASICS,
        key=lambda L: (_fifth_point_level(skill_order, L),
                       _first_index(skill_order, L)),
    )
    max_order = list(max_order)
    max_order_str = " > ".join(max_order)
    ult_levels = [i + 1 for i, x in enumerate(skill_order) if x == "R"]
    return max_order, max_order_str, ult_levels


def _compute(champion: str, mode: str) -> dict:
    """Build the response payload from scratch (no cache)."""
    skill_order = _skill_order_for(champion)
    if not skill_order:
        return {
            "ok": False,
            "reason": "no_skill_order",
            "champion": champion,
            "mode": mode,
            "skill_order": [],
        }
    max_order, max_order_str, ult_levels = _collapse(skill_order)
    return {
        "ok": True,
        "champion": champion,
        "mode": mode,
        "skill_order": skill_order,
        "max_order": max_order,
        "max_order_str": max_order_str,
        "ult_levels": ult_levels,
    }


def _serve_ds_skill_order(h) -> None:
    """GET /api/ds-skill-order handler."""
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
            log.warning("api/ds-skill-order import: %s", exc)
            h._send(503, json.dumps({
                "ok": False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:  # noqa: BLE001
            # Raw exception text stays in the log; the UI gets the same
            # generic degraded-mode message as the sibling routes.
            log.warning("api/ds-skill-order compute: %s", exc)
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
        log.warning("api/ds-skill-order: %s", exc)
        try:
            h._send(500, json.dumps({
                "ok": False, "error": str(exc)[:200],
            }).encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _reset_caches() -> None:
    """Test-only: clear the response cache + the loaded snapshot cache."""
    global _CHAMPIONS
    with _CACHE_LOCK:
        _CACHE.clear()
    with _CHAMPIONS_LOCK:
        _CHAMPIONS = None


GET_ROUTES = [
    (equals("/api/ds-skill-order"), _serve_ds_skill_order),
]

POST_ROUTES: list = []

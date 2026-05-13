"""Phase 3 — local HTTP server for the Daemon Slayer engine.

Wraps `stats`, `dps`, `rank` (and snapshot metadata) in plain-HTTP routes
on `:8893`. Stdlib ``ThreadingHTTPServer`` to match the rest of RC; no
FastAPI/aiohttp dependency. Snapshot is loaded once at startup and held
in memory — patch hot-reload lands in Phase 7 alongside the supervisor
entry.

Routes (all accept GET with query params for read-only sanity checking;
POST + JSON body is the contract for production callers):

  GET  /                  — index page with usage examples
  GET  /health            — engine + snapshot health
  GET  /snapshot          — patch + counts + manifest excerpt
  POST /stats             — body: {champion, level, items?, mode?}
  POST /dps               — body: {champion, level, items?, mode?,
                                    target_armor?, target_mr?,
                                    target_max_hp?, phase?}
  POST /rank              — body: {champion, level, items?, mode?,
                                    target_armor?, target_mr?,
                                    target_max_hp?, phase?,
                                    budget?, slots?, top?, sort?,
                                    include_components?, only?}
  POST /beam              — body: {champion, level, items?, mode?,
                                    target_armor?, target_mr?,
                                    target_max_hp?, phase?,
                                    slots?, beam_width?, top?,
                                    total_budget?, include_components?,
                                    only?, boots_unique?}

Errors map to:
  400 — body parse failure, missing required field, bad enum value
  404 — unknown champion or item id (KeyError from engine)
  422 — value-out-of-range / engine ValueError
  500 — anything unexpected
"""

from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from . import ENGINE_VERSION
from .ability_dps import compute_ability_dps, rank_items_by_ability_dps
from .beam import (
    DEFAULT_BEAM_WIDTH,
    DEFAULT_TOP_N as BEAM_DEFAULT_TOP_N,
    beam_search_build,
)
from .burst import (
    DEFAULT_COMBO_SEQUENCE,
    compute_burst_damage,
    rank_items_by_burst,
)
from .data_loader import DataSnapshot, SnapshotNotFound
from .dps import compute_dps
from .ehp import compute_ehp, rank_items_by_ehp
from .engine import build_champion
from .hps import compute_hps, rank_items_by_hps
from .hybrid import compute_hybrid, rank_items_by_hybrid
from .rank import SORT_KEYS, rank_items

_log = logging.getLogger("daemon_slayer.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8893

_INDEX_HTML = """<!doctype html>
<meta charset=utf-8>
<title>Daemon Slayer engine</title>
<style>
  body {{ font: 14px/1.45 system-ui, sans-serif; max-width: 780px;
         margin: 2em auto; padding: 0 1em; color: #1a1a1a; }}
  h1, h2 {{ font-weight: 600; }}
  code, pre {{ background: #f4f4f4; padding: 2px 4px; border-radius: 3px; }}
  pre {{ padding: 10px; overflow-x: auto; }}
  table {{ border-collapse: collapse; }}
  td, th {{ padding: 4px 10px; border-bottom: 1px solid #eee; text-align: left; }}
  .ok {{ color: #1f7a1f; font-weight: 600; }}
</style>
<h1>Daemon Slayer engine — v{version}</h1>
<p class=ok>snapshot patch <code>{patch}</code> &middot; {n_champ} champions &middot; {n_items} items</p>

<h2>Routes</h2>
<table>
<tr><th>method</th><th>path</th><th>purpose</th></tr>
<tr><td>GET</td><td><a href=/health>/health</a></td><td>liveness + version</td></tr>
<tr><td>GET</td><td><a href=/snapshot>/snapshot</a></td><td>patch + counts</td></tr>
<tr><td>POST</td><td>/stats</td><td>resolve champion stats at level + items</td></tr>
<tr><td>POST</td><td>/dps</td><td>auto-attack DPS over rotation scenarios</td></tr>
<tr><td>POST</td><td>/rank</td><td>rank items by DPS delta</td></tr>
<tr><td>POST</td><td>/beam</td><td>full-build beam search (top-N complete builds)</td></tr>
<tr><td>POST</td><td>/ehp</td><td>caster Effective HP under an enemy damage profile (Phase 1)</td></tr>
<tr><td>POST</td><td>/rank-tank</td><td>rank items by EHP delta (Phase 1)</td></tr>
<tr><td>POST</td><td>/hybrid</td><td>bruiser combined DPS+EHP score (Phase 2)</td></tr>
<tr><td>POST</td><td>/rank-bruiser</td><td>rank items by weighted (α·dps + β·ehp) delta (Phase 2)</td></tr>
<tr><td>POST</td><td>/ability-dps</td><td>per-spell ability DPS for a mage / caster build (Phase 4b)</td></tr>
<tr><td>POST</td><td>/rank-mage</td><td>rank items by total-ability-DPS delta (Phase 4c)</td></tr>
<tr><td>POST</td><td>/burst</td><td>single-combo total burst damage for an assassin build (Phase 5)</td></tr>
<tr><td>POST</td><td>/rank-assassin</td><td>rank items by total-burst-damage delta (Phase 5)</td></tr>
<tr><td>POST</td><td>/hps</td><td>total healing+shielding+buff throughput for an enchanter build (Phase 6)</td></tr>
<tr><td>POST</td><td>/rank-enchanter</td><td>rank items by total-throughput delta (Phase 6)</td></tr>
</table>

<h2>Example</h2>
<pre>curl -sX POST http://127.0.0.1:{port}/dps \\
  -H "content-type: application/json" \\
  -d '{{"champion":"Aatrox","level":11,"items":["6692","3006"],
       "mode":"ARAM","target_armor":80}}'</pre>

<p>GET equivalents accept the same fields as query parameters
(<code>items</code> comma-separated):
<a href="/stats?champion=Aatrox&level=11&items=6692,3006">
/stats?champion=Aatrox&amp;level=11&amp;items=6692,3006</a></p>
"""


# ---------------------------------------------------------------- snapshot cache


class _SnapshotCache:
    """Single-snapshot holder. Loaded once at server start; tests can
    inject by passing ``snapshot=`` to ``start_server``. Hot-reload on
    patch change is Phase 7."""

    def __init__(self) -> None:
        self._snap: Optional[DataSnapshot] = None
        self._lock = threading.Lock()

    def set(self, snap: DataSnapshot) -> None:
        with self._lock:
            self._snap = snap

    def get(self) -> DataSnapshot:
        with self._lock:
            if self._snap is None:
                raise RuntimeError("snapshot not loaded yet")
            return self._snap


_CACHE = _SnapshotCache()


def _load_default_snapshot(
    patch: Optional[str] = None,
    data_root: Optional[Path] = None,
) -> DataSnapshot:
    return DataSnapshot.load(patch=patch, data_root=data_root)


# ---------------------------------------------------------------- handler


class _ApiError(Exception):
    """Mapped to a JSON 4xx/5xx by the handler."""

    def __init__(self, status: int, message: str, *, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


def _coerce_str_list(value: Any, field_name: str) -> list[str]:
    """Accept ``list[str|int]`` (from JSON) or comma-separated string (from
    a query param). Returns canonicalised list of stripped non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    raise _ApiError(400, f"{field_name}: expected list or comma-separated string, got {type(value).__name__}")


def _required_str(body: dict, key: str) -> str:
    v = body.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise _ApiError(400, f"missing required field: {key}")
    return str(v).strip()


def _opt_int(body: dict, key: str, default: Optional[int] = None) -> Optional[int]:
    v = body.get(key, default)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        raise _ApiError(400, f"{key}: expected integer, got {v!r}")


def _opt_float(body: dict, key: str, default: float = 0.0) -> float:
    v = body.get(key, default)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        raise _ApiError(400, f"{key}: expected number, got {v!r}")


def _opt_bool(body: dict, key: str, default: bool = False) -> bool:
    v = body.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return default


def _opt_str(body: dict, key: str, default: Optional[str] = None) -> Optional[str]:
    v = body.get(key, default)
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


# ---------------------------------------------------------------- champion id resolution
#
# 2026-05-09 (s156): RC's coaches feed `champion` from coaching_data.json
# as the *display name* ("Kai'Sa", "Twisted Fate", "Wukong"), but DDragon
# / DS keys the snapshot by ID ("Kaisa", "TwistedFate", "MonkeyKing").
# Direct lookup raised 404 → coaches caught + dropped DS rows silently
# → daemon_slayer_picks never written → dashboard #ds-pill stayed hidden
# → user saw "ds not loaded at all" mid-game on Kai'Sa.
#
# Fix at the server: try the input as a DDragon ID first (no behavior
# change for callers that already pass IDs), then fall back to a lazy
# reverse map keyed off the display name (case-insensitive + alnum-
# stripped). Covers MonkeyKing/Wukong, Nunu/Nunu & Willump,
# Renata/Renata Glasc and the apostrophe family (Kai'Sa, K'Sante,
# Rek'Sai, Cho'Gath, Kha'Zix, Vel'Koz, Kog'Maw, Bel'Veth).

_DISPLAY_REVMAP_CACHE: dict[int, dict[str, str]] = {}


def _build_display_revmap(snap: DataSnapshot) -> dict[str, str]:
    rev: dict[str, str] = {}
    for cid, rec in snap.champions.items():
        display = (rec.get("name") or "").strip()
        if not display:
            continue
        # Three keys per champion so we tolerate punctuation drift:
        #   exact display ("Kai'Sa") · lowercase display ("kai'sa")
        #   alnum-stripped lower ("kaisa", "monkeyking", "twistedfate")
        rev[display] = cid
        rev[display.lower()] = cid
        stripped = "".join(c for c in display if c.isalnum()).lower()
        if stripped:
            rev[stripped] = cid
    return rev


def _resolve_champion_id(snap: DataSnapshot, name: str) -> str:
    if name in snap.champions:
        return name
    cache_key = id(snap)
    rev = _DISPLAY_REVMAP_CACHE.get(cache_key)
    if rev is None:
        rev = _build_display_revmap(snap)
        _DISPLAY_REVMAP_CACHE[cache_key] = rev
    if name in rev:
        return rev[name]
    lo = name.lower()
    if lo in rev:
        return rev[lo]
    stripped = "".join(c for c in name if c.isalnum()).lower()
    if stripped in rev:
        return rev[stripped]
    return name  # let the engine raise the canonical KeyError → 404


# ---------------------------------------------------------------- route handlers


def _route_stats(body: dict) -> dict:
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    augments = _coerce_str_list(body.get("augments"), "augments")
    try:
        resolved = build_champion(snap, champion_id=champion, level=level,
                                  item_ids=items, mode=mode, augments=augments)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return resolved.to_dict()


def _route_dps(body: dict) -> dict:
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    target_max_hp = _opt_float(body, "target_max_hp", 0.0)
    target_bonus_hp = _opt_float(body, "target_bonus_hp", 0.0)
    phase = _opt_str(body, "phase")
    augments = _coerce_str_list(body.get("augments"), "augments")
    if phase is not None and phase not in ("early", "mid", "late"):
        raise _ApiError(400, f"phase: must be early|mid|late, got {phase!r}")
    try:
        result = compute_dps(snap, champion_id=champion, level=level,
                             item_ids=items, mode=mode,
                             target_armor=target_armor, target_mr=target_mr,
                             target_max_hp=target_max_hp,
                             target_bonus_hp=target_bonus_hp,
                             phase=phase, augments=augments)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank(body: dict) -> dict:
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    target_max_hp = _opt_float(body, "target_max_hp", 0.0)
    target_bonus_hp = _opt_float(body, "target_bonus_hp", 0.0)
    phase = _opt_str(body, "phase")
    augments = _coerce_str_list(body.get("augments"), "augments")
    if phase is not None and phase not in ("early", "mid", "late"):
        raise _ApiError(400, f"phase: must be early|mid|late, got {phase!r}")
    budget = _opt_int(body, "budget", None)
    slot_count = _opt_int(body, "slots", 6) or 6
    top_n = _opt_int(body, "top", 20)
    if top_n is None:
        top_n = 20
    sort_by = _opt_str(body, "sort", "delta") or "delta"
    if sort_by not in SORT_KEYS:
        raise _ApiError(400, f"sort: must be one of {list(SORT_KEYS)}, got {sort_by!r}")
    include_components = _opt_bool(body, "include_components", False)
    filter_shared_uniques = _opt_bool(body, "filter_shared_uniques", True)
    only_ids: Optional[list[str]] = None
    if "only" in body and body["only"] not in (None, ""):
        only_ids = _coerce_str_list(body["only"], "only")
    try:
        result = rank_items(
            snap,
            champion_id=champion, level=level,
            current_item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp,
            target_bonus_hp=target_bonus_hp,
            phase=phase,
            budget=budget, slot_count=slot_count, top_n=top_n,
            include_components=include_components,
            only_item_ids=only_ids, sort_by=sort_by,
            augments=augments,
            filter_shared_uniques=filter_shared_uniques,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_ehp(body: dict) -> dict:
    """POST /ehp — compute Effective HP for the caster build.

    Body shape mirrors /dps but swaps ``target_armor`` / ``target_mr`` for
    ``enemy_ad_share`` / ``enemy_ap_share`` (the operator's *exposure* to
    physical/magical damage, not the target's resists).
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    enemy_ad_share = _opt_float(body, "enemy_ad_share", 0.5)
    enemy_ap_share = _opt_float(body, "enemy_ap_share", 0.5)
    augments = _coerce_str_list(body.get("augments"), "augments")
    try:
        result = compute_ehp(
            snap, champion_id=champion, level=level,
            item_ids=items, mode=mode,
            enemy_ad_share=enemy_ad_share,
            enemy_ap_share=enemy_ap_share,
            augments=augments,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank_tank(body: dict) -> dict:
    """POST /rank-tank — rank items by Effective HP gained.

    Mirror of ``/rank`` for the EHP scorer. Same body shape with two
    swaps: ``enemy_ad_share`` / ``enemy_ap_share`` (floats) replace
    ``target_armor`` / ``target_mr`` (irrelevant to EHP — they describe
    the target, not the caster's exposure).
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    enemy_ad_share = _opt_float(body, "enemy_ad_share", 0.5)
    enemy_ap_share = _opt_float(body, "enemy_ap_share", 0.5)
    augments = _coerce_str_list(body.get("augments"), "augments")
    budget = _opt_int(body, "budget", None)
    slot_count = _opt_int(body, "slots", 6) or 6
    top_n = _opt_int(body, "top", 20)
    if top_n is None:
        top_n = 20
    sort_by = _opt_str(body, "sort", "delta") or "delta"
    if sort_by not in SORT_KEYS:
        raise _ApiError(400, f"sort: must be one of {list(SORT_KEYS)}, got {sort_by!r}")
    include_components = _opt_bool(body, "include_components", False)
    filter_shared_uniques = _opt_bool(body, "filter_shared_uniques", True)
    only_ids: Optional[list[str]] = None
    if "only" in body and body["only"] not in (None, ""):
        only_ids = _coerce_str_list(body["only"], "only")
    try:
        result = rank_items_by_ehp(
            snap,
            champion_id=champion, level=level,
            current_item_ids=items, mode=mode,
            enemy_ad_share=enemy_ad_share,
            enemy_ap_share=enemy_ap_share,
            budget=budget, slot_count=slot_count, top_n=top_n,
            include_components=include_components,
            only_item_ids=only_ids, sort_by=sort_by,
            augments=augments,
            filter_shared_uniques=filter_shared_uniques,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _opt_weight(body: dict, key: str) -> Optional[float]:
    """Optional alpha/beta override. Returns None when absent (engine
    falls back to the per-champion table)."""
    if key not in body or body[key] in (None, ""):
        return None
    try:
        return float(body[key])
    except (TypeError, ValueError):
        raise _ApiError(400, f"{key}: expected number, got {body[key]!r}")


def _route_hybrid(body: dict) -> dict:
    """POST /hybrid — compute combined DPS+EHP score for the caster build.

    Phase 2 (s175, 2026-05-12). Body shape is the union of /dps and /ehp
    parameters plus optional ``alpha`` / ``beta`` weight overrides.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    target_max_hp = _opt_float(body, "target_max_hp", 0.0)
    target_bonus_hp = _opt_float(body, "target_bonus_hp", 0.0)
    enemy_ad_share = _opt_float(body, "enemy_ad_share", 0.5)
    enemy_ap_share = _opt_float(body, "enemy_ap_share", 0.5)
    phase = _opt_str(body, "phase")
    if phase is not None and phase not in ("early", "mid", "late"):
        raise _ApiError(400, f"phase: must be early|mid|late, got {phase!r}")
    augments = _coerce_str_list(body.get("augments"), "augments")
    alpha = _opt_weight(body, "alpha")
    beta = _opt_weight(body, "beta")
    try:
        result = compute_hybrid(
            snap, champion_id=champion, level=level,
            item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            enemy_ad_share=enemy_ad_share, enemy_ap_share=enemy_ap_share,
            phase=phase, augments=augments,
            alpha=alpha, beta=beta,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank_bruiser(body: dict) -> dict:
    """POST /rank-bruiser — rank items by weighted DPS+EHP delta.

    Phase 2 (s175, 2026-05-12). Body is the union of /rank and /rank-tank
    parameters. ``alpha`` / ``beta`` default to per-champion overrides
    from ``archetype_weights.json``; pass explicit floats to override.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    target_max_hp = _opt_float(body, "target_max_hp", 0.0)
    target_bonus_hp = _opt_float(body, "target_bonus_hp", 0.0)
    enemy_ad_share = _opt_float(body, "enemy_ad_share", 0.5)
    enemy_ap_share = _opt_float(body, "enemy_ap_share", 0.5)
    phase = _opt_str(body, "phase")
    if phase is not None and phase not in ("early", "mid", "late"):
        raise _ApiError(400, f"phase: must be early|mid|late, got {phase!r}")
    augments = _coerce_str_list(body.get("augments"), "augments")
    budget = _opt_int(body, "budget", None)
    slot_count = _opt_int(body, "slots", 6) or 6
    top_n = _opt_int(body, "top", 20)
    if top_n is None:
        top_n = 20
    sort_by = _opt_str(body, "sort", "delta") or "delta"
    if sort_by not in SORT_KEYS:
        raise _ApiError(400, f"sort: must be one of {list(SORT_KEYS)}, got {sort_by!r}")
    include_components = _opt_bool(body, "include_components", False)
    filter_shared_uniques = _opt_bool(body, "filter_shared_uniques", True)
    alpha = _opt_weight(body, "alpha")
    beta = _opt_weight(body, "beta")
    only_ids: Optional[list[str]] = None
    if "only" in body and body["only"] not in (None, ""):
        only_ids = _coerce_str_list(body["only"], "only")
    try:
        result = rank_items_by_hybrid(
            snap,
            champion_id=champion, level=level,
            current_item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            enemy_ad_share=enemy_ad_share, enemy_ap_share=enemy_ap_share,
            phase=phase,
            budget=budget, slot_count=slot_count, top_n=top_n,
            include_components=include_components,
            only_item_ids=only_ids, sort_by=sort_by,
            augments=augments,
            filter_shared_uniques=filter_shared_uniques,
            alpha=alpha, beta=beta,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _parse_max_priority(body: dict) -> tuple[str, str, str]:
    """Decode the ``max_priority`` body field.

    Accepts None / list / comma-string ("Q,W,E") / compact "QWE". Phase 4c
    shared between ``/ability-dps`` and ``/rank-mage`` so both routes parse
    the operator's priority override identically.
    """
    raw_prio = body.get("max_priority")
    if raw_prio is None or raw_prio == "":
        return ("Q", "W", "E")
    if isinstance(raw_prio, str) and "," not in raw_prio and len(raw_prio) == 3:
        return tuple(raw_prio.upper())  # type: ignore[return-value]
    parts = _coerce_str_list(raw_prio, "max_priority")
    if len(parts) != 3:
        raise _ApiError(400, f"max_priority: expected 3 keys, got {parts!r}")
    return tuple(p.upper() for p in parts)  # type: ignore[return-value]


def _parse_form_index(body: dict) -> Optional[dict[str, int]]:
    """Decode the optional ``form_index`` body field — JSON dict only."""
    raw_form = body.get("form_index")
    if isinstance(raw_form, dict):
        return {str(k).upper(): int(v) for k, v in raw_form.items()}
    return None


def _parse_combo_sequence(body: dict) -> tuple[str, ...]:
    """Decode the ``combo_sequence`` body field for /burst + /rank-assassin.

    Accepts None (returns engine default Q→W→E→AA→R→AA) / list / dash-string
    ("Q-W-E-AA-R-AA") / comma-string ("Q,W,E,AA,R,AA"). The engine validates
    individual tokens — this helper just normalizes the list shape.
    """
    raw = body.get("combo_sequence")
    if raw is None or raw == "":
        return DEFAULT_COMBO_SEQUENCE
    if isinstance(raw, str):
        # Dash-separated wins (no ambiguity); fall through to comma.
        sep = "-" if "-" in raw else ","
        parts = [p.strip() for p in raw.split(sep) if p.strip()]
    else:
        parts = _coerce_str_list(raw, "combo_sequence")
    if not parts:
        raise _ApiError(400, "combo_sequence: empty after parse")
    return tuple(parts)


def _route_ability_dps(body: dict) -> dict:
    """POST /ability-dps — per-spell ability DPS for the caster build.

    Phase 4b (s178, 2026-05-12). Body mirrors /dps with three additions:
      * ``target_current_hp_pct`` (float, default 1.0) — what fraction
        of max HP the target sits at when the cast lands; affects
        ``target_current_hp_pct`` / ``target_missing_hp_pct`` blocks
      * ``max_priority`` (str or list, default "QWE") — three keys
        describing max order; comma-separated as a query param
      * ``block_strategy`` (str, default "first") — how to combine
        multi-block abilities; one of first|sum|max
      * ``form_index`` (dict) — per-key form overrides for multi-form
        abilities (Aphelios weapons, Jayce stance); JSON only
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    target_max_hp = _opt_float(body, "target_max_hp", 0.0)
    target_bonus_hp = _opt_float(body, "target_bonus_hp", 0.0)
    target_current_hp_pct = _opt_float(body, "target_current_hp_pct", 1.0)
    augments = _coerce_str_list(body.get("augments"), "augments")
    block_strategy = _opt_str(body, "block_strategy", "first") or "first"
    max_priority = _parse_max_priority(body)
    form_index_overrides = _parse_form_index(body)
    try:
        result = compute_ability_dps(
            snap, champion_id=champion, level=level,
            item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            target_current_hp_pct=target_current_hp_pct,
            augments=augments,
            max_priority=max_priority,
            block_strategy=block_strategy,
            form_index_overrides=form_index_overrides,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank_mage(body: dict) -> dict:
    """POST /rank-mage — rank items by total-ability-DPS delta.

    Phase 4c (s179, 2026-05-12). Body is the union of /ability-dps and
    /rank parameters: ``target_*`` + ``target_current_hp_pct`` for the
    cast formula plus ``budget`` / ``slots`` / ``top`` / ``sort`` /
    ``include_components`` / ``only`` / ``filter_shared_uniques`` for the
    candidate-filtering pipeline shared with the other rankers.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    target_max_hp = _opt_float(body, "target_max_hp", 0.0)
    target_bonus_hp = _opt_float(body, "target_bonus_hp", 0.0)
    target_current_hp_pct = _opt_float(body, "target_current_hp_pct", 1.0)
    augments = _coerce_str_list(body.get("augments"), "augments")
    block_strategy = _opt_str(body, "block_strategy", "first") or "first"
    max_priority = _parse_max_priority(body)
    form_index_overrides = _parse_form_index(body)
    budget = _opt_int(body, "budget", None)
    slot_count = _opt_int(body, "slots", 6) or 6
    top_n = _opt_int(body, "top", 20)
    if top_n is None:
        top_n = 20
    sort_by = _opt_str(body, "sort", "delta") or "delta"
    if sort_by not in SORT_KEYS:
        raise _ApiError(400, f"sort: must be one of {list(SORT_KEYS)}, got {sort_by!r}")
    include_components = _opt_bool(body, "include_components", False)
    filter_shared_uniques = _opt_bool(body, "filter_shared_uniques", True)
    only_ids: Optional[list[str]] = None
    if "only" in body and body["only"] not in (None, ""):
        only_ids = _coerce_str_list(body["only"], "only")
    try:
        result = rank_items_by_ability_dps(
            snap,
            champion_id=champion, level=level,
            current_item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            target_current_hp_pct=target_current_hp_pct,
            budget=budget, slot_count=slot_count, top_n=top_n,
            include_components=include_components,
            only_item_ids=only_ids, sort_by=sort_by,
            augments=augments,
            max_priority=max_priority,
            block_strategy=block_strategy,
            form_index_overrides=form_index_overrides,
            filter_shared_uniques=filter_shared_uniques,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_burst(body: dict) -> dict:
    """POST /burst — single-combo burst damage for the caster build.

    Phase 5 (s180, 2026-05-13). Body mirrors /ability-dps with one
    addition:
      * ``combo_sequence`` (list or "Q-W-E-AA-R-AA") — tokens to fire;
        AA = auto-attack, P/Q/W/E/R = one cast, Q2/W2/E2/R2 = repeat
        at same rank. Default: ("Q","W","E","AA","R","AA").
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    target_max_hp = _opt_float(body, "target_max_hp", 0.0)
    target_bonus_hp = _opt_float(body, "target_bonus_hp", 0.0)
    target_current_hp_pct = _opt_float(body, "target_current_hp_pct", 1.0)
    augments = _coerce_str_list(body.get("augments"), "augments")
    block_strategy = _opt_str(body, "block_strategy", "first") or "first"
    max_priority = _parse_max_priority(body)
    form_index_overrides = _parse_form_index(body)
    combo_sequence = _parse_combo_sequence(body)
    try:
        result = compute_burst_damage(
            snap, champion_id=champion, level=level,
            item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            target_current_hp_pct=target_current_hp_pct,
            augments=augments,
            max_priority=max_priority,
            block_strategy=block_strategy,
            form_index_overrides=form_index_overrides,
            combo_sequence=combo_sequence,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank_assassin(body: dict) -> dict:
    """POST /rank-assassin — rank items by total-burst-damage delta.

    Phase 5 (s180, 2026-05-13). Body is the union of /burst and /rank
    parameters: ``target_*`` + ``target_current_hp_pct`` + ``combo_sequence``
    for the burst formula plus ``budget`` / ``slots`` / ``top`` / ``sort`` /
    ``include_components`` / ``only`` / ``filter_shared_uniques`` for the
    candidate-filtering pipeline shared with the other rankers.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    target_max_hp = _opt_float(body, "target_max_hp", 0.0)
    target_bonus_hp = _opt_float(body, "target_bonus_hp", 0.0)
    target_current_hp_pct = _opt_float(body, "target_current_hp_pct", 1.0)
    augments = _coerce_str_list(body.get("augments"), "augments")
    block_strategy = _opt_str(body, "block_strategy", "first") or "first"
    max_priority = _parse_max_priority(body)
    form_index_overrides = _parse_form_index(body)
    combo_sequence = _parse_combo_sequence(body)
    budget = _opt_int(body, "budget", None)
    slot_count = _opt_int(body, "slots", 6) or 6
    top_n = _opt_int(body, "top", 20)
    if top_n is None:
        top_n = 20
    sort_by = _opt_str(body, "sort", "delta") or "delta"
    if sort_by not in SORT_KEYS:
        raise _ApiError(400, f"sort: must be one of {list(SORT_KEYS)}, got {sort_by!r}")
    include_components = _opt_bool(body, "include_components", False)
    filter_shared_uniques = _opt_bool(body, "filter_shared_uniques", True)
    only_ids: Optional[list[str]] = None
    if "only" in body and body["only"] not in (None, ""):
        only_ids = _coerce_str_list(body["only"], "only")
    try:
        result = rank_items_by_burst(
            snap,
            champion_id=champion, level=level,
            current_item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            target_current_hp_pct=target_current_hp_pct,
            budget=budget, slot_count=slot_count, top_n=top_n,
            include_components=include_components,
            only_item_ids=only_ids, sort_by=sort_by,
            augments=augments,
            max_priority=max_priority,
            block_strategy=block_strategy,
            form_index_overrides=form_index_overrides,
            combo_sequence=combo_sequence,
            filter_shared_uniques=filter_shared_uniques,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _opt_targets_override(body: dict) -> Optional[float]:
    """Phase 6 — optional targets_per_proc_override (float). None when absent."""
    key = "targets_per_proc_override"
    if key not in body or body[key] in (None, ""):
        return None
    try:
        return float(body[key])
    except (TypeError, ValueError):
        raise _ApiError(400, f"{key}: expected number, got {body[key]!r}")


def _route_hps(body: dict) -> dict:
    """POST /hps — total healing+shielding+buff throughput for the build.

    Phase 6 (s181, 2026-05-13). Body shape mirrors /ehp's caster-only
    schema (no target_armor/_mr/_max_hp — these don't affect outgoing
    heals/shields). Optional ``targets_per_proc_override`` (float)
    replaces the per-item curated targets count for ALL items in the
    build — useful for Arena 2v2 scenarios (override=1).
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    augments = _coerce_str_list(body.get("augments"), "augments")
    targets_override = _opt_targets_override(body)
    try:
        result = compute_hps(
            snap, champion_id=champion, level=level,
            item_ids=items, mode=mode,
            augments=augments,
            targets_per_proc_override=targets_override,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank_enchanter(body: dict) -> dict:
    """POST /rank-enchanter — rank items by total-throughput delta.

    Phase 6 (s181, 2026-05-13). Mirror of /rank-tank for the HPS scorer.
    No target_* fields — outgoing healing doesn't care about enemy
    resists. Optional ``enchanter_only`` (bool, default True) restricts
    the candidate pool to the curated enchanter formulas registry; set
    False to score every candidate (most will tie at delta=0).
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    augments = _coerce_str_list(body.get("augments"), "augments")
    targets_override = _opt_targets_override(body)
    budget = _opt_int(body, "budget", None)
    slot_count = _opt_int(body, "slots", 6) or 6
    top_n = _opt_int(body, "top", 20)
    if top_n is None:
        top_n = 20
    sort_by = _opt_str(body, "sort", "delta") or "delta"
    if sort_by not in SORT_KEYS:
        raise _ApiError(400, f"sort: must be one of {list(SORT_KEYS)}, got {sort_by!r}")
    include_components = _opt_bool(body, "include_components", False)
    filter_shared_uniques = _opt_bool(body, "filter_shared_uniques", True)
    enchanter_only = _opt_bool(body, "enchanter_only", True)
    only_ids: Optional[list[str]] = None
    if "only" in body and body["only"] not in (None, ""):
        only_ids = _coerce_str_list(body["only"], "only")
    try:
        result = rank_items_by_hps(
            snap,
            champion_id=champion, level=level,
            current_item_ids=items, mode=mode,
            budget=budget, slot_count=slot_count, top_n=top_n,
            include_components=include_components,
            only_item_ids=only_ids, sort_by=sort_by,
            augments=augments,
            filter_shared_uniques=filter_shared_uniques,
            targets_per_proc_override=targets_override,
            enchanter_only=enchanter_only,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_beam(body: dict) -> dict:
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    target_max_hp = _opt_float(body, "target_max_hp", 0.0)
    target_bonus_hp = _opt_float(body, "target_bonus_hp", 0.0)
    phase = _opt_str(body, "phase")
    if phase is not None and phase not in ("early", "mid", "late"):
        raise _ApiError(400, f"phase: must be early|mid|late, got {phase!r}")
    slot_count = _opt_int(body, "slots", 6) or 6
    beam_width = _opt_int(body, "beam_width", DEFAULT_BEAM_WIDTH) or DEFAULT_BEAM_WIDTH
    top_n = _opt_int(body, "top", BEAM_DEFAULT_TOP_N) or BEAM_DEFAULT_TOP_N
    total_budget = _opt_int(body, "total_budget", None)
    include_components = _opt_bool(body, "include_components", False)
    boots_unique = _opt_bool(body, "boots_unique", True)
    only_ids: Optional[list[str]] = None
    if "only" in body and body["only"] not in (None, ""):
        only_ids = _coerce_str_list(body["only"], "only")
    try:
        result = beam_search_build(
            snap,
            champion_id=champion, level=level,
            current_item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp,
            target_bonus_hp=target_bonus_hp,
            phase=phase,
            slot_count=slot_count, beam_width=beam_width, top_n=top_n,
            total_budget=total_budget,
            include_components=include_components,
            only_item_ids=only_ids,
            boots_unique=boots_unique,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_health() -> dict:
    try:
        snap = _CACHE.get()
        return {
            "status": "ok",
            "engine_version": ENGINE_VERSION,
            "patch": snap.patch,
            "champions": len(snap.champions),
            "items": len(snap.items),
        }
    except RuntimeError:
        return {
            "status": "loading",
            "engine_version": ENGINE_VERSION,
            "patch": None,
            "champions": 0,
            "items": 0,
        }


def _route_snapshot() -> dict:
    snap = _CACHE.get()
    manifest = snap.manifest or {}
    return {
        "patch": snap.patch,
        "champions": len(snap.champions),
        "items": len(snap.items),
        "scenarios_by_id": len(snap.scenarios_by_id),
        "scenarios_by_lolmath": len(snap.scenarios_by_lolmath),
        "manifest": {
            "phase": manifest.get("phase"),
            "extracted_at": manifest.get("extracted_at"),
            "ddragon_version": manifest.get("ddragon_version"),
            "sources": manifest.get("sources"),
            "counts": manifest.get("counts"),
        },
    }


# ---------------------------------------------------------------- dispatcher


_POST_ROUTES = {
    "/stats": _route_stats,
    "/dps": _route_dps,
    "/rank": _route_rank,
    "/beam": _route_beam,
    "/ehp": _route_ehp,
    "/rank-tank": _route_rank_tank,
    "/hybrid": _route_hybrid,
    "/rank-bruiser": _route_rank_bruiser,
    "/ability-dps": _route_ability_dps,
    "/rank-mage": _route_rank_mage,
    "/burst": _route_burst,
    "/rank-assassin": _route_rank_assassin,
    "/hps": _route_hps,
    "/rank-enchanter": _route_rank_enchanter,
}

# GET routes that need a body merge from query params for the same handler.
_GET_DISPATCH_ROUTES = set(_POST_ROUTES.keys())


class Handler(BaseHTTPRequestHandler):
    server_version = f"DaemonSlayer/{ENGINE_VERSION}"

    # Quiet the default access-log spam — we surface our own.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        _log.debug("%s - %s", self.address_string(), format % args)

    # ----- helpers

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_error(self, status: int, message: str, detail: Any = None) -> None:
        payload: dict[str, Any] = {"error": message, "status": status}
        if detail is not None:
            payload["detail"] = detail
        self._send_json(status, payload)

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise _ApiError(400, f"invalid JSON body: {e}")
        if not isinstance(data, dict):
            raise _ApiError(400, "JSON body must be an object")
        return data

    def _query_to_body(self, query: str) -> dict:
        if not query:
            return {}
        parsed = parse_qs(query, keep_blank_values=False)
        # Collapse single-value lists; keep multi-value as comma-separated for
        # caller convenience (matches the JSON-list form via _coerce_str_list).
        out: dict[str, Any] = {}
        for key, values in parsed.items():
            if len(values) == 1:
                out[key] = values[0]
            else:
                out[key] = ",".join(values)
        return out

    # ----- entry points

    def _index_payload(self) -> str:
        try:
            snap = _CACHE.get()
            patch = snap.patch
            n_champ = len(snap.champions)
            n_items = len(snap.items)
        except RuntimeError:
            patch = "loading"
            n_champ = 0
            n_items = 0
        return _INDEX_HTML.format(
            version=ENGINE_VERSION, patch=patch,
            n_champ=n_champ, n_items=n_items,
            port=self.server.server_address[1],
        )

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        try:
            if path in ("", "/"):
                self._send_html(200, self._index_payload())
                return
            if path == "/health":
                self._send_json(200, _route_health())
                return
            if path == "/snapshot":
                self._send_json(200, _route_snapshot())
                return
            if path in _GET_DISPATCH_ROUTES:
                body = self._query_to_body(url.query)
                payload = _POST_ROUTES[path](body)
                self._send_json(200, payload)
                return
            self._send_error(404, f"no such route: {path}")
        except _ApiError as e:
            self._send_error(e.status, e.message, e.detail)
        except Exception as e:  # noqa: BLE001
            _log.exception("unhandled error in GET %s", path)
            self._send_error(500, f"internal error: {e}")

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        try:
            if path not in _POST_ROUTES:
                self._send_error(404, f"no such route: {path}")
                return
            body = self._read_json_body()
            # Allow query-string overrides on POST too — handy for testing.
            if url.query:
                merged = self._query_to_body(url.query)
                merged.update(body)
                body = merged
            payload = _POST_ROUTES[path](body)
            self._send_json(200, payload)
        except _ApiError as e:
            self._send_error(e.status, e.message, e.detail)
        except Exception as e:  # noqa: BLE001
            _log.exception("unhandled error in POST %s", path)
            self._send_error(500, f"internal error: {e}")


# ---------------------------------------------------------------- bootstrap


def start_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    snapshot: Optional[DataSnapshot] = None,
    patch: Optional[str] = None,
    data_root: Optional[Path] = None,
) -> ThreadingHTTPServer:
    """Create and return a server bound to ``host:port``. Caller drives the
    serving loop (``server.serve_forever()`` for blocking, or
    ``threading.Thread(target=server.serve_forever)`` for a daemon thread).

    A snapshot can be injected directly (test path) or loaded from disk
    via the ``patch`` / ``data_root`` overrides.
    """
    if snapshot is None:
        snapshot = _load_default_snapshot(patch=patch, data_root=data_root)
    _CACHE.set(snapshot)
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


def serve_forever(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                  patch: Optional[str] = None,
                  data_root: Optional[Path] = None) -> int:
    """Blocking entry point used by the CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        srv = start_server(host=host, port=port, patch=patch, data_root=data_root)
    except SnapshotNotFound as e:
        _log.error("snapshot not found: %s", e)
        return 2
    snap = _CACHE.get()
    _log.info("Daemon Slayer engine v%s on http://%s:%d  (patch %s, %d champions, %d items)",
              ENGINE_VERSION, host, port, snap.patch,
              len(snap.champions), len(snap.items))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        _log.info("shutting down")
    finally:
        srv.server_close()
    return 0

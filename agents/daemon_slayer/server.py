"""Phase 3 - local HTTP server for the Daemon Slayer engine.

Wraps `stats`, `dps`, `rank` (and snapshot metadata) in plain-HTTP routes
on `:8893`. Stdlib ``ThreadingHTTPServer`` to match the rest of RC; no
FastAPI/aiohttp dependency. Snapshot is loaded once at startup and held
in memory - patch hot-reload lands in Phase 7 alongside the supervisor
entry.

Routes (all accept GET with query params for read-only sanity checking;
POST + JSON body is the contract for production callers):

  GET  /                  - index page with usage examples
  GET  /health            - engine + snapshot health
  GET  /snapshot          - patch + counts + manifest excerpt
  POST /stats             - body: {champion, level, items?, mode?}
  POST /dps               - body: {champion, level, items?, mode?,
                                    target_armor?, target_mr?,
                                    target_max_hp?, phase?}
  POST /rank              - body: {champion, level, items?, mode?,
                                    target_armor?, target_mr?,
                                    target_max_hp?, phase?,
                                    budget?, slots?, top?, sort?,
                                    include_components?, only?}
  POST /beam              - body: {champion, level, items?, mode?,
                                    target_armor?, target_mr?,
                                    target_max_hp?, phase?,
                                    slots?, beam_width?, top?,
                                    total_budget?, include_components?,
                                    only?, boots_unique?}

Errors map to:
  400 - body parse failure, missing required field, bad enum value
  404 - unknown champion or item id (KeyError from engine)
  422 - value-out-of-range / engine ValueError
  500 - anything unexpected
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from . import ENGINE_VERSION
from .abilities import AbilitiesSnapshot
from .ability_dps import (
    _BLOCK_INDEX_CONDITIONS,
    _BLOCK_INDEX_DEFAULT_KEY,
    compute_ability_dps,
    rank_items_by_ability_dps,
)
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
from .fight_report import compute_fight_report
from .hps import compute_hps, rank_items_by_hps
from .hybrid import compute_hybrid, rank_items_by_hybrid
from .cc_output import compute_cc_output
from .mobility import compute_mobility
from .sustain import compute_sustain
from .scaling import compute_scaling
from .waveclear import compute_waveclear
from .threatrange import compute_threatrange
from .zonecontrol import compute_zonecontrol
from .objdamage import compute_objdamage
from .allyamp import compute_allyamp
from .antitank import compute_antitank, compute_antitank_live
from .dsp_live_consumers import (
    ally_protected_ehp,
    enemy_rune_threat,
    summoner_fight_adjustments,
)
from .extendedduel import compute_extendedduel
from .matchup import compute_matchup
from .onhit_dps import rank_items_by_onhit
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
<h1>Daemon Slayer engine - v{version}</h1>
<p class=ok>snapshot patch <code>{patch}</code> &middot; {n_champ} champions &middot; {n_items} items</p>

<h2>Routes</h2>
<table>
<tr><th>method</th><th>path</th><th>purpose</th></tr>
<tr><td>GET</td><td><a href=/health>/health</a></td><td>liveness + version</td></tr>
<tr><td>GET</td><td><a href=/snapshot>/snapshot</a></td><td>patch + counts</td></tr>
<tr><td>GET</td><td><a href=/modifier-summary>/modifier-summary</a></td><td>ability modifier-block taxonomy (diagnostic)</td></tr>
<tr><td>POST</td><td>/stats</td><td>resolve champion stats at level + items</td></tr>
<tr><td>POST</td><td>/dps</td><td>auto-attack DPS over rotation scenarios</td></tr>
<tr><td>POST</td><td>/rank</td><td>rank items by DPS delta</td></tr>
<tr><td>POST</td><td>/beam</td><td>full-build beam search (top-N complete builds)</td></tr>
<tr><td>POST</td><td>/ehp</td><td>caster Effective HP under an enemy damage profile (Phase 1)</td></tr>
<tr><td>POST</td><td>/rank-tank</td><td>rank items by EHP delta (Phase 1)</td></tr>
<tr><td>POST</td><td>/hybrid</td><td>bruiser combined DPS+EHP score (Phase 2)</td></tr>
<tr><td>POST</td><td>/rank-bruiser</td><td>rank items by weighted (alpha*dps + beta*ehp) delta (Phase 2)</td></tr>
<tr><td>POST</td><td>/ability-dps</td><td>per-spell ability DPS for a mage / caster build (Phase 4b)</td></tr>
<tr><td>POST</td><td>/rank-mage</td><td>rank items by total-ability-DPS delta (Phase 4c)</td></tr>
<tr><td>POST</td><td>/rank-onhit</td><td>rank items by combined on-hit AP DPS delta (Slice B)</td></tr>
<tr><td>POST</td><td>/burst</td><td>single-combo total burst damage for an assassin build (Phase 5)</td></tr>
<tr><td>POST</td><td>/rank-assassin</td><td>rank items by total-burst-damage delta (Phase 5)</td></tr>
<tr><td>POST</td><td>/hps</td><td>total healing+shielding+buff throughput for an enchanter build (Phase 6)</td></tr>
<tr><td>POST</td><td>/rank-enchanter</td><td>rank items by total-throughput delta (Phase 6)</td></tr>
<tr><td>POST</td><td>/cc-output</td><td>offensive crowd-control (lockdown) score for a champion (item 294)</td></tr>
<tr><td>POST</td><td>/mobility</td><td>self-mobility (gap-close / kiting) score for a champion (item 297)</td></tr>
<tr><td>POST</td><td>/sustain</td><td>sustain / vamp-throughput (damage-conversion + regen) score for a champion (item 298)</td></tr>
<tr><td>POST</td><td>/scaling</td><td>scaling / power-curve (early/mid/late power + signed slope) for a champion (item 299)</td></tr>
<tr><td>POST</td><td>/waveclear</td><td>wave-clear / AoE-shove (range-weighted clear score + top kind + ranged-shove flag) for a champion (item 300)</td></tr>
<tr><td>POST</td><td>/threat-range</td><td>effective threat-range (reach-weighted damage/CC score + top band + artillery flag) for a champion (item 301)</td></tr>
<tr><td>POST</td><td>/zone-control</td><td>zone-control / area-denial (denial-weighted persistence score + top kind + controls-terrain flag) for a champion (item 302)</td></tr>
<tr><td>POST</td><td>/objective-damage</td><td>objective / structure-damage (kind-weighted scope-scaled score + top kind + pressures-structures flag) for a champion (item 303)</td></tr>
<tr><td>POST</td><td>/ally-amp</td><td>ally-amplification / buff-throughput (kind-weighted reach-scaled score + top kind + saves-ally flag) for a champion (item 304)</td></tr>
<tr><td>POST</td><td>/anti-tank</td><td>anti-tank / %HP-damage + resist-shred (kind-weighted cadence-scaled score + top kind + shreds-resist flag) for a champion (item 308; optional live level ramp + item_ids live build, OQ18)</td></tr>
<tr><td>POST</td><td>/summoner-fight-adj</td><td>DSP5 live summoner-spell combat adjustments - self/enemy summoner sets folded to EHP/tenacity/MS/DR/antiheal (OQ18)</td></tr>
<tr><td>POST</td><td>/enemy-rune-threat</td><td>DSP6 enemy-rune incoming-threat fold - PtA amp / Conqueror ramp / Grasp poke-sustain / antiheal + ehp_divisor (OQ18)</td></tr>
<tr><td>POST</td><td>/ally-protected-ehp</td><td>DSP7 ally-enchanter-protected EHP - an ally's EHP with its live teammates' shield/heal/resist grants folded in (OQ18)</td></tr>
<tr><td>POST</td><td>/extended-duel</td><td>extended-dueling / 1v1 sustained-fight (kind-weighted cadence-scaled score + top kind + ramps flag) for a champion (item 309)</td></tr>
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


class _AbilitiesOverrideCache:
    """RM-115 / A-03 / RM-81: lazy holder for the OVERRIDE-ON abilities snapshot.

    ``apply_ability_base_overrides`` is a load-time kwarg on
    ``AbilitiesSnapshot.load`` (abilities.py:1006), not a per-call ranking
    flag, and ``abilities.load_default()`` (abilities.py:1302-1315) is keyless
    - it caches ONE snapshot for the process and cannot represent both states.

    Rather than key that global cache, this holder builds the flag-ON snapshot
    once (~30 ms) and hands it to the engine through the ``abilities_snapshot``
    kwarg the rankers already accept. ``get(False)`` returns ``None`` so the
    OFF path falls through to ``load_default()`` exactly as before - the
    default request stays byte-identical, and no OFF-path allocation is added.
    """

    def __init__(self) -> None:
        self._on: Optional[AbilitiesSnapshot] = None
        self._lock = threading.Lock()

    def get(self, apply_overrides: bool) -> Optional[AbilitiesSnapshot]:
        if not apply_overrides:
            return None
        with self._lock:
            if self._on is None:
                self._on = AbilitiesSnapshot.load(
                    apply_ability_base_overrides=True
                )
            return self._on

    def reset(self) -> None:
        """Test hook - drop the memoized flag-ON snapshot."""
        with self._lock:
            self._on = None


_ABIL_CACHE = _AbilitiesOverrideCache()


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


def _coerce_int_list(value: Any, field_name: str) -> list[int]:
    """Coerce a list / comma-string of ids to ``list[int]``, dropping any
    non-numeric token (fail-soft - a junk summoner / rune id contributes 0.0
    downstream rather than 400-ing the whole request)."""
    out: list[int] = []
    for tok in _coerce_str_list(value, field_name):
        try:
            out.append(int(tok))
        except (TypeError, ValueError):
            continue
    return out


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
        f = float(v)
    except (TypeError, ValueError):
        raise _ApiError(400, f"{key}: expected number, got {v!r}")
    # Reject NaN / +-inf: a non-finite stat input is never legitimate and
    # json.dumps would emit a bare NaN/Infinity token, which is invalid JSON
    # that breaks the dashboard's JSON.parse downstream (finding class 1).
    if not math.isfinite(f):
        raise _ApiError(400, f"{key}: must be a finite number, got {v!r}")
    return f


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
# Direct lookup raised 404 -> coaches caught + dropped DS rows silently
# -> daemon_slayer_picks never written -> dashboard #ds-pill stayed hidden
# -> user saw "ds not loaded at all" mid-game on Kai'Sa.
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
        #   exact display ("Kai'Sa") * lowercase display ("kai'sa")
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
    return name  # let the engine raise the canonical KeyError -> 404


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
    apply_mode_modifiers = _opt_bool(body, "apply_mode_modifiers", False)
    apply_ability_amps = _opt_bool(body, "apply_ability_amps", False)
    apply_passive_damage = _opt_bool(body, "apply_passive_damage", False)
    # R7 / R12 seam flags (DEFAULT-OFF -> byte-identical when the body omits them).
    # Scoped to /dps: rank_items() does NOT forward these to compute_dps, so the
    # clean wiring point is the direct compute_dps route. compute_dps accepts both
    # (dps.py: assume_passive_as_stacks, apply_target_vuln).
    #   assume_passive_as_stacks (R7) - assume the per-stack champion self-AS
    #     passive is at max stacks (folded onto base AS).
    #   apply_target_vuln (R12) - resolve the target-vulnerability damage multiplier.
    assume_passive_as_stacks = _opt_bool(body, "assume_passive_as_stacks", False)
    apply_target_vuln = _opt_bool(body, "apply_target_vuln", False)
    # OQ17 / B1: apply_melee_aa_gate drops a ranged_only on-hit proc (Runaan's
    # Wind's Fury bolts) on a melee champ. DEFAULT-OFF -> byte-identical when
    # omitted; /dps-scoped like R7/R12 (rank_items does NOT forward it). The live
    # default-ON flip stays EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md).
    apply_melee_aa_gate = _opt_bool(body, "apply_melee_aa_gate", False)
    if phase is not None and phase not in ("early", "mid", "late"):
        raise _ApiError(400, f"phase: must be early|mid|late, got {phase!r}")
    try:
        result = compute_dps(snap, champion_id=champion, level=level,
                             item_ids=items, mode=mode,
                             target_armor=target_armor, target_mr=target_mr,
                             target_max_hp=target_max_hp,
                             target_bonus_hp=target_bonus_hp,
                             phase=phase, augments=augments,
                             apply_mode_modifiers=apply_mode_modifiers,
                             apply_ability_amps=apply_ability_amps,
                             apply_passive_damage=apply_passive_damage,
                             assume_passive_as_stacks=assume_passive_as_stacks,
                             apply_target_vuln=apply_target_vuln,
                             apply_melee_aa_gate=apply_melee_aa_gate)
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
    apply_mode_modifiers = _opt_bool(body, "apply_mode_modifiers", False)
    # /rank seam flags (DEFAULT-OFF -> byte-identical when the body omits them):
    #   exempt_offclass_by_win (DSP2) - un-strip the off-class items a caster-marksman
    #     genuinely wins on (Ezreal/Corki/Smolder Trinity Force / Spear of Shojin).
    #   prefer_kit_axis_by_win (DSP11) - float a champ's WIN-anchored kit-axis items.
    #   cost_ceiling (F2) - drop candidates above the gold ceiling.
    #   widen_carry_pool (RM-04 A-01) - class-wide un-strip of Black Cleaver /
    #     Spear of Shojin / Stridebreaker / Sterak's Gage for ranged marksmen.
    exempt_offclass_by_win = _opt_bool(body, "exempt_offclass_by_win", False)
    prefer_kit_axis_by_win = _opt_bool(body, "prefer_kit_axis_by_win", False)
    widen_carry_pool = _opt_bool(body, "widen_carry_pool", False)
    cost_ceiling = _opt_int(body, "cost_ceiling", None)
    # R55: the target_current_hp_pct seam now reaches rank_items (carry/dps
    # scorer) too. Default 1.0 -> byte-identical when the body omits it. NOTE
    # /dps (the direct compute_dps route above) still does NOT forward this
    # param per the R7/R12 comment; /rank forwards it via rank_items instead.
    target_current_hp_pct = _opt_float(body, "target_current_hp_pct", 1.0)
    # Per-champ burst-carry calibration (Jhin pilot): a SHORT fight_length
    # engages rank_items' burst-vs-sustained blend. Absent -> None -> byte-
    # identical default ranking (no burst compute paid). The client sets it
    # from the champion -> fight_length allow-map at the carry chokepoint.
    fight_length = _opt_float(body, "fight_length", None)
    # RM-35 clause 2 (A-08): the RM-41 SYMMETRIC off-axis strip, extended from
    # the assassin/burst route to the CARRY route. DEFAULT-OFF -> byte-identical.
    # Reuses the existing champion_burst_axis gate, no new curated list.
    exclude_off_axis_items = _opt_bool(body, "exclude_off_axis_items", False)
    # RM-86 L1 kit-conversion gate, route-exposed (PART 7 prerequisite slice,
    # docs/OPEN_ITEMS_REVIEW_2026-07-25.md:451-457). rank.py:1294-1297 consults
    # the registry ONLY when the strength is > 0.0, so the 0.0 default performs
    # no lookup and no arithmetic and is byte-identical to omitting the key.
    # Until this landed the lever was Python-API-only, and
    # tools/daemon_slayer_build_orders_generate.py drives the shipped build
    # tables through :8893 - so no kit-conversion fix could reach an artifact.
    kit_conversion_strength = _opt_float(body, "kit_conversion_strength", 0.0)
    # A-12 / RM-46 crit conversion (Ashe Frost Shot: ad * (1 + 1.15c), and
    # Infinity Edge's bonus crit damage REPLACED rather than added, because her
    # passive states critical strikes deal no additional damage). Registry is
    # _crit_conversion_overrides.py, gate at dps.py:890. Route-exposed for the
    # same reason as kit_conversion_strength above: the shipped build tables are
    # generated through :8893, so a Python-API-only seam cannot reach them.
    apply_crit_conversion = _opt_bool(body, "apply_crit_conversion", False)
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
            fight_length=fight_length,
            apply_mode_modifiers=apply_mode_modifiers,
            exempt_offclass_by_win=exempt_offclass_by_win,
            prefer_kit_axis_by_win=prefer_kit_axis_by_win,
            widen_carry_pool=widen_carry_pool,
            cost_ceiling=cost_ceiling,
            target_current_hp_pct=target_current_hp_pct,
            exclude_off_axis_items=exclude_off_axis_items,
            kit_conversion_strength=kit_conversion_strength,
            apply_crit_conversion=apply_crit_conversion,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_ehp(body: dict) -> dict:
    """POST /ehp - compute Effective HP for the caster build.

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
    enemies = _coerce_str_list(body.get("enemies"), "enemies")
    include_conditional = _opt_bool(body, "include_conditional", False)
    apply_mode_modifiers = _opt_bool(body, "apply_mode_modifiers", False)
    apply_passive_mitigation = _opt_bool(body, "apply_passive_mitigation", False)
    apply_passive_resist = _opt_bool(body, "apply_passive_resist", False)
    apply_passive_revive = _opt_bool(body, "apply_passive_revive", False)
    # ENGINE 1.102.0 (2026-06-03): GAP-2 SIXTH survivability axis - an
    # ALLY-TARGETED grant a TEAMMATE confers (Orianna E / Braum W / Taric W resist,
    # Renata W revive). The generic external inputs default to the no-op
    # 0.0/0.0/1.0 -> byte-identical route response. Source them from
    # ``_passive_ally_grant_overrides.ally_resist_grant`` / ``ally_revive_multiplier``.
    external_resist_armor = _opt_float(body, "external_resist_armor", 0.0)
    external_resist_mr = _opt_float(body, "external_resist_mr", 0.0)
    external_revive_multiplier = _opt_float(body, "external_revive_multiplier", 1.0)
    # ENGINE 1.103.0 (2026-06-03): GAP-2 SEVENTH survivability axis - the
    # champion's INNATE tenacity / CC-immunity ability (Garen W / Olaf R /
    # Malzahar P) feeding the cc_blended discount. Default off -> byte-identical.
    apply_champion_tenacity = _opt_bool(body, "apply_champion_tenacity", False)
    # ENGINE 1.104.0 (item 292): GAP-2 EIGHTH survivability axis - the champion's
    # SELF spell-shield / block-one CC ability (Sivir E / Nocturne W / Fiora W /
    # Morgana E self). Default off -> byte-identical.
    apply_spell_shield = _opt_bool(body, "apply_spell_shield", False)
    # R104 (ENGINE 1.197.0): item-side spell-shield / block-next-ability passive
    # (Banshee's Veil 3102 / Edge of Night 3814 / Verdant Barrier 4632 "Annul").
    # The item lane of the champion spell-shield axis. Default off -> byte-identical.
    apply_item_spell_shield = _opt_bool(body, "apply_item_spell_shield", False)
    apply_item_mana_health = _opt_bool(body, "apply_item_mana_health", False)
    apply_item_resist_grants = _opt_bool(body, "apply_item_resist_grants", False)
    apply_rune_resist_grants = _opt_bool(body, "apply_rune_resist_grants", False)
    rune_ids = _coerce_str_list(body.get("rune_ids"), "rune_ids")
    apply_rune_health_grants = _opt_bool(body, "apply_rune_health_grants", False)
    apply_rune_hsp_amp = _opt_bool(body, "apply_rune_hsp_amp", False)
    # R137 (ENGINE 1.226.0, RM-99): item permanent-HP-per-proc stack (Heartsteel).
    assume_item_health_stacks = _opt_bool(body, "assume_item_health_stacks", False)
    apply_rune_flat_mitigation = _opt_bool(body, "apply_rune_flat_mitigation", False)
    assume_item_proc_heal = _opt_bool(body, "assume_item_proc_heal", False)
    apply_item_bonus_hp_amp = _opt_bool(body, "apply_item_bonus_hp_amp", False)
    assume_item_general_dr = _opt_bool(body, "assume_item_general_dr", False)
    # ENGINE 1.105.0 (item 293): GAP-2 NINTH survivability axis - the champion's
    # SELF guaranteed-survival window (untargetable / stasis / invuln: Tryndamere R
    # / Kindred R / Taric R / Kayle R self / Lissandra R self / Xayah R / Vladimir W
    # / Elise E / Fizz E / Mel W). Default off -> byte-identical.
    apply_survival_window = _opt_bool(body, "apply_survival_window", False)
    try:
        result = compute_ehp(
            snap, champion_id=champion, level=level,
            item_ids=items, mode=mode,
            enemy_ad_share=enemy_ad_share,
            enemy_ap_share=enemy_ap_share,
            augments=augments,
            enemy_champions=enemies,
            include_conditional=include_conditional,
            apply_mode_modifiers=apply_mode_modifiers,
            apply_passive_mitigation=apply_passive_mitigation,
            apply_passive_resist=apply_passive_resist,
            apply_passive_revive=apply_passive_revive,
            apply_champion_tenacity=apply_champion_tenacity,
            apply_spell_shield=apply_spell_shield,
            apply_item_spell_shield=apply_item_spell_shield,
            apply_item_mana_health=apply_item_mana_health,
            apply_item_resist_grants=apply_item_resist_grants,
            apply_rune_resist_grants=apply_rune_resist_grants,
            rune_ids=rune_ids,
            apply_rune_health_grants=apply_rune_health_grants,
            apply_rune_hsp_amp=apply_rune_hsp_amp,
            assume_item_health_stacks=assume_item_health_stacks,
            apply_rune_flat_mitigation=apply_rune_flat_mitigation,
            assume_item_proc_heal=assume_item_proc_heal,
            apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
            assume_item_general_dr=assume_item_general_dr,
            apply_survival_window=apply_survival_window,
            external_resist_armor=external_resist_armor,
            external_resist_mr=external_resist_mr,
            external_revive_multiplier=external_revive_multiplier,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank_tank(body: dict) -> dict:
    """POST /rank-tank - rank items by Effective HP gained.

    Mirror of ``/rank`` for the EHP scorer. Same body shape with two
    swaps: ``enemy_ad_share`` / ``enemy_ap_share`` (floats) replace
    ``target_armor`` / ``target_mr`` (irrelevant to EHP - they describe
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
    apply_mode_modifiers = _opt_bool(body, "apply_mode_modifiers", False)
    # Item 236: CC-adjusted ranking. enemies + include_conditional feed the
    # cc_blended_ehp discount; score_by="cc_blended" ranks on it (tenacity-aware
    # by default - apply_build_tenacity tri-state: omit -> ON for cc_blended /
    # OFF for blended, explicit 0/1 overrides). Default body = byte-identical.
    enemies = _coerce_str_list(body.get("enemies"), "enemies")
    include_conditional = _opt_bool(body, "include_conditional", False)
    # Term A (2026-07-18): "team_blended" is tank-only - /rank-bruiser keeps the
    # two-value allowlist, since ds.hybrid has no ally-grant term.
    score_by = _opt_str(body, "score_by", "blended") or "blended"
    if score_by not in ("blended", "cc_blended", "team_blended"):
        raise _ApiError(
            400,
            f"score_by: must be blended|cc_blended|team_blended, got {score_by!r}",
        )
    apply_build_tenacity = (
        _opt_bool(body, "apply_build_tenacity", False)
        if "apply_build_tenacity" in body else None
    )
    apply_passive_mitigation = _opt_bool(body, "apply_passive_mitigation", False)
    apply_passive_resist = _opt_bool(body, "apply_passive_resist", False)
    apply_passive_revive = _opt_bool(body, "apply_passive_revive", False)
    apply_champion_tenacity = _opt_bool(body, "apply_champion_tenacity", False)
    # ENGINE 1.104.0 (item 292): GAP-2 EIGHTH survivability axis - the champion's
    # SELF spell-shield / block-one CC ability (Sivir E / Nocturne W / Fiora W /
    # Morgana E self). Default off -> byte-identical.
    apply_spell_shield = _opt_bool(body, "apply_spell_shield", False)
    # R104 (ENGINE 1.197.0): item-side spell-shield / block-next-ability passive
    # (Banshee's Veil 3102 / Edge of Night 3814 / Verdant Barrier 4632 "Annul").
    # The item lane of the champion spell-shield axis. Default off -> byte-identical.
    apply_item_spell_shield = _opt_bool(body, "apply_item_spell_shield", False)
    apply_item_mana_health = _opt_bool(body, "apply_item_mana_health", False)
    apply_item_resist_grants = _opt_bool(body, "apply_item_resist_grants", False)
    apply_rune_resist_grants = _opt_bool(body, "apply_rune_resist_grants", False)
    rune_ids = _coerce_str_list(body.get("rune_ids"), "rune_ids")
    apply_rune_health_grants = _opt_bool(body, "apply_rune_health_grants", False)
    apply_rune_hsp_amp = _opt_bool(body, "apply_rune_hsp_amp", False)
    # R137 (ENGINE 1.226.0, RM-99): item permanent-HP-per-proc stack (Heartsteel).
    assume_item_health_stacks = _opt_bool(body, "assume_item_health_stacks", False)
    apply_rune_flat_mitigation = _opt_bool(body, "apply_rune_flat_mitigation", False)
    assume_item_proc_heal = _opt_bool(body, "assume_item_proc_heal", False)
    apply_item_bonus_hp_amp = _opt_bool(body, "apply_item_bonus_hp_amp", False)
    assume_item_general_dr = _opt_bool(body, "assume_item_general_dr", False)
    # ENGINE 1.105.0 (item 293): GAP-2 NINTH survivability axis - the champion's
    # SELF guaranteed-survival window (untargetable / stasis / invuln: Tryndamere R
    # / Kindred R / Taric R / Kayle R self / Lissandra R self / Xayah R / Vladimir W
    # / Elise E / Fizz E / Mel W). Default off -> byte-identical.
    apply_survival_window = _opt_bool(body, "apply_survival_window", False)
    # /rank-tank seam flags (DEFAULT-OFF/null -> byte-identical when omitted):
    #   cost_ceiling (F2) - drop candidates above the gold ceiling.
    #   prefer_survivability_by_win (RF3) - float the WIN-anchored survivability set.
    cost_ceiling = _opt_int(body, "cost_ceiling", None)
    prefer_survivability_by_win = _opt_bool(body, "prefer_survivability_by_win", False)
    # RM-87 / row A-18 (2026-07-25): the champion RESIST -> DAMAGE coupling lever.
    # /rank-tank ONLY - the seam corrects the TANK objective's blindness to a kit
    # that re-spends its own resists as damage (Rammus P / Ornn E), so it has no
    # place on the other archetype routes. Sort-only + DEFAULT-OFF: omitting both
    # keys (or sending a zero strength) is byte-identical.
    apply_resist_damage_coupling = _opt_bool(
        body, "apply_resist_damage_coupling", False
    )
    resist_coupling_strength = _opt_float(body, "resist_coupling_strength", 0.0)
    if resist_coupling_strength < 0.0:
        raise _ApiError(
            400,
            "resist_coupling_strength: must be >= 0.0, got "
            f"{resist_coupling_strength!r}",
        )
    # 2026-07-25: the three ASSUMED-INCOMING-SHARE seams. UNLIKE every other seam
    # on this route these ship DEFAULT-ON in ``compute_ehp`` (a champion-blind 0.5
    # incoming crit / basic-attack share), so the route needs an OFF switch, not
    # an ON one. Tri-state, following the ``apply_build_tenacity`` idiom above: a
    # key that is ABSENT is not forwarded AT ALL, so an unchanged body produces a
    # byte-identical engine call. Only an explicitly-sent key is passed through.
    assumed_share_kwargs: dict[str, bool] = {}
    if "assume_item_crit_dr" in body:
        assumed_share_kwargs["assume_item_crit_dr"] = _opt_bool(
            body, "assume_item_crit_dr", True
        )
    if "assume_item_aa_dr" in body:
        assumed_share_kwargs["assume_item_aa_dr"] = _opt_bool(
            body, "assume_item_aa_dr", True
        )
    if "assume_item_enemy_as_slow" in body:
        assumed_share_kwargs["assume_item_enemy_as_slow"] = _opt_bool(
            body, "assume_item_enemy_as_slow", True
        )
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
            apply_mode_modifiers=apply_mode_modifiers,
            enemy_champions=enemies,
            include_conditional=include_conditional,
            score_by=score_by,
            apply_build_tenacity=apply_build_tenacity,
            apply_passive_mitigation=apply_passive_mitigation,
            apply_passive_resist=apply_passive_resist,
            apply_passive_revive=apply_passive_revive,
            apply_champion_tenacity=apply_champion_tenacity,
            apply_spell_shield=apply_spell_shield,
            apply_item_spell_shield=apply_item_spell_shield,
            apply_item_mana_health=apply_item_mana_health,
            apply_item_resist_grants=apply_item_resist_grants,
            apply_rune_resist_grants=apply_rune_resist_grants,
            rune_ids=rune_ids,
            apply_rune_health_grants=apply_rune_health_grants,
            apply_rune_hsp_amp=apply_rune_hsp_amp,
            assume_item_health_stacks=assume_item_health_stacks,
            apply_rune_flat_mitigation=apply_rune_flat_mitigation,
            assume_item_proc_heal=assume_item_proc_heal,
            apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
            assume_item_general_dr=assume_item_general_dr,
            apply_survival_window=apply_survival_window,
            prefer_survivability_by_win=prefer_survivability_by_win,
            cost_ceiling=cost_ceiling,
            apply_resist_damage_coupling=apply_resist_damage_coupling,
            resist_coupling_strength=resist_coupling_strength,
            **assumed_share_kwargs,
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
        f = float(body[key])
    except (TypeError, ValueError):
        raise _ApiError(400, f"{key}: expected number, got {body[key]!r}")
    if not math.isfinite(f):
        raise _ApiError(400, f"{key}: must be a finite number, got {body[key]!r}")
    return f


def _route_hybrid(body: dict) -> dict:
    """POST /hybrid - compute combined DPS+EHP score for the caster build.

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
    include_conditional = _opt_bool(body, "include_conditional", False)
    apply_mode_modifiers = _opt_bool(body, "apply_mode_modifiers", False)
    enemies = _coerce_str_list(body.get("enemies"), "enemies")
    apply_build_tenacity = _opt_bool(body, "apply_build_tenacity", False)
    apply_passive_mitigation = _opt_bool(body, "apply_passive_mitigation", False)
    apply_passive_resist = _opt_bool(body, "apply_passive_resist", False)
    apply_passive_revive = _opt_bool(body, "apply_passive_revive", False)
    apply_champion_tenacity = _opt_bool(body, "apply_champion_tenacity", False)
    # ENGINE 1.104.0 (item 292): GAP-2 EIGHTH survivability axis - the champion's
    # SELF spell-shield / block-one CC ability (Sivir E / Nocturne W / Fiora W /
    # Morgana E self). Default off -> byte-identical.
    apply_spell_shield = _opt_bool(body, "apply_spell_shield", False)
    # R104 (ENGINE 1.197.0): item-side spell-shield / block-next-ability passive
    # (Banshee's Veil 3102 / Edge of Night 3814 / Verdant Barrier 4632 "Annul").
    # The item lane of the champion spell-shield axis. Default off -> byte-identical.
    apply_item_spell_shield = _opt_bool(body, "apply_item_spell_shield", False)
    apply_item_mana_health = _opt_bool(body, "apply_item_mana_health", False)
    apply_item_resist_grants = _opt_bool(body, "apply_item_resist_grants", False)
    apply_rune_resist_grants = _opt_bool(body, "apply_rune_resist_grants", False)
    rune_ids = _coerce_str_list(body.get("rune_ids"), "rune_ids")
    apply_rune_health_grants = _opt_bool(body, "apply_rune_health_grants", False)
    apply_rune_hsp_amp = _opt_bool(body, "apply_rune_hsp_amp", False)
    # R137 (ENGINE 1.226.0, RM-99): item permanent-HP-per-proc stack (Heartsteel).
    assume_item_health_stacks = _opt_bool(body, "assume_item_health_stacks", False)
    apply_rune_flat_mitigation = _opt_bool(body, "apply_rune_flat_mitigation", False)
    assume_item_proc_heal = _opt_bool(body, "assume_item_proc_heal", False)
    apply_item_bonus_hp_amp = _opt_bool(body, "apply_item_bonus_hp_amp", False)
    assume_item_general_dr = _opt_bool(body, "assume_item_general_dr", False)
    # ENGINE 1.105.0 (item 293): GAP-2 NINTH survivability axis - the champion's
    # SELF guaranteed-survival window (untargetable / stasis / invuln: Tryndamere R
    # / Kindred R / Taric R / Kayle R self / Lissandra R self / Xayah R / Vladimir W
    # / Elise E / Fizz E / Mel W). Default off -> byte-identical.
    apply_survival_window = _opt_bool(body, "apply_survival_window", False)
    try:
        result = compute_hybrid(
            snap, champion_id=champion, level=level,
            item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            enemy_ad_share=enemy_ad_share, enemy_ap_share=enemy_ap_share,
            phase=phase, augments=augments,
            enemy_champions=enemies,
            include_conditional=include_conditional,
            apply_mode_modifiers=apply_mode_modifiers,
            apply_build_tenacity=apply_build_tenacity,
            apply_passive_mitigation=apply_passive_mitigation,
            apply_passive_resist=apply_passive_resist,
            apply_passive_revive=apply_passive_revive,
            apply_champion_tenacity=apply_champion_tenacity,
            apply_spell_shield=apply_spell_shield,
            apply_item_spell_shield=apply_item_spell_shield,
            apply_item_mana_health=apply_item_mana_health,
            apply_item_resist_grants=apply_item_resist_grants,
            apply_rune_resist_grants=apply_rune_resist_grants,
            rune_ids=rune_ids,
            apply_rune_health_grants=apply_rune_health_grants,
            apply_rune_hsp_amp=apply_rune_hsp_amp,
            assume_item_health_stacks=assume_item_health_stacks,
            apply_rune_flat_mitigation=apply_rune_flat_mitigation,
            assume_item_proc_heal=assume_item_proc_heal,
            apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
            assume_item_general_dr=assume_item_general_dr,
            apply_survival_window=apply_survival_window,
            alpha=alpha, beta=beta,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank_bruiser(body: dict) -> dict:
    """POST /rank-bruiser - rank items by weighted DPS+EHP delta.

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
    include_conditional = _opt_bool(body, "include_conditional", False)
    apply_mode_modifiers = _opt_bool(body, "apply_mode_modifiers", False)
    enemies = _coerce_str_list(body.get("enemies"), "enemies")
    score_by = _opt_str(body, "score_by", "blended") or "blended"
    if score_by not in ("blended", "cc_blended"):
        raise _ApiError(400, f"score_by: must be blended|cc_blended, got {score_by!r}")
    apply_build_tenacity = (
        _opt_bool(body, "apply_build_tenacity", False)
        if "apply_build_tenacity" in body else None
    )
    apply_passive_mitigation = _opt_bool(body, "apply_passive_mitigation", False)
    apply_passive_resist = _opt_bool(body, "apply_passive_resist", False)
    apply_passive_revive = _opt_bool(body, "apply_passive_revive", False)
    apply_champion_tenacity = _opt_bool(body, "apply_champion_tenacity", False)
    # ENGINE 1.104.0 (item 292): GAP-2 EIGHTH survivability axis - the champion's
    # SELF spell-shield / block-one CC ability (Sivir E / Nocturne W / Fiora W /
    # Morgana E self). Default off -> byte-identical.
    apply_spell_shield = _opt_bool(body, "apply_spell_shield", False)
    # R104 (ENGINE 1.197.0): item-side spell-shield / block-next-ability passive
    # (Banshee's Veil 3102 / Edge of Night 3814 / Verdant Barrier 4632 "Annul").
    # The item lane of the champion spell-shield axis. Default off -> byte-identical.
    apply_item_spell_shield = _opt_bool(body, "apply_item_spell_shield", False)
    apply_item_mana_health = _opt_bool(body, "apply_item_mana_health", False)
    apply_item_resist_grants = _opt_bool(body, "apply_item_resist_grants", False)
    apply_rune_resist_grants = _opt_bool(body, "apply_rune_resist_grants", False)
    rune_ids = _coerce_str_list(body.get("rune_ids"), "rune_ids")
    apply_rune_health_grants = _opt_bool(body, "apply_rune_health_grants", False)
    apply_rune_hsp_amp = _opt_bool(body, "apply_rune_hsp_amp", False)
    # R137 (ENGINE 1.226.0, RM-99): item permanent-HP-per-proc stack (Heartsteel).
    assume_item_health_stacks = _opt_bool(body, "assume_item_health_stacks", False)
    apply_rune_flat_mitigation = _opt_bool(body, "apply_rune_flat_mitigation", False)
    assume_item_proc_heal = _opt_bool(body, "assume_item_proc_heal", False)
    apply_item_bonus_hp_amp = _opt_bool(body, "apply_item_bonus_hp_amp", False)
    assume_item_general_dr = _opt_bool(body, "assume_item_general_dr", False)
    # ENGINE 1.105.0 (item 293): GAP-2 NINTH survivability axis - the champion's
    # SELF guaranteed-survival window (untargetable / stasis / invuln: Tryndamere R
    # / Kindred R / Taric R / Kayle R self / Lissandra R self / Xayah R / Vladimir W
    # / Elise E / Fizz E / Mel W). Default off -> byte-identical.
    apply_survival_window = _opt_bool(body, "apply_survival_window", False)
    # /rank-bruiser seam flags (DEFAULT-OFF/null -> byte-identical when omitted):
    #   cost_ceiling (F2) - drop candidates above the gold ceiling.
    #   prefer_survivability_by_win (RF1) - float the WIN-anchored survivability set.
    cost_ceiling = _opt_int(body, "cost_ceiling", None)
    prefer_survivability_by_win = _opt_bool(body, "prefer_survivability_by_win", False)
    # R55: the target_current_hp_pct seam now reaches the bruiser (hybrid)
    # scorer's DPS axis. Default 1.0 -> byte-identical when the body omits it.
    target_current_hp_pct = _opt_float(body, "target_current_hp_pct", 1.0)
    # RM-39/RM-43 (DEFAULT-OFF): add the PHYSICAL-only ability term to the AD
    # branch, which is auto-attack-only by design (dps.py:34) for 92 of 173
    # champions. Routed here so the mandatory cohort-wide golden diff (ON vs
    # OFF across every AD-axis champion) is measurable over HTTP; without the
    # surface the ON path is unreachable from :8893. Default body =
    # byte-identical.
    apply_ad_axis_ability_damage = _opt_bool(
        body, "apply_ad_axis_ability_damage", False
    )
    # RM-115 p4 / RM-86 L1: the kit-conversion gate, extended from the CARRY
    # route (server.py:518) to the bruiser ranker - the gate-2 half of the
    # plumb that strands Olaf / Pantheon / RekSai / Riven. hybrid.py consults
    # the registry ONLY when the strength is > 0.0, so 0.0 does no lookup and
    # no arithmetic and is byte-identical to omitting the key.
    kit_conversion_strength = _opt_float(body, "kit_conversion_strength", 0.0)
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
            enemy_champions=enemies,
            include_conditional=include_conditional,
            apply_mode_modifiers=apply_mode_modifiers,
            apply_build_tenacity=apply_build_tenacity,
            apply_passive_mitigation=apply_passive_mitigation,
            apply_passive_resist=apply_passive_resist,
            apply_passive_revive=apply_passive_revive,
            apply_champion_tenacity=apply_champion_tenacity,
            apply_spell_shield=apply_spell_shield,
            apply_item_spell_shield=apply_item_spell_shield,
            apply_item_mana_health=apply_item_mana_health,
            apply_item_resist_grants=apply_item_resist_grants,
            apply_rune_resist_grants=apply_rune_resist_grants,
            rune_ids=rune_ids,
            apply_rune_health_grants=apply_rune_health_grants,
            apply_rune_hsp_amp=apply_rune_hsp_amp,
            assume_item_health_stacks=assume_item_health_stacks,
            apply_rune_flat_mitigation=apply_rune_flat_mitigation,
            assume_item_proc_heal=assume_item_proc_heal,
            apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
            assume_item_general_dr=assume_item_general_dr,
            apply_survival_window=apply_survival_window,
            score_by=score_by,
            alpha=alpha, beta=beta,
            prefer_survivability_by_win=prefer_survivability_by_win,
            cost_ceiling=cost_ceiling,
            target_current_hp_pct=target_current_hp_pct,
            apply_ad_axis_ability_damage=apply_ad_axis_ability_damage,
            kit_conversion_strength=kit_conversion_strength,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _parse_max_priority(body: dict) -> Optional[tuple[str, str, str]]:
    """Decode the optional ``max_priority`` body field.

    Returns ``None`` when the field is absent or empty so the engine's
    per-champion override registry (Phase 4d, s185) can resolve a
    champion-specific priority. Explicit values take precedence.

    Accepts list / comma-string ("Q,W,E") / compact "QWE". Phase 4c
    shared between ``/ability-dps``, ``/rank-mage``, ``/burst``, and
    ``/rank-assassin`` so all four routes parse the operator's priority
    override identically.
    """
    raw_prio = body.get("max_priority")
    if raw_prio is None or raw_prio == "":
        return None
    if isinstance(raw_prio, str) and "," not in raw_prio and len(raw_prio) == 3:
        return tuple(raw_prio.upper())  # type: ignore[return-value]
    parts = _coerce_str_list(raw_prio, "max_priority")
    if len(parts) != 3:
        raise _ApiError(400, f"max_priority: expected 3 keys, got {parts!r}")
    return tuple(p.upper() for p in parts)  # type: ignore[return-value]


def _parse_form_index(body: dict) -> Optional[dict[str, int]]:
    """Decode the optional ``form_index`` body field - JSON dict only."""
    raw_form = body.get("form_index")
    if isinstance(raw_form, dict):
        return {str(k).upper(): int(v) for k, v in raw_form.items()}
    return None


def _block_index_scalar_ok(x) -> bool:
    """True iff ``x`` is a clean int or list[int] (bool rejected)."""
    if isinstance(x, bool):
        return False
    if isinstance(x, int):
        return True
    return isinstance(x, list) and all(
        isinstance(e, int) and not isinstance(e, bool) for e in x
    )


def _parse_block_index(
    body: dict,
) -> "Optional[dict[str, int | list[int] | dict[str, int | list[int]]]]":
    """Decode the optional ``block_index`` body field - JSON dict only.

    Phase 5.9 (s191, 2026-05-14). Per-(champion, key) damage block_index
    override. ``{"E": 1}`` selects Cassiopeia's "Total Enhanced Damage"
    block instead of the default "Bonus Magic Damage" block. Shared by
    ``/ability-dps``, ``/rank-mage``, ``/burst``, and ``/rank-assassin``
    so all four routes accept the operator-supplied override the same way.
    Returns ``None`` when absent so the engine's per-champion registry
    (``champion_block_index.json``) can resolve a default.

    Phase 5.9.20 (s207, 2026-05-14): values may be int OR list[int]; lists
    express sum-of-blocks (operator-commits-to-all-components). JSON
    arrays parse as Python lists; this helper preserves them.

    Phase 5.9.28 (s228, 2026-05-16): values may ALSO be a conditional
    dict ``{"default": int|list[int], "<condition>": int|list[int]}``
    (target-state schema lift). Only well-formed conditional dicts are
    accepted - must contain ``"default"``, every other key must be in
    ``_BLOCK_INDEX_CONDITIONS``, every nested value must be int|list[int].
    Malformed dicts are skipped (untrusted body path: preserve the
    no-500 / fall-back-to-registry property - the engine's
    ``_normalize_block_index_value`` is the hard validator for the
    trusted on-disk registry, where a typo SHOULD raise).
    """
    raw = body.get("block_index")
    if not isinstance(raw, dict):
        return None
    out: dict[str, int | list[int] | dict[str, int | list[int]]] = {}
    for k, v in raw.items():
        key = str(k).upper()
        if isinstance(v, bool):
            # bool is an int subtype in Python - reject explicitly.
            continue
        if isinstance(v, int):
            out[key] = v
        elif isinstance(v, list) and all(
            isinstance(x, int) and not isinstance(x, bool) for x in v
        ):
            out[key] = list(v)
        elif isinstance(v, dict):
            # Conditional schema (s228). Accept only if fully well-formed;
            # else skip (defensive - same stance as the scalar branches).
            if _BLOCK_INDEX_DEFAULT_KEY not in v:
                continue
            if not all(
                (ck == _BLOCK_INDEX_DEFAULT_KEY or ck in _BLOCK_INDEX_CONDITIONS)
                and _block_index_scalar_ok(cv)
                for ck, cv in v.items()
            ):
                continue
            out[key] = {
                ck: (list(cv) if isinstance(cv, list) else cv)
                for ck, cv in v.items()
            }
        # else: silently skip malformed entries (preserves pre-s207
        # behavior of accepting only well-formed values; matches
        # _parse_form_index / _parse_max_priority defensiveness).
    return out


def _parse_combo_sequence(body: dict) -> Optional[tuple[str, ...]]:
    """Decode the optional ``combo_sequence`` body field.

    Returns ``None`` when the field is absent or empty so the engine's
    per-champion override registry (``champion_combo_sequences.json``,
    Phase 5.5 s186) can resolve a champion-specific combo. Explicit
    values take precedence.

    Accepts list / dash-string ("Q-W-E-AA-R-AA") / comma-string
    ("Q,W,E,AA,R,AA"). The engine validates individual tokens -
    this helper just normalizes the list shape.
    """
    raw = body.get("combo_sequence")
    if raw is None or raw == "":
        return None
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
    """POST /ability-dps - per-spell ability DPS for the caster build.

    Phase 4b (s178, 2026-05-12). Body mirrors /dps with these additions:
      * ``target_current_hp_pct`` (float, default 1.0) - what fraction
        of max HP the target sits at when the cast lands; affects
        ``target_current_hp_pct`` / ``target_missing_hp_pct`` blocks
      * ``max_priority`` (str or list, default "QWE") - three keys
        describing max order; comma-separated as a query param
      * ``block_strategy`` (str, default "first") - global strategy for
        multi-block abilities; one of first|sum|max
      * ``form_index`` (dict) - per-key form overrides for multi-form
        abilities (Aphelios weapons, Jayce stance); JSON only
      * ``block_index`` (dict) - per-(champion, key) damage-block index
        overrides; e.g. ``{"E": 1}`` for Cassi to score the "Total
        Enhanced Damage" block. Phase 5.9 (s191) - see
        ``champion_block_index.json`` for the engine's defaults.
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
    block_index_overrides = _parse_block_index(body)
    apply_ability_amps = _opt_bool(body, "apply_ability_amps", False)
    # RM-115: both seams below are accepted by compute_ability_dps
    # (ability_dps.py:960 / :949) but were never parsed here, so /ability-dps
    # could not reach either. A-07 / RM-82 TERM 2 and A-03 / RM-81 respectively.
    apply_passive_aura_damage = _opt_bool(body, "apply_passive_aura_damage", False)
    apply_ability_base_overrides = _opt_bool(
        body, "apply_ability_base_overrides", False
    )
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
            block_index_overrides=block_index_overrides,
            apply_ability_amps=apply_ability_amps,
            apply_passive_aura_damage=apply_passive_aura_damage,
            abilities_snapshot=_ABIL_CACHE.get(apply_ability_base_overrides),
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank_mage(body: dict) -> dict:
    """POST /rank-mage - rank items by total-ability-DPS delta.

    Phase 4c (s179, 2026-05-12). Body is the union of /ability-dps and
    /rank parameters: ``target_*`` + ``target_current_hp_pct`` for the
    cast formula plus ``budget`` / ``slots`` / ``top`` / ``sort`` /
    ``include_components`` / ``only`` / ``filter_shared_uniques`` for the
    candidate-filtering pipeline shared with the other rankers.

    ``apply_passive_aura_damage`` (A-07 / RM-82 TERM 2, default False) opts
    into crediting a ``per_second``-cadence passive aura - Mordekaiser P
    Darkness Rise is the only registered one - on the ability clock. This is
    NOT the ``apply_passive_damage`` flag that ``/rank`` and ``/rank-onhit``
    parse; that one routes on_hit passives onto the AUTO-ATTACK cadence.
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
    block_index_overrides = _parse_block_index(body)
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
    apply_ability_amps = _opt_bool(body, "apply_ability_amps", False)
    # A-07 / RM-82 TERM 2 - sustained passive-aura (P) damage credit. Parsed
    # exactly like apply_ability_amps directly above (same _opt_bool idiom,
    # same default-OFF contract) so an absent key and an explicit false are
    # indistinguishable at the scorer.
    apply_passive_aura_damage = _opt_bool(body, "apply_passive_aura_damage", False)
    # RM-115 / A-03 / RM-81 - the six wiki-verified ability-base corrections.
    # This one is a LOAD-time kwarg, not a ranking flag, so it is resolved into
    # an abilities snapshot here; False yields None and the engine falls
    # through to abilities.load_default() exactly as before.
    apply_ability_base_overrides = _opt_bool(
        body, "apply_ability_base_overrides", False
    )
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
            block_index_overrides=block_index_overrides,
            filter_shared_uniques=filter_shared_uniques,
            apply_ability_amps=apply_ability_amps,
            apply_passive_aura_damage=apply_passive_aura_damage,
            abilities_snapshot=_ABIL_CACHE.get(apply_ability_base_overrides),
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank_onhit(body: dict) -> dict:
    """POST /rank-onhit - rank items by combined on-hit AP DPS delta.

    Slice B Task 6 (2026-07-16). Body mirrors /rank-mage's shared fields
    (``target_*`` / ``budget`` / ``slots`` / ``top`` / ``sort`` /
    ``include_components`` / ``only`` / ``filter_shared_uniques``) plus two
    Slice-B-only params forwarded straight to ``rank_items_by_onhit``:
    ``apply_passive_damage`` (default True) and ``ap_ad_coherence`` (default
    0.0). ``rank_items_by_onhit`` has a narrower signature than
    ``rank_items_by_ability_dps`` - it has no ``target_current_hp_pct``,
    ``max_priority``, ``block_strategy``, ``form_index_overrides``,
    ``block_index_overrides``, or ``apply_ability_amps`` params, so those
    are not parsed here.
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
    apply_passive_damage = _opt_bool(body, "apply_passive_damage", True)
    ap_ad_coherence = _opt_float(body, "ap_ad_coherence", 0.0)
    only_ids: Optional[list[str]] = None
    if "only" in body and body["only"] not in (None, ""):
        only_ids = _coerce_str_list(body["only"], "only")
    try:
        result = rank_items_by_onhit(
            snap,
            champion_id=champion, level=level,
            current_item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            budget=budget, slot_count=slot_count, top_n=top_n,
            include_components=include_components,
            only_item_ids=only_ids, sort_by=sort_by,
            augments=augments,
            filter_shared_uniques=filter_shared_uniques,
            apply_passive_damage=apply_passive_damage,
            ap_ad_coherence=ap_ad_coherence,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_burst(body: dict) -> dict:
    """POST /burst - single-combo burst damage for the caster build.

    Phase 5 (s180, 2026-05-13). Body mirrors /ability-dps with one
    addition (Phase 5 - combo) plus all the shared registry overrides
    (max_priority, form_index, block_index Phase 5.9 - s191):
      * ``combo_sequence`` (list or "Q-W-E-AA-R-AA") - tokens to fire;
        AA = auto-attack, P/Q/W/E/R = one cast, Q2/W2/E2/R2 = repeat
        at same rank. Default: ("Q","W","E","AA","R","AA"); per-champion
        registry override via ``champion_combo_sequences.json``.
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
    block_index_overrides = _parse_block_index(body)
    combo_sequence = _parse_combo_sequence(body)
    aoe_targets_hit = _opt_int(body, "aoe_targets_hit", 1) or 1
    # R30 seam flag (DEFAULT-OFF -> byte-identical when the body omits it). Scoped to
    # /burst: rank_items_by_burst does NOT accept assume_magic_burst, only the direct
    # compute_burst_damage does (burst.py:485 - the on-cast magic-burst item proc).
    assume_magic_burst = _opt_bool(body, "assume_magic_burst", False)
    # R74 DSV8 seam flag (DEFAULT-OFF -> byte-identical when the body omits it).
    # Scoped to /burst exactly like assume_magic_burst above: rank_items_by_burst
    # does NOT accept assume_physical_burst, only the direct compute_burst_damage
    # does (the Goredrinker 226630 Thirsting Slash item-active physical burst).
    assume_physical_burst = _opt_bool(body, "assume_physical_burst", False)
    # R75 DSV9 seam flag (DEFAULT-OFF -> byte-identical when the body omits it).
    # Scoped to /burst exactly like assume_magic_burst above: rank_items_by_burst
    # does NOT accept assume_shielded_target, only the direct compute_burst_damage
    # does (the Serpent's Fang 6695 Shield Reaver one-time active-shield cut).
    assume_shielded_target = _opt_bool(body, "assume_shielded_target", False)
    # OQ17: the rune-proc layer + the /burst-scoped compute-direct seams
    # (DEFAULT-OFF/None -> byte-identical when omitted). These read the SINGLE-BUILD
    # burst NUMBER, not a ranker delta (a flat keystone amp washes out of a
    # candidate-baseline delta), so like R30 assume_magic_burst they live on the
    # direct /burst route rather than /rank-assassin:
    #   assume_takedown (DSV2) - Hubris/Collector kill-state offense.
    #   assume_ability_amp (DSV4) - Spear of Shojin on-cast ability amp.
    #   score_completion_runes (DSP4) - credit the completion runes (Shield Bash 8401).
    #   gate_target_hp_amp (R51) - honestly gate Cut Down 8017 / Coup 8014 on target HP.
    #   gate_caster_hp_amp + caster_current_hp_pct (R53) - gate Last Stand 8299 on caster HP.
    # The live default-ON flips stay EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md).
    runes = [
        int(x)
        for x in _coerce_str_list(body.get("runes"), "runes")
        if str(x).strip().lstrip("-").isdigit()
    ]
    assume_takedown = _opt_bool(body, "assume_takedown", False)
    assume_ability_amp = _opt_bool(body, "assume_ability_amp", False)
    score_completion_runes = _opt_bool(body, "score_completion_runes", False)
    gate_target_hp_amp = _opt_bool(body, "gate_target_hp_amp", False)
    gate_caster_hp_amp = _opt_bool(body, "gate_caster_hp_amp", False)
    caster_current_hp_pct = _opt_float(body, "caster_current_hp_pct", 1.0)
    # RM-115 / A-03 / RM-81 - load-time ability-base corrections, resolved into
    # an abilities snapshot. False yields None -> abilities.load_default().
    apply_ability_base_overrides = _opt_bool(
        body, "apply_ability_base_overrides", False
    )
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
            block_index_overrides=block_index_overrides,
            combo_sequence=combo_sequence,
            aoe_targets_hit=aoe_targets_hit,
            assume_magic_burst=assume_magic_burst,
            assume_physical_burst=assume_physical_burst,
            assume_shielded_target=assume_shielded_target,
            runes=(runes or None),
            assume_takedown=assume_takedown,
            assume_ability_amp=assume_ability_amp,
            score_completion_runes=score_completion_runes,
            gate_target_hp_amp=gate_target_hp_amp,
            gate_caster_hp_amp=gate_caster_hp_amp,
            caster_current_hp_pct=caster_current_hp_pct,
            abilities_snapshot=_ABIL_CACHE.get(apply_ability_base_overrides),
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_fight_report(body: dict) -> dict:
    """POST /v2/fight-report - unified V2 fight report (DS V2 S2).

    Composes the 5 additive V2 substrate modules (mana_sim, rune_procs,
    ability_hps, self_shred, scenario_matrix) into one report. Body:
      * ``champion`` (required), ``level``, ``items``, ``mode``,
        ``target_armor`` / ``target_mr`` / ``target_max_hp`` /
        ``target_bonus_hp``
      * ``sequence`` (list or comma string) - rotation tokens; default
        Q-W-E-AA-R-AA
      * ``runes`` (list or comma string of Riot perk ids) - keystone/proc
        rune layer; junk ids ignored
    ``compute_fight_report`` is itself fail-soft (per-section notes), so a
    KeyError here is only the champion-resolution failure (404).
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
    raw_seq = _coerce_str_list(body.get("sequence"), "sequence")
    sequence = raw_seq if raw_seq else None
    runes = [
        int(x)
        for x in _coerce_str_list(body.get("runes"), "runes")
        if str(x).strip().lstrip("-").isdigit()
    ]
    gate_ammo = _opt_bool(body, "gate_ammo", False)
    apply_ability_haste = _opt_bool(body, "apply_ability_haste", False)
    apply_mode_modifiers = _opt_bool(body, "apply_mode_modifiers", False)
    try:
        result = compute_fight_report(
            champion, level, item_ids=items, sequence=sequence, runes=runes,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            mode=mode, snapshot=snap,
            gate_ammo=gate_ammo, apply_ability_haste=apply_ability_haste,
            apply_mode_modifiers=apply_mode_modifiers,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_matchup(body: dict) -> dict:
    """POST /v2/matchup - Lane A 1v1 head-to-head trade resolution.

    Composes the existing pure scorers (burst + build_champion + mana_sim) into a
    deterministic who-wins-this-trade verdict, the substitute for the LLM laning
    judgment. Body:
      * ``champ_a`` / ``champ_b`` (both required)
      * ``level_a`` / ``level_b`` (default 1 each)
      * ``item_ids_a`` / ``item_ids_b`` (list or comma string)
      * ``mode`` (default SR)
      * ``hp_a_pct`` / ``hp_b_pct`` (current-HP-pct assumption; default 1.0)
    """
    snap = _CACHE.get()
    champ_a = _resolve_champion_id(snap, _required_str(body, "champ_a"))
    champ_b = _resolve_champion_id(snap, _required_str(body, "champ_b"))
    level_a = _opt_int(body, "level_a", 1) or 1
    level_b = _opt_int(body, "level_b", 1) or 1
    items_a = _coerce_str_list(body.get("item_ids_a"), "item_ids_a")
    items_b = _coerce_str_list(body.get("item_ids_b"), "item_ids_b")
    mode = _opt_str(body, "mode", "SR") or "SR"
    hp_a_pct = _opt_float(body, "hp_a_pct", 1.0)
    hp_b_pct = _opt_float(body, "hp_b_pct", 1.0)
    try:
        result = compute_matchup(
            snap, champ_a, champ_b, level_a, level_b,
            item_ids_a=items_a, item_ids_b=items_b, mode=mode,
            hp_a_pct=hp_a_pct, hp_b_pct=hp_b_pct,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_cc_output(body: dict) -> dict:
    """POST /cc-output - offensive crowd-control (lockdown) score for a champion.

    Item 294 (ENGINE 1.106.0): the mirror of the survivability CC axes - how
    much CC the champion APPLIES to enemies, weighted by CC kind into a single
    lockdown score. Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
    Additive read-only metric: it perturbs no other route.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    try:
        result = compute_cc_output(champion, mode=mode)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_mobility(body: dict) -> dict:
    """POST /mobility - self-mobility (gap-close / kiting) score for a champion.

    Item 297 (ENGINE 1.109.0): the eighth scored axis - how much a champion can
    reposition her own body (dashes / blinks / leaps / MS steroids / untargetable
    hops), normalised to Flash-units and weighted by kind into a single mobility
    score. Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
    Additive read-only metric: it perturbs no other route.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    try:
        result = compute_mobility(champion, mode=mode)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_sustain(body: dict) -> dict:
    """POST /sustain - sustain / vamp-throughput score for a champion.

    Item 298 (ENGINE 1.110.0): the ninth scored axis - how much effective HP a
    champion claws back during a fight by converting damage to health (lifesteal
    / omnivamp / spellvamp / drains) plus self HP-regen steroids, weighted by
    kind into a single sustain score. Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
    Additive read-only metric: it perturbs no other route.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    try:
        result = compute_sustain(champion, mode=mode)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_scaling(body: dict) -> dict:
    """POST /scaling - scaling / power-curve score for a champion.

    Item 299 (ENGINE 1.111.0): the tenth scored axis - a champion's power
    TRAJECTORY across the game, reduced to an early / mid / late power triple
    plus a signed ``scaling_slope`` (late - early): positive scales up, negative
    falls off. Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
    Additive read-only metric: it perturbs no other route.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    try:
        result = compute_scaling(champion, mode=mode)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_waveclear(body: dict) -> dict:
    """POST /waveclear - wave-clear / AoE-shove score for a champion.

    Item 300 (ENGINE 1.112.0): the eleventh scored axis - how fast and how safely
    a champion CLEARS A MINION WAVE and shoves a lane (the tempo / lane-priority /
    roam-window capability). Returns a range-weighted ``waveclear_score``, the
    ``top_kind`` label, and a ``ranged_shove`` safe-shove flag. Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
    Additive read-only metric: it perturbs no other route.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    try:
        result = compute_waveclear(champion, mode=mode)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_threatrange(body: dict) -> dict:
    """POST /threat-range - effective threat-range score for a champion.

    Item 301 (ENGINE 1.113.0): the twelfth scored axis - how FAR OUT a champion
    can deliver meaningful damage or CC (the poke / siege / safe-DPS-distance
    capability). Returns a reach-weighted ``threatrange_score``, the ``top_band``
    label (the champion's longest real threat), and an ``is_artillery`` flag.
    Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
    Additive read-only metric: it perturbs no other route.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    try:
        result = compute_threatrange(champion, mode=mode)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_zonecontrol(body: dict) -> dict:
    """POST /zone-control - zone-control / area-denial score for a champion.

    Item 302 (ENGINE 1.114.0): the thirteenth scored axis - how much a champion
    can make a piece of GROUND dangerous, impassable, or contested for a duration
    (the spatial area-denial dimension). Returns a denial-weighted
    ``zonecontrol_score``, the ``top_kind`` label (the champion's strongest
    area-control), and a ``controls_terrain`` flag. The axis is sparse: a pure
    target-focused champion scores 0.0.
    Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
    Additive read-only metric: it perturbs no other route.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    try:
        result = compute_zonecontrol(champion, mode=mode)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_objdamage(body: dict) -> dict:
    """POST /objective-damage - objective / structure-damage for a champion.

    Item 303 (ENGINE 1.115.0): the fourteenth scored axis - how much pressure a
    champion puts on the map's OBJECTIVES (turrets / structures and epic monsters
    - drake / baron / herald / grubs). Returns a kind-weighted, scope-scaled
    ``objdamage_score``, the ``top_kind`` label (the champion's strongest
    objective tool), and a ``pressures_structures`` flag (can it actually damage
    towers). Scores the full roster.
    Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
    Additive read-only metric: it perturbs no other route.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    try:
        result = compute_objdamage(champion, mode=mode)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_allyamp(body: dict) -> dict:
    """POST /ally-amp - ally-amplification / buff-throughput for a champion.

    Item 304 (ENGINE 1.116.0): the fifteenth scored axis - how much COMBAT VALUE
    a champion grants to her ALLIES (the shields, heals, steroids, hard-saves,
    and haste she pumps OUTWARD into her team - the mirror of the self-sustain
    axis pointed at teammates). Returns a kind-weighted, reach-scaled
    ``allyamp_score``, the ``top_kind`` label (the champion's strongest
    ally-buff), and a ``saves_ally`` flag (can it hard-save a teammate). The axis
    is sparse: a selfish carry / assassin / solo duelist scores 0.0.
    Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
    Additive read-only metric: it perturbs no other route.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    try:
        result = compute_allyamp(champion, mode=mode)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_antitank(body: dict) -> dict:
    """POST /anti-tank - anti-tank / %HP-damage + resist-shred for a champion.

    Item 308 (ENGINE 1.117.0): the sixteenth scored axis - how well a champion's
    OWN KIT melts a high-HP / high-resist target (the %max-HP / %current-HP damage
    and the armor/MR shred / %pen it brings; pure %-missing-health executes are
    excluded as finishers). Returns a kind-weighted, cadence-scaled
    ``antitank_score``, the ``top_kind`` label (the champion's strongest anti-tank
    tool), and a ``shreds_resist`` flag (does it lower the tank's resists for the
    whole team). The axis is selective: a flat-damage champion whose output
    ignores enemy health and resists scores 0.0.
    Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
      * ``level`` (optional int, R17/R39 ramp seam - B12): scales a ramp-seeded
        row's %max-HP / %current-HP magnitude toward its early endpoint. Omitted /
        ``level=18`` is byte-identical to item 308/315.
      * ``item_ids`` (optional list, P3.2 live-build seam - B4): when non-empty,
        resolves the champion's live AP/AD via ``compute_antitank_live`` so a
        seeded row's ratio (Gwen P / Kog'Maw W AP; Vi W / Camille W AD) scales.
        Omitted / empty stays on the static (no-stats) path.
      * ``augments`` (optional list): Arena augments forwarded to the live build.
    Every input DEFAULT-OFF -> a body omitting level + item_ids is byte-identical
    to the pre-OQ18 static result. Additive read-only metric.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    level = _opt_int(body, "level", None)
    item_ids = _coerce_str_list(body.get("item_ids"), "item_ids")
    augments = _coerce_str_list(body.get("augments"), "augments")
    try:
        if item_ids:
            # P3.2 live-build producer (B4): resolve AP/AD from the live build.
            # ``level`` sets the build-resolution level (default 18 = full build).
            result = compute_antitank_live(
                snap, champion, level if level is not None else 18,
                item_ids, mode=mode, augments=(augments or None),
            )
        else:
            # R17/R39 level-ramp seam (B12); level=None -> static.
            result = compute_antitank(champion, mode=mode, level=level)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_summoner_fight_adj(body: dict) -> dict:
    """POST /summoner-fight-adj - DSP5 live summoner-spell combat adjustments (B31).

    Folds the player's + the ENEMY's live summoner set into one adjustment struct
    (``dsp_live_consumers.summoner_fight_adjustments``) - self Heal/Barrier EHP,
    Cleanse tenacity, Ghost/Heal MS, Exhaust incoming-DR; enemy Ignite antiheal.
    Body:
      * ``self_spell_ids`` (list of Riot summoner ids; junk ids drop to 0.0)
      * ``enemy_spell_ids`` (list)
      * ``level`` (default 1; scales the level-based Heal / Ghost magnitudes)
    EMPTY sets -> all fields 0.0 (byte-identical no-op). Additive read-only.
    """
    self_ids = _coerce_int_list(body.get("self_spell_ids"), "self_spell_ids")
    enemy_ids = _coerce_int_list(body.get("enemy_spell_ids"), "enemy_spell_ids")
    level = float(_opt_int(body, "level", 1) or 1)
    return asdict(summoner_fight_adjustments(self_ids, enemy_ids, level))


def _route_enemy_rune_threat(body: dict) -> dict:
    """POST /enemy-rune-threat - DSP6 enemy-rune incoming-threat fold (B32).

    Folds the enemy's live rune set into one threat struct
    (``dsp_live_consumers.enemy_rune_threat``): Press the Attack incoming-amp,
    Conqueror ramp, Grasp/Second Wind poke-sustain, enemy antiheal, and an
    ``ehp_divisor`` = 1 + amp for a survivability lens.
    Body:
      * ``enemy_rune_ids`` (list of Riot perk ids; junk ids drop to 0.0)
      * ``level`` (default 1; scales Conqueror ramp)
      * ``antiheal_present`` (bool - any enemy antiheal source; no rune grants it)
      * ``enemy_max_hp`` / ``enemy_missing_hp`` (floats - for Grasp poke-sustain)
    EMPTY set + defaults -> amp 0.0, divisor 1.0 (no-op). Additive read-only.
    """
    rune_ids = _coerce_int_list(body.get("enemy_rune_ids"), "enemy_rune_ids")
    level = float(_opt_int(body, "level", 1) or 1)
    return asdict(enemy_rune_threat(
        rune_ids,
        level,
        antiheal_present=_opt_bool(body, "antiheal_present", False),
        enemy_max_hp=_opt_float(body, "enemy_max_hp", 0.0),
        enemy_missing_hp=_opt_float(body, "enemy_missing_hp", 0.0),
    ))


def _route_ally_protected_ehp(body: dict) -> dict:
    """POST /ally-protected-ehp - DSP7 ally-enchanter-protected EHP (B33).

    Returns an ``EhpResult`` for ``champion`` with its live allies' enchanter
    grants folded in (``dsp_live_consumers.ally_protected_ehp``): each granter's
    flat-HP shield/heal (Janna/Lulu/Karma/Yuumi E, Seraphine W, Soraka/Nami W)
    and resist grant (Orianna E / Braum W / Taric W).
    Body:
      * ``champion`` (required)
      * ``level`` (default 1)
      * ``item_ids`` (optional list - the protected ally's own build)
      * ``ally_grant_champions`` (list of the protected ally's LIVE teammates)
      * ``mode`` (default SR), ``enemy_champions`` (optional list)
      * ``granter_resists`` (optional dict {granter: [armor, mr, base_armor,
        base_mr]} for Taric's percent-of-resist grant)
    EMPTY ``ally_grant_champions`` -> byte-identical to a plain compute_ehp.
    Additive read-only.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    level = _opt_int(body, "level", 1) or 1
    mode = _opt_str(body, "mode", "SR") or "SR"
    item_ids = _coerce_str_list(body.get("item_ids"), "item_ids")
    allies = _coerce_str_list(body.get("ally_grant_champions"), "ally_grant_champions")
    enemies = _coerce_str_list(body.get("enemy_champions"), "enemy_champions")
    granter_resists = body.get("granter_resists")
    if not isinstance(granter_resists, dict):
        granter_resists = None
    try:
        result = ally_protected_ehp(
            snap,
            champion,
            level,
            item_ids=item_ids,
            ally_grant_champions=allies,
            mode=mode,
            enemy_champions=enemies,
            granter_resists=granter_resists,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_extendedduel(body: dict) -> dict:
    """POST /extended-duel - extended-dueling / 1v1 sustained-fight for a champion.

    Item 309 (ENGINE 1.118.0): the seventeenth scored axis - how well a champion's
    OWN KIT wins a PROLONGED 1v1 duel past the initial burst window (the RAMP /
    RESET / DUELHEAL / ENDURE attrition tools it brings). Returns a kind-weighted,
    cadence-scaled ``duel_score``, the ``top_kind`` label (the champion's strongest
    duel tool), and a ``ramps`` flag (does the kit get STRONGER the longer the fight
    runs - do not commit to a long 1v1 against it). The axis is selective: a burst /
    artillery / utility champion with no attrition tools scores 0.0.
    Body:
      * ``champion`` (required)
      * ``mode`` (default SR; carried on the result, does not change output)
    Additive read-only metric: it perturbs no other route.
    """
    snap = _CACHE.get()
    champion = _resolve_champion_id(snap, _required_str(body, "champion"))
    mode = _opt_str(body, "mode", "SR") or "SR"
    try:
        result = compute_extendedduel(champion, mode=mode)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank_assassin(body: dict) -> dict:
    """POST /rank-assassin - rank items by total-burst-damage delta.

    Phase 5 (s180, 2026-05-13). Body is the union of /burst and /rank
    parameters: ``target_*`` + ``target_current_hp_pct`` + ``combo_sequence``
    for the burst formula plus ``budget`` / ``slots`` / ``top`` / ``sort`` /
    ``include_components`` / ``only`` / ``filter_shared_uniques`` for the
    candidate-filtering pipeline shared with the other rankers.

    Optional ``runes`` (list or comma string of Riot perk ids; junk ids
    ignored) threads the keystone/proc rune layer into the burst formula
    (DS V2 S3). When the body omits ``runes`` the ranking is BYTE-IDENTICAL
    to today (empty list -> None inside ``rank_items_by_burst``).
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
    block_index_overrides = _parse_block_index(body)
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
    runes = [
        int(x)
        for x in _coerce_str_list(body.get("runes"), "runes")
        if str(x).strip().lstrip("-").isdigit()
    ]
    aoe_targets_hit = _opt_int(body, "aoe_targets_hit", 1) or 1
    # /rank-assassin seam flags (DEFAULT-OFF/None -> byte-identical when omitted):
    #   prefer_kit_axis_by_win (DSP11) - float a champ's WIN-anchored kit-axis items.
    # R30 assume_magic_burst + R74 assume_physical_burst + R75
    # assume_shielded_target are scoped to the /burst route: rank_items_by_burst
    # does NOT accept them (only compute_burst_damage does at burst.py:485).
    #   exclude_off_axis_items (RM-41) - strip candidates whose offense sits
    #     entirely on the champion's OFF damage axis (AD spellblade/on-hit/crit
    #     on a pure-AP assassin, and the RM-35 mirror). Data-driven gate; a
    #     champion without a decisive damage split is a no-op.
    prefer_kit_axis_by_win = _opt_bool(body, "prefer_kit_axis_by_win", False)
    exclude_off_axis_items = _opt_bool(body, "exclude_off_axis_items", False)
    # OQ17: the enemy-comp / kill-state ranking seams the burst ranker already
    # forwards to compute_burst_damage (assume_takedown/assume_ability_amp) or
    # resolves itself (assume_squishy_target/target_preset). DEFAULT-OFF/None ->
    # byte-identical when omitted; an unknown target_preset raises ValueError ->
    # 422 via the except below. The live default-ON flips stay EXCLUDED
    # (docs/LIVE_GAME_GATED_SYNC.md). The rune-gate seams (DSP4/R51/R53) are
    # /burst-scoped instead - they wash out of the candidate-baseline delta.
    assume_takedown = _opt_bool(body, "assume_takedown", False)
    assume_squishy_target = _opt_bool(body, "assume_squishy_target", False)
    assume_ability_amp = _opt_bool(body, "assume_ability_amp", False)
    target_preset = _opt_str(body, "target_preset", None)
    # RM-115 / RM-83: the RM-86 L1 kit-conversion gate, extended from the CARRY
    # route (server.py:481) to the assassin/burst ranker. burst.py:2160-2163
    # consults the registry ONLY when the strength is > 0.0, so 0.0 does no
    # lookup and no arithmetic and is byte-identical to omitting the key.
    kit_conversion_strength = _opt_float(body, "kit_conversion_strength", 0.0)
    # RM-115 / A-03 / RM-81 - load-time ability-base corrections. Naafiri is the
    # one of the six that routes here; False yields None so the OFF path still
    # falls through to abilities.load_default() and stays byte-identical.
    apply_ability_base_overrides = _opt_bool(
        body, "apply_ability_base_overrides", False
    )
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
            block_index_overrides=block_index_overrides,
            combo_sequence=combo_sequence,
            filter_shared_uniques=filter_shared_uniques,
            runes=(runes or None),
            aoe_targets_hit=aoe_targets_hit,
            prefer_kit_axis_by_win=prefer_kit_axis_by_win,
            exclude_off_axis_items=exclude_off_axis_items,
            assume_takedown=assume_takedown,
            assume_squishy_target=assume_squishy_target,
            assume_ability_amp=assume_ability_amp,
            target_preset=target_preset,
            kit_conversion_strength=kit_conversion_strength,
            abilities_snapshot=_ABIL_CACHE.get(apply_ability_base_overrides),
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _opt_targets_override(body: dict) -> Optional[float]:
    """Phase 6 - optional targets_per_proc_override (float). None when absent."""
    key = "targets_per_proc_override"
    if key not in body or body[key] in (None, ""):
        return None
    try:
        f = float(body[key])
    except (TypeError, ValueError):
        raise _ApiError(400, f"{key}: expected number, got {body[key]!r}")
    if not math.isfinite(f):
        raise _ApiError(400, f"{key}: must be a finite number, got {body[key]!r}")
    return f


def _route_hps(body: dict) -> dict:
    """POST /hps - total healing+shielding+buff throughput for the build.

    Phase 6 (s181, 2026-05-13). Body shape mirrors /ehp's caster-only
    schema (no target_armor/_mr/_max_hp - these don't affect outgoing
    heals/shields). Optional ``targets_per_proc_override`` (float)
    replaces the per-item curated targets count for ALL items in the
    build - useful for Arena 2v2 scenarios (override=1).
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
    """POST /rank-enchanter - rank items by total-throughput delta.

    Phase 6 (s181, 2026-05-13). Mirror of /rank-tank for the HPS scorer.
    No target_* fields - outgoing healing doesn't care about enemy
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
    # /rank-enchanter seam flags (DEFAULT-OFF/0.0 -> byte-identical when omitted):
    #   prefer_survivability_by_win (RF2) - inject + float the WIN-anchored
    #     enchanter survivability set above the generic template.
    #   assume_missing_hp_heal_amp / caster_missing_hp_pct (R5) - the comeback
    #     missing-HP heal-amp for a champ's own ability heals (MasterYi W / Sylas W
    #     / Lissandra R / Briar P), threaded into compute_hps -> compute_ability_hps.
    prefer_survivability_by_win = _opt_bool(body, "prefer_survivability_by_win", False)
    assume_missing_hp_heal_amp = _opt_bool(body, "assume_missing_hp_heal_amp", False)
    caster_missing_hp_pct = _opt_float(body, "caster_missing_hp_pct", 0.0)
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
            prefer_survivability_by_win=prefer_survivability_by_win,
            assume_missing_hp_heal_amp=assume_missing_hp_heal_amp,
            caster_missing_hp_pct=caster_missing_hp_pct,
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
    apply_mode_modifiers = _opt_bool(body, "apply_mode_modifiers", False)
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
            apply_mode_modifiers=apply_mode_modifiers,
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


def _route_modifier_summary() -> dict:
    """GET /modifier-summary - roster-wide ability MODIFIER-block taxonomy.

    Behavior-neutral diagnostic: walks the live ``AbilitiesSnapshot`` and
    buckets every champion ability MODIFIER block via
    ``modifier_blocks.summarize_modifiers`` into pve_only / target_shred /
    defensive_self / damage_amp_self / other. Reads only - touches no
    DPS / EHP / burst number. This is the live consumer for the deliberately
    additive ``modifier_blocks`` substrate (the module's docstring names "a
    coach surface" as its intended home); surfacing the classification is
    that surface. ``load_default`` is process-cached so repeated GETs do not
    re-read disk.
    """
    from .abilities import load_default
    from .modifier_blocks import summarize_modifiers
    return summarize_modifiers(load_default()).to_dict()


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
    "/rank-onhit": _route_rank_onhit,
    "/burst": _route_burst,
    "/rank-assassin": _route_rank_assassin,
    "/hps": _route_hps,
    "/rank-enchanter": _route_rank_enchanter,
    "/v2/fight-report": _route_fight_report,
    "/v2/matchup": _route_matchup,
    "/cc-output": _route_cc_output,
    "/mobility": _route_mobility,
    "/sustain": _route_sustain,
    "/scaling": _route_scaling,
    "/waveclear": _route_waveclear,
    "/threat-range": _route_threatrange,
    "/zone-control": _route_zonecontrol,
    "/objective-damage": _route_objdamage,
    "/ally-amp": _route_allyamp,
    "/anti-tank": _route_antitank,
    "/summoner-fight-adj": _route_summoner_fight_adj,
    "/enemy-rune-threat": _route_enemy_rune_threat,
    "/ally-protected-ehp": _route_ally_protected_ehp,
    "/extended-duel": _route_extendedduel,
}

# GET routes that need a body merge from query params for the same handler.
_GET_DISPATCH_ROUTES = set(_POST_ROUTES.keys())


class Handler(BaseHTTPRequestHandler):
    server_version = f"DaemonSlayer/{ENGINE_VERSION}"

    # Quiet the default access-log spam - we surface our own.
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

    def _drain_request_body(self) -> None:
        """Consume and discard any unread request body.

        Must be called on every early-return path that responds WITHOUT
        going through ``_read_json_body`` (the unknown-POST-route 404).
        If the body is left in the socket receive buffer, closing the
        connection makes Windows send a TCP RST instead of a clean FIN,
        and the client sees ``ConnectionResetError`` /
        ``ConnectionAbortedError`` instead of the 4xx we just wrote (the
        intermittent test_server flake). With keep-alive it desyncs the
        stream and corrupts the next response on the connection.
        Read in bounded chunks so a bogus huge Content-Length cannot
        wedge the handler.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)

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
            if path == "/modifier-summary":
                self._send_json(200, _route_modifier_summary())
                return
            if path in _GET_DISPATCH_ROUTES:
                body = self._query_to_body(url.query)
                payload = _POST_ROUTES[path](body)
                self._send_json(200, payload)
                return
            self._send_error(404, f"no such route: {path}")
        except _ApiError as e:
            self._send_error(e.status, e.message, e.detail)
        except Exception:  # noqa: BLE001
            # Never leak the raw exception text into the HTTP body (a stack /
            # exc string is an information-disclosure + breaks the friendly
            # degraded-mode contract). The full traceback is logged above.
            _log.exception("unhandled error in GET %s", path)
            self._send_error(500, "internal engine error - see daemon_slayer logs")

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        try:
            if path not in _POST_ROUTES:
                # Drain first - returning with an unread body in the
                # socket buffer makes Windows RST the connection on
                # close (the intermittent flake) instead of delivering
                # this 404 cleanly.
                self._drain_request_body()
                self._send_error(404, f"no such route: {path}")
                return
            body = self._read_json_body()
            # Allow query-string overrides on POST too - handy for testing.
            if url.query:
                merged = self._query_to_body(url.query)
                merged.update(body)
                body = merged
            payload = _POST_ROUTES[path](body)
            self._send_json(200, payload)
        except _ApiError as e:
            self._send_error(e.status, e.message, e.detail)
        except Exception:  # noqa: BLE001
            # Never leak the raw exception text into the HTTP body (a stack /
            # exc string is an information-disclosure + breaks the friendly
            # degraded-mode contract). The full traceback is logged above.
            _log.exception("unhandled error in POST %s", path)
            self._send_error(500, "internal engine error - see daemon_slayer logs")


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
    # RM-115: the flag-ON abilities snapshot is memoized for the process, so it
    # must not outlive the DataSnapshot it was built beside. There is no
    # hot-reload path today (Phase 7), but start_server IS called more than
    # once per process on the test path, sometimes at a different patch.
    _ABIL_CACHE.reset()
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

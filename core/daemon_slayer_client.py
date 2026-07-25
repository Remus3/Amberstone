"""Thin HTTP client for the local Daemon Slayer engine on :8893.

Phase 7 wire-in. Coach ticks need a non-blocking call into the engine
that fails silently when the server isn't up - the engine is opt-in
infrastructure, never load-bearing. Timeouts are tight (250 ms connect,
500 ms read) so a slow engine can't stall a coach loop.

Owners of name->id resolution: see ``core.daemon_slayer_resolver``. This
module operates purely on item IDs (string).
"""
from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from core.build_planner.coherence import coherence_rerank
from core.ds_archetype_hp_pct import archetype_target_current_hp_pct
from core.ds_burst_target import squishy_carry_target
from core.ds_champion_fight_length import champion_fight_length

logger = logging.getLogger("rc.core.daemon_slayer_client")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8893
DEFAULT_TIMEOUT = 0.5  # seconds, applied to connect+read combined


@dataclass(frozen=True)
class RankedItem:
    item_id: str
    item_name: str
    delta_dps: float
    gold: int
    # Phase 6 step 8 (2026-05-12): mirrored from server-side RankedItem so
    # consumers (coaches, dashboard) can suppress or annotate dead-unique
    # candidates without a second engine call.
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): mirrors server unique_passive_key - the positive
    # locked-family signal (collision-independent).
    unique_passive_key: str = ""
    # L4 crit-burst fix (2026-07-13): mirror the server's burst-inclusive
    # effective_score (= burst_gain + delta_dps * fight_length,
    # agents.daemon_slayer.rank). BEFORE L4 this field was dropped, so the carry
    # coherence re-rank's fight_length-engaged branch
    # (core.build_planner.coherence._coherence_adj) read a MISSING attribute ->
    # base 0.0 -> the re-rank collapsed to a target-BLIND kit-fit sort and the
    # burst reweight (L1/L3) was inert in production. Parsing it here makes the
    # burst-inclusive, target-sensitive score actually reach coherence_rerank.
    # Appended at the END with a default so existing construction is unaffected.
    effective_score: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "RankedItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            item_name=str(d.get("item_name", "")),
            delta_dps=float(d.get("delta_dps", 0.0)),
            gold=int(d.get("gold", 0)),
            shares_dead_unique=bool(d.get("shares_dead_unique", False)),
            dead_unique_key=str(d.get("dead_unique_key", "")),
            unique_passive_key=str(d.get("unique_passive_key", "")),
            effective_score=float(d.get("effective_score", 0.0)),
        )


def _post_json(path: str, body: dict, timeout: float = DEFAULT_TIMEOUT) -> Optional[dict]:
    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}{path}"
    try:
        req = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8"))
    except (URLError, HTTPError, socket.timeout, TimeoutError, ConnectionError) as e:
        logger.debug("daemon_slayer %s unreachable: %s", path, e)
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug("daemon_slayer %s unexpected: %s", path, e)
        return None


def is_engine_up(timeout: float = 0.25) -> bool:
    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/health"
    try:
        with urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def ensure_running() -> None:
    """Start the Daemon Slayer server if it is not already responding.

    Called once at RC dashboard startup. No-op if :8893 is healthy.
    Spawns tools/start_daemon_slayer.py as a detached background process
    using the same interpreter as the current process.
    """
    if is_engine_up(timeout=1.0):
        return
    launcher = Path(__file__).resolve().parent.parent / "tools" / "start_daemon_slayer.py"
    if not launcher.exists():
        logger.warning("daemon_slayer launcher not found at %s", launcher)
        return
    try:
        subprocess.Popen(
            [sys.executable, str(launcher)],
            cwd=str(launcher.parent.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        logger.info("daemon_slayer not running - spawned %s", launcher.name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("daemon_slayer auto-start failed: %s", exc)


def rank_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    top: int = 8,
    sort_by: str = "delta",
    only_item_ids: Optional[Iterable[str]] = None,
    augments: Optional[Iterable[str]] = None,
    filter_shared_uniques: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
    # Seam flags (Tier-2, behavior-preserving). Each default OFF/null so a
    # payload omitting it is byte-identical to today; emitted only when set.
    exempt_offclass_by_win: bool = False,    # DSP2
    prefer_kit_axis_by_win: bool = False,    # DSP11
    cost_ceiling: Optional[int] = None,      # F2
    assume_passive_as_stacks: bool = False,  # R7
    apply_target_vuln: bool = False,         # R12
    target_current_hp_pct: float = 1.0,      # R55
    fight_length: Optional[float] = None,    # per-champ burst-carry blend (Jhin pilot)
    widen_carry_pool: bool = False,          # RM-04 A-01
) -> Optional[list[RankedItem]]:
    """Call POST /rank and return the parsed top-N rows. None on engine failure.

    Empty list (vs. None) means the engine responded but had no candidates
    - e.g. champion already has 6 mode-legal items. Callers should treat
    None and [] differently (engine down vs. nothing to recommend).

    ``augments`` is an optional list of Arena augment apiName strings (e.g.
    ``["TheBrutalizer", "ItsCritical"]``); engine applies registered stat
    overlays before computing DPS. Unknown apiNames are silently skipped
    server-side.

    ``target_max_hp`` (Phase 4 batch 5) activates %-target-HP procs
    (BotRK, Eclipse). ``target_bonus_hp`` (Phase 4 batch 19) activates
    target-conditional damage amps (LDR Giant Slayer). Both default
    0.0 - engine treats 0 as "no signal" and procs gracefully no-op,
    so pre-batch callers see identical behavior.

    ``only_item_ids`` whitelists the candidate pool (same semantics as
    the tank/bruiser/mage/assassin/enchanter siblings). Before this was
    added the carry/dps branch silently ignored the whitelist, so an
    ADC build-order plan restricted to a curated pool would no-op the
    restriction - it now threads through to the server's ``only`` field.

    ``fight_length`` (per-champion burst-carry calibration, Jhin pilot) is the
    OPTIONAL fight-length-reweight seconds forwarded into the server's
    ``rank_items`` blend. ``None`` (default) omits the body key entirely, so the
    request is byte-identical to the pre-calibration path; a positive float
    engages the burst-vs-sustained blend. Set at the carry chokepoint from the
    ``core.ds_champion_fight_length`` allow-map (see
    ``rank_for_primary_archetype``).

    ``widen_carry_pool`` (RM-04 A-01, DEFAULT-OFF) opts into the engine's
    class-wide un-strip of the carry candidate pool (``rank_items``'s
    ``widen_carry_pool``, parsed server-side off the same body key). False
    (default) omits the body key entirely, so the request is byte-identical
    to the pre-seam path.
    """
    body = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
        "top": int(top),
        "sort": sort_by,
        "filter_shared_uniques": bool(filter_shared_uniques),
    }
    if only_item_ids is not None:
        body["only"] = [str(i) for i in only_item_ids if i]
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    if exempt_offclass_by_win:
        body["exempt_offclass_by_win"] = True
    if prefer_kit_axis_by_win:
        body["prefer_kit_axis_by_win"] = True
    if cost_ceiling is not None:
        body["cost_ceiling"] = int(cost_ceiling)
    if assume_passive_as_stacks:
        body["assume_passive_as_stacks"] = True
    if apply_target_vuln:
        body["apply_target_vuln"] = True
    # R55: emit only when non-default so a call at 1.0 is byte-identical.
    if target_current_hp_pct != 1.0:
        body["target_current_hp_pct"] = float(target_current_hp_pct)
    # Per-champ burst-carry blend: emit only when set so a call without it is
    # byte-identical to the pre-calibration request.
    if fight_length is not None:
        body["fight_length"] = float(fight_length)
    # RM-04 A-01: emit only when True so an un-widened call is byte-identical.
    if widen_carry_pool:
        body["widen_carry_pool"] = True
    data = _post_json("/rank", body, timeout=timeout)
    if data is None:
        return None
    ranked = data.get("ranked") or []
    return [RankedItem.from_dict(r) for r in ranked]


@dataclass(frozen=True)
class TankRankedItem:
    """Mirror of ``agents.daemon_slayer.ehp.EhpRankedItem`` - EHP scorer
    Phase 1 sibling of ``RankedItem``."""
    item_id: str
    item_name: str
    delta_ehp: float
    gold: int
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): mirrors server unique_passive_key - the positive
    # locked-family signal (collision-independent).
    unique_passive_key: str = ""
    # Term A (2026-07-18): the ally-granted EHP delta. Equals ``delta_ehp``
    # unless the caller asked for score_by="team_blended" AND the champion
    # reaches allies. Parsed explicitly so a team_blended re-rank is OBSERVABLE
    # client-side - dropping the active field is how a live re-rank silently
    # reads as inert.
    delta_team_blended_ehp: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "TankRankedItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            item_name=str(d.get("item_name", "")),
            delta_ehp=float(d.get("delta_ehp", 0.0)),
            gold=int(d.get("gold", 0)),
            shares_dead_unique=bool(d.get("shares_dead_unique", False)),
            dead_unique_key=str(d.get("dead_unique_key", "")),
            unique_passive_key=str(d.get("unique_passive_key", "")),
            delta_team_blended_ehp=float(
                d.get("delta_team_blended_ehp", d.get("delta_ehp", 0.0))
            ),
        )


def rank_tank_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    enemy_ad_share: Optional[float] = None,
    enemy_ap_share: Optional[float] = None,
    top: int = 8,
    sort_by: str = "delta",
    only_item_ids: Optional[Iterable[str]] = None,
    augments: Optional[Iterable[str]] = None,
    filter_shared_uniques: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
    # Seam flags (Tier-2, behavior-preserving; emitted only when set).
    prefer_survivability_by_win: bool = False,  # RF3
    cost_ceiling: Optional[int] = None,         # F2
    score_by: str = "blended",                  # Term A: + team_blended
) -> Optional[list[TankRankedItem]]:
    """Call POST /rank-tank and return the parsed top-N rows. None on engine failure.

    Phase 1 (s174, 2026-05-12) - Tank EHP scorer. Same engine-down semantics as
    ``rank_for`` (None = unreachable, [] = nothing to recommend).

    ``enemy_ad_share`` / ``enemy_ap_share`` are floats in [0,1] summing to <= 1.0;
    remainder is true-damage share. Defaults to 50/50 as a "no info" baseline.

    ``only_item_ids`` is the integration point for ``core/defensive_picks.py``
    Option B layering - pass the curated defensive item catalog as a whitelist
    so the EHP-driven ranking happens within an operator-vetted pool.
    """
    _resolved_ad_share, _resolved_ap_share = _resolve_enemy_shares(
        enemy_ad_share, enemy_ap_share
    )
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "enemy_ad_share": _resolved_ad_share,
        "enemy_ap_share": _resolved_ap_share,
        "top": int(top),
        "sort": sort_by,
        "filter_shared_uniques": bool(filter_shared_uniques),
    }
    if only_item_ids is not None:
        body["only"] = [str(i) for i in only_item_ids if i]
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    if prefer_survivability_by_win:
        body["prefer_survivability_by_win"] = True
    if cost_ceiling is not None:
        body["cost_ceiling"] = int(cost_ceiling)
    # Term A: emit only when non-default so a flagless call is byte-identical.
    if score_by != "blended":
        body["score_by"] = score_by
    data = _post_json("/rank-tank", body, timeout=timeout)
    if data is None:
        return None
    ranked = data.get("ranked") or []
    return [TankRankedItem.from_dict(r) for r in ranked]


def ehp_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    enemy_ad_share: Optional[float] = None,
    enemy_ap_share: Optional[float] = None,
    augments: Optional[Iterable[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """Call POST /ehp and return the raw result dict. None on failure.

    Phase 1 sibling of ``dps_for``. See ``rank_tank_for`` for share semantics.
    """
    _resolved_ad_share, _resolved_ap_share = _resolve_enemy_shares(
        enemy_ad_share, enemy_ap_share
    )
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "enemy_ad_share": _resolved_ad_share,
        "enemy_ap_share": _resolved_ap_share,
    }
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    return _post_json("/ehp", body, timeout=timeout)


@dataclass(frozen=True)
class BruiserRankedItem:
    """Mirror of ``agents.daemon_slayer.hybrid.HybridRankedItem`` - Phase 2
    sibling of ``RankedItem`` / ``TankRankedItem``.

    ``hybrid_delta_pct`` is the operator-facing sort key: a weighted sum of
    normalized percentage gains. ``delta_dps`` + ``delta_ehp`` are raw
    deltas exposed for transparency.
    """
    item_id: str
    item_name: str
    delta_dps: float
    delta_ehp: float
    hybrid_delta_pct: float
    gold: int
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): mirrors server unique_passive_key - the positive
    # locked-family signal (collision-independent).
    unique_passive_key: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "BruiserRankedItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            item_name=str(d.get("item_name", "")),
            delta_dps=float(d.get("delta_dps", 0.0)),
            delta_ehp=float(d.get("delta_ehp", 0.0)),
            hybrid_delta_pct=float(d.get("hybrid_delta_pct", 0.0)),
            gold=int(d.get("gold", 0)),
            shares_dead_unique=bool(d.get("shares_dead_unique", False)),
            dead_unique_key=str(d.get("dead_unique_key", "")),
            unique_passive_key=str(d.get("unique_passive_key", "")),
        )


def rank_bruiser_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    enemy_ad_share: Optional[float] = None,
    enemy_ap_share: Optional[float] = None,
    top: int = 8,
    sort_by: str = "delta",
    only_item_ids: Optional[Iterable[str]] = None,
    augments: Optional[Iterable[str]] = None,
    filter_shared_uniques: bool = True,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    timeout: float = DEFAULT_TIMEOUT,
    # Seam flags (Tier-2, behavior-preserving; emitted only when set).
    prefer_survivability_by_win: bool = False,  # RF1
    cost_ceiling: Optional[int] = None,         # F2
    target_current_hp_pct: float = 1.0,         # R55
) -> Optional[list[BruiserRankedItem]]:
    """Call POST /rank-bruiser and return the parsed top-N rows. None on engine failure.

    Phase 2 (s175, 2026-05-12) - Bruiser hybrid scorer. Same engine-down
    semantics as ``rank_for`` (None = unreachable, [] = nothing to recommend).

    ``alpha`` / ``beta`` default to per-champion ``archetype_weights.json``
    lookup server-side; pass explicit floats only when overriding (UI sliders,
    operator mid-game retune).
    """
    _resolved_ad_share, _resolved_ap_share = _resolve_enemy_shares(
        enemy_ad_share, enemy_ap_share
    )
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
        "enemy_ad_share": _resolved_ad_share,
        "enemy_ap_share": _resolved_ap_share,
        "top": int(top),
        "sort": sort_by,
        "filter_shared_uniques": bool(filter_shared_uniques),
    }
    if alpha is not None:
        body["alpha"] = float(alpha)
    if beta is not None:
        body["beta"] = float(beta)
    if only_item_ids is not None:
        body["only"] = [str(i) for i in only_item_ids if i]
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    if prefer_survivability_by_win:
        body["prefer_survivability_by_win"] = True
    if cost_ceiling is not None:
        body["cost_ceiling"] = int(cost_ceiling)
    # R55: emit only when non-default so a call at 1.0 is byte-identical.
    if target_current_hp_pct != 1.0:
        body["target_current_hp_pct"] = float(target_current_hp_pct)
    data = _post_json("/rank-bruiser", body, timeout=timeout)
    if data is None:
        return None
    ranked = data.get("ranked") or []
    return [BruiserRankedItem.from_dict(r) for r in ranked]


@dataclass(frozen=True)
class MageRankedItem:
    """Mirror of ``agents.daemon_slayer.ability_dps.AbilityDpsRankedItem``
    - Phase 4c sibling of ``RankedItem`` / ``TankRankedItem`` /
    ``BruiserRankedItem``.

    ``delta_ability_dps`` is the raw total-ability-DPS gain over the
    baseline; ``ability_dps_per_1k_gold`` is the efficiency view.
    """
    item_id: str
    item_name: str
    delta_ability_dps: float
    new_ability_dps: float
    gold: int
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): mirrors server unique_passive_key - the positive
    # locked-family signal (collision-independent).
    unique_passive_key: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "MageRankedItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            item_name=str(d.get("item_name", "")),
            delta_ability_dps=float(d.get("delta_ability_dps", 0.0)),
            new_ability_dps=float(d.get("new_ability_dps", 0.0)),
            gold=int(d.get("gold", 0)),
            shares_dead_unique=bool(d.get("shares_dead_unique", False)),
            dead_unique_key=str(d.get("dead_unique_key", "")),
            unique_passive_key=str(d.get("unique_passive_key", "")),
        )


def rank_mage_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    target_current_hp_pct: float = 1.0,
    top: int = 8,
    sort_by: str = "delta",
    only_item_ids: Optional[Iterable[str]] = None,
    augments: Optional[Iterable[str]] = None,
    max_priority: Optional[tuple[str, str, str]] = None,
    block_strategy: str = "first",
    form_index: Optional[dict[str, int]] = None,
    filter_shared_uniques: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[list[MageRankedItem]]:
    """Call POST /rank-mage and return the parsed top-N rows. None on engine failure.

    Phase 4c (s179, 2026-05-12) - Mage ability DPS scorer. Same engine-down
    semantics as ``rank_for`` (None = unreachable, [] = nothing to recommend).

    ``target_current_hp_pct`` is the fraction of max HP the assumed target
    sits at when the cast lands - affects target_missing_hp_pct /
    target_current_hp_pct damage blocks (Eve R, Garen R thresholds).

    ``max_priority`` is a 3-tuple of ability keys describing max order
    (default Q->W->E server-side); ``block_strategy`` is first|sum|max for
    multi-block abilities; ``form_index`` is a per-key form override
    dict for multi-form abilities (Aphelios, Jayce).
    """
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
        "target_current_hp_pct": float(target_current_hp_pct),
        "top": int(top),
        "sort": sort_by,
        "block_strategy": block_strategy,
        "filter_shared_uniques": bool(filter_shared_uniques),
    }
    if max_priority is not None:
        body["max_priority"] = list(max_priority)
    if form_index is not None:
        body["form_index"] = {str(k): int(v) for k, v in form_index.items()}
    if only_item_ids is not None:
        body["only"] = [str(i) for i in only_item_ids if i]
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    data = _post_json("/rank-mage", body, timeout=timeout)
    if data is None:
        return None
    ranked = data.get("ranked") or []
    return [MageRankedItem.from_dict(r) for r in ranked]


def ability_dps_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    target_current_hp_pct: float = 1.0,
    augments: Optional[Iterable[str]] = None,
    max_priority: Optional[tuple[str, str, str]] = None,
    block_strategy: str = "first",
    form_index: Optional[dict[str, int]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """Call POST /ability-dps and return the raw result dict. None on failure.

    Phase 4c sibling of ``dps_for`` / ``ehp_for`` / ``hybrid_for``. See
    ``rank_mage_for`` for ``max_priority`` / ``block_strategy`` /
    ``form_index`` semantics.
    """
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
        "target_current_hp_pct": float(target_current_hp_pct),
        "block_strategy": block_strategy,
    }
    if max_priority is not None:
        body["max_priority"] = list(max_priority)
    if form_index is not None:
        body["form_index"] = {str(k): int(v) for k, v in form_index.items()}
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    return _post_json("/ability-dps", body, timeout=timeout)


@dataclass(frozen=True)
class AssassinRankedItem:
    """Mirror of ``agents.daemon_slayer.burst.BurstRankedItem`` - Phase 5
    sibling of ``MageRankedItem`` / ``BruiserRankedItem`` / ``TankRankedItem``.

    ``delta_burst`` is the total-burst-damage gain over the baseline;
    ``burst_per_1k_gold`` is the efficiency view.
    """
    item_id: str
    item_name: str
    delta_burst: float
    new_burst: float
    gold: int
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): mirrors server unique_passive_key - the positive
    # locked-family signal (collision-independent).
    unique_passive_key: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "AssassinRankedItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            item_name=str(d.get("item_name", "")),
            delta_burst=float(d.get("delta_burst", 0.0)),
            new_burst=float(d.get("new_burst", 0.0)),
            gold=int(d.get("gold", 0)),
            shares_dead_unique=bool(d.get("shares_dead_unique", False)),
            dead_unique_key=str(d.get("dead_unique_key", "")),
            unique_passive_key=str(d.get("unique_passive_key", "")),
        )


def rank_assassin_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    target_current_hp_pct: float = 1.0,
    top: int = 8,
    sort_by: str = "delta",
    only_item_ids: Optional[Iterable[str]] = None,
    augments: Optional[Iterable[str]] = None,
    max_priority: Optional[tuple[str, str, str]] = None,
    block_strategy: str = "first",
    form_index: Optional[dict[str, int]] = None,
    combo_sequence: Optional[Iterable[str]] = None,
    filter_shared_uniques: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
    # Seam flags (Tier-2, behavior-preserving; emitted only when set).
    prefer_kit_axis_by_win: bool = False,  # DSP11
    assume_magic_burst: bool = False,      # R30
) -> Optional[list[AssassinRankedItem]]:
    """Call POST /rank-assassin and return the parsed top-N rows. None on engine failure.

    Phase 5 (s180, 2026-05-13) - Assassin burst-window scorer. Same engine-down
    semantics as ``rank_for`` (None = unreachable, [] = nothing to recommend).

    ``target_current_hp_pct`` is the fraction of max HP the assumed target
    sits at when the combo lands - affects target_missing_hp_pct /
    target_current_hp_pct damage blocks (Zed R execute, Garen R threshold).

    ``combo_sequence`` is an iterable of tokens (AA / P / Q / W / E / R /
    Q2 / W2 / E2 / R2). Default: ("Q","W","E","AA","R","AA"). See
    ``agents.daemon_slayer.burst`` module docstring for token semantics.
    """
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
        "target_current_hp_pct": float(target_current_hp_pct),
        "top": int(top),
        "sort": sort_by,
        "block_strategy": block_strategy,
        "filter_shared_uniques": bool(filter_shared_uniques),
    }
    if max_priority is not None:
        body["max_priority"] = list(max_priority)
    if form_index is not None:
        body["form_index"] = {str(k): int(v) for k, v in form_index.items()}
    if combo_sequence is not None:
        body["combo_sequence"] = [str(t) for t in combo_sequence if t]
    if only_item_ids is not None:
        body["only"] = [str(i) for i in only_item_ids if i]
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    if prefer_kit_axis_by_win:
        body["prefer_kit_axis_by_win"] = True
    if assume_magic_burst:
        body["assume_magic_burst"] = True
    data = _post_json("/rank-assassin", body, timeout=timeout)
    if data is None:
        return None
    ranked = data.get("ranked") or []
    return [AssassinRankedItem.from_dict(r) for r in ranked]


def burst_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    target_current_hp_pct: float = 1.0,
    augments: Optional[Iterable[str]] = None,
    max_priority: Optional[tuple[str, str, str]] = None,
    block_strategy: str = "first",
    form_index: Optional[dict[str, int]] = None,
    combo_sequence: Optional[Iterable[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """Call POST /burst and return the raw result dict. None on failure.

    Phase 5 sibling of ``ability_dps_for`` / ``dps_for`` / ``ehp_for`` /
    ``hybrid_for``. See ``rank_assassin_for`` for ``combo_sequence``
    semantics.
    """
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
        "target_current_hp_pct": float(target_current_hp_pct),
        "block_strategy": block_strategy,
    }
    if max_priority is not None:
        body["max_priority"] = list(max_priority)
    if form_index is not None:
        body["form_index"] = {str(k): int(v) for k, v in form_index.items()}
    if combo_sequence is not None:
        body["combo_sequence"] = [str(t) for t in combo_sequence if t]
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    return _post_json("/burst", body, timeout=timeout)


def hybrid_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    enemy_ad_share: Optional[float] = None,
    enemy_ap_share: Optional[float] = None,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    augments: Optional[Iterable[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """Call POST /hybrid and return the raw result dict. None on failure.

    Phase 2 sibling of ``dps_for`` and ``ehp_for``. See ``rank_bruiser_for``
    for alpha/beta semantics.
    """
    _resolved_ad_share, _resolved_ap_share = _resolve_enemy_shares(
        enemy_ad_share, enemy_ap_share
    )
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
        "enemy_ad_share": _resolved_ad_share,
        "enemy_ap_share": _resolved_ap_share,
    }
    if alpha is not None:
        body["alpha"] = float(alpha)
    if beta is not None:
        body["beta"] = float(beta)
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    return _post_json("/hybrid", body, timeout=timeout)


@dataclass(frozen=True)
class EnchanterRankedItem:
    """Mirror of ``agents.daemon_slayer.hps.HpsRankedItem`` - HPS scorer
    Phase 6 sibling of ``RankedItem`` / ``TankRankedItem`` / ``BruiserRankedItem``
    / ``MageRankedItem`` / ``AssassinRankedItem``."""
    item_id: str
    item_name: str
    delta_hps: float
    new_hps: float
    gold: int
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): mirrors server unique_passive_key - the positive
    # locked-family signal (collision-independent).
    unique_passive_key: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "EnchanterRankedItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            item_name=str(d.get("item_name", "")),
            delta_hps=float(d.get("delta_hps", 0.0)),
            new_hps=float(d.get("new_hps", 0.0)),
            gold=int(d.get("gold", 0)),
            shares_dead_unique=bool(d.get("shares_dead_unique", False)),
            dead_unique_key=str(d.get("dead_unique_key", "")),
            unique_passive_key=str(d.get("unique_passive_key", "")),
        )


def rank_enchanter_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    top: int = 8,
    sort_by: str = "delta",
    only_item_ids: Optional[Iterable[str]] = None,
    augments: Optional[Iterable[str]] = None,
    targets_per_proc_override: Optional[float] = None,
    enchanter_only: bool = True,
    filter_shared_uniques: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
    # Seam flags (Tier-2, behavior-preserving; emitted only when set).
    prefer_survivability_by_win: bool = False,  # RF2
    assume_missing_hp_heal_amp: bool = False,   # R5
    caster_missing_hp_pct: float = 0.0,         # R5 input
) -> Optional[list[EnchanterRankedItem]]:
    """Call POST /rank-enchanter and return the parsed top-N rows. None on engine failure.

    Phase 6 (s181, 2026-05-13) - Enchanter healing throughput scorer. Same
    engine-down semantics as ``rank_for`` (None = unreachable, [] = nothing
    to recommend).

    ``targets_per_proc_override`` replaces the per-item curated targets count
    for ALL items in the build (Arena 2v2 -> override=1).
    ``enchanter_only`` restricts the candidate pool to the curated enchanter
    registry (default True).
    """
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "top": int(top),
        "sort": sort_by,
        "enchanter_only": bool(enchanter_only),
        "filter_shared_uniques": bool(filter_shared_uniques),
    }
    if targets_per_proc_override is not None:
        body["targets_per_proc_override"] = float(targets_per_proc_override)
    if only_item_ids is not None:
        body["only"] = [str(i) for i in only_item_ids if i]
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    if prefer_survivability_by_win:
        body["prefer_survivability_by_win"] = True
    if assume_missing_hp_heal_amp:
        body["assume_missing_hp_heal_amp"] = True
    if caster_missing_hp_pct:
        body["caster_missing_hp_pct"] = float(caster_missing_hp_pct)
    data = _post_json("/rank-enchanter", body, timeout=timeout)
    if data is None:
        return None
    ranked = data.get("ranked") or []
    return [EnchanterRankedItem.from_dict(r) for r in ranked]


def hps_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    augments: Optional[Iterable[str]] = None,
    targets_per_proc_override: Optional[float] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """Call POST /hps and return the raw result dict. None on failure.

    Phase 6 sibling of ``dps_for`` / ``ehp_for`` / ``hybrid_for`` /
    ``ability_dps_for`` / ``burst_for``. See ``rank_enchanter_for`` for
    ``targets_per_proc_override`` semantics.
    """
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
    }
    if targets_per_proc_override is not None:
        body["targets_per_proc_override"] = float(targets_per_proc_override)
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    return _post_json("/hps", body, timeout=timeout)


@dataclass(frozen=True)
class OnhitRankedItem:
    """Mirror of ``agents.daemon_slayer.onhit_dps.OnhitDpsRankedItem`` -
    Slice B (2026-07-16) sibling of ``MageRankedItem`` / ``AssassinRankedItem``.

    ``delta_dps`` / ``new_dps`` describe the COMBINED on-hit DPS (ability +
    auto, plain sum - matches ``OnhitDpsResult.onhit_dps``); ``ability_dps``
    / ``auto_dps`` are the two halves (``new_dps == ability_dps + auto_dps``
    per row). There is NO ``effective_score`` field here - the AP/AD
    axis-coherence penalty (``ap_ad_coherence``) is applied to the sort key
    SERVER-side, so rows already arrive sorted.
    """
    item_id: str
    item_name: str
    gold: int
    delta_dps: float
    new_dps: float
    ability_dps: float
    auto_dps: float
    dps_per_1k_gold: float
    is_terminal: bool
    tags: tuple[str, ...]
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): mirrors server unique_passive_key - the positive
    # locked-family signal (collision-independent).
    unique_passive_key: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "OnhitRankedItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            item_name=str(d.get("item_name", "")),
            gold=int(d.get("gold", 0)),
            delta_dps=float(d.get("delta_dps", 0.0)),
            new_dps=float(d.get("new_dps", 0.0)),
            ability_dps=float(d.get("ability_dps", 0.0)),
            auto_dps=float(d.get("auto_dps", 0.0)),
            dps_per_1k_gold=float(d.get("dps_per_1k_gold", 0.0)),
            is_terminal=bool(d.get("is_terminal", False)),
            tags=tuple(d.get("tags", ())),
            shares_dead_unique=bool(d.get("shares_dead_unique", False)),
            dead_unique_key=str(d.get("dead_unique_key", "")),
            unique_passive_key=str(d.get("unique_passive_key", "")),
        )


def rank_onhit_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    top: int = 8,
    sort_by: str = "delta",
    only_item_ids: Optional[Iterable[str]] = None,
    augments: Optional[Iterable[str]] = None,
    filter_shared_uniques: bool = True,
    apply_passive_damage: bool = True,
    ap_ad_coherence: float = 0.0,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[list[OnhitRankedItem]]:
    """Call POST /rank-onhit and return the parsed top-N rows. None on engine failure.

    Slice B (2026-07-16) - on-hit AP combined-DPS scorer, the sibling of
    ``rank_mage_for`` for champions whose kit needs BOTH ability DPS and
    on-hit-auto DPS scored together (Gwen, Kayle, Kog'Maw - see
    ``agents.daemon_slayer.onhit_dps``). Same engine-down semantics as
    ``rank_for`` (None = unreachable, [] = nothing to recommend). Drops the
    mage-only ``target_current_hp_pct`` / ``max_priority`` / ``block_strategy``
    / ``form_index`` params - the on-hit scorer does not use them.

    ``apply_passive_damage`` (default True) routes an allowlisted kit
    on-hit passive onto the auto-attack cadence server-side.
    ``ap_ad_coherence`` (default 0.0 = off) is the per-champ AP/AD
    axis-coherence penalty forwarded to the server ranker's sort key.
    """
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
        "top": int(top),
        "sort": sort_by,
        "filter_shared_uniques": bool(filter_shared_uniques),
        "apply_passive_damage": bool(apply_passive_damage),
        "ap_ad_coherence": float(ap_ad_coherence),
    }
    if only_item_ids is not None:
        body["only"] = [str(i) for i in only_item_ids if i]
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    data = _post_json("/rank-onhit", body, timeout=timeout)
    if data is None:
        return None
    ranked = data.get("ranked") or []
    return [OnhitRankedItem.from_dict(r) for r in ranked]


# Ranged-carry off-class gate (item 208 carry, 2026-06-10). The engine's
# own DPS-pool filter (agents/daemon_slayer/rank.py, item 213) keys on the
# Marksman tag plus attackrange >= 500, so ranged carries below that floor
# (Graves 425) or without the tag still surfaced melee/tank items - the
# rows that polluted data/champion_loadouts.json carry paths. This is the
# client-side gate at the shared carry chokepoint: every loadout regen
# path (tools/champion_loadout_autogen.fetch_items; core.build_order.
# plan_build_order via tools/champion_loadout_align) and the live coach
# dispatch flow through the carry branch of rank_for_primary_archetype,
# so a patch regen cannot reproduce the pollution even against a live
# engine that predates the pool filter. Range-keyed, never a champion
# list - melee carries (Nilah 225) and Pantheon's operator-pinned Sup
# Roam Umbral Glaive (175) are exempt by the same mechanic.
# Divine Sunderer joined the set in the item-s8 sweep (2026-06-10): the
# arena Sheen-line melee spellblade was sitting on 7 ranged-carry arena
# rows (Jhin / Jinx / Nami / Seraphine / Twisted Fate / Ziggs / Zilean)
# via the same engine lineage the original four came from.
CARRY_RANGED_ATTACKRANGE_FLOOR: float = 350.0

CARRY_RANGED_OFFCLASS_ITEM_NAMES: frozenset = frozenset({
    "Trinity Force",
    "Bastionbreaker",
    "Heartsteel",
    "Umbral Glaive",
    "Divine Sunderer",
})

# Carry build-coherence re-rank window (Step 1, 2026-07-13). The metric re-rank
# (core.build_planner.coherence.coherence_rerank) needs the buried crit core in
# the candidate window before it can lift it, so the carry branch requests at
# least this many rows from the engine, then truncates back to the caller's
# ``top``. Wide enough to contain the crit amplifiers that greedy delta_dps buries
# at rank ~6-9 (measured on the 16.13.1 ARAM/SR cells).
CARRY_COHERENCE_WINDOW: int = 40

_DS_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"
_champ_attackrange_index: Optional[dict] = None


def _resolve_enemy_shares(
    enemy_ad_share: Optional[float],
    enemy_ap_share: Optional[float],
) -> tuple[float, float]:
    """Resolve the enemy damage-share pair into an engine-legal (ad, ap).

    The engine requires the pair to sum to <= 1.0. Every ranking entry point used
    to default BOTH sides to 0.5 independently, so a caller supplying only the
    side it actually knows shipped 0.77 + 0.5 = 1.27, the server rejected the
    body, and ``_post_json`` mapped that to None - the caller saw "engine
    unreachable" and rendered NO recommendation at all. A silent total failure
    from a perfectly reasonable call.

    That path stopped being hypothetical when real enemy compositions started
    feeding the ranker instead of a synthetic 50/50: measured over the rewind
    corpus, 50.1 percent of 1286 real team comps carry an AD share outside
    [0.40, 0.60].

    Rules, in order:
      * neither supplied -> the neutral (0.5, 0.5) split, so existing calls are
        byte-identical;
      * exactly one supplied -> derive the partner as ``1.0 - x``. The shares
        partition one enemy team's damage, so the complement is the only sensible
        reading, and a mid-game coach must degrade to a usable answer rather than
        to nothing;
      * both supplied -> passed through untouched, INCLUDING a deliberate
        sub-unit split (a true-damage remainder is real and must survive);
      * both supplied but summing over 1.0 -> scaled down proportionally rather
        than rejected, for the same degrade-to-usable reason.

    Inputs are clamped to [0, 1] first, so no caller can produce a body the
    engine will refuse.
    """

    def _clamp(x: float) -> float:
        return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))

    ad = None if enemy_ad_share is None else _clamp(enemy_ad_share)
    ap = None if enemy_ap_share is None else _clamp(enemy_ap_share)

    if ad is None and ap is None:
        return (0.5, 0.5)
    if ap is None:
        return (ad, _clamp(1.0 - ad))
    if ad is None:
        return (_clamp(1.0 - ap), ap)

    total = ad + ap
    if total > 1.0:
        # Proportional scale-down keeps the RATIO the caller expressed, which is
        # the load-bearing part of the signal; the absolute magnitudes are not.
        if total <= 0.0:
            return (0.5, 0.5)
        return (ad / total, ap / total)
    return (ad, ap)


def _norm_champ_key(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _canon_champ_key(s: str) -> str:
    """Index-lookup key bridging DISPLAY names onto canonical DDragon ids (RM-95).

    ``_norm_champ_key`` alone lowercases + strips punctuation, which already
    reconciles 18 of the 21 champions whose display name differs from their
    DDragon id ("Cho'Gath" -> chogath == "Chogath" -> chogath). It CANNOT
    reconcile the 3 whose display name is not a punctuation variant, because the
    name carries extra words or a different word entirely: "Wukong" ->
    MonkeyKing, "Nunu & Willump" -> Nunu, "Renata Glasc" -> Renata. Those
    resolve only through the canonical DDragon map.

    Reuses the single canonical resolver
    (:func:`core.archetype_picks.canonical_champion_id`) rather than carrying a
    second alias dict: it is derived from ``ddragon_champions.json``, so a future
    rename or release is picked up by a data refresh with no code change. The
    lazy local import mirrors the circular-import-avoidance pattern already used
    by :func:`_onhit_coherence_for` below.

    Fail-soft: an unresolvable name passes through unchanged, so this is a strict
    superset of ``_norm_champ_key`` - measured 0 regressions across every DDragon
    display name and id (173 champions).
    """
    resolved = s
    try:
        from core.archetype_picks import canonical_champion_id

        resolved = canonical_champion_id(s) or s
    except Exception:  # noqa: BLE001 - fail-soft resolver, never gate a lookup
        resolved = s
    return _norm_champ_key(resolved)


def champion_attackrange(champion: str) -> float:
    """Base attackrange from the local DS champion snapshot, keyed by
    DDragon id or display name. 0.0 when unresolved - unknown champions
    fail soft to melee so the carry gate never fires on a champ the
    snapshot cannot identify."""
    global _champ_attackrange_index
    if _champ_attackrange_index is None:
        index: dict = {}
        try:
            patch = (_DS_DATA_DIR / "current.txt").read_text(
                encoding="utf-8"
            ).strip()
            raw = (_DS_DATA_DIR / patch / "champions.json").read_text(
                encoding="utf-8"
            )
            data = json.loads(raw).get("data") or {}
            for cid, rec in data.items():
                stats = (rec or {}).get("stats") or {}
                try:
                    rng = float(stats.get("attackrange") or 0.0)
                except (TypeError, ValueError):
                    continue
                index[_norm_champ_key(cid)] = rng
                name = (rec or {}).get("name")
                if name:
                    index[_norm_champ_key(str(name))] = rng
        except (OSError, ValueError):
            index = {}
        _champ_attackrange_index = index
    return float(_champ_attackrange_index.get(_canon_champ_key(champion), 0.0))


_champ_ability_index: Optional[dict] = None


def champion_has_ability_data(champion: str) -> bool:
    """True when the local DS snapshot carries ability data for ``champion``.

    Champions released after the frozen Meraki ``latest`` content_patch have no
    entry in ``<patch>/champion_abilities.json`` (16.14.1: Locke, Zaahen - both
    absent from Meraki's bulk map, which carries 171 of 173). The dispatcher
    already detects the kit-less case for ds.ability / ds.burst / ds.hps via
    their all-zero rankings, but ds.hybrid folds ability damage into every row
    (``hybrid.py`` imports ``compute_ability_dps``) while still producing
    non-zero auto-DPS + EHP terms - so its output looks healthy and a row-delta
    check cannot flag it. This champion-level signal is what covers that branch.

    Keys normalize like :func:`champion_attackrange`, so a DDragon id
    ("LeeSin") and a display name ("Lee Sin") both resolve.

    Fail-soft: an unreadable, missing or empty index returns True for EVERY
    champion, so a snapshot problem never spuriously flags the whole roster.
    """
    global _champ_ability_index
    if _champ_ability_index is None:
        index: dict = {}
        try:
            patch = (_DS_DATA_DIR / "current.txt").read_text(
                encoding="utf-8"
            ).strip()
            raw = (_DS_DATA_DIR / patch / "champion_abilities.json").read_text(
                encoding="utf-8"
            )
            data = json.loads(raw)
            data = data.get("data") if isinstance(data.get("data"), dict) else data
            for cid in (data or {}):
                index[_norm_champ_key(str(cid))] = True
        except (OSError, ValueError, AttributeError):
            index = {}
        _champ_ability_index = index
    if not _champ_ability_index:
        return True
    return bool(_champ_ability_index.get(_canon_champ_key(champion), False))


_champ_stale_index: Optional[dict] = None


# Tri-state ability-data coverage (RM-95 / A-26). Plain lowercase strings so the
# value is JSON-serializable straight onto a diagnostic surface.
ABILITY_DATA_ABSENT = "absent"
ABILITY_DATA_STALE = "stale"
ABILITY_DATA_CURRENT = "current"


def _champion_is_stale(champion: str) -> bool:
    """True when ``champion`` is named in the RM-81 wiki staleness report.

    Fail-soft: a missing or unreadable report yields an empty index, so every
    champion reads False (not stale). Absence of evidence is not evidence of
    staleness and a report problem must never flag the whole roster.
    """
    global _champ_stale_index
    if _champ_stale_index is None:
        index: dict = {}
        try:
            patch = (_DS_DATA_DIR / "current.txt").read_text(
                encoding="utf-8"
            ).strip()
            raw = (_DS_DATA_DIR / patch / "ability_staleness.json").read_text(
                encoding="utf-8"
            )
            for cid in json.loads(raw).get("stale_champions") or []:
                index[_norm_champ_key(str(cid))] = True
        except (OSError, ValueError, AttributeError):
            index = {}
        _champ_stale_index = index
    return bool(_champ_stale_index.get(_canon_champ_key(champion), False))


def champion_ability_data_status(champion: str) -> str:
    """Tri-state ability-data coverage: ABSENT / STALE / CURRENT (RM-95).

    Composes the two guards that were previously never composed:

    * :func:`champion_has_ability_data` - "is the champion PRESENT?" (RM-79).
    * the RM-81 wiki staleness report - "are the values still RIGHT?".

    Why a third state is needed. ``tools/ds_wiki_staleness_check.py`` derives
    its target roster from ``champion_abilities.json`` itself, so a champion
    ABSENT from that file can never become a check target, never lands in
    ``stale_champions``, and therefore came back "current". The staleness
    program certified as clean exactly the champions with no ability data at
    all (16.14.1: Locke, Zaahen - both missing from Meraki's bulk map, which
    carries 171 of 173). ABSENT and STALE are also differently actionable:
    STALE is fixed by a data refresh, ABSENT is blocked upstream and cannot be.

    ABSENT wins over STALE when a champion is somehow both - there are no
    stored values to refresh, so the stronger signal is the honest one.

    THE FAIL-SOFT CONTRACT IS UNCHANGED, and the whole point of this function is
    that it keeps the two failure kinds apart:

    * A missing / unreadable REPORT (either file) is a snapshot problem. Every
      champion reads CURRENT - the roster is never flagged off a broken read.
      :func:`champion_has_ability_data` already returns True for everyone when
      its index is empty, so ABSENT is unreachable on that path by construction.
    * A champion with no entry in a PRESENT ability map is a per-champion data
      hole and reads ABSENT.

    CURRENT means "no drift proven", not "verified current": the staleness
    report under-reports by design, skipping damage labels it cannot match
    verbatim.

    Keys resolve through :func:`_canon_champ_key`, so a DDragon id ("MonkeyKing")
    and a Live Client display name ("Wukong") give the same answer.
    """
    if not champion_has_ability_data(champion):
        return ABILITY_DATA_ABSENT
    if _champion_is_stale(champion):
        return ABILITY_DATA_STALE
    return ABILITY_DATA_CURRENT


def champion_ability_data_is_current(champion: str) -> bool:
    """False when ``champion``'s ability data is STALE or ABSENT (RM-81 / RM-95).

    Thin boolean view over :func:`champion_ability_data_status` - prefer that
    function for anything diagnostic, since it separates the two failure kinds.

    RM-95 correction: this used to read ``not stale_index.get(champion)`` alone,
    which returned True for a champion with NO ability data at all, because
    absent data can never be proven drifted. It certified precisely the
    champions it should have flagged hardest. Absent data is now False - a guard
    whose job is to catch bad data must not certify data it does not have.

    Fail-soft is preserved exactly: a missing or unreadable report (of either
    kind) still returns True for every champion. See
    :func:`champion_ability_data_status` for the full contract.
    """
    return champion_ability_data_status(champion) == ABILITY_DATA_CURRENT


# Kit-dependent scorers (ds.ability / ds.burst / ds.hps) need the champion's
# ability data. A champ released after the frozen Meraki `latest` content_patch
# has NO ability entries, so those scorers return an identically-zero delta for
# every item and the ranker degenerates to the cheapest starter items (a useless
# "+0.0" build - the Locke 16.14.1 symptom). ds.dps and ds.ehp need no kit data,
# so the dispatcher detects the all-zero case and falls back to ds.dps. RC-side +
# non-regressive by construction: a real kit always scores > 0 on at least one
# item, so the guard never fires for a champ that has ability data
# (byte-identical to pre-fix behavior).
#
# CORRECTION 2026-07-18: this comment previously grouped ds.hybrid with the
# no-kit-data scorers. That is WRONG - agents/daemon_slayer/hybrid.py imports
# compute_ability_dps and folds ability damage into every row's base damage, so a
# kit-less champion loses its whole ability term there too. ds.hybrid cannot use
# _kitless_all_zero to notice (its auto-DPS + EHP terms stay non-zero, so the
# ranking looks healthy), which is why the bruiser branch flags the degraded case
# champion-side via champion_has_ability_data(). This matters most for Zaahen,
# whose DEFAULT route IS bruiser.
_KITLESS_DELTA_EPS = 1e-9


def _kitless_all_zero(rows, attr: str) -> bool:
    """True when EVERY ranked row's ``attr`` delta is ~0 (kit-less signal).
    Non-empty guard: an empty ``rows`` is build-complete / fully filtered,
    NOT kit-less, so it must not trigger the fallback."""
    return bool(rows) and all(
        abs(getattr(r, attr, 0.0) or 0.0) <= _KITLESS_DELTA_EPS for r in rows
    )


def _onhit_coherence_for(champion: str) -> float:
    """Per-champ AP/AD coherence strength from the Task-9 on-hit-AP roster.

    Slice B (2026-07-16). Fail-soft to 0.0 (off) whenever the roster
    module/loader is absent or the champion is unmapped, so a call made
    before Task 9 lands stays byte-identical to no gate at all.
    ``core/ds_onhit_ap_roster.py`` does not exist yet as of Task 7 - the
    ``except ImportError`` branch below is the ACTIVE path today, so every
    champion resolves to 0.0 (gate off) until Task 9 ships the roster +
    loader.
    """
    try:
        from core.ds_onhit_ap_roster import load_onhit_ap_roster
    except ImportError:
        return 0.0
    try:
        roster = load_onhit_ap_roster()  # {canonical_champ_id: coherence}
        key = champion
        try:
            # Local import mirrors the circular-import-avoidance pattern
            # already used for this lookup elsewhere in the codebase (e.g.
            # core/ds_antitank_hint.py) - canonicalize best-effort so a Live
            # Client display name still resolves against the roster's
            # DDragon-id keys.
            from core.archetype_picks import canonical_champion_id
            key = canonical_champion_id(champion) or champion
        except ImportError:
            pass
        return float(roster.get(key, 0.0))
    except Exception:  # noqa: BLE001 - fail-soft resolver, never gate on a roster error
        return 0.0


def rank_for_primary_archetype(
    champion: str,
    archetype: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    # DPS-side inputs (used when archetype routes to ds.dps / ds.hybrid / ds.ability / ds.burst):
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    # EHP-side inputs (used when archetype routes to ds.ehp / ds.hybrid):
    enemy_ad_share: Optional[float] = None,
    enemy_ap_share: Optional[float] = None,
    # Hybrid-only overrides (silently ignored by other scorers):
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    # Mage + assassin inputs (silently ignored by other scorers):
    target_current_hp_pct: float = 1.0,
    max_priority: Optional[tuple[str, str, str]] = None,
    block_strategy: str = "first",
    form_index: Optional[dict[str, int]] = None,
    # Assassin-only input (silently ignored by other scorers):
    combo_sequence: Optional[Iterable[str]] = None,
    # Enchanter-only input (silently ignored by other scorers):
    targets_per_proc_override: Optional[float] = None,
    # Tank/bruiser/mage/assassin/enchanter-side whitelist (silently ignored by ds.dps):
    only_item_ids: Optional[Iterable[str]] = None,
    # Common:
    top: int = 8,
    sort_by: str = "delta",
    augments: Optional[Iterable[str]] = None,
    filter_shared_uniques: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
    # Seam flags (Tier-2, behavior-preserving). Each routes to the correct
    # archetype branch only; defaults OFF/null/0.0 so a flagless call is
    # byte-identical to pre-seam behavior. Branches that don't take a given
    # flag never receive it (it stays a no-op for that archetype).
    exempt_offclass_by_win: bool = False,        # carry (DSP2)
    prefer_kit_axis_by_win: bool = False,        # carry (DSP11) + assassin (DSP11)
    cost_ceiling: Optional[int] = None,          # carry (F2) + tank + bruiser
    prefer_survivability_by_win: bool = False,   # bruiser (RF1) + tank (RF3) + enchanter (RF2)
    score_by: str = "blended",                   # tank only (Term A): + team_blended
    assume_magic_burst: bool = False,            # assassin (R30)
    assume_passive_as_stacks: bool = False,      # carry (R7)
    apply_target_vuln: bool = False,             # carry (R12)
    assume_missing_hp_heal_amp: bool = False,    # enchanter (R5)
    caster_missing_hp_pct: float = 0.0,          # enchanter (R5 input)
    assume_archetype_hp_pct: bool = False,       # carry+bruiser+mage+assassin (R55)
    apply_squishy_burst_target: bool = True,     # carry (L4) - see the swap below
    widen_carry_pool: bool = False,              # carry (RM-04 A-01)
) -> Optional[dict]:
    """Phase 3 + 4c + 5 + 6 (s176/s179/s180/s181, 2026-05-12+) - route to the right scorer per archetype.

    The DS engine ships 7 scorers (ds.dps, ds.ehp, ds.hybrid, ds.ability,
    ds.burst, ds.hps, ds.onhit) - one per archetype branch. This dispatcher
    exposes a single call shape that the coaches + UI use, routing based on
    the operator's pick from ``state.cs_archetype_pick.primary``.

    Returns a dict with shape:
        {
            "ok":          bool,
            "scorer":      "dps" | "ehp" | "hybrid" | "ability" | "burst" | "hps" | "onhit",
            "archetype":   str,   # the requested archetype (echoed)
            "ranked":      [RankedItem-like dicts],
            "fell_back":   bool,  # always False post-Phase-6 (all archetypes wired)
        }
    ``ok=False`` means the engine was unreachable. ``fell_back`` is kept
    for backward compatibility - all 7 archetype branches return
    ``fell_back=False`` now that ds.hps shipped (Phase 6 s181). Unknown
    archetype strings fall through to ds.dps with ``fell_back=False`` too.

    Args ``alpha`` / ``beta`` only apply to ``bruiser``; ``only_item_ids``
    applies to tank/bruiser/mage/assassin/enchanter; ``target_current_hp_pct``
    / ``max_priority`` / ``block_strategy`` / ``form_index`` apply to
    mage + assassin; ``combo_sequence`` applies to assassin only;
    ``targets_per_proc_override`` applies to enchanter only. Other
    archetypes silently ignore them.

    ``assume_archetype_hp_pct`` (R55, DEFAULT-OFF) opts into the archetype-aware
    DEFAULT for the ``target_current_hp_pct`` seam. When False (default) the
    behavior is EXACTLY as before: carry / bruiser get no ``target_current_hp_pct``
    override and mage / assassin get the caller's ``target_current_hp_pct``. When
    True the seam value for ALL four damage branches (carry / bruiser / mage /
    assassin) is resolved from the requested archetype via
    ``archetype_target_current_hp_pct`` (SUSTAINED / juggernaut -> 0.5, target
    ground down over the fight; BURST + non-damage / unknown -> 1.0). The live
    default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.

    ``widen_carry_pool`` (RM-04 A-01, DEFAULT-OFF) is CARRY-ONLY - it is
    forwarded to the ds.dps branch's ``rank_for`` call and never reaches the
    tank / bruiser / mage / assassin / enchanter / on-hit branches. False
    (default) omits the body key, so a flagless dispatch is byte-identical.
    """
    arch = (archetype or "").strip().lower()
    # Kit-dependent-scorer fallback (see _kitless_all_zero): default False.
    # The mage / assassin / enchanter branches set it True when they detect a
    # champ with no ability data (all-zero ranking) and fall through to ds.dps.
    fell_back = False

    # R55 (DEFAULT-OFF): resolve the archetype-aware current-HP fraction the four
    # damage branches use. When the flag is off, keep the caller's value (mage /
    # assassin) and leave carry / bruiser at their no-override default 1.0. The
    # resolver lives in core (not the engine package) so this HTTP client never
    # imports agents.daemon_slayer in-process (split-brain guard).
    if assume_archetype_hp_pct:
        effective_hp_pct = archetype_target_current_hp_pct(arch)
    else:
        effective_hp_pct = target_current_hp_pct

    # Routing table - explicit so future Phase 5-6 scorers slot in by
    # adding one branch each.
    if arch == "tank":
        rows = rank_tank_for(
            champion,
            level=level, item_ids=item_ids, mode=mode,
            enemy_ad_share=enemy_ad_share, enemy_ap_share=enemy_ap_share,
            top=top, sort_by=sort_by,
            only_item_ids=only_item_ids,
            augments=augments,
            filter_shared_uniques=filter_shared_uniques,
            timeout=timeout,
            prefer_survivability_by_win=prefer_survivability_by_win,
            cost_ceiling=cost_ceiling,
            score_by=score_by,
        )
        if rows is None:
            return None
        return {
            "ok":        True,
            "scorer":    "ehp",
            "archetype": arch,
            "ranked":    [
                {
                    "item_id":            r.item_id,
                    "item_name":          r.item_name,
                    "delta":              r.delta_ehp,
                    "gold":               r.gold,
                    "shares_dead_unique": r.shares_dead_unique,
                    "dead_unique_key":    r.dead_unique_key,
                    "unique_passive_key": r.unique_passive_key,
                    # Term A: equals "delta" unless score_by="team_blended".
                    "delta_team_blended": r.delta_team_blended_ehp,
                }
                for r in rows
            ],
            "fell_back": False,
        }

    if arch == "bruiser":
        # R55: carry / bruiser only receive the seam override when the flag is
        # on (byte-identical no-override default otherwise).
        _bruiser_hp_kwargs = (
            {"target_current_hp_pct": effective_hp_pct}
            if assume_archetype_hp_pct else {}
        )
        rows = rank_bruiser_for(
            champion,
            level=level, item_ids=item_ids, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            enemy_ad_share=enemy_ad_share, enemy_ap_share=enemy_ap_share,
            top=top, sort_by=sort_by,
            only_item_ids=only_item_ids,
            augments=augments,
            filter_shared_uniques=filter_shared_uniques,
            alpha=alpha, beta=beta,
            timeout=timeout,
            prefer_survivability_by_win=prefer_survivability_by_win,
            cost_ceiling=cost_ceiling,
            **_bruiser_hp_kwargs,
        )
        if rows is None:
            return None
        return {
            "ok":        True,
            "scorer":    "hybrid",
            "archetype": arch,
            "ranked":    [
                {
                    "item_id":            r.item_id,
                    "item_name":          r.item_name,
                    "delta_dps":          r.delta_dps,
                    "delta_ehp":          r.delta_ehp,
                    "hybrid_delta_pct":   r.hybrid_delta_pct,
                    "gold":               r.gold,
                    "shares_dead_unique": r.shares_dead_unique,
                    "dead_unique_key":    r.dead_unique_key,
                    "unique_passive_key": r.unique_passive_key,
                }
                for r in rows
            ],
            # ds.hybrid folds compute_ability_dps into every row's base damage
            # (agents/daemon_slayer/hybrid.py), so a kit-less champion silently
            # loses its whole ability term here. A row-delta check cannot see it
            # (auto-DPS + EHP are still non-zero), so flag it champion-side.
            "fell_back": fell_back or not champion_has_ability_data(champion),
        }

    if arch == "mage":
        rows = rank_mage_for(
            champion,
            level=level, item_ids=item_ids, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            # R55: effective_hp_pct == the caller's target_current_hp_pct when
            # the flag is off (byte-identical); the archetype default when on.
            target_current_hp_pct=effective_hp_pct,
            top=top, sort_by=sort_by,
            only_item_ids=only_item_ids,
            augments=augments,
            max_priority=max_priority,
            block_strategy=block_strategy,
            form_index=form_index,
            filter_shared_uniques=filter_shared_uniques,
            timeout=timeout,
        )
        if rows is None:
            return None
        if not _kitless_all_zero(rows, "delta_ability_dps"):
            return {
                "ok":        True,
                "scorer":    "ability",
                "archetype": arch,
                "ranked":    [
                    {
                        "item_id":            r.item_id,
                        "item_name":          r.item_name,
                        "delta":              r.delta_ability_dps,
                        "new_ability_dps":    r.new_ability_dps,
                        "gold":               r.gold,
                        "shares_dead_unique": r.shares_dead_unique,
                        "dead_unique_key":    r.dead_unique_key,
                        "unique_passive_key": r.unique_passive_key,
                    }
                    for r in rows
                ],
                "fell_back": False,
            }
        # Kit-less champ (no ability data in the frozen Meraki snapshot):
        # fall through to ds.dps below rather than serve an all-zero build.
        fell_back = True

    if arch == "assassin":
        rows = rank_assassin_for(
            champion,
            level=level, item_ids=item_ids, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            # R55: effective_hp_pct == the caller's target_current_hp_pct when
            # the flag is off (byte-identical); the archetype default when on.
            target_current_hp_pct=effective_hp_pct,
            top=top, sort_by=sort_by,
            only_item_ids=only_item_ids,
            augments=augments,
            max_priority=max_priority,
            block_strategy=block_strategy,
            form_index=form_index,
            combo_sequence=combo_sequence,
            filter_shared_uniques=filter_shared_uniques,
            timeout=timeout,
            prefer_kit_axis_by_win=prefer_kit_axis_by_win,
            assume_magic_burst=assume_magic_burst,
        )
        if rows is None:
            return None
        if not _kitless_all_zero(rows, "delta_burst"):
            return {
                "ok":        True,
                "scorer":    "burst",
                "archetype": arch,
                "ranked":    [
                    {
                        "item_id":            r.item_id,
                        "item_name":          r.item_name,
                        "delta":              r.delta_burst,
                        "new_burst":          r.new_burst,
                        "gold":               r.gold,
                        "shares_dead_unique": r.shares_dead_unique,
                        "dead_unique_key":    r.dead_unique_key,
                        "unique_passive_key": r.unique_passive_key,
                    }
                    for r in rows
                ],
                "fell_back": False,
            }
        # Kit-less champ (no ability data in the frozen Meraki snapshot):
        # fall through to ds.dps below rather than serve an all-zero build.
        fell_back = True

    if arch == "enchanter":
        rows = rank_enchanter_for(
            champion,
            level=level, item_ids=item_ids, mode=mode,
            top=top, sort_by=sort_by,
            only_item_ids=only_item_ids,
            augments=augments,
            targets_per_proc_override=targets_per_proc_override,
            filter_shared_uniques=filter_shared_uniques,
            timeout=timeout,
            prefer_survivability_by_win=prefer_survivability_by_win,
            assume_missing_hp_heal_amp=assume_missing_hp_heal_amp,
            caster_missing_hp_pct=caster_missing_hp_pct,
        )
        if rows is None:
            return None
        if not _kitless_all_zero(rows, "delta_hps"):
            return {
                "ok":        True,
                "scorer":    "hps",
                "archetype": arch,
                "ranked":    [
                    {
                        "item_id":            r.item_id,
                        "item_name":          r.item_name,
                        "delta":              r.delta_hps,
                        "new_hps":            r.new_hps,
                        "gold":               r.gold,
                        "shares_dead_unique": r.shares_dead_unique,
                        "dead_unique_key":    r.dead_unique_key,
                        "unique_passive_key": r.unique_passive_key,
                    }
                    for r in rows
                ],
                "fell_back": False,
            }
        # Kit-less champ (no ability data in the frozen Meraki snapshot):
        # fall through to ds.dps below rather than serve an all-zero build.
        fell_back = True

    if arch == "onhit":
        rows = rank_onhit_for(
            champion,
            level=level, item_ids=item_ids, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            top=top, sort_by=sort_by,
            only_item_ids=only_item_ids,
            augments=augments,
            filter_shared_uniques=filter_shared_uniques,
            timeout=timeout,
            apply_passive_damage=True,
            ap_ad_coherence=_onhit_coherence_for(champion),
        )
        if rows is None:
            return None
        # No kitless-all-zero fallback for onhit: it scores off autos+abilities,
        # so a roster champ always has data. None already means engine-down.
        return {
            "ok":        True,
            "scorer":    "onhit",
            "archetype": arch,
            "ranked":    [
                {
                    "item_id":            r.item_id,
                    "item_name":          r.item_name,
                    "delta":              r.delta_dps,
                    "delta_dps":          r.delta_dps,
                    "gold":               r.gold,
                    "shares_dead_unique": r.shares_dead_unique,
                    "dead_unique_key":    r.dead_unique_key,
                    "unique_passive_key": r.unique_passive_key,
                }
                for r in rows
            ],
            "fell_back": False,
        }

    # carry / anything else -> fall through to ds.dps.
    # Post-Phase-6 (s181): all 6 archetypes have their own scorer; this path
    # handles only the catch-all (empty string, unknown labels) AND the
    # kit-less ability/burst/hps fallback (fell_back was set True above when a
    # kit-dependent branch produced an all-zero ranking).
    # R55: carry only receives the seam override when the flag is on
    # (byte-identical no-override default otherwise).
    _carry_hp_kwargs = (
        {"target_current_hp_pct": effective_hp_pct}
        if assume_archetype_hp_pct else {}
    )
    # Per-champion burst-carry calibration (Jhin pilot): consult the allow-map
    # for a SHORT fight_length that tilts the carry / ds.dps blend toward the
    # champ's lethality-crit burst core. A champion ABSENT from the map resolves
    # to None -> rank_for omits the body key -> byte-identical default ranking.
    # Applied here at the shared carry chokepoint so BOTH the live per-tick coach
    # path and the offline build-order / loadout backfill engage it identically.
    _carry_fight_length = champion_fight_length(champion)
    # L4 squishy-carry target swap (2026-07-13, docs/specs/2026-07-13-ds-crit-
    # burst-fix.md): a MAPPED burst carry (_carry_fight_length engaged) deletes
    # the enemy CARRY, not the tanky team AVERAGE the caller's target encodes
    # (coach_integration.enemy_stats). Swap in the squishy-carry stat line
    # (core.ds_burst_target.squishy_carry_target) so crit / lethality-execute
    # (Infinity Edge / The Collector) out-value front-loaded current-HP on-hit
    # (BORK) the way they do against a real squishy. Auto-scoped to the
    # fight_length allow-map: a NON-mapped champion (_carry_fight_length is None)
    # keeps the caller's target UNCHANGED (byte-identical). Covers both the live
    # coach path and the offline build-order backfill (shared chokepoint). mode +
    # level are in scope here.
    #
    # OPT-OUT (apply_squishy_burst_target=False): a caller that supplies its OWN
    # deliberate enemy target - the build_order_variants anti_tank (a WALL) /
    # anti_squishy (a GLASS comp) cells - must NOT have that target overridden by
    # the squishy swap, or the two variants collapse onto each other for a mapped
    # crit ADC (the anti_tank pen build would be lost). Such callers pass
    # apply_squishy_burst_target=False and keep their explicit target. The live
    # per-tick coach path leaves it at the default True (the fix intent).
    if _carry_fight_length is not None and apply_squishy_burst_target:
        _sq = squishy_carry_target(mode, level)
        _tgt_armor = _sq["target_armor"]
        _tgt_mr = _sq["target_mr"]
        _tgt_max_hp = _sq["target_max_hp"]
        _tgt_bonus_hp = _sq["target_bonus_hp"]
    else:
        _tgt_armor = target_armor
        _tgt_mr = target_mr
        _tgt_max_hp = target_max_hp
        _tgt_bonus_hp = target_bonus_hp
    # Carry build-coherence re-rank (Step 1, 2026-07-13): request a WIDER window
    # so the buried crit AMPLIFIER core (Infinity Edge etc.) is present, then a
    # metric coherence re-rank (core.build_planner.coherence.coherence_rerank)
    # docks cross-archetype artifacts (Essence Reaver / Eclipse) below it. The
    # re-rank truncates back to the caller's ``top`` and is carry-scoped by
    # control flow (non-carry archetypes return earlier). NOT win-rate, NOT a
    # hand-blacklist - a continuous metric dock from kit_synergy primitives.
    _carry_window = max(int(top), CARRY_COHERENCE_WINDOW)
    rows = rank_for(
        champion,
        level=level, item_ids=item_ids, mode=mode,
        target_armor=_tgt_armor, target_mr=_tgt_mr,
        target_max_hp=_tgt_max_hp, target_bonus_hp=_tgt_bonus_hp,
        top=_carry_window, sort_by=sort_by,
        only_item_ids=only_item_ids,
        augments=augments,
        filter_shared_uniques=filter_shared_uniques,
        timeout=timeout,
        exempt_offclass_by_win=exempt_offclass_by_win,
        prefer_kit_axis_by_win=prefer_kit_axis_by_win,
        cost_ceiling=cost_ceiling,
        assume_passive_as_stacks=assume_passive_as_stacks,
        apply_target_vuln=apply_target_vuln,
        fight_length=_carry_fight_length,
        widen_carry_pool=widen_carry_pool,
        **_carry_hp_kwargs,
    )
    if rows is None:
        return None
    # Ranged-carry off-class gate (item 208 carry) - see the constants
    # above for why this lives client-side at the shared carry chokepoint.
    if champion_attackrange(champion) >= CARRY_RANGED_ATTACKRANGE_FLOOR:
        rows = [
            r for r in rows
            if r.item_name not in CARRY_RANGED_OFFCLASS_ITEM_NAMES
        ]
    # Coherence re-rank + truncate to the caller's requested top (byte-identical
    # no-op for a non-carry archetype - see coherence_rerank). Thread the same
    # per-champion fight_length used above (L1 crit-burst fix, 2026-07-13) so the
    # re-rank sorts on the burst-inclusive effective_score when the knob is
    # engaged instead of neutralizing it with a raw-delta_dps re-sort; None /
    # <= 0 (no allow-map entry) keeps the byte-identical default order.
    rows = coherence_rerank(
        rows, champion, top=int(top), fight_length=_carry_fight_length,
    )
    return {
        "ok":        True,
        "scorer":    "dps",
        # On a kit-less fallback (fell_back) the served build IS a ds.dps
        # carry build, so echo "carry" for a coherent label instead of the
        # requested-but-unservable mage/assassin/enchanter. Genuine
        # carry/unknown callers keep the existing "" -> "carry" behavior.
        "archetype": "carry" if fell_back else (arch or "carry"),
        "ranked":    [
            {
                "item_id":            r.item_id,
                "item_name":          r.item_name,
                "delta":              r.delta_dps,
                "gold":               r.gold,
                "shares_dead_unique": r.shares_dead_unique,
                "dead_unique_key":    r.dead_unique_key,
                "unique_passive_key": r.unique_passive_key,
            }
            for r in rows
        ],
        "fell_back": fell_back,
    }


def dps_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    augments: Optional[Iterable[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """Call POST /dps and return the raw result dict. None on failure.

    See ``rank_for`` for ``target_max_hp`` / ``target_bonus_hp`` semantics.
    """
    body = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
    }
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    return _post_json("/dps", body, timeout=timeout)


def matchup(
    champ_a: str,
    champ_b: str,
    *,
    level_a: int = 1,
    level_b: int = 1,
    item_ids_a: Optional[Iterable[str]] = None,
    item_ids_b: Optional[Iterable[str]] = None,
    mode: str = "SR",
    hp_a_pct: float = 1.0,
    hp_b_pct: float = 1.0,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """Call POST /v2/matchup and return the raw MatchupResult dict. None on failure.

    Lane A 1v1 head-to-head trade resolution - the deterministic substitute for
    an LLM "who wins this trade" judgment. Same engine-down semantics as the
    other ``*_for`` helpers (None = unreachable).

    Result dict carries ``verdict`` (one of all_in / trade / back_off / even),
    ``net_swing`` (who-wins scalar in [-1, 1], positive = A favored),
    ``pct_a_removed`` / ``pct_b_removed`` (capped fraction of each side's
    effective HP removed by one combo), plus the raw damage + mana-gate fields.
    ``hp_a_pct`` / ``hp_b_pct`` are the current-HP-pct assumption for each side.
    """
    body: dict = {
        "champ_a": champ_a,
        "champ_b": champ_b,
        "level_a": int(level_a),
        "level_b": int(level_b),
        "item_ids_a": [str(i) for i in (item_ids_a or []) if i],
        "item_ids_b": [str(i) for i in (item_ids_b or []) if i],
        "mode": mode,
        "hp_a_pct": float(hp_a_pct),
        "hp_b_pct": float(hp_b_pct),
    }
    return _post_json("/v2/matchup", body, timeout=timeout)

"""Thin HTTP client for the local Daemon Slayer engine on :8893.

Phase 7 wire-in. Coach ticks need a non-blocking call into the engine
that fails silently when the server isn't up - the engine is opt-in
infrastructure, never load-bearing. Timeouts are tight (250 ms connect,
500 ms read) so a slow engine can't stall a coach loop.

Owners of name→id resolution: see ``core.daemon_slayer_resolver``. This
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
        )


def rank_tank_for(
    champion: str,
    *,
    level: int,
    item_ids: Iterable[str],
    mode: str = "SR",
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    top: int = 8,
    sort_by: str = "delta",
    only_item_ids: Optional[Iterable[str]] = None,
    augments: Optional[Iterable[str]] = None,
    filter_shared_uniques: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[list[TankRankedItem]]:
    """Call POST /rank-tank and return the parsed top-N rows. None on engine failure.

    Phase 1 (s174, 2026-05-12) - Tank EHP scorer. Same engine-down semantics as
    ``rank_for`` (None = unreachable, [] = nothing to recommend).

    ``enemy_ad_share`` / ``enemy_ap_share`` are floats in [0,1] summing to ≤ 1.0;
    remainder is true-damage share. Defaults to 50/50 as a "no info" baseline.

    ``only_item_ids`` is the integration point for ``core/defensive_picks.py``
    Option B layering - pass the curated defensive item catalog as a whitelist
    so the EHP-driven ranking happens within an operator-vetted pool.
    """
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "enemy_ad_share": float(enemy_ad_share),
        "enemy_ap_share": float(enemy_ap_share),
        "top": int(top),
        "sort": sort_by,
        "filter_shared_uniques": bool(filter_shared_uniques),
    }
    if only_item_ids is not None:
        body["only"] = [str(i) for i in only_item_ids if i]
    if augments:
        body["augments"] = [str(a) for a in augments if a]
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
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    augments: Optional[Iterable[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """Call POST /ehp and return the raw result dict. None on failure.

    Phase 1 sibling of ``dps_for``. See ``rank_tank_for`` for share semantics.
    """
    body: dict = {
        "champion": champion,
        "level": int(level),
        "items": [str(i) for i in item_ids if i],
        "mode": mode,
        "enemy_ad_share": float(enemy_ad_share),
        "enemy_ap_share": float(enemy_ap_share),
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
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    top: int = 8,
    sort_by: str = "delta",
    only_item_ids: Optional[Iterable[str]] = None,
    augments: Optional[Iterable[str]] = None,
    filter_shared_uniques: bool = True,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[list[BruiserRankedItem]]:
    """Call POST /rank-bruiser and return the parsed top-N rows. None on engine failure.

    Phase 2 (s175, 2026-05-12) - Bruiser hybrid scorer. Same engine-down
    semantics as ``rank_for`` (None = unreachable, [] = nothing to recommend).

    ``alpha`` / ``beta`` default to per-champion ``archetype_weights.json``
    lookup server-side; pass explicit floats only when overriding (UI sliders,
    operator mid-game retune).
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
        "enemy_ad_share": float(enemy_ad_share),
        "enemy_ap_share": float(enemy_ap_share),
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
    (default Q→W→E server-side); ``block_strategy`` is first|sum|max for
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
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    augments: Optional[Iterable[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """Call POST /hybrid and return the raw result dict. None on failure.

    Phase 2 sibling of ``dps_for`` and ``ehp_for``. See ``rank_bruiser_for``
    for alpha/beta semantics.
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
        "enemy_ad_share": float(enemy_ad_share),
        "enemy_ap_share": float(enemy_ap_share),
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
) -> Optional[list[EnchanterRankedItem]]:
    """Call POST /rank-enchanter and return the parsed top-N rows. None on engine failure.

    Phase 6 (s181, 2026-05-13) - Enchanter healing throughput scorer. Same
    engine-down semantics as ``rank_for`` (None = unreachable, [] = nothing
    to recommend).

    ``targets_per_proc_override`` replaces the per-item curated targets count
    for ALL items in the build (Arena 2v2 → override=1).
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
CARRY_RANGED_ATTACKRANGE_FLOOR: float = 350.0

CARRY_RANGED_OFFCLASS_ITEM_NAMES: frozenset = frozenset({
    "Trinity Force",
    "Bastionbreaker",
    "Heartsteel",
    "Umbral Glaive",
})

_DS_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"
_champ_attackrange_index: Optional[dict] = None


def _norm_champ_key(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


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
    return float(_champ_attackrange_index.get(_norm_champ_key(champion), 0.0))


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
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
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
) -> Optional[dict]:
    """Phase 3 + 4c + 5 + 6 (s176/s179/s180/s181, 2026-05-12+) - route to the right scorer per archetype.

    The DS engine ships 6 scorers (ds.dps, ds.ehp, ds.hybrid, ds.ability,
    ds.burst, ds.hps) - one per archetype branch. This dispatcher exposes
    a single call shape that the coaches + UI use, routing based on the
    operator's pick from ``state.cs_archetype_pick.primary``.

    Returns a dict with shape:
        {
            "ok":          bool,
            "scorer":      "dps" | "ehp" | "hybrid" | "ability" | "burst" | "hps",
            "archetype":   str,   # the requested archetype (echoed)
            "ranked":      [RankedItem-like dicts],
            "fell_back":   bool,  # always False post-Phase-6 (all archetypes wired)
        }
    ``ok=False`` means the engine was unreachable. ``fell_back`` is kept
    for backward compatibility - all 6 archetype branches return
    ``fell_back=False`` now that ds.hps shipped (Phase 6 s181). Unknown
    archetype strings fall through to ds.dps with ``fell_back=False`` too.

    Args ``alpha`` / ``beta`` only apply to ``bruiser``; ``only_item_ids``
    applies to tank/bruiser/mage/assassin/enchanter; ``target_current_hp_pct``
    / ``max_priority`` / ``block_strategy`` / ``form_index`` apply to
    mage + assassin; ``combo_sequence`` applies to assassin only;
    ``targets_per_proc_override`` applies to enchanter only. Other
    archetypes silently ignore them.
    """
    arch = (archetype or "").strip().lower()

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
                }
                for r in rows
            ],
            "fell_back": False,
        }

    if arch == "bruiser":
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
            "fell_back": False,
        }

    if arch == "mage":
        rows = rank_mage_for(
            champion,
            level=level, item_ids=item_ids, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            target_current_hp_pct=target_current_hp_pct,
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

    if arch == "assassin":
        rows = rank_assassin_for(
            champion,
            level=level, item_ids=item_ids, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            target_current_hp_pct=target_current_hp_pct,
            top=top, sort_by=sort_by,
            only_item_ids=only_item_ids,
            augments=augments,
            max_priority=max_priority,
            block_strategy=block_strategy,
            form_index=form_index,
            combo_sequence=combo_sequence,
            filter_shared_uniques=filter_shared_uniques,
            timeout=timeout,
        )
        if rows is None:
            return None
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
        )
        if rows is None:
            return None
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

    # carry / anything else → fall through to ds.dps.
    # Post-Phase-6 (s181): all 6 archetypes have their own scorer; this
    # path handles only the catch-all (empty string, unknown labels).
    fell_back = False
    rows = rank_for(
        champion,
        level=level, item_ids=item_ids, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        top=top, sort_by=sort_by,
        only_item_ids=only_item_ids,
        augments=augments,
        filter_shared_uniques=filter_shared_uniques,
        timeout=timeout,
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
    return {
        "ok":        True,
        "scorer":    "dps",
        "archetype": arch or "carry",
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

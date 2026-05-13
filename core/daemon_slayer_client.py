"""Thin HTTP client for the local Daemon Slayer engine on :8893.

Phase 7 wire-in. Coach ticks need a non-blocking call into the engine
that fails silently when the server isn't up — the engine is opt-in
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

    @classmethod
    def from_dict(cls, d: dict) -> "RankedItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            item_name=str(d.get("item_name", "")),
            delta_dps=float(d.get("delta_dps", 0.0)),
            gold=int(d.get("gold", 0)),
            shares_dead_unique=bool(d.get("shares_dead_unique", False)),
            dead_unique_key=str(d.get("dead_unique_key", "")),
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
        logger.info("daemon_slayer not running — spawned %s", launcher.name)
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
    augments: Optional[Iterable[str]] = None,
    filter_shared_uniques: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[list[RankedItem]]:
    """Call POST /rank and return the parsed top-N rows. None on engine failure.

    Empty list (vs. None) means the engine responded but had no candidates
    — e.g. champion already has 6 mode-legal items. Callers should treat
    None and [] differently (engine down vs. nothing to recommend).

    ``augments`` is an optional list of Arena augment apiName strings (e.g.
    ``["TheBrutalizer", "ItsCritical"]``); engine applies registered stat
    overlays before computing DPS. Unknown apiNames are silently skipped
    server-side.

    ``target_max_hp`` (Phase 4 batch 5) activates %-target-HP procs
    (BotRK, Eclipse). ``target_bonus_hp`` (Phase 4 batch 19) activates
    target-conditional damage amps (LDR Giant Slayer). Both default
    0.0 — engine treats 0 as "no signal" and procs gracefully no-op,
    so pre-batch callers see identical behavior.
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
    if augments:
        body["augments"] = [str(a) for a in augments if a]
    data = _post_json("/rank", body, timeout=timeout)
    if data is None:
        return None
    ranked = data.get("ranked") or []
    return [RankedItem.from_dict(r) for r in ranked]


@dataclass(frozen=True)
class TankRankedItem:
    """Mirror of ``agents.daemon_slayer.ehp.EhpRankedItem`` — EHP scorer
    Phase 1 sibling of ``RankedItem``."""
    item_id: str
    item_name: str
    delta_ehp: float
    gold: int
    shares_dead_unique: bool = False
    dead_unique_key: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "TankRankedItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            item_name=str(d.get("item_name", "")),
            delta_ehp=float(d.get("delta_ehp", 0.0)),
            gold=int(d.get("gold", 0)),
            shares_dead_unique=bool(d.get("shares_dead_unique", False)),
            dead_unique_key=str(d.get("dead_unique_key", "")),
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

    Phase 1 (s174, 2026-05-12) — Tank EHP scorer. Same engine-down semantics as
    ``rank_for`` (None = unreachable, [] = nothing to recommend).

    ``enemy_ad_share`` / ``enemy_ap_share`` are floats in [0,1] summing to ≤ 1.0;
    remainder is true-damage share. Defaults to 50/50 as a "no info" baseline.

    ``only_item_ids`` is the integration point for ``core/defensive_picks.py``
    Option B layering — pass the curated defensive item catalog as a whitelist
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
    """Mirror of ``agents.daemon_slayer.hybrid.HybridRankedItem`` — Phase 2
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

    Phase 2 (s175, 2026-05-12) — Bruiser hybrid scorer. Same engine-down
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

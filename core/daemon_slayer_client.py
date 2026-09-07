"""Thin HTTP client for the local Daemon Slayer engine on :8860.

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
DEFAULT_PORT = 8860
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


def _emit_ehp_family_seams(body: dict, **seams: bool) -> None:
    """Write the True members of the RM-115 EHP-family seam block into ``body``.

    All twenty seams in this block are ``_opt_bool`` server-side with an engine
    default of False, so the emit rule is uniform: a False (or absent) flag
    writes NOTHING, keeping the request byte-identical to every pre-seam call.
    That uniformity is why this is one helper rather than the same four-line
    ``if`` repeated seventy-six times across the four entry points.

    The seam NAMES stay declared as explicit keyword arguments on each calling
    function - never ``**kwargs`` - because
    ``agents/daemon_slayer/tests/test_route_seams_reach_the_client_per_route.py``
    reads those signatures to decide whether a route's seams are reachable, and
    a passthrough would make an unreachable seam look wired.
    """
    for name, on in seams.items():
        if on:
            body[name] = True


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

    Called once at RC dashboard startup. No-op if :8860 is healthy.
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
    # W2 conversion seams - appended LAST per the repo convention. Both are
    # parsed off the SAME POST /rank body server-side (server.py:481 / :488).
    kit_conversion_strength: float = 0.0,    # RM-86 L1 lever
    apply_crit_conversion: bool = False,     # A-12 / RM-46 (Ashe Frost Shot)
    apply_ad_axis_ability_damage: bool = False,  # RM-36 / RM-38 (AD-caster)
    # RM-36 dual-scaling SPLIT credit - MODIFIER of the flag above, inert on
    # its own. Without it the AD-axis term is exactly 0.0 for Ezreal.
    apply_ad_axis_dual_scaling_split: bool = False,
    apply_passive_damage: bool = False,       # RM-42 (kit-passive registry)
    apply_extra_shot_procs: bool = False,     # RM-42 follow-on (extra shot)
    # RM-115 tail (1.254.0) - the two seams /rank parses that no client
    # function could express. DEFAULT-OFF; omitted key == byte-identical.
    apply_mode_modifiers: bool = False,
    exclude_off_axis_items: bool = False,
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

    ``kit_conversion_strength`` (RM-86 L1, DEFAULT-0.0) and
    ``apply_crit_conversion`` (A-12 / RM-46, DEFAULT-OFF) are the two
    champion-selective conversion seams. Both were already parsed by the server
    (``agents/daemon_slayer/server.py:481`` / ``:488``) and accepted by the
    engine (``rank.py:918`` / ``:921``) but had NO client plumb, so the Ashe +
    Quinn fixes shipped 2026-07-25 could not reach a live coach tick or a
    generated build table. The engine gates are NOT symmetric:
    ``apply_crit_conversion`` is a bool whose omit-value is False, while
    ``kit_conversion_strength`` is a float that ``rank.py:1303-1305`` consults
    the registry for ONLY when it is ``> 0.0``. Each key is therefore emitted
    only when it would actually do something, keeping a flagless request
    byte-identical to the pre-plumb path.

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
    # RM-86 L1: the engine consults the kit-conversion registry only when the
    # lever is strictly positive (rank.py:1303-1305), so 0.0 and any negative
    # are inert server-side - emit nothing and stay byte-identical.
    if kit_conversion_strength > 0.0:
        body["kit_conversion_strength"] = float(kit_conversion_strength)
    # A-12 / RM-46: bool seam, engine default False - emit only when ON.
    if apply_crit_conversion:
        body["apply_crit_conversion"] = True
    if apply_ad_axis_ability_damage:
        body["apply_ad_axis_ability_damage"] = True
    if apply_ad_axis_dual_scaling_split:
        body["apply_ad_axis_dual_scaling_split"] = True
    if apply_passive_damage:
        body["apply_passive_damage"] = True
    if apply_extra_shot_procs:
        body["apply_extra_shot_procs"] = True
    # RM-115 tail: bool seams, engine default False - emit only when ON.
    #
    # apply_mode_modifiers has TWO lanes and only one can reorder. The
    # MULTIPLIER lane (urf/ofa/usb/nb dmg_dealt) scales weighted_dps
    # uniformly, so every delta scales by the same constant and a delta sort
    # is invariant under uniform scale - measured on Jhin mode=URF, the top
    # row moves exactly x1.01 and all 214 rows keep their order. The ADDEND
    # lane (ar/swift growth addends) shifts base AD and base AS
    # non-uniformly and DOES reorder (Quinn mode=ARENA, 34 of 148 rows).
    # ``mode`` is the transport; SR and ARAM are both inert.
    if apply_mode_modifiers:
        body["apply_mode_modifiers"] = True
    # exclude_off_axis_items strips rows rather than reordering them, and on
    # this auto-attack scorer every stripped row is DEEP - Jhin at the client
    # default top=8 is byte-identical, and only widens at top >= 50. ``top``
    # is therefore a load-bearing transport for observing this seam.
    if exclude_off_axis_items:
        body["exclude_off_axis_items"] = True
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
    # R194 slice A (2026-07-26): the vamp-inclusive EHP delta. Equals
    # ``delta_ehp`` unless the caller asked for score_by="sustain" AND armed
    # ``assume_max_stacks_omnivamp``. Parsed explicitly for the same reason as
    # the Term A field above - dropping the ACTIVE field is how a live re-rank
    # silently reads as inert.
    delta_sustain_ehp: float = 0.0

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
            delta_sustain_ehp=float(
                d.get("delta_sustain_ehp", d.get("delta_ehp", 0.0))
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
    score_by: str = "blended",                  # Term A: + team_blended; R194: + sustain
    # 2026-07-25: the three ASSUMED-INCOMING-SHARE seams. These are the ONLY
    # seams on this route that ship DEFAULT-ON in the engine (a champion-blind
    # 0.5 incoming crit / basic-attack share), so what a caller needs is an OFF
    # switch. ``None`` = inherit the engine default and OMIT the key entirely,
    # which keeps a flagless call byte-identical. Appended at END per the
    # no-mid-signature-insert convention.
    assume_item_crit_dr: Optional[bool] = None,
    assume_item_aa_dr: Optional[bool] = None,
    assume_item_enemy_as_slow: Optional[bool] = None,
    # RM-87 / row A-18: the champion RESIST -> DAMAGE coupling lever
    # (/rank-tank only, sort-only). Both default None -> key omitted -> the
    # engine's DEFAULT-OFF path, byte-identical.
    apply_resist_damage_coupling: Optional[bool] = None,
    resist_coupling_strength: Optional[float] = None,
    # RM-115 transport: the four routes have always parsed an ``enemies``
    # roster, and no client function sent one. Four seams in the block below
    # (apply_spell_shield, apply_item_spell_shield, apply_champion_tenacity,
    # apply_build_tenacity) consume it and are INERT without it, so wiring the
    # flags alone would have made them reachable and dead.
    enemies: Optional[Iterable[str]] = None,
    # RM-115 EHP-family seam block - appended LAST per the repo convention.
    # All bools, all DEFAULT-OFF, all emitted only when True. ``rune_ids`` is
    # the transport the four apply_rune_* seams ride; _route_rank_tank has
    # always parsed it and no client function sent it.
    rune_ids: Optional[Iterable[str]] = None,
    apply_item_resist_grants: bool = False,
    apply_item_bonus_hp_amp: bool = False,
    apply_item_mana_health: bool = False,
    apply_item_spell_shield: bool = False,
    apply_spell_shield: bool = False,
    apply_passive_resist: bool = False,
    apply_passive_mitigation: bool = False,
    apply_passive_revive: bool = False,
    apply_champion_tenacity: bool = False,
    apply_survival_window: bool = False,
    apply_mode_modifiers: bool = False,
    apply_rune_resist_grants: bool = False,
    apply_rune_health_grants: bool = False,
    apply_rune_hsp_amp: bool = False,
    apply_rune_flat_mitigation: bool = False,
    assume_item_general_dr: bool = False,
    assume_item_health_stacks: bool = False,
    assume_item_proc_heal: bool = False,
    # TRI-STATE, unlike every other seam in this block. ``_route_rank_tank``
    # (server.py:701-703) reads it as None-when-absent, and the engine turns it
    # ON by default for the cc_blended metric - so this is an OFF switch, and a
    # plain ``bool = False`` with emit-when-True could never express the OFF.
    # None = inherit (omit the key), False = explicitly disable.
    apply_build_tenacity: Optional[bool] = None,
    # R194 slice A (RM-116 part a): the item-passive omnivamp credit on the
    # RANKER lane, appended at END per the repo convention. Plain DEFAULT-OFF
    # bool emitted only when True. It is INERT unless ``score_by="sustain"`` is
    # also sent - the credit lands on the sustain metric alone - which is why
    # the two are documented as a pair rather than as independent switches.
    assume_max_stacks_omnivamp: bool = False,
    # RM-91 T1: the champion HEALTH -> DAMAGE coupling lever (/rank-tank only,
    # sort-only), the health-axis twin of the RM-87 pair above and a SEPARATE
    # flag because the two registries are disjoint. Both default None -> key
    # omitted -> the engine's DEFAULT-OFF path, byte-identical. Appended at END
    # per the no-mid-signature-insert convention.
    apply_health_damage_coupling: Optional[bool] = None,
    health_coupling_strength: Optional[float] = None,
    # RM-91 T2: the ITEM caster-HP proc lever (/rank-tank only, sort-only) - the
    # half that fixes the row's headline. T1 above is monotone in the candidate's
    # health delta and so cannot reorder two health items; this pair credits the
    # candidate ITEM's own caster-HP-scaling proc and is keyed by ITEM ID, so a
    # zero-proc item (Randuin's Omen 3143) earns nothing regardless of how much
    # health it grants. A SEPARATE flag from T1 because the two credit different
    # payers, so arming one must never silently arm the other. Both default None
    # -> key omitted -> the engine's DEFAULT-OFF path, byte-identical.
    apply_item_caster_hp_proc: Optional[bool] = None,
    item_caster_hp_proc_strength: Optional[float] = None,
    # RM-118: the wielder HSP ITEM-amp on the RANKER lane, mirroring ``ehp_for``
    # (the scalar lane wired at R197). Plain DEFAULT-OFF bool, emitted only when
    # True so a flagless call is byte-identical. Appended at END per the
    # no-mid-signature-insert convention.
    assume_hsp_amp: bool = False,
    # RM-118 residual: the per-instance FLAT damage-block credit (Fizz P, Amumu E,
    # Leona W) on the RANKER lane. The ONLY one of the four survivability seams
    # ``ehp_for`` gained that ``rank_items_by_ehp`` accepts - the other three are
    # scalar-only, so this function must NOT grow them or it would send keys
    # ``_route_rank_tank`` does not parse. Plain DEFAULT-OFF bool, emitted only
    # when True. Appended at END per the no-mid-signature-insert convention.
    assume_passive_flat_mitigation: bool = False,
    # RM-118 residual (2026-07-30): the two SELF-side rune survivability lanes on
    # the RANKER lane. ``rank_items_by_ehp`` names BOTH (ehp.py:3161-3162), so
    # unlike the three scalar-only seams noted above these are a real sort input
    # here. Routed through ``_emit_ehp_family_seams`` because all four of that
    # helper's callers now post to a route that parses them.
    apply_rune_self_heal: bool = False,
    apply_rune_shield_grants: bool = False,
    # RM-118 mana lane: the champion MANA -> DAMAGE coupling lever (/rank-tank
    # only, sort-only), the MANA-axis twin of the RM-87 resist pair and the
    # RM-91 T1 health pair above. A SEPARATE flag from both because the three
    # registries are disjoint - a merged flag would arm a mana credit on a
    # resist converter. Both default None -> key omitted -> the engine's
    # DEFAULT-OFF path, byte-identical. Appended at END per the
    # no-mid-signature-insert convention.
    apply_mana_damage_coupling: Optional[bool] = None,
    mana_coupling_strength: Optional[float] = None,
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
    # Assumed-share seams + the RM-87 coupling pair: None means "inherit", and an
    # omitted key is what makes a flagless call byte-identical on the wire.
    for _key, _val in (
        ("assume_item_crit_dr", assume_item_crit_dr),
        ("assume_item_aa_dr", assume_item_aa_dr),
        ("assume_item_enemy_as_slow", assume_item_enemy_as_slow),
        ("apply_resist_damage_coupling", apply_resist_damage_coupling),
        # RM-91: the health-axis twin, same None-means-inherit contract.
        ("apply_health_damage_coupling", apply_health_damage_coupling),
        # RM-91 T2: the ITEM-keyed half, same contract again.
        ("apply_item_caster_hp_proc", apply_item_caster_hp_proc),
        # RM-118 mana lane: the mana-axis twin, same None-means-inherit contract.
        ("apply_mana_damage_coupling", apply_mana_damage_coupling),
    ):
        if _val is not None:
            body[_key] = bool(_val)
    if resist_coupling_strength is not None:
        body["resist_coupling_strength"] = float(resist_coupling_strength)
    if health_coupling_strength is not None:
        body["health_coupling_strength"] = float(health_coupling_strength)
    if item_caster_hp_proc_strength is not None:
        body["item_caster_hp_proc_strength"] = float(item_caster_hp_proc_strength)
    if mana_coupling_strength is not None:
        body["mana_coupling_strength"] = float(mana_coupling_strength)
    if enemies:
        body["enemies"] = [str(e) for e in enemies if e]
    if rune_ids:
        body["rune_ids"] = [str(r) for r in rune_ids if r]
    _emit_ehp_family_seams(
        body,
        apply_item_resist_grants=apply_item_resist_grants,
        apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
        apply_item_mana_health=apply_item_mana_health,
        apply_item_spell_shield=apply_item_spell_shield,
        apply_spell_shield=apply_spell_shield,
        apply_passive_resist=apply_passive_resist,
        apply_passive_mitigation=apply_passive_mitigation,
        apply_passive_revive=apply_passive_revive,
        apply_champion_tenacity=apply_champion_tenacity,
        apply_survival_window=apply_survival_window,
        apply_mode_modifiers=apply_mode_modifiers,
        apply_rune_resist_grants=apply_rune_resist_grants,
        apply_rune_health_grants=apply_rune_health_grants,
        apply_rune_hsp_amp=apply_rune_hsp_amp,
        apply_rune_flat_mitigation=apply_rune_flat_mitigation,
        assume_item_general_dr=assume_item_general_dr,
        assume_item_health_stacks=assume_item_health_stacks,
        assume_item_proc_heal=assume_item_proc_heal,
        assume_max_stacks_omnivamp=assume_max_stacks_omnivamp,
        apply_rune_self_heal=apply_rune_self_heal,
        apply_rune_shield_grants=apply_rune_shield_grants,
    )
    # Tri-state: None omits the key and inherits the engine's default-ON for
    # cc_blended; an explicit False is the only way to turn it OFF.
    if apply_build_tenacity is not None:
        body["apply_build_tenacity"] = bool(apply_build_tenacity)
    # RM-118: emit only when armed so a flagless call is byte-identical.
    if assume_hsp_amp:
        body["assume_hsp_amp"] = True
    # RM-118 residual: emit only when armed so a flagless call is byte-identical.
    if assume_passive_flat_mitigation:
        body["assume_passive_flat_mitigation"] = True
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
    # RM-115 transport: the four routes have always parsed an ``enemies``
    # roster, and no client function sent one. Four seams in the block below
    # (apply_spell_shield, apply_item_spell_shield, apply_champion_tenacity,
    # apply_build_tenacity) consume it and are INERT without it, so wiring the
    # flags alone would have made them reachable and dead.
    enemies: Optional[Iterable[str]] = None,
    # RM-115 EHP-family seam block - appended LAST per the repo convention.
    # Every one is a bool parsed by _route_ehp with an engine default of False,
    # so an omitted key leaves the request byte-identical to every pre-seam
    # call. ``rune_ids`` is the TRANSPORT the four apply_rune_* seams ride: the
    # route has always parsed it, but no client function sent it, so wiring the
    # flags without it would make them reachable and inert - the exact failure
    # mode RM-115 exists to kill.
    rune_ids: Optional[Iterable[str]] = None,
    apply_item_resist_grants: bool = False,
    apply_item_bonus_hp_amp: bool = False,
    apply_item_mana_health: bool = False,
    apply_item_spell_shield: bool = False,
    apply_spell_shield: bool = False,
    apply_passive_resist: bool = False,
    apply_passive_mitigation: bool = False,
    apply_passive_revive: bool = False,
    apply_champion_tenacity: bool = False,
    apply_survival_window: bool = False,
    apply_mode_modifiers: bool = False,
    apply_rune_resist_grants: bool = False,
    apply_rune_health_grants: bool = False,
    apply_rune_hsp_amp: bool = False,
    apply_rune_flat_mitigation: bool = False,
    assume_item_general_dr: bool = False,
    assume_item_health_stacks: bool = False,
    assume_item_proc_heal: bool = False,
    # R193 slice C: item-passive omnivamp (Riftmaker at max Void Corruption
    # stacks) into the EHP SUSTAIN axis. This is the SCALAR lane; R194 slice A
    # added the ranker lane, where ``rank_tank_for`` carries the same seam and
    # it becomes visible under ``score_by="sustain"``.
    assume_max_stacks_omnivamp: bool = False,
    # R197: the ITEM lane of the wielder Heal-and-Shield-Power axis, the twin of
    # the rune lane ``apply_rune_hsp_amp`` already in the block above. ``item_ids``
    # is its transport - the engine sums ``heal_shield_amp_pct`` over the
    # CANDIDATE'S OWN inventory (Redemption 3107 = 0.10, Mikael 3222 = 0.12), so
    # an empty build collapses it to 1.0 and the flag alone would be reachable and
    # inert. Deliberately NOT routed through ``_emit_ehp_family_seams``: that
    # helper is called by four functions, and only /ehp parses this key - folding
    # it in would let a later edit leak the seam onto /rank-tank, /rank-bruiser or
    # /hybrid, none of which parse it. Appended at END per the
    # no-mid-signature-insert convention.
    assume_hsp_amp: bool = False,
    # RM-118 residual: four EHP survivability seams whose ENGINE half shipped
    # complete while no route parsed them, so the R197 stranded-seam guard
    # ledgered them as debt. Deliberately NOT routed through
    # ``_emit_ehp_family_seams`` for the same reason as ``assume_hsp_amp`` above:
    # that helper is called by four functions and only ``/ehp`` parses three of
    # these, so folding them in would let a later edit leak a key onto
    # /rank-bruiser or /hybrid, neither of which parses any of them.
    # ``assume_passive_flat_mitigation`` is the one exception - it also reaches
    # ``/rank-tank``, where ``rank_tank_for`` carries it separately. Plain
    # DEFAULT-OFF bools, emitted only when True, appended at END per the
    # no-mid-signature-insert convention. Their transports are already here:
    # ``champion`` + ``level`` for the two champion-keyed registries, ``item_ids``
    # for the two item-keyed ones (Guardian Angel 3026 / Zhonya's 3157).
    assume_passive_flat_mitigation: bool = False,
    assume_passive_health_stacks: bool = False,
    assume_item_revive: bool = False,
    assume_item_stasis: bool = False,
    # RM-118 residual (2026-07-30): the two SELF-side rune survivability lanes.
    # These DO go through ``_emit_ehp_family_seams`` - unlike the four above,
    # every one of that helper's four callers now posts to a route that parses
    # them (``compute_ehp`` / ``rank_items_by_ehp`` / ``compute_hybrid`` /
    # ``rank_items_by_hybrid`` all name both), so there is no route to leak onto.
    # ``rune_ids`` above is the transport.
    apply_rune_self_heal: bool = False,
    apply_rune_shield_grants: bool = False,
    # RM-118 residual (2026-07-30): the two VAMP lanes. MEASURED off
    # inspect.signature - both name ``compute_ehp`` and NOTHING else, so /ehp is
    # the entire route table and these are deliberately NOT routed through
    # ``_emit_ehp_family_seams`` (that helper has four callers, three of which
    # post to routes that do not parse either key - folding them in would leak a
    # key that dies on the wire). ``item_ids`` is the transport for both: crit
    # and lifesteal come out of the resolved stat block, and the cleave lane
    # additionally needs Ravenous Hydra 3074 (or its Arena mirror 223074) in the
    # build. ``targets_in_rotation`` is the SECOND transport the cleave lane
    # needs - the enemy count its AoE lands on - and /ehp had no such float
    # before this slice, so the flag alone could only ever express the
    # single-target case. Sent only when given; the engine default is 1.0 and it
    # is read only inside the flag's ``if``, so an unarmed call is unchanged.
    # Appended at END per the no-mid-signature-insert convention.
    targets_in_rotation: Optional[float] = None,
    assume_crit_weighted_vamp: bool = False,
    assume_cleave_lifesteal: bool = False,
    # RM-118 residual (2026-08-04): the FIVE per-item shield opt-ins into the EHP
    # ItemShield pool (Kaenic Rookern 2504, Eclipse 6692, Chainlaced Crushers
    # 3173, Seraph's Embrace 3040, Fimbulwinter 3121, each plus its mode
    # mirrors). MEASURED off inspect.signature - all five name ``compute_ehp``
    # and NOTHING else, so /ehp is the entire route table and they are
    # deliberately NOT routed through ``_emit_ehp_family_seams`` (that helper has
    # four callers, three of which post to routes that parse none of these keys -
    # folding them in would leak a key that dies on the wire). ``item_ids`` is
    # the whole transport: the engine arms per item id off the equipped
    # inventory and resolves the magnitude from ``level`` plus the resolved
    # max-HP / max-mana / bonus-AD stat block. Plain DEFAULT-OFF bools, emitted
    # only when True, appended at END per the no-mid-signature-insert
    # convention. This exposes the seams; it does NOT flip any live default.
    assume_kaenic_shield: bool = False,
    assume_eclipse_shield: bool = False,
    assume_chainlaced_shield: bool = False,
    assume_seraphs_shield: bool = False,
    assume_fimbulwinter_shield: bool = False,
    # RM-200: the SCALING half of the wielder-HSP item lane ``assume_hsp_amp``
    # opens above. Only /ehp and /sustain parse it, so it is deliberately NOT
    # routed through ``_emit_ehp_family_seams`` - that helper is shared by four
    # entry points and folding this in would let a later edit leak the key onto
    # /rank-tank, /rank-bruiser or /hybrid, none of which parse it. A MODIFIER of
    # ``assume_hsp_amp``: setting this alone is accepted and arithmetically inert
    # engine-side, because the helper is reached only inside that flag's branch.
    # Transport is the existing ``item_ids`` (Dawncore 6621). Appended at END per
    # the no-mid-signature-insert convention.
    assume_scaling_hsp_grants: bool = False,
    # RM-201: the guaranteed-minimum CC band and the axis it rides.
    #
    # ``include_conditional`` is NOT incidental here. ``/ehp`` has parsed it
    # since ENGINE 1.39.0 but this module never carried it - measured, the name
    # did not appear anywhere in this file before this slice - because the
    # per-route client-reach guard filters candidate keys by
    # ``_SEAM_PREFIXES = ("apply_", "assume_", "gate_", "exclude_")`` and
    # ``include_conditional`` matches none of them, so it was never examined.
    # The floor band lives on the CONDITIONAL registry, so shipping
    # ``apply_cc_floor`` without its axis would give the client a seam it can
    # set and that can never move a number - the reachable-and-dead failure mode
    # RM-115 exists to kill. They ship together.
    #
    # ``enemies`` above is the third gate: an empty comp skips the cc block
    # entirely. Deliberately NOT routed through ``_emit_ehp_family_seams`` -
    # that helper has four callers and only ``/ehp`` parses ``apply_cc_floor``
    # (measured off inspect.signature: it names ``compute_ehp`` and nothing
    # else), so folding it in would leak a key that dies on the wire. Plain
    # DEFAULT-OFF bools emitted only when True, appended at END per the
    # no-mid-signature-insert convention.
    include_conditional: bool = False,
    apply_cc_floor: bool = False,
    # RM-334: the item-236 build-tenacity credit. ``_route_ehp`` learned this
    # key in the same slice, and the per-route client-reach guard requires the
    # client function POSTing that route to be able to express it - wiring the
    # route alone would ship a seam settable by curl and dead to every RC
    # caller, the reachable-and-dead failure RM-115 exists to kill.
    #
    # A plain DEFAULT-OFF bool, NOT the tri-state ``rank_tank_for`` /
    # ``rank_bruiser_for`` carry: those resolve None per ``score_by`` against
    # ``rank_items_by_ehp`` (Optional[bool] = None), and ``/ehp`` has no
    # scoring mode - ``compute_ehp`` takes a plain ``bool = False``.
    # Appended at END per the no-mid-signature-insert convention.
    apply_build_tenacity: bool = False,
) -> Optional[dict]:
    """Call POST /ehp and return the raw result dict. None on failure.

    Phase 1 sibling of ``dps_for``. See ``rank_tank_for`` for share semantics.

    The RM-115 seam block is DEFAULT-OFF end to end: each flag is emitted only
    when True, so omitting them all reproduces the pre-seam request byte for
    byte.

    ``apply_build_tenacity`` used to be documented here as "deliberately absent
    - ``_route_ehp`` does not parse it (it needs a resolved build, which /ehp
    does not rank over)". RM-334 measured that reason backwards and corrected
    it: build tenacity needs a RESOLVED build, and ``/ehp`` is the route that
    scores exactly one - ``ehp.py:2582`` reads
    ``total_item_tenacity(item_ids)``, and ``item_ids`` is the ``items`` list
    this function already sends. The RANKERS are the endpoints without a single
    resolved build, which is why they carry the tri-state and this does not.
    Its TRANSPORT is ``item_ids`` plus ``enemies``: a build with no tenacity
    source, or an empty enemy comp, leaves it arithmetically inert.
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
    if enemies:
        body["enemies"] = [str(e) for e in enemies if e]
    if rune_ids:
        body["rune_ids"] = [str(r) for r in rune_ids if r]
    _emit_ehp_family_seams(
        body,
        apply_item_resist_grants=apply_item_resist_grants,
        apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
        apply_item_mana_health=apply_item_mana_health,
        apply_item_spell_shield=apply_item_spell_shield,
        apply_spell_shield=apply_spell_shield,
        apply_passive_resist=apply_passive_resist,
        apply_passive_mitigation=apply_passive_mitigation,
        apply_passive_revive=apply_passive_revive,
        apply_champion_tenacity=apply_champion_tenacity,
        apply_survival_window=apply_survival_window,
        apply_mode_modifiers=apply_mode_modifiers,
        apply_rune_resist_grants=apply_rune_resist_grants,
        apply_rune_health_grants=apply_rune_health_grants,
        apply_rune_hsp_amp=apply_rune_hsp_amp,
        apply_rune_flat_mitigation=apply_rune_flat_mitigation,
        assume_item_general_dr=assume_item_general_dr,
        assume_item_health_stacks=assume_item_health_stacks,
        assume_item_proc_heal=assume_item_proc_heal,
        assume_max_stacks_omnivamp=assume_max_stacks_omnivamp,
        apply_rune_self_heal=apply_rune_self_heal,
        apply_rune_shield_grants=apply_rune_shield_grants,
    )
    # DEFAULT-OFF, emit-when-True: an omitted key leaves _route_ehp's
    # _opt_bool(body, "assume_hsp_amp", False) on its engine default, so a call
    # that does not name the seam is byte-identical on the wire to a pre-R197 one.
    if assume_hsp_amp:
        body["assume_hsp_amp"] = True
    # RM-200: same emit-when-True contract. Arming this WITHOUT assume_hsp_amp
    # is accepted and inert by construction - see the signature comment.
    if assume_scaling_hsp_grants:
        body["assume_scaling_hsp_grants"] = True
    # RM-118 residual: same emit-when-True contract - each key absent leaves
    # _route_ehp's _opt_bool on its engine default, so a call that names none of
    # them is byte-identical on the wire to a pre-wire one.
    for _seam, _armed in (
        ("assume_passive_flat_mitigation", assume_passive_flat_mitigation),
        ("assume_passive_health_stacks", assume_passive_health_stacks),
        ("assume_item_revive", assume_item_revive),
        ("assume_item_stasis", assume_item_stasis),
        ("assume_crit_weighted_vamp", assume_crit_weighted_vamp),
        ("assume_cleave_lifesteal", assume_cleave_lifesteal),
        # RM-118 residual: the five per-item shield opt-ins, same
        # emit-when-True contract - each key absent leaves _route_ehp's
        # _opt_bool on its engine default, so a call that names none of them is
        # byte-identical on the wire to a pre-wire one.
        ("assume_kaenic_shield", assume_kaenic_shield),
        ("assume_eclipse_shield", assume_eclipse_shield),
        ("assume_chainlaced_shield", assume_chainlaced_shield),
        ("assume_seraphs_shield", assume_seraphs_shield),
        ("assume_fimbulwinter_shield", assume_fimbulwinter_shield),
        # RM-201: the CC-floor band and the conditional axis it is gated on.
        # Same emit-when-True contract - both keys absent leaves _route_ehp's
        # _opt_bool on the engine default, so a call naming neither is
        # byte-identical on the wire to a pre-wire one.
        ("include_conditional", include_conditional),
        ("apply_cc_floor", apply_cc_floor),
        # RM-334: same emit-when-True contract - an absent key leaves
        # _route_ehp's _opt_bool(body, "apply_build_tenacity", False) on the
        # engine default, so a call that does not name it is byte-identical on
        # the wire to a pre-RM-334 one.
        ("apply_build_tenacity", apply_build_tenacity),
    ):
        if _armed:
            body[_seam] = True
    # The cleave lane's non-boolean transport. Emitted only when the caller
    # names it, so an omitted count leaves _route_ehp's _opt_float on the
    # engine's own 1.0 default and the request is byte-identical on the wire.
    if targets_in_rotation is not None:
        body["targets_in_rotation"] = float(targets_in_rotation)
    return _post_json("/ehp", body, timeout=timeout)


def sustain_for(
    champion: str,
    *,
    mode: str = "SR",
    item_ids: Optional[Iterable[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    # R197: the SUSTAIN half of the same wielder-HSP item lane ``ehp_for``
    # carries above. Scoped to the REGEN kind engine-side - a vamp-only champion
    # is byte-identical even with the seam ON - and INERT without ``item_ids``,
    # which is why the two are declared as a pair rather than as independent
    # switches. DEFAULT-OFF, emitted only when True.
    assume_hsp_amp: bool = False,
    # RM-200: the SCALING half of that same lane, and inert without BOTH the
    # flag above and ``item_ids`` - it modifies the sum ``assume_hsp_amp`` opens
    # rather than opening one of its own. DEFAULT-OFF, emitted only when True.
    assume_scaling_hsp_grants: bool = False,
) -> Optional[dict]:
    """Call POST /sustain and return the raw SustainResult dict. None on failure.

    Item 298 (ENGINE 1.110.0) scalar probe - the sustain / vamp-throughput axis.
    Same engine-down semantics as ``ehp_for`` / ``hps_for`` (None = unreachable),
    same ``DEFAULT_TIMEOUT`` fail-silent contract.

    WHY THIS FUNCTION EXISTS AT ALL, given it has no caller yet
    ----------------------------------------------------------
    ``_route_sustain`` began parsing ``assume_hsp_amp`` at R197 and no client
    function POSTed /sustain, so the per-route reachability guard
    (``agents/daemon_slayer/tests/test_route_seams_reach_the_client_per_route.py``)
    went RED with ('/sustain', 'assume_hsp_amp'). That guard offers two remedies
    and states its own preference plainly: wire the client function, or add the
    pair to ``_STRANDED_BY_ROUTE``. The ledger was declined here for two reasons.

    First, /sustain is not the shape of the two routes that ARE declined in that
    ledger. /v2/fight-report is declined because its compute has only test
    callers; ``compute_sustain`` has LIVE in-process consumers today
    (``dashboard/routes_ds_profile.py:204`` and ``core/ds_capability_gap.py:164``),
    so the metric already ships to the operator and this is only the
    out-of-process door to it. /beam is declined because its live consumer holds
    a deliberately bespoke HTTP call (a 4.0s budget and an error STRING that
    ``_post_json``'s None collapses); /sustain has no such contract conflict.

    Second, having no caller is not this module's bar for existing: ``ehp_for``,
    ``hybrid_for``, ``ability_dps_for`` and ``hps_for`` all carry zero non-test
    call sites and none of them are ledgered. This module is a probe surface as
    much as a consumer surface. (``matchup`` was named in this list when R197
    landed and that was wrong - it has two live callers,
    ``core/laning_verdicts.py:295`` and ``dashboard/routes_ds_matchup.py:170``.
    The four above verify; the conclusion did not depend on the fifth.)

    Be honest about what that buys: this makes the seam EXPRESSIBLE, not live.
    Nothing in RC calls this yet, and the two in-process consumers above call
    ``compute_sustain(champion, mode)`` positionally with no inventory, so they
    cannot arm the seam either. Wiring a real consumer is separate work.
    """
    body: dict = {
        "champion": champion,
        "mode": mode,
    }
    # Emitted only when non-empty: _route_sustain reads items through
    # _coerce_str_list(body.get("items")), which maps an absent key to [], so
    # omitting it is the same request as sending an empty list with fewer bytes.
    if item_ids:
        body["items"] = [str(i) for i in item_ids if i]
    # DEFAULT-OFF, emit-when-True - same contract as the ``ehp_for`` twin.
    if assume_hsp_amp:
        body["assume_hsp_amp"] = True
    if assume_scaling_hsp_grants:
        body["assume_scaling_hsp_grants"] = True
    return _post_json("/sustain", body, timeout=timeout)


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
    # RM-115 p4 seam - appended LAST per the repo convention. Parsed off the
    # POST /rank-bruiser body server-side. DEFAULT-0.0; the engine consults the
    # kit-conversion registry only when strictly positive, so omitting the key
    # keeps the request byte-identical to every pre-seam call.
    kit_conversion_strength: float = 0.0,       # RM-86 L1 (Olaf/Pantheon/RekSai/Riven)
    # RM-115 transport: _route_rank_bruiser parses score_by and rank_tank_for
    # has always sent it; this one never did, so the cc_blended metric that
    # the two tenacity seams move was unreachable on the bruiser route.
    score_by: str = "blended",
    # RM-115 transport: the four routes have always parsed an ``enemies``
    # roster, and no client function sent one. Four seams in the block below
    # (apply_spell_shield, apply_item_spell_shield, apply_champion_tenacity,
    # apply_build_tenacity) consume it and are INERT without it, so wiring the
    # flags alone would have made them reachable and dead.
    enemies: Optional[Iterable[str]] = None,
    # RM-115 EHP-family seam block - appended LAST per the repo convention.
    # /rank-bruiser parses the widest set of the four: it is the only route in
    # the family that also carries apply_ad_axis_ability_damage (RM-39/RM-43).
    # All bools, all DEFAULT-OFF, emitted only when True. ``rune_ids`` is the
    # transport the four apply_rune_* seams ride.
    rune_ids: Optional[Iterable[str]] = None,
    apply_item_resist_grants: bool = False,
    apply_item_bonus_hp_amp: bool = False,
    apply_item_mana_health: bool = False,
    apply_item_spell_shield: bool = False,
    apply_spell_shield: bool = False,
    apply_passive_resist: bool = False,
    apply_passive_mitigation: bool = False,
    apply_passive_revive: bool = False,
    apply_champion_tenacity: bool = False,
    apply_survival_window: bool = False,
    apply_mode_modifiers: bool = False,
    apply_rune_resist_grants: bool = False,
    apply_rune_health_grants: bool = False,
    apply_rune_hsp_amp: bool = False,
    apply_rune_flat_mitigation: bool = False,
    assume_item_general_dr: bool = False,
    assume_item_health_stacks: bool = False,
    assume_item_proc_heal: bool = False,
    apply_ad_axis_ability_damage: bool = False,
    # RM-36 dual-scaling SPLIT credit - MODIFIER of the flag above. Plain
    # DEFAULT-OFF bool, emitted by _emit_ehp_family_seams only when True.
    apply_ad_axis_dual_scaling_split: bool = False,
    # TRI-STATE, unlike every other seam in this block - see rank_tank_for.
    # ``_route_rank_bruiser`` (server.py:973-975) reads it as None-when-absent
    # and the engine defaults it ON for cc_blended, so None = inherit and
    # False = explicitly disable. A plain bool could not express the OFF.
    apply_build_tenacity: Optional[bool] = None,
    # RM-118 (2026-07-29): the wielder HSP ITEM-amp seam (R60). Sibling of the
    # rank_tank_for wire (1a2f92e7). Appended LAST; a plain EHP-family bool,
    # emitted via _emit_ehp_family_seams only when True -> byte-identical off.
    assume_hsp_amp: bool = False,
    # RM-118 residual (2026-07-30): all three stranded rune lanes on the BRUISER
    # ranker. ``rank_items_by_hybrid`` names every one (hybrid.py:1037-1042), so
    # each can change an item CHOICE here. ``rune_ids`` above is the transport.
    apply_rune_self_heal: bool = False,
    apply_rune_shield_grants: bool = False,
    apply_rune_offense_grants: bool = False,
    # RM-118 residual (2026-08-04): the same two stranded hybrid-axis seams on
    # the BRUISER ranker. ``rank_items_by_hybrid`` names both and forwards them
    # per candidate, so each can change an item CHOICE - measured for Ahri at
    # level 13 over the full 140-row pool, the order moves for each seam alone.
    apply_cast_rate_propensity_prior: bool = False,
    assume_ms_utility: bool = False,
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
    # RM-86 L1: the engine consults the kit-conversion registry only when the
    # lever is strictly positive (the hybrid.py sort gate), so 0.0 and any
    # negative are inert server-side - emit nothing and stay byte-identical.
    if kit_conversion_strength > 0.0:
        body["kit_conversion_strength"] = float(kit_conversion_strength)
    if enemies:
        body["enemies"] = [str(e) for e in enemies if e]
    if rune_ids:
        body["rune_ids"] = [str(r) for r in rune_ids if r]
    _emit_ehp_family_seams(
        body,
        apply_item_resist_grants=apply_item_resist_grants,
        apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
        apply_item_mana_health=apply_item_mana_health,
        apply_item_spell_shield=apply_item_spell_shield,
        apply_spell_shield=apply_spell_shield,
        apply_passive_resist=apply_passive_resist,
        apply_passive_mitigation=apply_passive_mitigation,
        apply_passive_revive=apply_passive_revive,
        apply_champion_tenacity=apply_champion_tenacity,
        apply_survival_window=apply_survival_window,
        apply_mode_modifiers=apply_mode_modifiers,
        apply_rune_resist_grants=apply_rune_resist_grants,
        apply_rune_health_grants=apply_rune_health_grants,
        apply_rune_hsp_amp=apply_rune_hsp_amp,
        apply_rune_flat_mitigation=apply_rune_flat_mitigation,
        assume_item_general_dr=assume_item_general_dr,
        assume_item_health_stacks=assume_item_health_stacks,
        assume_item_proc_heal=assume_item_proc_heal,
        apply_ad_axis_ability_damage=apply_ad_axis_ability_damage,
        apply_ad_axis_dual_scaling_split=apply_ad_axis_dual_scaling_split,
        assume_hsp_amp=assume_hsp_amp,
        apply_rune_self_heal=apply_rune_self_heal,
        apply_rune_shield_grants=apply_rune_shield_grants,
        apply_rune_offense_grants=apply_rune_offense_grants,
        apply_cast_rate_propensity_prior=apply_cast_rate_propensity_prior,
        assume_ms_utility=assume_ms_utility,
    )
    # Tri-state, same contract as rank_tank_for: None omits the key and
    # inherits the engine's default-ON for cc_blended.
    if apply_build_tenacity is not None:
        body["apply_build_tenacity"] = bool(apply_build_tenacity)
    if score_by != "blended":
        body["score_by"] = score_by
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
    # A-07 / RM-82 TERM 2 seam - appended LAST per the repo convention. Parsed
    # off the POST /rank-mage body server-side (server.py:1265).
    apply_passive_aura_damage: bool = False,  # A-07 / RM-82 (Morde Darkness Rise)
    # RM-115 A-03 / RM-81 ability-base seam. DEFAULT-OFF; omitted key ==
    # byte-identical. Load-time on the engine (abilities.py:1006), resolved
    # server-side into an abilities snapshot.
    apply_ability_base_overrides: bool = False,
    # RM-115 tail (1.254.0). The Hwei staged-block lane is keyed
    # ("Hwei","Q",2), so it needs form_index={"Q": 2} to fire; Illaoi is
    # registry-present but documented LIVE-INERT at this snapshot, so it is
    # the wrong control. DEFAULT-OFF.
    apply_ability_amps: bool = False,
    # RM-172 (2026-08-06): the ARENA/Swiftplay stat-growth ADDEND lane, wired
    # UNIFORMLY across the DS route seam rather than left half-reachable.
    # DEFAULT-OFF and emitted only when ON, so an omitted key leaves the request
    # byte-identical. No extra transport is needed - the addend table is keyed by
    # (champion, mode) and both are already on the wire.
    apply_mode_modifiers: bool = False,
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

    ``apply_passive_aura_damage`` (A-07 / RM-82 TERM 2, DEFAULT-OFF) credits
    per-second passive aura damage into the ability DPS total. It is a bool
    seam whose omit-value is False, so leaving it alone keeps the request body
    byte-identical to every pre-seam call. The registry backing it
    (``_passive_damage_overrides.per_second_aura_entry``) resolves a
    ``per_second`` aura for Mordekaiser only today; every other champion
    returns None and is unmoved with the flag ON.

    NOT to be confused with ``apply_passive_damage`` - that is the separate
    AA-cadence passive flag on /rank and /rank-onhit. This one is MAGE-ONLY:
    /rank-mage is the sole route that parses it (server.py:1265).
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
    # A-07 / RM-82 TERM 2: bool seam, engine default False - emit only when ON.
    if apply_passive_aura_damage:
        body["apply_passive_aura_damage"] = True
    # RM-115: bool seam, engine default False - emit only when ON.
    if apply_ability_base_overrides:
        body["apply_ability_base_overrides"] = True
    if apply_ability_amps:
        body["apply_ability_amps"] = True
    # RM-172: bool seam, engine default False - emit only when ON.
    if apply_mode_modifiers:
        body["apply_mode_modifiers"] = True
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
    # RM-115 seams - appended LAST per the repo convention. Both are parsed off
    # the POST /ability-dps body server-side and are DEFAULT-OFF, so an omitted
    # key leaves the request byte-identical to every pre-seam call.
    apply_passive_aura_damage: bool = False,   # A-07 / RM-82 TERM 2
    apply_ability_base_overrides: bool = False,  # A-03 / RM-81
    apply_ability_amps: bool = False,          # RM-115 tail (1.254.0)
    apply_mode_modifiers: bool = False,        # RM-172 ARENA addend lane
) -> Optional[dict]:
    """Call POST /ability-dps and return the raw result dict. None on failure.

    Phase 4c sibling of ``dps_for`` / ``ehp_for`` / ``hybrid_for``. See
    ``rank_mage_for`` for ``max_priority`` / ``block_strategy`` /
    ``form_index`` semantics, and for what the three RM-115 seams do.

    ``apply_ability_amps`` needs no extra transport - its three lanes read
    ``champion`` / ``level`` / ``max_priority`` / ``form_index``, all already
    on the wire. The staged-block lane is keyed ``("Hwei","Q",2)``, so that
    one requires ``form_index={"Q": 2}`` to fire.
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
    # RM-115: bool seams, engine default False - emit only when ON.
    if apply_passive_aura_damage:
        body["apply_passive_aura_damage"] = True
    if apply_ability_base_overrides:
        body["apply_ability_base_overrides"] = True
    if apply_ability_amps:
        body["apply_ability_amps"] = True
    # RM-172: bool seam, engine default False - emit only when ON.
    if apply_mode_modifiers:
        body["apply_mode_modifiers"] = True
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
    # RM-115 gate-3 seam - appended LAST per the repo convention. Parsed off
    # the POST /rank-assassin body server-side.
    kit_conversion_strength: float = 0.0,  # RM-86 L1 lever (RM-83 Naafiri)
    # RM-115 A-03 / RM-81 ability-base seam. DEFAULT-OFF; omitted key ==
    # byte-identical. Naafiri is the one of the six that routes here.
    apply_ability_base_overrides: bool = False,
    # RM-115 tail (1.254.0) - the four seams /rank-assassin parses that this
    # function could not express, plus target_preset. All DEFAULT-OFF.
    #
    # ``assume_magic_burst`` above is DELIBERATELY NOT one of them and must not
    # be "fixed" by adding a route parse: /rank-assassin correctly refuses it
    # (rank_items_by_burst has no such parameter, only compute_burst_damage
    # does, burst.py:522). It stays here because it is load-bearing across
    # coach_integration/archetype_dispatch.py and dashboard/routes_state.py.
    # The lever is now legitimately reachable on the route that DOES parse it:
    # ``burst_for(assume_magic_burst=...)``, wired in the same pass.
    #
    # ``target_preset`` is the DSP8 SUPERSET of assume_squishy_target - it is
    # the only path that also substitutes target MR. Shipping the binary alias
    # without the superset would be exactly the half-wire RM-115 exists to
    # prevent, so both go on the wire together. Values: squishy / bruiser /
    # tank / high_cc.
    exclude_off_axis_items: bool = False,
    assume_takedown: bool = False,
    assume_squishy_target: bool = False,
    assume_ability_amp: bool = False,
    target_preset: Optional[str] = None,
    apply_mode_modifiers: bool = False,  # RM-172 ARENA addend lane
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
    # RM-86 L1: the engine consults the kit-conversion registry only when the
    # lever is strictly positive (burst.py:2160-2162), so 0.0 and any negative
    # are inert server-side - emit nothing and stay byte-identical.
    if kit_conversion_strength > 0.0:
        body["kit_conversion_strength"] = float(kit_conversion_strength)
    # RM-115: bool seam, engine default False - emit only when ON.
    if apply_ability_base_overrides:
        body["apply_ability_base_overrides"] = True
    # RM-115 tail: bool seams, engine default False - emit only when ON.
    #
    # TWO TRANSPORT TRAPS, both measured and both silent:
    #   * assume_squishy_target is disabled by any POSITIVE target_armor - the
    #     substitution is guarded on target_armor <= 0.0 (burst.py:2018). At
    #     the client default 0.0 it works; a coach that supplies a measured
    #     enemy armor turns it off without any error.
    #   * the Collector arm of assume_takedown is disabled by target_max_hp
    #     == 0.0 (burst.py:1075), which IS this function's own default. Hubris
    #     and Hollow Radiance still move; The Collector never gets credited.
    if exclude_off_axis_items:
        body["exclude_off_axis_items"] = True
    if assume_takedown:
        body["assume_takedown"] = True
    if assume_squishy_target:
        body["assume_squishy_target"] = True
    if assume_ability_amp:
        body["assume_ability_amp"] = True
    if target_preset:
        body["target_preset"] = str(target_preset)
    # RM-172: bool seam, engine default False - emit only when ON.
    if apply_mode_modifiers:
        body["apply_mode_modifiers"] = True
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
    # RM-115 A-03 / RM-81 ability-base seam - appended LAST per the repo
    # convention. DEFAULT-OFF; omitted key == byte-identical.
    apply_ability_base_overrides: bool = False,
    # RM-115 tail (1.254.0). TWO STRANDED TRANSPORTS FIRST, then the 7 seams.
    # ``runes`` and ``caster_current_hp_pct`` are NOT seam-prefixed, so neither
    # RM-115 guard can see them - and without them BOTH gate_* seams below are
    # reachable-and-dead, which is the exact illusion RM-115 exists to kill.
    # Measured at 1.253.0: with ``runes`` omitted, gate_target_hp_amp=True and
    # gate_caster_hp_amp=True are byte-identical to baseline.
    # NOTE the key is ``runes``, NOT the EHP family's ``rune_ids`` - /burst
    # parses a different key, so the 1.253.0 rune_ids wiring does not help here.
    runes: Optional[Iterable] = None,
    caster_current_hp_pct: float = 1.0,
    score_completion_runes: bool = False,
    assume_ability_amp: bool = False,
    assume_magic_burst: bool = False,
    assume_physical_burst: bool = False,
    assume_shielded_target: bool = False,
    assume_takedown: bool = False,
    gate_caster_hp_amp: bool = False,
    gate_target_hp_amp: bool = False,
    apply_mode_modifiers: bool = False,  # RM-172 ARENA addend lane
) -> Optional[dict]:
    """Call POST /burst and return the raw result dict. None on failure.

    Phase 5 sibling of ``ability_dps_for`` / ``dps_for`` / ``ehp_for`` /
    ``hybrid_for``. See ``rank_assassin_for`` for ``combo_sequence``
    semantics.

    /burst is a single-build scalar compute with no candidate loop, so every
    RM-115 acceptance on this route is a SCALAR; a rank criterion is
    unsatisfiable by construction. All seams are DEFAULT-OFF.

    Transport traps, all measured:

      * ``gate_target_hp_amp`` / ``gate_caster_hp_amp`` need ``runes`` to
        carry the gated rune (Cut Down 8017 / Coup de Grace 8014 for the
        target gate, Last Stand 8299 for the caster gate). Omit ``runes`` and
        the flags are inert.
      * ``gate_caster_hp_amp`` additionally needs ``caster_current_hp_pct``
        below 1.0 - Last Stand ramps 1.05 -> 1.11 over caster HP 0.60 -> 0.30.
      * The gates are HONESTY gates, not enablers: OFF applies the amp
        unconditionally, so turning ``gate_target_hp_amp`` ON at a full-HP
        target correctly REMOVES Coup de Grace's amp (a negative delta).
      * ``assume_shielded_target`` and the Collector arm of
        ``assume_takedown`` both need ``target_max_hp`` > 0.
      * ``score_completion_runes`` is not seam-prefixed either, and is the
        only way Shield Bash 8401 reaches the score once ``runes`` is wired.
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
    # RM-115: bool seam, engine default False - emit only when ON.
    if apply_ability_base_overrides:
        body["apply_ability_base_overrides"] = True
    # RM-115 tail: the two stranded transports, emitted only when non-default
    # so an untouched call stays byte-identical.
    if runes:
        body["runes"] = [str(r) for r in runes if str(r).strip()]
    if caster_current_hp_pct != 1.0:
        body["caster_current_hp_pct"] = float(caster_current_hp_pct)
    if score_completion_runes:
        body["score_completion_runes"] = True
    if assume_ability_amp:
        body["assume_ability_amp"] = True
    if assume_magic_burst:
        body["assume_magic_burst"] = True
    if assume_physical_burst:
        body["assume_physical_burst"] = True
    if assume_shielded_target:
        body["assume_shielded_target"] = True
    if assume_takedown:
        body["assume_takedown"] = True
    if gate_caster_hp_amp:
        body["gate_caster_hp_amp"] = True
    if gate_target_hp_amp:
        body["gate_target_hp_amp"] = True
    # RM-172: bool seam, engine default False - emit only when ON.
    if apply_mode_modifiers:
        body["apply_mode_modifiers"] = True
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
    # RM-115 transport: the four routes have always parsed an ``enemies``
    # roster, and no client function sent one. Four seams in the block below
    # (apply_spell_shield, apply_item_spell_shield, apply_champion_tenacity,
    # apply_build_tenacity) consume it and are INERT without it, so wiring the
    # flags alone would have made them reachable and dead.
    enemies: Optional[Iterable[str]] = None,
    # RM-115 EHP-family seam block - appended LAST per the repo convention.
    # All bools, all DEFAULT-OFF, emitted only when True. ``rune_ids`` is the
    # transport the four apply_rune_* seams ride. ``apply_ad_axis_ability_damage``
    # is deliberately absent: _route_hybrid does not parse it (it is
    # /rank-bruiser only).
    rune_ids: Optional[Iterable[str]] = None,
    apply_item_resist_grants: bool = False,
    apply_item_bonus_hp_amp: bool = False,
    apply_item_mana_health: bool = False,
    apply_item_spell_shield: bool = False,
    apply_spell_shield: bool = False,
    apply_passive_resist: bool = False,
    apply_passive_mitigation: bool = False,
    apply_passive_revive: bool = False,
    apply_champion_tenacity: bool = False,
    apply_build_tenacity: bool = False,
    apply_survival_window: bool = False,
    apply_mode_modifiers: bool = False,
    apply_rune_resist_grants: bool = False,
    apply_rune_health_grants: bool = False,
    apply_rune_hsp_amp: bool = False,
    apply_rune_flat_mitigation: bool = False,
    assume_item_general_dr: bool = False,
    assume_item_health_stacks: bool = False,
    assume_item_proc_heal: bool = False,
    # RM-118 residual (2026-07-30): the three stranded rune lanes. ``compute_hybrid``
    # is the only engine entry point that names all three, so /hybrid is the one
    # route where a single call can arm both axes at once. They ride the
    # ``rune_ids`` transport already declared above.
    apply_rune_self_heal: bool = False,
    apply_rune_shield_grants: bool = False,
    apply_rune_offense_grants: bool = False,
    # RM-118 residual (2026-08-04): the last two stranded hybrid-axis seams.
    # NEITHER needs extra transport - the propensity prior rides the in-engine
    # per-spell rows and the MS multiplier reads the resolved stat block against
    # the champion's base movespeed. ``compute_dps`` names neither, so
    # ``dps_for`` does NOT get them.
    apply_cast_rate_propensity_prior: bool = False,
    assume_ms_utility: bool = False,
) -> Optional[dict]:
    """Call POST /hybrid and return the raw result dict. None on failure.

    Phase 2 sibling of ``dps_for`` and ``ehp_for``. See ``rank_bruiser_for``
    for alpha/beta semantics.

    RM-118 residual rune seams, all DEFAULT-OFF and all needing ``rune_ids``:
    ``apply_rune_offense_grants`` moves the DPS axis, ``apply_rune_self_heal``
    (Second Wind 8444) and ``apply_rune_shield_grants`` (Guardian 8465, SELF
    shield only) move the EHP axis, and either half moves ``hybrid_score``.

    RM-118 residual hybrid-axis seams, both DEFAULT-OFF and neither needing a
    transport:

      * ``apply_cast_rate_propensity_prior`` - the RM-98 propensity PRIOR half
        (RM-98 shipped the cast-rate TIME BASE). It rides both ability branches,
        so it moves the score with or without
        ``apply_ad_axis_ability_damage``.
      * ``assume_ms_utility`` - credit bonus movement speed as a utility
        multiplier on the blended score. Identity on a build with no bonus MS.
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
    if enemies:
        body["enemies"] = [str(e) for e in enemies if e]
    if rune_ids:
        body["rune_ids"] = [str(r) for r in rune_ids if r]
    _emit_ehp_family_seams(
        body,
        apply_item_resist_grants=apply_item_resist_grants,
        apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
        apply_item_mana_health=apply_item_mana_health,
        apply_item_spell_shield=apply_item_spell_shield,
        apply_spell_shield=apply_spell_shield,
        apply_passive_resist=apply_passive_resist,
        apply_passive_mitigation=apply_passive_mitigation,
        apply_passive_revive=apply_passive_revive,
        apply_champion_tenacity=apply_champion_tenacity,
        apply_build_tenacity=apply_build_tenacity,
        apply_survival_window=apply_survival_window,
        apply_mode_modifiers=apply_mode_modifiers,
        apply_rune_resist_grants=apply_rune_resist_grants,
        apply_rune_health_grants=apply_rune_health_grants,
        apply_rune_hsp_amp=apply_rune_hsp_amp,
        apply_rune_flat_mitigation=apply_rune_flat_mitigation,
        assume_item_general_dr=assume_item_general_dr,
        assume_item_health_stacks=assume_item_health_stacks,
        assume_item_proc_heal=assume_item_proc_heal,
        apply_rune_self_heal=apply_rune_self_heal,
        apply_rune_shield_grants=apply_rune_shield_grants,
        apply_rune_offense_grants=apply_rune_offense_grants,
        apply_cast_rate_propensity_prior=apply_cast_rate_propensity_prior,
        assume_ms_utility=assume_ms_utility,
    )
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
    apply_mode_modifiers: bool = False,         # RM-172 ARENA addend lane
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
    # RM-172: bool seam, engine default False - emit only when ON.
    if apply_mode_modifiers:
        body["apply_mode_modifiers"] = True
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
    # RM-118 residual (2026-08-04): the ABILITY lane of the wielder HSP amp.
    # NO extra transport - ``amp_factor`` comes from ``item_ids``, already on
    # the wire below. /hps is the sole owner; ``rank_enchanter_for`` does NOT
    # get it, because ``rank_items_by_hps`` cannot read it.
    apply_ability_hsp_amp: bool = False,
    # RM-172: unlike apply_ability_hsp_amp above, this one IS shared with
    # rank_enchanter_for - rank_items_by_hps names it.
    apply_mode_modifiers: bool = False,
) -> Optional[dict]:
    """Call POST /hps and return the raw result dict. None on failure.

    Phase 6 sibling of ``dps_for`` / ``ehp_for`` / ``hybrid_for`` /
    ``ability_dps_for`` / ``burst_for``. See ``rank_enchanter_for`` for
    ``targets_per_proc_override`` semantics.

    RM-118 residual seam, DEFAULT-OFF:

      * ``apply_ability_hsp_amp`` - amp the CHAMPION-ABILITY heal/shield fold
        by the wielder's own item Heal/Shield-Power factor, the lane the item
        half has had since R60. Identity when the build carries no HSP item or
        the champion has no ability heal block; measured mover at level 13 with
        Ardent 3504 + Redemption 3107 + Mikael's 3222 on every enchanter probed
        (Soraka / Sona / Nami / Janna / Yuumi / Seraphine).
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
    if apply_ability_hsp_amp:
        body["apply_ability_hsp_amp"] = True
    # RM-172: bool seam, engine default False - emit only when ON.
    if apply_mode_modifiers:
        body["apply_mode_modifiers"] = True
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
    apply_mode_modifiers: bool = False,  # RM-172 ARENA addend lane
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
    # RM-172: bool seam, engine default False - emit only when ON.
    if apply_mode_modifiers:
        body["apply_mode_modifiers"] = True
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
    # W2 conversion seams - appended LAST per the repo convention.
    # ``apply_crit_conversion`` is CARRY-ONLY (POST /rank is the only route
    # that parses it). ``kit_conversion_strength`` is carry + assassin +
    # bruiser as of RM-115: /rank, /rank-assassin and /rank-bruiser all parse
    # it, so it is forwarded to the ds.dps, ds.burst and ds.hybrid chokepoints
    # and never reaches the tank / mage / enchanter / on-hit branches.
    kit_conversion_strength: float = 0.0,        # carry + assassin + bruiser (RM-86 L1)
    apply_crit_conversion: bool = False,         # carry (A-12 / RM-46)
    apply_ad_axis_ability_damage: bool = False,  # carry (RM-36 / RM-38)
    # carry (RM-36) - dual-scaling SPLIT credit, MODIFIER of the flag above.
    apply_ad_axis_dual_scaling_split: bool = False,
    apply_passive_damage: bool = False,          # carry (RM-42)
    apply_extra_shot_procs: bool = False,        # carry (RM-42 follow-on)
    # RM-115 gate-3 seam, MAGE-ONLY: /rank-mage is the sole route that parses
    # apply_passive_aura_damage (server.py:1265), so it is forwarded to the
    # ds.ability branch alone. Forwarding it elsewhere would be inert.
    apply_passive_aura_damage: bool = False,     # mage (A-07 / RM-82 TERM 2)
    # RM-115 A-03 / RM-81: mage + assassin. All six corrected champions route
    # to one of those two archetypes, so it is forwarded to both branches and
    # nowhere else. /rank, /rank-tank and /rank-bruiser do not parse it.
    apply_ability_base_overrides: bool = False,  # mage + assassin (A-03 / RM-81)
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

    ``kit_conversion_strength`` (RM-86 L1, DEFAULT-0.0) and
    ``apply_crit_conversion`` (A-12 / RM-46, DEFAULT-OFF) are CARRY-ONLY for the
    same reason - POST /rank is the only route that parses them. Before this
    plumb the dispatcher could not express either, so both registries
    (``kit_conversion.py`` / ``_crit_conversion_overrides.py``) were inert on
    every shipped path. See ``rank_for`` for the per-key emit gates.
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
            kit_conversion_strength=kit_conversion_strength,
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
            apply_passive_aura_damage=apply_passive_aura_damage,
            apply_ability_base_overrides=apply_ability_base_overrides,
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
            kit_conversion_strength=kit_conversion_strength,
            apply_ability_base_overrides=apply_ability_base_overrides,
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
        # W2: the two champion-selective conversion seams. rank_for emits each
        # body key only when it is non-default, so a flagless dispatch keeps the
        # exact pre-plumb payload.
        kit_conversion_strength=kit_conversion_strength,
        apply_crit_conversion=apply_crit_conversion,
        apply_ad_axis_ability_damage=apply_ad_axis_ability_damage,
        apply_ad_axis_dual_scaling_split=apply_ad_axis_dual_scaling_split,
        apply_passive_damage=apply_passive_damage,
        apply_extra_shot_procs=apply_extra_shot_procs,
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
    # RM-115 tail (1.254.0) - the six seams /dps parses that no client function
    # could express. Appended LAST per the repo convention, all DEFAULT-OFF in
    # the engine (dps.py), so an omitted key is byte-identical to a pre-seam
    # call. /dps is a single-build scalar compute with no candidate loop, so
    # every acceptance here is a SCALAR - a rank criterion is unsatisfiable.
    # NO extra transport is required: champion / level / items / mode / the
    # four target_* / augments are all already on the wire below, and that is
    # the complete transport set all six consumers need.
    apply_ability_amps: bool = False,
    apply_melee_aa_gate: bool = False,
    apply_mode_modifiers: bool = False,
    apply_passive_damage: bool = False,
    apply_extra_shot_procs: bool = False,
    apply_target_vuln: bool = False,
    assume_passive_as_stacks: bool = False,
    # RM-118 residual (2026-07-30): the RUNE OFFENSE lane, plus the ``rune_ids``
    # TRANSPORT it rides. Unlike the six RM-115 seams above this one DOES need
    # extra transport - the registry is keyed by Riot perk id - so the flag is
    # useless without the roster and both are wired together. Emitted only when
    # armed, so a pre-seam call is byte-identical.
    rune_ids: Optional[Iterable[str]] = None,
    apply_rune_offense_grants: bool = False,
    # RM-118 residual (2026-08-04): the R212 crit-chance / crit-damage override
    # lane. NO extra transport - the registry is keyed by champion id, already
    # on the wire below. /dps is the sole owner; ``rank_for`` does not get it.
    apply_crit_chance_overrides: bool = False,
) -> Optional[dict]:
    """Call POST /dps and return the raw result dict. None on failure.

    See ``rank_for`` for ``target_max_hp`` / ``target_bonus_hp`` semantics.

    RM-115 seams, all DEFAULT-OFF:

      * ``apply_mode_modifiers`` - ``mode`` is the transport. SR is inert (the
        wiki sidecar has no ``sr`` key) and ARAM is inert by construction
        (dps.py applies the ARAM axes unconditionally; the flag gates the
        ``elif`` sidecar lane only). URF is the mover.
      * ``apply_ability_amps`` - Fiora E is the only non-placeholder
        ``base="aa"`` entry in ``_ability_amp_overrides``; do not reach for
        Caitlyn/Jayce/Sivir/Nidalee, whose entries are 0.0 placeholders.
      * ``apply_melee_aa_gate`` - drops ``ranged_only`` procs on a melee
        caster, so the delta is NEGATIVE (Runaan's 3085 on Fiora).
      * ``apply_passive_damage`` / ``assume_passive_as_stacks`` /
        ``apply_target_vuln`` - champion-keyed registry lanes.

    RM-118 residual seam, also DEFAULT-OFF:

      * ``apply_rune_offense_grants`` - credit a rune-granted (bonus AD, AP,
        attack-speed fraction) triple into the stat block. ``rune_ids`` is the
        transport; measured movers at level 13 are Conqueror 8010, Absolute
        Focus 8233 and Gathering Storm 8236. Legend: Alacrity 9104 and Jack Of
        All Trades 8316 are conditional (an attack-speed-locked champion and a
        distinct-item-stat census threshold respectively), so a build that does
        not meet the condition correctly reads as no change.
      * ``apply_crit_chance_overrides`` - apply the per-champion crit-chance
        multiplier and the overflow conversion. Only 4 of 173 champions carry a
        registry row, so this is identity for everyone else even when ON.
        Measured movers at level 13 on an IE build: Yasuo and Yone (chance
        doubling plus overflow AD, DPS up) and Jhin (the 0.86 crit-damage
        penalty, DPS DOWN). Senna is registered but her lane is overflow LIFE
        STEAL, which a weighted-DPS read does not surface.
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
    # RM-115: bool seams, engine default False - emit only when ON.
    if apply_ability_amps:
        body["apply_ability_amps"] = True
    if apply_melee_aa_gate:
        body["apply_melee_aa_gate"] = True
    if apply_mode_modifiers:
        body["apply_mode_modifiers"] = True
    if apply_passive_damage:
        body["apply_passive_damage"] = True
    if apply_extra_shot_procs:
        body["apply_extra_shot_procs"] = True
    if apply_target_vuln:
        body["apply_target_vuln"] = True
    if assume_passive_as_stacks:
        body["assume_passive_as_stacks"] = True
    if rune_ids:
        body["rune_ids"] = [str(r) for r in rune_ids if r]
    if apply_rune_offense_grants:
        body["apply_rune_offense_grants"] = True
    if apply_crit_chance_overrides:
        body["apply_crit_chance_overrides"] = True
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
    apply_mode_modifiers: bool = False,  # RM-172 ARENA addend lane
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
    # RM-172: bool seam, engine default False - emit only when ON.
    if apply_mode_modifiers:
        body["apply_mode_modifiers"] = True
    return _post_json("/v2/matchup", body, timeout=timeout)

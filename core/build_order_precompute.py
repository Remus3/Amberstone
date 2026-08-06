# arch: Lane B build-order precompute (comp-archetype table) | section=core | frozen=no
"""Lane B build-order precompute (HZ-B1) - PRIMARY north star: drive live
Haiku usage to ZERO.

PURPOSE
    Precompute, offline + deterministically, the optimal ordered item build for
    a grid of ``(my_champ x mode x enemy-comp-archetype)`` so a FUTURE coach can
    read a dict at request time INSTEAD of round-tripping the "what do I build
    into this enemy comp" question through Claude Haiku (or a live :8860 call).
    The order is the SHIPPED, deterministic Daemon Slayer build planner's
    (``core.build_order.plan_build_order``) - this module is the bias-map + sweep
    + persist + read layer around it, NO new build / combat math.

THE AXIS - enemy COMP ARCHETYPE (distinct from the damage-profile table)
    The existing ``data/daemon_slayer/<patch>/build_orders_<mode>.json`` (item
    265/266, ``tools/daemon_slayer_build_orders_generate.py``) keys on a
    DAMAGE-PROFILE axis: ``ad_heavy`` / ``balanced`` / ``ap_heavy`` is purely the
    enemy AD/AP *share* (the armor-vs-MR lean) over a CONSTANT typical-enemy stat
    block (armor 80 / mr 60 / hp 2000). That answers "armor or MR first".

    HZ-B1's axis is different + complementary: the enemy COMP ARCHETYPE - the
    SHAPE of the enemy team (a wall of frontline vs a pile of squishy burst vs a
    poke comp), which changes the build ORDER + item CHOICES, not just the AD/AP
    lean:

      * ``frontline_heavy`` - tanks / bruisers, lots of HP + resists. The engine
        values %max-HP damage, armor / magic penetration, and antiheal-adjacent
        bruiser-shred items because raw flat damage bounces off the HP wall.
      * ``burst_heavy``     - assassins / squishy carries, low HP, you die fast.
        The engine values early raw power + stats (and the higher AD/AP-agnostic
        share) because a squishy enemy folds to a completed component spike and
        there is no HP wall to shred.
      * ``poke``            - ranged mages / marksmen, sustained mid-range DPS,
        moderate HP, leans AP. The engine values resists + sustain-relevant power
        at moderate enemy durability.
      * ``mixed``           - a balanced 2-2-1 comp; the neutral baseline (the
        typical-enemy stat block, even AD/AP share).

    Each class is a fixed itemization BIAS = a parameterization of the levers the
    shipped ``plan_build_order`` already exposes - ``target_armor`` /
    ``target_mr`` / ``target_max_hp`` / ``target_bonus_hp`` (the enemy stat
    context that drives %max-HP + penetration item value), ``enemy_ad_share`` /
    ``enemy_ap_share`` (the AD/AP lean, threaded via ``rank_kwargs``), and
    ``target_current_hp_pct`` (execute / low-HP-target value). We change ONLY
    these inputs per class and let the engine rerank + reorder; the resulting
    order is correct-by-construction (the engine's own math under a different
    enemy model), NOT a prediction.

WHAT v1 IS (honest scope)
    BUILD + PERSIST + READ only. The live coach flip is EXCLUDED (charter 4b
    "do not flip blind" - the table is read by a FUTURE consumer, HZ-C1, after
    real-game validation + operator OK; Haiku / the live :8860 path stays the
    interim floor). The committed table seeds a documented archetype-diverse
    champion sample (``SEED_CHAMPIONS`` - a SAMPLE, not a tier list).
    ``--champions all`` expands the sweep to the full canonical roster (every
    champion in the active patch's DS registry) offline; ``--mode all`` selects
    all three modes (sr / aram / arena) and is INDEPENDENT of the champion axis
    (it does NOT expand the roster). Full-roster offline gen is deferred-for-cost,
    not a code change.

SHAPE (per mode, atomic write to data/daemon_slayer/build_orders/<patch>/)::

    {
      "version": "<patch>", "generated_at": "<iso>", "mode": "<sr|aram|arena>",
      "schema": "build_order_precompute/v1", "engine_version": "<ds engine>",
      "dimensions": {"comp_archetypes": ["frontline_heavy", ...], "level": 11},
      "build_orders": {
        "<champ display name>": {
          "<comp_archetype>": {
            "comp_archetype": "<class>",
            "order": ["<item_id>", ...],      # ordered, incl. boots
            "bias": {"target_armor": ..., "enemy_ad_share": ..., ...}
          }
        }
      }
    }

NOTE - NEW build_orders/ SUBDIRECTORY. This writes to
``data/daemon_slayer/build_orders/<patch>/build_orders_<mode>.json``; it does
NOT touch the FLAT ``data/daemon_slayer/<patch>/build_orders_<mode>.json`` (the
item-265/266 damage-profile table). The two tables coexist on different axes.

FAIL-SOFT (read side)
    A missing / unreadable / malformed table yields ``{}`` and every ``lookup``
    yields ``{}``. The future coach surface degrades to "no precomputed build"
    (it falls back to the existing path), never an exception. Mirrors
    ``core.laning_scenario_precompute`` / ``core.pickban_targets``.
"""
from __future__ import annotations

import logging
logger = logging.getLogger("rc.build_order_precompute")
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

# Allow running as a direct script path (python core/build_order_precompute.py)
# in addition to `python -m core.build_order_precompute` - put the project root
# on sys.path before the package imports below. No-op when already importable.
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

# The build planner is the shipped, tested engine orchestration layer. Importing
# it pulls engine code (not data); plan_build_order resolves its own DS
# dispatcher lazily, and accepts an injectable rank_fn for headless tests. We do
# NOT reimplement ordering, boots injection, or the no-double-unique rule here.
from core.build_order import (
    DEFAULT_SLOTS,
    SCORE_BY_DEFAULT,
    SCORE_BY_VALUES,
    plan_build_order,
)
from core import archetype_picks
from agents.daemon_slayer.mode_variants import canonical_champions

# Project root: core/ -> C:\Riot Commander\
_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _ROOT / "data"
_DS_DIR = _DATA_DIR / "daemon_slayer"
_CURRENT_TXT = _DS_DIR / "current.txt"

# NEW subdir (see module docstring) - keeps the comp-archetype table separate
# from the item-265/266 flat damage-profile table.
_OUT_SUBDIR = "build_orders"

# Patch fallback when current.txt is missing (guards a fresh checkout only).
_FALLBACK_PATCH = "16.11.1"

SCHEMA_VERSION = "build_order_precompute/v1"

# Representative build level for the precompute. 11 = 2-item mid, the same
# point the item-265/266 table is pinned at (a stable mid-game reference for the
# enemy stat block); the order is robust across the lane phases the coach reads.
DEFAULT_LEVEL = 11

# Full build = 6 item slots (incl. boots) in every mode RC coaches. Reused from
# core.build_order.DEFAULT_SLOTS so a slot-count change there propagates here.
SLOTS = DEFAULT_SLOTS

DS_MODE_BY_KEY = {"sr": "SR", "aram": "ARAM", "arena": "ARENA"}
_MODE_KEYS = ("sr", "aram", "arena")


# --------------------------------------------------------------------------- #
# The comp-archetype taxonomy + itemization bias map
# --------------------------------------------------------------------------- #
# Order matters for stable JSON output + UI left->right rendering by a future
# consumer. A closed set of 4 - small + documented per the charter.
COMP_ARCHETYPES: tuple[str, ...] = (
    "frontline_heavy", "burst_heavy", "poke", "mixed",
)
COMP_ARCHETYPE_SET = frozenset(COMP_ARCHETYPES)

# Each comp archetype -> the enemy-context itemization BIAS threaded into the
# shipped plan_build_order. ONLY these levers change per class; the engine does
# the reranking + reordering. The numbers are the typical enemy SHAPE per comp,
# benchmarked off the item-265/266 mixed baseline (armor 80 / mr 60 / hp 2000 /
# bonus_hp 600), scaled up for a frontline wall and down for a squishy burst
# comp. ``target_current_hp_pct`` stays 1.0 (full-HP target) - the durability is
# carried by the resist + HP block, not a synthetic low-HP assumption.
#
#   * frontline_heavy: a durable comp (high armor + mr + a real HP wall) ->
#     engine values %max-HP + penetration + bruiser-shred; AD-leaning frontline.
#   * burst_heavy: a squishy assassin / glass comp (low resists, low HP) ->
#     engine values raw early power; the lack of an HP wall demotes %max-HP.
#   * poke: ranged casters at moderate durability, AP-leaning -> resists +
#     sustain-relevant power.
#   * mixed: the neutral 2-2-1 baseline (the item-265/266 stat block, even split).
COMP_BIAS: dict[str, dict[str, float]] = {
    "frontline_heavy": {
        "target_armor": 110.0,
        "target_mr": 80.0,
        "target_max_hp": 3200.0,
        "target_bonus_hp": 1800.0,
        "enemy_ad_share": 0.6,
        "enemy_ap_share": 0.4,
        "target_current_hp_pct": 1.0,
    },
    "burst_heavy": {
        "target_armor": 50.0,
        "target_mr": 40.0,
        "target_max_hp": 1900.0,
        "target_bonus_hp": 500.0,
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
        "target_current_hp_pct": 1.0,
    },
    "poke": {
        "target_armor": 60.0,
        "target_mr": 70.0,
        "target_max_hp": 2100.0,
        "target_bonus_hp": 650.0,
        "enemy_ad_share": 0.4,
        "enemy_ap_share": 0.6,
        "target_current_hp_pct": 1.0,
    },
    "mixed": {
        "target_armor": 80.0,
        "target_mr": 60.0,
        "target_max_hp": 2400.0,
        "target_bonus_hp": 1000.0,
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
        "target_current_hp_pct": 1.0,
    },
}

# Archetype-diverse laner SAMPLE for the committed seed table. NOT a tier list -
# a neutral spread of damage types + roles (Garen = manaless bruiser, Annie = AP
# burst, Caitlyn = AD marksman, Malphite = AP tank, ...). Mirrors the HZ-A1
# SEED_CHAMPIONS spread. Expand to the full roster offline with
# ``--champions all`` (see full_roster / resolve_champions below).
SEED_CHAMPIONS: tuple[str, ...] = (
    "Garen", "Darius", "Annie", "Ahri", "Caitlyn",
    "Ezreal", "Lux", "Malphite", "Jax", "Syndra",
)

# Read cache keyed (mode, patch) -> (mtime, payload). mtime-aware: a stale entry
# is dropped when the file on disk is newer than what we cached. Mirrors
# core.laning_scenario_precompute._CACHE.
_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}


# --------------------------------------------------------------------------- #
# Pure taxonomy helpers (no engine, no snapshot)
# --------------------------------------------------------------------------- #
def bias_for(comp_archetype: str) -> dict[str, float]:
    """Return the itemization bias dict for a comp archetype.

    Raises ``KeyError`` on an unknown class - comp archetypes are a closed set
    the caller controls (mirrors ``laning_scenario_precompute.level_for_band``).
    A defensive copy so callers cannot mutate the module-level table.
    """
    return dict(COMP_BIAS[comp_archetype])


# The plan_build_order signature accepts the enemy stat block (target_armor /
# target_mr / target_max_hp / target_bonus_hp) as DIRECT kwargs, but the AD/AP
# share + current-HP-pct levers ride ``rank_kwargs`` (splatted into the DS
# dispatcher). Splitting here is the single source of truth so the module + the
# characterization test thread an IDENTICAL call.
_DIRECT_BIAS_KEYS: frozenset[str] = frozenset({
    "target_armor", "target_mr", "target_max_hp", "target_bonus_hp",
})
_RANK_BIAS_KEYS: frozenset[str] = frozenset({
    "enemy_ad_share", "enemy_ap_share", "target_current_hp_pct",
})


def split_bias(bias: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    """Split a comp-archetype bias into ``(direct_kwargs, rank_kwargs)`` for
    ``plan_build_order``: the enemy stat block goes direct, the AD/AP share +
    current-HP-pct ride ``rank_kwargs``. Pure - exposed so the precompute path
    and any test thread the engine call identically."""
    direct = {k: v for k, v in bias.items() if k in _DIRECT_BIAS_KEYS}
    rank = {k: v for k, v in bias.items() if k in _RANK_BIAS_KEYS}
    return direct, rank


# --------------------------------------------------------------------------- #
# Starter-tier floor - the "wrong precompute" guard rail
# --------------------------------------------------------------------------- #
# A shipped build ORDER is a FULL 6-slot build. A starter item in one of those
# slots is not a partial answer, it is a wrong one - and nothing upstream stops
# it. The engine's candidate-pool filter (agents/daemon_slayer/rank.py:687
# _filter_candidates) denies already-equipped / non-coachable / off-map /
# non-terminal / over-budget ids, and a starter is NONE of those: Doran's Helm
# (1120, 450g), Doran's Bow (1086, 400g), Cull (1083, 450g) and Guardian's Blade
# (3177, 950g) are all purchasable, terminal (``into`` empty) and map-legal, so
# they sit in the pool of every scorer in every mode.
#
# Today's tables are clean only as an ACCIDENT of the ordering metric. The order
# is planned with ``sort_by="delta"`` (absolute gain), which a 450g starter can
# never win against a 3000g legendary. The engine's OTHER shipped ordering
# metric, ``sort_by="efficiency"`` (gain per gold, implemented on all 7 scorers
# and transported end to end as body key ``sort``), inverts exactly that
# comparison, because stat-per-gold is what a starter maximizes. MEASURED
# 2026-08-06 over a 15-champion x 4-comp-archetype static sweep: 52 of 60 cells
# changed under efficiency, pulling Doran's Helm / Doran's Bow / Guardian's Blade
# into slots 3-5. So this floor is one flag away from mattering across every
# cell at once.
#
# THE RULE IS DERIVED FROM THE ITEM DATA, not assumed. Classification uses the
# Meraki / DDragon bulk that is already the source of truth for item metrics:
# the ``Lane`` tag plus a gold ceiling. Measured over the whole 16.15.1 registry,
# 78 items carry ``Lane`` - 76 cost under 1000g and are all genuinely starter
# tier (the Doran's line, Cull, Dark Seal, the Guardian's line, the support-quest
# starters, potions, trinkets, zero-gold quest markers), and exactly 2 cost more
# (Atma's Reckoning 223039 / 663039 at 2500g, a real legendary carrying the tag).
# The ceiling therefore sits in an EMPTY price band - dearest starter 950g,
# cheapest Lane-tagged legendary 2500g - rather than splitting a continuum.
#
# It is deliberately NOT a ``depth`` test: the mode-mirror namespaces (22xxxx
# Arena / 44xxxx / 66xxxx) ship ``depth: None`` with a flattened 2500-2750g
# price, so ``depth >= 2`` would flag 71 of the 138 currently-shipped ids -
# every Arena mirror legendary and every upgraded boot included.
STARTER_TIER_TAG = "Lane"
STARTER_TIER_GOLD_CEILING = 1000


def is_starter_tier(record: object) -> bool:
    """True when a DDragon / Meraki item ``record`` is starter tier.

    Starter tier = carries the ``Lane`` tag AND costs less than
    ``STARTER_TIER_GOLD_CEILING``. Pure, and TOTAL: a missing, non-dict, or
    unpriced record classifies as NOT starter tier. Unknown never becomes a
    positive on purpose - the caller is a guard rail over shipped artifacts, and
    a ragged item record must not be able to condemn a table on its own.
    """
    if not isinstance(record, dict):
        return False
    tags = record.get("tags")
    if not isinstance(tags, (list, tuple)) or STARTER_TIER_TAG not in tags:
        return False
    gold = record.get("gold")
    total = gold.get("total") if isinstance(gold, dict) else None
    try:
        return int(total) < STARTER_TIER_GOLD_CEILING
    except (TypeError, ValueError):
        return False


def iter_order_item_ids(payload: object):
    """Yield ``(champion, axis_class, item_id)`` for every ORDER slot in a
    build-order table payload.

    Walks BOTH committed leaf shapes, because the three table families do not
    agree on one: the FLAT damage-axis family stores a bare list of ids per axis
    class, while the comp-archetype precompute and the durability variants store
    ``{"order": [...]}``. A walker that understood only one shape would silently
    skip a whole family.

    Ids are yielded as ``str`` in table order. Blank / None slots are skipped.
    TOTAL - a missing, malformed, or partially-null payload yields nothing rather
    than raising, matching the fail-soft contract of every Lane B read surface.
    """
    if not isinstance(payload, dict):
        return
    orders = payload.get("build_orders")
    if not isinstance(orders, dict):
        return
    for champion, classes in orders.items():
        if not isinstance(classes, dict):
            continue
        for axis_class, cell in classes.items():
            if isinstance(cell, dict):
                cell = cell.get("order")
            if not isinstance(cell, (list, tuple)):
                continue
            for item_id in cell:
                if item_id is None or not str(item_id).strip():
                    continue
                yield str(champion), str(axis_class), str(item_id)


def engine_version() -> str:
    """The shipped DS engine version stamped into the table (fail-soft to ""
    so a missing engine package never sinks a dry-run)."""
    try:
        from agents.daemon_slayer import ENGINE_VERSION  # type: ignore
        return str(ENGINE_VERSION)
    except Exception:  # noqa: BLE001 - stamp is informational, never fatal
        return ""


def archetype_for(champion: str) -> str:
    """Resolve the primary scorer archetype for ``champion`` (DDragon-tag
    default or operator pick). Falls back to ``carry`` on a blank resolve -
    same resolver the item-265/266 generator uses, so the two tables agree on
    which scorer a champion reads."""
    info = archetype_picks.get_archetype_for(champion)
    return str(info.get("primary") or "carry")


# --------------------------------------------------------------------------- #
# Engine-backed cell + table sweep
# --------------------------------------------------------------------------- #
def compute_cell(
    champion: str,
    comp_archetype: str,
    *,
    mode: str = "SR",
    archetype: Optional[str] = None,
    level: int = DEFAULT_LEVEL,
    rank_fn: Optional[Callable[..., Optional[dict]]] = None,
    score_by: str = SCORE_BY_DEFAULT,
) -> dict:
    """Compute ONE precompute cell via the shipped ``plan_build_order``.

    Threads the comp-archetype's itemization bias (resist / HP context + AD/AP
    share + current-HP-pct) into the engine and returns the persisted leaf:
    ``{comp_archetype, order, bias}``. ``order`` is the ordered item-id list
    (incl. boots, no-double-unique enforced by the engine). An engine that is
    down / has nothing to plan yields ``order=[]`` (never raises - the planner's
    own None / empty contract).

    ``archetype`` defaults to the champion's resolved primary scorer.
    ``rank_fn`` is forwarded to ``plan_build_order`` for headless tests (the DS
    dispatcher stand-in); production leaves it None so the engine resolves it.

    ``score_by`` (default ``"blended"``, A-21 / RM-90 S1) is the EHP objective
    the TANK-routed cells rank on. It is NOT part of ``COMP_BIAS`` on purpose:
    the comp axis describes the ENEMY, while ``score_by`` picks which objective
    the scorer optimizes, so it is a sweep-wide knob rather than a per-class
    bias. Forwarded ONLY when non-default so a default regen is byte-identical.
    """
    bias = bias_for(comp_archetype)
    direct, rank_kwargs = split_bias(bias)
    arch = archetype if archetype is not None else archetype_for(champion)
    ds_mode = DS_MODE_BY_KEY.get(str(mode).lower(), str(mode))
    score_kwargs = (
        {} if str(score_by) == SCORE_BY_DEFAULT else {"score_by": str(score_by)}
    )
    try:
        result = plan_build_order(
            champion, arch,
            level=int(level), owned_item_ids=[], mode=ds_mode,
            slots=SLOTS, rank_fn=rank_fn, rank_kwargs=rank_kwargs,
            **score_kwargs, **direct,
        )
    except Exception:  # noqa: BLE001 - one bad cell never sinks the sweep
        result = None
    order = (
        [str(s.item_id) for s in result.order if s.item_id]
        if result is not None and result.order else []
    )
    return {
        "comp_archetype": comp_archetype,
        "order": order,
        "bias": bias,
    }


def build_orders_for_champion(
    champion: str,
    *,
    mode: str = "SR",
    level: int = DEFAULT_LEVEL,
    rank_fn: Optional[Callable[..., Optional[dict]]] = None,
    score_by: str = SCORE_BY_DEFAULT,
) -> dict[str, dict]:
    """Return ``{comp_archetype: cell}`` for one champion in one mode. The
    champion's scorer archetype is resolved once + reused across comp classes
    (the comp axis does not change which scorer a champion reads).

    ``score_by`` is passed through to every cell (see :func:`compute_cell`)."""
    arch = archetype_for(champion)
    out: dict[str, dict] = {}
    for comp in COMP_ARCHETYPES:
        out[comp] = compute_cell(
            champion, comp, mode=mode, archetype=arch,
            level=level, rank_fn=rank_fn, score_by=score_by,
        )
    return out


def generate_table(
    champions: Sequence[str],
    *,
    mode: str = "SR",
    level: int = DEFAULT_LEVEL,
    rank_fn: Optional[Callable[..., Optional[dict]]] = None,
    score_by: str = SCORE_BY_DEFAULT,
) -> dict:
    """Sweep the (champ x comp-archetype) grid into a payload dict.

    Cell order is deterministic (champions outer, then COMP_ARCHETYPES). Every
    leaf is a ``compute_cell`` dict. Stamps the patch + DS engine version +
    schema + the comp-archetype dimensions stanza.

    ``score_by`` is stamped into ``dimensions`` ONLY when non-default, so a
    default regen writes a payload byte-identical to the committed table while a
    seam-ON regen is self-describing (a reader can tell which objective the
    table was built against without re-deriving it).
    """
    build_orders: dict[str, dict] = {}
    for champ in champions:
        build_orders[archetype_picks.canonical_champion_id(champ)] = (
            build_orders_for_champion(
                champ, mode=mode, level=level, rank_fn=rank_fn,
                score_by=score_by,
            )
        )
    dimensions: dict = {
        "comp_archetypes": list(COMP_ARCHETYPES),
        "level": int(level),
    }
    if str(score_by) != SCORE_BY_DEFAULT:
        dimensions["score_by"] = str(score_by)
    return {
        "version": resolve_patch(),
        "generated_at": _now_iso(),
        "mode": str(mode).lower(),
        "schema": SCHEMA_VERSION,
        "engine_version": engine_version(),
        "dimensions": dimensions,
        "build_orders": build_orders,
    }


# --------------------------------------------------------------------------- #
# Persist
# --------------------------------------------------------------------------- #
def resolve_patch() -> str:
    """Read the active patch from current.txt; fall back to _FALLBACK_PATCH."""
    try:
        txt = _CURRENT_TXT.read_text(encoding="utf-8").strip()
        if txt:
            return txt
    except Exception:  # noqa: BLE001 - fail-soft to fallback
        pass
    return _FALLBACK_PATCH


def _now_iso() -> str:
    """UTC timestamp in ISO-8601, trimmed to seconds."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def out_dir_for(patch: str, override: Optional[str] = None) -> Path:
    """Output directory for ``patch`` (or the override path verbatim).

    Default: ``data/daemon_slayer/build_orders/<patch>`` (the NEW subdir).
    """
    if override:
        return Path(override)
    return _DS_DIR / _OUT_SUBDIR / patch


def atomic_write(payload: dict, out_path: Path) -> None:
    """Write ``payload`` to ``out_path`` via tmp + os.replace (atomic).

    A reader polling mid-write must never see a partial file (CLAUDE.md hard
    rule). ASCII-only, sorted keys for a stable diff. Mirrors
    ``core.laning_scenario_precompute.atomic_write``.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f".{out_path.stem}.", suffix=".tmp", dir=str(out_path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=True, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_path, str(out_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- #
# Read (fail-soft) - the future-coach lookup layer (HZ-C1 consumer)
# --------------------------------------------------------------------------- #
def _db_path(mode: str, patch: str) -> Path:
    return (
        _DS_DIR / _OUT_SUBDIR / patch / f"build_orders_{str(mode).lower()}.json"
    )


def load_build_order_precompute(
    mode: str = "sr", patch: Optional[str] = None
) -> dict:
    """Return the build-order precompute payload for ``mode`` + patch (or ``{}``).

    Cached + mtime-aware; fail-soft to ``{}`` on any missing / parse error.
    Mirrors ``core.laning_scenario_precompute.load_laning_scenarios``.
    """
    use_patch = patch or resolve_patch()
    key = (str(mode).lower(), use_patch)
    path = _db_path(mode, use_patch)
    try:
        mtime = path.stat().st_mtime
    except Exception:  # noqa: BLE001 - missing file -> empty
        _CACHE.pop(key, None)
        return {}
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except Exception:  # noqa: BLE001 - malformed -> empty
        payload = {}
    _CACHE[key] = (mtime, payload)
    return payload


def lookup(payload: dict, champion: str, comp_archetype: str) -> dict:
    """Navigate a loaded payload to one build-order cell (``{}`` when any key is
    absent). Pure - operates on an already-loaded dict so it is trivially
    testable + reusable by the future live consumer (HZ-C1)."""
    node: object = (
        payload.get("build_orders") if isinstance(payload, dict) else None
    )
    for step in (champion, comp_archetype):
        if not isinstance(node, dict):
            return {}
        node = node.get(step)
    return node if isinstance(node, dict) else {}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_csv(value: str) -> list[str]:
    return [tok.strip() for tok in str(value).split(",") if tok.strip()]


# The ONE ``--champions`` value (case-insensitive) that expands the sweep past
# SEED_CHAMPIONS to the whole canonical roster. ``--mode`` selects sr/aram/arena
# ONLY - it never touches the champion axis. Keeping this a named constant is the
# single source of truth both this CLI and the HZ-B2 CLI (build_order_variants)
# resolve against.
_ALL_CHAMPIONS_TOKEN = "all"

# Exit codes for the loud producer refusals. Distinct from the pre-existing
# engine-down 2 so an operator (or a scheduled regen) can tell WHICH refusal
# fired from the exit status alone.
EXIT_NO_ROSTER = 2
EXIT_EMPTY_TABLE = 3


class RosterUnavailableError(RuntimeError):
    """The canonical champion roster could not be resolved.

    Shared by both producers (this module and
    ``tools/daemon_slayer_build_orders_generate``) so an unresolvable roster has
    exactly ONE exception type to catch, whichever registry failed.
    """


def full_roster() -> list[str]:
    """Return the FULL canonical champion roster (sorted DDragon ids).

    Sourced from the DS engine champion registry for the active patch,
    ``data/daemon_slayer/<patch>/champions.json`` - the same per-patch registry
    the engine plans builds against (also read by
    ``core.archetype_picks._load_damage_axes``). Every canonical id is yielded
    (e.g. ``Annie``, ``Belveth``, ``MonkeyKing``), sorted for a stable sweep +
    diff. This is the ``--champions all`` roster: run a regen over the WHOLE
    roster with one flag, no hand-maintained 173-name CSV.

    Raises :class:`RosterUnavailableError` when the registry is missing /
    unreadable / empty. It deliberately does NOT fall back to
    ``SEED_CHAMPIONS``: a caller that asked for the full roster and silently
    received the 10-name seed would overwrite a complete table with a
    6-percent stub, and every consumer of a missing cell degrades silently
    (precomputed_build_coach / next_buy_fallback return ``[]``,
    _deterministic_coaching / laning_verdicts return ``None``), so the producer
    is the ONLY place that truncation can still be caught.
    """
    path = _DS_DIR / resolve_patch() / "champions.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - re-raised as the loud domain error
        raise RosterUnavailableError(
            f"champion registry {path} is missing or unreadable ({exc}); "
            "refusing to substitute the SEED sample for a full-roster request"
        ) from exc
    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    # DDragon ships THROWBACK-MODE rows beside the canonical roster - the
    # 16.15.1 drop adds 60 Jade_<Champion> entries at base_key + 60000. They are
    # NOT aliases (own stat line, own id), so a dedup does not absorb them; they
    # are partitioned out, because nothing downstream can cover them (Meraki
    # 404s all 60 -> no abilities, no archetype, no build order). See
    # agents.daemon_slayer.mode_variants.
    data = canonical_champions(data) if isinstance(data, dict) else {}
    # set() before sort: keeps "sorted and deduped" true by construction rather
    # than an accident of today's registry shape.
    ids = sorted({
        str(entry["id"])
        for entry in (data.values() if isinstance(data, dict) else ())
        if isinstance(entry, dict) and entry.get("id")
    })
    if not ids:
        raise RosterUnavailableError(
            f"champion registry {path} yielded no champion ids; "
            "refusing to substitute the SEED sample for a full-roster request"
        )
    return ids


def resolve_champions(value: str) -> list[str]:
    """Resolve a ``--champions`` CLI value to the champion list to sweep.

    * ``all`` (case-insensitive, whitespace-tolerant) -> the full canonical
      roster (``full_roster``).
    * a non-empty CSV -> those names parsed verbatim (``_parse_csv``), as today.
    * empty / whitespace-only -> ``SEED_CHAMPIONS`` (backward-compat: the
      committed seed sample - the default is deliberately UNCHANGED).
    """
    if str(value).strip().lower() == _ALL_CHAMPIONS_TOKEN:
        return full_roster()
    return _parse_csv(value) or list(SEED_CHAMPIONS)


def _count_cells(payload: dict) -> tuple[int, int]:
    """Return (champ_count, nonempty_order_count) for a mode payload."""
    bo = payload.get("build_orders") or {}
    champs = len(bo)
    cells = 0
    for classes in bo.values():
        for cell in (classes or {}).values():
            if (cell or {}).get("order"):
                cells += 1
    return champs, cells


def _engine_up() -> bool:
    """True when the live DS server is reachable (a non-dry run refuses to write
    against a dead engine - an empty table is worse than no table). Fail-soft to
    False if the client import fails."""
    try:
        from core import daemon_slayer_client as dsc
        return bool(dsc.is_engine_up(timeout=1.0))
    except Exception:  # noqa: BLE001
        return False


def _install_static_transport() -> None:
    """Compute build orders in-process via the DS server's POST-route handlers,
    with no :8860 HTTP and no running server.

    ``rank_for_primary_archetype`` (the default rank_fn) reaches the engine
    through ``daemon_slayer_client._post_json``; rebinding that one function to
    call ``server._POST_ROUTES[path](body)`` directly makes regen self-contained
    for a patch-refresh (reference_hz_precompute_patch_regen: the tables go dark
    on a bump unless regenerated, and the live path needs :8860 up). The handlers
    are the exact callables ``do_POST`` invokes, so the build orders are
    identical to the live path by construction - only the transport changes.
    """
    from core import daemon_slayer_client as dsc
    from agents.daemon_slayer import server as ds_server

    # The route handlers read a module-level snapshot that serve_forever() loads
    # at startup; load it here (same DataSnapshot.load the server uses) so the
    # in-process calls resolve against identical data.
    try:
        ds_server._CACHE.get()
    except RuntimeError:
        ds_server._CACHE.set(ds_server._load_default_snapshot())

    routes = ds_server._POST_ROUTES

    def _inprocess_post(path, body, timeout=dsc.DEFAULT_TIMEOUT):
        handler = routes.get(path)
        if handler is None:
            return None
        try:
            return handler(dict(body))
        except Exception:  # noqa: BLE001 - mirror the HTTP path's None-on-failure
            return None

    dsc._post_json = _inprocess_post


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI parser.

    Split out of :func:`main` so a test can assert the flag surface (notably the
    A-21 ``--score-by`` default + whitelist) without running a sweep.
    """
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", default="all",
                    choices=("all",) + _MODE_KEYS,
                    help="Which MODE(s) to generate: sr/aram/arena or all "
                         "(default: all). Selects modes ONLY - it does NOT "
                         "expand the champion roster; use --champions all "
                         "for the full roster.")
    ap.add_argument("--champions", default="",
                    help="CSV of champ DDragon names, or 'all' for the FULL "
                         "canonical roster (the active patch's DS registry). "
                         "'all' is the ONLY full-roster path. Default (empty): "
                         "the SEED_CHAMPIONS sample.")
    ap.add_argument("--level", type=int, default=DEFAULT_LEVEL,
                    help=f"Build level for the enemy context "
                         f"(default: {DEFAULT_LEVEL}).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print per-mode cell counts without writing.")
    ap.add_argument("--out", default="",
                    help="Override output directory (default: "
                         "data/daemon_slayer/build_orders/<patch>).")
    ap.add_argument("--static", action="store_true",
                    help="Compute in-process via the DS server handlers (no "
                         ":8860 HTTP / no running server). Self-contained regen "
                         "for patch-refresh; output is identical to the live "
                         "path by construction.")
    ap.add_argument("--score-by", default=SCORE_BY_DEFAULT,
                    choices=tuple(sorted(SCORE_BY_VALUES)),
                    help="EHP objective the TANK-routed cells rank on (A-21 / "
                         "RM-90 S1). 'blended' (default) is today's own-EHP "
                         "behavior and writes a byte-identical table; "
                         "'team_blended' additionally prices the EHP an item "
                         "confers on teammates, per-champion gated by the DS "
                         "engine's ally-reach signal. Ignored by every non-tank "
                         "archetype.")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = _build_arg_parser()
    args = ap.parse_args(argv)

    try:
        champions = resolve_champions(args.champions)
    except RosterUnavailableError as exc:
        logger.error("%s", exc)
        return EXIT_NO_ROSTER

    # Static mode computes in-process via the DS server handlers (no :8860).
    # Otherwise a non-dry run requires the live engine (the planner makes :8860
    # calls when rank_fn is None). A dry run never queries it.
    if args.static:
        _install_static_transport()
    elif not args.dry_run and not _engine_up():
        logger.info("DS engine at 127.0.0.1:8860 is not responding. Start it via "
              '`"C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" tools/start_daemon_slayer.py` and re-run (a non-dry run '
              "refuses to write tables against a dead engine).", file=sys.stderr)
        return 2

    patch = resolve_patch()
    out_dir = out_dir_for(patch, args.out or None)
    target_modes = _MODE_KEYS if args.mode == "all" else (args.mode,)

    logger.info(f"build-order precompute gen patch={patch} modes={target_modes} "
          f"champions={len(champions)} level={args.level} "
          f"score_by={args.score_by} "
          f"dry_run={args.dry_run} out={out_dir}")

    started = time.time()
    for mode_key in target_modes:
        payload = generate_table(
            champions, mode=DS_MODE_BY_KEY.get(mode_key, "SR"),
            level=int(args.level), score_by=args.score_by,
        )
        champs, cells = _count_cells(payload)
        if args.dry_run:
            logger.info(f"  [dry-run] {mode_key:5s}: {champs} champions, "
                  f"{cells} non-empty orders (not written)")
        elif cells == 0:
            # _engine_up() only catches an engine that was dead BEFORE the
            # sweep; one that dies mid-sweep is swallowed per-cell ("one bad
            # cell never sinks the sweep") and would otherwise write a
            # full-size table of empty orders over a good one, exit 0, and
            # surface nowhere downstream.
            logger.error(
                "%s: sweep produced 0 non-empty orders across %d champions - "
                "refusing to write %s (engine failure mid-sweep?)",
                mode_key, champs, out_dir / f"build_orders_{mode_key}.json",
            )
            return EXIT_EMPTY_TABLE
        else:
            out_path = out_dir / f"build_orders_{mode_key}.json"
            atomic_write(payload, out_path)
            logger.info(f"  {mode_key:5s}: {champs} champions, {cells} non-empty "
                  f"orders -> {out_path.name}")

    logger.info(f"done in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

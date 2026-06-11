# arch: Lane B build-order VARIANTS (anti-tank / anti-squishy, A3-driven) | section=core | frozen=no
"""Lane B build-order VARIANTS (HZ-B2) - PRIMARY north star: drive live Haiku
usage to ZERO.

PURPOSE
    Precompute, offline + deterministically, an explicit ``anti_tank`` (vs a
    high-HP / frontline wall) vs ``anti_squishy`` (vs a burst / low-HP comp)
    build-order PAIR per ``(my_champ x mode)`` so a FUTURE coach can read a dict
    at request time INSTEAD of asking Claude Haiku (or the live :8893 path) "do
    I pivot anti-tank into this enemy comp, and what do I buy". The order is the
    SHIPPED, deterministic build planner's (``core.build_order.plan_build_order``)
    output under each variant's enemy-stat bias - this module is the bias-map +
    A3-modulation + sweep + persist + read layer around it, NO new build / combat
    math.

DISTINCT FROM HZ-B1 (the comp-archetype table, ``core.build_order_precompute``)
    HZ-B1 keys on a comp-SHAPE axis: ``frontline_heavy`` / ``burst_heavy`` /
    ``poke`` / ``mixed`` - four FIXED enemy stat blocks, each a class the WHOLE
    grid shares. HZ-B1's ``frontline_heavy`` already nudges toward penetration /
    %max-HP via its (constant) high-HP wall.

    HZ-B2 is a different, complementary axis: a champion-DECISION pair driven by
    the DS anti-tank axis A3 (``core.ds_antitank_hint.build_antitank_hint``):

      * ``anti_tank``    - the enemy is a high-HP, high-resist WALL. The engine
        values %max-HP damage, %armor / %magic penetration, lethality-agnostic
        armor-pen, and antiheal because flat damage bounces off the wall. BUT how
        hard the champion must lean there is NOT constant: it is MODULATED by that
        champion's OWN A3 anti-tank score. A champion whose kit already shreds
        tanks (Vayne %max-HP W, score ~0.95 -> ``lean_in``) faces a SOFTER
        synthetic wall - its kit carries the shred, so it over-itemizes less. A
        flat-damage champion that cannot shred with its kit (Lux / Caitlyn /
        Annie, score 0.0 -> ``recommend_antitank_items``) faces the FULL wall, so
        the engine front-loads the penetration / %HP item. This A3 plumbing is
        what makes HZ-B2 the anti-tank BRANCH and not a second copy of HZ-B1's
        frontline class.
      * ``anti_squishy``  - the enemy is a low-HP, low-resist burst / glass comp.
        The engine values raw early power + lethality + crit; there is no HP wall
        to shred, so the penetration / %max-HP items demote. A3-INVARIANT (a wall
        the kit could shred does not exist here), so this bias is the same for
        every champion.

    The two variants are the EXTREME ENDS of the enemy-durability spectrum,
    surfaced as a clean labeled pair the future coach can flip between on the
    live enemy comp - whereas HZ-B1's four classes are intermediate shapes.

A3 INTEGRATION (the axis the directive names)
    ``antitank_signal(champ, mode)`` wraps ``build_antitank_hint`` against a
    synthetic all-frontline enemy comp (5 known tanks) so the A3 gate always
    ``applies`` - the question it answers is "IF the enemy is a tank wall, does
    THIS champion's kit handle it (``lean_in``) or must it buy anti-tank items
    (``recommend_antitank_items``)". ``variant_bias_for(champ, "anti_tank")``
    reads that signal and scales the wall's ``target_max_hp`` (and a touch of
    ``target_bonus_hp``) DOWN by the champion's ``my_antitank_score`` - a high
    kit-shred score relaxes the synthetic wall. The A3 stanza
    (score / top_kind / shreds_resist / lean_in / recommend_antitank_items) is
    also stamped on every cell as provenance of the pivot.

WHAT v1 IS (honest scope)
    BUILD + PERSIST + READ only. The live coach flip is EXCLUDED (charter 4b
    "do not flip blind" - the table is read by a FUTURE consumer, HZ-C1, after
    real-game validation + operator OK; Haiku / the live :8893 path stays the
    interim floor). The committed table seeds the SAME archetype-diverse champion
    sample HZ-B1 used (``SEED_CHAMPIONS`` imported from HZ-B1 so the two tables
    line up champ-for-champ); ``--champions`` / ``--mode all`` expand it offline.

SHAPE (per mode, atomic write to data/daemon_slayer/build_orders/<patch>/)::

    {
      "version": "<patch>", "generated_at": "<iso>", "mode": "<sr|aram|arena>",
      "schema": "build_order_variants/v1", "engine_version": "<ds engine>",
      "dimensions": {"variants": ["anti_tank", "anti_squishy"], "level": 13,
                     "driven_by": "ds_antitank_hint/A3"},
      "build_orders": {
        "<champ display name>": {
          "<variant>": {
            "variant": "<variant>",
            "order": ["<item_id>", ...],     # ordered, incl. boots
            "bias": {"target_armor": ..., "target_max_hp": ..., ...},
            "antitank": {"my_antitank_score": ..., "lean_in": ...,
                         "recommend_antitank_items": ..., "shreds_resist": ...,
                         "top_kind": ...}
          }
        }
      }
    }

NOTE - shares the HZ-B1 ``build_orders/`` subdir under a DISTINCT filename
``build_order_variants_<mode>.json`` (HZ-B1 owns ``build_orders_<mode>.json``).
Neither clobbers the other; HZ-B1's schema + tests are untouched.

FAIL-SOFT (read side)
    A missing / unreadable / malformed table yields ``{}`` and every ``lookup``
    yields ``{}``. The future coach degrades to "no precomputed variant" (it
    falls back to the existing path), never an exception. Mirrors
    ``core.build_order_precompute`` / ``core.laning_scenario_precompute``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

# Allow running as a direct script path (python core/build_order_variants.py) in
# addition to `python -m core.build_order_variants` - put the project root on
# sys.path before the package imports below. No-op when already importable.
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

# Reuse the shipped engine orchestration + the HZ-B1 layer wholesale. We do NOT
# reimplement ordering / boots / the no-double rule (build_order), nor the
# bias-splitting / persist / patch helpers (build_order_precompute). The A3
# signal source is core.ds_antitank_hint (read-only consumer of the DS
# antitank scorer).
from core.build_order import DEFAULT_SLOTS, plan_build_order
from core.build_order_precompute import (
    DS_MODE_BY_KEY,
    SEED_CHAMPIONS,
    archetype_for,
    engine_version,
    resolve_patch,
    split_bias,
)
from core.ds_antitank_hint import build_antitank_hint

# Project root: core/ -> C:\Riot Commander\
_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _ROOT / "data"
_DS_DIR = _DATA_DIR / "daemon_slayer"
_CURRENT_TXT = _DS_DIR / "current.txt"

# Shares the HZ-B1 subdir; a DISTINCT filename keeps the two tables apart.
_OUT_SUBDIR = "build_orders"
_FILE_PREFIX = "build_order_variants"

# Patch fallback when current.txt is missing (guards a fresh checkout only).
_FALLBACK_PATCH = "16.11.1"

SCHEMA_VERSION = "build_order_variants/v1"

# Representative build level for the variant precompute. 13 = a 3-item powerspike
# point where the anti-tank vs anti-squishy itemization choice is live (a couple
# of slots already committed, the pivot item is the next pick). HZ-B1 pins 11 (a
# 2-item mid); the variant axis benefits from one more slot of context so the
# penetration / lethality choice is exercised, not pre-empted by core slots.
DEFAULT_LEVEL = 13

# Full build = 6 item slots (incl. boots). Reused from core.build_order so a
# slot-count change there propagates here.
SLOTS = DEFAULT_SLOTS

DS_MODE_KEYS = ("sr", "aram", "arena")


# --------------------------------------------------------------------------- #
# The variant taxonomy + base enemy-stat bias map
# --------------------------------------------------------------------------- #
# A closed pair (the two extremes of the enemy-durability spectrum). Order
# matters for stable JSON output + left->right UI rendering by a future consumer.
VARIANTS: tuple[str, ...] = ("anti_tank", "anti_squishy")
VARIANT_SET = frozenset(VARIANTS)

# Each variant -> the BASE enemy-context itemization bias threaded into the
# shipped plan_build_order. Only these levers change per variant; the engine
# does the reranking + reordering. The numbers are the typical enemy SHAPE at
# each extreme, anchored off the HZ-B1 mixed baseline (armor 80 / mr 60 /
# hp 2400 / bonus_hp 1000) and pushed to the ends:
#
#   * anti_tank: a high-HP, high-resist WALL (armor 200 / mr 130 / hp 4200 /
#     bonus_hp 2700, AD-leaning frontline) -> engine front-loads %max-HP +
#     %armor / %MR penetration + antiheal. This is the BASE wall; the actual
#     per-champion wall is this SOFTENED by the champion's A3 kit-shred score
#     in ``variant_bias_for`` (a champ that already shreds needs less itemized
#     pen). target_current_hp_pct stays 1.0 - the durability is the resist + HP
#     block, not a synthetic low-HP assumption.
#   * anti_squishy: a low-HP, low-resist GLASS comp (armor 35 / mr 30 / hp 1500 /
#     bonus_hp 300, even AD/AP share) -> engine values raw early power +
#     lethality + crit; no wall to shred, so penetration / %HP items demote.
#     A3-invariant.
VARIANT_BIAS: dict[str, dict[str, float]] = {
    "anti_tank": {
        "target_armor": 200.0,
        "target_mr": 130.0,
        "target_max_hp": 4200.0,
        "target_bonus_hp": 2700.0,
        "enemy_ad_share": 0.6,
        "enemy_ap_share": 0.4,
        "target_current_hp_pct": 1.0,
    },
    "anti_squishy": {
        "target_armor": 35.0,
        "target_mr": 30.0,
        "target_max_hp": 1500.0,
        "target_bonus_hp": 300.0,
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
        "target_current_hp_pct": 1.0,
    },
}

# Synthetic all-frontline enemy comp fed to the A3 gate so it always ``applies``
# (>= HIGH_HP_ENEMY_MIN tanky enemies). These 5 are tank/bruiser-archetype
# champions in the registry; the comp is a STAND-IN for "the enemy is a tank
# wall", not a real opponent - we only read back whether MY champion's kit
# handles that wall (lean_in) or must itemize it (recommend_antitank_items).
_SYNTHETIC_TANK_WALL: tuple[str, ...] = (
    "Malphite", "Ornn", "Sion", "Sejuani", "Maokai",
)

# How strongly a champion's own A3 anti-tank score relaxes the synthetic wall.
# A score of 1.0 (a maximal kit-shredder like Vayne, ~0.95) removes up to this
# fraction of the wall's bonus HP pool; a score of 0.0 (a flat-damage champ)
# leaves the full wall. Bounded + conservative - the goal is a softer, not
# absent, wall (the champion still benefits from SOME itemized pen / %HP).
_A3_WALL_RELAX = 0.45
# The maximum fraction of the wall we ever relax (so even a perfect shredder
# still sees a meaningful wall - it does not collapse to the squishy model).
_A3_WALL_RELAX_CAP = 0.45

# Read cache keyed (mode, patch) -> (mtime, payload). mtime-aware; mirrors
# core.build_order_precompute._CACHE.
_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}


# --------------------------------------------------------------------------- #
# A3 signal (the anti-tank axis the directive names)
# --------------------------------------------------------------------------- #
def antitank_signal(champion: str, mode: str = "SR") -> dict:
    """Return the A3 anti-tank decision signal for ``champion`` (never raises).

    Wraps ``core.ds_antitank_hint.build_antitank_hint`` against a synthetic
    all-frontline enemy comp so the A3 gate always ``applies`` - the returned
    dict answers "IF the enemy is a tank wall, does this champion's kit handle
    it or must it itemize anti-tank". Keys (a stable subset of the A3 hint):
    ``my_antitank_score`` (float), ``top_kind`` (str), ``shreds_resist`` (bool),
    ``lean_in`` (bool - kit already shreds), ``recommend_antitank_items`` (bool -
    must buy the shred). Fail-soft to a zeroed stanza on any error."""
    try:
        hint = build_antitank_hint(
            champion, list(_SYNTHETIC_TANK_WALL), mode or "SR"
        )
        return {
            "my_antitank_score": float(hint.get("my_antitank_score", 0.0) or 0.0),
            "top_kind": str(hint.get("my_top_kind") or ""),
            "shreds_resist": bool(hint.get("shreds_resist")),
            "lean_in": bool(hint.get("lean_in")),
            "recommend_antitank_items": bool(hint.get("recommend_antitank_items")),
        }
    except Exception:  # noqa: BLE001 - the signal is provenance, never fatal
        return {
            "my_antitank_score": 0.0,
            "top_kind": "",
            "shreds_resist": False,
            "lean_in": False,
            "recommend_antitank_items": False,
        }


# --------------------------------------------------------------------------- #
# Pure taxonomy helpers (no engine snapshot beyond the A3 registry read)
# --------------------------------------------------------------------------- #
def variant_bias_for(champion: str, variant: str, mode: str = "SR") -> dict[str, float]:
    """Return the enemy-context itemization bias for one ``(champion, variant)``.

    ``anti_squishy`` is the static base bias (A3-invariant - no wall to shred).
    ``anti_tank`` is the base wall SOFTENED by the champion's own A3 anti-tank
    score: a maximal kit-shredder (score ~1.0) sees up to ``_A3_WALL_RELAX_CAP``
    of the wall's bonus-HP pool removed (its kit carries the shred); a
    flat-damage champion (score 0.0) sees the full wall. This is the A3 axis
    deciding HOW HARD the champion itemizes anti-tank.

    Raises ``KeyError`` on an unknown variant (a closed set the caller controls).
    A defensive copy so callers cannot mutate the module-level table.
    """
    base = dict(VARIANT_BIAS[variant])
    if variant != "anti_tank":
        return base
    score = antitank_signal(champion, mode)["my_antitank_score"]
    # Clamp the score to [0, 1] then relax the wall proportionally (capped).
    relax = min(max(score, 0.0), 1.0) * _A3_WALL_RELAX
    relax = min(relax, _A3_WALL_RELAX_CAP)
    base["target_max_hp"] = round(base["target_max_hp"] * (1.0 - relax), 1)
    base["target_bonus_hp"] = round(base["target_bonus_hp"] * (1.0 - relax), 1)
    return base


# --------------------------------------------------------------------------- #
# Engine-backed cell + table sweep
# --------------------------------------------------------------------------- #
def compute_variant_cell(
    champion: str,
    variant: str,
    *,
    mode: str = "SR",
    archetype: Optional[str] = None,
    level: int = DEFAULT_LEVEL,
    rank_fn: Optional[Callable[..., Optional[dict]]] = None,
) -> dict:
    """Compute ONE variant cell via the shipped ``plan_build_order``.

    Threads the ``(champion, variant)`` A3-modulated enemy-stat bias into the
    engine and returns the persisted leaf ``{variant, order, bias, antitank}``.
    ``order`` is the ordered item-id list (incl. boots, no-double-unique enforced
    by the engine). An engine that is down / has nothing to plan yields
    ``order=[]`` (never raises - the planner's own None / empty contract).

    ``archetype`` defaults to the champion's resolved primary scorer.
    ``rank_fn`` is forwarded to ``plan_build_order`` for headless tests (the DS
    dispatcher stand-in); production leaves it None so the engine resolves it.
    """
    bias = variant_bias_for(champion, variant, mode)
    direct, rank_kwargs = split_bias(bias)
    arch = archetype if archetype is not None else archetype_for(champion)
    ds_mode = DS_MODE_BY_KEY.get(str(mode).lower(), str(mode))
    try:
        result = plan_build_order(
            champion, arch,
            level=int(level), owned_item_ids=[], mode=ds_mode,
            slots=SLOTS, rank_fn=rank_fn, rank_kwargs=rank_kwargs, **direct,
        )
    except Exception:  # noqa: BLE001 - one bad cell never sinks the sweep
        result = None
    order = (
        [str(s.item_id) for s in result.order if s.item_id]
        if result is not None and result.order else []
    )
    return {
        "variant": variant,
        "order": order,
        "bias": bias,
        "antitank": antitank_signal(champion, mode),
    }


def variants_for_champion(
    champion: str,
    *,
    mode: str = "SR",
    level: int = DEFAULT_LEVEL,
    rank_fn: Optional[Callable[..., Optional[dict]]] = None,
) -> dict[str, dict]:
    """Return ``{variant: cell}`` for one champion in one mode. The champion's
    scorer archetype is resolved once + reused across variants (the variant axis
    does not change which scorer a champion reads)."""
    arch = archetype_for(champion)
    out: dict[str, dict] = {}
    for variant in VARIANTS:
        out[variant] = compute_variant_cell(
            champion, variant, mode=mode, archetype=arch,
            level=level, rank_fn=rank_fn,
        )
    return out


def generate_table(
    champions: Sequence[str],
    *,
    mode: str = "SR",
    level: int = DEFAULT_LEVEL,
    rank_fn: Optional[Callable[..., Optional[dict]]] = None,
) -> dict:
    """Sweep the (champ x variant) grid into a payload dict.

    Cell order is deterministic (champions outer, then VARIANTS). Every leaf is a
    ``compute_variant_cell`` dict. Stamps the patch + DS engine version + schema +
    the variant dimensions stanza (which names the A3 axis it is driven by).
    """
    build_orders: dict[str, dict] = {}
    for champ in champions:
        build_orders[champ] = variants_for_champion(
            champ, mode=mode, level=level, rank_fn=rank_fn,
        )
    return {
        "version": resolve_patch(),
        "generated_at": _now_iso(),
        "mode": str(mode).lower(),
        "schema": SCHEMA_VERSION,
        "engine_version": engine_version(),
        "dimensions": {
            "variants": list(VARIANTS),
            "level": int(level),
            "driven_by": "ds_antitank_hint/A3",
        },
        "build_orders": build_orders,
    }


# --------------------------------------------------------------------------- #
# Persist
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    """UTC timestamp in ISO-8601, trimmed to seconds."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def out_dir_for(patch: str, override: Optional[str] = None) -> Path:
    """Output directory for ``patch`` (or the override path verbatim).

    Default: ``data/daemon_slayer/build_orders/<patch>`` (shared with HZ-B1).
    """
    if override:
        return Path(override)
    return _DS_DIR / _OUT_SUBDIR / patch


def atomic_write(payload: dict, out_path: Path) -> None:
    """Write ``payload`` to ``out_path`` via tmp + os.replace (atomic).

    A reader polling mid-write must never see a partial file (CLAUDE.md hard
    rule). ASCII-only, sorted keys for a stable diff. Mirrors
    ``core.build_order_precompute.atomic_write``.
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
        _DS_DIR / _OUT_SUBDIR / patch
        / f"{_FILE_PREFIX}_{str(mode).lower()}.json"
    )


def load_build_order_variants(
    mode: str = "sr", patch: Optional[str] = None
) -> dict:
    """Return the build-order variant payload for ``mode`` + patch (or ``{}``).

    Cached + mtime-aware; fail-soft to ``{}`` on any missing / parse error.
    Mirrors ``core.build_order_precompute.load_build_order_precompute``.
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


def lookup(payload: dict, champion: str, variant: str) -> dict:
    """Navigate a loaded payload to one variant cell (``{}`` when any key is
    absent). Pure - operates on an already-loaded dict so it is trivially
    testable + reusable by the future live consumer (HZ-C1)."""
    node: object = (
        payload.get("build_orders") if isinstance(payload, dict) else None
    )
    for step in (champion, variant):
        if not isinstance(node, dict):
            return {}
        node = node.get(step)
    return node if isinstance(node, dict) else {}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_csv(value: str) -> list[str]:
    return [tok.strip() for tok in str(value).split(",") if tok.strip()]


def _count_cells(payload: dict) -> tuple[int, int]:
    """Return (champ_count, nonempty_order_count) for a mode payload."""
    bo = payload.get("build_orders") or {}
    champs = len(bo)
    cells = 0
    for variants in bo.values():
        for cell in (variants or {}).values():
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", default="all",
                    choices=("all",) + DS_MODE_KEYS,
                    help="Restrict generation to one mode (default: all).")
    ap.add_argument("--champions", default="",
                    help="CSV of champ DDragon display names "
                         "(default: SEED_CHAMPIONS, shared with HZ-B1).")
    ap.add_argument("--level", type=int, default=DEFAULT_LEVEL,
                    help=f"Build level for the enemy context "
                         f"(default: {DEFAULT_LEVEL}).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print per-mode cell counts without writing.")
    ap.add_argument("--out", default="",
                    help="Override output directory (default: "
                         "data/daemon_slayer/build_orders/<patch>).")
    args = ap.parse_args(argv)

    champions = _parse_csv(args.champions) or list(SEED_CHAMPIONS)

    # A non-dry run requires a live engine (the planner makes :8893 calls when
    # rank_fn is None). A dry run never queries it.
    if not args.dry_run and not _engine_up():
        print("DS engine at 127.0.0.1:8893 is not responding. Start it via "
              '`"C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" tools/start_daemon_slayer.py` and re-run (a non-dry run '
              "refuses to write tables against a dead engine).", file=sys.stderr)
        return 2

    patch = resolve_patch()
    out_dir = out_dir_for(patch, args.out or None)
    target_modes = DS_MODE_KEYS if args.mode == "all" else (args.mode,)

    print(f"build-order VARIANTS gen patch={patch} modes={target_modes} "
          f"champions={len(champions)} level={args.level} "
          f"dry_run={args.dry_run} out={out_dir}")

    started = time.time()
    for mode_key in target_modes:
        payload = generate_table(
            champions, mode=DS_MODE_BY_KEY.get(mode_key, "SR"),
            level=int(args.level),
        )
        champs, cells = _count_cells(payload)
        if args.dry_run:
            print(f"  [dry-run] {mode_key:5s}: {champs} champions, "
                  f"{cells} non-empty orders (not written)")
        else:
            out_path = out_dir / f"{_FILE_PREFIX}_{mode_key}.json"
            atomic_write(payload, out_path)
            print(f"  {mode_key:5s}: {champs} champions, {cells} non-empty "
                  f"orders -> {out_path.name}")

    print(f"done in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# arch: Lane B precomputed build-order COVERAGE measurement | section=tools | frozen=no
"""tools.build_order_coverage - measure the precomputed build-order universe.

PRIMARY north star context: Lane B of the Haiku-elimination program wants every
build-coaching surface to read a PRECOMPUTED Daemon Slayer answer at request
time instead of calling an LLM. A precompute that is silently PARTIAL is the
dangerous state - a coach flipped off its live call degrades only for the
uncovered cells, and every consumer in this repo fails SOFT (returns ``[]`` /
``{}`` / ``None``), so nothing says so out loud.

This module answers one question with numbers: what IS the precomputed
build-order universe, and what fraction of it is populated?

THREE ARTIFACT FAMILIES, TWO KEYSPACES
--------------------------------------
There are three build-order table families in this repo across two champion
key-spaces. Confusing them silently returns ``{}`` (see the module docstring of
``core/next_buy_fallback.py``):

  * ``comp`` - ``data/daemon_slayer/build_orders/<patch>/build_orders_<mode>.json``
    schema ``build_order_precompute/v1``, CANONICAL DDragon-id keyed
    ("MonkeyKing", "Belveth"). Producer: ``core.build_order_precompute``.
    Axis: ``COMP_ARCHETYPES`` (4).
  * ``variant`` - ``data/daemon_slayer/build_orders/<patch>/build_order_variants_<mode>.json``
    schema ``build_order_variants/v1``, CANONICAL keyed. Producer:
    ``core.build_order_variants``. Axis: ``VARIANTS`` (2).
  * ``flat`` - ``data/daemon_slayer/<patch>/build_orders_<mode>.json``
    (NO ``build_orders/`` path segment), DISPLAY-name keyed ("Nunu & Willump",
    "Kha'Zix"). Producer: ``tools/daemon_slayer_build_orders_generate.py``.
    Axis: ``ENEMY_COMP_CLASSES`` (3).

PRODUCER-DERIVED UNIVERSE
-------------------------
Every axis of the expected universe is imported from the PRODUCER module, never
enumerated from the table on disk. Deriving the universe from the consumer (or
from the artifact itself) is circular: a table regenerated with 10 of 173
champions would define its own universe as 10 and report 100 percent. So:

  * modes      <- ``build_order_precompute._MODE_KEYS`` / ``build_order_variants.DS_MODE_KEYS``
                  / ``daemon_slayer_build_orders_generate.MODES``
  * champions  <- ``build_order_precompute.full_roster()`` (canonical families)
                  and ``daemon_slayer_build_orders_generate.load_champions()``
                  (flat family)
  * axes       <- ``COMP_ARCHETYPES`` / ``VARIANTS`` / ``ENEMY_COMP_CLASSES``
  * slots      <- ``daemon_slayer_build_orders_generate._SLOTS``
  * patch      <- ``data/daemon_slayer/current.txt`` via ``resolve_patch()``

MODES IN SCOPE: sr / aram / arena only. ARAM Mayhem (raw gameMode ``KIWI``) maps
onto the ``aram`` table via ``core.mode_capabilities.district_config``, so it is
covered by the aram tables and is NOT a fourth keyspace. TFT and brawl have no
build tables by design and are excluded (``core/next_buy_fallback.py:67``).

A cell counts as COVERED only when its ``order`` is a non-empty list. An empty
order is exactly what every producer emits when the DS engine is down or has
nothing to plan (``core/build_order_precompute.py:303``), so "the key exists"
is not evidence of coverage.

CLI::

    python tools/build_order_coverage.py            # human matrix
    python tools/build_order_coverage.py --json     # machine-readable
    python tools/build_order_coverage.py --min 1.0  # exit 1 below the floor
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import build_order_precompute as _bop  # noqa: E402
from core import build_order_variants as _bov  # noqa: E402

from tools import daemon_slayer_build_orders_generate as _gen  # noqa: E402

# Family ids. Stable strings - the guard test and any future dashboard row key
# off these.
FAMILY_COMP = "comp"
FAMILY_VARIANT = "variant"
FAMILY_FLAT = "flat"
FAMILIES: tuple[str, ...] = (FAMILY_COMP, FAMILY_VARIANT, FAMILY_FLAT)

# Which key-space each family is written in. Purely descriptive - the roster for
# each family is still pulled from that family's OWN producer below.
KEYSPACE_BY_FAMILY: dict[str, str] = {
    FAMILY_COMP: "canonical",
    FAMILY_VARIANT: "canonical",
    FAMILY_FLAT: "display",
}

_DS_DIR = _ROOT / "data" / "daemon_slayer"


def resolve_patch() -> str:
    """The active patch, read through the producer's own resolver."""
    return _bop.resolve_patch()


def table_path(family: str, mode: str, patch: str) -> Path:
    """On-disk path for one (family, mode) table at ``patch``.

    Resolved through each producer's own path helper where one exists, so a
    producer relocating its output cannot leave this tool measuring a stale
    location.
    """
    mode = str(mode).lower()
    if family == FAMILY_COMP:
        return _bop._db_path(mode, patch)
    if family == FAMILY_VARIANT:
        return _bov._db_path(mode, patch)
    if family == FAMILY_FLAT:
        return _gen.out_dir_for(patch, None) / f"build_orders_{mode}.json"
    raise ValueError(f"unknown family {family!r}")


def expected_modes(family: str) -> tuple[str, ...]:
    """Modes the family's PRODUCER sweeps under ``--mode all``."""
    if family == FAMILY_COMP:
        return tuple(_bop._MODE_KEYS)
    if family == FAMILY_VARIANT:
        return tuple(_bov.DS_MODE_KEYS)
    if family == FAMILY_FLAT:
        return tuple(_gen.MODES)
    raise ValueError(f"unknown family {family!r}")


def expected_axes(family: str) -> tuple[str, ...]:
    """The per-champion axis the family's PRODUCER emits a cell for."""
    if family == FAMILY_COMP:
        return tuple(_bop.COMP_ARCHETYPES)
    if family == FAMILY_VARIANT:
        return tuple(_bov.VARIANTS)
    if family == FAMILY_FLAT:
        return tuple(_gen.ENEMY_COMP_CLASSES)
    raise ValueError(f"unknown family {family!r}")


def expected_roster(family: str) -> tuple[str, ...]:
    """The champion roster the family's PRODUCER sweeps under ``--champions all``.

    Canonical families read the per-patch DS engine registry
    (``full_roster()``); the flat family reads the DDragon champion dump in
    DISPLAY-name form (``load_champions()``). Two key-spaces, two producer-side
    sources - never one roster reused for both.
    """
    if family in (FAMILY_COMP, FAMILY_VARIANT):
        return tuple(_bop.full_roster())
    if family == FAMILY_FLAT:
        return tuple(_gen.load_champions())
    raise ValueError(f"unknown family {family!r}")


def expected_slots() -> int:
    """Item slots in a complete build order (producer constant)."""
    return int(_gen._SLOTS)


def _cell_order(leaf: object) -> object:
    """Pull the item-id list out of a cell.

    The canonical families wrap the list in a dict under ``order``; the flat
    family stores the bare list. Both shapes are handled so one measurement
    covers all three families.
    """
    if isinstance(leaf, dict):
        return leaf.get("order")
    return leaf


def measure_table(family: str, mode: str, patch: str) -> dict:
    """Coverage for ONE (family, mode) table. Never raises.

    Returns a dict with ``expected`` / ``covered`` cell counts plus the named
    defect groups: champions absent from the table entirely, cells present but
    empty, cells shorter than a full build, and keys present on disk that the
    producer would not emit (a stale roster or a key-space drift).
    """
    path = table_path(family, mode, patch)
    roster = expected_roster(family)
    axes = expected_axes(family)
    slots = expected_slots()
    result = {
        "family": family,
        "mode": mode,
        "keyspace": KEYSPACE_BY_FAMILY[family],
        "path": str(path),
        "exists": path.is_file(),
        "expected": len(roster) * len(axes),
        "covered": 0,
        "missing_champions": [],
        "empty_cells": [],
        "short_cells": [],
        "extra_keys": [],
        "error": "",
    }
    if not result["exists"]:
        result["error"] = "table absent"
        result["missing_champions"] = list(roster)
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a corrupt table is a 0pct result
        result["error"] = f"unreadable: {exc}"
        result["missing_champions"] = list(roster)
        return result
    orders = payload.get("build_orders") if isinstance(payload, dict) else None
    if not isinstance(orders, dict):
        result["error"] = "no build_orders block"
        result["missing_champions"] = list(roster)
        return result

    for champ in roster:
        cells = orders.get(champ)
        if not isinstance(cells, dict):
            result["missing_champions"].append(champ)
            continue
        for axis in axes:
            order = _cell_order(cells.get(axis))
            if isinstance(order, list) and order:
                result["covered"] += 1
                if len(order) < slots:
                    result["short_cells"].append(f"{champ}/{axis}:{len(order)}")
            else:
                result["empty_cells"].append(f"{champ}/{axis}")

    result["extra_keys"] = sorted(set(orders) - set(roster))
    return result


def measure_all(patch: str | None = None) -> dict:
    """Full coverage matrix across every family x mode. Never raises."""
    use_patch = patch or resolve_patch()
    tables = []
    for family in FAMILIES:
        for mode in expected_modes(family):
            tables.append(measure_table(family, mode, use_patch))
    expected = sum(t["expected"] for t in tables)
    covered = sum(t["covered"] for t in tables)
    return {
        "patch": use_patch,
        "slots": expected_slots(),
        "expected": expected,
        "covered": covered,
        "ratio": (covered / expected) if expected else 0.0,
        "tables": tables,
    }


def _fmt(report: dict) -> str:
    lines = [
        f"build-order coverage  patch={report['patch']}  "
        f"slots={report['slots']}",
        "",
        f"{'family':9s} {'keyspace':10s} {'mode':6s} "
        f"{'covered':>9s} {'expected':>9s} {'pct':>7s}  notes",
    ]
    for t in report["tables"]:
        pct = (100.0 * t["covered"] / t["expected"]) if t["expected"] else 0.0
        notes = []
        if t["error"]:
            notes.append(t["error"])
        if t["missing_champions"]:
            notes.append(f"missing_champions={len(t['missing_champions'])}")
        if t["empty_cells"]:
            notes.append(f"empty_cells={len(t['empty_cells'])}")
        if t["short_cells"]:
            notes.append(f"short_cells={len(t['short_cells'])}")
        if t["extra_keys"]:
            notes.append(f"extra_keys={len(t['extra_keys'])}")
        lines.append(
            f"{t['family']:9s} {t['keyspace']:10s} {t['mode']:6s} "
            f"{t['covered']:9d} {t['expected']:9d} {pct:6.1f}%  "
            + (", ".join(notes) if notes else "-")
        )
    lines.append("")
    lines.append(
        f"TOTAL {report['covered']} / {report['expected']} cells "
        f"({100.0 * report['ratio']:.2f}%)"
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure precomputed build-order coverage (Lane B).",
    )
    ap.add_argument("--patch", default=None,
                    help="patch to measure (default: data/daemon_slayer/current.txt)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="emit the raw report as JSON")
    ap.add_argument("--min", type=float, default=None, dest="min_ratio",
                    help="exit 1 when overall coverage is below this ratio (0-1)")
    args = ap.parse_args(argv)

    report = measure_all(args.patch)
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_fmt(report))
    if args.min_ratio is not None and report["ratio"] < args.min_ratio:
        print(
            f"FAIL: coverage {report['ratio']:.4f} below floor {args.min_ratio}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""RM-295c: the empty-publish-over-a-good-cache sweep, closed as a MEASURED
population rather than a fix count.

Mechanical criterion (the row's own): a module under `core/` that declares a
module-global `_LOADED` + `_LOADED_AT` TTL pair. Measured 2026-10-04:
population = 2, both already guarded by cycle 37 (RM-295a) and pinned by
behaviour tests:
  - core/smoothed_rates_101qq.py `_publish` drops an EMPTY rebuild over a
    non-empty snapshot (tests/test_smoothed_rates_101qq*.py);
  - core/rank_tier_bench.py `_refresh_now` keeps the previous grid when the
    rebuild is empty (`if not grid and _GRID`;
    tests/test_rank_tier_bench.py test_an_empty_rebuild_does_not_wipe_a_good_grid).
Fixes needed this sweep: 0. Immune: 0 of 2 by construction; 2 of 2 guarded.

Widened pass (any `core/` module with a TTL plus a `global` rebind), 5 more,
all recorded IMMUNE or out of class, none given the guard blind:
  - core/minimap_blob_detect.py: holds last-good on a transient grab failure
    (`_HOLD_LAST_GOOD_S`) and its empty state is MEANINGFUL (no champions on
    the minimap) - the guard would break it;
  - core/cost_tracker.py: a 2 s dedupe cache, no fail-soft loader;
  - core/riot_api.py / core/riot_api_cache.py: SQLite-backed per-key cache,
    no whole-snapshot publish;
  - core/self_cast_log.py: listener state, not a cache.

This guard makes the population self-reporting: a NEW module adopting the
`_LOADED`/`_LOADED_AT` pair fails here until it is reviewed for the empty-
publish class and added below.
"""
from __future__ import annotations

import ast
from pathlib import Path

_CORE = Path(__file__).resolve().parent.parent / "core"

REVIEWED = {"rank_tier_bench.py", "smoothed_rates_101qq.py"}


def _module_globals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _population() -> set[str]:
    found = set()
    for path in sorted(_CORE.glob("*.py")):
        g = _module_globals(path)
        if "_LOADED" in g and "_LOADED_AT" in g:
            found.add(path.name)
    return found


def test_population_is_exactly_the_reviewed_set():
    pop = _population()
    assert pop, "enumeration collapsed - an empty population passes vacuously"
    assert pop == REVIEWED, (
        f"live-first cache population changed: {sorted(pop ^ REVIEWED)}. "
        "Review each new module for the RM-295c empty-publish class (guard it "
        "with a failing test, or record why it is immune) before adding it.")


def test_reviewed_modules_still_carry_the_empty_rebuild_guard():
    rtb = (_CORE / "rank_tier_bench.py").read_text(encoding="utf-8")
    assert "if not grid and _GRID:" in rtb
    sr = (_CORE / "smoothed_rates_101qq.py").read_text(encoding="utf-8")
    assert "Also drops an EMPTY rebuild over a non-empty snapshot" in sr

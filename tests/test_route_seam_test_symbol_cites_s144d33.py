"""Guard: two DS route-seam test docstrings cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Two DS test modules list the engine
API surface they "confirmed before scaffolding", each entry pinned with a line
cite. Every cite had drifted onto unrelated code; every claim still held.

- ``test_oq17_route_seam_transport.py`` (e2801db54, 2026-07-02):
  ``burst.py:461-492`` (``compute_burst_damage``'s seam params, def now at
  507), ``burst.py:1596-1628`` (``rank_items_by_burst``'s seam params, def now
  at 1945) and ``dps.py:628`` (``compute_dps``'s ``apply_melee_aa_gate``, def
  now at 769).
- ``test_rank_route_seam_passthrough.py`` (3f2557286, 2026-06-27):
  ``server.py:166`` (``_SnapshotCache.set``, now at 201; 166 is a row of the
  index HTML), ``rank.py:549-551``, ``ehp.py:1930-1931``,
  ``hybrid.py:618-619``, ``burst.py:1512`` and ``hps.py:815`` (the
  ``rank_items*`` seam params).

The oq17 docstring also said, twice, that ``rank_items_by_burst`` "forwards"
``assume_squishy_target`` / ``target_preset``. It accepts them and consumes
them itself (they resolve the target preset); only ``assume_takedown`` and
``assume_ability_amp`` go on to ``compute_burst_damage``. Both sites now say
"accepts", which is what the tests below pin.

The tests pin each listed parameter to its function's signature, so a renamed
or dropped seam fails here instead of leaving a docstring that lies.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import burst, dps, ehp, hps, hybrid, rank, server

REPO = Path(__file__).resolve().parent.parent
DS_TESTS = REPO / "agents" / "daemon_slayer" / "tests"

CITING = (
    DS_TESTS / "test_oq17_route_seam_transport.py",
    DS_TESTS / "test_rank_route_seam_passthrough.py",
)

_LINE_CITE = re.compile(r"\w\.py:\d")

# (function, the seam parameters the docstrings say it takes)
_SURFACE = (
    (burst.compute_burst_damage, (
        "runes", "assume_takedown", "assume_ability_amp",
        "score_completion_runes", "gate_target_hp_amp", "gate_caster_hp_amp",
        "caster_current_hp_pct",
    )),
    (burst.rank_items_by_burst, (
        "assume_takedown", "assume_squishy_target", "assume_ability_amp",
        "target_preset", "prefer_kit_axis_by_win",
    )),
    (dps.compute_dps, ("apply_melee_aa_gate",)),
    (rank.rank_items, (
        "exempt_offclass_by_win", "prefer_kit_axis_by_win", "cost_ceiling",
    )),
    (ehp.rank_items_by_ehp, ("prefer_survivability_by_win", "cost_ceiling")),
    (hybrid.rank_items_by_hybrid, (
        "prefer_survivability_by_win", "cost_ceiling",
    )),
    (hps.rank_items_by_hps, ("prefer_survivability_by_win",)),
)

# Phrases only the replacement prose carries, per citing file.
_NAMED_IN_PROSE = {
    "test_oq17_route_seam_transport.py": (
        "(rank_items_by_burst, already accepts these)",
        "caster_current_hp_pct - ``burst.compute_burst_damage``.",
        "* rank_items_by_burst accepts assume_takedown",
        "target_preset - ``burst.rank_items_by_burst``.",
        "apply_melee_aa_gate - ``dps.compute_dps``.",
    ),
    "test_rank_route_seam_passthrough.py": (
        "- ``server._SnapshotCache.set``.",
        "cost_ceiling - ``rank.rank_items``.",
        "- ``ehp.rank_items_by_ehp``.",
        "- ``hybrid.rank_items_by_hybrid``.",
        "- ``burst.rank_items_by_burst``.",
        "- ``hps.rank_items_by_hps``.",
    ),
}


def _docstring(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    end = text.index('"""', 3)
    return text[: end + 3]


def test_citing_files_exist() -> None:
    for path in CITING:
        assert path.is_file(), path


def test_no_line_cites_left() -> None:
    for path in CITING:
        hits = _LINE_CITE.findall(_docstring(path))
        assert not hits, f"{path.name}: line cites {hits}"


def test_replacement_prose_names_the_symbols() -> None:
    for path in CITING:
        doc = _docstring(path)
        for phrase in _NAMED_IN_PROSE[path.name]:
            assert phrase in doc, f"{path.name}: missing {phrase!r}"


def test_listed_seam_params_are_in_the_signatures() -> None:
    for func, params in _SURFACE:
        have = inspect.signature(func).parameters
        missing = [p for p in params if p not in have]
        assert not missing, f"{func.__qualname__} lacks {missing}"


def test_no_forwards_claim_left_in_oq17() -> None:
    assert "forwards" not in _docstring(CITING[0])


def test_snapshot_cache_set_is_what_get_returns() -> None:
    assert isinstance(server._CACHE, server._SnapshotCache)
    cache = server._SnapshotCache()
    snap = object()
    cache.set(snap)  # type: ignore[arg-type]
    assert cache.get() is snap


def test_burst_rank_result_exposes_target_resists() -> None:
    src = inspect.getsource(burst.BurstRankResult.to_dict)
    for key in ('"target_armor"', '"target_mr"'):
        assert key in src, key

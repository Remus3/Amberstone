"""Guard: two DS burst tests cite burst.py / rank.py by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Two DS test modules explained the
engine path they exercise with line cites; every cite had drifted, every
claim still held.

- ``test_arena_mirror_magic_burst_rm323.py`` (c9bea8b07, 2026-09-01):
  ``burst.py:1143-1163`` (the DSV6 ``assume_magic_burst`` block in
  ``compute_burst_damage``, now near 1170-1187) and ``burst.py:681-683``
  (``mode_mult``, now near 699-701; 681-683 had been a ``build_champion``
  comment even at the creating commit).
- ``test_l2_execute_in_burst_term.py`` (52346e4c7, 2026-07-13):
  ``rank.py:991`` / ``rank.py:1090`` (the ``baseline_burst`` /
  ``trial_burst`` calls in ``rank_items``, now near 1267 / 1399) and
  ``burst.py:1051`` (the ``assume_takedown`` execute block, now near 1131).

The prose now names the functions, and the tests below pin each claim to the
code, so a moved or renamed seam fails here instead of leaving prose that lies.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import burst, effects, rank

REPO = Path(__file__).resolve().parent.parent
DS_TESTS = REPO / "agents" / "daemon_slayer" / "tests"
DS_PKG = REPO / "agents" / "daemon_slayer"

CITING = (
    DS_TESTS / "test_arena_mirror_magic_burst_rm323.py",
    DS_TESTS / "test_l2_execute_in_burst_term.py",
)

_LINE_CITE = re.compile(r"\w\.py:\d|\(:\d")

# Phrases only the replacement prose carries, per citing file.
_NAMED_IN_PROSE = {
    "test_arena_mirror_magic_burst_rm323.py": (
        "``assume_magic_burst`` seam in\n``burst.compute_burst_damage``",
        "``effects.total_magic_burst_damage``",
        "(``mode_mult`` in burst.compute_burst_damage)",
    ),
    "test_l2_execute_in_burst_term.py": (
        "``baseline_burst`` and every candidate\n``trial_burst`` in "
        "``rank.rank_items``",
        "(the execute block in ``burst.compute_burst_damage``)",
        "(``rank.rank_items``: ``trial_burst`` - ``baseline_burst``)",
    ),
}


def test_citing_files_exist() -> None:
    for path in CITING:
        assert path.is_file(), path


def test_no_line_cites_left() -> None:
    for path in CITING:
        hits = _LINE_CITE.findall(path.read_text(encoding="utf-8"))
        assert not hits, f"{path.name}: line cites {hits}"


def test_replacement_prose_names_the_symbols() -> None:
    for path in CITING:
        text = path.read_text(encoding="utf-8")
        for phrase in _NAMED_IN_PROSE[path.name]:
            assert phrase in text, f"{path.name}: missing {phrase!r}"


def test_magic_burst_fields_are_read_only_by_the_dsv6_seam() -> None:
    reader = inspect.getsource(effects.total_magic_burst_damage)
    assert "magic_burst_base" in reader
    assert "magic_burst_ap_ratio" in reader
    callers = []
    for path in sorted(DS_PKG.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name != "effects.py" and (
            "total_magic_burst_damage(" in text
            or ".magic_burst_base" in text
            or ".magic_burst_ap_ratio" in text
        ):
            callers.append(path.name)
    assert callers == ["burst.py"], callers
    src = inspect.getsource(burst.compute_burst_damage)
    seam = src.index("if assume_magic_burst:")
    assert "total_magic_burst_damage(" in src[seam:seam + 200]


def test_burst_mode_mult_is_one_outside_aram() -> None:
    src = inspect.getsource(burst.compute_burst_damage)
    assert 'mode_mult = 1.0\n    if mode == "ARAM":' in src
    assert src.count("mode_mult =") == 2


def test_execute_is_gated_on_assume_takedown() -> None:
    src = inspect.getsource(burst.compute_burst_damage)
    gate = src.index("if assume_takedown and target_max_hp > 0:")
    assert "total_execute_max_hp_pct(" in src[gate:gate + 200]
    default = inspect.signature(burst.compute_burst_damage).parameters[
        "assume_takedown"
    ].default
    assert default is False


def test_rank_items_burst_term_goes_through_safe_burst() -> None:
    src = inspect.getsource(rank.rank_items)
    assert "baseline_burst = _safe_burst(" in src
    assert "trial_burst = _safe_burst(" in src
    assert "trial_burst - baseline_burst" in src
    assert "assume_takedown=True" in inspect.getsource(rank._safe_burst)

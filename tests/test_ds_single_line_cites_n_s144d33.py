"""Guard: ``_rune_offense_grants.py`` cites ``rune_procs`` by symbol, not line (RM-1053 part).

Measured 2026-10-30 at ENGINE 1.290.0. The module carried 13 line cites,
all into ``rune_procs.py``:

- ``rune_procs.py:743`` / ``:762`` (x2 each) for the Absolute Focus 8233 and
  Gathering Storm 8236 ``RUNE_PROCS`` rows, and ``rune_procs.py:685`` (x2,
  one of them inside the ``_ADJUDICATED_NON_GRANTS["9923"]`` reason string)
  for the Hail of Blades 9923 row. All three still land on the row's opening
  line.
- ``rune_procs.py:212`` (x5) for the "the caller multiplies by the live
  stack count (max 12)" contract; that quote now sits on :213, inside
  ``_conqueror_adaptive``.
- ``rune_procs.py:426`` / ``:434`` for "the grant does NOT enter the burst
  total" and "burst is BYTE-IDENTICAL"; the second quote now ends on :435.
  Both live in the Absolute Focus and Gathering Storm paragraphs of the
  "Conditionally modeled" item 232 comment block.

Most still resolve, but a line cite rots on the next edit above it. The
tests below pin the cites and the claims they carried by symbol instead.
Sibling sweep: no other module or test outside these RM-1053 guards cites
``rune_procs.py`` by line; CHANGELOG history is left as written.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import _rune_offense_grants, rune_procs

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|``:\d|\blines \d")

TARGETS = {
    "_rune_offense_grants.py": (
        "Absolute Focus 8233 (``rune_procs.RUNE_PROCS[8233]``) and Gathering "
        "Storm 8236 (``rune_procs.RUNE_PROCS[8236]``)",
        "The Absolute Focus and Gathering Storm paragraphs of the ``rune_procs`` "
        "\"Conditionally modeled\" item 232 comment block",
        "``rune_procs._conqueror_adaptive`` states the engine's own contract",
        "ALREADY registered and scored as ``rune_procs.RUNE_PROCS[9923]``. "
        "Adding it here would double-credit it.",
        "``conqueror_stacks`` - rune_procs._conqueror_adaptive puts the stack "
        "count on the caller",
        "``rune_procs._conqueror_adaptive`` assigns the live stack count to the "
        "caller",
        "Already registered as rune_procs.RUNE_PROCS[8236] with proc_type "
        "\"adaptive\"",
        "Already registered as rune_procs.RUNE_PROCS[8233] with proc_type "
        "\"adaptive\"",
        "hardcoded 12. rune_procs._conqueror_adaptive assigns the live stack "
        "count to the caller",
        "``rune_procs._conqueror_adaptive`` puts the live stack count on the "
        "caller",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def _conditional_block() -> str:
    src = inspect.getsource(rune_procs)
    start = src.index("# Conditionally modeled (honest gate, byte-identical default)")
    end = src.index("# Honest exclusions (NOT in RUNE_PROCS)", start)
    return src[start:end]


def test_pattern_matches_the_old_shapes():
    for sample in (
        "grants - Absolute Focus 8233 (``rune_procs.py:743``) and Gathering Storm 8236",
        "hybrid or rank path has ever seen it. ``rune_procs.py:426`` and",
        "    in ``rune_procs.py:685``. Adding it here would double-credit it.",
        "# ``conqueror_stacks`` - rune_procs.py:212 puts the stack count on the caller",
        '        "registered and scored at rune_procs.py:685 - adding it here would "',
    ):
        assert _LINE_CITE.search(sample), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_hail_of_blades_reason_names_the_row():
    # A runtime value split over two literals, so it is checked as a value.
    reason = _rune_offense_grants._ADJUDICATED_NON_GRANTS["9923"]
    assert "registered and scored as rune_procs.RUNE_PROCS[9923] - adding it here would double-credit it" in reason
    assert not _LINE_CITE.search(reason)


def test_sorcery_rows_are_registered_adaptive():
    focus = rune_procs.RUNE_PROCS[8233]
    storm = rune_procs.RUNE_PROCS[8236]
    assert focus.name == "Absolute Focus" and focus.proc_type == "adaptive"
    assert storm.name == "Gathering Storm" and storm.proc_type == "adaptive"
    assert focus.condition == "caster_hp_above"
    assert storm.condition == "game_time"


def test_hail_of_blades_row_is_registered():
    hob = rune_procs.RUNE_PROCS[9923]
    assert hob.name == "Hail of Blades"
    assert hob.proc_type == "per_attack"


def test_conqueror_contract_lives_in_conqueror_adaptive():
    flat = _flat(inspect.getsource(rune_procs._conqueror_adaptive))
    assert "compute_rune_proc_damage surfaces the PER-STACK adaptive force" in flat
    assert "the caller multiplies by the live stack count (max 12)" in flat


def test_conditional_block_states_both_outcomes():
    block = _flat(_conditional_block())
    focus = block.index("Absolute Focus 8233 (Sorcery)")
    storm = block.index("Gathering Storm 8236 (Sorcery)")
    assert "the grant does NOT enter the burst total" in block[focus:storm]
    assert "burst is BYTE-IDENTICAL" in block[storm:]

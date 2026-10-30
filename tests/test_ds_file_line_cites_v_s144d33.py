"""Guard: the per-spell CC registry and the EHP lift-doc cites cite by
symbol (v).

Measured 2026-10-30 at ENGINE 1.290.0. The last RM-1053 residue in
``_per_spell_cc.py`` and ``ehp.py`` (plus the two DS test docstrings that
copy the ehp cites):

- ``_per_spell_cc.py`` said Senna W was "verified via grep on
  ability_dps.py - line 1182". ability_dps.py no longer names Senna at
  all; the root tuple is seeded in this module's own
  ``_build_per_spell_cc_durations``, inside its ENGINE 1.34.0 wave 4
  block.
- ``ehp.py`` (5 sites) and ``test_ehp_enemy_pen.py`` /
  ``test_ehp_gold_efficiency_t1f4.py`` cited
  ``docs/COMPETITOR_LIFT_2026-06-08.md`` by line. That path no longer
  exists: the doc moved to ``docs/_archive/``. The line ranges were still
  right inside the archived copy, so the cites now name the archive path
  and the ``#### T1-F3`` / ``#### T1-F4`` section id instead of lines.

The tests below pin the cites, and the facts they restate, by symbol.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import _per_spell_cc, ehp

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
LIFT = "COMPETITOR_LIFT_2026-06-08.md"
ARCHIVED = REPO / "docs" / "_archive" / LIFT
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|(?<![\w.]):\d|\blines? \d")
# Guard u's strip, plus a hyphenated prose word such as "travel-line 1.0".
_NOT_A_CITE = re.compile(r"\[:\d+\]|(?<!\w):8860\b|%:\d+%|-lines? (?=\d)")

TARGETS = {
    "_per_spell_cc.py": (
        "verified in this module: the ENGINE 1.34.0 wave 4 block of "
        "_build_per_spell_cc_durations seeds Senna W root",
    ),
    "ehp.py": (
        "at 0.99 per the lift-doc spec (the T1-F3 WHAT line of "
        f"docs/_archive/{LIFT}) so a single",
        f"T1-F3 (BACKLOG MED, docs/_archive/{LIFT} T1-F3) -",
        f"T1-F3 (2026-06-09, docs/_archive/{LIFT} T1-F3):",
        f'"EHP per gold" verdict (docs/_archive/{LIFT} T1-F4):',
        f"T1-F4 (BACKLOG LOW, docs/_archive/{LIFT} T1-F4) -",
    ),
    "tests/test_ehp_enemy_pen.py": (
        f"T1-F3 (BACKLOG MED, docs/_archive/{LIFT} T1-F3) -",
    ),
    "tests/test_ehp_gold_efficiency_t1f4.py": (
        f"T1-F4 (BACKLOG LOW, docs/_archive/{LIFT} T1-F4) -",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def _section(heading_id: str) -> str:
    lines = ARCHIVED.read_text(encoding="utf-8").splitlines()
    at = next(i for i, line in enumerate(lines)
              if line.startswith(f"#### {heading_id} "))
    body = [lines[at]]
    for line in lines[at + 1:]:
        if line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


def test_pattern_matches_the_old_shapes():
    for sample in (
        "#   verified via grep on ability_dps.py - line 1182 has Senna W",
        f"(docs/{LIFT} line 60) so a single source can",
        f'"""T1-F3 (BACKLOG MED, docs/{LIFT} lines 59-66) -',
        f"# T1-F4 (BACKLOG LOW, docs/{LIFT} lines 68-75) -",
    ):
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


def test_strip_drops_only_the_hyphenated_word():
    assert not _LINE_CITE.search(_NOT_A_CITE.sub(
        "", "# Sejuani R - Glacial Prison: stun on travel-line 1.0/1.5"))
    assert _LINE_CITE.search(_NOT_A_CITE.sub("", "travel-line 1.0 line 60"))
    assert _LINE_CITE.search(_NOT_A_CITE.sub("", "see lines 59-66"))


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_cite_of_the_moved_path(name):
    text = (DS / name).read_text(encoding="utf-8")
    assert f"docs/{LIFT}" not in text


def test_the_lift_doc_lives_only_in_the_archive():
    assert ARCHIVED.is_file()
    assert not (REPO / "docs" / LIFT).exists()


def test_t1f3_what_line_states_the_99_percent_cap():
    what = [line for line in _section("T1-F3").splitlines()
            if line.startswith("- WHAT:")]
    assert len(what) == 1
    assert "capped 99%" in what[0]
    assert ehp._clamp_pct(5.0) == 0.99
    assert ehp._clamp_pct(-1.0) == 0.0


def test_t1f4_section_is_the_ehp_per_gold_verdict():
    head = _section("T1-F4").splitlines()[0]
    assert "EHP-per-gold" in head
    assert "buy verdict" in head


def test_senna_w_is_seeded_in_the_wave_4_block():
    assert _per_spell_cc._build_per_spell_cc_durations()["Senna"]["W"] == (
        1.25, 1.5, 1.75, 2.0, 2.25)
    src = inspect.getsource(_per_spell_cc._build_per_spell_cc_durations)
    start = src.index("# ----- ENGINE 1.34.0 wave 4 ")
    end = src.index("# ----- ENGINE 1.35.0 wave 5 ")
    assert 'registry.setdefault("Senna", {})["W"]' in src[start:end]

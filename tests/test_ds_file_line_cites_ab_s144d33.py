"""Guard: the A-03 / RM-81 override test cites the shaping notes by heading (ab).

Measured 2026-10-30 at ENGINE 1.290.0, re-deriving the RM-1053 "DS test
lines" residue over agents/daemon_slayer/tests. Two prose cites in
``test_ability_base_overrides.py`` were bare line numbers into the archived
``DS_ABILITY_SHAPING_NOTES.md``:

- the ``{{ap|X to Y}}`` linear-ramp method was cited at ``:528-532``; that
  resolved, but it is the notes' ``### Method`` section;
- ``test_non_registry_champion_dps_unchanged`` called Ziggs a SENSITIVE
  harness control "at :546". It was wrong: that line is the Gwen row, and
  the notes' ``### Positive control`` table lists Ahri, Zed and Gwen as
  SENSITIVE with no Ziggs in it. Of the three champions the test samples,
  only Zed is one of those controls.

The tests below pin the heading cites, the correction, and the notes and
registry facts the test's prose restates. The notes are archived and never
edited, so these reads stay stable.
"""
from __future__ import annotations

import re
from pathlib import Path

from agents.daemon_slayer._ability_base_overrides import _ABILITY_BASE_OVERRIDES

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_ability_base_overrides.py"
)
NOTES = (
    REPO / "docs" / "_archive" / "2026-07-28-research-consolidation"
    / "DS_ABILITY_SHAPING_NOTES.md"
)
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|(?<![\w.]):\d|\blines? \d")
_NOT_A_CITE = re.compile(r"\[:\d+\]|(?<!\w):8860\b|%:\d+%|-lines? (?=\d)")

PHRASES = (
    'the notes\' "### Method" section states the harness used',
    "Ziggs, Zed and Lux are not in the override registry",
    'The notes\' "### Positive control" table lists Ahri, Zed and Gwen as '
    "SENSITIVE harness controls; Zed is the one of them sampled here",
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(heading: str) -> str:
    lines = NOTES.read_text(encoding="utf-8").splitlines()
    start = lines.index(heading)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("#")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_pattern_matches_the_old_shapes():
    for sample in (
        "# the notes' method section, :528-532, states the harness used).",
        "control at :546) must score identically with the flag ON.",
    ):
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for sample in PHRASES:
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left():
    text = TARGET.read_text(encoding="utf-8")
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]
    assert not hits, "cite by heading, not line:\n" + "\n".join(hits)


def test_names_the_headings():
    flat = _flat(TARGET.read_text(encoding="utf-8"))
    for phrase in PHRASES:
        assert phrase in flat, phrase
    assert "Ziggs (an ability-route champion" not in flat


def test_method_section_states_the_linear_ramp():
    flat = _flat(_section("### Method"))
    assert "linear ramp across the same rank count" in flat
    assert "{{ap|X to Y}}" in flat


def test_positive_control_lists_zed_not_ziggs():
    rows = {
        m.group(1): m.group(2)
        for m in re.finditer(
            r"^(\w+)\s+ds\.\w+\s+(SENSITIVE|\*\*\* INERT \*\*\*)",
            _section("### Positive control - this is what makes the nulls "
                     "trustworthy"),
            re.M,
        )
    }
    assert {k for k, v in rows.items() if v == "SENSITIVE"} == {
        "Ahri", "Zed", "Gwen"
    }
    assert "Ziggs" not in rows


def test_sampled_champions_are_outside_the_registry():
    registered = {cid for cid, _key, _form in _ABILITY_BASE_OVERRIDES}
    assert registered
    assert not registered & {"Ziggs", "Zed", "Lux"}
    flat = _flat(TARGET.read_text(encoding="utf-8"))
    assert 'for champ in ("Ziggs", "Zed", "Lux"):' in flat

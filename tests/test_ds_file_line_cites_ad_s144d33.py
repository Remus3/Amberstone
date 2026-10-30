"""Guard: the RM-97 pet / summon pin cites objdamage and zonecontrol by symbol (ad).

Measured 2026-10-30 at ENGINE 1.290.0, re-deriving the RM-1053 "DS test
lines" residue over agents/daemon_slayer/tests. The CONTRAST bullets in the
module docstring of ``test_pet_summon_damage_uncredited_rm97.py`` cited
``objdamage.py`` "lines 79-83 / 92" and ``zonecontrol.py`` "lines 73-77".
Both still resolved (the SUMMON_DPS / SUMMON comment entries and the
objdamage weight row), but nothing fenced them: the two earlier rm97 guards
match only ``ability_dps.py:<n>`` and ``<module>.py:<n>``, not "lines <n>".
The zonecontrol bullet also said "the same population", while that comment
adds Illaoi tentacles and Azir soldiers.

The tests below pin the rewritten prose and the source facts it restates.
"""
from __future__ import annotations

import re
from pathlib import Path

from agents.daemon_slayer import objdamage, zonecontrol

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "tests" / "test_pet_summon_damage_uncredited_rm97.py"

_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|\blines? \d")

OBJDAMAGE_PHRASE = (
    "``agents/daemon_slayer/objdamage.py`` ``_OBJDAMAGE_KIND_WEIGHT`` - "
    "``SUMMON_DPS`` weight 0.55; the kind-weight comment above it names "
    '"Heimerdinger turrets / Yorick ghouls + Maiden / Malzahar voidlings / '
    'Annie Tibbers / Elise spiders / Zyra plants / Ivern Daisy".'
)
ZONECONTROL_PHRASE = (
    "``agents/daemon_slayer/zonecontrol.py`` ``_ZONECONTROL_KIND_WEIGHT`` - "
    "``SUMMON`` weight 0.60; the comment above it names the same population "
    "plus Illaoi tentacles and Azir soldiers."
)
OBJDAMAGE_NAMES = (
    "Heimerdinger turrets / Yorick ghouls + Maiden / Malzahar voidlings / "
    "Annie Tibbers / Elise spiders / Zyra plants / Ivern Daisy"
)
ZONECONTROL_NAMES = (
    "Heimerdinger Q turrets", "Zyra plants", "Yorick ghouls + R Maiden",
    "Malzahar W voidlings", "Annie R Tibbers", "Ivern R Daisy",
    "Elise spiders", "Illaoi tentacles", "Azir soldiers",
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _comment_entry(module: Path, assignment: str, start: str, stop: str) -> str:
    lines = module.read_text(encoding="utf-8").splitlines()
    end = next(i for i, line in enumerate(lines) if line.startswith(assignment))
    block = []
    for line in reversed(lines[:end]):
        if not line.startswith("#"):
            break
        block.append(line[1:])
    text = _flat(" ".join(reversed(block)))
    return text[text.index(start):text.index(stop)]


def test_pattern_matches_the_old_shapes():
    for sample in (
        "* ``agents/daemon_slayer/objdamage.py`` lines 79-83 / 92 - ``SUMMON_DPS``",
        "* ``agents/daemon_slayer/zonecontrol.py`` lines 73-77 - ``SUMMON`` weight",
        "* ``agents/daemon_slayer/abilities.py:274``",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (OBJDAMAGE_PHRASE, ZONECONTROL_PHRASE):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_names_the_symbols():
    src = _flat(TARGET.read_text(encoding="utf-8"))
    assert OBJDAMAGE_PHRASE in src
    assert ZONECONTROL_PHRASE in src
    assert "naming the same population." not in src


def test_summon_weights_are_as_stated():
    assert objdamage._OBJDAMAGE_KIND_WEIGHT["SUMMON_DPS"] == 0.55
    assert zonecontrol._ZONECONTROL_KIND_WEIGHT["SUMMON"] == 0.6


def test_objdamage_comment_names_the_population():
    entry = _comment_entry(
        DS / "objdamage.py", "_OBJDAMAGE_KIND_WEIGHT", "0.55 SUMMON_DPS", "0.45 BURST_SECURE",
    )
    assert OBJDAMAGE_NAMES in entry


def test_zonecontrol_comment_names_the_population():
    entry = _comment_entry(
        DS / "zonecontrol.py", "_ZONECONTROL_KIND_WEIGHT", "0.60 SUMMON", "0.45 DISPLACE",
    )
    for name in ZONECONTROL_NAMES:
        assert name in entry, name

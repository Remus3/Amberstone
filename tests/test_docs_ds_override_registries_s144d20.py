"""Guard (RM-995): the override-registry and per-spell CC counts stay true.

Measured 2026-10-27 at patch 16.21.1, ``docs/DAEMON_SLAYER.md`` "Engine
substrate & registries" states two families of counts that were correct but
unguarded:

* the four per-(champion, key) override registries cover "132 distinct
  champions / 167 (champion, registry) entries" (block_index 125,
  max_priority 15, combo_sequences 15, form_index 12), which is "77.2% of the
  171-champion abilities keyspace (76.3% of the full 173 roster)";
* ``_PER_SPELL_CC_DURATIONS`` holds "108 entries / 89 champs".

The doc itself warns the registry counts must come from the nested
``champions`` key (a top-level count returns 2), so this guard counts the same
way. Every figure is re-derived from the data, never from a literal here.
ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_DS = _REPO_ROOT / "agents" / "daemon_slayer"
_REGISTRIES = {
    "block_index": "champion_block_index.json",
    "max_priority": "champion_max_priority.json",
    "combo_sequences": "champion_combo_sequences.json",
    "form_index": "champion_form_index.json",
}


def _doc() -> str:
    return " ".join(_DOC.read_text(encoding="utf-8").split())


def _one(pattern: str, what: str) -> re.Match:
    hits = list(re.finditer(pattern, _doc()))
    assert len(hits) == 1, f"expected exactly one {what} in the DS doc, got {len(hits)}"
    return hits[0]


def _registry_champions() -> dict[str, set[str]]:
    out = {}
    for name, fname in _REGISTRIES.items():
        data = json.loads((_DS / fname).read_text(encoding="utf-8"))
        out[name] = set(data["champions"])
    return out


def _patch_data(fname: str) -> set[str]:
    patch = (_REPO_ROOT / "data" / "daemon_slayer" / "current.txt").read_text(
        encoding="utf-8"
    ).strip()
    path = _REPO_ROOT / "data" / "daemon_slayer" / patch / fname
    return set(json.loads(path.read_text(encoding="utf-8"))["data"])


def _abilities_keyspace() -> set[str]:
    return _patch_data("champion_abilities.json")


def _roster() -> set[str]:
    return _patch_data("champions.json")


def test_doc_registry_totals_match_the_data():
    regs = _registry_champions()
    m = _one(
        r"\*\*(\d+) distinct champions / (\d+) \(champion, registry\) entries\*\*",
        "registry total",
    )
    distinct = set().union(*regs.values())
    assert int(m.group(1)) == len(distinct)
    assert int(m.group(2)) == sum(len(c) for c in regs.values())


def test_doc_per_registry_counts_match_the_data():
    regs = _registry_champions()
    m = _one(
        r"Per registry: block_index (\d+), max_priority (\d+), "
        r"combo_sequences (\d+), form_index (\d+)\.",
        "per-registry breakdown",
    )
    stated = dict(zip(("block_index", "max_priority", "combo_sequences", "form_index"),
                      (int(g) for g in m.groups())))
    assert stated == {k: len(v) for k, v in regs.items()}


def test_every_registry_champion_is_in_the_abilities_keyspace():
    distinct = set().union(*_registry_champions().values())
    assert distinct, "the override registries are empty - the count guards would be vacuous"
    assert distinct <= _abilities_keyspace()


def test_doc_coverage_percentages_match_the_data():
    distinct = set().union(*_registry_champions().values())
    keyspace = _abilities_keyspace()
    roster = len(_roster())
    m = _one(
        r"cover (\d+\.\d)% of the (\d+)-champion abilities keyspace "
        r"\((\d+\.\d)% of the full (\d+) roster\)",
        "coverage percentage",
    )
    assert int(m.group(2)) == len(keyspace)
    assert int(m.group(4)) == roster
    assert m.group(1) == f"{100 * len(distinct) / len(keyspace):.1f}"
    assert m.group(3) == f"{100 * len(distinct) / roster:.1f}"


def test_doc_per_spell_cc_counts_match_the_registry():
    m = _one(
        r"`_PER_SPELL_CC_DURATIONS` registry (\d+) entries / (\d+) champs",
        "per-spell CC count",
    )
    assert int(m.group(1)) == sum(len(v) for v in _PER_SPELL_CC_DURATIONS.values())
    assert int(m.group(2)) == len(_PER_SPELL_CC_DURATIONS)

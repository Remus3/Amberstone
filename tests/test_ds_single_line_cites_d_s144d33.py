"""Guard: four more DS tests cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Each file below carried exactly one
line cite:

- ``test_oq18_route_seam_transport.py`` cited ``antitank.py:639/731`` for
  ``compute_antitank`` / ``compute_antitank_live``; both defs moved down
  (seed rows were added above them), so :639 is now a Yorick / Zac seed row.
- ``test_pet_summon_damage_uncredited_rm97.py`` cited ``abilities.py:274``
  for ``AbilityForm.damage_blocks_only``; it still resolves, but a line cite
  rots on the next edit above it (the three stale cites here are the proof).
- ``test_resist_damage_coupling_rm87.py`` cited
  ``_passive_damage_overrides.py:840-843`` for the K'Sante P All Out Bonus
  documented reject; :840-842 is now the Jhin Whisper row, and the reject
  bullet sits in the GAP-2 CASTER-DEFENSIVE-STAT header comment.
- ``test_roster_key_id_only_contract_rm330.py`` cited ``server.py:398`` for
  ``_resolve_champion_id``; the def is now ~60 lines lower.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import abilities, antitank, server

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
PDO = REPO / "agents" / "daemon_slayer" / "_passive_damage_overrides.py"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

TARGETS = {
    "test_oq18_route_seam_transport.py": (
        "``antitank.compute_antitank``",
        "``antitank.compute_antitank_live``",
    ),
    "test_pet_summon_damage_uncredited_rm97.py": (
        "``abilities.AbilityForm.damage_blocks_only``",
    ),
    "test_resist_damage_coupling_rm87.py": (
        "_passive_damage_overrides",
        "GAP-2 CASTER-DEFENSIVE-STAT",
    ),
    "test_roster_key_id_only_contract_rm330.py": (
        "``server._resolve_champion_id``",
    ),
}


def test_pattern_matches_the_old_shapes():
    for sample in (
        "snapshot, champion, level, item_ids, mode, augments) - antitank.py:639/731.",
        "* ``agents/daemon_slayer/abilities.py:274`` ``AbilityForm.damage_blocks_only``",
        "# _passive_damage_overrides.py:840-843 (bilinear caster-resist * target",
        "``_resolve_champion_id`` (server.py:398), but the ROSTER keys",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``antitank.compute_antitank_live``",
        "``abilities.AbilityForm.damage_blocks_only``",
        "``server._resolve_champion_id``",
    ):
        assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    for symbol in TARGETS[name]:
        assert symbol in text, f"{name}: {symbol}"


def test_antitank_signatures_match_the_oq18_claim():
    plain = list(inspect.signature(antitank.compute_antitank).parameters)
    assert plain[:4] == ["champion", "mode", "stats", "level"]
    live = list(inspect.signature(antitank.compute_antitank_live).parameters)
    assert live[:6] == [
        "snapshot", "champion", "level", "item_ids", "mode", "augments",
    ]


def test_damage_blocks_only_is_the_damage_kind_filter():
    src = inspect.getsource(abilities.AbilityForm.damage_blocks_only)
    assert 'b.attribute_kind == "damage"' in src


def test_ksante_all_out_reject_sits_in_the_gap2_header():
    src = PDO.read_text(encoding="utf-8")
    header = src.index("# GAP-2 CASTER-DEFENSIVE-STAT passives")
    reject = src.index("#   - K'Sante P All Out Bonus", header)
    assert reject < src.index('("Taric", "P", 0): PassiveDamageEntry(', header)
    bullet = src[reject : src.index("#   - Rammus W", reject)]
    assert "bilinear" in bullet
    assert '"All Out" state' in bullet


def test_resolve_champion_id_is_the_tolerant_resolver():
    params = list(inspect.signature(server._resolve_champion_id).parameters)
    assert params == ["snap", "name"]
    src = inspect.getsource(server._resolve_champion_id)
    assert "name.lower()" in src
    assert "c.isalnum()" in src

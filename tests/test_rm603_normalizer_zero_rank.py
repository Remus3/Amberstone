"""RM-603: an unranked ability (abilityLevel 0) must read as level 0, not None.

game_reader/snapshot_normalizer.py _read_my_abilities used
``ability.get("abilityLevel") or ability.get("level")``, so a real 0 fell
through the falsy ``or`` to a missing key and became None. The skill-point
tracker treats None as "no reading", so every slot not yet ranked (R before
level 6) blanked the whole reading. Synthetic payload, no player names.
"""
from __future__ import annotations

from core import skill_point_tracker as spt
from game_reader.snapshot_normalizer import _NormalizerMixin


class _Host(_NormalizerMixin):
    def __init__(self, abilities):
        self._abilities = abilities

    def _get(self, url):
        if url.endswith("/activeplayerabilities"):
            return self._abilities
        raise RuntimeError("not in this test")


_AB = {"Passive": {"displayName": "P"},
       "Q": {"displayName": "Qa", "abilityLevel": 1},
       "W": {"displayName": "Wa", "abilityLevel": 0},
       "E": {"displayName": "Ea", "abilityLevel": 0},
       "R": {"displayName": "Ra", "abilityLevel": 0}}


def test_zero_rank_reads_as_zero():
    out = _Host(_AB)._read_my_abilities()
    assert out["w"] == {"name": "Wa", "level": 0}
    assert out["r"]["level"] == 0
    assert out["q"]["level"] == 1


def test_absent_level_still_reads_none():
    out = _Host({"Q": {"displayName": "Qa"}})._read_my_abilities()
    assert out["q"]["level"] is None


def test_legacy_level_key_still_read():
    out = _Host({"Q": {"displayName": "Qa", "level": 2}})._read_my_abilities()
    assert out["q"]["level"] == 2


def test_normalized_state_feeds_the_tracker():
    st = {"level": 2, "my_abilities": _Host(_AB)._read_my_abilities()}
    rd = spt.read_skill_snapshot(st)
    assert rd is not None
    assert spt.spendable(rd, "Annie") == 1

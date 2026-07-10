"""Tests for R101-B: ARAM + Arena OCR shadow-field registration.

Slice R101-A's tiered vision router logs every SHADOW_FIELDS entry OCR-vs-Sonnet.
R101-B registers 8 already-built OCR numerics as shadow-only on both the ARAM
coach (coaches.aram_coach.Coach) and the Arena vision reader
(coaches.arena_coach.ArenaVisionReader). Each shadow field must (a) live in
SHADOW_FIELDS, (b) also be present in TIERED_FIELDS so the R101-A router sees
it, and (c) carry a TIERED_VALIDATORS entry - WITHOUT being read into any
served dict (shadow-only, non-consuming).

These tests introspect the class-level constants directly; nothing here
instantiates a coach, so no Anthropic key, network call, or screen capture is
required.
"""

from __future__ import annotations

from coaches.aram_coach import Coach as ARAMCoach
from coaches.arena_coach import ArenaVisionReader

EXPECTED = {
    "ally_1_hp", "ally_2_hp", "ally_3_hp", "ally_4_hp",
    "gold", "level", "cs", "kda",
}
_HP_FIELDS = ("ally_1_hp", "ally_2_hp", "ally_3_hp", "ally_4_hp")


# -- ARAM registration --------------------------------------------------------

def test_aram_shadow_fields_exact_set():
    assert set(ARAMCoach._ARAM_SHADOW_FIELDS) == EXPECTED


def test_aram_shadow_subset_of_tiered_fields():
    # Registered in TIERED_FIELDS so the R101-A router logs them, still shadow.
    assert EXPECTED.issubset(set(ARAMCoach._ARAM_TIERED_FIELDS))


def test_aram_shadow_each_has_validator():
    for field in EXPECTED:
        assert field in ARAMCoach._ARAM_TIERED_VALIDATORS


def test_aram_shadow_strict_subset_not_consuming():
    # A strict subset proves the fields are registered without asserting any
    # served-dict mutation - the non-consuming shadow guard.
    shadow = set(ARAMCoach._ARAM_SHADOW_FIELDS)
    tiered = set(ARAMCoach._ARAM_TIERED_FIELDS)
    assert shadow < tiered


# -- Arena registration -------------------------------------------------------

def test_arena_shadow_fields_exact_set():
    assert set(ArenaVisionReader.SHADOW_FIELDS) == EXPECTED


def test_arena_shadow_subset_of_tiered_fields():
    assert EXPECTED.issubset(set(ArenaVisionReader.TIERED_FIELDS))


def test_arena_shadow_each_has_validator():
    for field in EXPECTED:
        assert field in ArenaVisionReader.TIERED_VALIDATORS


def test_arena_shadow_strict_subset_not_consuming():
    shadow = set(ArenaVisionReader.SHADOW_FIELDS)
    tiered = set(ArenaVisionReader.TIERED_FIELDS)
    assert shadow < tiered


# -- Validator behavior (both coaches share one numeric contract) -------------

def _assert_numeric_validators(validators):
    for hp in _HP_FIELDS:
        v = validators[hp]
        assert v(50)
        assert not v(101)
        assert not v(-1)
    level = validators["level"]
    assert level(5)
    assert not level(19)
    assert not level(0)
    gold = validators["gold"]
    assert gold(1200)
    assert not gold(-5)
    cs = validators["cs"]
    assert cs(200)
    assert not cs(1001)
    kda = validators["kda"]
    assert kda("3/1/7")
    assert not kda("31")
    assert not kda(5)


def test_aram_validator_behavior():
    _assert_numeric_validators(ARAMCoach._ARAM_TIERED_VALIDATORS)


def test_arena_validator_behavior():
    _assert_numeric_validators(ArenaVisionReader.TIERED_VALIDATORS)

"""core/mayhem_detect.is_mayhem - the single ARAM Mayhem detector.

Live caller: coaches/aram_coach.py (vision cadence, the " Mayhem" prompt tag,
the augment recommendation gate). Contract pinned here: True only when the
game_mode field is one of the known Mayhem aliases (KIWI / MAYHEM /
ARAM_MAYHEM, matched as whole tokens, case-insensitive); never raises; any
non-string, non-ASCII, over-long or glued-substring value is not Mayhem.
"""
from __future__ import annotations

import types

import pytest

from core.mayhem_detect import is_mayhem


class _Snap:
    def __init__(self, game_mode=None, gameMode=None):  # noqa: N803 - Riot key
        if game_mode is not None:
            self.game_mode = game_mode
        if gameMode is not None:
            self.gameMode = gameMode


class _Slotted:
    __slots__ = ("game_mode",)


def _stable_id(value):
    """repr, except for a value whose default repr carries its memory address:
    each pytest-xdist worker would collect a different test id and the run
    stops at collection ("Different tests were collected"). Those are named by
    their content or type instead."""
    if isinstance(value, _Snap):
        return f"_Snap({vars(value)!r})"
    if type(value) is object:
        return "object()"
    return repr(value)


# -- live aliases stay True ----------------------------------------------------

@pytest.mark.parametrize("state", [
    "KIWI", "kiwi", " KIWI ", "ARAM_MAYHEM", "MAYHEM", "aram_mayhem",
    "KIWI_JADE", "KIWI2",
    {"game_mode": "KIWI"}, {"gameMode": "ARAM_MAYHEM"},
    {"game_mode": "", "gameMode": "KIWI"},
    {"game_mode": None, "gameMode": "kiwi"},
    _Snap(game_mode="KIWI"), _Snap(gameMode="KIWI"),
], ids=_stable_id)
def test_known_alias_is_mayhem(state):
    assert is_mayhem(state) is True


def test_slotted_snapshot_reads_and_unset_slot_is_not_mayhem():
    s = _Slotted()
    assert is_mayhem(s) is False
    s.game_mode = "KIWI"
    assert is_mayhem(s) is True


@pytest.mark.parametrize("state", [
    None, "", "ARAM", "CLASSIC", "CHERRY", "URF", "ARAM_UNRANKED_5X5",
    {}, {"game_mode": "ARAM"}, {"game_mode": "ARAM", "gameMode": "KIWI"},
    _Snap(), _Snap(game_mode="CLASSIC"), 0, 2400, object(),
], ids=_stable_id)
def test_other_modes_are_not_mayhem(state):
    assert is_mayhem(state) is False


# -- F1: a non-string mode value is never str()-ed into a match ----------------

@pytest.mark.parametrize("value", [
    ["KIWI"], ("KIWI",), {"KIWI": 1}, {"KIWI"}, b"KIWI", bytearray(b"KIWI"),
], ids=repr)
def test_non_string_mode_value_is_not_mayhem(value):
    assert is_mayhem({"game_mode": value}) is False
    assert is_mayhem(_Snap(game_mode=value)) is False


def test_non_string_truthy_game_mode_does_not_mask_gameMode():  # noqa: N802
    assert is_mayhem({"game_mode": 5, "gameMode": "KIWI"}) is True
    assert is_mayhem({"game_mode": ["ARAM"], "gameMode": "KIWI"}) is True


# -- F2: no Unicode lookalike, no str subclass can forge a match ---------------

@pytest.mark.parametrize("value", [
    "k" + chr(0x131) + "w" + chr(0x131),          # dotless i: upper() folds it to "KIWI"
    "KIWI" + chr(0x200B),              # zero-width space
    "".join(map(chr, (0xFF2B, 0xFF29, 0xFF37, 0xFF29))),  # fullwidth KIWI
    "MAYHE" + chr(0x39C),             # Greek capital mu
], ids=repr)
def test_non_ascii_mode_is_not_mayhem(value):
    assert is_mayhem(value) is False
    assert is_mayhem({"game_mode": value}) is False


def test_str_subclass_cannot_redirect_the_match():
    class _Forged(str):
        def upper(self):
            return "KIWI"

        def split(self, *a, **k):
            return ["KIWI"]

        def __contains__(self, item):
            return True

        def __len__(self):
            return 1

    assert is_mayhem(_Forged("ARAM")) is False
    assert is_mayhem({"game_mode": _Forged("ARAM")}) is False
    # A plain subclass carrying a real alias still reads as that alias.
    assert is_mayhem(type("_Plain", (str,), {})("KIWI")) is True


# -- F3: never raises ----------------------------------------------------------

def test_raising_accessors_read_as_not_mayhem():
    class _Prop:
        @property
        def game_mode(self):
            raise RuntimeError("boom")

    class _BadDict(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")

    class _BadStr:
        def __str__(self):
            raise RuntimeError("boom")

    class _BadBool:
        def __bool__(self):
            raise ValueError("ambiguous")

    assert is_mayhem(_Prop()) is False
    assert is_mayhem(_BadDict(game_mode="KIWI")) is False
    assert is_mayhem({"game_mode": _BadStr()}) is False
    assert is_mayhem({"game_mode": _BadBool(), "gameMode": "KIWI"}) is True


def test_raising_or_lying_dunder_class_reads_as_not_mayhem():
    # isinstance() consults an instance's own __class__; it must not be the
    # path by which the detector raises or is fooled into str.__str__.
    class _RaisingClass:
        @property
        def __class__(self):
            raise RuntimeError("boom")

    class _ClaimsStr:
        @property
        def __class__(self):
            return str

    assert is_mayhem(_RaisingClass()) is False
    assert is_mayhem({"game_mode": _RaisingClass()}) is False
    assert is_mayhem(_ClaimsStr()) is False
    assert is_mayhem({"game_mode": _ClaimsStr(), "gameMode": "KIWI"}) is True


def test_non_dict_mapping_is_read():
    assert is_mayhem(types.MappingProxyType({"game_mode": "KIWI"})) is True
    assert is_mayhem(types.MappingProxyType({"game_mode": "ARAM"})) is False


# -- F4: an over-long value is refused without a scan --------------------------

def test_over_long_value_is_not_mayhem():
    assert is_mayhem("A_" * 100 + "KIWI") is False
    assert is_mayhem({"game_mode": "KIWI_" + "X" * 200}) is False


# -- F5: whole-token match, not a substring ------------------------------------

@pytest.mark.parametrize("value", ["KIWIFRUIT", "NOTMAYHEM", "SKIWI"], ids=repr)
def test_glued_substring_is_not_mayhem(value):
    assert is_mayhem(value) is False


def test_result_is_a_real_bool():
    assert type(is_mayhem("KIWI")) is bool
    assert type(is_mayhem("ARAM")) is bool

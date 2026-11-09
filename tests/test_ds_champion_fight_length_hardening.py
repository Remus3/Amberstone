"""Hardening pins for core.ds_champion_fight_length (true-audit s144 cycle 186).

The resolver sits at the carry chokepoint of
core.daemon_slayer_client.rank_for_primary_archetype: a non-None answer engages
the burst fight_length blend AND swaps the caller's enemy target for the
squishy-carry stat line, so a false match re-ranks a whole build and a raise
escapes the fail-soft :8860 client.

- S144-T-565: a non-str champion (int key, bytes, float, any object) raised
  AttributeError out of ``_norm``; it now resolves to None (default ranking).
- S144-T-566: a non-ASCII spelling folded onto a calibrated ASCII key
  ("JINX" spelt with U+0130, a combining accent, a zero-width space); every key and
  every DDragon id is ASCII, so any non-ASCII name is now unmapped.
- S144-T-567: an over-long name was scanned char by char on every carry call;
  a name past _MAX_NAME_LEN now resolves to None without a scan.
- S144-T-568: the allow-map was a mutable module dict; it is now read-only.
"""
from __future__ import annotations

import math

import pytest

from core import ds_champion_fight_length as fl
from core.ds_champion_fight_length import _CHAMPION_FIGHT_LENGTH, champion_fight_length


class _Weird:
    def lower(self):  # a duck-typed str stand-in must not be trusted
        return "jhin"


@pytest.mark.parametrize(
    "champ",
    [202, 202.0, b"Jhin", bytearray(b"Jhin"), ["Jhin"], ("jhin",), _Weird(), object(), True],
)
def test_non_str_champion_resolves_none_never_raises(champ) -> None:
    assert champion_fight_length(champ) is None


@pytest.mark.parametrize("champ", [None, 0, "", "   ", "'", "&."])
def test_empty_or_falsy_resolves_none(champ) -> None:
    assert champion_fight_length(champ) is None


@pytest.mark.parametrize(
    "champ",
    [
        "J" + chr(0x130) + "NX",              # dotted capital I lowers to i + U+0307
        "JH" + chr(0x130) + "N",
        "Jhi" + chr(0x301) + "n",             # combining acute accent
        "Jhin" + chr(0x200B),                 # zero-width space
        # The two below were already unmapped; pinned as characterization.
        "".join(chr(0xFF00 + ord(c) - 0x20) for c in "Jhin"),  # fullwidth
        "Dr" + chr(0x430) + "ven",            # Cyrillic a
    ],
)
def test_non_ascii_spelling_is_unmapped(champ) -> None:
    assert champion_fight_length(champ) is None


def test_overlong_name_is_unmapped() -> None:
    assert fl._MAX_NAME_LEN >= 32
    pad = " " * (fl._MAX_NAME_LEN + 1 - len("Jhin"))
    assert len("Jhin" + pad) == fl._MAX_NAME_LEN + 1
    assert champion_fight_length("Jhin" + pad) is None
    # At the cap it still resolves (spaces fold away).
    assert champion_fight_length("Jhin" + pad[:-1]) == 0.5


@pytest.mark.parametrize(
    "champ,want",
    [
        ("Jhin", 0.5), (" jhin ", 0.5), ("J.H.I.N", 0.5), ("Draven", 0.3),
        ("samira", 0.3), ("TWITCH", 0.5), ("Caitlyn", 0.5), ("jinx", 0.5),
        ("Kai'Sa", None), ("Nunu & Willump", None), ("Ashe", None),
    ],
)
def test_ascii_display_and_ddragon_spellings_unchanged(champ, want) -> None:
    assert champion_fight_length(champ) == want


def test_str_subclass_resolves_like_its_value() -> None:
    class Name(str):
        __slots__ = ()

        def lower(self):  # an override must not redirect the lookup
            return "draven"  # 0.3: distinct from both expected answers

    assert champion_fight_length(Name("Jhin")) == 0.5
    assert champion_fight_length(Name("Ashe")) is None


def test_allow_map_is_read_only() -> None:
    with pytest.raises(TypeError):
        _CHAMPION_FIGHT_LENGTH["ashe"] = 0.5  # type: ignore[index]
    with pytest.raises((TypeError, AttributeError)):
        _CHAMPION_FIGHT_LENGTH.pop("jhin")  # type: ignore[attr-defined]
    assert champion_fight_length("Ashe") is None
    assert champion_fight_length("Jhin") == 0.5


def test_allow_map_values_are_in_the_validated_band() -> None:
    # Module docstring: every engaged FL was validated inside [0.3, 0.75].
    assert _CHAMPION_FIGHT_LENGTH
    for key, value in _CHAMPION_FIGHT_LENGTH.items():
        assert key == key.lower() and key.isascii() and key.isalnum(), key
        assert type(value) is float and math.isfinite(value), key
        assert 0.3 <= value <= 0.75, key

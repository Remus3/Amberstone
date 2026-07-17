"""Slice A (2026-07-16 AP-axis sweep) - AP burst-assassin classification.

DDragon tags + the P6 axis correction collapse AP-kit assassins to `mage`
(the sustained ds.ability scorer, Liandry's-DoT), because axis_correct_archetype
tags the assassin archetype as AD-only. But ds.burst flows AP amplification
(burst.py: a Diana / Akali build registers their AP amp), so these short-window
burst assassins belong on it. This pins the curated override that routes them to
`assassin`, plus the controls that must NOT move.
"""
from __future__ import annotations

import pytest

from core import archetype_picks as ap


@pytest.fixture(autouse=True)
def _fresh_caches():
    ap._invalidate_axis_cache()
    ap._invalidate_picks_cache()
    yield
    ap._invalidate_axis_cache()
    ap._invalidate_picks_cache()


AP_ASSASSINS = ["Akali", "Ekko", "Evelynn", "Fizz", "Katarina", "LeBlanc", "Diana"]


@pytest.mark.parametrize("champ", AP_ASSASSINS)
def test_ap_assassin_defaults_to_assassin(champ, monkeypatch):
    monkeypatch.setattr(ap, "_load_picks", lambda: {})
    primary, secondary = ap.default_for_champion(champ)
    assert primary == "assassin", f"{champ} should route to the burst scorer"
    assert secondary == "mage"


@pytest.mark.parametrize("champ", AP_ASSASSINS)
def test_ap_assassin_get_archetype_for_primary(champ, monkeypatch):
    monkeypatch.setattr(ap, "_load_picks", lambda: {})
    info = ap.get_archetype_for(champ)
    assert info["primary"] == "assassin"
    assert info["source"] == "default"


# Controls: the override must NOT pull these onto the burst scorer.
@pytest.mark.parametrize("champ,expected", [
    ("Qiyana", "assassin"),    # AD assassin - already burst, unchanged
    ("Zed", "assassin"),       # AD assassin - unchanged
    ("Syndra", "mage"),        # ranged sustained mage - stays mage
    ("Cassiopeia", "mage"),    # DoT mage - stays mage
    ("Pyke", "assassin"),      # AD kit via enchanter->assassin correction - unchanged
    ("Gwen", "onhit"),         # on-hit AP - Slice B Task 10 now owns it (ds.onhit)
    ("Kayle", "onhit"),        # on-hit AP - Slice B Task 10 now owns it (ds.onhit)
    ("Kassadin", "mage"),      # EXCLUDED: scaling mana-assassin, default already Rabadon's-led
])
def test_controls_unchanged(champ, expected, monkeypatch):
    monkeypatch.setattr(ap, "_load_picks", lambda: {})
    assert ap.default_for_champion(champ)[0] == expected


def test_operator_pick_still_wins(monkeypatch):
    # An explicit mage pick on Akali must not be overridden by the AP-assassin set.
    monkeypatch.setattr(ap, "_load_picks", lambda: {
        "Akali": {"champion": "Akali", "primary": "mage",
                  "secondary": "assassin", "source": ap.SOURCE_USER_CS},
    })
    info = ap.get_archetype_for("Akali")
    assert info["primary"] == "mage"
    assert info["source"] == ap.SOURCE_USER_CS

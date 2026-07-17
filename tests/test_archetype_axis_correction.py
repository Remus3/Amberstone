"""P6 lolmath build-engine parity - kit-damage-axis archetype correction.

DDragon class tags encode role, not the AD-vs-AP axis a kit scales on, so the
tag default sent AP kits (Gwen, Teemo) to AD scorers and an AD assassin (Pyke)
to the AP enchanter scorer - the DS build engine then built the wrong damage
axis. ``core.archetype_picks`` now re-bases the DEFAULT archetype against the
kit's ``lolmath.damage_distribution`` (the ground-truth axis), below an explicit
operator pick. These are per-champion characterization assertions for the fix.
"""
from __future__ import annotations

import pytest

from core import archetype_picks as ap


@pytest.fixture(autouse=True)
def _fresh_caches():
    # Defaults read the patch champions.json + the persisted picks; start each
    # test from a clean cache so prior tests cannot leak state.
    ap._invalidate_axis_cache()
    ap._invalidate_picks_cache()
    yield
    ap._invalidate_axis_cache()
    ap._invalidate_picks_cache()


# Champions whose tag default was on the WRONG damage axis and must re-base to
# `mage`. The AP burst-assassins (Akali/Ekko/Evelynn/Fizz/Katarina/Leblanc/Diana)
# used to appear here as "mage" too, but they are now routed to the ds.burst
# scorer by the curated _AP_ASSASSIN_IDS override (the ds.burst scorer flows AP
# amp - it is NOT AD-only). Their classification is covered by
# tests/test_ap_assassin_override.py. Kassadin stays mage (excluded from the
# override); Pyke is an AD kit corrected off the AP enchanter scorer. Gwen and
# KogMaw used to appear here too, but Slice B (Task 10, 2026-07-16) now routes
# the on-hit-AP roster to the ds.onhit scorer, layered on top of this axis
# correction; their classification is covered by tests/test_onhit_ap_routing.py.
EXPECTED_FLIPS = {
    "Teemo": "mage", "Rumble": "mage",
    "Mordekaiser": "mage", "Nidalee": "mage", "Elise": "mage",
    "Gragas": "mage", "Lillia": "mage", "Kassadin": "mage",
    "Pyke": "assassin",
}

# Champions that must NOT change: aligned damage archetypes, an axis-neutral
# tank (AP-dealing Malphite still wants durability, not a glass AP pivot), and
# the lolmath quirks where the KIT axis already agrees with DS (XinZhao AD,
# Taric AP) - we align to the kit, not to lolmath.
EXPECTED_KEEPS = {
    "Garen": "bruiser",    # AD kit, AD archetype - aligned
    "Annie": "mage",       # AP kit, AP archetype - aligned
    "Caitlyn": "carry",    # AD kit, AD archetype - aligned
    "Malphite": "tank",    # AP kit but tank is axis-neutral - never corrected
    "Taric": "enchanter",  # AP kit, AP archetype - aligned (lolmath builds AD)
    "XinZhao": "bruiser",  # AD kit, AD archetype - aligned (lolmath builds AP)
}


@pytest.mark.parametrize("champ,expected", sorted(EXPECTED_FLIPS.items()))
def test_default_archetype_rebased_to_kit_axis(champ, expected, monkeypatch):
    # Hermetic: this guards the DEFAULT kit-axis rebasing, so isolate from the
    # live data/cs_archetype_picks.json - an operator may have since picked one
    # of these champs in champ-select (a user_cs pick sets source != "default"
    # and legitimately overrides the kit axis). The pick-wins path is covered by
    # test_operator_pick_overrides_axis_correction below.
    monkeypatch.setattr(ap, "_load_picks", lambda: {})
    info = ap.get_archetype_for(champ)
    assert info["source"] == "default", f"{champ} should have no operator pick"
    assert info["primary"] == expected, (
        f"{champ}: kit axis={ap.kit_damage_axis(champ)} -> expected {expected}, "
        f"got {info['primary']}"
    )


@pytest.mark.parametrize("champ,expected", sorted(EXPECTED_KEEPS.items()))
def test_aligned_or_neutral_archetype_unchanged(champ, expected, monkeypatch):
    # Hermetic: same reason as above - guard the default, not the live pick file.
    monkeypatch.setattr(ap, "_load_picks", lambda: {})
    assert ap.get_archetype_for(champ)["primary"] == expected


def test_kit_damage_axis_known_champions():
    assert ap.kit_damage_axis("Gwen") == "ap"
    assert ap.kit_damage_axis("Pyke") == "ad"
    assert ap.kit_damage_axis("Garen") == "ad"
    assert ap.kit_damage_axis("Malphite") == "ap"


def test_axis_from_distribution_thresholds():
    assert ap._axis_from_distribution({"magical": 0.70, "physical": 0.13}) == "ap"
    assert ap._axis_from_distribution({"magical": 0.06, "physical": 0.76}) == "ad"
    # genuine hybrid - neither gate cleared, no flip
    assert ap._axis_from_distribution({"magical": 0.50, "physical": 0.45}) is None
    # dominant but margin too thin
    assert ap._axis_from_distribution({"magical": 0.56, "physical": 0.44}) is None
    assert ap._axis_from_distribution({}) is None


def test_axis_correct_archetype_logic():
    # AP kit on an AD archetype -> mage
    assert ap.axis_correct_archetype("Gwen", "bruiser", ["Fighter"]) == "mage"
    # AD kit on the AP enchanter -> prefer the AD secondary class tag (assassin)
    assert ap.axis_correct_archetype("Pyke", "enchanter",
                                     ["Support", "Assassin"]) == "assassin"
    # already aligned -> unchanged
    assert ap.axis_correct_archetype("Annie", "mage", ["Mage"]) == "mage"
    # tank is axis-neutral -> never corrected even on an AP kit
    assert ap.axis_correct_archetype("Malphite", "tank", ["Tank"]) == "tank"


def test_flip_surfaces_role_archetype_as_secondary():
    # The corrected champ keeps its tag-based archetype as the alt-view so the
    # operator can flip back in one tap. Teemo, not Gwen - Slice B (Task 10) now
    # layers a further onhit-roster override on Gwen (see
    # tests/test_onhit_ap_routing.py::test_routes_to_onhit).
    primary, secondary = ap.default_for_champion("Teemo")
    assert primary == "mage"
    assert secondary == "carry"


def test_operator_pick_overrides_axis_correction(monkeypatch):
    # An explicit operator pick wins over the kit-axis re-base.
    monkeypatch.setattr(ap, "_load_picks", lambda: {
        "Gwen": {"champion": "Gwen", "primary": "bruiser",
                 "secondary": "tank", "source": "user_cs"},
    })
    info = ap.get_archetype_for("Gwen")
    assert info["primary"] == "bruiser"
    assert info["source"] == "user_cs"

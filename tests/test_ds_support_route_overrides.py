# arch: Slice C support-tag route-override tests (RM-84) | section=tests | frozen=no
"""RM-84 - Support-tag archetype misroute.

``tag_to_archetype("Support") == "enchanter"``, so every champion whose FIRST
DDragon tag is Support routes to ``ds.hps``. ``axis_correct_archetype`` only
resolves AD-vs-AP conflicts, so it rescues the AD cases (Pyke, Senna) and is
structurally blind to an AP-vs-AP misroute (Morgana) or an axis-neutral one
(Thresh / Rakan / Taric / Bard).

The engine anchor these tests defend: the build target is the optimal ultimate
build, and it must NEVER offer an item a champion would never build. The
enchanter route hands all of them Echoes of Helia > Ardent Censer > Staff of
Flowing Water, which have a ~0% real pick rate for the overridden champions at
every build depth in every role.

Per Engine/Build Conventions these are PER-CHAMPION assertions - a single
generic shape is not an acceptable validation for a route fix.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.archetype_picks import default_for_champion
from core.ds_support_route_overrides import (
    _flatten,
    load_support_route_overrides,
)

_ROSTER = Path(__file__).resolve().parent.parent / "core" / "ds_support_route_overrides.json"

# (champion, expected_primary) - adjudicated individually against live 16.14
# Emerald+ pick-rate data. See the JSON's per-champion ``evidence`` field.
_OVERRIDDEN = [
    ("Morgana", "mage"),
    ("Thresh", "tank"),
    ("Rakan", "tank"),
    ("Taric", "tank"),
    ("Bard", "tank"),
]

# Support-tag champions whose enchanter route is CORRECT (real builds are
# heal/shield throughput). These must be untouched by the override.
_CORRECT_ENCHANTERS = ["Nami", "Soraka", "Janna", "Lulu", "Milio", "Yuumi", "Sona", "Ivern", "Seraphine"]

# Adjudicated and deliberately HELD - no current scorer expresses these kits,
# so flipping them would swap one anchor violation for another.
_HELD = ["Renata Glasc", "Zilean"]


@pytest.mark.parametrize("champ,expected", _OVERRIDDEN)
def test_overridden_champion_routes_to_target_scorer(champ: str, expected: str) -> None:
    primary, _secondary = default_for_champion(champ)
    assert primary == expected, f"{champ} should route to {expected}, got {primary}"


@pytest.mark.parametrize("champ,_expected", _OVERRIDDEN)
def test_overridden_champion_keeps_enchanter_as_alt_view(champ: str, _expected: str) -> None:
    # The operator can still flip back in one tap; the demoted route stays visible.
    _primary, secondary = default_for_champion(champ)
    assert secondary == "enchanter"


@pytest.mark.parametrize("champ", _CORRECT_ENCHANTERS)
def test_correct_enchanters_are_not_touched(champ: str) -> None:
    primary, _ = default_for_champion(champ)
    assert primary == "enchanter", f"{champ} is a real enchanter and must not be re-routed"


@pytest.mark.parametrize("champ", _HELD)
def test_held_champions_are_absent_from_the_roster(champ: str) -> None:
    assert champ not in load_support_route_overrides()


def test_ad_support_tags_still_fixed_by_axis_correction_not_this_roster() -> None:
    # Pre-existing behavior, asserted so a future roster edit cannot silently
    # take ownership of the AD cases (or regress them).
    roster = load_support_route_overrides()
    assert default_for_champion("Pyke")[0] == "assassin"
    assert default_for_champion("Senna")[0] == "carry"
    assert "Pyke" not in roster and "Senna" not in roster


def test_renata_alias_keys_all_resolve_consistently() -> None:
    # "Renata" / "RenataGlasc" / "Renata Glasc" all resolve through the tag map;
    # a partial override would make the route depend on which spelling a caller
    # happened to use.
    routes = {default_for_champion(k)[0] for k in ("Renata", "RenataGlasc", "Renata Glasc")}
    assert len(routes) == 1, f"Renata alias keys disagree: {routes}"


# --- loader contract ------------------------------------------------------


def test_roster_json_is_ascii_and_parses() -> None:
    raw = _ROSTER.read_bytes()
    assert raw.decode("ascii")  # repo hard rule: 7-bit ASCII authored content
    doc = json.loads(raw.decode("ascii"))
    assert set(_ROSTER_CHAMPS(doc)) == {c for c, _ in _OVERRIDDEN}


def _ROSTER_CHAMPS(doc: dict) -> list:
    return list(doc.get("champions", {}))


def test_flatten_skips_malformed_entries_without_raising() -> None:
    out = _flatten(
        {
            "champions": {
                "Good": {"primary": "tank", "secondary": "enchanter"},
                "NoPrimary": {"secondary": "enchanter"},
                "BadPrimary": {"primary": "wizard", "secondary": "enchanter"},
                "NotADict": "tank",
            }
        }
    )
    assert out == {"Good": ("tank", "enchanter")}


@pytest.mark.parametrize("bad", [{}, {"champions": None}, {"champions": []}, None])
def test_flatten_fail_soft_on_garbage(bad) -> None:
    assert _flatten(bad) == {}


def test_missing_secondary_defaults_to_enchanter() -> None:
    out = _flatten({"champions": {"X": {"primary": "mage"}}})
    assert out == {"X": ("mage", "enchanter")}

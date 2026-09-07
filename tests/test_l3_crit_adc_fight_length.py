"""L3 regression: crit-ADC per-champ fight_length allow-map + live engagement.

docs/specs/2026-07-13-ds-crit-burst-fix.md lever L3 adds five crit-burst
marksmen to core.ds_champion_fight_length._CHAMPION_FIGHT_LENGTH so the carry
chokepoint (core.daemon_slayer_client.rank_for_primary_archetype) threads a
SHORT fight_length into rank_for + the L1 coherence_rerank, surfacing the
crit-burst core (Infinity Edge etc.) the sustained ds.dps scorer buries.

RED-first: before L3 every champ here was ABSENT from the allow-map ->
champion_fight_length(champ) is None -> the ``== <FL>`` assertions fail and the
carry branch emits NO fight_length. GREEN once L3 lands the five entries.

The engine-side VALUE proof (a short fight_length lifts Infinity Edge into the
top-4 + demotes BORK off #1, in-process sweep at the live tanky target, levels
13 + 16) is recorded in the module docstring of core.ds_champion_fight_length.
This file pins the allow-map contract + the client-side live-path engagement -
the half that needs core imports, so it lives in tests/ next to
test_jhin_fight_length_wiring.py, keeping the DS engine package core-free.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import pytest

from core import daemon_slayer_client as dsc
from core.ds_champion_fight_length import champion_fight_length

# L3 crit-burst marksmen -> chosen fight_length (see the module docstring + spec).
# draven/samira: pure burst -> the 0.3 floor. twitch/caitlyn/jinx: retain a
# sustained component -> the calibrated Jhin-pilot 0.5 (identical lift to 0.3).
_L3_FIGHT_LENGTH = {
    "Draven": 0.3,
    "Samira": 0.3,
    "Twitch": 0.5,
    "Caitlyn": 0.5,
    "Jinx": 0.5,
}
# Genuinely-sustained marksmen L3 did NOT add -> stay None (byte-identical carry).
_SUSTAINED_CONTROLS = ["Ashe", "KogMaw", "Aphelios"]


# --------------------------------------------------------------------------- #
# 1. allow-map resolution: case/format-insensitive, Jhin preserved, controls None
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("champ,fl", sorted(_L3_FIGHT_LENGTH.items()))
def test_crit_adc_resolves_to_chosen_fl(champ, fl) -> None:
    assert champion_fight_length(champ) == fl
    # Case/format-insensitive: display id, upper, and lower resolve identically.
    assert champion_fight_length(champ.lower()) == fl
    assert champion_fight_length(champ.upper()) == fl


def test_twitch_case_insensitive_explicit() -> None:
    # Spec-named explicit case: "Twitch" / "twitch" both resolve to 0.5.
    assert champion_fight_length("Twitch") == 0.5
    assert champion_fight_length("twitch") == 0.5


def test_jhin_pilot_unchanged() -> None:
    # L3 must not disturb the Jhin pilot value.
    assert champion_fight_length("Jhin") == 0.5


def test_per_champ_fl_split() -> None:
    # draven/samira at the 0.3 burst floor; twitch/caitlyn/jinx at 0.5.
    assert champion_fight_length("Draven") == 0.3
    assert champion_fight_length("Samira") == 0.3
    assert champion_fight_length("Twitch") == 0.5
    assert champion_fight_length("Caitlyn") == 0.5
    assert champion_fight_length("Jinx") == 0.5


@pytest.mark.parametrize("champ", _SUSTAINED_CONTROLS)
def test_sustained_controls_still_none(champ) -> None:
    # Genuinely-sustained marksmen must remain unmapped (byte-identical carry).
    assert champion_fight_length(champ) is None


# --------------------------------------------------------------------------- #
# 2. live-path engagement: the carry chokepoint emits the champ's fight_length
#    into the POST /rank body (proves L3 flows through rank_for_primary_archetype,
#    not just the dict). Mirrors tests/test_jhin_fight_length_wiring.py.
# --------------------------------------------------------------------------- #
@pytest.fixture
def capture_body(monkeypatch):
    """Intercept _post_json, capturing the request body; canned empty ranking."""
    captured: dict = {}

    def _fake_post(path, body, timeout=dsc.DEFAULT_TIMEOUT):
        captured["path"] = path
        captured["body"] = dict(body)
        return {"ranked": []}

    monkeypatch.setattr(dsc, "_post_json", _fake_post)
    return captured


@pytest.mark.parametrize("champ,fl", sorted(_L3_FIGHT_LENGTH.items()))
def test_carry_branch_emits_fight_length_for_crit_adc(capture_body, champ, fl) -> None:
    out = dsc.rank_for_primary_archetype(
        champ, "carry", level=13, item_ids=[], mode="SR", target_armor=80.0,
    )
    assert out is not None and out["scorer"] == "dps"
    assert capture_body["path"] == "/rank"
    assert capture_body["body"].get("fight_length") == fl, (
        f"{champ} carry request must carry fight_length={fl}"
    )


@pytest.mark.parametrize("champ", _SUSTAINED_CONTROLS)
def test_carry_branch_omits_fight_length_for_sustained(capture_body, champ) -> None:
    out = dsc.rank_for_primary_archetype(
        champ, "carry", level=13, item_ids=[], mode="SR", target_armor=80.0,
    )
    assert out is not None and out["scorer"] == "dps"
    assert "fight_length" not in capture_body["body"], (
        f"{champ} (genuinely sustained) must not carry fight_length"
    )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))

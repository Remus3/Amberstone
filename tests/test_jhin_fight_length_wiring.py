"""RED-first: client-side wiring for the Jhin per-champ fight_length blend.

Core half (needs core imports, so it lives in tests/ not the mirrored DS test
dir). Proves:

  1. The champion -> fight_length allow-map has EXACTLY the intended entry
     (Jhin -> 0.5), resolves case/format-insensitively, and returns None for
     every control champ + a numeric key.
  2. rank_for() forwards a ``fight_length`` into the POST /rank body only when
     set (omitted -> byte-identical request).
  3. rank_for_primary_archetype()'s carry branch consults the allow-map: a Jhin
     dispatch emits fight_length=0.5 in the body; a CONTROL champ dispatch
     (Jinx/Ashe/Caitlyn/Kog'Maw/Twitch/Aphelios) emits NO fight_length -> their
     carry ranking request is byte-identical to the pre-calibration path.

The engine-side value proof (0.5 surfaces the lethality core) lives in
agents/daemon_slayer/tests/test_jhin_fight_length.py.
"""
from __future__ import annotations

import pytest

from core import daemon_slayer_client as dsc
from core.ds_champion_fight_length import (
    _CHAMPION_FIGHT_LENGTH,
    champion_fight_length,
)

_CONTROLS = ["Jinx", "Ashe", "Caitlyn", "KogMaw", "Twitch", "Aphelios"]


# --------------------------------------------------------------------------- #
# 1. allow-map resolver
# --------------------------------------------------------------------------- #
def test_allow_map_has_exactly_jhin() -> None:
    assert set(_CHAMPION_FIGHT_LENGTH) == {"jhin"}
    assert len(_CHAMPION_FIGHT_LENGTH) == 1
    assert _CHAMPION_FIGHT_LENGTH["jhin"] == 0.5


def test_jhin_resolves_case_insensitive() -> None:
    assert champion_fight_length("Jhin") == 0.5
    assert champion_fight_length("JHIN") == 0.5
    assert champion_fight_length("jhin") == 0.5


def test_controls_and_junk_resolve_none() -> None:
    for champ in _CONTROLS:
        assert champion_fight_length(champ) is None, f"{champ} must be unmapped"
    assert champion_fight_length("202") is None  # numeric key must not match
    assert champion_fight_length("") is None
    assert champion_fight_length("Aatrox") is None


# --------------------------------------------------------------------------- #
# 2 + 3. client body emission + carry-branch allow-map consult
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


def test_rank_for_emits_fight_length_when_set(capture_body) -> None:
    dsc.rank_for("Jhin", level=13, item_ids=[], mode="SR", fight_length=0.5)
    assert capture_body["path"] == "/rank"
    assert capture_body["body"].get("fight_length") == 0.5


def test_rank_for_omits_fight_length_when_none(capture_body) -> None:
    dsc.rank_for("Jhin", level=13, item_ids=[], mode="SR")
    assert "fight_length" not in capture_body["body"]


def test_carry_branch_applies_allow_map_for_jhin(capture_body) -> None:
    out = dsc.rank_for_primary_archetype(
        "Jhin", "carry", level=13, item_ids=[], mode="SR", target_armor=80.0,
    )
    assert out is not None and out["scorer"] == "dps"
    assert capture_body["body"].get("fight_length") == 0.5


@pytest.mark.parametrize("champ", _CONTROLS)
def test_carry_branch_omits_fight_length_for_controls(capture_body, champ) -> None:
    # A control champ is absent from the allow-map -> the carry request carries
    # NO fight_length -> byte-identical to the pre-calibration ranking request.
    out = dsc.rank_for_primary_archetype(
        champ, "carry", level=13, item_ids=[], mode="SR", target_armor=80.0,
    )
    assert out is not None and out["scorer"] == "dps"
    assert "fight_length" not in capture_body["body"], (
        f"{champ} carry request must not carry fight_length"
    )

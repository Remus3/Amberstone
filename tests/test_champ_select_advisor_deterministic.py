"""Tests for core.champ_select_advisor_deterministic - the deterministic
champ-select pick-advisor (Haiku-elimination Tier-2 candidate, no LLM)."""
from __future__ import annotations

from pathlib import Path

import core.champ_select_advisor_deterministic as adv
from core.champ_select_advisor_deterministic import (
    _SUMMONER_BY_ARCH,
    _summoners,
    _watchout,
    advise_pick,
)

_ADVICE_KEYS = {"advice", "swap", "summoners", "watchout"}


def test_empty_on_no_state():
    assert advise_pick(None) == {"advice": "", "swap": "", "summoners": "", "watchout": ""}
    assert advise_pick({}) == {"advice": "", "swap": "", "summoners": "", "watchout": ""}
    assert advise_pick({"my_team": ["Ashe"]})["advice"] == ""  # no my_champion


def test_shape_keys_and_str_types():
    out = advise_pick({"my_champion": "Ahri", "their_team": ["Zed", "Caitlyn"]})
    assert set(out) == _ADVICE_KEYS
    for v in out.values():
        assert isinstance(v, str)


def test_no_anthropic_dependency():
    # The whole point is ZERO live-LLM cost: the module must not import anthropic
    # or invoke the client (the word may appear in the docstring rationale).
    src = Path(adv.__file__).read_text(encoding="utf-8")
    low = src.lower()
    assert "import anthropic" not in low
    assert "anthropic." not in low
    assert "messages.create" not in low


def test_summoner_map_covers_all_six_archetypes():
    assert set(_SUMMONER_BY_ARCH) == {
        "carry", "mage", "assassin", "bruiser", "tank", "enchanter"}
    # Aggressive classes take Ignite; sustained/utility take Heal; mage Barrier.
    assert _SUMMONER_BY_ARCH["assassin"] == "Flash + Ignite"
    assert _SUMMONER_BY_ARCH["bruiser"] == "Flash + Ignite"
    assert _SUMMONER_BY_ARCH["tank"] == "Flash + Ignite"
    assert _SUMMONER_BY_ARCH["mage"] == "Flash + Barrier"
    assert _SUMMONER_BY_ARCH["carry"] == "Flash + Heal"
    assert _SUMMONER_BY_ARCH["enchanter"] == "Flash + Heal"


def test_summoners_unknown_champ_falls_back_to_heal():
    # An unresolvable name yields no archetype -> the safe default.
    assert _summoners("ZzzNotAChamp") == "Flash + Heal"


def test_summoners_is_one_of_known_set():
    out = advise_pick({"my_champion": "Ahri"})
    assert out["summoners"] in set(_SUMMONER_BY_ARCH.values())


def test_watchout_empty_with_no_enemies():
    assert _watchout([]) == ""
    assert advise_pick({"my_champion": "Ahri", "their_team": []})["watchout"] == ""


def test_watchout_names_an_enemy():
    # Even with no tag data, the first named enemy is surfaced.
    w = _watchout(["SomeEnemyName"])
    assert w.startswith("Watch ") and "SomeEnemyName" in w


def test_aram_swap_surfaced_from_comp_verdict(monkeypatch):
    # advise_pick must reuse the trusted ARAM comp verdict: when it recommends a
    # swap, the advisor surfaces swap_to in BOTH the swap field and the headline.
    import core.aram_comp_verdict as acv
    monkeypatch.setattr(acv, "comp_verdict", lambda state: {
        "ok": True, "recommendation": "swap", "swap_to": "Ashe",
        "variant_to": "", "reason": "No frontline - swap to Ashe to soak.",
        "confidence": "high", "factors": {},
    })
    out = advise_pick({"my_champion": "Brand", "is_aram": True,
                       "my_team": ["Brand", "Zed", "Lux"], "bench": ["Ashe"]})
    assert out["swap"] == "Ashe"
    assert "Ashe" in out["advice"]


def test_aram_variant_keeps_champ_no_swap(monkeypatch):
    import core.aram_comp_verdict as acv
    monkeypatch.setattr(acv, "comp_verdict", lambda state: {
        "ok": True, "recommendation": "variant", "swap_to": "",
        "variant_to": "ap", "reason": "All-AD comp - the AP variant adds magic.",
        "confidence": "medium", "factors": {},
    })
    out = advise_pick({"my_champion": "Kayle", "is_aram": True,
                       "my_team": ["Kayle", "Zed", "Talon"]})
    assert out["swap"] == ""
    assert "Kayle" in out["advice"]


def test_sr_never_swaps():
    out = advise_pick({"my_champion": "Ahri", "is_aram": False,
                       "my_team": ["Ahri", "Zed", "Lux"],
                       "their_team": ["Caitlyn", "Leona", "Garen"]})
    assert out["swap"] == ""
    assert out["advice"].startswith("Stay Ahri")


def test_advice_is_clipped_to_100_chars(monkeypatch):
    import core.aram_comp_verdict as acv
    monkeypatch.setattr(acv, "comp_verdict", lambda state: {
        "ok": True, "recommendation": "swap", "swap_to": "Ashe",
        "variant_to": "", "reason": "x" * 400, "confidence": "high", "factors": {},
    })
    out = advise_pick({"my_champion": "Brand", "is_aram": True,
                       "my_team": ["Brand", "Zed", "Lux"], "bench": ["Ashe"]})
    assert len(out["advice"]) <= 100


def test_failsoft_never_raises_on_garbage():
    # Bad team payloads must degrade to the empty/stay shape, never raise.
    for bad in ({"my_champion": 123}, {"my_champion": "Ahri", "their_team": "notalist"},
                {"my_champion": "Ahri", "their_team": [None, 5]}):
        out = advise_pick(bad)
        assert set(out) == _ADVICE_KEYS

"""True-audit (s144 cycle 136) pins for core.precomputed_anvil_advisor.

Each test names the S144-T finding it pins. recompute_arena_build is
monkeypatched (hermetic, data-independent) except where the test needs the
real input normalisation to reach it, in which case a recording stub is used.
"""
from __future__ import annotations

import logging

import pytest

from core import precomputed_anvil_advisor as adv

_PATH = ["Guinsoo's Rageblade", "Kraken Slayer", "Blade of the Ruined King"]


@pytest.fixture
def path(monkeypatch):
    def _install(p):
        monkeypatch.setattr(adv, "recompute_arena_build", lambda *a, **k: p)
    return _install


def _pick(choices, **kw):
    kw.setdefault("champion", "Jinx")
    kw.setdefault("current_items", [])
    kw.setdefault("alive_opponents", [])
    kw.setdefault("hp_pct", 100)
    return adv.compute_anvil_pick(anvil_choices=choices, **kw)


# RM-1643: a 1-3 character fragment must not substring-bind to a path item.
# Live shape: a vision reply carrying anvil_choices as a bare string becomes
# list("Kraken Slayer") at the caller, i.e. one entry per character.
def test_short_fragment_does_not_bind(path):
    path(_PATH)
    out = _pick(list("Kraken"))
    assert out["take"] is None
    assert out["n_matches"] == 0
    assert out["conf"] == "low"
    assert all(r["rank"] is None for r in out["ranked"])


def test_three_char_fragment_does_not_bind(path):
    path(_PATH)
    out = _pick(["rag"])
    assert out["take"] is None


def test_four_char_display_variant_still_binds(path):
    path(["Zhonya's Hourglass"])
    out = _pick(["Zhon"])
    assert out["take"] == "Zhon"
    assert out["take_rank"] == 1


def test_short_exact_name_still_binds(path):
    # An exact normalized name binds whatever its length.
    path(["Kraken Slayer", "Hex"])
    out = _pick(["hex"])
    assert out["take_rank"] == 2


# RM-1644: an exact name anywhere in the path beats an earlier substring.
def test_exact_match_beats_earlier_substring(path):
    path(["Rageblade Prime", "Rageblade"])
    out = _pick(["Rageblade"])
    assert out["take_rank"] == 2
    assert out["ranked"][0]["rank"] == 2


def test_substring_keeps_earliest_path_rank(path):
    path(["Zhonya's Hourglass", "Zhonya's Paradox"])
    out = _pick(["Zhonyas"])
    assert out["take_rank"] == 1


# RM-1645: a generator of choices is read once; the fail-soft shape still
# lists every offered choice when the ideal path is empty.
def test_generator_choices_survive_empty_path(path):
    path([])
    out = _pick(c for c in ["Kraken Slayer", "Bloodthirster"])
    assert [r["name"] for r in out["ranked"]] == ["Kraken Slayer", "Bloodthirster"]


def test_generator_choices_ranked(path):
    path(_PATH)
    out = _pick(c for c in ["Kraken Slayer"])
    assert out["take"] == "Kraken Slayer"


# RM-1646: a bare str / bytes / mapping / non-iterable choices is no offer,
# never iterated by character or key, and never raises.
@pytest.mark.parametrize("bad", [
    "Kraken Slayer", b"Kraken Slayer", {"Kraken Slayer": 1}, 7, 3.5, object(),
])
def test_non_sequence_choices_is_no_offer(path, bad):
    path(_PATH)
    out = _pick(bad)
    assert out["take"] is None
    assert out["ranked"] == []
    assert out["conf"] == "low"


# RM-1647: a non-str choice is dropped, never str()-coerced into a match,
# and never leaks into the ranked names.
def test_non_str_choice_dropped(path):
    path(_PATH)
    out = _pick([{"name": "Kraken Slayer"}, 3031, None, True, "  ", "Kraken Slayer"])
    assert [r["name"] for r in out["ranked"]] == ["Kraken Slayer"]
    assert out["n_matches"] == 1


def test_choice_names_are_stripped(path):
    path(_PATH)
    out = _pick(["  Kraken Slayer \n"])
    assert out["ranked"][0]["name"] == "Kraken Slayer"


def test_overlong_choice_dropped(path):
    path(_PATH)
    out = _pick(["Kraken Slayer" * 50, "Kraken Slayer"])
    assert [r["name"] for r in out["ranked"]] == ["Kraken Slayer"]


def test_offer_read_is_bounded(path):
    path(_PATH)

    def _endless():
        while True:
            yield "Bloodthirster"

    out = _pick(_endless())
    assert len(out["ranked"]) == adv._MAX_OFFERED


# RM-1648: a non-list ideal path (a str would iterate by character) is no
# path, and non-str path entries are dropped rather than str()-coerced.
def test_str_ideal_path_is_no_path(path):
    path("Kraken Slayer")
    out = _pick(["Kraken Slayer"])
    assert out["take"] is None
    assert out["ideal_path"] == []
    assert [r["name"] for r in out["ranked"]] == ["Kraken Slayer"]


def test_unordered_ideal_path_is_no_path(path):
    # A rank is a position, so a set (no order) is not a path.
    path({"Kraken Slayer", "Bloodthirster"})
    out = _pick(["Kraken Slayer"])
    assert out["take"] is None
    assert out["ideal_path"] == []


def test_non_str_path_entries_dropped(path):
    path([{"Kraken Slayer": 1}, 6672, "Kraken Slayer"])
    out = _pick(["Kraken Slayer"])
    assert out["ideal_path"] == ["Kraken Slayer"]
    assert out["take_rank"] == 1


def test_ideal_path_is_a_fresh_list(path):
    src = ["Kraken Slayer"]
    path(src)
    out = _pick(["Kraken Slayer"])
    out["ideal_path"].append("x")
    assert src == ["Kraken Slayer"]


# RM-1649: owned items / opponents / champion are normalised before the
# rule-based build, so one bad owned entry does not zero the whole signal and a
# bare-string owned list is not read character by character.
def test_inputs_normalised_before_recompute(monkeypatch):
    seen = {}

    def _rec(champion, current_items, gold, alive_opponents, hp_pct):
        seen.update(champion=champion, items=list(current_items), gold=gold,
                    opps=list(alive_opponents), hp=hp_pct)
        return list(_PATH)

    monkeypatch.setattr(adv, "recompute_arena_build", _rec)
    out = adv.compute_anvil_pick(
        champion="  Jinx ",
        current_items=["Kraken Slayer", 3031, None, " "],
        anvil_choices=["Bloodthirster", "Kraken Slayer"],
        alive_opponents="Malphite",
        hp_pct=float("nan"),
        gold=-5,
    )
    assert seen == {"champion": "Jinx", "items": ["Kraken Slayer"], "gold": 0,
                    "opps": [], "hp": 100}
    assert out["take"] == "Kraken Slayer"


@pytest.mark.parametrize("hp,want", [(True, 100), (150, 100), (-3, 0),
                                     (42.7, 42), ("50", 100), (None, 100),
                                     pytest.param(10 ** 400, 100, id="huge-int")])
def test_hp_pct_clamped(monkeypatch, hp, want):
    seen = {}
    monkeypatch.setattr(adv, "recompute_arena_build",
                        lambda c, i, g, o, h: seen.setdefault("hp", h) and [])
    _pick(["Kraken Slayer"], hp_pct=hp)
    assert seen["hp"] == want


@pytest.mark.parametrize("champ", [None, "", "   ", 7, ["Jinx"], b"Jinx"])
def test_unusable_champion_is_low_conf_without_recompute(monkeypatch, champ):
    called = []
    monkeypatch.setattr(adv, "recompute_arena_build",
                        lambda *a, **k: called.append(1) or list(_PATH))
    out = _pick(["Kraken Slayer"], champion=champ)
    assert called == []
    assert out["conf"] == "low"
    assert [r["name"] for r in out["ranked"]] == ["Kraken Slayer"]


class _HostileStr(str):
    __slots__ = ()

    def strip(self, *a):
        raise RuntimeError("hostile strip")

    def lower(self):
        raise RuntimeError("hostile lower")


def test_str_subclass_overrides_never_raise(path):
    path(_PATH)
    out = _pick([_HostileStr(" Kraken Slayer ")], champion=_HostileStr(" Jinx "))
    assert out["take"] == "Kraken Slayer"
    assert type(out["take"]) is str


# RM-1650: a raising recompute is logged (with the traceback) instead of
# swallowed silently, and still never raises.
def test_recompute_failure_is_logged(monkeypatch, caplog):
    def _boom(*a, **k):
        raise KeyError("build DB")
    monkeypatch.setattr(adv, "recompute_arena_build", _boom)
    with caplog.at_level(logging.DEBUG, logger="rc.precomputed_anvil_advisor"):
        out = _pick(["Kraken Slayer"])
    assert out["conf"] == "low"
    recs = [r for r in caplog.records if r.name == "rc.precomputed_anvil_advisor"]
    assert recs and recs[0].exc_info is not None

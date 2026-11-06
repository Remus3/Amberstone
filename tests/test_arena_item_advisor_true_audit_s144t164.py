"""coaches/_arena_item_advisor.py - true-audit lane, s144 cycle 164.

Each test names the S144-T finding it pins. The advisor runs on every Arena
coach tick (coaches/arena_coach.py recompute_arena_build call) and feeds the
anvil precompute (core/precomputed_anvil_advisor.py) and the deterministic
Arena block (dashboard/_deterministic_coaching.py), so a wrong list here is a
wrong live recommendation and a raise here leaves item_build stale.

  RM-1947 owned-item dedup false positives (bare substring both ways)
  RM-1948 a duplicated build entry is recommended twice (live data)
  RM-1949 the anti-heal pivot recommends an item the player already owns
  RM-1950 junk shapes raise (blank / non-str names, non-dict entry,
             unhashable champion)
  S144-T-506 a str where a list belongs is iterated letter by letter
  RM-1951 one malformed DDragon entry blanks every tag and re-parses the
             file on every tick
  RM-1952 a whitespace / case variant of the champion name misses
"""
from __future__ import annotations

import pytest

from coaches import _arena_item_advisor as aia

_CHAMP = "Testchamp"


@pytest.fixture
def db(monkeypatch):
    """Synthetic, already-loaded caches: (arena, aram, tags)."""
    arena: dict = {}
    aram: dict = {}
    tags: dict = {}
    monkeypatch.setattr(aia, "_arena_builds_cache", arena)
    monkeypatch.setattr(aia, "_aram_builds_cache", aram)
    monkeypatch.setattr(aia, "_tags_cache", tags)
    monkeypatch.setattr(aia, "_WARNED_LOAD_PATHS", set())
    return arena, aram, tags


@pytest.fixture
def cold(monkeypatch):
    """Cold caches over the REAL tracked data files."""
    for attr in ("_arena_builds_cache", "_aram_builds_cache", "_tags_cache"):
        monkeypatch.setattr(aia, attr, None)
    monkeypatch.setattr(aia, "_WARNED_LOAD_PATHS", set())


def _run(champ=_CHAMP, owned=(), opps=()):
    return aia.recompute_arena_build(champ, owned, 0, opps, 100)


# -- RM-1947: dedup false positives -------------------------------------

@pytest.mark.parametrize("build_item,owned_item", [
    # build first word "blade" is a substring of "rageblade"
    ("Blade of The Ruined King", "Guinsoo's Rageblade"),
    # build first word "the" is a substring of "...of the ruined king"
    ("The Collector", "Blade of The Ruined King"),
    # build first word "black" is a substring of "blackfire"
    ("Black Cleaver", "Blackfire Torch"),
    # owned first word "the" is a whole word of the build item
    ("Jak'Sho, The Protean", "The Collector"),
    # the original BUG #2 direction stays fixed
    ("Guinsoo's Rageblade", "Blade of The Ruined King"),
])
def test_s144t502_unrelated_owned_item_does_not_hide_a_build_item(
    build_item, owned_item
):
    assert aia._filter_owned([build_item, "Kraken Slayer"], [owned_item]) == [
        build_item, "Kraken Slayer"]


@pytest.mark.parametrize("build_item,owned_item", [
    ("Zhonya's", "Zhonya's Hourglass"),            # short build form
    ("Zhonya's Hourglass", "Zhonya's"),            # short owned form
    ("Blade of the Ruined King", "Blade of The Ruined King"),  # case
    ("Kinkou Jitte (Phase-2 new arena-only Zed item)", "Kinkou Jitte"),
    ("Jak'Sho", "Jak'Sho, The Protean"),           # punctuation
    ("Kraken Slayer", "Kraken Slayer"),            # exact
])
def test_s144t502_same_item_still_dedups(build_item, owned_item):
    assert aia._filter_owned([build_item, "Statikk Shiv"], [owned_item]) == [
        "Statikk Shiv"]


@pytest.mark.parametrize("build_item,owned_item", [
    # spelling variants the old first-word rule caught (verifier finding)
    ("Storm Surge", "Stormsurge"),
    ("Navori Flickerblades", "Navori Flickerblade"),
    ("Lich Bane", "Lichbane"),
    ("Goredrink", "Goredrinker"),
    ("Deaths Dance", "Death's Dance"),
])
def test_s144t502_spelling_variant_still_dedups(build_item, owned_item):
    assert aia._filter_owned([build_item, "Statikk Shiv"], [owned_item]) == [
        "Statikk Shiv"]


def test_s144t502_owned_comma_name_hides_both_split_fragments():
    # verifier finding: the arena data splits "Jak'Sho, The Protean" into
    # "Jak'Sho" + "The Protean"; the old rule hid "The Protean" only by
    # its "the" substring accident
    assert aia._filter_owned(
        ["Cruelty", "Jak'Sho", "The Protean", "The Collector"],
        ["Jak'Sho, The Protean"]) == ["Cruelty", "The Collector"]


@pytest.mark.parametrize("champ", [
    "Leona", "Nautilus", "Rammus", "Rell", "Sejuani", "Skarner"])
def test_s144t502_live_owned_jaksho_hides_the_protean(cold, champ):
    out = _run(champ, owned=["Jak'Sho, The Protean"])
    assert out, champ
    assert "The Protean" not in out and "Jak'Sho" not in out, out


@pytest.mark.parametrize("build_item,owned_item", [
    # renamed items: build files keep the old name (alias table)
    ("Liandry's Anguish", "Liandry's Torment"),
    ("Luden's Echo", "Luden's Companion"),
    # an in-progress quest owns the item under a "Quest:" label
    ("Wooglet's Witchcap", "Quest: Wooglet's Witchcap"),
    # a champion-specific variant ends with the item's own words
    ("Talisman Of Ascension", "Veigar's Talisman of Ascension"),
    ("Veigar's Talisman of Ascension", "Talisman Of Ascension"),
    ("Jak'Sho, The Protean", "The Protean"),
])
def test_s144t502_old_rule_catches_kept(build_item, owned_item):
    assert aia._filter_owned([build_item, "Statikk Shiv"], [owned_item]) == [
        "Statikk Shiv"]


def test_s144t502_one_word_suffix_is_not_a_variant():
    assert aia._filter_owned(["Shiv", "Terminus"], ["Statikk Shiv"]) == [
        "Shiv", "Terminus"]


def test_s144t502_short_compact_prefix_does_not_match():
    # "black" is 5 letters, under the 6-letter character-prefix floor
    assert aia._filter_owned(["Blackfire Torch"], ["Black"]) == [
        "Blackfire Torch"]


@pytest.mark.parametrize("champ,owned,banned", [
    ("Ahri", "Stormsurge", "Storm Surge"),
    ("Vex", "Stormsurge", "Storm Surge"),
    ("Xayah", "Navori Flickerblade", "Navori Flickerblades"),
])
def test_s144t502_live_variant_owned_is_not_re_recommended(
    cold, champ, owned, banned
):
    full, _ = aia._resolve_build_path(champ)
    assert banned in full, (champ, full)   # the data still spells it so
    assert banned not in _run(champ, owned=[owned])


def test_s144t503_variant_repeat_in_build_recommended_once(db):
    arena, _, _ = db
    arena[_CHAMP] = {"ideal_core_priority": [
        "Mystic Punch", "Terminus", "Mystic Punch (augment-mirror)",
        "Stormsurge", "Storm Surge"]}
    assert _run() == ["Mystic Punch", "Terminus", "Stormsurge"]


def test_s144t502_live_kaisa_owning_rageblade_keeps_botrk(cold):
    out = _run("Kai'Sa", owned=["Guinsoo's Rageblade"])
    assert "Blade of The Ruined King" in out, out
    assert "Guinsoo's Rageblade" not in out


# -- RM-1948: duplicates -------------------------------------------------

def test_s144t503_duplicate_build_entry_recommended_once(db):
    arena, _, _ = db
    arena[_CHAMP] = {"ideal_core_priority": [
        "A Item", "B Item", "A Item", "C Item", "a item", "D Item", "E Item",
        "F Item", "G Item"]}
    out = _run()
    assert out == ["A Item", "B Item", "C Item", "D Item", "E Item", "F Item"]


@pytest.mark.parametrize("champ", [
    "Kha'Zix", "Zed", "Fiddlesticks", "Orianna", "Viktor"])
def test_s144t503_live_data_duplicates_never_reach_the_list(cold, champ):
    out = _run(champ)
    assert out, champ
    assert len(out) == len(set(out)), out


# -- RM-1949: anti-heal pivot vs owned items ----------------------------

_HEALERS = ["Aatrox", "Soraka"]


def test_s144t504_pivot_never_recommends_an_owned_item(db):
    arena, _, _ = db
    arena[_CHAMP] = {"ideal_core_priority": [
        "Hamstringer", "Bloodthirster", "Kraken Slayer",
        "Lord Dominik's Regards"]}
    out = _run(owned=["Mortal Reminder"], opps=_HEALERS)
    assert "Mortal Reminder" not in out, out
    assert out == ["Hamstringer", "Bloodthirster", "Kraken Slayer",
                   "Lord Dominik's Regards"]


def test_s144t504_owned_antiheal_skips_the_reorder(db):
    arena, _, _ = db
    arena[_CHAMP] = {"ideal_core_priority": [
        "Luden's Echo", "Shadowflame", "Morellonomicon"]}
    out = _run(owned=["Thornmail"], opps=_HEALERS)
    assert out == ["Luden's Echo", "Shadowflame", "Morellonomicon"]


def test_s144t504_pivot_still_fires_without_owned_antiheal(db):
    arena, _, _ = db
    arena[_CHAMP] = {"ideal_core_priority": [
        "Hamstringer", "Bloodthirster", "Kraken Slayer",
        "Lord Dominik's Regards"]}
    out = _run(owned=[], opps=_HEALERS)
    assert out == ["Mortal Reminder", "Hamstringer", "Bloodthirster",
                   "Kraken Slayer"]


# -- RM-1950: junk shapes never raise -----------------------------------

@pytest.mark.parametrize("owned", [
    ["   "], [None], [5], [{"name": "x"}], [["x"]], None, 5,
], ids=lambda v: repr(v))
def test_s144t505_junk_owned_never_raises(db, owned):
    arena, _, _ = db
    arena[_CHAMP] = {"ideal_core_priority": ["Kraken Slayer", "Terminus"]}
    assert _run(owned=owned) == ["Kraken Slayer", "Terminus"]


def test_s144t505_junk_build_entries_are_dropped_not_raised(db):
    arena, _, _ = db
    arena[_CHAMP] = {"ideal_core_priority": [
        "  ", None, 7, {"x": 1}, ["y"], " Kraken Slayer ", "Terminus"]}
    assert _run() == ["Kraken Slayer", "Terminus"]


@pytest.mark.parametrize("champ", [None, 5, ["Zed"], {"a": 1}, "", "   ",
                                   "_note", "_provenance"])
def test_s144t505_junk_champion_returns_empty(db, champ):
    arena, aram, _ = db
    arena["_note"] = "metadata string, not an entry"
    aram["_provenance"] = ["not", "an", "entry"]
    assert _run(champ) == []


def test_s144t505_non_dict_entry_falls_back_to_aram(db):
    arena, aram, _ = db
    arena[_CHAMP] = ["drifted", "list"]
    aram[_CHAMP] = {"full_build": ["Kraken Slayer"]}
    assert _run() == ["Kraken Slayer"]


@pytest.mark.parametrize("opps", [
    [None, 5, ["Aatrox"], {"n": 1}, "  "], None, 7,
], ids=lambda v: repr(v))
def test_s144t505_junk_opponents_never_raise(db, opps):
    arena, _, tags = db
    tags["Malphite"] = ["Tank"]
    arena[_CHAMP] = {"ideal_core_priority": ["A Item", "B Item", "Terminus"]}
    assert _run(opps=opps) == ["A Item", "B Item", "Terminus"]


# -- S144-T-506: str where a list belongs ----------------------------------

def test_s144t506_str_build_is_not_iterated_by_letter(db):
    arena, aram, _ = db
    arena[_CHAMP] = {"ideal_core_priority": "Kraken Slayer"}
    aram[_CHAMP] = {"full_build": ["Terminus"]}
    assert _run() == ["Terminus"]


def test_s144t506_str_build_without_fallback_is_empty(db):
    arena, _, _ = db
    arena[_CHAMP] = {"ideal_core_priority": "Kraken Slayer"}
    assert _run() == []


def test_s144t506_str_owned_is_one_item(db):
    arena, _, _ = db
    arena[_CHAMP] = {"ideal_core_priority": ["Kraken Slayer", "Terminus"]}
    assert _run(owned="Kraken Slayer") == ["Terminus"]


def test_s144t506_str_opponent_is_one_name(db):
    arena, _, tags = db
    tags["Malphite"] = ["Tank"]
    arena[_CHAMP] = {"ideal_core_priority": ["A Item", "B Item", "Terminus"]}
    # one tank is below the 2+ threshold: no reorder, and no raise
    assert _run(opps="Malphite") == ["A Item", "B Item", "Terminus"]


def test_s144t506_tank_pivot_still_fires(db):
    arena, _, tags = db
    tags["Malphite"] = ["Tank", "Fighter"]
    tags["Ornn"] = ["Tank"]
    arena[_CHAMP] = {"ideal_core_priority": ["A Item", "B Item", "Terminus"]}
    assert _run(opps=["Malphite", "Ornn"]) == ["Terminus", "A Item", "B Item"]


# -- RM-1951: DDragon tag map -------------------------------------------

def _ddragon(tmp_path, data):
    import json
    p = tmp_path / "ddragon.json"
    p.write_text(json.dumps({"type": "champion", "data": data}),
                 encoding="utf-8")
    return p


def test_s144t507_one_bad_entry_keeps_the_rest_and_caches(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(aia, "_tags_cache", None)
    monkeypatch.setattr(aia, "_WARNED_LOAD_PATHS", set())
    monkeypatch.setattr(aia, "_DDRAGON_PATH", _ddragon(tmp_path, {
        "Bad": "not an entry",
        "Bad2": {"name": 5, "tags": ["Tank"]},
        "Malphite": {"name": "Malphite", "tags": ["Tank", "Fighter"]},
        "Ornn": {"name": "Ornn", "tags": "Tank"},
        "Odd": {"name": "Odd", "tags": [1, None, "Mage"]},
    }))
    first = aia._load_tags()
    assert first["Malphite"] == ["Tank", "Fighter"]
    assert first["Ornn"] == ["Tank"]
    assert first["Odd"] == ["Mage"]
    assert aia._tags_cache is first, "a good load must be cached"
    assert aia._load_tags() is first


@pytest.mark.parametrize("data", [
    ["not", "a", "dict"], {"Bad": "x", "Bad2": {"name": None}}, {}],
    ids=["list-data", "all-bad", "empty"])
def test_s144t507_unusable_data_block_is_not_cached(monkeypatch, tmp_path,
                                                     data):
    monkeypatch.setattr(aia, "_tags_cache", None)
    monkeypatch.setattr(aia, "_WARNED_LOAD_PATHS", set())
    monkeypatch.setattr(aia, "_DDRAGON_PATH", _ddragon(tmp_path, data))
    assert aia._load_tags() == {}
    assert aia._tags_cache is None


# -- RM-1952: champion name variants ------------------------------------

@pytest.mark.parametrize("champ", ["Zed", " Zed ", "zed", "ZED"])
def test_s144t508_name_variants_resolve(db, champ):
    arena, _, _ = db
    arena["Zed"] = {"ideal_core_priority": ["Duskblade of Draktharr"]}
    assert _run(champ) == ["Duskblade of Draktharr"]


def test_s144t508_variant_fallback_reaches_aram(db):
    _, aram, _ = db
    aram["Kai'Sa"] = {"full_build": ["Kraken Slayer"]}
    assert _run("kai'sa") == ["Kraken Slayer"]


def test_s144t505_result_is_a_fresh_list_of_str(db):
    arena, _, _ = db
    icp = ["Kraken Slayer", "Terminus"]
    arena[_CHAMP] = {"ideal_core_priority": icp}
    out = _run()
    out.append("mutated")
    assert icp == ["Kraken Slayer", "Terminus"]
    assert all(isinstance(x, str) for x in _run())

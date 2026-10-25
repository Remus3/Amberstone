"""RM-840: one TFT set resolver replaces the hard-coded Set 17 data paths.

RC was wired to Set 17 in six places (plan U5, measured at 373c693bb):
tft/tft_coach_engine.py :109/:112, :133/:136, :388/:391 (meta file),
tft/tft_roll_odds.py :293 (lane set), performance_tracker.py :375-377 (meta
file) and tft/tft_live_analysis.py :158-186 (the champion whitelist, measured
against the Set 17 roster only). Set 18 has been live since about 2026-08-26
with Set 17 still playable, so the default must be the NEWEST ingested set,
Set 17 must stay resolvable, and a live set id must win when one is present.

Which set a live game is running is LIVE-GAME-GATED: nobody has measured
whether :2999 or the LCU exposes it during a TFT game. These tests pin the
plumbing (a set id noted from live data wins), not the field a real game uses.

Every test builds its own data/meta under tmp_path unless it names the
committed tree on purpose (the `_committed_` tests).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tft import tft_set

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolated_resolver(monkeypatch):
    """No noted live set and no env pin leaks between tests."""
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, indent=1).encode("ascii") + b"\n")


@pytest.fixture
def two_sets(tmp_path):
    """A data/meta holding a Set 17 meta (+PBE twin) and a Set 18 meta + extract."""
    meta = tmp_path / "data" / "meta"
    _write(meta / "tft_set17_meta.json", {
        "_set": 17, "champions_set17": ["Jinx", "Meepsie"],
        "all_traits": ["Anima", "Meeple"],
        "trait_augments": {"Anima Heart": {"impact": 1}},
        "comps": {"Anima Squad": {"core_units": ["Jinx"]}},
    })
    _write(meta / "tft_set17_pbe_meta.json", {"_set": 17, "_data_type": "pbe"})
    _write(meta / "tft_set18_meta.json", {
        "_set": 18, "comps": {}, "trait_augments": {}, "double_up": {},
    })
    _write(meta / "tft_set18_cdragon.json", {
        "_set": 18, "champions": ["Kobuko", "Yunara"],
        "all_traits": ["Elderwood", "Fae"],
    })
    # Not a set data file: must not be read as "set 17 ingested twice" or
    # as a set of its own.
    _write(meta / "tft_set17_champion_codes.json", {"Jinx": 18})
    return tmp_path


# -- discovery and the default ------------------------------------------------

def test_ingested_sets_are_discovered_off_disk(two_sets):
    assert tft_set.ingested_sets(root=two_sets) == [17, 18]


def test_default_is_the_newest_ingested_set(two_sets):
    assert tft_set.default_set(root=two_sets) == 18
    assert tft_set.resolve_set(root=two_sets) == 18


def test_a_cdragon_extract_alone_counts_as_ingested(tmp_path):
    _write(tmp_path / "data" / "meta" / "tft_set19_cdragon.json", {"_set": 19})
    assert tft_set.ingested_sets(root=tmp_path) == [19]
    assert tft_set.resolve_set(root=tmp_path) == 19


def test_nothing_ingested_falls_back_to_the_pre_rm840_set(tmp_path):
    (tmp_path / "data" / "meta").mkdir(parents=True)
    assert tft_set.ingested_sets(root=tmp_path) == []
    assert tft_set.default_set(root=tmp_path) is None
    assert tft_set.resolve_set(root=tmp_path) == tft_set.FALLBACK_SET == 17


# -- Set 17 stays resolvable --------------------------------------------------

def test_set17_still_resolves_explicitly(two_sets):
    p = tft_set.meta_path(17, root=two_sets)
    assert p == two_sets / "data" / "meta" / "tft_set17_meta.json"
    assert tft_set.load_meta(17, root=two_sets)["_set"] == 17
    assert tft_set.roster(17, root=two_sets) == ["Jinx", "Meepsie"]


def test_default_meta_path_is_the_newest_set(two_sets):
    assert tft_set.meta_path(root=two_sets).name == "tft_set18_meta.json"
    assert tft_set.load_meta(root=two_sets)["_set"] == 18


def test_pbe_twin_used_only_when_that_set_has_one(two_sets):
    assert tft_set.meta_path(17, pbe=True, root=two_sets).name == "tft_set17_pbe_meta.json"
    # Set 18 has no PBE twin: the set's own live meta, never another set's.
    assert tft_set.meta_path(18, pbe=True, root=two_sets).name == "tft_set18_meta.json"


def test_missing_meta_never_borrows_another_sets_file(tmp_path):
    """The old sites fell back to tft_set17_meta.json; feeding Set 17 comps
    to a Set 19 game is the defect, so the path stays the set's own."""
    meta = tmp_path / "data" / "meta"
    _write(meta / "tft_set17_meta.json", {"_set": 17, "comps": {"X": {}}})
    _write(meta / "tft_set19_cdragon.json", {"_set": 19})
    p = tft_set.meta_path(root=tmp_path)
    assert p.name == "tft_set19_meta.json"
    assert not p.exists()
    assert tft_set.load_meta(root=tmp_path) == {}


# -- the live override ----------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    (17, 17), ("18", 18), ("TFTSet17", 17), ("TFTSet17_PAIRS", 17),
    ("TFT_Set17", 17), ("Set18", 18), ("tftset18_turbo", 18),
    (None, None), (True, None), (0, None), ("", None), ("abc", None),
    ("DA_18_Kobuko", None), (17.5, None), ({"set": 17}, None),
])
def test_parse_set_id(raw, want):
    assert tft_set.parse_set_id(raw) == want


def test_live_set_argument_wins_over_the_default(two_sets):
    assert tft_set.resolve_set(live_set="TFTSet17", root=two_sets) == 17
    assert tft_set.meta_path(root=two_sets).name == "tft_set18_meta.json"


def test_noted_live_set_wins_over_the_default(two_sets):
    assert tft_set.note_live_set("TFTSet17_PAIRS") == 17
    assert tft_set.resolve_set(root=two_sets) == 17
    assert tft_set.meta_path(root=two_sets).name == "tft_set17_meta.json"
    tft_set.clear_live_set()
    assert tft_set.resolve_set(root=two_sets) == 18


def test_noted_live_set_expires(two_sets, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(tft_set, "_monotonic", lambda: clock[0])
    tft_set.note_live_set(17)
    assert tft_set.resolve_set(root=two_sets) == 17
    clock[0] += tft_set.LIVE_TTL_S + 1
    assert tft_set.noted_live_set() is None
    assert tft_set.resolve_set(root=two_sets) == 18


def test_live_set_without_data_does_not_win(two_sets):
    """A live game on a set RC has not ingested cannot be served; the newest
    ingested set is the best data on disk."""
    assert tft_set.resolve_set(live_set=19, root=two_sets) == 18


def test_env_pin_beats_default_but_live_beats_env(two_sets, monkeypatch):
    monkeypatch.setenv(tft_set.ENV_PIN, "17")
    assert tft_set.resolve_set(root=two_sets) == 17
    monkeypatch.setenv(tft_set.ENV_PIN, "18")
    assert tft_set.resolve_set(live_set=17, root=two_sets) == 17


def test_live_set_noted_from_game_data(two_sets):
    # Candidate key names are UNMEASURED (live-game-gated); the measured
    # set-id spellings in the tree are the LCU team-planner previous-context
    # "setId": "TFTSet17" / "TFTSet18" (scripts/discover_champion_codes.py
    # PLANNER_CONTEXT; tft/tft_set.py docstring, session 134).
    assert tft_set.note_live_set_from_game_data({"gameMode": "TFT"}) is None
    assert tft_set.resolve_set(root=two_sets) == 18
    assert tft_set.note_live_set_from_game_data(
        {"gameMode": "TFT", "setId": "TFTSet17"}) == 17
    assert tft_set.resolve_set(root=two_sets) == 17
    assert tft_set.note_live_set_from_game_data("not a dict") is None


def test_state_reader_notes_a_live_set_before_parsing(monkeypatch):
    """tft/tft_state_reader.py:112 read() is the one live TFT game-data tap."""
    from tft.tft_state_reader import TftStateReader

    seen = []
    monkeypatch.setattr(tft_set, "note_live_set_from_game_data",
                        lambda gd: seen.append(dict(gd)))
    rdr = object.__new__(TftStateReader)  # skip __init__ (OCR thread)
    raw = {"gameData": {"gameMode": "TFT", "setId": "TFTSet17"}}
    rdr._fetch = lambda: raw
    rdr._parse = lambda r, gd=None: {"ok": True}
    assert rdr.read() == {"ok": True}
    assert seen == [raw["gameData"]]


# -- rosters --------------------------------------------------------------------

def test_roster_prefers_the_cdragon_extract(two_sets):
    assert tft_set.roster(18, root=two_sets) == ["Kobuko", "Yunara"]
    assert tft_set.trait_names(18, root=two_sets) == ["Elderwood", "Fae"]
    assert tft_set.trait_names(17, root=two_sets) == ["Anima", "Meeple"]


def test_union_roster_covers_every_ingested_set(two_sets):
    assert tft_set.all_champion_names(root=two_sets) == {
        "Jinx", "Meepsie", "Kobuko", "Yunara"}
    assert tft_set.all_trait_names(root=two_sets) == {
        "Anima", "Meeple", "Elderwood", "Fae"}


# -- consumers read through the resolver ---------------------------------------

def test_roll_odds_lane_set_comes_from_the_resolver(monkeypatch):
    """tft/tft_roll_odds.py:281 constants_health() lane_set default."""
    from tft import tft_roll_odds as ro

    monkeypatch.setattr(tft_set, "resolve_set", lambda *a, **k: 42)
    assert ro.constants_health()["lane_set"] == 42


def test_coach_engine_meta_sections_come_from_the_resolver(two_sets, monkeypatch):
    """tft/tft_coach_engine.py:98 / :122 loaders (cached per resolved path)."""
    from tft import tft_coach_engine as eng

    monkeypatch.setattr(tft_set, "comp_state", lambda root=None: {})
    monkeypatch.setattr(tft_set, "ROOT", two_sets)
    assert eng._load_trait_augment_data() == {}  # Set 18 skeleton: empty
    tft_set.note_live_set(17)
    assert eng._load_trait_augment_data() == {"Anima Heart": {"impact": 1}}
    assert eng._load_double_up_rules() == {}


def test_coach_engine_selected_comp_reads_the_resolved_set(two_sets, monkeypatch):
    """tft/tft_coach_engine.py:230 _build_prompt SELECTED COMP block."""
    from tft import tft_coach_engine as eng

    monkeypatch.setattr(tft_set, "ROOT", two_sets)
    monkeypatch.setattr(tft_set, "comp_state",
                        lambda root=None: {"selected": "Anima Squad"})
    assert "SELECTED COMP" not in eng._build_prompt({"level": 4})
    tft_set.note_live_set(17)
    assert "SELECTED COMP: Anima Squad" in eng._build_prompt({"level": 4})


def test_performance_tracker_meta_lookup_goes_through_the_resolver(tmp_path, monkeypatch):
    """performance_tracker.py:330 save_tft_rating comp enrichment."""
    import performance_tracker as pt

    calls = []
    real = tft_set.meta_path

    def spy(*a, **k):
        calls.append(k.get("root"))
        return real(*a, **k)

    monkeypatch.setattr(tft_set, "meta_path", spy)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "comp_state.json").write_text(
        json.dumps({"selected": "Test Comp"}), encoding="utf-8")
    live = {"level": 8, "traits_active": [], "board_units": [],
            "augments": [], "last_round_result": "4th"}
    pt.save_tft_rating(str(tmp_path), live,
                       {"stage": 4, "game_time_s": 1800, "alive_others": 7})
    assert calls and all(Path(c) == tmp_path for c in calls)


def test_live_analysis_whitelist_includes_set18_roster():
    """tft/tft_live_analysis.py:186 _TFT_CHAMP_LOWER and :257 _sanitize_units."""
    from tft import tft_live_analysis as tla

    for name in ("Kobuko", "Yunara", "Alune", "Kha'Zix", "Elder Dragon"):
        assert name.lower() in tla._TFT_CHAMP_LOWER, name
    assert tla._sanitize_units(["Kobuko 2-star", "Elderwood", "Jinx"]) == [
        "Kobuko 2-star", "unknown", "Jinx"]


def test_live_analysis_no_ingested_champion_reads_as_a_trait():
    """Widening _TRAIT_NAMES with ingested traits must not turn a real
    champion of ANY ingested set into "unknown"."""
    from tft import tft_live_analysis as tla

    names = tft_set.all_champion_names()
    s17, s18 = set(tft_set.roster(17)), set(tft_set.roster(18))
    assert len(s17) >= 60 and len(s18) >= 60
    assert names >= s17 | s18 and s18 - s17  # anchored: not an empty walk
    hits = sorted(n for n in names if tla._is_trait_label(n.lower()))
    assert hits == []
    assert tla._sanitize_units(sorted(names)) == sorted(names)


# -- the committed tree ---------------------------------------------------------

def test_committed_tree_defaults_to_set18_and_keeps_set17():
    sets = tft_set.ingested_sets(root=REPO_ROOT)
    assert 17 in sets and 18 in sets
    assert tft_set.default_set(root=REPO_ROOT) == 18
    assert tft_set.meta_path(17, root=REPO_ROOT).exists()
    assert tft_set.meta_path(18, root=REPO_ROOT).exists()


def test_committed_set18_meta_is_a_skeleton_with_no_tier_data():
    """No third-party comps or tier list absorbed (licence gate)."""
    meta = tft_set.load_meta(18, root=REPO_ROOT)
    assert meta["_set"] == 18
    for key in ("comps", "tier_list", "trait_augments", "double_up"):
        assert meta[key] == {}, key
    assert "unverified" in meta["_note"].lower()

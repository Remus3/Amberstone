"""S144-D-211..214: data/daemon_slayer/sr_draft_presets.json against DDragon.

The SR draft presets name runes and summoner spells by hand, and the module
that reads them (coaches/sr_draft_profile.py) carries an in-module copy,
`_FALLBACK_PRESETS`, used whenever the file is missing or unreadable. Every
lookup is a plain dict get or a coercion that silently falls back, so a stale
name, an illegal tree pair or an out-of-range number never raises - it just
emits a page League rejects or a query the engine never sees.

- S144-D-211: every keystone named in `rune_defaults_by_role` (file and
  fallback) is a slot-0 rune of the tracked DDragon runes, by its CURRENT
  DDragon name. "Phase Rush" is the pre-rename name of 8230; DDragon 16.22.1
  calls it "Stormraider's Surge" (RM-1379 aliased it in the rune writer only).
- S144-D-212: every (keystone, primary, secondary) the module can emit, from
  the file AND from the fallback, is a page `lcu_rune_writer.build_perk_ids`
  accepts - keystone in its primary tree, secondary a different live tree.
  The fallback carried an empty `tree_by_keystone`, so a broken file made
  every non-Precision keystone (Electrocute, Glacial Augment, ...) ride the
  Precision default and the writer refused the page (RM-1378 legality).
- S144-D-213: every `spells_by_role` id is a CLASSIC-mode summoner spell of
  the tracked DDragon summoner file, each pair is two distinct spells, and
  the jungle pair carries Smite.
- S144-D-214: every shipped `engine_query` number sits inside the bounds
  `_query_body` enforces and every phase is one /beam accepts, so no shipped
  value is silently replaced by a default; the skeleton cuts tile the build
  with no gap or overlap.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import coaches.sr_draft_profile as sdp
from lcu import lcu_rune_writer as w

_ROOT = Path(__file__).resolve().parent.parent
_PRESETS = _ROOT / "data" / "daemon_slayer" / "sr_draft_presets.json"
_RUNES = _ROOT / "data" / "meta" / "ddragon_runes.json"
_SUMMONERS = _ROOT / "data" / "meta" / "ddragon_summoner_spells.json"

_SMITE = 11


def _shipped() -> dict:
    return json.loads(_PRESETS.read_text(encoding="utf-8"))


def _keystone_tree() -> dict[str, str]:
    """{keystone DDragon name: its tree name} from the tracked rune file."""
    out: dict[str, str] = {}
    for tree in json.loads(_RUNES.read_text(encoding="utf-8")):
        for rune in tree["slots"][0]["runes"]:
            out[rune["name"]] = tree["name"]
    return out


def _tree_names() -> set[str]:
    return {t["name"] for t in json.loads(_RUNES.read_text(encoding="utf-8"))}


def _classic_spell_ids() -> set[int]:
    data = json.loads(_SUMMONERS.read_text(encoding="utf-8"))["data"]
    return {int(s["key"]) for s in data.values() if "CLASSIC" in s.get("modes", [])}


_SOURCES = {"file": _shipped, "fallback": lambda: sdp._FALLBACK_PRESETS}


# -- checkers (pure, so each has a planted-defect test) ---------------------

def stale_keystones(presets: dict, live: dict[str, str]) -> list[tuple]:
    bad = []
    for role, kinds in sorted(presets["rune_defaults_by_role"].items()):
        for kind, name in sorted(kinds.items()):
            if name not in live:
                bad.append((role, kind, name))
    return bad


def illegal_tree_rows(presets: dict, live: dict[str, str],
                      trees: set[str]) -> list[tuple]:
    bad = []
    for keystone, row in sorted(presets["tree_by_keystone"].items()):
        pri, sec = row.get("primary"), row.get("secondary")
        if live.get(keystone) != pri or sec not in trees or sec == pri:
            bad.append((keystone, pri, sec, live.get(keystone)))
    return bad


def emitted_pages(presets: dict) -> list[tuple]:
    """Every (role, kind, keystone, primary, secondary) the module emits."""
    out = []
    for role in sorted(presets["rune_defaults_by_role"]):
        for kind in sdp._PROFILE_KINDS:
            _ks, runes = sdp._runes_for(role, kind, presets)
            out.append((role, kind, runes["keystone"], runes["primary"],
                        runes["secondary"]))
    return out


def bad_spell_pairs(presets: dict, classic: set[int]) -> list[tuple]:
    bad = []
    for role, pair in sorted(presets["spells_by_role"].items()):
        if (not isinstance(pair, list) or len(pair) != 2
                or any(isinstance(s, bool) or not isinstance(s, int) for s in pair)
                or pair[0] == pair[1]
                or not set(pair) <= classic):
            bad.append((role, pair))
    return bad


def out_of_bounds_queries(presets: dict) -> list[tuple]:
    bad = []
    for kind, preset in sorted(presets["engine_query"].items()):
        for name, (_d, lo, hi) in sdp._QUERY_INT_FIELDS.items():
            v = preset.get(name)
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                bad.append((kind, name, v))
        for name, (_d, lo, hi) in sdp._QUERY_FLOAT_FIELDS.items():
            v = preset.get(name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                bad.append((kind, name, v))
        phase = preset.get("phase")
        if phase is not None and phase not in sdp._BEAM_PHASES:
            bad.append((kind, "phase", phase))
    return bad


def skeleton_gaps(presets: dict, slots: int) -> list[str]:
    cuts = [tuple(presets["skeleton_split"][s]) for s in ("start", "core", "final")]
    problems = []
    if cuts[0][0] != 0:
        problems.append(f"start begins at {cuts[0][0]}, not 0")
    for (lo1, hi1), (lo2, _hi2) in zip(cuts, cuts[1:]):
        if hi1 != lo2:
            problems.append(f"cut {lo1}:{hi1} does not meet {lo2}")
    for lo, hi in cuts:
        if not 0 <= lo < hi:
            problems.append(f"cut {lo}:{hi} is empty or reversed")
    if cuts[-1][1] != slots:
        problems.append(f"final ends at {cuts[-1][1]}, not {slots} slots")
    return problems


# -- anchor: an emptied table must not pass every check vacuously ----------

@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_s144d211_tables_cover_every_role_and_kind(source):
    presets = _SOURCES[source]()
    by_role = presets["rune_defaults_by_role"]
    assert set(by_role) == set(sdp._ROLES)
    for role, kinds in by_role.items():
        assert set(kinds) == set(sdp._PROFILE_KINDS), role
    assert len(emitted_pages(presets)) == len(sdp._ROLES) * len(sdp._PROFILE_KINDS)
    assert presets["tree_by_keystone"] and presets["spells_by_role"]
    assert _keystone_tree() and _classic_spell_ids()


# -- S144-D-211: keystone names are current DDragon names -------------------

@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_s144d211_every_role_keystone_is_a_live_ddragon_keystone(source):
    assert stale_keystones(_SOURCES[source](), _keystone_tree()) == []


def test_s144d211_tree_table_is_keyed_by_live_keystone_names():
    live = _keystone_tree()
    for source in sorted(_SOURCES):
        stale = sorted(k for k in _SOURCES[source]()["tree_by_keystone"] if k not in live)
        assert stale == [], (source, stale)


def test_s144d211_checker_catches_the_legacy_name():
    planted = {"rune_defaults_by_role": {"TOP": {"experimental": "Phase Rush"}}}
    assert stale_keystones(planted, _keystone_tree()) == [
        ("TOP", "experimental", "Phase Rush")]


# -- S144-D-212: every emitted page is one the rune writer accepts ----------

@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_s144d212_tree_rows_put_each_keystone_in_its_own_tree(source):
    presets = _SOURCES[source]()
    assert illegal_tree_rows(presets, _keystone_tree(), _tree_names()) == []


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_s144d212_every_role_keystone_has_a_tree_row(source):
    presets = _SOURCES[source]()
    rows = presets["tree_by_keystone"]
    missing = sorted({name for kinds in presets["rune_defaults_by_role"].values()
                      for name in kinds.values() if name not in rows})
    assert missing == []


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_s144d212_every_emitted_page_is_accepted_by_the_writer(source):
    refused = [page for page in emitted_pages(_SOURCES[source]())
               if w.build_perk_ids(page[2], page[3], page[4]) is None]
    assert refused == []


def test_s144d212_checker_catches_a_keystone_outside_its_tree():
    planted = {"tree_by_keystone": {
        "Electrocute": {"primary": "Precision", "secondary": "Domination"},
        "Conqueror": {"primary": "Precision", "secondary": "Precision"},
        "Guardian": {"primary": "Resolve", "secondary": "Nowhere"},
    }}
    bad = illegal_tree_rows(planted, _keystone_tree(), _tree_names())
    assert [row[0] for row in bad] == ["Conqueror", "Electrocute", "Guardian"]


# -- S144-D-213: summoner ids are live CLASSIC spells ------------------------

@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_s144d213_every_spell_pair_is_two_live_classic_spells(source):
    assert bad_spell_pairs(_SOURCES[source](), _classic_spell_ids()) == []


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_s144d213_jungle_pair_carries_smite(source):
    assert _SMITE in _SOURCES[source]()["spells_by_role"]["JUNGLE"]


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_s144d213_every_role_has_a_spell_pair(source):
    presets = _SOURCES[source]()
    roles = set(presets["rune_defaults_by_role"]) | {"_unknown"}
    assert roles <= set(presets["spells_by_role"])


def test_s144d213_module_default_pair_is_live():
    assert bad_spell_pairs({"spells_by_role": {"_": list(sdp._DEFAULT_SPELLS)}},
                           _classic_spell_ids()) == []
    assert sdp._DEFAULT_KEYSTONE in _keystone_tree()


def test_s144d213_checker_catches_dead_duplicate_and_mode_only_spells():
    # 32 = Mark (ARAM only), 13 = Clarity (not CLASSIC), 9999 = no such spell.
    planted = {"spells_by_role": {"A": [4, 32], "B": [4, 4], "C": [13, 4],
                                  "D": [4, 9999], "E": [4, True], "F": [4, 12]}}
    assert [r for r, _p in bad_spell_pairs(planted, _classic_spell_ids())] == [
        "A", "B", "C", "D", "E"]


# -- S144-D-214: no shipped number is silently replaced ----------------------

@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_s144d214_engine_query_values_inside_the_coercion_bounds(source):
    presets = _SOURCES[source]()
    assert set(presets["engine_query"]) == set(sdp._PROFILE_KINDS)
    assert out_of_bounds_queries(presets) == []


@pytest.mark.parametrize("kind", sdp._PROFILE_KINDS)
def test_s144d214_query_body_carries_the_shipped_values_verbatim(kind):
    preset = _shipped()["engine_query"][kind]
    body = sdp._query_body("Ahri", preset, warn=False)
    for name in (*sdp._QUERY_INT_FIELDS, *sdp._QUERY_FLOAT_FIELDS):
        assert body[name] == preset[name], name
    assert body.get("phase") == preset["phase"]


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_s144d214_skeleton_cuts_tile_every_preset_build(source):
    presets = _SOURCES[source]()
    for kind, preset in sorted(presets["engine_query"].items()):
        assert skeleton_gaps(presets, preset["slots"]) == [], kind


def test_s144d214_checkers_catch_planted_defects():
    planted = {"engine_query": {"primary": {
        "level": 19, "slots": 6, "beam_width": 10, "top": 1,
        "target_armor": -1, "target_mr": 50, "phase": "midgame"}}}
    assert out_of_bounds_queries(planted) == [
        ("primary", "level", 19), ("primary", "target_armor", -1),
        ("primary", "phase", "midgame")]
    gap = {"skeleton_split": {"start": [0, 2], "core": [3, 4], "final": [4, 5]}}
    assert len(skeleton_gaps(gap, 6)) == 2

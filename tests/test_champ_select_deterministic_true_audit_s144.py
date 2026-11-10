"""True-audit (lane 8, S144-T-742) pins for dashboard/_champ_select_deterministic.py.

Each test names the defect it pins. Valid input is unchanged (measured over the
real roster in the cycle report); these cover the wrong-typed / partial-failure
paths the module's own docstring promises to fail soft on.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

import dashboard._champ_select_deterministic as m

_SHAPE = {"build": [], "runes": {}, "ally_notes": ""}

_RUNES_JSON = [
    {"id": 8000, "slots": [{"runes": [{"id": 8005, "name": "Press the Attack"},
                                      {"id": 8008, "name": "Lethal Tempo"}]}]},
]


@pytest.fixture(autouse=True)
def _fresh_keystone_cache():
    """Every test starts with an unloaded keystone map and leaves none behind."""
    m._KEYSTONE_ID_TO_NAME = None
    m._KEYSTONE_RETRY_AT = 0.0
    yield
    m._KEYSTONE_ID_TO_NAME = None
    m._KEYSTONE_RETRY_AT = 0.0


def _runes_dir(tmp_path, payload: bytes):
    meta = tmp_path / "data" / "meta"
    meta.mkdir(parents=True)
    (meta / "ddragon_runes.json").write_bytes(payload)
    return tmp_path


# --- the empty shape -------------------------------------------------------

def test_empty_brief_is_a_fresh_object_every_call():
    """dict(_EMPTY) was a SHALLOW copy: a caller appending to the returned
    build list wrote into the module constant, so every later failed brief
    carried that item."""
    first = m.brief_deterministic(None, [], [], "", "sr")
    assert first == _SHAPE
    first["build"].append("Infinity Edge")
    first["runes"]["keystone"] = "Conqueror"
    second = m.brief_deterministic(None, [], [], "", "sr")
    assert second == _SHAPE
    assert m._EMPTY == _SHAPE


@pytest.mark.parametrize("champ", [None, 123, "", "   ", ["Jinx"], True])
def test_non_text_or_blank_champ_is_the_empty_shape_without_a_resolver_call(champ):
    with mock.patch("coaches.loadout_resolver.resolve") as res:
        assert m.brief_deterministic(champ, [], [], "", "sr") == _SHAPE
    res.assert_not_called()


# --- keystone map ----------------------------------------------------------

def test_keystone_map_reads_a_bom_file(tmp_path):
    """read_text(encoding="utf-8") kept the BOM PowerShell 5.1 writes, so
    json.loads raised and every keystone read as blank."""
    root = _runes_dir(tmp_path, b"\xef\xbb\xbf" + json.dumps(_RUNES_JSON).encode())
    with mock.patch.object(m, "APP_DIR", root):
        assert m._keystone_id_to_name() == {8005: "Press the Attack",
                                            8008: "Lethal Tempo"}


def test_keystone_map_one_bad_tree_or_rune_keeps_the_rest(tmp_path):
    """One malformed tree raised out of the loop and lost EVERY keystone; a
    bool id was stored (True == 1) and a non-text name became the keystone."""
    trees = [
        "junk",
        {"slots": "x"},
        {"slots": ["not-a-dict"]},
        {"slots": [{"runes": "x"}]},
        {"slots": [{"runes": [
            "junk",
            {"id": True, "name": "Bool Id"},
            {"id": 8010, "name": {"a": 1}},
            {"id": 8011, "name": "   "},
            {"id": "8012", "name": "String Id"},
            {"id": 8005, "name": " Press the Attack "},
        ]}]},
    ]
    root = _runes_dir(tmp_path, json.dumps(trees).encode())
    with mock.patch.object(m, "APP_DIR", root):
        assert m._keystone_id_to_name() == {8005: "Press the Attack"}


def test_keystone_map_non_list_root_reads_empty(tmp_path):
    root = _runes_dir(tmp_path, b'{"slots": []}')
    with mock.patch.object(m, "APP_DIR", root):
        assert m._keystone_id_to_name() == {}


def test_keystone_map_failure_is_retried_not_cached_for_the_process(tmp_path):
    """A missing / mid-write runes file at first use pinned an EMPTY map for
    the life of the process. Now a failure is retried after the window, and
    not re-read inside it (no disk read per brief)."""
    clock = [1000.0]
    with mock.patch.object(m, "APP_DIR", tmp_path), \
            mock.patch.object(m, "_monotonic", lambda: clock[0]):
        assert m._keystone_id_to_name() == {}
        _runes_dir(tmp_path, json.dumps(_RUNES_JSON).encode())
        clock[0] += m._KEYSTONE_RETRY_S - 1
        assert m._keystone_id_to_name() == {}
        clock[0] += 2
        assert m._keystone_id_to_name()[8005] == "Press the Attack"
        # A good map is cached: removing the file changes nothing.
        (tmp_path / "data" / "meta" / "ddragon_runes.json").unlink()
        clock[0] += 10 * m._KEYSTONE_RETRY_S
        assert m._keystone_id_to_name()[8008] == "Lethal Tempo"


# --- runes -----------------------------------------------------------------

@pytest.mark.parametrize("rune_cmd", [["x"], "x", 5, None])
def test_runes_from_a_non_dict_cmd_is_the_blank_runes_shape(rune_cmd):
    assert m._runes_from_cmd(rune_cmd) == {
        "keystone": "", "primary_tree": "", "secondary_tree": "", "shards": []}


@pytest.mark.parametrize("cmd", [
    {"perk_ids": [[1], 2, 3]},
    {"perk_ids": [{"a": 1}]},
    {"primary_id": [8000], "sub_id": {"x": 1}},
    {"perk_ids": "8005 5008 5005"},
    {"perk_ids": 8005},
])
def test_runes_wrong_typed_fields_never_raise(cmd):
    """An unhashable perk or tree id raised TypeError and lost the whole brief
    (build included); a string perk_ids was walked per character."""
    out = m._runes_from_cmd(cmd)
    assert out["keystone"] == ""
    assert out["primary_tree"] == ""
    assert out["secondary_tree"] == ""
    assert out["shards"] == []


def test_runes_bool_tree_id_is_not_a_tree():
    with mock.patch.dict(m._TREE_ID_TO_NAME, {1: "One"}):
        assert m._runes_from_cmd({"primary_id": True})["primary_tree"] == ""
        assert m._runes_from_cmd({"primary_id": 1})["primary_tree"] == "One"


# --- ally notes -------------------------------------------------------------

@pytest.mark.parametrize("allies", ["Leona", {"Leona": 1}, 7, None])
def test_non_list_allies_give_no_notes(allies):
    """A bare string was walked per character ("L is on your team")."""
    assert m._ally_notes("Jinx", allies) == ""


def test_padded_ally_names_resolve_and_self_stays_excluded():
    out = m._ally_notes("Jinx", [" Jinx ", " Leona "])
    assert "Jinx" not in out
    assert out.startswith("Leona is your main engage")


def test_tag_loader_failure_reads_as_no_notes():
    with mock.patch("core.archetype_picks._load_champion_tags",
                    side_effect=RuntimeError("boom")):
        assert m._ally_notes("Jinx", ["Leona"]) == ""


def test_non_list_tags_entry_is_not_read_per_character():
    """A string tags value read its first CHARACTER as the tag, which maps to
    the "carry" fallback, so a support was called the main carry."""
    with mock.patch("core.archetype_picks._load_champion_tags",
                    return_value={"Leona": "Tank"}):
        out = m._ally_notes("Jinx", ["Leona"])
    assert "main carry" not in out
    assert out == "Leona is on your team - coordinate around their kit."


def test_non_dict_tag_table_reads_as_untagged():
    with mock.patch("core.archetype_picks._load_champion_tags",
                    return_value=["Leona"]):
        assert m._ally_notes("Jinx", ["Leona"]) == (
            "Leona is on your team - coordinate around their kit.")


# --- one failing part never loses the others ---------------------------------

def test_runes_failure_keeps_build_and_notes():
    with mock.patch.object(m, "_runes_from_cmd", side_effect=RuntimeError("x")):
        out = m.brief_deterministic("Jinx", [], ["Leona", "Jinx"], "BOTTOM", "sr")
    assert out["build"]
    assert out["runes"] == {}
    assert "Leona" in out["ally_notes"]


def test_notes_failure_keeps_build_and_runes():
    with mock.patch.object(m, "_ally_notes", side_effect=RuntimeError("x")):
        out = m.brief_deterministic("Jinx", ["Darius", "Garen", "Zed"],
                                    ["Leona"], "BOTTOM", "sr")
    assert out["build"]
    assert out["runes"]["primary_tree"]
    assert out["ally_notes"] == "Enemy comp is AD-heavy - prioritize armor."


def _resolved(raw_items):
    return {"ok": True, "raw_items": raw_items, "rune_cmd": {}}


@pytest.mark.parametrize(("raw_items", "build"), [
    ("Infinity Edge", []),
    ({"Infinity Edge": 1}, []),
    (["  ", " Infinity Edge ", None, 3, "Bloodthirster"],
     ["Infinity Edge", "Bloodthirster"]),
])
def test_build_only_carries_real_item_names(raw_items, build):
    """A string raw_items was split into one build entry per character."""
    with mock.patch("coaches.loadout_resolver.default_variant", return_value=""), \
            mock.patch("coaches.loadout_resolver.resolve",
                       return_value=_resolved(raw_items)):
        assert m.brief_deterministic("Jinx", [], [], "", "sr")["build"] == build


def test_padded_champ_is_stripped_before_resolving():
    with mock.patch("coaches.loadout_resolver.default_variant",
                    return_value="") as dv, \
            mock.patch("coaches.loadout_resolver.resolve",
                       return_value=_resolved(["Infinity Edge"])) as res:
        m.brief_deterministic(" Jinx ", [], [], "", "sr")
    assert dv.call_args.args[0] == "Jinx"
    assert res.call_args.args[0] == "Jinx"

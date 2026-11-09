"""s144 true-audit (S144-T-604): core/laning_verdicts.py input-shape hardening.

``laning_choices`` runs inside dashboard/_deterministic_coaching.py
``_compute_uncached`` on every coach refresh, and that whole fan-out sits under
one ``try``: a raise from this module blanks the ENTIRE deterministic result
(choices, callouts, build and objective rows), not just the laning chips. The
module docstring promises "it never raises". Measured on the old module, it
did raise on:

  * a non-finite or overflowing ``net_swing`` (OverflowError in round());
  * a non-finite ``level`` (OverflowError in int());
  * a scalar ``my_item_ids`` (TypeError) and a scalar ``owned`` (TypeError);
  * a non-str ``build_next_item`` (AttributeError on .strip()) or ``trigger``
    (pydantic ValidationError);
  * an items_index that is a list, or whose ``byId`` is a list (AttributeError);
  * a non-dict matchup result with ``apply_cv`` on (AttributeError);
  * an unhashable champion in ``_next_build_item`` (TypeError).

and it served fabricated or wrong-shaped values on:

  * ANY unknown verdict string (or a non-str verdict) -> the "Trade even" pair,
    although the DS engine emits exactly all_in / trade / back_off / even;
  * a bool / numeric-string / out-of-range ``net_swing`` -> "+100%", "+5000%";
  * a dict / None / blank enemy or champion -> its ``str()`` sent to the
    engine as a champion name ("None", "{'championName': ...}");
  * a str ``my_item_ids`` -> one id per character; dicts / bools -> their str;
  * a level of -5 or 101 -> sent as is; a bool level -> 1 over a real my_level;
  * a non-str / path-shaped mode -> sent to the engine and spliced into the
    build_orders file name; a path-shaped current.txt patch read a JSON file
    outside the patch directory;
  * a str ``balanced`` path -> one item per character; a non-str byId name
    (dict, int) -> returned as the item "name".
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.laning_verdicts as lv

_INF = float("inf")
_NAN = float("nan")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _mdict(verdict: object = "trade", net_swing: object = 0.25) -> dict:
    return {"verdict": verdict, "net_swing": net_swing}


class _Recorder:
    """matchup() stand-in that records its call and returns ``result``."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


@pytest.fixture
def ds_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated DS data dir + items_index; returns the DS dir."""
    ds = tmp_path / "ds"
    (ds / "16.11.1").mkdir(parents=True)
    (ds / "current.txt").write_text("16.11.1", encoding="utf-8")
    idx = tmp_path / "items_index.json"
    idx.write_text(json.dumps({"byId": {
        "3020": "Sorcerer's Shoes",
        "3089": "Rabadon's Deathcap",
        "3157": "Zhonya's Hourglass",
    }}), encoding="utf-8")
    monkeypatch.setattr(lv, "_DS_DATA_DIR", ds)
    monkeypatch.setattr(lv, "_ITEMS_INDEX_PATH", idx)
    return ds


def _write_orders(ds: Path, champ_orders: object, mode: str = "sr",
                  patch: str = "16.11.1") -> None:
    (ds / patch).mkdir(parents=True, exist_ok=True)
    doc = {"build_orders": {"Ahri": champ_orders}}
    (ds / patch / f"build_orders_{mode}.json").write_text(
        json.dumps(doc), encoding="utf-8")


@pytest.fixture
def rec(ds_tree: Path, monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    r = _Recorder(_mdict())
    monkeypatch.setattr(lv, "matchup", r)
    return r


_BASE = {"my_champion": "Ahri", "enemy_comp": ["Zed"]}


# --------------------------------------------------------------------------
# _fmt_swing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", [_INF, -_INF, 10 ** 400, "1e400"])
def test_fmt_swing_non_finite_or_huge_never_raises(value: object) -> None:
    assert lv._fmt_swing(value) == ""


@pytest.mark.parametrize("value", [True, False, "0.5", b"0.5", [0.5], None, _NAN])
def test_fmt_swing_non_number_reads_missing(value: object) -> None:
    assert lv._fmt_swing(value) == ""


@pytest.mark.parametrize("value", [50, -1.5, 1.0001, -2])
def test_fmt_swing_outside_unit_interval_reads_missing(value: object) -> None:
    assert lv._fmt_swing(value) == ""


@pytest.mark.parametrize("value, text", [
    (0.34, "+34% net HP"), (-0.2, "-20% net HP"), (1, "+100% net HP"),
    (-1, "-100% net HP"), (0, "+0% net HP"), (0.0, "+0% net HP"),
])
def test_fmt_swing_valid_values_unchanged(value: object, text: str) -> None:
    assert lv._fmt_swing(value) == text


# --------------------------------------------------------------------------
# verdict_to_choices
# --------------------------------------------------------------------------

@pytest.mark.parametrize("verdict", ["error", "draw", "unknown", "allin", "even!"])
def test_unknown_verdict_serves_nothing(verdict: str) -> None:
    assert lv.verdict_to_choices(_mdict(verdict)) == []


@pytest.mark.parametrize("verdict", [["all_in"], 1, {"v": "trade"}, True])
def test_non_str_verdict_serves_nothing(verdict: object) -> None:
    assert lv.verdict_to_choices(_mdict(verdict)) == []


@pytest.mark.parametrize("verdict, label", [
    (" ALL_IN ", "All in now"), ("Trade", "Trade now"),
    ("back_off", "Back off"), ("EVEN", "Trade even"),
])
def test_known_verdicts_still_normalised(verdict: str, label: str) -> None:
    out = lv.verdict_to_choices(_mdict(verdict))
    assert [c.key for c in out] == ["A", "B"]
    assert out[0].label == label


@pytest.mark.parametrize("swing", [_INF, -_INF, "1e400"])
def test_verdict_to_choices_non_finite_swing_drops_clause(swing: object) -> None:
    out = lv.verdict_to_choices(_mdict("trade", swing))
    assert out[0].expected_outcome == "net HP swing in your favor"


@pytest.mark.parametrize("item", [5, {"a": 1}, ["Rabadon's Deathcap"], True])
def test_non_str_build_item_is_dropped(item: object) -> None:
    out = lv.verdict_to_choices(_mdict(), build_next_item=item)
    assert [c.key for c in out] == ["A", "B"]


def test_str_build_item_still_appended() -> None:
    out = lv.verdict_to_choices(_mdict(), build_next_item="  Zhonya's Hourglass ")
    assert [c.key for c in out] == ["A", "B", "C"]
    assert out[2].label == "Buy Zhonya's Hourglass"


@pytest.mark.parametrize("trigger", [7, None, ["Zed"], {"t": 1}])
def test_non_str_trigger_is_not_stamped(trigger: object) -> None:
    out = lv.verdict_to_choices(_mdict(), trigger=trigger)  # type: ignore[arg-type]
    assert [c.trigger for c in out] == ["", ""]


# --------------------------------------------------------------------------
# laning_choices - level
# --------------------------------------------------------------------------

def _levels(r: _Recorder) -> tuple:
    kw = r.calls[-1][1]
    return kw["level_a"], kw["level_b"]


@pytest.mark.parametrize("level", [_INF, -_INF, _NAN, "1e400"])
def test_non_finite_level_reads_one(rec: _Recorder, level: object) -> None:
    assert lv.laning_choices({**_BASE, "level": level})
    assert _levels(rec) == (1, 1)


@pytest.mark.parametrize("level", [-5, 101, 10 ** 30, -0.5, "abc", "-3", [6], {}])
def test_out_of_range_or_junk_level_reads_one(rec: _Recorder, level: object) -> None:
    lv.laning_choices({**_BASE, "level": level})
    assert _levels(rec) == (1, 1)


def test_bool_level_falls_through_to_my_level(rec: _Recorder) -> None:
    lv.laning_choices({**_BASE, "level": True, "my_level": 7})
    assert _levels(rec) == (7, 7)


@pytest.mark.parametrize("gs_extra, want", [
    ({"level": 6}, 6), ({"level": 6.9}, 6), ({"level": "7"}, 7),
    ({"level": 0, "my_level": 9}, 9), ({"my_level": 12}, 12), ({}, 1),
    ({"level": 18}, 18), ({"level": 100}, 100),
])
def test_valid_levels_unchanged(rec: _Recorder, gs_extra: dict, want: int) -> None:
    lv.laning_choices({**_BASE, **gs_extra})
    assert _levels(rec) == (want, want)


# --------------------------------------------------------------------------
# laning_choices - item ids
# --------------------------------------------------------------------------

def _ids(r: _Recorder) -> list:
    return r.calls[-1][1]["item_ids_a"]


@pytest.mark.parametrize("ids", [5, "3089", {"3089": 1}, True, 3.5])
def test_scalar_item_ids_send_none(rec: _Recorder, ids: object) -> None:
    lv.laning_choices({**_BASE, "my_item_ids": ids})
    assert _ids(rec) == []


def test_item_ids_keep_only_id_shaped_entries(rec: _Recorder) -> None:
    lv.laning_choices({**_BASE, "my_item_ids": [
        {"a": 1}, 3089, True, "3020", " 1001 ", 0, None, -5, "abc", 2.0,
        "12345678", (3157,),
    ]})
    assert _ids(rec) == ["3089", "3020", "1001"]


def test_item_ids_tuple_accepted(rec: _Recorder) -> None:
    lv.laning_choices({**_BASE, "my_item_ids": (3089, "3020")})
    assert _ids(rec) == ["3089", "3020"]


# --------------------------------------------------------------------------
# laning_choices - champion names
# --------------------------------------------------------------------------

def _champs(r: _Recorder) -> tuple:
    return r.calls[-1][0][:2]


@pytest.mark.parametrize("comp", [
    [{"championName": "Zed"}], [None], ["   "], [5], [["Zed"]], ["Ze\x00d"],
    ["x" * 65],
])
def test_no_valid_enemy_serves_nothing(rec: _Recorder, comp: list) -> None:
    assert lv.laning_choices({**_BASE, "enemy_comp": comp}) == []
    assert rec.calls == []


@pytest.mark.parametrize("comp", [
    [None, "Zed"], ["  ", "Zed"], [{"x": 1}, "Zed"], [" Zed "], [["l"], "Zed"],
])
def test_first_valid_enemy_is_used(rec: _Recorder, comp: list) -> None:
    lv.laning_choices({**_BASE, "enemy_comp": comp})
    assert _champs(rec) == ("Ahri", "Zed")


def test_same_role_pick_still_works(rec: _Recorder) -> None:
    gs = {**_BASE, "enemy_comp": ["Lux", "Zed"], "role": "MID",
          "enemy_roles": {"Lux": "support", "Zed": " mid "}}
    lv.laning_choices(gs, mode="SR")
    assert _champs(rec) == ("Ahri", "Zed")


def test_same_role_ignores_non_str_role_keys(rec: _Recorder) -> None:
    gs = {**_BASE, "enemy_comp": ["Lux", "Zed"], "role": "mid",
          "enemy_roles": {5: "mid", ("Zed",): "mid"}}
    lv.laning_choices(gs, mode="SR")
    assert _champs(rec) == ("Ahri", "Lux")


def test_localised_names_accepted(rec: _Recorder) -> None:
    gs = {"my_champion": "Kai'Sa", "enemy_comp": ["Nunu & Willump"]}
    lv.laning_choices(gs)
    assert _champs(rec) == ("Kai'Sa", "Nunu & Willump")


@pytest.mark.parametrize("bad", [{"x": 1}, ["Ahri"], 0, "   ", "A\nhri", "x" * 65])
def test_bad_my_champion_falls_back_to_champion(rec: _Recorder, bad: object) -> None:
    lv.laning_choices({"my_champion": bad, "champion": "Ahri", "enemy_comp": ["Zed"]})
    assert _champs(rec) == ("Ahri", "Zed")


@pytest.mark.parametrize("bad", [{"x": 1}, 5, None, "", "\t"])
def test_no_valid_my_champion_serves_nothing(rec: _Recorder, bad: object) -> None:
    assert lv.laning_choices({"my_champion": bad, "enemy_comp": ["Zed"]}) == []
    assert rec.calls == []


# --------------------------------------------------------------------------
# laning_choices - mode and engine result
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [5, None, "", "../x", "S R", "sr\x00", "A" * 17])
def test_bad_mode_serves_nothing_and_skips_engine(rec: _Recorder, mode: object) -> None:
    assert lv.laning_choices(dict(_BASE), mode=mode) == []  # type: ignore[arg-type]
    assert rec.calls == []


@pytest.mark.parametrize("mode", ["SR", "ARAM", "ARENA", "aram", "CLASSIC"])
def test_valid_modes_pass_through(rec: _Recorder, mode: str) -> None:
    assert lv.laning_choices(dict(_BASE), mode=mode)
    assert rec.calls[-1][1]["mode"] == mode


@pytest.mark.parametrize("apply_cv", [False, True])
@pytest.mark.parametrize("result", [["x"], "trade", 5, True])
def test_non_dict_engine_result_serves_nothing(
    ds_tree: Path, monkeypatch: pytest.MonkeyPatch, result: object, apply_cv: bool,
) -> None:
    monkeypatch.setattr(lv, "matchup", _Recorder(result))
    assert lv.laning_choices(dict(_BASE), apply_cv=apply_cv, vision_state={}) == []


# --------------------------------------------------------------------------
# _next_build_item
# --------------------------------------------------------------------------

def test_next_build_item_characterisation(ds_tree: Path) -> None:
    _write_orders(ds_tree, {"balanced": [3020, "3089"]})
    assert lv._next_build_item("Ahri", ["Sorcerer's Shoes"], mode="sr") == (
        "Rabadon's Deathcap")
    assert lv._next_build_item("Ahri", (), mode="SR") == "Sorcerer's Shoes"


@pytest.mark.parametrize("idx_doc", [[1, 2], {"byId": [1]}, {"byId": "x"}, "s", 5])
def test_wrong_shaped_items_index_reads_none(ds_tree: Path, idx_doc: object) -> None:
    _write_orders(ds_tree, {"balanced": [3020]})
    lv._ITEMS_INDEX_PATH.write_text(json.dumps(idx_doc), encoding="utf-8")
    assert lv._next_build_item("Ahri", [], mode="sr") is None


def test_non_str_or_blank_byid_names_are_skipped(ds_tree: Path) -> None:
    _write_orders(ds_tree, {"balanced": [1, 2, 3, 4, 3157]})
    lv._ITEMS_INDEX_PATH.write_text(json.dumps({"byId": {
        "1": {"name": "x"}, "2": 7, "3": "   ", "4": ["n"],
        "3157": "Zhonya's Hourglass",
    }}), encoding="utf-8")
    assert lv._next_build_item("Ahri", [], mode="sr") == "Zhonya's Hourglass"


def test_str_balanced_path_is_not_iterated_per_character(ds_tree: Path) -> None:
    _write_orders(ds_tree, {"balanced": "30"})
    lv._ITEMS_INDEX_PATH.write_text(json.dumps({"byId": {
        "3": "Three", "0": "Zero"}}), encoding="utf-8")
    assert lv._next_build_item("Ahri", [], mode="sr") is None


def test_non_list_balanced_falls_back_to_a_list_path(ds_tree: Path) -> None:
    _write_orders(ds_tree, {"balanced": {"3020": 1}, "ad_heavy": [3089]})
    assert lv._next_build_item("Ahri", [], mode="sr") == "Rabadon's Deathcap"


@pytest.mark.parametrize("ids", [[[1], "3089"], [True, "3089"], [None, 3089]])
def test_junk_ids_in_path_skipped(ds_tree: Path, ids: list) -> None:
    _write_orders(ds_tree, {"balanced": ids})
    assert lv._next_build_item("Ahri", [], mode="sr") == "Rabadon's Deathcap"


@pytest.mark.parametrize("owned", [5, 3.5, True, {"Sorcerer's Shoes": 1}, "Sorcerer's Shoes"])
def test_non_list_owned_reads_as_nothing_owned(ds_tree: Path, owned: object) -> None:
    _write_orders(ds_tree, {"balanced": [3020, 3089]})
    assert lv._next_build_item("Ahri", owned, mode="sr") == "Sorcerer's Shoes"


def test_bool_in_owned_is_not_an_owned_name(ds_tree: Path) -> None:
    # Old: isinstance(True, int) let a bool through, normalised to "true",
    # which matched an item whose name normalises the same way.
    _write_orders(ds_tree, {"balanced": [3020, 3089]})
    lv._ITEMS_INDEX_PATH.write_text(json.dumps({"byId": {
        "3020": "True", "3089": "Rabadon's Deathcap"}}), encoding="utf-8")
    assert lv._next_build_item("Ahri", [True], mode="sr") == "True"


@pytest.mark.parametrize("champ", [["Ahri"], {"Ahri": 1}, 5, None])
def test_non_str_champion_reads_none(ds_tree: Path, champ: object) -> None:
    _write_orders(ds_tree, {"balanced": [3020]})
    assert lv._next_build_item(champ, [], mode="sr") is None  # type: ignore[arg-type]


def test_path_shaped_mode_cannot_leave_the_patch_dir(ds_tree: Path) -> None:
    # Old: f"build_orders_{mode}.json" with mode "x/../../evil" resolved to
    # <ds>/evil.json (a lexical walk) and that file was read as build orders.
    (ds_tree / "evil.json").write_text(json.dumps(
        {"build_orders": {"Ahri": {"balanced": [3089]}}}), encoding="utf-8")
    assert lv._next_build_item("Ahri", [], mode="x/../../evil") is None
    assert lv._next_build_item("Ahri", [], mode=5) is None  # type: ignore[arg-type]


@pytest.mark.parametrize("patch", ["..", ".", "a/b", "a\\b", "", "16.11.1\x00", "x" * 33])
def test_path_shaped_patch_is_refused(ds_tree: Path, patch: str) -> None:
    # A build_orders file one level up: the old code read it via patch "..".
    (ds_tree.parent / "build_orders_sr.json").write_text(json.dumps(
        {"build_orders": {"Ahri": {"balanced": [3089]}}}), encoding="utf-8")
    (ds_tree / "current.txt").write_text(patch, encoding="utf-8")
    assert lv._resolve_patch() is None
    assert lv._next_build_item("Ahri", [], mode="sr") is None


def test_real_patch_shapes_accepted(ds_tree: Path) -> None:
    for patch in ("16.11.1", "26.21", "16.11.1-pbe"):
        (ds_tree / "current.txt").write_text(f" {patch}\n", encoding="utf-8")
        assert lv._resolve_patch() == patch


# --------------------------------------------------------------------------
# property: laning_choices never raises on a junk game_state
# --------------------------------------------------------------------------

_JUNK = [None, True, 5, -1, _INF, _NAN, 10 ** 400, "x", "", [], {}, [None],
         [{}], [_INF], {"a": [1]}, object(), b"bytes", ("t",)]
_KEYS = ["my_champion", "champion", "enemy_comp", "enemy_roles", "role",
         "level", "my_level", "items", "my_items", "my_item_ids"]


@pytest.mark.parametrize("key", _KEYS)
def test_laning_choices_never_raises_on_junk(
    ds_tree: Path, monkeypatch: pytest.MonkeyPatch, key: str,
) -> None:
    _write_orders(ds_tree, {"balanced": [3020, 3089]}, mode="sr")
    for result in (_mdict("all_in", _INF), _mdict("trade", 0.3), _mdict(5, "x")):
        monkeypatch.setattr(lv, "matchup", _Recorder(result))
        for junk in _JUNK:
            gs = {**_BASE, "items": ["Sorcerer's Shoes"], "my_item_ids": [3020],
                  key: junk}
            out = lv.laning_choices(gs, mode="SR")
            assert isinstance(out, list)
            for c in out:
                assert isinstance(c.label, str) and isinstance(c.trigger, str)

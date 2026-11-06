"""Lane 8 (true-audit) s144 cycle 116 - core/daemon_slayer_resolver.py.

The resolver turns Live Client item display names into DDragon ids for every
coach that calls Daemon Slayer, and sums item HP for the Giant Slayer amp. It
reads three files RC does not author byte-for-byte (``items_index.json``, the
patch-current DDragon ``items.json`` and ``current.txt``), so every finding
below is "merely wrong input" reaching a path that promised to fail soft.

RM-1464 import-time derivation raised on a junk row (``stats`` not a
           mapping, ``tags`` not a list) or a too-deep document, although its
           docstring promises the floor "rather than raising" because a throw
           at import takes every coach down.
RM-1465 the HP / per-mode loader raised AttributeError / TypeError out of
           ``name_to_id(mode=...)`` and ``bonus_hp_for_id`` on a non-object
           document, a non-mapping ``data``, ``stats`` or ``maps``, or a
           non-string ``name``.
RM-1466 a NaN, infinite, negative or boolean ``FlatHPPoolMod`` was stored,
           so ``total_bonus_hp`` returned NaN / inf into the engine.
RM-1467 the legacy index loader raised on a non-object document or a
           non-mapping ``byName``, and turned a dict / bool value into a
           garbage id string ("{'x': 1}", "True").
RM-1468 a malformed or HP-empty file was never remembered, so EVERY lookup
           re-read and re-parsed the whole items.json and logged a WARNING
           (six names per coach tick); a transient OSError must still retry.
RM-1469 ``current.txt`` written by PowerShell 5.1 carries a BOM that stayed
           in the patch token (items.json "missing", HP and per-mode index
           silently empty), and a path-segment token escaped the data dir.
RM-1470 junk call args: a non-str name or mode raised, a bare string to
           ``resolve_many`` / ``resolve_inventory`` / ``total_bonus_hp`` was
           iterated character by character, a non-iterable raised.
"""
from __future__ import annotations

import importlib
import json
import logging
import math
import pathlib

import pytest

PATCH = "9.9.1"

HEARTSTEEL = {
    "name": "Heartsteel",
    "stats": {"FlatHPPoolMod": 900},
    "maps": {"11": True, "12": True, "30": False},
    "tags": ["Health"],
}
RIFTMAKER = {
    "name": "Riftmaker",
    "stats": {"FlatHPPoolMod": 350},
    "maps": {"11": True},
    "tags": ["Health"],
}


@pytest.fixture
def res(tmp_path, monkeypatch):
    m = importlib.import_module("core.daemon_slayer_resolver")
    ds = tmp_path / "ds"
    (ds / PATCH).mkdir(parents=True)
    (ds / "current.txt").write_bytes(PATCH.encode("ascii"))
    monkeypatch.setattr(m, "_DS_DATA_DIR", ds)
    monkeypatch.setattr(m, "_PATCH_FILE", ds / "current.txt")
    monkeypatch.setattr(m, "_INDEX_PATH", tmp_path / "items_index.json")
    for name, value in (
        ("_cache", {}), ("_cache_mtime", 0.0), ("_hp_cache", {}),
        ("_hp_cache_mtime", 0.0), ("_hp_cache_patch", ""),
        ("_byname_by_mode", {}),
    ):
        monkeypatch.setattr(m, name, value)
    for name in ("_index_failed_sig", "_hp_failed_sig"):
        monkeypatch.setattr(m, name, None, raising=False)
    m._test_ds = ds
    return m


def _items(m, payload) -> pathlib.Path:
    path = m._test_ds / PATCH / "items.json"
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_bytes(text.encode("utf-8"))
    return path


def _index(m, payload) -> pathlib.Path:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    m._INDEX_PATH.write_bytes(text.encode("utf-8"))
    return m._INDEX_PATH


def _count_reads(monkeypatch, target: pathlib.Path) -> list:
    seen: list = []
    real = pathlib.Path.read_text

    def counting(self, *a, **kw):
        if pathlib.Path(self) == target:
            seen.append(1)
        return real(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "read_text", counting)
    return seen


# --- RM-1464 import-time derivation ------------------------------------

def test_derivation_survives_junk_rows(res, tmp_path):
    path = _items(res, {"data": {
        "1": {"stats": [1], "tags": ["Consumable"]},
        "2": {"stats": {}, "tags": 5},
        "3": {"stats": {}, "tags": "Consumable"},
        "4": {"stats": {}, "tags": ["Trinket"]},
        "2052": {"stats": {}, "tags": [], "consumed": True, "inStore": False},
    }})
    out = res._derive_non_inventory_ids(path)
    assert out >= res._NON_INVENTORY_BASE_IDS
    assert {"4", "2052"} <= out
    # A junk stats block is not proof the row is stat-less: keep its slot.
    assert "1" not in out
    # A bare-string tag is not a tag list; substring matching is refused.
    assert "3" not in out
    assert "2" not in out


def test_derivation_survives_a_too_deep_document(res):
    path = _items(res, "[" * 200000)
    assert res._derive_non_inventory_ids(path) == res._NON_INVENTORY_BASE_IDS


# --- RM-1465 HP / per-mode loader shape --------------------------------

@pytest.mark.parametrize("payload", [
    [1, 2],
    {"data": [HEARTSTEEL]},
    {"data": "rows"},
    "[" * 200000,
], ids=["doc-list", "data-list", "data-str", "too-deep"])
def test_hp_loader_degrades_on_a_malformed_document(res, payload):
    _items(res, payload)
    assert res.bonus_hp_for_id("3084") == 0.0
    assert res.name_to_id("Heartsteel", mode="sr") is None


def test_hp_loader_skips_junk_rows_and_keeps_good_ones(res):
    _items(res, {"data": {
        "3084": HEARTSTEEL,
        "1": {"name": "Junk Stats", "stats": [900], "maps": {"11": True}},
        "2": {"name": "Junk Maps", "stats": {}, "maps": ["11"]},
        "3": {"name": 42, "stats": {}, "maps": {"11": True}},
        "4": {"name": ["x"], "stats": {}, "maps": {"11": True}},
    }})
    assert res.bonus_hp_for_id("3084") == 900.0
    assert res.name_to_id("Heartsteel", mode="sr") == "3084"
    assert res.bonus_hp_for_id("1") == 0.0
    assert res.name_to_id("Junk Maps", mode="sr") is None


# --- RM-1466 HP value validation ---------------------------------------

@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "-100", "true"])
def test_nonsense_hp_is_dropped(res, raw):
    text = (
        '{"data": {"3084": {"name": "Heartsteel", "maps": {"11": true},'
        ' "stats": {"FlatHPPoolMod": 900}},'
        ' "9": {"name": "Bad", "maps": {"11": true},'
        ' "stats": {"FlatHPPoolMod": ' + raw + '}}}}'
    )
    _items(res, text)
    assert res.bonus_hp_for_id("9") == 0.0
    total = res.total_bonus_hp(["3084", "9"])
    assert math.isfinite(total)
    assert total == 900.0


def test_numeric_string_hp_still_parses(res):
    _items(res, {"data": {"3084": dict(HEARTSTEEL, stats={"FlatHPPoolMod": "900"})}})
    assert res.bonus_hp_for_id("3084") == 900.0


# --- RM-1467 legacy index shape ----------------------------------------

@pytest.mark.parametrize("payload", [
    [1], {"byName": ["heartsteel"]}, {"byName": "x"}, "[" * 200000,
], ids=["doc-list", "byname-list", "byname-str", "too-deep"])
def test_index_loader_degrades_on_a_malformed_document(res, payload):
    _index(res, payload)
    assert res.name_to_id("Heartsteel") is None


def test_index_loader_keeps_only_scalar_ids(res):
    _index(res, {"byName": {
        "heartsteel": {"x": 1},
        "riftmaker": True,
        "sunfireaegis": 3068,
        "infinityedge": " 3031 ",
        "blank": "  ",
        "floaty": 3.5,
    }})
    assert res.name_to_id("Heartsteel") is None
    assert res.name_to_id("Riftmaker") is None
    assert res.name_to_id("Sunfire Aegis") == "3068"
    assert res.name_to_id("Infinity Edge") == "3031"
    assert res.name_to_id("Blank") is None
    assert res.name_to_id("Floaty") is None


# --- RM-1468 no re-parse storm -----------------------------------------

def test_malformed_items_json_is_parsed_once_and_warned_once(
        res, monkeypatch, caplog):
    path = _items(res, "{not json")
    reads = _count_reads(monkeypatch, path)
    with caplog.at_level(logging.WARNING, logger="rc.core.daemon_slayer_resolver"):
        for _ in range(5):
            assert res.bonus_hp_for_id("3084") == 0.0
            assert res.name_to_id("Heartsteel", mode="sr") is None
    assert len(reads) == 1
    warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warned) == 1
    # Repairing the file (new size / mtime) is picked up on the next call.
    _items(res, {"data": {"3084": HEARTSTEEL}})
    assert res.bonus_hp_for_id("3084") == 900.0


def test_hp_empty_items_json_is_parsed_once(res, monkeypatch):
    path = _items(res, {"data": {"3071": {
        "name": "Black Cleaver", "stats": {"FlatPhysicalDamageMod": 40},
        "maps": {"11": True}}}})
    reads = _count_reads(monkeypatch, path)
    for _ in range(5):
        assert res.name_to_id("Black Cleaver", mode="sr") == "3071"
        assert res.bonus_hp_for_id("3071") == 0.0
    assert len(reads) == 1


def test_malformed_index_is_parsed_once_and_warned_once(res, monkeypatch, caplog):
    path = _index(res, "{not json")
    reads = _count_reads(monkeypatch, path)
    with caplog.at_level(logging.WARNING, logger="rc.core.daemon_slayer_resolver"):
        for _ in range(5):
            assert res.name_to_id("Heartsteel") is None
    assert len(reads) == 1
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1
    _index(res, {"byName": {"heartsteel": "3084"}})
    assert res.name_to_id("Heartsteel") == "3084"


def test_empty_index_is_parsed_once(res, monkeypatch):
    path = _index(res, {"byName": {}})
    reads = _count_reads(monkeypatch, path)
    for _ in range(5):
        assert res.name_to_id("Heartsteel") is None
    assert len(reads) == 1


def test_undecodable_files_degrade_and_are_read_once(res, monkeypatch):
    items = res._test_ds / PATCH / "items.json"
    items.write_bytes(b"\xff\xfe{}")
    _index(res, "{}")
    res._INDEX_PATH.write_bytes(b"\xff\xfe{}")
    item_reads = _count_reads(monkeypatch, items)
    for _ in range(3):
        assert res.bonus_hp_for_id("3084") == 0.0
        assert res.name_to_id("Heartsteel") is None
    assert len(item_reads) == 1


def test_transient_read_error_is_retried(res, monkeypatch):
    path = _items(res, {"data": {"3084": HEARTSTEEL}})
    real = pathlib.Path.read_text
    state = {"fail": True}

    def flaky(self, *a, **kw):
        if pathlib.Path(self) == path and state["fail"]:
            state["fail"] = False
            raise PermissionError(13, "sharing violation")
        return real(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "read_text", flaky)
    assert res.bonus_hp_for_id("3084") == 0.0
    assert res.bonus_hp_for_id("3084") == 900.0


# --- RM-1469 patch token -----------------------------------------------

def test_current_txt_bom_is_stripped(res):
    res._PATCH_FILE.write_bytes(b"\xef\xbb\xbf" + PATCH.encode("ascii") + b"\r\n")
    _items(res, {"data": {"3084": HEARTSTEEL}})
    assert res._current_patch() == PATCH
    assert res._items_json_path() is not None
    assert res.bonus_hp_for_id("3084") == 900.0


@pytest.mark.parametrize("token", ["..", "../9.9.1", "a/b", "a\\b", "C:x", "..\\x"])
def test_path_segment_patch_token_is_refused(res, token):
    res._PATCH_FILE.write_bytes(token.encode("ascii"))
    assert res._current_patch() is None
    assert res._items_json_path() is None


# --- RM-1470 junk call args --------------------------------------------

@pytest.mark.parametrize("name", [3084, 3.5, {"Heartsteel": 1}, ["Heartsteel"], b"Heartsteel"])
def test_non_string_name_resolves_to_none(res, name):
    _index(res, {"byName": {"heartsteel": "3084"}})
    assert res.name_to_id(name) is None
    assert res.name_to_id(name, mode="sr") is None


@pytest.mark.parametrize("mode", [5, ["sr"], b"sr"])
def test_non_string_mode_falls_back_to_the_legacy_index(res, mode):
    _index(res, {"byName": {"heartsteel": "3084"}})
    assert res.name_to_id("Heartsteel", mode=mode) == "3084"


def test_bare_string_and_non_iterable_args(res):
    _index(res, {"byName": {"heartsteel": "3084", "healthpotion": "2003"}})
    _items(res, {"data": {"3084": HEARTSTEEL}})
    assert res.resolve_many("Heartsteel") == ["3084"]
    assert res.resolve_inventory("Heartsteel") == ["3084"]
    assert res.resolve_inventory("Health Potion") == []
    assert res.resolve_many(5) == []
    assert res.resolve_inventory(5) == []
    assert res.total_bonus_hp("3084") == 900.0
    assert res.total_bonus_hp(7) == 0.0
    assert res.resolve_many(["Heartsteel", None, 7, "Nope"]) == ["3084"]

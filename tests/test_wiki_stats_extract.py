"""Offline unit tests for tools/daemon_slayer_wiki_stats_extract.py (item 221).

NO NETWORK: every test either exercises a pure helper or monkeypatches the
module's ``_expand`` (the single network seam) with canned wiki responses.
The real wiki is edge-blocked from the build host; these tests pin the
parse / name-map / file-shape / fail-soft logic so a future host that can
reach wiki.gg runs a known-correct extractor.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TOOL_PATH = _PROJECT_ROOT / "tools" / "daemon_slayer_wiki_stats_extract.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ds_wiki_extract", _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


WX = _load_module()


# -- _parse_scalar -----------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("0.3", 0.3),
    ("0.30000001192093", 0.30000001192093),
    ("2500", 2500.0),
    ("0.30000001192093||", 0.30000001192093),   # trailing compound-get sep
    ("0.3|junk", 0.3),
    ("  0.25  ", 0.25),
    ("", None),
    ("   ", None),
    ("notanumber", None),
    ("|", None),
    (None, None),
])
def test_parse_scalar(raw, expected):
    assert WX._parse_scalar(raw) == expected


# -- _wiki_name --------------------------------------------------------

def test_wiki_name_uses_display_name():
    names = {"Kaisa": "Kai'Sa", "MonkeyKing": "Wukong", "Aatrox": "Aatrox"}
    assert WX._wiki_name("Kaisa", names) == "Kai'Sa"
    assert WX._wiki_name("MonkeyKing", names) == "Wukong"
    assert WX._wiki_name("Aatrox", names) == "Aatrox"


def test_wiki_name_falls_back_to_id_when_missing():
    assert WX._wiki_name("Unknown", {}) == "Unknown"


def test_wiki_name_override_wins(monkeypatch):
    monkeypatch.setitem(WX._WIKI_NAME_OVERRIDES, "Foo", "FooWikiTitle")
    assert WX._wiki_name("Foo", {"Foo": "FooDisplay"}) == "FooWikiTitle"


# -- _load_champion_ids (real abilities-file shape: champs under "data") -

def test_load_champion_ids_reads_data_container(tmp_path, monkeypatch):
    patch = "99.99.9"
    d = tmp_path / patch
    d.mkdir(parents=True)
    (d / "champion_abilities.json").write_text(json.dumps({
        "version": "x", "count": 2,
        "data": {"Zed": {"Q": {}}, "Aatrox": {"Q": {}}},
    }), encoding="utf-8")
    monkeypatch.setattr(WX, "DATA_DIR", tmp_path)
    assert WX._load_champion_ids(patch) == ["Aatrox", "Zed"]   # sorted


def test_load_champion_ids_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(WX, "DATA_DIR", tmp_path)
    with pytest.raises(SystemExit):
        WX._load_champion_ids("nope")


def test_load_champion_ids_empty_data_raises(tmp_path, monkeypatch):
    patch = "0.0.0"
    d = tmp_path / patch
    d.mkdir(parents=True)
    (d / "champion_abilities.json").write_text(json.dumps({"data": {}}), encoding="utf-8")
    monkeypatch.setattr(WX, "DATA_DIR", tmp_path)
    with pytest.raises(SystemExit):
        WX._load_champion_ids(patch)


def test_load_champion_ids_against_real_snapshot():
    """The committed 16.11.1 abilities file parses + yields >150 ids."""
    real = WX.DATA_DIR / "16.11.1" / "champion_abilities.json"
    if not real.exists():
        pytest.skip("16.11.1 abilities snapshot not present")
    ids = WX._load_champion_ids("16.11.1")
    assert len(ids) > 150
    assert "Aatrox" in ids
    assert ids == sorted(ids)


# -- _load_display_names (real meta_build mirror) ----------------------

def test_load_display_names_real_mirror():
    real = WX.META_DDRAGON_DIR / "16.11.1" / "champion.json"
    if not real.exists():
        pytest.skip("16.11.1 meta_build champion.json not present")
    names = WX._load_display_names("16.11.1")
    assert names.get("Kaisa") == "Kai'Sa"
    assert names.get("MonkeyKing") == "Wukong"
    assert names.get("Aatrox") == "Aatrox"


def test_load_display_names_falls_back_to_newest(tmp_path, monkeypatch):
    base = tmp_path / "ddragon"
    older = base / "1.0.0"
    older.mkdir(parents=True)
    (older / "champion.json").write_text(json.dumps({"data": {"Aatrox": {"name": "Aatrox"}}}), encoding="utf-8")
    monkeypatch.setattr(WX, "META_DDRAGON_DIR", base)
    names = WX._load_display_names("missing-patch")   # exact dir absent -> newest
    assert names["Aatrox"] == "Aatrox"


# -- _fetch_field (monkeypatched _expand, no network) ------------------

def test_fetch_field_bare(monkeypatch):
    monkeypatch.setattr(WX, "_expand", lambda c, f: "0.3" if f == "attack_cast_time" else "")
    assert WX._fetch_field("Aatrox", "attack_cast_time", stats_fallback=True) == 0.3


def test_fetch_field_stats_fallback(monkeypatch):
    calls = []

    def fake(champ, field):
        calls.append(field)
        return "2500" if field == "stats.missile_speed" else ""

    monkeypatch.setattr(WX, "_expand", fake)
    val = WX._fetch_field("Caitlyn", "missile_speed", stats_fallback=True)
    assert val == 2500.0
    assert calls == ["missile_speed", "stats.missile_speed"]


def test_fetch_field_no_fallback(monkeypatch):
    calls = []

    def fake(champ, field):
        calls.append(field)
        return ""

    monkeypatch.setattr(WX, "_expand", fake)
    assert WX._fetch_field("X", "missile_speed", stats_fallback=False) is None
    assert calls == ["missile_speed"]


# -- extract (monkeypatched _expand + file loaders, no network) --------

def _stub_loaders(monkeypatch, ids, names):
    monkeypatch.setattr(WX, "_load_champion_ids", lambda patch: ids)
    monkeypatch.setattr(WX, "_load_display_names", lambda patch: names)


def test_extract_happy(monkeypatch):
    _stub_loaders(monkeypatch, ["Aatrox", "Caitlyn"],
                  {"Aatrox": "Aatrox", "Caitlyn": "Caitlyn"})

    def fake(champ, field):
        table = {
            ("Aatrox", "attack_cast_time"): "0.3",
            ("Caitlyn", "attack_cast_time"): "0.30625",
            ("Caitlyn", "missile_speed"): "2500",
        }
        return table.get((champ, field), "")

    monkeypatch.setattr(WX, "_expand", fake)
    payload = WX.extract("16.11.1", sleep_s=0.0, limit=None, verbose=False)
    assert payload["_champ_count"] == 2
    assert payload["_with_cast_time"] == 2
    assert payload["_errors"] == []
    assert payload["champions"]["Aatrox"]["attack_cast_time"] == 0.3
    assert payload["champions"]["Aatrox"]["missile_speed"] is None        # melee
    assert payload["champions"]["Caitlyn"]["missile_speed"] == 2500.0
    assert payload["_fields"] == ["attack_cast_time", "missile_speed"]


def test_extract_failsoft_on_block(monkeypatch):
    """An edge-block (every call raises) records errors + 0 cast times, never raises."""
    _stub_loaders(monkeypatch, ["Aatrox"], {"Aatrox": "Aatrox"})

    def boom(champ, field):
        raise urllib_error_401()

    monkeypatch.setattr(WX, "_expand", boom)
    payload = WX.extract("16.11.1", sleep_s=0.0, limit=None, verbose=False)
    assert payload["_with_cast_time"] == 0
    assert len(payload["_errors"]) == 1
    assert payload["champions"]["Aatrox"]["attack_cast_time"] is None


def urllib_error_401():
    import urllib.error
    return urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)


def test_extract_limit(monkeypatch):
    _stub_loaders(monkeypatch, ["A", "B", "C", "D"], {})
    monkeypatch.setattr(WX, "_expand", lambda c, f: "0.25" if f == "attack_cast_time" else "")
    payload = WX.extract("p", sleep_s=0.0, limit=2, verbose=False)
    assert payload["_champ_count"] == 2


# -- ASCII hygiene (no em-dash / smart-quote repo rule) ----------------

def test_tool_is_ascii():
    raw = _TOOL_PATH.read_text(encoding="utf-8")
    nonascii = [(i, c) for i, c in enumerate(raw) if ord(c) > 127]
    assert not nonascii, f"non-ASCII in extractor: {nonascii[:5]}"


def test_test_file_is_ascii():
    raw = Path(__file__).read_text(encoding="utf-8")
    nonascii = [(i, c) for i, c in enumerate(raw) if ord(c) > 127]
    assert not nonascii, f"non-ASCII in test file: {nonascii[:5]}"

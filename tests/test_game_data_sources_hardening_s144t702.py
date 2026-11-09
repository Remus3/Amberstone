"""lib/game_data/sources.py hardening (s144 true-audit, S144-T-702).

The three parsers read bodies RC did not author (Data Dragon, Meraki, the
League wiki Lua module). ``lib.game_data.fetch.fetch`` turns a
``SourceParseError`` into a loud ``MissingSourceError("<source>: ...")`` and
catches nothing else from ``src.parse``, so every malformed body must surface
as a ``SourceParseError`` - an AttributeError / KeyError / TypeError escapes
as a raw traceback with no source named. Numbers must be finite: the
reconciler's ``_differ`` compares with ``abs(v - first) > tol``, which is
False for NaN, so a NaN from one source was chosen with no caveat at all.
"""
from __future__ import annotations

import json
import math

import pytest

from lib.game_data import build as gd_build
from lib.game_data import fetch as gd_fetch
from lib.game_data import sources as gd_sources

_EMPTY_ITEMS = json.dumps({"data": {}}).encode()
_EMPTY_CHAMPS = json.dumps({"data": {}}).encode()


def _dd(champion: bytes = _EMPTY_CHAMPS, item: bytes = _EMPTY_ITEMS) -> dict:
    return gd_sources._ddragon_parse({"champion": champion, "item": item})


def _mk(champions: bytes = b"{}", items: bytes = b"{}") -> dict:
    return gd_sources._meraki_parse({"champions": champions, "items": items})


def _wiki(stats_body: str, *, opener: str = '["stats"] = {') -> dict:
    text = (
        "return {\n"
        '  ["Aatrox"] = {\n'
        '    ["id"] = 266,\n'
        '    ["apiname"] = "Aatrox",\n'
        f"    {opener}\n"
        f"{stats_body}\n"
        "    },\n"
        "  },\n"
        "}\n"
    )
    return gd_sources._wiki_parse({"module": text.encode("utf-8")})


# ------------------------------------------------------------ characterization


def test_ddragon_happy_path_shape_is_unchanged():
    champ = json.dumps({
        "version": "16.1.1",
        "data": {"Aatrox": {"stats": {"hp": 650, "armor": 38, "attackspeed": 0.651}}},
    }).encode()
    item = json.dumps({
        "data": {"1001": {"stats": {"FlatHPPoolMod": 0}, "gold": {"total": 300}}},
    }).encode()
    out = _dd(champ, item)
    assert out["version"] == "16.1.1"
    assert out["champions"] == {"Aatrox": {"hp": 650, "armor": 38, "attack_speed": 0.651}}
    # A DDragon item stat it does not list reads as 0 (DDragon lists only the
    # non-zero stats); that is the shipped contract and stays.
    assert out["items"]["1001"] == {"ad": 0, "ap": 0, "armor": 0, "mr": 0, "hp": 0, "gold_total": 300}


def test_meraki_happy_path_and_removed_items_are_unchanged():
    champs = json.dumps({"Aatrox": {"stats": {"health": {"flat": 650, "perLevel": 114}}}}).encode()
    items = json.dumps({
        "1001": {"stats": {"health": {"flat": 0}}, "shop": {"prices": {"total": 300}}},
        "9999": {"removed": True, "stats": {"health": {"flat": 5}}},
        "8888": "not an item",
    }).encode()
    out = _mk(champs, items)
    assert out["champions"] == {"Aatrox": {"hp": 650, "hp_per_level": 114}}
    assert out["items"] == {"1001": {"hp": 0, "gold_total": 300}}


def test_wiki_happy_path_reads_depth_one_scalars():
    out = _wiki('      ["hp_base"] = 650,\n      ["arm_base"] = 38,\n      ["as_ratio"] = 0.625,')
    assert out["champions"]["Aatrox"] == {"hp": 650, "armor": 38, "as_ratio": 0.625}


# ------------------------------------------------------------ F1 non-finite


def test_ddragon_drops_nan_and_infinity_champion_stats():
    champ = b'{"data":{"A":{"stats":{"hp":NaN,"armor":Infinity,"spellblock":-Infinity,"movespeed":345}}}}'
    assert _dd(champ)["champions"]["A"] == {"move_speed": 345}


def test_ddragon_drops_non_finite_item_stats_and_gold():
    item = b'{"data":{"1":{"stats":{"FlatHPPoolMod":NaN,"FlatArmorMod":20},"gold":{"total":Infinity}}}}'
    row = _dd(item=item)["items"]["1"]
    assert "hp" not in row and "gold_total" not in row
    assert row["armor"] == 20


def test_meraki_drops_non_finite_numbers():
    champs = b'{"A":{"stats":{"health":{"flat":NaN,"perLevel":100}}}}'
    items = b'{"1":{"stats":{"health":{"flat":Infinity}},"shop":{"prices":{"total":NaN}}}}'
    out = _mk(champs, items)
    assert out["champions"]["A"] == {"hp_per_level": 100}
    assert out["items"]["1"] == {}


def test_wiki_drops_a_scalar_that_overflows_to_infinity():
    out = _wiki('      ["hp_base"] = ' + "9" * 400 + ',\n      ["arm_base"] = 38,')
    assert out["champions"]["Aatrox"] == {"armor": 38}


def test_every_parsed_number_is_finite_downstream_of_a_nan_body():
    """The reconciler cannot see a NaN, so the parse must never emit one."""
    champ = b'{"version":"1","data":{"A":{"stats":{"hp":NaN}}}}'
    out = _dd(champ)
    for row in out["champions"].values():
        assert all(math.isfinite(v) for v in row.values())


def test_nan_is_invisible_to_the_reconciler_differ():
    """Pins WHY F1 matters: _differ never flags a NaN disagreement."""
    assert gd_build._differ({"ddragon": float("nan"), "meraki": 650}) is False


# ------------------------------------------------------------ F2 shape -> SourceParseError


@pytest.mark.parametrize("champion,item", [
    (b'{"data":{"A":[1]}}', _EMPTY_ITEMS),
    (b'{"data":{"A":"x"}}', _EMPTY_ITEMS),
    (b'{"data":{"A":{"stats":[1]}}}', _EMPTY_ITEMS),
    (b'{"data":{"A":{"stats":5}}}', _EMPTY_ITEMS),
    (_EMPTY_CHAMPS, b'{"data":{"1":[1]}}'),
    (_EMPTY_CHAMPS, b'{"data":{"1":{"stats":"x"}}}'),
])
def test_ddragon_malformed_entry_is_a_source_parse_error(champion, item):
    with pytest.raises(gd_sources.SourceParseError):
        _dd(champion, item)


def test_ddragon_non_object_gold_is_omitted_not_a_crash():
    out = _dd(item=b'{"data":{"1":{"stats":{},"gold":5}}}')
    assert "gold_total" not in out["items"]["1"]


def test_ddragon_missing_stats_still_yields_an_empty_row():
    out = _dd(b'{"data":{"A":{"name":"A"}}}', b'{"data":{"1":{"stats":null}}}')
    assert out["champions"]["A"] == {}
    assert out["items"]["1"] == {"ad": 0, "ap": 0, "armor": 0, "mr": 0, "hp": 0}


def test_ddragon_empty_list_stats_still_reads_as_an_empty_row():
    """An empty object serialised as ``[]`` read as empty before; it still does."""
    out = _dd(b'{"data":{"A":{"stats":[]}}}', b'{"data":{"1":{"stats":[]}}}')
    assert out["champions"]["A"] == {}
    assert out["items"]["1"] == {"ad": 0, "ap": 0, "armor": 0, "mr": 0, "hp": 0}


def test_ddragon_non_string_version_reads_as_none():
    assert _dd(b'{"version":5,"data":{}}')["version"] is None


def test_meraki_non_object_stat_and_shop_are_omitted_not_a_crash():
    champs = b'{"A":{"stats":{"health":600,"armor":{"flat":30}}}}'
    items = b'{"1":{"stats":{"health":7},"shop":[1]},"2":{"stats":[],"shop":{"prices":5}}}'
    out = _mk(champs, items)
    assert out["champions"]["A"] == {"armor": 30}
    assert out["items"] == {"1": {}, "2": {}}


@pytest.mark.parametrize("parse,bodies", [
    (gd_sources._ddragon_parse, {"champion": _EMPTY_CHAMPS}),
    (gd_sources._ddragon_parse, {"item": _EMPTY_ITEMS}),
    (gd_sources._meraki_parse, {"champions": b"{}"}),
    (gd_sources._wiki_parse, {}),
])
def test_a_missing_body_is_a_source_parse_error(parse, bodies):
    with pytest.raises(gd_sources.SourceParseError, match="missing"):
        parse(bodies)


@pytest.mark.parametrize("parse,bodies", [
    (gd_sources._ddragon_parse, {"champion": "{}", "item": _EMPTY_ITEMS}),
    (gd_sources._meraki_parse, {"champions": None, "items": b"{}"}),
    (gd_sources._wiki_parse, {"module": "return {}"}),
])
def test_a_non_bytes_body_is_a_source_parse_error(parse, bodies):
    with pytest.raises(gd_sources.SourceParseError):
        parse(bodies)


def test_every_source_parse_raises_only_source_parse_error_on_junk():
    junk_values = [b"[]", b"5", b'"x"', b"null", b"{}", b'{"data":[]}', b"\xff\xfe", b""]
    for src in gd_sources.SOURCES:
        names = list(src.urls("16.1.1"))
        for junk in junk_values:
            try:
                src.parse({n: junk for n in names})
            except gd_sources.SourceParseError:
                pass


def test_fetch_names_the_source_when_a_body_is_structurally_junk(tmp_path, monkeypatch):
    """End to end: a malformed DDragon entry fails as MissingSourceError, not a traceback."""
    bodies = {
        gd_sources.DDRAGON_VERSIONS_URL: b'["16.1.1"]',
        "https://ddragon.leagueoflegends.com/cdn/16.1.1/data/en_US/champion.json": b'{"data":{"A":[1]}}',
        "https://ddragon.leagueoflegends.com/cdn/16.1.1/data/en_US/item.json": _EMPTY_ITEMS,
    }
    ddragon = [s for s in gd_sources.SOURCES if s.id == "ddragon"]
    monkeypatch.setattr(gd_fetch, "_get", lambda _client, url: bodies[url])
    with pytest.raises(gd_fetch.MissingSourceError, match="^ddragon: "):
        gd_fetch.fetch(None, client=object(), cache_dir=tmp_path, sources=ddragon)
    assert not any(tmp_path.rglob("*.body"))  # a bad body is never cached


# ------------------------------------------------------------ F3 wiki nested tables


def test_wiki_nested_mode_table_never_overrides_a_base_stat():
    body = (
        '      ["hp_base"] = 650,\n'
        '      ["aram"] = {\n'
        '        ["dmg_dealt"] = 1.05,\n'
        '        ["sub"] = { ["k"] = 1 },\n'
        '        ["hp_base"] = 9999,\n'
        "      },\n"
        '      ["arm_base"] = 38,'
    )
    assert _wiki(body)["champions"]["Aatrox"] == {"hp": 650, "armor": 38}


def test_wiki_nested_table_with_a_digit_in_its_key_is_still_skipped():
    body = (
        '      ["hp_base"] = 650,\n'
        '      ["arm_base"] = 38,\n'
        '      ["mode2"] = {\n'
        '        ["arm_base"] = 77,\n'
        "      },"
    )
    assert _wiki(body)["champions"]["Aatrox"] == {"hp": 650, "armor": 38}


def test_wiki_nested_only_stat_is_not_promoted_to_depth_one():
    body = '      ["hp_base"] = 650,\n      ["urf"] = {\n        ["ms"] = 999,\n      },'
    assert _wiki(body)["champions"]["Aatrox"] == {"hp": 650}


@pytest.mark.parametrize("opener", ['["stats"]={', '["stats"]  =  {', '["stats"] =\n    {'])
def test_wiki_stats_opener_spacing_does_not_drop_the_champion(opener):
    out = _wiki('      ["hp_base"] = 650,', opener=opener)
    assert out["champions"]["Aatrox"] == {"hp": 650}


# ------------------------------------------------------------ F4 version feed


@pytest.mark.parametrize("body", [b'["", "16.1.1"]', b'["16.1.1", "  "]', b'[" 16.1.1"]'])
def test_parse_versions_refuses_blank_or_padded_entries(body):
    with pytest.raises(gd_sources.SourceParseError):
        gd_sources.parse_versions(body)


def test_parse_versions_happy_path():
    assert gd_sources.parse_versions(b'["16.2.1", "16.1.1"]') == ["16.2.1", "16.1.1"]

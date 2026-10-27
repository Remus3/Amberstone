"""RM-787: the RM-600 rule at the two remaining wiki-parser sites.

Measured against the live ``Module:ChampionData/data`` on 2026-10-27 (s144 queue
cycle 7): the module holds 175 champion blocks over 174 apinames. Kled is the
only duplicate - block "Kled" (id 240: hp_base 410, range 250, ms 305) and
block "Kled & Skaarl" (id 240.1: hp_base 810, range 125, ms 345, plus a
Lua-commented ``--["aram"] = { ... --},`` table). Gnar's ``["range"] = 175,``
carries a trailing ``--see his passive ...`` comment.

- ``lib/game_data/sources.py`` ``_wiki_parse`` kept the LAST Kled block (hp 810,
  range 125, ms 345 published as the wiki's Kled), and its end-anchored scalar
  regex dropped Gnar's commented range line, so the wiki row had no
  ``attack_range`` for Gnar. The trimmed replay fixture in
  ``tests/fixtures/game_data_replay/`` carries only the primary Kled block,
  which is why ``tests/test_game_data_reconcile.py`` stayed green.
- ``tools/ds_windup_offset_compare.py`` ``parse_module`` also kept the LAST
  block and read commented scalars as live. On the live module both Kled blocks
  carry the same four windup fields, so that site is INERT today; the fixture
  below gives the two blocks different windups to make the rule observable.

The rule (RM-600, ``tools/daemon_slayer_wiki_stats_extract.py``): strip Lua
comments first (a ``--`` inside a string is data), and when two blocks share an
apiname keep the integer-id record in either order; a lone non-integer-id record
is still used. The fixture text is synthetic, shaped like the live module.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lib.game_data import sources as gd_sources

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import ds_windup_offset_compare as windup  # noqa: E402

_GNAR = """\
  ["Gnar"] = {
    ["id"]         = 150,
    ["apiname"]    = "Gnar",
    ["title"]      = "the Missing -- Link",
    ["stats"] = {
      ["hp_base"]  = 540,
      ["range"]    = 175,--see his passive in his article for the real range
      ["ms"]       = 335,
      ["as_base"]  = 0.625,
      ["attack_delay_offset"] = -0.1,
    },
  },
"""

_KLED = """\
  ["Kled"] = {
    ["id"]         = 240,
    ["apiname"]    = "Kled",
    ["stats"] = {
      ["hp_base"]  = 410,
      ["hp_lvl"]   = 84,
      ["range"]    = 250,
      ["ms"]       = 305,
      ["as_base"]  = 0.625,
      ["as_ratio"] = 0.625,
      ["attack_cast_time"] = 0.28,
    },
  },
"""

_KLED_SKAARL = """\
  ["Kled & Skaarl"] = {
    ["id"]         = 240.1,
    ["apiname"]    = "Kled",
    ["stats"] = {
      ["hp_base"]  = 810,
      ["hp_lvl"]   = 84+1000/17,
      ["range"]    = 125,
      ["ms"]       = 345,
      ["as_base"]  = 0.7,
      ["as_ratio"] = 0.7,
      ["attack_cast_time"] = 0.4,
      --["attack_delay_offset"] = 0.5,
      --["aram"] = { this is pointless
      --["dmg_dealt"] = 1.05,
      --},
    },
  },
"""

_GNAR_BIG = """\
  ["Mega Gnar"] = {
    ["id"]         = 150.1,
    ["apiname"]    = "GnarBig",
    ["stats"] = {
      ["hp_base"]  = 640,
      ["range"]    = 175,
    },
  },
"""


def _module(*blocks: str) -> str:
    return "-- <pre>\nreturn {\n" + "".join(blocks) + "}\n-- </pre>\n-- [[Category:Lua]]\n"


def _wiki(text: str) -> dict:
    return gd_sources._wiki_parse({"module": text.encode("utf-8")})["champions"]


# ----------------------------------------------------------- lib/game_data/sources.py


@pytest.mark.parametrize("order", ["primary_first", "primary_last"])
def test_sources_wiki_keeps_kleds_primary_record_in_either_order(order):
    blocks = (_KLED, _KLED_SKAARL) if order == "primary_first" else (_KLED_SKAARL, _KLED)
    kled = _wiki(_module(_GNAR, *blocks))["Kled"]
    assert kled["hp"] == 410
    assert kled["attack_range"] == 250
    assert kled["move_speed"] == 305
    assert kled["hp_per_level"] == 84


def test_sources_wiki_reads_a_scalar_that_carries_a_trailing_comment():
    gnar = _wiki(_module(_GNAR, _KLED))["Gnar"]
    assert gnar["attack_range"] == 175
    assert gnar["hp"] == 540 and gnar["move_speed"] == 335


def test_sources_wiki_still_uses_a_lone_non_integer_record():
    champs = _wiki(_module(_GNAR, _GNAR_BIG, _KLED))
    assert champs["GnarBig"]["hp"] == 640
    assert set(champs) == {"Gnar", "GnarBig", "Kled"}


def test_sources_wiki_still_refuses_a_module_with_no_champions():
    with pytest.raises(gd_sources.SourceParseError):
        _wiki("-- <pre>\nreturn {\n  -- [\"Kled\"] = { [\"apiname\"] = \"Kled\" },\n}\n")


# ------------------------------------------------- tools/ds_windup_offset_compare.py


@pytest.mark.parametrize("order", ["primary_first", "primary_last"])
def test_windup_parse_keeps_kleds_primary_record_in_either_order(order):
    blocks = (_KLED, _KLED_SKAARL) if order == "primary_first" else (_KLED_SKAARL, _KLED)
    kled = windup.parse_module(_module(_GNAR, *blocks))["Kled"]
    assert kled == {
        "attack_cast_time": 0.28,
        "attack_delay_offset": None,
        "as_base": 0.625,
        "as_ratio": 0.625,
    }


def test_windup_parse_never_reads_a_commented_scalar():
    kled = windup.parse_module(_module(_KLED_SKAARL))["Kled"]
    assert kled["attack_delay_offset"] is None
    assert kled["attack_cast_time"] == 0.4


def test_windup_parse_keeps_each_champions_own_fields():
    mod = windup.parse_module(_module(_GNAR, _GNAR_BIG, _KLED))
    assert set(mod) == {"Gnar", "GnarBig", "Kled"}
    assert mod["Gnar"]["attack_delay_offset"] == -0.1
    assert mod["Gnar"]["as_base"] == 0.625
    # GnarBig publishes no windup fields: none may leak in from a neighbour.
    assert mod["GnarBig"] == {
        "attack_cast_time": None,
        "attack_delay_offset": None,
        "as_base": None,
        "as_ratio": None,
    }

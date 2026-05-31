# arch: offline tests for the lolmath-wiki stat sidecar extractor | section=tools-tests | frozen=no
"""Offline unit tests for ``tools/daemon_slayer_wiki_stats_extract.py``.

NO network. Every wiki call path is monkeypatched. Item 221 (2026-05-30);
rewritten 2026-05-30 (item 221 deep-dive) for the action=raw primary path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import daemon_slayer_wiki_stats_extract as W  # noqa: E402


# --------------------------------------------------------------------------- _parse_scalar
class TestParseScalar:
    def test_plain_float(self):
        assert W._parse_scalar("0.30000001192093") == pytest.approx(0.3)

    def test_trailing_compound_separator(self):
        # feasibility doc 1g: compound get returns "0.30000001192093||"
        assert W._parse_scalar("0.30000001192093||") == pytest.approx(0.3)

    def test_blank_returns_none(self):
        assert W._parse_scalar("") is None
        assert W._parse_scalar("   ") is None

    def test_non_numeric_returns_none(self):
        assert W._parse_scalar("abc") is None

    def test_pipe_only_returns_none(self):
        assert W._parse_scalar("|") is None

    def test_integer_like(self):
        assert W._parse_scalar("2500") == pytest.approx(2500.0)


# --------------------------------------------------------------------------- _wiki_name
class TestWikiName:
    def test_override_wins(self, monkeypatch):
        monkeypatch.setattr(W, "_WIKI_NAME_OVERRIDES", {"MonkeyKing": "Wukong"})
        assert W._wiki_name("MonkeyKing", {"MonkeyKing": "X"}) == "Wukong"

    def test_fallback_to_display(self):
        assert W._wiki_name("Aatrox", {"Aatrox": "Aatrox"}) == "Aatrox"

    def test_fallback_to_id_when_missing(self):
        assert W._wiki_name("Zyx", {}) == "Zyx"


# --------------------------------------------------------------------------- _load_champion_ids
class TestLoadChampionIds:
    def test_reads_data_container(self, tmp_path, monkeypatch):
        monkeypatch.setattr(W, "DATA_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        (pd / "champion_abilities.json").write_text(
            json.dumps({"version": "16.11.1", "data": {"Ahri": {}, "Aatrox": {}}}),
            encoding="utf-8",
        )
        assert W._load_champion_ids("16.11.1") == ["Aatrox", "Ahri"]  # sorted

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(W, "DATA_DIR", tmp_path)
        with pytest.raises(SystemExit):
            W._load_champion_ids("16.11.1")

    def test_no_data_container_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(W, "DATA_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        (pd / "champion_abilities.json").write_text(json.dumps({"version": "x"}), encoding="utf-8")
        with pytest.raises(SystemExit):
            W._load_champion_ids("16.11.1")


# --------------------------------------------------------------------------- _load_display_names
class TestLoadDisplayNames:
    def test_reads_meta_build_mirror(self, tmp_path, monkeypatch):
        monkeypatch.setattr(W, "META_DDRAGON_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        (pd / "champion.json").write_text(
            json.dumps({"data": {"MonkeyKing": {"name": "Wukong"}, "Aatrox": {"name": "Aatrox"}}}),
            encoding="utf-8",
        )
        names = W._load_display_names("16.11.1")
        assert names["MonkeyKing"] == "Wukong"
        assert names["Aatrox"] == "Aatrox"

    def test_falls_back_to_newest_when_exact_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(W, "META_DDRAGON_DIR", tmp_path)
        pd = tmp_path / "16.10.1"
        pd.mkdir()
        (pd / "champion.json").write_text(
            json.dumps({"data": {"Aatrox": {"name": "Aatrox"}}}), encoding="utf-8"
        )
        names = W._load_display_names("16.99.9")  # exact patch dir absent
        assert names["Aatrox"] == "Aatrox"


# --------------------------------------------------------------------------- _parse_lua_table
class TestParseLuaTable:
    SAMPLE = (
        "return {\n"
        '  ["Aatrox"] = {\n'
        '    ["id"]         = 266,\n'
        '    ["apiname"]    = "Aatrox",\n'
        '    ["stats"] = {\n'
        '      ["attack_cast_time"]  = 0.300000011920928,\n'
        '      ["attack_total_time"] = 1.51999998092651,\n'
        "    },\n"
        "  },\n"
        '  ["Caitlyn"] = {\n'
        '    ["id"]         = 51,\n'
        '    ["apiname"]    = "Caitlyn",\n'
        '    ["stats"] = {\n'
        '      ["attack_cast_time"]  = 0.625,\n'
        '      ["attack_total_time"] = 1.0625,\n'
        '      ["missile_speed"]     = 2500,\n'
        "    },\n"
        "  },\n"
        '  ["Ahri"] = {\n'
        '    ["id"]         = 103,\n'
        '    ["apiname"]    = "Ahri",\n'
        '    ["stats"] = {\n'
        '      ["missile_speed"] = 550,\n'
        "    },\n"
        "  },\n"
        "}\n"
    )

    def test_keys_by_apiname(self):
        t = W._parse_lua_table(self.SAMPLE)
        assert set(t) == {"Aatrox", "Caitlyn", "Ahri"}

    def test_pulls_scalars(self):
        t = W._parse_lua_table(self.SAMPLE)
        assert t["Aatrox"]["attack_cast_time"] == pytest.approx(0.3)
        assert t["Aatrox"]["attack_total_time"] == pytest.approx(1.52, abs=0.01)
        assert t["Caitlyn"]["missile_speed"] == pytest.approx(2500.0)

    def test_melee_missile_is_none(self):
        t = W._parse_lua_table(self.SAMPLE)
        assert t["Aatrox"]["missile_speed"] is None

    def test_defaulter_cast_is_none(self):
        # Ahri block omits attack_cast_time -> None (the getter fills it at extract time)
        t = W._parse_lua_table(self.SAMPLE)
        assert t["Ahri"]["attack_cast_time"] is None
        assert t["Ahri"]["missile_speed"] == pytest.approx(550.0)

    def test_stores_wiki_name(self):
        t = W._parse_lua_table(self.SAMPLE)
        assert t["Aatrox"]["wiki_name"] == "Aatrox"

    def test_nested_subtable_not_a_champ(self):
        # the stats subtable has no id/apiname head -> excluded from the result
        t = W._parse_lua_table(self.SAMPLE)
        assert "stats" not in t

    def test_empty_input(self):
        assert W._parse_lua_table("") == {}


# --------------------------------------------------------------------------- _fetch_field (getter fallback)
class TestFetchField:
    def test_bare_field_resolves(self, monkeypatch):
        monkeypatch.setattr(W, "_expand", lambda c, f: "0.3" if f == "attack_cast_time" else "")
        assert W._fetch_field("Aatrox", "attack_cast_time", stats_fallback=True) == pytest.approx(0.3)

    def test_stats_fallback_when_bare_empty(self, monkeypatch):
        seen = []

        def fake_expand(c, f):
            seen.append(f)
            return "920" if f == "stats.missile_speed" else ""

        monkeypatch.setattr(W, "_expand", fake_expand)
        assert W._fetch_field("Aatrox", "missile_speed", stats_fallback=True) == pytest.approx(920.0)
        assert "stats.missile_speed" in seen

    def test_returns_none_when_both_empty(self, monkeypatch):
        monkeypatch.setattr(W, "_expand", lambda c, f: "")
        assert W._fetch_field("Aatrox", "missile_speed", stats_fallback=True) is None

    def test_first_hit_wins_no_fallback_call(self, monkeypatch):
        calls = []

        def fake_expand(c, f):
            calls.append(f)
            return "0.3"

        monkeypatch.setattr(W, "_expand", fake_expand)
        assert W._fetch_field("Aatrox", "attack_cast_time", stats_fallback=True) == pytest.approx(0.3)
        assert len(calls) == 1


# --------------------------------------------------------------------------- extract
class TestExtract:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        W._WIKI_TABLE_CACHE = None
        yield
        W._WIKI_TABLE_CACHE = None

    def test_happy_path_two_champs(self, monkeypatch):
        ids = ["Aatrox", "Ahri"]
        names = {"Aatrox": "Aatrox", "Ahri": "Ahri"}
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ids)
        monkeypatch.setattr(W, "_load_display_names", lambda p: names)
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {})  # empty -> getter fallback
        monkeypatch.setattr(
            W, "_fetch_field",
            lambda disp, field, stats_fallback: 0.3 if field == "attack_cast_time" else None,
        )
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False, source="wiki")
        assert out["_with_cast_time"] == 2
        assert out["champions"]["Aatrox"]["attack_cast_time"] == pytest.approx(0.3)
        assert out["_champ_count"] == 2

    def test_table_path_no_getter(self, monkeypatch):
        # a populated raw table supplies the value; the getter must NOT fire
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Aatrox"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Aatrox": "Aatrox"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {"Aatrox": 175.0})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {
            "Aatrox": {"wiki_name": "Aatrox", "attack_cast_time": 0.3,
                       "attack_total_time": 1.52, "missile_speed": None},
        })

        def boom(disp, field, stats_fallback):
            raise AssertionError("getter must not fire when the table has the value")

        monkeypatch.setattr(W, "_fetch_field", boom)
        # source=wiki: a null missile_speed stays null (melee), no cdragon backfill
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False, source="wiki")
        assert out["_with_cast_time"] == 1
        rec = out["champions"]["Aatrox"]
        assert rec["attack_cast_time"] == pytest.approx(0.3)
        assert rec["attack_total_time"] == pytest.approx(1.52)
        assert rec["missile_speed"] is None

    def test_defaulter_falls_back_to_getter(self, monkeypatch):
        # champ present in table but attack_cast_time null (Ahri) -> getter fills it
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Ahri"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Ahri": "Ahri"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {"Ahri": 550.0})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {
            "Ahri": {"wiki_name": "Ahri", "attack_cast_time": None,
                     "attack_total_time": None, "missile_speed": 550.0},
        })
        monkeypatch.setattr(
            W, "_fetch_field",
            lambda disp, field, stats_fallback: 0.3 if field == "attack_cast_time" else None,
        )
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False, source="wiki")
        assert out["champions"]["Ahri"]["attack_cast_time"] == pytest.approx(0.3)
        assert out["champions"]["Ahri"]["missile_speed"] == pytest.approx(550.0)

    def test_limit_caps_calls(self, monkeypatch):
        ids = ["Aatrox", "Ahri", "Akali"]
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ids)
        monkeypatch.setattr(W, "_load_display_names", lambda p: {i: i for i in ids})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {})
        monkeypatch.setattr(W, "_fetch_field", lambda disp, field, stats_fallback: 0.25)
        out = W.extract("16.11.1", sleep_s=0, limit=2, verbose=False, source="wiki")
        assert out["_champ_count"] == 2

    def test_fail_soft_records_errors(self, monkeypatch):
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Aatrox"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Aatrox": "Aatrox"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {})

        def boom(disp, field, stats_fallback):
            raise RuntimeError("blocked")

        monkeypatch.setattr(W, "_fetch_field", boom)
        # default_cast=False so the all-null path stays 0 (proves the fail-soft + the
        # "0 measured -> do not commit" warning path, separate from the default tier).
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        source="wiki", default_cast=False)
        assert out["_with_cast_time"] == 0
        assert len(out["_errors"]) == 1

    def test_raw_fetch_failure_degrades_to_getter(self, monkeypatch):
        # raw module fetch raises -> table_err recorded + per-champ getter still runs
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Aatrox"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Aatrox": "Aatrox"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {})

        def raw_boom():
            raise RuntimeError("401 blocked")

        monkeypatch.setattr(W, "_load_wiki_table", raw_boom)
        monkeypatch.setattr(
            W, "_fetch_field",
            lambda disp, field, stats_fallback: 0.3 if field == "attack_cast_time" else None,
        )
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False, source="wiki")
        assert out["_with_cast_time"] == 1
        assert any("raw module fetch failed" in e for e in out["_errors"])

    def test_ascii_only_output(self, monkeypatch):
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Aatrox"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Aatrox": "Aatrox"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {})
        monkeypatch.setattr(W, "_fetch_field", lambda disp, field, stats_fallback: 0.3)
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False, source="wiki")
        json.dumps(out, ensure_ascii=True)  # must not raise

    def test_engine_independent_no_imports(self):
        # no heavy DS engine import; stdlib + urllib only
        src = open(W.__file__, encoding="utf-8").read()
        assert "import requests" not in src
        assert "from agents" not in src
        assert "import agents" not in src


# --------------------------------------------------------------------------- _cdragon_slug
class TestCdragonSlug:
    def test_default_is_lowercased_id(self):
        assert W._cdragon_slug("Aatrox") == "aatrox"
        assert W._cdragon_slug("MonkeyKing") == "monkeyking"
        assert W._cdragon_slug("Kaisa") == "kaisa"
        assert W._cdragon_slug("Belveth") == "belveth"

    def test_override_wins(self, monkeypatch):
        monkeypatch.setattr(W, "_CDRAGON_SLUG_OVERRIDES", {"Foo": "barbaz"})
        assert W._cdragon_slug("Foo") == "barbaz"
        assert W._cdragon_slug("Aatrox") == "aatrox"  # untouched falls through


# --------------------------------------------------------------------------- _parse_cdragon_bin
class TestParseCdragonBin:
    # A minimal CDragon character-bin shape: a root key, the CharacterRecords
    # basic-attack block, and a primary <Name>BasicAttack spell with missileSpeed.
    RANGED = {
        "/Characters/Caitlyn": {
            "CharacterRecords/Root": {
                "basicAttack": {
                    "mAttackCastTime": 0.625,
                    "mAttackTotalTime": 1.0625,
                },
            },
            "Spells/CaitlynBasicAttack": {
                "mSpell": {"missileSpeed": 2500.0},
            },
        }
    }
    MELEE = {
        "/Characters/Aatrox": {
            "CharacterRecords/Root": {
                "basicAttack": {
                    "mAttackCastTime": 0.3,
                    "mAttackTotalTime": 1.6,
                    "extraAttacks": [{"mAttackCastTime": 0.0}],
                },
            },
            "Spells/AatroxBasicAttack": {
                "mSpell": {"missileSpeed": 347.8},
            },
        }
    }

    def test_ranged_pulls_all_three(self):
        f = W._parse_cdragon_bin(self.RANGED)
        assert f["attack_cast_time"] == pytest.approx(0.625)
        assert f["attack_total_time"] == pytest.approx(1.0625)
        assert f["missile_speed"] == pytest.approx(2500.0)

    def test_melee_still_parses_raw_missile(self):
        # the parser captures missileSpeed raw; the melee drop happens in _cdragon_scalars
        f = W._parse_cdragon_bin(self.MELEE)
        assert f["attack_cast_time"] == pytest.approx(0.3)
        assert f["missile_speed"] == pytest.approx(347.8)

    def test_extra_attack_cast_not_captured(self):
        # extraAttacks[..]/mAttackCastTime (0.0) must NOT win over the basicAttack one
        f = W._parse_cdragon_bin(self.MELEE)
        assert f["attack_cast_time"] == pytest.approx(0.3)

    def test_cast_only_under_basicattack_ancestor(self):
        # an mAttackCastTime NOT under a basicAttack ancestor must be ignored
        doc = {"/Characters/X": {"somethingElse": {"mAttackCastTime": 9.9}}}
        f = W._parse_cdragon_bin(doc)
        assert f["attack_cast_time"] is None

    def test_missile_only_under_primary_basicattack_spell(self):
        # a missileSpeed under a non-(<Name>BasicAttack/mSpell) path must be ignored
        doc = {"/Characters/X": {"Spells/XRAbility/XR": {"mSpell": {"missileSpeed": 779.0}}}}
        f = W._parse_cdragon_bin(doc)
        assert f["missile_speed"] is None

    def test_bool_is_not_numeric(self):
        doc = {"/Characters/X": {"basicAttack": {"mAttackCastTime": True}}}
        f = W._parse_cdragon_bin(doc)
        assert f["attack_cast_time"] is None

    def test_missing_fields_all_none(self):
        assert all(v is None for v in W._parse_cdragon_bin({}).values())


# --------------------------------------------------------------------------- _cdragon_scalars (melee guard)
class TestCdragonScalars:
    def test_ranged_keeps_missile(self, monkeypatch):
        monkeypatch.setattr(W, "_fetch_with_retry", lambda url: json.dumps(TestParseCdragonBin.RANGED))
        out = W._cdragon_scalars("Caitlyn", 650.0)
        assert out["attack_cast_time"] == pytest.approx(0.625)
        assert out["missile_speed"] == pytest.approx(2500.0)

    def test_melee_drops_missile_keeps_cast(self, monkeypatch):
        monkeypatch.setattr(W, "_fetch_with_retry", lambda url: json.dumps(TestParseCdragonBin.MELEE))
        out = W._cdragon_scalars("Aatrox", 175.0)
        assert out["attack_cast_time"] == pytest.approx(0.3)
        assert out["attack_total_time"] == pytest.approx(1.6)
        assert out["missile_speed"] is None  # melee guard drops the swing missileSpeed

    def test_unknown_range_drops_missile(self, monkeypatch):
        monkeypatch.setattr(W, "_fetch_with_retry", lambda url: json.dumps(TestParseCdragonBin.RANGED))
        out = W._cdragon_scalars("Caitlyn", None)  # no attackrange known -> treat as melee
        assert out["missile_speed"] is None
        assert out["attack_cast_time"] == pytest.approx(0.625)  # cast still kept

    def test_rounds_to_six(self, monkeypatch):
        doc = {"/Characters/X": {"CharacterRecords/Root": {
            "basicAttack": {"mAttackCastTime": 0.300000011920928}}}}
        monkeypatch.setattr(W, "_fetch_with_retry", lambda url: json.dumps(doc))
        out = W._cdragon_scalars("Aatrox", 175.0)
        assert out["attack_cast_time"] == round(0.300000011920928, 6)

    def test_retry_helper_used(self, monkeypatch):
        calls = []

        def fake(url):
            calls.append(url)
            return json.dumps(TestParseCdragonBin.RANGED)

        monkeypatch.setattr(W, "_fetch_with_retry", fake)
        W._cdragon_scalars("Caitlyn", 650.0)
        assert len(calls) == 1
        assert "caitlyn.bin.json" in calls[0]


# --------------------------------------------------------------------------- _fetch_with_retry
class TestFetchWithRetry:
    def test_first_try_wins(self, monkeypatch):
        monkeypatch.setattr(W, "_fetch", lambda url, timeout=40: "OK")
        assert W._fetch_with_retry("http://x", retries=3, backoff_s=0) == "OK"

    def test_retries_then_succeeds(self, monkeypatch):
        seq = [RuntimeError("404"), RuntimeError("404"), "OK"]

        def fake(url, timeout=40):
            v = seq.pop(0)
            if isinstance(v, Exception):
                raise v
            return v

        monkeypatch.setattr(W, "_fetch", fake)
        assert W._fetch_with_retry("http://x", retries=3, backoff_s=0) == "OK"

    def test_raises_after_exhausting(self, monkeypatch):
        def boom(url, timeout=40):
            raise RuntimeError("perma 404")

        monkeypatch.setattr(W, "_fetch", boom)
        with pytest.raises(RuntimeError):
            W._fetch_with_retry("http://x", retries=2, backoff_s=0)


# --------------------------------------------------------------------------- _merge_fill (wiki wins, cdragon fills)
class TestMergeFill:
    def test_wiki_wins_when_present(self):
        rec = {}
        W._merge_fill(rec, "attack_cast_time", 0.3, 0.25)
        assert rec["attack_cast_time"] == pytest.approx(0.3)
        assert rec["attack_cast_time_src"] == "wiki"

    def test_cdragon_fills_when_wiki_null(self):
        rec = {}
        W._merge_fill(rec, "attack_cast_time", None, 0.25)
        assert rec["attack_cast_time"] == pytest.approx(0.25)
        assert rec["attack_cast_time_src"] == "cdragon"

    def test_both_null_stays_null(self):
        rec = {}
        W._merge_fill(rec, "missile_speed", None, None)
        assert rec["missile_speed"] is None
        assert rec["missile_speed_src"] is None

    def test_wiki_wins_even_if_cdragon_also_present(self):
        rec = {}
        W._merge_fill(rec, "attack_total_time", 1.52, 1.6)
        assert rec["attack_total_time"] == pytest.approx(1.52)
        assert rec["attack_total_time_src"] == "wiki"


# --------------------------------------------------------------------------- _load_attack_ranges
class TestLoadAttackRanges:
    def test_reads_attackrange_stat(self, tmp_path, monkeypatch):
        monkeypatch.setattr(W, "META_DDRAGON_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        (pd / "champion.json").write_text(
            json.dumps({"data": {
                "Aatrox": {"name": "Aatrox", "stats": {"attackrange": 175}},
                "Caitlyn": {"name": "Caitlyn", "stats": {"attackrange": 650}},
                "NoStats": {"name": "NoStats"},  # missing stats -> omitted
            }}),
            encoding="utf-8",
        )
        ar = W._load_attack_ranges("16.11.1")
        assert ar["Aatrox"] == pytest.approx(175.0)
        assert ar["Caitlyn"] == pytest.approx(650.0)
        assert "NoStats" not in ar


# --------------------------------------------------------------------------- extract with cdragon backfill
class TestExtractBackfill:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        W._WIKI_TABLE_CACHE = None
        yield
        W._WIKI_TABLE_CACHE = None

    def test_cdragon_fills_wiki_null_cast(self, monkeypatch):
        # wiki has the champ but cast is null; cdragon supplies it under source=both
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Ahri"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Ahri": "Ahri"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {"Ahri": 550.0})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {
            "Ahri": {"wiki_name": "Ahri", "attack_cast_time": None,
                     "attack_total_time": None, "missile_speed": 1750.0},
        })
        # wiki getter fallback returns nothing (the raw-omitter the getter ALSO leaves blank)
        monkeypatch.setattr(W, "_fetch_field", lambda disp, field, stats_fallback: None)
        monkeypatch.setattr(W, "_cdragon_scalars", lambda cid, ar: {
            "attack_cast_time": 0.203919, "attack_total_time": None, "missile_speed": None,
        })
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False, source="both")
        rec = out["champions"]["Ahri"]
        assert rec["attack_cast_time"] == pytest.approx(0.203919)
        assert rec["attack_cast_time_src"] == "cdragon"
        # wiki missile_speed wins, stays wiki-sourced
        assert rec["missile_speed"] == pytest.approx(1750.0)
        assert rec["missile_speed_src"] == "wiki"
        assert out["_with_cast_time"] == 1
        assert out["_cdragon_cast_fills"] == 1

    def test_wiki_value_not_overwritten_by_cdragon(self, monkeypatch):
        # wiki has a real cast; cdragon must NOT fire / must NOT win
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Caitlyn"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Caitlyn": "Caitlyn"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {"Caitlyn": 650.0})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {
            "Caitlyn": {"wiki_name": "Caitlyn", "attack_cast_time": 0.625,
                        "attack_total_time": 1.0625, "missile_speed": 2500.0},
        })

        def boom(cid, ar):
            raise AssertionError("cdragon must not fire when all wiki scalars present")

        monkeypatch.setattr(W, "_cdragon_scalars", boom)
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False, source="both")
        rec = out["champions"]["Caitlyn"]
        assert rec["attack_cast_time"] == pytest.approx(0.625)
        assert rec["attack_cast_time_src"] == "wiki"
        assert out["_cdragon_cast_fills"] == 0

    def test_source_cdragon_only_skips_wiki(self, monkeypatch):
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Aatrox"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Aatrox": "Aatrox"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {"Aatrox": 175.0})

        def wiki_boom():
            raise AssertionError("wiki table must not load under source=cdragon")

        monkeypatch.setattr(W, "_load_wiki_table", wiki_boom)
        monkeypatch.setattr(W, "_cdragon_scalars", lambda cid, ar: {
            "attack_cast_time": 0.3, "attack_total_time": 1.6, "missile_speed": None,
        })
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False, source="cdragon")
        rec = out["champions"]["Aatrox"]
        assert rec["attack_cast_time"] == pytest.approx(0.3)
        assert rec["attack_cast_time_src"] == "cdragon"
        assert out["_source_mode"] == "cdragon"

    def test_source_wiki_only_skips_cdragon(self, monkeypatch):
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Ahri"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Ahri": "Ahri"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {"Ahri": 550.0})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {
            "Ahri": {"wiki_name": "Ahri", "attack_cast_time": None,
                     "attack_total_time": None, "missile_speed": 1750.0},
        })
        monkeypatch.setattr(W, "_fetch_field", lambda disp, field, stats_fallback: None)

        def cd_boom(cid, ar):
            raise AssertionError("cdragon must not fire under source=wiki")

        monkeypatch.setattr(W, "_cdragon_scalars", cd_boom)
        # default_cast=False isolates the wiki path: cdragon never fires AND the
        # engine-default tier is off, so the wiki null stays null.
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        source="wiki", default_cast=False)
        rec = out["champions"]["Ahri"]
        assert rec["attack_cast_time"] is None  # wiki-only + no default leaves it null
        assert rec["attack_cast_time_src"] is None
        assert out["_source_mode"] == "wiki"

    def test_cdragon_failure_is_fail_soft(self, monkeypatch):
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Aatrox"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Aatrox": "Aatrox"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {"Aatrox": 175.0})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {})
        monkeypatch.setattr(W, "_fetch_field", lambda disp, field, stats_fallback: None)

        def cd_boom(cid, ar):
            raise RuntimeError("404")

        monkeypatch.setattr(W, "_cdragon_scalars", cd_boom)
        # default_cast=False isolates the cdragon-failure path (no engine-default masking it)
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        source="both", default_cast=False)
        assert out["champions"]["Aatrox"]["attack_cast_time"] is None
        assert len(out["_errors"]) == 1
        assert "cdragon" in out["_errors"][0]

    def test_ascii_output_with_provenance(self, monkeypatch):
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Aatrox"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Aatrox": "Aatrox"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {"Aatrox": 175.0})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {})
        monkeypatch.setattr(W, "_fetch_field", lambda disp, field, stats_fallback: None)
        monkeypatch.setattr(W, "_cdragon_scalars", lambda cid, ar: {
            "attack_cast_time": 0.3, "attack_total_time": 1.6, "missile_speed": None,
        })
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False, source="both")
        json.dumps(out, ensure_ascii=True)  # must not raise


# --------------------------------------------------------------------------- engine-default cast fill
class TestEngineDefaultCast:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        W._WIKI_TABLE_CACHE = None
        yield
        W._WIKI_TABLE_CACHE = None

    def _common(self, monkeypatch):
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Garen"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Garen": "Garen"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {"Garen": 175.0})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {})
        monkeypatch.setattr(W, "_fetch_field", lambda disp, field, stats_fallback: None)
        # cdragon has no override for Garen (the real-world case): all-null parse
        monkeypatch.setattr(W, "_cdragon_scalars", lambda cid, ar: {
            "attack_cast_time": None, "attack_total_time": None, "missile_speed": None,
        })

    def test_default_value_matches_combo_fallback(self):
        # the engine-default fill MUST equal combo.py's own AA-windup fallback so
        # default-filled champs stay byte-identical to the no-sidecar path.
        from agents.daemon_slayer import combo as _cb
        assert W._ENGINE_DEFAULT_CAST_TIME == pytest.approx(_cb._DEFAULT_AA_WINDUP_S)

    def test_default_fills_unmeasured_cast(self, monkeypatch):
        self._common(monkeypatch)
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        source="both", default_cast=True)
        rec = out["champions"]["Garen"]
        assert rec["attack_cast_time"] == pytest.approx(W._ENGINE_DEFAULT_CAST_TIME)
        assert rec["attack_cast_time_src"] == "default"
        assert out["_with_cast_time"] == 1
        assert out["_with_cast_measured"] == 0
        assert out["_default_cast_fills"] == 1
        # the default tier does NOT touch total/missile
        assert rec["attack_total_time"] is None
        assert rec["missile_speed"] is None

    def test_no_default_leaves_null(self, monkeypatch):
        self._common(monkeypatch)
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        source="both", default_cast=False)
        rec = out["champions"]["Garen"]
        assert rec["attack_cast_time"] is None
        assert rec["attack_cast_time_src"] is None
        assert out["_with_cast_time"] == 0
        assert out["_default_cast_fills"] == 0

    def test_measured_not_counted_as_default(self, monkeypatch):
        # a wiki-measured cast must NOT be counted as a default fill
        monkeypatch.setattr(W, "_load_champion_ids", lambda p: ["Aatrox"])
        monkeypatch.setattr(W, "_load_display_names", lambda p: {"Aatrox": "Aatrox"})
        monkeypatch.setattr(W, "_load_attack_ranges", lambda p: {"Aatrox": 175.0})
        monkeypatch.setattr(W, "_load_wiki_table", lambda: {
            "Aatrox": {"wiki_name": "Aatrox", "attack_cast_time": 0.3,
                       "attack_total_time": 1.52, "missile_speed": None},
        })
        out = W.extract("16.11.1", sleep_s=0, limit=None, verbose=False,
                        source="both", default_cast=True)
        rec = out["champions"]["Aatrox"]
        assert rec["attack_cast_time_src"] == "wiki"
        assert out["_with_cast_measured"] == 1
        assert out["_default_cast_fills"] == 0

    def test_merge_fill_default_tier(self):
        rec = {}
        W._merge_fill(rec, "attack_cast_time", None, None, 0.3)
        assert rec["attack_cast_time"] == pytest.approx(0.3)
        assert rec["attack_cast_time_src"] == "default"

    def test_merge_fill_cdragon_beats_default(self):
        rec = {}
        W._merge_fill(rec, "attack_cast_time", None, 0.25, 0.3)
        assert rec["attack_cast_time"] == pytest.approx(0.25)
        assert rec["attack_cast_time_src"] == "cdragon"


# --------------------------------------------------------------------------- ASCII hygiene
class TestAsciiHygiene:
    def test_source_is_ascii(self):
        data = open(W.__file__, encoding="utf-8").read()
        try:
            data.encode("ascii")
        except UnicodeEncodeError as e:
            pytest.fail(f"non-ascii byte in extractor: {e}")
        assert "daemon_slayer_wiki" in W.__file__  # sanity: right module

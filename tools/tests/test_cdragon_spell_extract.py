# arch: offline tests for the cdragon per-spell stat sidecar extractor | section=tools-tests | frozen=no
"""Offline unit tests for ``tools/daemon_slayer_cdragon_spell_extract.py``.

NO network. The bin-fetch seam (``_champ_spells`` / ``_fetch_with_retry``) is
monkeypatched with canned ``.bin.json`` dicts. Item 225 (2026-05-30).
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import daemon_slayer_cdragon_spell_extract as C  # noqa: E402

# --------------------------------------------------------------------------- engine-independence guard
# RM-170 (2026-08-06). Was `assert "from agents" not in src`. Commit d0ad0569
# (2026-07-30) deliberately added ONE engine import to both cdragon extractors
# without updating the guard, leaving it red and unseen because `pytest tests`
# does not collect tools/tests. The contract is narrowed, not dropped - see the
# matching block in test_cdragon_ratio_extract.py for the full rationale.
# Matched via AST, NOT text: a semicolon defeats line-prefix matching, and the
# leaf check has to reject ANY non-stdlib root, not just the literal string
# `import requests`. Both were live bypasses in the first cut of this guard.
_ALLOWED_AGENTS_IMPORTS = frozenset({
    ("agents.daemon_slayer.mode_variants", ("canonical_champions",)),
})
_LEAF_ALLOWED_ROOTS = frozenset(sys.stdlib_module_names) | {"__future__", "typing"}


def _agents_imports(src: str) -> list[tuple[str, tuple[str, ...]]]:
    """Every `agents...` import in src, as (module, imported names)."""
    found: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "agents" or mod.startswith("agents."):
                found.append((mod, tuple(sorted(a.name for a in node.names))))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "agents" or alias.name.startswith("agents."):
                    found.append((alias.name, ()))
    return found


def _assert_agents_imports_allowlisted(src: str, path: str) -> None:
    offenders = [i for i in _agents_imports(src) if i not in _ALLOWED_AGENTS_IMPORTS]
    assert offenders == [], (
        f"{path} imports the DS engine beyond the RM-170 allowlist "
        f"({sorted(_ALLOWED_AGENTS_IMPORTS)}): {offenders}"
    )


def _assert_mode_variants_is_leaf() -> None:
    """The one allowlisted helper must stay a stdlib-only pure-data leaf.

    A RELATIVE import counts as a failure: `from . import x` inside
    agents/daemon_slayer reaches the engine just as surely as an absolute one.
    """
    mv = (
        Path(__file__).resolve().parents[2]
        / "agents" / "daemon_slayer" / "mode_variants.py"
    )
    assert mv.exists(), f"allowlisted helper missing: {mv}"
    roots: set[str] = set()
    for node in ast.walk(ast.parse(mv.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                roots.add(f"<relative import level {node.level}>")
            elif node.module:
                roots.add(node.module.split(".")[0])
    bad = sorted(r for r in roots if r not in _LEAF_ALLOWED_ROOTS)
    assert bad == [], (
        f"{mv} is no longer a stdlib-only leaf, so allowlisting it no longer "
        f"preserves extractor engine-independence: {bad}"
    )


# --------------------------------------------------------------------------- canned bins
# The CDragon bin is a FLAT dict of dotted-path keys; each spell record holds its
# scalars under ``mSpell``. CharacterRecords/Root.spellNames gives the Q/W/E/R
# slot order. These mirror the real shapes verified live this session.

# Corki-like: R (MissileBarrage) carries mMaxAmmo + a sibling MissileBarrageMissile.
CORKI = {
    "Characters/Corki/CharacterRecords/Root": {
        "spellNames": [
            "PhosphorusBombAbility/PhosphorusBomb",
            "CarpetBombAbility/CarpetBomb",
            "GGunAbility/GGun",
            "MissileBarrageAbility/MissileBarrage",
        ],
    },
    "Characters/Corki/Spells/PhosphorusBombAbility/PhosphorusBomb": {
        "mSpell": {"missileSpeed": 0.0, "castRadius": [250.0, 250.0, 250.0]},
    },
    "Characters/Corki/Spells/PhosphorusBombAbility/PhosphorusBombMissile": {
        "mSpell": {"missileSpeed": 1000.0},
    },
    "Characters/Corki/Spells/CarpetBombAbility/CarpetBomb": {
        "mSpell": {"missileSpeed": 700.0, "mLineWidth": 160.0,
                   "castRadius": [100.0, 100.0]},
    },
    "Characters/Corki/Spells/GGunAbility/GGun": {
        "mSpell": {"missileSpeed": 902.0, "castConeDistance": 725.0,
                   "castConeAngle": 28.0, "castRadius": [100.0, 100.0]},
    },
    "Characters/Corki/Spells/MissileBarrageAbility/MissileBarrage": {
        "mSpell": {
            "mMaxAmmo": [4, 4, 4, 4, 4, 4, 4],
            "mAmmoRechargeTime": [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0],
            "missileSpeed": 828.5,
            "mSpellTags": ["Trait_Ultimate"],
            "castRadius": [550.0, 550.0],
            "mLineWidth": 40.0,
        },
    },
    "Characters/Corki/Spells/MissileBarrageAbility/MissileBarrageMissile": {
        "mSpell": {"missileSpeed": 2000.0},
    },
}

# Leona-like: E (LeonaZenithBlade) cast 1200 + sibling Missile 2000; Q/E/R carry
# the ImmobilizingCCSpell tag.
LEONA = {
    "Characters/Leona/CharacterRecords/Root": {
        "spellNames": [
            "LeonaShieldOfDaybreakAbility/LeonaShieldOfDaybreak",
            "LeonaSolarBarrierAbility/LeonaSolarBarrier",
            "LeonaZenithBladeAbility/LeonaZenithBlade",
            "LeonaSolarFlareAbility/LeonaSolarFlare",
        ],
    },
    "Characters/Leona/Spells/LeonaShieldOfDaybreakAbility/LeonaShieldOfDaybreak": {
        "mSpell": {"missileSpeed": 0.0, "mSpellTags": ["Trait_ImmobilizingCCSpell"],
                   "castRadius": [100.0]},
    },
    "Characters/Leona/Spells/LeonaSolarBarrierAbility/LeonaSolarBarrier": {
        "mSpell": {"missileSpeed": 828.5, "mSpellTags": []},
    },
    "Characters/Leona/Spells/LeonaZenithBladeAbility/LeonaZenithBlade": {
        "mSpell": {"missileSpeed": 1200.0, "mSpellTags": ["Trait_ImmobilizingCCSpell"]},
    },
    "Characters/Leona/Spells/LeonaZenithBladeAbility/LeonaZenithBladeMissile": {
        "mSpell": {"missileSpeed": 2000.0},
    },
    "Characters/Leona/Spells/LeonaSolarFlareAbility/LeonaSolarFlare": {
        "mSpell": {"missileSpeed": 20.0, "mSpellTags": ["Trait_ImmobilizingCCSpell"],
                   "castRadius": [120.0, 120.0]},
    },
}

# Nautilus W: clean cone geometry (dist=1400 angle=20.0).
NAUTILUS = {
    "Characters/Nautilus/CharacterRecords/Root": {
        "spellNames": [
            "NautilusAnchorDragAbility/NautilusAnchorDrag",
            "NautilusPiercingGazeAbility/NautilusPiercingGaze",
            "NautilusSplashZoneAbility/NautilusSplashZone",
            "NautilusGrandLineAbility/NautilusGrandLine",
        ],
    },
    "Characters/Nautilus/Spells/NautilusAnchorDragAbility/NautilusAnchorDrag": {
        "mSpell": {"missileSpeed": 1200.0, "mSpellTags": ["Trait_ImmobilizingCCSpell"]},
    },
    "Characters/Nautilus/Spells/NautilusPiercingGazeAbility/NautilusPiercingGaze": {
        "mSpell": {"missileSpeed": 1500.0, "castConeDistance": 1400.0,
                   "castConeAngle": 20.0, "castRadius": [210.0, 210.0]},
    },
    "Characters/Nautilus/Spells/NautilusSplashZoneAbility/NautilusSplashZone": {
        "mSpell": {"missileSpeed": 0.0},
    },
    "Characters/Nautilus/Spells/NautilusGrandLineAbility/NautilusGrandLine": {
        "mSpell": {"missileSpeed": 1400.0, "mSpellTags": ["Trait_ImmobilizingCCSpell"]},
    },
}

# A champ with NONE of the 4 buckets (all point spells, no ammo/cc/geometry).
PLAIN = {
    "Characters/Plain/CharacterRecords/Root": {
        "spellNames": [
            "PlainQAbility/PlainQ",
            "PlainWAbility/PlainW",
            "PlainEAbility/PlainE",
            "PlainRAbility/PlainR",
        ],
    },
    "Characters/Plain/Spells/PlainQAbility/PlainQ": {"mSpell": {"missileSpeed": 0.0}},
    "Characters/Plain/Spells/PlainWAbility/PlainW": {"mSpell": {"missileSpeed": 0.0}},
    "Characters/Plain/Spells/PlainEAbility/PlainE": {"mSpell": {"missileSpeed": 0.0}},
    "Characters/Plain/Spells/PlainRAbility/PlainR": {"mSpell": {"missileSpeed": 0.0}},
}


# --------------------------------------------------------------------------- _cdragon_patch_segment
class TestPatchSegment:
    def test_three_segment_truncates(self):
        assert C._cdragon_patch_segment("16.11.1") == "16.11"

    def test_two_segment_passthrough(self):
        assert C._cdragon_patch_segment("16.11") == "16.11"

    def test_non_numeric_label_passthrough(self):
        assert C._cdragon_patch_segment("latest") == "latest"
        assert C._cdragon_patch_segment("pbe") == "pbe"

    def test_double_digit_minor(self):
        assert C._cdragon_patch_segment("16.24.3") == "16.24"


# --------------------------------------------------------------------------- _cdragon_slug
class TestCdragonSlug:
    def test_default_is_lowercased_id(self):
        assert C._cdragon_slug("Aatrox") == "aatrox"
        assert C._cdragon_slug("MonkeyKing") == "monkeyking"

    def test_override_wins(self, monkeypatch):
        monkeypatch.setattr(C, "_CDRAGON_SLUG_OVERRIDES", {"Foo": "barbaz"})
        assert C._cdragon_slug("Foo") == "barbaz"
        assert C._cdragon_slug("Aatrox") == "aatrox"


# --------------------------------------------------------------------------- _load_champion_ids
class TestLoadChampionIds:
    def test_reads_data_container(self, tmp_path, monkeypatch):
        monkeypatch.setattr(C, "DATA_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        (pd / "champion_abilities.json").write_text(
            json.dumps({"version": "16.11.1", "data": {"Ahri": {}, "Aatrox": {}}}),
            encoding="utf-8",
        )
        assert C._load_champion_ids("16.11.1") == ["Aatrox", "Ahri"]  # sorted

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(C, "DATA_DIR", tmp_path)
        with pytest.raises(SystemExit):
            C._load_champion_ids("16.11.1")

    def test_no_data_container_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(C, "DATA_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        (pd / "champion_abilities.json").write_text(
            json.dumps({"version": "x"}), encoding="utf-8"
        )
        with pytest.raises(SystemExit):
            C._load_champion_ids("16.11.1")


# --------------------------------------------------------------------------- small parse helpers
class TestParseHelpers:
    def test_int_array(self):
        assert C._int_array([4, 4, 4]) == [4, 4, 4]
        assert C._int_array([4.0, 5.0]) == [4, 5]
        assert C._int_array([]) is None
        assert C._int_array("nope") is None
        assert C._int_array([4, "x"]) is None

    def test_float_array(self):
        assert C._float_array([20.0, 18.5]) == [20.0, 18.5]
        assert C._float_array([]) is None
        assert C._float_array([20.0, True]) is None  # bool not numeric

    def test_first_scalar(self):
        assert C._first_scalar([210.0, 210.0]) == pytest.approx(210.0)
        assert C._first_scalar(40.0) == pytest.approx(40.0)
        assert C._first_scalar([]) is None
        assert C._first_scalar(None) is None

    def test_num_rejects_bool(self):
        assert C._num(True) is None
        assert C._num(3) == pytest.approx(3.0)


# --------------------------------------------------------------------------- _cc_tags
class TestCcTags:
    def test_immobilizing_captured(self):
        assert C._cc_tags(["Trait_ImmobilizingCCSpell", "Trait_Ultimate"]) == [
            "Trait_ImmobilizingCCSpell"
        ]

    def test_no_cc_tag_empty(self):
        assert C._cc_tags(["Trait_Ultimate", "PositiveEffect_MoveBlock"]) == []

    def test_specific_cc_substrings(self):
        assert C._cc_tags(["SomeStunSpell"]) == ["SomeStunSpell"]
        assert C._cc_tags(["RootApplier", "SnareThing"]) == ["RootApplier", "SnareThing"]

    def test_non_list_returns_empty(self):
        assert C._cc_tags(None) == []
        assert C._cc_tags("Trait_ImmobilizingCCSpell") == []  # not a list


# --------------------------------------------------------------------------- _ammo_bucket
class TestAmmoBucket:
    def test_real_ammo(self):
        b = C._ammo_bucket({"mMaxAmmo": [4, 4, 4], "mAmmoRechargeTime": [20.0, 20.0, 20.0]})
        assert b == {"max": [4, 4, 4], "recharge": [20.0, 20.0, 20.0]}

    def test_no_ammo_returns_none(self):
        assert C._ammo_bucket({}) is None

    def test_negative_sentinel_returns_none(self):
        # the -1 "no ammo" sentinel must NOT register as charges
        assert C._ammo_bucket({"mMaxAmmo": [-1, -1, -1]}) is None

    def test_zero_max_returns_none(self):
        assert C._ammo_bucket({"mMaxAmmo": [0, 0]}) is None

    def test_ammo_without_recharge(self):
        b = C._ammo_bucket({"mMaxAmmo": [3, 3]})
        assert b == {"max": [3, 3], "recharge": None}


# --------------------------------------------------------------------------- _geometry_bucket
class TestGeometryBucket:
    def test_clean_cone(self):
        g = C._geometry_bucket({"castConeDistance": 1400.0, "castConeAngle": 20.0,
                                "castRadius": [210.0]})
        assert g["cone_distance"] == pytest.approx(1400.0)
        assert g["cone_angle"] == pytest.approx(20.0)

    def test_conflated_cast_radius_flagged(self):
        g = C._geometry_bucket({"castRadius": [210.0, 210.0]})
        assert g["cast_radius"] == pytest.approx(210.0)
        assert g["cast_radius_conflated"] is True

    def test_real_cast_radius_not_flagged(self):
        g = C._geometry_bucket({"castRadius": [550.0, 550.0]})
        assert g["cast_radius"] == pytest.approx(550.0)
        assert g["cast_radius_conflated"] is False

    def test_boilerplate_100_flagged(self):
        g = C._geometry_bucket({"castRadius": [100.0]})
        assert g["cast_radius_conflated"] is True

    def test_line_width_from_mlinewidth(self):
        g = C._geometry_bucket({"mLineWidth": 160.0})
        assert g["line_width"] == pytest.approx(160.0)

    def test_line_width_from_missile_spec(self):
        g = C._geometry_bucket({"mMissileSpec": {"mMissileWidth": 70.0}})
        assert g["line_width"] == pytest.approx(70.0)

    def test_no_geometry_returns_none(self):
        assert C._geometry_bucket({"missileSpeed": 1200.0}) is None


# --------------------------------------------------------------------------- _resolve_missile_speed
class TestResolveMissileSpeed:
    def test_positive_cast_record_wins(self):
        # Leona E: cast 1200 (> placeholder) wins even though sibling is 2000;
        # both are recorded for provenance.
        spells = C._spells_index(LEONA, "Leona")
        r = C._resolve_missile_speed(
            spells["LeonaZenithBladeAbility/LeonaZenithBlade"],
            "LeonaZenithBladeAbility", spells,
        )
        assert r["missile_speed"] == pytest.approx(1200.0)
        assert r["_cast_record_speed"] == pytest.approx(1200.0)
        assert r["_missile_record_speed"] == pytest.approx(2000.0)

    def test_tiny_cast_falls_to_sibling(self):
        # Corki Q: cast 0 -> sibling PhosphorusBombMissile 1000 wins.
        spells = C._spells_index(CORKI, "Corki")
        r = C._resolve_missile_speed(
            spells["PhosphorusBombAbility/PhosphorusBomb"],
            "PhosphorusBombAbility", spells,
        )
        assert r["missile_speed"] == pytest.approx(1000.0)
        assert r["_cast_record_speed"] == pytest.approx(0.0)
        assert r["_missile_record_speed"] == pytest.approx(1000.0)

    def test_no_sibling_keeps_tiny_positive(self):
        # a tiny positive cast with no sibling missile keeps the tiny value
        spells = {"XAbility/X": {"missileSpeed": 20.0}}
        r = C._resolve_missile_speed(spells["XAbility/X"], "XAbility", spells)
        assert r["missile_speed"] == pytest.approx(20.0)

    def test_zero_with_no_sibling_is_none(self):
        spells = {"XAbility/X": {"missileSpeed": 0.0}}
        r = C._resolve_missile_speed(spells["XAbility/X"], "XAbility", spells)
        assert r["missile_speed"] is None

    def test_sibling_must_be_same_ability(self):
        # a Missile record under a DIFFERENT ability must NOT leak in
        spells = {
            "XAbility/X": {"missileSpeed": 0.0},
            "YAbility/YMissile": {"missileSpeed": 3000.0},
        }
        r = C._resolve_missile_speed(spells["XAbility/X"], "XAbility", spells)
        assert r["missile_speed"] is None
        assert r["_missile_record_speed"] is None


# --------------------------------------------------------------------------- _parse_cdragon_spells
class TestParseCdragonSpells:
    def test_corki_slot_ordering_and_ammo(self):
        out = C._parse_cdragon_spells(CORKI, "corki")
        assert sorted(out.keys()) == ["E", "Q", "R", "W"]
        # R = MissileBarrage carries ammo
        assert out["R"]["ammo"] == {"max": [4, 4, 4, 4, 4, 4, 4],
                                    "recharge": [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0]}
        # Q has no ammo
        assert out["Q"]["ammo"] is None

    def test_corki_q_missile_from_sibling(self):
        out = C._parse_cdragon_spells(CORKI, "corki")
        assert out["Q"]["missile_speed"] == pytest.approx(1000.0)  # from sibling
        assert out["Q"]["missile_cast_record"] == pytest.approx(0.0)
        assert out["Q"]["missile_sub_record"] == pytest.approx(1000.0)

    def test_corki_e_clean_cone(self):
        out = C._parse_cdragon_spells(CORKI, "corki")
        assert out["E"]["geometry"]["cone_distance"] == pytest.approx(725.0)
        assert out["E"]["geometry"]["cone_angle"] == pytest.approx(28.0)

    def test_leona_cc_tags(self):
        out = C._parse_cdragon_spells(LEONA, "leona")
        assert out["Q"]["cc_tags"] == ["Trait_ImmobilizingCCSpell"]
        assert out["W"]["cc_tags"] == []  # SolarBarrier, no CC
        assert out["E"]["cc_tags"] == ["Trait_ImmobilizingCCSpell"]
        assert out["R"]["cc_tags"] == ["Trait_ImmobilizingCCSpell"]

    def test_leona_e_missile_resolution(self):
        out = C._parse_cdragon_spells(LEONA, "leona")
        # cast 1200 wins (> placeholder); sibling 2000 recorded
        assert out["E"]["missile_speed"] == pytest.approx(1200.0)
        assert out["E"]["missile_sub_record"] == pytest.approx(2000.0)

    def test_nautilus_w_clean_cone_geometry(self):
        out = C._parse_cdragon_spells(NAUTILUS, "nautilus")
        assert out["W"]["geometry"]["cone_distance"] == pytest.approx(1400.0)
        assert out["W"]["geometry"]["cone_angle"] == pytest.approx(20.0)
        # the W castRadius 210 is the conflated boilerplate
        assert out["W"]["geometry"]["cast_radius_conflated"] is True

    def test_plain_has_no_buckets(self):
        out = C._parse_cdragon_spells(PLAIN, "plain")
        assert sorted(out.keys()) == ["E", "Q", "R", "W"]
        for slot in ("Q", "W", "E", "R"):
            assert out[slot]["ammo"] is None
            assert out[slot]["cc_tags"] == []
            assert out[slot]["geometry"] is None
            assert out[slot]["missile_speed"] is None

    def test_no_spellnames_returns_empty(self):
        doc = {"Characters/Foo/CharacterRecords/Root": {}}
        assert C._parse_cdragon_spells(doc, "foo") == {}

    def test_no_characters_root_returns_empty(self):
        assert C._parse_cdragon_spells({"SomethingElse": {}}, "foo") == {}

    def test_empty_doc_returns_empty(self):
        assert C._parse_cdragon_spells({}, "foo") == {}

    def test_casing_split_root_and_spells(self):
        # Fiddlesticks-class: Root (with spellNames) under one name casing,
        # the ability spell records under the OTHER casing. Must still resolve.
        doc = {
            "Characters/FiddleSticks/CharacterRecords/Root": {
                "spellNames": [
                    "FiddleSticksQAbility/FiddleSticksQ", "", "", "",
                ]
            },
            "Characters/Fiddlesticks/Spells/FiddleSticksQAbility/FiddleSticksQ": {
                "mSpell": {"mSpellTags": ["Trait_ImmobilizingCCSpell"]}
            },
        }
        out = C._parse_cdragon_spells(doc, "fiddlesticks")
        assert "Q" in out
        assert out["Q"]["cc_tags"] == ["Trait_ImmobilizingCCSpell"]


# --------------------------------------------------------------------------- _char_root_name
class TestCharRootName:
    def test_derives_internal_name(self):
        assert C._char_root_name(CORKI, "corki") == "Corki"

    def test_mismatched_casing_name(self):
        doc = {"Characters/MonkeyKing/CharacterRecords/Root": {}}
        assert C._char_root_name(doc, "wukong") == "MonkeyKing"

    def test_no_characters_key(self):
        assert C._char_root_name({"Other/Thing": {}}, "x") is None

    def test_multi_root_prefers_one_with_spellnames(self):
        # Fiddlesticks-class: an effigy/clone character precedes the real champ;
        # only the real root carries spellNames. Must skip the effigy.
        doc = {
            "Characters/FiddleSticksTrinket/CharacterRecords/Root": {},
            "Characters/FiddleSticks/CharacterRecords/Root": {
                "spellNames": ["Drain/FiddleSticksDrain"]
            },
        }
        assert C._char_root_name(doc, "fiddlesticks") == "FiddleSticks"

    def test_multi_root_falls_back_to_first_when_none_have_spellnames(self):
        doc = {
            "Characters/A/CharacterRecords/Root": {},
            "Characters/B/CharacterRecords/Root": {},
        }
        assert C._char_root_name(doc, "x") == "A"


# --------------------------------------------------------------------------- extract
class TestExtract:
    def test_happy_path_multi_champ(self, monkeypatch):
        ids = ["Corki", "Leona", "Nautilus"]
        bins = {"Corki": CORKI, "Leona": LEONA, "Nautilus": NAUTILUS}
        monkeypatch.setattr(C, "_load_champion_ids", lambda p: ids)
        monkeypatch.setattr(
            C, "_fetch_with_retry", lambda url, **kw: json.dumps(_bin_for(url, bins))
        )
        out = C.extract("16.11.1", sleep_s=0, limit=None, verbose=False)
        assert out["_champ_count"] == 3
        assert out["_patch_segment"] == "16.11"
        # Corki R ammo + 3 champs each carry CC tags + cones
        assert out["_with_ammo"] == 1  # only Corki R
        assert out["_with_cc_tags"] >= 5  # Leona Q/E/R + Nautilus Q/R
        assert out["_with_geometry"] >= 1
        assert out["champions"]["Corki"]["spells"]["R"]["ammo"]["max"][0] == 4

    def test_limit_caps_calls(self, monkeypatch):
        ids = ["Corki", "Leona", "Nautilus"]
        bins = {"Corki": CORKI, "Leona": LEONA, "Nautilus": NAUTILUS}
        monkeypatch.setattr(C, "_load_champion_ids", lambda p: ids)
        monkeypatch.setattr(
            C, "_fetch_with_retry", lambda url, **kw: json.dumps(_bin_for(url, bins))
        )
        out = C.extract("16.11.1", sleep_s=0, limit=2, verbose=False)
        assert out["_champ_count"] == 2

    def test_fail_soft_on_bad_bin(self, monkeypatch):
        monkeypatch.setattr(C, "_load_champion_ids", lambda p: ["Corki"])

        def boom(url, **kw):
            raise RuntimeError("404 blocked")

        monkeypatch.setattr(C, "_fetch_with_retry", boom)
        out = C.extract("16.11.1", sleep_s=0, limit=None, verbose=False)
        assert out["champions"]["Corki"]["spells"] == {}
        assert len(out["_errors"]) == 1
        assert "cdragon" in out["_errors"][0]
        assert out["_with_ammo"] == 0

    def test_unparseable_bin_records_miss(self, monkeypatch):
        # a 200 with no Characters root -> "no spellNames" miss, not a crash
        monkeypatch.setattr(C, "_load_champion_ids", lambda p: ["Corki"])
        monkeypatch.setattr(
            C, "_fetch_with_retry", lambda url, **kw: json.dumps({"Other": {}})
        )
        out = C.extract("16.11.1", sleep_s=0, limit=None, verbose=False)
        assert out["champions"]["Corki"]["spells"] == {}
        assert any("no spellNames" in e for e in out["_errors"])

    def test_ascii_only_output(self, monkeypatch):
        monkeypatch.setattr(C, "_load_champion_ids", lambda p: ["Corki"])
        monkeypatch.setattr(
            C, "_fetch_with_retry", lambda url, **kw: json.dumps(CORKI)
        )
        out = C.extract("16.11.1", sleep_s=0, limit=None, verbose=False)
        json.dumps(out, ensure_ascii=True)  # must not raise

    def test_engine_independent_no_imports(self):
        src = open(C.__file__, encoding="utf-8").read()
        assert "import requests" not in src
        _assert_agents_imports_allowlisted(src, C.__file__)

    def test_allowlisted_helper_is_itself_engine_free(self):
        _assert_mode_variants_is_leaf()


# --------------------------------------------------------------------------- _fetch_with_retry
class TestFetchWithRetry:
    def test_first_try_wins(self, monkeypatch):
        monkeypatch.setattr(C, "_fetch", lambda url, timeout=40: "OK")
        assert C._fetch_with_retry("http://x", retries=3, backoff_s=0) == "OK"

    def test_retries_then_succeeds(self, monkeypatch):
        seq = [RuntimeError("404"), "OK"]

        def fake(url, timeout=40):
            v = seq.pop(0)
            if isinstance(v, Exception):
                raise v
            return v

        monkeypatch.setattr(C, "_fetch", fake)
        assert C._fetch_with_retry("http://x", retries=3, backoff_s=0) == "OK"

    def test_raises_after_exhausting(self, monkeypatch):
        def boom(url, timeout=40):
            raise RuntimeError("perma 404")

        monkeypatch.setattr(C, "_fetch", boom)
        with pytest.raises(RuntimeError):
            C._fetch_with_retry("http://x", retries=2, backoff_s=0)


# --------------------------------------------------------------------------- ASCII hygiene
class TestAsciiHygiene:
    def test_source_is_ascii(self):
        data = open(C.__file__, encoding="utf-8").read()
        try:
            data.encode("ascii")
        except UnicodeEncodeError as e:
            pytest.fail(f"non-ascii byte in extractor: {e}")
        assert "cdragon_spell" in C.__file__  # sanity: right module


# --------------------------------------------------------------------------- helper
def _bin_for(url: str, bins: dict) -> dict:
    """Pick the canned bin whose slug appears in the fetched URL."""
    for cid, doc in bins.items():
        if "/" + cid.lower() + "/" in url or cid.lower() + ".bin.json" in url:
            return doc
    return {}

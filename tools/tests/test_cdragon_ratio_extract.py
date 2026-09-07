# arch: offline tests for the cdragon ability-ratio sidecar extractor | section=tools-tests | frozen=no
"""Offline unit tests for ``tools/daemon_slayer_cdragon_ratio_extract.py``.

NO network. The resolver core is fed INLINE python-dict fixtures shaped like real
CommunityDragon character-bin spell records (mSpell with DataValues +
mSpellCalculations.<Calc>.mFormulaParts). Each fixture is a minimal but
shape-faithful slice of a live 16.11 bin (verified against lux/zac/jhin/darius).
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

import daemon_slayer_cdragon_ratio_extract as R  # noqa: E402

# --------------------------------------------------------------------------- engine-independence guard
# RM-170 (2026-08-06). This guard used to read `assert "from agents" not in src`.
# Commit d0ad0569 (2026-07-30, "patch refresh 16.15.1 + partition the new
# throwback-mode registry") deliberately added ONE engine import to both cdragon
# extractors and did not update the guard, so it went red and STAYED red - which
# nobody saw, because `pytest tests` does not collect tools/tests.
#
# The contract is kept, not deleted: the extractors must stay runnable without
# the DS engine's behaviour. `canonical_champions` is allowlisted because
# agents/daemon_slayer/mode_variants.py is a stdlib-only pure-data registry, and
# duplicating that champion-id mapping into tools/ would be a drift hazard worse
# than the coupling. Any OTHER agents import still fails, and
# _assert_mode_variants_is_leaf keeps the allowance honest by asserting the
# allowlisted module has not itself grown engine dependencies.
# Matched via AST, NOT text. The first cut of this guard compared the stripped
# source LINE with startswith(), which a semicolon walks straight through:
# `from agents...import canonical_champions; from agents.daemon_slayer import dps`
# imports fine, passes ruff, and passed that guard. Parsing removes the whole
# class of textual bypasses (semicolons, aliasing, line continuations, trailing
# lint-suppression comments) instead of patching them one at a time.
_ALLOWED_AGENTS_IMPORTS = frozenset({
    ("agents.daemon_slayer.mode_variants", ("canonical_champions",)),
})
# `typing` and `__future__` are in sys.stdlib_module_names already; named here
# only so the intent of the leaf rule is readable.
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

    This is the whole justification for allowlisting it, so it has to test the
    real property. An earlier cut only rejected the literal string
    `import requests`, which `import httpx` sailed past. Assert against
    sys.stdlib_module_names instead, and treat a RELATIVE import as a failure
    too - `from . import x` inside agents/daemon_slayer reaches the engine.
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


def _dv(name, values):
    return {"name": name, "values": list(values), "__type": "SpellDataValue"}


def _mspell(data_values, calcs):
    return {"DataValues": list(data_values), "mSpellCalculations": dict(calcs)}


def _only_block(mspell, calc_name):
    blocks = R.resolve_spell_damage_blocks(mspell)
    by = {b["name"]: b for b in blocks}
    assert calc_name in by, f"{calc_name} not in {list(by)}"
    return by[calc_name]


# --------------------------------------------------------------------------- 1. Lux-Q-like base + AP
class TestLuxQLike:
    BASE = [40.0, 80.0, 120.0, 160.0, 200.0, 240.0, 280.0]

    def _mspell(self):
        return _mspell(
            [_dv("BaseDamage", self.BASE), _dv("APRatio", [0.75] * 7)],
            {
                "TotalDamage": {
                    "mFormulaParts": [
                        {"mDataValue": "BaseDamage",
                         "__type": "NamedDataValueCalculationPart"},
                        {"mDataValue": "APRatio",
                         "__type": "StatByNamedDataValueCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )

    def test_base_and_ap_resolved(self):
        b = _only_block(self._mspell(), "TotalDamage")
        assert b["resolution"] == "mechanical"
        # CDragon arrays are rank-0..rankN length 7; engine indexes rank N at N-1.
        # After trim (len>=6), leading rank-0 entry is dropped: index 0 becomes rank 1.
        assert b["base"] == self.BASE[1:]
        assert b["ap_pct"] == [75.0] * 6

    def test_no_other_ratio_fields(self):
        b = _only_block(self._mspell(), "TotalDamage")
        assert b["total_ad_pct"] is None
        assert b["bonus_ad_pct"] is None
        assert b["caster_max_hp_pct"] is None
        assert b["target_max_hp_pct"] is None


# --------------------------------------------------------------------------- 2. inline coefficient AP
class TestInlineCoefficient:
    def test_coefficient_ap(self):
        # Lux Q live shape: StatByCoefficient with mCoefficient and NO mStat -> AP.
        ms = _mspell(
            [_dv("BaseDamage", [20.0, 65.0, 115.0, 165.0, 215.0, 265.0, 315.0])],
            {
                "TotalDamageTT": {
                    "mFormulaParts": [
                        {"mDataValue": "BaseDamage",
                         "__type": "NamedDataValueCalculationPart"},
                        {"mCoefficient": 1.2,
                         "__type": "StatByCoefficientCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "TotalDamageTT")
        assert b["resolution"] == "mechanical"
        # BaseDamage is len 7; after trim rank-0: base len 6, rank_len becomes 6.
        assert b["base"] == [65.0, 115.0, 165.0, 215.0, 265.0, 315.0]
        assert b["ap_pct"] == [120.0] * 6


# --------------------------------------------------------------------------- 3. total-AD (mStat 2)
class TestTotalAd:
    def test_stat2_is_total_ad(self):
        ms = _mspell(
            [_dv("ADRatio", [0.9] * 5)],
            {
                "TotalDamage": {
                    "mFormulaParts": [
                        {"mStat": 2, "mDataValue": "ADRatio",
                         "__type": "StatByNamedDataValueCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "TotalDamage")
        assert b["resolution"] == "mechanical"
        assert b["total_ad_pct"] == [90.0] * 5
        assert b["ap_pct"] is None

    def test_stat8_is_bonus_ad(self):
        # Jhin-passive live shape: StatByCoefficient mStat 8 -> bonus AD.
        ms = _mspell(
            [],
            {
                "BonusADCalc": {
                    "mFormulaParts": [
                        {"mStat": 8, "mCoefficient": 0.35,
                         "__type": "StatByCoefficientCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "BonusADCalc")
        assert b["resolution"] == "mechanical"
        # no data values -> coefficient broadcasts to the default 7-rank length
        assert b["bonus_ad_pct"] == pytest.approx([35.0] * 7)
        assert b["total_ad_pct"] is None  # mStat 8 is bonus AD, not total AD


# --------------------------------------------------------------------------- 4. max-HP caster (mStat 12)
class TestMaxHpCaster:
    def test_stat12_health_ratio_is_caster(self):
        # Zac-Q live shape: base + AP + HealthRatio(mStat 12, mStatFormula 2).
        ms = _mspell(
            [
                _dv("BaseDamage", [40.0, 55.0, 70.0, 85.0, 100.0]),
                _dv("APRatio", [0.30] * 5),
                _dv("HealthRatio", [0.03] * 5),
            ],
            {
                "TotalDamage": {
                    "mFormulaParts": [
                        {"mDataValue": "BaseDamage",
                         "__type": "NamedDataValueCalculationPart"},
                        {"mDataValue": "APRatio",
                         "__type": "StatByNamedDataValueCalculationPart"},
                        {"mStat": 12, "mStatFormula": 2, "mDataValue": "HealthRatio",
                         "__type": "StatByNamedDataValueCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "TotalDamage")
        assert b["resolution"] == "mechanical"
        assert b["base"] == [40.0, 55.0, 70.0, 85.0, 100.0]
        assert b["ap_pct"] == [30.0] * 5
        assert b["caster_max_hp_pct"] == [3.0] * 5  # 0.03 fraction -> 3.0 percent
        assert b["target_max_hp_pct"] is None

    def test_stat12_target_named_is_target(self):
        # a Target-prefixed data value flips the caster default to target max HP.
        ms = _mspell(
            [_dv("TargetHealthRatio", [0.08] * 5)],
            {
                "TotalDamage": {
                    "mFormulaParts": [
                        {"mStat": 12, "mStatFormula": 2,
                         "mDataValue": "TargetHealthRatio",
                         "__type": "StatByNamedDataValueCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "TotalDamage")
        assert b["resolution"] == "mechanical"
        assert b["target_max_hp_pct"] == [8.0] * 5
        assert b["caster_max_hp_pct"] is None


# --------------------------------------------------------------------------- 5. GameCalculationModified flat ref
class TestGameCalculationModified:
    def test_flat_ref_times_multiplier_resolves(self):
        # Darius-Cleave live shape: HandleDamage = BladeDamage * 0.35, BladeDamage
        # is a flat (base + total-AD) calc, so the modified block resolves.
        ms = _mspell(
            [
                _dv("BladeBase", [10.0, 20.0, 30.0, 40.0, 50.0]),
                _dv("BladeADRatio", [1.0] * 5),
            ],
            {
                "BladeDamage": {
                    "mFormulaParts": [
                        {"mDataValue": "BladeBase",
                         "__type": "NamedDataValueCalculationPart"},
                        {"mStat": 2, "mDataValue": "BladeADRatio",
                         "__type": "StatByNamedDataValueCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                },
                "HandleDamage": {
                    "mFormulaParts": [
                        {
                            "mMultiplier": {"mNumber": 0.35,
                                            "__type": "NumberCalculationPart"},
                            "mModifiedGameCalculation": "BladeDamage",
                            "__type": "GameCalculationModified",
                        }
                    ],
                    "__type": "GameCalculation",
                },
            },
        )
        b = _only_block(ms, "HandleDamage")
        assert b["resolution"] == "mechanical"
        # base 10..50 * 0.35; total-AD ratio 100% * 0.35 = 35%
        assert b["base"] == pytest.approx([3.5, 7.0, 10.5, 14.0, 17.5])
        assert b["total_ad_pct"] == pytest.approx([35.0] * 5)

    def test_modified_ref_to_nonflat_calc_falls_back(self):
        # if the referenced calc carries a level part, the modified block falls back.
        ms = _mspell(
            [],
            {
                "LevelCalc": {
                    "mFormulaParts": [
                        {"__type": "ByCharLevelInterpolationCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                },
                "HandleDamage": {
                    "mFormulaParts": [
                        {
                            "mMultiplier": {"mNumber": 0.5,
                                            "__type": "NumberCalculationPart"},
                            "mModifiedGameCalculation": "LevelCalc",
                            "__type": "GameCalculationModified",
                        }
                    ],
                    "__type": "GameCalculation",
                },
            },
        )
        b = _only_block(ms, "HandleDamage")
        assert b["resolution"] == "fallback"
        assert b["base"] is None


# --------------------------------------------------------------------------- 6. HARD fallback (level part)
class TestHardFallback:
    @pytest.mark.parametrize("bad_type", [
        "ByCharLevelInterpolationCalculationPart",
        "ByCharLevelBreakpointsCalculationPart",
        "BuffCounterByNamedDataValueCalculationPart",
        "BuffCounterByCoefficientCalculationPart",
        "GameCalculationConditional",
        "StatBySubPartCalculationPart",
    ])
    def test_level_or_buff_part_forces_fallback(self, bad_type):
        ms = _mspell(
            [_dv("BaseDamage", [10.0] * 5)],
            {
                "TotalDamage": {
                    "mFormulaParts": [
                        {"mDataValue": "BaseDamage",
                         "__type": "NamedDataValueCalculationPart"},
                        {"__type": bad_type},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "TotalDamage")
        assert b["resolution"] == "fallback"
        # NO ratio/base fields populated on a fallback block
        assert b["base"] is None
        for f in ("ap_pct", "total_ad_pct", "bonus_ad_pct",
                  "caster_max_hp_pct", "target_max_hp_pct"):
            assert b[f] is None

    def test_cross_ref_spell_calculation_key_falls_back(self):
        ms = _mspell(
            [],
            {
                "TotalDamage": {
                    "mFormulaParts": [
                        {"mSpellCalculationKey": "SomeBuffCalc",
                         "__type": "StatByNamedDataValueCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "TotalDamage")
        assert b["resolution"] == "fallback"


# --------------------------------------------------------------------------- 7. unknown stat enum -> fallback
class TestUnknownStatEnum:
    def test_unknown_enum_falls_back_conservatively(self):
        # mStat 4 (attack speed, live: Jhin AS ratio) is NOT a damage stat we map.
        ms = _mspell(
            [_dv("ASRatio", [0.3] * 5)],
            {
                "TotalDamage": {
                    "mFormulaParts": [
                        {"mStat": 4, "mStatFormula": 2, "mDataValue": "ASRatio",
                         "__type": "StatByNamedDataValueCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "TotalDamage")
        assert b["resolution"] == "fallback"
        for f in ("ap_pct", "total_ad_pct", "bonus_ad_pct",
                  "caster_max_hp_pct", "target_max_hp_pct"):
            assert b[f] is None

    def test_unknown_coefficient_enum_falls_back(self):
        ms = _mspell(
            [],
            {
                "C": {
                    "mFormulaParts": [
                        {"mStat": 99, "mCoefficient": 0.5,
                         "__type": "StatByCoefficientCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "C")
        assert b["resolution"] == "fallback"


# --------------------------------------------------------------------------- subpart product/sum (flat-only)
class TestSubParts:
    def test_product_of_stat_ratio_and_number_scales_ratio(self):
        # (APRatio[0.5]) * (mNumber 2.0) -> 100% AP ratio (0.5*2.0=1.0 -> 100.0).
        ms = _mspell(
            [_dv("APRatio", [0.5] * 5)],
            {
                "C": {
                    "mFormulaParts": [
                        {
                            "mPart1": {"mDataValue": "APRatio",
                                       "__type": "StatByNamedDataValueCalculationPart"},
                            "mPart2": {"mNumber": 2.0,
                                       "__type": "NumberCalculationPart"},
                            "__type": "ProductOfSubPartsCalculationPart",
                        }
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "C")
        assert b["resolution"] == "mechanical"
        assert b["ap_pct"] == pytest.approx([100.0] * 5)

    def test_product_with_nonflat_subpart_falls_back(self):
        ms = _mspell(
            [_dv("APRatio", [0.5] * 5)],
            {
                "C": {
                    "mFormulaParts": [
                        {
                            "mPart1": {"mDataValue": "APRatio",
                                       "__type": "StatByNamedDataValueCalculationPart"},
                            "mPart2": {"__type": "ByCharLevelBreakpointsCalculationPart"},
                            "__type": "ProductOfSubPartsCalculationPart",
                        }
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "C")
        assert b["resolution"] == "fallback"

    def test_sum_of_flat_base_parts_combines(self):
        ms = _mspell(
            [_dv("A", [10.0] * 5), _dv("B", [5.0] * 5)],
            {
                "C": {
                    "mFormulaParts": [
                        {
                            "mSubparts": [
                                {"mDataValue": "A",
                                 "__type": "NamedDataValueCalculationPart"},
                                {"mDataValue": "B",
                                 "__type": "NamedDataValueCalculationPart"},
                            ],
                            "__type": "SumOfSubPartsCalculationPart",
                        }
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "C")
        assert b["resolution"] == "mechanical"
        assert b["base"] == pytest.approx([15.0] * 5)


# --------------------------------------------------------------------------- mDataValues alias + cherry note
class TestDataValuesAliasAndCherry:
    def test_reads_mdatavalues_alias(self):
        # the older Riot tooling names the list mDataValues; the resolver reads it.
        ms = {
            "mDataValues": [_dv("BaseDamage", [10.0] * 5), _dv("APRatio", [0.4] * 5)],
            "mSpellCalculations": {
                "TotalDamage": {
                    "mFormulaParts": [
                        {"mDataValue": "BaseDamage",
                         "__type": "NamedDataValueCalculationPart"},
                        {"mDataValue": "APRatio",
                         "__type": "StatByNamedDataValueCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        }
        b = _only_block(ms, "TotalDamage")
        assert b["base"] == [10.0] * 5
        assert b["ap_pct"] == pytest.approx([40.0] * 5)

    def test_cherry_override_noted_not_used(self):
        ms = _mspell(
            [_dv("APRatio", [0.5] * 5)],
            {
                "TotalDamage": {
                    "mFormulaParts": [
                        {"mDataValue": "APRatio",
                         "__type": "StatByNamedDataValueCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        ms["DataValuesModeOverride"] = {"cherry": {"APRatio": [0.9] * 5}}
        b = _only_block(ms, "TotalDamage")
        # SR/default value used (0.5 -> 50.0), cherry NOT the primary, just flagged
        assert b["ap_pct"] == pytest.approx([50.0] * 5)
        assert b["cherry_override"] is True

    def test_missing_data_value_falls_back(self):
        ms = _mspell(
            [],  # no DataValues at all
            {
                "TotalDamage": {
                    "mFormulaParts": [
                        {"mDataValue": "APRatio",
                         "__type": "StatByNamedDataValueCalculationPart"},
                    ],
                    "__type": "GameCalculation",
                }
            },
        )
        b = _only_block(ms, "TotalDamage")
        assert b["resolution"] == "fallback"


# --------------------------------------------------------------------------- resolve_spell_damage_blocks shape
class TestSpellBlocks:
    def test_empty_when_no_calcs(self):
        assert R.resolve_spell_damage_blocks({}) == []
        assert R.resolve_spell_damage_blocks({"DataValues": []}) == []

    def test_multiple_calcs_sorted(self):
        ms = _mspell(
            [_dv("A", [1.0] * 5)],
            {
                "ZCalc": {"mFormulaParts": [
                    {"mDataValue": "A", "__type": "NamedDataValueCalculationPart"}],
                    "__type": "GameCalculation"},
                "ACalc": {"mFormulaParts": [
                    {"mDataValue": "A", "__type": "NamedDataValueCalculationPart"}],
                    "__type": "GameCalculation"},
            },
        )
        blocks = R.resolve_spell_damage_blocks(ms)
        assert [b["name"] for b in blocks] == ["ACalc", "ZCalc"]

    def test_ascii_output(self):
        ms = _mspell(
            [_dv("BaseDamage", [10.0] * 5), _dv("APRatio", [0.75] * 5)],
            {"T": {"mFormulaParts": [
                {"mDataValue": "BaseDamage",
                 "__type": "NamedDataValueCalculationPart"},
                {"mDataValue": "APRatio",
                 "__type": "StatByNamedDataValueCalculationPart"}],
                "__type": "GameCalculation"}},
        )
        json.dumps(R.resolve_spell_damage_blocks(ms), ensure_ascii=True)  # no raise


# --------------------------------------------------------------------------- resolve_bin_ratios (slot mapping)
class TestResolveBinRatios:
    def _bin(self):
        # a minimal single-champ bin: Root.spellNames + one Q spell record.
        return {
            "Characters/Lux/CharacterRecords/Root": {
                "spellNames": [
                    "LuxQAbility/LuxQ", "LuxWAbility/LuxW",
                    "LuxEAbility/LuxE", "LuxRAbility/LuxR",
                ],
            },
            "Characters/Lux/Spells/LuxQAbility/LuxQ": {
                "mSpell": _mspell(
                    [_dv("BaseDamage", [40.0] * 7), _dv("APRatio", [0.6] * 7)],
                    {"TotalDamage": {"mFormulaParts": [
                        {"mDataValue": "BaseDamage",
                         "__type": "NamedDataValueCalculationPart"},
                        {"mDataValue": "APRatio",
                         "__type": "StatByNamedDataValueCalculationPart"}],
                        "__type": "GameCalculation"}},
                ),
            },
        }

    def test_q_slot_resolved(self):
        out = R.resolve_bin_ratios(self._bin(), "lux")
        assert "Q" in out
        q = out["Q"]
        # BaseDamage and APRatio are len 7; after trim rank-0 they become len 6.
        assert any(b["resolution"] == "mechanical" and b["ap_pct"] == [60.0] * 6
                   for b in q)

    def test_no_root_returns_empty(self):
        assert R.resolve_bin_ratios({"junk": 1}, "lux") == {}


# --------------------------------------------------------------------------- drift builder
class TestDrift:
    def test_drift_changed_and_match(self, tmp_path, monkeypatch):
        # Meraki says Lux Q ap_pct=[60..], CDragon resolves [75..] -> changed row.
        monkeypatch.setattr(R, "DATA_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        (pd / "champion_abilities.json").write_text(
            json.dumps({"data": {"Lux": {"Q": [
                {"damage_blocks": [
                    {"attribute": "Magic Damage", "base": [40.0] * 7,
                     "ap_pct": [60.0] * 7}]}]}}}),
            encoding="utf-8",
        )
        cdragon = {
            "_n_fallback_blocks": 2,
            "champions": {"Lux": {"Q": [
                {"name": "T", "base": [40.0] * 7, "ap_pct": [75.0] * 7,
                 "total_ad_pct": None, "bonus_ad_pct": None,
                 "caster_max_hp_pct": None, "target_max_hp_pct": None,
                 "resolution": "mechanical", "calc_type": "GameCalculation"}]}},
        }
        drift = R.build_drift("16.11.1", cdragon)
        s = drift["summary"]
        assert s["n_changed"] == 1
        assert s["n_blocks_compared"] == 1
        assert s["n_fallback"] == 2
        row = next(r for r in drift["rows"] if r["field"] == "ap_pct")
        assert row["meraki"] == [60.0] * 7
        assert row["cdragon"] == [75.0] * 7
        assert row["delta"] == pytest.approx(15.0)
        assert row["kind"] == "changed"

    def test_drift_only_cdragon_and_meraki_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr(R, "DATA_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        # Meraki has a total_ad_pct CDragon never resolves (meraki_only); CDragon
        # resolves a bonus_ad_pct Meraki lacks (only_cdragon).
        (pd / "champion_abilities.json").write_text(
            json.dumps({"data": {"Zed": {"Q": [
                {"damage_blocks": [
                    {"attribute": "Phys", "base": [10.0] * 5,
                     "total_ad_pct": [100.0] * 5}]}]}}}),
            encoding="utf-8",
        )
        cdragon = {
            "_n_fallback_blocks": 0,
            "champions": {"Zed": {"Q": [
                {"name": "T", "base": None, "ap_pct": None,
                 "total_ad_pct": None, "bonus_ad_pct": [40.0] * 5,
                 "caster_max_hp_pct": None, "target_max_hp_pct": None,
                 "resolution": "mechanical", "calc_type": "GameCalculation"}]}},
        }
        drift = R.build_drift("16.11.1", cdragon)
        s = drift["summary"]
        assert s["n_only_cdragon"] == 1
        assert s["n_meraki_only"] == 1
        assert s["n_blocks_compared"] == 0

    def test_drift_ascii(self, tmp_path, monkeypatch):
        monkeypatch.setattr(R, "DATA_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        (pd / "champion_abilities.json").write_text(
            json.dumps({"data": {"Lux": {"Q": [
                {"damage_blocks": [{"attribute": "M", "ap_pct": [60.0] * 5}]}]}}}),
            encoding="utf-8",
        )
        cdragon = {"_n_fallback_blocks": 0, "champions": {"Lux": {"Q": [
            {"name": "T", "ap_pct": [60.0] * 5, "base": None,
             "total_ad_pct": None, "bonus_ad_pct": None,
             "caster_max_hp_pct": None, "target_max_hp_pct": None,
             "resolution": "mechanical", "calc_type": "GameCalculation"}]}}}
        drift = R.build_drift("16.11.1", cdragon)
        json.dumps(drift, ensure_ascii=True)  # must not raise


# --------------------------------------------------------------------------- extract subset + fail-soft
class TestExtract:
    def test_subset_and_failsoft(self, tmp_path, monkeypatch):
        monkeypatch.setattr(R, "DATA_DIR", tmp_path)
        pd = tmp_path / "16.11.1"
        pd.mkdir()
        (pd / "champion_abilities.json").write_text(
            json.dumps({"data": {"Lux": {}, "Darius": {}, "Zac": {}}}),
            encoding="utf-8",
        )

        def fake_blocks(cid, seg):
            if cid == "Darius":
                raise RuntimeError("blocked")
            return {"Q": [{"name": "T", "resolution": "mechanical", "base": [1.0],
                           "ap_pct": [50.0], "total_ad_pct": None,
                           "bonus_ad_pct": None, "caster_max_hp_pct": None,
                           "target_max_hp_pct": None, "calc_type": "GameCalculation"}]}

        monkeypatch.setattr(R, "_champ_blocks", fake_blocks)
        out = R.extract("16.11.1", sleep_s=0, limit=None,
                        champions=["Lux", "Darius"], verbose=False)
        assert out["_champ_count"] == 2  # Zac excluded by subset
        assert out["_n_mechanical_blocks"] == 1  # only Lux
        assert any("Darius" in e for e in out["_errors"])

    def test_engine_independent_no_agents_import(self):
        src = open(R.__file__, encoding="utf-8").read()
        assert "import requests" not in src
        _assert_agents_imports_allowlisted(src, R.__file__)

    def test_allowlisted_helper_is_itself_engine_free(self):
        _assert_mode_variants_is_leaf()


# --------------------------------------------------------------------------- leading rank-0 trim
class TestLeadingRankZeroTrim:
    def test_len7_base_and_ap_trimmed(self):
        # len-7 DataValues: rank-0 entry stripped; result len 6.
        ms = _mspell(
            [_dv("BaseDamage", [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0]),
             _dv("APRatio", [0.5] * 7)],
            {"T": {"mFormulaParts": [
                {"mDataValue": "BaseDamage",
                 "__type": "NamedDataValueCalculationPart"},
                {"mDataValue": "APRatio",
                 "__type": "StatByNamedDataValueCalculationPart"},
            ], "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["resolution"] == "mechanical"
        assert b["base"] == [20.0, 30.0, 40.0, 50.0, 60.0, 70.0]
        assert b["ap_pct"] == [50.0] * 6

    def test_len6_base_trimmed(self):
        # len-6 DataValues: rank-0 entry stripped; result len 5.
        ms = _mspell(
            [_dv("BaseDamage", [5.0, 10.0, 15.0, 20.0, 25.0, 30.0])],
            {"T": {"mFormulaParts": [
                {"mDataValue": "BaseDamage",
                 "__type": "NamedDataValueCalculationPart"},
            ], "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["resolution"] == "mechanical"
        assert b["base"] == [10.0, 15.0, 20.0, 25.0, 30.0]

    def test_len5_base_unchanged(self):
        # len-5 DataValues: below trim threshold, no trim applied.
        ms = _mspell(
            [_dv("BaseDamage", [10.0, 20.0, 30.0, 40.0, 50.0])],
            {"T": {"mFormulaParts": [
                {"mDataValue": "BaseDamage",
                 "__type": "NamedDataValueCalculationPart"},
            ], "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["resolution"] == "mechanical"
        assert b["base"] == [10.0, 20.0, 30.0, 40.0, 50.0]


# --------------------------------------------------------------------------- explosion guard
class TestExplosionGuard:
    def test_absurd_ap_ratio_is_fallback(self):
        # [76.0]*5 as AP ratio fraction -> 7600% - tooltip aggregate, not mechanical.
        ms = _mspell(
            [_dv("APRatio", [76.0] * 5)],
            {"T": {"mFormulaParts": [
                {"mDataValue": "APRatio",
                 "__type": "StatByNamedDataValueCalculationPart"},
            ], "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["resolution"] == "fallback"
        assert b["base"] is None
        for f in R._RATIO_FIELDS:
            assert b[f] is None

    def test_absurd_base_is_fallback(self):
        # base value > 5000 is an explosion (tooltip aggregate, not flat damage).
        ms = _mspell(
            [_dv("BaseDamage", [6000.0] * 5)],
            {"T": {"mFormulaParts": [
                {"mDataValue": "BaseDamage",
                 "__type": "NamedDataValueCalculationPart"},
            ], "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["resolution"] == "fallback"
        assert b["base"] is None

    def test_normal_base_and_ap_not_caught(self):
        # base 280 + ap 150% are within the explosion thresholds -> stays mechanical.
        ms = _mspell(
            [_dv("BaseDamage", [280.0] * 5), _dv("APRatio", [1.5] * 5)],
            {"T": {"mFormulaParts": [
                {"mDataValue": "BaseDamage",
                 "__type": "NamedDataValueCalculationPart"},
                {"mDataValue": "APRatio",
                 "__type": "StatByNamedDataValueCalculationPart"},
            ], "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["resolution"] == "mechanical"
        assert b["base"] == [280.0] * 5
        assert b["ap_pct"] == pytest.approx([150.0] * 5)


# --------------------------------------------------------------------------- fractional-base guard
class TestFractionalBaseGuard:
    def test_all_sub_one_base_is_fallback(self):
        # base [0.03]*5 - every value < 1.0 means a ratio leaked into the base.
        ms = _mspell(
            [_dv("BaseDamage", [0.03] * 5)],
            {"T": {"mFormulaParts": [
                {"mDataValue": "BaseDamage",
                 "__type": "NamedDataValueCalculationPart"},
            ], "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["resolution"] == "fallback"
        assert b["base"] is None

    def test_base_with_value_ge_one_not_caught(self):
        # base [3.0..7.0] has values >= 1.0 -> fractional guard does NOT trigger.
        ms = _mspell(
            [_dv("BaseDamage", [3.0, 4.0, 5.0, 6.0, 7.0]),
             _dv("APRatio", [0.4] * 5)],
            {"T": {"mFormulaParts": [
                {"mDataValue": "BaseDamage",
                 "__type": "NamedDataValueCalculationPart"},
                {"mDataValue": "APRatio",
                 "__type": "StatByNamedDataValueCalculationPart"},
            ], "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["resolution"] == "mechanical"
        assert b["base"] == [3.0, 4.0, 5.0, 6.0, 7.0]


# --------------------------------------------------------------------------- float32-noise snap
class TestFloatSnap:
    """CDragon bins store ratios as float32 (0.55 -> 0.550000011920929). The raw
    ``fraction*100`` then ``round6`` leaks that noise as ``55.000001`` / ``64.999998``
    which mis-compares byte-for-byte against the clean Meraki ``55.0`` / ``65.0``.
    The resolver must SNAP emitted base + ratio arrays so float32 noise collapses to
    the clean authored value while a genuine fractional ratio (67.5) survives."""

    def test_float32_noise_snaps_clean_ratio(self):
        ms = _mspell(
            [_dv("APRatio", [0.55000001, 0.60000002, 0.64999998, 0.69999999, 0.75])],
            {"T": {"mFormulaParts": [
                {"mDataValue": "APRatio",
                 "__type": "StatByNamedDataValueCalculationPart"}],
                "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["resolution"] == "mechanical"
        assert b["ap_pct"] == [55.0, 60.0, 65.0, 70.0, 75.0]

    def test_float32_noise_snaps_base(self):
        ms = _mspell(
            [_dv("BaseDamage", [129.999995, 130.000004, 130.0, 130.0, 130.0])],
            {"T": {"mFormulaParts": [
                {"mDataValue": "BaseDamage",
                 "__type": "NamedDataValueCalculationPart"}],
                "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["base"] == [130.0, 130.0, 130.0, 130.0, 130.0]

    def test_genuine_fractional_ratio_preserved(self):
        ms = _mspell(
            [_dv("APRatio", [0.675] * 5), _dv("APRatio2", [0.825] * 5)],
            {"T": {"mFormulaParts": [
                {"mDataValue": "APRatio",
                 "__type": "StatByNamedDataValueCalculationPart"}],
                "__type": "GameCalculation"}},
        )
        b = _only_block(ms, "T")
        assert b["ap_pct"] == [67.5] * 5


# --------------------------------------------------------------------------- ASCII hygiene (tool source)
class TestAsciiHygiene:
    def test_source_is_ascii(self):
        data = open(R.__file__, encoding="utf-8").read()
        try:
            data.encode("ascii")
        except UnicodeEncodeError as e:
            pytest.fail(f"non-ascii byte in extractor: {e}")
        # no smart quotes / en / em dashes specifically
        for bad in ("\u2013", "\u2014", "\u2018", "\u2019", "\u201c", "\u201d"):
            assert bad not in data
        assert "daemon_slayer_cdragon_ratio" in R.__file__

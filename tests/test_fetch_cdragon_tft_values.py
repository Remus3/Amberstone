"""RM-891: the CDragon TFT extract keeps the numbers, not just the words.

scripts/fetch_cdragon_tft.py used to keep apiName / name / desc per augment and
item, and only minUnits per trait, so 548 of 595 Set 18 augments carried an
unresolved `@Var@` placeholder ("Gain 3 random components, @Gold@ gold, ...")
while the raw payload held the value (`effects: {"Gold": 2.0}`).

The fixture mirrors raw rows measured 2026-10-25 on CDragon latest
cdragon/tft/en_us.json (Big Grab Bag, the Elderwood trait, the Golem Smash
ability). Trait effect variables arrive under hashed keys; `{b027c2f9}` is the
FNV-1a 32 hash of the lower-cased name "stonebarktreebonushealth", the name the
trait's own desc uses at that breakpoint. A placeholder naming a runtime
counter (`@TFTUnitProperty.item:...@`) has no value in the payload and must
stay in the text, marked, never guessed.
"""
from __future__ import annotations

import json

import scripts.fetch_cdragon_tft as fct

ELDERWOOD_DESC = (
    "Gain placeable Elderwood plants.<br><row>(@MinUnits@) A Stonebark Tree</row>"
    "<br><row>(@MinUnits@) Stonebark Trees gain @StonebarkTreeBonusHealth@ Health</row>")


def _raw():
    return {
        "sets": {"18": {
            "name": "Set10",
            "champions": [{
                "apiName": "DA_18_Golem", "name": "Golem", "cost": 1,
                "traits": ["Elderwood"], "role": "APTank",
                "stats": {"hp": 650.0, "armor": 35.0, "mana": 25.0, "range": 1.0},
                "ability": {"name": "Golem Smash", "icon": "x.tex",
                            "desc": "Slam for @ModifiedDamage@ magic damage.",
                            "variables": [{"name": "Damage",
                                           "value": [100.0, 300.0, 480.0]}]},
            }],
            "traits": [{
                "apiName": "DA_18_Elderwood", "name": "Elderwood",
                "desc": ELDERWOOD_DESC, "icon": "i.tex",
                "effects": [
                    {"minUnits": 3, "maxUnits": 4, "style": 1,
                     "variables": {"{0f90e7a4}": 0.25}},
                    {"minUnits": 5, "maxUnits": 25000, "style": 3,
                     "variables": {"{0f90e7a4}": 0.25, "{b027c2f9}": 200.0}},
                ],
            }],
        }},
        "setData": [{"mutator": "TFTSet18", "number": 18,
                     "augments": ["DA_18_BigGrabBag", "DA_18_Tracker"],
                     "items": ["DA_18_Blade"]}],
        "items": [
            {"apiName": "DA_18_BigGrabBag", "name": "Big Grab Bag", "isAugment": True,
             "desc": "Gain 3 random components, @Gold@ gold, and 1 Reforger.",
             "effects": {"Gold": 2.0}, "associatedTraits": []},
            {"apiName": "DA_18_Tracker", "name": "Tracker", "isAugment": True,
             "desc": ("Gain @bonushealth@ Health and @AS*100@% Attack Speed. "
                      "Total: @TFTUnitProperty.item:TFT_Tracker_Value1@"),
             "effects": {"BonusHealth": 150.0, "AS": 0.10000000149011612},
             "associatedTraits": []},
            {"apiName": "DA_18_Blade", "name": "Blade", "isAugment": False,
             "desc": "Deal @StonebarkTreeBonusHealth@ and @Missing@ and @Flag@.",
             "effects": {"{b027c2f9}": 12.5, "Flag": True},
             "composition": []},
        ],
    }


def _extract():
    return fct.build_extract(_raw(), 18, branch="latest", content_version=None,
                             fetched="2026-10-25")


def _by_api(rows):
    return {r["apiName"]: r for r in rows}


def test_augment_placeholder_resolves_from_effects_by_name():
    aug = _by_api(_extract()["augments"])["DA_18_BigGrabBag"]
    assert aug["desc"] == "Gain 3 random components, 2 gold, and 1 Reforger."


def test_multiplied_and_case_folded_placeholders_resolve():
    aug = _by_api(_extract()["augments"])["DA_18_Tracker"]
    assert aug["desc"].startswith("Gain 150 Health and 10% Attack Speed.")


def test_runtime_counter_placeholder_stays_marked_never_guessed():
    aug = _by_api(_extract()["augments"])["DA_18_Tracker"]
    assert aug["desc"].endswith("Total: @TFTUnitProperty.item:TFT_Tracker_Value1@")


def test_item_text_resolves_hashed_key_and_leaves_missing_or_non_numeric_marked():
    item = _by_api(_extract()["items"])["DA_18_Blade"]
    assert item["desc"] == "Deal 12.5 and @Missing@ and @Flag@."


def test_placeholder_census_is_recorded_per_kind():
    ph = _extract()["_placeholders"]
    assert ph["augments"] == {"total": 4, "resolved": 3}
    assert ph["items"] == {"total": 3, "resolved": 1}
    # Every trait placeholder names MinUnits or a variable the effects carry.
    assert ph["traits"] == {"total": 3, "resolved": 3}


def test_unit_rows_keep_stats_and_ability_variables():
    unit = _by_api(_extract()["units"])["DA_18_Golem"]
    assert unit["stats"] == {"hp": 650.0, "armor": 35.0, "mana": 25.0, "range": 1.0}
    assert unit["ability"] == {"name": "Golem Smash",
                               "desc": "Slam for @ModifiedDamage@ magic damage.",
                               "variables": {"Damage": [100.0, 300.0, 480.0]}}


def test_trait_values_kept_per_breakpoint_with_hashed_keys_named_from_the_desc():
    trait = _by_api(_extract()["traits"])["DA_18_Elderwood"]
    assert trait["breakpoints"] == [3, 5]
    assert trait["effects"] == [
        {"minUnits": 3, "maxUnits": 4, "variables": {"{0f90e7a4}": 0.25}},
        {"minUnits": 5, "maxUnits": 25000,
         "variables": {"{0f90e7a4}": 0.25, "StonebarkTreeBonusHealth": 200.0}},
    ]


def test_fnv1a_hash_matches_the_measured_cdragon_key():
    assert fct.bin_hash("StonebarkTreeBonusHealth") == "{b027c2f9}"


def test_extract_stays_ascii_json_serialisable():
    data = json.dumps(_extract(), ensure_ascii=True)
    assert "@Gold@" not in data


def _resolved(desc, effects):
    tally = {"total": 0, "resolved": 0}
    return fct._resolve(desc, effects, tally), tally


def test_non_finite_values_stay_marked_and_never_crash():
    nan, inf = float("nan"), float("inf")
    out, tally = _resolved("@A@ @B@ @C*1e400@ @D*nan@",
                           {"A": nan, "B": inf, "C": 2.0, "D": 1.0})
    assert out == "@A@ @B@ @C*1e400@ @D*nan@"
    assert tally == {"total": 4, "resolved": 0}


def test_small_and_fractional_values_are_never_rounded_to_zero():
    out, _ = _resolved("@A@|@B@|@C@|@D@|@E*100@",
                       {"A": 1e-05, "B": -0.004, "C": 0.005, "D": 1234567.5,
                        "E": 0.3333333432674408})
    assert out == "0.00001|-0.004|0.005|1234567.5|33.3333"


def test_a_stray_at_sign_does_not_swallow_the_next_placeholder():
    out, tally = _resolved("@X@ and @Missing and @Y@", {"X": 1.0, "Y": 2.0})
    assert out == "1 and @Missing and 2"
    assert tally == {"total": 2, "resolved": 2}


def test_values_and_products_past_exact_print_stay_marked_and_never_crash():
    huge = 10 ** 400
    out, tally = _resolved("@A@ @B*2@ @C@ @D@ @E*3@ @F*1.5@",
                           {"A": huge, "B": huge, "C": 10 ** 15 + 1, "D": 10 ** 15,
                            "E": 3 ** 33, "F": 2 ** 52 + 1})
    assert out == "@A@ @B*2@ @C@ 1000000000000000 @E*3@ @F*1.5@"
    assert tally == {"total": 6, "resolved": 1}


def test_only_a_plain_decimal_multiplier_is_applied():
    arabic_three = chr(0x0663)
    out, tally = _resolved(f"@X*@ @X*1_0@ @X*{arabic_three}@ @X*2@ @X*0.5@", {"X": 4.0})
    assert out == f"@X*@ @X*1_0@ @X*{arabic_three}@ 8 2"
    assert tally == {"total": 5, "resolved": 2}


def test_near_integers_render_exactly_unless_float32_noise():
    # Measured CDragon 16.21 noise: Tons of Stats I 3.999996, Clockwork
    # Accelerator 10.000002, Coronation 20.000005 (DDragon shows 4 / 10 / 20).
    out, _ = _resolved("@A@ @B*100@ @C*100@ @D@ @E@ @F@",
                       {"A": 1.00001, "B": 0.699999988079071, "C": 0.10000000149011612,
                        "D": 3.999996, "E": 10.000002, "F": 20.000005})
    assert out == "1.00001 70 10 4 10 20"


def test_hashed_trait_key_is_not_renamed_onto_an_existing_name():
    trait = {"desc": "@X@", "effects": [
        {"minUnits": 2, "maxUnits": 3,
         "variables": {fct.bin_hash("X"): 1.0, "X": 5.0}}]}
    tally = {"total": 0, "resolved": 0}
    rows = fct._trait_effects(trait, tally)
    assert rows[0]["variables"] == {fct.bin_hash("X"): 1.0, "X": 5.0}


def test_case_folded_keys_that_collide_are_ambiguous_not_guessed():
    out, _ = _resolved("@AB@ @ab@ @Cd@", {"Ab": 1.0, "aB": 2.0, "cD": 3.0})
    assert out == "@AB@ @ab@ 3"


def test_ability_and_stats_shapes_that_are_not_rows_never_crash_build_extract():
    raw = _raw()
    unit = raw["sets"]["18"]["champions"][0]
    unit["ability"] = {"name": "n", "desc": "d", "variables": 5}
    unit["stats"] = {"hp": float("nan"), "armor": 35.0, "range": "far"}
    ex = fct.build_extract(raw, 18, branch="latest", content_version=None,
                           fetched="2026-10-25")
    golem = _by_api(ex["units"])["DA_18_Golem"]
    assert golem["ability"]["variables"] == {}
    assert golem["stats"] == {"armor": 35.0}
    json.dumps(ex, allow_nan=False)


def test_non_finite_variable_values_become_null_not_nan_tokens():
    raw = _raw()
    ab = raw["sets"]["18"]["champions"][0]["ability"]
    ab["variables"] = [{"name": "Damage", "value": [1.0, float("inf"), "x"]},
                       {"name": ["x"], "value": 1.0}]
    raw["sets"]["18"]["traits"][0]["effects"][0]["variables"] = {"{0f90e7a4}": float("nan")}
    ex = fct.build_extract(raw, 18, branch="latest", content_version=None,
                           fetched="2026-10-25")
    assert _by_api(ex["units"])["DA_18_Golem"]["ability"]["variables"] == {
        "Damage": [1.0, None, None]}
    assert _by_api(ex["traits"])["DA_18_Elderwood"]["effects"][0]["variables"] == {
        "{0f90e7a4}": None}
    json.dumps(ex, allow_nan=False)


def test_a_multiplied_product_prints_exactly_at_any_size():
    out, tally = _resolved("@A*0.1@ @B*100000@ @C*100@ @D*100@ @E*1.5@",
                           {"A": 1234567, "B": 1.1, "C": 4321.1,
                            "D": 0.10000000149011612, "E": 600000000000001})
    assert out == "123456.7 110000 432110 10 900000000000001.5"
    assert tally == {"total": 5, "resolved": 5}


def test_a_trait_variable_cleaned_to_null_does_not_count_as_resolved():
    trait = {"desc": "@Good@ @Bad@ @MinUnits@", "effects": [
        {"minUnits": 2, "maxUnits": 3,
         "variables": {"Good": 1.0, "Bad": float("nan")}}]}
    tally = {"total": 0, "resolved": 0}
    fct._trait_effects(trait, tally)
    assert tally == {"total": 3, "resolved": 2}


def test_long_multipliers_are_refused_and_bounded_ones_stay_exact():
    out, tally = _resolved("@X*1.0000000000000000000000000001@ @Y*123456789.123456789@",
                           {"X": 100000, "Y": 12345.678901234567})
    assert out == ("@X*1.0000000000000000000000000001@ "
                   "1524157876695.625652796830777625363")  # Fraction-exact
    assert tally == {"total": 2, "resolved": 1}


def test_breakpoint_bounds_are_json_safe():
    raw = _raw()
    raw["sets"]["18"]["traits"][0]["effects"][1]["maxUnits"] = float("nan")
    ex = fct.build_extract(raw, 18, branch="latest", content_version=None,
                           fetched="2026-10-25")
    assert _by_api(ex["traits"])["DA_18_Elderwood"]["effects"][1]["maxUnits"] is None
    json.dumps(ex, allow_nan=False)


def test_a_small_product_is_rounded_once_from_the_exact_decimal():
    out, tally = _resolved("@A*10@ @B*10@ @C*0.1@ @D*0.001@ @E*0@ @F*1@",
                           {"A": 498.47450000000003, "B": 0.012501749999999999,
                            "C": 5e-324, "D": 1.23456e-318, "E": -2.5, "F": -0.0})
    assert out == "4984.75 0.125017 5e-325 1.23456e-321 0 0"
    assert tally == {"total": 6, "resolved": 6}


def test_an_unmultiplied_float_prints_its_own_decimal_text_rounded_once():
    out, _ = _resolved("@A@ @B@ @C@ @D@ @E@",
                       {"A": 5e-324, "B": 1.2347e-320, "C": 1.2345650000000001,
                        "D": 100000.0078125, "E": -0.0})
    assert out == "5e-324 1.2347e-320 1.23457 100000.0078125 0"

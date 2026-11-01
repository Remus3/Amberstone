"""Tests for tools/gated_g240_ratio_spot.py (G2-40 PREP, s144 lane gated c50).

Every game input is hand-built (RM-906: no real game, match or player id). The tool
is a read-only sampler and grader; these tests pin its refusals and verdicts, that
its prediction is the engine's own evaluator, and the source facts the doc row cites.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.daemon_slayer.abilities import AbilityForm, DamageBlock
from agents.daemon_slayer.stats import growth_multiplier
from tools import gated_frame_readback as frame_tool
from tools import gated_g240_ratio_spot as g240
from tools import gated_live_probe as probe_tool

ROOT = Path(__file__).resolve().parent.parent
TOOL_SRC = ROOT / "tools" / "gated_g240_ratio_spot.py"
MECH = {"resolution": "mechanical", "calc_type": "GameCalculation"}
FALL = {"resolution": "fallback", "calc_type": "GameCalculationModified"}
SYNTH_ID = "SyntheticPlayer#TEST"
T0 = 1000.0


def _form(blocks, *, damage_type="MAGIC", parse_status="ok", index=0):
    return AbilityForm(
        key="Q", name="Test", form_index=index, icon=None, cooldown=None, cost=None,
        damage_type=damage_type, targeting=None, affects=None, resource=None,
        is_aoe=False, damage_blocks=tuple(blocks), raw_effects_count=0,
        raw_leveling_count=0, parse_status=parse_status, parse_notes=(),
    )


def _dmg(name="Magic Damage", **fields):
    return DamageBlock(attribute=name, attribute_kind="damage", **fields)


class _Abilities:
    patch = "99.1.1"

    def __init__(self, champs):
        self.champions = champs

    def has_champion(self, champ):
        return champ in self.champions

    def champion_ids(self):
        return tuple(self.champions)

    def get_abilities(self, champ):
        return self.champions[champ]


class _Data:
    def __init__(self, ad_growth=0.0):
        self.ad_growth = ad_growth

    def champion(self, _champ):
        return {"stats": {"attackdamage": 60, "attackdamageperlevel": self.ad_growth,
                          "hp": 500, "hpperlevel": 0, "armor": 20, "armorperlevel": 0,
                          "spellblock": 30, "spellblockperlevel": 0, "mp": 300,
                          "mpperlevel": 0, "movespeed": 330}}


def _fixture():
    abilities = _Abilities({"Testchamp": {
        "P": (),
        # control: one mechanical block, one form, one damage block. Three distinct
        # ranks, so an off-by-one on the rank index shows.
        "Q": (_form([_dmg(base=(80.0, 120.0, 160.0), ap_pct=(85.0, 90.0, 95.0))]),),
        # fallback of the control's type, with a bonus-AD term.
        "W": (_form([_dmg("Ratio Damage", base=(10.0, 20.0, 30.0),
                          bonus_ad_pct=(100.0, 100.0, 100.0))]),),
        # fallback whose block the engine could not parse.
        "E": (_form([_dmg("Odd", base=(5.0,), unparsed_modifiers=({"x": 1},))]),),
        # mechanical but two damage blocks: not a clean control.
        "R": (_form([_dmg("A", base=(1.0,)), _dmg("B", base=(2.0,))]),),
    }, "Physchamp": {
        "Q": (_form([_dmg("Phys Control", base=(100.0,))], damage_type="PHYSICAL"),),
        "W": (_form([_dmg("Phys Ratio", base=(20.0,), bonus_ad_pct=(100.0,))],
                    damage_type="PHYSICAL"),),
        # A MAGIC fallback no PHYSICAL control can vouch for.
        "E": (_form([_dmg("Magic Ratio", base=(20.0,), ap_pct=(50.0,))]),),
        "R": (_form([_dmg("True Ratio", base=(20.0,), ap_pct=(50.0,))], damage_type="TRUE"),),
    }})
    sidecar = {"Testchamp": {"Q": [MECH], "W": [FALL, MECH], "E": [FALL], "R": [MECH]},
               "Physchamp": {"Q": [MECH], "W": [FALL], "E": [FALL], "R": [FALL]}}
    return abilities, sidecar


def _snap(*, mode="PRACTICETOOL", ranks=None, ad=100.0, ability_power=100.0, items=(),
          stats=None, raw="game_character_displayname_Testchamp", in_all_players=True,
          level=1, game_time=42.0):
    ranks = ranks or {"Q": 2, "W": 2, "E": 1, "R": 1}
    champion_stats = {
        "attackDamage": ad, "abilityPower": ability_power, "maxHealth": 1000.0,
        "armor": 40.0, "magicResist": 40.0, "resourceMax": 400.0, "moveSpeed": 345.0,
        "physicalLethality": 0.0, "magicPenetrationFlat": 0.0,
        "armorPenetrationPercent": 1.0, "magicPenetrationPercent": 1.0,
    }
    champion_stats.update(stats or {})
    me = {"riotId": SYNTH_ID, "level": level,
          "abilities": {k: {"abilityLevel": v} for k, v in ranks.items()},
          "championStats": champion_stats}
    players = []
    if in_all_players:
        players = [{"riotId": SYNTH_ID, "rawChampionName": raw,
                    "items": [{"itemID": i} for i in items]}]
    return {"activePlayer": me, "allPlayers": players,
            "gameData": {"gameMode": mode, "gameTime": game_time}}


def _capture(snapshot=None, key="Q", block="Magic Damage", form=0, armor=0.0, mr=0.0,
             hp=1000.0, source=g240.SOURCE_RELAY, captured_at=T0 + 42.0, data=None):
    abilities, sidecar = _fixture()
    return g240.capture(abilities, data or _Data(), sidecar, snapshot or _snap(), key=key,
                        block_name=block, form_index=form, target_armor=armor,
                        target_mr=mr, target_max_hp=hp, source=source,
                        captured_at=captured_at)


def _control(**kw):
    return _capture(**kw)


def _fallback(**kw):
    return _capture(key="W", block="Ratio Damage", **kw)


PHYS_RAW = "game_character_displayname_Physchamp"


def _phys(key, block, **kw):
    kw.setdefault("snapshot", _snap(raw=PHYS_RAW))
    return _capture(key=key, block=block, **kw)


# ---------------------------------------------------------------- classify


@pytest.mark.parametrize("key,blocks,expected", [
    ("Q", [MECH], "control"),
    ("Q", [MECH, MECH], "other"),   # the engine may stay on Meraki
    ("W", [FALL, MECH], "fallback"),
    ("E", [FALL], "fallback"),
    ("R", [MECH], "other"),         # two engine damage blocks
    ("Q", [], "other"),             # no sidecar block at all
    ("Q", None, "other"),
])
def test_classify_roles(key, blocks, expected):
    abilities, _ = _fixture()
    assert g240.classify(blocks, abilities.get_abilities("Testchamp")[key]) == expected


def test_classify_no_damage_block_is_other_even_with_a_fallback():
    util = DamageBlock(attribute="Slow", attribute_kind="slow", base=(1.0,))
    assert g240.classify([FALL], (_form([util]),)) == "other"
    assert g240.classify([FALL], ()) == "other"


@pytest.mark.parametrize("form", [
    _form([_dmg(base=(1.0,))], damage_type="MIXED"),
    _form([_dmg(base=(1.0,))], damage_type=None),
    _form([_dmg(base=(1.0,))], parse_status="partial"),
    _form([_dmg(base=(1.0,), unparsed_modifiers=({"x": 1},))]),
])
def test_a_control_must_be_cleanly_predictable(form):
    assert g240.classify([MECH], (form,)) == "other"


def test_two_forms_cannot_be_a_control():
    forms = (_form([_dmg(base=(1.0,))]), _form([_dmg(base=(1.0,))], index=1))
    assert g240.classify([MECH], forms) == "other"


# ---------------------------------------------------------------- prediction


def test_prediction_reads_the_live_rank_with_a_zero_based_index():
    assert _control()["raw"] == pytest.approx(120.0 + 0.90 * 100.0)
    snap = _snap(ranks={"Q": 3, "W": 1, "E": 1, "R": 1})
    assert _control(snapshot=snap)["raw"] == pytest.approx(160.0 + 0.95 * 100.0)
    assert _control(snapshot=snap)["rank"] == 3


def test_bonus_ad_is_live_ad_minus_base_at_the_live_level():
    snap = _snap(level=10)
    rec = _fallback(snapshot=snap, data=_Data(ad_growth=3.0))
    base_ad = 60.0 + 3.0 * growth_multiplier(10)
    assert rec["raw"] == pytest.approx(20.0 + (100.0 - base_ad))
    assert rec["level"] == 10


def test_mitigation_uses_the_resist_of_the_damage_type():
    magic = _control(armor=999.0, mr=50.0)
    assert magic["raw"] == pytest.approx(210.0)
    assert magic["predicted"] == pytest.approx(210.0 * 100.0 / 150.0)
    physical = _phys("W", "Phys Ratio", armor=100.0, mr=999.0)
    assert physical["predicted"] == pytest.approx(physical["raw"] / 2.0)


def test_true_damage_ignores_resist_and_needs_no_penetration_proof():
    abilities = _Abilities({"Testchamp": {
        "Q": (_form([_dmg("True", base=(50.0,))], damage_type="TRUE"),)}})
    rec = g240.capture(abilities, _Data(), {"Testchamp": {"Q": [MECH]}},
                       _snap(items=(1001,)), key="Q", block_name="True", form_index=0,
                       target_armor=30.0, target_mr=30.0, target_max_hp=1000.0,
                       source=g240.SOURCE_RELAY, captured_at=T0)
    assert rec["predicted"] == pytest.approx(50.0)


def test_unparsed_block_is_recorded_unpredictable():
    rec = _capture(key="E", block="Odd", snapshot=_snap())
    assert rec["unpredictable"] == "block has unparsed modifiers"


def test_record_carries_context_and_no_player_identity():
    rec = _control(captured_at=1234.5)
    assert rec["game_mode"] == "PRACTICETOOL"
    assert rec["game_time_s"] == 42.0
    assert rec["captured_at"] == 1234.5
    assert rec["source"] == g240.SOURCE_RELAY
    assert SYNTH_ID not in json.dumps(rec)


# ---------------------------------------------------------------- refusals


def test_champion_comes_from_the_raw_name_not_the_display_name():
    snap = _snap(raw="game_character_displayname_MonkeyKing")
    snap["allPlayers"][0]["championName"] = "Wukong"
    assert g240.active_champion(snap) == "MonkeyKing"
    snap["allPlayers"][0]["rawChampionName"] = "Wukong"
    with pytest.raises(g240.Refused):
        g240.active_champion(snap)


def test_the_active_row_is_the_riot_id_match_not_the_first_or_a_shared_name():
    snap = _snap(raw="game_character_displayname_Mine")
    mine = snap["allPlayers"][0]
    mine["summonerName"] = "Shared"
    other = {"riotId": "Other#TEST", "summonerName": "Shared",
             "rawChampionName": "game_character_displayname_Theirs", "items": []}
    snap["allPlayers"] = [other, mine]
    snap["activePlayer"]["summonerName"] = "Shared"
    assert g240.active_champion(snap) == "Mine"
    del snap["activePlayer"]["riotId"]
    assert g240.active_champion(snap) == "Theirs"  # name-only is all the payload gives


def test_champion_case_differs_between_client_and_snapshot():
    abilities, _ = _fixture()
    assert g240.resolve_champion(abilities, "TESTCHAMP") == "Testchamp"
    rec = _capture(snapshot=_snap(raw="game_character_displayname_testCHAMP"))
    assert rec["champion"] == "Testchamp"


@pytest.mark.parametrize("kwargs,fragment", [
    ({"snapshot": _snap(mode="CLASSIC")}, "not Practice Tool"),
    ({"snapshot": _snap(ranks={"Q": 0, "W": 1, "E": 1, "R": 1})}, "not levelled"),
    ({"key": "R", "block": "A"}, "neither a fallback nor a control"),
    ({"block": "No Such Block"}, "no damage block"),
    ({"form": 3}, "no form"),
    ({"snapshot": _snap(raw="game_character_displayname_Ghost")}, "not in the ability"),
    ({"snapshot": _snap(in_all_players=False)}, "not readable"),
    ({"snapshot": _snap(level=0)}, "level"),
    ({"snapshot": _snap(game_time=None)}, "gameTime"),
    ({"snapshot": _snap(stats={"abilityPower": None})}, "abilityPower"),
    ({"mr": -30.0}, "resist"),
    ({"armor": float("nan")}, "resist"),
    ({"mr": float("inf")}, "resist"),
    ({"hp": 0.0}, "max HP"),
    ({"hp": -5.0}, "max HP"),
    ({"hp": float("nan")}, "max HP"),
])
def test_capture_refusals(kwargs, fragment):
    with pytest.raises(g240.Refused, match=fragment):
        _capture(**kwargs)


def test_an_empty_stat_block_is_refused_not_read_as_zero():
    snap = _snap()
    snap["activePlayer"]["championStats"] = {}
    with pytest.raises(g240.Refused, match="championStats"):
        _capture(snapshot=snap)


@pytest.mark.parametrize("stats", [
    {"magicPenetrationFlat": 10.0},
    {"magicPenetrationFlat": None},
    {"magicPenetrationPercent": 0.67},
    {"magicPenetrationPercent": None},
    {"bonusMagicPenetrationPercent": 0.3},
    {"magicLethality": 18.0},
])
def test_resist_above_zero_refuses_unless_magic_penetration_is_proven_absent(stats):
    with pytest.raises(g240.Refused, match="penetration"):
        _capture(snapshot=_snap(stats=stats), mr=30.0)
    # The same state is fine on a 0 resist, where penetration cannot matter.
    assert _capture(snapshot=_snap(stats=stats))["predicted"] == pytest.approx(210.0)


@pytest.mark.parametrize("stats", [
    {"physicalLethality": 5.0},
    {"armorPenetrationFlat": 5.0},
    {"armorPenetrationPercent": 0.67},  # the item-free self-granted case
    {"bonusArmorPenetrationPercent": 0.3},
])
def test_resist_above_zero_refuses_unless_armor_penetration_is_proven_absent(stats):
    with pytest.raises(g240.Refused, match="penetration"):
        _phys("W", "Phys Ratio", snapshot=_snap(raw=PHYS_RAW, stats=stats), armor=30.0)


@pytest.mark.parametrize("none_value", [0.0, 1.0])
def test_both_ends_of_the_percent_field_read_as_no_penetration(none_value):
    snap = _snap(stats={"magicPenetrationPercent": none_value})
    assert _capture(snapshot=snap, mr=30.0)["predicted"] > 0


def test_items_refuse_a_resist_but_a_trinket_does_not(monkeypatch):
    with pytest.raises(g240.Refused, match="items owned"):
        _capture(snapshot=_snap(items=(3135,)), mr=30.0)
    monkeypatch.setattr(g240, "_non_inventory_ids", lambda: frozenset({"3340"}))
    assert _capture(snapshot=_snap(items=(3340,)), mr=30.0)["items_owned"] == 0
    with pytest.raises(g240.Refused, match="items owned"):
        _capture(snapshot=_snap(items=(3340, 3135)), mr=30.0)


def test_the_trinket_set_is_the_shared_one():
    ids = g240._non_inventory_ids()
    assert ids, "the shared set must load, or every resist capture refuses"
    from core.daemon_slayer_resolver import NON_INVENTORY_IDS
    assert ids == frozenset(str(i) for i in NON_INVENTORY_IDS)


def test_resist_above_zero_refuses_an_unreadable_item_list():
    snap = _snap()
    del snap["allPlayers"][0]["items"]
    with pytest.raises(g240.Refused, match="items owned"):
        _capture(snapshot=snap, mr=30.0)
    assert _capture(snapshot=snap)["items_owned"] is None


def test_base_stats_scale_every_field_with_the_live_level():
    class _Grown:
        def champion(self, _champ):
            return {"stats": {"attackdamage": 60, "attackdamageperlevel": 3,
                              "hp": 500, "hpperlevel": 100, "armor": 20, "armorperlevel": 4,
                              "spellblock": 30, "spellblockperlevel": 2, "mp": 300,
                              "mpperlevel": 25, "movespeed": 330}}

    grown = growth_multiplier(10)
    assert g240.base_stats(_Grown(), "x", 10) == pytest.approx({
        "ad": 60 + 3 * grown, "hp": 500 + 100 * grown, "armor": 20 + 4 * grown,
        "mr": 30 + 2 * grown, "mp": 300 + 25 * grown, "ms": 330.0})


def test_no_row_for_the_active_player_is_refused_not_the_first_row():
    snap = _snap()
    snap["allPlayers"][0]["riotId"] = "Other#TEST"
    with pytest.raises(g240.Refused, match="not readable"):
        g240.active_champion(snap)
    snap["allPlayers"] = 5
    with pytest.raises(g240.Refused, match="not readable"):
        g240.active_champion(snap)


def test_the_other_types_penetration_does_not_refuse():
    rec = _capture(snapshot=_snap(stats={"physicalLethality": 5.0}), mr=30.0)
    assert rec["predicted"] == pytest.approx(210.0 * 100.0 / 130.0)


def test_read_snapshot_envelope_freshness():
    data = _snap()
    assert g240.read_snapshot({"data": data, "ts": 1000.0}, now=1005.0) is data
    assert g240.read_snapshot(data) is data
    with pytest.raises(g240.Refused, match="stale"):
        g240.read_snapshot(data, now=1000.0)  # the live path needs the envelope's clock
    for ts in (1000.0 - g240.MAX_SNAPSHOT_AGE_S - 1.0, 1010.0, None, "x", float("nan")):
        with pytest.raises(g240.Refused, match="stale"):
            g240.read_snapshot({"data": data, "ts": ts}, now=1000.0)
    for bad in ([], {}, {"activePlayer": {}}):
        with pytest.raises(g240.Refused):
            g240.read_snapshot(bad)


def test_fetch_live_reads_the_relay_with_the_token(monkeypatch):
    calls = []

    def fake_get(url, token):
        calls.append((url, token))
        return {"data": _snap(), "ts": 500.0}, None

    monkeypatch.setattr(probe_tool, "_get_json", fake_get)
    monkeypatch.setattr(frame_tool, "resolve_token", lambda: ("synthetic-token", "env"))
    monkeypatch.setattr(g240.time, "time", lambda: 501.0)
    assert g240._fetch_live()["gameData"]["gameTime"] == 42.0
    assert calls == [("http://127.0.0.1:8889/latest-liveclient", "synthetic-token")]
    monkeypatch.setattr(g240.time, "time", lambda: 900.0)
    with pytest.raises(g240.Refused, match="stale"):
        g240._fetch_live()
    monkeypatch.setattr(probe_tool, "_get_json", lambda u, t: (None, "URLError"))
    with pytest.raises(g240.Refused, match="relay read failed"):
        g240._fetch_live()


# ---------------------------------------------------------------- grade


def test_sample_ok_needs_a_passing_control():
    result = g240.grade([(_control(), 210.0), (_fallback(), 60.0)])
    assert result["verdict"] == "SAMPLE_OK"
    assert [s["verdict"] for s in result["samples"]] == ["MATCH", "MATCH"]
    assert "not a tick" in result["note"]


def test_finding_is_a_fallback_miss_under_a_passing_control():
    result = g240.grade([(_control(), 210.0), (_fallback(), 90.0)])
    assert result["verdict"] == "FINDING"
    assert result["samples"][1]["verdict"] == "MISMATCH"


def test_no_control_voids_a_match_and_a_miss_alike():
    for observed in (60.0, 90.0):
        result = g240.grade([(_fallback(), observed)])
        assert result["verdict"] == "INCOMPLETE"
        assert result["samples"][0]["verdict"] == "VOID"


def test_a_control_miss_voids_a_fallback_miss_instead_of_blaming_ds():
    result = g240.grade([(_control(), 300.0), (_fallback(), 90.0)])
    assert result["verdict"] == "INCOMPLETE"
    assert result["samples"][1]["reason"].startswith("no passing same-type control")


def test_one_control_miss_beside_a_control_match_still_voids():
    abilities = _Abilities({"Testchamp": {
        "Q": (_form([_dmg(base=(80.0, 120.0), ap_pct=(90.0, 90.0))]),),
        "R": (_form([_dmg("Solo", base=(100.0,))]),),
        "W": (_form([_dmg("Ratio Damage", base=(10.0, 20.0), ap_pct=(50.0, 50.0))]),),
    }})
    sidecar = {"Testchamp": {"Q": [MECH], "R": [MECH], "W": [FALL]}}

    def cap(key, block):
        return g240.capture(abilities, _Data(), sidecar, _snap(), key=key, block_name=block,
                            form_index=0, target_armor=0.0, target_mr=0.0, target_max_hp=1000.0,
                            source=g240.SOURCE_RELAY, captured_at=T0)

    result = g240.grade([(cap("Q", "Magic Damage"), 210.0), (cap("R", "Solo"), 900.0),
                         (cap("W", "Ratio Damage"), 70.0)])
    assert result["verdict"] == "INCOMPLETE"
    assert result["samples"][2]["reason"] == "a control missed in this group"


@pytest.mark.parametrize("kwargs,observed", [
    ({"hp": 5000.0}, 210.0),
    ({"mr": 40.0}, 150.0),      # a clean MATCH at its own, different, resist
    ({"armor": 40.0}, 210.0),
])
def test_a_control_on_another_target_does_not_validate_the_sample(kwargs, observed):
    control = _control(**kwargs)
    result = g240.grade([(control, observed), (_fallback(), 60.0)])
    assert result["samples"][0]["verdict"] == "MATCH"
    assert result["samples"][1]["verdict"] == "VOID"
    assert result["verdict"] == "INCOMPLETE"


@pytest.mark.parametrize("field,value", [
    ("champion", "Otherchamp"),
    ("ds_patch", "98.1.1"),
])
def test_a_control_from_another_champion_or_patch_does_not_validate(field, value):
    control = _control()
    control[field] = value
    result = g240.grade([(control, 210.0), (_fallback(), 60.0)])
    assert result["samples"][0]["verdict"] == "MATCH"
    assert result["samples"][1]["verdict"] == "VOID"


def test_a_control_proves_only_the_resist_of_its_own_damage_type():
    # A wrong typed MR cannot be caught by a PHYSICAL control, so it must not FINDING.
    control = _phys("Q", "Phys Control", mr=100.0)
    magic = _phys("E", "Magic Ratio", mr=100.0)
    result = g240.grade([(control, 100.0), (magic, 900.0)])
    assert result["samples"][1]["verdict"] == "VOID"
    assert result["verdict"] == "INCOMPLETE"
    # The same pairing is fine for its own type, and for TRUE, which has no resist.
    same = g240.grade([(control, 100.0), (_phys("W", "Phys Ratio", mr=100.0), 60.0)])
    assert same["verdict"] == "SAMPLE_OK"
    true = g240.grade([(control, 100.0), (_phys("R", "True Ratio", mr=100.0), 70.0)])
    assert true["verdict"] == "SAMPLE_OK"


def test_a_true_control_proves_no_resist():
    abilities, sidecar = _fixture()
    abilities.champions["Physchamp"]["Q"] = (
        _form([_dmg("Phys Control", base=(100.0,))], damage_type="TRUE"),)

    def cap(key, block):
        return g240.capture(abilities, _Data(), sidecar, _snap(raw=PHYS_RAW), key=key,
                            block_name=block, form_index=0, target_armor=0.0, target_mr=0.0,
                            target_max_hp=1000.0, source=g240.SOURCE_RELAY,
                            captured_at=T0 + 42.0)

    result = g240.grade([(cap("Q", "Phys Control"), 100.0), (cap("W", "Phys Ratio"), 60.0)])
    assert result["samples"][1]["verdict"] == "VOID"


def test_a_match_with_the_ratio_times_zero_tests_nothing():
    snap = _snap(ability_power=0.0)
    control = _control(snapshot=snap)                # base-only is fine for a control
    assert control["ratio_part"] == pytest.approx(0.0)
    sample = _capture(snapshot=_snap(ad=60.0, ability_power=0.0), key="W",
                      block="Ratio Damage")          # 0 bonus AD
    assert sample["predicted"] == pytest.approx(20.0)
    result = g240.grade([(control, 120.0), (sample, 20.0)])
    assert result["samples"][0]["verdict"] == "MATCH"
    assert result["samples"][1]["verdict"] == "BASE_ONLY"
    assert result["verdict"] == "INCOMPLETE"


def test_a_miss_with_the_ratio_times_zero_is_still_a_finding():
    control = _control(snapshot=_snap(ability_power=0.0))
    sample = _capture(snapshot=_snap(ad=60.0, ability_power=0.0), key="W",
                      block="Ratio Damage")
    assert g240.grade([(control, 120.0), (sample, 90.0)])["verdict"] == "FINDING"


def test_the_ratio_part_must_clear_the_same_tolerance_as_the_match():
    untested = _capture(snapshot=_snap(ad=61.9), key="W", block="Ratio Damage")
    tested = _capture(snapshot=_snap(ad=62.5), key="W", block="Ratio Damage")
    control = _control()
    assert untested["ratio_part"] == pytest.approx(1.9)
    assert tested["ratio_part"] == pytest.approx(2.5)
    low = g240.grade([(control, 210.0), (untested, untested["predicted"])])
    assert low["samples"][1]["verdict"] == "BASE_ONLY"
    high = g240.grade([(control, 210.0), (tested, tested["predicted"])])
    assert high["samples"][1]["verdict"] == "MATCH"


@pytest.mark.parametrize("weakest,expected", [
    (10.0, "BASE_ONLY"),   # above the 2.0 floor, inside 3 percent of 1000
    (g240._tolerance(1000.0), "BASE_ONLY"),
    (31.0, "MATCH"),
])
def test_the_ratio_part_is_judged_by_the_relative_tolerance_on_a_big_hit(weakest, expected):
    sample = dict(_fallback(), predicted=1000.0, weakest_ratio_part=weakest)
    result = g240.grade([(_control(), 210.0), (sample, 1000.0)])
    assert result["samples"][1]["verdict"] == expected


def _mixed_sample():
    return dict(_fallback(), block="Mixed", damage_type="MIXED",
                unpredictable="damage type MIXED")


def test_an_unpredictable_sample_says_nothing_beside_a_clean_pass():
    result = g240.grade([(_control(), 210.0), (_fallback(), 60.0), (_mixed_sample(), 999.0)])
    row = result["samples"][2]
    assert row["verdict"] == "UNPREDICTABLE"
    assert row["reason"] == "damage type MIXED"
    assert result["verdict"] == "SAMPLE_OK"


def test_an_unpredictable_sample_alone_cannot_pass_or_find():
    result = g240.grade([(_mixed_sample(), 999.0)])
    assert result["samples"][0]["verdict"] == "UNPREDICTABLE"
    assert result["verdict"] == "INCOMPLETE"


def test_an_unpredictable_rehearsal_is_still_void():
    sample = dict(_mixed_sample(), source=g240.SOURCE_FILE)
    assert g240.grade([(sample, 999.0)])["samples"][0]["verdict"] == "VOID"


def test_a_block_scaling_on_target_state_is_unpredictable_and_no_control():
    block = _dmg("Tick", base=(5.0,), target_max_hp_pct=(2.0,))
    assert g240.classify([FALL], (_form([block]),)) == "fallback"
    assert g240.classify([MECH], (_form([block]),)) == "other"
    assert "target state" in g240._unpredictable_reason(_form([block]), block)
    mixed = _dmg("Mixed", base=(5.0,))
    assert "MIXED" in g240._unpredictable_reason(_form([mixed], damage_type="MIXED"), mixed)


def test_a_small_control_cannot_pass_a_wrong_resist_into_a_finding():
    # Typed MR 30, real MR 60. The small control sits inside the absolute floor, and
    # a bigger sample then misses by the same resist error: no DS defect anywhere.
    abilities = _Abilities({"Testchamp": {
        "Q": (_form([_dmg("Small", base=(10.0,))]),),
        "W": (_form([_dmg("Big", base=(175.0,), ap_pct=(10.0,))]),),
    }})
    sidecar = {"Testchamp": {"Q": [MECH], "W": [FALL]}}

    def cap(key, block):
        return g240.capture(abilities, _Data(), sidecar, _snap(), key=key, block_name=block,
                            form_index=0, target_armor=0.0, target_mr=30.0,
                            target_max_hp=1000.0, source=g240.SOURCE_RELAY, captured_at=T0)

    small, big = cap("Q", "Small"), cap("W", "Big")
    assert g240.matches(10.0 * 100.0 / 160.0, small["predicted"])
    result = g240.grade([(small, 10.0 * 100.0 / 160.0), (big, big["raw"] * 100.0 / 160.0)])
    assert result["samples"][0]["verdict"] == "WEAK"
    assert result["samples"][1]["verdict"] == "VOID"
    assert result["verdict"] == "INCOMPLETE"


def test_a_control_at_the_floor_counts_and_a_small_control_miss_still_voids():
    assert g240.CONTROL_MIN_PREDICTED == pytest.approx(2.0 / 0.03)
    abilities = _Abilities({"Testchamp": {
        "Q": (_form([_dmg("Edge", base=(67.0,))]),),
        "R": (_form([_dmg("Small", base=(10.0,))]),),
        "W": (_form([_dmg("Ratio", base=(20.0,), ap_pct=(50.0,))]),),
    }})
    sidecar = {"Testchamp": {"Q": [MECH], "R": [MECH], "W": [FALL]}}

    def cap(key, block):
        return g240.capture(abilities, _Data(), sidecar, _snap(), key=key, block_name=block,
                            form_index=0, target_armor=0.0, target_mr=0.0,
                            target_max_hp=1000.0, source=g240.SOURCE_RELAY, captured_at=T0)

    edge, small, ratio = cap("Q", "Edge"), cap("R", "Small"), cap("W", "Ratio")
    assert g240.grade([(edge, 67.0), (ratio, 70.0)])["verdict"] == "SAMPLE_OK"
    missed = g240.grade([(edge, 67.0), (small, 40.0), (ratio, 90.0)])
    assert missed["samples"][1]["verdict"] == "MISMATCH"
    assert missed["samples"][2]["verdict"] == "VOID"


def test_a_repeated_block_name_cannot_say_which_number_it_is():
    abilities = _Abilities({"Testchamp": {
        "Q": (_form([_dmg("Control", base=(100.0,))]),),
        "W": (_form([_dmg("Magic Damage", base=(150.0,)), _dmg("Magic Damage", base=(525.0,)),
                     _dmg("Unique", base=(20.0,), ap_pct=(50.0,))]),),
        "E": (_form([_dmg("Magic Damage", base=(1.0,)), _dmg("Magic Damage", base=(2.0,))]),),
    }})
    sidecar = {"Testchamp": {"Q": [MECH], "W": [FALL], "E": [FALL]}}

    def cap(key, block):
        return g240.capture(abilities, _Data(), sidecar, _snap(), key=key, block_name=block,
                            form_index=0, target_armor=0.0, target_mr=0.0,
                            target_max_hp=1000.0, source=g240.SOURCE_RELAY, captured_at=T0)

    repeated = cap("W", "Magic Damage")
    assert repeated["unpredictable"] == "block name repeats in this form"
    result = g240.grade([(cap("Q", "Control"), 100.0), (repeated, 525.0)])
    assert result["samples"][1]["verdict"] == "UNPREDICTABLE"
    assert result["verdict"] == "INCOMPLETE"
    assert cap("W", "Unique")["unpredictable"] is None
    out = g240.plan(abilities, sidecar, "Testchamp")
    assert out["sample_order"] == ["W"]
    assert out["uncovered"] == ["E"]


def test_plan_leaves_out_a_covered_type_with_no_gradeable_block():
    abilities = _Abilities({"Testchamp": {
        "Q": (_form([_dmg("Control", base=(100.0,))]),),
        "W": (_form([_dmg("Tick", base=(5.0,), target_max_hp_pct=(2.0,))]),),
    }})
    out = g240.plan(abilities, {"Testchamp": {"Q": [MECH], "W": [FALL]}}, "Testchamp")
    assert out["sample_order"] == []
    assert out["uncovered"] == ["W"]


def test_a_second_capture_at_a_raised_stat_is_a_new_sample():
    low = _fallback()
    high = _fallback(snapshot=_snap(ad=150.0))
    assert low["predicted"] != high["predicted"]
    result = g240.grade([(_control(), 210.0), (low, low["predicted"]),
                         (high, high["predicted"])])
    assert result["verdict"] == "SAMPLE_OK"


def test_a_fractional_rank_is_not_read_as_a_rank():
    snap = _snap(ranks={"Q": 1.5, "W": 1, "E": 1, "R": 1})
    with pytest.raises(g240.Refused, match="not levelled"):
        _capture(snapshot=snap)


def test_a_non_finite_prediction_is_refused():
    abilities = _Abilities({"Testchamp": {"Q": (_form([_dmg(ap_pct=(1e308,))]),)}})
    with pytest.raises(g240.Refused, match="not finite"):
        g240.capture(abilities, _Data(), {"Testchamp": {"Q": [MECH]}},
                     _snap(ability_power=1e308), key="Q", block_name="Magic Damage",
                     form_index=0, target_armor=0.0, target_mr=0.0, target_max_hp=1000.0,
                     source=g240.SOURCE_RELAY, captured_at=T0)


def test_each_ratio_must_show_one_cannot_cover_for_another():
    abilities = _Abilities({"Testchamp": {
        "Q": (_form([_dmg("Control", base=(100.0,))]),),
        "W": (_form([_dmg("Both", base=(20.0,), ap_pct=(30.0,), bonus_ad_pct=(40.0,))]),),
    }})
    sidecar = {"Testchamp": {"Q": [MECH], "W": [FALL]}}

    def cap(snapshot):
        return (g240.capture(abilities, _Data(), sidecar, snapshot, key="Q",
                             block_name="Control", form_index=0, target_armor=0.0,
                             target_mr=0.0, target_max_hp=1000.0,
                             source=g240.SOURCE_RELAY, captured_at=T0),
                g240.capture(abilities, _Data(), sidecar, snapshot, key="W", block_name="Both",
                             form_index=0, target_armor=0.0, target_mr=0.0,
                             target_max_hp=1000.0, source=g240.SOURCE_RELAY,
                             captured_at=T0))

    control, ad_only = cap(_snap(ad=260.0, ability_power=0.0))  # 200 bonus AD, 0 AP
    assert ad_only["ratio_part"] == pytest.approx(80.0)
    assert ad_only["weakest_ratio_part"] == 0.0
    result = g240.grade([(control, 100.0), (ad_only, ad_only["predicted"])])
    assert result["samples"][1]["verdict"] == "BASE_ONLY"
    assert result["verdict"] == "INCOMPLETE"

    control, both = cap(_snap(ad=260.0, ability_power=100.0))
    assert both["weakest_ratio_part"] == pytest.approx(30.0)
    assert g240.grade([(control, 100.0), (both, both["predicted"])])["verdict"] == "SAMPLE_OK"
    # A miss there still counts: a base-only read is no excuse for a wrong number.
    control, ad_only = cap(_snap(ad=260.0, ability_power=0.0))
    assert g240.grade([(control, 100.0), (ad_only, 300.0)])["verdict"] == "FINDING"


def test_the_weakest_ratio_part_is_mitigated_like_the_prediction():
    rec = _control(mr=50.0)
    assert rec["weakest_ratio_part"] == pytest.approx(0.90 * 100.0 * 100.0 / 150.0)
    assert _capture(key="E", block="Odd")["weakest_ratio_part"] == 0.0


def test_an_edited_weakest_ratio_part_does_not_re_derive():
    rec = _fallback()
    rec["weakest_ratio_part"] = 500.0
    with pytest.raises(g240.Refused, match="re-derive"):
        _verify(rec)


def test_a_voided_sample_cannot_sit_under_a_pass():
    # A gross miss with no control of its type must not read as a pass overall.
    abilities = _Abilities({"Testchamp": {
        "Q": (_form([_dmg("Control", base=(100.0,))]),),
        "W": (_form([_dmg("Magic Ratio", base=(20.0,), ap_pct=(50.0,))]),),
        "E": (_form([_dmg("Phys Ratio", base=(20.0,), ap_pct=(50.0,))], damage_type="PHYSICAL"),),
    }})
    sidecar = {"Testchamp": {"Q": [MECH], "W": [FALL], "E": [FALL]}}

    def cap(key, block):
        return g240.capture(abilities, _Data(), sidecar, _snap(), key=key, block_name=block,
                            form_index=0, target_armor=0.0, target_mr=0.0,
                            target_max_hp=1000.0, source=g240.SOURCE_RELAY, captured_at=T0)

    result = g240.grade([(cap("Q", "Control"), 100.0), (cap("W", "Magic Ratio"), 70.0),
                         (cap("E", "Phys Ratio"), 9999.0)])
    assert [s["verdict"] for s in result["samples"]] == ["MATCH", "MATCH", "VOID"]
    assert result["verdict"] == "INCOMPLETE"


@pytest.mark.parametrize("field", g240._TARGET_STATE_FIELDS)
def test_every_target_state_field_is_unpredictable_alone_or_as_a_sibling(field):
    assert field in DamageBlock.__dataclass_fields__
    scaling = _dmg("Tick", base=(5.0,), **{field: (2.0,)})
    assert "target state" in g240._unpredictable_reason(_form([scaling]), scaling)
    assert g240.classify([MECH], (_form([scaling]),)) == "other"
    floor = _dmg("Minimum", base=(50.0,))
    both = _form([floor, scaling])
    assert "target state" in g240._unpredictable_reason(both, floor)


def test_a_bilinear_term_is_target_state_too():
    block = _dmg("Product", base=(5.0,), bilinear_terms=((0.01, "ap", "target_max_hp"),))
    assert "target state" in g240._unpredictable_reason(_form([block]), block)
    plain = _dmg("Plain", base=(5.0,))
    assert g240._unpredictable_reason(_form([plain]), plain) is None


def test_a_floor_block_beside_a_target_scaling_sibling_is_unpredictable():
    floor = _dmg("Minimum Bonus Damage", base=(50.0,))
    scaling = _dmg("Bonus Damage", target_max_hp_pct=(6.0,))
    form = _form([floor, scaling])
    assert "target state" in g240._unpredictable_reason(form, floor)
    abilities = _Abilities({"Testchamp": {"Q": (_form([_dmg("Control", base=(100.0,))]),),
                                          "W": (form,)}})
    out = g240.plan(abilities, {"Testchamp": {"Q": [MECH], "W": [FALL]}}, "Testchamp")
    assert out["sample_order"] == []


@pytest.mark.parametrize("observed,expected", [
    (103.0, False),    # the tolerance itself is a match
    (104.0, True),
    (106.0, True),     # the band's edge: 2 x 3
    (106.5, False),
    (94.0, True),
    (93.5, False),
])
def test_the_near_miss_band_is_twice_the_tolerance(observed, expected):
    assert g240.near_miss(observed, 100.0) is expected


def test_a_miss_a_passing_control_could_hide_is_not_a_finding():
    # Typed MR 30, real MR 34, whole-number combat text: the control just passes and
    # the sample just misses, with no DS defect anywhere.
    abilities = _Abilities({"Testchamp": {
        "Q": (_form([_dmg("Control", base=(410.0,))]),),
        "W": (_form([_dmg("Sample", base=(150.0,), ap_pct=(25.0,))]),),
    }})
    sidecar = {"Testchamp": {"Q": [MECH], "W": [FALL]}}

    def cap(key, block):
        return g240.capture(abilities, _Data(), sidecar, _snap(ability_power=200.0), key=key,
                            block_name=block, form_index=0, target_armor=0.0, target_mr=30.0,
                            target_max_hp=1000.0, source=g240.SOURCE_RELAY, captured_at=T0)

    control, sample = cap("Q", "Control"), cap("W", "Sample")
    real = 100.0 / 134.0
    control_seen = round(control["raw"] * real)
    sample_seen = round(sample["raw"] * real)
    result = g240.grade([(control, float(control_seen)), (sample, float(sample_seen))])
    assert result["samples"][0]["verdict"] == "MATCH"
    assert result["samples"][1]["verdict"] == "NEAR_MISS"
    assert result["verdict"] == "INCOMPLETE"


def test_a_near_miss_beside_a_match_is_not_a_sample_ok():
    other = _capture(key="W", block="Ratio Damage", snapshot=_snap(ad=150.0))
    result = g240.grade([(_control(), 210.0), (_fallback(), 60.0),
                         (other, other["predicted"] + 5.0)])
    assert result["samples"][2]["verdict"] == "NEAR_MISS"
    assert result["verdict"] == "INCOMPLETE"


def test_a_near_miss_control_still_voids_the_group():
    result = g240.grade([(_control(), 210.0 + 8.0), (_fallback(), 60.0)])
    assert result["samples"][0]["verdict"] == "MISMATCH"
    assert result["samples"][1]["verdict"] == "VOID"


def test_every_finding_says_it_is_a_candidate():
    result = g240.grade([(_control(), 210.0), (_fallback(), 90.0)])
    assert result["verdict"] == "FINDING"
    assert "candidate" in result["note"]


def test_a_fractional_level_is_refused():
    with pytest.raises(g240.Refused, match="level"):
        _capture(snapshot=_snap(level=1.5))


def test_a_control_minutes_apart_in_one_game_still_validates():
    assert g240.SESSION_SKEW_S == 120.0
    later = _control(snapshot=_snap(game_time=642.0), captured_at=T0 + 642.0)
    assert g240.grade([(later, 210.0), (_fallback(), 60.0)])["verdict"] == "SAMPLE_OK"


def test_a_control_from_another_game_does_not_validate_the_sample():
    far = _control(captured_at=T0 + 42.0 + g240.SESSION_SKEW_S + 1.0)
    result = g240.grade([(far, 210.0), (_fallback(), 60.0)])
    assert result["samples"][1]["verdict"] == "VOID"
    near = _control(captured_at=T0 + 42.0 + g240.SESSION_SKEW_S - 1.0)
    assert g240.grade([(near, 210.0), (_fallback(), 60.0)])["verdict"] == "SAMPLE_OK"


@pytest.mark.parametrize("which", ["control", "fallback", "both"])
def test_a_rehearsal_from_a_file_never_counts(which):
    control = _control(source=g240.SOURCE_FILE if which != "fallback" else g240.SOURCE_RELAY)
    sample = _fallback(source=g240.SOURCE_FILE if which != "control" else g240.SOURCE_RELAY)
    result = g240.grade([(control, 210.0), (sample, 60.0)])
    assert result["verdict"] == "INCOMPLETE"
    assert result["samples"][1]["verdict"] == "VOID"


def test_a_rehearsal_miss_is_no_finding():
    result = g240.grade([(_control(), 210.0), (_fallback(source=g240.SOURCE_FILE), 90.0)])
    assert result["verdict"] == "INCOMPLETE"


def test_unpredictable_fallback_never_counts_as_a_finding_or_a_pass():
    odd = _capture(key="E", block="Odd")
    result = g240.grade([(_control(), 210.0), (odd, 999.0)])
    assert result["samples"][1]["verdict"] == "UNPREDICTABLE"
    assert result["verdict"] == "INCOMPLETE"


@pytest.mark.parametrize("observed,predicted,expected", [
    (102.0, 100.0, True),     # ABS_TOL at the low end
    (103.0, 100.0, True),     # 3 percent of 100
    (103.5, 100.0, False),
    (1030.0, 1000.0, True),
    (1031.0, 1000.0, False),
    (970.0, 1000.0, True),
    (2.0, 0.0, True),
    (2.5, 0.0, False),
])
def test_tolerance_is_the_stated_predicate(observed, predicted, expected):
    assert g240.matches(observed, predicted) is expected


def _n_fallbacks(n):
    out = []
    for i in range(n):
        rec = _fallback()
        rec["block"] = f"Block {i}"
        out.append((rec, 60.0))
    return out


def test_bulk_pass_is_refused_and_controls_do_not_count():
    fine = [(_control(), 210.0)] + _n_fallbacks(g240.MAX_FALLBACK_SAMPLES)
    assert g240.grade(fine)["verdict"] == "SAMPLE_OK"
    with pytest.raises(g240.Refused, match="bulk pass"):
        g240.grade([(_control(), 210.0)] + _n_fallbacks(g240.MAX_FALLBACK_SAMPLES + 1))


def test_repeated_sample_is_refused():
    with pytest.raises(g240.Refused, match="repeated"):
        g240.grade([(_fallback(), 60.0), (_fallback(), 60.0)])


@pytest.mark.parametrize("observed", [
    0, -1.0, "60", None, True, float("nan"), float("inf"),
])
def test_observed_must_be_a_positive_finite_number(observed):
    with pytest.raises(g240.Refused, match="positive"):
        g240.grade([(_fallback(), observed)])


@pytest.mark.parametrize("record", [
    {}, [], {"tool": "other"}, {"tool": g240.TOOL},
])
def test_foreign_records_are_refused(record):
    with pytest.raises(g240.Refused):
        g240.grade([(record, 60.0)])


@pytest.mark.parametrize("field,value", [
    ("role", "other"), ("source", "typed"), ("key", "P"),
    ("predicted", float("inf")), ("predicted", float("nan")), ("predicted", "60"),
    ("predicted", None), ("predicted", [60.0]), ("raw", None),
    ("target_armor", None), ("target_armor", [1.0]), ("target_armor", -1.0),
    ("target_max_hp", 0.0), ("ds_patch", None), ("champion", ""), ("block", 7),
    ("rank", 0), ("rank", "2"), ("rank", True), ("level", 0), ("form", -1),
    ("stats", {}), ("stats", None), ("unpredictable", 1),
    ("captured_at", None), ("game_time_s", float("nan")), ("game_time_s", -1.0),
    ("ratio_part", None), ("weakest_ratio_part", None), ("rank", 7), ("level", 31), ("predicted", 10 ** 400),
])
def test_unusable_record_values_are_refused_never_a_crash(field, value):
    rec = _fallback()
    rec[field] = value
    with pytest.raises(g240.Refused):
        g240.grade([(rec, 60.0)])


# ---------------------------------------------------------------- re-derive


def _verify(rec, data=None):
    abilities, sidecar = _fixture()
    return g240.verify_record(rec, abilities, data or _Data(), sidecar)


def test_an_untouched_record_re_derives():
    assert _verify(_control())["role"] == "control"
    assert _verify(_fallback())["role"] == "fallback"
    assert _verify(_control(mr=50.0))["predicted"] == pytest.approx(140.0)


@pytest.mark.parametrize("field,value,fragment", [
    ("predicted", 90.0, "re-derive"),
    ("role", "control", "re-derive"),      # a fallback relabelled as a control
    ("damage_type", "TRUE", "re-derive"),
    ("unpredictable", "edited", "re-derive"),
    ("rank", 3, "re-derive"),              # the prediction was for rank 2
    ("target_armor", 50.0, None),          # a magic block ignores armor: still clean
    ("target_mr", 50.0, "re-derive"),
    ("ratio_part", 0.0, "re-derive"),
    ("ds_patch", "98.1.1", "DS patch"),
    ("champion", "Ghost", "not in the ability"),
    ("block", "No Such Block", "no damage block"),
])
def test_an_edited_record_does_not_re_derive(field, value, fragment):
    rec = _fallback()
    rec[field] = value
    if fragment is None:
        assert _verify(rec)
        return
    with pytest.raises(g240.Refused, match=fragment):
        _verify(rec)


# ---------------------------------------------------------------- CLI


@pytest.fixture
def cli(monkeypatch):
    abilities, sidecar = _fixture()
    monkeypatch.setattr(g240, "load_data", lambda: (abilities, _Data(), sidecar))
    monkeypatch.setattr(g240, "_fetch_live", lambda: pytest.fail("no live read expected"))
    return monkeypatch


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


_TARGET = ["--target-armor", "0", "--target-mr", "0", "--target-max-hp", "1000"]


def _cap_args(key, block, out):
    return ["capture", "--key", key, "--block", block, "--out", str(out), *_TARGET]


def test_cli_live_capture_then_grade_round_trip(tmp_path, cli, capsys):
    cli.setattr(g240, "_fetch_live", _snap)
    ctl, smp = tmp_path / "control.json", tmp_path / "sample.json"
    assert g240.main(_cap_args("Q", "Magic Damage", ctl)) == 0
    assert g240.main(_cap_args("W", "Ratio Damage", smp)) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["control.json", "sample.json"]
    assert json.loads(ctl.read_text(encoding="utf-8"))["source"] == g240.SOURCE_RELAY
    capsys.readouterr()
    assert g240.main(["grade", f"{ctl}=210", f"{smp}=60"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "SAMPLE_OK"
    assert g240.main(["grade", f"{ctl}=210", f"{smp}=90"]) == 3
    assert json.loads(capsys.readouterr().out)["verdict"] == "FINDING"


def test_cli_snapshot_capture_is_a_rehearsal_grade_never_counts(tmp_path, cli, capsys):
    snap = _write_json(tmp_path / "snap.json", {"data": _snap(), "ts": 1.0})
    ctl, smp = tmp_path / "control.json", tmp_path / "sample.json"
    assert g240.main([*_cap_args("Q", "Magic Damage", ctl), "--snapshot", snap]) == 0
    assert g240.main([*_cap_args("W", "Ratio Damage", smp), "--snapshot", snap]) == 0
    capsys.readouterr()
    assert g240.main(["grade", f"{ctl}=210", f"{smp}=60"]) == 3
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "INCOMPLETE"
    assert {s["verdict"] for s in out["samples"]} == {"VOID"}


def test_cli_grade_refuses_an_edited_record(tmp_path, cli, capsys):
    cli.setattr(g240, "_fetch_live", _snap)
    ctl, smp = tmp_path / "control.json", tmp_path / "sample.json"
    assert g240.main(_cap_args("Q", "Magic Damage", ctl)) == 0
    assert g240.main(_cap_args("W", "Ratio Damage", smp)) == 0
    rec = json.loads(smp.read_text(encoding="utf-8"))
    rec["predicted"] = 90.0
    smp.write_text(json.dumps(rec), encoding="utf-8")
    capsys.readouterr()
    assert g240.main(["grade", f"{ctl}=210", f"{smp}=90"]) == 2
    assert "re-derive" in capsys.readouterr().err


def test_cli_never_overwrites_an_earlier_lock(tmp_path, cli, capsys):
    cli.setattr(g240, "_fetch_live", _snap)
    out = tmp_path / "rec.json"
    assert g240.main(_cap_args("Q", "Magic Damage", out)) == 0
    before = out.read_bytes()
    assert g240.main(_cap_args("Q", "Magic Damage", out)) == 2
    assert out.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["rec.json"]
    assert "overwrite" in capsys.readouterr().err


def test_cli_refused_capture_writes_nothing(tmp_path, cli, capsys):
    snap = _write_json(tmp_path / "snap.json", _snap(mode="CLASSIC"))
    out = tmp_path / "rec.json"
    code = g240.main([*_cap_args("Q", "Magic Damage", out), "--snapshot", snap])
    assert code == 2
    assert not out.exists()
    assert "REFUSED" in capsys.readouterr().err


def test_cli_plan_from_a_snapshot_lists_cast_order(tmp_path, cli, capsys):
    snap = _write_json(tmp_path / "snap.json", _snap())
    assert g240.main(["plan", "--snapshot", snap]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["champion"] == "Testchamp"
    assert out["sample_order"] == ["W"]
    assert out["no_control"] is False
    assert out["uncovered"] == ["E"]  # its only block is unparsed: nothing to grade
    assert {r["key"]: r["role"] for r in out["abilities"]} == {
        "Q": "control", "W": "fallback", "E": "fallback"}


def test_plan_leaves_a_fallback_no_control_covers_out_of_the_cast_order():
    abilities, sidecar = _fixture()
    out = g240.plan(abilities, sidecar, "Physchamp")
    assert out["sample_order"] == ["W", "R"]
    assert out["uncovered"] == ["E"]


def test_plan_says_when_a_champion_has_no_control():
    abilities, sidecar = _fixture()
    sidecar["Testchamp"]["Q"] = [FALL]
    assert g240.plan(abilities, sidecar, "Testchamp")["no_control"] is True
    with pytest.raises(g240.Refused):
        g240.plan(abilities, sidecar, "Ghost")


@pytest.mark.parametrize("pair", ["no-equals", "=5", "file.json=abc"])
def test_cli_bad_pair_exits_2(pair, capsys):
    assert g240.main(["grade", pair]) == 2
    assert "REFUSED" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["nan", "inf", "-5"])
def test_cli_non_finite_observed_exits_2(tmp_path, cli, value, capsys):
    cli.setattr(g240, "_fetch_live", _snap)
    out = tmp_path / "rec.json"
    assert g240.main(_cap_args("W", "Ratio Damage", out)) == 0
    capsys.readouterr()
    assert g240.main(["grade", f"{out}={value}"]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_cli_out_into_a_missing_directory_exits_2(tmp_path, cli, capsys):
    cli.setattr(g240, "_fetch_live", _snap)
    assert g240.main(_cap_args("Q", "Magic Damage", tmp_path / "nope" / "q.json")) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_cli_never_touches_a_neighbouring_tmp_file(tmp_path, cli):
    cli.setattr(g240, "_fetch_live", _snap)
    neighbour = tmp_path / "q.json.tmp"
    neighbour.write_text("keep", encoding="utf-8")
    assert g240.main(_cap_args("Q", "Magic Damage", tmp_path / "q.json")) == 0
    assert neighbour.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("snapshot", [
    {"activePlayer": {"level": 1}, "allPlayers": 5},
    "[" * 200000,
    {"activePlayer": {"level": 10 ** 400, "championStats": {"attackDamage": 10 ** 400}}},
], ids=["all-players-not-a-list", "deep-nesting", "huge-integers"])
def test_cli_malformed_snapshots_exit_2(tmp_path, cli, snapshot, capsys):
    path = tmp_path / "snap.json"
    path.write_text(snapshot if isinstance(snapshot, str) else json.dumps(snapshot),
                    encoding="utf-8")
    assert g240.main(["plan", "--snapshot", str(path)]) == 2
    assert g240.main([*_cap_args("Q", "Magic Damage", tmp_path / "q.json"),
                      "--snapshot", str(path)]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_cli_missing_file_exits_2(tmp_path, capsys):
    assert g240.main(["grade", f"{tmp_path / 'nope.json'}=5"]) == 2
    assert "REFUSED" in capsys.readouterr().err


# ---------------------------------------------------------------- tracked data + source


def test_census_over_the_tracked_sidecar_agrees_with_its_own_header():
    abilities, _data, sidecar = g240.load_data()
    result = g240.census(abilities, sidecar)
    doc = g240._read_cdragon_sidecar_doc(Path(abilities.data_root), abilities.patch)
    assert result["blocks_by_resolution"]["fallback"] == doc["_n_fallback_blocks"]
    assert result["blocks_by_resolution"]["mechanical"] == doc["_n_mechanical_blocks"]
    assert sum(result["fallback_by_calc_type"].values()) == doc["_n_fallback_blocks"]
    # Anchored: an empty pool would otherwise pass every later statement.
    assert result["abilities_by_role"]["fallback"] > 0
    assert result["abilities_by_role"]["control"] > 0
    assert result["champions_with_a_covered_fallback"] > 0


def test_the_filed_reason_class_is_not_derivable_from_the_sidecar():
    _abilities, _data, sidecar = g240.load_data()
    blocks = [b for per_key in sidecar.values() for bl in per_key.values()
              if isinstance(bl, list) for b in bl]
    assert blocks
    assert not [b for b in blocks if set(b) & {"reason", "fallback_reason", "class"}]
    fallback = [b for b in blocks if b.get("resolution") == "fallback"]
    assert fallback
    ratio_keys = ("base", "ap_pct", "bonus_ad_pct", "total_ad_pct", "caster_max_hp_pct",
                  "target_max_hp_pct")
    assert not [b for b in fallback if any(b.get(k) for k in ratio_keys)]


def _real_control():
    abilities, data, sidecar = g240.load_data()
    for champ in abilities.champion_ids():
        row = g240.plan(abilities, sidecar, champ)
        ctl = next((r for r in row["abilities"] if r["role"] == "control"), None)
        if ctl:
            return abilities, data, sidecar, champ, ctl
    raise AssertionError("no control ability anywhere in the tracked data")


def test_a_real_champion_captures_and_re_derives_through_the_real_engine():
    abilities, data, sidecar, champ, ctl = _real_control()
    rec = g240.capture(abilities, data, sidecar,
                       _snap(raw=f"game_character_displayname_{champ}"),
                       key=ctl["key"], block_name=ctl["forms"][0]["blocks"][0],
                       form_index=ctl["forms"][0]["form"], target_armor=0.0, target_mr=0.0,
                       target_max_hp=1000.0, source=g240.SOURCE_RELAY, captured_at=T0)
    assert rec["role"] == "control"
    assert rec["predicted"] > 0
    assert rec["unpredictable"] is None
    assert rec["ds_patch"] == abilities.patch
    assert g240.verify_record(rec, abilities, data, sidecar) is rec
    edited = dict(rec, predicted=rec["predicted"] + 50.0)
    with pytest.raises(g240.Refused, match="re-derive"):
        g240.verify_record(edited, abilities, data, sidecar)


def test_the_tool_stays_read_only_at_source():
    src = TOOL_SRC.read_text(encoding="utf-8")
    for banned in ("restart_trigger", "taskkill", "method=\"POST\"", "lcu_client",
                   ".unlink(", "shutil", "subprocess"):
        assert banned not in src
    assert "write_text" not in src
    assert src.count('.open("x"') == 1, "only capture --out writes, and only a new file"

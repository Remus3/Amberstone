"""S144-T-612..617 - composition_advisor.py true-audit (lane 8, s144 cycle 219).

composition_advisor.comp_context_str is the comp_context_fn the live SR/ARAM
worker calls every coaching tick (app/__init__.py -> core/sr_aram_worker.py);
its string becomes the COMPOSITION ANALYSIS block of the Haiku prompt.
enemy_damage_profile also feeds core/comp_coverage.py and role_profiles.py.

Findings pinned here (each test was RED before the fix):

- S144-T-612: ARAM Mayhem (game_mode KIWI) never got the ARAM rules - is_aram
  was a substring test for "ARAM", while the canonical router
  (core.game_snapshot.mode_from_game_mode_string) maps KIWI to MODE_ARAM.
- S144-T-613: the ARAM mana-item warning in validate_item was unreachable -
  the generic mana branch above it returned first for the same items.
- S144-T-614: a champion with no profile (measured: Rakan, Skarner, Yunara,
  Zaahen, Locke have no data/champion_profiles/*.json) was counted as an AD
  semi-tank fighter, so an unprofiled team read "100% AD" and gained tanks.
- S144-T-615: an empty or wholly unprofiled enemy team still printed the
  fabricated line "Enemy: mixed 0% AD / 0% AP" into the prompt.
- S144-T-616: wrong-shaped input raised (None team, None game_mode, a non-str
  item) and a bare string team was split into one-letter "champions", so the
  whole comp_context block was lost for the tick.
- S144-T-617: a repeated owned item produced the same warning twice, spending
  both warning slots on one finding; the Warmog's exclusion was case-sensitive.
"""
from __future__ import annotations

import composition_advisor as ca
from champion_profiles import CHAMPIONS

UNPROFILED = "Notachampion Zz"


def _pick(dmg: str, role: str, **extra) -> str:
    for name, d in sorted(CHAMPIONS.items()):
        if d.get("dmg") == dmg and d.get("role") == role and all(
                d.get(k) == v for k, v in extra.items()):
            return name
    raise AssertionError(f"no profiled champion with dmg={dmg} role={role} {extra}")


def test_fixture_name_is_really_unprofiled():
    assert UNPROFILED not in CHAMPIONS


# -- S144-T-612: ARAM Mayhem is ARAM ------------------------------------------

def test_kiwi_mode_gets_aram_suggestions():
    me = _pick("ad", "fighter")
    enemies = [_pick("ap", "mage")]
    aram = ca.suggest_items(me, enemies, [], [], 0, "ARAM")
    kiwi = ca.suggest_items(me, enemies, [], [], 0, "KIWI")
    assert any(s[0].startswith("Death's Dance") for s in aram)
    assert kiwi == aram


def test_classic_mode_gets_no_aram_suggestions():
    me = _pick("ad", "fighter")
    out = ca.suggest_items(me, [_pick("ap", "mage")], [], [], 0, "CLASSIC")
    assert not any("ARAM" in reason for _, reason in out)


# -- S144-T-613: the ARAM mana warning is reachable ---------------------------

def test_aram_mana_warning_is_emitted_in_aram():
    me = _pick("ad", "fighter", mana=False)
    ok, warn = ca.validate_item("Tear of the Goddess", me, [], [], [], "ARAM")
    assert ok is False
    assert warn.startswith("ARAM: ")


def test_aram_mana_warning_is_emitted_in_kiwi():
    me = _pick("ad", "fighter", mana=False)
    ok, warn = ca.validate_item("Manamune", me, [], [], [], "KIWI")
    assert ok is False
    assert warn.startswith("ARAM: ")


def test_sr_mana_warning_keeps_generic_text():
    me = _pick("ad", "fighter", mana=False)
    ok, warn = ca.validate_item("Tear of the Goddess", me, [], [], [], "CLASSIC")
    assert ok is False
    assert "doesn't use mana" in warn and not warn.startswith("ARAM")


# -- S144-T-614: an unprofiled champion is not invented as AD -----------------

def test_unprofiled_enemy_is_not_counted_as_ad():
    prof = ca.enemy_damage_profile([UNPROFILED] * 5)
    assert prof["ad"] == 0.0
    assert prof["ad_count"] == 0
    assert prof["tank_count"] == 0


def test_unprofiled_enemy_is_left_out_of_the_ratio():
    mage = _pick("ap", "mage")
    prof = ca.enemy_damage_profile([mage, UNPROFILED])
    assert prof["ap"] == 1.0
    assert prof["ad"] == 0.0


def test_profiled_team_ratio_unchanged():
    ad = _pick("ad", "marksman")
    ap = _pick("ap", "mage")
    prof = ca.enemy_damage_profile([ad, ad, ap, ap])
    assert prof["ad"] == 0.5 and prof["ap"] == 0.5 and prof["mixed"] is True
    assert set(prof) == {"ad", "ap", "mixed", "ad_count", "ap_count",
                         "tank_count", "sustain_count"}


# -- S144-T-615: no fabricated profile line -----------------------------------

def test_empty_enemy_team_has_no_profile_line():
    me = _pick("ap", "mage")
    out = ca.comp_context_str(me, [], [], [], [], "CLASSIC")
    assert "Enemy:" not in out
    assert "0% AD" not in out


def test_unprofiled_enemy_team_has_no_profile_line():
    me = _pick("ap", "mage")
    out = ca.comp_context_str(me, [], [UNPROFILED] * 5, [], [], "CLASSIC")
    assert "Enemy:" not in out


def test_profiled_enemy_team_keeps_profile_line():
    me = _pick("ap", "mage")
    ad = _pick("ad", "marksman")
    out = ca.comp_context_str(me, [], [ad] * 4, [], [], "CLASSIC")
    assert out.splitlines()[0] == "Enemy: 100% AD - prioritize armor items"


# -- S144-T-616: wrong-shaped input degrades instead of raising ---------------

def test_none_enemy_team_does_not_raise():
    prof = ca.enemy_damage_profile(None)
    assert prof["ad"] == 0.0 and prof["ap"] == 0.0


def test_bare_string_team_is_one_name_not_letters():
    mage = _pick("ap", "mage")
    assert ca.enemy_damage_profile(mage) == ca.enemy_damage_profile([mage])


def test_non_str_team_entries_are_skipped():
    mage = _pick("ap", "mage")
    prof = ca.enemy_damage_profile([None, 5, {"a": 1}, mage])
    assert prof["ap"] == 1.0


def test_none_game_mode_does_not_raise():
    me = _pick("ad", "fighter", mana=False)
    ok, warn = ca.validate_item("Sheen", me, [], [], [], None)
    assert ok is False and not warn.startswith("ARAM")
    out = ca.comp_context_str(me, ["Tear of the Goddess"], [], [], [], None)
    assert "doesn't use mana" in out


def test_non_str_item_does_not_raise():
    me = _pick("ad", "fighter", mana=False)
    out = ca.comp_context_str(me, [{"displayName": "x"}, None, 3011,
                                   "Tear of the Goddess"], [], [], [], "CLASSIC")
    assert "doesn't use mana" in out
    assert ca.validate_item(None, me, [], [], [], "CLASSIC") == (True, "")
    assert isinstance(ca.suggest_items(me, None, None, None, 0, None), list)


def test_bare_string_items_are_not_split_into_letters():
    me = _pick("ad", "fighter", mana=False)
    out = ca.comp_context_str(me, "Tear of the Goddess", [], [], [], "CLASSIC")
    assert out.count("doesn't use mana") == 1


# -- S144-T-617: one finding, one line; Warmog's exclusion by name ------------

def test_repeated_item_warns_once():
    me = _pick("ap", "mage")
    ad = _pick("ad", "marksman")
    out = ca.comp_context_str(me, ["Negatron Cloak", "Negatron Cloak"],
                              [ad] * 5, [], [], "CLASSIC")
    assert out.count("Negatron Cloak provides MR") == 1


def test_warmogs_never_flagged_as_armor_whatever_the_case():
    me = _pick("ad", "fighter")
    ap = _pick("ap", "mage")
    for name in ("Warmog's Armor", "warmog's armor", "WARMOG'S ARMOR"):
        assert ca.validate_item(name, me, [ap] * 5, [], [], "CLASSIC") == (True, "")


def test_armor_item_vs_ap_team_still_flagged():
    me = _pick("ad", "fighter")
    ap = _pick("ap", "mage")
    ok, warn = ca.validate_item("Thornmail", me, [ap] * 5, [], [], "CLASSIC")
    assert ok is False and "provides armor" in warn

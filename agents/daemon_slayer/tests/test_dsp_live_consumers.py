"""DSP5/6/7 live-context consumer tests.

DSP5 (summoner) + DSP6 (enemy-rune) are pure (no snapshot). DSP7
(ally_protected_ehp) loads the DataSnapshot like test_ehp.py. Each consumer must
be a byte-identical no-op on an EMPTY context and move in the correct direction
when a real context is supplied.
"""
from agents.daemon_slayer.dsp_live_consumers import (
    ally_protected_ehp,
    enemy_rune_threat,
    summoner_fight_adjustments,
)

# Summoner spell ids (cited LIVE_GAME_GATED_SYNC.md): Ignite 14, Exhaust 3,
# Heal 7, Barrier 21, Cleanse 1, Ghost 6.
_IGNITE, _EXHAUST, _HEAL, _CLEANSE = 14, 3, 7, 1
# Rune ids: Press the Attack 8005, Grasp 8437, Second Wind 8444.
_PTA, _GRASP, _SECOND_WIND = 8005, 8437, 8444


# --- DSP5 -------------------------------------------------------------------

def test_summoner_empty_is_zero():
    a = summoner_fight_adjustments()
    assert a.self_ehp_bonus == 0.0
    assert a.self_cc_discount_pct == 0.0
    assert a.self_ms_pct == 0.0
    assert a.self_incoming_dr_pct == 0.0
    assert a.enemy_antiheal_pct == 0.0


def test_summoner_self_heal_cleanse_exhaust():
    a = summoner_fight_adjustments(self_spell_ids=[_HEAL, _CLEANSE, _EXHAUST], level=11)
    assert a.self_ehp_bonus > 0.0          # Heal flat heal -> EHP
    assert a.self_cc_discount_pct == 0.75  # Cleanse tenacity
    assert a.self_incoming_dr_pct == 0.35  # Exhaust on the enemy carry
    assert a.self_ms_pct > 0.0             # Heal move-speed burst


def test_summoner_enemy_ignite_antiheal():
    a = summoner_fight_adjustments(enemy_spell_ids=[_IGNITE])
    assert a.enemy_antiheal_pct == 0.40


# --- DSP6 -------------------------------------------------------------------

def test_enemy_rune_empty_is_identity():
    t = enemy_rune_threat()
    assert t.incoming_amp_pct == 0.0
    assert t.ehp_divisor == 1.0
    assert t.antiheal_pct == 0.0
    assert t.poke_sustain_hp == 0.0


def test_enemy_rune_pta_amp():
    t = enemy_rune_threat([_PTA], level=11)
    assert abs(t.incoming_amp_pct - 0.08) < 1e-9
    assert abs(t.ehp_divisor - 1.08) < 1e-9


def test_enemy_rune_antiheal_flag():
    assert enemy_rune_threat([], antiheal_present=True).antiheal_pct == 0.40
    assert enemy_rune_threat([], antiheal_present=False).antiheal_pct == 0.0


def test_enemy_rune_poke_sustain_needs_hp():
    no_hp = enemy_rune_threat([_GRASP, _SECOND_WIND], level=11)
    assert no_hp.poke_sustain_hp == 0.0
    with_hp = enemy_rune_threat(
        [_GRASP, _SECOND_WIND], level=11, enemy_max_hp=2000.0, enemy_missing_hp=500.0)
    assert with_hp.poke_sustain_hp > 0.0


# --- DSP7 -------------------------------------------------------------------

def test_ally_protected_ehp_empty_byte_identical():
    from agents.daemon_slayer.data_loader import DataSnapshot
    from agents.daemon_slayer.ehp import compute_ehp
    snap = DataSnapshot.load()
    champ, lvl = "Jinx", 11
    base = compute_ehp(snap, champion_id=champ, level=lvl, mode="SR")
    got = ally_protected_ehp(snap, champ, lvl, mode="SR")
    assert got.blended_ehp == base.blended_ehp
    assert got.physical_ehp == base.physical_ehp
    assert got.magical_ehp == base.magical_ehp


def test_ally_protected_ehp_janna_uplift():
    from agents.daemon_slayer._passive_ally_grant_overrides import ally_flat_hp_grant
    from agents.daemon_slayer.data_loader import DataSnapshot
    from agents.daemon_slayer.ehp import compute_ehp
    snap = DataSnapshot.load()
    champ, lvl = "Jinx", 11
    # Janna E is a registered flat-HP granter; assert the substrate first so a
    # registry change fails loudly here rather than silently no-op the uplift.
    assert ally_flat_hp_grant("Janna", lvl, True) > 0.0
    base = compute_ehp(snap, champion_id=champ, level=lvl, mode="SR")
    prot = ally_protected_ehp(snap, champ, lvl, ally_grant_champions=["Janna"], mode="SR")
    assert prot.blended_ehp > base.blended_ehp


def test_engine_version_pin():
    from agents.daemon_slayer import ENGINE_VERSION
    assert ENGINE_VERSION == "1.205.0"

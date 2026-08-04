"""R127: CDragon per-instance resource guard for full-channel ult totals.

The item-320 ``prefer_cdragon_ratios`` cutover (default-ON) re-sources ability
ratios from CDragon's mechanical blocks. For a channeled multi-wave ult whose
Meraki block is the baked full-channel TOTAL (MissFortune R "Bullet Time",
1050/1200/1350% total AD) and whose sole CDragon mechanical block is the
per-wave atomic (``PhysicalDamagePerWave``, 60% AD), the single-block
direct-pair branch overwrites the total with the per-wave value - a ~17.7x
undercount that drags MissFortune's ``total_ability_dps`` -45%.

``apply_cdragon_resource_guard`` (default False -> byte-identical to the current
live snapshot) excludes the (MissFortune, R) pairing so the Meraki full-channel
total survives. Default-OFF; the live flip is gated (LIVE_GAME_GATED_SYNC.md).
"""
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.abilities import AbilitiesSnapshot


def _mf_r_damage_block(snap):
    forms = snap.champions["MissFortune"]["R"]
    for b in forms[0].damage_blocks:
        if b.attribute_kind == "damage":
            return b
    raise AssertionError("no MF R damage block")


def test_engine_version_pinned():
    assert ENGINE_VERSION == "1.271.0"


def test_guard_off_is_current_live_per_wave():
    # Default (guard OFF) reproduces the current LIVE behavior: the CDragon
    # per-wave atomic overwrote the Meraki full-channel total.
    snap = AbilitiesSnapshot.load(prefer_cdragon_ratios=True)
    b = _mf_r_damage_block(snap)
    assert b.total_ad_pct == (60.0, 60.0, 60.0)
    assert b.ap_pct == (25.0, 25.0, 25.0)


def test_guard_on_restores_meraki_full_channel_total():
    snap = AbilitiesSnapshot.load(
        prefer_cdragon_ratios=True, apply_cdragon_resource_guard=True
    )
    b = _mf_r_damage_block(snap)
    assert b.total_ad_pct == (1050.0, 1200.0, 1350.0)
    assert b.ap_pct == (350.0, 400.0, 450.0)


def test_guard_touches_exactly_missfortune_r():
    # The guard must move ONLY the enrolled (MissFortune, R) form; every other
    # champion/key stays byte-identical to the ungarded cutover snapshot.
    base = AbilitiesSnapshot.load(prefer_cdragon_ratios=True)
    guarded = AbilitiesSnapshot.load(
        prefer_cdragon_ratios=True, apply_cdragon_resource_guard=True
    )
    diffs = [
        (cid, key)
        for cid, keys in base.champions.items()
        for key, forms in keys.items()
        if guarded.champions[cid][key] != forms
    ]
    assert diffs == [("MissFortune", "R")]


def test_guard_off_matches_no_arg_default():
    # Explicit guard=False is identical to omitting it (byte-identical default).
    a = AbilitiesSnapshot.load(prefer_cdragon_ratios=True)
    b = AbilitiesSnapshot.load(
        prefer_cdragon_ratios=True, apply_cdragon_resource_guard=False
    )
    assert a.champions == b.champions

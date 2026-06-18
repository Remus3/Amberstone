"""compute_antitank_live - the P3.2 caster-stat PRODUCER (build-resolved AP/AD).

The static ``compute_antitank`` leaves the P3.2 ``ap_ratio`` / ``ad_ratio``
scaling dormant (the /anti-tank route passes no stats). ``compute_antitank_live``
resolves the champion's AP/AD from its live build via ``engine.build_champion``
and feeds them so a seeded row scales. Additive: a champ with no seeded ratio, or
a naked / zero-AP-AD build, is byte-identical to the static score.
"""
from agents.daemon_slayer.antitank import compute_antitank, compute_antitank_live
from agents.daemon_slayer.data_loader import DataSnapshot


def test_naked_build_byte_identical():
    snap = DataSnapshot.load()
    # Gwen P is AP-only seeded; a naked build has AP 0 so it does not scale.
    live = compute_antitank_live(snap, "Gwen", 11, [])
    static = compute_antitank("Gwen")
    assert live.antitank_score == static.antitank_score


def test_ap_build_scales_seeded_champ():
    snap = DataSnapshot.load()
    static = compute_antitank("Gwen").antitank_score  # 0.85
    # Rabadon's Deathcap 3089 -> ~130 AP; 0.85 + 130 * 0.0005 = 0.915.
    live = compute_antitank_live(snap, "Gwen", 11, ["3089"]).antitank_score
    assert live > static


def test_unseeded_champ_byte_identical_even_with_ap_build():
    snap = DataSnapshot.load()
    # Vayne W is pure %max-HP (no caster-stat ratio) -> an AP build is a no-op.
    live = compute_antitank_live(snap, "Vayne", 11, ["3089"])
    static = compute_antitank("Vayne")
    assert live.antitank_score == static.antitank_score


def test_unknown_champion_fail_soft():
    snap = DataSnapshot.load()
    r = compute_antitank_live(snap, "NotAChampion", 11, [])
    assert r.antitank_score == 0.0


def test_bad_item_falls_back_to_static():
    snap = DataSnapshot.load()
    # An unknown item id makes build_champion raise; the producer fail-softs to
    # the static (no-stats) score rather than propagating.
    r = compute_antitank_live(snap, "Gwen", 11, ["999999999"])
    assert r.antitank_score == compute_antitank("Gwen").antitank_score

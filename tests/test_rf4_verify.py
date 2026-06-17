"""Hermetic tests for the RF4 residual loop-until-dry classifier.

RF4 re-checks the DSP10 consolidated worst-N tail AFTER the RF1 (hybrid/bruiser),
RF2 (hps/enchanter), and RF3 (ehp/tank) DEFAULT-OFF survivability item-credit seams
shipped. Every worst row is bucketed, and the swarm is "dry" iff no NEW
survivability-class cluster survives: an untabled, non-Cluster-A hybrid/hps/ehp
champ whose buried winners still form a COHERENT survivability set (>= min_axis_hits
WIN-correlated survivability items, the strongest carrying a lift >= min_defect_lift)
the RF1-RF3 tables missed.

The dps/burst lane is DSP2/DSP11's (closed by its own loop-until-dry pass); the
ability/mage lane is the deferred DSV1 AP-DoT / Cluster-A archetype lane - neither
is an RF survivability cluster. Cluster A (Zilean/Shaco/Kayle/Seraphine AP-in-ARAM)
is operator-gated, never a new cluster.

Synthesize the worst-row dicts by hand (no rewind db, no engine) so the verdict
logic is provable in isolation. feedback_clean_checkout_probe-safe.
"""
from ops.audit.ds_perm_swarm.rf4_verify import classify_survivability_worst

_SURV = {"Force of Nature", "Spirit Visage", "Jak'Sho, The Protean", "Warmog's Armor"}
_RF1 = {"Udyr"}
_RF2 = {"Rakan"}
_RF3 = {"Rell"}
_CLUSTER_A = {"Zilean", "Shaco", "Kayle", "Seraphine"}
_DSP11 = {"Pyke", "Nilah"}


def _row(champ, scorer, buried):
    """buried = list of (item_id, name, lift_over_baseline[, n])."""
    bw = []
    for b in buried:
        iid, name, lift = b[0], b[1], b[2]
        n = b[3] if len(b) > 3 else 10
        bw.append({"id": iid, "name": name, "n": n, "wr": 60.0,
                   "lift_over_baseline": lift})
    return {"champion": champ, "scorer": scorer, "archetype": "x",
            "buried_winners": bw}


def _classify(rows):
    return classify_survivability_worst(
        rows, rf1_champs=_RF1, rf2_champs=_RF2, rf3_champs=_RF3,
        cluster_a=_CLUSTER_A, survivability_names=_SURV, dsp11_champs=_DSP11,
        min_axis_hits=2, min_defect_lift=5.0, min_item_n=5,
    )


def test_rf1_tabled_is_covered():
    res = _classify([_row("Udyr", "hybrid", [("4401", "Force of Nature", 18.7)])])
    assert res["by_champion"]["Udyr"]["category"] == "covered_rf1"


def test_rf2_tabled_is_covered():
    res = _classify([_row("Rakan", "hps", [("2051", "Guardian's Horn", 15.2)])])
    assert res["by_champion"]["Rakan"]["category"] == "covered_rf2"


def test_rf3_tabled_is_covered():
    res = _classify([_row("Rell", "ehp", [("1011", "Giant's Belt", 27.1)])])
    assert res["by_champion"]["Rell"]["category"] == "covered_rf3"


def test_cluster_a_is_deferred_even_on_an_rf_lane():
    # Zilean rides the hps lane in the report but is operator-gated AP-in-ARAM.
    res = _classify([_row("Zilean", "hps", [("3083", "Warmog's Armor", 9.0),
                                            ("3065", "Spirit Visage", 8.0)])])
    assert res["by_champion"]["Zilean"]["category"] == "cluster_a_deferred"


def test_dps_burst_lane_is_not_an_rf_cluster():
    res = _classify([_row("SomeAdc", "dps", [("3031", "Infinity Edge", 12.0)])])
    assert res["by_champion"]["SomeAdc"]["category"] == "dps_burst_lane"


def test_dsp11_tabled_dps_is_covered():
    res = _classify([_row("Pyke", "burst", [("6701", "Opportunity", 6.1)])])
    assert res["by_champion"]["Pyke"]["category"] == "covered_dsp11"


def test_ability_mage_lane_is_separate():
    res = _classify([_row("MageX", "ability", [("4645", "Shadowflame", 12.7),
                                               ("3089", "Rabadon's Deathcap", 9.0)])])
    assert res["by_champion"]["MageX"]["category"] == "ability_mage_lane"


def test_no_buried_is_not_a_cluster():
    res = _classify([_row("CleanBruiser", "hybrid", [])])
    assert res["by_champion"]["CleanBruiser"]["category"] == "no_buried"


def test_single_survivability_hit_is_thin_or_noise():
    # One survivability item buried (< min_axis_hits) on an untabled hybrid champ.
    res = _classify([_row("ThinBruiser", "hybrid",
                          [("4401", "Force of Nature", 18.0),
                           ("9999", "Some DPS Item", 9.0)])])
    assert res["by_champion"]["ThinBruiser"]["category"] == "thin_or_noise"


def test_two_survivability_hits_below_lift_floor_is_noise():
    res = _classify([_row("MarginBruiser", "hybrid",
                          [("4401", "Force of Nature", 3.0),
                           ("3065", "Spirit Visage", 2.0)])])
    rec = res["by_champion"]["MarginBruiser"]
    assert rec["category"] == "thin_or_noise"
    assert rec["n_surv_hits"] == 0


def test_strong_coherent_survivability_set_is_new_cluster_and_not_dry():
    res = _classify([_row("NewBruiser", "hybrid",
                          [("4401", "Force of Nature", 18.0),
                           ("3065", "Spirit Visage", 12.0),
                           ("9999", "Some DPS Item", 4.0)])])
    rec = res["by_champion"]["NewBruiser"]
    assert rec["category"] == "NEW_SURVIVABILITY_CLUSTER"
    assert rec["n_surv_hits"] == 2
    assert [d["champion"] for d in res["new_clusters"]] == ["NewBruiser"]
    assert res["dry"] is False


def test_ehp_lane_strong_set_also_flagged():
    res = _classify([_row("NewTank", "ehp",
                          [("4401", "Force of Nature", 14.0),
                           ("3083", "Warmog's Armor", 8.0)])])
    rec = res["by_champion"]["NewTank"]
    assert rec["category"] == "NEW_SURVIVABILITY_CLUSTER"
    assert res["dry"] is False


def test_low_n_survivability_hit_does_not_count():
    # A survivability buried winner under min_item_n is too thin to seed a cluster.
    res = _classify([_row("ThinSample", "hybrid",
                          [("4401", "Force of Nature", 18.0, 3),
                           ("3065", "Spirit Visage", 12.0, 4)])])
    rec = res["by_champion"]["ThinSample"]
    assert rec["category"] == "thin_or_noise"
    assert rec["n_surv_hits"] == 0


def test_dry_when_only_covered_deferred_and_noise():
    rows = [
        _row("Udyr", "hybrid", [("4401", "Force of Nature", 18.7)]),   # rf1
        _row("Rakan", "hps", [("2051", "Guardian's Horn", 15.2)]),     # rf2
        _row("Rell", "ehp", [("1011", "Giant's Belt", 27.1)]),         # rf3
        _row("Zilean", "hps", [("3083", "Warmog's Armor", 9.0)]),      # cluster A
        _row("Pyke", "burst", [("6701", "Opportunity", 6.1)]),         # dsp11
        _row("MageX", "ability", [("4645", "Shadowflame", 12.7)]),     # ability lane
        _row("ThinBruiser", "hybrid", [("4401", "Force of Nature", 18.0)]),  # 1 hit
    ]
    res = _classify(rows)
    assert res["new_clusters"] == []
    assert res["dry"] is True
    assert res["n_worst"] == 7

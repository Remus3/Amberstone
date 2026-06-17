"""Hermetic tests for the DSP10 pass-2 loop-until-dry classifier.

Pass 2 re-checks the DSP10 consolidated worst-N tail AFTER the DSP11 Cluster-B2
kit-axis seam shipped: every worst row is bucketed, and the swarm is "dry" iff no
NEW B2-class defect survives - an untabled, non-Cluster-A dps/burst champ whose
buried winners still form a COHERENT kit-axis set (>= 2 items on one axis whose
strongest carries a lift >= min_defect_lift) the DSP11 table missed.

Synthesize the worst-row dicts by hand (no rewind db, no engine) so the verdict
logic is provable in isolation. feedback_clean_checkout_probe-safe.
"""
from ops.audit.ds_perm_swarm.dsp10_pass2_verify import classify_worst

_AXES = {"crit": {"3031", "6675", "3036"}, "lethality": {"6701", "3142", "6696"}}
_TABLED = {"Pyke", "Nilah"}
_CLUSTER_A = {"Shaco", "Kayle"}


def _row(champ, scorer, buried):
    """buried = list of (item_id, lift_over_baseline)."""
    return {
        "champion": champ,
        "scorer": scorer,
        "archetype": "carry",
        "buried_winners": [
            {"id": i, "name": f"Item{i}", "lift_over_baseline": lift}
            for i, lift in buried
        ],
    }


def _classify(rows):
    return classify_worst(
        rows, tabled_champs=_TABLED, cluster_a=_CLUSTER_A,
        axis_item_sets=_AXES, min_axis_hits=2, min_defect_lift=5.0,
    )


def test_tabled_champ_is_covered():
    res = _classify([_row("Pyke", "burst", [("6701", 6.1), ("3142", 5.8)])])
    assert res["by_champion"]["Pyke"]["category"] == "covered_dsp11"


def test_cluster_a_is_deferred():
    res = _classify([_row("Shaco", "burst", [("6701", 9.0), ("3142", 7.0)])])
    assert res["by_champion"]["Shaco"]["category"] == "cluster_a_deferred"


def test_no_buried_is_not_a_defect():
    res = _classify([_row("Zaahen", "burst", [])])
    assert res["by_champion"]["Zaahen"]["category"] == "no_buried"


def test_ap_mage_other_scorer_excluded():
    # An ability/mage scorer is a separate lane (AP DoT valuation), not B2.
    res = _classify([_row("MageX", "ability", [("6701", 9.0), ("3142", 7.0)])])
    assert res["by_champion"]["MageX"]["category"] == "other_scorer"


def test_single_axis_hit_is_within_axis_noise():
    # One crit item buried (< min_axis_hits) on an untabled dps ADC = cost/component
    # noise within the champ's own axis, NOT a wrong-axis B2 defect.
    res = _classify([_row("Yunara", "dps", [("3031", 22.0), ("9999", 8.0)])])
    assert res["by_champion"]["Yunara"]["category"] == "within_axis_noise"


def test_marginal_lift_two_axis_items_is_noise():
    # The Caitlyn case: a pure ranged crit marksman whose model already targets
    # crit and only differs on WHICH crit item by a marginal lift. Two crit items
    # buried but the strongest is below min_defect_lift -> within-axis cost noise.
    res = _classify([_row("Caitlyn", "dps", [("3036", 3.4), ("6675", 0.8)])])
    rec = res["by_champion"]["Caitlyn"]
    assert rec["category"] == "within_axis_noise"
    assert rec["top_axis"] == "crit" and rec["top_axis_lift"] == 3.4


def test_strong_coherent_kit_axis_set_is_new_b2_defect_and_not_dry():
    res = _classify([_row("NewAdc", "dps", [("3031", 15.8), ("6675", 0.3), ("9999", 4.0)])])
    rec = res["by_champion"]["NewAdc"]
    assert rec["category"] == "NEW_B2_DEFECT"
    assert rec["top_axis"] == "crit"
    assert [d["champion"] for d in res["new_b2_defects"]] == ["NewAdc"]
    assert res["dry"] is False


def test_dry_when_only_covered_deferred_and_noise():
    rows = [
        _row("Pyke", "burst", [("6701", 6.1), ("3142", 5.8)]),  # covered
        _row("Shaco", "burst", [("6701", 9.0), ("3142", 7.0)]),  # cluster A
        _row("Zaahen", "burst", []),                              # no buried
        _row("MageX", "ability", [("6701", 9.0), ("3142", 7.0)]),  # other scorer
        _row("Caitlyn", "dps", [("3036", 3.4), ("6675", 0.8)]),  # within-axis noise
    ]
    res = _classify(rows)
    assert res["new_b2_defects"] == []
    assert res["dry"] is True
    assert res["n_worst"] == 5


def test_burst_scorer_strong_coherent_set_also_flagged():
    res = _classify([_row("NewAssassin", "burst", [("6701", 8.0), ("3142", 6.0), ("6696", 2.0)])])
    rec = res["by_champion"]["NewAssassin"]
    assert rec["category"] == "NEW_B2_DEFECT"
    assert rec["top_axis"] == "lethality"
    assert res["dry"] is False

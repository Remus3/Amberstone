"""Y-05: loss-aware net-benefit gate for the ARAM bench swap verdict.

Method from external reference S (method only, clean-room): a bench swap is
judged on the TRIAL team (my champion replaced by the candidate), not on the
candidate alone. compute_factors + _ordered_gaps run on both teams; a swap is
accepted only when gaps fixed >= weighted gaps newly introduced, where a newly
introduced range or frontline gap weighs 2 (the two factors the verdict
already marks high-confidence). Ranking: net gaps removed, then "keeps every
factor already satisfied", then the legacy coverage score.

These are comp-balance FACTS over champions.json, never an outcome prediction.

Champion facts read from data/daemon_slayer/16.18.1/champions.json via the
module itself (range / lean / frontline) plus the curated _ENGAGE / _SUSTAIN:
  Malphite 125 AP Tank engage   | Garen 175 AD Fighter+Tank
  Ahri 550 AP                   | Zed 125 AD Assassin (not frontline)
  Kassadin 150 AP Assassin      | Rakan 300 AP engage (not frontline)
  Yuumi 425 AP sustain (melee by the 500 cut)
  Caitlyn 650 AD | Ashe 600 AD engage | Soraka 550 AP sustain
"""
from __future__ import annotations

import copy

from core import aram_comp_verdict as cv

# Malphite is the SOLE frontline; Rakan keeps engage alive without him; only
# Ahri is ranged (Yuumi 425 < 500) -> the single gap is range.
_SOLE_FRONTLINE = ["Malphite", "Ahri", "Zed", "Rakan", "Yuumi"]
# Garen is the sole frontline; no engage; only Ahri ranged -> range + engage.
_GAREN_ANCHOR = ["Garen", "Ahri", "Zed", "Kassadin", "Yuumi"]
_BALANCED = ["Caitlyn", "Ahri", "Malphite", "Aatrox", "Lux"]


def _state(team, me, bench):
    return {
        "my_team": list(team), "my_champion": me,
        "their_team": ["Yasuo", "Zed", "Lee Sin", "Riven", "Akali"],
        "bench": list(bench), "variants": [], "current_variant": "default",
    }


def test_fixture_facts_hold():
    # Anchor: if the data drifts so a fixture no longer means what it says,
    # fail here rather than pass the behaviour tests vacuously.
    f = cv.compute_factors(_SOLE_FRONTLINE)
    assert f["n"] == 5
    assert [g for g, _ in cv._ordered_gaps(f)] == ["range"]
    assert f["frontline_count"] == 1
    g = cv.compute_factors(_GAREN_ANCHOR)
    assert [x for x, _ in cv._ordered_gaps(g)] == ["range", "engage"]
    assert g["frontline_count"] == 1


def test_introduced_weight_pinned():
    assert cv._INTRODUCED_WEIGHT == {"range": 2, "frontline": 2}
    assert cv._introduced_weight(["frontline"]) == 2
    assert cv._introduced_weight(["range"]) == 2
    assert cv._introduced_weight(["sustain"]) == 1
    assert cv._introduced_weight(["engage", "damage:ad"]) == 2
    assert cv._introduced_weight(["range", "frontline", "sustain"]) == 5
    assert cv._introduced_weight([]) == 0


def test_range_fix_removing_sole_frontline_is_rejected():
    # Legacy picked Caitlyn (she is ranged). Trial team loses its only
    # frontline: fixed 1 (range) < introduced 2 (frontline, double) -> reject.
    out = cv.comp_verdict(_state(_SOLE_FRONTLINE, "Malphite", ["Caitlyn"]))
    assert out["ok"] is True
    assert out["recommendation"] == "stay", out
    assert out["swap_to"] == ""
    assert out["gaps_before"] == ["range"]
    assert out["gaps_after"] == ["range"]
    assert "Caitlyn" in out["caveat"] and "frontline" in out["caveat"]
    assert out["caveat"] in out["reason"]


def test_double_weight_is_what_rejects():
    # Same shape, but I am Yuumi (sole sustain): losing sustain weighs 1, so
    # fixed 1 >= introduced 1 -> accepted, with an explicit caveat. The ONLY
    # difference from the rejection above is the weight of the lost factor.
    out = cv.comp_verdict(_state(_SOLE_FRONTLINE, "Yuumi", ["Caitlyn"]))
    assert out["recommendation"] == "swap"
    assert out["swap_to"] == "Caitlyn"
    assert out["gaps_before"] == ["range"]
    assert out["gaps_after"] == ["sustain"]
    assert "sustain" in out["caveat"]
    assert out["caveat"] in out["reason"]


def test_frontline_loss_accepted_only_when_outweighed_and_caveated():
    # Ashe fixes range AND engage (2) but removes the sole frontline (2):
    # 2 >= 2 -> accepted, never silently.
    out = cv.comp_verdict(_state(_GAREN_ANCHOR, "Garen", ["Ashe"]))
    assert out["recommendation"] == "swap"
    assert out["swap_to"] == "Ashe"
    assert out["gaps_before"] == ["range", "engage"]
    assert out["gaps_after"] == ["frontline"]
    assert "frontline" in out["caveat"]


def test_rank_keeps_satisfied_factor_over_legacy_score():
    # I am Yuumi (sole sustain). Ashe: fixes range+engage, breaks sustain ->
    # net 1, legacy score 2. Soraka: fixes range, breaks nothing -> net 1,
    # legacy score 1. Tie on net; keeps-every-satisfied-factor picks Soraka.
    team = ["Yuumi", "Ahri", "Zed", "Kassadin", "Garen"]
    out = cv.comp_verdict(_state(team, "Yuumi", ["Ashe", "Soraka"]))
    assert out["recommendation"] == "swap"
    assert out["swap_to"] == "Soraka", out
    assert out["caveat"] == ""


def test_rank_net_first():
    # Garen anchor, me = Kassadin (breaks nothing when swapped out). Ashe fixes
    # range+engage (net 2); Caitlyn fixes range only (net 1). Ashe wins.
    out = cv.comp_verdict(_state(_GAREN_ANCHOR, "Kassadin", ["Caitlyn", "Ashe"]))
    assert out["swap_to"] == "Ashe"
    assert out["gaps_after"] == []
    assert out["caveat"] == ""


def test_balanced_comp_still_stays_with_keys():
    out = cv.comp_verdict(_state(_BALANCED, "Caitlyn", ["Malphite", "Soraka"]))
    assert out["recommendation"] == "stay"
    assert out["gaps_before"] == [] and out["gaps_after"] == []
    assert out["caveat"] == ""


def test_empty_bench_degrades_to_stay():
    out = cv.comp_verdict(_state(_SOLE_FRONTLINE, "Malphite", []))
    assert out["ok"] is True
    assert out["recommendation"] == "stay"
    assert out["gaps_before"] == ["range"] == out["gaps_after"]
    assert out["caveat"] == ""


def test_unknown_shape_carries_new_keys():
    out = cv.comp_verdict(None)
    assert out["gaps_before"] == [] and out["gaps_after"] == []
    assert out["caveat"] == ""


def test_my_champion_absent_from_team_is_not_net_checked():
    # Without my slot the trial team cannot be built; keep the legacy pick but
    # say so instead of claiming a net check that never ran.
    out = cv.comp_verdict(_state(_SOLE_FRONTLINE, "Teemo", ["Caitlyn"]))
    assert out["recommendation"] == "swap"
    assert out["swap_to"] == "Caitlyn"
    assert "not net-checked" in out["caveat"]


def test_trial_never_mutates_inputs_or_cache():
    state = _state(_SOLE_FRONTLINE, "Malphite", ["Caitlyn", "Soraka"])
    team_ref, bench_ref = state["my_team"], state["bench"]
    before_state = copy.deepcopy(state)
    index = cv._load_index()
    assert index, "champion index empty - cache test would be vacuous"
    before_index = copy.deepcopy(index)
    cv.comp_verdict(state)
    assert state == before_state
    assert state["my_team"] is team_ref and state["bench"] is bench_ref
    assert cv._load_index() is index
    assert index == before_index


def test_result_is_json_serialisable():
    import json
    out = cv.comp_verdict(_state(_GAREN_ANCHOR, "Garen", ["Ashe"]))
    assert json.loads(json.dumps(out))["gaps_after"] == ["frontline"]

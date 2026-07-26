"""PGR renderer over T2 findings. Headless, synthetic fixtures.

The load-bearing assertion in this file is that the win-side and the loss-side
are DIFFERENT VIEWS, not one view with a sign flip
(docs/REPLAY_T2_PARSE_CRITERIA.md section 4).
"""
from __future__ import annotations

from core import pgr_event_report as pgr


def _match(win_team=200):
    return {"info": {"participants": [
        {"participantId": i, "teamId": 100 if i <= 5 else 200,
         "teamPosition": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][(i - 1) % 5],
         "win": (100 if i <= 5 else 200) == win_team,
         "timePlayed": 1800, "totalMinionsKilled": 200,
         "neutralMinionsKilled": 0, "goldEarned": 12000,
         "totalDamageDealtToChampions": 21000, "totalDamageTaken": 18000,
         "visionScore": 30, "wardsPlaced": 12, "wardsKilled": 4,
         "timeCCingOthers": 20, "totalHealsOnTeammates": 0,
         "damageDealtToTurrets": 3000, "kills": 5, "deaths": 4, "assists": 9}
        for i in range(1, 11)]}}


def _kill(t, killer, victim, assists=(), bounty=300, shutdown=0):
    return {"type": "CHAMPION_KILL", "timestamp": t, "killerId": killer,
            "victimId": victim, "assistingParticipantIds": list(assists),
            "bounty": bounty, "shutdownBounty": shutdown,
            "position": {"x": 100, "y": 200}}


def _buy(t, pid, item):
    return {"type": "ITEM_PURCHASED", "timestamp": t,
            "participantId": pid, "itemId": item}


def _skill(t, pid, slot):
    return {"type": "SKILL_LEVEL_UP", "timestamp": t,
            "participantId": pid, "skillSlot": slot}


def _tl(events):
    return {"info": {"frameInterval": 60000,
                     "frames": [{"timestamp": 0, "participantFrames": {},
                                 "events": events}]}}


def _busy_timeline(pid=2):
    """Three deaths of differing cost, with purchases interleaved."""
    return _tl([
        _buy(30000, pid, 1055),
        _kill(120000, 7, pid, bounty=300, shutdown=0),          # 300
        _buy(300000, pid, 3006),
        _kill(600000, 7, pid, bounty=200, shutdown=900),        # 1100
        _buy(700000, pid, 6672),
        _kill(900000, 7, pid, assists=[8, 9], bounty=400),      # 400
        _skill(61000, pid, 1), _skill(122000, pid, 2),
        _skill(183000, pid, 1),
    ])


# --------------------------------------------- the two views are different

def test_losing_player_gets_the_cost_view_and_winner_gets_decisions():
    m, tl = _match(win_team=200), _busy_timeline(2)
    assert pgr.render(m, tl, 2)["view"] == "cost"
    assert pgr.render(m, tl, 7)["view"] == "decisions"


def test_the_two_views_are_not_sign_flips_of_one_another():
    # Section 4 exists because computing the same criteria for both sides and
    # flipping the sign is the wrong answer. The criteria SETS must differ.
    m, tl = _match(win_team=200), _busy_timeline(2)
    cost = {ln["criterion"] for ln in pgr.render(m, tl, 2)["lines"]}
    decisions = {ln["criterion"] for ln in pgr.render(m, tl, 7)["lines"]}
    assert cost and decisions
    assert cost != decisions
    assert "death_cost" in cost
    assert "death_cost" not in decisions


def test_both_views_are_reachable_for_the_same_player_on_demand():
    # render() picks by outcome, but a consumer may ask for either explicitly.
    m, tl = _match(win_team=200), _busy_timeline(2)
    assert pgr.cost_attribution(m, tl, 2)
    assert pgr.decision_pattern(m, tl, 2)


# --------------------------------------------------- loss side: ranking

def test_cost_lines_are_ranked_by_magnitude_gold_descending():
    lines = pgr.cost_attribution(_match(), _busy_timeline(2), 2)
    gold = [ln["magnitude_gold"] for ln in lines]
    assert gold == sorted(gold, reverse=True)
    assert gold[0] == 1100


def test_one_death_produces_exactly_one_cost_line_however_many_subsets_hit():
    # death_cost, early_deaths, solo_deaths and shutdowns_given are the SAME
    # death relabelled. Listing each as its own line would make one death
    # appear up to four times and destroy the ranking.
    tl = _tl([_kill(60000, 7, 2, bounty=100, shutdown=500)])  # early + solo + shutdown
    lines = [ln for ln in pgr.cost_attribution(_match(), tl, 2)
             if ln["criterion"] == "death_cost"]
    assert len(lines) == 1
    assert set(lines[0]["tags"]) == {"early_deaths", "solo_deaths",
                                     "shutdowns_given"}


# ------------------------------------------- loss side: cost attribution

def test_each_cost_line_is_attributed_to_the_nearest_preceding_decision():
    lines = pgr.cost_attribution(_match(), _busy_timeline(2), 2)
    top = lines[0]
    assert top["magnitude_gold"] == 1100
    assert top["attributed_to"]["decision"] == "item_purchased"
    assert top["attributed_to"]["item_id"] == 3006
    assert top["attributed_to"]["t_ms"] == 300000
    assert top["attributed_to"]["gap_ms"] == 300000


def test_a_death_before_any_decision_is_attributed_to_nothing_explicitly():
    # Fabricating an attribution out of an empty history is worse than none.
    tl = _tl([_kill(20000, 7, 2, bounty=300), _buy(30000, 2, 1055)])
    line = pgr.cost_attribution(_match(), tl, 2)[0]
    assert line["attributed_to"] is None


# ----------------------------------------------- win side: decisions only

def test_decision_lines_never_claim_the_decision_was_correct():
    # The trap in section 4: a winner's action is not automatically correct.
    lines = pgr.decision_pattern(_match(), _busy_timeline(7), 7)
    assert lines
    for ln in lines:
        assert ln["validated"] is False
        assert "corpus" in ln["promotion"].lower()


def test_decision_lines_are_chronological_not_gold_ranked():
    lines = pgr.decision_pattern(_match(), _busy_timeline(7), 7)
    times = [ln["t_ms"] for ln in lines]
    assert times == sorted(times)


# ------------------------------------------------------ cohort context

def _baselines():
    # Player reads 12000 gold / 30 min = 400.0, which lands between p25 and
    # p50. Deliberately off every boundary so the band is unambiguous.
    return {"JUNGLE": {"gold_per_min": {
        "n": 40, "mean": 430.0,
        "p10": 200.0, "p25": 300.0, "p50": 450.0,
        "p75": 600.0, "p90": 800.0}}}


def test_cohort_ranks_use_rank_of_and_report_the_band():
    ctx = pgr.cohort_context(_match(), 2, _baselines())
    ranked = {r["metric"]: r for r in ctx["ranked"]}
    assert ranked["gold_per_min"]["at_or_above_p"] == 25
    assert ranked["gold_per_min"]["n"] == 40


def test_a_metric_with_no_cohort_table_is_listed_unavailable_not_average():
    ctx = pgr.cohort_context(_match(), 2, _baselines())
    assert "cs_per_min" in ctx["unavailable"]
    assert all(r["metric"] != "cs_per_min" for r in ctx["ranked"])


def test_no_baselines_at_all_yields_no_ranks_and_no_crash():
    ctx = pgr.cohort_context(_match(), 2, None)
    assert ctx["ranked"] == []
    assert ctx["unavailable"]


# ------------------------------------------------------------ rendering

def test_render_text_is_pure_ascii_and_names_the_view():
    m, tl = _match(win_team=200), _busy_timeline(2)
    text = pgr.render_text(pgr.render(m, tl, 2, _baselines()))
    text.encode("ascii")
    assert "COST" in text.upper()
    assert "1100" in text


def test_render_carries_role_win_and_participant_identity():
    rep = pgr.render(_match(win_team=200), _busy_timeline(2), 2)
    assert rep["participant_id"] == 2
    assert rep["role"] == "JUNGLE"
    assert rep["win"] is False

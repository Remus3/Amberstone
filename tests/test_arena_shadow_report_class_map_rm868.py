"""RM-868 - the Arena shadow report scores a shared action CLASS, gates on 70%.

The live log read 3/438 (0.7%) agreement because the report compared the
deterministic side's closed 5-label set against Haiku's free-text labels as
exact strings (``record_agreement``, ``det == haiku``), so even BUY ITEMS vs
CAMP PHASE (the same shop verdict) scored as a disagreement, and the flip read
said ``ready: True`` at 1% because ``_flip_readiness`` had no agreement floor.

Grounded before writing (file:line at origin/main 77dae2dbd):

* ``core/arena_action_rule.py`` ``decide_action(hp_pct, camp_phase,
  low_opp_count)`` (``:62``) returns exactly BUY ITEMS / KITE BACK / ALL IN /
  PLAY AGGRO / FIGHT SMART (rule order ``:14-26``).
* ``tools/arena_shadow_report.py``: ``record_agreement`` (``:185``, keys det /
  haiku / agree), ``summarize_agreement`` (``:232``, keys comparable / agree /
  agreement_rate / dead_state / unclassified / by_champion / confusion),
  ``is_dead_state`` (``:164``), ``_flip_readiness`` (``:286``, keys ready /
  state / comparable / min_sample), ``build_report(path, min_sample)``
  (``:322``), ``main(argv)`` (``:362``), ``is_focus_board_relog`` (``:108``).
* The FLIP_GATE the sibling reports use: ``tools/aram_shadow_report.py:60``
  and ``tools/champ_select_shadow_report.py:85`` (0.70); the state vocabulary
  awaiting_accrual / not_ready / ready is ``champ_select_shadow_report``
  ``_state_and_hint`` (``:601``).
* Haiku labels below are the ones observed in the live
  ``data/arena_coach_shadow.jsonl`` (617 rows, census 2026-10-25).
"""
from __future__ import annotations

import json

import pytest

from core.arena_action_rule import decide_action
from tools import arena_shadow_report as rep


def _row(det_action="FIGHT SMART", haiku_action="FIGHT SMART", champ="Kaisa",
         rnd="~3", det_strategy="Your HP 50%; 4 teams left",
         haiku_strategy="Trade on cooldowns"):
    return {
        "ts": "2026-10-25T00:00:00+00:00",
        "mode": "arena",
        "champ": champ,
        "round": rnd,
        "enemy_comp": [],
        "deterministic": {
            "action": det_action, "round_strategy": det_strategy,
            "fight_rule": "", "augment_advice": "", "anvil_advice": "",
            "target_priority": "", "risk": "", "choices": [],
        },
        "live_haiku": {
            "action": haiku_action, "round_strategy": haiku_strategy,
            "fight_rule": "", "augment_advice": "", "anvil_advice": "",
            "target_priority": "", "risk": "", "choices": [],
        },
    }


def _relog(row):
    out = json.loads(json.dumps(row))
    out["focus_board_relog"] = True
    return out


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                    encoding="utf-8")


# -- the shared class map ------------------------------------------------------

DET_EXPECTED = {
    "BUY ITEMS": rep.SHOP,
    "KITE BACK": rep.DEFENSIVE,
    "FIGHT SMART": rep.NEUTRAL,
    "PLAY AGGRO": rep.AGGRESSIVE,
    "ALL IN": rep.AGGRESSIVE,
}


def test_det_class_map_covers_exactly_what_the_rule_can_emit():
    emitted = {
        decide_action(hp, camp, low)
        for hp in (None, 0, 10, 24.9, 25, 50, 70, 70.1, 90, 100)
        for camp in (False, True)
        for low in (None, 0, 1, 2)
    }
    assert emitted == set(DET_EXPECTED)
    assert dict(rep.DET_ACTION_CLASS) == DET_EXPECTED
    for label, cls in DET_EXPECTED.items():
        assert rep.action_class(label) == cls


@pytest.mark.parametrize("label,cls", [
    # shop / camp phase (det rule 1 wins outright, so a phase word wins here)
    ("CAMP PHASE", "SHOP"), ("BUY ITEMS", "SHOP"), ("AUGMENT SELECT", "SHOP"),
    ("AUGMENT SELECT + BUY ITEMS", "SHOP"), ("WAIT CAMP PHASE", "SHOP"),
    ("WAIT FOR CAMP PHASE", "SHOP"), ("RESPAWN BUY ITEMS", "SHOP"),
    ("RESPAWN CAMP PHASE", "SHOP"), ("SURVIVE CAMP PHASE", "SHOP"),
    ("AUGMENT PHASE", "SHOP"), ("WAIT SHOP", "SHOP"),
    (" camp  phase ", "SHOP"),
    # defensive (prompt: kite, disengage, survive)
    ("KITE BACK", "DEFENSIVE"), ("KITE PERIMETER", "DEFENSIVE"),
    ("KITE SURVIVE", "DEFENSIVE"), ("SURVIVE TO NEXT ROUND", "DEFENSIVE"),
    ("SURVIVE ROUND", "DEFENSIVE"), ("DISENGAGE IMMEDIATE", "DEFENSIVE"),
    ("WAIT / DO NOT FIGHT", "DEFENSIVE"),
    # HOLD POSITION: its one live row says "survive ..., avoid skirmish engage"
    ("HOLD POSITION", "DEFENSIVE"),
    # aggressive
    ("ALL IN", "AGGRESSIVE"), ("PLAY AGGRO", "AGGRESSIVE"),
    ("SCAN THEN ENGAGE", "AGGRESSIVE"), ("FOCUS CARRY", "AGGRESSIVE"),
    # neutral
    ("FIGHT SMART", "NEUTRAL"),
    # non-combat waits
    ("WAIT FOR MATCHUP", "NONCOMBAT"), ("SPAWN WAIT", "NONCOMBAT"),
    ("SCOUT OPPONENT", "NONCOMBAT"), ("WAIT OBJECTIVE", "NONCOMBAT"),
    ("WAIT SPAWN", "NONCOMBAT"), ("REVIVE PRIORITY", "NONCOMBAT"),
    ("SKIP ROUND", "NONCOMBAT"), ("WAIT FOR OPPONENT", "NONCOMBAT"),
    ("RESPAWN PENDING", "NONCOMBAT"), ("WAIT FOR RESPAWN", "NONCOMBAT"),
])
def test_observed_haiku_labels_classify(label, cls):
    assert rep.action_class(label) == cls


@pytest.mark.parametrize("label", [
    "ARENA ROUND ~23 ANALYSIS", "CRITICAL CONTEXT MISMATCH DETECTED",
    "", "   ", None, 42,
])
def test_unknown_or_empty_label_has_no_class(label):
    assert rep.action_class(label) is None


# -- class-level agreement ------------------------------------------------------

@pytest.mark.parametrize("det,haiku,agree", [
    ("BUY ITEMS", "CAMP PHASE", True),
    ("BUY ITEMS", "AUGMENT SELECT", True),
    ("KITE BACK", "SURVIVE ROUND", True),
    ("PLAY AGGRO", "ALL IN", True),
    ("KITE BACK", "HOLD POSITION", True),
    ("FIGHT SMART", "HOLD POSITION", False),
    ("PLAY AGGRO", "CAMP PHASE", False),
    ("FIGHT SMART", "KITE BACK", False),
    ("KITE BACK", "WAIT FOR MATCHUP", False),
])
def test_record_agreement_scores_the_class(det, haiku, agree):
    pair = rep.record_agreement(_row(det_action=det, haiku_action=haiku))
    assert pair["agree"] is agree
    assert pair["det_class"] == rep.action_class(det)
    assert pair["haiku_class"] == rep.action_class(haiku)
    assert pair["exact"] is (det == haiku)


def test_unknown_label_is_unclassified_not_a_disagreement():
    rows = [
        _row(det_action="PLAY AGGRO", haiku_action="ARENA ROUND ~23 ANALYSIS"),
        _row(det_action="PLAY AGGRO", haiku_action="ALL IN"),
    ]
    assert rep.record_agreement(rows[0]) is None
    agr = rep.summarize_agreement(rows)
    assert agr["unclassified"] == 1
    assert agr["comparable"] == 1 and agr["agree"] == 1


def test_exact_label_agreement_is_kept_as_a_secondary_column():
    rows = [
        _row(det_action="BUY ITEMS", haiku_action="CAMP PHASE"),
        _row(det_action="KITE BACK", haiku_action="KITE BACK"),
        _row(det_action="PLAY AGGRO", haiku_action="CAMP PHASE"),
    ]
    agr = rep.summarize_agreement(rows)
    assert agr["comparable"] == 3
    assert agr["agree"] == 2
    assert agr["agreement_rate"] == round(2 / 3, 4)
    assert agr["exact_agree"] == 1
    assert agr["exact_agreement_rate"] == round(1 / 3, 4)
    assert {"det_class": "AGGRESSIVE", "haiku_class": "SHOP", "n": 1,
            "agree": False} in agr["class_confusion"]


def test_fight_axis_isolates_fight_vs_fight_rows():
    rows = [
        _row(det_action="FIGHT SMART", haiku_action="KITE BACK"),   # one band
        _row(det_action="PLAY AGGRO", haiku_action="KITE BACK"),    # opposite
        _row(det_action="KITE BACK", haiku_action="SURVIVE ROUND"),  # same
        _row(det_action="PLAY AGGRO", haiku_action="CAMP PHASE"),   # not fight
    ]
    fa = rep.summarize_agreement(rows)["fight_axis"]
    assert fa["comparable"] == 3
    assert fa["agree"] == 1
    assert fa["within_one_band"] == 2


# -- the 70% gate ----------------------------------------------------------------

def test_flip_gate_matches_the_sibling_reports():
    from tools import aram_shadow_report, champ_select_shadow_report
    assert rep.FLIP_GATE == 0.70
    assert rep.FLIP_GATE == aram_shadow_report.FLIP_GATE
    assert rep.FLIP_GATE == champ_select_shadow_report.FLIP_GATE


def test_live_shape_438_comparables_at_one_percent_is_not_ready(tmp_path):
    rows = [_row(champ=f"C{i}", rnd=f"~{i}", det_action="PLAY AGGRO",
                 haiku_action="PLAY AGGRO") for i in range(3)]
    rows += [_row(champ=f"D{i}", rnd=f"~{i}", det_action="PLAY AGGRO",
                  haiku_action="CAMP PHASE") for i in range(435)]
    p = tmp_path / "live_shape.jsonl"
    _write(p, rows)
    report = rep.build_report(p, min_sample=20)
    fr = report["flip_readiness"]
    assert report["agreement"]["comparable"] == 438
    assert fr["ready"] is False
    assert fr["state"] == "not_ready"
    assert fr["flip_gate"] == rep.FLIP_GATE
    assert report["flip_gate"] == rep.FLIP_GATE


@pytest.mark.parametrize("agree_n,ready", [(14, True), (13, False), (20, True)])
def test_ready_needs_the_gate_as_well_as_the_sample(tmp_path, agree_n, ready):
    rows = [_row(champ=f"A{i}", det_action="BUY ITEMS", haiku_action="CAMP PHASE")
            for i in range(agree_n)]
    rows += [_row(champ=f"B{i}", det_action="PLAY AGGRO", haiku_action="KITE BACK")
             for i in range(20 - agree_n)]
    p = tmp_path / "gate.jsonl"
    _write(p, rows)
    fr = rep.build_report(p, min_sample=20)["flip_readiness"]
    assert fr["comparable"] == 20
    assert fr["ready"] is ready
    assert fr["state"] == ("ready" if ready else "not_ready")
    assert fr["agreement_pct"] == round(100 * agree_n / 20)


def test_a_met_gate_below_the_sample_still_awaits(tmp_path):
    p = tmp_path / "few.jsonl"
    _write(p, [_row(champ=f"C{i}", det_action="BUY ITEMS",
                    haiku_action="CAMP PHASE") for i in range(5)])
    fr = rep.build_report(p, min_sample=20)["flip_readiness"]
    assert fr["ready"] is False
    assert fr["state"] == "awaiting_accrual"


# -- RM-854 relog skip survives the class map ------------------------------------

def test_a_relogged_class_agreeing_pair_counts_once(tmp_path):
    first = _row(det_action="BUY ITEMS", haiku_action="CAMP PHASE")
    p = tmp_path / "relog.jsonl"
    _write(p, [first, _relog(first)])
    report = rep.build_report(p, min_sample=1)
    assert report["coverage"]["total"] == 1
    assert report["coverage"]["focus_board_relogs"] == 1
    assert report["agreement"]["comparable"] == 1
    assert report["agreement"]["agree"] == 1
    assert report["flip_readiness"]["ready"] is True


def test_relogs_never_reach_the_gate_under_the_class_map(tmp_path):
    rows = []
    for i in range(10):
        r = _row(champ=f"C{i}", rnd=f"~{i}", det_action="BUY ITEMS",
                 haiku_action="CAMP PHASE")
        rows += [r, _relog(r)]
    p = tmp_path / "relogs.jsonl"
    _write(p, rows)
    report = rep.build_report(p, min_sample=11)
    assert report["agreement"]["comparable"] == 10
    assert report["coverage"]["focus_board_relogs"] == 10
    assert report["flip_readiness"]["state"] == "awaiting_accrual"


# -- player-dead detection from Haiku's own text ---------------------------------

# True positives: an unambiguous statement that the PLAYER is dead or
# spectating NOW (the live phrasings, plus the pre-existing spectate / HP 0%).
@pytest.mark.parametrize("action,strategy", [
    ("ELIMINATED", "Round is lost."),
    ("ELIMINATED - CAMP PHASE", "Heal and buy."),
    ("DEAD - WAIT RESPAWN", "Watch the next pair."),
    ("SPECTATE ROUND", "Watch their positioning."),
    ("CRITICAL STATUS: YOU ARE DEAD. WAITING FOR RESPAWN/NEXT ROUND.", "Wait."),
    ("CAMP PHASE", "You are dead at 0% HP. Hwei at 100%. Use this downtime."),
    ("CAMP PHASE", "You are DEAD at 0% HP. Mel at 100% - next round incoming."),
    ("CAMP PHASE", "You are dead this round. Naafiri is dead. Heal at campfire."),
    ("CAMP PHASE", "You're dead - plan the next buy."),
    ("CAMP PHASE", "You are spectating Kog'Maw's fight."),
    ("ELIMINATED", "You and Syndra are dead. Both at 0% HP."),
    ("CAMP PHASE", "You and Syndra are dead. Both at 0% HP."),
])
def test_player_dead_haiku_text_is_dead_state(action, strategy):
    assert rep.is_dead_state(_row(det_action="KITE BACK", haiku_action=action,
                                  haiku_strategy=strategy)) is True


def test_det_hp_zero_is_dead_and_other_hp_is_not():
    dead = _row(det_strategy="Your HP 0%; 3 teams left - kite, disengage, survive")
    alive = _row(det_strategy="Your HP 10%; 3 teams left - kite, disengage, survive")
    assert rep.is_dead_state(dead) is True
    assert rep.is_dead_state(alive) is False


# The coordinator's refutation cases, in BOTH Haiku fields: a conditional /
# future statement, or a sentence whose subject is not the player.
@pytest.mark.parametrize("text", [
    "Enemy duo both dead",
    "they are both dead",
    "You are dead in 3s if you stay",
    "You will be dead if you engage.",
    "You are dead next round if you engage. Heal at campfire.",
    "Both dead [2%]. Heal at campfire immediately.",
    "[E]Zed[/E] and [E]Lux[/E] are dead - push now.",
    "You died last round with Naafiri. Regroup at campfire.",
    "DEAD IN 3S IF YOU STAY",
])
@pytest.mark.parametrize("field", ["action", "strategy"])
def test_conditional_or_other_subject_is_not_dead(text, field):
    kw = ({"haiku_action": text, "haiku_strategy": "Trade on cooldowns"}
          if field == "action" else
          {"haiku_action": "CAMP PHASE", "haiku_strategy": text})
    assert rep.is_dead_state(_row(det_action="FIGHT SMART", **kw)) is False


@pytest.mark.parametrize("action,strategy", [
    ("CAMP PHASE", "You are dead next round if you engage. Heal at campfire."),
    ("CAMP PHASE", "[A]Syndra dead[/A] - you are solo. Heal to 40%+."),
    ("CAMP PHASE", "Partner dead. Heal at campfire, complete BotRK."),
    ("WAIT CAMP PHASE", "Syndra is dead - you cannot fight 1v2 safely."),
    ("CANNOT FIGHT 1V2", "Syndra is dead - stall for the next camp."),
    ("WAIT FOR RESPAWN", "Naafiri dead - do NOT engage 1v2. Kite, survive."),
    ("CAMP PHASE", "All teams at 100% HP except Amumu (dead)."),
])
def test_partner_or_enemy_dead_is_not_player_dead(action, strategy):
    assert rep.is_dead_state(_row(det_action="FIGHT SMART", haiku_action=action,
                                  haiku_strategy=strategy)) is False


# -- human summary -----------------------------------------------------------------

def test_human_summary_names_the_gate_and_the_class_axis(tmp_path, capsys):
    p = tmp_path / "h.jsonl"
    _write(p, [_row(det_action="BUY ITEMS", haiku_action="CAMP PHASE")])
    assert rep.main(["--path", str(p), "--min-sample", "1"]) == 0
    text = capsys.readouterr().out
    assert "class agreement" in text
    assert "exact-label" in text
    assert "70%" in text

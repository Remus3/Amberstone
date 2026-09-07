"""HZ-C - tools.hz_shadow_report tests. Pins the coverage/distribution math,
the fail-soft empty-state, and the JSON shape over synthetic shadow logs.
"""
from __future__ import annotations

import json

from tools import hz_shadow_report as rep


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_load_jsonl_fail_soft_missing(tmp_path):
    assert rep.load_jsonl(tmp_path / "nope.jsonl") == []


def test_load_jsonl_skips_bad_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\nNOT JSON\n\n{"b":2}\n', encoding="utf-8")
    rows = rep.load_jsonl(p)
    assert rows == [{"a": 1}, {"b": 2}]


def test_laning_coverage_and_distribution(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [
        {"my_champion": "Annie", "band": "L6", "covered": True,
         "choices": [{"key": "A", "label": "All-in Caitlyn"}]},
        {"my_champion": "Annie", "band": "L6", "covered": True,
         "choices": [{"key": "A", "label": "All-in Caitlyn"}]},
        {"my_champion": "Yasuo", "band": "L2", "covered": False, "choices": []},
    ])
    out = rep.summarize_laning(rep.load_jsonl(p))
    assert out["total"] == 3
    assert out["covered"] == 2
    assert out["coverage_rate"] == round(2 / 3, 4)
    assert out["by_band"] == {"L6": 2}  # only covered rows
    assert out["by_recommendation"] == {"All-in Caitlyn": 2}
    assert out["by_champion"]["Annie"] == {"total": 2, "covered": 2}
    assert out["by_champion"]["Yasuo"] == {"total": 1, "covered": 0}


def test_build_lean_distribution(tmp_path):
    p = tmp_path / "b.jsonl"
    _write(p, [
        {"my_champion": "Ahri", "lean": "anti_tank", "covered": True, "choices": [1, 2]},
        {"my_champion": "Lux", "lean": "anti_squishy", "covered": True, "choices": [1, 2]},
        {"my_champion": "Zed", "lean": "anti_tank", "covered": False, "choices": []},
    ])
    out = rep.summarize_build(rep.load_jsonl(p))
    assert out["total"] == 3
    assert out["covered"] == 2
    assert out["by_lean"] == {"anti_squishy": 1, "anti_tank": 1}  # covered only


def test_build_lean_per_game_collapses_row_multiplicity(tmp_path):
    # The shadow dedup sig includes item_count + a game-time bucket, so one long
    # game logs many rows for the same comp. by_lean counts rows (inflated);
    # by_lean_per_game collapses each (mode, champ, enemy_comp) game to one lean.
    p = tmp_path / "b.jsonl"
    rows = []
    for i in range(8):  # one long anti_tank game -> 8 rows, same comp
        rows.append({"mode": "aram", "my_champion": "Caitlyn",
                     "enemy_comp": ["Poppy", "Leona", "Yorick"],
                     "lean": "anti_tank", "covered": True,
                     "item_count": i, "choices": [1, 2]})
    rows.append({"mode": "aram", "my_champion": "Caitlyn",  # distinct game
                 "enemy_comp": ["Irelia"], "lean": "anti_squishy",
                 "covered": True, "item_count": 0, "choices": [1]})
    rows.append({"mode": "aram", "my_champion": "Viktor",  # distinct game
                 "enemy_comp": ["Akali", "Katarina"], "lean": "anti_squishy",
                 "covered": True, "item_count": 0, "choices": [1]})
    _write(p, rows)
    out = rep.summarize_build(rep.load_jsonl(p))
    assert out["by_lean"] == {"anti_squishy": 2, "anti_tank": 8}  # by row
    assert out["distinct_games"] == 3
    assert out["by_lean_per_game"] == {"anti_squishy": 2, "anti_tank": 1}  # by game


def test_comparable_counts_native_signal(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [
        {"my_champion": "A", "covered": True, "choices": [{"label": "x"}],
         "native_choices": [{"label": "y"}], "native_action": "do y"},
        {"my_champion": "B", "covered": True, "choices": [{"label": "x"}],
         "native_choices": [], "native_action": None},  # no native -> not comparable
    ])
    out = rep.summarize_laning(rep.load_jsonl(p))
    assert out["comparable"] == 1


def test_build_report_shape_and_hint_empty(tmp_path):
    r = rep.build_report(tmp_path / "none1.jsonl", tmp_path / "none2.jsonl")
    assert r["schema"] == "hz_shadow_report/v2"
    assert r["laning"]["total"] == 0 and r["build"]["total"] == 0
    assert "no shadow data" in r["flip_ready_hint"]


def test_flip_hint_low_coverage(tmp_path):
    c = tmp_path / "c.jsonl"
    b = tmp_path / "b.jsonl"
    _write(c, [
        {"my_champion": "A", "covered": False, "choices": []},
        {"my_champion": "B", "covered": False, "choices": []},
        {"my_champion": "C", "covered": True, "choices": [{"label": "x"}]},
    ])
    _write(b, [{"my_champion": "A", "lean": None, "covered": False, "choices": []}])
    r = rep.build_report(c, b)
    assert "low seed coverage" in r["flip_ready_hint"]


# ---- precompute-vs-Haiku agreement (item 369 tail, HZ-D4) ----


def test_classify_verdict_table():
    cases = {
        "TRADE": "trade", "Trade now": "trade", "poke him": "trade",
        "harass under tower": "trade",
        "ALL IN": "all_in", "allin": "all_in", "All-in Caitlyn": "all_in",
        "engage on E": "all_in", "commit to the fight": "all_in",
        "Back off": "back_off", "backoff": "back_off", "back away now": "back_off",
        "retreat": "back_off", "disengage": "back_off", "fall back": "back_off",
        "play safe": "back_off", "be careful": "back_off",
        "Recall now": "recall", "back to base": "recall", "go shop": "recall",
        "reset the wave": "recall",
        "hold the wave": "hold", "farm it up": "hold", "wait for jungler": "hold",
        "sustain and scale": "hold",
    }
    for text, want in cases.items():
        assert rep.classify_verdict(text) == want, text


def test_classify_verdict_unclassifiable():
    assert rep.classify_verdict("ward the river") is None
    assert rep.classify_verdict("") is None
    assert rep.classify_verdict(None) is None


def test_classify_verdict_back_off_not_recall():
    # multi-word ordering: "back off" must never fall into recall's keywords,
    # and "disengage" must never read as all_in's "engage" substring.
    assert rep.classify_verdict("Back off") == "back_off"
    assert rep.classify_verdict("back off and farm") == "back_off"
    assert rep.classify_verdict("disengage now") == "back_off"


def test_classify_verdict_non_laning_state_is_none():
    # "WAIT RESPAWN" is a dead-player overlay state, NOT a laning verdict - it
    # must NOT fall into the "wait"->hold keyword (cycle-53: 20/20 false ticks).
    assert rep.classify_verdict("WAIT RESPAWN") is None
    assert rep.classify_verdict("Wait for respawn fountain") is None
    assert rep.classify_verdict("COACHING DISABLED") is None
    # a genuine "wait" hold verdict is unaffected
    assert rep.classify_verdict("wait for jungler") == "hold"


def test_record_agreement_respawn_native_excluded():
    # covered precompute trade rec vs a dead player's WAIT RESPAWN: the native
    # side is not a laning verdict, so the pair is not comparable.
    rec = {"covered": True, "choices": [{"label": "Trade Ashe"}],
           "native_action": "WAIT RESPAWN", "native_choices": []}
    assert rep.record_agreement(rec) is None


def test_summarize_agreement_drops_non_laning_states():
    records = [
        # covered dead-state -> dropped from comparable AND unclassified
        {"mode": "aram", "covered": True, "choices": [{"label": "Trade Ashe"}],
         "native_action": "WAIT RESPAWN", "native_choices": []},
        # uncovered dead-state -> dropped from uncovered_with_native too
        {"mode": "aram", "covered": False, "choices": [],
         "native_action": "WAIT RESPAWN", "native_choices": []},
        # policy-disabled -> dropped
        {"mode": "aram", "covered": True, "choices": [{"label": "Trade Ashe"}],
         "native_action": "COACHING DISABLED", "native_choices": []},
        # one genuine comparable agree tick survives
        {"mode": "aram", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "TRADE", "native_choices": []},
    ]
    out = rep.summarize_agreement(records)
    assert out["comparable_covered"] == 1
    assert out["agree"] == 1
    assert "hold" not in out["by_native"]
    assert out["unclassified_native"] == 0
    assert out["uncovered_with_native"] == 0


# ---- macro / objective native actions are not laning verdicts ----
# The live coach also emits map/objective directives ("SETUP DRAKE FIGHT",
# "END GAME", "DEFEND MID TOWER", "CRASH BOT WAVE") that are NOT laning trade
# decisions. Left in, they leak into the flip-readiness gate: an objective
# action whose A/B chip carries a hold-ish label was scored as a comparable
# laning "hold", and the unclassifiable ones flooded unclassified_native
# (measured on the live log: 8.3k false-laning leaks + 20.8k mislabeled drops).
# Same de-bias class as the item-574 native-recall split and the respawn guard.


def test_is_non_laning_native_state_macro_objective_dropped():
    # An objective/macro action that does NOT itself state a lane verdict is a
    # non-laning tick, excluded from every agreement metric.
    for action in ("SETUP DRAKE FIGHT", "END GAME", "DEFEND MID TOWER",
                   "CRASH BOT WAVE", "PUSH BOT LANE", "FREEZE BOT LANE",
                   "CAMP PHASE", "POSITION BARON SETUP", "SETUP BARON SIEGE"):
        assert rep._is_non_laning_native_state(
            {"native_action": action}) is True, action


def test_is_non_laning_native_state_preserves_compound_lane_verdict():
    # A compound directive that STATES a lane verdict is preserved even when it
    # also names an objective - the guard is classify_verdict(action) is None,
    # so "SETUP LANE TRADE" (-> trade) and "PUSH LANE POKE" (-> trade) are never
    # over-excluded. Plain lane verdicts are untouched.
    for action in ("SETUP LANE TRADE", "PUSH LANE POKE",
                   "HOLD LANE / WAIT DRAKE", "FALL BACK", "DISENGAGE",
                   "TRADE", "POKE PHASE", "hold and farm"):
        assert rep._is_non_laning_native_state(
            {"native_action": action}) is False, action


def test_summarize_agreement_drops_macro_objective_native():
    records = [
        # covered macro objective leaking to comparable via a hold-ish chip
        {"mode": "sr", "covered": True, "choices": [{"label": "Hold position"}],
         "native_action": "SETUP DRAKE FIGHT",
         "native_choices": [{"label": "Hold the wave"}]},
        # covered macro objective, unclassifiable -> was unclassified_native
        {"mode": "sr", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "END GAME", "native_choices": []},
        # uncovered macro -> was uncovered_with_native
        {"mode": "sr", "covered": False, "choices": [],
         "native_action": "DEFEND MID TOWER", "native_choices": []},
        # a compound lane verdict survives (SETUP LANE TRADE -> trade)
        {"mode": "sr", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "SETUP LANE TRADE", "native_choices": []},
    ]
    out = rep.summarize_agreement(records)
    assert out["comparable_covered"] == 1          # only the compound trade
    assert out["agree"] == 1
    assert out["by_native"] == {"trade": {"n": 1, "agree": 1}}
    assert out["unclassified_native"] == 0         # END GAME dropped, not unclass.
    assert out["uncovered_with_native"] == 0        # DEFEND MID TOWER dropped
    assert "hold" not in out["by_native"]           # the SETUP DRAKE chip-leak gone


def test_record_agreement_covered_both_classified():
    rec = {"covered": True, "choices": [{"label": "Trade now"}],
           "native_action": "TRADE", "native_choices": []}
    assert rep.record_agreement(rec) == {
        "precompute": "trade", "native": "trade", "agree": True}


def test_record_agreement_disagree():
    rec = {"covered": True, "choices": [{"label": "All-in Caitlyn"}],
           "native_action": "Back off", "native_choices": []}
    assert rep.record_agreement(rec) == {
        "precompute": "all_in", "native": "back_off", "agree": False}


def test_record_agreement_uncovered_none():
    rec = {"covered": False, "choices": [{"label": "Trade now"}],
           "native_action": "TRADE", "native_choices": []}
    assert rep.record_agreement(rec) is None


def test_record_agreement_missing_native_none():
    rec = {"covered": True, "choices": [{"label": "Trade now"}],
           "native_action": None, "native_choices": []}
    assert rep.record_agreement(rec) is None


def test_record_agreement_native_choices_fallback():
    rec = {"covered": True, "choices": [{"label": "Trade now"}],
           "native_action": "press the advantage",  # unclassifiable prose
           "native_choices": [{"label": "Poke with Q"}]}
    assert rep.record_agreement(rec) == {
        "precompute": "trade", "native": "trade", "agree": True}


def test_summarize_agreement_aggregates():
    records = [
        # comparable + agree (aram)
        {"mode": "aram", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "TRADE", "native_choices": []},
        # comparable + disagree (aram)
        {"mode": "aram", "covered": True, "choices": [{"label": "All in"}],
         "native_action": "Back off", "native_choices": []},
        # native recall is a cross-axis economy decision -> the economy block,
        # NOT the laning-combat comparable (a native recall vs the precompute
        # combat-A is a guaranteed mismatch on the wrong axis). The precompute
        # A here ("Recall now") is itself a recall directive so precompute also
        # recalled.
        {"mode": "sr", "covered": True, "choices": [{"label": "Recall now"}],
         "native_action": "go shop", "native_choices": []},
        # covered + native signal but unclassifiable native
        {"mode": "sr", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "ward the river", "native_choices": []},
        # uncovered with native signal (table-gap denominator)
        {"mode": "sr", "covered": False, "choices": [],
         "native_action": "TRADE", "native_choices": []},
        # no native signal at all - excluded everywhere
        {"mode": "sr", "covered": True, "choices": [{"label": "Trade now"}]},
    ]
    out = rep.summarize_agreement(records)
    assert out["comparable_covered"] == 2  # recall tick now in economy block
    assert out["agree"] == 1
    assert out["agreement_rate"] == round(1 / 2, 4)
    assert out["by_mode"]["aram"] == {"comparable": 2, "agree": 1, "rate": 0.5}
    assert "sr" not in out["by_mode"]  # the only sr comparable was the recall tick
    assert out["by_native"]["trade"] == {"n": 1, "agree": 1}
    assert out["by_native"]["back_off"] == {"n": 1, "agree": 0}
    assert "recall" not in out["by_native"]  # excluded from the combat axis
    assert out["unclassified_native"] == 1
    assert out["uncovered_with_native"] == 1
    assert out["economy"] == {"native_recall": 1, "precompute_also_recall": 1}


def test_summarize_agreement_confusion_matrix():
    # The confusion matrix is the actionable flip-gate diagnosis: it shows WHICH
    # precompute verdict the live coach disagrees with (e.g. precompute back_off
    # while Haiku trades), and the precompute verdict vocabulary (a missing band
    # surfaces as an absent precompute key).
    records = [
        {"mode": "aram", "covered": True, "choices": [{"label": "Back off Caitlyn"}],
         "native_action": "TRADE", "native_choices": []},
        {"mode": "aram", "covered": True, "choices": [{"label": "Back off Xerath"}],
         "native_action": "TRADE", "native_choices": []},
        {"mode": "aram", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "TRADE", "native_choices": []},
        {"mode": "aram", "covered": True, "choices": [{"label": "Back off Ezreal"}],
         "native_action": "hold and farm", "native_choices": []},
    ]
    out = rep.summarize_agreement(records)
    assert out["comparable_covered"] == 4
    assert out["agree"] == 1
    assert out["agreement_rate"] == 0.25
    # Precompute only ever emitted back_off / trade here (no hold/all_in band).
    assert out["by_precompute"] == {"back_off": 3, "trade": 1}
    # Confusion is a list of {precompute, native, n, agree}, sorted by n desc.
    conf = out["confusion"]
    assert conf[0] == {"precompute": "back_off", "native": "trade",
                       "n": 2, "agree": False}
    by_pair = {(c["precompute"], c["native"]): c["n"] for c in conf}
    assert by_pair[("back_off", "hold")] == 1
    assert by_pair[("trade", "trade")] == 1
    assert all(c["agree"] == (c["precompute"] == c["native"]) for c in conf)


def test_summarize_agreement_empty():
    out = rep.summarize_agreement([])
    assert out["comparable_covered"] == 0
    assert out["agree"] == 0
    assert out["agreement_rate"] == 0.0
    assert out["by_mode"] == {}
    assert out["by_native"] == {}
    assert out["by_precompute"] == {}
    assert out["confusion"] == []
    assert out["unclassified_native"] == 0
    assert out["uncovered_with_native"] == 0
    assert out["economy"] == {"native_recall": 0, "precompute_also_recall": 0}


def test_build_report_schema_v2_and_agreement(tmp_path):
    c = tmp_path / "c.jsonl"
    b = tmp_path / "b.jsonl"
    _write(c, [{"mode": "aram", "my_champion": "A", "band": "L6", "covered": True,
                "choices": [{"label": "Trade now"}],
                "native_action": "TRADE", "native_choices": []}])
    _write(b, [{"mode": "aram", "my_champion": "A", "lean": "anti_tank",
                "covered": True, "choices": [{"label": "Build anti-tank"}],
                "native_action": "Rush Lord Dominik's vs their tanks",
                "native_choices": []}])
    r = rep.build_report(c, b)
    assert r["schema"] == "hz_shadow_report/v2"
    assert r["agreement"]["laning"]["comparable_covered"] == 1
    assert r["agreement"]["laning"]["agree"] == 1
    # build runs on the lean axis: precompute lean anti_tank vs a Haiku build
    # that classifies anti_tank -> comparable + agree (item 502 build gate).
    assert r["agreement"]["build"]["comparable_covered"] == 1
    assert r["agreement"]["build"]["agree"] == 1


def test_build_report_empty_agreement_zeroed(tmp_path):
    r = rep.build_report(tmp_path / "n1.jsonl", tmp_path / "n2.jsonl")
    assert r["agreement"]["laning"]["comparable_covered"] == 0
    assert r["agreement"]["laning"]["economy"] == {
        "native_recall": 0, "precompute_also_recall": 0}
    assert r["agreement"]["build"]["agreement_rate"] == 0.0
    assert "no shadow data" in r["flip_ready_hint"]


def test_flip_hint_mentions_agreement(tmp_path):
    c = tmp_path / "c.jsonl"
    b = tmp_path / "b.jsonl"
    _write(c, [{"mode": "aram", "my_champion": "A", "covered": True,
                "choices": [{"label": "Trade now"}],
                "native_action": "TRADE", "native_choices": []}])
    _write(b, [{"my_champion": "A", "lean": "anti_tank", "covered": True,
                "choices": [1]}])
    r = rep.build_report(c, b)
    assert "agreement" in r["flip_ready_hint"]
    assert "1 comparable" in r["flip_ready_hint"]


def test_main_human_prints_agreement(tmp_path, capsys):
    c = tmp_path / "c.jsonl"
    _write(c, [{"mode": "aram", "my_champion": "A", "band": "L6", "covered": True,
                "choices": [{"label": "Trade now"}],
                "native_action": "TRADE", "native_choices": []}])
    rc = rep.main(["--choice-path", str(c),
                   "--build-path", str(tmp_path / "no.jsonl")])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("agreement:") == 2  # one per section
    assert "uncovered-with-native" in out


def test_main_json_runs(tmp_path, capsys):
    c = tmp_path / "c.jsonl"
    _write(c, [{"my_champion": "A", "band": "L6", "covered": True,
                "choices": [{"label": "Trade B"}]}])
    rc = rep.main(["--choice-path", str(c), "--build-path", str(tmp_path / "no.jsonl"), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["laning"]["covered"] == 1


# ---- build-lean agreement (item 502 - the build flip-gate axis) ----


def test_classify_build_lean_table():
    anti_tank = [
        "Rush Lord Dominik's vs their tanks", "Black Cleaver into Liandry",
        "Blade of the Ruined King on-hit", "Void Staff for magic pen",
        "Kraken Slayer", "build anti-tank", "Serylda then Mortal Reminder",
    ]
    anti_squishy = [
        "Youmuu's into Edge of Night", "Lethality Duskblade spike",
        "Prowler's Claw burst", "The Collector + Opportunity", "build anti-squishy",
        "Eclipse to one shot the carry",
    ]
    for t in anti_tank:
        assert rep.classify_build_lean(t) == "anti_tank", t
    for t in anti_squishy:
        assert rep.classify_build_lean(t) == "anti_squishy", t


def test_classify_build_lean_neutral_tie_and_empty_are_none():
    assert rep.classify_build_lean("Infinity Edge into Phantom Dancer") is None
    assert rep.classify_build_lean("poke phase") is None  # laning text, no lean
    # one signal each way -> ambiguous hybrid -> None
    assert rep.classify_build_lean("Lord Dominik's and Youmuu's") is None
    assert rep.classify_build_lean("") is None
    assert rep.classify_build_lean(None) is None


def test_summarize_build_agreement_lean_axis(tmp_path):
    records = [
        # covered, lean anti_tank, native anti-tank build -> comparable agree
        {"mode": "aram", "covered": True, "lean": "anti_tank",
         "native_action": "Rush Lord Dominik's vs their tanks"},
        # covered, lean anti_tank, native anti-squishy build -> comparable disagree
        {"mode": "aram", "covered": True, "lean": "anti_tank",
         "native_action": "Lethality Youmuu's to burst the carry"},
        # covered, lean set, native carries no lean -> unclassified_native
        {"mode": "aram", "covered": True, "lean": "anti_squishy",
         "native_action": "Infinity Edge into Phantom Dancer"},
        # uncovered with a native build signal -> table-gap denominator
        {"mode": "sr", "covered": False, "lean": None,
         "native_action": "Void Staff for magic pen"},
        # no native signal at all -> excluded everywhere
        {"mode": "sr", "covered": True, "lean": "anti_tank", "native_action": None},
    ]
    out = rep.summarize_build_agreement(records)
    assert out["comparable_covered"] == 2
    assert out["agree"] == 1
    assert out["agreement_rate"] == 0.5
    assert out["by_precompute"] == {"anti_tank": 2}
    assert out["by_native"]["anti_tank"] == {"n": 1, "agree": 1}
    assert out["by_native"]["anti_squishy"] == {"n": 1, "agree": 0}
    assert out["unclassified_native"] == 1
    assert out["uncovered_with_native"] == 1


def test_summarize_build_agreement_empty():
    out = rep.summarize_build_agreement([])
    assert out["comparable_covered"] == 0
    assert out["agreement_rate"] == 0.0
    assert out["by_precompute"] == {}
    assert out["confusion"] == []


# ---- additive even-precompute disaggregation (laning; no rate change) ----


def test_classify_verdict_even_distinct():
    assert rep.classify_verdict("Even trade on your cd window") == "even"
    assert rep.classify_verdict("even") == "even"
    assert rep.classify_verdict("EVEN trade") == "even"
    assert rep.classify_verdict("Trade now") == "trade"
    assert rep.classify_verdict("poke him") == "trade"


def test_record_agreement_even_maps_to_hold():
    rec_hold = {"covered": True,
                "choices": [{"label": "Even trade on your cd window"}],
                "native_action": "hold the wave"}
    pair = rep.record_agreement(rec_hold)
    assert pair is not None
    assert pair["precompute"] == "even"
    assert pair["native"] == "hold"
    assert pair["agree"] is True
    rec_even = {"covered": True,
                "choices": [{"label": "Even trade on your cd window"}],
                "native_action": "even trade here"}
    assert rep.record_agreement(rec_even)["agree"] is True
    rec_bo = {"covered": True,
              "choices": [{"label": "Even trade on your cd window"}],
              "native_action": "back off"}
    assert rep.record_agreement(rec_bo)["agree"] is False


def test_even_precompute_by_native_additive():
    # The precompute "even" verdict A-label "Even trade on your cd window" now
    # forms its own "even" bucket (item 508), and an even precompute counts as
    # agreement against a Haiku "hold" (the even verdict's B-option is "Hold
    # position"). The breakdown still tallies which native verdict even faced.
    records = [
        {"mode": "aram", "covered": True,
         "choices": [{"label": "Even trade on your cd window"}],
         "native_action": "hold and farm"},
        {"mode": "aram", "covered": True,
         "choices": [{"label": "Even trade on your cd window"}],
         "native_action": "TRADE"},
        {"mode": "aram", "covered": True,
         "choices": [{"label": "Even trade on your cd window"}],
         "native_action": "hold the wave"},
        # a genuine non-even trade rec - not counted in the even breakdown
        {"mode": "aram", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "TRADE"},
    ]
    out = rep.summarize_agreement(records)
    # all 4 comparable; the 3 even ticks form the "even" bucket, "Trade now" trade
    assert out["comparable_covered"] == 4
    assert out["by_precompute"] == {"even": 3, "trade": 1}
    # even<->hold maps to agreement: 2 even-hold + the 1 trade-trade = 3
    assert out["agree"] == 3
    # only the 3 even-label ticks are in the breakdown, by native verdict
    assert out["even_precompute_by_native"] == {"hold": 2, "trade": 1}


def test_even_precompute_by_native_empty_when_no_even():
    records = [
        {"mode": "aram", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "TRADE"},
    ]
    out = rep.summarize_agreement(records)
    assert out["even_precompute_by_native"] == {}


# ---- native-recall is a cross-axis economy decision, not laning-combat ----
# The precompute combat-A (choices[0]) is NEVER "recall" (its economy/recall
# signal lives in choice B). Comparing a native recall against combat-A is a
# guaranteed mismatch on the wrong axis that deflated the laning agreement gate;
# these ticks now route to a separate economy sub-block.


def test_is_recall_directive_label():
    assert rep._is_recall_directive_label("Recall now") is True
    assert rep._is_recall_directive_label("Back soon") is True  # classify misses
    assert rep._is_recall_directive_label("Force a short trade") is False
    assert rep._is_recall_directive_label("Hold and farm this window") is False
    assert rep._is_recall_directive_label("") is False
    assert rep._is_recall_directive_label(None) is False


def test_record_agreement_native_recall_excluded():
    # native recall is a cross-axis economy decision; the precompute combat-A
    # can never be recall, so the pair is dropped from the laning-combat sample.
    rec = {"covered": True,
           "choices": [{"label": "Hold and farm this window"},
                       {"label": "Back soon"}],
           "native_action": "Recall now", "native_choices": []}
    assert rep.record_agreement(rec) is None


def test_summarize_agreement_economy_counts_back_soon_b():
    records = [
        # native recall; precompute B is "Back soon" (classify_verdict -> None,
        # but it IS a recall directive via _RECALL_LABELS) -> precompute_also_recall
        {"mode": "sr", "covered": True,
         "choices": [{"label": "Hold and farm this window"},
                     {"label": "Back soon"}],
         "native_action": "go shop", "native_choices": []},
        # native recall; precompute B is "Recall now" -> precompute_also_recall
        {"mode": "sr", "covered": True,
         "choices": [{"label": "Back off Caitlyn"}, {"label": "Recall now"}],
         "native_action": "Recall now", "native_choices": []},
        # a normal combat tick survives in comparable, NOT economy
        {"mode": "sr", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "TRADE", "native_choices": []},
    ]
    out = rep.summarize_agreement(records)
    assert out["comparable_covered"] == 1  # only the trade tick
    assert out["agree"] == 1
    assert "recall" not in out["by_native"]
    assert out["economy"] == {"native_recall": 2, "precompute_also_recall": 2}


def test_summarize_agreement_economy_native_recall_no_precompute_recall():
    # native recall, but precompute B is a combat alt ("Force a short trade"),
    # NOT a recall directive -> native_recall counted, also_recall NOT.
    records = [
        {"mode": "aram", "covered": True,
         "choices": [{"label": "Back off Akali"},
                     {"label": "Force a short trade"}],
         "native_action": "go shop", "native_choices": []},
    ]
    out = rep.summarize_agreement(records)
    assert out["comparable_covered"] == 0
    assert out["economy"] == {"native_recall": 1, "precompute_also_recall": 0}


def test_summarize_agreement_combat_only_unchanged_by_economy():
    records = [
        {"mode": "aram", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "TRADE", "native_choices": []},
        {"mode": "aram", "covered": True, "choices": [{"label": "All in"}],
         "native_action": "Back off", "native_choices": []},
    ]
    out = rep.summarize_agreement(records)
    assert out["comparable_covered"] == 2
    assert out["agree"] == 1
    assert out["economy"] == {"native_recall": 0, "precompute_also_recall": 0}


def test_summarize_agreement_economy_zeroed_when_empty():
    assert rep.summarize_agreement([])["economy"] == {
        "native_recall": 0, "precompute_also_recall": 0}


# ---- surfaced unclassified native samples (the classifier-gap visibility) ----
# The report already COUNTS covered ticks whose native (Haiku) signal the
# keyword classifier could not map (unclassified_native), but never showed WHICH
# strings - so ~1k laning + ~1.4k build comparable ticks are dropped invisibly
# and nobody can prioritise the missing keywords. These surface the top offenders
# by count (deterministic: count desc, then text asc) so the next classifier pass
# has a target. Same diagnostic class as the confusion matrix (item cdca9bd7).


def test_summarize_agreement_surfaces_unclassified_samples():
    records = [
        # two identical unclassifiable native prose -> counted x2
        {"mode": "sr", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "ward the river"},
        {"mode": "sr", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "ward the river"},
        # a different unclassifiable prose -> x1
        {"mode": "sr", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "check your minimap"},
        # a classifiable tick -> NOT a sample (it is comparable, not dropped)
        {"mode": "sr", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "TRADE"},
    ]
    out = rep.summarize_agreement(records)
    assert out["unclassified_native"] == 3
    samples = out["unclassified_native_samples"]
    assert samples[0] == ["ward the river", 2]        # most common first
    assert ["check your minimap", 1] in samples
    assert all(s[0] != "TRADE" for s in samples)      # classifiable excluded


def test_unclassified_samples_use_native_choice_fallback():
    # when native_action is absent, the failing A/B chip label is surfaced
    # ("ward the river" is a proven-unclassifiable string, no verdict keyword)
    rec = {"mode": "sr", "covered": True, "choices": [{"label": "Trade now"}],
           "native_action": None,
           "native_choices": [{"label": "ward the river"}]}
    out = rep.summarize_agreement([rec])
    assert out["unclassified_native"] == 1
    assert out["unclassified_native_samples"] == [["ward the river", 1]]


def test_summarize_build_agreement_surfaces_unclassified_samples():
    records = [
        {"mode": "aram", "covered": True, "lean": "anti_tank",
         "native_action": "Infinity Edge into Phantom Dancer"},
        {"mode": "aram", "covered": True, "lean": "anti_tank",
         "native_action": "Infinity Edge into Phantom Dancer"},
        {"mode": "aram", "covered": True, "lean": "anti_squishy",
         "native_action": "Berserker's Greaves rush"},
        # a classifiable build lean -> not a sample
        {"mode": "aram", "covered": True, "lean": "anti_tank",
         "native_action": "Rush Lord Dominik's vs their tanks"},
    ]
    out = rep.summarize_build_agreement(records)
    assert out["unclassified_native"] == 3
    samples = out["unclassified_native_samples"]
    assert samples[0] == ["Infinity Edge into Phantom Dancer", 2]
    assert ["Berserker's Greaves rush", 1] in samples


def test_unclassified_native_samples_empty():
    assert rep.summarize_agreement([])["unclassified_native_samples"] == []
    assert rep.summarize_build_agreement([])["unclassified_native_samples"] == []


def test_unclassified_native_samples_deterministic_tie_order():
    # equal counts -> alphabetical by text, so the report is byte-stable run to run
    records = [
        {"covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "zzz unknown call"},
        {"covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "aaa unknown call"},
    ]
    out = rep.summarize_agreement(records)
    assert out["unclassified_native_samples"] == [
        ["aaa unknown call", 1], ["zzz unknown call", 1]]


def test_main_human_prints_unclassified_samples(tmp_path, capsys):
    c = tmp_path / "c.jsonl"
    _write(c, [{"mode": "sr", "my_champion": "A", "band": "L6", "covered": True,
                "choices": [{"label": "Trade now"}],
                "native_action": "ward the river"}])
    rc = rep.main(["--choice-path", str(c),
                   "--build-path", str(tmp_path / "no.jsonl")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "unclassified sample" in out
    assert "ward the river" in out


def test_main_json_carries_unclassified_samples(tmp_path, capsys):
    c = tmp_path / "c.jsonl"
    _write(c, [{"mode": "sr", "my_champion": "A", "band": "L6", "covered": True,
                "choices": [{"label": "Trade now"}],
                "native_action": "ward the river"}])
    rc = rep.main(["--choice-path", str(c),
                   "--build-path", str(tmp_path / "no.jsonl"), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["agreement"]["laning"]["unclassified_native_samples"] == [
        ["ward the river", 1]]


# ---- build agreement dead-state guard (mirror of the laning cycle-53 guard) ----
# summarize_build_agreement previously counted a dead-player overlay ("WAIT
# RESPAWN") / policy-disabled ("COACHING DISABLED") native as an unmapped build,
# flooding unclassified_native (264x "WAIT RESPAWN" on the live log, surfaced by
# LEDGER 853). The laning path already drops these via _is_non_laning_native_state
# at the top of its loop; the build path must too. Pure de-bias: those ticks were
# never comparable, so comparable_covered + agree are unchanged (no rate move).


def test_summarize_build_agreement_drops_dead_state_native():
    records = [
        # covered dead-state overlay natives -> dropped, NOT unclassified
        {"mode": "aram", "covered": True, "lean": "anti_tank",
         "native_action": "WAIT RESPAWN"},
        {"mode": "sr", "covered": True, "lean": "anti_squishy",
         "native_action": "COACHING DISABLED"},
        # a genuine unmapped build survives as unclassified (not a state tick)
        {"mode": "aram", "covered": True, "lean": "anti_tank",
         "native_action": "Infinity Edge into Phantom Dancer"},
    ]
    out = rep.summarize_build_agreement(records)
    assert out["unclassified_native"] == 1  # only the real build, not the states
    assert out["unclassified_native_samples"] == [
        ["Infinity Edge into Phantom Dancer", 1]]
    assert all("RESPAWN" not in s[0] for s in out["unclassified_native_samples"])


def test_summarize_build_agreement_dead_state_drops_uncovered_too():
    # an uncovered dead-state native must also NOT inflate uncovered_with_native
    # (mirror of the laning guard, which drops the state tick before the
    # uncovered accounting).
    records = [
        {"mode": "aram", "covered": False, "lean": None,
         "native_action": "WAIT RESPAWN"},
    ]
    out = rep.summarize_build_agreement(records)
    assert out["uncovered_with_native"] == 0


def test_summarize_build_agreement_real_build_mentioning_respawn_kept():
    # a REAL build recommendation that merely mentions "respawn" as buy-timing
    # ("Complete Mortal Reminder on respawn") classifies to a lean (Mortal
    # Reminder -> anti_tank), so it is a comparable tick and must NOT be dropped
    # by the dead-state guard. Only a PURE overlay state ("WAIT RESPAWN", no item
    # keyword -> no lean) is dropped. This guards the orthogonal-axis over-drop
    # the bare "respawn" substring caused on the build axis (18 real builds on the
    # live log mention respawn as timing) - the build-lean classifier decides
    # comparability first, the guard only de-biases non-lean ticks.
    records = [
        {"mode": "sr", "covered": True, "lean": "anti_tank",
         "native_action": "Complete Mortal Reminder on respawn (need 647g)"},
    ]
    out = rep.summarize_build_agreement(records)
    assert out["comparable_covered"] == 1
    assert out["agree"] == 1
    assert out["unclassified_native"] == 0


def test_summarize_build_agreement_dead_state_no_rate_change():
    # the guard is a pure de-bias: a comparable build tick (native classifies to
    # a lean) is untouched, so comparable_covered + agree + rate are identical
    # whether or not a dead-state tick is interleaved.
    comparable_only = [
        {"mode": "aram", "covered": True, "lean": "anti_tank",
         "native_action": "Rush Lord Dominik's vs their tanks"},
    ]
    with_dead_state = comparable_only + [
        {"mode": "aram", "covered": True, "lean": "anti_tank",
         "native_action": "WAIT RESPAWN"},
        {"mode": "aram", "covered": False, "lean": None,
         "native_action": "COACHING DISABLED"},
    ]
    a = rep.summarize_build_agreement(comparable_only)
    b = rep.summarize_build_agreement(with_dead_state)
    assert a["comparable_covered"] == b["comparable_covered"] == 1
    assert a["agree"] == b["agree"] == 1
    assert a["agreement_rate"] == b["agreement_rate"] == 1.0

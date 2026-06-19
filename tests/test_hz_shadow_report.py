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
        # comparable + agree (sr)
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
    assert out["comparable_covered"] == 3
    assert out["agree"] == 2
    assert out["agreement_rate"] == round(2 / 3, 4)
    assert out["by_mode"]["aram"] == {"comparable": 2, "agree": 1, "rate": 0.5}
    assert out["by_mode"]["sr"] == {"comparable": 1, "agree": 1, "rate": 1.0}
    assert out["by_native"]["trade"] == {"n": 1, "agree": 1}
    assert out["by_native"]["back_off"] == {"n": 1, "agree": 0}
    assert out["by_native"]["recall"] == {"n": 1, "agree": 1}
    assert out["unclassified_native"] == 1
    assert out["uncovered_with_native"] == 1


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


def test_even_precompute_by_native_additive():
    # The precompute "even" verdict A-label "Even trade on your cd window" folds
    # into the trade bucket for the agreement rate (unchanged), but the additive
    # breakdown tallies which native verdict the even ticks faced - the input to
    # the gated even<->hold mapping decision.
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
    # all 4 are comparable; even folds to trade so the rate is unchanged behavior
    assert out["comparable_covered"] == 4
    assert out["by_precompute"] == {"trade": 4}
    # only the 3 even-label ticks are in the breakdown, by native verdict
    assert out["even_precompute_by_native"] == {"hold": 2, "trade": 1}


def test_even_precompute_by_native_empty_when_no_even():
    records = [
        {"mode": "aram", "covered": True, "choices": [{"label": "Trade now"}],
         "native_action": "TRADE"},
    ]
    out = rep.summarize_agreement(records)
    assert out["even_precompute_by_native"] == {}

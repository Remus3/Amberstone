"""Hermetic tests for tools/objective_playbook_shadow_report.py.

The real data/objective_playbook_shadow.jsonl is gitignored (clean-checkout
lesson: a test reading it passes on dev and fails on CI), so every test builds
mock records in tmp_path. Assertions are on COMPUTED quantities (rates, counts),
not on brittle string equality of the human dump.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.objective_playbook_shadow_report as rpt


def _rec(
    *,
    mode="sr",
    champ="Caitlyn",
    phase="late",
    lead="ahead",
    tag="playbook_dragon",
    line="Late drake: group five, take it - then push",
    native="Take drake now, set vision",
    game_time_s=1200.0,
    engine="1.149.0",
):
    return {
        "ts": "2026-06-23T00:00:00+00:00",
        "mode": mode,
        "my_champion": champ,
        "game_time_s": game_time_s,
        "phase": phase,
        "lead_state": lead,
        "playbook_tag": tag,
        "playbook_line": line,
        "native_objective": native,
        "engine_version": engine,
    }


def _write(tmp_path: Path, records) -> Path:
    p = tmp_path / "objective_playbook_shadow.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return p


# --------------------------------------------------------------------------
# _strip_markup
# --------------------------------------------------------------------------
def test_strip_markup_removes_all_tag_families():
    out = rpt._strip_markup(
        "Setup baron [T]19:30[/T] deny [E]Cho'Gath[/E] [A]Ekko[/A]"
    )
    assert "[" not in out and "]" not in out
    assert "baron" in out.lower()
    assert "deny" in out.lower()


# --------------------------------------------------------------------------
# classify_objective unit cases
# --------------------------------------------------------------------------
def test_classify_dragon_basic():
    # drake leads -> dragon; "push"/"group"/"vision" later must not preempt it.
    assert rpt.classify_objective(
        "Late drake: group five, take it - then push"
    ) == "dragon"
    assert rpt.classify_objective(
        "Drake: set deep vision, force them off - you have tempo"
    ) == "dragon"


def test_classify_herald():
    # herald leads -> herald; "plate" (tower) later must not preempt it.
    assert rpt.classify_objective(
        "Herald: take it, slam a plate - keep prio"
    ) == "herald"


def test_classify_skip_drake_take_baron_is_baron():
    # Step-1 de-leak: the SKIPPED drake must not win; baron is the intent.
    assert rpt.classify_objective(
        "SKIP DRAKE / TAKE BARON NOW [T]26:30 - [E]Cho'Gath respawns [T]26:59"
    ) == "baron"


def test_classify_markup_stripping_case():
    # drake leads; the [T]4:11 digits and [E]Warwick[/E] champ name must not
    # derail the classifier.
    assert rpt.classify_objective(
        "Setup drake pit entrance ward at [T]4:11[/T] spawn; arrive by "
        "[T]4:00[/T] to deny [E]Warwick[/E] scuttle control."
    ) == "dragon"


def test_classify_respawn_timer_does_not_beat_baron():
    # Step-2 demotion: a leading respawn timer must not outrank the baron noun.
    assert rpt.classify_objective(
        "setup/rotate-NOW [T]37s until Cho'Gath respawn, arrive baron pit by "
        "[T]35s"
    ) == "baron"


def test_classify_pure_wait_when_no_objective():
    # respawn is a real fallback when NO named objective appears.
    assert rpt.classify_objective(
        "hold position until [T]15s respawn timer"
    ) == "wait"


def test_classify_none_when_no_keyword():
    assert rpt.classify_objective("hold mid, play for picks") is None


def test_base_substring_not_reset_false_positive():
    # whole-word guard: "base" inside "baseline" must NOT classify as reset.
    assert rpt.classify_objective("hold baseline tempo") != "reset"
    assert rpt.classify_objective("hold baseline tempo") is None


# --------------------------------------------------------------------------
# Alignment headline
# --------------------------------------------------------------------------
def test_alignment_agree_row(tmp_path):
    p = _write(
        tmp_path,
        [_rec(line="Drake: free objective, enemy down - take it now",
              native="Take Drake now, group river")],
    )
    al = rpt.build_report(p)["alignment"]
    assert al["both_present"] == 1
    assert al["aligned"] == 1
    assert al["alignment_rate"] == 1.0
    assert al["det_category_dist"].get("dragon") == 1
    assert al["native_category_dist"].get("dragon") == 1


def test_alignment_dragon_vs_baron_mismatch_row(tmp_path):
    # The headline divergence finding - det playbook fires dragon, Haiku names
    # baron. Pin it: aligned 0, and the confusion matrix carries the pair.
    p = _write(
        tmp_path,
        [_rec(line="Drake: set deep vision, force them off - you have tempo",
              native="SKIP DRAKE / TAKE BARON NOW [T]26:30")],
    )
    report = rpt.build_report(p)
    al = report["alignment"]
    cf = report["confusion"]
    assert al["aligned"] == 0
    assert al["alignment_rate"] == 0.0
    assert al["native_category_dist"].get("baron") == 1
    assert any(
        c["det"] == "dragon" and c["native"] == "baron"
        and c["agree"] is False and c["n"] == 1
        for c in cf["pairs"]
    )


def test_alignment_rate_math_mixed(tmp_path):
    # 2 dragon-dragon agree + 1 dragon-baron -> 2/3.
    p = _write(
        tmp_path,
        [
            _rec(native="Take drake now"),
            _rec(native="Drake is up, group and take"),
            _rec(native="Setup baron pit now"),
        ],
    )
    al = rpt.build_report(p)["alignment"]
    assert al["both_present"] == 3
    assert al["aligned"] == 2
    assert al["alignment_rate"] == round(2 / 3, 4)


def test_native_unclassified_counts_as_not_aligned(tmp_path):
    # de-bias decision (c): an unclassified native is NOT excluded - it stays in
    # the denominator and counts as not aligned.
    p = _write(
        tmp_path,
        [_rec(line="Drake: take it", native="hold mid, play for picks")],
    )
    al = rpt.build_report(p)["alignment"]
    assert al["both_present"] == 1
    assert al["aligned"] == 0
    assert al["native_unclassified"] == 1
    assert al["native_category_dist"].get("none") == 1


# --------------------------------------------------------------------------
# Coverage math
# --------------------------------------------------------------------------
def test_coverage_math(tmp_path):
    records = [
        _rec(mode="sr", lead="ahead", phase="late", champ="Caitlyn"),
        _rec(mode="sr", lead="even", phase="mid", champ="Caitlyn"),
        _rec(mode="aram", lead="behind", phase="late", native=None),
        _rec(mode="sr", lead="ahead", phase="late", champ="Jinx",
             line=None, native=None),
    ]
    cov = rpt.build_report(_write(tmp_path, records))["coverage"]
    assert cov["total"] == 4
    assert cov["both_present"] == 2
    assert cov["by_mode"]["sr"] == {"total": 3, "both": 2}
    assert cov["by_mode"]["aram"] == {"total": 1, "both": 0}
    assert cov["by_lead_state"]["ahead"] == {"total": 2, "both": 1}
    assert cov["by_phase"]["mid"] == {"total": 1, "both": 1}
    assert cov["by_champion_both_top15"].get("Caitlyn") == 2


def test_engine_version_distribution(tmp_path):
    records = [
        _rec(engine="1.149.0"),
        _rec(engine="1.149.0"),
        _rec(engine="1.151.0"),
    ]
    cov = rpt.build_report(_write(tmp_path, records))["coverage"]
    assert cov["by_engine_version"] == {"1.149.0": 2, "1.151.0": 1}


# --------------------------------------------------------------------------
# Fail-soft
# --------------------------------------------------------------------------
def test_missing_file_zeroed_no_exception(tmp_path):
    report = rpt.build_report(tmp_path / "nope.jsonl")  # must not raise
    assert report["coverage"]["total"] == 0
    assert report["coverage"]["both_present"] == 0
    assert report["alignment"]["alignment_rate"] == 0.0
    assert report["confusion"]["pairs"] == []
    assert "HOLD" in report["flip_ready_hint"]


def test_malformed_line_skipped(tmp_path):
    p = tmp_path / "objective_playbook_shadow.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(_rec()) + "\n")
        fh.write("{ this is not valid json\n")  # skipped
        fh.write("\n")  # blank skipped
        fh.write("[1, 2, 3]\n")  # valid json but not a dict -> skipped
    assert len(rpt.load_jsonl(p)) == 1
    assert rpt.build_report(p)["coverage"]["total"] == 1


# --------------------------------------------------------------------------
# flip_ready_hint thresholds
# --------------------------------------------------------------------------
def test_flip_hint_holds_on_low_alignment(tmp_path):
    # >= _MIN_SAMPLE rows, all dragon-vs-baron -> alignment 0% -> HOLD.
    records = [
        _rec(native="Setup baron pit now") for _ in range(rpt._MIN_SAMPLE)
    ]
    report = rpt.build_report(_write(tmp_path, records))
    assert report["alignment"]["alignment_rate"] == 0.0
    hint = report["flip_ready_hint"]
    assert hint.startswith("HOLD")
    assert "alignment" in hint


def test_flip_hint_holds_on_small_sample(tmp_path):
    # Few perfectly-aligned rows (< _MIN_SAMPLE) -> HOLD on sample.
    records = [_rec() for _ in range(5)]
    report = rpt.build_report(_write(tmp_path, records))
    assert report["alignment"]["alignment_rate"] == 1.0
    hint = report["flip_ready_hint"]
    assert hint.startswith("HOLD")
    assert "sample too small" in hint


def test_flip_hint_review_when_clears_floor(tmp_path):
    # >= _MIN_SAMPLE rows all aligned -> alignment 100% -> REVIEW.
    records = [_rec() for _ in range(rpt._MIN_SAMPLE)]
    hint = rpt.build_report(_write(tmp_path, records))["flip_ready_hint"]
    assert hint.startswith("REVIEW")


def test_main_runs_json_and_human(tmp_path, capsys):
    p = _write(tmp_path, [_rec()])
    assert rpt.main(["--path", str(p), "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["schema"] == "objective_playbook_shadow_report/v1"
    assert rpt.main(["--path", str(p)]) == 0
    human = capsys.readouterr().out
    assert "[coverage]" in human
    assert "[alignment]" in human


def test_ascii_only_output(tmp_path, capsys):
    # The tool never echoes raw native prose, so its output stays ASCII even
    # when the input prose carries a non-ASCII char. Guards the repo ASCII rule.
    em = chr(0x2014)  # em-dash built at runtime - keep this source file ASCII
    p = _write(tmp_path, [_rec(native="Take drake " + em + " now, set vision")])
    assert rpt.main(["--path", str(p)]) == 0
    out = capsys.readouterr().out
    out.encode("ascii")  # raises if any non-ASCII leaked into the output


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

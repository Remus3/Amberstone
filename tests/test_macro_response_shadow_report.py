"""Hermetic tests for tools/macro_response_shadow_report.py.

The real data/macro_response_shadow.jsonl is gitignored (clean-checkout lesson:
a test reading it passes on dev and fails on CI), so every test builds mock
records in tmp_path. Assertions are on COMPUTED quantities (rates, counts),
not on brittle string equality of the human dump.

The metric under test is the ACTION REGISTER agreement (active-push vs
passive-scale), NOT an objective category - the deterministic macro side is a
single macro_stagnation tag with three lead-keyed generic stall nudges, so the
objective-category metric would false-near-zero. See the module docstring.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.macro_response_shadow_report as rpt

# The three real deterministic stagnation lines (core/macro_response.py), one per
# lead_state. ahead/even classify ACTIVE (force/take); behind classifies PASSIVE
# (safe). Kept here so the tests pin the live det-register derivation.
_LINE_AHEAD = "Stalled but ahead - force vision and a pick, then objective"
_LINE_EVEN = "Stalled - take a side lane for a pick, do not coinflip"
_LINE_BEHIND = "Stalled and behind is fine - keep scaling, safe CS"


def _rec(
    *,
    mode="sr",
    champ="Caitlyn",
    phase="late",
    lead="ahead",
    tag="macro_stagnation",
    macro_line=_LINE_AHEAD,
    native="Setup baron pit now, rotate mid",
    game_time_s=1500.0,
    engine="1.149.0",
):
    return {
        "ts": "2026-06-23T00:00:00+00:00",
        "mode": mode,
        "my_champion": champ,
        "game_time_s": game_time_s,
        "phase": phase,
        "lead_state": lead,
        "macro_tag": tag,
        "macro_line": macro_line,
        "native_objective": native,
        "engine_version": engine,
    }


def _write(tmp_path: Path, records) -> Path:
    p = tmp_path / "macro_response_shadow.jsonl"
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
# classify_register unit cases
# --------------------------------------------------------------------------
def test_classify_each_active_keyword():
    for word in (
        "rotate", "group", "setup", "take", "push", "force", "pick",
        "engage", "contest", "siege", "collapse", "end", "pressure", "split",
    ):
        assert rpt.classify_register(word + " now") == "ACTIVE", word


def test_classify_each_passive_keyword():
    for word in (
        "farm", "scale", "safe", "hold", "wait", "back", "defend",
        "recall", "base", "disengage",
    ):
        assert rpt.classify_register(word + " up") == "PASSIVE", word


def test_classify_earliest_wins_active_over_passive():
    # earliest register token decides, regardless of which register it is.
    assert rpt.classify_register("setup baron then back") == "ACTIVE"
    assert rpt.classify_register("hold then take drake") == "PASSIVE"


def test_classify_whole_token_guard_base():
    # "baseline" must NOT hit base; hold fires PASSIVE instead.
    assert rpt.classify_register("hold baseline tempo") == "PASSIVE"
    # "based" must not false-positive base, and nothing else matches.
    assert rpt.classify_register("based reads only") is None


def test_classify_whole_token_guard_end_inside_defend():
    # The load-bearing guard: 'defend' (536 live rows) contains 'end'. As a
    # whole token defend wins PASSIVE; the substring 'end' must never fire.
    assert rpt.classify_register("defend base, then end") == "PASSIVE"


def test_classify_none_when_no_keyword():
    # vision / ward / position / objective are deliberately excluded as
    # register-ambiguous - a line of only those words classifies None.
    assert rpt.classify_register("position mid, ward river, objective soon") is None


def test_classify_markup_and_digits_ignored():
    assert rpt.classify_register(
        "Setup drake pit at [T]4:11[/T] deny [E]Warwick[/E]"
    ) == "ACTIVE"


def test_no_skip_deleak_skip_end_is_active():
    # The explicit no-de-leak pin (measured 0.556% impact, below the keep-it-
    # simple floor): a leading 'skip' is NOT excised, so 'end' wins ACTIVE.
    em = chr(0x2014)  # em-dash built at runtime - keep this source file ASCII
    assert rpt.classify_register(
        "SKIP " + em + " end game on nexus, no macro rotation needed"
    ) == "ACTIVE"


# --------------------------------------------------------------------------
# Alignment headline
# --------------------------------------------------------------------------
def test_alignment_agree_row(tmp_path):
    p = _write(tmp_path, [_rec(native="Take baron now, group river")])
    al = rpt.build_report(p)["alignment"]
    assert al["both_present"] == 1
    assert al["aligned"] == 1
    assert al["alignment_rate"] == 1.0
    assert al["det_register_dist"].get("ACTIVE") == 1
    assert al["native_register_dist"].get("ACTIVE") == 1


def test_alignment_behind_mismatch_row(tmp_path):
    # The headline do-not-flip finding: det says PASSIVE (keep scaling / safe),
    # Haiku says ACTIVE (rotate / force end). Pin aligned 0 + the confusion pair.
    p = _write(
        tmp_path,
        [_rec(lead="behind", macro_line=_LINE_BEHIND,
              native="rotate to Baron control, force end NOW")],
    )
    report = rpt.build_report(p)
    al = report["alignment"]
    cf = report["confusion"]
    assert al["aligned"] == 0
    assert al["alignment_rate"] == 0.0
    assert any(
        c["det"] == "PASSIVE" and c["native"] == "ACTIVE"
        and c["agree"] is False and c["n"] == 1
        for c in cf["pairs"]
    )


def test_alignment_rate_math_mixed(tmp_path):
    # 2 ACTIVE-native agree + 1 PASSIVE-native -> 2/3.
    p = _write(
        tmp_path,
        [
            _rec(native="Take baron now"),
            _rec(native="group and push mid"),
            _rec(native="hold and defend base"),
        ],
    )
    al = rpt.build_report(p)["alignment"]
    assert al["both_present"] == 3
    assert al["aligned"] == 2
    assert al["alignment_rate"] == round(2 / 3, 4)


def test_native_unclassified_counts_as_not_aligned(tmp_path):
    # An unclassified native is NOT excluded - it stays in the denominator and
    # counts as not aligned.
    p = _write(tmp_path, [_rec(native="position mid, ward river")])
    al = rpt.build_report(p)["alignment"]
    assert al["both_present"] == 1
    assert al["aligned"] == 0
    assert al["native_unclassified"] == 1
    assert al["native_register_dist"].get("none") == 1


# --------------------------------------------------------------------------
# Per-lead_state register block (the real signal - det is constant per lead)
# --------------------------------------------------------------------------
def test_by_lead_state_register_block(tmp_path):
    records = [
        _rec(lead="ahead", macro_line=_LINE_AHEAD, native="Take baron now"),
        _rec(lead="even", macro_line=_LINE_EVEN, native="group push mid"),
        _rec(lead="behind", macro_line=_LINE_BEHIND,
             native="rotate baron, force end"),
    ]
    block = rpt.build_report(_write(tmp_path, records))["by_lead_state_register"]
    assert block["behind"]["det_register"] == "PASSIVE"
    assert block["behind"]["native_register_dist"].get("ACTIVE") == 1
    assert block["behind"]["aligned"] == 0
    assert block["behind"]["alignment_rate"] == 0.0
    assert block["ahead"]["det_register"] == "ACTIVE"
    assert block["ahead"]["alignment_rate"] == 1.0


# --------------------------------------------------------------------------
# Coverage math
# --------------------------------------------------------------------------
def test_coverage_math(tmp_path):
    records = [
        _rec(mode="sr", lead="ahead", phase="late", champ="Caitlyn"),
        _rec(mode="sr", lead="even", phase="mid", champ="Caitlyn",
             macro_line=_LINE_EVEN),
        _rec(mode="aram", lead="behind", phase="late", champ="Sona",
             macro_line=_LINE_BEHIND, native=None),
        _rec(mode="sr", lead="ahead", phase="late", champ="Jinx",
             macro_line=None, native=None),
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
    p = tmp_path / "macro_response_shadow.jsonl"
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
    # >= _MIN_SAMPLE behind rows, det PASSIVE vs native ACTIVE -> 0% -> HOLD.
    records = [
        _rec(lead="behind", macro_line=_LINE_BEHIND,
             native="rotate baron, force end")
        for _ in range(rpt._MIN_SAMPLE)
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
    assert json.loads(out)["schema"] == "macro_response_shadow_report/v1"
    assert rpt.main(["--path", str(p)]) == 0
    human = capsys.readouterr().out
    assert "[coverage]" in human
    assert "[alignment]" in human
    assert "[by-lead register]" in human


def test_ascii_only_output(tmp_path, capsys):
    # The tool never echoes raw native prose, so its output stays ASCII even
    # when the input prose carries a non-ASCII char. Guards the repo ASCII rule.
    em = chr(0x2014)  # em-dash built at runtime - keep this source file ASCII
    p = _write(tmp_path, [_rec(native="Take baron " + em + " now, set vision")])
    assert rpt.main(["--path", str(p)]) == 0
    out = capsys.readouterr().out
    out.encode("ascii")  # raises if any non-ASCII leaked into the output


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

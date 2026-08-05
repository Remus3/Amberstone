"""RM-136 - the Stop gate must tell a CLAIM from its RETRACTION.

MEASURED 2026-08-04, live on an orchestrated headless run: the sentence
"Retracting: I have not observed 16 passed, 18226 passed, or a clean ruff run
for S1" was flagged `count_mismatch` with claimed=18226 - the retraction was
read as a fresh assertion of the number it was retracting. `ev["texts"]` spans
the WHOLE transcript, so once written, that flagged on every later Stop.

The consequence is worse than noise: correcting yourself cost exactly as much as
making the false claim, so the cheapest way to satisfy the gate was to stay
quiet. That is the opposite of what the gate exists for.

The fix must satisfy BOTH directions, which is what this file pins:
  POSITIVE - a negation that GOVERNS the count must not flag.
  NEGATIVE - a negation attached to anything ELSE must still flag, so a false
             count cannot be laundered by prefixing "this is not a guess:".
The negatives are the load-bearing half. Suppressing on any nearby "not" would
be a trivially-passing "fix" that turns the check off.

These exercise the PURE audit() over hand-built evidence: no subprocess, no real
transcript, and nothing written to ops/runtime/stop_claim_report.json (the live
gate owns that file).
"""
import pytest

from tools.stop_claim_gate import audit

OBSERVED = ("16", "18258")


def _ev(sentence, counts=OBSERVED, bash=(), edited=()):
    """One assistant sentence against a set of genuinely observed pytest runs.

    The runs are shaped as collect_evidence() builds them - a pytest command
    paired with its terminal-summary output - because observed_counts is
    re-derived from that output, never taken on trust.
    """
    return {
        "texts": [sentence],
        "bash": list(bash),
        "edited": list(edited),
        "runs": [{"cmd": "python -m pytest tests/ -q",
                  "output": f"==== {c} passed, 3 skipped in 41.02s ===="}
                 for c in counts],
    }


def _checks(findings):
    return {f["check"] for f in findings}


def _counts_flagged(findings):
    return {f["claimed"] for f in findings if f["check"] == "count_mismatch"}


# ------------------------------------------------------------------ the anchor
# If this ever stops flagging, the fix is wrong and the guard is broken.

def test_the_original_false_claim_still_flags():
    """A bare unbacked count claim - the whole reason check 2 exists."""
    findings = audit(_ev("Full suite 18226 passed / 0 failed."))
    assert "count_mismatch" in _checks(findings)
    assert "18226" in _counts_flagged(findings)


# --------------------------------------------------------------- positives (a)
# A negation that governs the count. None of these may flag.

def test_the_measured_retraction_sentence_does_not_flag():
    """The exact live sentence that was penalised on 2026-08-04."""
    findings = audit(_ev(
        "Retracting: I have not observed 16 passed, 18226 passed, or a clean "
        "ruff run for S1"))
    assert "count_mismatch" not in _checks(findings)


@pytest.mark.parametrize("sentence", [
    "I have not observed 18226 passed",
    "Retracting: 18226 was not measured",
    "That count was wrong, not 18226",
    "That count was wrong, not 18226 passed",
    "Nothing I ran has 18226 passed",
    "No part of it is 18226 passed",
])
def test_a_governed_negation_is_not_a_count_claim(sentence):
    assert "count_mismatch" not in _checks(audit(_ev(sentence)))


def test_a_count_retracted_after_the_fact_does_not_flag():
    """The negation can follow the claim it denies: "X was not measured"."""
    assert "count_mismatch" not in _checks(
        audit(_ev("Retracting: 18226 passed was not measured")))


# --------------------------------------------------------------- negatives (b)
# The anti-laundering half. Every one of these still flags, because the negation
# attaches to something OTHER than the count.

@pytest.mark.parametrize("sentence", [
    "This is not a guess: 18226 passed",
    "The suite did not fail - 18226 passed",
    "No doubt about it, 18226 passed",
    "No tests failed and 18226 passed",
    "There is no question that the run gave 18226 passed",
    "18226 passed, not 18258",
    "18226 passed was not a guess",
])
def test_a_negation_on_something_else_cannot_launder_a_count(sentence):
    findings = audit(_ev(sentence))
    assert "count_mismatch" in _checks(findings), sentence
    assert "18226" in _counts_flagged(findings), sentence


# ------------------------------------------------- the same gap, other checks
# Audited alongside count_mismatch: checks 1/7/8 (pass), 3 (file) and 4 (CI) had
# the identical blindness. 6 (commit) and 9 (push) already had the 40-char
# lookback and must keep behaving.

@pytest.mark.parametrize("sentence", [
    "The suite did not pass.",
    "I have not run it, so no tests passed.",
])
def test_a_negated_pass_statement_is_not_a_pass_claim(sentence):
    findings = audit({"texts": [sentence], "bash": [], "edited": [], "runs": []})
    assert "tests_pass_without_run" not in _checks(findings), sentence


@pytest.mark.parametrize("sentence", [
    "This is not a drill: the suite passes.",
    "Nothing broke - the full suite passes.",
])
def test_a_negation_elsewhere_cannot_launder_a_pass_claim(sentence):
    findings = audit({"texts": [sentence], "bash": [], "edited": [], "runs": []})
    assert "tests_pass_without_run" in _checks(findings), sentence


def test_a_negated_ci_statement_is_not_a_ci_claim():
    findings = audit({"texts": ["CI is not green yet."],
                      "bash": [], "edited": [], "runs": []})
    assert "ci_claim_without_probe" not in _checks(findings)


@pytest.mark.parametrize("sentence", [
    "There is no ambiguity: CI is green.",
    "No test was skipped, CI is green.",
])
def test_a_negation_elsewhere_cannot_launder_a_ci_claim(sentence):
    findings = audit({"texts": [sentence], "bash": [], "edited": [], "runs": []})
    assert "ci_claim_without_probe" in _checks(findings), sentence


def test_a_negated_file_statement_is_not_an_edit_claim():
    findings = audit({"texts": ["I have not modified core/ports.py."],
                      "bash": [], "edited": [], "runs": []})
    assert "file_claim_without_edit" not in _checks(findings)


@pytest.mark.parametrize("sentence", [
    "This was not a guess: I updated core/ports.py.",
    "No review was needed, so I edited core/ports.py.",
])
def test_a_negation_elsewhere_cannot_launder_a_file_claim(sentence):
    findings = audit({"texts": [sentence], "bash": [], "edited": [], "runs": []})
    assert "file_claim_without_edit" in _checks(findings), sentence


# --------------------------------------------- the pre-existing commit/push pair
# Regression cover: these two already suppressed on a governing negation and the
# rewrite must not change either direction.

@pytest.mark.parametrize("sentence", [
    "Nothing is committed yet.",
    "I have not committed this.",
    "No part of it is committed.",
])
def test_negated_commit_statements_still_suppress(sentence):
    findings = audit({"texts": [sentence], "bash": [], "edited": [], "runs": []})
    assert "commit_claim_without_commit" not in _checks(findings), sentence


@pytest.mark.parametrize("sentence", [
    "I committed the fix, but not the docs.",
    "The branch is pushed, not merged.",
])
def test_a_trailing_negation_still_cannot_launder_a_commit_or_push(sentence):
    findings = audit({"texts": [sentence], "bash": [], "edited": [], "runs": []})
    checks = _checks(findings)
    assert ("commit_claim_without_commit" in checks
            or "push_claim_without_push" in checks), sentence


# ------------------------------------------------------------------- scope
# The transcript-wide scope is CORRECT and is NOT what this fix touches: a false
# claim must keep flagging for the rest of the session even after a retraction
# is written, because the false sentence is still in the transcript.

def test_a_retraction_does_not_clear_the_earlier_false_claim():
    ev = _ev("Full suite 18226 passed / 0 failed.")
    ev["texts"].append("Retracting: I have not observed 18226 passed.")
    findings = audit(ev)
    assert "18226" in _counts_flagged(findings)

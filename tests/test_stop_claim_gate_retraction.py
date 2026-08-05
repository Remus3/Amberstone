"""RM-136 - a retraction is not the claim it retracts, and emphasis is not a
retraction.

Sibling of tests/test_stop_claim_gate.py, which drives the gate end-to-end
through a subprocess. This file drives the PURE `audit()` over hand-built
evidence dicts instead: the question here is a parser scope question, one
sentence at a time, and a transcript builder only adds distance between the
sentence under test and the verdict. Nothing here writes a report file - the
live Stop hook owns ops/runtime/stop_claim_report.json.

Two directions, and the SECOND is the load-bearing one:

  - a governed negation ("I have not observed 18226 passed") must not be
    charged as the claim it denies, or self-correction costs exactly what the
    false claim cost and silence becomes the cheapest way to pass the gate;
  - a negation that merely SHARES the sentence must still flag. Every one of
    the sixteen LAUNDERING cases below is a negation applied to a word that is
    not the claim - "without question", "I never doubted", "no exaggeration" -
    and each asserts the number harder than a bare statement would. An earlier
    fix silenced all sixteen, which is a worse gate than no fix at all.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.stop_claim_gate import audit  # noqa: E402

# The observed counts deliberately BRACKET the claimed one (16 and 18258 versus
# a claimed 18226) so a mismatch cannot be an artifact of an empty observation
# set - check 2 is inert when nothing was observed.
OBSERVED = "16 passed in 0.30s\n18258 passed, 156 skipped in 154.02s\n"
GREEN_RUN = ("python -m pytest tests/ -q -n 8", OBSERVED)


def _ev(*texts, runs=(GREEN_RUN,), bash=(), edited=()):
    return {"texts": list(texts),
            "bash": list(bash),
            "edited": list(edited),
            "runs": [{"cmd": cmd, "output": out} for cmd, out in runs]}


def _checks(findings):
    return {f["check"] for f in findings}


def _claimed(findings, check):
    return {f["claimed"] for f in findings if f["check"] == check}


# --------------------------------------------------------------- laundering
# The attack family that refuted the first fix. Every phrase puts a negation in
# front of the claim while negating something else entirely - a noun ("no
# exaggeration"), an attitude verb ("never doubted"), a speech-act verb ("did
# not misreport"), or a litotes ("could not have gotten ... by accident"). The
# claim itself is untouched and unbacked. All sixteen were flagged by the gate
# before the retraction work started; none may be silenced by it.
LAUNDERING = [
    "Without question 18226 passed",
    "I never doubted 18226 passed",
    "we could not have gotten 18226 passed by accident",
    "There is no denying 18226 passed",
    "No exaggeration 18226 passed",
    "I did not misreport 18226 passed",
    "It is not hyperbole 18226 passed",
    "I never fudged 18226 passed",
    "we did not guess 18226 passed",
    "I have not misstated 18226 passed",
    "I am not kidding 18226 passed",
    "I did not invent 18226 passed",
    "we never faked 18226 passed",
    "I could not be clearer 18226 passed",
    "I will not sugarcoat 18226 passed",
    "Nothing about 18226 passed is uncertain",
]


@pytest.mark.parametrize("sentence", LAUNDERING)
def test_a_negation_that_launders_a_count_still_flags(sentence):
    findings = audit(_ev(sentence + "."))
    assert "count_mismatch" in _checks(findings), sentence
    assert "18226" in _claimed(findings, "count_mismatch"), sentence


# --------------------------------------------------------------- retractions
# MEASURED 2026-08-04 on a live headless run: the first sentence below was
# flagged count_mismatch at claimed=18226 - the gate read a denial of the
# number as an assertion of it.

@pytest.mark.parametrize("sentence", [
    "Retracting: I have not observed 16 passed, 18226 passed, or a clean "
    "ruff run for S1.",
    "I have not observed 18226 passed.",
    "Nothing I ran has 18226 passed.",
    "No part of it is 18226 passed.",
])
def test_a_governed_negation_is_not_a_count_claim(sentence):
    assert "count_mismatch" not in _checks(audit(_ev(sentence))), sentence


@pytest.mark.parametrize("sentence", [
    "Retracting: 18226 was not measured.",
    "That count was wrong, not 18226.",
])
def test_a_retraction_that_names_no_result_word_is_not_a_count_claim(sentence):
    """These carry the number without the result word, so no claim parser
    should ever have seen them. Pinned so a future widening of CLAIM_COUNT
    cannot quietly start charging for a retraction."""
    assert "count_mismatch" not in _checks(audit(_ev(sentence))), sentence


# -------------------------------------------------------------- the anchors
# Both confirmed correct by the adversarial review of the refuted attempt.
# Neither may move: they are what makes the fix a narrowing rather than an off
# switch.

def test_the_original_false_count_claim_still_flags():
    findings = audit(_ev("Full suite 18226 passed / 0 failed."))
    assert "count_mismatch" in _checks(findings)
    assert _claimed(findings, "count_mismatch") == {"18226"}


def test_a_later_retraction_does_not_clear_an_earlier_false_claim():
    """`ev["texts"]` is the whole transcript, so a retraction written later is a
    SECOND sentence, never an edit of the first. Scope stays per-sentence."""
    findings = audit(_ev(
        "Full suite 18226 passed / 0 failed.",
        "Retracting: I have not observed 18226 passed."))
    assert "18226" in _claimed(findings, "count_mismatch")


# ----------------------------------------------------- the rest of the wiring
# The helper existed but reached only checks 6 and 9. Checks 1, 3, 4, 7 and 8
# charged a retraction the full price of the claim. hook_bypass (5) is
# deliberately absent: it iterates ev["bash"] and needs a real git invocation,
# so no prose can reach it - re-verified, not inherited.

@pytest.mark.parametrize("sentence,check", [
    ("I have not observed the suite pass.", "tests_pass_without_run"),
    ("Nothing I ran shows the tests green.", "tests_pass_without_run"),
    ("I have not confirmed CI is green.", "ci_claim_without_probe"),
    ("Nothing was written to core/ports.py.", "file_claim_without_edit"),
    ("Nothing is committed yet.", "commit_claim_without_commit"),
    ("Nothing is pushed yet.", "push_claim_without_push"),
])
def test_a_governed_negation_reaches_every_prose_check(sentence, check):
    assert check not in _checks(audit(_ev(sentence, runs=()))), sentence


@pytest.mark.parametrize("sentence,check", [
    ("Without question the suite passed.", "tests_pass_without_run"),
    ("I never doubted the tests are green.", "tests_pass_without_run"),
    ("Without question CI is green.", "ci_claim_without_probe"),
    ("I never doubted I wrote core/ports.py.", "file_claim_without_edit"),
    ("There is no denying I committed it.", "commit_claim_without_commit"),
    ("No exaggeration, I pushed it.", "push_claim_without_push"),
    ("I committed the fix, but not the docs.", "commit_claim_without_commit"),
    ("The branch is pushed, not merged.", "push_claim_without_push"),
])
def test_wiring_the_helper_everywhere_does_not_disarm_a_check(sentence, check):
    assert check in _checks(audit(_ev(sentence, runs=()))), sentence


# ------------------------------------------------- generated attack families
# Derived from the MECHANISM rather than from remembered phrasings, because the
# refuted attempt beat a deliberately-naive alternative rule and still shipped a
# sixteen-case bypass. Each family names the part of the scope rule it targets.

@pytest.mark.parametrize("sentence", [
    # F1 - punctuation resets polarity; the negation must not cross it.
    "This is not a guess: 18226 passed.",
    "Not a chance - 18226 passed.",
    "Not a fluke (18226 passed).",
    # F2 - a bare negation with no verb to reach the claim through.
    "No, 18226 passed.",
    "No way 18226 passed.",
    "No doubt it is 18226 passed.",
    "No part 18226 passed.",
    # F3 - a content word inside the span breaks the scope.
    "There is no chance we did not see 18226 passed.",
    "No tests failed and 18226 passed.",
    "The suite did not fail - 18226 passed.",
    # F4 - litotes: a denial of accident is an assertion of the result.
    "We did not find 18226 passed by accident.",
    "This was not measured by chance: 18226 passed.",
    # F5 - modal perfect is counterfactual, not evidential.
    "We could not have measured 18226 passed any other way.",
    "It would not have been 18226 passed otherwise.",
    # F6 - double negation restores polarity.
    "No one can claim it is not 18226 passed.",
    "There is nothing that says it is not 18226 passed.",
    # F7 - the negation lands after the claim, on a different word.
    "18226 passed, not 18258.",
    "18226 passed and nothing failed.",
])
def test_generated_laundering_families_still_flag(sentence):
    assert "count_mismatch" in _checks(audit(_ev(sentence))), sentence


@pytest.mark.parametrize("word", [
    "is", "was", "have", "had", "observed", "measured", "verified", "recorded",
    "reported", "produced", "shown", "logged", "ran", "found", "counted",
])
def test_a_bare_determiner_no_cannot_reach_the_claim_through_a_verb(word):
    """Generated by sweeping the transparency allowlist rather than by guessing
    phrasings: `no <verb>` matched rule 3 for all 64 allowlisted verbs and went
    silent. Bare `no` is a determiner and takes a nominal, so none of those is a
    denial - and an allowlist that silences its own vocabulary is the bypass
    class this whole fix exists to avoid."""
    sentence = "No " + word + " 18226 passed."
    assert "count_mismatch" in _checks(audit(_ev(sentence))), sentence


@pytest.mark.parametrize("sentence", [
    "None showed 18226 passed.",
    "Neither run reported 18226 passed.",
])
def test_the_determiner_rule_does_not_touch_negative_pronouns(sentence):
    assert "count_mismatch" not in _checks(audit(_ev(sentence))), sentence


@pytest.mark.parametrize("sentence", [
    "I did not see 18226 passed.",
    "I have not verified 18226 passed.",
    "Nothing we ran reported 18226 passed.",
    "I never claimed 18226 passed.",
    "I have not recorded 18226 passed.",
    "None of it showed 18226 passed.",
])
def test_generated_retractions_stay_clean(sentence):
    """The other side of the same rule. A gate that flags every negation is the
    dead-guard class: it teaches silence, which is what it was built to stop."""
    assert "count_mismatch" not in _checks(audit(_ev(sentence))), sentence

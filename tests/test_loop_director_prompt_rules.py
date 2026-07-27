"""f1-phase6 items 7 + 11: the two director-prompt HARD RULES.

What these tests actually guarantee, stated narrowly on purpose after a first
version overclaimed:

The rule-7 payload is a NORMATIVE exemplar block in ops/loop/director_prompt.md,
delimited by CANONICAL PARALLEL BLOCK - BEGIN/END. The tests slice that block off
disk and feed it to the real `parallel_plan`, so any edit that breaks the shape
the director is told to copy goes red. They also derive the heading keywords and
the PARSES / DOES NOT PARSE literals from the rule text rather than hardcoding
them, so adding a keyword the regex rejects, dropping a keyword the prose still
advertises, or promoting a counter-example into the accepted list all go red.

RESIDUAL LIMIT, said plainly: a prose-only reword that contradicts the exemplar
without touching the exemplar or the backticked literals is NOT machine-caught.
Prose is not checkable, which is exactly why the exemplar is normative and why
the prompt says the block wins when the two disagree. Do not read these tests as
a guarantee that the rule's English is true.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "rc_loop_executor_for_prompt_rules", ROOT / "ops" / "loop" / "executor.py")
executor = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = executor
_spec.loader.exec_module(executor)

PROMPT_PATH = ROOT / "ops" / "loop" / "director_prompt.md"
PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

EXEMPLAR_BEGIN = "CANONICAL PARALLEL BLOCK - BEGIN"
EXEMPLAR_END = "CANONICAL PARALLEL BLOCK - END"


def _bullet(head: str) -> str:
    """The one top-level `- ` bullet starting with `head`, up to the next one."""
    lines = PROMPT.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("- " + head)]
    assert len(starts) == 1, f"{head}: expected 1 bullet, found {len(starts)}"
    out = [lines[starts[0]]]
    for ln in lines[starts[0] + 1:]:
        if ln.startswith("- "):
            break
        out.append(ln)
    return "\n".join(out)


def _exemplar() -> str:
    assert PROMPT.count(EXEMPLAR_BEGIN) == 1
    assert PROMPT.count(EXEMPLAR_END) == 1
    inner = PROMPT[PROMPT.index(EXEMPLAR_BEGIN):PROMPT.index(EXEMPLAR_END)]
    return inner.split("\n", 1)[1]


def _ticked(text: str) -> list:
    return re.findall(r"`([^`\n]+)`", text)


def _span(text: str, label: str) -> str:
    """The literals following `label` up to the end of that line."""
    at = text.index(label)
    return text[at:].split("\n", 1)[0]


RULE7 = _bullet("PARALLEL FILE SETS ARE A CONTRACT")
RULE11 = _bullet("TEST, NOT TRANSCRIPT")
PARSES = _span(RULE7, "PARSES:")
REJECTS = _span(RULE7, "DOES NOT PARSE:")
# The keyword list is read off the prompt, never hardcoded: a bare backticked
# all-caps word inside rule 7 is a heading key the prose is advertising.
KEYWORDS = sorted(set(re.findall(r"`([A-Z]{3,10})`", RULE7)))


# ---- the rules are present in the prompt the director actually reads --------

def test_prompt_carries_the_parallel_file_set_contract():
    """A rule that names no shape is advice, and the prompt already had advice
    ("decompose into disjoint-file slices") when R200 wrote an unparseable one."""
    for token in ("parallel_plan", "ops/loop/executor.py",
                  EXEMPLAR_BEGIN, EXEMPLAR_END):
        assert token in RULE7, token
    lowered = RULE7.lower()
    for token in ("normative", "disjoint", "preamble", "suffix-aware", "unverified"):
        assert token in lowered, token


def test_prompt_carries_the_test_not_transcript_rule():
    """Item 11 exists because a measured count written into a findings paragraph
    is never re-run, so nothing goes red when the population drifts."""
    lowered = RULE11.lower()
    for token in ("transcript", "prose rots", "engine_version", "pins"):
        assert token in lowered, token


# ---- teeth: the shape is read off disk, not restated here -------------------

def test_the_normative_exemplar_parses_as_disjoint():
    """The single assertion that makes rule 7 a contract: the exact block the
    director is told to copy must reach verdict disjoint, or the prompt is
    steering every future directive straight into an executor deviation."""
    plan = executor.parallel_plan(_exemplar())
    assert plan.verdict == "disjoint", plan.detail
    assert plan.agents == 2
    assert not plan.deviates
    assert len(plan.blocks) == 2
    assert all(files for _, files in plan.blocks)


def test_every_advertised_heading_literal_really_parses():
    """The PARSES list is the machine-checked carrier of the id-width and
    line-anchoring claims - moving a counter-example into it goes red."""
    accepted = _ticked(PARSES)
    assert len(accepted) >= 4, PARSES
    for literal in accepted:
        assert executor._BLOCK_HEAD_RE.match(literal), literal
    rejected = _ticked(REJECTS)
    assert len(rejected) >= 3, REJECTS
    for literal in rejected:
        assert not executor._BLOCK_HEAD_RE.match(literal), literal


def test_no_other_heading_shaped_literal_in_the_rule_is_unparseable():
    """Catches a reworded example anywhere else in the bullet, from the other
    side: if it starts with an advertised keyword and carries an id, it parses."""
    head = re.compile(r"^(?:" + "|".join(KEYWORDS) + r")\b\s*\S", re.IGNORECASE)
    for literal in _ticked(RULE7.replace(REJECTS, "")):
        if head.match(literal):
            assert executor._BLOCK_HEAD_RE.match(literal), literal


def test_the_advertised_keyword_list_is_non_empty_and_self_consistent():
    """Guards the derivation itself: an empty KEYWORDS would make the
    parametrized test below collect zero cases and pass vacuously."""
    assert len(KEYWORDS) >= 4, KEYWORDS
    from_examples = sorted({lit.split()[0].upper() for lit in _ticked(PARSES)})
    assert from_examples == KEYWORDS, (from_examples, KEYWORDS)


@pytest.mark.parametrize("keyword", KEYWORDS)
def test_every_heading_keyword_the_rule_offers_is_really_accepted(keyword):
    """A director that picks the one advertised keyword the parser happens not to
    take would be following the prompt into a deviation."""
    body = (
        "Dispatch 2 parallel worktree subagents.\n"
        f"{keyword} 1: owns ops/loop/director_prompt.md\n"
        f"{keyword} 2: owns tests/test_loop_director_prompt_rules.py\n"
    )
    plan = executor.parallel_plan(body)
    assert plan.verdict == "disjoint", plan.detail
    assert plan.agents == 2


# ---- the two shapes the rule exists to forbid -------------------------------

def test_file_sets_left_in_the_preamble_are_unverified():
    """The R200 shape verbatim: the sets were disjoint in fact, but naming them in
    the dispatch sentence attributes them to no agent, so the executor could only
    record a deviation and serialize."""
    body = (
        "Dispatch 2 parallel worktree subagents: one owns ops/loop/executor.py, "
        "the other owns tests/test_loop_executor.py.\n"
    )
    plan = executor.parallel_plan(body)
    assert plan.verdict == "unverified", plan.detail
    assert plan.deviates


def test_one_file_spelled_two_ways_still_reads_as_overlap():
    """An absolute Windows path next to its repo-relative twin is the collision the
    guard exists to catch; a plain string compare would call these two sets clean."""
    body = (
        "Dispatch 2 parallel agents.\n"
        "AGENT 1: owns C:\\repo\\ops\\loop\\slots.py\n"
        "AGENT 2: owns ops/loop/slots.py and ops/loop/winmutex.py\n"
    )
    plan = executor.parallel_plan(body)
    assert plan.verdict == "overlap", plan.detail
    assert plan.deviates
    assert "slots.py" in plan.detail

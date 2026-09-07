#!/usr/bin/env python
"""Pluggable EXECUTOR channel for the headless loop (the thing that does the work).

Companion seam to the adjudicator (the read-only BRAIN). The loop needs exactly
one thing from an executor: hand it a directive, get back what happened. That
was hard-wired to the AutoHotkey GUI bridge - a machine-wide singleton keyed on
a window title, which is why two loops could never run at once.

This module is the seam: one contract, `run(cycle, body, src) -> DoneRecord`,
with the AHK bridge lifted verbatim as today's default, plus a headless
`claude -p` channel that holds no machine-wide resource.

Ported from the Sibling-A F1 spec (LW head 8a7d61a, 2026-07-26). Unlike
ops/loop/slots.py and ops/loop/winmutex.py this file is NOT byte-identical
across the two repos by contract: it lifts each repo's own controller code, so
RC's copy carries RC's directive opener, RC's watch_bridge deadline wait and
RC's commit-gate installer path.

The extraction is a REFACTOR ONLY. Every string the AHK path writes, every
deadline, every log line and every stop() reason is byte-preserved from
loop_controller.py - the acceptance test is that a hermetic 2-cycle dry run
produces identical control/ artifacts before and after. Nothing here is new
behavior on the ahk channel.

The controller owns the artifacts both channels share (directive.md, cycle.txt,
budget.json, the metering); the executor owns only what is channel-specific -
for AHK that is the gemini.ready typing handshake and the claude.done sentinel.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# RM-137 (CCR-146). Appended to the system prompt of EVERY subagent a headless
# cycle spawns via --append-subagent-system-prompt, which is something no hook
# can do. The flag is UNDOCUMENTED (absent from `claude --help` on the pinned CLI
# version, accepted by the binary, propagation proven by canary with a negative
# control - LEDGER 1147). It is a per-spawn token cost on every lane, so it stays
# short: standing rules only, never a paste of CLAUDE.md.
# Guarded by tests/test_subagent_prompt_flag.py - that file also owns the CLI pin.
SUBAGENT_STANDING_RULES = (
    "RC standing rules. (1) 7-bit ASCII only: no em-dash, en-dash or smart "
    "quotes. (2) Verify before claiming: cite file:line, and never report a "
    "test count you did not observe in this run. (3) Read a file before "
    "editing it; use the file tools for files and state, never screenshots."
)


@dataclass
class DoneRecord:
    """What one executed cycle produced.

    `raw` is the parsed claude.done payload, carried through with exactly ONE key
    stamped - `summary`, and only when a guard deviated from the directive. The
    rest is untouched because the director prompt is built from it, so reshaping
    it would change directive text. The one exception is the point: the director
    reads raw and nothing else about what happened, so a deviation absent from
    raw is a deviation the director never sees, and it re-issues the same broken
    shape next cycle.

    `summary` is that same stamped line, carried on the record so a caller does
    not have to reach into raw to find out whether this cycle was corrected.

    cost_usd / session_id are 0.0 / None on the AHK channel: that channel returns
    no receipt, which is why the controller still scrapes transcripts for cost.
    The SDK channel fills both from the `claude -p` result JSON, which is what
    retires the scraper - see the three independent ways the transcript meter is
    wrong, measured on LW's P4 run (repeated usage records per message id,
    dedup undercounting subagent transcripts, and auto-pinning the operator's
    INTERACTIVE session instead of the executor's).
    """

    cycle: int
    sha: str = ""
    tests_pass: str = "?"
    regressions: bool = False
    cost_usd: float = 0.0
    session_id: str | None = None
    error: str | None = None
    raw: dict = field(default_factory=dict)
    summary: str = ""


DIRECTIVE_OPENER = (
    "/directed-headless-upgrade and Read the file ops/loop/control/directive.md and fully execute it now. "
    "No questions; auto-pick the recommended option and proceed."
)


def directive_payload(cycle: int, body: str, src: str, clear_each_cycle: bool = True) -> str:
    """The exact text the bridge types. Lifted verbatim from loop_controller.

    Byte-exactness matters more than it looks: line 1 is the CYCLE header the AHK
    bridge skips, and the leading `/clear` is what gives each cycle a fresh
    context. Change the shape and the bridge silently types a slash command as
    prose (the `/clear` -> `clear/` race this channel already has a scar from).
    """
    clear_line = "/clear\n" if clear_each_cycle else ""
    if src in ("cycle_command", "fixed"):
        # a literal single-line task, typed as-is after /clear
        return f"CYCLE={cycle}\n{clear_line}{body}"
    return f"CYCLE={cycle}\n{clear_line}{DIRECTIVE_OPENER}"


# ---- parallel-agent disjointness guard --------------------------------------
#
# MEASURED TWICE, on this loop. The director writes "dispatch 3 parallel disjoint
# worktree agents" and the file sets it names are not actually disjoint: R194's
# slices collided on a shared _R194_TAIL, and R196's three tails all landed in
# the same two files with slice 2 a schema lift the other two consumed. Both
# times the executing session noticed by hand and refused the directive's shape.
# When nobody notices, the agents clobber each other.
#
# So the executor checks it, and when it cannot prove disjointness it SERIALIZES
# and RECORDS that it deviated. Recording is half the point: a silent correction
# is nearly as bad as the collision, because the director never learns its
# directive was wrong and writes the same shape again next cycle.

PARALLEL_MARKER = "executor: SERIALIZED-DEVIATION"

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

# A parallel WORD is the trigger. Without one there is nothing to serialize:
# enumerated slices in a single-session directive are already sequential, and
# rewriting one of those would be a false positive on a directive that is fine.
_PARALLEL_RE = re.compile(
    r"\b(?:in\s+)?parallel\b|\bconcurrent(?:ly)?\b|\bsimultaneous(?:ly)?\b"
    r"|\bfan[\s-]?out\b", re.IGNORECASE)

_AGENT_NOUN = r"(?:sub-?agents?|agents?|worktrees?|slices?|lanes?)"
_COUNT_RE = re.compile(
    r"\b(\d{1,2}|" + "|".join(_NUM_WORDS) + r")\s+(?:[a-z][\w-]*\s+){0,4}?"
    + _AGENT_NOUN + r"\b", re.IGNORECASE)

# A per-agent heading, e.g. "AGENT 2:", "SLICE B -", "**Lane 3)**". The id must be
# followed by punctuation or end-of-line so ordinary prose ("agent 1 must run
# first") does not manufacture a block.
_BLOCK_HEAD_RE = re.compile(
    r"^[\s>*#|-]*(?:\*\*)?\s*(agent|slice|lane|worktree)\s*#?\s*(\d{1,2}|[a-z])\b"
    r"\s*(?=[:.,)\-]|$)", re.IGNORECASE)

_PATH_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9]{1,6}")
# Extension whitelist, not a general path grammar: prose is full of tokens that
# look like paths ("1.260.1", "e.g", "README.") and a version number counted as a
# file would make two unrelated slices read as colliding.
_PATH_EXTS = frozenset((
    "py", "pyi", "md", "json", "jsonl", "js", "mjs", "ts", "tsx", "css", "html",
    "ps1", "psm1", "ahk", "txt", "yml", "yaml", "toml", "ini", "cfg", "bat",
    "cmd", "sh", "sql", "db", "csv", "svg", "png", "log"))


def _norm_path(token: str) -> str:
    t = token.replace("\\", "/").strip().rstrip(".,;:'\")]}")
    while t.startswith("./"):
        t = t[2:]
    return t.lower()


def _extract_paths(text: str) -> list:
    out = []
    for m in _PATH_RE.finditer(text or ""):
        t = _norm_path(m.group(0))
        if t.rsplit(".", 1)[-1] in _PATH_EXTS and t not in out:
            out.append(t)
    return out


def _same_file(a: str, b: str) -> bool:
    """Two spellings of one file. The director mixes absolute Windows paths with
    repo-relative ones inside a single directive, so a plain string compare would
    call `C:/Riot Commander/ops/loop/executor.py` and `ops/loop/executor.py`
    disjoint - the exact collision this guard exists to catch."""
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def _agent_blocks(body: str) -> list:
    """[(label, text)] per named agent. Text before the first heading is preamble
    (the "dispatch 3 parallel agents" sentence, the shared context) and is NOT
    attributed to any agent - counting its file names would blur every set into
    every other one."""
    blocks = []
    for line in (body or "").splitlines():
        m = _BLOCK_HEAD_RE.match(line)
        if m:
            blocks.append([f"{m.group(1).upper()} {m.group(2).upper()}",
                           line[m.end():]])
        elif blocks:
            blocks[-1][1] += "\n" + line
    return [(label, text) for label, text in blocks]


@dataclass
class ParallelPlan:
    """What the executor could work out about a directive's parallel dispatch.

    `verdict` is deliberately four-valued, not a bool. "unverified" is the whole
    design: an extractor that silently found no file sets would make this guard
    pass vacuously on every directive it cannot parse, and a guard that degrades
    into always-passing is the failure mode this repo keeps getting bitten by
    (see gate_inactive_reason for the same lesson learned the same way). A
    directive that clearly names N>1 parallel agents whose file sets cannot be
    read with confidence is a RECORDED deviation, not a pass.
    """

    agents: int = 0
    blocks: list = field(default_factory=list)  # [(label, [normalized paths])]
    verdict: str = "none"  # none | disjoint | overlap | unverified
    detail: str = ""

    @property
    def deviates(self) -> bool:
        return self.verdict in ("overlap", "unverified")


def parallel_plan(body: str) -> ParallelPlan:
    """Pure: read a free-form director directive and judge its parallel dispatch.

    Deliberately NOT an NLP parser - a conservative matcher plus an explicit
    unknown state is the right size. It answers three questions in order: does
    this directive dispatch agents in PARALLEL, how MANY does it name, and can
    each one's file set be read. Any doubt at any step lands in "unverified".
    """
    text = body or ""
    if not _PARALLEL_RE.search(text):
        return ParallelPlan()
    # The count is read only from lines that also carry a parallel word, so a
    # stray "3 slices" in the acceptance criteria does not set N.
    named = 0
    for line in text.splitlines():
        if not _PARALLEL_RE.search(line):
            continue
        for m in _COUNT_RE.finditer(line):
            tok = m.group(1).lower()
            named = max(named, int(tok) if tok.isdigit() else _NUM_WORDS.get(tok, 0))

    blocks = [(label, _extract_paths(chunk)) for label, chunk in _agent_blocks(text)]
    agents = max(named, len(blocks))
    if agents < 2:
        # One agent (or none named) cannot collide with itself.
        return ParallelPlan(agents=agents, blocks=blocks)

    if len(blocks) < max(2, named):
        return ParallelPlan(
            agents=agents, blocks=blocks, verdict="unverified",
            detail=(f"could not verify disjointness: the directive names {agents} "
                    f"parallel agents but only {len(blocks)} labelled file set(s) "
                    f"could be read"))
    empty = [label for label, files in blocks if not files]
    if empty:
        return ParallelPlan(
            agents=agents, blocks=blocks, verdict="unverified",
            detail=(f"could not verify disjointness: {', '.join(empty)} name(s) no "
                    f"files, so the sets cannot be compared"))

    clashes = []
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            shared = sorted({b for a in blocks[i][1] for b in blocks[j][1]
                             if _same_file(a, b)})
            if shared:
                clashes.append(f"{blocks[i][0]} and {blocks[j][0]} both name "
                               f"{', '.join(shared)}")
    if clashes:
        return ParallelPlan(agents=agents, blocks=blocks, verdict="overlap",
                            detail="file sets are NOT disjoint: " + "; ".join(clashes))
    return ParallelPlan(agents=agents, blocks=blocks, verdict="disjoint",
                        detail=f"{agents} parallel agents, file sets disjoint")


SERIALIZE_HEADER = "EXECUTOR OVERRIDE - RUN THE NAMED AGENTS SEQUENTIALLY, NOT IN PARALLEL"
UNVERIFIED_HEADER = ("EXECUTOR OVERRIDE - PROVE THE FILE SETS ARE DISJOINT, "
                     "OR RUN THE NAMED AGENTS SEQUENTIALLY")

# Kept, but no longer the mechanism. stamp_deviations below is what GUARANTEES
# the director sees the correction; this ask is only the human-readable half, and
# a model that explains the deviation in its own words is better context than a
# marker alone. What it may not be is the only route - see the stamp's docstring.
_REPORT_IT = (
    "State this deviation in your summary line. The director does not read this file "
    "back, so an unreported correction teaches it nothing and it writes the same "
    "shape again next cycle.\n")


# ---- the mechanical deviation stamp (both guards) ---------------------------
#
# MEASURED 2026-07-27. Both guards below correct a directive, log the correction
# to control/controller.log, and then ASK the executing model to repeat it in its
# summary line. controller.log is not a director input: loop_controller.py:577
# feeds the model-authored claude.done payload forward as `=== LAST claude.done
# ===` and that is all the director ever learns about the cycle. So whether the
# correction reached the component that CAUSED it depended on the model
# volunteering it in prose, and a model that silently complies teaches the
# director nothing - the same failure the comment at the top of this section says
# recording exists to prevent, one layer up.

DEVIATION_STAMP = "executor: DEVIATIONS APPLIED"


def stamp_deviations(summary, deviations) -> str:
    """Pure: the summary the controller reports, with any deviations stamped on.

    A PREFIX, not a suffix, for the same reason the override headers are: the
    director's context dump is long and gets truncated and skimmed from the top,
    and the part after the bar is the model's own prose - the half that may be
    absent, vague, or wrong about what the executor actually did. The guaranteed
    half goes first.

    Byte-identical passthrough when nothing deviated, which is what keeps every
    clean cycle's summary and raw payload exactly as the model wrote them.
    Idempotent because run() must not be able to double-stamp one record.
    """
    s = summary or ""
    if not deviations:
        return s
    if s.startswith(DEVIATION_STAMP):
        return s
    head = f"{DEVIATION_STAMP}: {'; '.join(deviations)}"
    return f"{head} | {s}" if s else head


def deviation_only_raw(stamped: str) -> dict:
    """The raw payload a FAILED cycle hands the controller.

    Empty when nothing deviated, which is byte-for-byte the shape every error
    path had before the stamp existed. When something DID deviate the stamp has
    to live in raw and not only on the record, because the controller reads
    `rec.raw` and nothing else off a DoneRecord (loop_controller.py `done =
    rec.raw` -> `last_done` -> the director's `=== LAST claude.done ===` dump).
    A stamp carried only on DoneRecord.summary would be invisible on exactly the
    branch that has no model prose in it at all.
    """
    return {"summary": stamped} if stamped else {}


def serialize_directive(body: str, plan: ParallelPlan) -> str:
    """Pure: the directive as it must actually be executed.

    Prepended, not appended: on the director path the bridge types only the
    opener and the session READS control/directive.md, so the correction has to
    be the first thing in that file or it is prose buried under the plan it
    contradicts.

    The two deviation kinds get DIFFERENT instructions, deliberately. A proven
    overlap leaves no discretion - those agents demonstrably collide. "Cannot
    verify" is weaker evidence and deserves a weaker remedy: a real directive on
    disk (config.fixed.json) fans out 10 scouts across effect CHANNELS and names
    no files at all, and those ten probably never collide, so forcing them
    sequential would cost 10x wall clock on a directive that was fine. What it
    may NOT do is dispatch unexamined - which is exactly what happened before
    this guard - so the session must first write down each agent's actual file
    set and prove disjointness, and serialize when it cannot. Either way the
    deviation is already recorded in controller.log; the difference is only in
    what the session is told to do next.

    Dependency ORDER is not inferable from prose - R196's prerequisite slice was
    number 2 of 3 - so this pins the listed order and tells the session to
    reorder when it can see the prerequisite. That is a real instruction to a
    capable executor, not a claim this function computed a DAG.
    """
    order = " -> ".join(label for label, _ in plan.blocks) or "the order listed below"
    tail = f"--- ORIGINAL DIRECTIVE FOLLOWS, UNCHANGED ---\n{body}"
    if plan.verdict == "overlap":
        return (
            f"{SERIALIZE_HEADER}\n"
            f"{PARALLEL_MARKER} {plan.detail}\n\n"
            f"This directive dispatches {plan.agents} agents in parallel and their file "
            f"sets COLLIDE, so the executor has refused the parallel shape. Run them ONE "
            f"AT A TIME: {order}. If one slice is a prerequisite the others consume (a "
            f"schema lift, a shared helper, a shared test tail), run that one FIRST and "
            f"say which.\n{_REPORT_IT}\n{tail}")
    return (
        f"{UNVERIFIED_HEADER}\n"
        f"{PARALLEL_MARKER} {plan.detail}\n\n"
        f"This directive dispatches {plan.agents} agents in parallel and the executor "
        f"could not read a file set for each one, so it cannot be dispatched as written. "
        f"BEFORE dispatching anything: write down the exact file set each agent will "
        f"edit, and check them pairwise. Dispatch in parallel ONLY on file sets you have "
        f"shown to be disjoint; run the rest SEQUENTIALLY ({order}), prerequisite slice "
        f"first.\n{_REPORT_IT}\n{tail}")


def enforce_agent_disjointness(cycle, body, *, log=None, awrite=None, ctl=None,
                               note=None):
    """Judge the directive, and on a deviation serialize it AND record it.

    Returns the body to execute - byte-identical to the input whenever the
    directive is already fine, which is what keeps every non-parallel and every
    genuinely-disjoint cycle untouched.

    The record goes to two places because they have two different readers. `log`
    is control/controller.log - the file the operator greps and the judge reads -
    under a marker distinct from winmutex's UNSERIALIZED. `note` is the executor's
    per-cycle deviation list, which stamp_deviations puts on the summary the
    DIRECTOR reads; the director is the component that wrote the bad directive,
    and it never sees controller.log. directive.md is rewritten either way so the
    session that does the work reads the serialized plan, not the parallel one.
    """
    plan = parallel_plan(body)
    if not plan.deviates:
        return body
    if note:
        note(f"{PARALLEL_MARKER} {plan.detail}")
    if log:
        # The marker is constant so one grep finds every deviation; the tail says
        # which remedy was applied, because the two are not the same event.
        remedy = ("serializing them instead of dispatching in parallel"
                  if plan.verdict == "overlap"
                  else "not dispatchable until the file sets are proven disjoint")
        log(f"cycle {cycle}: {PARALLEL_MARKER} {plan.detail} - {plan.agents} named "
            f"parallel agents, {remedy}")
    fixed = serialize_directive(body, plan)
    if awrite and ctl is not None:
        awrite(Path(ctl) / "directive.md", fixed)
    return fixed


# ---- directive grounding guard ----------------------------------------------
#
# MEASURED 2026-07-27, on this loop. director_prompt.md:14-18 makes the director
# open every directive with three grounding fields - GROUNDED-AGAINST,
# NOT-A-DUPLICATE-OF and PREMISE-CHECK - and all three are claims the model makes
# about ITSELF. Nothing read them back: a grep for those three tokens across the
# .py tree returned zero hits. So the director emitted the same already-landed
# unit of work twice (the f1-phase6 inbox apply, landed across four commits that
# were every one an ancestor of HEAD) while self-reporting HEAD=f173ce39 against
# a real HEAD of 9d836162, and the executor typed it verbatim both times.
#
# Two of the three claims are CHECKABLE against the repo, so the executor checks
# them: the HEAD it says it grounded against, and any commit it names that is
# already merged.
#
# The third is checked too, but only for what the director already decided. This
# guard shipped abstaining on PREMISE-CHECK as "free prose with no machine-
# readable referent"; MEASURED 2026-07-27 cycle 13, that cost a whole cycle. The
# directive carried two [UNVERIFIED] premises (staged .githooks changes exist,
# the inbox holds winmutex.py.from-lw), both false on disk - the index was empty
# and winmutex.py was already byte-identical and already SHA-pinned - and the
# cycle was a full no-op, the 6th stale-premise cycle in 7. The referent is the
# TAG, not the prose: director_prompt.md:18 makes the director tag each claim
# [from-digest] or [UNVERIFIED], so an [UNVERIFIED] premise is the director
# stamping its OWN claim an unknown. Reporting that back is propagation, not the
# invention the abstention was guarding against, and it is the same rule this
# file already states four times over (:188, :213, :478, :558): an unknown is
# never a pass. What the executor still does NOT do is judge whether a premise is
# TRUE - that stays the session's job, on disk.

GROUNDING_MARKER = "executor: STALE-GROUNDING"
GROUNDING_HEADER = "EXECUTOR OVERRIDE - RE-GROUND THIS DIRECTIVE AGAINST THE REAL HEAD"
# A separate header because the head is not always the fault. On a premise-only
# finding the prefix's HEAD matched and no named commit had landed, and opening
# that correction with "AGAINST THE REAL HEAD" would send the session re-reading
# a digest that was already right - a guard that misstates what it measured is
# read as noise by the next model that sees it.
PREMISE_HEADER = "EXECUTOR OVERRIDE - VERIFY THE PREMISES THIS DIRECTIVE CALLS UNVERIFIED"
# And a third, for the same reason the second exists. A digest-premise finding
# leaves the HEAD current, no sha landed, and nothing self-declared unknown - the
# only thing measured is that a claim the director sourced from an audit names a
# file that is sitting in the tree. Opening that with either header above would
# state a fault this function did not find.
DIGEST_HEADER = "EXECUTOR OVERRIDE - RE-READ THE FILES THESE FROM-DIGEST PREMISES NAME"

_GROUNDED_HEAD_RE = re.compile(
    r"GROUNDED-AGAINST:.*?\bHEAD\s*=\s*([0-9a-fA-F]{4,40})\b", re.IGNORECASE)

# 7 is git's own default abbreviation length, and the floor is load-bearing: the
# very line that carries the HEAD claim also carries LEDGER-TOP=1074 and a cycle
# number, and handing those to `git rev-parse` invites an ambiguous-prefix answer
# that would manufacture a finding out of a ledger id.
_SHA_TOKEN_RE = re.compile(r"\b[0-9a-fA-F]{7,40}\b")

# A directive is prose written by a model, and each probe is a git subprocess in
# an unattended loop, so a pathological directive naming hundreds of hex-looking
# tokens must not turn one cycle into a process storm. The shas that decide this
# question are in the grounding prefix, which is the first thing scanned.
_MAX_SHA_PROBES = 24

# FIELD-BOUNDED, and that bound is the entire false-positive defence on this
# side. This repo's own LEDGER and ORCHESTRATION_PLAN rows carry [UNVERIFIED] in
# their prose and the director quotes them into directive bodies constantly, so a
# whole-body scan would fire on nearly every cycle and be ignored by the third.
# One line, because that is how director_prompt.md:14-18 emits the field - a
# wrapped premise loses its tail here, which is the safe direction to be wrong.
#
# EVERY match, not the first. The line anchor already defeats mid-sentence
# quoting, but these directives block-quote the PRIOR directive routinely and an
# indented copy of its prefix sits ABOVE the live field - a first-match scan
# reads the quote and goes silent on the real one. That is a false negative, the
# failure this guard exists to close (:478, an unknown is never a pass), so it
# scans them all. The door that re-opens is narrow and cheap: a quoted premise
# fires too, costing one extra bullet, and since a re-quote repeats the SAME
# claim the dedup below collapses the common case to nothing. _MAX_PREMISE_
# FINDINGS bounds the rest.
_PREMISE_LINE_RE = re.compile(r"^[ \t]*PREMISE-CHECK:[ \t]*(.*)$", re.MULTILINE)
_PREMISE_TAG_RE = re.compile(r"\[(UNVERIFIED|from-digest)\]", re.IGNORECASE)

# The sentence split is BACKWARD-ONLY, and that asymmetry is the whole point. The
# tag's side is not fixed - director_prompt.md:18 fixes the vocabulary and nothing
# else - so the live cycle-13 line tags each claim in front and the R200 incident
# line tags it behind. Reading FORWARD, the next tag is a sufficient stop and a
# sentence rule there costs claims outright: "e.g. " / "i.e. " / "no. " end no
# sentence, and a forward cut at the first dot-space leaves "e.g", which is not a
# premise anyone can go and check - the claim then vanishes entirely. Reading
# BACKWARD is where the sentence edge is load-bearing: "[from-digest] A. B
# [UNVERIFIED]" needs it or the claim the director already called VERIFIED gets
# quoted back at the session as work to do. The residual is a truncated QUOTE on
# a trailing tag whose claim carries an abbreviation - text, not a finding, which
# is the survivable direction.
_PREMISE_SPLIT_RE = re.compile(r"[.;]\s+")
# Text that OPENS with a sentence terminator means the tag before it CLOSED a
# sentence, so that tag trails its claim. This is the only forward/backward
# discriminator that never has to guess where a sentence ends.
_PREMISE_CLOSES_RE = re.compile(r"^[ \t]*[.;]")
# The prompt's own placeholder, which any directive ABOUT this loop quotes
# verbatim off director_prompt.md:18. Rejected for what it IS - angle-bracketed
# template text - and not by length, because a length floor silently drops real
# terse claims like "[UNVERIFIED] CI" and that is the same dropped-claim failure
# by another route.
_PREMISE_PLACEHOLDER_RE = re.compile(r"^<[^<>]*>$")
_PREMISE_TRIM = " \t.;,:<>"

# Same unattended-loop reason as _MAX_SHA_PROBES, one layer over: every finding
# becomes a line PREPENDED to the directive the session reads, so a pathological
# premise line must not bury the directive under its own correction.
_MAX_PREMISE_FINDINGS = 8

# The OTHER tag. MEASURED 2026-07-27 cycle 15: _field_claims skips every
# [from-digest] claim outright, which is exactly right as an R208 matter - the
# director stamped those KNOWN and the executor does not judge whether a semantic
# claim is true. Cycle 15's entire directive then rested on one of them, verbatim
# off control/directive.md:3:
#
#   PREMISE-CHECK: [from-digest] LAST AUDIT reports VERDICT: REGRESS for
#   corrupted uses refs in docs-guards.yml.
#
# and it was false. `grep -rn "uses:" .github/workflows/` returns 10 refs, every
# one a real version tag; zero match the corrupted `@agents\...\test_x.py` shape
# the digest described; `gh run list` shows docs-guards run 30289333992 SUCCESS
# at HEAD 98f29111. The tag bought that claim a free pass through the guard and
# it burned the cycle.
#
# What changed is NOT the R208 abstention, which stands: the executor still has
# no standing to say whether a premise holds, and this raises no verdict on one.
# What it raises is the single mechanical fact a digest claim can carry - the
# claim NAMED A FILE and the file is right there - so the finding is an
# instruction to go and read it before acting, and never an assertion that the
# claim is wrong. A digest is model-authored prose ABOUT the tree, written at
# some earlier moment; the tree is on disk and costs one read.
#
# EXISTENCE is the entire false-positive defence, and it has to be, because most
# digest claims are perfectly legitimate. "13061 tests pass", "the loop is armed"
# and "LAST AUDIT reports VERDICT: PASS" name no file and raise nothing. Silence
# is the default here in a way it deliberately is not for [UNVERIFIED]: a guard
# that fires on every digest-sourced claim is a guard the session skims, which is
# how the premise correction above stops being read at all.
_PATH_SUFFIXES = (".py", ".md", ".yml", ".yaml", ".json", ".js", ".css", ".ps1")
# SHAPE first, lookup second. A claim is mostly ordinary words and the lookup is
# a filesystem or index probe, so a separator or a source suffix is what earns a
# token the probe at all - the same reason _SHA_TOKEN_RE has a 7-char floor.
_PATH_SHAPE_HINT = "/"
# Asymmetric, and that asymmetry is load-bearing. A LEADING dot is part of the
# path in this repo (.github/, .githooks/) so it is never trimmed off the front;
# a TRAILING one is sentence punctuation, because no file here ends in a dot.
# The rest is how directives actually spell a path: backticks, quotes, parens.
_PATH_LEAD_TRIM = "`'\"([{<"
_PATH_TRAIL_TRIM = "`'\")]}>.,;:!?"
# Bounded for the same reason as _MAX_SHA_PROBES, and it bites harder here: the
# basename branch of the resolver is a git call, so a pathological premise line
# listing dozens of file-shaped tokens must not turn one cycle into a process
# storm. Budget is per directive, not per claim.
_MAX_PATH_PROBES = 16


@dataclass
class GroundingFinding:
    """One checkable grounding claim that did not survive the check."""

    kind: str  # stale-head | already-landed | unverified | unverified-premise | digest-premise
    token: str
    detail: str
    # Appended at the END with a default because every construction of this class
    # is POSITIONAL: a field inserted mid-class breaks all of them at once (the
    # item-216 shape). Only digest-premise fills it. The paths ride the finding
    # rather than being re-derived in the override block, because re-deriving
    # them would mean parsing the prose this same function just wrote.
    paths: tuple = ()


def _field_claims(field, *, tag="unverified") -> list:
    """The claims carrying one TAG in ONE PREMISE-CHECK field.

    Forward from the tag to the next tag, and backward only when the tag closed a
    sentence or the field ended - one rule for both tag positions, and the only
    one of the two that needs to know where a sentence ends is the fallback.

    A claim must carry a letter. That rejects the leftover punctuation a
    malformed field produces without rejecting a real short claim.

    `tag` is a parameter rather than a second copy of this function because the
    splitting is the hard part and it is identical for both vocabularies - the
    six abbreviation cases, the trailing-tag fallback and the placeholder reject
    are all pinned by tests that only ever exercised [UNVERIFIED], and a
    duplicate would drift out from under every one of them.
    """
    if _PREMISE_PLACEHOLDER_RE.match(field.strip()):
        return []
    tags = list(_PREMISE_TAG_RE.finditer(field))
    out = []
    for i, hit in enumerate(tags):
        if hit.group(1).lower() != tag:
            continue
        end = tags[i + 1].start() if i + 1 < len(tags) else len(field)
        ahead = field[hit.end():end]
        claim = "" if _PREMISE_CLOSES_RE.match(ahead) else ahead.strip(_PREMISE_TRIM)
        if not claim:
            behind = field[tags[i - 1].end() if i else 0:hit.start()]
            sentences = [s for s in _PREMISE_SPLIT_RE.split(behind) if s.strip(_PREMISE_TRIM)]
            claim = sentences[-1].strip(_PREMISE_TRIM) if sentences else ""
        if any(c.isalpha() for c in claim):
            out.append(claim)
    return out


def _premise_claims(text, tag):
    """Every claim carrying TAG across every PREMISE-CHECK field, lazily.

    Deduplicated case-insensitively and in first-seen order: the directive is
    read top-down by a session, and the same premise reported twice is noise it
    learns to skim - which is how a correction stops being read at all.

    A generator rather than a capped list because the two consumers cap at
    DIFFERENT points. The unverified side is a finding per claim, so the cap is
    the claim count; the digest side filters on whether a claim names a real
    path, so capping claims first would let eight fileless claims crowd out the
    one that actually points at something to read.
    """
    seen = set()
    for m in _PREMISE_LINE_RE.finditer(text or ""):
        for claim in _field_claims(m.group(1), tag=tag):
            if claim.lower() in seen:
                continue
            seen.add(claim.lower())
            yield claim


def _unverified_premises(text) -> list:
    """The claims the director tagged [UNVERIFIED] in its own PREMISE-CHECK field."""
    out = []
    for claim in _premise_claims(text, "unverified"):
        out.append(claim)
        if len(out) >= _MAX_PREMISE_FINDINGS:
            break
    return out


def _claim_paths(claim, resolve_path, budget):
    """The repo paths ONE claim names that resolve, plus the probe budget left.

    Deduped by token before the probe and by answer after it: a claim naming a
    file twice, or naming it once by path and once by basename, is one file to
    re-read and one bullet.
    """
    out, seen = [], set()
    for raw in claim.split():
        tok = raw.lstrip(_PATH_LEAD_TRIM).rstrip(_PATH_TRAIL_TRIM)
        if not tok or tok.lower() in seen:
            continue
        if _PATH_SHAPE_HINT not in tok and not tok.lower().endswith(_PATH_SUFFIXES):
            continue
        seen.add(tok.lower())
        if budget <= 0:
            break
        budget -= 1
        found = (resolve_path(tok) or "").strip()
        if found and found not in out:
            out.append(found)
    return tuple(out), budget


def _digest_premises(text, resolve_path) -> list:
    """(claim, paths) for every [from-digest] claim that names a path on disk.

    Returns nothing at all without a resolver, and that is the only shape a pure
    function can take here - it may not call the filesystem itself. The hole that
    leaves (a caller who forgets, and a guard that silently never fires) is
    closed by a test on the production caller, not by a default in here, because
    a default that reaches the disk would make this function untestable against
    anything but whatever tree the machine happened to have.
    """
    if not resolve_path:
        return []
    out, budget = [], _MAX_PATH_PROBES
    for claim in _premise_claims(text, "from-digest"):
        paths, budget = _claim_paths(claim, resolve_path, budget)
        if paths:
            out.append((claim, paths))
            if len(out) >= _MAX_PREMISE_FINDINGS:
                break
        if budget <= 0:
            break
    return out


def grounding_findings(body, *, head, resolve, is_ancestor, resolve_path=None) -> list:
    """Pure: judge a directive's SELF-REPORTED grounding against the repository.

    The lookups are injected rather than called directly so this stays a pure
    function of its inputs - the ancestry question is the whole check, and a
    version that shells out could only be tested against whatever history the
    machine happened to have.

    RESOLUTION is the entire false-positive defence on the already-landed side.
    The hex shape alone matches far too much - a build number, a truncated
    digest, and English words spelled out of abcdef all fit it - so a token is
    only ever a finding when git says it is a commit AND says that commit is
    already merged. A sha that resolves but is not an ancestor (a sibling repo's
    head, a branch tip) is legitimate context and is left alone.

    The [UNVERIFIED] premise findings ask the repository nothing at all - the
    director already stamped those claims unknown - so they need no lookup and
    cost no probe, and they are raised even when HEAD is unreadable.

    The [from-digest] premise findings ask it exactly ONE thing, through
    resolve_path: does the file this claim names exist. They still raise no
    verdict on the claim - see the block above _PATH_SUFFIXES for the cycle-15
    measurement - only the pointer at what to re-read. With no resolver injected
    they are silent, which is what keeps this function pure.
    """
    text = body or ""
    out = []
    m = _GROUNDED_HEAD_RE.search(text)
    claimed = m.group(1).lower() if m else ""
    real = (head or "").strip().lower()

    if claimed and not real:
        # The directive asserted something checkable and the check could not be
        # run. Reporting nothing here is the always-passing degradation this file
        # keeps re-learning (see ParallelPlan "unverified", gate_inactive_reason):
        # an unreadable HEAD is an unknown, never a pass.
        out.append(GroundingFinding(
            "unverified", claimed,
            f"the directive claims GROUNDED-AGAINST HEAD={claimed} and the real HEAD "
            f"could not be read, so the claim is unverified"))
    elif claimed and not real.startswith(claimed):
        out.append(GroundingFinding(
            "stale-head", claimed,
            f"the directive claims GROUNDED-AGAINST HEAD={claimed} but the real HEAD "
            f"is {real[:8]}, so it was written against a stale digest"))

    # After the HEAD claim, so an unreadable-HEAD run still reports that first:
    # the head is the claim the session must resolve before anything else.
    for claim in _unverified_premises(text):
        # The detail opens with the kind because GROUNDING_MARKER is one fixed
        # grep token and it says STALE - true of the head findings, false here.
        # The operator reading controller.log gets no other discriminator, so it
        # has to be the first thing after the marker.
        out.append(GroundingFinding(
            "unverified-premise", claim,
            f"UNVERIFIED-PREMISE \"{claim}\" - the directive tagged this claim [UNVERIFIED] "
            f"itself, so it is not a fact the work below may assume"))

    # After the self-declared unknowns, because an unknown is the stronger of the
    # two: it has to be PROVEN before the work runs, where this one has to be
    # RE-READ. Same prefix discipline on the detail - one grep marker, so the
    # kind is the first thing an operator sees after it.
    for claim, paths in _digest_premises(text, resolve_path):
        named = ", ".join(paths)
        out.append(GroundingFinding(
            "digest-premise", claim,
            f"FROM-DIGEST-PREMISE \"{claim}\" - the directive sourced this claim from an "
            f"audit digest rather than from the repository, and it names {named}. Re-read "
            f"that file before acting on the claim",
            paths))

    if not real:
        return out

    seen = set()
    for tok_m in _SHA_TOKEN_RE.finditer(text):
        tok = tok_m.group(0).lower()
        # The claimed HEAD is a grounding assertion, not proposed work, and the
        # stale-head finding above already names it - counting it again would
        # report one fault as two and send the session looking for a second one.
        if tok == claimed or tok in seen:
            continue
        seen.add(tok)
        if len(seen) > _MAX_SHA_PROBES:
            break
        full = (resolve(tok) or "").strip().lower()
        if not full or not is_ancestor(full, real):
            continue
        out.append(GroundingFinding(
            "already-landed", tok,
            f"{tok} is already an ancestor of HEAD, so the work the directive names "
            f"around it is already in the history"))
    return out


def reground_directive(body, findings) -> str:
    """Pure: the directive with the executor's grounding correction on top.

    Prepended for the same reason the serialize override is: on the director path
    the bridge types only the opener and the session READS control/directive.md,
    so a correction anywhere but the first line is prose buried under the plan it
    contradicts.

    ADVISORY, not fatal. Every input here is a heuristic string match over model
    prose, and a directive that cites a landed commit as CONTEXT looks identical
    to one that re-issues it. So this states what the repo actually says and hands
    the judgement to the session, which can read both. Aborting the cycle on a
    guess would trade a duplicated unit of work for a dead unattended run.
    """
    # Exact kind matches, never a prefix or a substring test: "unverified-premise"
    # sharing six letters with "unverified" is the whole trap here, and bucketing
    # it as stale would print "the grounding prefix below is stale" over a HEAD
    # the same function just measured as current.
    stale = [f for f in findings if f.kind in ("stale-head", "unverified")]
    landed = [f.token for f in findings if f.kind == "already-landed"]
    premises = [f.token for f in findings if f.kind == "unverified-premise"]
    digest = [f for f in findings if f.kind == "digest-premise"]
    bullets = "\n".join(f"- {f.detail}" for f in findings)
    tail = f"--- ORIGINAL DIRECTIVE FOLLOWS, UNCHANGED ---\n{body}"
    steps = ["Re-read the real HEAD and the newest docs/LEDGER.md rows yourself before "
             "you act on anything below."]
    if stale:
        steps.append("The grounding prefix below is stale, so every 'not yet on disk' "
                     "claim in it was made against a different tree - re-check each one "
                     "on disk, not against the prefix.")
    if landed:
        steps.append(f"These commits are ALREADY MERGED: {', '.join(landed)}. If the unit "
                     f"of work below is the work they carry, do NOT re-do it - pick the "
                     f"next NON-duplicate unit and say which.")
    if premises:
        steps.append("The directive declared these premises UNKNOWN itself: "
                     + "; ".join(f'"{p}"' for p in premises)
                     + ". Verify EACH one on disk - the file, the index, the test - "
                     "before you edit anything. If they do not hold, the unit of work "
                     "below is a no-op: do NOT run it, pick the next NON-duplicate unit "
                     "and say which.")
    if digest:
        # The paths, not the claims, because the paths ARE the instruction. This
        # step may not say the claim is wrong - the executor never opened the
        # file - so it says where the file is and what a digest is worth.
        named = []
        for f in digest:
            named.extend(p for p in f.paths if p not in named)
        steps.append("These premises came from an audit DIGEST rather than from the "
                     "repository, and each one names a file that is in this tree: "
                     + ", ".join(named)
                     + ". Re-read those files yourself before you act on the claims. A "
                     "digest records what an audit SAID at some earlier moment, never what "
                     "the tree holds now, and re-reading costs one Read. If a file does not "
                     "match its claim, the unit of work below is a no-op: do NOT run it, "
                     "pick the next NON-duplicate unit and say which.")
    # Header and lead follow what actually fired. A premise-only finding leaves the
    # head claim intact and correct, and a correction that opens by contradicting a
    # measurement it did not make teaches the session to discount the next one.
    lead = ("The grounding prefix in this directive is SELF-REPORTED by the director and "
            "the executor checked it against the repository. It does not hold:")
    header = GROUNDING_HEADER
    if premises and not stale and not landed:
        lead = ("The grounding prefix in this directive is SELF-REPORTED by the director, "
                "and it tagged its own premises [UNVERIFIED]. A self-declared unknown is "
                "not a fact:")
        header = PREMISE_HEADER
    elif digest and not stale and not landed:
        # Weaker than the two above ON PURPOSE, and the wording is the whole
        # finding: nothing here has been checked against the repository except
        # that the named file exists. The session is being sent to read, not
        # told it was lied to.
        lead = ("The PREMISE-CHECK in this directive is SELF-REPORTED by the director, and "
                "it says these claims came from an audit DIGEST. A digest is model-authored "
                "prose ABOUT the repository, not the repository - and each claim below "
                "names a file that is sitting in this tree:")
        header = DIGEST_HEADER
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    return (
        f"{header}\n"
        f"{GROUNDING_MARKER} {'; '.join(f.detail for f in findings)}\n\n"
        f"{lead}\n"
        f"{bullets}\n\n"
        f"{numbered}\n{_REPORT_IT}\n{tail}")


def _git_out(repo_root, *args) -> str:
    """stdout of a bounded git read, or "" on any failure.

    Bounded and swallowing for the same reason the controller's own git helper
    is: these run inside an unattended loop with no deadline around them, so a
    wedged git (a stale index.lock, a hung hook) must not strand the run. An
    empty answer lands in the unverified branch above, which is RECORDED rather
    than quietly passed.
    """
    try:
        r = subprocess.run(["git", "-C", str(repo_root), *args],
                           capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return ""
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def _git_head(repo_root) -> str:
    return _git_out(repo_root, "rev-parse", "HEAD").lower()


def _git_resolve(repo_root, token) -> str:
    """The full sha a token names, or "" when it is not a commit.

    `^{commit}` is not decoration: without it a tree, a blob or a branch whose
    name happens to be hex resolves too, and a blob id counted as a commit would
    then be asked an ancestry question it cannot answer.
    """
    return _git_out(repo_root, "rev-parse", "--verify", "-q",
                    f"{token}^{{commit}}").lower()


def _git_is_ancestor(repo_root, a, b) -> bool:
    """True iff commit a is an ancestor of (or identical to) commit b.

    A direct call rather than _git_out because the answer is the EXIT CODE and
    there is no stdout to read.
    """
    if not a or not b:
        return False
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", a, b],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _repo_path(repo_root, token) -> str:
    """The repo-relative path a premise token names, or "" when it names none.

    Two questions, in order. The first is the literal one - is this token a file
    under the repo root - and it answers the fully-spelled path a directive body
    usually carries.

    The second is the BASENAME, and it is not a convenience: the measured
    cycle-15 field says `docs-guards.yml` while the file is
    .github/workflows/docs-guards.yml, so a root-relative-only probe would have
    gone silent on the one incident this whole finding exists to close. That
    question goes to the INDEX rather than to a filesystem walk - one bounded git
    call, tracked files only, which also means an untracked scratch file with a
    colliding name can never manufacture a finding.

    A directory is not an answer. The finding is a pointer at something to READ,
    and "re-read docs/" is not an instruction anyone can act on.
    """
    if not token:
        return ""
    try:
        if (Path(repo_root) / token).is_file():
            return token.replace("\\", "/")
    except OSError:
        return ""
    if "/" in token or "\\" in token:
        return ""
    for line in _git_out(repo_root, "ls-files", "--", token, f"*/{token}").splitlines():
        line = line.strip()
        if line and line.rsplit("/", 1)[-1].lower() == token.lower():
            return line
    return ""


def enforce_directive_grounding(cycle, body, *, log=None, awrite=None, ctl=None,
                                repo_root=".", note=None):
    """Check the directive's grounding, and on a finding annotate it AND record it.

    Sibling of enforce_agent_disjointness and deliberately the same shape: returns
    the body to execute, byte-identical to the input whenever the grounding holds,
    logs to the controller's own log seam under its own grep marker, and rewrites
    control/directive.md so the session that does the work reads the correction.

    Recording is half the point here too, and this guard is where the two readers
    diverge hardest. controller.log serves the operator and the auditor; `note`
    serves the DIRECTOR, which is the component that got this wrong - it emitted
    the same landed unit twice - and which reads only the claude.done payload the
    stamp lands on.
    """
    findings = grounding_findings(
        body,
        head=_git_head(repo_root),
        resolve=lambda tok: _git_resolve(repo_root, tok),
        is_ancestor=lambda a, b: _git_is_ancestor(repo_root, a, b),
        # Injected HERE and nowhere else. grounding_findings has no default for
        # this and must not grow one - a filesystem call inside a pure function
        # would make it answer differently on every machine that ran the tests.
        # This is the only production caller, so this line is what decides
        # whether the digest-premise finding can fire at all.
        resolve_path=lambda tok: _repo_path(repo_root, tok))
    if not findings:
        return body
    detail = "; ".join(f.detail for f in findings)
    if note:
        note(f"{GROUNDING_MARKER} {detail}")
    if log:
        log(f"cycle {cycle}: {GROUNDING_MARKER} " + detail)
    fixed = reground_directive(body, findings)
    if awrite and ctl is not None:
        awrite(Path(ctl) / "directive.md", fixed)
    return fixed


class AhkExecutor:
    """The legacy GUI channel: write gemini.ready, wait for AHK to type it, wait
    for the done sentinel. Verbatim lift - see the module docstring.

    Machine-wide singleton by construction (it targets a window title), so this
    channel can never satisfy the concurrent-run requirement. That is the whole
    reason the SDK channel exists.
    """

    name = "ahk"

    def __init__(self, cfg, ctl, *, log, stop, awrite, wait_for, wait_gone, rjson,
                 stall_action, stall_recovery_directive):
        self.cfg = cfg
        self.ctl = ctl
        self.log = log
        self.stop = stop
        self.awrite = awrite
        self.wait_for = wait_for
        self.wait_gone = wait_gone
        self.rjson = rjson
        self.stall_action = stall_action
        self.stall_recovery_directive = stall_recovery_directive
        self.deviations: list = []

    def run(self, cycle: int, body: str, src: str) -> DoneRecord:
        ctl = self.ctl
        # Per-CYCLE, not per-executor: the controller builds one executor and
        # calls run() once per cycle for the life of the run, so without this
        # reset cycle 1's deviation would stamp every clean cycle after it and
        # teach the director a fault that is not in the directive it just wrote.
        self.deviations = []
        # Grounding first: it judges the directive AS AUTHORED, and running it
        # after the disjointness rewrite would make it read that guard's own
        # header as part of the director's text.
        body = enforce_directive_grounding(cycle, body, log=self.log,
                                           awrite=self.awrite, ctl=ctl,
                                           repo_root=self.cfg.get("repo_root", "."),
                                           note=self.deviations.append)
        # No-op (returns the same string, writes nothing) unless the directive
        # dispatches parallel agents whose file sets are not provably disjoint.
        body = enforce_agent_disjointness(cycle, body, log=self.log,
                                          awrite=self.awrite, ctl=ctl,
                                          note=self.deviations.append)
        self.awrite(ctl / "gemini.ready",
                    directive_payload(cycle, body, src,
                                      self.cfg.get("clear_each_cycle", True)))
        self.log(f"cycle {cycle}: directive written ({len(body)} chars), gemini.ready set")

        # AHK/stub deletes gemini.ready after typing; its disappearance IS the typed signal
        if not self.wait_gone(ctl / "gemini.ready", time.time() + 120):
            self.stop(f"cycle {cycle}: AHK never typed (gemini.ready not consumed in 120s)")
        deadline = time.time() + self.cfg["cycle_deadline_sec"]
        self.log(f"cycle {cycle}: typed (ready consumed); deadline in {self.cfg['cycle_deadline_sec']}s")

        # WP-I3: one-shot stall recovery before a hard STOP. On the FIRST cycle-deadline
        # breach, inject a /diagnose recovery directive into the existing (stalled) session
        # and extend the deadline ONCE (decision = stall_action, pure + tested); hard-STOP
        # only on a SECOND breach. The no-progress and AHK-never-typed guards remain the
        # runaway backstops so a truly wedged run still stops cleanly after exactly one
        # recovery attempt.
        breach = 0
        while not self.wait_for(ctl / "claude.done", deadline, watch_bridge=True):
            breach += 1
            if self.stall_action(breach) == "stop":
                self.stop(f"cycle {cycle}: claude.done not seen after stall recovery (hard hang)")
            self.log(f"cycle {cycle}: deadline breach {breach} - injecting stall recovery, extending once")
            self.awrite(ctl / "gemini.ready", self.stall_recovery_directive(cycle))
            if not self.wait_gone(ctl / "gemini.ready", time.time() + 120):
                self.stop(f"cycle {cycle}: AHK never typed the stall-recovery directive")
            deadline = time.time() + self.cfg["cycle_deadline_sec"]

        done = self.rjson(ctl / "claude.done", {})
        (ctl / "claude.done").unlink(missing_ok=True)
        # Stamped into raw as well as onto the record: raw IS the director's only
        # view of this cycle, so a stamp that lived only on the record would be
        # invisible to the component whose directive was corrected.
        #
        # Written back ONLY when something deviated, because on this channel the
        # payload comes from done_sentinel.py, which has no `summary` key at all -
        # so an unconditional write would add `"summary": ""` to the director's
        # context on every clean cycle, which is a shape change to the seam this
        # guard exists to keep honest rather than a record of anything.
        stamped = stamp_deviations(str(done.get("summary") or ""), self.deviations)
        if self.deviations:
            done["summary"] = stamped
        return DoneRecord(
            cycle=cycle,
            sha=done.get("sha") or "",
            tests_pass=done.get("tests_pass", "?"),
            regressions=bool(done.get("regressions")),
            raw=done,
            summary=stamped,
        )


DONE_SCHEMA = {
    "type": "object",
    "properties": {
        "sha": {"type": "string"},
        "tests_pass": {"type": "string"},
        "regressions": {"type": "boolean"},
        "summary": {"type": "string"},
    },
    "required": ["sha", "tests_pass", "regressions", "summary"],
}

FINAL_STEP = (
    "FINAL STEP: do NOT run ops/loop/done_sentinel.py. Instead return the JSON object "
    "required by the output schema: sha (the live git HEAD after your commit), "
    "tests_pass (the count you observed THIS run, as a string), regressions (true only "
    "if you could not reach green), summary (one line)."
)

def canonical_interpreter() -> str:
    """Absolute path to the project interpreter, RESOLVED, never baked in.

    The pin has to stay ABSOLUTE - a bare ``py`` resolves to the dep-less
    pymanager runtime and zeroes the suite (tests/test_bare_py_ban.py). But the
    account-specific prefix must come from the environment, because a command
    naming one account's home is a command that silently does not run under
    another, and a step that does not run reports nothing.

    Falls back to the interpreter actually running this module, which is the
    correct answer on any machine where the Python314 layout is absent.
    """
    local = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    candidate = Path(local) / "Programs" / "Python" / "Python314" / "python.exe"
    return str(candidate if candidate.exists() else Path(sys.executable))


# Byte-verbatim as director_prompt.md spelled it before the placeholder landed,
# including the double space after "run", except that the interpreter is now
# RESOLVED rather than hardcoded. This is RC's interpreter, NOT LW's - the two
# repos legitimately differ here, and copying LW's string would break the ahk
# rollback path in a way only a live dry cycle catches.
AHK_FINAL_STEP = (
    f'FINAL STEP: run  "{canonical_interpreter()}" '
    "ops/loop/done_sentinel.py --tests <PASS_COUNT> --regressions <0_or_1>"
)


def final_step_instruction(channel) -> str:
    """THE single source of truth for how a cycle signals completion.

    The two channels need OPPOSITE completion steps and both used to be written
    down independently - director_prompt.md hardcoded the sentinel command while
    sdk_prompt appended "do NOT run done_sentinel.py". Appending last probably
    won, but probably is not a contract, and the director path had never been
    exercised on the sdk channel: every sdk cycle in either repo so far used
    fixed_directive or cycle_command, both of which bypass the director.

    ahk: the controller blocks on control/claude.done, so the sentinel command
    IS the completion signal and the directive must carry it.
    sdk: `claude -p` returns a schema-validated structured_output, so the
    sentinel is redundant and running it would write a file nothing reads.

    Unknown channels raise, matching build().
    """
    ch = str(channel or "ahk").strip().lower()
    if ch == "ahk":
        return AHK_FINAL_STEP
    if ch == "sdk":
        return FINAL_STEP
    raise ValueError(
        f"unknown executor channel {ch!r} (known: 'ahk', 'sdk')")


def sdk_prompt(cycle: int, body: str, src: str) -> str:
    """The prompt piped to `claude -p` on stdin.

    Deliberately NOT directive_payload(): that one carries a CYCLE header the AHK
    bridge skips and a leading `/clear`, both of which are artifacts of typing
    into a live window. A `-p` call is already a fresh process, so `/clear` is
    meaningless and the header would just be prose in the prompt.
    """
    head = body if src in ("cycle_command", "fixed") else DIRECTIVE_OPENER
    # Via final_step_instruction, never FINAL_STEP directly: the directive body
    # and the appended instruction must come from one place or they drift apart
    # again, which is the defect this whole seam exists to close.
    return f"{head}\n\n{final_step_instruction('sdk')}\n"


# ---- child-process teardown (platform seam) ---------------------------------
#
# MEASURED 2026-07-27 on the nightly ubuntu run. The sdk timeout path was
# `taskkill /F /T` and nothing else. On POSIX taskkill is a missing executable,
# so the OSError was swallowed, the child outlived the kill, and the
# `proc.wait(timeout=30)` that followed re-raised TimeoutExpired straight out of
# the handler - against an INJECTED deadline of 2s, which is why the failure
# reads "timed out after 30 seconds" and why it ESCAPED run() instead of being
# recorded. A loop executor that cannot kill a hung child on Linux is a real
# defect, not a test artifact.

# The reap is bounded and its expiry is deliberately NOT fatal: by the time it
# runs the cycle's verdict is already decided, and letting it raise is exactly
# what turned one wedged child into a dead unattended run.
_REAP_TIMEOUT_SEC = 30

# Resolved at import, not at the call site: SIGKILL does not exist on Windows,
# so naming it inside the POSIX branch would make that branch unreachable - and
# so unpinnable - from the one machine this loop actually runs on. The point of
# the seam is that the platform NOT under my feet still gets a test.
_KILL_SIG = getattr(signal, "SIGKILL", signal.SIGTERM)


def _spawn_group_kwargs() -> dict:
    """The POSIX-only Popen kwargs the teardown below depends on.

    start_new_session is load-bearing rather than tidy: it gives the child its
    own process group, and WITHOUT it os.getpgid(child) answers with the
    CONTROLLER's group - so the killpg below would kill the loop that is trying
    to reap, a self-kill dressed as a teardown. It is POSIX-only by definition
    (Windows _execute_child takes it as `unused_start_new_session`), so passing
    it on nt would be a silent no-op that reads as protection.

    CREATE_NO_WINDOW is deliberately NOT returned from here, though it is the
    mirror-image platform kwarg. tests/test_no_console_flash_scheduled_tools.py
    resolves `creationflags` by AST at every subprocess spawn site, and a
    `**dict` argument is opaque to that scan: folding the flag in here left this
    module's only spawn site unprovable and made the console-flash guard report
    a protection it could no longer see. A console flashing on the operator's
    desktop is a recurring real defect here, so the flag stays written out
    LITERALLY at the Popen call. `creationflags=0` is legal on POSIX
    (subprocess.py:867 raises only when it is non-zero) and the getattr default
    IS 0 there, so the literal costs that platform nothing.
    """
    if os.name == "nt":
        return {}
    return {"start_new_session": True}


def _kill_process_tree(proc) -> None:
    """Kill a wedged executor child and its descendants. Never raises.

    A `claude -p` that wedged has child tool processes, so killing the pid alone
    orphans them still holding the pipes this cycle is blocked on - which is why
    both branches target the TREE and proc.kill() is only the fallback for when
    the tree kill could not be attempted.

    NEVER Stop-Process (CLAUDE.md hard rule): on Windows the tree kill is
    `taskkill /F /T`, byte-unchanged from the path that already works. On POSIX
    it is os.killpg against the child's own group, guarded by a comparison with
    the loop's own pgid for the reason _spawn_group_kwargs spells out.

    Split out as a seam for the same reason _is_on_disk_executable is: the
    branch that only ever runs on the other platform is pinned by monkeypatch
    from Windows rather than left for a CI run to discover - which is precisely
    how a Windows-only kill path shipped as the whole teardown.
    """
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=_REAP_TIMEOUT_SEC,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            pgid = os.getpgid(proc.pid)
            if pgid != os.getpgid(0):
                os.killpg(pgid, _KILL_SIG)
                return
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


class SdkExecutor:
    """Headless `claude -p` channel. No window, no window title, no typing.

    This is the channel that makes concurrent LW+RC runs possible: it holds no
    machine-wide resource, so two loops collide only on things the slot governor
    and the named mutexes already bound.

    It also returns a receipt the AHK channel never could - total_cost_usd and a
    schema-validated structured_output - which is what retires the transcript
    meter and done_sentinel.py once this channel is the default.
    """

    name = "sdk"

    def __init__(self, cfg, ctl, *, log, stop, awrite, **_ignored):
        self.cfg = cfg
        self.ctl = ctl
        self.log = log
        self.stop = stop
        self.awrite = awrite
        self.session_id: str | None = None
        self.deviations: list = []

    def _argv_prefix(self) -> list:
        """`executor_cmd` may be a string or an argv list (tests inject a shim)."""
        cmd = self.cfg.get("executor_cmd")
        if isinstance(cmd, list):
            return list(cmd)
        if isinstance(cmd, str) and cmd:
            return [cmd]
        import shutil
        return [shutil.which("claude.cmd") or shutil.which("claude") or "claude"]

    def build_argv(self, cycle: int) -> list:
        import json as _json
        argv = self._argv_prefix() + [
            "-p",
            "--output-format", "json",
            "--input-format", "text",
            "--permission-mode", self.cfg.get("permission_mode", "bypassPermissions"),
            "--json-schema", _json.dumps(DONE_SCHEMA),
            "--add-dir", str(self.cfg.get("repo_root", ".")),
        ]
        # RM-137: push RC's standing rules into every subagent this cycle spawns.
        # Config-driven on purpose - if a CLI upgrade ever rejects the flag, the
        # kill is deleting one key, not editing code mid-incident.
        subagent_prompt = str(self.cfg.get("subagent_prompt", "") or "").strip()
        if subagent_prompt:
            argv += ["--append-subagent-system-prompt", subagent_prompt]
        model = self.cfg.get("executor_model")
        if model:
            argv += ["--model", str(model)]
        budget = self.cfg.get("cycle_budget_usd")
        if budget:
            argv += ["--max-budget-usd", str(budget)]
        # clear_each_cycle True reproduces the AHK channel's /clear exactly: a
        # brand new session per cycle. False keeps continuity via --resume, which
        # is cheaper (no cold re-read of CLAUDE.md + living docs each cycle).
        if self.cfg.get("clear_each_cycle", True) or not self.session_id:
            import uuid
            argv += ["--session-id", str(uuid.uuid4())]
        else:
            argv += ["--resume", self.session_id]
        return argv

    def run(self, cycle: int, body: str, src: str) -> DoneRecord:
        import json as _json

        # Per-CYCLE, not per-executor: this object outlives the cycle (it even
        # carries session_id across them), so without the reset cycle 1's
        # deviation would stamp every clean cycle after it and teach the director
        # a fault that is not in the directive it just wrote.
        self.deviations = []
        # Same guards as the ahk channel, in the same order, and they matter MORE
        # here: a `-p` run is unattended, so nobody is watching to refuse a
        # colliding directive or to notice one that re-issues landed work.
        body = enforce_directive_grounding(cycle, body, log=self.log,
                                           awrite=self.awrite, ctl=self.ctl,
                                           repo_root=self.cfg.get("repo_root", "."),
                                           note=self.deviations.append)
        body = enforce_agent_disjointness(cycle, body, log=self.log,
                                          awrite=self.awrite, ctl=self.ctl,
                                          note=self.deviations.append)
        argv = self.build_argv(cycle)
        prompt = sdk_prompt(cycle, body, src)
        timeout = float(self.cfg.get("cycle_deadline_sec", 5400))
        self.log(f"cycle {cycle}: sdk executor starting ({len(body)} chars, timeout {timeout:.0f}s)")

        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", cwd=str(self.cfg.get("repo_root", ".")),
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                **_spawn_group_kwargs())
        try:
            out, err = proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            self.log(f"cycle {cycle}: sdk timeout after {timeout:.0f}s - killing the child tree")
            _kill_process_tree(proc)
            try:
                proc.wait(timeout=_REAP_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                # Reaping is a courtesy; the cycle's verdict is already decided.
                # Letting this escape IS the measured defect - it converted a
                # recorded failed cycle into an exception that took the run down.
                self.log(f"cycle {cycle}: sdk child survived the tree kill - not reaped")
            # Every failure path stamps too, and into raw as well as onto the
            # record. A cycle that deviated and THEN failed is the case where the
            # director most needs to know its directive was corrected: it is about
            # to be handed a dead cycle with no model prose in it at all, and
            # without the stamp it would read the failure as the whole story and
            # re-issue the same shape.
            stamped = stamp_deviations("", self.deviations)
            return DoneRecord(cycle=cycle, error=f"timeout after {timeout:.0f}s",
                              summary=stamped, raw=deviation_only_raw(stamped))

        try:
            res = _json.loads(out.strip() or "{}")
        except ValueError:
            head = (out or err or "").strip().replace("\n", " ")[:200]
            self.log(f"cycle {cycle}: sdk returned unparseable stdout: {head}")
            stamped = stamp_deviations("", self.deviations)
            return DoneRecord(cycle=cycle, error=f"unparseable result: {head}",
                              summary=stamped, raw=deviation_only_raw(stamped))

        cost = float(res.get("total_cost_usd") or 0.0)
        sid = res.get("session_id")
        if sid:
            self.session_id = sid

        if res.get("is_error") or proc.returncode != 0:
            detail = str(res.get("result") or err or "").strip().replace("\n", " ")[:200]
            self.log(f"cycle {cycle}: sdk reported error (rc={proc.returncode}): {detail}")
            stamped = stamp_deviations("", self.deviations)
            return DoneRecord(cycle=cycle, cost_usd=cost, session_id=sid,
                              error=detail or f"exit {proc.returncode}",
                              summary=stamped, raw=deviation_only_raw(stamped))

        so = res.get("structured_output")
        if not isinstance(so, dict) or not all(k in so for k in DONE_SCHEMA["required"]):
            # The CLI validates against --json-schema, so this means the run ended
            # without producing one (hit a limit, refused, wandered off). Treat it
            # as a failed cycle rather than inventing fields - a fabricated sha
            # would defeat the controller's same-sha no-progress guard.
            self.log(f"cycle {cycle}: sdk returned no valid structured_output")
            stamped = stamp_deviations("", self.deviations)
            return DoneRecord(cycle=cycle, cost_usd=cost, session_id=sid,
                              error="missing or incomplete structured_output",
                              summary=stamped, raw=deviation_only_raw(stamped))

        self.log(f"cycle {cycle}: sdk done cost=${round(cost, 4)} "
                 f"sha={str(so.get('sha'))[:8]} tests={so.get('tests_pass')}")
        # Stamped into raw as well as onto the record, for the reason the ahk
        # channel spells out: raw is the director's only view of this cycle.
        stamped = stamp_deviations(str(so.get("summary") or ""), self.deviations)
        raw = dict(so)
        if self.deviations:
            raw["summary"] = stamped
        return DoneRecord(
            cycle=cycle,
            sha=str(so.get("sha") or ""),
            tests_pass=str(so.get("tests_pass", "?")),
            regressions=bool(so.get("regressions")),
            cost_usd=cost,
            session_id=sid,
            raw=raw,
            summary=stamped,
        )


HOOK_NAMES = ("pre-commit", "commit-msg")


def _hook_index_modes(root, hooks) -> dict:
    """Index mode per hook basename, from `git ls-files -s -- <hooks_dir>`.

    The GIT INDEX is the source of truth here, not the on-disk bit. On NTFS the
    POSIX exec bit is meaningless - `os.access(p, os.X_OK)` is True for every
    readable file - so an on-disk check is vacuous on the very machine that runs
    this loop, which is the "guard that degrades into always-passing" failure
    this repo keeps hitting. The index mode is what a fresh POSIX clone
    materializes, so it is what decides whether the hook runs THERE.

    Returns {} when the dir is untracked or outside the work tree (e.g. a
    `.git/hooks` install). Nothing in the index means nothing to judge - the
    caller must not read that as a breach.
    """
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", str(hooks)],
                           capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0:
        return {}
    modes = {}
    for line in (r.stdout or "").splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if path and parts:
            modes[path.rsplit("/", 1)[-1]] = parts[0]
    return modes


def _is_on_disk_executable(path) -> bool:
    """Whether the WORKING-TREE file carries a POSIX exec bit.

    DOCUMENTED NO-OP ON WINDOWS: `os.access(p, os.X_OK)` is True for every
    existing file on nt, so this probe can only ever bite on a POSIX clone -
    which is precisely the clone that loses the gate. Returning True explicitly
    on nt states that out loud instead of letting the platform decide quietly,
    and it makes the POSIX branch a seam the tests can monkeypatch, so the case
    that matters is pinned from Windows rather than skipped there.
    """
    if os.name == "nt":
        return True
    return os.access(path, os.X_OK)


def gate_inactive_reason(repo_root) -> str | None:
    """Why the commit gate is not active, or None if it looks active.

    `core.hooksPath` is LOCAL config and is NOT cloned. A fresh clone therefore
    has the tracked `.githooks/` on disk and NO hooks running - the tracked dir
    buys nothing until someone runs `python scripts/install_hooks.py`. An
    unattended headless run in that state commits and pushes with no glyph /
    ruff / trailer gate at all, and nobody is watching a session-start report.
    So the loop refuses to start rather than run ungated: this is the one place
    where failing loud beats degrading quietly.

    Presence alone was not enough. MEASURED 2026-07-26: all five tracked hooks
    in `.githooks/` were index mode 100644, and git silently refuses to run a
    non-executable hook on a POSIX clone - so the gate was inert on every Linux
    checkout, CI included, and this check called it green. So the index mode is
    read too (see _hook_index_modes for why the index and not the on-disk bit).

    The index mode is not the whole story either: it is what a fresh clone
    MATERIALIZES, not what git consults at commit time. A hook can be tracked
    100755 and still be 644 in the working tree (a later `chmod -x`, a clone
    with core.fileMode=false, an export or rsync that dropped modes, a container
    bind-mount), and git skips it just as silently. So the on-disk bit is probed
    last (see _is_on_disk_executable - a documented no-op on Windows).

    HONEST LIMIT, per the CLAUDE.md hard rule: presence plus index mode plus the
    on-disk bit is still not proof a hook FIRES. Each read raises the floor -
    the fresh-clone case, the mode-100644 case and the cleared-disk-bit case all
    now fail loud - but the gap does not close: a hook can be present, tracked,
    executable on disk and still be a no-op (empty body, an early `exit 0`, a
    shebang pointing at a missing interpreter), and on Windows the disk probe
    reads nothing at all. The end-to-end test - stage a banned glyph, attempt a
    real commit, assert HEAD unchanged - stays the only real proof and is not
    something a loop start can run.
    """
    root = Path(repo_root)
    if not (root / ".githooks").is_dir():
        return None  # not this repo's convention - do not invent a blocker
    try:
        r = subprocess.run(["git", "-C", str(root), "config", "--get", "core.hooksPath"],
                           capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        return f"could not verify the commit gate: {e}"
    configured = (r.stdout or "").strip()
    if not configured:
        return "core.hooksPath is unset, so this clone runs ZERO git hooks"
    hooks = Path(configured)
    if not hooks.is_absolute():
        hooks = root / hooks
    if not hooks.is_dir():
        return f"core.hooksPath points at a missing directory: {hooks}"
    missing = [n for n in HOOK_NAMES if not (hooks / n).is_file()]
    if missing:
        return f"hooks missing from {hooks}: {', '.join(missing)}"
    modes = _hook_index_modes(root, hooks)
    # A hook absent from the index has no mode to judge (untracked dir, or a
    # `.git/hooks` install) - that is the already-covered presence case, not a
    # mode breach, so it is skipped rather than reported.
    not_exec = [f"{n} is {modes[n]}" for n in HOOK_NAMES
                if modes.get(n) not in (None, "100755")]
    if not_exec:
        return (f"hooks tracked non-executable in {hooks} ({', '.join(not_exec)}, want 100755): "
                "git silently skips a non-executable hook on any POSIX clone, so this gate "
                "is inert there - fix with `git update-index --chmod=+x`")
    # Last, because the index mode is the more portable fault and its fix
    # repairs every future clone; this one is about THIS checkout only. It is
    # deliberately not scoped to tracked hooks - a `.git/hooks` install has no
    # index mode to judge, but git skips a non-executable file there just the
    # same, and scoping to the index would rebuild the hole one layer down.
    on_disk = [n for n in HOOK_NAMES if not _is_on_disk_executable(hooks / n)]
    if on_disk:
        return (f"hooks present but not executable on disk in {hooks} "
                f"({', '.join(on_disk)}): the tracked mode is right and the working-tree "
                "file still has no exec bit (a later `chmod -x`, a clone with "
                "core.fileMode=false, an export or rsync that dropped modes), and git "
                "skips it silently - fix with `chmod +x`")
    return None


def build(cfg, ctl, **deps):
    """Return the executor the config selects. `channel` defaults to ahk.

    Unknown values fail LOUD rather than silently falling back: a typo in
    `channel` must not quietly run the legacy singleton channel during a
    concurrent run, which is exactly the failure this seam exists to prevent.
    """
    channel = str(cfg.get("channel", "ahk")).strip().lower()
    if channel == "ahk":
        return AhkExecutor(cfg, ctl, **deps)
    if channel == "sdk":
        return SdkExecutor(cfg, ctl, **deps)
    raise ValueError(
        f"unknown executor channel {channel!r} (known: 'ahk', 'sdk')")

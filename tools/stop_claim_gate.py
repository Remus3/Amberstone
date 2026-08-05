"""Stop-hook claim gate - audit a finished session's claims against its own evidence.

RM-136 (CCR-127 wire + CCR-143 taxonomy, re-implemented in RC's own code; nothing
vendored). A Stop hook receives the finished transcript and nothing else, so this
is the adapter that turns a session into checkable claims. Where a claim is
explicit enough to reconcile against files and counts, `tools/truth_gate.py` is
the deeper tool; this gate is the thing that can run with no claims file at all.

Contract:
  - reads the Stop payload as JSON on stdin (measured 2026-08-01, CLI 2.1.220:
    the payload carries session_id / transcript_path / cwd / hook_event_name /
    stop_hook_active / last_assistant_message).
  - writes ops/runtime/stop_claim_report.json atomically.
  - REPORT-ONLY by default: always exit 0. `--arm` exits 2 on findings and is
    deliberately opt-in - a gate that fires wrongly once gets disabled forever,
    so arming waits until the report is observed quiet on clean sessions.

Usage (hook):
  pythonw.exe tools/stop_claim_gate.py
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = ROOT / "ops" / "runtime" / "stop_claim_report.json"
DEFAULT_HISTORY = ROOT / "ops" / "runtime" / "stop_claim_history.jsonl"
HISTORY_MAX = 500

# Claim patterns. Deliberately narrow: a false positive costs more than a miss,
# because the first wrong flag is what gets the hook turned off.
CLAIM_TESTS_PASS = re.compile(
    r"\b(?:suite|tests?)\b[^.\n]{0,40}?\b(?:pass(?:es|ed|ing)?|green)\b"
    r"|\bgreen\b[^.\n]{0,20}?\b(?:suite|tests?)\b", re.I)
CLAIM_COUNT = re.compile(r"\b(\d[\d,]{0,9})\s+passed\b", re.I)
# "Test 1 passed" names ONE case; "1397 passed" counts a suite. Same three
# tokens, opposite meanings, and reading the first as the second flagged a
# backed claim on 2026-08-01. A variable-width lookbehind is not available in
# `re`, so the preceding word is read off the sentence separately.
#
# It used to be CAPTURED, by an optional `(\w+)\s+` group at the head of the
# pattern, and that made the match start one word to the LEFT of the number.
# MEASURED 2026-08-04: every scope rule downstream then measured the span up to
# `match.start()`, which no longer contained the word that broke the scope -
# the word was inside the match. Sixteen laundering phrasings ("Without
# question 18226 passed", "I never doubted 18226 passed") came out with an
# empty span and were silenced. A claim pattern must span the claim and nothing
# else, or every consumer inherits its off-by-one-word.
CLAIM_COUNT_PRECEDING = re.compile(r"(\w+)\s+$")
CLAIM_COUNT_ORDINAL = frozenset({
    "test", "case", "step", "phase", "mutant", "option", "slice", "agent",
    "check", "round", "attempt", "item", "fixture", "run", "batch", "lane",
})
CLAIM_FILE = re.compile(
    r"\b(?:updated|edited|created|added|wrote|written|modified|fixed|patched)\b"
    r"[^.\n]{0,40}?([\w./\\-]+\.(?:py|md|js|css|json|html|ps1|txt|ya?ml))\b", re.I)
# A file "claim" in a COUNTERFACTUAL is not a claim. CLAIM_FILE matches a
# claim-verb within 40 chars of a filename, which cannot tell the indicative
# ("added a line to CLAUDE.md") from the conditional ("an entry ADDED to
# CLAUDE.md WOULD leave the watchdog auto-merging") - the second describes a
# hypothetical edit by someone else, at some future time, and asserts nothing
# about what this session did. MEASURED 2026-08-03: that exact sentence blocked
# four consecutive Stops on a session that had edited no such file and had in
# fact MEASURED the behaviour it was describing.
# The discriminator is a modality-of-unreality marker ANYWHERE in the sentence,
# vetoed by a first-person completed-action marker - so "I edited CLAUDE.md,
# which would break X" still flags (the claim is real; the modal is incidental),
# while a pure hypothetical does not.
CLAIM_HYPOTHETICAL = re.compile(
    r"\b(?:would|could|might|should|if|unless|whenever|were\s+\w+\s+to|"
    r"hypothetical(?:ly)?|suppose|imagine)\b", re.I)
CLAIM_FIRST_PERSON_DID = re.compile(
    r"\b(?:I|we)\s+(?:have\s+|just\s+|already\s+)*"
    r"(?:updated|edited|created|added|wrote|written|modified|fixed|patched)\b", re.I)
# SECOND false-positive shape in the same family, measured 2026-08-03 (lane 8):
# naming the file you COPIED FROM. "Fixed with the in-tree precedent at
# dashboard/routes_static.py:64-67" is a POINTER for the reader, not a claim to
# have authored that file - but CLAIM_FILE sees `fixed ... routes_static.py` and
# cannot tell "fixed X" from "fixed it the way X does". Unfixable by the model
# for the same reason as the counterfactual: the sentence is already in the
# transcript. Worse, the cheapest way to satisfy the gate would be to STOP
# CITING PRECEDENT, and citing precedent is exactly the behaviour the repo wants.
# The discriminator is a citation marker BETWEEN the claim verb and the path -
# that position is what puts the path in a citation role - vetoed by the same
# first-person completed-action marker, so "I fixed routes_static.py per the
# precedent" still flags. A marker AFTER the path does not suppress.
CLAIM_CITATION = re.compile(
    r"\b(?:precedent|per|see|cite[sd]?|citation|as in|example|documented|"
    r"described|modell?ed on|copied from|following|reference[sd]?|"
    r"pattern (?:at|in|from))\b", re.I)
# THIRD shape, same blindness, different check: a NEGATED claim. "Nothing is
# committed yet" asserts the opposite of having committed, and reporting that
# honestly was itself flagged as an unbacked commit claim (measured 2026-08-03,
# lane 8). The negation must GOVERN the claim word, not merely share its
# sentence: "I committed the fix, but not the docs" still flags. The scope rule
# that decides that lives in `_negation_governs`.
CLAIM_NEGATION = re.compile(
    r"\b(?:nothing|not|no|never|none|neither|without|nor|\w+n't)\b", re.I)
CLAIM_CI = re.compile(r"\bCI\b[^.\n]{0,30}?\b(?:green|passing|passed|clean)\b", re.I)
CLAIM_COMMIT = re.compile(r"\bcommitted\b|\bcommit(?:ted)?\s+(?:and pushed|is in|landed)\b", re.I)
CLAIM_PUSH = re.compile(r"\bpushed\b", re.I)
CLAIM_FULL_SUITE = re.compile(r"\b(?:full suite|all tests|entire suite|whole suite)\b", re.I)

# Evidence patterns.
EV_PYTEST = re.compile(r"(?:^|\s|-m\s)pytest\b", re.I)
EV_FILTERED = re.compile(r"\s-k\s|::|\btests?[\w/\\.-]*\.py\b", re.I)
EV_COMMIT = re.compile(r"\bgit\b[^|;&]*\bcommit\b", re.I)
EV_PUSH = re.compile(r"\bgit\b[^|;&]*\bpush\b", re.I)
# The binary and its subcommand need not be ADJACENT: RC's own convention is to
# invoke gh by absolute path through a variable (`GH="...gh.exe"; "$GH" run
# list`), so requiring "gh run" made a real probe invisible on every wrap. The
# span stops at | and & so a pipeline into an unrelated command cannot borrow
# the match, and a bare `run` with no gh binary anywhere still proves nothing.
EV_CI = re.compile(r"\bgh(?:\.exe)?\b[^|&\n]*?\b(?:run|pr|api|workflow)\b"
                   r"|actions/runs", re.I)
# FOURTH transport, same family, measured 2026-08-01: the span above is
# single-line and &-terminated by construction, so it cannot see a probe whose
# binary and subcommand are bound through a VARIABLE and then used on another
# line or after an `&&`. Both shapes are RC's own house style and both were used
# repeatedly in one wrap while the gate reported "no CI probe":
#   GH="C:/.../gh.exe" && "$GH" run list        (crosses the &)
#   GH=r'C:/.../gh.exe'\n ... subprocess.run([GH,'run','list'])   (crosses the \n)
# Widening EV_CI's span to cover them would credit ANY later `run` after ANY gh
# mention, which is exactly the looseness that produced the first armed session's
# 9 false positives. So this binds the SAME NAME instead: capture the identifier
# that was assigned a gh binary path, then require THAT identifier immediately
# ahead of a gh subcommand. An assignment alone is not evidence, and a `run` with
# no gh-bound variable in front of it is not evidence.
EV_CI_VAR = re.compile(
    r"(?P<name>\b\w+)\s*=\s*r?[\"'][^\"'\n]*\bgh(?:\.exe)?[\"']"
    r"[\s\S]*?"
    r"[\$\{\"'\[,\s](?P=name)[\}\"']?\s*[,\s]\s*[\"']?(?:run|pr|api|workflow)\b",
    re.I)
EV_BYPASS = re.compile(r"--no-verify\b|--no-gpg-sign\b|core\.hooksPath\s*=", re.I)
EV_PASSED = re.compile(r"\b(\d[\d,]{0,9})\s+passed\b", re.I)
EV_VACUOUS = re.compile(r"no tests ran|collected 0 items", re.I)
# A backgrounded run answers with a launcher handoff, not a summary. The real
# output lands later, when the output file is read by some unrelated command.
EV_BACKGROUND = re.compile(r"running in background with ID|Output is being written to",
                           re.I)
# Deliberately the TERMINAL-SUMMARY shape, not a bare "N passed". Crediting any
# floating count is what poisoned the first armed gate; requiring the trailing
# duration is what keeps this a widening of evidence and not of belief.
EV_SUMMARY_LINE = re.compile(
    r"\d[\d,]*\s+(?:passed|failed|error)\b[^\n]*?\bin\s+[\d.]+\s*s", re.I)

EDIT_TOOLS = {"edit", "write", "multiedit", "notebookedit"}

# Everything below exists because the ARMED gate's first real session produced 9
# findings and 9 false positives (LEDGER 1154). Every one was the gate reading a
# DESCRIPTION of a thing as the thing itself: a bypass flag named inside a
# heredoc that was writing documentation, the phrase "no tests ran" appearing in
# prose, and a claim quoted as an example. Stripping quotation before matching is
# the fix; matching inside it is the bug.
_HEREDOC = re.compile(r"<<-?\s*'?(\w+)'?.*?^\1\s*$", re.S | re.M)
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"", re.S)
_FENCED = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`]*`")


# A quoted token that is an EXECUTABLE PATH is the command, not data. Windows
# forces the quotes - `C:\Program Files\GitHub CLI\gh.exe` cannot be written
# unquoted - so deleting it with the rest of the quoted literals made every CI
# probe on this machine invisible to EV_CI. MEASURED 2026-08-04: a session that
# ran `"C:/Program Files/GitHub CLI/gh.exe" run view <id>` seven times was still
# flagged ci_claim_without_probe, because after stripping, the command read
# ` run view <id>` with no `gh` token left for any pattern to see. The repo's
# own /done instructions mandate that absolute quoted path, so this was not an
# unusual way to invoke it - it was the prescribed one.
_QUOTED_EXE = re.compile(r"""["']([^"']*?[\/])?([\w.-]+\.exe)["']""", re.I)


def strip_command_noise(command):
    """A command's heredoc body and quoted literals are DATA, not the command.

    A quoted EXECUTABLE PATH is the exception: it collapses to its basename
    rather than vanishing, so the invoked binary survives for the evidence
    patterns while the surrounding prose-stripping is unchanged.
    """
    command = _QUOTED_EXE.sub(lambda m: " " + m.group(2) + " ", command)
    return _QUOTED.sub(" ", _HEREDOC.sub(" ", command))


def strip_prose_noise(text):
    """Fenced blocks, inline code and quoted spans are quotation, not assertion."""
    return _QUOTED.sub(" ", _INLINE_CODE.sub(" ", _FENCED.sub(" ", text)))
# Split on sentence boundaries only, never on the dot inside `core/ports.py` -
# a naive [.;\n] split severs every filename and silently kills check 3.
_SENTENCE = re.compile(r"(?<=[.;!?])\s+|\n")


def _blocks(row):
    message = row.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _result_text(block):
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content
                        if isinstance(part, dict))
    return ""


def collect_evidence(rows):
    """Split a transcript into the assistant's claims and the session's evidence.

    Test runs are PAIRED with the result that followed them. A count or a
    "no tests ran" marker floating anywhere in the session is not an observation
    of a suite run - reading it as one is what poisoned every claim in the first
    armed session.
    """
    ev = {"texts": [], "bash": [], "edited": [], "runs": []}
    pending = None
    deferred = None
    for row in rows:
        role = row.get("type")
        for block in _blocks(row):
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and role == "assistant":
                ev["texts"].append(str(block.get("text", "")))
            elif kind == "tool_use":
                name = str(block.get("name", "")).lower()
                data = block.get("input") or {}
                if name in ("bash", "powershell"):
                    command = str(data.get("command", ""))
                    ev["bash"].append(command)
                    if EV_PYTEST.search(strip_command_noise(command)):
                        pending = {"cmd": command, "output": ""}
                        ev["runs"].append(pending)
                if name in EDIT_TOOLS:
                    target = data.get("file_path") or data.get("path") or ""
                    if target:
                        ev["edited"].append(str(target))
            elif kind == "tool_result":
                text = _result_text(block)
                if pending is not None:
                    pending["output"] = text
                    # A backgrounded run has not reported yet. Keep it open so
                    # the summary can be attached when the output file is read.
                    deferred = pending if EV_BACKGROUND.search(text) else deferred
                    pending = None
                elif deferred is not None and EV_SUMMARY_LINE.search(text):
                    # The deferred run finally speaking, through whatever command
                    # happened to read its output file. Attach, do not free-float.
                    deferred["output"] += "\n" + text
                    deferred = None
    return ev


def _sentences(texts):
    for text in texts:
        for part in _SENTENCE.split(text):
            part = part.strip()
            if part:
                yield part


def _same_file(claimed, edited_paths):
    claim = claimed.replace("\\", "/").lower().lstrip("./")
    for path in edited_paths:
        actual = path.replace("\\", "/").lower()
        if actual.endswith(claim) or claim.endswith(actual):
            return True
    return False


# A FIXED-WIDTH lookback cannot tell a retraction from a laundered claim, and
# MEASURED 2026-08-04 it charged the same price for both: "Retracting: I have
# not observed 16 passed, 18226 passed, or a clean ruff run" was flagged
# count_mismatch at 18226 - the retraction read as a fresh assertion of the
# number it retracted. Correcting yourself then cost exactly what the false
# claim cost, so silence became the cheapest way to satisfy the gate.
#
# The rule below is SCOPE, not proximity: a negation governs a claim only when
# nothing but scope-transparent material stands between the two. Everything
# else breaks the scope, which is what keeps "this is not a guess: 18226
# passed" flagging. Five conditions, and the anti-laundering value is in all
# but the first:
#   1. no polarity-resetting punctuation in the span - a colon, a clause dash,
#      a paren or a bracket starts a new assertion the negation cannot cross;
#   2. every word in the span is scope-transparent (an auxiliary, an evidence
#      verb, a determiner or list material). One content word - "guess",
#      "doubt", "question", "exaggeration" - means the negation denies THAT;
#   3. a non-adjacent negation must reach the claim THROUGH a verb, so a bare
#      "no, 18226 passed" stays an assertion;
#   4. a negation already inside an earlier negation's reach is polarity-
#      RESTORED and denies nothing ("no one can claim it is not 18226 passed").
#      Coordination resets that, so "nothing was committed and nothing was
#      pushed" keeps both denials;
#   5. a modal perfect ("could not have measured") is counterfactual rather
#      than evidential, and a litotes marker after the claim ("... by
#      accident") inverts the whole sentence back into an assertion.
# The allowlists are deliberately small, so an unusual retraction phrasing
# still flags. That is the safe direction: a false flag costs one sentence, a
# bypass costs the guard.
#
# KNOWN LIMITS, measured 2026-08-04 over a 233-sentence differential corpus run
# against the pre-fix gate. These are accepted, not unnoticed:
#   - a retraction placed AFTER its claim ("18226 passed was not measured") is
#     NOT recognised and still flags. A trailing branch was tried and dropped:
#     it needed a reality-verb test that "was not a reporting error" and "was
#     not really in doubt" both satisfied, which is a bypass for one phrasing.
#   - "I should not have said 18226 passed" flags. It is a real retraction, but
#     it is indistinguishable in form from "we could not have gotten 18226
#     passed by accident", and only one of the two may be silenced.
#   - a retraction reached through an unlisted verb ("I have not been able to
#     confirm 18226 passed", "I did not say 18226 passed") flags. Widening the
#     verb list is how "did not misreport" would get in.
#   - `none`/`neither` may still reach a claim through a single verb, so an
#     agrammatical "None measured 18226 passed" is silenced; unlike bare `no`
#     those are pronouns, so the determiner rule cannot apply.
#   - scope is one SENTENCE, and `_sentences` splits on [.;!?] only. A
#     retraction spanning two sentences does not reach its claim.
#   - none of this sees intent. It sees the shape of the words.
_NEG_SCOPE_PUNCT = re.compile(r"^[\w\s,]*$")
_NEG_SCOPE_VERB = frozenset("""
    is are was were be been being am have has had do does did
    observe observed observes observing measure measured measures
    record recorded records report reported reports see seen saw sees
    run ran runs produce produced produces verify verified verifies
    confirm confirmed confirms claim claimed claims assert asserted asserts
    state stated states show shown showed shows log logged logs
    count counted counts find found finds
""".split())
# ACHIEVEMENT verbs (get/got/gotten, reach/reached, hit) and SPEECH verbs
# (say/says/said) are deliberately absent. Denying an achievement is the litotes
# that laundered "we could not have gotten 18226 passed by accident", and
# "nothing that says it is not 18226 passed" needs `says` opaque to stay flagged.
# Modals are absent for the same reason - they are handled as counterfactual
# markers below, not as verbs a denial travels through.
_NEG_SCOPE_FILLER = frozenset("""
    a an the any all part of it its this that these those they them we i my our
    yet still actually ever even really or nor
    pass passes passed passing green clean committed pushed
""".split())
# `about` is NOT filler: "nothing about 18226 passed is uncertain" makes the
# claim the TOPIC of the denial, not its content. Nor is `and` - "no tests
# failed and 18226 passed" is two assertions, one of them unbacked.
_NEG_MODAL = re.compile(
    r"\b(?:can|could|will|would|shall|should|may|might|must)\s*$", re.I)
_NEG_PERFECT = frozenset({"have", "has", "had", "been"})
_NEG_LITOTES = re.compile(
    r"\bby\s+(?:accident|chance|luck|mistake|coincidence)\b|\bcoincidence\b", re.I)
# Coordination opens a fresh polarity domain; anything else between two
# negations means the first one scopes over the second.
_NEG_COORD = re.compile(r"\b(?:and|or|nor|but|then|also|plus)\b|[.;:!?]", re.I)


def _scope_words(span):
    return [word.lower() for word in re.findall(r"\w+", span)]


def _transparent(words):
    return all(word.isdigit() or word in _NEG_SCOPE_VERB
               or word in _NEG_SCOPE_FILLER for word in words)


def _polarity_restored(sentence, neg):
    """True when an earlier negation in this sentence scopes over `neg`."""
    for earlier in CLAIM_NEGATION.finditer(sentence[:neg.start()]):
        if not _NEG_COORD.search(sentence[earlier.end():neg.start()]):
            return True
    return False


def _negation_governs(sentence, start, end):
    """True when some negation in this sentence has the claim in its scope.

    `start` and `end` bound the CLAIM itself. They are passed explicitly rather
    than taken from a match object because a claim pattern that captures its own
    left context puts the scope-breaking word inside the match, where no span
    can see it - the exact defect that silenced sixteen laundering phrasings.
    """
    if _NEG_LITOTES.search(sentence[end:]):
        return False
    for neg in CLAIM_NEGATION.finditer(sentence):
        if neg.start() >= end:
            break
        if _polarity_restored(sentence, neg):
            continue
        if neg.start() >= start:
            # Inside the claim span ("the suite did not pass"): only the tail of
            # the claim itself stands between the two, so no verb is required.
            span = sentence[neg.end():end]
            if _NEG_SCOPE_PUNCT.match(span) and _transparent(_scope_words(span)):
                return True
            continue
        span = sentence[neg.end():start]
        if not _NEG_SCOPE_PUNCT.match(span) or not _transparent(_scope_words(span)):
            continue
        words = _scope_words(span)
        if _NEG_MODAL.search(sentence[:neg.start()]) and any(w in _NEG_PERFECT
                                                             for w in words):
            continue
        # Bare `no` is a DETERMINER and must take a nominal, so `no <verb>` is
        # not English and cannot be a denial. Without this, the 64 agrammatical
        # fragments the probe generated ("No measured 18226 passed") reached the
        # claim through rule 3. `none` and `neither` are pronouns and stay
        # allowed ("None showed 18226 passed").
        if (neg.group().lower() == "no" and words
                and words[0] in _NEG_SCOPE_VERB and words[0] not in _NEG_SCOPE_FILLER):
            continue
        if not span.strip():
            return True
        if any(word in _NEG_SCOPE_VERB for word in words):
            return True
    return False


def _negated(sentence, claim_re):
    """True when EVERY occurrence of the claim in this sentence is governed by a
    negation. One ungoverned mention is still a claim."""
    matches = list(claim_re.finditer(sentence))
    return bool(matches) and all(
        _negation_governs(sentence, m.start(), m.end()) for m in matches)


def audit(ev):
    """Nine checks. Every finding cites the sentence that made the claim."""
    findings = []

    def flag(check, quote, claimed="", observed=""):
        findings.append({"check": check, "quote": quote[:300],
                         "claimed": str(claimed), "observed": str(observed)})

    bash = [strip_command_noise(c) for c in ev["bash"]]
    runs = ev["runs"]
    ran_pytest = bool(runs)
    filtered_only = ran_pytest and all(EV_FILTERED.search(r["cmd"]) for r in runs)
    observed_counts = {m.replace(",", "") for r in runs
                       for m in EV_PASSED.findall(r["output"])}
    # Vacuous only if EVERY run was vacuous. One real green run answers the claim.
    vacuous = ran_pytest and all(EV_VACUOUS.search(r["output"]) for r in runs)
    did_commit = any(EV_COMMIT.search(c) for c in bash)
    did_push = any(EV_PUSH.search(c) for c in bash)
    # EV_CI runs on the noise-stripped command; EV_CI_VAR must NOT, because
    # strip_command_noise deletes quoted literals and a `python -c "<script>"`
    # probe is ENTIRELY inside one quoted literal - stripped, it reduces to
    # `python -c` and no pattern could ever see it. Heredocs are still removed
    # for EV_CI_VAR, so a heredoc that DOCUMENTS a gh invocation stays data.
    raw_bash = [_HEREDOC.sub(" ", c) for c in ev["bash"]]
    probed_ci = (any(EV_CI.search(c) for c in bash)
                 or any(EV_CI_VAR.search(c) for c in raw_bash))

    # 5 - evidence-only check. Requires an actual git invocation: a bypass flag
    # NAMED in prose or a heredoc body is documentation, not a bypass.
    for command in bash:
        if EV_BYPASS.search(command) and re.search(r"\bgit\b", command):
            flag("hook_bypass", command, observed=command)

    for sentence in _sentences(strip_prose_noise(t) for t in ev["texts"]):
        claims_pass = (bool(CLAIM_TESTS_PASS.search(sentence))
                       and not _negated(sentence, CLAIM_TESTS_PASS))
        if claims_pass and not ran_pytest:
            flag("tests_pass_without_run", sentence)                       # 1
        if claims_pass and vacuous:
            flag("vacuous_run", sentence, observed="no tests ran")         # 8
        if claims_pass and CLAIM_FULL_SUITE.search(sentence) and filtered_only:
            flag("full_suite_claim_over_filtered_run", sentence,           # 7
                 observed="; ".join(r["cmd"] for r in runs))
        # finditer, not findall: the scope rule needs the claim's own bounds,
        # and the retraction is per-NUMBER - one denied count in a sentence
        # does not license the others.
        for claim in CLAIM_COUNT.finditer(sentence):
            lead = CLAIM_COUNT_PRECEDING.search(sentence[:claim.start()])
            if lead and lead.group(1).lower() in CLAIM_COUNT_ORDINAL:
                continue
            bare = claim.group(1).replace(",", "")
            if _negation_governs(sentence, claim.start(), claim.end()):
                continue
            if observed_counts and bare not in observed_counts:
                flag("count_mismatch", sentence, claimed=bare,             # 2
                     observed=", ".join(sorted(observed_counts)))
        # A counterfactual asserts nothing about this session - see
        # CLAIM_HYPOTHETICAL. Computed once per sentence, not per path.
        hypothetical = (bool(CLAIM_HYPOTHETICAL.search(sentence))
                        and not CLAIM_FIRST_PERSON_DID.search(sentence))
        # finditer, not findall: the citation test needs the SPAN, because only
        # a marker between the verb and the path puts the path in a citation
        # role. First-person completed action vetoes both suppressions.
        first_person = bool(CLAIM_FIRST_PERSON_DID.search(sentence))
        for match in CLAIM_FILE.finditer(sentence):
            if hypothetical:
                continue
            path = match.group(1)
            lead = sentence[match.start():match.start(1)]
            if CLAIM_CITATION.search(lead) and not first_person:
                continue
            if _negation_governs(sentence, match.start(), match.end()):
                continue
            if not _same_file(path, ev["edited"]):
                flag("file_claim_without_edit", sentence, claimed=path)    # 3
        if (CLAIM_CI.search(sentence) and not probed_ci
                and not _negated(sentence, CLAIM_CI)):
            flag("ci_claim_without_probe", sentence)                       # 4
        if (CLAIM_COMMIT.search(sentence) and not did_commit
                and not _negated(sentence, CLAIM_COMMIT)):
            flag("commit_claim_without_commit", sentence)                  # 6
        if (CLAIM_PUSH.search(sentence) and not did_push
                and not _negated(sentence, CLAIM_PUSH)):
            flag("push_claim_without_push", sentence)                      # 9
    return findings


def read_transcript(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def history_row(report):
    """One flat line per audit.

    The report is overwritten on every Stop, so it can only ever answer "was the
    last session clean". The arm/disarm decision needs "has the armed gate been
    quiet across sessions", which is an n greater than 1 - that is what this is.
    """
    findings = report.get("findings", [])
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": report.get("session_id", ""),
        "mode": report.get("mode", ""),
        "armed": bool(report.get("armed", False)),
        "findings": len(findings),
        "checks": sorted({f["check"] for f in findings}),
        "blocked": bool(report.get("blocked", False)),
        "reason": report.get("reason", report.get("error", "")),
    }


def append_history(report, target, cap=HISTORY_MAX):
    """Append then roll to the last `cap` lines.

    Bookkeeping must never break the gate: a Stop hook that raises on a full
    disk or a locked file is worse than one that keeps no history, so every
    failure here is swallowed deliberately.
    """
    try:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(history_row(report)) + "\n")
        if cap > 0:
            lines = [ln for ln in target.read_text(encoding="utf-8").splitlines() if ln]
            if len(lines) > cap:
                tmp = target.with_suffix(target.suffix + ".tmp")
                tmp.write_text("\n".join(lines[-cap:]) + "\n",
                               encoding="utf-8", newline="\n")
                tmp.replace(target)
    except (OSError, ValueError):
        pass


def write_report(report, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--history", default=str(DEFAULT_HISTORY),
                        help="rolling JSONL of every audit; the report is "
                             "overwritten per Stop and cannot answer 'quiet "
                             "across sessions' on its own")
    parser.add_argument("--history-max", type=int, default=HISTORY_MAX,
                        help="keep only the newest N lines; 0 disables rolling")
    parser.add_argument("--arm", action="store_true",
                        help="exit 2 on findings; OFF by default and stays off "
                             "until the report is observed quiet on clean sessions")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    report = {
        "mode": "armed" if args.arm else "report-only",
        "armed": bool(args.arm),
        "session_id": payload.get("session_id", ""),
        "cwd": payload.get("cwd", ""),
        "transcript": payload.get("transcript_path", ""),
        "findings": [],
    }

    transcript = payload.get("transcript_path")
    if not transcript or not Path(transcript).exists():
        report["error"] = "transcript-unreadable"
        write_report(report, args.report)
        append_history(report, args.history, args.history_max)
        return 0

    findings = audit(collect_evidence(read_transcript(transcript)))
    report["findings"] = findings

    # Exit 2 on Stop BLOCKS the session from ending and hands stderr back to the
    # model. So re-entry is the hazard: if the model restates the claim, a second
    # block loops forever. `stop_hook_active` is true once we have already
    # blocked, and it is the only thing standing between armed mode and a spin.
    reentry = bool(payload.get("stop_hook_active"))
    should_block = bool(args.arm and findings and not reentry)
    report["blocked"] = should_block
    if args.arm and findings and reentry:
        report["reason"] = "stop_hook_active"
    write_report(report, args.report)
    append_history(report, args.history, args.history_max)

    if should_block:
        lines = [f"stop_claim_gate: {len(findings)} claim(s) not backed by this "
                 f"session's own evidence. Fix or retract, then finish."]
        for finding in findings:
            detail = ""
            if finding["claimed"] or finding["observed"]:
                detail = f" (claimed {finding['claimed']!r} / observed {finding['observed']!r})"
            lines.append(f"  - {finding['check']}{detail}: {finding['quote']}")
        lines.append(f"  full report: {args.report}")
        # Under pythonw.exe sys.stderr can be None. Blocking with no reason is
        # worse than not blocking, so never let the emit itself raise.
        try:
            if sys.stderr is not None:
                print("\n".join(lines), file=sys.stderr)
        except (OSError, ValueError):
            pass
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

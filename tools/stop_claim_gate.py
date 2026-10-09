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
  - RM-687: a sub-agent's tool rows are NOT in the main transcript; they sit in
    <transcript minus .jsonl>/subagents/agent-<id>.jsonl (measured CLI 2.1.294,
    2026-10-08; nested agents share that flat dir). Read LAZILY, only when a
    CLEARABLE finding would stand, only THIS session's dir, and CREDIT-ONLY:
    paired runs / edits / CI probes / commits / merges / pushes can remove a
    main-only finding, never add one. Never raises. See CLEARABLE.
  - REPORT-ONLY by default: always exit 0, prints nothing. `--arm` on
    blocking findings still exits 0 but prints ONE stdout JSON object,
    {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext":
    "<one line <= 160 chars: gate, count, codes, report path>"}}, which keeps
    the session going and shows as "Stop hook feedback", never a "Stop hook
    error" (MAIN ORDER 2026-10-07 2237; the full message goes to the report's
    `message`). Arming is deliberately opt-in - a gate that fires wrongly once gets disabled forever,
    so arming waits until the report is observed quiet on clean sessions.

Usage (hook):
  python.exe tools/stop_claim_gate.py --arm

python.exe here is deliberate, not drift. Under the desktop harness a hook
inherits a windowless console from its bash parent and does not flash (measured
2026-09-14), so the pythonw token buys nothing; and this gate's only block
channel is exit 2 plus stderr, which is unmeasured under pythonw on Stop. An
interpreter swap was proposed as a console-flash remedy and REFUTED by that
measurement - do not redo it. (The block channel was exit 2 plus stderr when
that was measured; it is now exit 0 plus one stdout JSON line, which is also
unmeasured under pythonw, so the reasoning stands.)
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
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
CLAIM_COUNT = re.compile(r"(?:(\w+)\s+)?\b(\d[\d,]{0,9})\s+passed\b", re.I)
# "Test 1 passed" names ONE case; "1397 passed" counts a suite. Same three
# tokens, opposite meanings, and reading the first as the second flagged a
# backed claim on 2026-08-01. A variable-width lookbehind is not available in
# `re`, so the preceding word is captured and filtered here instead.
CLAIM_COUNT_ORDINAL = frozenset({
    "test", "case", "step", "phase", "mutant", "option", "slice", "agent",
    "check", "round", "attempt", "item", "fixture", "run", "batch", "lane",
})
# Same blindness, a different separator: a SPACE-grouped thousand is ONE
# number, not a word plus a number. MEASURED 2026-09-10 on the prose
# "10 856 passed" - CLAIM_COUNT.findall returns ('10', '856') and the gate
# reports the session claimed "856", a string that appears nowhere in the
# transcript. The claim was TRUE (the run printed 10856), so the finding is a
# pure false positive, the class this module's header calls costlier than a
# miss. Widening the prefix group is not available: it is what feeds
# CLAIM_COUNT_ORDINAL, so the grouping SHAPE is filtered at the consumer.
#
# The shape alone is NOT the discriminator, and a first version that used it
# alone was measured wrong the same day. That version dropped the pair
# unconditionally whenever the prefix was 1-3 digits and the count exactly 3,
# on the theory that an evader would have to write a count no reader parses as
# a suite total. Running the real gate against an observed 1397 refuted it:
# "lane 8 328 passed", "run 2 654 passed", "12 999 passed", "123 999 passed"
# and "0 000 passed" ALL went from FLAG to SILENT. "lane 8 328 passed" reads
# as an ordinary suite total, so the fence was false and EVERY 3-digit total
# 000-999 became unflaggable behind any 1-3 digit token. Do NOT re-simplify
# this back to the shape-only test.
#
# So the suppression is EVIDENCE-DERIVED: the shape opens the door, and the
# JOINED form having actually been OBSERVED is what walks through it. "10 856"
# is suppressed only because 10856 is in observed_counts; "lane 8 328" is not,
# because 8328 never ran. This also disposes of the anti-join objection that
# motivated the blanket drop - "run 2 1397 passed" would join to a false 21397,
# but its count is 4 digits and never reaches this guard at all.
#
# Residual, honestly: this can only ever be evaded by making the joined form
# equal a genuinely observed count, i.e. by telling the truth about a run that
# happened. It stays a MISS-shaped rule, never a false-pass one - suppression
# only ever deletes a claim, so no wrong number is laundered into agreement.
# On fall-through the reported `claimed` stays the trailing group (856), not
# the joined form: once the join is unobserved there is no evidence the prefix
# was a separator at all, and for "lane 8 328 passed" the claim genuinely IS
# 328. Reporting 8328 there would re-commit the exact defect this block
# exists to fix - a `claimed` string that appears nowhere in the prose.
CLAIM_COUNT_GROUPED = re.compile(r"^\d{1,3}$")
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
# lane 8). The negation must GOVERN the claim word, so it is looked for in the
# 40 chars immediately BEFORE the match and not merely somewhere in the
# sentence: "I committed the fix, but not the docs" still flags.
# The contracted forms ("isn't pushed", "wasn't pushed", "haven't pushed")
# were missed until 2026-10-04: only the spelled-out "not" was in the set, so
# "The branch isn't pushed" flagged while "The branch is not pushed" did not.
# Same 40-char governing window, so a TRAILING contraction ("pushed, but it
# isn't merged") still flags. The apostrophe class admits U+2019, escaped so
# this file stays 7-bit ASCII.
CLAIM_NEGATION = re.compile(
    r"\b(?:nothing|not|no|never|none|neither|without|cannot)\b"
    r"|\b\w+n['\u2019]t\b", re.I)
CLAIM_CI = re.compile(r"\bCI\b[^.\n]{0,30}?\b(?:green|passing|passed|clean)\b", re.I)
# A CI claim in the FUTURE or as an INTENT ("I'll confirm CI is green", "will
# check CI passing", "need to verify CI is green") reports a plan, not CI state.
# Measured flagging 2026-10-04. The marker must stand in the 40 chars BEFORE
# "CI" - the same governing-window rule as CLAIM_NEGATION - so "CI is green;
# I'll merge next" and "CI passed, so I will merge" still flag.
CLAIM_CI_FUTURE = re.compile(
    r"\b(?:will|shall|going\s+to|about\s+to|plan(?:ning)?\s+to|intend\s+to)\b"
    r"|\b\w+['\u2019]ll\b"
    r"|\b(?:need|needs|have|has|want|wants|yet)\s+to\s+"
    r"(?:check|confirm|verify|probe|watch|see|re-?check)\b", re.I)
CLAIM_COMMIT = re.compile(r"\bcommitted\b|\bcommit(?:ted)?\s+(?:and pushed|is in|landed)\b", re.I)
CLAIM_PUSH = re.compile(r"\bpushed\b", re.I)
# FOURTH shape in the same family, measured 2026-09-20: ATTRIBUTED speech.
# `CLAIM_PUSH` is a bare `\bpushed\b`, so it cannot tell the speaker's OWN
# assertion of a completed upload from a relay of what some DOCUMENT asserts,
# nor from a sentence whose whole point is to DISCLAIM that assertion. Both
# shapes fired on one session, and both were scrupulous reporting:
#   "- `RC-NEXT-SESSION.txt` hand-off (tree clean, ..., everything pushed)"
#   "The hand-off's claim that everything is pushed is consistent with what I
#    measured, but I have not independently confirmed the remote."
# The second is the session CORRECTING its own earlier over-claim, which is
# exactly the behaviour the repo wants and exactly what the gate punished.
# `_negated` cannot reach it: the negation governs the CONFIRMATION, not the
# verb the pattern keys on, so it is nowhere near the 40-char window.
#
# The first also shows why backticking - the remedy the armed emit prescribes -
# does not cover this class. The author DID backtick, and `strip_prose_noise`
# duly deleted the filename that carried the attribution, leaving the bare noun
# "hand-off" to do all the work. Backticks help a QUOTED FIGURE; they do not
# help a relayed PROPOSITION spelled in ordinary prose.
#
# Two arms, both vetoed by a first-person completed-push marker, so "According
# to the plan, I pushed the fix" still flags:
#
# (1) CLAIM_ATTRIBUTION - an explicit reporting relation standing BEFORE the
#     claim word: "according to", "per the <source>", "reportedly", a source
#     noun bound to a reporting verb ("the note says"), or a claim/assertion
#     NOUN ("X's claim that", "claims to have"). Position matters for the same
#     reason it does in CLAIM_CITATION: a marker AFTER the claim did not govern
#     it. Deliberately NOT included: bare "quoting" / "verbatim", which would
#     suppress "I quoted the count and pushed the fix".
#
# (2) CLAIM_RELAY_HEAD - the NOMINAL relay: a document noun immediately heading
#     a parenthetical that contains the claim, with no first-person pronoun and
#     no completed-action verb anywhere ahead of it. That last clause is what
#     keeps "Wrote the hand-off (tree clean, everything pushed)" flagging - a
#     sentence with an actor in it is the actor's own claim. The relay noun set
#     is a NARROW subset on purpose: "report", "summary" and "log" are common
#     headings for a session's own output, so they are credited only through
#     arm (1), which demands an actual reporting verb.
#
# Erring deliberately toward FIRING: there is no standalone epistemic-disclaimer
# arm. "Everything is pushed, though I have not verified the remote" is a flat
# first-person claim carrying a hedge, and suppressing it would be a false
# negative - the costlier direction for a guard. The disclaiming example above
# is suppressed by its ATTRIBUTION ("the hand-off's claim that"), which is the
# honest reason, not by the disclaimer.
_SOURCE_NOUN = (r"hand-?offs?|notes?|docs?|documents?|documentation|readme|"
                r"ledger|roadmap|wakeup|reports?|summary|prompts?|messages?|"
                r"transcript|entry|logs?|memo|banner|inbox|changelog|spec|"
                r"brief|instructions|plan")
_RELAY_NOUN = (r"hand-?offs?|notes?|docs?|documents?|documentation|readme|"
               r"ledger|roadmap|wakeup|prompts?|messages?|transcript|entry|"
               r"memo|inbox|changelog|spec|brief|instructions")
_REPORTING_VERB = (r"says?|said|states?|stated|asserts?|asserted|claims?|"
                   r"claimed|reports?|reported|records?|recorded|insists?|"
                   r"insisted|notes?|noted|tells?|told|describes?|described|"
                   r"reads?")
CLAIM_ATTRIBUTION = re.compile(
    r"\baccording to\b|\breportedly\b|\ballegedly\b|\bsupposedly\b|"
    r"\bostensibly\b|\bon (?:its|their|his|her) say-so\b"
    r"|\bper\s+(?:the\s+|its\s+|their\s+|my\s+|our\s+)?(?:" + _SOURCE_NOUN + r")\b"
    r"|\b(?:" + _SOURCE_NOUN + r")\b(?:'s)?[^.\n]{0,20}?\b(?:" + _REPORTING_VERB + r")\b"
    r"|'s\s+(?:claim|assertion|statement|report|note|word)\b"
    r"|\bclaims?\s+(?:that|to)\b|\bclaimed\s+(?:that|to)\b", re.I)
CLAIM_RELAY_HEAD = re.compile(r"\b(?:" + _RELAY_NOUN + r")\b[^.\n(]{0,15}\(", re.I)
CLAIM_OWN_ACTION = re.compile(
    r"\b(?:I|we|my|our|us)\b"
    r"|\b(?:wrote|writes|writing|write|written|updated|update|created|create|"
    r"added|add|made|make|left|leave|ran|run|committed|commit|pushed|push|"
    r"landed|shipped|finished|completed|done|did|verified|measured|confirmed)\b",
    re.I)
CLAIM_FIRST_PERSON_PUSHED = re.compile(
    r"\b(?:I|we)\s+(?:have\s+|has\s+|had\s+|just\s+|already\s+|then\s+|also\s+|"
    r"finally\s+|since\s+|therefore\s+)*push(?:ed)?\b", re.I)
# Check 6 (commit) carries the same blindness as check 9, measured 2026-09-20:
# three correct sentences from one session flagged commit_claim_without_commit
# while none claimed the SPEAKER committed anything -
#   "The committed build tables are unaffected, ..."        (adjective)
#   "I checked the committed tables at HEAD ..."            (adjective, a READ)
#   "The build agent committed these build tables in ..."   (third party)
# CLAIM_ATTRIBUTION does not reach any of them: it models REPORTING relations,
# and has no vocabulary for an agent as the grammatical subject. So two narrow
# per-match exemptions, both vetoed by a first-person commit anywhere in the
# sentence, so "The build agent committed X, and I committed Y" still flags:
#
# (1) ADJECTIVAL - a determiner immediately before "committed" and a following
#     word that is not a coordinator ("the committed tables"). "committed and
#     pushed" keeps flagging because "and" is refused as the following word.
# (2) THIRD-PARTY SUBJECT - an agent-shaped noun or third-person pronoun as the
#     immediate subject, optionally through an auxiliary or adverb. "session" is
#     deliberately NOT in the set: "this session committed" is the speaker.
#     Nor are "merger" and "operator" (removed after an adversarial refutation
#     of the first cut, 2026-09-20): in this repo the MERGER is the speaking
#     main session, and the operator never runs commands, so neither is a
#     third party whose commit the speaker is merely reporting.
#
# Refinements from that same refutation:
#   - the adjectival exemption is refused when the sentence asserts LANDED
#     state ("the committed fix is in main") - that is a claim about what
#     happened, whatever part of speech carries it;
#   - the first-person veto keys on ANY first-person git ACTION (committed,
#     pushed, merged, landed, ...), so "They committed it and I pushed" flags.
#     It keys on git verbs only: "I checked the committed tables" stays exempt.
# ACCEPTED RESIDUE (round 3, 2026-09-20): open-ended adjectival forms ("Its
# committed state is green", "That committed work is done") and pure
# third-party sentences with no first-person clause are exempt BY DESIGN.
CLAIM_FIRST_PERSON_COMMITTED = re.compile(
    r"\b(?:I|we)\s+(?:have\s+|has\s+|had\s+|just\s+|already\s+|then\s+|also\s+|"
    r"finally\s+|since\s+|therefore\s+)*"
    r"(?:commit(?:ted)?|push(?:ed)?|merged?|land(?:ed)?|cherry-?picked|"
    r"rebased|amended|shipped)\b"
    # Passive first person ("merged by me") - round 2 of the refutation.
    r"|\b(?:commit(?:ted)?|push(?:ed)?|merged|landed|cherry-?picked|rebased|"
    r"amended|shipped)\s+by\s+(?:me|us)\b", re.I)
# Round 2 also widened the landed-state tails. "at HEAD" is deliberately NOT
# here: it is a READ locator ("I checked the committed tables at HEAD"), while
# "in/into HEAD" asserts the change landed. Any "origin" counts.
CLAIM_COMMIT_LANDED_STATE = re.compile(
    r"\b(?:is|are|was|were|now|went)\s+live\b"
    r"|\b(?:in|on|into|onto)\s+(?:main|master)\b|\borigin\b"
    r"|\b(?:in|into)\s+HEAD\b|\bdeployed\b|\bproduction\b"
    r"|\blanded\b|\bsits?\s+on\b|\bpushed\b|\bmerged\b|\bshipped\b", re.I)
CLAIM_COMMIT_DETERMINER_LEAD = re.compile(
    r"\b(?:the|a|an|this|that|these|those|its|their|his|her)\s+$", re.I)
CLAIM_COMMIT_ADJECTIVE_TAIL = re.compile(
    r"\s+(?!(?:and|or|to|by|in|on|at|as)\b)[A-Za-z]", re.I)
# 2026-10-04 widening, each shape measured flagging:
#   - an agent noun carrying an IDENTIFIER ("Agent-a3", "Slice 2", "Agent B");
#   - a POSSESSIVE subject ("The slice's commit landed in its worktree");
#   - a sibling tree's CHANNEL CODE as subject ("LW committed 700cd64"). Codes
#     are matched by SHAPE (2-4 uppercase letters, case-sensitive), never by a
#     list of sibling names - those must never appear in a tracked file. RC is
#     THIS tree's own code and is excluded, as are acronyms that are not actors;
#   - a PASSIVE third-party agent ("committed by the agent", "by LW").
# Every one stays vetoed by a first-person git action anywhere on the line.
_THIRD_PARTY_AUX = r"\s+(?:(?:has|had|have|already|just|then|also|finally)\s+)*$"
_AGENT_NOUN = r"(?:agents?|subagents?|slices?|workers?|verifier|lanes?|sibling)"
_AGENT_ID = r"(?:[-_]\w{1,16}|\s+(?:[A-Z]|\d+|[a-z]*\d\w*))?"
CLAIM_COMMIT_THIRD_PARTY_LEAD = re.compile(
    r"\b(?:" + _AGENT_NOUN + _AGENT_ID + r"|they|he|she)(?:'s|s')?"
    + _THIRD_PARTY_AUX, re.I)
# Shouted prose is not a channel code: "THE COMMITTED FIX IS IN MAIN" must keep
# flagging, so English function words in capitals are refused too.
_NOT_A_CHANNEL_CODE = (r"(?:RC|CI|PR|HEAD|WIP|TODO|API|URL|OK|LF|CRLF|JSON|UI|DS|"
                       r"THE|THIS|THAT|ITS|AND|BUT|ALL|ANY|OUR|WE|US|IT|HE|SHE|"
                       r"YOU|NOT|NOW|THEN|ALSO|JUST|HAS|HAD|HAVE|WAS|IS|ARE|"
                       r"WERE|BEEN|SO|AS|ONE|EACH|BOTH|SOME|THEY|THEM)")
CLAIM_COMMIT_CHANNEL_CODE_LEAD = re.compile(
    r"(?<![\w-])(?!" + _NOT_A_CHANNEL_CODE + r"\b)[A-Z]{2,4}(?:'s)?"
    + _THIRD_PARTY_AUX)
CLAIM_COMMIT_THIRD_PARTY_BY = re.compile(
    r"\s+by\s+(?:(?:the|a|an|its|each|that|this)\s+)?(?:\w+\s+)?"
    r"(?:" + _AGENT_NOUN + r")\b", re.I)
CLAIM_COMMIT_CHANNEL_CODE_BY = re.compile(
    r"\s+by\s+(?!" + _NOT_A_CHANNEL_CODE + r"\b)[A-Z]{2,4}\b")
# Check 10 (merge), added 2026-10-04 on a verifier finding: "Merged to main."
# made no claim the gate could see - CLAIM_COMMIT and CLAIM_PUSH never read
# "merged" - although in this repo a merge to main IS a deployment. Narrow on
# purpose: the past participle plus a to/into/onto/on main|master target (up to
# three object words between, "merged it into main", "merged the slice branch
# into main"). Suppressed by the SAME guards as check 6 - a governing negation,
# a future/intent marker (CLAIM_CI_FUTURE, same 40-char window), attribution,
# and a third-party subject (agent noun, channel code, passive "by the agent")
# - all vetoed by a first-person git action anywhere on the line.
CLAIM_MERGE = re.compile(
    r"\bmerged\s+(?:[\w./'-]+\s+){0,3}?(?:to|into|onto|on)\s+"
    r"(?:the\s+)?(?:origin/)?(?:main|master)\b", re.I)
CLAIM_FULL_SUITE = re.compile(r"\b(?:full suite|all tests|entire suite|whole suite)\b", re.I)

# Evidence patterns.
EV_PYTEST = re.compile(r"(?:^|\s|-m\s)pytest\b", re.I)
# A CI-log fetch. ADDED 2026-09-06: this gate indexed only LOCAL pytest
# invocations, so a suite count read out of a CI log was never in
# observed_counts and every ACCURATE report of one scored as count_mismatch.
# Measured that session - a true "31706 passed" from `gh run view <id> --log`
# was flagged twice while the local runs topped out at 1869.
#
# That is worth fixing rather than tolerating: a gate that cries wolf on
# correctly-sourced figures trains the reader to wave it through, which is
# exactly when it stops catching the real thing. The same session it caught a
# genuine one - a "25 passed" computed as 28 minus 3 rather than observed.
#
# The binary is spelled `gh(?:\.exe)?`, matching EV_CI below. It was NOT, until
# 2026-09-10: the two patterns for the same binary had diverged by exactly one
# token, and this one required a literal `gh`. RC's prescribed invocation is a
# quoted absolute path, which strip_command_noise collapses to the basename, so
# the command reached this pattern as ` gh.exe  run view <id> --log`. The `.`
# broke `\bgh\s+run`, EV_CI_LOG returned False while EV_CI returned True on the
# very same string, and the fix above was inert for the way this repo actually
# fetches a log. Found by MEASUREMENT, not by reading - a frozen 91-transcript
# corpus put 4 of its 28 count_mismatch findings on this miss, across three
# unrelated shapes (a `>` redirect, a PowerShell `&` call operator, a `| grep`).
# Two patterns naming one binary must be kept in step; reading either alone
# gives the wrong answer.
#
# This widens only which COMMAND is recognised. What is credited from the
# fetched output is unchanged - `audit` still keeps CI counts to lines matching
# EV_SUMMARY_LINE, so a stale count echoed from a workflow comment is no more
# believable through this spelling than through the old one.
EV_CI_LOG = re.compile(r"\bgh(?:\.exe)?\s+run\s+view\b[^\n]*--log(?:-failed)?\b",
                       re.I)
# Node's built-in runner is the SECOND suite in this repo (rc-shell). Until
# 2026-08-11 the gate could not see it at all: it parsed only pytest's
# "N passed", so an accurate "rc-shell 328 passed" scored as count_mismatch -
# and, more seriously, a FALSE rc-shell claim could never have been caught
# either. Widening the evidence here is what makes the guard cover both suites.
EV_NODE_TEST = re.compile(r"\bnpm\s+(?:run\s+)?test\b|\bnode\b[^|;&\n]*--test\b", re.I)
# Node prints "<marker> pass 328", not "328 passed" - keyword first, no trailing
# "in X.Ys". Anchored to a WHOLE line whose only content is the marker, the
# keyword and the number, so prose containing the word "pass" cannot feed the
# observed set ("every check did pass 99 times" must not match, and does not).
#
# The prefix class is [^a-zA-Z] and NOT \W, which was the first attempt and was
# WRONG: node's marker is U+2139 INFORMATION SOURCE, and Python's Unicode-aware
# \w treats it as a WORD character, so \W* never matched it and the whole
# widening was silently inert. Measured, not assumed. The glyph is matched by
# class rather than written out because this file is 7-bit ASCII by repo rule.
EV_NODE_PASS = re.compile(r"^[^a-zA-Z\n]{0,4}pass\s+(\d[\d,]{0,9})\s*$", re.M)
EV_FILTERED = re.compile(r"\s-k\s|::|\btests?[\w/\\.-]*\.py\b"
                         # `node --test <one file>` is as filtered as `-k`.
                         r"|[\w/\\.-]+\.test\.[cm]?js\b", re.I)
# (?<!-): `--no-commit` (cherry-pick / revert / merge) is the OPPOSITE of
# committing, and \b alone let it count as evidence.
EV_COMMIT = re.compile(r"\bgit\b[^|;&]*(?<!-)\bcommit\b", re.I)
# Commit-CREATING subcommands other than `git commit` (measured 2026-10-04: a
# merger cherry-picked slices onto main, said "X is committed in <sha>", and was
# flagged). The subcommand must be git's FIRST non-option word, so `git log
# --grep=revert` or `git merge-base` cannot borrow it. cherry-pick / revert make
# a commit unless told not to; a plain `git merge` is NOT credited - it
# fast-forwards whenever it can and the command line cannot say which happened -
# so only `merge --no-ff` counts. Sequencer controls (--abort/--quit/--skip) and
# --no-commit / -n / --squash / --ff-only create nothing.
EV_COMMIT_CREATING = re.compile(
    r"\bgit\b(?:\s+-[Cc]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+"
    r"(cherry-pick|revert|merge)\b([^|;&\n]*)", re.I)
_NO_COMMIT_FLAG = re.compile(
    r"(?:^|\s)(?:--abort|--quit|--skip|--no-commit|--squash|--ff-only)(?=\s|$)")
_PICK_NO_COMMIT_SHORT = re.compile(r"(?:^|\s)-n(?=\s|$)")
_MERGE_NO_FF = re.compile(r"(?:^|\s)--no-ff(?=\s|$)")


def _creates_commit(command):
    """True when a cherry-pick / revert / `merge --no-ff` in COMMAND commits."""
    for match in EV_COMMIT_CREATING.finditer(command):
        sub, tail = match.group(1).lower(), match.group(2)
        if _NO_COMMIT_FLAG.search(tail):
            continue
        if sub == "merge":
            if _MERGE_NO_FF.search(tail):
                return True
            continue
        if not _PICK_NO_COMMIT_SHORT.search(tail):
            return True
    return False


# Check 9 / 10 evidence. The subcommand must be git's FIRST non-option word
# (measured 2026-10-04: `git ... push` anywhere credited `git stash push`, the
# stash form this environment prescribes, as a push, and `git merge-base` as a
# merge, silencing the unbacked claim). The -C/-c argument is OPTIONAL so a
# quoted path that strip_command_noise blanked cannot swallow the subcommand;
# the subcommand refuses a following [\w.-] so `-c push.default=x` and
# `merge-base` cannot match. A dry run (--dry-run / -n) uploads nothing, and a
# merge --abort / --quit merges nothing.
# KNOWN, NOT FIXED (round-4 verifier, 2026-10-08; filed as a follow-up):
# `git -c -c -c ...` repeated ~20 times backtracks exponentially here (6.1 s
# on the main path) - an unrealistic shape, pre-existing, left as is.
_GIT_LEAD = r"\bgit(?:\.exe)?(?:\s+-[Cc](?:\s+\S+)?|\s+--?[\w-]+(?:=\S+)?)*\s+"
_EV_PUSH = re.compile(_GIT_LEAD + r"push(?![\w.-])([^|;&\n]*)", re.I)
# The dry-run test is spelling-aware (RM-687 verifier, 2026-10-08: `-nv` and
# `--dry` were credited as real pushes). git accepts a short-option BUNDLE
# (`-nv`, `-vn`, `-fn`) and any unambiguous prefix of a long option (`--dr` up;
# `--d` is ambiguous with --delete), so both count as dry. In a bundle the scan
# stops at `o`: `-o` takes a value, so in `-onotify` the n is the value's. A
# SEPARATE token after `-o` is still scanned - deliberately strict, because a
# quoted -o value is already blanked by strip_command_noise and the next token
# may be the real flag. `--no-verify` is a long option and never reads as -n.
_PUSH_DRY_LONG = re.compile(r"--dr(?:y(?:-(?:r(?:u(?:n)?)?)?)?)?")
_EV_GIT_MERGE = re.compile(_GIT_LEAD + r"merge(?![\w.-])([^|;&\n]*)", re.I)
_MERGE_NO_OP = re.compile(r"(?:^|\s)(?:--abort|--quit)(?=\s|$)")
# `pr merge` is matched without the binary because RC invokes gh through a
# variable ("$GH" pr merge) - see EV_CI below.
_EV_PR_MERGE = re.compile(r"\bpr\s+merge\b", re.I)


def _push_is_dry(args):
    """True when the `git push` ARGS ask for a dry run, in any spelling git takes."""
    for token in args.split():
        if token.startswith("--"):
            if _PUSH_DRY_LONG.fullmatch(token):
                return True
        elif token.startswith("-"):
            for flag in token[1:]:
                if flag == "o":
                    break
                if flag == "n":
                    return True
    return False


def _did_push(command):
    """True when COMMAND runs a real (non-dry-run) `git push`."""
    return any(not _push_is_dry(m.group(1))
               for m in _EV_PUSH.finditer(command))


def _did_merge(command):
    """True when COMMAND runs a `git merge` (not --abort/--quit) or `pr merge`."""
    return bool(_EV_PR_MERGE.search(command)) or any(
        not _MERGE_NO_OP.search(m.group(1))
        for m in _EV_GIT_MERGE.finditer(command))
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
# RM-490: a run that died with pytest's own `INTERNALERROR>` marker is vacuous
# too - it produced no trustworthy verdict, even when it printed a count on the
# way down (LEDGER precedent: an xdist worker crash that misreported "22 failed",
# and an OOM `INTERNALERROR MemoryError` during a five-slice parallel run).
# Anchored on the line-leading marker pytest prints, so prose that merely NAMES
# the word does not poison a real run.
EV_VACUOUS = re.compile(r"no tests ran|collected 0 items|^\s*INTERNALERROR>",
                        re.I | re.M)
# A backgrounded run answers with a launcher handoff, not a summary. The real
# output lands later, when the output file is read by some unrelated command.
EV_BACKGROUND = re.compile(r"running in background with ID|Output is being written to",
                           re.I)
# RM-498: summary-bearing reads one backgrounded launch may be credited with.
# Two, because the largest legitimate single job is the dual suite (DS then RC);
# a bound, so one launch does not credit every summary-shaped line read for the
# rest of the session.
DEFERRED_SUMMARY_CAP = 2
# Deliberately the TERMINAL-SUMMARY shape, not a bare "N passed". Crediting any
# floating count is what poisoned the first armed gate; requiring the trailing
# duration is what keeps this a widening of evidence and not of belief.
EV_SUMMARY_LINE = re.compile(
    r"\d[\d,]*\s+(?:passed|failed|error)\b[^\n]*?\bin\s+[\d.]+\s*s"
    # Node's equivalent terminal marker: the duration line closing its summary
    # block. Same intent - a SUMMARY shape, never a floating count. Prefix class
    # is [^a-zA-Z] for the same measured reason as EV_NODE_PASS: node's U+2139
    # marker is a WORD character to Python's Unicode \w, so \W* never matches it.
    r"|^[^a-zA-Z\n]{0,4}duration_ms\s+[\d.]+\s*$", re.I | re.M)

EDIT_TOOLS = {"edit", "write", "multiedit", "notebookedit"}

# RM-421: the claim surface was chat prose only - an Edit/Write records its
# file_path and never its CONTENT, so a fabricated count written into a
# tracked file was invisible while the same sentence in chat was flagged.
# DECIDED narrow first cut (the row's own proposal): scan ONLY the content
# written into these two append-style trackers, with the EXISTING
# CLAIM_COUNT + strip_prose_noise, under a NEW check name that is ADVISORY -
# reported, never blocking - until its false-positive rate is scored apart
# from count_mismatch. Widening what is scanned is what poisoned the first
# armed session (LEDGER 1154), and a doc legitimately recites historical
# counts, so this neither widens to every file nor arms.
ARTIFACT_SCAN_BASENAMES = frozenset({"ledger.md", "backlog.md"})
# RM-687: subagent_hook_bypass (a sub-agent's `--no-verify` and kin) is
# advisory too - check 5 stays main-bash-only and blocking.
ADVISORY_CHECKS = frozenset({"artifact_count_mismatch", "subagent_hook_bypass"})


def _written_content(name, data):
    """The text an Edit / Write / MultiEdit puts on disk (new side only)."""
    if name == "write":
        return str(data.get("content") or "")
    if name == "edit":
        return str(data.get("new_string") or "")
    if name == "multiedit":
        return "\n".join(str(e.get("new_string") or "")
                         for e in (data.get("edits") or []) if isinstance(e, dict))
    return ""

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

# SIXTH shape in the false-reading family, and the FIRST that makes the gate
# blind rather than noisy - every fix above narrowed what would be FLAGGED, this
# one is a claim the gate never got to examine at all. RM-397, measured
# 2026-09-09.
#
# `_QUOTED` deletes everything between two single quotes. That is right for a
# COMMAND, where a single quote is a delimiter. It is wrong for PROSE, where a
# single quote is far more often an apostrophe: two ordinary possessives or
# contractions in one paragraph pair as if they opened and closed a quotation,
# and the span between them is deleted before the claim scan runs. Measured:
#   "The runner's log says 9999 passed, and the session's report agrees."
# strips to "The runner s report agrees." and CLAIM_COUNT finds nothing; the
# same sentence without apostrophes yields the claim.
#
# So prose gets its OWN pattern and `_QUOTED` is left alone for
# `strip_command_noise` - shell quoting has no possessives, and narrowing there
# would change evidence detection for commands, which is a different blast
# radius and not this defect.
#
# Only the single-quote branch changes. An apostrophe FLANKED BY WORD
# CHARACTERS can neither open a span nor close one, so "doesn't" inside a real
# quotation does not truncate it either - truncating would re-expose the tail as
# prose, which is the very false-positive class the stripping exists to stop.
# The inner alternation is unambiguous by construction (`[^']` never matches a
# quote, the second branch only matches a quote), so there is no nested-quantifier
# blowup: MEASURED on this machine at 0.44 ms for a 5000-char pathological input
# and 0.72 ms at 10000, i.e. linear, not exponential.
_QUOTED_PROSE = re.compile(
    r"(?<![A-Za-z0-9])'(?:[^']|(?<=[A-Za-z0-9])'(?=[A-Za-z0-9]))*'(?![A-Za-z0-9])"
    r"|\"[^\"]*\"", re.S)


# A quoted token that is an EXECUTABLE PATH is the command, not data. Windows
# forces the quotes - `C:\Program Files\GitHub CLI\gh.exe` cannot be written
# unquoted - so deleting it with the rest of the quoted literals made every CI
# probe on this machine invisible to EV_CI. MEASURED 2026-08-04: a session that
# ran `"C:/Program Files/GitHub CLI/gh.exe" run view <id>` seven times was still
# flagged ci_claim_without_probe, because after stripping, the command read
# ` run view <id>` with no `gh` token left for any pattern to see. The repo's
# own /done instructions mandate that absolute quoted path, so this was not an
# unusual way to invoke it - it was the prescribed one.
#
# The separator class is `[\\/]`, and the BACKSLASH half of it is RM-400, measured
# 2026-09-10. The original wrote `[\/]`, which inside a character class is a
# forward slash and nothing else - the escape is inert there. So only a
# POSIX-spelled path ever collapsed, and the NATIVE Windows spelling of the very
# same command, `"C:\Program Files\GitHub CLI\gh.exe" run view <id> --log`, matched
# no branch, fell through to `_QUOTED`, and was deleted whole. That is the exact
# 2026-08-04 end state this pattern was written to prevent, reached by a different
# spelling: EV_CI_LOG and EV_CI both saw ` run view <id> --log` with no binary in
# it, so the fetch was never indexed and its CI counts never reached
# observed_counts. Found incidentally by RM-398's final verifier, not by that fix.
#
# MEASURED over the same frozen 92-transcript corpus: 3 findings REMOVED, 0 added,
# 31 -> 28. All three are `ci_claim_without_probe` in ONE session that probed CI
# SEVEN times, every one of them `& "C:\Program Files\GitHub CLI\gh.exe" run ...`,
# and was told it had never probed. NOT ONE count_mismatch moved, and the reason
# is the OPPOSITE of the one first written here - a claim that this corpus held no
# backslash `run view --log` FETCH, which an adversarial pass REFUTED before it
# shipped. The fetch IS exercised: session 42af2f7d runs
# `& "C:\Program Files\GitHub CLI\gh.exe" run view <id> --log --job=...`, newly
# indexed by this fix (its ci_runs goes 0 -> 1). Its count stays flagged - but
# the reason written here was ITSELF REFUTED, re-measured 2026-09-10, and this
# is the second correction to the same sentence. The output does NOT carry a
# bare `28150 passed`. Hand-opened, the fetched lines read
# `28150 passed, 266 skipped, 8059` / `subtests passed in 1609.87s` / `(0:26:49)`
# - a GENUINE pytest terminal summary, hard-wrapped by that session's own
# `Select-String | Select-Object -Last 5` rendering. EV_SUMMARY_LINE is applied
# LINE BY LINE in the comprehension below, so the count and its `in <n>s`
# duration land on different physical lines and neither half matches alone.
# So this is a FALSE POSITIVE against a real summary, NOT a positive control.
# Corpus-wide it is the only one: of 60 indexed ci_runs across 24 sessions,
# exactly one carries a summary recoverable only by un-wrapping, and
# command-level misses are now ZERO. The fix is still not widened, and the
# reason is unchanged even though the fact under it moved - un-wrapping widens
# what is BELIEVED from output, not which command is recognised, and that is
# the direction this fence exists to refuse.
#
# The directory group stays OPTIONAL - a bare `"gh.exe"` has no separator and must
# still rewrite - and the lazy `[^"']*?` stops at the LAST separator before the
# basename, so a mixed-separator path pasted between shells resolves too.
#
# This widens only which COMMAND is recognised, never what is believed from its
# output: `audit` still keeps CI counts to lines matching EV_SUMMARY_LINE, so a
# stale count echoed from a workflow comment is no more creditable through this
# spelling than through the old one. Pinned by a test, not by this sentence.
_QUOTED_EXE = re.compile(r"""["']([^"']*?[\\/])?([\w.-]+\.exe)["']""", re.I)


def strip_command_noise(command):
    """A command's heredoc body and quoted literals are DATA, not the command.

    A quoted EXECUTABLE PATH is the exception: it collapses to its basename
    rather than vanishing, so the invoked binary survives for the evidence
    patterns while the surrounding prose-stripping is unchanged.
    """
    command = _QUOTED_EXE.sub(lambda m: " " + m.group(2) + " ", command)
    return _QUOTED.sub(" ", _HEREDOC.sub(" ", command))


def strip_prose_noise(text):
    """Fenced blocks, inline code and quoted spans are quotation, not assertion.

    Uses `_QUOTED_PROSE`, NOT `_QUOTED`: in prose an apostrophe is not a
    delimiter, and reading it as one deleted the claims between two possessives.
    """
    return _QUOTED_PROSE.sub(" ", _INLINE_CODE.sub(" ", _FENCED.sub(" ", text)))
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
    ev = {"texts": [], "bash": [], "edited": [], "runs": [], "ci_runs": [],
          "artifacts": []}
    pending = None
    # RM-498: one OPEN entry per backgrounded launch, each with room for
    # DEFERRED_SUMMARY_CAP summary-bearing reads. The old single per-session
    # slot, cleared on the first read, credited one count and dropped the rest:
    # a job running both suites, two concurrent jobs, and a later launch whose
    # slot an earlier harness-backgrounded run had swallowed were all measured
    # false positives on TRUE numbers.
    deferred = []
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
                    stripped = strip_command_noise(command)
                    if EV_PYTEST.search(stripped) or EV_NODE_TEST.search(stripped):
                        pending = {"cmd": command, "output": ""}
                        ev["runs"].append(pending)
                    elif EV_CI_LOG.search(stripped):
                        # Kept in a SEPARATE list, deliberately. Folding these
                        # into ev["runs"] would make ran_pytest true for a
                        # session that fetched a log and ran nothing, which would
                        # silently convert tests_pass_without_run into a pass -
                        # widening the gate's blind spot instead of its evidence.
                        pending = {"cmd": command, "output": ""}
                        ev["ci_runs"].append(pending)
                if name in EDIT_TOOLS:
                    target = data.get("file_path") or data.get("path") or ""
                    if target:
                        ev["edited"].append(str(target))
                        base = str(target).replace("\\", "/").rsplit("/", 1)[-1]
                        if base.lower() in ARTIFACT_SCAN_BASENAMES:
                            written = _written_content(name, data)
                            if written:
                                ev["artifacts"].append((str(target), written))
            elif kind == "tool_result":
                text = _result_text(block)
                if pending is not None:
                    pending["output"] = text
                    # A backgrounded run has not reported yet. Keep it open so
                    # its summaries can be attached when the output file is read.
                    if EV_BACKGROUND.search(text):
                        pending["_room"] = DEFERRED_SUMMARY_CAP
                        deferred.append(pending)
                    pending = None
                elif deferred and EV_SUMMARY_LINE.search(text):
                    # A deferred run finally speaking, through whatever command
                    # happened to read its output file. Attach to the OLDEST open
                    # launch with room left. Only the summary-shaped LINES are
                    # attached, never the whole result, so a floating count read
                    # alongside a real summary is not laundered into evidence.
                    target = deferred[0]
                    target["output"] += "\n" + "\n".join(
                        line for line in text.splitlines()
                        if EV_SUMMARY_LINE.search(line))
                    target["_room"] -= 1
                    if target["_room"] <= 0:
                        deferred.pop(0)
    for run in ev["runs"]:
        run.pop("_room", None)
    return ev


def _sentences_with_line(texts):
    """Split each text into lines, then each line into sentences on `_SENTENCE`,
    yielding every non-empty sentence paired with its enclosing LINE.

    Check 6 needs the line: the splitter breaks on ";", so a first-person git
    action in the next clause ("The agent committed X; I landed it") would
    otherwise be invisible to the veto."""
    for text in texts:
        for line in text.split("\n"):
            for part in _SENTENCE.split(line):
                part = part.strip()
                if part:
                    yield part, line


def _same_file(claimed, edited_paths):
    claim = claimed.replace("\\", "/").lower().lstrip("./")
    for path in edited_paths:
        actual = path.replace("\\", "/").lower()
        if actual.endswith(claim) or claim.endswith(actual):
            return True
    return False


def audit(ev):
    """Nine checks. Every finding cites the sentence that made the claim."""
    findings = []

    def _negated(sentence, claim_re):
        """True when a negation GOVERNS the claim word, not merely shares its
        sentence. Scoped to the 40 chars ahead of the match, so "I committed the
        fix, but not the docs" is still a claim while "nothing is committed yet"
        is its denial."""
        match = claim_re.search(sentence)
        if not match:
            return False
        return bool(CLAIM_NEGATION.search(sentence[max(0, match.start() - 40):match.start()]))

    def _attributed(sentence, claim_re, first_person=CLAIM_FIRST_PERSON_PUSHED):
        """True when the claim is ATTRIBUTED speech, not the speaker's own.

        See CLAIM_ATTRIBUTION. Scoped to check 9 (push) and check 6 (commit),
        each on MEASURED false positives: push first, then commit on 2026-09-20
        when three correct sentences from one session (two adjectival "the
        committed <noun>", one a build agent's commit) were flagged. It is still
        NOT applied to any other check - widening a suppression to a check
        whose false positives have not been observed is how a guard goes quiet.
        `first_person` is the per-check veto: a first-person completed action
        of the check's own verb anywhere in the sentence keeps it a claim.
        """
        match = claim_re.search(sentence)
        if not match:
            return False
        if first_person.search(sentence):
            return False
        lead = sentence[:match.start()]
        if CLAIM_ATTRIBUTION.search(lead):
            return True
        return bool(CLAIM_RELAY_HEAD.search(lead)
                    and not CLAIM_OWN_ACTION.search(lead))

    def _commit_speaker_claim(sentence, line):
        """True when some CLAIM_COMMIT match is plausibly the SPEAKER's own
        commit - i.e. not adjectival and not a third-party subject's. A
        first-person git action anywhere on the same LINE always counts (the
        sentence splitter breaks on ";", so "The agent committed X; I landed
        it" would otherwise hide the veto in the next clause), and an
        adjective never exempts a sentence asserting landed state."""
        if CLAIM_FIRST_PERSON_COMMITTED.search(line):
            return True
        landed = bool(CLAIM_COMMIT_LANDED_STATE.search(sentence))
        for match in CLAIM_COMMIT.finditer(sentence):
            lead = sentence[:match.start()]
            tail = sentence[match.end():]
            if (not landed and match.group(0).lower() == "committed"
                    and CLAIM_COMMIT_DETERMINER_LEAD.search(lead)
                    and CLAIM_COMMIT_ADJECTIVE_TAIL.match(tail)):
                continue
            if (CLAIM_COMMIT_THIRD_PARTY_LEAD.search(lead)
                    or CLAIM_COMMIT_CHANNEL_CODE_LEAD.search(lead)
                    or CLAIM_COMMIT_THIRD_PARTY_BY.match(tail)
                    or CLAIM_COMMIT_CHANNEL_CODE_BY.match(tail)):
                continue
            return True
        return False

    def _merge_speaker_claim(sentence, line):
        """Check 10's analogue of _commit_speaker_claim: True when some
        CLAIM_MERGE match is the SPEAKER's, i.e. not negated, not future, and
        not a third party's. A first-person git action on the line always
        counts."""
        if CLAIM_FIRST_PERSON_COMMITTED.search(line):
            return True
        for match in CLAIM_MERGE.finditer(sentence):
            lead = sentence[:match.start()]
            tail = sentence[match.end():]
            window = lead[-40:]
            if CLAIM_NEGATION.search(window) or CLAIM_CI_FUTURE.search(window):
                continue
            if (CLAIM_COMMIT_THIRD_PARTY_LEAD.search(lead)
                    or CLAIM_COMMIT_CHANNEL_CODE_LEAD.search(lead)
                    or CLAIM_COMMIT_THIRD_PARTY_BY.match(tail)
                    or CLAIM_COMMIT_CHANNEL_CODE_BY.match(tail)):
                continue
            return True
        return False

    def flag(check, quote, claimed="", observed=""):
        findings.append({"check": check, "quote": quote[:300],
                         "claimed": str(claimed), "observed": str(observed)})

    bash = [strip_command_noise(c) for c in ev["bash"]]
    runs = ev["runs"]
    ran_pytest = bool(runs)
    filtered_only = ran_pytest and all(EV_FILTERED.search(r["cmd"]) for r in runs)
    observed_counts = {m.replace(",", "") for r in runs
                       for pat in (EV_PASSED, EV_NODE_PASS)
                       for m in pat.findall(r["output"])}
    # CI-log counts are credited ONLY from a genuine terminal-summary line, never
    # from a bare "N passed" anywhere in the log. A CI log echoes the workflow
    # FILE, and workflow comments in this repo carry stale historical counts
    # ("# 19m42s / 23607 passed / ..."). Crediting those would let a fetch
    # launder every number printed anywhere in a workflow - a widening of
    # BELIEF, which is the failure this module's EV_SUMMARY_LINE note already
    # warns about. Same doctrine, applied to a second source.
    observed_counts |= {m.replace(",", "")
                        for r in ev.get("ci_runs", [])
                        for line in r["output"].splitlines()
                        if EV_SUMMARY_LINE.search(line)
                        for m in EV_PASSED.findall(line)}
    # Vacuous only if EVERY run was vacuous. One real green run answers the claim.
    vacuous = ran_pytest and all(EV_VACUOUS.search(r["output"]) for r in runs)
    # RM-687: the subagent_* flags are set only on main()'s MERGED evidence,
    # after a lazy read of THIS session's sub-agent transcripts; the result is
    # used credit-only (see CLEARABLE). did_merge inherits a sub-agent push.
    did_commit = (any(EV_COMMIT.search(c) or _creates_commit(c) for c in bash)
                  or bool(ev.get("subagent_commit")))
    did_push = any(_did_push(c) for c in bash) or bool(ev.get("subagent_push"))
    did_merge = (did_push or any(_did_merge(c) for c in bash)
                 or bool(ev.get("subagent_merge")))
    # EV_CI runs on the noise-stripped command; EV_CI_VAR must NOT, because
    # strip_command_noise deletes quoted literals and a `python -c "<script>"`
    # probe is ENTIRELY inside one quoted literal - stripped, it reduces to
    # `python -c` and no pattern could ever see it. Heredocs are still removed
    # for EV_CI_VAR, so a heredoc that DOCUMENTS a gh invocation stays data.
    raw_bash = [_HEREDOC.sub(" ", c) for c in ev["bash"]]
    probed_ci = (any(EV_CI.search(c) for c in bash)
                 or any(EV_CI_VAR.search(c) for c in raw_bash)
                 or bool(ev.get("subagent_ci")))

    # 5 - evidence-only check. Requires an actual git invocation: a bypass flag
    # NAMED in prose or a heredoc body is documentation, not a bypass.
    for command in bash:
        if EV_BYPASS.search(command) and re.search(r"\bgit\b", command):
            flag("hook_bypass", command, observed=command)

    for sentence, line in _sentences_with_line(
            strip_prose_noise(t) for t in ev["texts"]):
        claims_pass = bool(CLAIM_TESTS_PASS.search(sentence))
        if claims_pass and not ran_pytest:
            flag("tests_pass_without_run", sentence)                       # 1
        if claims_pass and vacuous:
            flag("vacuous_run", sentence, observed="no tests ran")         # 8
        if claims_pass and CLAIM_FULL_SUITE.search(sentence) and filtered_only:
            flag("full_suite_claim_over_filtered_run", sentence,           # 7
                 observed="; ".join(r["cmd"] for r in runs))
        for prefix, count in CLAIM_COUNT.findall(sentence):
            if prefix.lower() in CLAIM_COUNT_ORDINAL:
                continue
            # Space-grouped thousands - see CLAIM_COUNT_GROUPED. The shape is
            # necessary but NOT sufficient: suppress only when the JOINED form
            # was actually observed, otherwise fall through and flag the
            # trailing group exactly as before.
            joined = prefix + count
            if (CLAIM_COUNT_GROUPED.match(prefix) and len(count) == 3
                    and "," not in count and joined in observed_counts):
                continue
            bare = count.replace(",", "")
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
            if not _same_file(path, ev["edited"]):
                flag("file_claim_without_edit", sentence, claimed=path)    # 3
        ci_match = CLAIM_CI.search(sentence)
        if (ci_match and not probed_ci
                and not CLAIM_CI_FUTURE.search(
                    sentence[max(0, ci_match.start() - 40):ci_match.start()])):
            flag("ci_claim_without_probe", sentence)                       # 4
        if (CLAIM_COMMIT.search(sentence) and not did_commit
                and not _negated(sentence, CLAIM_COMMIT)
                and _commit_speaker_claim(sentence, line)
                and not _attributed(sentence, CLAIM_COMMIT,
                                    CLAIM_FIRST_PERSON_COMMITTED)):
            flag("commit_claim_without_commit", sentence)                  # 6
        if (CLAIM_PUSH.search(sentence) and not did_push
                and not _negated(sentence, CLAIM_PUSH)
                and not _attributed(sentence, CLAIM_PUSH)):
            flag("push_claim_without_push", sentence)                      # 9
        if (not did_merge and CLAIM_MERGE.search(sentence)
                and _merge_speaker_claim(sentence, line)
                and not _attributed(sentence, CLAIM_MERGE,
                                    CLAIM_FIRST_PERSON_COMMITTED)):
            flag("merge_claim_without_merge", sentence)                    # 10
    # RM-421 - ADVISORY, see ARTIFACT_SCAN_BASENAMES. Same claim regex and
    # the same observed-counts evidence as count_mismatch; only the surface
    # differs. Never fires without observed counts (nothing to contradict).
    for target, written in ev.get("artifacts", []):
        cleaned = strip_prose_noise(written)
        for prefix, count in CLAIM_COUNT.findall(cleaned):
            if prefix.lower() in CLAIM_COUNT_ORDINAL:
                continue
            bare = count.replace(",", "")
            if observed_counts and bare not in observed_counts:
                flag("artifact_count_mismatch", f"{target}: {count} passed",
                     claimed=bare, observed=", ".join(sorted(observed_counts)))
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


# RM-687: sub-agent evidence. Under kit v10 SUBAGENT-FIRST deny mode the main
# thread cannot run pytest, gh, git or Edit, so every such act is a sub-agent's
# - and a sub-agent's tool rows are NOT in the main transcript (measured
# 2026-10-08, CLI 2.1.294: session 9f5488a7 held 135 main rows, 0 of them
# isSidechain). They live beside it in
# `<transcript minus .jsonl>/subagents/agent-<agentId>.jsonl`, nested agents in
# the same flat dir, so every relayed result flagged although a sub-agent had
# produced it. main() reads them LAZILY (only when a CLEARABLE finding would
# otherwise stand) and only for THIS session's dir.
#
# SUB-AGENT EVIDENCE IS CREDIT-ONLY (coordinator order, 2026-10-08): the final
# findings are the main-only findings that ALSO survive an audit over main plus
# sub-agent evidence, matched on (check, quote, claimed), plus a merged finding
# only on a sentence whose main finding was cleared (a narrower REPLACEMENT,
# see credit_only). It never flags a sentence main did not flag - so a relayed
# sum can never newly fire count_mismatch. A sub-agent run that is vacuous
# (EV_VACUOUS, incl. INTERNALERROR) never credits. Every kind pairs a tool_use
# to its tool_result by id,
# never by adjacency (sub-agents issue parallel calls), and none credits from a
# backgrounded call or a launch-handoff result except test runs, which use the
# same deferred mechanism as collect_evidence within the one sub-agent file:
#   tests   (1/2/7/8) pytest / node-test / CI-log calls whose output carries a
#                     passed count (CI logs: summary lines only);
#   edits   (3)       Edit / Write / MultiEdit / NotebookEdit not is_error;
#   CI      (4)       the same command-only EV_CI / EV_CI_VAR bar as main;
#   commit  (6)       a commit-creating command whose output has git's
#                     `[<branch> <sha>] ` line (merge --no-ff: "Merge made by");
#   merge   (10)      a merge with a success line and no conflict / fatal /
#                     error line, or `pr merge` not is_error;
#   push    (9)       see _pair_credit.
# Sub-agent commands never enter ev["bash"] (main's command-only rules would
# credit them); each kind sets its own flag. Prose and Agent/Task prompts never
# credit. Check 6 is widened here on an OBSERVED false positive: under deny mode
# every relayed commit claim flagged (the _attributed doctrine is met).
# NOT changed: artifact_count_mismatch (RM-421) audits what the MAIN thread
# wrote into LEDGER / BACKLOG; a sub-agent's writes there are a different
# speaker's, so that check stays main-only. A sub-agent's `--no-verify` is the
# ADVISORY check subagent_hook_bypass, computed only when the files were loaded.
CLEARABLE = frozenset({
    "tests_pass_without_run", "vacuous_run", "full_suite_claim_over_filtered_run",
    "count_mismatch", "file_claim_without_edit", "ci_claim_without_probe",
    "commit_claim_without_commit", "push_claim_without_push",
    "merge_claim_without_merge"})
SUBAGENT_FILE_MAX = 64 * 1024 * 1024
SUBAGENT_TOTAL_MAX = 256 * 1024 * 1024
# A command longer than this is not parsed for an ancestry probe (re-verifier:
# 30k spaces after the probe took 4 s through the old tail regex).
COMMAND_PARSE_MAX = 20000
_SUBAGENT_LABEL = re.compile(r"[A-Za-z0-9_-]{1,64}")
# The scan must never raise out of a Stop hook. A tuple, not a blind
# `except Exception` (ruff BLE ratchet); it covers JSON junk, odd row shapes,
# unreadable files and a directory named like a transcript.
_SCAN_ERRORS = (OSError, ValueError, TypeError, AttributeError, LookupError,
                RuntimeError, MemoryError, OverflowError, re.error)
# A backgrounded call (input run_in_background, or a launch-handoff result in
# the EV_BACKGROUND shape) has no observed outcome yet, so it credits NO kind.
# Every output regex below is matched one LINE at a time, and a line longer
# than this is skipped unmatched (and closes a push block): the first cut's
# `^\s*[+*]?\s*` took ~9 s on one 30k-whitespace line (RM-687 verifier).
OUTPUT_LINE_MAX = 1000
#
# ACCEPTED RESIDUE, recorded so it is not re-found as a defect (RM-687 verifier,
# 2026-10-08). (1) FORGERY: a command that hand-echoes a ref-update line, an
# `Everything up-to-date` line or a `<prefix>0` line is credited - output-text
# evidence cannot defend against deliberate forgery. Accepted because the
# main-thread check 9 credits a bare `git push` COMMAND with no output check at
# all, so this evidence is strictly stronger than the existing bar, and the
# gate's threat model is an honest-mistake unbacked claim, not an adversarial
# agent. (2) BINDING: an ancestry probe is tied neither to the CLAIMED sha nor
# to session time (any commit already on the remote credits), and a reflog line
# is time-bound but not sha-bound. The claim side names no sha to bind to.

# Kind "push": a real `git push` (same _did_push discipline: first subcommand,
# dry run excluded, so `git stash push` never counts) whose OUTPUT carries a
# ref-update success line. The flag column must be blank, + or *, so
# `! [rejected]` / `! [remote rejected]` cannot match. is_error is NOT a signal:
# the measured real push came back is_error TRUE because a later command on the
# same line failed ("fatal: Needed a single revision").
#
# POSITIVELY anchored (RM-687 verifier: a rejected push followed by
# `git fetch origin 2>&1 | tail -1` was credited off the fetch's update line,
# its `From <url>` header cut by the tail). git prints `To <url>` and then every
# ref status line contiguously (transport print_ref_status), so a success line
# counts only inside that block; any other line closes it - a fetch's `From`
# header, a rejection's `error:` line, a blank or overlong line. A fetch-shaped
# destination (`-> origin/...`, `-> refs/remotes/...`, `-> FETCH_HEAD`, and
# `-> <remote>/...` for every remote a fetch / pull / `remote update` in the SAME
# command names; `--all` or a bare `remote update` makes any `<x>/<y>` fetch
# shaped) never counts, even inside a block (re-verifier: `git fetch upstream`
# after a `| head -2` push). And a call holding ANY dry-run push never credits a
# push (re-verifier: `git push -n backup main; git push origin main` with the
# real push rejected). No adjacent ambiguous quantifiers anywhere.
_PUSH_TO_HEADER = re.compile(r"^To[ \t]+\S")
_PUSH_STATUS = re.compile(
    r"^[ \t]*(?:[-+*!=][ \t]+)?"
    r"(?:[0-9a-f]{7,40}\.\.\.?[0-9a-f]{7,40}|\[[a-z ]{1,40}\])[ \t]")
_PUSH_REF_OK = re.compile(
    r"^[ \t]*(?:[+*][ \t]+)?(?:[0-9a-f]{7,40}\.\.\.?[0-9a-f]{7,40}"
    r"|\[new (?:branch|tag|reference)\])[ \t]+\S+[ \t]+->[ \t]+(\S+)")
_PUSH_UP_TO_DATE = re.compile(r"^Everything up-to-date[ \t]*$")
# Every positional argument of a fetch / pull / `remote update` is taken as a
# remote name - a deliberate superset of "the first non-option argument", so a
# separate option value (`--depth 3 upstream`) cannot hide the real remote.
_EV_FETCH = re.compile(_GIT_LEAD + r"(fetch|pull|remote[ \t]+update)(?![\w.-])([^|;&\n]*)",
                       re.I)

# Kind "ancestry": `git merge-base --is-ancestor <rev> <ref>` where <ref> is a
# REMOTE-TRACKING ref, matched on a quote-MASKED copy of the command (same
# length, so spans map back to the raw text): a quoted literal naming the probe
# is data. Its success must be OBSERVABLE - either nothing but redirections
# follows it up to end-of-command or `&&` (and the result is not an error), or
# the next statement echoes `$?` / `$LASTEXITCODE` and the output carries that
# literal prefix followed by 0.
_EV_ANCESTRY = re.compile(
    _GIT_LEAD + r"merge-base(?![\w.-])[ \t]+--is-ancestor[ \t]+"
    r"(?P<rev>[^\s;&|<>()]+)[ \t]+(?P<ref>[^\s;&|<>()]+)", re.I)
# The tail after the probe is walked by hand (_ancestry_tail), one redirection
# token at a time: the old single regex put `[ \t]*` beside `\s*` and went
# quadratic on a run of spaces (re-verifier, 2026-10-08).
_REDIRECT = re.compile(r"(?:[0-9]+|&|\*)?>>?(?:&[0-9-]|[ \t]*[^\s;&|<>]+)|<[ \t]*[^\s;&|<>]+")
# After `&&`, a `;`, newline, `||` or background `&` would let a LATER statement
# decide is_error, so the probe's exit status would no longer be observable.
_CHAIN_BREAK = re.compile(r"[;\n]|\|\||(?<![&>])&(?![&>])")
_STATUS_ECHO = re.compile(r"(?:echo|write-output|printf)[ \t]+(?P<arg>[^;\n&|]*)", re.I)
_STATUS_VAR = re.compile(r"\$\?|\$LASTEXITCODE\b", re.I)
_HAS_LETTER = re.compile(r"[A-Za-z]")

# Kind "reflog": `git reflog` or `git log -g/--walk-reflogs` whose output dates
# an `update by push` at or after the session start. Undated `@{N}` lines and
# lines without a timezone never credit.
_EV_REFLOG = re.compile(_GIT_LEAD + r"(reflog|log)(?![\w.-])([^|;&\n]*)", re.I)
_REFLOG_WALK = re.compile(r"(?:^|\s)(?:-g|--walk-reflogs)(?=\s|$)")
_REFLOG_PUSH = re.compile(
    r"@\{(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})[ \t]*([+-]\d{2}:?\d{2}|Z)\}: update by push")


def subagent_dir(transcript_path):
    """THIS session's sub-agent transcript dir: `<transcript minus suffix>/subagents`."""
    return Path(transcript_path).with_suffix("") / "subagents"


def _subagent_files(directory):
    """`agent-*.jsonl` FILES directly in DIRECTORY (flat) as (path, size),
    newest mtime first; anything over SUBAGENT_FILE_MAX or not a regular file
    is skipped."""
    found = []
    if not directory.is_dir():
        return found
    for path in directory.glob("agent-*.jsonl"):
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except _SCAN_ERRORS:
            continue
        if stat.st_size <= SUBAGENT_FILE_MAX:
            found.append((stat.st_mtime, path, stat.st_size))
    found.sort(key=lambda item: item[0], reverse=True)
    return [(path, size) for _mtime, path, size in found]


def _agent_label(path):
    label = path.stem[len("agent-"):]
    return label if _SUBAGENT_LABEL.fullmatch(label) else ""


def _tool_text(content):
    """A tool_result's text; list parts are joined by NEWLINE so line anchors hold."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part["text"] for part in content
                         if isinstance(part, dict) and isinstance(part.get("text"), str))
    return ""


def _output_lines(output):
    """OUTPUT's lines, each overlong one replaced by None (skipped unmatched)."""
    return [line if len(line) <= OUTPUT_LINE_MAX else None
            for line in output.splitlines()]


def _fetch_remotes(stripped):
    """(remote names, any_remote) that a fetch / pull / `remote update` in the
    noise-stripped command updates. A bare fetch / pull is origin; `--all` or a
    bare `remote update` is any remote."""
    names, any_remote = {"origin"}, False
    for match in _EV_FETCH.finditer(stripped):
        args = match.group(2).split()
        positional = [a for a in args if not a.startswith("-") and not set(a) & set("<>")]
        if "--all" in args or (match.group(1).lower().startswith("remote") and not positional):
            any_remote = True
        names.update(positional)
    return names, any_remote


def _fetch_shaped(dst, remotes, any_remote):
    """True when DST is a remote-tracking / fetch destination, never a push's."""
    if dst == "FETCH_HEAD" or dst.startswith("refs/remotes/"):
        return True
    if any_remote and "/" in dst:
        return True
    return any(dst.startswith(name + "/") for name in remotes)


def _push_output_ok(output, remotes=frozenset({"origin"}), any_remote=False):
    """True when OUTPUT carries a ref-update success line INSIDE a git push
    `To <url>` status block (see _PUSH_TO_HEADER) whose destination is not
    fetch shaped, or `Everything up-to-date`."""
    in_block = False
    for line in _output_lines(output):
        if line is None:
            in_block = False
        elif _PUSH_TO_HEADER.match(line):
            in_block = True
        elif _PUSH_UP_TO_DATE.match(line):
            return True
        elif in_block:
            ok = _PUSH_REF_OK.match(line)
            if ok and not _fetch_shaped(ok.group(1), remotes, any_remote):
                return True
            in_block = bool(ok or _PUSH_STATUS.match(line))
    return False


def _remote_tracking(ref):
    low = ref.lower()
    return (ref.startswith(("origin/", "refs/remotes/"))
            or any(tag in low for tag in ("@{u}", "@{upstream}", "@{push}")))


def _echoed_zero(arg, output):
    """True when ARG (an echo argument, raw) reads `$?` / `$LASTEXITCODE` and
    OUTPUT has a line that is exactly the argument's literal prefix plus 0."""
    arg = arg.strip()
    status = _STATUS_VAR.search(arg)
    if not status:
        return False
    lead = arg[:status.start()]
    if lead.count("'") % 2:
        return False  # inside single quotes the variable is never expanded
    prefix = lead.replace('"', "").replace("'", "")
    if "$" in prefix or "`" in prefix:
        return False  # not a literal prefix
    if not _HAS_LETTER.search(prefix):
        # A bare `echo $?` prints a lone 0 that any honest `wc -l` or
        # `rev-list --count` beside it can also print (re-verifier, 2026-10-08):
        # the prefix must name the probe, e.g. `rc=` / `ancestor_exit=`.
        return False
    want = prefix + "0"
    return any(line is not None and line.rstrip() == want
               for line in _output_lines(output))


def _skip_blanks(text, pos, blanks=" \t"):
    while pos < len(text) and text[pos] in blanks:
        pos += 1
    return pos


def _ancestry_tail(masked, pos):
    """Walk the tail after a probe: skip redirections, then return
    ("end", None), ("and", <rest>), ("next", <start of next statement>) or
    (None, None). Linear: one token at a time, no regex backtracking."""
    while True:
        pos = _skip_blanks(masked, pos)
        redirect = _REDIRECT.match(masked, pos)
        if not redirect:
            break
        pos = redirect.end()
    if not masked[pos:].strip():
        return "end", None
    if masked.startswith("&&", pos):
        return "and", masked[pos + 2:]
    pos = _skip_blanks(masked, pos, "\r")
    if pos < len(masked) and masked[pos] in ";\n":
        return "next", _skip_blanks(masked, pos + 1, " \t\r\n")
    return None, None


def _ancestry_ok(command, output, errored):
    """True when COMMAND observably proved `<rev>` is an ancestor of a
    remote-tracking ref. See _EV_ANCESTRY. A command over COMMAND_PARSE_MAX
    chars is not parsed at all."""
    if len(command) > COMMAND_PARSE_MAX:
        return False
    raw = _HEREDOC.sub(" ", _QUOTED_EXE.sub(lambda m: " " + m.group(2) + " ", command))
    masked = _QUOTED.sub(lambda m: "x" * len(m.group(0)), raw)
    for match in _EV_ANCESTRY.finditer(masked):
        ref = raw[match.start("ref"):match.end("ref")].replace('"', "").replace("'", "")
        if not _remote_tracking(ref):
            continue
        if masked[:match.start()].rstrip().endswith(("||", "!")):
            continue  # `x || probe` may never run it; `! probe` inverts it
        shape, tail = _ancestry_tail(masked, match.end())
        if shape == "end" and not errored:
            return True
        if shape == "and" and not errored and not _CHAIN_BREAK.search(tail):
            return True
        if shape == "next":
            echo = _STATUS_ECHO.match(masked, tail)
            if echo and _echoed_zero(raw[echo.start("arg"):echo.end("arg")], output):
                return True
    return False


def _reflog_time(day, clock, zone):
    try:
        if zone == "Z":
            tz = timezone.utc
        else:
            digits = zone[1:].replace(":", "")
            offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
            tz = timezone(-offset if zone[0] == "-" else offset)
        return datetime.strptime(day + " " + clock, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
    except ValueError:
        return None


def _reflog_ok(command, output, session_start):
    """True when COMMAND walks a reflog and OUTPUT dates an `update by push` at
    or after SESSION_START (timezone-aware)."""
    walks = any(m.group(1).lower() == "reflog" or _REFLOG_WALK.search(m.group(2))
                for m in _EV_REFLOG.finditer(strip_command_noise(command)))
    if not walks:
        return False
    for line in _output_lines(output):
        for match in _REFLOG_PUSH.finditer(line or ""):
            stamp = _reflog_time(*match.groups())
            if stamp is not None and stamp >= session_start:
                return True
    return False


def _pair_credit(command, output, errored, session_start):
    """The push evidence kind one paired sub-agent call credits, or None. A
    background-launch result credits nothing (see OUTPUT_LINE_MAX notes)."""
    if EV_BACKGROUND.search(output):
        return None
    stripped = strip_command_noise(command)
    pushes = list(_EV_PUSH.finditer(stripped))
    if (pushes and not any(_push_is_dry(m.group(1)) for m in pushes)
            and _push_output_ok(output, *_fetch_remotes(stripped))):
        return "push"
    if _ancestry_ok(command, output, errored):
        return "ancestry"
    if session_start is not None and _reflog_ok(command, output, session_start):
        return "reflog"
    return None


# Commit (check 6) and merge (check 10) output shapes. Matched per line on
# lines no longer than OUTPUT_LINE_MAX; the failure markers are searched over
# the whole result, so an overlong line can only ever withhold credit.
_COMMIT_LINE = re.compile(r"^\[[^\]\n]+ [0-9a-f]{7,40}\] ")
_MERGE_OK = re.compile(r"^Updating [0-9a-f]{7,}\.\.[0-9a-f]{7,}|^Fast-forward"
                       r"|Merge made by|Already up[ -]to[ -]date")
_MERGE_BAD = re.compile(r"CONFLICT|Automatic merge failed|^fatal:|^error:", re.M)


def _commit_output_ok(stripped, output):
    if any(line is not None and _COMMIT_LINE.match(line) for line in _output_lines(output)):
        return True
    return "Merge made by" in output and _creates_commit(stripped)


def _merge_output_ok(stripped, output, errored):
    if _EV_PR_MERGE.search(stripped) and not errored:
        return True
    if not any(not _MERGE_NO_OP.search(m.group(1)) for m in _EV_GIT_MERGE.finditer(stripped)):
        return False
    return (any(line is not None and _MERGE_OK.search(line) for line in _output_lines(output))
            and not _MERGE_BAD.search(output))


def _new_subagent_evidence():
    return {"runs": [], "ci_runs": [], "edited": [], "ci": False, "commit": False,
            "merge": False, "push": None, "bypass": []}


def _tool_use_of(block):
    """(id, name, input) of a usable tool_use block, else None."""
    tid, name, data = block.get("id"), block.get("name"), block.get("input")
    if isinstance(tid, str) and isinstance(name, str) and isinstance(data, dict):
        return tid, name.lower(), data
    return None


def _scan_subagent_file(path, session_start=None):
    """Every evidence kind in ONE sub-agent transcript (see CLEARABLE). Results
    are taken in file order and paired to their tool_use by id; a junk row or
    block is skipped on its own and never voids the file."""
    found = _new_subagent_evidence()
    uses, runs, deferred = {}, [], []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "tool_" not in line:
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(row, dict):
                continue
            for block in _blocks(row):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    use = _tool_use_of(block)
                    if use and use[0] not in uses:
                        uses[use[0]] = use
                        _note_bypass(found, use)
                elif block.get("type") == "tool_result":
                    tid = block.get("tool_use_id")
                    use = uses.pop(tid, None) if isinstance(tid, str) else None
                    _absorb_result(found, runs, deferred, use, _tool_text(block.get("content")),
                                   block.get("is_error") is True, session_start)
    for run in runs:
        run.pop("_room", None)
        if run["ci"]:
            if any(EV_SUMMARY_LINE.search(line) and EV_PASSED.search(line)
                   for line in run["output"].splitlines()):
                found["ci_runs"].append({"cmd": run["cmd"], "output": run["output"]})
        elif EV_VACUOUS.search(run["output"]):
            # A vacuous / INTERNALERROR run never credits, even when it printed
            # a count on the way down - in the main thread the same output
            # scores vacuous_run (RM-490). Round-4 verifier, 2026-10-08.
            continue
        elif EV_PASSED.search(run["output"]) or EV_NODE_PASS.search(run["output"]):
            found["runs"].append({"cmd": run["cmd"], "output": run["output"]})
    return found


def _note_bypass(found, use):
    _tid, name, data = use
    command = data.get("command")
    if name in ("bash", "powershell") and isinstance(command, str):
        stripped = strip_command_noise(command)
        if EV_BYPASS.search(stripped) and re.search(r"\bgit\b", stripped):
            found["bypass"].append(command)


def _absorb_result(found, runs, deferred, use, text, errored, session_start):
    """Fold one tool_result (and its paired tool_use, if any) into FOUND."""
    _tid, name, data = use if use else (None, "", {})
    command = data.get("command") if name in ("bash", "powershell") else None
    stripped = strip_command_noise(command) if isinstance(command, str) else ""
    is_run = bool(stripped) and bool(EV_PYTEST.search(stripped) or EV_NODE_TEST.search(stripped))
    is_ci_log = bool(stripped) and not is_run and bool(EV_CI_LOG.search(stripped))
    background = bool(data.get("run_in_background")) or bool(EV_BACKGROUND.search(text))
    if is_run or is_ci_log:
        # Same deferred mechanism as collect_evidence: a backgrounded launch
        # stays open for its summary lines, read later by any other call.
        run = {"cmd": command, "output": text, "ci": is_ci_log}
        runs.append(run)
        if background:
            run["_room"] = DEFERRED_SUMMARY_CAP
            deferred.append(run)
    elif deferred and EV_SUMMARY_LINE.search(text):
        target = deferred[0]
        target["output"] += "\n" + "\n".join(
            line for line in text.splitlines() if EV_SUMMARY_LINE.search(line))
        target["_room"] -= 1
        if target["_room"] <= 0:
            deferred.pop(0)
    if use is None or background:
        return
    if name in EDIT_TOOLS:
        target = data.get("file_path") or data.get("path") or data.get("notebook_path")
        if isinstance(target, str) and target and not errored:
            found["edited"].append(target)
        return
    if not stripped:
        return
    if EV_CI.search(stripped) or EV_CI_VAR.search(_HEREDOC.sub(" ", command)):
        found["ci"] = True
    if (EV_COMMIT.search(stripped) or _creates_commit(stripped)) and _commit_output_ok(stripped, text):
        found["commit"] = True
    if _did_merge(stripped) and _merge_output_ok(stripped, text, errored):
        found["merge"] = True
    if found["push"] is None:
        found["push"] = _pair_credit(command, text, errored, session_start)


def subagent_evidence(transcript_path, session_start=None):
    """Evidence from THIS session's sub-agent transcripts, merged across files
    read newest first within SUBAGENT_TOTAL_MAX bytes, or None when there is no
    file to read. "push" is {"kind", "agent"} for the first push credit found.
    A file that fails is no evidence; this never raises out of the hook.
    SESSION_START None disables the reflog push kind."""
    try:
        files = _subagent_files(subagent_dir(transcript_path))
    except _SCAN_ERRORS:
        return None
    if not files:
        return None
    total, budget = _new_subagent_evidence(), SUBAGENT_TOTAL_MAX
    for path, size in files:
        if size > budget:
            break
        budget -= size
        try:
            part = _scan_subagent_file(path, session_start)
            label = _agent_label(path)
        except _SCAN_ERRORS:
            continue
        for key in ("runs", "ci_runs", "edited"):
            total[key].extend(part[key])
        for key in ("ci", "commit", "merge"):
            total[key] = total[key] or part[key]
        total["bypass"].extend((label, command) for command in part["bypass"])
        if total["push"] is None and part["push"]:
            total["push"] = {"kind": part["push"], "agent": label}
    return total


def subagent_push_evidence(transcript_path, session_start=None):
    """The first push credit in THIS session's sub-agent transcripts, as
    {"kind": "push"|"ancestry"|"reflog", "agent": "<agentId or ''>"}, else None."""
    found = subagent_evidence(transcript_path, session_start)
    return found["push"] if found else None


def _merge_evidence(ev, sub):
    """EV plus sub-agent evidence. Sub-agent commands never enter "bash"."""
    merged = dict(ev)
    merged["runs"] = list(ev.get("runs", [])) + sub["runs"]
    merged["ci_runs"] = list(ev.get("ci_runs", [])) + sub["ci_runs"]
    merged["edited"] = list(ev.get("edited", [])) + sub["edited"]
    merged["subagent_ci"] = sub["ci"]
    merged["subagent_commit"] = sub["commit"]
    merged["subagent_merge"] = sub["merge"]
    merged["subagent_push"] = bool(sub["push"])
    return merged


def _finding_key(finding):
    return finding["check"], finding["quote"], finding["claimed"]


def credit_only(main_findings, merged_findings):
    """(kept, cleared). A CLEARABLE main finding survives only when the merged
    audit still raises it. A merged finding is added ONLY on a sentence whose
    main finding was cleared: sub-agent evidence may REPLACE a flag on an
    already-flagged sentence with a narrower one (tests_pass_without_run ->
    full_suite_claim_over_filtered_run after a `-k` sub-agent run, or ->
    count_mismatch), but never flags a sentence main did not flag (round-4
    verifier, 2026-10-08)."""
    still = {_finding_key(f) for f in merged_findings}
    kept, removed = [], []
    for finding in main_findings:
        if finding["check"] not in CLEARABLE or _finding_key(finding) in still:
            kept.append(finding)
        else:
            removed.append(finding)
    cleared_quotes = {f["quote"] for f in removed}
    have = {_finding_key(f) for f in kept}
    for finding in merged_findings:
        key = _finding_key(finding)
        if finding["quote"] in cleared_quotes and key not in have:
            kept.append(finding)
            have.add(key)
    return kept, sorted({f["check"] for f in removed})


def _bypass_findings(sub):
    """ADVISORY subagent_hook_bypass findings, one per distinct command."""
    findings, seen = [], set()
    for label, command in sub["bypass"]:
        if command in seen:
            continue
        seen.add(command)
        findings.append({"check": "subagent_hook_bypass", "quote": command[:300],
                         "claimed": "", "observed": "agent " + (label or "?")})
    return findings


def _parse_aware(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.utcoffset() is not None else None


def _session_start(rows):
    """Earliest parseable, timezone-aware top-level `timestamp` in the MAIN
    transcript rows, or None (which disables the reflog kind)."""
    earliest = None
    try:
        for row in rows or ():
            if isinstance(row, dict):
                stamp = _parse_aware(row.get("timestamp"))
                if stamp is not None and (earliest is None or stamp < earliest):
                    earliest = stamp
    except _SCAN_ERRORS:
        return None
    return earliest


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
                        help="emit one Stop-feedback JSON line on findings; OFF by default and stays off "
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

    rows = read_transcript(transcript)
    ev = collect_evidence(rows)
    findings = audit(ev)
    # RM-687: LAZY - sub-agent transcripts are read only when a CLEARABLE
    # finding would otherwise stand, so the common Stop reads nothing extra.
    # CREDIT-ONLY - see credit_only. Any failure keeps the main-only findings.
    if any(f["check"] in CLEARABLE for f in findings):
        sub = subagent_evidence(transcript, _session_start(rows))
        if sub is not None:
            try:
                kept, cleared = credit_only(findings, audit(_merge_evidence(ev, sub)))
                findings = kept + _bypass_findings(sub)
                report["subagent_cleared"] = cleared
                if sub["push"]:
                    report["subagent_push"] = sub["push"]
            except _SCAN_ERRORS:
                pass
    report["findings"] = findings

    # A firing gate keeps the session from ending and hands its feedback line to
    # the model (it was exit 2 + stderr until 2026-10-07). So re-entry is the hazard: if the model restates the claim, a second
    # block loops forever. `stop_hook_active` is true once we have already
    # blocked, and it is the only thing standing between armed mode and a spin.
    reentry = bool(payload.get("stop_hook_active"))
    # RM-421: advisory checks are reported and recorded, never blocking.
    blocking = [f for f in findings if f["check"] not in ADVISORY_CHECKS]
    should_block = bool(args.arm and blocking and not reentry)
    report["blocked"] = should_block
    if args.arm and blocking and reentry:
        report["reason"] = "stop_hook_active"
    write_report(report, args.report)
    append_history(report, args.history, args.history_max)

    if should_block:
        # The remedy named here must be one this file IMPLEMENTS. It used to
        # read "Fix or retract, then finish", and there is no retraction path in
        # `audit` - RM-217 asked for one, RM-396 refused it by name as a
        # self-serve silencer, and RM-398 recorded the decision to keep the
        # strict behaviour and ACCEPT that retractions flag. Half the sentence
        # was therefore false, and it was not inert - it told sessions to keep
        # retracting, which cannot work, because the scan re-reads the WHOLE
        # transcript every Stop and an earlier turn cannot be edited. The
        # re-flagging that follows is structural and large: measured 2026-09-12
        # over `ops/runtime/stop_claim_history.jsonl` (500 rows, the rolling
        # cap), one session carries 49 Stops with findings, 48 of them
        # count_mismatch, and five more sessions carry 14 or more. Prescribing
        # the remedy that works is the fix; the gate's behaviour is unchanged.
        lines = [f"stop_claim_gate: {len(findings)} claim(s) not backed by this "
                 f"session's own evidence. Back them with a real run, or "
                 f"backtick a figure you are quoting rather than asserting "
                 f"(a backticked count is stripped before any check). A later "
                 f"withdrawal does NOT clear a finding - the scan re-reads the "
                 f"whole transcript every Stop."]
        for finding in findings:
            detail = ""
            if finding["claimed"] or finding["observed"]:
                detail = f" (claimed {finding['claimed']!r} / observed {finding['observed']!r})"
            lines.append(f"  - {finding['check']}{detail}: {finding['quote']}")
        lines.append(f"  full report: {args.report}")
        # MAIN ORDER 2026-10-07 2237 (operator Console review): the full reason
        # lives in the report file ONLY; the model gets one feedback line via
        # hookSpecificOutput.additionalContext on exit 0, which the transcript
        # shows as "Stop hook feedback", not a "Stop hook error" dump (exit 2 +
        # stderr, or decision:block). It keeps the conversation going under the
        # same loop protections, so the stop_hook_active handling above stands.
        report["message"] = "\n".join(lines)
        write_report(report, args.report)
        out = {"hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": feedback_line(findings, args.report)}}
        # Under pythonw.exe sys.stdout can be None. Never let the emit raise.
        try:
            if sys.stdout is not None:
                sys.stdout.write(json.dumps(out) + "\n")
                sys.stdout.flush()
        except (OSError, ValueError):
            pass
    return 0


FEEDBACK_MAX = 160


def feedback_line(findings, report_path, limit=FEEDBACK_MAX):
    """One line, at most `limit` chars: gate, count, finding codes, report path.

    The path is shown ROOT-relative when the report sits under ROOT (the live
    case: ops/runtime/stop_claim_report.json). The code list is cut first, with
    a `+N more` tail, down to one code; only then is an overlong path shortened,
    by eliding its middle so the drive and the file name both survive."""
    codes = []
    for finding in findings:
        if finding["check"] not in codes:
            codes.append(finding["check"])
    n = len(findings)
    noun = "unbacked claim" if n == 1 else "unbacked claims"
    path = _display_path(report_path)
    head = f"stop_claim_gate: {n} {noun}"

    def build(shown, rest, shown_path):
        listed = ",".join(shown) + (f",+{rest} more" if rest else "")
        return f"{head} ({listed}); see {shown_path}"

    if not codes:
        return f"{head}; see {path}"[:limit]
    for keep in range(len(codes), 0, -1):
        line = build(codes[:keep], len(codes) - keep, path)
        if len(line) <= limit:
            return line
    rest = len(codes) - 1
    budget = limit - len(build(codes[:1], rest, ""))
    if budget >= 12:
        tail = budget - 3 - 3
        return build(codes[:1], rest, path[:3] + "..." + path[-tail:])
    return build(codes[:1], rest, path)[:limit]


def _display_path(report_path):
    raw = " ".join(str(report_path).split())
    try:
        return Path(raw).resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return raw


if __name__ == "__main__":
    sys.exit(main())

# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-09, MEMORY.md compaction pass (relocated `2026-09-09g` RM-395 SHIPPED; newest 3 = MEMORY.md compaction `2026-09-09j` + RM-397 shipped `2026-09-09i` + RM-396 refuted / RM-397 filed `2026-09-09h`). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-09j - MEMORY.md compacted to 16.9 KB by relocating two blocks; no repo code touched

Tier-0 housekeeping on the memory index only - nothing in this repo changed
except this note. The PostToolUse hook was warning: `MEMORY.md` sat at **20548
bytes / 124 lines** against a 17.1 KB target.

**What moved, and nothing else.** Two coherent blocks were relocated VERBATIM
into two NEW sub-indexes, hooks and links intact:

* the whole `## Tooling` block, 11 entries -> `INDEX_tooling.md`;
* 17 of the 19 `## Projects & parking-lots` lines -> `INDEX_projects.md`.

**Two project rows stayed INLINE on purpose**, on the same precedent as the
three costliest ops entries: `project_repo_is_public` and
`project_responder_headless_loop_program`. Both change what a session is
ALLOWED to do, so neither may be one hop away. Each vacated section keeps its
heading plus a one-line pointer, matching the Riot-API / ops / testing-traps
shape already in the file.

**AFTER: 17307 bytes / 97 lines (16.9 KB)** - under target, with **NOTHING
dropped and NOTHING unindexed**, which is the one forbidden move here.

**The acceptance is reachability, not bytes.** Re-derived the way
`check_memory_index` does it (`tools/drift_guard.py:165-215`: `*.md` stems minus
the index, markdown link targets, ONE level into `INDEX_*` from a snapshot taken
before the loop, exempt prefixes `project_ds_sweep_` and `_` at `:75`/`:207`).
BEFORE: 497 memory files, 100 exempt, **397 non-exempt, 0 unreachable, 0 dead**.
AFTER: 499 files, 100 exempt, **399 non-exempt, 0 unreachable, 0 dead** - the
two extra non-exempt files are the new sub-indexes themselves, both linked
directly from `MEMORY.md` (they must be: the recursion snapshot means a sub-index
linked only from another sub-index is never followed). `python tools/drift_guard.py`
-> `0 breach(es)`, exit 0. `tests/test_drift_guard.py` 47 passed;
`tests/test_citation_drift_guard_rm171.py` 11 passed / 125 subtests.
`tools/perseus_sync.py` re-run: memory=499, `--verify` active=1622 embedded=1622.

**TRAP, and it bit on the first pass: do NOT write a bare markdown link target
inside MEMORY.md's own footer prose.** Describing the guard's regex by quoting a
literal link target made the guard parse it as a REAL link to a file that does
not exist - one dead index link, from a sentence that was only ever describing
the check. The footer now says "markdown link targets" in words and carries the
warning. A doc that documents its own guard can breach that guard.

---

# 2026-09-09i - RM-397 SHIPPED: the first repair to this gate that WIDENS what it examines, measured against a frozen corpus rather than argued

Seventh row of the same headless day, operator AWAY. Tier-1: one tool module plus
its test, no engine, no `ENGINE_VERSION` bump, no DS bounce, nothing outward -
**except that the gate is ARMED, so this one does change what happens at every
wrap.** LEDGER 1380, shipped as `e518786e2`.

**The defect.** `_QUOTED` (`:184`) is `'[^']*'|"[^"]*"` with `re.S`, and
`strip_prose_noise` applies it to every assistant text block BEFORE the claim
scan. Two ordinary possessives in one paragraph therefore paired as quote
delimiters and everything between them was deleted, so a claim landing in that
span was never examined at all. A FALSE-NEGATIVE hole in the instrument that
audits this session's own claims.

**The fix.** A prose-only `_QUOTED_PROSE` used by `strip_prose_noise` ALONE. It
refuses to open a span on an apostrophe flanked by word characters, and tolerates
an inner contraction inside a genuine quoted span so that span is suppressed END
TO END rather than truncated at the apostrophe. `_QUOTED` is BYTE-UNCHANGED
(md5-verified by a verifier, not asserted) and `strip_command_noise` is untouched
- shell quoting has no possessives - with a test pinning that scope decision so a
later pass does not unify the two patterns.

**THE CORPUS IS 91 TRANSCRIPTS, NOT THE 90 THE ROW WAS FILED WITH** - one session
was created after filing. **And the trap worth carrying forward: it had to be
FROZEN to a scratchpad copy first.** The live directory contains the RUNNING
session's own growing transcript, so a before/after comparison over it compares
two different corpora and the "after" side is inflated by text the "before" run
never saw. Every future measurement over this corpus hits that.

**Measured, not argued: baseline 26 findings over 15 transcripts -> 34 over 21.
8 NEW, 0 LOST**, and merged `main` replays IDENTICAL to the adjudicated state.
**An INDEPENDENT adjudicator classified all 8 against their transcripts and found
ZERO clean false positives - that is the ADJUDICATOR'S classification, not my own
re-derivation.** I did not re-adjudicate all 8 by hand. **The one I DID
corroborate myself**, by grepping the frozen transcript `db9fa5f4`: a claim of
`17 passed / 205 errors of 221 collected` was re-measured by a LATER session in
the same corpus as `18 passed` with `222 collected` - a wrong count that shipped
unchallenged precisely because this hole hid it.

**Seven of the eight are direct apostrophe pairing. The EIGHTH is the subtler
half of the same defect** - an apostrophe span swallowed the OPENING double quote
of a phrase, the orphaned closing quote paired with a later one, and 988 chars
were deleted. The adjudicator required a test for exactly that interaction and it
is MUTATION-CHECKED (empty findings list under the old pattern). The anchor test
`test_the_real_transcript_that_produced_nine_false_positives_is_clean` is
NON-VACUOUS: 2 of the 9 assistant blocks in its fixture strip differently under
the new pattern. Regex is linear, re-timed independently to 160k chars.
`tests/test_stop_claim_gate.py` gains 9 tests in an RM-397 section, file total
**81 passed** observed on `main` after the merge.

**THE DIRECTION WAS THE RISK AND IT HELD.** Every prior repair to this file
(LEDGER 1154 / 1156 / 1175 / 1178) NARROWED the gate to kill a false positive;
this one WIDENS what it examines. The 1175/1178 precedent does NOT transfer, by
its own stated justification: those were right because the cheapest way to
satisfy the gate was behaviour the repo wants, whereas here the cheapest remedy
is to run the probe yourself, which is the standing rule anyway.

**THE COST, stated plainly rather than sold as "more findings": 6 of the 91
sessions go from quiet to Stop-BLOCKING, one block each**, bounded by the
re-entry guard.

**Filed rather than bundled: RM-398.** `count_mismatch` cannot distinguish a
count asserted as SUCCESS from one asserted as a RED or mutation state, and 3 of
the 8 new findings are that shape. NOT fixed here on purpose: a `"mutation:"` or
`"red state:"` suppressor is an evasion prefix available to the party the
instrument polices and would reopen the hole RM-397 just closed. Any acceptable
design must derive RED-ness from evidence the session cannot author at will. The
row also carries the genuine pre-existing formatting false positive already in
the corpus - `10 856 passed` parsed as claimed `856` - a clean parser narrowing
with no evasion surface, independent of the RED-state question.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial, and
SUBAGENT-FIRST TO KEEP THE MAIN WINDOW CLEAR. ONE row per cycle, gate BEFORE the
irreversible act, commit, push, LEDGER entry. ARMING is never adjudicated - if a
row needs it, PING THE OPERATOR.

**Expect the gate to be louder, and that is the change working, not a
regression.** 6 sessions in the corpus now block where they were quiet. Do NOT
respond to a new `count_mismatch` by narrowing the gate - RM-396 is REFUTED and
RM-398 pre-refutes the prose-marker version. Run the probe.

**Also open, not adjudicated, carried from the previous block:**
`tests/test_inbox_responder_runner.py` carries two defects in one module -
`:214` asserts `_TMP_LOGS` non-empty, a positive control that cannot tell "the
arms were skipped" from "the runner is broken"; and `_live_surfaces_unchanged` is
non-hermetic against a LIVE RC appending to `ops/runtime` mid-suite, measured
three times on 2026-09-09 and absent on two other runs, so it is window-dependent
by construction.

**Housekeeping still NOT done:** `MEMORY.md` is over the hook's preferred size.
It is not a free edit - the file's own footer requires re-deriving reachability
over every non-exempt memory against `MEMORY.md` plus every `INDEX_*` before a
consolidation may be called safe. Its own row, not a tidy-up.

**Check `moon_sync_inbox/` at session start** for RSC's answer to the three
questions RC asked at the 2026-09-09h wrap.

---

# 2026-09-09h - RM-396 REFUTED, RM-397 FILED: the row was to patch the instrument that audits me, and the answer was DO NOTHING

Sixth row of the same headless day, operator AWAY. Docs + memory only, Tier-0:
no code, no test, no `ENGINE_VERSION` bump, no DS bounce, nothing outward.
LEDGER 1379.

**The conflict of interest was the first fact, not an afterthought.**
`tools/stop_claim_gate.py` audits this session's own claims, and the standing
memory names the hazard of the audited party patching it. **Cite correction a
gate caught: that hazard is NOT a comment in the file.** Searching it for that
language returns ZERO matches, and `:74-77` is the `CLAIM_CITATION` note about
not chilling precedent-citation. The false cite lived in the memory and this row
repeated it into three artifacts while rewriting that same memory. So the
decision went
to an INDEPENDENT adjudicator with the conflict disclosed, told to say DO NOTHING
if that was honest, and handed the acceptance test that could kill the proposal -
this session's own `41 passed` flag, which fired CORRECTLY when I quoted a
subagent's count without probing it.

**It returned DO NOTHING. Four measured grounds, none of them rhetorical.**
(1) The cure already exists and is one backtick pair wide: `strip_prose_noise`
already deletes fenced, inline-code and quoted spans for EVERY check - probed
here, bare prose flags, backticked and quoted forms do not. (2) No discriminator
survives the corpus - THE ADJUDICATOR'S SCORING, not re-derived by me: against 19
real `count_mismatch` findings over the 90 transcripts, a negation rule launders
`"not a cascade: 1 failed / 29496 passed"`,
a priorness rule launders three genuine unbacked counts, and their conjunction
fires on nothing. (3) No veto exists for numbers the way `CLAIM_FIRST_PERSON_DID`
vetoes the file suppressors, so any count suppressor is a one-phrase evasion by
the party writing the sentence. (4) The 1175/1178 precedent does not transfer -
there the cheap cure was to stop citing precedent, which the repo wants; here it
is to mark a quotation as a quotation.

**The asymmetry, narrower than I first wrote it.** `count_mismatch` has an honest
in-session cure when the claim is TRUE - today's `41 passed` flag cleared the
moment I ran the guard myself - but it is NOT the only check with one; four
others (`ran_pytest`, `probed_ci`, `did_commit`, `did_push`) clear the same way.
**And the cure is PROSPECTIVE ONLY:** a bare-prose refuted figure can never
clear, because a number you are refuting never enters `observed_counts`. That is
the motivating case exactly. The refutation stands on grounds (2) and (3), which
do not depend on a cure existing at all.

**RM-397 is the real defect, and it points the other way.** `_QUOTED` (`:184`) is
`'[^']*'` with `re.S`, so two ordinary prose APOSTROPHES pair as delimiters and
the span between them is deleted before any check. My own probe:
`"The runner's log says 9999 passed, and the session's report agrees."` strips to
`"The runner s report agrees."` and the count vanishes. **My first blast-radius
figure was WRONG BY 2.3x, in the direction that flattered the finding, and a gate
caught it:** I counted every `type=="text"` block and got 1408 spans / 131
claim-shaped / longest 5502, but `collect_evidence` (`:257`) takes text ONLY when
`role == "assistant"`, so user-side text is never scanned. Re-derived with the
split: **SCANNED 565 spans / 57 claim-shaped / longest claim-bearing 1658**;
never-scanned 843 / 74 / 4441, and the 5502 headline carries no claim shape at
all. The gate-relevant number is **57**. It disarms EIGHT checks over the span,
not nine - `hook_bypass` (`:368`) runs in the bash loop and never sees
`strip_prose_noise`.

**Two more recorded rather than built:** `CLAIM_COUNT` mis-parses space-grouped
digits (`"DS 10 856 passed"` yields `('10','856')`, reporting a `claimed` string
that never appeared) - unscheduled parser narrowing. And the heredoc-invisible
pytest trap is REAL AS A MECHANISM BUT MEASURED INERT - the adjudicator's figure,
not mine: 49 such commands across the 90 transcripts, ZERO produced an `N passed`
result. Closed so it is not re-pitched; re-derive before acting on it.

**Do NOT redo.** Do not re-pitch `CLAIM_COUNT` suppression - RM-396 is REFUTED
with the corpus scoring in the row. Do not build a retraction token or per-turn
scope; both were rejected, the first as a self-serve silencer. Do not quote a
refuted figure in bare prose - backtick it. And do NOT cite `:74-77` for the
audited-party hazard; that cite is false and this row is where it was killed.

## TWO STANDING DIRECTIVES ISSUED AT THIS WRAP (operator, 2026-09-09)

**1. SUBAGENT-FIRST, AND THE REASON IS NOW PART OF THE RULE:** "sub-agent first
to keep main session quiet and clear, always." The main window is the OPERATOR'S
surface. The main thread holds the plan, the merge, the gate and the report - not
the doing. `CLAUDE.md` "Session Default" updated; memory
`feedback_main_window_belongs_to_operator_subagent_always`.

**2. THE FIVE-WAY RESPONDER WORK GOES ON A HEADLESS LOOP** - "its tests and
fixes", unattended, with ONE mandatory stop: ping the operator when the other
projects must be involved. RC reads that as the ARMING seam, not the build seam.
`RC-InboxResponder` stays DISARMED until an expiring agreement record arms it,
and an unattended loop must never arm another repo. Memory
`project_responder_headless_loop_program`.

**SCOPE CORRECTION, made twice and the second time in public.** A first draft of
both records said the runner was "NOT started". **RM-384 SHIPPED the runner
2026-09-08 (LEDGER 1364), with RM-385 and RM-386 shipping both tails the same
day** - the ROADMAP line saying so sits three lines above the rows that were
being read. So the loop's scope is TESTS, FIXES AND HARDENING on a shipped
runner, plus arming. The stale version reached RSC's inbox before it was caught;
a correction note followed seven minutes later. `feedback_row_age_check_before_building`,
paid on an outbound note, which is the worse direction.

**RSC was instructed with the same prompt, as the operator asked** - two notes in
`C:\Resin Compute\moon_sync_inbox\`: the directive relay (1822) and the
correction (1829). RC asked RSC three questions: does it read the ping boundary
the same way (arming, not building); is its own responder work at a comparable
point; and any refutation - with RC's standing note that agreement between two
agents is not evidence, so a specific objection is worth more than a "sounds
right". **Check that inbox at next session start.**

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial, and
now explicitly SUBAGENT-FIRST TO KEEP THE MAIN WINDOW CLEAR. ONE row per cycle,
gate BEFORE the irreversible act, commit, push, LEDGER entry. The RC <-> RSC
exchange is the only outward scope; `CS`, `LW` and `LL` are on operator-ordered
STANDBY and their silence is STANDBY, never dissent. ARMING is never adjudicated -
if a row needs it, say so and PING THE OPERATOR.

**The next row is RM-397**, fully measured above. **Its DIRECTION is the risk and
that is the whole brief:** every prior repair to this gate (LEDGER 1154 / 1156 /
1175 / 1178) NARROWED it to kill a false positive; this one WIDENS what it
examines. Narrow `_QUOTED` so an apostrophe flanked by word characters cannot open
a span, keep genuine single-quoted spans suppressed, anchor on the real-transcript
corpus the file already uses, and MEASURE the change against all 90 transcripts
for new false positives before arming. `feedback_mutation_probe_vs_naive_alternative`
applies - derive the attack families from the mechanism, not from a naive foil.

**Also open, not adjudicated:** `tests/test_inbox_responder_runner.py` carries two
defects in one module - `:214` asserts `_TMP_LOGS` non-empty, a positive control
that cannot tell "the arms were skipped" from "the runner is broken"; and
`_live_surfaces_unchanged` is non-hermetic against a LIVE RC appending to
`ops/runtime` mid-suite, measured three times on 2026-09-09 and absent on two
other runs, so it is window-dependent by construction.

**Housekeeping the harness asked for and this session did NOT do:** `MEMORY.md` is
19.7 KB against a 24.4 KB read limit and the hook wants it under 17.1 KB. It is
not a free edit - the file's own footer requires re-deriving reachability over
every non-exempt memory against `MEMORY.md` plus every `INDEX_*` before a
consolidation may be called safe. Treat it as its own row, not a tidy-up.

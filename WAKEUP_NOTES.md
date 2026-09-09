# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-09, RM-397 SHIPPED pass (relocated `2026-09-09f` ADR-015; newest 3 = RM-397 shipped `2026-09-09i` + RM-396 refuted / RM-397 filed `2026-09-09h` + RM-395 shipped `2026-09-09g`). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-09-09g - RM-395 SHIPPED: the row I filed one commit earlier was wrong twice, and the step that caught it is the one the row demanded

Fifth row of the same headless day, operator AWAY. Tier-1: two test modules, no
engine, no `ENGINE_VERSION` bump, no DS bounce, nothing outward. LEDGER 1378.
Two parallel single-file slices, one merger, gate before the commit.

**Both corrections came from doing the step the row itself demanded FIRST** -
state whether an EMPTY enumeration would PASS each assertion before converting.
That step is in ADR-015's Watch for because RM-394 nearly shipped a silent
always-green. Here it caught my own filing.

1. **"Both are ABSENCE guards, the empty-set-safe shape" is FALSE for the laning
   guard.** `_app_source_files()` has exactly one consumer and it asserts SET
   EQUALITY against a two-element expectation, so an empty enumeration gives
   `set()` and FAILS. Self-anchoring, no anchor needed - PROVEN by mutation
   (`assert set() == {...}`, 1 failed / 26 passed), not reasoned.
2. **The row named two exposed sites; there are three** - and my framing of the
   third was ALSO wrong. `CallerSurfaceAbsenceTests.test_no_live_caller` sweeps
   6377 files with 5044 under the export trees, but its own
   `rel.startswith("ops/runtime/")` skip existed at HEAD (`:172`) and dropped
   every one BEFORE any read: read-set 1260 both sides, symmetric difference
   EMPTY. **Cost, not correctness.** I told the operator otherwise mid-session.
   Its real defect is the ADR's other green-by-luck sense - it never skipped
   `python-embed` / `node_modules` / `.claude`.

**Shipped.** `test_laning_verdict_flip_retired.py`: 2082 -> 397 enumerated, all
1685 removed are vendored `python-embed`, set-diff confirms 0 RC source lost and
0 gained, 15 first-party SCOPE skips kept and only 4 infrastructure entries
deleted; 27 passed. `test_dead_endpoint_cleanup_item186.py`: both sites, site 1
9112 -> 2386 (its two filters were removing ZERO files), site 2 to one root walk
plus a prefix filter reaching the identical 1260 read-set; 4 passed. **A gate
caught 1331 recited as the read-set in four places: 1331 is the caller SURFACE,
and this guard's own `dashboard/routes_` skip removes exactly 71 of them before
anything is opened.** Surface and read-set are different populations one line
apart, and the in-file comment saying "1331 across the caller surface" was right
while every doc restating it as the read-set was wrong.

**The anchors, and the mutation that justifies them.** With the identical
forced-empty mutation applied to the PRE-conversion code both tests PASSED
VACUOUSLY. After, they fail under three independent mutations (`Path.rglob`
empty, the `_repo_walk` enumerators empty, `EXCLUDED_DIRS` widened to a partial
collapse leaving 76 files). Each anchor checks TWO oracles - on disk AND actually
delivered to the scanning arm - so a decayed constant reports "anchor gone", not
"walk collapsed"; a `_MIN_SCANNED = 100` floor sits far below the true 2386/1260
so it tracks collapse, not roster.

**Suite:** `pytest tests -n 8` = 21639 passed, 97 skipped, 4921 subtests, 0
failed, exit 0. No `_live_surfaces_unchanged` error this run - consistent with
the window-dependent external-writer attribution, not evidence against it.

**Do NOT redo.** ADR-015 needs no amendment - both Watch-for items did exactly
what they were written to do. Do not add an anchor to the laning guard; set
equality already is one. Do not "fix" site 2's `ops/runtime/` skip as dead - it
is a no-op only under `tracked_only=True`, and still fires on the git-absent
fallback, which is the path RM-394's reds were on.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial. ONE
row per cycle, gate BEFORE the irreversible act, commit, push, LEDGER entry.
The RC <-> RSC exchange is the only outward scope; `CS`, `LW` and `LL` are on
operator-ordered STANDBY and their silence is STANDBY, never dissent. ARMING is
never adjudicated - if a row needs it, say so and move on.

**No row is queued - pick one.** RM-392, RM-393, RM-394 and RM-395 all shipped
today, and ADR-015 records the decision behind the last two. The two known-open
items, neither adjudicated into a row:

1. **`tools/stop_claim_gate.py:38`** - `CLAIM_COUNT` has no counterfactual or
   citation suppression, unlike `CLAIM_FILE` (`:47-83`) which has both, so
   quoting a figure IN ORDER TO REFUTE IT re-fires every turn. Read the hazard
   its own comments name at `:74-77` before touching it. **SUPERSEDED
   2026-09-09h: this candidate became RM-396 and is REFUTED, and the `:74-77`
   cite in this sentence is FALSE - no such comment exists in the file.**
2. **`tests/test_inbox_responder_runner.py`** - two defects in one module. `:214`
   asserts `_TMP_LOGS` non-empty, a positive control that cannot tell "the arms
   were skipped" from "the runner is broken" (it is the 1 residual error when git
   is off PATH). And `_live_surfaces_unchanged` is non-hermetic against a LIVE RC
   appending to `ops/runtime` mid-suite - measured three times on 2026-09-09,
   absent on a fourth run, so it is window-dependent by construction.

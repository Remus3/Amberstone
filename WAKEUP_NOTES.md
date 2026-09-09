# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-09, RM-396/RM-397 pass (relocated `2026-09-09e` RM-394 shipped; newest 3 = RM-396 refuted / RM-397 filed `2026-09-09h` + RM-395 shipped `2026-09-09g` + ADR-015 `2026-09-09f`). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-09-09f - ADR-015 written: the record _repo_walk never had, and the reason a ledger row alone would not have worked

Fourth row of the same headless day, operator AWAY. Docs-only, Tier-0: no code,
no test, no `ENGINE_VERSION` bump, no DS bounce, nothing outward. LEDGER 1377.

**The code was never the gap.** `tests/_repo_walk.py` shipped 2026-09-07 in
`a0a23b57c` carrying a real decision - git index first, `EXCLUDED_DIRS` as
backstop, `tracked_relpaths()` returning `None` never an empty set - with its own
anti-vacuity guard and four consumers, and NO ledger row, NO ADR, NO `CLAUDE.md`
line. Two days later RM-394 proposed re-deciding the universe from scratch
because nobody could find the decision that had already been made.

**A ledger row alone would not have fixed that, so this is three places.**
`docs/adr/ADR-015-shared-repo-enumeration.md` plus an index row and a Test guards
line in the reading order (the ADR index is what `CLAUDE.md` declares as "before
re-litigating a past choice, check here first"), and ONE rule line in the
`CLAUDE.md` Testing Discipline section - because the moment discoverability has
to work is the moment somebody is WRITING a new root-walking guard, and that is
the file auto-loaded then. The ledger is append-only history 1377 entries deep,
findable only by someone who already knows what to grep for: exactly the reader
RM-394 proved does not exist.

**The ADR records the trade-off, not a sales pitch.** Untracked new `.py` is
invisible until staged (and staged is what the hook and CI see). Alternatives
named with why they lose. And the failure mode the decision CREATES is in Watch
for: converting an empty-set-safe assertion can turn a machine-local RED into a
silent always-GREEN, measured at 56 passed during RM-394.

**RM-395 filed for the two holdouts - and the gate made it a better row than I
wrote.** I filed one of them as safe; BOTH are green by luck.
`tests/test_dead_endpoint_cleanup_item186.py:199` walks **9112 `.py`, 4772 (52
percent) inside the gitignored export copies**, its two filters removing ZERO
files today. My "green because the symbols are absent there" was REFUTED - they
are PRESENT, in each export tree's copy of that guard file, which its path-exact
self-exemption misses. It is green because no line there carries both `import`
and a deleted symbol: one line-shape from a phantom. And the hazard is TIME - an
export is a snapshot of an OLDER repo. `tests/test_laning_verdict_flip_retired.py:85`
I called safe-by-accident on `ops`; also refuted as understated - it does not
skip `python-embed` and walks **2082 files, 1685 (81 percent) vendored
`python-embed`**. Bound corrected too: a stronger AST resolver finds **2** root
walkers against **39** subdirectory walks; my "11 files, 9 subdirectory" was a
receiver-name-heuristic artifact. Two is the whole set, both passes.

**A guard caught my id allocation, same lesson one size down.** I checked RM-395
was free with `grep -c RM-395` over BACKLOG / ROADMAP / LEDGER, got 0, called it
free. `tests/test_rm_id_registry_drift.py` went RED: `docs/DS_SWEEP_TRACKER.md:72`
already PINNED RM-395 as next-free. A grep finding no ROW body is not a claim
about the registry. The pin was advanced with the allocation recorded beside it
in the same commit. **Take an RM id from that registry, never from a grep** - and
do NOT recite the advanced figure in prose elsewhere: writing it into the LEDGER
entry made the same guard red a second time, because the classifier reads a bare
id as an ALLOCATION unless a "next free" cue precedes it. ROADMAP's eleven
next-free pointers were left alone - NOT because they defer to the tracker (only
three of the eleven do; the gate refuted that reason) but because RM-316 already
owns them.

**Do NOT redo.** Do not convert those two here - RM-395 owns them, and both are
`assert not offenders` shapes that MUST be anchored before conversion. Do not
turn a grep for `rglob` into a repo-wide rewrite: 11 AST hits, 9 of them
SUBDIRECTORY walks that need nothing. Two is the whole set.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial. ONE
row per cycle, gate BEFORE the irreversible act, commit, push, LEDGER entry.
The RC <-> RSC exchange is the only outward scope; `CS`, `LW` and `LL` are on
operator-ordered STANDBY and their silence is STANDBY, never dissent. ARMING is
never adjudicated - if a row needs it, say so and move on.

**The next row is RM-395** - small, bounded, fully measured above, and the ONLY
thing it needs that is not already written down is the anchor decision: for each
of the two guards, state whether an EMPTY enumeration would PASS its assertion
before you convert it, and add the anchor where it would. Read ADR-015 first.

**Also open, neither adjudicated into a row:** `tools/stop_claim_gate.py:38`
(`CLAIM_COUNT` has no counterfactual or citation suppression, unlike `CLAIM_FILE`
at `:47-83`, so quoting a figure IN ORDER TO REFUTE IT re-fires every turn - read
the hazard its own comments name at `:74-77` first - **SUPERSEDED 2026-09-09h:
became RM-396, REFUTED, and that `:74-77` cite is FALSE**); and
`tests/test_inbox_responder_runner.py:214`, whose `_TMP_LOGS` positive control
cannot tell "the arms were skipped" from "the runner is broken", in a module
measured today to be non-hermetic against a LIVE RC writing `ops/runtime`
mid-suite.

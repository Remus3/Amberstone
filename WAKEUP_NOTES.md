# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-10, RM-399 wrap (relocated `2026-09-09h` RM-396 refuted / RM-397 filed; newest 3 = RM-399 shipped `2026-09-10a` + MEMORY.md compaction `2026-09-09j` + RM-397 shipped `2026-09-09i`). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-10a - RM-399 SHIPPED, and specifying it found FIVE sibling-name escapes already PUBLISHED from RC's own tree

Tier-1, operator AWAY: one tool, one guard, one hook, docs. LEDGER 1383, merged `a715baf58`.

**THE HEADLINE IS THE ESCAPES, NOT THE TOOL. FIVE REAL sibling PROJECT NAMES sat in RC's own
tracked prose, all live in HEAD and ALL FIVE ALREADY PUBLISHED** to the public remote; the
2026-09-07 identity scrub reported CLEAN and missed every one. **FOUR are redacted AT HEAD
ONLY (`f6cf005bb`) - remediating HEAD does NOT undo publication and NO history rewrite was
performed** (operator decision; a force-push does not reach `refs/pull/N/head` anyway).

**THE FIFTH IS OPEN AND UNFIXABLE ALONE:** `tests/test_loop_concurrency.py:492`, inside the
`SHARED_SHA256` byte-identical block (474-539), a two-word name SPLIT ACROSS A COMMENT LINE
WRAP - not contiguous in the blob, which is why every whole-token sweep ever run here called
it clean. It ships as a KNOWN, NAMED, VISIBLE exception (`tools/sibling_name_sweep.py:112`,
asserted REPORTED not suppressed). Removal is a JOINT re-pin, relayed to RSC 2026-09-10 and
**AWAITING THEIR REPLY** - do not re-pin unilaterally.

**MEASURED on main:** 126 passed; ARMED tree scan = EXACTLY 1 finding (the known site) over
627214858 bytes / 4721 files, 482 binary/LFS blobs declared un-scanned; the gate ran on its
OWN push, clean over 95220 bytes / 6 files / 2 commit messages. The honest claim is "the sweep
half is ARMED with a measured escape rate above zero", never "sibling names cannot leak".

**DO NOT REDO:** RM-397 SHIPPED (`e518786e2`), RM-398 FILED (deliberately NOT bundled), RM-399
SHIPPED. The halt-before-any-byte-leaves boundary is ADOPTED, binds EVERY session, no timeout -
but its PUSH half was SUPERSEDED the same session by `8facd08d4`: **the push gate is on DIFF
CONTENT, not destination.** Do NOT restore the destination wording and do NOT restore the
own-origin carve-out (RSC conceded it removed seam (f)).

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

**AFTER: 17303 bytes / 97 lines (16.9 KB)**, re-derived after the LAST edit -
the commit message `15e9ca198` cites 17307, measured before a four-byte footer
correction, which is the standing "your own edit staled the citation" trap - under target, with **NOTHING
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

# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-10, RM-398 partial wrap (relocated `2026-09-09i` RM-397 shipped; newest 3 = RM-398 partial `2026-09-10b` + RM-399 shipped `2026-09-10a` + MEMORY.md compaction `2026-09-09j`). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-10b - RM-398 PARTIAL SHIPPED, and the row's own mechanism was REFUTED while its population claim survived

Tier-1, operator AWAY: one tool module plus its test, docs. LEDGER 1384, shipped
as `271d69a53`. The gate was already armed, so nothing outward changed.

**EVERY NUMBER HERE WAS MEASURED OVER A FROZEN 91-TRANSCRIPT CORPUS COPY, and
that is not a detail.** The live transcript directory holds the RUNNING session's
own growing transcript, so a before/after comparison over it compares two
different corpora. Carry that trap into every future pass over this corpus.

**TWO PARSER FIXES, both to `tools/stop_claim_gate.py`.** FIX 1: `CLAIM_COUNT`
read `10 856 passed` as prefix `10` plus count `856` and flagged `claimed=856`, a
string never in the prose, while the true `10856` sat in `observed_counts`. **Its
FIRST version was REFUTED BY MEASUREMENT** - dropping any 1-3 digit prefix plus a
comma-free 3-digit count silenced `lane 8 328 passed`, `run 2 654 passed`,
`12 999`, `123 999` and `0 000` against an observed `1397`, making every 3-digit
suite total unflaggable whenever a small number preceded it. Shipped form is
evidence-derived: suppress only when `prefix + count` is ITSELF in
`observed_counts`, so the evader would have to be telling the truth. Two tests
kill the blanket-drop mutant. FIX 2: `EV_CI_LOG` demanded a literal `gh` token
while `EV_CI` in the same file already wrote `gh(?:\.exe)?`, and RC's prescribed
quoted-absolute-path form strips to basename `gh.exe`, whose `.` broke
`\bgh\s+run`. It WIDENS belief, so the summary-line restriction was verified by
call path and fenced by a test.

**MEASURED, verifier-re-derived: `count_mismatch` 28 -> 23, 5 removed, 0 added,
removed set a strict SUBSET of the 6 predicted, perfectly additive.** FIX 1
removes 2 (the `856` artifact in `c4bf4a1a`), FIX 2 removes 3 (`274b84bc` x2,
`958c1483`). **FIX 2 was predicted to remove 4 and removed 3** - the verifier
refuted the prediction, `42af2f7d` correctly survives because its claimed `28150`
is not on a summary line in the fetched log. Do not carry the 4 forward. Suite:
`94 passed`.

**THE HEADLINE IS THAT RM-398'S OWN MECHANISM IS REFUTED.** `observed_counts`
applies `EV_PASSED` to run output with NO green/red filter: an adjudicator
measured 1354 paired runs, 347 with a nonzero `N failed`, and 312 of those had
their `N passed` harvested normally (the 35 that did not are runs where nothing
passed). **0 of 28 findings are caused by red-ness; a RED-state discriminator is
not the fix.** **But the POPULATION CLAIM SURVIVES, and the probe's counter-
headline "the RED-state population is ZERO" is itself REFUTED** - at least 9 of
the 28 do assert their count in an explicitly non-green state. The row had the
SHAPE right and the CAUSE wrong: the cause is invisibility of the run.
**Measured causes of the 28:** SUBAGENT-INVISIBLE 12, CI-LOG PATTERN MISS 4,
FILE-ONLY / prior-session recital 7, SPACE-GROUPED 2, UNRECOGNISED RUNNER 1,
NEGATED/RETRACTED 1, TRUE POSITIVE by design 1.

**DO NOT RE-PITCH crediting subagent transcripts.** An adjudicator opened all 12
SUBAGENT-INVISIBLE findings: **12 relay / 0 independent parent re-run**, and
THREE were later RETRACTED by the authoring session as wrong (`17e9bb48` 18226,
`39bc4be6` 18953 branch-local, `1131adbe` 10722 stale). The proposal's own guard
- credit only paired run output - does not help, because each of those WAS a real
paired subagent run. It is the LARGEST TRUE-POSITIVE class in the corpus, and
crediting it would suppress true positives against CLAUDE.md Verification
Discipline. The narrowed variant INVERTS the incentive - it silences a
mis-attributed "Measured this run" while still flagging the corpus's most honest
phrasing. **DO NOT RE-PITCH `_negated` reuse for `CLAIM_COUNT` either**: already
shipped once, refuted for laundering phrases, third version closed as a dead end.

**FILED, NOT FIXED, and the reason is a conflict of interest worth remembering:**
RM-400 (`_QUOTED_EXE` at `:285` accepts only a forward-slash directory, so a
quoted backslash `gh.exe` is invisible to both `EV_CI_LOG` and `EV_CI`;
pre-existing at HEAD, untouched by this diff) and RM-401 (`CLAIM_PUSH` at `:131`
matches an adjectival "pushed"). **RM-401 flagged THIS session twice, which is
exactly why this session is not the one to patch it** - the session a gate flags
is the worst-placed one to narrow that gate.

**LEAVE ALONE, adjudicator-agreed:** the 7 file-only / prior-session recitals,
the 1 workflow-comment recital, the 1 unrecognised runner. Every "fix" widens
evidence toward "a number that appeared somewhere", which is the poisoning that
wrecked the first armed session.

**DO NOT REDO:** RM-397 SHIPPED, RM-399 SHIPPED, RM-398 PARTIAL SHIPPED with its
mechanism refuted and two proposals refused. The JOINT RE-PIN for the fifth
sibling-name escape is still AWAITING RSC's reply - do not re-pin unilaterally.

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

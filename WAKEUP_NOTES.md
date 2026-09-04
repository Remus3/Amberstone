# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-03b - RM-337: the shipped Share package passes clean (ON MAIN)

STATE. Main carries RM-337. A clean copy of `Share/` in a temp dir OUTSIDE the
repo now reports **8376 passed / 0 failed / 24 skipped / 11256 subtests**. The
baseline this session opened with, measured the same way, was 13 failed / 8361
passed / 24 skipped. 8361 + 13 + 2 new guard tests = 8376 - the zero came from
fixing tests, not excluding them. DS from the repo root 10847 passed / 13659
subtests / 0 failed, which is yesterday's 10845 plus exactly the 2 guard tests.
`ds_share_sync.py --check` exit 0 at 535 files. `drift_guard.py` 0 breaches.
NO `ENGINE_VERSION` bump and no `:8860` bounce - Tier-1, nothing in the engine
moved.

VERIFY IT THE HARD WAY OR NOT AT ALL. `cd Share` inside the repo passes for the
wrong reason, and all 13 were always green in the main tree. The only honest
check is `cp -r Share <temp outside repo> && python -m pytest src -q` there.

WHAT SHIPPED. 16 literal sites across 14 files anchored on
`_DS_DIR = Path(__file__).resolve().parents[1]`. Three more than the row filed:
a sibling sweep found `test_akshan_passive_carry_rm42.py` (same defect, but
excluded from the mirror by `_HOST_DEPENDENT_TESTS`, so a count taken in the
package could never show it) and `test_geometry_item232.py` (already correct,
but it passed an `agents/`-prefixed literal that had to go so the guard could
carry zero exemptions).

THE GUARD IS THE HALF THAT MATTERS.
`agents/daemon_slayer/tests/test_no_cwd_relative_paths.py` - `ast`-based, not a
grep, so a `#` comment naming such a path stays legal; docstrings exempt
STRUCTURALLY by node identity, never by name; NO per-file skip list. Its
forbidden prefixes are assembled from `_TOP_PACKAGE = "agents"` because as plain
literals they would be its own first two violations - do not "simplify" that
back. Proven non-vacuous by planting a violation and watching it go red BOTH in
the repo and inside the shipped package copy, where it resolves its scan root to
the temp dir. It asserts it scanned more than 50 files (finds 438) and that it
finds itself.

TWO RESIDUALS, WRITTEN DOWN SO THE ROW IS NOT OVER-CLAIMED. It keys on the
`agents/` prefix per the filed acceptance, so a bare
`open("champion_block_index.json")` would slip through (none exists today), and
a concatenated `"agents" + "/x.json"` splits the constant and evades it - the
guard's own `_TOP_PACKAGE` line demonstrates that bypass.

DRIFT FOUND WHILE IN THESE FILES, all fixed. `Share/README.md` needed correcting
a SECOND time in two days (yesterday it went from "passes clean" to "expect 13";
this made that stale in reverse) and rewriting it surfaced three more defects in
the same section: a garbled duplicated clause, a "21 skips" line contradicting
the same file's own header of 24, and a "356 of 429, drops 73" recital against a
measured 362 of 437, drops 75. Separately, ROADMAP + BACKLOG still marked
RM-329..RM-336 OPEN although LEDGER 1322 shipped all eight the day before, and
ROADMAP still advertised "next free id RM-337" - the id this session used. Eight
status tokens flipped with the LEDGER cite (bodies left as the record), next free
id now RM-338. Two of the eight were spot-checked in code first, not taken on the
ledger's word.

NEXT. Next free id is **RM-338**. Still open: RM-208 + RM-220 (lane 6),
RM-326/327/328 + RM-209 (lane 4). The five lane worktrees are at `22e8bd0ef`,
now two batches behind main - fast-forward before using one.

---

# 2026-09-03 - MERGER: RM-329..RM-336 shipped as one batch, ENGINE 1.280.0 (ON MAIN)

STATE. Main at the 1.280.0 bump, pushed. All eight rows the 2026-09-02 lane-5
refill filed are CLOSED. `:8860` bounced and serving 1.280.0 / 16.15.1 / 173
champs / 706 items. Share mirror `--check` exit 0 at 534 files. DS 10845 passed
/ 13659 subtests / 0 failed; RC 20370 passed / 96 skipped / 4779 subtests / 0
failed (measured AFTER the bounce - before it, `test_live_three_profiles` is
structurally red). ROADMAP 72151 of 81920 = 88.07 pct, measured ON MAIN. All six
run worktrees removed, branches deleted. The five lane worktrees are untouched
at `22e8bd0ef` and are now one batch behind main - fast-forward before using one.

WHAT SHIPPED. RM-331 (Arena augments resolve by DISPLAY name; alias index over
apiName AND name, zero collisions across all 6 snapshots) and RM-334 (`/ehp`
parses `apply_build_tenacity`) are the two behaviour changes that earned the
bump. RM-329 (mode-provenance notes on all 7 EHP-family routes plus
`compute_hps`), RM-330 option B, RM-332, RM-333, RM-335, RM-336 rode along.

READ THIS BEFORE THE NEXT PARALLEL RUN - THE MACHINE OOM'd. Five slices each
running the ~10.7k DS suite, at least three with `-n 8`, took free RAM to 721 MB
of 32 GB. `git status` died on malloc, one slice hit `INTERNALERROR MemoryError`,
two slices were killed. **It presents as an API error and is not one.** Cap it:
single-process pytest in slices, targeted modules while iterating, ONE full suite
at the end. Killed slices resume fine via SendMessage with context intact - both
did, and nothing was lost. A slice suite run that died on malloc reports nothing
trustworthy; re-run it rather than reading it.

NEXT - RM-337 is the obvious pick and it is already filed with acceptance.
A clean copy of `Share/` OUTSIDE the repo reports 13 failed / 8361 passed. They
are PRE-EXISTING (set-difference against `22e8bd0ef` returns exactly one new
name, already fixed) and caused by CWD-relative path opens -
`test_rune_procs_per_attack.py:99` opens the literal
`agents/daemon_slayer/rune_procs.py`, which resolves at the repo root but not
under `Share/src`. **All 13 are GREEN in the main tree, for the wrong reason** -
verify any fix from a clean copy outside the repo, never from `cd Share` inside
it and never from the main tree. Fix with `__file__`-relative paths PLUS a guard
asserting no test under `agents/daemon_slayer/tests/` opens a path starting with
`agents/`; the guard is the load-bearing half. Do NOT fix by excluding them from
the mirror - they have no host subject and belong in the package.
`Share/README.md`'s "0 failed / passes clean" claim is already corrected in place
to the measured 13. Also still open from earlier refills: RM-208 + RM-220 (lane
6), RM-326/327/328 + RM-209 (lane 4). Next free id is RM-338.

TWO TRAPS THIS RUN PAID FOR. (1) `tools/ds_share_sync.py` had a SECOND
`write_text` path (doc-anchor refresh, `:1043`) while its sibling at `:1099`
already passed `newline=""` and carried a comment about this exact failure. It
only fires on an ENGINE bump, which is how it survived the RM-284 sweep that
created the `eol=lf` pin. Fixed. **If you add a writer for a tracked pinned file,
write bytes or pass `newline=""` - and remember a bump-only path is invisible
between releases.** (2) The build-order tables DO have a stamp guard tying them
to `ENGINE_VERSION` - this session asserted otherwise off too narrow a grep and
got 14 red assertions for it. `python -m core.build_order_precompute --static
--mode all --champions all` and the `build_order_variants` twin; both name their
own regen command in the failure text. The generator writes CRLF, so normalise
the six JSON files to LF afterwards.

COUNTING. Do not trust a merger-supplied baseline either - S6 was briefed the DS
base was 10741 and correctly refuted it with exact arithmetic (true base 10803;
10741 was one slice's ISOLATED number). And `grep -rl` for a version literal
matches compiled `.pyc` binaries: the bump surface is 131 `.py` files / 155
occurrences, not the 381 a naive `grep -rl` reports.

# 2026-09-02/03 - lane 5 REFILL, then merger + two repo fixes (all ON MAIN)

Started as a detached lane-5 research refill, then the operator directed the
merge and two follow-on repo fixes. Everything below is on `main`, pushed, CI
green, and all five lane worktrees are fast-forwarded to it and clean.

**Commits, newest first:**
```
8119b3334  eol=lf for every other text type (RM-284 follow-on, LEDGER 1321)
a2d132489  RM-284 - *.md text eol=lf (LEDGER 1320)
acc7f25ad  ROADMAP relocation pass - 8 rows, 0 ids lost
6c4e37bde  clear the budget breach the merge itself caused
7ff7f00cb  Merge lane/research: RM-329..RM-336 refill (LEDGER 1319)
aac80637c  preserve the merger session's orphaned WAKEUP archive
```

**REFILL: RM-329..RM-336 filed, next free id RM-337.** Six LANE 6 (the starved
lane - its ROADMAP-visible work was ONE row), two LANE 7. The refutation pass
changed three of nine candidates: RM-332 KILLED as a defect (`unique_passive_key`
is a DEDUP family, `shield=None` is CORRECT - kept as a Tier-0 note fix), RM-330
downgraded to DECIDE-THEN-ACT after its live-defect claim was refuted twice, and
RM-329 re-framed and severity-capped. RM-220 also got the ROADMAP pointer it had
never had.

**MERGE: the main tree was NOT clean.** It held an uncommitted 124-line
`docs/history_notes.md` addition, 28.5h stale - the archive half of the
2026-09-01c merger `/done`, never staged. Committed FIRST and separately
(`aac80637c`) so the merge could not clobber it.

**RM-284 CLOSED, both halves.** (a) the relocation pass took ROADMAP 89.9 -> 87.55
pct with all 179 ids retained and every fence kept in its stub; (b) `.gitattributes`
now pins 18 text suffixes to `eol=lf`, so on-disk equals blob. ROADMAP measured
71719 on disk against a 71522 blob before, and 71522/71522 after.

**THE RECURRING LESSON THIS SESSION, three times over: measure with the same
filter the contract uses.**
- A doc budget measured in a lane worktree (LF) passed while main (CRLF) breached.
  ALWAYS measure a budget on main.
- A green `ci` run proved nothing because the scheduled nightly SKIPS the `check`
  job. Read `jobs[].steps[].conclusion`, never the workflow conclusion.
- The eol guard flagged 7 LFS payloads that were correct, because it filtered by
  SUFFIX while `.gitattributes` filters by effective attribute. It asks
  `git check-attr` now.

**Three of my own claims were corrected mid-run** and are recorded rather than
quietly fixed: "the bundle is absent from both trees" (wrong path), "CI is
unaffected" twice (docstring, then derivation - now rests on six observed run
conclusions), and a recommendation to relocate three ROADMAP rows that were
ALREADY relocated on 2026-08-31.

**Memories added/updated:** `reference_ds_probe_flag_needs_its_scoring_axis` (new
- a DS flag reads INERT unless the request selects the axis it moves),
`reference_green_ci_run_may_have_skipped_the_job` (new),
`reference_windows_write_text_crlf_byte_count` (two new sections). MEMORY.md's
four sub-index counts were DELETED rather than refreshed - all four were stale
(79/20/31/59 against 73/19/30/41) and nothing guards them.

**NEXT:** lane 6 has 8 actionable rows (RM-208, RM-220, RM-329..334); lane 4 still
holds RM-326/327/328 + RM-209 unworked. Full brief with acceptance checks and the
do-not-redo set: `C:\\Users\\Administrator\\Desktop\\RC-NEXT-SESSION.txt`.

---

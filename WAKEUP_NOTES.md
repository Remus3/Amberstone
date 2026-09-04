# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-04 - six-slice batch: RM-208 / 209 / 220 / 326 / 327 / 328 shipped, RM-338 found+fixed, RM-339 filed (ON MAIN)

STATE. Main carries all seven. ENGINE **1.280.0 unchanged**, patch 16.15.1,
`:8860` NOT bounced and no Share sync - `ds_share_sync.py --check` exit 0 at 535
files proves nothing merged touches a mirrored file. Tier-1 throughout. Six
worktree slices on disjoint file sets plus one read-only adjudicator; all six
branches and worktrees removed at wrap. LEDGER 1324 has the full detail.

WHAT SHIPPED.
- RM-208 DS doc route guard: `ast` over `_POST_ROUTES`, BOTH directions, whole
  backticked doc tokens so `/v2/matchup` stops splitting into `/v` + `/matchup`.
- RM-220 wiki staleness: `{{ap|}}` brace-balancing reaches rank-count,
  enumerated and named-parameter forms. `skipped_labels` 109 -> 72, zero-label
  rows 27 -> 2, `findings` ROSE 214 -> 225. 2 cited aliases. Part (C) decided in
  writing, deliberately NOT implemented.
- RM-209 CSS: 5 tokens mapped onto existing names, 2 declared as new roles.
- RM-326/327 lobby: dataset-signature render gates + focus carry + reorder
  re-index, following the `champ_select.js:704` precedent.
- RM-328 team-context mount RESTORED (adjudicated, not assumed).
- RM-338 (filed and closed same day): every Top-8 `up` chevron was dead to the
  mouse. RM-339 filed, not fixed.

FIVE TRAPS WORTH CARRYING, all paid for this run.
1. **THREE FILED ACCEPTANCES WERE DEFECTIVE AND THE SLICES CAUGHT ALL THREE.**
   RM-328's "assert `#tc-allies` has 5 child slots" is VACUOUS - the no-payload
   branch pads to 5 placeholders, so it passes with the payload never reaching
   the DOM. RM-327's "two mouse clicks at one screen position" cannot
   discriminate a fix from HEAD in a position-indexed list. RM-208's 4(b)
   described the forward direction while asking for the reverse. Read an
   acceptance as a hypothesis, not an instruction.
2. **A WHOLE-TREE DIGEST CANNOT BE STAMPED BY A SLICE.**
   `test_web_ascii_sweep.py::test_live_half_digest_...` moves on any `web/` edit.
   The RM-209 slice correctly refused to stamp it. The merger owns it once,
   after every slice lands, and the file's own rule wants a two-tree diff with
   the SAME tokeniser - 11 differing files here, exactly the union of the four
   web-touching slices.
3. **TWO FILED CENSUSES WERE WRONG IN THE SAFE-LOOKING DIRECTION.** RM-209 filed
   21 sites / 8 files; truth is 22 / 10, and the row's own enumeration summed to
   22. RM-220's baseline had drifted 87/208 -> 92/214 because the wiki moves.
   Re-measure before building, every time.
4. **`git commit -m "merge: ..."` IS REJECTED.** The commit-msg hook enforces
   `<type>(<scope>)?: <description>`. Use `chore(merge): <branch>`. Four merges
   failed on this before it was noticed, and the failure reads like a conflict.
5. **RESTORING OLD MARKUP VERBATIM VIOLATES THE ASCII RULE.** The 2026-05
   team-context hunk carries U+2026 and U+2014. Anything recovered from
   pre-purge history needs a programmatic ASCII assertion, not a glance.

NEXT SESSION
------------
Task: Pick the next open row. Next free id is RM-340.
      RM-339 (LANE 4, Tier-1) is the natural follow-on to this batch: 25 dead
      `getElementById` ids, of which 21 are still live residue. Adjudicate each
      RESTORE-or-REMOVE from git history the way RM-328 was - a dead id is NOT
      proof of dead code. Keep its guard SEPARATE from RM-209's CSS guard.
      Also open: RM-322 (LANE 7), RM-212, RM-214, RM-286/287, RM-291..295.
      Bodies + acceptance in BACKLOG.md; ROADMAP.md carries the pointers.

Context: Main is at the six-slice merge, ENGINE 1.280.0, patch 16.15.1, :8860
      serving. Lane worktrees at C:\rc-worktrees\rc-lane-* were NOT touched this
      run and still sit at a55ece97e - fast-forward them before using one.

Acceptance: whatever the chosen row states. Tier-2 rows (engine/scorer/schema/
      ENGINE_VERSION) need the full dual suite from the REPO ROOT plus a DS
      :8860 restart and a Share mirror sync; Tier-0/1 do not.

Do NOT redo: RM-208 / RM-209 / RM-220 / RM-326 / RM-327 / RM-328 / RM-338 are
      CLOSED (LEDGER 1324). RM-337 closed 2026-09-03 (LEDGER 1323). Do not
      re-open RM-220 part (B) as a blanket vocabulary gap - that hypothesis was
      refuted once already as RM-218, and the 2 zero-label rows that remain are
      a DIFFERENT mechanism (`{{as|}}` head-cut and `[[File:...]]` pipes), not
      an `{{ap|}}` form. Do not delete the 44x44 hit-target overlays - they are
      a deliberate audit floor; four of the five sibling sites were measured
      NOT broken.

Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES +
      git log.

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

LANES ARE CURRENT - no fast-forward needed next session. All five lane
worktrees (`ds`, `repo`, `research`, `true-audit`, `uiux`) were fast-forwarded
from `22e8bd0ef` to `81f7e734a` and pushed at wrap; `lane/uiux` had no upstream
and now tracks `origin/lane/uiux`. Checked before merging: every lane was
ahead=0 both locally AND on origin, all five worktrees clean with zero stashes,
so there was nothing to merge - the fast-forward was the whole job. Do not go
looking for unmerged lane work.

NEXT. Next free id is **RM-338**. Still open: RM-208 + RM-220 (lane 6),
RM-326/327/328 + RM-209 (lane 4).

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

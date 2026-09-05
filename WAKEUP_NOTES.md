# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-04f - RM-212: rc-shell test list guarded; RM-342 filed, and it is the bigger one (ON MAIN)

STATE. Sixth row of the day (LEDGER 1324 six-slice batch, then 1325 RM-339,
1326 RM-340, 1327 RM-341, 1328 RM-322, 1329 RM-212). ENGINE 1.280.0 unchanged,
Tier-1, one new guard. No worktree, no `web/` change, no digest re-stamp owed.

WHAT SHIPPED. `rc-shell/package.json:9` runs its Node suite as a single
`node --test <16 explicit paths>` string with nothing globbing the directory, so
the next test file added would run NOWHERE with every signal green. The list is
still exactly in sync (16 named, 16 on disk) - this closed an UNREALISED trap,
which is the cheapest moment to close one. Guard:
`tests/test_rc_shell_test_script_covers_the_dir_rm212.py`, 5 assertions, proven
red in BOTH directions (drop a name / add an unnamed file).

TWO FENCES ON THAT GUARD, both deliberate:
- **A directory glob is NOT the fix.** `package.json:12` pins `"node": ">=18"`
  and directory-mode `node --test` semantics differ across that range. Probed,
  not assumed: on Node v24.15.0 `node --test test/` does not reproduce the
  enumerated run cleanly here either.
- **It ASSERTS rather than skips when rc-shell is absent.** A guard that
  excuses itself when its subject vanishes is green over its own blind spot -
  the same shape as the still-open RM-214.

**RM-342 IS THE FINDING THAT MATTERS AND IT IS BIGGER THAN RM-212.** Having
guarded that the list covers the directory, I asked whether the list runs at
all. It does not: grepping `.github/workflows/*.yml` for `rc-shell`, `npm test`,
`npm run test` and `node --test` returns **ZERO** hits, and no pytest harness
runs them either (unlike `web/js`, which IS node-executed from Python). Those
**329 tests pass locally and are invisible to CI.** Worse,
`tests/test_overlay_a1_slider_apply.py:19` already justifies its own narrower
approach with "the rc-shell node tests cover the shell half" - the repo is
leaning on coverage no CI job produces.

So: RM-212 does NOT make rc-shell CI-covered. Do not read it that way.

NEXT SESSION
------------
Task: Pick the next open row. Next free id is RM-343.
      **RM-342 is the natural follow-on** (LANE 7, Tier-1): get the rc-shell
      suite running in CI. There is an in-repo precedent for the cheap shape -
      `web/js` is node-executed from pytest, and
      `tests/test_interrupt_panel.py:5` records a
      `node --test web/mc/arm_confirm.test.mjs` invocation - so a pytest harness
      would ride the existing CI job rather than needing a new workflow. Two
      traps are written into the row: Node must exist on the CI image, and a
      harness that SKIPS when node is missing reproduces exactly the
      self-excusing shape RM-212's guard was written to avoid.
      Also open: RM-214, RM-286/287, RM-291..RM-295.
      Bodies + acceptance in BACKLOG.md; ROADMAP.md carries the pointers.

Context: ENGINE 1.280.0, patch 16.15.1, :8860 serving. ROADMAP at 88.5 pct of
      its 81920-byte budget (guard warns at 90) - room for about one more row
      before another relocation pass is owed. Lane worktrees at
      C:\rc-worktrees\rc-lane-* were NOT touched today and still sit at
      a55ece97e - fast-forward before use.

Acceptance: whatever the chosen row states. Tier-2 rows (engine/scorer/schema/
      ENGINE_VERSION) need the full dual suite from the REPO ROOT plus a DS
      :8860 restart and a Share mirror sync; Tier-0/1 do not.

Do NOT redo: RM-212 (1329), RM-322 (1328), RM-341 closed-as-REFUTED (1327),
      RM-340 (1326), RM-339 (1325), RM-208/209/220/326/327/328/338 (1324). Do
      not re-measure the rc-shell 16/16 equality or the 329/0 suite result, and
      do not convert the test script to a directory glob - that is fenced with a
      measured reason.

Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES +
      git log.

---

# 2026-09-04e - RM-322: test-scope table re-measured, CI-unrun set split, tree list guarded (ON MAIN)

STATE. Fifth row of the day (LEDGER 1324 six-slice batch, 1325 RM-339, 1326
RM-340, 1327 RM-341, 1328 RM-322). ENGINE 1.280.0 unchanged, Tier-0/1, one doc
plus one new guard. No worktree, no `web/` change, no digest re-stamp owed.

THE ROW'S OWN NUMBERS WERE STALE WHEN I OPENED IT. RM-322 was filed 2026-09-01
carrying a re-measure of a table measured 2026-08-06; by 2026-09-04 that
re-measure had itself drifted, because this session alone added roughly a
hundred tests. Everything was re-derived from scratch.

MEASURED FRESH (`pytest <tree> --collect-only -q`, repo root, Python314):
  tests 20561 | agents/daemon_slayer/tests 10856 | agents/agent3_testing/suite
  359 | tools/tests 348 | benchmarks 7 | repo-root `pytest .` 32131.
  Invariant holds exactly: the five sum to 32131, so no sixth tree is hiding.
  `pytest tests` = 64 pct; dual suite = 31417 of 32131 = 98 pct.

THE REAL DEFECT WAS A CONFLATION, AND THE DOC ALREADY CONTRADICTED ITSELF.
It called all three non-local trees "uncovered", but `benchmarks` runs in CI
(`codspeed.yml:51`) - and the same document said so 17 lines further down. Now
split: **three trees / 714 tests** are outside both local suites, but only
**two trees / 707 tests** (`agents/agent3_testing/suite` + `tools/tests`) are
run by NO CI job. The table gained a CI column so the two can never be read off
one number again.

THREE TRAPS WORTH CARRYING.
1. **My CI invocation-site count was WRONG and the row was right.** I counted 7,
   it said 9. My regex wanted `pytest` at a line start / after `;&|` / after
   `run:` and missed two env-prefixed forms, `RC_REQUIRE_HOOK_GATE=1 pytest`
   (ci.yml:388) and `RC_REQUIRE_BUILD_ORDER_TABLES=1 pytest` (:412). Second
   time in one day for that pattern trap. The corrected nine, and the
   env-prefix warning, are now IN the doc.
2. **THE NEW GUARD WOULD NOT HAVE RUN WHERE IT MATTERS.** `ci.yml` carries
   `paths-ignore: ['**/*.md']`, so a docs-only commit triggers no full suite;
   `docs-guards.yml` covers that case and runs whatever
   `tools/md_guard_selector.py` prints. My guard was absent from the 65
   selected modules - the selector takes its universe from TRACKED files and
   mine was untracked. Staged, it selects at 66. **Stage a new md-reading guard
   before believing the selector.**
3. **A stale `file:line` cite is worse than none** - it reads as verified. The
   doc named `test_skip_condition_hygiene.py:59-60` as the producing side while
   `_TEST_TREES` sits at `:72`.

THE GUARD PINS SHAPE, NEVER COUNTS - the row explicitly forbade a count guard
and it is right: counts drift on almost every commit.
`tests/test_docs_operations_test_scope_rm322.py` asserts only that the doc table
names the same trees as `_TEST_TREES` and that the cite still lands on it. Both
sides read off disk. Do NOT "improve" it into pinning the numbers.

NOT DONE, deliberately: the `pytest . -n 8` line at the end of that section
still quotes a 2026-08-06 measurement (29840 passed). It is explicitly
date-stamped, so it is honest as written, and re-running the full root suite to
refresh a prose figure is not worth the wall-clock.

NEXT SESSION
------------
Task: Pick the next open row. Next free id is RM-342.
      Open: RM-212 (`rc-shell/package.json:9` names its 16 test files by hand,
      nothing guards the list against the directory - and memory
      `reference_rc_shell_test_script_enumerates_files` says a new file runs
      NOWHERE until added, so this is an unrun-gate row), RM-214 (vision-server
      `/monitor` path-disclosure guard skips itself once the file it probes for
      exists in CWD), RM-286/287, RM-291..RM-295.
      Bodies + acceptance in BACKLOG.md; ROADMAP.md carries the pointers.

Context: ENGINE 1.280.0, patch 16.15.1, :8860 serving. ROADMAP is at 87.6 pct of
      its 81920-byte budget after this session's relocation pass - room for
      roughly two more rows. Lane worktrees at C:\rc-worktrees\rc-lane-* were
      NOT touched today and still sit at a55ece97e - fast-forward before use.

Acceptance: whatever the chosen row states. Tier-2 rows (engine/scorer/schema/
      ENGINE_VERSION) need the full dual suite from the REPO ROOT plus a DS
      :8860 restart and a Share mirror sync; Tier-0/1 do not.

Do NOT redo: RM-322 (1328), RM-341 closed-as-REFUTED (1327), RM-340 (1326),
      RM-339 (1325), RM-208/209/220/326/327/328/338 (1324). Do not re-measure
      the test-scope table unless you need the numbers for a decision - they are
      dated and the doc says so. Do not add a guard pinning those counts.

Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES +
      git log.

---

# 2026-09-04d - RM-341 CLOSED, premise REFUTED; ROADMAP relocation pass done (ON MAIN)

STATE. Fourth row of the day (LEDGER 1324 six-slice batch, 1325 RM-339, 1326
RM-340, 1327 RM-341). ENGINE 1.280.0 unchanged, Tier-1. **No `web/` change at
all this row, so no live-half digest re-stamp was owed** - the only row today
that touched no web asset. Slice worktree and branch removed.

THE ROW WAS WRONG AND SO WAS MY COUNTER-HYPOTHESIS. RM-341 said there were two
competing `VIEW_IDS` registries that had drifted and needed guarding against
each other. There are not. `web/js/lib/state.js` is the only real one; the
10-tuple at `dashboard/view_router_state.py:31` was read by **NOTHING** - no
importer, no `import *`, no `getattr`/`importlib`, and neither of the module's
two tests takes it. Both branches the row offered (add the 2 ids / guard
containment) were wrong. So was the subset reading the row itself argued for
and that I initially accepted: the module docstring at `:16` claims the machine
maps "to one of `VIEW_IDS`", and that claim is FALSE - `derive_view` returns
exactly 5 ids against the tuple's 10, confirmed two ways (ast + an exhaustive
dynamic sweep).

**A constant that looks like a contract but has no readers costs more than it
documents.** Its only observed effect was manufacturing the false "drifted by
3" finding that created this row - which I then re-measured to 2 before filing,
when the real answer was that the comparison was meaningless either way.

WHAT SHIPPED INSTEAD. The tuple is deleted and the docstring repaired, and the
guard the row SHOULD have asked for is in place:
`tests/test_view_router_registry_rm341.py` pins that every id `derive_view` can
return exists in the canonical JS registry - SUBSET, not equality, because the
JS list legitimately holds manual-only views. That closes a real silent-rot
channel the dead tuple never covered: the module is a declared test mirror, so
a view renamed in `state.js` would leave it deriving a stale id with its
existing tests still green, since they never cross the language boundary.

TRAPS WORTH CARRYING.
1. **Ask "who reads this?" before "are these two in sync?"** The sync question
   presupposes both sides matter. A sibling sweep of all 7 module-scope
   constants found `VIEW_IDS` was the only dead one - a clean result, recorded
   so nobody re-asks.
2. **A relocation pass can hide OPEN work.** Mine first classified RM-12 and
   RM-15 as "pure closed" - both carry OPEN halves - because my line indices
   were 0-based and `sed` is 1-based, so I inspected the wrong rows. Caught it,
   then restricted the pass to the 8 rows closed THIS SESSION and asserted
   programmatically that none carries an OPEN half.

ROADMAP BUDGET: **now 87.6%** (was 89.9, guard warns at 90). The 8 rows closed
2026-09-03/04 were relocated verbatim to `docs/ROADMAP_HISTORY.md`.
RM-329..RM-336 was deliberately LEFT in ROADMAP despite being shipped, because
it carries the live "next free id" pointer - do not relocate it without moving
that pointer somewhere first. Room for roughly two more rows before the next
pass is owed.

NEXT SESSION
------------
Task: Pick the next open row. Next free id is RM-342.
      Open: RM-322 (LANE 7, doc-vs-measured test-scope drift at
      `docs/OPERATIONS.md:27`), RM-212 (`rc-shell/package.json` names its test
      files by hand, nothing guards the list), RM-214 (vision-server `/monitor`
      path-disclosure guard skips itself), RM-286/287, RM-291..RM-295.
      Bodies + acceptance in BACKLOG.md; ROADMAP.md carries the pointers.

Context: ENGINE 1.280.0, patch 16.15.1, :8860 serving. Lane worktrees at
      C:\rc-worktrees\rc-lane-* were NOT touched today and still sit at
      a55ece97e - fast-forward before using one.

Acceptance: whatever the chosen row states. Tier-2 rows (engine/scorer/schema/
      ENGINE_VERSION) need the full dual suite from the REPO ROOT plus a DS
      :8860 restart and a Share mirror sync; Tier-0/1 do not.

Do NOT redo: RM-341 CLOSED-as-REFUTED (1327), RM-340 (1326), RM-339 (1325),
      RM-208/209/220/326/327/328/338 (1324). **Do not re-add a Python-side
      `VIEW_IDS`** - it was deleted on measurement, not on taste, and the
      docstring carries a do-not-re-add note. Do not assert equality between
      the JS registry and the mirror's derive range; subset is correct and
      `historical-pgr` is the documented manual-only case. Do not re-derive the
      id census, the view-registry census, or the drift count - all measured
      and corrected today.

Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES +
      git log.

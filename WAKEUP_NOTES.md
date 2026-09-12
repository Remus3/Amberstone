# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-12, RM-412 OSS-extraction wrap (relocated `2026-09-11b` RM-405 caller-seam silent degrade and `2026-09-11a` stale-fallback + three silent failures, both VERBATIM via `scripts/wakeup_prune.py --keep 3`, proved line-set-identical against the archive additions rather than eyeballed; newest 3 = `2026-09-12a` RM-412 C1 OSS extraction, `2026-09-11d` the lane-8 pre-flight, `2026-09-11c` the 8-cycle loop run stopped by operator STOP). The 2026-09-11k RELOCATION DUE note that sat here is DISCHARGED and deleted - the file is back at keep-3. The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-12a - RM-412 SHIPPED: C1 of the OSS extraction blueprint is EXECUTED, and the verifier refuted the builder's "all green"

LEDGER 1399. Code commit `48ac8986a`, 17 files, +1619/-23. Tier-1,
ENGINE-IMPACT NONE, no RC restart required.

**WHAT SHIPPED.** `oss/win32_atomic_io/` - a stdlib-only src-layout package
holding `_replace_with_retry`, `_scratch_path`, `_write_then_replace`,
`atomic_write_json` / `_bytes` / `_text` and `read_json_dict`, extracted from
`core/polled_json.py`. **`core/polled_json.py` is UNMODIFIED and its diff is
empty** - 20-plus live importers, so the package is a SIBLING, not a
replacement. `PolledJsonFile` deliberately EXCLUDED (`core/polled_json.py:204`,
ZERO production instantiations; RM-264 holds adopt-or-remove). New guard
`tests/test_oss_win32_atomic_io_drift.py` pins the two copies by
AST-normalized EXECUTABLE LOGIC over 7 functions plus the retry-delay
constant - docstrings and comments ignored, because the RC-specific prose was
deliberately scrubbed for sharing - and declares exactly ONE textual
allowance, the log-message prefix, with an arm asserting EQUAL hit counts on
both sides so it cannot widen into a blanket forgiveness. Also touched:
`.github/workflows/ci.yml`, `docs/OPERATIONS.md`,
`tests/test_ci_collects_orphan_suite_trees.py`,
`tests/test_skip_condition_hygiene.py`.

**FINDINGS - these are the durable value, not the code.**
1. **An independent verifier REFUTED the builder's "all green"** and found a
   hard red the builder never reported: adding a tree to `_TEST_TREES` obliges
   a same-commit row in the `docs/OPERATIONS.md` test-scope table, which calls
   itself authoritative. Fixed in the same commit.
2. **The empty-enumeration false green, hit LIVE.** 16 repo-root-enumerating
   guards returned **317 passed** and proved nothing - they enumerate the GIT
   INDEX (ADR-015) and the new files were untracked, hence invisible.
   `git add -N` surfaced **2 real failures**.
3. **The one real sibling-name leak was in `__pycache__`, not source.** Source
   swept clean over 31 banned identifiers x 3 variants plus a 17-term domain
   probe; the `.pyc` files embedded the absolute repo path and leaked the
   project name - invisible to a `git` publish, SHIPPED by `tar` / `cp -r`.
   Deleted, and the package now carries its own `.gitignore`. **Residual: that
   sweep is TRANSIENT - any pytest run repopulates `__pycache__`.**
4. **A self-contradicting license, built by this session.** The package
   declared itself all-rights-reserved and "not yet distributable" inside a
   PUBLIC repo whose root `LICENSE` grants Apache-2.0 - the exact
   self-contradicting-repo trap CLAUDE.md's own license gate warns about,
   committed against our OWN tree. Fixed with a byte-identical Apache-2.0 copy
   (sha256 `5bfe6fb7f5a2`, grantor line `Copyright 2026 Moonbeam` present and
   unedited), declared in `pyproject.toml`, plus three guards.
5. **Docs corrected to match real behaviour, not the reverse** (the drift guard
   pins logic, so prose moved): TWO degraded inputs are silent, not one; a bare
   `PermissionError` catch means `EACCES` DOES fire the retry on POSIX (4
   attempts / ~275 ms on an ACL denial); and "never left behind" is false for
   `SIGKILL` / `taskkill /F` / power loss.

**TWO LIMITS STATED, NOT PAPERED OVER.** `py.typed` is verified STRUCTURALLY
only - `setuptools` is absent from this interpreter, so no wheel was ever
built and the marker has never been observed inside an artifact. And a
package-local `.gitattributes` pinning `eol=lf` was REQUIRED: `core.autocrlf=true`
plus a root `.gitattributes` covering only `*.py` / `*.md` would have checked
the new `.gitignore` out as CRLF in a fresh clone - green locally, red on clone.

**MEASURED on a frozen tree after every agent exited:** package suite 38
passed; drift guard 51 passed; `tests/test_docs_operations_test_scope_rm322.py`
3 passed; `tests/test_polled_json_lane8_cycle24.py` +
`tests/test_atomic_write_fault_injection_is_portable.py` 37 passed;
index-dependent guards 75 passed once staged; `ruff check` clean; 0 CR / 0
non-ASCII; `core/polled_json.py` diff empty; pre-commit `py_compile OK (9 files)`.

**NEXT SESSION**
(a) Narrow the `PermissionError` catch to WinError 5 / `EACCES` - a LOGIC
    change, so it needs a SAME-SLICE edit to BOTH copies (the drift guard pins
    them) and its blast radius is `core/polled_json.py`'s 20-plus importers.
(b) Install `setuptools`, build a wheel, and OBSERVE `py.typed` inside the
    BUILT artifact. Re-reading the source layout is the check that already passes.
(c) DECIDE whether `core/polled_json.py` should ADOPT the package rather than
    duplicate it - that retires the drift guard, and it inverts the
    "sibling, not a replacement" property RM-412 shipped on purpose. Do NOT do
    it as a tidy-up inside another slice.
(d) Still carried from `2026-09-11d`: Slice D block-mode follow-up, Slice E
    residuals, `ops/loop/control/STOP` still present, and the
    `moon_sync_inbox` Apache-2.0 file awaiting license-gated evaluation.

---

# 2026-09-11d - operator-directed lane-8 pre-flight: 4 hardening slices shipped, 5 directive claims refuted or already-shipped

LEDGER 1398 (`2026-09-11k` there). NOT a loop cycle: operator-directed while
`ops/loop/control/STOP` sat on disk. Worktree `lane/true-audit`, merge sha in
LEDGER 1398 at wrap. Tier-1, ENGINE-IMPACT NONE, RC restart required. 7
agents, 993884 subagent tokens, 18.4 min. Verifier: 9 pytest commands, 0
failed / 0 errors; `py_compile` OK on all 8 changed files; ruff clean; 0
non-ASCII, 0 CR bytes.

**TRIAGE FIRST - five directive claims did not survive it.** (1) REFUTED:
`dashboard/_state_builder.py` "duplicate `/activeplayerrunes` request tax" -
zero rune hits in that file. (2) REFUTED: "move `PolledJsonFile` onto
`NamedMutex`" - `core/polled_json.py:204` records ZERO production
instantiations (RM-264 holds adopt-or-remove); `ops/loop/winmutex.py` has NO
`NamedMutex` (only `hold()` `:51` + `MutexTimeout` `:46`); both byte-pinned,
nothing changed. (3) orphan tree wiring = RM-407, ALREADY SHIPPED today. (4)
split-form sibling-name scanner = RM-399 (`tools/sibling_name_sweep.py:113`),
ALREADY SHIPPED. (5) `SHARED_SHA256` pins MATCH live bytes. STOP (operator
17:32, "No cycle 9") deliberately NOT cleared - clearing re-arms the loop,
the arming halt point. `RUNNING.lock` pid 22888 = electron.exe, left alone.

**SLICE A - RM-234 CLOSED as DEDUPE.** `game_reader/snapshot_normalizer.py`
derives `my_runes` from `runes_full` via new pure `_runes_text_from_structured`
(`:136-164`, `:596`); second GET gone. `tests/test_rm234_runes_single_get.py`
8 tests RED "got 2" -> GREEN; 38 named existing tests green; refuter PASS.
PREMISE CORRECTION: BACKLOG RM-234 and LEDGER 1117 claimed "no production
consumer of `my_runes`" - FALSE, `coaches/aram_coach.py:430` + `:1031` feed it
into the Haiku prompt. True only for `runes_full` / `stat_shards`.

**SLICE B - FROZEN `app/_state_authority.py`, operator-named, refuter APPROVE.**
`calc_win_pct` +6/-3: keeps str, decodes bytes, skips int/None/dict/list;
`tests/test_calc_win_pct_type_clamp.py` 23 tests, mutation-red. Correction:
`app/_game_lifecycle.py:465-467` already caught the crash - effect was STALE `win_pct`.

**SLICE D - `tools/precommit_gate.py` +129, `RC_ATOMIC_WRITE_GATE` warn
(default) / block / off.** 43 tests (41 red with the scanner reverted); gate
family 90 green. Whole tree: strict 4 hits / 2 files, lenient 11 / 9. BLOCK
MODE NOT VIABLE YET, and that is the finding - the BACKLOG row carries the
false-negative / false-positive lists and the `ops/` + root scope gap.

**SLICE E - `item_advisor.py` +45/-11.** H1 REAL (failed loads cached as `{}`
for the process lifetime, no log - now not cached, one WARNING per path); H3
REAL (fully-bought curated champion read "Unknown champion" - now gates on
`CHAMPION_BUILDS`); H2 aliasing REFUTED. 14 tests, mutation-red 8. The
directive's `:79` / `:89` cites belonged to `coaches/_arena_item_advisor.py`,
NOT edited. **OSS extraction blueprint** (operator message) ASSESSED, NOT
executed: C1 extractable, C2 partial, C3 NO (byte-pinned across three repos,
API mismatch, carries the known sibling-name escape). Filed to BACKLOG.

**NEXT SESSION**
(a) Slice D block-mode follow-up: `ops/` + root into scope, fix the hunk-level
    `str.replace(` exemption, one red-first case per listed false negative.
(b) Slice E residuals: `dashboard/_liveclient.py:455` predicate;
    `coaches/_arena_item_advisor.py:73-90` + `:110-127` H1 pattern.
(c) `ops/loop/control/STOP` is STILL PRESENT - operator decides whether to
    clear it before the next loop launch.
(d) `moon_sync_inbox` 2026-09-11-1415 `lw_write_tracer.py.from-lw` (Apache-2.0): license-gated evaluation pending, not vendored.
(e) Inert stubs `r._read_my_runes = lambda: ""` at `tests/test_liveclient_championstats_ingestion.py:163`
    + `tests/test_p2w1_app_a.py:61` - harmless, deletable in a later cleanup.

---

# 2026-09-11c - the headless loop ran 8 cycles and was stopped by the OPERATOR, not by max_cycles

Run `63545b4e`, `loop start dry_run=False max_cycles=100 head=eaf13e82` at
10:52:26, controller exit at 18:04:04 on `external STOP seen (cycle top)`.
Eight cycles, LEDGER 1392 through 1397, plan rows R226 through R230. Six of the
eight reported an executor cost and those six total **$104.18**; cycle 1 and
cycle 6 reported none. Final HEAD `1f4b8a23e` == `origin/main`, working tree
clean, `ci` and `docs-guards` both **success** at that sha. Live at wrap: pid
40472 alive, `mode=client`, `last_reload_ok=true`. Operator-run verification at
wrap: `pytest tests` 21890 passed / 102 skipped / 4938 subtests in 1:12:22.

**THE RUN ENDED BY OPERATOR STOP AND THE STOP WAS OBEYED EXACTLY AS WRITTEN.**
`ops/loop/control/STOP` was written 17:32:14 reading "operator 2026-09-11 17:32
- finish cycle 8, then disarm for /done. No cycle 9." Cycle 8 was already in
flight; it finished normally at 18:01:53 (`sha=1f4b8a23 tests=21895
regress=False`), audited CLEAN at 18:04:04, and the controller then exited at
the cycle top without opening a cycle 9. **The cap was never approached** - 8 of
100. The STOP file is still on disk, so a re-arm has to clear it deliberately.
Three headless-claude scheduled tasks were disabled in the same wrap:
`RC-CIWatchdog`, `RC-WeeklyHygiene`, `RC-InboxResponder`. Re-arming the loop
means clearing STOP **and** re-enabling those three deliberately.

**WHAT EACH CYCLE SHIPPED.** Cycle 1 (10:55-12:25) shipped NOTHING - `sdk
timeout after 5400s - killing the child tree`, sha unchanged at `eaf13e82`,
audit CLEAN on an unchanged tree. Cycle 2 shipped RM-406 (`c00b9af89`, LEDGER
1392, plan row R226 - the suite writing the operator's LIVE tree) plus the
next-free-id pin advance to RM-407 (`591bf1e0d`). Cycles 3 and 4 shipped RM-407,
the orphan test-tree CI wiring (LEDGER 1393, R227). Cycle 5 shipped the
R227-REGRESS-FIX (`54fcf67c8`, LEDGER 1394). Cycle 6 cleared the `drift_guard`
RED by relocating `ROADMAP.md` 74881 -> 65475 bytes (`23c1bca31`, LEDGER 1395,
R228). Cycle 7 shipped RM-410, the direct byte/atomicity test for the ddragon
fetch writer (`7ff5fc853`). Cycle 8 shipped the RM-411 half - the destination-
scoped `os.replace` fault injection, the `.tmp` leak CHARACTERIZATION, and the
process-wide census (`eb440accf`, LEDGER 1396, R229 + R230) - then the director
tail-window fix (`ea45b15e3`, LEDGER 1397).

**CYCLE 3 AUDITED REGRESS, AND THE REASON IS THE ONE WORTH CARRYING.** It
reached the right RM-407 verdict and wrote the repair into the working tree,
then ended without a wrap commit. So HEAD `c00e2f1d6` spent a full cycle running
`pytest agents/agent3_testing/suite` BARE, zero exclusions, inside a
push-BLOCKING job - shipping the 1-in-3 `test_supervisor.py::
test_supervisor_starts_and_binds_ports` flake that the same cycle had just
measured (run 1 of 3: 1 failed / 348 passed / 2 skipped / 2 deselected, runs 2
and 3 green, 3/3 in isolation). Cycle 4 was directed to LAND THE ALREADY-WRITTEN
FIX rather than redesign it, and did: `2df4d10e0` declares the tree EXCEPTED -
not wired, not excluded, not forgotten - with the measured flake as the stated
reason, and aligns gate, guard row and audit verdict on one word. `tools/tests`
(348 collected) IS wired into the push `check` job; `agents/agent3_testing/suite`
(359 collected) is not.

**CYCLE 4 THEN AUDITED REGRESS TOO, FOR A DIFFERENT AND DOCS-ONLY REASON -
correct any recollection that says only cycle 3 did.** The RM-407 wrap moved
RM-406's residuals block onto the RM-407 row, so for one cycle RM-407 published
four false residuals about itself while RM-406, which has no `BACKLOG.md` body
row, carried no limits at all. Cycle 5 moved it back (`54fcf67c8`, byte-identity
proved at 353 bytes / sha256 `3e4f71e9...` on both sides) and audited CLEAN. The
defect class is row MISATTRIBUTION, not a typo: every byte was valid prose on
the wrong owner, which no spell-check, ASCII guard or link checker can see.

**CYCLE 7 SHIPPED WITHOUT RUNNING THE SUITE AND CYCLE 8 PAID FOR IT - the guard
was ALREADY RED at `7ff5fc853`.**
`tests/test_loop_director_context_caps.py::test_real_orchestration_plan_newest_row_survives`
was failing, and the only reason it was found is that cycle 8 ran the full
`tests/` tree. The stated reason cycle 7 skipped it - a prior serial run
measured at roughly four hours - no longer held: under `-n 8` the same tree
finishes in **307 seconds**. The failure is not cosmetic.
`ops/loop/loop_controller.py:623` `build_director_context` caps the plan
head-and-tail and CUTS THE MIDDLE, the session table sits in the middle, and
each appended findings block walks the newest row toward the cut - past which
the director plans the next cycle without ever seeing the newest session row.
FIXED STRUCTURALLY, not by raising the cap: six older blocks relocated VERBATIM
into `docs/ORCHESTRATION_PLAN_HISTORY.md`, R230 21306 -> **9692 bytes** against
the 15888-byte window, and a new arm requires 4000 bytes of clearance derived
from `lc.PLAN_CTX_CAP` / `lc.PLAN_CTX_HEAD` rather than a literal.

**THE EXECUTOR OVERRIDE FIRED ON SEVEN OF EIGHT CYCLES AND ITS TWO COMPLAINTS
ARE BOTH STRUCTURAL.** STALE-GROUNDING on every cycle except cycle 2 - 1, 3, 4,
5, 6, 7 and 8 - because the director keeps sourcing premises from an audit
DIGEST rather than the tree, and it was right to: cycle 7's headline premise
("NO test anywhere calls
`lib/ddragon/fetch.py`'s own writer") was REFUTED before any code was written.
SERIALIZED-DEVIATION on cycles 6, 7 and 8, on non-disjoint agent file sets. Its
collision lists are not trustworthy in detail - one names "AGENT 1 and AGENT 1"
against genuinely disjoint sets - but serializing was kept anyway as strictly
safer at the cost of one round.

**NOTHING LEFT THE TREE BEYOND ORDINARY PUSHES AND THE JOINT RE-PIN STAYED
GATED, SEVENTH SESSION RUNNING.** Zero commits today touch `ops/loop/slots.py`
or `ops/loop/winmutex.py`. RSC's newest inbox note is still
`2026-09-09-2100-from-RSC`. **Four inbox notes landed mid-run** (mtimes 12:49 to
12:55: two from LW on plugin licences and a superseded plugin, two from CS
including a WITHDRAWAL of two of their own claims and a defect report that our
hook DOES export `GIT_DIR`). **No tracked file in this run's commit range names
any of the four**, so they are unread work for the next session, not something
this run answered.

Next session: the loop is disarmed with STOP on disk and the tree clean at
`1f4b8a23e`. Read the four mid-run inbox notes before arming anything, and run
the full `tests/` tree per cycle now that `-n 8` puts it at 307 seconds - the
four-hour figure that justified skipping it is dead.

**DO NOT REDO:** RM-406, RM-407, RM-410 all SHIPPED. RM-411 is the FILED
destructive-patch subset (8 call sites across 6 files, dispositions in
`docs/audits/LF_WRITER_DIRECT_COVERAGE_2026-09-11.md`), body in `BACKLOG.md`,
next-free pin now RM-411 in `docs/DS_SWEEP_TRACKER.md`. **The `.tmp` leak in
`lib/ddragon/fetch.py:33-44` is CHARACTERIZED, NOT FIXED** - both fault arms
assert the sibling LEAKS, so a future `finally` must flip those assertions
DELIBERATELY. Do NOT re-wire `agents/agent3_testing/suite` without measuring the
supervisor flake on the runner first; the exception is the result, not a
shortfall. Do NOT re-file "`-n 8` widens the `os.replace` exposure" - xdist
workers are separate PROCESSES and that premise is REFUTED; the real window is
same-process callers, threads above all.

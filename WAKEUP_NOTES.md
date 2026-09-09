# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-09, RM-392 shipping pass (relocated `2026-09-08g` RM-389; newest 3 = RM-392 shipped `2026-09-09c` + RM-392/RM-393/RM-394 filed `2026-09-09b` + RM-390/RM-391 `2026-09-09`). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-09c - RM-392 ADOPTED SCOPE SHIPPED: two lines of code, and the row it was not looking for was five times its filed size

Single-row headless session, operator AWAY. Tier-1: one test-support fixture, no
engine, no `ENGINE_VERSION` bump, no DS bounce, nothing outward. LEDGER 1374.

**The change is two lines.** `tests/test_inbox_responder_runner.py:466-467` now
opens the session-scoped `git_repo` fixture with
`if shutil.which("git") is None: pytest.skip(...)`, plus a `:454-465` docstring
saying why this shape and no other. That was the whole adopted scope, twice
adjudicated down to one site before this session started.

**Measured both sides, same box, same command, PATH sanitized so
`shutil.which("git")` is `None`:** before `18 passed, 205 errors` (205 ERROR
lines, 204 unique ids - the filed figures, to the entry); after `18 passed,
204 skipped, 1 error`. The stated acceptance was 204 errors -> 204 skips, and
that is what happened.

**The 1 residual error is PRE-EXISTING and is not this defect** - checked
against the BEFORE log, not asserted. It is `_live_surfaces_unchanged` teardown
at `:214` failing `assert _TMP_LOGS`: a positive control that cannot tell "the
arms were skipped" from "the runner is broken". Left alone on purpose.

**My own edit staled the row's citations inside the same commit, and my first
correction of that was wrong twice.** Re-deriving after the last edit caught the
gated spawns `:462,465` -> `:475,478` and `world` `:488` -> `:501` (I had
already written the stale `:488` into the new docstring). The GATE caught the
rest: the insertion is `14 1` in `git diff --numstat`, not "13 inserted lines",
and my warning scoped itself to "every `:4xx` number" while a `:29xx` cite sat
in the same paragraph (`:2965,2966` -> `:2978,2979`) and TWO stale cites sat in
the RM-393 row three lines below (`:482` -> `:495`, `run` helper `:461-463` ->
`:474-476`). RM-393 is the next row, so that one would have shipped pre-edit
numbers to the next session. All corrected in the tree.

**RM-394 was filed at one-fifth size, and finding that out was the session's
real yield.** Running the target file alongside the hygiene guard produced an
unrelated red: `test_universe_covers_every_test_bearing_tree_in_the_repo`, 8
phantom test trees, all under `ops/runtime/responder_export/<sha>/`. Those
export trees are a COPY OF THE REPO, so the class is any guard that globs the
repo root and filters by a HAND-LIST instead of by git. A sweep (22
`os.walk(`/`rglob(` sites anchored on ROOT/REPO in `tests/*.py`) measured FOUR
red guards: `test_frozen_file_list_contract.py` (filed),
`test_skip_condition_hygiene.py:1420`, `test_anthropic_base_url_pin.py:74`,
`test_target_state_caller_p1l4.py:197`. **The gate then found a FIFTH by
running the whole suite** - `test_rm364_prompt_sanitizer_population.py`
`::test_anthropic_egress_census_is_fully_classified`, 50 phantom builders,
assert `:426` - which that grep CANNOT see, because its enumeration spans two
lines (`REPO_ROOT / root` on `:408`, `rglob(` on `:411`). **So 22 is not a
bound.** Five measured red; 18 grep hits are candidates; the real candidate set
is bigger by an unmeasured amount. Adding `responder_export` to one
`HEADER_SCAN_SKIP_DIRS` repairs one of five.

**Do NOT redo.** Do not re-measure the 204/205 reproduction. Do not widen the
gate to a second site - the residual false-RED tail is an explicit non-goal in
the row. Do not delete the `responder_export` trees to make the five guards
green; that is the symptom, it is destructive, and nobody asked. Do not extend
any hand-list.

**Suite state at wrap, measured on this tree, not inherited:** `pytest tests -n 8`
= `5 failed, 21632 passed, 97 skipped, 4921 subtests` in 248s, and the 5 reds are
EXACTLY the five RM-394-class guards. Nothing else in `tests/` is red. The gate's
run also showed a 6th, `phase8_smoke/test_sr_draft_profile_engine.py`
`::TestLiveEngineIntegration::test_live_three_profiles`; it passes standalone and
did not recur here - parallel-only flake.

**CI on `main` is RED at `58468b276` and it is NOT this change - do not debug it
as if it were.** `docs-guards` is GREEN. `ci` fails in the `check` job at the
`Install Playwright Chromium` step, before pytest ever runs:
`apt` cannot fetch `dl.google.com/linux/chrome-stable/.../Packages.gz`, `Hash Sum
mismatch`, `Installation process exited with code: 100`. Reran `--failed` once,
same failure four minutes later, so it is an upstream index that is stale on
Google's side rather than a flake that clears instantly. No prior art in the repo
(first occurrence of this string). Rerun it before assuming anything; if it
persists across a day, THEN it is a row.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial. ONE
row per cycle, gate BEFORE the irreversible act, commit, push, LEDGER entry.
The RC <-> RSC exchange is the only outward scope; `CS`, `LW` and `LL` are on
operator-ordered STANDBY and their silence is STANDBY, never dissent. ARMING is
never adjudicated - if a row needs it, say so and move on.

**The next row is RM-393**, which is small, bounded and already fully measured:
inspect the return code in `_status` (`tests/test_lane_worktree_eol_rm343.py:92-94`)
and `_content_diff` (`:97-100`), so the four consumers that assert against EMPTY
(`:111`, `:135`, `:164`, `:261`) can no longer pass vacuously when git runs and
FAILS. Do NOT widen it into a general unchecked-`stdout` sweep - the 2-file /
7-site census that bounds it is in the row, and an earlier draft's "8 across 3
files" was already refuted.

**RM-394 is the bigger one and it is now a decision, not a measurement.** The
five red guards are measured; what is unchosen is the universe: `git ls-files`
(fixes every future ignored tree, stops scanning untracked working files) or
`os.walk` minus everything `git check-ignore` claims. Pick one, apply it to all
five, and do not add a sixth hand-list. Before you start, run the full `tests/`
suite once and take the red list from THAT - not from a grep, which already
missed one member of this class.

---

# 2026-09-09b - RM-392, RM-393 and RM-394 FILED: every inherited number was wrong, and so was the premise

Single-row headless session, operator AWAY. The row was FILED-BUT-ROWLESS and
filing it WAS the act. Docs-only, Tier-0: no code, no test, no `ENGINE_VERSION`
bump, no DS bounce, nothing delivered outward. Full account in LEDGER 1373.

**The row.** RC's suite carries external-binary call sites that ERROR on tool
absence instead of skipping. RC has a 2116-line guard against the MIRROR defect
(`tests/test_skip_condition_hygiene.py`) that is structurally blind to this one -
it audits skip CONDITIONS, and an ungated spawn has no skip to inspect.

**Every inherited number was wrong.** The prior session filed 115 call sites over
the 940 top-level `tests/*.py`. Re-derived from scratch, because the
classification was never persisted: 148 over 147 distinct lines, then a hostile
pass found it ONE SHORT (`tests/test_overlay_callouts_ui_audit.py:394-395`, a
real Chromium launch two independent AST passes both missed, correctly gated
anyway) - 149. The two passes reconciled SITE BY SITE, not by totals: two
`shutil.which` calls on one line at `tests/test_subagent_prompt_flag.py:76`, and
an aliased `_shutil.which` at `tests/test_inbox_responder_runner.py:2966`.
Separately 120 spawn sites across the four guarded trees, 31 of them
`sys.executable` - that pair derived twice, identical. The headline was off by
one in two places; measured here, git off PATH gives 222 collected, 18 passed,
205 error entries over 204 unique ids.

**Enumeration trap worth keeping:** git pathspec `*` crosses `/`, so
`git ls-files 'tests/*.py'` returns 1068, not 940. Depth-filter or be wrong.

**The inbound PATH warning does not reach RC, refuted twice.** No RC git hook
runs pytest (all six `.githooks` bodies read; `pre-push` is git-lfs only), and a
live probe shows the hook PATH differs by ONE prepended entry with all eight
probed tools still RESOLVING - only `git` RELOCATES, and a false-RED site needs
ABSENCE. **And the premise was wrong too:** `check=True` is not the
discriminator, since many ungated sites omit it and error identically.

**THE ONE RULE, paid for a third time.** Adjudication ran twice. Pass one
rejected the do-nothing option on a "live false-GREEN passing vacuously today";
the shape is real (and pass one found a site the census missed) but the "today"
half is false. My correction of THAT called the trigger set "wider" than tool
absence - it is DISJOINT, because absence raises `FileNotFoundError` before
`.stdout` exists. Three corrections deep, and each one needed the next.

**Do NOT redo.** The census (149 / 120 / 31 / 204-of-222) is measured and in the
rows. Do not re-derive the RM-392 totals; do not re-open whether the pre-push
PATH finding applies here; do not build a conftest fixture that converts absence
errors to skips - it was REJECTED on measurement, it moves the whole population
out of a STATIC auditor's reach, and `ci.yml:110-113` already records RC losing a
nightly to that pattern. Do not write a predicate keyed on `check=True`.

**Marked NOT-re-derived in the row itself, so nobody quotes them as measured:**
the bucket split over the 149, the truly-ungated-of-89 figure with its
false-positive rate, and the guard cost estimate.

**An INHERITED red the wrap ritual found, now RM-394.** The local docs-guard
suite returned 1 failed / 1752 passed / 1 skipped:
`tests/test_frozen_file_list_contract.py::test_frozen_arch_headers_are_a_subset_of_the_authority`
reports 24 orphan `frozen=yes` headers, ALL under
`ops/runtime/responder_export/<sha>/` - gitignored (`.gitignore:178`), 0 tracked
files, export trees dated 2026-09-08 so older than this session. `:171-185`
walks the DISK, so it is red on Legion and green on every CI runner. Do NOT
"fix" it by adding one more name to the `HEADER_SCAN_SKIP_DIRS` hand-list at
`:56-64`; the row states the two real options.

**The gate returned FAIL and all five findings were real.** In order: a future
act ("re-enabled at wrap") written in the past tense in the record itself; "CI
provisions git and chromium explicitly" when only chromium is explicit and git
arrives via `actions/checkout`; an "8 across 3 files" census that counted a
`check=True` call as unchecked (truth: 7 across 2); "55 of the 62" when 55
MENTION the fixture and one of them defines it (truth: 54 request it); and two
citation ranges off by a line at each end. All five were fixed in the working
tree BEFORE the commit. **That is the entire argument for where the gate goes.**

**A SECOND gate over the FIXES also returned FAIL, and the finding is sharper
than the first.** All five fixes held under independent re-derivation, including
a hunt for a helper-mediated eighth unchecked spawn that a naive AST pass cannot
see (three candidates, all correctly excluded - their callers assert on
`.returncode`). Both new defects were in RM-394, the row added AFTER gate 1, and
both were the SAME citation-range class gate 1 had just failed. **A row added
after a gate inherits none of its coverage and will repeat the defect the gate
just taught.** Gate whatever you add, however late and however small.

**Two instrument defects filed as notes, deliberately NOT fixed here.**
`tools/stop_claim_gate.py:38` `CLAIM_COUNT` has no counterfactual or citation
suppression, unlike `CLAIM_FILE` (`:47-83`) which has both, so quoting a figure
IN ORDER TO REFUTE IT is unsuppressable and re-fires every turn for the rest of
the session. Patching the instrument that audits your own claims, in the same
session, to stop it flagging your own claim, is the hazard its own comments name
at `:74-77`. And three agents sharing one scratchpad collided on a common
filename; two intermediates were written inside that window and never
regenerated, so nothing sourced from them is quoted anywhere.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial. ONE
row per cycle, gate BEFORE the irreversible act, commit, push, LEDGER entry.
The RC <-> RSC exchange is the only outward scope; `CS`, `LW` and `LL` are on
operator-ordered STANDBY and their silence is STANDBY, never dissent. ARMING is
never adjudicated - if a row needs it, say so and move on.

**The next row is RM-392's adopted scope, and it is deliberately ONE SITE:** put
a `shutil.which` capability gate on `tests/test_inbox_responder_runner.py:462,465`
(the session-scoped `git_repo` fixture at `:453`). `shutil.which` is the ONLY
repair shape that passes both the new intent and the existing false-GREEN guard -
measured: `try/except FileNotFoundError -> skip`, `try/except OSError -> skip`
and probe-the-returncode -> skip ALL score UNRESOLVED against `scan_source`
(`tests/test_skip_condition_hygiene.py:1285`), and `:1539-1551` fails on anything
that is not CAPABILITY. Verify the repair by re-running the git-off-PATH
reproduction and asserting the 204 errors become 204 skips.

RM-393 is the follow-on after it: inspect the return code in `_status`
(`tests/test_lane_worktree_eol_rm343.py:92-94`) and `_content_diff` (`:97-100`).
Do not widen it into a general unchecked-`stdout` sweep - the 3-file census that
bounds it is in the row.

Start with `/clear`, bootstrap from CLAUDE.md + MEMORY.md + this file + `git
log`, then `python tools/perseus_recall.py "<the row in your own words>"` BEFORE
touching anything. Disable `RC-InboxResponder` before any suite run and re-enable
it at wrap. Never `pytest .`.

---

# 2026-09-09 - RM-390 and RM-391: two seams decided, and FIVE gate rounds that all found something

Two-row headless session, operator AWAY, one row per cycle. Both rows adjudicated
(two position agents, a distinct adjudicator that never graded its own work) and
both gated BEFORE the commit. Commits `84e42da40` (RM-390) and `0d54ee3af`
(RM-391), both pushed. RM-390's CI is genuinely green - `check: success` with 19
steps and ZERO skipped, `docs-guards: success`, `nightly-full-suite` skipped as a
push run always skips it. RM-391 is docs-only, so `ci` never fired (ci.yml
path-ignores `**/*.md`) and `docs-guards` is its gate. Responder slice 596 passed
/ 1 skipped (595 / 1 at `f36cc3a0b`, so exactly one arm added, in RM-390).
`RC-InboxResponder` was DISABLED for the suite runs and re-enabled before the
first commit. Full accounts in LEDGER 1371 and 1372.

**RM-390 DECIDED: the quotable set is the LIVE WINDOW ONLY.** `trial_rows` is a
single-file reader BY DECISION - it takes a path, never a root, and has no glob -
because consent is bounded by ONE agreement. History across agreements is
rendered outside the runner by a fan-out recipe now printed verbatim in spec
section 8, which doubles as the only pre-arm check that the live window is not
short. The losing position (a bounded spanning reader) lost on EVIDENCE TRUTH,
not cost: it added a SECOND way to be silently partial whose `complete=False`
flag is printed by a renderer that does not exist. Spec sections 8 / 15 / 16,
the `trial_rows` docstring, one mutation-proven arm.

**RM-391 CLOSED, docs-only, no code: the answered record takes no cap and no
pruner.** The adjudicator rejected BOTH drafted positions on a clause neither had
read - spec section 2 already licenses deleting ONE entry by hand, and
`tools/inbox_responder_runner.py:272-276` records such a deletion performed. So
the row's question was upside down: a name IS dropped, by a human, precisely in
order to re-cycle the note it names. Measured `answered - inbox` = 0 of 108, so a
pruner would drop nothing today.

**THE PROCESS FINDING, and it is the whole session.** Five gate rounds ran and
every one found something. RM-389's lesson was WHERE to gate; this session paid
its RIDER instead - an account of your own prior error is a claim too. **In
RM-390 my correction of a wrong number was itself wrong:** "archives 40" became
"archives 35" became a measured 36, because the rotation sees 71 lines (the cycle
appends its own row first), not 70. Neither cited test asserts an archived count
at all, so the spec now quotes none. **In RM-391 three claims made during the
adjudication were corrected before shipping:** the metrics ledger is NOT "trimmed
to 200 rows" (RM-388 made it ROTATE; `METRICS_CARRY_ROWS` is a carry tail), my
own correction of that quoted a row count from a file that gains a row every five
minutes, and "all dry-cycle stubs" was false (6 of 10 note-bearing rows are live
cycles). **And a contract was over-read in three files at once:** rule 7.2 bans
EDITING a delivered note and says nothing about a receiver archiving its own
inbox, so RM-391's flip condition rests on a GAP plus current practice, never on
a prohibition.

**Two traps worth keeping.** Python 3.13+ strips the common leading indentation
from `__doc__` at compile time, so `inspect.getsource(f).replace(f.__doc__, "")`
silently does NOTHING and a body scan then trips on the docstring's own prose -
split on the triple quotes instead, and assert the prose separately as a vacuity
control. And a `python -c` recipe printed in a doc must be RUN before it ships;
this one was, verbatim, from the repo root.

**Do NOT redo:** RM-390 and RM-391 in any form. Do not build a spanning or
root-taking `trial_rows`, do not add a cap or a pruner to the answered record,
and do not re-open the "corrected in three places" arithmetic (LEDGER 1370).

**Still open, unchanged:** the 39 FALSE-RED-risk external-binary call sites in
`tests/` (no row filed yet; the audit covered only the 940 top-level files, so it
UNDERSTATES), and the inbound RSC finding that a pre-push hook runs with git's
own PATH, which puts that classification in doubt in exactly the environment that
gates every push.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial. ONE
row per cycle, gate BEFORE the irreversible act, commit, push, LEDGER entry.
The RC <-> RSC exchange is the only outward scope; `CS`, `LW` and `LL` are on
operator-ordered STANDBY and their silence is STANDBY, never dissent. ARMING is
never adjudicated - if a row needs it, say so and move on.

`BACKLOG.md` "Reliability / hardening" has no responder row left open. The
strongest candidate is the one filed but ROWLESS above: **file a row for the
FALSE-RED external-binary call sites**, then decide its scope by adjudication -
RC has a 2116-line guard against false-GREEN skips and NOTHING against false-RED,
and the guard is structurally blind to an ungated `subprocess.run([...],
check=True)` because there is no skip to inspect. Measure before scoping: the
audit covered 940 top-level `tests/*.py` while 1068 `.py` are tracked under
`tests/`, so 128 subdirectory modules were never looked at. Re-probe the inbound
PATH finding first - it may change the classification of every one of them.

Start with `/clear`, bootstrap from CLAUDE.md + MEMORY.md + this file + `git
log`, then `python tools/perseus_recall.py "<the row in your own words>"` BEFORE
touching anything. Disable `RC-InboxResponder` before any suite run and re-enable
it at wrap. Never `pytest .`.

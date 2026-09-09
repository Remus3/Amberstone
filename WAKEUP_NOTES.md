# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-09, RM-394 shipping pass (relocated `2026-09-09b` the RM-392/393/394 filing note; newest 3 = RM-394 shipped `2026-09-09e` + RM-393 shipped `2026-09-09d` + RM-392 shipped `2026-09-09c`). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-09e - RM-394 SHIPPED: the decision was already made in code, and the gate caught the conversion trading a red for a silent green

Third row of the same headless day, operator AWAY. Tier-1: seven test-support
files, no engine, no `ENGINE_VERSION` bump, no DS bounce, nothing outward.
LEDGER 1376. Five parallel single-file slices, one merger, TWO read-only gates
before the commit - and the second gate existed only because the first one's
repairs were written after it ran.

**The row asked which universe to build. Neither had to be built.**
`tests/_repo_walk.py` already implements the tracked-set-primary answer, with
`EXCLUDED_DIRS` as a backstop and `tracked_relpaths()` returning `None` (never an
empty set) on git failure, plus its own anti-vacuity guard and four consumers.
**Settled as CODE, not as a recorded decision** - added in `a0a23b57c`
(2026-09-07, public-flip scrub) with no ledger row naming it, which is exactly
how five guards kept hand-rolling their own root walks beside it. So the fix was
ADOPTION, not invention.

**All five converted**, plus `responder_export` added to the shared
`EXCLUDED_DIRS` for the git-absent fallback - one entry in one shared list, which
is the whole difference from the per-file hand-list the row rejects. Notable
local call: `docs` was the only genuinely non-infrastructure skip anywhere in the
five, and it was DROPPED after measuring that `pytest.ini` `norecursedirs` does
not exclude `docs`, so a test landing there really would be collected and really
would belong in the scan.

**The gate refuted the claim that mattered.** I claimed none of the five could
pass on an empty enumeration. Four cannot. `test_skip_condition_hygiene.py`
COULD - `discovered - set(_TEST_TREES)` is empty-set-safe, and forcing the
enumeration empty left it at 56 passed. Unrepaired, the conversion would have
traded a machine-local RED for a silent always-GREEN, which is worse than what it
fixed. Anchored on the directory holding the guard itself
(`assert "tests" in discovered`, asserted against the DISK so it is not circular
with `_TEST_TREES`) and proven to bite by my own mutation probe. The gate's
second finding: the new `EXCLUDED_DIRS` entry was pinned only indirectly by
another guard's fixture, so `tests/test_repo_walk.py` pins it directly now.
**Both repairs were added AFTER gate 1, so a SECOND gate ran over them and the
docs - and it found two more defects, both in the post-gate material**: the
header said six changed `.py` when repair 2 made it seven, and the row still
carried gate 1's "the only failure across all six files" three sentences after
describing the repair that makes it two. LEDGER 1374 paid for this exact lesson
two rows ago; it took a third payment to actually gate the post-gate material.

**Counts, all re-derived against the OLD algorithms on this disk and all held:**
8 phantom trees, 34 phantom ctor sites, 50 unclassified builders, 36 frozen
headers of which 24 under `responder_export` (12 modules x 2 export trees). New:
12 headers, the 4 real test trees, 17 ctor sites = `CONSTRUCT_FILES`, 17 census
entries with 0 unclassified and 0 stale.

**Suite:** `pytest tests -n 8` = 21639 passed, 97 skipped, 4921 subtests, 0
failed. Three whole-suite runs agreed on every count and DISAGREED on one ERROR
(`_live_surfaces_unchanged` teardown, "live surfaces moved") - present in mine,
absent in gate 1, present in gate 2. That disagreement IS the evidence: the LIVE
RC process was measured appending to `ops/runtime/responder_metrics.jsonl` inside
the suite window, a fresh cycle row every five minutes from a changing pid.
External writer, not a regression - the responder runner module is non-hermetic
against a live RC.

**Do NOT redo.** Do not delete the `responder_export` trees. Do not extend any
hand-list. Do not "tidy" the two cosmetic divergences between the five slices
(`relative_posix` versus `p.relative_to(...).as_posix()`, one positional
`patterns`) - no behavioural effect, and churn on five freshly converted guards
is not worth it. Do not re-derive the phantom counts.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial. ONE
row per cycle, gate BEFORE the irreversible act, commit, push, LEDGER entry.
The RC <-> RSC exchange is the only outward scope; `CS`, `LW` and `LL` are on
operator-ordered STANDBY and their silence is STANDBY, never dissent. ARMING is
never adjudicated - if a row needs it, say so and move on.

**No row is queued - pick one.** RM-392, RM-393 and RM-394 all shipped today.
The three known-open items, none of them adjudicated into a row yet:

1. **`tests/_repo_walk.py` has no ledger row and four-plus-five consumers now.**
   That is the condition that caused RM-394: a settled decision nobody could
   find. Writing its row is cheap and prevents the next five divergent walks.
2. **`tools/stop_claim_gate.py:38`** - `CLAIM_COUNT` has no counterfactual or
   citation suppression, unlike `CLAIM_FILE` (`:47-83`) which has both, so
   quoting a figure IN ORDER TO REFUTE IT re-fires every turn. Note the hazard
   its own comments name at `:74-77` before touching it.
3. **`tests/test_inbox_responder_runner.py:214`** - the `_live_surfaces_unchanged`
   teardown asserts `_TMP_LOGS` non-empty, a positive control that cannot tell
   "the arms were skipped" from "the runner is broken"; it is the 1 residual
   error when git is off PATH. And the same fixture is non-hermetic against a
   LIVE RC writing `ops/runtime` mid-suite, measured today.

---

# 2026-09-09d - RM-393 SHIPPED: the helpers now inspect the return code, and the sibling census held up

Second row of the same headless day, operator AWAY. Tier-1: one test module, no
engine, no `ENGINE_VERSION` bump, no DS bounce, nothing outward. LEDGER 1375.

**The defect, stated honestly:** `_status` and `_content_diff` in
`tests/test_lane_worktree_eol_rm343.py` returned `subprocess.run(...).stdout`
with the return code inspected nowhere. A failing `git` exits non-zero with an
EMPTY stdout and its message on stderr, which `capture_output` swallows, so the
four consumers that assert against `""` would have passed vacuously. Not a live
false-GREEN - an assertion that could not fail for the reason it exists to catch.

**The repair is one helper.** Both delegate to `_query(args, cwd)` (`:92-109`),
which asserts `returncode == 0` and carries the command, rc, cwd and the
SWALLOWED STDERR in the message. `check=True` would inspect the code too; it was
rejected because `CalledProcessError` throws away the stderr text, which is the
whole diagnostic in this failure mode.

**TDD, RED watched first:** the new arm (`:122-144`) reported
`Failed: DID NOT RAISE` against the old helpers, and it ships with a positive
control (`:147-155`) so the gate cannot be met by raising unconditionally. The
git failure is manufactured with a `.git` gitfile reading `gitdir: nowhere` -
rc 128, empty stdout, and independent of whatever sits above `tmp_path`, which a
plain non-repo directory would NOT be.

**The sibling census was re-derived and the filed row survived it.** In
`tests/test_loop_audit_range.py` the sites at `:100,164,168,181` assert
MEMBERSHIP and fail loudly; `:58` feeds `_log_count`, whose three callers assert
`>= 2`, `== 2`, `== 4` (`:98`, `:116`, `:130`), so a failure returning 0 fails
all three. Nothing outside the row needed touching. Module green at 16 passed,
ruff clean.

**Citation shift, measured (`git diff --numstat` = `59 4`, net +55):** RM-393's
four consumer cites `:111,135,164,261` are now `:166,190,219,316`.

**Do NOT redo.** Do not widen this into a general unchecked-`stdout` sweep - the
census that bounds it is re-derived and in the row. Do not swap `_query`'s assert
for `check=True`; the stderr text is the point.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial. ONE
row per cycle, gate BEFORE the irreversible act, commit, push, LEDGER entry.
The RC <-> RSC exchange is the only outward scope; `CS`, `LW` and `LL` are on
operator-ordered STANDBY and their silence is STANDBY, never dissent. ARMING is
never adjudicated - if a row needs it, say so and move on.

**The next row is RM-394, and it is a DECISION, not a measurement.** Five guards
are measured red on Legion and green in CI, every one failing solely on the
gitignored `ops/runtime/responder_export/<sha>/` trees, which are a COPY OF THE
REPO. Pick the universe once and apply it to all five: `git ls-files` (fixes
every future ignored tree, at the cost of no longer scanning untracked working
files) or `os.walk` minus everything `git check-ignore` claims. Do NOT add a
sixth hand-list entry - that repairs one of five. **Take the red list from a full
`pytest tests` run, never from a grep:** the fifth member was invisible to the
22-site grep that found the first four, because its enumeration spans two lines.

**Also open, both from the RM-392 session and deliberately not fixed there:**
`tools/stop_claim_gate.py:38` `CLAIM_COUNT` has no counterfactual or citation
suppression (unlike `CLAIM_FILE` at `:47-83`, which has both), so quoting a
figure IN ORDER TO REFUTE IT re-fires every turn; and the module-scoped
`_live_surfaces_unchanged` teardown in `tests/test_inbox_responder_runner.py:214`
asserts `_TMP_LOGS` non-empty, a positive control that cannot tell "the arms were
skipped" from "the runner is broken" (it is the 1 residual error when git is off
PATH).

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
persists across a day, THEN it is a row. **CLEARED - do not chase it.** The next
push, `b286246bf` (RM-393), ran `ci` green: `check` conclusion `success`, read
from `jobs[]` and not from the run conclusion, so it is not
`reference_green_ci_run_may_have_skipped_the_job`. `nightly-full-suite` shows
`skipped`, which is the normal push-run shape. Two consecutive failures four
minutes apart and a clean run about half an hour later: transient upstream apt
index, exactly as suspected, and it never reached pytest.

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

# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-04c - RM-157 CLOSED: the invoice finally read, and it validated the reconstruction

Commits: `4cc862d0` (reconstruction + re-price), `027d1031` (invoice + BACKLOG filing),
`5adef80f` (doc-budget relocation). LEDGER 1188 + 1189.

Both routes to the billed number were shut at session start and were RE-PROBED, not
inherited: no `user` scope (billing 404), `list_connected_browsers` empty, repo PRIVATE.
Rather than stall, rebuilt the billing FORMULA from `runs/{id}/jobs` - GitHub bills
private Actions per JOB, ceil to the minute, 1x on ubuntu-latest, and the `repo` scope
already reads every input. Mid-session the operator granted `user`, so the invoice
became readable and CONFIRMED the derivation to ~6 percent (derived 2682 billed min for
Aug 1-4 vs the invoice's 2846 month-to-date). That validation is the durable result and
is written into memory as a general technique.

Numbers that settle earlier guesses: rate is **0.006/min** (not the 0.008 list figure I
first estimated with), allotment is **~3000/mo**, and the old
`settings/billing/{actions,shared-storage}` endpoints are now **410 Gone** - only
`users/{u}/settings/billing/usage` works. Actions Linux billed min: Apr 26 / May 1467 /
Jun 3003 / **Jul 6030 (first real bill, NET 18.13 USD)** / Aug 1-4 alone 2846. Doubling
month over month.

Call: **KEEP the per-push full suite.** ~64 USD/mo, and it buys the only pre-merge gate
on a repo with ZERO pull_request runs and a ~11 percent catch rate (4 of the 37 push
checks that completed FAILED). Every cheap narrowing was already taken, so further cuts
cut coverage.

Do NOT redo: RM-157 is CLOSED and its row is relocated to `docs/ROADMAP_HISTORY.md`
(2026-08-04) with a pointer left in ROADMAP. Do not restore the `/done` dispatch. Do not
re-pitch deleting the per-push suite on cost share - cite a catch rate. The push-volume
lever (branch-plus-PR for the headless loop) is FILED in `BACKLOG.md` under Platform /
observability, not open work in ROADMAP.

Next: pick the top open ROADMAP item. Watch the monthly `usage` row rather than the
cadence projection - July's 6030 is the last full-month fact.

---

# 2026-08-04b - RM-157 first half: the wrap summoned a suite the push already ran

The `/done` ritual's section 2c dispatch is RETIRED in both halves of the mirror pair
(`tools/done.md` + `.claude/commands/done.md`, copied byte-for-byte; drift guard exit 0).
Re-measured over `created>=2026-08-01`: 256 runs / 2126.6 min runner wall clock, of which
`ci` workflow_dispatch was 18 runs / 485.8 min - every one section 2c, every one a duplicate
of the push `check` run since RM-119's second half. 22.8 percent of all runner time for zero
signal. Sections 2b/8c now collect ONE run; the SHAPE note says Phase 2 fires CI by pushing.

**The measure-first instruction is what paid.** By run COUNT docs-guards (109) looks like the
problem; by MINUTES it is 8.4 percent, the smallest job in the repo, and the only watcher of
a docs-only push. CodSpeed is 3.7 percent. Both deliberately untouched - a triage done on run
count would have cut the cheap job and kept the expensive duplicate.

**Still OPEN and now an OPERATOR action: the billed number.** Every billing endpoint 404s
because the `gh` token carries `delete_repo, gist, read:org, repo, workflow` and NOT `user`.
Unlock is `gh auth refresh -h github.com -s user`, a device-code flow that cannot run
non-interactively. `/timing` still reports `billable.UBUNTU.total_ms = 0` with a correct
`run_duration_ms` on the same payload. Every figure above is WALL CLOCK, not billed.

Do NOT re-tune RM-156 (closed, CI-verified). Do NOT restore the dispatch - the two cases that
run no `ci` (docs-only push, non-main branch with no PR) were both checked and neither
justifies it. ROADMAP.md is at 71.5 KB against its 80 KB budget - tight, watch it.

**Fixed forward at wrap (LEDGER 1187, `89ca2314`).** `RC-WeeklyHygiene` pushed `cf1c49b9`
mid-session with 24 U+2713 glyphs in its report's Status column and turned `docs-guards` RED;
the red arrived attached to MY doc-sync push, not to the commit that caused it. Check blame
before diff when a wrap goes red. Root cause was `agents/agent6_auditor/charter.md` never
naming the ASCII rule that `test_agent6_reports_are_ascii` enforces - now named there.

---

# 2026-08-04a - RM-156: a timed-out job and a superseded one say the same word

Closed RM-156 (commit `c8199a96`). The filing said the push CI job had "13 minutes of
headroom and already blew it". **The 13 was wrong - measured over 40 runs it was about 3.**
The filing sampled the four runs around the failure, which is the middle of the
distribution and blind to the tail: successful `check` wall clock spans 22m17s to **36m49s**.

**One ceiling was bounding two independent tails.** The killed run (`30866367283`, 40m16s)
was slow in the SUITE - its dual-suite step had burned 38m41s against a 20m47s-27m40s norm.
The 36m49s run (`30820229244`), the slowest SUCCESS on record, was slow in SETUP: a 10m33s
`Install Playwright Chromium` cache miss on an otherwise normal suite. The 2026-07-28
arithmetic that produced the 40 modelled only the suite tail.

**Fix:** step-level `timeout-minutes: 45` on each dual-suite step, because a step killed by
its own timeout is marked FAILED (job concludes `failure`) while a job killed by the job
ceiling concludes `cancelled` - the same word as a concurrency supersede. Job ceilings become
backstops: `check` 40 -> 65, `nightly-full-suite` 30 -> 60. **The ordering is the invariant**
and is pinned by `tests/test_ci_job_timeout_headroom_rm156.py` (job >= step + 12): if a later
edit leaves job <= step, the job dies first and every overrun is silently `cancelled` again.

**`nightly-full-suite` had LESS headroom than the job that failed** (24m13s-28m08s against 30)
and was never mentioned in the filing. Both jobs got both halves.

**The premise is not in GitHub's docs.** They document only the job -> `cancelled` half. The
step -> FAILED half comes from `actions/runner` `src/Runner.Worker/StepsRunner.cs`. Recorded
as source-not-docs in the test docstring, so it gets re-measured if behaviour ever differs.

**Verifier refuted two of my claims, both real.** (1) I read the step-duration max off an
aggregate: it is 27m40s, not 25m29s. (2) `pyyaml` is installed only in `check`, so every
assertion in my new module AND in `test_ci_docs_guard_coverage.py` silently SKIPPED in the
nightly job - and my docstring had claimed an existing sibling covered that. It does not; it
keys on its own filename and is per-file, not per-job. Fixed with pyyaml on the nightly pip
line plus a per-JOB assertion. 8-mutation matrix: no mutation escapes all five tests.

**NEW, operator-raised at wrap: Actions minutes are blown out.** 255 workflow runs in the
first 4 days of August, and every push runs the full ~27-minute dual suite. Filed as RM-157.
**Do not confuse it with RM-156** - raising a timeout ceiling costs nothing unless it is hit;
the minute burn is the per-push full suite (RM-119's second half), which is a deliberate
coverage choice that now needs re-pricing.

Suite: 28554 passed / 108 skipped / 8102 subtests / 0 failed. ruff clean.

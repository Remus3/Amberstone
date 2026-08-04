# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

**RM-157 half-shipped 2026-08-04.** The `/done` ritual's section 2c dispatch is retired in
both halves of the mirror pair (drift guard clean) - re-measured at 18 dispatches / 485.8
minutes over the same 4 days, 22.8 percent of all runner wall clock, and every one a
duplicate of the push `check` run. CodSpeed (3.7 percent) and docs-guards (8.4 percent, the
biggest COUNT but the smallest job) were measured and deliberately LEFT ALONE. The BILLED
number is still unread: the `gh` token has no `user` scope, so every billing endpoint 404s,
and `gh auth refresh -h github.com -s user` is a device-code flow only the operator can run.

Suite: 28554 passed / 108 skipped / 8102 subtests / 0 failed. ruff clean.

---

# 2026-08-03g - lane 8 cycle 7: stale relay data that called itself perfectly fresh

Audited `core/liveclient_cache.py` (criterion 1 - it parses the `:8889` relay envelope, which a
separate process authors on its own release cadence). EXPECTATION recorded before reading:
unvalidated dict access, a broad `except Exception` masking a shape change, staleness math
trusting an upstream timestamp, maybe a non-atomic write. Scored honestly: the staleness-math
prediction was RIGHT and worse than predicted; the non-atomic-write prediction was REFUTED - the
module writes nothing, it is a read-through cache.

**Method was empirical, not by reading.** `_fetch_once` was driven with nine adversarial bodies
through a mocked `urlopen` BEFORE any edit. That is what turned a hunch into three measured
defects, and it also killed one hypothesis I would otherwise have "confirmed" by reading.

**FINDING 1 - `age_s` failed OPEN three different ways.** Missing/null `ts` with data present
returned `0.0` ("perfectly fresh") forever; a FUTURE `ts` was clamped to `0.0` by
`max(0.0, ...)`; a non-numeric `ts` raised from a `float()` sited OUTSIDE the `try/except`,
escaping into the poll loop which logged it at DEBUG and left `_snapshot` frozen. **Eight**
consumers gate on that number, so one timestamp-less envelope defeated every freshness gate at
once. Now fail-closed AND total: unestablishable age reports `_UNKNOWN_AGE_S` (86400.0, kept
FINITE because two consumers pass the value outward and `json.dumps(inf)` is not valid JSON).

**FINDING 2 (sibling grep, same root cause)** - `modes/shared_vision.py:66` clamped a future
frame stamp the same way, letting an untrustworthy frame through the 90s cap that exists to stop
exactly that. The other seven `float(... or 0)` sites are fail-CLOSED already - recorded as
measured negatives, not changed.

**RM-155 CLOSED.** Root fix is an autouse `RC_FUSION_SHADOW_PATH` redirect in `tests/conftest.py`
(the path resolves through the env var at CALL time, so the existing module-global redirects
could never reach it). Backfill was real, not hypothetical: this worktree's corpus was ALREADY
polluted and the invariants test was ALREADY FAILING when the cycle began - an inherited red, not
one I caused. Removed it, then ran the full suite TWICE with identical counts and the production
path never recreated.

**Two process lessons worth keeping.** (1) A mutation caught my own test being VACUOUS - it
asserted `age_s > 12.0`, which a 1970 stamp also satisfies, so deleting the guard stayed GREEN.
Tightened to assert the sentinel exactly. (2) The verifier returned CONFIRM on all 9 claims and
STILL found a residual I had missed - `age_s` raised `TypeError` for a directly-built `Snapshot`
because `_coerce_ts` only guarded the fetch path. A CONFIRM verdict is not the same as "nothing
left"; read the residuals.

Suites from repo root: `tests/` 18162 passed / 154 skipped; DS 10341 passed. ruff clean.
Commit `b529ca89`, LEDGER 1184. Deployed to the live tree and re-probed.

---

# 2026-08-03f - lane 8 cycle 6: a relay that reported only to a console it does not have, and a token literal the dashboard hands out

Audited `tools/liveclient_relay.py` - zero dedicated tests, running live as `RC-LiveClientRelay`.
Picked deliberately for a different SHAPE than cycles 4-5: an agent loop, not a server or a store.

**FINDING 1 - every diagnostic went nowhere.** The task's `<Command>` is `pythonw.exe` (no
console) and the module reported only via `print()`. It already KNEW - its own comment warns a
stale token "401s ... silently (pythonw, no console) -> coach dead" - and kept printing anyway.

**FINDING 2 - a dead token literal in FOUR files the dashboard SERVES UNAUTHENTICATED.**
`_serve_agent_file` has no auth at all and the dashboard binds `::`, so `GET /agent/<name>`
returns the source to anyone on LAN or tailnet (verifier confirmed reachable on both, not just
loopback). The literal is dead - proven by POSTing it to :8889 and getting 401 while the live
token 200s. **The fourth file was found by the test, not by me:** my hand grep checked the names I
happened to eyeball; the test reads `_AGENT_ALLOWED` off disk via `ast` and parametrizes over it,
and caught `phase_watcher.py`.

**FINDING 3** - upload target was a hardcoded LAN IP, sending the token in cleartext across the
LAN when both ends are the same machine. Now loopback, env-overridable. Verified :8889 accepts the
loopback POST *before* trusting the change.

**REFUTED:** no timeout-less call exists here (2s/3s already). My expectation was wrong.

**The logging test took THREE attempts to become non-vacuous, by two different mechanisms.** v1
read pytest's own root-logger handlers (`basicConfig` is a no-op when handlers already exist), v2
used a fixed marker that a stale log file already contained. Only mutation testing ever said so.

**The verifier REFUTED a measurement of mine.** I had recorded `screen_agent`/`phase_watcher` as
"already file-logging, the template to copy". They call `basicConfig` with no `filename=`/
`handlers=` - stderr only, discarded under pythonw exactly like a print. **My grep counted the
string `basicConfig` as evidence of file logging** - the function name, not the argument that
matters. RM-154 rewritten; it was pointing the next implementer at a broken template.

**Then the deploy caught a regression the diff could not.** With the FileHandler live and no game
running, the relay wrote a WARNING every ~6s: ~2 MB/day burying the one line that matters. Giving
a silent module a channel is only half the job. Now WARN-on-change / DEBUG-on-repeat / INFO-on-
recovery. Measured live: old process ~50 warnings in 5 idle minutes, new one logged once and grew
**0 lines in 45 idle seconds**.

**RM-155, found by accident and worth more than it cost: the RC suite is NOT IDEMPOTENT in a fresh
tree.** `data/fusion_shadow.jsonl` is gitignored; run 1 SKIPS the invariants test and passes -
and the suite itself writes 1 record to that production path. Run 2 reads the 1-record corpus,
stops skipping, and fails. Measured end to end. Never bites a dev box (main tree has 565 records).
NOT caused by this slice - main tree at HEAD passes.

Also self-inflicted and owned: my first RM-154 draft blew the ROADMAP 80 KiB CI budget; fixed by
compressing rows and leaving narrative in the LEDGER where it belongs.

22 tests, 5 mutations RED. RC `tests/` 18136 passed / 154 skipped; DS 10341 passed.
LEDGER 1183 (+ post-deploy addendum). Deployed + verified live on the relay task.

**Session wrap (cycles 3-6, one session).** Four files audited end to end, all 7 dimensions each:
`lcu/lcu_postgame_collector.py` (1180), `dashboard/api_schema.py` + `_handler.py` (1181),
`core/riot_api_cache.py` (1182), `tools/liveclient_relay.py` + 3 sibling agents (1183). Plus the
cycle-2 merge and its two process findings (1179). **Filed, not fixed: RM-151..RM-155.** At wrap,
`drift_guard` flagged ROADMAP at 100 percent of its 81920-byte budget - relocated the CLOSED
RM-04 roster sweep (13589 bytes, zero open markers) verbatim to `docs/ROADMAP_HISTORY.md`,
leaving a fence that keeps the two probe hazards. ROADMAP now 68892 bytes / 84 percent.

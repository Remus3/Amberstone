# NOW-7 measurement pass - logger-leak detector, REPORT-ONLY (2026-10-03)

ROADMAP NOW-7 requires a report-only measurement before any gate is armed. This
is that measurement. Nothing here asserts; no green test can go red.

## Instrument

- `tests/_logger_leak_report.py` - wraps `pytest_runtest_protocol` (setup +
  call + teardown), snapshots `propagate` / `level` / `handlers` (identity) /
  `disabled` for root plus every `logging.Logger` in
  `logging.root.manager.loggerDict`, diffs after teardown, appends JSONL rows
  (`nodeid, logger, attribute, before, after, created`).
- DEFAULT-OFF: inert unless `RC_LOGGER_LEAK_REPORT=1`. Output dir
  `RC_LOGGER_LEAK_REPORT_DIR`, default `ops/runtime/logger_leak_report/`
  (gitignored), one file per process (Windows O_APPEND is not atomic).
- A logger CREATED during a test is compared against the stdlib default, so an
  import that merely creates a logger is not a row.
- The detector's own failures land in `attribute: "_detector_error"`, a bucket
  named after the INSTRUMENT, not the subject. Measured count: 0.
- Registered from `tests/conftest.py` by importing the hook name.
- `tests/test_now7_logger_leak_detector.py` (7 tests): planted leak recorded;
  mutate-and-restore records nothing; new default logger is not a leak; new
  logger with cut propagation is; flag parsing; end-to-end in a subprocess -
  only the leaker is recorded, and nothing is written when the flag is unset.
  Non-vacuous: forcing the hook on regardless of the flag turns the inert test
  red (1 failed, 6 passed), restored to 7 passed.

## Run and coverage - HONEST STATEMENT

1. `RC_LOGGER_LEAK_REPORT=1 python -m pytest tests -q -p no:randomly`
   (worktree root, serial). `python -m pytest` was used, not bare `pytest`
   (RM-486 exit 127). The run did NOT complete: it was killed by the harness
   2h background ceiling at 91 percent. Measured from the progress output:
   22711 of 24947 collected tests executed (22566 pass, 140 skip, 2 xfail,
   2 xpass, 1 FAILED - nodeid not recovered because the summary never
   printed; not investigated, out of scope). No exit code exists for run 1.
2. Remainder: the 67 files from `tests/test_tft_roll_odds.py` onward (the file
   holding test #22712; 1741 tests of that file overlap run 1), same flag,
   separate report dir. Exit 0: 3973 passed, 4 skipped in 206.84s.
   Combined coverage: all 24947 collected tests ran at least once.
3. Overhead control: the same 67 files with the flag OFF took 211.12s, so the
   detector cost is within noise on that chunk. The slowness of run 1 is the
   suite, not the detector, on that evidence - unmeasured for the first 91
   percent.

## Findings

In-process suite (runs 1 + 2): **6 rows, 4 distinct tests, 4 distinct
loggers, 0 detector errors. Zero `propagate` rows. Zero `handlers` rows.
Zero `disabled` rows.** All 6 are `level`.

| Test | Logger | Change | Verdict |
|---|---|---|---|
| `test_p2w2_ds_f.py::FiveHundredBodyNoLeakTests::test_get_500_body_does_not_leak_raw_exception` | `daemon_slayer.server` | NOTSET -> CRITICAL | ARTEFACT: `setUpClass` :78 sets, `tearDownClass` :98 restores; credited to first/last test of the class |
| `...::FiveHundredBodyNoLeakTests::test_post_500_body_does_not_leak_raw_exception` | `daemon_slayer.server` | CRITICAL -> NOTSET | same pair, the restore |
| `test_p2w2_ds_f.py::NonFiniteFloatRejectTests::test_inf_enemy_share_is_rejected_400` | `daemon_slayer.server` | NOTSET -> CRITICAL | ARTEFACT: :139 / :153 class pair |
| `...::NonFiniteFloatRejectTests::test_no_route_emits_bare_nan_token_in_body` | `daemon_slayer.server` | CRITICAL -> NOTSET | same pair, the restore |
| `test_performance_tracker_lane8_cycle23.py::TestSecretIsNeverLogged::test_a_raising_record_result_cannot_put_the_key_in_the_log` | `rc.tracker` | NOTSET -> DEBUG | REAL LEAK: `setLevel(DEBUG)` at :380, never restored |
| `test_tft_live_analysis_lane8_cycle43.py::TftLiveAnalysisAuditTest::test_w5_upstream_error_text_is_redacted_before_it_is_logged` | `rc.tft.live` | NOTSET -> DEBUG | REAL LEAK: `setLevel(DEBUG)` at :320, handler removed but level never restored |

So: **2 real leaks (both level-only, both DEBUG, both benign-direction for
caplog - they widen, they do not blind), 4 rows that are one class-scoped
mutate/restore pair seen twice.** The NOW-6 shape (propagate cut) has ZERO
live instances in the current suite.

Out-of-process (separate pytest child): `test_now6_logger_leak_regression.py`
spawns a child pytest that inherits the env, so the detector ran there too
(file `leaks-main-35116.jsonl`): 5 rows on
`test_rewind_timeline_429_retry.py::...::test_retry_only_dry_run_leaves_db_bytes_unchanged`
- `rc.lcu` NOTSET -> WARNING (pre-existing logger), plus `PIL`,
`PIL.Image`, `PIL.PngImagePlugin`, `PIL.JpegImagePlugin` created at WARNING
(import-time creation with a non-default level; noise for a gate). These are
NOT part of the in-process count above.

## Implications for arming (NOT done here)

- A gate arming on pre-existing-logger changes would turn exactly 2 tests red
  today (plus the class-scope pairs unless class fixtures are attributed
  properly). Blast radius is small and measured.
- Required before arming: (a) treat a change restored by the end of the
  enclosing class/module as clean (the 4 artefact rows), (b) exclude or
  separately bucket `created: true` rows (PIL import noise), (c) do not let the
  env var leak into child pytests, or give children their own bucket.

## Arming (2026-10-03, second pass) - GATE ARMED

### Fixes and prerequisites

- The 2 real leaks are fixed. In `tests/test_performance_tracker_lane8_cycle23.py`
  (`rc.tracker`) the level is saved before `setLevel(DEBUG)` and restored in
  the existing finally. In `tests/test_tft_live_analysis_lane8_cycle43.py`
  (`rc.tft.live`) it is restored next to `removeHandler`. Non-vacuous: the
  HEAD copies of both files, run under the armed gate, go red at exactly those
  two tests (`'NOTSET' -> 'DEBUG'` on each logger). The fixed files are green.
- (a) Class/module scope: snapshots are taken around SETUP, CALL and
  TEARDOWN. A change made in CALL that is still present after the test's own
  teardown is that test's leak. A change made in SETUP or TEARDOWN (where
  `setUpClass` and class/module-scoped fixtures run) is held PENDING, owned by
  the test that made it. It is clean if restored by the end of the module.
  Otherwise it is raised at the module's last test, naming the owner. The
  `tests/test_p2w2_ds_f.py` pairs are now clean.
- (b) Import-time configuration counts as baseline. Collection-time imports
  are already in every pre-test snapshot. A module first imported DURING a
  test is bracketed by a `sys.meta_path` watcher (installed only while a test
  runs; the real loader is put back after exec), and its logger changes are
  marked import-owned. Found while arming: `coaches/_base_coach.py`
  `_silence_chatty_loggers()` sets `PIL.*` and `rc.lcu` to WARNING at import.
  That is where the first pass's child-process rows came from, not a test
  leak. Without the watcher, a narrow run that imports it lazily in a fixture
  would have gone red.
- (c) Nested runs: the first process to load the detector stamps
  `RC_LOGGER_LEAK_OUTER_PID`. xdist workers stamp `RC_LOGGER_LEAK_WORKER_PID`
  and stay active. Any other process that sees a foreign stamp (a child pytest
  spawned by a test, e.g. `test_now6_logger_leak_regression.py`) is inert in
  every mode.
- pytest's own capture handlers (`_pytest.*`) are left out of snapshots.

### Report-only re-run

`RC_LOGGER_LEAK_REPORT=1 python -m pytest tests -q -n 6 --dist loadfile
--timeout=300` (worktree root). This used xdist, NOT a serial run like the
first pass: the first pass's 2h+ serial runtime made a serial re-run
impractical. Result: **0 leak rows, 0 detector errors** (the report dir was
never created). Suite: 4 failed, 24873 passed, 144 skipped, 1 xfailed,
3 xpassed in 452s. One failure was this slice's own new test tripping
`test_no_environ_in_assert_operands` (now fixed). The other 3 are listed below.

### Armed run

Modes: the default is ARMED (a leak becomes a teardown ERROR on the leaker,
and the message names the logger, the attribute and before -> after).
`RC_LOGGER_LEAK_REPORT=1` means report-only. `RC_LOGGER_LEAK_GATE=0` disarms
the gate for one run.

- `python -m pytest tests -q -n 6 --dist loadfile --timeout=300`: 3 failed,
  24874 passed, 144 skipped, 1 xfailed, 3 xpassed in 456s. **Zero gate
  errors.** The 3 failures also fail with the gate disarmed, and they are in
  files this slice did not touch:
  `test_no_console_flash_scheduled_tools.py[ops/loop/adjudicator.py]`,
  `test_loop_concurrency.py[slots.py]` (sibling carrier digest drift), and
  `test_p2w2_ds_h.py::test_ephemeral_failure_message_redacts_stderr`
  (`_FakeProc` has no `args`).
- `python -m pytest agents/daemon_slayer -q -n 6 --dist loadfile`: 10933
  passed, exit 0. The gate is registered only by `tests/conftest.py`, so it
  does not run in that suite.

### Regression tests

`tests/test_now7_logger_leak_detector.py` runs a child pytest with the gate
armed and checks that:

- it goes RED at a planted call-phase leaker;
- it stays GREEN for caplog, a unittest `setUpClass`/`tearDownClass` pair, a
  pytest class-scoped fixture pair, and a lazily imported module that sets
  its own logger level;
- a setup-phase fixture leak is raised at the module boundary, naming the
  fixture's test;
- the same project is inert when it runs as a nested child.

There are also unit tests for import ownership, the import watcher, the
`_pytest` handler exclusion, the mode flags and process classification.

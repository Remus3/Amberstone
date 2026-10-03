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

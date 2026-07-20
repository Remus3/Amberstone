# Silent no-op exception handler triage - SPEC

Date: 2026-07-19
Status: SPEC (read-only triage; no source file was modified producing this)
Sizing script: `<scratchpad>/size_silent_excepts.py` (re-runnable, takes repo root as argv[1])

---

## 1. Measured population (this run, not carried forward)

Measured with `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
against `C:\Riot Commander`, excluding `tests/`, `Share/`, `python-embed/`,
`docs/_archive/`, `.git`, `node_modules`, `__pycache__`, venvs, `worktrees`.

Definition: an `except` handler whose body is ONLY `pass` / `continue` / `break` /
`...` (category `noop`), or ONLY a `<x>.debug(...)` expression statement, optionally
mixed with those no-ops (category `debug_only`).

| Metric | Measured |
|---|---|
| First-party .py files scanned | 756 |
| Parse errors | 0 |
| **TOTAL silent handlers** | **789** |
| debug-only | 173 |
| noop-only | 616 |
| broad (bare / `Exception` / `BaseException`) | 489 |
| narrow | 300 |
| debug-only x broad | 160 |
| debug-only x narrow | 13 |
| noop x broad | 329 |
| noop x narrow | 287 |

Delta vs the prior session's cited 781 / 166 / 615 / 510: total +8, debug-only +7,
noop-only +1, broad -21. The broad delta is a definition difference, not drift: this
script classifies a tuple handler as broad only if `Exception` or `BaseException`
appears in it, so `except (OSError, json.JSONDecodeError)` counts narrow. Treat 789 /
173 / 616 / 489 as the current baseline and re-run the script rather than reusing any
number in this table.

### Densest files (total silent handlers, debug-only in parens)

| Count | File | debug-only |
|---|---|---|
| 23 | `game_reader/snapshot_normalizer.py` | 23 |
| 18 | `ops/rc_supervisor.py` (FROZEN) | 0 |
| 17 | `app/_game_lifecycle.py` (FROZEN) | 2 |
| 16 | `coaches/_base_coach.py` | 7 |
| 15 | `coaches/arena_coach.py` | 7 |
| 14 | `coaches/aram_coach.py` | 2 |
| 14 | `lcu/lcu_rune_writer.py` | 8 |
| 14 | `tft/tft_live_analysis.py` | 4 |
| 13 | `core/tft_worker.py` | 3 |
| 12 | `agents/supervisor.py` | 7 |
| 12 | `tft/tft_coach_engine.py` | 1 |
| 10 | `dashboard/routes_pickban.py` | 4 |
| 10 | `dashboard/routes_state.py` | 4 |
| 7 | `performance_tracker.py` | 5 |
| 5 | `core/decision_detector.py` | 4 |
| 4 | `core/cost_tracker.py` | 4 |

All per-file debug-only counts named in the triage brief were reproduced exactly by
this run (snapshot_normalizer 23, lcu_rune_writer 8, agents/supervisor 7,
arena_coach 7, _base_coach 7, performance_tracker 5, cost_tracker 4,
decision_detector 4, routes_state 4).

### Frozen-file caveat

`ops/rc_supervisor.py` (18), `app/_game_lifecycle.py` (17), `core/log_setup.py` (6),
`lcu/lcu_client.py` (7), `core/game_snapshot.py`, `app/_loop.py`, `app/_health_monitor.py`
are on the CLAUDE.md frozen list. Together they hold 48+ of the 789. They are OUT OF
SCOPE for every batch below and need an explicit operator grant before any edit.

---

## 2. Classification

Classes: **A** real defect (a real failure is hidden), **B** best-effort-correct,
**C** too-broad (narrow the handler type), **D** mechanically blocked (the callee
already swallows and returns a sentinel, so no exception can reach the handler).

### 2a. A-CLASS FINDINGS

Three confirmed, one live-gated candidate group, one same-shape cluster.

---

**A1. `coaches/arena_coach.py:273` - permanently poisoned augment name map (CONFIRMED)**

`_augment_name_map()` builds `out` at :252, and on ANY exception inside the
`snap_dir.iterdir()` / `json.loads` / loop block (:253-272) logs at `logger.debug`
(:274) and then falls through to `_AUG_NAME_MAP_CACHE = out` at :275 - OUTSIDE the
`try`. The empty or **partially built** map is installed as the process-lifetime cache.
Every subsequent `_resolve_augment_apiname()` (:279-286) returns `None`, and per the
function's own docstring at :246-247 the caller then "skips augment persistence on that
tick" for the rest of the process. A mid-loop failure is worse than a total failure: a
partial map is cached and only SOME augments silently stop resolving. No warning, no
retry, no counter.

Fix shape: assign the cache only on the success path, or cache a `None` sentinel on
failure so the next call retries; escalate the log to `warning`.

Regression test (fails if the error is swallowed):
Reset `_AUG_NAME_MAP_CACHE = None`, monkeypatch `pathlib.Path.iterdir` (or
`json.loads`) used by that function to raise `OSError`, call `_augment_name_map()`,
then REMOVE the fault and call it again. Assert the second call returns a non-empty
map. Today the second call returns the cached `{}` and the test fails only once the
poisoning is fixed - so write it as a currently-failing characterization test. Second
assertion: `caplog` at WARNING level contains the failure, which is empty today.

---

**A2. `agents/supervisor.py:758` - post-game summary filing failure is invisible (CONFIRMED)**

`_file_post_game_summary` exists solely to call `self._scheduler.file_task(op="game-summary", ...)`
at :748-755. Success logs at `log.info` (:756-757). Failure logs at `log.debug` (:759)
under a broad `except Exception`. The logging is asymmetric: if filing has been broken
for its whole life, the operator sees no INFO line and no WARN line - identical to the
function never having been called. This is the RM-107 shape (a path that never works,
swallowed forever).

Fix shape: `log.warning` (or `log.exception`) at :758, matching the reconciler's own
`warning` at `agents/supervisor.py:467`. Optionally narrow once `file_task`'s raise set
is known.

Regression test: monkeypatch the supervisor's `_scheduler.file_task` to raise
`RuntimeError("boom")`, call `_file_post_game_summary(...)`, assert
`caplog.record_tuples` contains a record at level >= WARNING mentioning the summary.
Fails today (record is DEBUG).

---

**A3. `agents/supervisor.py:744` - rating enrichment silently dropped (CONFIRMED, lower blast radius)**

The `try` at :732 wraps both the file read AND the field-merge loop at :735-743. The
handler at :744 is already narrow (`OSError, json.JSONDecodeError`) so a merge-logic
bug would in fact propagate - but the `_lrf(...)` CALL at :728 sits inside the
ImportError-shaped guard at :729, so a bug INSIDE `_latest_rating_file` is caught by
`except Exception` and the summary silently loses `rating` / `label` / `stats` /
`mode_category`. The filed summary is then structurally incomplete with no signal.

Fix shape: move `rating_path = _lrf(...)` (:728) out of the try; keep only the
`from performance_tracker import ...` inside and narrow :729 to `ImportError`.

Regression test: monkeypatch `performance_tracker._latest_rating_file` to raise
`ValueError`, call the summary builder, assert the exception propagates (or that a
WARNING is logged). Today it is absorbed into a DEBUG line and `rating_path` becomes
`None`.

---

**A4. `game_reader/snapshot_normalizer.py:1056, 1104, 1133, 1161` - live-client rune/ability reads are unfalsifiably silent (A-CANDIDATE, LIVE-GATED)**

These four wrap `self._get(f"{LIVE_API}/...")` where `LIVE_API` is
`https://<host>:2999/liveclientdata` (`game_reader/poller.py:29`) and `_get`
(`game_reader/poller.py:250-253`) does NOT swallow - it lets `urllib` raise. So these
handlers are the sole swallow point for a 404 / endpoint rename / auth change on
`/activeplayerrunes`, `/playermainrunes?summonerName=`, `/activeplayerabilities`.

The consequence is real: these fields feed live coach prompts directly -
`coaches/aram_coach.py:350` (`My abilities (Q/W/E/R): {my_abilities}`),
`coaches/aram_coach.py:352` (`Enemy keystones: {enemy_runes}`),
`coaches/arena_coach.py:192`. A permanently-404ing endpoint degrades every coach prompt
with zero operator signal, forever. `_read_enemy_runes` (:1133) is the highest risk:
it queries by `summonerName=` (`:1119, :1124`) and the repo already carries a
name-vs-DDragon-id hazard note, so a Riot-ID-era rename would 404 per enemy, per tick,
silently.

**Not yet confirmed as a live failure.** Probe evidence gathered: `enemy_runes`,
`my_abilities`, `my_runes` are all absent from every persisted
`data/*coaching_data.json`. That is INCONCLUSIVE, not proof - those files are coach
OUTPUT, not the raw poller state dict, and the fields are not necessarily persisted.
Confirming requires one live game with the handlers temporarily escalated to `warning`.

Fix shape (independent of the live verdict): escalate to `log.warning` with a
throttle, or add a once-per-session "live-client subresource unavailable" counter, so
the failure is falsifiable at all.

Regression test: monkeypatch the mixin's `_get` to raise `urllib.error.HTTPError(...404...)`,
call `_read_enemy_runes([{...one enemy...}])`, assert a WARNING record is emitted (and
that a health/degradation counter increments). Today only a DEBUG line exists, so the
test fails until the fix lands. Add the symmetric test for `_read_my_abilities`.

---

**A5. Cache-the-failure cluster (SAME SHAPE as A1, lower likelihood - treat as A-shape / C-priority)**

`dashboard/routes_pickban.py:115, 146, 166, 201` each catch broadly and then pin the
empty result into a module-level cache OUTSIDE the try (`:117, :148, :168, :203`),
permanently serving an empty map for the process lifetime. Downgraded from A because
both backing files exist and are written atomically via `tmp.replace`
(`scripts/data_pipeline.py:82-85`), so a reader-side transient is not realistic today.
The structural hazard is identical to A1 and should be fixed in the same batch and by
the same rule: never cache a failed load.

Regression test (one parameterized test covering all four): fault the loader, call it,
un-fault it, call again, assert the second call succeeds.

### 2b. D-CLASS (MECHANICALLY BLOCKED) - do not attempt to narrow

The RM-107 shape recurs, and the blocking callees are now named:

| Handler | Blocking callee |
|---|---|
| `coaches/arena_coach.py:879` | `core/coaching_timestamps.py:73-74` (swallows, returns None) |
| `coaches/arena_coach.py:955` | `core/augment_shadow.py:112-113` |
| `coaches/arena_coach.py:971, 1008, 1021` | `coaches/_base_coach.py:66-68` (`load_json` -> `{}`) and `:100-102` (`safe_write` returns) |
| `coaches/aram_coach.py:557` | same `_base_coach.py:66-68 / 100-102` pair |
| `lcu/lcu_rune_writer.py:888` | `lcu/lcu_client.py:173-183` (`_request` returns None on URLError/OSError/TimeoutError/JSONDecodeError, and on non-2xx at `:160`) |
| `lcu/lcu_rune_writer.py:996` | `lcu/lcu_client.py:384` (`get_all_rune_pages` -> None) plus `:173-183` |

Note the contrast worth preserving: the rune-writer POST retry loop at
`lcu/lcu_rune_writer.py:1030` is NOT blocked and correctly escalates to `log.warning`
at `:1036`. That is the target pattern for the C-class handlers.

### 2c. C-CLASS (NARROW THE HANDLER TYPE)

Grouped by the narrowing that applies. Full list with reasons:

`ImportError` only (the import is the only raising statement):
`coaches/_base_coach.py:342, 458, 477, 484, 702`,
`coaches/arena_coach.py:587, 615`, `coaches/aram_coach.py:579`,
`dashboard/routes_state.py:672`, `agents/supervisor.py:744`.

`OSError` (and/or `json.JSONDecodeError`) file I/O:
`coaches/_base_coach.py:56, 97, 447, 582`, `coaches/arena_coach.py:468`,
`lcu/lcu_rune_writer.py:370, 488`, `performance_tracker.py:321, 396`,
`core/cost_tracker.py:489`, `core/decision_detector.py:690`,
`dashboard/routes_pickban.py:115, 146, 166, 201`, `agents/supervisor.py:758`.

`(TypeError, ValueError)` / shape errors:
`performance_tracker.py:263`, `lcu/lcu_rune_writer.py:920`,
`dashboard/routes_pickban.py:699, 710`, `coaches/aram_coach.py:586, 639`
(overlay teardown: `AttributeError, RuntimeError`).

Two C-class handlers deserve a log-level lift alongside the narrowing because their
siblings in the same function already use `warning`:
`performance_tracker.py:321` (siblings at `:322` and `:328` are `warning`) and
`agents/supervisor.py:758` (sibling at `:467` is `warning`).

### 2d. B-CLASS (CORRECT AS-IS)

Leave alone; a one-line comment is optional. The recurring correct shapes:

- Loop guards that retry next tick: `coaches/_base_coach.py:379, 464`,
  `coaches/arena_coach.py:603`, `coaches/aram_coach.py:641`,
  `lcu/lcu_rune_writer.py:574, 584`, `core/decision_detector.py:896`.
- Shutdown / cancellation cleanup: `agents/supervisor.py:346, 362, 374, 413, 477`,
  `coaches/_base_coach.py:362`, `lcu/lcu_rune_writer.py:366, 484, 566`,
  `core/decision_detector.py:97`.
- Prometheus / shadow telemetry with the real work outside the guard:
  `core/cost_tracker.py:277, 383, 406`, `coaches/_base_coach.py:682, 704, 746`,
  `dashboard/routes_state.py:235, 691`, `coaches/arena_coach.py:702, 1081`.
- Fallback chains with a working alternative path:
  `dashboard/routes_state.py:835, 851`, `lcu/lcu_rune_writer.py:431, 867`,
  `coaches/arena_coach.py:362, 691, 857`, `agents/supervisor.py:702`.
- Already-narrow skip-one-bad-row handlers: `dashboard/routes_state.py:42`,
  `dashboard/routes_pickban.py:141, 164, 198, 899`, `lcu/lcu_rune_writer.py:260`,
  `performance_tracker.py:131, 375`, `agents/supervisor.py:718`.

Also relevant to any "is it really invisible" argument: `core/log_setup.py:140` sends
DEBUG to the log file unconditionally, so `.debug()` handlers ARE recorded on disk.
The defect in the A-class cases is not that nothing is written; it is that nothing is
written at a level any operator, alert, or health surface reads, and that the failure
has no retry and no counter.

---

## 3. Batch plan (disjoint file sets, parallel worktree agents)

Each batch touches a file set disjoint from every other, so all six can run
concurrently in worktrees with a single merger. No batch touches a frozen file.
Every batch is Tier-1 or Tier-2 per the Execution Efficiency rules; batches touching
only handler types and log levels are Tier-1 (module tests only). Batch 1 and 2 add
tests, so run the owning module's tests plus the new file.

**BATCH 1 - A-class arena augment cache (HIGHEST VALUE)**
Files: `coaches/arena_coach.py`, plus a new
`tests/test_silent_except_arena_augment_cache.py`.
Work: fix A1 (:273 / :275 cache poisoning), escalate to `warning`, add the
poison-then-recover regression test. Do NOT touch the five D-class handlers in the
same file (`:879, 955, 971, 1008, 1021`) beyond adding a one-line
"callee already swallows" comment.

**BATCH 2 - A-class supervisor post-game filing**
Files: `agents/supervisor.py`, plus a new
`tests/test_silent_except_supervisor_postgame.py`.
Work: fix A2 (:758 -> `warning`) and A3 (hoist `_lrf(...)` out of the try at :728,
narrow :729 to `ImportError`). Add both regression tests.

**BATCH 3 - live-client observability (A-candidate, live-gated)**
Files: `game_reader/snapshot_normalizer.py`, plus a new
`tests/test_silent_except_liveclient_subresource.py`.
Work: escalate `:1056, 1104, 1133, 1161` from `debug` to a throttled `warning` and add
a degradation counter. Add the `_get`-raises-404 regression tests. Explicitly LEAVE the
16 per-field micro-handlers at `:1182-1197` and `:1222-1237` alone - they are
per-field coercion guards with a working default and changing them is a separate,
larger refactor. Record the live-game confirmation as a follow-up gated item.

**BATCH 4 - dashboard cache-the-failure + narrowing**
Files: `dashboard/routes_pickban.py`, `dashboard/routes_state.py`.
Work: A5 cluster (stop caching failed loads at `:117, 148, 168, 203`), narrow the four
loaders to `(OSError, json.JSONDecodeError)`, narrow `routes_state.py:672` to
`ImportError` and `routes_pickban.py:699, 710` to `(TypeError, ValueError, AttributeError)`.
One parameterized fault-then-recover test.

**BATCH 5 - coach base + aram narrowing**
Files: `coaches/_base_coach.py`, `coaches/aram_coach.py`.
Work: C-class only. Narrow the five `ImportError` sites in `_base_coach.py`
(`:342, 458, 477, 484, 702`) and `aram_coach.py:579`; narrow the OSError sites
(`_base_coach.py:56, 97, 447, 582`); narrow the two overlay sites
(`aram_coach.py:586, 639`). Comment the D-class site `aram_coach.py:557`.
No behavior change intended - existing coach tests are the gate.

**BATCH 6 - tracker / lcu-writer narrowing**
Files: `performance_tracker.py`, `core/cost_tracker.py`, `core/decision_detector.py`,
`lcu/lcu_rune_writer.py`.
Work: C-class narrowing per section 2c, plus the two log-level lifts
(`performance_tracker.py:321`). Comment the two D-class sites
(`lcu_rune_writer.py:888, 996`) citing `lcu/lcu_client.py:173-183` and `:384`.
Do NOT touch `lcu/lcu_client.py` itself (frozen).

**DEFERRED (needs an operator grant)**
`ops/rc_supervisor.py` (18), `app/_game_lifecycle.py` (17), `core/log_setup.py` (6),
`lcu/lcu_client.py` (7). 48 handlers, all frozen-list.

**NOT TRIAGED YET**
The 789 total minus the ~110 handlers classified above. The remaining bulk sits in
`tft/tft_live_analysis.py` (14), `core/tft_worker.py` (13), `tft/tft_coach_engine.py`
(12), `coach_integration/_coach.py` (9), `tools/lcu_agent.py` (9),
`dashboard/_deterministic_coaching.py` (8), `dashboard/server.py` (8) and a long tail.
Re-run the sizing script and apply the same A/B/C/D grid; the TFT cluster is the
obvious next triage batch.

---

## 4. Regression-test rule for this program

Every A-class fix ships a test that FAILS while the error is swallowed. The two shapes
that work here:

1. **Observability test** - inject a fault into the callee, assert a record at level
   >= WARNING (or a counter increment) exists. Fails today because the only record is
   DEBUG. Use `caplog.set_level(logging.WARNING)` so a DEBUG line cannot satisfy it.
2. **Recovery test** - inject a fault, call, remove the fault, call again, assert the
   second call succeeds. Fails today wherever a failed result is cached outside the
   `try` (A1, A5).

Asserting "the exception propagates" is the weakest form and is only correct where the
caller genuinely should crash - which is none of the A-class sites here. Prefer the two
shapes above.

# Orphan test-tree audit - RM-407

**Measured 2026-09-11, base HEAD `591bf1e0d`, in worktree
`C:\Riot Commander\.claude\worktrees\agent-abb71fadc14359596`.**
Interpreter `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`.

RC carries two test trees that no CI job collects. The question this audit
answers is NOT "do they exist" but "do they ASSERT anything, and will they run
on an `ubuntu-latest` runner". Wiring a vacuous tree buys runner minutes and
proves nothing.

Every number below was observed in THIS run. Nothing is carried forward from a
prior measurement, and where a figure is DERIVED rather than observed it says so
in the same sentence.

## Verdict table

| tree | collected (measured) | run result (observed) | vacuity candidates | platform blockers | conftest-redirect status | VERDICT |
|---|---|---|---|---|---|---|
| `tools/tests` | **348** | **348 passed, 0 failed, 0 error, 0 skipped, 20.17s** | **0 confirmed** (17 probe survivors, all hand-reviewed and cleared - list below) | **0** | root `conftest.py` applies; `tests/conftest.py` RM-406 redirects do NOT. Moot: 0 live-path writes measured | **WIRE** |
| `agents/agent3_testing/suite` | **359** | **357 passed, 0 failed, 0 error, 2 skipped, 21.16s** | **0 confirmed** (24 probe survivors, all hand-reviewed and cleared - list below) | **1** (`test_supervisor.py:206`, correctly two-branched - not a blocker) | root `conftest.py` + own `suite/conftest.py` apply; `tests/conftest.py` RM-406 redirects do NOT. Moot for the filesystem (all 15 writes tmp-rooted) but NOT for the network - see live-write findings | **WIRE-WITH-EXCLUSIONS** |

### Exact exclusions for the agent3 verdict

```
pytest agents/agent3_testing/suite \
  --ignore=agents/agent3_testing/suite/test_file_task_api.py \
  --deselect "agents/agent3_testing/suite/test_round14.py::test_head_on_api_env_returns_200" \
  --deselect "agents/agent3_testing/suite/test_scheduler_lock.py::test_two_processes_no_interleaved_lines"
```

Measured reasons, one per exclusion:

1. **`test_file_task_api.py` (6 tests)** - every test takes the module-scope
   fixture `live_supervisor` (`test_file_task_api.py:25-29`), which calls
   `pytest.skip("supervisor not running on :8890")` when TCP 127.0.0.1:8890 is
   closed. On `ubuntu-latest` nothing listens there, so all 6 skip
   unconditionally: pure runner minutes, zero coverage. The six are
   `test_file_task_endpoint_happy_path` (`:32`),
   `test_file_task_endpoint_missing_fields_400` (`:56`),
   `test_file_task_endpoint_frozen_file_gates` (`:74`),
   `test_task_detail_endpoint` (`:115`), `test_task_detail_404_for_unknown`
   (`:147`), `test_task_detail_rejects_bad_id` (`:158`).
2. **`test_round14.py::test_head_on_api_env_returns_200` (`:18`, gate at `:35`)** -
   same :8890 gate, inline rather than via fixture. Always-skip on CI.
3. **`test_scheduler_lock.py::test_two_processes_no_interleaved_lines` (`:37`)** -
   its OWN comment at `:48-49` reads
   `(CI does not run this suite; this keeps the spec verification triplet deterministic.)`.
   The test is a 3-attempt retry loop around two spawned processes each writing
   50 lock-contended JSONL records (`:41-77`), and the retry exists precisely
   because host load starves a writer. That tuning assumes CI does not run it.
   A 2-process contention race on a shared runner under `-n auto` is a flake
   candidate, and the test itself says so.

Net after exclusions: the three exclusions remove **8** of the 359 collected
tests - 6 from `test_file_task_api.py` plus 1 each from the two deselects, each
count confirmed this run with `--collect-only -q` - leaving **351 collected**.
Of those, **2 are expected to skip on a fresh runner** (the `data/db`
machine-local pair, see portability findings), so **349 expected to execute**.
Those last two figures are DERIVED from the enumerated gate population, not
observed on a Linux runner; this audit had no Linux runner.

## The glob false positive

`git ls-files "*test_*.py" "*_test.py" | sed "s|/[^/]*$||" | sort -u` returns a
bare `tools` entry alongside `tools/tests`. A naive enumeration files that as a
THIRD orphan tree. It is not one.

Re-derived this run. The full population of depth-1 matches under `tools/` is:

```
$ git ls-files "*test_*.py" "*_test.py" | grep -E "^tools/[^/]+$"
tools/pytest_guard.py
```

**One file. That is the whole population.** It matches `*test_*.py` because the
literal substring `pytest_guard` contains `test_`, i.e. `py` + `test_` +
`guard.py`. It is the PostToolUse syntax-gate hook, not a test:
`grep -c "^def test_\|^class Test" tools/pytest_guard.py` returns **0**, and its
module docstring (`tools/pytest_guard.py:2`) describes it as
"PostToolUse fast syntax gate".

There are exactly **two** orphan trees, not three.

## Vacuity findings

Taxonomy from `memory/INDEX_testing_traps.md` (27 ways a test can be green while
proving nothing). Three probes were run. Populations are printed in full; where
a probe returned zero, the exact pattern is stated, because an empty grep is a
claim about the pattern rather than about the tree.

### (a) EMPTY-ENUMERATION ALWAYS-GREEN

Pattern: `grep -rn "rglob\|glob(\|walk(\|iterdir\|listdir" <tree> --include="*.py"`
(the `--include` is load-bearing: without it the same grep reports roughly 60
phantom hits out of `__pycache__` `.pyc` bytes).

`agents/agent3_testing/suite` - **1 instance**, printed in full:

- `test_round42.py:155` `siblings = list(css.parent.iterdir())`.
  **ANCHORED, not vacuous.** The next line is `assert len(siblings) == 1`
  (`:156`), so an empty enumeration FAILS rather than passing. `:157` then pins
  the member by name. This is the correct shape.

`tools/tests` - **4 instances**, printed in full:

- `test_cdragon_ratio_extract.py:55` and `test_cdragon_spell_extract.py:40`, both
  inside `_agents_imports(src)`. The consumer asserts `offenders == []`
  (`ratio:68`, `spell:53`), which is a negative assertion and DOES pass on an
  empty walk. **Cleared anyway**, because the enumeration universe is anchored
  upstream: `src` is `open(R.__file__).read()` / `open(C.__file__).read()`
  (`ratio:733`, `spell:575`) - the source of a module the test file imports at
  module level (`ratio:22`, `spell:20`), so an import failure errors the file
  rather than silently emptying the set, and the same test asserts
  `"import requests" not in src` on the identical string. An empty `src` cannot
  reach these lines.
- `test_cdragon_ratio_extract.py:90` and `test_cdragon_spell_extract.py:72`,
  inside `_assert_mode_variants_is_leaf()`. Also a negative assertion
  (`bad == []`), but explicitly anchored one line earlier by
  `assert mv.exists(), f"allowlisted helper missing: {mv}"` (`ratio:88`,
  `spell:70`). A file with zero imports genuinely IS a stdlib-only leaf, so the
  empty case is correct rather than vacuous.

**Confirmed vacuous: 0 of 5.**

### (b) MOCKS-OF-ITSELF

Census first. Pattern
`grep -rn "patch(\|monkeypatch.setattr\|MagicMock\|Mock(" <tree> --include="*.py"`:
**128 mock-shaped lines in agent3** (30 files), **172 in tools/tests** (7 files).
300 lines is past hand-review, so the shape was classified mechanically by AST:
a test that patches `MODULE.attr` and then, LATER IN THE SAME BODY, CALLS
`MODULE.attr(...)` directly - so the assertion sees only the mock. Legitimate
seam injection (patch a dependency, then call a DIFFERENT production entry
point, e.g. `monkeypatch.setattr(C, "_fetch_with_retry", ...)` followed by
`C.extract(...)` at `test_cdragon_spell_extract.py:566-572`) is deliberately not
flagged.

Result over both trees: **675 test functions scanned, 0 flagged.**

A zero from a detector is worthless until the detector is shown to fire, so it
was run against a seeded positive control carrying both the `monkeypatch.setattr`
form and the `patch.object` form plus one legitimate-seam decoy. It flagged
**2 of 3**, correctly passing over the decoy. The detector is live; the zero
stands.

**Named blind spot:** the string form `@patch("module.attr")` / `patch("a.b.c")`
is NOT resolved, because the patched name never appears as an AST `Name` node
the body can be matched against. The population that could hide there is small -
the only string-form patches in either tree are the three at
`test_supervisor_stub.py:46`, `:61`, `:77`, all
`patch("agents.supervisor.subprocess.run", return_value=fake_proc)`, which patch
`subprocess.run` (a stdlib dependency), not the supervisor function under test.
Hand-checked: not the mocks-of-itself shape.

**Confirmed vacuous: 0.**

### (c) ASSERTS-ON-ITS-OWN-FIXTURE-LITERAL

Probed by proxy, since the literal form is not directly greppable: find test
functions in which NO production symbol is ever exercised, so nothing but the
test's own literals can decide the outcome. The universe of production symbols
is every name bound by a non-stdlib, non-pytest import in the file; file-local
helpers are resolved transitively; `pytest.raises` / `pytest.warns` /
`pytest.fail` count as assertions; a test taking a non-builtin fixture is
treated as "reach unknown" and skipped rather than flagged.

**41 survivors of 674** (the 674 is the AST-visible `def test*` count; it differs
from 359+348=707 collected because `@pytest.mark.parametrize` expands one
definition into several collected items). All 41 were hand-reviewed. All 41
CLEARED. Printed in full.

**agent3 - 24 survivors:**

| site | test | review |
|---|---|---|
| `test_round12.py:129` | `test_mode_transition_callback_exception_swallowed` | asserts via a captured-callback list, not `assert` - real behaviour |
| `test_round14.py:18` | `test_head_on_api_env_returns_200` | reaches a live HTTP service; SUT is out-of-process. EXCLUDED above for the skip reason, not for vacuity |
| `test_round24.py:133` | `test_dashboard_has_kda_row` | reads real `web/index.html` off disk, asserts two substrings |
| `test_round26.py:129`, `test_round29.py:169`, `test_round32.py:213`, `test_round33.py:173`, `test_round34.py:186`, `test_round35.py:165`, `test_round36.py:202`, `test_round37.py:235`, `test_round38.py:215`, `test_round42.py:309` | `test_supervisor_registers_*_route` family (10) | each reads real `agents/_supervisor_http.py` off disk and asserts a route literal plus a handler name are present |
| `test_round38.py:226`, `test_round39.py:170`, `test_round42.py:303`, `test_round43.py:200`, `test_round43.py:207` | wiring/constant-integrity family (5) | same shape against `agents/supervisor.py` and `agents/agent7_context/input_parser.py` |
| `test_scheduler_lock.py:37` | `test_two_processes_no_interleaved_lines` | SUT runs in a spawned subprocess; the parent only inspects the artifact. EXCLUDED above for flake risk, not vacuity |
| `test_supervisor.py:59`, `:67`, `:77` | `test_mode_dbs_exist`, `test_resolved_decisions_written`, `test_migration_ran` | filesystem/SQLite state assertions against real artifacts |
| `test_supervisor.py:111` | `test_supervisor_starts_and_binds_ports` | SUT is a spawned `python -m agents.supervisor`; the parent asserts port binds plus two DISTINCT heartbeat values |
| `test_warm_ui_watchdog.py:103` | `test_watchdog_handles_missing_ws_gracefully` | a "must not raise" test - the absence of an exception IS the assertion |

**Honest caveat on the 15 source-substring tests.** They are weak - they prove a
string exists in a file, not that the route is reachable - and 15 of the 24 agent3
survivors are that one shape. That is a quality observation, not a vacuity
finding: the assertion is against real production bytes read off disk, so
deleting the route reddens the test. They are not always-green and they are not
grounds to block.

**tools/tests - 17 survivors:**

| site | test | review |
|---|---|---|
| `test_cdragon_ratio_extract.py:579`, `:688`, `test_cdragon_spell_extract.py:566`, `test_wiki_stats_extract.py:339`, `:493`, `:820` | ASCII-output family (6) | `json.dumps(out, ensure_ascii=True)` on a real extractor result - "must not raise" IS the assertion |
| `test_cdragon_ratio_extract.py:737`, `test_cdragon_spell_extract.py:579` | `test_allowlisted_helper_is_itself_engine_free` (2) | delegate to `_assert_mode_variants_is_leaf()`, which asserts internally (probe cannot see through the call) |
| `test_cdragon_drift_audit.py:220`, `test_roster_decap_a26.py:248`, `test_upstream_drift_check.py:308`, `test_wiki_leveling_capture_rm95b_b2.py:274` | source-hygiene family (4) | read the real tool source and assert an ASCII / no-dash property. Production-agnostic BY DESIGN - these are hygiene guards, and the repo-wide no-em-dash rule is exactly what they enforce |
| `test_roster_decap_a26.py:179` | `test_the_gap_is_exactly_locke_and_zaahen` | asserts `len(roster) == 173`, `len(abil) == 171` and the exact set difference against the COMMITTED DS snapshot. Strong, and anchored on both sides |
| `test_wiki_leveling_capture_rm95b_b2.py:243`, `:249`, `:254`, `:261` | leveling-capture family (4) | **FALSE POSITIVES of the probe.** Each calls `self._run(monkeypatch)`, a CLASS method defined at `:225` whose body calls `W.extract(...)` at `:240`. The transitive resolver walks module-level functions only, so it cannot see through a method. Real production code decides all four |

**Confirmed vacuous across both trees: 0.**

## Portability findings (`ubuntu-latest`)

### sys.platform / os.name gates

Pattern
`grep -rn "sys.platform\|platform.system\|os.name" <tree> --include="*.py"`:

- `agents/agent3_testing/suite` - **1 instance**, printed in full:
  `test_supervisor.py:206` `if sys.platform.startswith("win"):`. Reviewed. It is
  correctly TWO-branched - `taskkill /F /PID` on Windows (`:207`), `proc.kill()`
  on everything else (`:208-209`). **Not a blocker.**
- `tools/tests` - **0 instances.**

### Windows-only APIs and tooling

Pattern
`grep -rn "schtasks\|pythonw\|win32\|pywin32\|os.startfile\|winreg\|ctypes.windll\|taskkill\|powershell\|\.ps1\|\.bat" <tree> --include="*.py"`:

- `agents/agent3_testing/suite` - **2 instances**, both the `taskkill` above
  (`test_supervisor.py:205` is its comment, `:207` the call). Guarded.
- `tools/tests` - **0 instances.**

### Backslash / absolute Windows path literals

Pattern `grep -rn "C:\\\\\|\\\\\\\\Users\|\\\\\\\\Riot" <tree> --include="*.py"`
over BOTH trees: **0 instances.** Every path is built with `pathlib` or comes
from `tmp_path`.

### Module-level imports that could error at COLLECTION

This is the one that matters most, because a module-level import of a
Windows-only package reds the whole FILE on Linux rather than failing one test.
Enumerated every `^import` / `^from` line in both trees and subtracted the
stdlib plus pytest:

- `agents/agent3_testing/suite` - **22 non-stdlib module-level imports, all
  repo-internal**: `agents.agent0_gatekeeper`, `agents.agent1_lead`,
  `agents.agent2_backend.db_schema`, `agents.agent2_backend.smb_push`,
  `agents.agent4_coach_mentor.analyzer`, `agents.agent7_context`,
  `agents.agent7_context.warm_session`, `agents.supervisor`, and
  `lib.modes` (`test_supervisor.py:23`). `lib/modes.py` is present and tracked.
  **Zero third-party, zero Windows-only.**
- `tools/tests` - **12 non-stdlib module-level imports, all sibling tool
  modules** reached via a `sys.path.insert` of the `tools/` dir:
  `ds_cdragon_drift_audit`, `daemon_slayer_cdragon_ratio_extract`,
  `daemon_slayer_cdragon_spell_extract`, `daemon_slayer_extract`,
  `daemon_slayer_wiki_ability_extract`, `daemon_slayer_wiki_stats_extract`,
  `upstream_drift_check`. **Zero third-party, zero Windows-only.**

### CWD coupling

`grep -rn 'Path("[A-Za-z]' <tree> --include="*.py"` - relative path literals
resolved against the process working directory, not against `__file__`:

- `agents/agent3_testing/suite` - **17 instances** (the full population, at
  `test_round24.py:135`, `test_round26.py:134`, `test_round27.py:8`,
  `test_round29.py:172`, `test_round32.py:218`, `test_round33.py:176`,
  `test_round34.py:189`, `test_round35.py:168`, `test_round36.py:205`,
  `test_round37.py:238`, `test_round38.py:218`, `test_round38.py:227`,
  `test_round39.py:171`, `test_round42.py:304`, `test_round42.py:312`,
  `test_round43.py:201`, `test_round43.py:208`). Every one requires the process
  CWD to BE the repo root. **Not a blocker for the intended wiring** - CI's
  existing invocation already runs from the repo root - but it is a real
  constraint on the wiring SHAPE, and it means these 17 cannot be moved behind a
  `working-directory:` change or invoked from a subdirectory.
- `tools/tests` - **0 instances.** It anchors on `Path(__file__)` throughout.

### Environment-conditional skips (always-skip on a fresh runner)

Pattern `grep -rn "pytest.skip\|skipif\|pytest.mark.skip" <tree> --include="*.py"`:

- `agents/agent3_testing/suite` - **6 instances**, printed in full:
  `test_file_task_api.py:28` (:8890 live supervisor),
  `test_round14.py:36` (:8890 live supervisor),
  `test_supervisor.py:42` / `:45` / `:50` / `:52` (machine-local
  `data/db` match-history corpus, absent in any fresh checkout).
  Two of these fired in THIS run: **2 skipped**, both from `test_supervisor.py:42`
  with reason `no ...\data\db - machine-local match history absent in this checkout`.
  The :8890 pair did NOT fire here, because 127.0.0.1:8890 is OPEN on this
  machine - probed directly this run, result `8890 OPEN on this machine`.
- `tools/tests` - **0 instances.** No environment can make a `tools/tests` test
  silently not run.

### Third-party and network dependencies

Pattern
`grep -rn "subprocess.Popen\|subprocess.run\|socket.socket\|bind(\|requests\.\|urlopen\|httpx" <tree> --include="*.py"`:

- `agents/agent3_testing/suite` - **20 instances**: 8 `urlopen` calls to
  `http://127.0.0.1:8890` (`test_file_task_api.py:46`, `:65`, `:89`, `:107`,
  `:130`, `:136`, `:149`, `:160`) plus `test_round14.py:40`; 2 ephemeral-port
  binds (`test_quality_pass.py:35-36`, `test_supervisor.py:105-106`); 2 real
  `subprocess.Popen` spawns (`test_scheduler_lock.py:60`,
  `test_supervisor.py:161`); 1 `taskkill` (`test_supervisor.py:207`); 3 patched
  `subprocess.run` (`test_supervisor_stub.py:46`, `:61`, `:77`).
  **No outbound internet.** All loopback.
- `tools/tests` - **1 instance**, and it is a COMMENT, not code:
  `test_cdragon_ratio_extract.py:80`, prose reading "`import requests`, which
  `import httpx` sailed past". **Zero subprocess, zero sockets, zero network.**

### Tracked-data dependencies

Both trees read committed data. Verified tracked AND not LFS-backed this run
(`git ls-files --error-unmatch` plus `git check-attr filter`, which returned
`filter: unspecified` for each):
`data/daemon_slayer/current.txt` (contents `16.15.1`),
`data/daemon_slayer/16.15.1/champions.json` (398603 bytes),
`data/daemon_slayer/16.15.1/champion_abilities.json` (3016747 bytes),
`agents/state/resolved_decisions.json`. A fresh clone gets real bytes, not LFS
pointers.

## conftest / live-write findings

### What actually applies to each tree

The handed-down ground truth said neither tree sits under `tests/conftest.py`
and so neither inherits the RM-406 live-tree write redirects. **That half is
correct and was re-verified.** But the fuller picture is that a **repo-root
`conftest.py` EXISTS and DOES apply to both trees**, which the summary did not
say, and which matters because it means the trees are not conftest-free:

- `conftest.py` (repo root, tracked) - applies to EVERYTHING under the rootdir,
  both orphan trees included. It inserts the repo root on `sys.path` (`:13`) and
  installs the `subTest` channel guard (`:15-17`). Its own docstring
  (`conftest.py:1-6`) says it exists precisely because `tests/conftest.py` only
  covers `tests/`.
- `agents/agent3_testing/suite/conftest.py` - exists, tracked. `sys.path` insert
  (`:27-29`) plus an autouse fixture clearing asyncio's running-loop slot
  (`:41-45`).
- `tools/tests/conftest.py` - **does not exist** (confirmed by `ls`; the tracked
  conftest population is exactly four files: `conftest.py`,
  `tests/conftest.py`, `tests/snapshot_panels/conftest.py`,
  `agents/agent3_testing/suite/conftest.py`).
- The RM-406 redirects (`redirect_prod_write_paths_to_tmp` at
  `tests/conftest.py:371`, `redirect_prod_path_globals_to_tmp` at `:442`,
  `redirect_cost_tracker_spend_dir_to_tmp` at `:589`, and the import-time
  hermeticity block from `:46`) live ONLY in `tests/conftest.py` and reach
  ONLY `tests/`. **Neither orphan tree inherits them.**

`pytest.ini` carries only `norecursedirs`; there is no `setup.cfg`,
`pyproject.toml` or `tox.ini`, so no `testpaths` setting is silently scoping
collection.

### Do the trees write the operator's live tree?

Pattern
`grep -rn "write_text\|write_bytes\|os.replace\|shutil.copy\|shutil.move\|\.unlink(\|os.remove\|open(.*[\"'][wa][\"']" <tree> --include="*.py"`,
then every hit whose target was not lexically obvious was traced to its variable
assignment.

- `tools/tests` - **16 write sites, 16 tmp-rooted, 0 live-path, 0 unresolvable.**
  Every one writes into `pd`, and every `pd` assignment in the tree is
  `tmp_path / "<patch>"` (`test_cdragon_ratio_extract.py:633`, `:663`, `:690`,
  `:710`; `test_cdragon_spell_extract.py:235`, `:250`;
  `test_roster_decap_a26.py:53`, `:96`, `:125`; `test_wiki_ability_extract.py:447`;
  `test_wiki_stats_extract.py:62`, `:77`, `:88`, `:100`, `:693`). The one
  exception, `test_roster_decap_a26.py:180 pd = self._patch_dir()`, resolves to
  the committed DS snapshot dir and is READ-ONLY there (`:181-184`, both
  `read_text`). **Clean.**
- `agents/agent3_testing/suite` - **15 non-obvious write sites, 15 tmp-rooted,
  0 live-path, 0 unresolvable.** Traced: `test_round12.py:82/118/122/145/148`
  write `health = tmp_path / "health.json"` (`:77`, `:113`, `:140`);
  `test_round19.py:43/87` write under `tmp_path` (`:42`, `:85`) with
  `_PROJECT_ROOT` monkeypatched to `tmp_path` (`:82`, `:137`);
  `test_round42.py:27/46/151/166/224/246` all write under `tmp_path` with
  `ui_applier._PROJECT_ROOT` monkeypatched to `tmp_path` (`:24`, `:43`, `:148`,
  `:163`, and siblings); `test_smb_push.py:33` writes `src = tmp_path / "x.txt"`
  (`:32`); `test_supervisor.py:142` `shutil.copy2` READS the tracked
  `agents/state/resolved_decisions.json` and WRITES into `tmp_path / "state"`
  (`:138-142`). `test_supervisor.py:145-150` documents having already FIXED a
  live-tree pollution defect of exactly this class ("Point the mode DBs at a tmp
  dir so the run leaves the checkout alone").

**The filesystem half is clean in both trees. The NETWORK half of agent3 is
not, and no filesystem grep can see it.** `test_file_task_api.py` POSTs real
task records into whatever supervisor is listening on 127.0.0.1:8890 - including
the operator's LIVE one. This run measured 8890 OPEN on this machine, and those
six tests did not skip, so **this audit's own run filed live tasks named
`test-round22-file-task-happy` and siblings into the running supervisor.** That
is the strongest argument for the `--ignore` on that file: on CI it is dead
weight, and locally it is a live side effect that the RM-406 redirect net was
never built to catch, because RM-406 redirects PATHS and this escapes over a
socket.

## Why wiring is worth doing at all

Both trees carry self-documented evidence that being uncollected has ALREADY
cost real defect-detection, written by the authors at the time:

- `tools/tests/test_cdragon_spell_extract.py:24-27`:
  commit `d0ad0569` (2026-07-30) "deliberately added ONE engine import to both
  cdragon extractors without updating the guard, **leaving it red and unseen
  because `pytest tests` does not collect tools/tests**". A guard sat red for a
  week because nothing ran it.
- `agents/agent3_testing/suite/test_scheduler_lock.py:48-49`:
  "(CI does not run this suite; ...)" - here the orphan status is a load-bearing
  ASSUMPTION the test was tuned around, which is why that one test is excluded
  rather than wired.

## LIMITS - what this audit cannot see

Stated plainly, because a verdict is only as good as its blind spots.

1. **No Linux runner was used.** Every run reported here executed on Windows
   with Python 3.14 against the worktree. The `ubuntu-latest` claims are derived
   from source inspection (platform gates, module-level imports, path literals,
   skip conditions), not from an observed Linux run. A collection-time failure
   from a transitively-imported module that behaves differently on Linux would
   not appear in any measurement above. **The only way to close this is to run
   the wired job once on the runner and read the result.**
2. **Both trees were run SERIALLY and in ISOLATION.** CI runs
   `-n auto --dist loadfile`. Cross-tree interference under xdist was not
   measured, and agent3 in particular carries process-global state (the asyncio
   running-loop fixture in its own conftest exists because of exactly that class
   of leakage). A green serial run is not a green `-n auto` run.
3. **The mocks-of-itself detector does not resolve the string-patch form**
   (`patch("a.b.c")`) nor patches applied through a fixture. The three
   string-form patches in the trees were hand-checked, but a future one would
   pass unseen.
4. **The probe (c) proxy does not resolve class methods**, which is why four
   `test_wiki_leveling_capture_rm95b_b2.py` rows surfaced as false positives. It
   also skips any test taking a custom fixture, so a vacuous test whose literal
   arrives through a fixture is outside its reach. The 41 survivors are a
   CANDIDATE set, not a complete one - a vacuous test could sit outside it.
5. **Non-filesystem side effects are only partially covered.** The :8890
   discovery came from a network grep, not from the live-write grep. Side
   effects through other channels - a named mutex, an env var written into a
   parent process, a database outside the greps - were not systematically swept.
6. **`git check-attr filter` was checked on four data files, not on every file
   either tree reads.** An LFS-backed dependency elsewhere would not have been
   caught.
7. **This audit measured whether the tests RUN and ASSERT. It did not measure
   whether they assert the RIGHT thing.** The 15 agent3 source-substring tests
   are the clearest case: they will redden if a route literal is deleted and
   stay green through any behavioural break that preserves the string. Wiring
   them buys regression detection of a narrow kind. That is still more than
   zero, which is what an uncollected tree buys.
8. **Runner-minute cost was not measured.** Observed wall-clock here is 20.17s
   and 21.16s serially on this machine. A runner is slower and
   `test_supervisor.py::test_supervisor_starts_and_binds_ports` alone budgets a
   25s port deadline (`test_supervisor.py:170`) plus up to 20 one-second
   heartbeat polls (`:192`) under a 60s timeout mark (`:110`). Whether that is
   worth the minutes is an operator call this audit does not make.

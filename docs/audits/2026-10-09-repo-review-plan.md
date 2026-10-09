# RC full-tree repo review - plan (2026-10-09)

Source: MAIN ORDER 2026-10-08 2246, section 8 REPO-REVIEW (operator order S7),
read with the kit-v14 ORDER 2026-10-09 0930 (no change to section 8; v14 adds
the `blocked` progress state and `Refused.code`, both used here).
Findings: `docs/audits/2026-10-09-repo-review-findings.md`.

## 1. What the order asks

ONE headless driver through the kit spawn path (FLEET-COMMON 10; kind `build`,
a non-empty note label, item-12 progress file with a checklist) PLANS, then
reviews 100 percent of the files on disk in this repo - tracked, untracked and
ignored alike. ACCEPT: this plan, plus a findings file that covers every
top-level folder, each finding DONE / FILED (row id) / NOT-APPLICABLE, and a
reviewed file count equal to the count on disk.

Review topics (section 8, each finding carries one): H folder hierarchy and
organisation; M memory recall (memory files, hand-off, what a fresh session
must read); D dated files that can move to an archive or be pruned (Recycle Bin
only, FLEET-COMMON 9; consumer checked first); P pins and leaves; W worktrees;
S scratch; O orphans; T stale files; X files living outside the repo,
consolidated into ONE sidecar folder `<sidecar-root>\RC` (MAIN's per-machine
sidecar root; a drive-rooted literal never enters a tracked file); MD refactor / clean /
audit of the .md set (CLAUDE.md outside its pinned FLEET-COMMON block); I
inferred topics, each marked inferred.

Known findings, folded in and NOT re-derived (section 8 says so): section 2
PERF-AUDIT items 1-12 (`KF-P1`..`KF-P12`), section 3 README-AUDIT items 1-8
(`KF-R1`..`KF-R8`), section 5 SIDECAR-1 lines (`KF-S1` live launcher lines,
`KF-S2` record lines), section 6 ATLAS items 1-9 (`KF-A1`..`KF-A9`). Every
reviewer prompt carries the list; a reviewer that meets one cites the id.

## 2. The universe (measured 2026-10-09, frozen at `enumerate`)

Definition: every regular file under the repo root, walked on the filesystem,
except the root `.git/` directory. A linked worktree registered by
`git worktree list` inside the root (`.claude/worktrees/*`) is ONE unit: it is
another checkout of this same repository at another commit, reviewed under the
worktrees topic. Status per file: tracked = in the git index (ADR-015: the
index first), ignored = git's own ignore rules (`git ls-files --others
--ignored`, then `git check-ignore` for the few files git never lists itself,
e.g. the gitlink backups under `ops/runtime/e_move_backup/gitlinks/`),
untracked = the rest.

Reconciliation at freeze: 43,647 units = 43,637 files + 10 worktree units;
5,398 tracked (index 5,398, none missing on disk), 38,237 ignored, 2
untracked (this driver and its test, before their commit). The planner's
"about 43.5k" matches. Files appear between freeze and compile (logs,
progress files, bytecode): `delta` re-measures the disk at compile time and
reviews every unit that appeared since in extra `D` batches, so the reviewed
count is reconciled to the fresh count, not to a stale one. A unit deleted
since the freeze is reported as gone, not counted.

Amendment (during the run): the review's own staging dir
`ops/runtime/repo_review/` is its output, not its subject, and is excluded
from every later measurement (otherwise each answer it writes would move the
count it is reconciled against). Its two files present at the freeze were
reviewed anyway (batch B26) and are reported as excluded.

| Top-level | Units | Tracked | Ignored | Untracked | Worktree | Batches |
|---|---:|---:|---:|---:|---:|---|
| `(root files)` | 38 | 30 | 8 | 0 | 0 | B01, MD01 |
| `.claude` | 39 | 0 | 29 | 0 | 10 | B01, C01 |
| `.githooks` | 6 | 6 | 0 | 0 | 0 | B01 |
| `.github` | 15 | 15 | 0 | 0 | 0 | B01 |
| `.obsidian` | 18 | 0 | 18 | 0 | 0 | B01 |
| `.playwright-mcp` | 18 | 0 | 18 | 0 | 0 | B01 |
| `.pytest_cache` | 5 | 0 | 5 | 0 | 0 | C03 |
| `.ruff_cache` | 164 | 0 | 164 | 0 | 0 | C03 |
| `.superpowers` | 46 | 0 | 46 | 0 | 0 | B01 |
| `LICENSES` | 1 | 1 | 0 | 0 | 0 | B01 |
| `Share` | 3 | 0 | 3 | 0 | 0 | B01, C02 |
| `__pycache__` | 15 | 0 | 15 | 0 | 0 | C02 |
| `_scratch` | 3 | 0 | 3 | 0 | 0 | B01 |
| `agents` | 2485 | 718 | 1767 | 0 | 0 | B01-B06, C02, C03 |
| `app` | 14 | 7 | 7 | 0 | 0 | B06, C02 |
| `assets` | 8 | 8 | 0 | 0 | 0 | B06 |
| `atlas` | 14 | 14 | 0 | 0 | 0 | B06 |
| `coach_integration` | 12 | 6 | 6 | 0 | 0 | B07, C02 |
| `coaches` | 56 | 28 | 28 | 0 | 0 | B07, C02 |
| `config` | 24 | 19 | 5 | 0 | 0 | B07 |
| `core` | 482 | 242 | 240 | 0 | 0 | B08, B09, C02 |
| `dashboard` | 212 | 105 | 107 | 0 | 0 | B10, C02 |
| `data` | 3040 | 924 | 2116 | 0 | 0 | B10-B13, C06 |
| `docs` | 814 | 569 | 245 | 0 | 0 | B13-B18, MD01 |
| `game_reader` | 8 | 4 | 4 | 0 | 0 | B18, C02 |
| `lane-widget` | 33 | 33 | 0 | 0 | 0 | B18 |
| `lcu` | 18 | 9 | 9 | 0 | 0 | B18, C02 |
| `lib` | 41 | 20 | 21 | 0 | 0 | B18, C02 |
| `logs` | 85 | 0 | 85 | 0 | 0 | B18 |
| `mc` | 10 | 5 | 5 | 0 | 0 | B19, C02 |
| `modes` | 4 | 2 | 2 | 0 | 0 | B19, C02 |
| `modules` | 4 | 2 | 2 | 0 | 0 | B19, C02 |
| `moon_sync_inbox` | 812 | 0 | 812 | 0 | 0 | C09, C02 |
| `ops` | 11526 | 589 | 10936 | 1 | 0 | B19-B26, C02, C07 |
| `oss` | 24 | 13 | 11 | 0 | 0 | B26, C02 |
| `python-embed` | 2229 | 0 | 2229 | 0 | 0 | C08 |
| `rc-shell` | 7931 | 32 | 7899 | 0 | 0 | B26, C04 |
| `scripts` | 79 | 42 | 37 | 0 | 0 | B27, C02 |
| `tests` | 5402 | 1422 | 3979 | 1 | 0 | B28-B37, C02 |
| `tft` | 22 | 11 | 11 | 0 | 0 | B37, C02 |
| `tools` | 477 | 262 | 215 | 0 | 0 | B38, B39, C02 |
| `vision_server` | 16 | 8 | 8 | 0 | 0 | B39, C02 |
| `web` | 7394 | 252 | 7142 | 0 | 0 | B39-B41, C03, C05 |
| **Total (42 folders + root files)** | **43647** | **5398** | **38237** | **2** | **10** | **51** |

## 3. Method

Driver: `ops/loop/repo_review.py` (tracked; tests `tests/test_repo_review_driver.py`;
listed in the `KIT_ROUTED` inventory of `tests/test_headless_env.py`).
Subcommands `enumerate` (freeze manifest + plan), `run`, `delta`, `compile`.

- Spawn path: `ops/loop/fleet_route.spawn` -> `ops/fleet_kit/fleet_headless.spawn`,
  the only door (FLEET-COMMON 10). sonnet (writes_code False, the kit's pick),
  effort = the kit's pick for the label (medium), kind `build`, note label
  `repo-review-<batch>`; the kit writes the usage row to
  `ops/loop/control/headless_usage.jsonl` and owns the 120-runs / 24 h budget.
- Read-only by the CLI's own permission layer: `--permission-mode dontAsk`,
  `--allowedTools Read,Grep,Glob`, every writer, shell, agent and web tool in
  `--disallowedTools`. The reviewer returns ONE JSON object; the driver writes
  it to the gitignored staging dir `ops/runtime/repo_review/`.
- Fail closed: a route or kit refusal (proxy down, budget spent, ...) halts the
  whole driver with progress status `blocked` and the refusal code. No retry on
  another path, ever. Halt switch `ops/loop/control/REPO_REVIEW_STOP`; the
  driver's own run ceiling is 70.
- Progress: the driver writes `ops/loop/control/progress/repo-review.json`
  (pct, ETA from the measured mean run time, checklist = remaining batches);
  this executor writes `ops/loop/control/progress/s8-review.json`.
- Coverage rule: a unit counts as reviewed ONLY when its batch's run returned
  an answer that parses, names the batch and reports `manifest_count` equal to
  the batch size. A malformed answer gets one re-run, then the batch is failed
  and its units stay unreviewed until a re-run succeeds.

Row-by-row batches (`B`, `MD`): the prompt lists every unit with status, size,
mtime, the date of the newest commit touching it, and `refs` = how many OTHER
tracked text files mention its name or module stem (an orphan HINT; the
reviewer confirms with Grep before calling anything an orphan). Batches are
packed folder by folder to 150 weight units (code and prose 1.0, data and
binaries 0.35), so related files share one reviewer.

Class batches (`C`): nine bulk classes that are regenerable, third-party or
mirrors are reviewed BY CLASS - the prompt carries the measured facts for the
whole class (count, bytes, mtime range, extension and folder histograms, and
computed facts: orphan bytecode whose source is gone, npm package count,
responder export folders, DDragon versions kept, every inbox entry, every
worktree's branch / HEAD / lock) plus a deterministic sample of 60 paths, and
the verdict covers every unit of the class. Per-file reading of 7,898 npm
files or 6,481 bytecode files adds nothing a class verdict misses; the order
does not forbid it, and the count stays exact because every unit is assigned.

| Class | Units | Why by class |
|---|---:|---|
| C01 worktrees | 10 | each unit is a checkout of this repo |
| C02 bytecode caches | 6481 | regenerable output of the .py files |
| C03 tool caches | 183 | regenerable ruff / pytest caches |
| C04 node_modules | 7898 | third-party install output, lockfile tracked |
| C05 DDragon web mirror | 7138 | Riot static data, versioned folders |
| C06 meta_build mirror | 1991 | DDragon detail mirror, versioned folders |
| C07 responder exports | 9955 | copies of repo files per export |
| C08 python-embed | 2229 | third-party runtime |
| C09 channel inbox | 785 | gitignored notes and kit bundles (every entry listed) |

## 4. Batches and budget

51 batches = 9 class + 1 core-docs + 41 row-by-row, plus `D` delta batches at
compile. Runs: 51, at most one re-run each, driver ceiling 70, kit ceiling 120
per rolling 24 h; the kit budget read 0 runs used at plan time. Parallel 4.

| Batch | Kind | Units | Scope |
|---|---|---:|---|
| C01 | class | 10 | Linked worktrees nested inside the repo root (one unit each) |
| C02 | class | 6481 | Python bytecode caches (__pycache__ / *.pyc) |
| C03 | class | 183 | Tool caches (.ruff_cache / .pytest_cache) |
| C04 | class | 7898 | Vendored npm dependencies (node_modules) |
| C05 | class | 7138 | DDragon asset mirror under web/data/ddragon |
| C06 | class | 1991 | data/meta_build mirror (DDragon detail JSON + html) |
| C07 | class | 9955 | ops/runtime/responder_export snapshots |
| C08 | class | 2229 | Embedded Python distribution (python-embed) |
| C09 | class | 785 | Channel inbox moon_sync_inbox (notes and kit bundles) |
| MD01 | mdcore | 20 | Core .md set, hand-off and memory recall |
| B01 | files | 181 | root files, `.claude`, `.githooks`, `.github` + 13 more folders |
| B02 | files | 141 | `agents/agent2_backend` .. `agents/agent7_context` |
| B03 | files | 162 | `agents/daemon_slayer` |
| B04 | files | 150 | `agents/daemon_slayer` |
| B05 | files | 150 | `agents/daemon_slayer` |
| B06 | files | 166 | `agents/daemon_slayer`, `agents/state`, `app`, `assets/wards`, `atlas/snapshots` |
| B07 | files | 58 | `coach_integration`, `coaches`, `config` |
| B08 | files | 151 | `core` |
| B09 | files | 91 | `core`, `core/build_planner` |
| B10 | files | 176 | `dashboard`, `data` |
| B11 | files | 381 | `data/champion_profiles` .. `data/external` |
| B12 | files | 428 | `data/icons` |
| B13 | files | 223 | `data/icons` .. `data/vision_profiles`, `docs` root files |
| B14 | files | 184 | `docs/_archive` |
| B15 | files | 150 | `docs/_archive` |
| B16 | files | 145 | `docs/_archive`, `docs/_overlap`, `docs/_rescore` |
| B17 | files | 123 | `docs/_rsc_score` .. `docs/specs` |
| B18 | files | 288 | `docs/ui_audit`, `game_reader`, `lane-widget`, `lcu`, `lib`, `logs` |
| B19 | files | 52 | `mc`, `modes`, `modules`, `ops` root files |
| B20 | files | 373 | `ops/audit` |
| B21 | files | 126 | `ops/audit`, `ops/fleet_kit` |
| B22 | files | 300 | `ops/loop` |
| B23 | files | 59 | `ops/loop`, `ops/migrate` |
| B24 | files | 164 | `ops/runtime` |
| B25 | files | 244 | `ops/runtime` |
| B26 | files | 199 | `ops/runtime`, `ops/tls`, `oss`, `rc-shell` (outside node_modules) |
| B27 | files | 42 | `scripts` (pilot batch) |
| B28-B35 | files | 8 x 150 | `tests` |
| B36 | files | 144 | `tests` and its fixture / golden / smoke subfolders |
| B37 | files | 182 | `tests/snapshot_panels`, `tests/snapshot_regressions`, `tft` |
| B38 | files | 151 | `tools` |
| B39 | files | 128 | `tools` subfolders, `vision_server`, `web` root files |
| B40 | files | 115 | `web/css`, `web/data` (outside ddragon), `web/icons` |
| B41 | files | 130 | `web/js`, `web/mock` |

## 5. Statuses and what is NOT done here

- DONE: the defect is already fixed at HEAD (a commit hash is cited), or is
  fixed by this run. This run lands no code fixes beyond the driver itself:
  fixes land later in slices through the git lock and the suite gate.
- FILED (RM-n): needs a fix; one ROADMAP row per coherent fix (findings that
  share a fix share a row), with file:line ground truth and an acceptance.
- NOT-APPLICABLE: recorded, no action needed, or the order's fence applies.
- LISTED, not done: every sidecar move (topic X) and every irreversible or
  operator-gated act (prune, history change, frozen file, out-of-tree write).
  Section 5's remaining moves wait on MAIN setting `FLEET_SIDECAR_ROOT`
  (kit v14 3.4); MAIN has not set it, and any move outside the repo root is
  RC's halt boundary.
- The reviewer output never names a machine, account, address, token or a
  sibling repository; leaks are named by class and file:line only.

## 6. Deliverables

- `docs/audits/2026-10-09-repo-review-plan.md` (this file)
- `docs/audits/2026-10-09-repo-review-findings.md`
- `ops/loop/control/progress/repo-review.json` (driver) and
  `ops/loop/control/progress/s8-review.json` (executor), both gitignored
- staging, gitignored: `ops/runtime/repo_review/` (manifest, batches, prompts,
  raw answers, per-batch findings, summary)

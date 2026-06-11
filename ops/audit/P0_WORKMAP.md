# DEEP AUDIT work-map (built cycle 1, P0 baseline, 2026-06-11)

Charter: docs/DEEP_AUDIT_CHARTER.md. Live phase state: Desktop synopsis.
Every line below is a live-verified P0 observation feeding P1-P8. Sources cited.

## Baseline facts (verified this cycle)

- HEAD 22a71c4e, CI green (3 latest runs success, gh run list).
- Model: claude-fable-5[1m] probe accepted (headless claude -p exit 0, replied OK);
  set in .claude/settings.json "model". effortLevel xhigh already present.
- Tree: 30398 files / 4350.5 MB on disk (.git, __pycache__, node_modules excluded);
  git-tracked 2896 files / 409.3 MB. Full detail: ops/audit/P0_INVENTORY.md + p0_inventory_full.csv.
- Tests: full root suite via pytest -q; summary in ops/audit/p0_pytest_baseline.txt
  (full log ops/audit/p0_pytest_full.txt). Share/ validated separately (pytest.ini norecursedirs).
- Health: RC pid 1492 alive mode=client; vision :8889 alive (haiku, api_key_ok, in-process);
  DS :8893 ok ENGINE 1.120.0 patch 16.12.1 champions 172 items 706; supervisor pid 1940;
  cost today 0.021924 USD; bridge gamepc red age ~917705s (expected, retired).
- /metrics serving (rc_alive 1, coach/vision/bridge counter families present).
- Dashboard reference screenshot: ops/audit/p0_dashboard_reference.jpeg (devtools viewport,
  NOT the 1920x1080 baseline - layout squish in RECENT 5 is viewport-suspect).

## P1 STRUCTURE targets (from inventory)

- data/ 1503 files 2356 MB untracked-heavy: rewind_history.db 1737 MB, riot_api_cache.db 90 MB,
  match_history.db.bak-item211-* x2 (15.6 MB, stale backups - delete candidates),
  match_history.db-wal 4 MB (checkpoint), det_coach_shadow.jsonl 3.7 MB growth file.
- web/ 22254 files 1707 MB (PNG mirror dominates: 22760 png repo-wide / 1762 MB) - mirror
  layout + prune policy review.
- logs/ 1997 files 115 MB - retention policy (rotated .1/.2 files: 66 MB).
- python-embed/ 2229 files 58 MB untracked runtime - confirm consumer (electron/rc-shell?) in P1.
- _scratch/ 70 files 2.9 MB + _archive/ 76 files 2.8 MB - scrap triage.
- docs/ 271 files 48 MB - bloat reduction (P8 rewrite pass feeds this).
- Tracked bloat: 4x laning_scenarios ~63 MB each are LFS (keep; verify LFS health),
  data/daemon_slayer/16.10.1/scenarios.json 3.4 MB tracked - stale-patch candidate.

## P2 CODE AUDIT seeds (verified anomalies)

- [RESOLVED cycle 5, item 399] RC-VisionServer scheduled task: confirmed vestigial duplicate
  (live :8889 = pythonw child spawned by dashboard/server.py self-heal; the schtask's
  python.exe instance lost the port race -> exit 1 every boot). Task DELETED, XML archived
  docs/_archive/2026-06-11_RC-VisionServer_schtask_removed.xml; CLAUDE.md / OPERATIONS /
  start_claude.ps1 / legion_on+off.ps1 / docstrings / ADR-003 synced.
- [RESOLVED cycle 5, item 399] ResourceManager.shutdown logging-after-close noise: shutdown()
  now toggles logging.raiseExceptions off for its duration (restored in finally);
  tests/test_resource_manager_shutdown_logging.py (RED->GREEN).
- [RESOLVED cycle 6, item 400] .pytest_cache policy: confirmed gitignored (git check-ignore),
  ~2.6 MB local cache, harmless - no -p no:cacheprovider needed; policy = leave default.
- [RESOLVED cycle 5, item 399] INTERPRETER DUALITY: gemini ruled OPTION 4 (absolute canonical
  path everywhere + permanent ban). Swept .claude hooks/skills (live) + docs + ops/loop +
  core hint strings (297 offenders -> 0); guard tests/test_bare_py_ban.py.
- [RESOLVED cycle 6, item 400] bare-py DEFERRED TAIL swept: 8 tools/*.cmd where-py exec
  blocks -> canonical interpreter + python-on-PATH fallback (CRLF-normalized); ~192 docstring/
  hint tokens across tools/*.py (incl frozen bridge tools, charter-authorized) + scripts/*.py +
  core/benchmarks + core/prom_metrics + _item_ability_haste + riot-commander.spec + 8
  remediation-hint tests -> UNQUOTED forward-slash canonical path (the path has no spaces;
  quoted-backslash form was a Python unicode-escape / embedded-quote syntax trap - caught by
  ruff+py_compile, reverted, re-swept); Share/docs -> portable `python` spelling; Share/src
  regenerated via ds_share_sync. Guard allowlist narrowed to gamepc-foreign + by-design quotes
  (ROADMAP gamepc recipes, P0_WORKMAP, precommit/truth_gate characterization, ops/tls artifact).
- [RESOLVED cycle 5, item 399] stale `|| "16.10.1"` JS fallbacks: 22 literals -> 1
  DDRAGON_FALLBACK_VERSION const (web/js/lib/items_index.js); drift guard bans scattered
  semver literals in web/js.

## P3 PRUNE seeds

- Desktop synopsis file itself had a UTF-8 BOM (re-written ASCII this cycle) - BOM sweep scope
  includes non-repo operator artifacts.
- gamepc/2-PC references: sweep code+docs+memories (charter item 5b). gamepc_*.py files exist
  at root (inventory CSV) - archival decision in P3 (prior verify said NOT-safe; re-verify).
- Smart-quote retro-sweep folds in (charter item 6).

## P7 UI seeds (from reference screenshot)

- TONIGHT'S PICK row: "ADVISORIESNone" missing separator/spacing (confirmed at any viewport).
- RECENT 5 card vertical word-wrap + champion-name truncation at narrow viewport - re-check at
  1920 baseline before logging as a defect.

## P8 DOCS seeds (live-vs-docs drift verified)

- CLAUDE.md DS header says ENGINE 1.101.0 / 705 items; live /health says 1.120.0 / 706 items.
- docs/DAEMON_SLAYER.md same drift class (DS-batch docs-sync job).

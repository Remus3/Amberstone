# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-4 (2026-06-11 prunes) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-11 - DEEP-AUDIT cycle 7: P2 W1 core/ per-file fanout, slices A-G [item 401]

- 103 core/*.py / 29531 LOC audited via 7 disjoint worktree slices (A spine / B coach / C build-WPA / D postgame / E archetype-vision / F infra-workers / G bridge-lessons); octopus merge 6273d655 + fix commit 09184ff3; 98 new tests (tests/test_p2w1_core_{a..g}.py).
- Load-bearing fixes: WPA trio pinned-16.11.1 catalogs -> dynamic current.txt resolution (item-397 auto-prune would have silently emptied all 3 panels next patch); 2 SECURITY fixes in lessons_receiver (remote `source` path traversal out of MEMORY_DIR -> _safe_peer; frontmatter newline injection could spoof cross_project/type -> _fm_scalar); TFT raw_state defensive-copy gap (game_snapshot.py:610 FROZEN edit, charter-auth); tesseract timeout=10s x8 call sites; obs_publisher reply drain + eventSubscriptions=0 (conn flapped ~1/min); polled_json WinError-5 retry; hotkeys force_scan atomic; cost_tracker malformed-budget no longer disables cap; legacy vision-token fallback removed (liveclient_cache).
- DEFER findings ledger NEW ops/audit/P2_FINDINGS.md (8 MED / ~26 LOW / 5 INFO; incl 13-file legacy-token literal fanout, riot_api_cache no-prune 94.7MB, mode-divergence URF/queue-900). Manifest W1 core ticked.
- Gate round A REFUSE (4f: new obs tests used asyncio.run; an earlier suite test leaves a main-thread running-loop marker - green in isolation) -> thread-isolated _run_coro; round B PROCEED 15285p/0f/7s exit 0 (+98 = new tests exactly). RC restarted pid 9300 alive reload_ok; 7 worktrees removed. TRAP: new async tests must not use asyncio.run (suite polluter logged as W5 item).
- NEXT cycle 8: W1 dashboard/ (78 files / 20629 LOC, ~4 slices; routes_* independent) per P2_FANOUT_MANIFEST.md.

---

# 2026-06-11 - DEEP-AUDIT cycle 6: P2b fixture ruling + bare-py tail + fanout manifest [item 400]

- DS fixture pins: gemini RULED B - 16.9.1 RETIRED (test_effects_expansion repointed to 16.10.1; purchasable-set delta verified EMPTY 466==466; dir git-rm'd 8 files), {16.10.1, 16.11.1} frozen permanent, new pins target 16.11.1. Guard tests/test_ds_fixture_policy.py (2 tests: pair present + 16.9.1 stays gone); policy in docs/DAEMON_SLAYER.md substrate bullet. Full consolidation REJECTED (drift risk ~50 pinned files >> 23 MB).
- bare-py tail: 8 tools/*.cmd where-py exec blocks -> RC_PY canonical + python fallback (all 15 cmd CRLF-normalized); 192 tokens across 94 files (tools/*.py incl frozen bridge set, scripts, core/benchmarks+prom_metrics, _item_ability_haste, riot-commander.spec, 8 hint tests) -> UNQUOTED forward-slash canonical path. TRAP LOGGED: quoted-backslash form inside Python strings = \U unicode-escape + embedded-quote SyntaxErrors (ruff+py_compile caught; reverted; re-swept). Share/docs -> python spelling; ds_share_sync regen (335 files). Guard allowlist narrowed to gamepc-foreign + by-design quotes; ROADMAP keeps its 2 gamepc historical recipes for the P3 prune.
- .pytest_cache gitignored-confirmed CLOSED. P2 fanout manifest: ops/audit/P2_FANOUT_MANIFEST.md (1307 files / 399052 LOC, 5 waves, slice protocol, standing finding classes).
- Gate PROCEED 15187p/0f/7s exit 0 (ops/audit/p2b_truth_gate_report.json; +2 = policy tests). NEXT cycle 7: P2 fanout W1 runtime spine (core/ slices first).

---

# 2026-06-11 - DEEP-AUDIT cycle 5: P2a code-audit seeds x4 [item 399]

- RC-VisionServer schtask root-caused (boot port-race loser vs dashboard/server.py:219 self-heal child; exit-1 anomaly) -> DELETED, XML archived docs/_archive/, 9 touchpoints synced (CLAUDE.md, OPERATIONS row, start_claude.ps1, legion_on/off, docstrings, ADR-003 dated update). Vision :8889 alive untouched.
- resource_manager shutdown(): logging.raiseExceptions toggled off for the drain (finally-restored); kills the "--- Logging error ---" pytest-tail noise. 3 tests RED->GREEN.
- Bare-py duality: gemini ruled OPTION 4 (absolute canonical path + permanent ban; consult ops/loop/control/_gemini_consult_p2.txt). 297->0 offenders; guard tests/test_bare_py_ban.py; live .claude hooks/skills swept (51 repl). Deferred tail allowlisted + in P0_WORKMAP (Share mirror, tools docstrings, tools/*.cmd, scripts, ROADMAP).
- web/js: 22 semver fallback literals -> DDRAGON_FALLBACK_VERSION (lib/items_index.js); guard bans scattered semver in web/js.
- Gate PROCEED 15185p/0f/7s exit 0 (p2a_truth_gate_report.json; +5 = new tests exactly). Octopus merge 3b6679fb. NEXT P2b: per-file audit fanout + DS fixture-pin consolidation + .pytest_cache policy + bare-py deferred tail.

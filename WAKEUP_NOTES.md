# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-09 - orchestrated Electron-overlay session: HZ-D1 route + shell P4 + prune + sidequest [item 378]

Operator: continue Electron overlay autonomously, multi-agent orchestrated, self-audit, prune files/branches, no operator gating. 4-agent Workflow (wf_51d1c597) -> merge -> 5-phase UI audit -> verifier -> fix -> push. Commits `b58a1550`/`47b9e5d6`/`c97f5fcc`/`6e8989ec`/`0522ceab`. NO engine, no Share delta, no RC restart.

- **S1 (`b58a1550`):** `?overlay=1` overlay route - `body[data-shell=overlay]` + active-match pin; NEW `web/css/overlay.css` (460px right-dock, transparent page, CALL+BUILD+lead/choices/callouts only) + `web/js/overlay_pulse.js` (one-shot 1.2s edge-glow on content change); asset-hash covers both; +6 snapshot tests.
- **UI audit:** 4 MUST-FIX fixed in-slice (`0522ceab`): flex 0 1 auto/overflow hidden (1080 clip), mount display:flex (gap restore), rn-lead accent re-assert, .rc-src 13px. 3 NICE deferred (active_match.js 9-10px inline fonts, eyebrow contrast, boot-pulse burst).
- **S2 (`47b9e5d6`):** rc-shell P4 partial - ACTIVE 20s auto-revert + poll backoff 2-15s + Alt+Shift+C `panelset=` cycle; node 77/77. Dashboard-side panelset rendering = next slice.
- **S3:** 3 orphan worktree-agent branches DELETED (patch-equivalent to main `9d2e85ea`/`df78b090`/`7e8e47fa`); ROADMAP item-280/281 stale NEXT lines corrected.
- **Prune (`c97f5fcc`):** 10 dated docs -> `_archive/` + 7 refs rewritten; rc-shell/.pytest_cache deleted.
- **Verifier catch:** pre-existing `test_ledger_holds_relocated_items` red (LEDGER split-home) - re-scoped; full suite 5706/0 fail fresh.
- **Sidequest (no naming):** Share core in sync (1.120.0/16.12.1) BUT Share's calculator-ingest subdir pins 1.108.0/16.11.1 + the external site's deployed chunks embed 16.11.1 with no DS markers = bundle offered-not-consumed. OWED: regen ingest bundle at next Share sync; extend `ds_share_sync.py --check` to cover that subdir.
- **S1 agent flag (chip task_8a4ebe04):** renderLead/renderCallouts/renderCoachChoices read `state.latest` keys (lead_projection/callouts/coach) no ingest path assigns - overlay mounts may stay dark until wired; verify on a live game.
- Owed next: Electron visual launch (`npm start`) + live-game overlay capture; dashboard panelset rendering; Phase 4 controls; Phase 5.

---

# 2026-06-09 - HZ precompute regen at live patch 16.12.1 (unblock shadow coverage) [item 377]

Operator "start what is up next that is open" -> diagnosed the Haiku-to-ZERO HZ shadow gate. `hz_shadow_report` showed 0/512 laning + 0/475 build covered. ROOT CAUSE: HZ-A/B precompute dirs existed ONLY at 16.11.1 but live patch is 16.12.1 (item 372 patch-refresh deferred the HZ regen; item 374 S4 re-deferred). The patch-keyed reader found no 16.12.1 dir -> every new-game shadow record logged covered=false. Data-only, NO engine, ENGINE 1.120.0 untouched, no Share (HZ tables not Share-mirrored). Commit `cc35d5ed`, CI green (run 27249973771).

- Regenerated all 3 SR tables at 16.12.1 from the full 172-champ roster (`data/daemon_slayer/16.12.1/champions.json` keys; item-370 baseline +1 patch-added champ):
  - laning_scenarios/16.12.1/laning_scenarios_sr.json  355008 cells / 66MB (LFS)
  - build_orders/16.12.1/build_orders_sr.json          172 champs / 688 orders
  - build_orders/16.12.1/build_order_variants_sr.json  344 orders
- Generators: `core/{laning_scenario_precompute,build_order_precompute,build_order_variants}.py --mode sr --champions <172-csv>`; laning needs `PYTHONPATH=repo` (top-level `agents` import) + 187s for the 172x172x3 sweep.
- Read path live-verified at 16.12.1: `lookup` + `precomputed_choices` Ahri vs Darius L6 -> back_off / "Recall now".
- `hz_shadow_report` 0-coverage is HISTORICAL only - `covered` is baked into each record at log time (report line 81 reads the record, never the live table). Accrues covered=true on NEW games now the dir exists.
- HZ tests 165 passed; ruff/hygiene green; clean tree pushed.
- Don't-redo: SR HZ precompute now current at 16.12.1; ARAM/Arena `--mode all` expand STILL deferred (item 374 S4); owed = confirm covered=true on the next live SR game.

---

# 2026-06-09 - session-start anomaly triage: DDragon flake-tolerance + rc_facts gamepc demotion + /weekly-hygiene automation [item 376]

Session-start flagged 3 anomalies (operator "your call"): RC-DDragonMirrorRefresh result=2, gamepc :8892 None, gamepc bridge stale ~9d. Ops/tools/docs only - NO engine, NO ENGINE bump, NO Share, no RC restart. 4 commits `3f4dc43f`/`f62b5bc1`/`56052df9`/`9cc5a6ad`.

- **DDragon (`3f4dc43f`+`f62b5bc1`):** result=2 was benign - `--check-changed` HEAD-probes 6792 assets nightly, ANY single transient flake (CDN-edge 404 among ~4966 profileicons) tripped `failed>=1` -> exit 2 (foreground re-run: 6792/6792 skip, fail=0). Fix: `fetch_one` retries a 404 once; NEW `FAIL_RATIO_TOLERANCE=0.005` + `_failures_within_tolerance` shared by `_exit_code_for` (exit 2 only when failed/total>0.5%) AND the index-advance gate (a tolerable flake during a version flip advances `_index.json` same-night). +11 tests (52 total).
- **rc_facts (`56052df9`):** gamepc out-of-pipeline post-1PC (ADR-011) so MCP-None + bridge-stale are EXPECTED; NEW `RC_GAMEPC_RETIRED` flag (default on, `=0` re-arms) demotes both to annotated info lines via `_gamepc_mcp_anomaly`/`_bridge_peer_anomalies`; Peer + queue-backlog still flag. +9 tests (file had none). Live: Anomalies now shows ONLY the real DDragon result=2 (self-clears tonight 3:30 AM).
- **/weekly-hygiene (`9cc5a6ad`):** NEW skill `.claude/commands/weekly-hygiene.md` (local/gitignored) + persistent `RC-WeeklyHygiene` task (Sun 04:17) via `tools/weekly_hygiene_run.ps1` (headless `claude -p /weekly-hygiene` sonnet, appends a dated WAKEUP entry so flags surface) + `ops/install_RC_WeeklyHygiene.ps1` (idempotent) + OPERATIONS.md row. CronCreate (7d expiry) + cloud /schedule (no local tree) both unfit. Smoke READY exit 0; NextRun 2026-06-14 04:17.
- **Memory (no git):** 2 capture-memories gamepc:8892 -> Legion-local (Windows-MCP/computer-use/preview); MEMORY.md 2 index hooks updated.
- **Don't-redo:** a single-asset DDragon result=2 is benign-tolerated now (a real outage is >0.5% or pins the index); set `RC_GAMEPC_RETIRED=0` if gamepc returns to service; first `RC-WeeklyHygiene` fires Sun 6/14 04:17 (commits relocate-only trims + appends its own WAKEUP entry).

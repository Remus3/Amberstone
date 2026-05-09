# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s141 wrap — 2026-05-09 (Phase 7 — phase-marker comment normalization)

## What shipped
- **12 RC orchestration phase-markers** converted to `# arch: phase <id> [(YYYY-MM-DD)] — <one-line note>` form across 10 files: `core/bridge_envelope.py`, `core/metrics_cache.py`, `ops/rc_self_monitor.py` (×4), `tools/build_portable.py`, `tft/tft_state_reader.py`, `game_reader/snapshot_normalizer.py`, `agents/agent2_backend/migration_rewind.py`, `tft/tft_live_analysis.py`, `tft/tft_coach_engine.py`.
- **`tools/gen_archmap.py`** extended: new `PHASE_RE` regex + `_collect_phase_markers()` + `_render_phase_journal()`; new sentinel block `<!-- phasejournal:start/end -->` rendered between archmap and god-modules sections of `docs/ARCHITECTURE.md`. Self-skip via `PHASE_SCAN_SKIP_FILES = {"tools/gen_archmap.py"}` to avoid the docstring's example markers polluting output.
- **`docs/ARCHITECTURE.md`**: new "Phase journal" section auto-populated with 11 entries, sorted dated-first by date desc, then undated by phase id.
- **`RC_FUTUREPROOFING_PLAN.md`** (Desktop): Phase 7 phase-marker checkbox + `.rgignore` checkbox flipped; status table updated to 🟠 in-progress (s141).
- 386 tests pass, ruff 0 violations, archmap `--check` clean, py_compile clean. Commit: **48d11be** pushed → origin/main.

## Key decisions
- **Plan estimate vs reality**: plan said "27 phase-markers"; actual universe is ~200+ across 4 numbering systems (RC orchestration Phase 0.X, RC futureproofing 1–7, RC Tier 1–4 milestones, DS engine internal Phase 4 batches in `agents/daemon_slayer/`). Narrowed to RC orchestration/architecture markers only.
- **Excluded**: DS engine batch tags (~100+, own batch system, all dated 2026-05-04, self-document via DS roadmap) and Tier markers (mostly inside frozen files like `web_dashboard.py`, `main.py`, `app/__init__.py`).
- **Skipped frozen file**: `ops/rc_supervisor.py:1188` (FROZEN per CLAUDE.md). Phase 0.13 marker at `ops/rc_self_monitor.py:197` covers same phase; journal not impoverished.
- **Format edge case**: `phase 0.3 (fix 3)` collides with optional `(YYYY-MM-DD)` group; convention is to put qualifiers in the note (`phase 0.3 — note (fix 3)`).
- **Format edge case**: marker line MUST be a complete one-line sentence; the regex is line-based and truncates multi-line continuations. Continuations stay on subsequent comment lines as regular text, not part of the journal note.

## Do NOT redo
- Don't try to mass-convert DS engine `# Phase 4 batch N (2026-05-04):` tags — explicitly out of scope; DS has its own batching system.
- Don't try to convert Tier markers (`Tier 2 #6`, `T2 #8`, `Tier 3 #15`, `Tier 4 #16`) — most live in frozen files; separate convention.
- Don't add phase markers without dates going forward — new markers should include `(YYYY-MM-DD)`. The legacy undated markers were converted as-is to avoid speculative dating.
- Don't edit the `<!-- phasejournal:start/end -->` block manually — pre-commit hook will reject.

## What's next
1. **Phase 7 remaining** — `/wrap` auto-prune of WAKEUP_NOTES, Conventional Commits commit-msg hook. Each warrants its own scoped session.
2. **Phase 6 — Bridge consolidation** — still blocked on operator approval for frozen files (`bridge_post_result.py`, `bridge_pull_tasks.py`, `process-bridge-tasks.md`).
3. **Game-PC LCU agent not posting** — flagged at session start (SessionStart anomaly); separate task, surface for diagnosis if it persists.

---

# s140 wrap — 2026-05-09 (Phase 2.4 — moon_vision_server split)

## What shipped
- **`vision_server/` package** (new): split `moon_vision_server.py` (710 LOC) into 7 internal modules — `_config.py` (75), `_stats.py` (65), `_frame.py` (117), `_relay.py` (118), `_inference.py` (264), `_http.py` (245), `__init__.py` (79). Real code lives here.
- **`moon_vision_server.py`** (kept): reduced to 21-LOC entrypoint shim — `from vision_server import main; sys.exit(main())`. Preserves the file path that `RC-VisionServer` scheduled task and `dashboard/server.py:191` spawn-by-path.
- **`tools/build_portable.py`**: added `moon_vision_server.py` to `_ROOT_PY_FILES` (closed pre-existing bundle gap) + `vision_server` to `_SOURCE_PACKAGES`.
- **`docs/ARCHITECTURE.md`**: god-module table updated, archmap auto-regenerated.
- 386 tests pass, ruff clean, `:8889/health` verified post-restart (PID 17508→10476). Commit: **9cf262a** pushed → origin/main.

## Key decisions
- **Shim pattern, not package replacement**: `moon_vision_server.py` is spawned by file path from two callers (scheduled task XML + dashboard subprocess). Editing those would require touching frozen-adjacent task XML; keeping a 21-LOC shim is cheaper and preserves the contract.
- **Sub-file deviation from plan**: plan listed 4 files (frame_upload, frame_cache, tier_routes, sonnet_escalation). Actual = 6 internal because plan missed LCU relay, liveclient relay, stats, HTTP handler, config. Combined frame_upload+frame_cache (share state) and combined tier_routes+sonnet_escalation into `_inference.py` (both inference handlers feeding same stats).
- **Cross-module state**: `_frame` and `_relay` directly mutate `_stats._stats[k]["bytes"]` under `_stats._stats_lock`. Kept the direct mutation — wrapping it in setters would just create indirection.
- **Pre-existing bundle gap**: `moon_vision_server.py` was NEVER in `_ROOT_PY_FILES` — portable builds have been shipping without the vision server. Fix bundled with this change.

## Do NOT redo
- Don't try to import from `moon_vision_server` (Python module) — the file is path-spawned, not import-consumed. Use `from vision_server import …` instead.
- Don't delete `moon_vision_server.py` thinking it's dead code — RC-VisionServer scheduled task XML hardcodes that path.
- Don't switch `python.exe` → `pythonw.exe` in the task XML without operator approval; that's a console-window cosmetic, not a Phase 2.4 scope item.

## What's next
1. **Phase 6 — Bridge consolidation** — blocked on operator approval for frozen files (`bridge_post_result.py`, `bridge_pull_tasks.py`, `process-bridge-tasks.md`).
2. **Game-PC LCU agent not posting** — SessionStart anomaly flagged at session start; separate task, surface for diagnosis.
3. **Vision regions calibration** — blocked on live game.

---

# s138 wrap — 2026-05-09 (Phase 2.3 — coach_integration split)

## What shipped
- **`coach_integration/` package** (new): split `coach_integration.py` (1225 LOC, `\r\r\n` line-ending artifact) into `_profiles.py` (181 LOC), `_sr_prompt.py` (455 LOC), `_coach.py` (607 LOC), `__init__.py` (6 LOC facade). All frozen-file callers (`app/__init__.py`, `main.py`) unchanged.
- **`tools/build_portable.py`**: removed `"coach_integration.py"` from `_ROOT_PY_FILES`, added `"coach_integration"` to `_SOURCE_PACKAGES`.
- **`docs/ARCHITECTURE.md`**: archmap regenerated for new package sub-modules.
- **FUTUREPROOFING_PLAN.md** (`Desktop`): Phase 3.3 and Phase 2.3 marked done; status table updated.
- 386 tests pass, ruff 0 violations.

## Key decisions
- Actual structure was SR-only (not multi-mode dispatch) — planned `dispatch.py/budget.py/cache_keys.py/writers.py` split didn't match reality; used `_profiles/_sr_prompt/_coach` instead.
- File had `\r\r\n` double-CR endings making Python splitlines() double-count lines (2449 apparent, 1225 real). Stripped on extraction.
- Path fix: `Path(__file__).parent` → `.parent.parent` in `_sr_prompt.py` and `_coach.py` since files are now one level deeper.
- `main.py` (frozen) sets `_ci._APP_DIR = APP_DIR` — attribute injection onto package `__init__`; never READ, harmless.

## Do NOT redo
- Don't re-investigate the line-count discrepancy — it was `\r\r\n` endings, stripped at extraction.
- Don't try to put `CoachIntegration` in a smaller file — the class is naturally 578 lines.

## What's next
1. **Phase 2.2** — `game_reader.py` (1473 LOC) split into `core/game_reader/` package.
2. **Phase 4 remaining** — dispatch-level POST validation in `_dispatch.py` (low priority).
3. **Vision regions calibration** — blocked on live game.


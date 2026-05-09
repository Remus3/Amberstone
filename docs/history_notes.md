# RC session history archive

Sessions older than the last 2–3 full sessions are progressively compacted here.
Current WAKEUP_NOTES.md keeps only the most recent 2–3 sessions.
Compaction rule: 3+ sessions old → 1-2 line summary entry below.

---

# s143 wrap — 2026-05-09 (Phase 4.1 — dispatch-level soft-warn validator)

## What shipped
- **`dashboard/_dispatch.py`** gained `_validate_request_body(path, body)` called at the top of `dispatch_post` before route lookup. Path-keyed against `_REQUEST_MODELS` (5 paths today: `/api/input`, `/api/command`, `/api/ds-preview`, `/api/bridge/inbox`, `/api/speak`). Soft-warn — never raises, never blocks dispatch; route handlers still run their own existing validation.
- **`tests/phase4_dispatch_validate/`** (new) — 26 tests: registry shape, valid bodies (5 routes × minimal + ds-preview full), invalid bodies (missing required, wrong type, extras-on-`_ForbidExtra`, allow-extra-on-`_AllowExtra`), non-dict bodies (None/list/str/int parametrized), query-string handling, and a `dispatch_post` integration test that monkeypatches `_gather_post` to confirm validator fires before route dispatch.
- **Live verified**: POSTed `{}` to `https://127.0.0.1:8888/api/input` → route returned `400 empty_text` AND log emitted `WARNING rc.dispatch request_body[/api/input] text: Field required` (validator fired). POSTed `{"text":"phase4 smoke"}` → `200 ok`, no warnings.
- **Plan + CLAUDE.md updated**: `RC_FUTUREPROOFING_PLAN.md` Phase 4 closed (4.1 codegen target + 4.3 dashboard JS sub-checkbox flipped — Phase 3.2 had already shipped them; dispatch checkbox flipped + s143 Findings appended; status table 🟠→🟢 2/2 sessions). CLAUDE.md priority #4 ✅. 440 tests pass (was 412, +26 new + 2 drift). Ruff clean. archmap clean. Commit: **791e2db**.

## Key decisions
- **Soft-warn, opt-in by path** (not central hard-validate). Adding a route to `_REQUEST_MODELS` is one line; missing routes pass through silently. Mirrors the operator-approved Phase 4.3 `validate_coaching_payload` pattern. Hard-gating per-route is a future tightening once we trust the contract is stable.
- **5 paths covered, 16 unmodeled paths pass through silently**: loadout/sr-draft/replay-coach/coach-toggle/experimental-*/aram-analyze/decisions-*/health-peer-* don't have Request models in `api_schema.py` yet. No false-warning noise on routes without a model.
- **`_dispatch.py` had `\r\r\n` (double-CR) endings** — same Phase 2.3 gotcha as `coach_integration.py`. Normalized to LF on this edit; commit diff shows `+394/-113` because of the EOL normalization, NOT because the rewrite was extensive.
- **caplog gotcha noted**: `LogRecord.message` is unset until `getMessage()` is called. First-cut test helper used `r.message % r.args`; switched to `r.getMessage()` (canonical). Worth remembering for any future caplog-based test.
- **Phase 4 fully closes** even though 4.3 still has unchecked boxes — those (`bridge_log.py` mirror, OBS publisher) were explicitly marked "out of scope" / "non-existent in tree" in the s129 Findings.

## Do NOT redo
- Don't add hard-rejection (HTTP 400) for invalid bodies in `_dispatch.py` without operator buy-in — soft-warn was the explicitly approved pattern. Silently dropping requests that previously worked would be a regression.
- Don't add the unmodeled 16 POST routes to `_REQUEST_MODELS` without first authoring their pydantic Request models in `api_schema.py` — the lookup will crash if a path maps to None or to something not a `BaseModel` subclass.
- Don't try to hard-rewrite `dashboard/_dispatch.py` to use `_AllowExtra` everywhere "to silence warnings" — `_ForbidExtra` on `InputRequest`/`CommandRequest` is intentional (these have a finite-keyword API surface and any extra field IS a contract drift signal).
- Don't reintroduce CRLF or `\r\r\n` to `_dispatch.py` — file is now LF, archmap header still recognized, all hooks pass.

## What's next
1. **Phase 6 — Bridge consolidation** — still blocked on operator approval for frozen files (`bridge_post_result.py`, `bridge_pull_tasks.py`, `process-bridge-tasks.md`). Only un-shipped phase from the futureproofing plan.
2. **Game-PC LCU agent — phase=Offline persistent** — flagged at session start (probe showed phase=Offline age=-27s); separate diagnosis task if it persists into next session.
3. **Vision regions calibration** — blocked on live game.
4. **Optional follow-on for Phase 4**: extend `_REQUEST_MODELS` coverage to the 16 unmodeled POST routes once their schemas are authored in `api_schema.py`. Low-priority polish; not blocking.

---

# s142 wrap — 2026-05-09 (Phase 7 — WAKEUP_NOTES auto-prune + Conventional Commits hook)

## What shipped
- **`scripts/wakeup_prune.py`** (new, 130 LOC): pure-Python helper that splits WAKEUP_NOTES.md by `\n---\n\n`, identifies sessions via `^# s\d+ wrap` regex, keeps the first N (default 3), and atomically moves the remainder to `docs/history_notes.md` newest-first. Modes: default (prune), `--dry-run`, `--check` (exits 1 if over limit). Idempotent — re-running is a no-op. Self-heals legacy buggy files missing the blank-line-before-rule (28 unit tests cover the round-trip).
- **`.githooks/commit-msg`** (new) + **`scripts/precommit_msg_check.py`** (new, 110 LOC): commit-msg hook validating Conventional Commits subject lines. Pattern: `^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([\w./\- ]+\))?!?:\s+\S`. Skips Merge/Revert/Reapply/fixup!/squash!/amend! auto-subjects; soft-warns over 100 chars; bypassable via `--no-verify`. Activates the moment `git config core.hooksPath .githooks` is set (already required for pre-commit).
- **`tests/phase7_polish/`** (new): 28 unit tests covering split/render round-trip + blank-line preservation + buggy-input self-heal + 4 prune scenarios + check mode + every recent commit shape from `git log` + all canonical types + scopes with `./-/` chars + breaking-change `!` + all skip-prefixes + 9 reject cases.
- **`/done` skill section 6c rewritten** in both project-local (`.claude/commands/done.md`) and user-level (`~/.claude/commands/done.md`) — replaced the 5-step manual archive workflow with a single `py scripts/wakeup_prune.py --keep 3` invocation.
- **Living docs synced**: ROADMAP.md + CLAUDE.md priorities + RC_FUTUREPROOFING_PLAN.md (Desktop) all reflect Phase 7 → ✅ Done. Archmap regenerated to index 2 new phase-7 markers (`scripts/wakeup_prune.py:4`, `scripts/precommit_msg_check.py:4`).
- 414 tests pass (was 386, +28 new), ruff 0 violations, archmap `--check` clean.

## Key decisions
- **Archive target = `docs/history_notes.md`, NOT `docs/_archive/CHANGELOG.md`** as plan said. The existing /done skill already pointed at history_notes.md and 27+ sessions are already archived there. Switching now would either invalidate the existing archive or require a one-shot migration with no upside.
- **`--check` mode but NOT wired into pre-commit (yet)**. Pre-commit-hook enforcement of "WAKEUP_NOTES has ≤3 sessions" would block commits whenever the operator forgot to prune. That's annoying and recoverable. The helper is idempotent and the /done skill calls it; trust the skill, don't bolt on a forcing function.
- **Hook validates SUBJECT line only**. Body and trailers are unrestricted (so `Co-Authored-By:` trailers, multi-paragraph bodies, etc. all pass through). Standard Conventional Commits behavior.
- **Render bug found via dogfood**: first-cut helper stripped trailing `\n` per block + joined with `\n---\n\n`, producing `bullet\n---\n\n# next` (missing blank line above rule). Fixed by `rstrip + add \n` per block, joined with `\n---\n\n`. Round-trip on a buggy legacy file now self-heals to canonical form. Tests for both directions added.
- **Period normalization on phase-marker notes**: docstring lines ending in `.` were stripped to match the existing convention (other markers in the journal don't end in periods). Pre-commit `gen_archmap.py --check` enforces drift.
- **Two done.md copies**: project-local (`C:/Riot Commander/.claude/commands/done.md`) is committed source-of-truth; user-level (`~/.claude/commands/done.md`) is a personal mirror. Edited both for consistency.

## Do NOT redo
- Don't try to switch the WAKEUP_NOTES archive to `docs/_archive/CHANGELOG.md` — `docs/history_notes.md` is the established archive and 27+ sessions are already there.
- Don't add `wakeup_prune.py --check` to pre-commit hook without operator buy-in — it would block commits during normal in-progress work.
- Don't tighten the commit-msg regex to disallow scopes with spaces or `/` — multiple recent commits (e.g. `feat(scripts/wakeup): …`) intentionally use those.
- Don't strip the `Reapply ` skip-prefix — it's emitted by `git revert <revert-commit>` and is a legitimate auto-subject.
- Don't reintroduce `b.strip("\n")` in `render()` — it was the cause of the lost-blank-line bug; test `test_render_preserves_blank_line_before_separator` is the regression.

## What's next
1. **Phase 6 — Bridge consolidation** — still blocked on operator approval for frozen files (`bridge_post_result.py`, `bridge_pull_tasks.py`, `process-bridge-tasks.md`).
2. **Phase 4 remaining** — dispatch-level POST validation in `_dispatch.py` (low priority).
3. **Game-PC LCU agent not posting** — flagged at session start (SessionStart anomaly); separate task, surface for diagnosis if it persists.
4. **Vision regions calibration** — blocked on live game.

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

---

# s137 wrap — 2026-05-08 (Phase 3.3 — Playwright panel snapshot tests)

## What shipped
- **`tests/snapshot_panels/`** (new): 6-fixture Playwright harness — lobby/sr/aram/arena/brawl/tft × 4 panels = 24 screenshots per run.
- **`tests/snapshot_panels/conftest.py`**: `_MockServer` (ThreadingHTTPServer serving `web/` + fixture-driven `/api/*`), `pw_browser` session-scoped fixture, `_WS_STUB` JS snippet.
- **`tests/snapshot_panels/test_panel_snapshots.py`**: parametrized `test_panels[fixture]` — loads fixture, waits for `#rn-action` coaching text (or 800ms for lobby), asserts all 4 panels visible, screenshots each.
- **`.github/workflows/ci.yml`**: added `playwright install --with-deps chromium` step + `panel snapshot tests` step.
- Commit: **02ed835** pushed → origin/main.

## Key decisions
- Root cause of flaky failures: the dashboard's WebSocket connects to the **real supervisor on :8891** (not just the mock HTTP server). The real supervisor sends live `mode="client"` health/state, overriding the fixture and hiding `#item-build`. Fix: `_WS_STUB` injected via `page.add_init_script()` makes `window.WebSocket` immediately fire `onclose` without connecting.
- SSE format: the mock sends `store["data"]` (raw `StateResponse` JSON with `mode_key`) directly. The JS `setupStateStream()` reads `st.mode_key`, not a WS-style envelope wrapper.
- Arena/TFT: both pass cleanly once WS is stubbed. TFT doesn't use `#item-build` for build paths but the panel IS visible (CSS only hides it for `data-mode="client"`).

## Do NOT redo
- Don't re-investigate the `#item-build` visibility issue — it was the WS (:8891) overriding fixture. Stubbing WS fixed it in 02ed835.
- Don't try to remove the WS stub; it's intentional isolation for test determinism.

## What's next
1. **Phase 2.3** — `coach_integration.py` (1217 LOC) split into `coach_integration/` package.
2. **Phase 4 remaining** — dispatch-level POST validation in `_dispatch.py` (low priority).
3. **Vision regions calibration** — blocked on live game.

---

# s136 wrap — 2026-05-08 (Phase 3.2 — JSDoc typedef codegen)

## What shipped
- **`tools/gen_state_schema.py`** (new): introspects `dashboard/api_schema.py` + `core/coaching_payload.py` pydantic models; emits `web/js/lib/state_schema.js`. `--check` mode exits 1 if out of sync.
- **`web/js/lib/state_schema.js`** (new, generated): 12 `@typedef` blocks — `CoachPayload` union + 5 per-mode payloads (Aram/Arena/Brawl/Sr/Tft) + 6 HTTP shapes (StateResponse/HealthBlock/etc). `StateResponse.coach` overridden to `CoachPayload` type.
- **`web/jsconfig.json`** (new): `checkJs: false`, `include: js/**/*.js` — VS Code resolves imports without TypeScript compilation.
- **`.githooks/pre-commit`** (modified): schema sync check added after archmap check.
- **`docs/ARCHITECTURE.md`** (auto-updated): archmap regenerated for new `gen_state_schema.py` entry.
- Commit: **e65135c** pushed → origin/main.

## Key decisions
- Script introspects `model_fields[name].annotation` directly (pydantic v2 resolves string annotations from `from __future__ import annotations` at class creation time — always actual type objects).
- `StateResponse.coach` is `dict[str,Any]` in Python but overridden to `CoachPayload` in `_OVERRIDES` — this is the whole point of the typedef file.
- `export {}` at end of `state_schema.js` makes it an ES module (required for `@import` to work from other ESM files).

## Do NOT redo
- Don't re-run `gen_state_schema.py` manually if you just changed a pydantic model — the pre-commit hook will catch it and print the hint. Just run it once and commit.

## What's next
1. **Phase 3.3** — Playwright snapshot tests: 5 panels × 26 sim fixtures = 130 PNG snapshots, wire to CI.
2. **Phase 2.3** — `coach_integration.py` (1217 LOC) split into `coach_integration/` package.
3. **Phase 4 remaining** — dispatch-level POST validation in `_dispatch.py` (low priority).
4. **Vision regions calibration** — blocked on live game.

---

# s135 wrap — 2026-05-08 (Phase 3.1 — CSS panel split)

## What shipped
- **`scripts/extract_css_panels.py`** (new): one-shot extractor — 13 sections by line-range, writes `web/css/panels/*.css`, rewrites `dashboard.css` as 25-line `@import` router.
- **`web/css/panels/`** (new): 13 panel CSS files — `base.css` (106 lines), `header.css` (1637), `grid.css` (463), `bridge_pending.css` (375), `map_state.css` (580), `right_now.css` (97), `next.css` (47), `item_build.css` (441), `input_activity.css` (506), `champ_select.css` (364), `home.css` (841), `primitives.css` (290), `dev.css` (54).
- **`web/css/dashboard.css`** (modified): 5812 → 25 lines (Google Fonts @import + 13 panel @imports).

## Key decisions
- `champ_select.css` merges two non-contiguous source ranges (lines 4264–4276 + 5118–5468); the home overlay CSS between them goes into `home.css`. Cascade order is safe — distinct class namespaces (`cs-*` vs `home-*`).
- Static handler `prefix("/css/")` already covers subdirs — no server change needed.

## Verification
- All 13 panel files + dashboard.css: HTTP 200 from RC.
- Game-PC dashboard screenshot: all panels render correctly, no layout regressions.

## Do NOT redo
- Don't re-run `extract_css_panels.py` — dashboard.css is now the @import router; re-running would split an already-split file.

## What's next
1. **Phase 3.2** — `tools/gen_state_schema.py` introspects `dashboard/_state_builder.py` → `web/js/lib/state_schema.js` JSDoc `@typedef` blocks + pre-commit hook sync.
2. **Phase 3.3** — Playwright snapshot tests (5 panels × 26 sim fixtures = 130 PNGs), wire to CI.
3. **Phase 4 remaining** — dispatch-level POST validation in `_dispatch.py` (low priority).
4. **Vision regions calibration** — blocked on live game.

---

# s134 wrap — 2026-05-08 (null session — no work done)

## What shipped
- Nothing. Session opened with `/done` immediately.

## RC state at close
- pid=1108, alive=True, last_reload_ok=True
- mode_key=client, lcu_phase=Unknown (not in game)
- No unpushed commits. No pending lessons.

## What's next
1. **Phase 3.2** — CSS split: `web/css/panels/*.css` with `@import` in main CSS
2. **Phase 3.3** — JS typedef codegen from `api_schema.py` (deferred until Phase 3 panels proven stable)
3. **Phase 4 remaining** — dispatch-level POST validation (low priority)
4. **Vision regions calibration** — blocked on live game

- **s135 (2026-05-08)** Phase 3.1 CSS split — `scripts/extract_css_panels.py` one-shot extractor; 13 CSS panel files in `web/css/panels/`; `dashboard.css` → 25-line @import router (5812→25 LOC). Dashboard screenshot verified.
- **s133 (2026-05-08)** Phase 3.1 ESM panels — `tools/extract_panels.py`; 7 panel JS modules extracted from main.js (8225→4189 lines). Commit `38ac760`.
- **s132 (2026-05-08)** Phase 3.1 ESM lib/ — `web/js/main.js` + 4 lib modules (helpers/state/items_index/idempotent_render); ESM module type on index.html. Commit `7bbf032`.
- **s131 (2026-05-08)** TFT 17.3 patch update — Morgana 4g, Anima/Stargazer reworks, Primordian AVOID, AP comps buffed, Horizon Focus removed. `tft_pbe_data.py` + `tft_pbe_engine.py`. Commit `0e9617b`. 380 tests pass.
- **s130 (2026-05-08)** CI fix — anthropic try/except guard in `coach_integration.py`; pydantic added to `requirements.txt` + CI. Commit `808afea`. 380 tests green.
- **s129 (2026-05-08)** Phase 4 contracts/schemas — `core/coaching_payload.py` (5 pydantic models, soft-validate), `dashboard/api_schema.py`, `core/bridge_envelope.py`, `docs/API.md` (40 routes). Commit `31bbe4f`. 4.2 tool rewrites blocked (frozen files). JS typedef codegen deferred to Phase 3.

---

# s128 wrap — 2026-05-08 (Phase 5 — CI gate + smoke harness COMPLETE)

- Commit `d21f533`. Fixed test_app_authority.py (52→0 failures, _HeadlessApp subclass). Arena/Brawl golden fixtures added (343→380 tests). phase2_smoke suite (31 tests, all 5 coach modes). CI: ruff + phase8_smoke wired. ruff.toml 101→0 violations. Bug fix: tft_live_analysis.py:274 `_j.loads`→`_pj.loads`.

---

# s127 wrap — 2026-05-08 (Phase 2.1 — champion_profiles.py split COMPLETE)

## What shipped
- **`champion_profiles.py`** shrunk from 902 → 29 LOC. Now a thin JSON loader.
- **`data/champion_profiles/*.json`** — 168 champion files, each a flat dict with `dmg/role/mana/sustain/mechanic/aram` fields. All checked in.
- **`scripts/extract_champion_profiles.py`** — one-shot migration helper left in tree as migration doc.
- **`docs/ARCHITECTURE.md`** — god-module table updated; archmap regenerated via pre-commit.
- **`ROADMAP.md`** — Phase 2.1 ✅ Done.
- Commit **8fa11f4** pushed → origin/main (172 files changed: 1399 insertions, 906 deletions).

## Key decisions
- Thin loader stays at **root `champion_profiles.py`** (not `core/`). `ops/rc_dev_runtime.py` (frozen) watches `"champion_profiles"` as a module-name string — moving it would require a frozen-file edit. Zero caller changes.
- Import surface preserved exactly: 12 module-level exports (`CHAMPIONS, TANKS, FIGHTERS, MAGES, ASSASSINS, MARKSMEN, SUPPORTS, AD_CHAMPS, AP_CHAMPS, HYBRID_CHAMPS, SUSTAIN_CHAMPS, MANA_CHAMPS`).
- Pre-existing test failure in `tests/snapshot_regressions/test_app_authority.py` is unrelated — confirmed via git stash; 289 other tests all pass.

## Do NOT redo
- Don't re-run the extractor — 168 JSONs already committed. It's idempotent but unnecessary.
- Don't re-backfill `# arch:` header on `champion_profiles.py` — already updated to "thin loader".

---

# s108 wrap — 2026-05-06 (WT flash fixes — Legion + Game-PC)

- `dashboard/server.py`: `creationflags=0x08000000` on vision server Popen (commit `cab0ce4`). Game-PC `gamepc_bridge_daemon.py`: `--dangerously-skip-permissions` fix + DEVNULL suppression — stopped 807+ crash-loop invocations per day.

---

# s107 wrap — 2026-05-06 (API cost audit + dynamic debounce + CLAUDE.md slim)

## What shipped
- **Vision loop gate** — `_run_vision()` guards in ARAM/Arena/Brawl coaches: `if self._fetch_game_data() is None: return`. Kills 24/7 Sonnet burn when no game is active (was 84% of LoLOverlay key spend on May 4).
- **Dynamic debounce** — all 3 coaches: `_STABLE_DEBOUNCE_S` class attr (ARAM 25s / Arena 22s / Brawl 20s). `_on_state_received` sets `self._DEBOUNCE_S` to stable rate when no meaningful state change; snaps back to fast rate on dead_enemies / items / level / hp_pct drop ≥10.
- **CLAUDE.md slimmed** from 355→109 lines. Deep docs moved to `docs/AGENTS.md` (new) + `docs/DAEMON_SLAYER.md` (new). Bridge spawn cost note added.
- **Settings cleanup** — both `.claude/settings.json` files: removed `typescript-lsp` plugin; `additionalDirectories` `C:/` → `C:/Riot Commander`.
- Commits: `5658b1f` (vision gate + debounce + CLAUDE.md slim)

---

# s117 wrap — 2026-05-08 (TFT patch 17.2)
TFT patch 17.2: tft_pbe_engine.py system prompt + tft_pbe_data.py ENCOUNTERS (21) + GOD_BLESSINGS (24) + trait balance. tft_set17_meta.json -> 17.2. commit be3d168. DDragon still shows "16.9.1" (stale cache) — actual patch 26.9; coaching functional.

---

**s125 — 2026-05-08** (9234d0f) Phase 1.1 knowledge architecture: docs/_archive/ created, 23 dated artifacts moved, 4 living docs authored (ARCHITECTURE.md 136 lines, OPERATIONS.md 153, BRIDGE.md 136, ROADMAP.md 64). Bootstrap reduced from 2000+ → 492 lines.

**s124 — 2026-05-08** (no commit) RC_FUTUREPROOFING_PLAN.md authored on Desktop by Opus 4.7 1M context — 7-phase leverage-ordered refactor plan. No code changes.

---

- **s123 2026-05-08** — rc_facts bridge probe rewrite (04a305b): `/api/health/all` peer probe replaces stale log-age heuristic. DS server health line added. RC-DaemonSlayer false exit-1 anomaly suppressed (server healthy; task runs as SYSTEM, can't write logs).
- **s122 2026-05-08** — Game-PC socket exhaustion (STATUP.GG/Overlay Platform M 17,463 kernel handles → WSAENOBUFS). `taskkill /F /PID 3340`; restarted RC-WatcherHealthPublisher-GamePC + RC-BridgeWatcher-GamePC tasks. TDD skill installed fleet-wide.
- **s121 2026-05-08** — Fleet model downgrade → `claude-sonnet-4-6` 200k. 5 plugins disabled on Legion (nimble, ralph-loop, playwright, chrome-devtools-mcp, firecrawl); Peer mirrored via bridge task. MEMORY.md pruned 6 stale entries.
- **s120 2026-05-08** — RC dev panel shipped (7424e24): `⚙ Dev / Sim Preview` view with SIM FIXTURES, VISION STATUS, RC LOG TAIL cards; `dashboard/routes_dev.py` + CSS view-switch.
- **s119 2026-05-08** — Roadmap: 5 items shipped — Phase 4 SessionStart enrichment (d069e4d), DS startup diagnostics (04e63d4), SR coach objective_window fix (e8d976b), bridge introspection `?source=` param (5a790d2), ROADMAP closures (items_index rotation, vision_token policy).
- **s118 2026-05-08** — Bridge Watcher node-load restraint (f3ae4cb): `_check_rc_health()` downgrades auto-action to escalate when RC degraded; push notifications suppressed during degraded cycles; 30/30 selftests pass; watcher pid=15004.
- **s116 2026-05-08** — Game-PC boot fix + Smite jungler detection (1ef54e3/2229d89/6bec3ce): `gamepc_boot.ps1` now calls `start_gamepc_claude.ps1`; Smite-based 3-tier jungler cascade in `game_reader.py`; 8 new tests.
- **s115 2026-05-07** — DS calibration game_id wiring (d66d14b): `gamepc_lcu_agent.py` fetches `gameData.gameId` in-game; `game_reader.py` reads `/latest-lcu` relay; `coach_integration.py` passes game_id to `log_ds_run()`.
- **s114 2026-05-07** — Bridge Watcher Phase 3 (6dd91ff): `--dry-run` mode, artifact rotation, self-healing watchdog thread; 21/21 selftests.
- **s113 2026-05-07** — Bridge Watcher Phase 2 (05983a4): adaptive cadence (`_read_mode()`), active/sleep/auto modes, `/api/bridge/cadence`, `/sleep`+`/wake` slash commands.
- **s112 2026-05-07** — Bridge Watcher Phase 1 (f6095a0): sliding 24h event ring, push notifications, RC-DaemonSlayer result=1 fix.
- **s111 2026-05-06** — Infrastructure fixes: RC-BridgeWatcher + RC-Phase3-Supervisor restarted; `claude-rc.ps1` `/loop` removed; ROADMAP fleet-health items marked ✅.
- **s110 2026-05-06** — Cross-Claude sync Phase 3 + DS/roadmap doc cleanup. `_lessons_summary()` in `rc_facts.py` for SessionStart hook (4c4ce1a); ROADMAP/CLAUDE/README doc cleanup (b6d02ae).
- **s109 2026-05-06** — Memory library: 6 new memory entries (feedback + reference patterns). No code changes to RC repo.

---

## s106 wrap — 2026-05-05 (DaemonSlayer flash fix + preflight expansion)

### What shipped
- **`ops/RC-DaemonSlayer.xml`** — `python.exe` → `pythonw.exe`; task reinstalled. No more console flash on boot/restart. DS live at `:8893` engine=0.60.0 patch=16.9.1.
- **`start_claude.ps1`** — added RC-DaemonSlayer + RC-Phase3-Supervisor + RC-BridgeWatcher preflight checks; `:8893` + `:8890` HTTP probes; final `claude` launch fixed to `--name "Legion"`. commit `0d1b545`.

### Do NOT redo
- RC-DaemonSlayer XML is already pythonw.exe.

---

## s92–s103 detailed notes (2026-05-04 – 2026-05-05)

### s103 — 2026-05-05 (DS champ-select panel + dashboard bug fixes)
- **DS champ-select panel** `112350a` — `#cs-ds-block` + `/api/ds-preview` endpoint. Fires once per (champion, mode). Item tiles with +Ndps tooltips.
- **SR SSE mode fix** `5ee58b6` — `_state_builder.py` returned `mode_key="game"`; JS `driveNow` dropped all SR state. Fixed to `"sr"`.
- **Item icon cache race** `f5ce231` — `_itemResolveCache` cached null before `items_index.json` loaded; idempotency sig blocked re-render. Fix: clear cache + tile sigs on ITEMS load.
- **Augments pill fix** `5ee58b6` — CSS `static-pill` overrode `.hidden`; now `display:none !important`.
- **`/done` §6b living-doc sync** `d6fbce0` — ROADMAP/CLAUDE.md/README updated as part of done ritual.

### s102 — 2026-05-05 (SR coach signature hash fix + RECOMMENDED panel)
- **SR coach hash fix** (frozen, user-approved) — `_state_signature` fallbacks had wrong key names vs `_convert` output. hp_bucket/mana_bucket/gold_bucket/level all fixed. Coach now re-fires on HP changes, gold/item thresholds, level-ups, deaths.
- **RECOMMENDED panel** — `dashboard.js` falls back to `sr_items` when `item_build` empty; `next: true` items populate RECOMMENDED.
- **SR API key** — `API-Key-Claude.txt` written from CLI env to unblock SR coaching.

### s101 — 2026-05-05 (DS health indicator + Item Build DS picks panel)
- **DS health in `/api/health/all`** `50248a7` — probes `:8893/health`; DS down → yellow rollup.
- **Health dot tooltip** — DS engine status: `DS engine up · v0.60.0 · 547i/168c`.
- **Item Build panel DS section** — `#ib-ds-block` renders `daemon_slayer_picks` as `.ds-chip` compact chips with green delta-dps text.

### s100 — 2026-05-05 (Tiered vision + open-items cleanup)
- **Tiered vision** `46e9fb8` — `GameVisionReader.read_tiered()` + `read_or_escalate()` wired into ARAM/Arena/Brawl. OCR first; `timer` canary gates Sonnet escalation. Expand by calibrating `data/vision_regions.json`.
- **Open items** `41c87bc` — rune writer SR shard3: 5002→5001; items_index.json alias collision sorted by ID length; Yunara phantom dups: zero-duration exit + 90-min dedup.

### s99 — 2026-05-05 (Daemon Slayer batch 64 — Malignance + Stage 5 calibration)
- **Batch 64** `e7c4cd9` — Malignance Hatefog promoted (ENGINE_VERSION 0.60.0, 929 tests). New `CallContext.ult_casts_per_sec` + `ult_rates.py` (172 champions from rewind_history.db). Deferred: 3 (Lightning Braid, Kinkou Jitte, Mejai's Arena).
- **Stage 5 calibration pipeline** — `core/ds_calibration.py` + `data/ds_calibration.jsonl`; all 4 coaches log DS picks per tick.

### s98 — 2026-05-05 (Daemon Slayer batch 63 — blocked items resolved)
- **Batch 63** `e56e878` — Hellfire Hatchet (CD=15s confirmed), Fiendhunter Bolts (CD=45s confirmed), Innervating Locket Fill the Soul promoted. ENGINE_VERSION 0.59.0, 922 tests.
- Key insight: check Meraki `passives[].cooldown` before deferring "ability-triggered" items.

### s96 — 2026-05-04 (ARAM DS-before-Haiku refactor + documentation sweep)
- **ARAM coach DS-before-Haiku** `3b84949` — DS `rank_for()` before `messages.create()`; `{ds_picks}` injected into user turn; pre-DS hardcoded item rules removed (−37% system prompt ~1,849→1,170 tokens).
- **Documentation sweep** — CLAUDE.md, README.md, ROADMAP.md updated. `DS_COMPLETION_ROADMAP.txt` created on Desktop.

### s95 — 2026-05-04 (Daemon Slayer batches 57–62)
- Batches 57–60 `9f128c4..864e65d` — `caster_bonus_armor` + `caster_lethality` added; Void Immolation, Golden Spatula, Darksteel Talons, Bastionbreaker, Reality Fracture promoted. ENGINE_VERSION 0.57.0, 899 tests.
- Batch 61 `2148ed2` — Zaz'Zak's Realmspike + Bloodsong (spellblade + Expose Weakness damage_amp). 899 tests.
- Batch 62 `dcfeb63` — Cruelty dual-variant (Arena 447109 + SR 667109). ENGINE_VERSION 0.58.0, 911 tests.

### s94 — 2026-05-04 (Daemon Slayer batches 54–56)
- Batch 54 `ded3d01` — `bonus_ap_stacked` (Mejai's) + `bonus_as_conditional` (Yun Tal 27% uptime) + Sword of the Divine. ENGINE_VERSION 0.55.0, 843 tests.
- Batch 55 `e054c1c` — 46 defensive_only entries; DDragon purchasable coverage COMPLETE (547 entries, 850 tests). Coverage gate test added.
- Batch 56 `ede9c89` — `ap_amp_pct_per_100_caster_hp` schema; Demonic Embrace Arena. ENGINE_VERSION 0.56.0, 856 tests.

### s93 — 2026-05-04 (Daemon Slayer batches 50–53)
- Batch 50 — `armor_reduction_flat` + `mr_reduction_flat` schema; Flesheater promoted.
- Batch 51 — Fated Ashes (Inflame) + 5 defensive components.
- Batch 52 — Night Harvester, Luden's Echo, Bloodletter's Curse SR; ability-cast schema resolved via `every_n_seconds`.
- Batch 53 `255dd22` — Hamstringer Scour + Stormsurge Squall. ENGINE_VERSION 0.54.0, 829 tests.

### s92 — 2026-05-04 (Daemon Slayer batches 38–49)
- Batches 38–41 `0369403..bc61b4c` — Giant Slayer schema; `mr_reduction_pct`; Arena re-skins; Navori key collision fix. 494 tests.
- Batches 42–43 `b92301f` — Arena 222xxx/223xxx/224xxx/32xxxx mirrors; 83 defensive_only. 530 tests.
- Batches 44–45 `6eaccae` — Sheen spellblade; Tiamat Cleave; Bami's Cinder Immolate; boots. 558 tests.
- Batches 46–47 `8795097` — Divine Sunderer Arena; Demonic Embrace; Blighting Jewel. 587 tests.
- Batches 48–49 `1230dca` — 1xxx components complete; Spellslinger's Shoes dual-pen; Arena Arena. ENGINE_VERSION 0.53.0, 603 tests.

---

## Session ledger s27–s91 (condensed — from WAKEUP_NOTES compaction 2026-05-04)

All narrative detail in `ROADMAP.md §1` and `git log`.

| Session | Date | Key commit(s) | Theme |
|---|---|---|---|
| s27 (a–u) | 2026-05-01 | 778971d..957dab7 | All Tier 1–4 audit items; asyncio migration (T2 #8 C1–C5); tkinter-free |
| s28 | 2026-05-02 | a38d002..7307e6a | RC↔Peer cross-Claude bridge live (Tailscale); inheritance arc |
| s29 | 2026-05-02 | 7223afe, c4c9e07 | Game-PC joined tailnet as `gamepc-rc`; bridge_monitor sidecar live |
| s30 | 2026-05-02 | 645e041..4c2514d | One-click gamepc_boot.ps1; cross-Claude learning-sync vision doc |
| s31 | 2026-05-02 | — | Phase 3 supervisor; dashboard OWNED fix; cron echo silenced |
| s32 | 2026-05-02 | c58e689, dc73303 | Live stat mirror; ally_comp overwrite fix |
| s33–s36 | 2026-05-02–03 | 0302fc7..0fcf102 | Action label decay fix; bridge `/messages` alias; arena advisor v1 |
| s37–s45 | 2026-05-03 | (DS Phase 1) | Daemon Slayer extractor; lolmath chunk topology; champion builds refresh |
| s46–s55 | 2026-05-03 | (DS Phase 2) | DS engine scaffolding; stat walk; on-hit framework; 40 items |
| s56–s65 | 2026-05-03 | (DS Phase 3) | DS Arena items; beam search; augment schema; 150+ items |
| s66–s75 | 2026-05-03–04 | (DS Phase 4) | DS spellblade/unique-passive; Arena mirror pass; 300+ items |
| s76–s80 | 2026-05-04 | (DS batch 20–24) | Rune writer shard3 fix; Bridge Watcher hardening; Bridge Pending UI |
| s81–s84 | 2026-05-04 | (DS batch 25–28) | Arena augment persistence; Meraki bulk switch; vision tracker polish |
| s85–s88 | 2026-05-04 | 0cecfa3..28d2a93 | DS batches 29–32; magic_amp schema; Rabadon's; 550 tests |
| s89 | 2026-05-04 | 0cecfa3 | DS batch 33: ability-burn promos, caster_bonus_hp, 367 tests |
| s90 | 2026-05-04 | 1bd105d, 6b04992 | DS batches 34–35: magic_amp_pct schema, dual-pen, spellblade |
| s91 | 2026-05-04 | 8f7811b, 8d208c3 | DS batches 36–37: TRUE damage type, Arena 443/447 sweeps, 428 tests |

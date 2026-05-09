# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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

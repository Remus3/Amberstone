# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s145 wrap — 2026-05-09 (ticket review + Riot API key policy reversal)

## What shipped
- **Reviewed 12 RC_TICKET_*.md from `Desktop/Tickets/`** (a "transfer plan" pack adapted from another project). All rejected for premise mismatches against RC's architecture (no flat-string coach state, no WebSocket LCU, no YOLO, no numpy, no async runtime, hardcoded minimap bbox, etc.). Per-ticket rationale lives in the session transcript.
- **Two real concerns surfaced** during review and were addressed via follow-up tickets:
  1. Hardcoded minimap bbox in `agents/supervisor.py:597` is brittle to HUD-scale changes / left-side toggle / non-1080p. → FU01.
  2. Full-team context enrichment (loss streak, mains, rank, mastery on locked champ) requires Riot Web API — LCU/scrapers can't reach it. → ADR-006 + FU02–FU04.
- **ADR-006 — Riot API key policy reversal** (`docs/adr/ADR-006-riot-api-key-policy.md`): Personal-tier key permitted for champ-select + post-game enrichment only. Single-user shape. Live in-game advisory remains LCU/LiveClient-only per Riot ToS. Memory `reference_no_riot_api_key.md` rewritten as superseded; MEMORY.md index updated.
- **4 follow-up tickets drafted** to `C:/Users/Administrator/Desktop/Tickets/`:
  - **FU01** minimap-locate — 3-path resolver (override → PersistedSettings → hardcoded fallback).
  - **FU02** `core/riot_api.py` + champ-select team-context — rate limiter + SQLite cache + progressive reveal + ranked-queue name obfuscation gate.
  - **FU03** `scripts/stage_riot_key.py` — clipboard helper for daily dev-key staging during the Personal-tier approval wait. Throwaway after approval.
  - **FU04** Riot Personal-tier API key application — research-grounded form-field walkthrough + ready-to-paste description + screenshot checklist + post-submit playbook.
- **Retired** `RC_FUTUREPROOFING_PLAN.md` from Desktop → `docs/_archive/RC_FUTUREPROOFING_PLAN_retired_2026-05-09.md` (with `.rgignore` restored). All 7 phases ✅.

## Key decisions
- **Personal tier, not Production.** Personal = non-expiring, no domain verification, same 20/s + 100/2min throughput as Dev. Production requires verified domain + ToS + Privacy Policy + hosted site — overkill for single-user.
- **Channel is a web form, not email.** developer.riotgames.com → Register Product → Personal. Reviews via portal Project Discussion tab. Realistic approval window: 2–6 weeks.
- **Web API key MUST NOT power live in-game advisory** per Riot policy. RC's live coaching loop runs on LCU + LiveClient + local vision and is unaffected by this ADR.
- **Cold all-10-player champ-select fan-out is ~80–150 calls** vs the 100/2min ceiling. Cache-immutable (Match-V5, Account-V1) + TTL (League-V4, Mastery) + progressive reveal over 90s window + priority queue (locked-champ mastery + rank fire first; mains + streak as bandwidth allows).

## What's next
- **Recommended:** FU02 panel stub (route + ESM panel + CSS scaffolding + `TeamContext` payload schema) → captures honest screenshots → submit FU04 application. The 2–6 week Riot clock dominates downstream timeline.
- **Alternate:** FU01 minimap-locate (S, fully independent, removes a silent-failure mode you've already hit).
- FU03 only useful during the dev-key bridge period — not yet needed.

---

# s144 wrap — 2026-05-09 (Phase 6 — bridge CLI consolidation)

## What shipped
- **`tools/bridge_cli.py`** (574 LOC) — single argparse-subparser entrypoint with subcommands `task | post-result | pull | fetch | ping | heartbeat | post`. SSL ctx, urllib helpers, processed-tasks file, last-seen file, vision-health probe, and Stop-hook transcript parsing — each previously duplicated 2–7× across the originals — now live exactly once.
- **7 thin shims** (16–26 LOC each, 139 LOC total) replace the 7 originals (772 LOC total). Each shim imports `bridge_cli.main` and prepends its subcommand to argv. Cron contracts preserved exactly — `bridge_pull_tasks.py --target legion` still emits `{now, target, count, tasks}`; the `/process-bridge-tasks` skill spec was untouched.
- **`BridgeMetrics` namespace** in `core/prom_metrics.py` — counters `posts_total{kind,target}`, `fetches_total{status}`, `pulls_total{target,status}`; gauge `pull_pending{target}`. Class-level Counter/Gauge so registration happens on import.
- **`tests/phase6_bridge_cli/test_bridge_cli.py`** (new) — 42 tests: argparse contracts, envelope shapes (task with/without prompt, post-result with --suggestions/--exit-code/--from-stdin/--reply-to=peer routing via core.bridge.send), pull filtering (target match, rc alias on legion, answered/processed exclusion, sort-oldest-first, fetch-error path), fetch hook (last-seen file write, peer filtering case-insensitive), Stop-hook transcript extraction, heartbeat `--once` mode, BridgeMetrics class registration, parametrized subprocess --help dispatch over each shim.
- **Live verified**: `py tools/bridge_pull_tasks.py --target legion` → exact pre-shim JSON shape; `py tools/bridge_ping.py` → POST + GET read-back + vision health all OK, exit 0. RC supervisor untouched (RC-BridgeWatcher daemon excluded from rewrite scope).
- **Plan + living docs synced**: `RC_FUTUREPROOFING_PLAN.md` Phase 6 → 🟢 done (1/1 session); Phase 4.2 tool-rewrite checkbox flipped (s144 Findings); BACKLOG's "Bridge contract v1" item closed; CLAUDE.md priority #6 ✅; ROADMAP table updated; ARCHITECTURE.md auto-regenerated. 476 CI-scoped tests pass (was 440 + 42 mine + drift). Ruff clean. archmap clean.
- **Cleaned leftovers**: deleted `web/js/main.js.bak` (Phase 3.1), 3 `dev-panel*.jpeg` screenshots, `_audit5_tasks.tmp.jsonl`, 0-byte `agentsstatetask_queue.jsonl`. Kept `.playwright-mcp/` cache (used by snapshot tests).

## Key decisions
- **Scope**: plan said "12 scripts → shims"; actual CLI surface is 7 small scripts. The 5 `bridge_watcher*.py` daemons (2486 LOC combined) are long-lived processes, not CLI commands — out of rewrite scope.
- **Argparse over Click**: zero new dep, equivalent readability via `add_subparsers(dest="cmd", required=True)`.
- **State consolidation deferred**: per-process `%LOCALAPPDATA%` files (`rc-bridge-tasks-processed.txt`, `rc-bridge-last-seen.txt`) stay where they are — the watcher daemons own the `bridge_*` files in `ops/runtime/`, and refactoring those touches frozen daemon internals.
- **`heartbeat --once`** added for testability — original was an unkillable `while True:`. Default behaviour unchanged.
- **Frozen-list unchanged**: `bridge_post_result.py` and `bridge_pull_tasks.py` keep `frozen=yes` headers. Future contract changes still require operator approval — but the implication now extends to `bridge_cli.py` since the shims delegate to it.

## Commits
- **75603fe** — `feat(bridge): Phase 6 — consolidate 7 small bridge CLIs into bridge_cli.py (s144)`
- **f764e35** — `docs: sync living docs — Phase 6 complete (s144)`
- Pushed: `87eacc2..f764e35  main -> main`

## What's next
- Futureproofing plan now has every actionable phase ✅. Open RC work is operational, not refactor: vision regions calibration (blocked on live game), gamepc_boot.ps1 hardening, Bridge Watcher acceptance-criteria (need 50+ real-traffic samples), DS calibration pipeline (rewind_history.db staleness).
- Watcher-daemon refactor (`bridge_watcher*.py` → envelope-aware, shared state, BridgeMetrics-instrumented) remains a future Phase if the watcher lifecycle ever opens up.

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

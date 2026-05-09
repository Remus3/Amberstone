# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s147 wrap — 2026-05-09 (FU04 close — Personal-tier API key issued same-day)

## What shipped
- **FU04 application submitted and approved same-day** on developer.riotgames.com (App ID 834837, well inside the documented 2–6 week window). Personal keys never expire → FU03 clipboard helper permanently superseded.
- **Evidence bundle** at `Desktop/FU04-Application-Evidence/` (4 PNGs + README; mirror at Game-PC `C:\fu04-evidence\`). Operator added 6 confirmation PNGs (1.PNG–6.PNG) post-approval.
- **Capture pipeline patched mid-session:** .NET `CopyFromScreen` raced against Edge's hardware compositor during view transitions, saving stale framebuffer content. Rewrote PS capture to use `PrintWindow` API with `PW_RENDERFULLCONTENT` flag — reads window surface directly, race-free. Helper at `C:\fu04-evidence\_capture_window.ps1`.
- **Caught + excluded** the dashboard's `LAST MATCH` view from evidence — it's actually the live in-game coaching surface (NEXT/RIGHT NOW/FIGHT/BASE/MAP STATE), exactly what Riot forbids in Web-API context. SESSION view used instead for scene 3.
- **HISTORY view scored the strongest evidence slot** (scene 4) — 2846 matches + literal "needs Riot key" UI label in SEASON STATS column.
- **Form-side overflow strategy:** Product Description ~1500 char limit hit; compliance/rate-math/endpoint list moved to "Anything Else" field. Both documented in bundle README.
- **Commit f1c8b10** `feat(adr): FU04 close — Personal-tier API key issued 2026-05-09 (s147)` — ADR-006 status; CLAUDE.md priorities (FU04 ✅, FU02 UNBLOCKED, FU03 🚫); `.gitignore` gains `API-Key-Riot.txt` (was missing — caught at FU04 close).

## Key decisions
- **Key file canonical, env optional, Legion-only.** `C:\Riot Commander\API-Key-Riot.txt` (42 bytes, no newline) mirrors `API-Key-Claude.txt`. Optional User-level `RIOT_API_KEY` env on Legion for parity. Game-PC has no Riot Web API code.
- **Scene 02 carries double duty:** champ-select capture shows existing build chooser (top) AND FU02 team-context panel (bottom) — same cs-overlay surface, both annotated in README.

## What's next
- **FU02 runtime fan-out** is the immediate next session: `core/riot_api.py` (rate limiter at 20/s + 100/2min, SQLite cache at `data/riot_api_cache.db`, 4 endpoint wrappers — Account-V1 / Match-V5 / League-V4 / Champion-Mastery-V4), the cache-then-fan-out pump on `POST /api/team-context/refresh`, progressive reveal over the ~90s champ-select window. Ticket at `Desktop/Tickets/RC_TICKET_FU02_riot_api_module.md`.
- **FU01 minimap-locate** is still independent and ready anytime.
- Don't redo: FU03 clipboard helper is *permanently* superseded. Don't draft / don't ship.

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

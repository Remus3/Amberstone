# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s148 wrap — 2026-05-09 (FU02 fan-out shipped + TFT match-history filter)

## What shipped
- **FU02 main work** (commit `dfa13f0`): `core/riot_api.py` (240 LOC) + `core/riot_api_cache.py` (260 LOC) + fan-out wired into `dashboard/routes_team_context.py`. Personal-tier key resolver, dual token bucket (20/s + 100/120s + 429 cooldown), SQLite cache (immutable for match data + Account, 5-min TTL for ranks + mastery), six endpoint wrappers (Account-V1, Match-V5 ids/detail/timeline, League-V4, Mastery-V4), priority-1 (rank+mastery) + priority-2 (mains/winrate/streak) fan-out via daemon thread, progressive reveal via `_update_entry` + `_mark_complete`, swappable `_FANOUT_DISPATCHER` so tests stub it out, backend ranked-name-blanking (queue 420/440) defense-in-depth.
- **63 new tests** across `test_riot_api.py`, `test_riot_api_cache.py`, `test_fanout.py` — rate-limiter dual-window math, cache miss/hit/expiry/concurrency, all six endpoints with mocked HTTP, key-resolver failure paths, fan-out worker progressive reveal + per-entry failure isolation, ranked-queue gate, default-dispatcher API-key gate. **Total suite: 565 pass** (was 496). Ruff clean.
- **Live-fired** the worker against the real Personal-tier key with fake PUUIDs — bucket held, `partial` flipped to `false` after deadline, `/metrics` exposes `rc_riot_api_calls_total{endpoint,outcome}` + bucket gauges.
- **Dark Star Vertical TFT filter** (commit `b12c71c`): `dashboard/builders.py` now excludes `mode='TFT'` from the Recent 5 + This Week + today-aggregate queries on the home view, AND from the shared `_load_match_rows` loader (cascades to History view sessions + session summary). Underlying rows stay in `match_history.db` for any TFT-aware consumer.

## Key decisions
- **Fan-out dispatcher is pluggable.** Module-level `_FANOUT_DISPATCHER` callable in `routes_team_context.py`; default checks `riot_api.is_configured()` and spawns a daemon thread; tests overwrite it with a recorder. Avoided monkey-patching `core.riot_api` internals from the test layer.
- **TFT filter is read-side, not data-deletion.** `match_history.db` rows untouched. Per memory `feedback_field_remove_visual_only.md`: "remove a field" means visual; data plumbing stays alive.
- **SQLite write-serialization.** Switched to `RLock` and serialized `set_immutable`/`set_ttl` via the instance lock — Windows + WAL + per-call connections + tight thread contention produced occasional "database is locked" errors. Cache is rate-limiter-bounded so write parallelism cost is trivial.
- **Champion-name → ID lookup** via DDragon `champion.json` glob, lazy-loaded in `routes_team_context._champ_name_to_id`. Soft-fail: missing IDs just skip the mastery call for that entry.

## What's next
- **FU01 minimap-locate** — still independent + ready anytime. 3-path resolver (override → PersistedSettings → hardcoded fallback) for `agents/supervisor.py:597`. Ticket at `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- **LCU agent extension** to actually POST to `/api/team-context/refresh` on `ChampSelect` transition. Currently Game-PC's `tools/gamepc_lcu_agent.py` collects myTeam/theirTeam but doesn't forward to the team-context endpoint — was deliberately deferred this session (panel + fan-out are wired; agent hookup is the last mile). Not in CLAUDE.md priorities yet.
- **Live verification with real PUUIDs** — needs an actual ChampSelect or a manual roster post with real `puuid` strings to confirm rank/mastery/mains all populate end-to-end against Riot's API.
- **Don't redo:** FU02 runtime fan-out is fully shipped. The panel stub from s146 is now backed by real data. Don't re-ship.

## Blockers
- None. FU01 is unblocked; LCU agent extension is unblocked.

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

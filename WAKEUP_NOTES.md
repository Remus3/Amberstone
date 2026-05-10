# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s149 wrap — 2026-05-09 (LCU agent → /api/team-context/refresh wiring)

## What shipped
- **FU02 last mile** (commit `e7b5af1`): Game-PC `tools/gamepc_lcu_agent.py` now POSTs the 10-player roster (with PUUIDs) to Legion `:8888/api/team-context/refresh` on ChampSelect entry + on lock/swap. Bearer auth via `bridge_shared_secret`. +238 LOC, no removals.
- **Bridge-secret resolver**: `RC_BRIDGE_SECRET` env → `bridge_secret.txt` → `local_paths.json{bridge_shared_secret}` → `""`. Empty = warn-once + skip POST (no historical default).
- **Champion-id → name cache**: lazy-loaded once per agent boot from LCU's `/lol-game-data/assets/v1/champion-summary.json`. Unknown ids translate to `""` so the dashboard renders blank rather than numeric garbage.
- **Edge-trigger semantics**: POSTs on (a) entering ChampSelect, (b) `(cellId, championId)` signature change. Rate-limited to `TEAM_CONTEXT_REPOST_S=3.0s` between re-fires; resets state on leave so next CS always re-fires the initial POST. Failure isolated from `/upload-lcu` cadence.
- **30 new tests** in `tests/fu02_team_context/test_lcu_agent_refresh.py`: resolver priority, pick-signature stability, body translation, POST helper, edge-trigger rate-limit + leave-reset + failure-doesn't-latch. **Total suite: 595 pass** (was 565). Ruff clean.
- **Game-PC deployed live**: `bridge_secret.txt` written via gamepc MCP, agent fetched from `:8888/agent/`, RC-LCU restarted (PID 16080). Resolver self-test confirmed `secret_len=43 first4=at_Y last2=WQ`. `/api/team-context` returns `null` cold, ready to fill.
- **Docs sync**: `tools/GAMEPC_CLAUDE.md` now documents the new POST + the bridge-secret deploy steps.

## Key decisions
- **Stdlib-only on Game-PC.** No `from core import bridge` — agent runs from `C:\RC-Agent\` where the project tree isn't importable. File-based resolver mirrors the pattern in `bridge_watcher_health_publisher.py:_resolve_token`.
- **Send display-name strings, not numeric ids.** Route's `_skeleton_entry` stores `locked_champion: str` for direct dashboard render; route's `_champ_name_to_id()` reverses via DDragon for mastery. Sticking with the FU02-shipped contract avoided a server-side schema change.
- **Edge-fire from `_state_push_loop`, not a new thread.** POST is fire-and-forget over Tailnet (~200ms) and only runs once per change. Spawning a fourth thread for one-shot POSTs was overkill.
- **`puuid` added to `_team_picks()` snapshot** — also makes /upload-lcu consumers richer with no new endpoint shape needed.

## What's next
- **Live verification** — waiting on next CS pop. Watch for `[team-context] refresh OK queue=… roster=…` in agent stdout (hidden — easier probe: `curl -k https://127.0.0.1:8888/api/team-context | py -m json.tool`).
- **FU01 minimap-locate** — still independent. 3-path resolver for `agents/supervisor.py:597`. Ticket at `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- **Don't redo:** FU02 wiring is shipped end-to-end (panel + fan-out + LCU agent). Bridge secret is on Game-PC (`C:\RC-Agent\bridge_secret.txt`). Agent (PID 16080) is healthy and heartbeating.

## Blockers
- None. Verification is observational — picks itself up on the next champ-select.

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

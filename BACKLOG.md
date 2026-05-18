# Riot Commander — Backlog

_Aspirational / longer-term items. Extracted from ROADMAP.md "Future" section 2026-05-08._
_When an item moves to active work, migrate it to ROADMAP.md "Open items"._

---

## Bridge Watcher hardening

- **Per-call cost histogram**: track median/p95 cost per lane in Prometheus; alert if p95 doubles week-over-week.
- **`bridge_watcher_install.ps1` self-update**: detect stale local copy and prompt to re-pull when a new watcher ships.
- ~~**Bridge contract v1**~~: shipped — `core/bridge_envelope.py` (Phase 4.2, s129) defines `body_path` / `claimed_by` / `ttl_at` / `suggestions`; `tools/bridge_cli.py` (Phase 6, s144) consolidates the 7 small CLIs over it. Watcher daemon refactor (bigger envelope-aware rewrite) deferred separately.

## Cross-Claude infrastructure

- **Cross-Claude lessons Phase 4**: confidence scoring, symmetry check, auto-revert (Phases 1–3 shipped 2026-05-06).
- **Bridge MCP tool wrapper**: REPL-style access to `/api/bridge` query params from any Claude session.

## Coaching depth

- **rewind_history.db SR records with game_id**: post-live SR game; wired in code (d66d14b) but blocked on new records.
- **LCU deeper integration**: Pengu Loader Discord/GitHub research for endpoints RC doesn't use yet (richer pre/post-game data). Research-first, no code scheduled. **Reference catalog identified 2026-05-17:** `KebsCS/lcu-and-riotclient-api` (lcu.kebs.dev) is a current (client 26.05), exhaustive (2839 ops) endpoint map — the authoritative source for the richer endpoints (mastery-by-puuid, `match-history .../games/{gameId}` + `game-timelines`, `loadouts/v4`, `signed-ranked-stats`). No LICENSE → reference only, don't vendor; optionally diff its `data.json` per patch. This supersedes the Discord crawl as the primary endpoint-discovery method.
- **Interactive Item Shaper (post-DS-100%)** _(noted s214, 2026-05-15)_: final-polish layer on top of the per-archetype scorers. UI exposes 3 modifiers — `DAMAGE` / `SURVIVABILITY` / `UTILITY` — each with a +/- nudge that reshapes the active scorer's weighting on the fly (e.g. Bruiser α=0.65/β=0.35 default → DAMAGE+ pushes toward α=0.80, SURVIVABILITY+ pushes toward α=0.45). The shaper reads + writes the running coach's archetype weights without persisting them; on match end the weights snap back to the archetype default. Intended as a real-time "I'm in a fight-heavy comp, push damage" / "they're snowballing, hold survivability" hint loop. **Block on**: DS engine reaches 100% champion coverage so the weight knobs sit on a complete underlying scorer surface before exposing them to operator-driven tuning.

## Platform / observability

- **Memory watchdog remediation wiring**: `ResourceManager` logs at 500 MB but doesn't trigger a coach restart. Wire to `app/_remediation.py` (frozen-file, needs owner approval).
- **Streaming vision**: delta-encoded frames instead of full JPEG every 2s. ~5× bandwidth reduction.
- **Mobile-native dashboard**: current PWA adds ~2s touch latency. Native iOS/Android would reduce that.

## Data pipeline

- **TFT vision relay frame dimensions**: lock OCR pipeline to 1920×1080 once validated (pair with NOTE-025 calibration).
- ~~**Adversarial sim fixtures**~~: shipped s173.1 (`38ca915`) — 4 fixtures + 2 tests under `tests/snapshot_panels/`; uncovered s151 `gameTime` ref-error during initial run.

## Developer experience

- **Type hints + ruff one-time pass**: codebase mixes annotated/unannotated. `ruff --fix` + annotations on public coach API.
- ~~**Test fixtures for adversarial paths**~~: shipped s173.1 (`38ca915`) — see Data pipeline entry above; this was a duplicate of the same item.
- ~~**Console-pipe localStorage flush failure-recovery loop**~~: shipped s173.1 (`51e0da7`) — `flushQueueAfterSuccess` now preserves entries on replay failure (per-entry removal via `_dropQueuedEntry`).

## Reliability / hardening

- **MCP server hung-tool watchdog**: `concurrent.futures` watchdog at the MCP server tier. Currently `run_powershell` has subprocess timeout; broader dispatch is uncovered.
- ~~**`MatchDB` thread-safety validation**~~: moot — `core/match_db.py` was refactored 2026-04-28 (audit proposal 1.2) from RLock to WAL + per-thread connections. FIX-021 lock no longer exists; serialization is now SQLite WAL.
- **`/api/analyze` streaming response**: current 30s timeout fine for ARAM (sub-second); may need SSE if full-mode analyses scale.

## Speculative

- **`.rofl` file replay coaching**: `coaches/replay_coach.py` shipped lite version (rewind_history.db). Full `.rofl` parsing **confirmed dead-end 2026-05-17** — fraxiinus `roflxd` (the maintained .ROFL parser family) shows a parsed .ROFL exposes only end-of-game aggregate `PlayerStatistics[]`, a strict *subset* of RC's existing Match-V5 SQLite; the in-game packet stream (frame positions / ability casts / event stream a replay-review page would want) is Riot-obfuscated and unparseable on the current patch. The planned s220 **S5 Replay page stays Match-V5-timeline-driven**; do not re-pitch .rofl parsing.
- **PyInstaller packaging**: `riot-commander.spec` exists as opt-in starter. Not prioritized.
- **OBS publisher activation**: `T3 #11` shipped (264 LOC, opt-in); not wired to any active workflow.

## Research / inspiration (s219, 2026-05-15)

- **coachless.gg teardown**: analyze https://coachless.gg/ — both the site and its app — for build patterns, post-game analysis UX, and any insight worth lifting into the Post Game Review or future Deep Review page. Operator can re-subscribe for a month to access the locked content if a deeper teardown is warranted.
- **Local DDragon mirror auto-refresh**: download every icon path (champions, items, summoner spells, runes, augments, profile-icons) into `/data/ddragon/<patch>/` on each patch flip + auto-update when DDragon ships new assets mid-patch. Today the mirror lags at 16.8.1 while live patch is 16.10.1 — Post Game Review pinned to 16.8.1 + CDN fallback as workaround (s219). A real mirror keeper would be one cron + a manifest diff.
- ~~**Pengu.lol MCP — adapt to RC**~~: **rejected 2026-05-17.** Evaluated `rumi-chan/league-client-mcp` (the MIT candidate): it is a thin generic `fetch()` passthrough that *requires* Pengu Loader injected + a live client running just to make an LCU call, and inherits the exact same LCU surface RC already hits. Strictly worse than RC's out-of-process Python lockfile client (no Pengu/live-game dependency, more robust). Exposes no richer endpoints and no augment access. Do not re-adopt or re-research.
- **Pengu.lol Discord crawl** _(demoted 2026-05-17)_: the static KebsCS catalog now covers released endpoint knowledge; keep this only as a *secondary* sweep for unreleased / in-progress community work (replay-timeline access, novel Mayhem detection). Research-only; surface findings before scheduling code work. **One concrete lift already surfaced** (Mayhem-Doctor, 2026-05-17): the static asset `/lol-game-data/assets/v1/cherry-augments.json` resolves augment id → name/icon/rarity (`kSilver/kGold/kPrismatic`) — authoritative augment table without screen-OCR for *naming* (OCR still needed for *which* augments are offered live). Independently re-confirmed: zero `/lol-cherry/*` and zero `/lol-game-augments/*` live endpoints exist (KebsCS full 26.05 catalog) — augment-OCR stays; do not re-pitch an LCU augment API.

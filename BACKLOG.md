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
- **LCU deeper integration**: Pengu Loader Discord/GitHub research for endpoints RC doesn't use yet (richer pre/post-game data). Research-first, no code scheduled.

## Platform / observability

- **Memory watchdog remediation wiring**: `ResourceManager` logs at 500 MB but doesn't trigger a coach restart. Wire to `app/_remediation.py` (frozen-file, needs owner approval).
- **Streaming vision**: delta-encoded frames instead of full JPEG every 2s. ~5× bandwidth reduction.
- **Mobile-native dashboard**: current PWA adds ~2s touch latency. Native iOS/Android would reduce that.

## Data pipeline

- **TFT vision relay frame dimensions**: lock OCR pipeline to 1920×1080 once validated (pair with NOTE-025 calibration).
- **Adversarial sim fixtures**: add corrupted JSON / partial state / mode-transition fixtures to harden dashboard renderer (currently 26 happy-path fixtures).

## Developer experience

- **Type hints + ruff one-time pass**: codebase mixes annotated/unannotated. `ruff --fix` + annotations on public coach API.
- **Test fixtures for adversarial paths**: partial state, corrupted JSON, mode transitions.
- **Console-pipe localStorage flush failure-recovery loop**: currently fire-and-forget (queued errors replay on next post but no retry loop).

## Reliability / hardening

- **MCP server hung-tool watchdog**: `concurrent.futures` watchdog at the MCP server tier. Currently `run_powershell` has subprocess timeout; broader dispatch is uncovered.
- **`MatchDB` thread-safety validation**: lock added defensively (FIX-021); validate under parallel-writer load if introduced.
- **`/api/analyze` streaming response**: current 30s timeout fine for ARAM (sub-second); may need SSE if full-mode analyses scale.

## Speculative

- **`.rofl` file replay coaching**: `coaches/replay_coach.py` shipped lite version (rewind_history.db). Full `.rofl` parsing deferred (encrypted, non-public format).
- **PyInstaller packaging**: `riot-commander.spec` exists as opt-in starter. Not prioritized.
- **OBS publisher activation**: `T3 #11` shipped (264 LOC, opt-in); not wired to any active workflow.

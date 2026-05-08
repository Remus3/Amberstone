# Riot Commander — Agent Context

Live League / TFT coaching dashboard. Reads Riot Live Client API, calls Claude Haiku for coaching and Sonnet for vision, writes JSON to `data/`, serves `:8888` HTTPS dashboard on Game-PC's secondary display. RC is tkinter-free; Daemon Slayer (`:8893`) computes real DPS math per champion.

> **Living docs (read at session start):** `docs/ARCHITECTURE.md` · `docs/OPERATIONS.md` · `docs/BRIDGE.md` · `ROADMAP.md`
> **Deep references:** `docs/DAEMON_SLAYER.md` (DS engine · 547 items · ENGINE_VERSION 0.60.0) · `docs/AGENTS.md` (Phase 3 framework) · `BACKLOG.md` (aspirational)
> **Dated artifacts** in `docs/_archive/` (excluded from ripgrep searches).

## Topology

| Machine | Tailnet / IP | LAN IP | Role |
|---|---|---|---|
| **Legion** | `legion-rc` / `100.70.22.55` | `192.168.8.230` | Runs RC, supervisor, vision server, web dashboard |
| **Game-PC** | `gamepc-rc` / `100.95.66.128` | `192.168.8.237` | Runs League; Edge fullscreen on secondary display (1920×1280, 100% scale) |
| **Peer** | `peer-host` / `<peer-tailnet-ip>` | — | Cross-Claude peer; RC↔Peer bridge |

All three in tailnet `tailc150de.ts.net`. Prefer tailnet hostnames. Vision runs in-process at `127.0.0.1:8889`.

## Paths

- Project root: `C:\Riot Commander\`
- Python: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
- API key: `C:\Riot Commander\API-Key-Claude.txt` (gitignored)
- Health: `C:\Riot Commander\ops\runtime\health.json`
- Logs: `C:\Riot Commander\logs\YYYY-MM-DD.log`

## Hard rules

- **Always `py_compile` before restart.** Syntax errors crash silently under `pythonw.exe`.
- **Atomic writes only:** `tmp.write_text(...); tmp.replace(target)`. Overlays poll mid-write.
- **Never `Stop-Process`.** Hangs MCP pipe. Use `taskkill /F /PID`.
- **Restart via `restart_trigger.txt`** (write any content; supervisor clears + restarts within ~5s).
- **`SCRIPT_DIR` in `app/__init__.py` MUST be `Path(__file__).parent.parent`** (package layout).
- **State assumptions explicitly before coding.**
- **Frozen files** (do not modify without explicit user approval):
  `main.py`, `core/log_setup.py`, `core/moon_proxy.py`, `lcu/lcu_client.py`,
  `core/game_snapshot.py`, `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`,
  `app/__init__.py`, `app/_loop.py`, `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`,
  `tools/bridge_watcher_classify.py`,
  `tools/bridge_watcher_actions.py`, `tools/bridge_watcher_action_prompt.md`,
  `tools/bridge_watcher_history.py`, `tools/bridge_watcher_install.ps1`,
  `tools/bridge_watcher_hook.ps1`, `tools/bridge_watcher_config.json`,
  `tools/bridge_post_result.py`, `tools/bridge_pull_tasks.py`,
  `tools/process-bridge-tasks.md`, `tools/diagnose.md`, `tools/caveman.md`,
  `dashboard/routes_bridge_pending.py`, `ops/RC-BridgeWatcher.xml`.

## Restart workflow

```
echo restart > restart_trigger.txt
```
Verify: read `ops/runtime/health.json`, confirm new `pid`, `alive=true`, `last_reload_ok=true`.
Hard fallback: `taskkill /F /PID <pid>` then `restart.bat`.

## Session workflow

Scoped sessions — each focused task is one session.
- **End:** commit + update `WAKEUP_NOTES.md` (keep last 2–3 sessions at full fidelity; archive older to `docs/history_notes.md`) + push.
- **Start:** `/clear`, bootstrap from CLAUDE.md + MEMORY.md + git log + WAKEUP_NOTES + `docs/ARCHITECTURE.md` + `ROADMAP.md` (all 4 under 800 lines total).
- `/clear` between Tier items, between coding/reviewing modes, between focus-area switches.

## Web dashboard

`web_dashboard.py` at `:8888` HTTPS. Key endpoints: `/`, `/api/state`, `/api/health/all`, `/api/bridge/pending`, `/api/input`, `/api/command`, `/api/ds-preview`, `/metrics`. Viewed in Edge fullscreen on Game-PC secondary (1920×1280, 100% scale). Cert via `tools/regen_rc_cert.ps1`. Each machine has its own Anthropic API key (`riot-commander-legion`, `riot-commander-gamepc`, `riot-commander-peer`).

## Scheduled tasks (Legion)

Key: `RC-Supervisor` (logon, Administrator, HIGHEST) · `RC-VisionServer` (startup, SYSTEM, HIGHEST) · `RC-BridgeWatcher` (logon, daemon). Full list + Game-PC tasks: `docs/OPERATIONS.md`.

## Vision pipeline

Game-PC `gamepc_screen_agent.py` POSTs frames every 2s to `:8889/upload-frame`. Coaches call `modes.shared_vision._capture_screen()` → GET `:8889/latest-frame`. **`_run_vision()` gates on `_fetch_game_data() is not None`** — vision never fires during lobby/idle. Tiered: OCR first, Sonnet escalation for misses. Calibrate `data/vision_regions.json` to expand OCR coverage.

## Mode detection

`game_reader.py._process_game()` → `core/game_snapshot.py` → mode strings. ARAM Mayhem (`KIWI`) → `MODE_ARAM`.

## Where to find current state

- Live PID + mode + health: `ops/runtime/health.json`
- Current game state: `data/{aram,arena,brawl,tft}_coaching_data.json`
- Recent activity: `logs/YYYY-MM-DD.log`
- Architecture / module map: `docs/ARCHITECTURE.md`
- Ops commands + restart: `docs/OPERATIONS.md`
- Bridge wire format + watcher: `docs/BRIDGE.md`
- Open work: `ROADMAP.md` · Aspirational: `BACKLOG.md` · History: `docs/_archive/CHANGELOG.md`

## Useful commands

Full reference: `docs/OPERATIONS.md`. Quick-start:
```
python -c "import json; print(json.dumps(json.loads(open(r'ops/runtime/health.json').read()), indent=2))"
echo restart > restart_trigger.txt
curl -k https://127.0.0.1:8888/api/health/all
```

## Memory frontmatter — cross-project sync fields

Standard memory files carry `name`, `description`, `type`. Two optional fields
are valid for memories that should ride the RC↔Peer bridge (Phase 1 schema,
`docs io RC peer/RC_PHASE1_LESSON_SCHEMA_2026-05-02.md`):

```yaml
cross_project: true          # opt-in; default false. Only feedback/reference/project eligible.
applies_when: "<trigger>"    # required when cross_project=true; free-form grep-able phrase
does_not_apply_when:         # optional list; receiver skips if any entry matches local context
  - "<neg-trigger>"
```

`type: user` memories are never eligible. Default is OFF — author decides at write-time.
False-negatives are recoverable (edit frontmatter later); false-positives are bridge spam.

## Testing Discipline

Always run the full test suite after schema changes, engine version bumps, or item-effect additions. Avoid data-fragile cross-item comparison assertions; prefer assertions on computed quantities. When stubbing methods accessed via class, wrap with `@staticmethod` correctly.

## Windows Environment Notes

Claude Desktop on Windows may be installed via the Microsoft Store (check `%LOCALAPPDATA%\Packages`) in addition to standard install paths. Use `pythonw.exe` (not `python.exe`) for background daemons to avoid flashing console windows.

## Daemon Slayer Batch Workflow

When continuing Daemon Slayer work: pick the next batch from ROADMAP, implement schema/engine changes, add tests (target green before commit), bump engine version, commit + push, verify live, update hand-off notes.

## Session Wrap-up

When invoked with `/done` or asked to wrap a session: (1) audit pending changes, (2) commit and push, (3) update ROADMAP/CLAUDE/README if relevant, (4) process lessons/WAKEUP_NOTES, (5) run bridge probe, (6) print final banner. Run independent steps in parallel.

## Active priorities

1. 🟠 Phase 1.1 doc architecture — in progress (this session): _archive + ARCHITECTURE.md + OPERATIONS.md + BRIDGE.md + ROADMAP split.
2. 🟡 Vision regions calibration — tune `data/vision_regions.json` bboxes; OCR canary gates Sonnet. Blocked on live game.
3. 🟡 DS calibration pipeline — game_id wired (d66d14b); future SR records carry game_id. Blocked on rewind_history.db staleness (last entry Dec 2025).
4. 🟡 TFT 17.3 — due ~2026-05-12. Same process as 17.2.
5. 🟡 gamepc_boot.ps1 hardening — add `RC-WatcherHealthPublisher-GamePC` + `RC-BridgeWatcher-GamePC` to idempotent start sequence.
6. 🟡 Bridge Watcher acceptance-criteria — need 50+ real-traffic samples (watch `auto_ok_since_boot` vs `auto_err_since_boot`).

Full open work + future: `ROADMAP.md` + `BACKLOG.md`. Completed work: `docs/_archive/CHANGELOG.md`.

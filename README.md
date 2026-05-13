# Riot Commander

Live coaching overlay + second-screen dashboard for League of Legends and Teamfight Tactics. Reads Riot's local Live Client API, runs tiered vision (Tesseract OCR + Claude Sonnet) and LLM coaching (Claude Haiku), and serves an HTTPS dashboard viewed in Chrome on Game-PC's secondary display.

Personal project. Private repo. Not packaged for general use. Codebase has been through a multi-tier engineering audit (Tier 1–3 complete, Tier 4 polish complete, Tier 2 #9 deliberately deferred); see [Engineering](#engineering) for the audit ledger.

---

## What it does

- **Real-time coaching** — Claude Haiku for fast in-game tips, Claude Sonnet for screenshot-based vision reasoning, Tesseract OCR for cheap region reads, fast-path heuristics from the Live Client snapshot when an LLM call would be redundant
- **Daemon Slayer build engine** — local HTTP service on `:8893`; no runtime API cost. Computes real damage-per-second AND Effective HP for any champion×item×target combination. **DDragon purchasable coverage complete: 547 items** (SR, ARAM, Arena, Brawl) with **1151 passing tests** (ENGINE_VERSION 0.65.0). Models armor/MR penetration, on-hit effects, spellblade procs, true damage, Giant Slayer scaling, AP amps, damage amps, armor/MR shred, caster-HP-scaled amps, full Arena item mirror pool, and dead-unique candidate filtering (Trinity→ER, Sterak's→Maw, Sunfire→Hollow Radiance no longer ranked). s174 adds the Tank EHP scorer (`/ehp`, `/rank-tank` routes); s175 adds the Bruiser hybrid scorer (`/hybrid`, `/rank-bruiser` routes) composing dps + ehp via per-champion (α,β) weights from `archetype_weights.json`; s176 ships the CS archetype-picker UI in the champ-select view + `GET/POST /api/cs-archetype-pick` REST endpoint + `rank_for_primary_archetype()` dispatcher that routes carry/bruiser/tank to their scorers (mage/assassin/enchanter fall back to ds.dps with `fell_back=True` until Phases 4-6). s177 ships Phase 4a champion ability ingest — `agents/daemon_slayer/abilities.py` + `tools/daemon_slayer_abilities_extract.py` consuming Meraki bulk; 171/172 champions / 927 ability forms with 98.4% ok / 99.3% parsed; data-only this phase, Phase 4b adds the formula evaluator. Two of six archetype scorers shipped; the third UI layer lets the operator pick; Phase 4a primes the ground for the Mage scorer. All 4 coaches (ARAM, Arena, Brawl, SR) use DS-before-Haiku — picks injected in user turn before LLM call
- **Decision detector** — `core/decision_detector.py` watches game state and surfaces "decision moments" (dragon up with N enemies missing, baron contest, item spike) with a contest / give / skip choice tag; Recent Coach Calls history is on a dedicated `#coach-calls` sub-page
- **Web dashboard** (`:8888`, HTTPS, mkcert-signed) — home / lobby / last-match / session / history / replay / loadouts / settings / diagnostics / coach-calls views, viewed in Chrome on Game-PC's secondary display. Design baseline is standard 1920×1080 with Chrome chrome present (titlebar + URL bar + bookmarks bar); the layout flex-grows into any extra vertical space when F11 fullscreen is used. Server-Sent Events on `/api/state-stream` for idle efficiency
- **Champion-select build chooser** — surfaces preferred keystone + items per matchup from local match data; writes runes via the LCU. DS Engine build preview panel (`#cs-ds-block`, `/api/ds-preview`) shows DPS-ranked item tiles with +Ndps tooltips before the game starts. Pick & Ban Recommendations panel (`/api/champ-select/pickban-recs`) overlays operator-aware performance row + ban suggestions from `rewind_history.db` per role
- **Match history** — local SQLite (`data/rewind_history.db`, 2,846 matches / 29,064 participants / 645,982 timeline frames) is the primary data source; no Riot API key required, no rate limits
- **TFT coaching** — separate worker for autobattler mode; vision migrated to the same screen-relay path as League coaches in 2026-04
- **Prometheus instrumentation** — `/metrics` (text/plain exposition, zero-dep) for coach calls/tokens/USD by model+purpose, vision token allocation, latency histograms, scrape-time gauges for liveness and bridge freshness
- **OBS publisher** (opt-in) — daemon thread pushes a one-line state summary to an OBS Text source via OBS-WS v5; resilient to OBS being down
- **PyInstaller spec** (opt-in) — frozen-bundle starter for a self-contained dist/ build
- **Cross-Claude infrastructure** — three Claude Code instances on three machines (Legion, Game-PC, Peer) coordinate over a Tailscale-secured HTTPS bridge with a shared bearer token; zero-cost bridge daemons (`RC-BridgeDaemon` on Game-PC, `peer_bridge_daemon.py` on Peer) poll every 30 s and only invoke Claude when tasks are pending — no idle API cost

---

## Topology

Three machines on tailnet `tailc150de.ts.net` under `<operator-email>`. **Tailnet hostnames are primary**; LAN IPs are kept as fallback for legacy probes and intra-LAN paths.

| Machine | Tailnet | LAN | Display | Role |
|---|---|---|---|---|
| **Legion** | `legion-rc` / `100.70.22.55` | `192.168.8.230` | 1 monitor | RC main process, web dashboard `:8888`, vision server `:8889`, supervisor, MCP client to Game-PC |
| **Game-PC** | `gamepc-rc` / `100.95.66.128` | `192.168.8.237` | 2 — primary TV (the game) + secondary iPad-as-monitor over Duet (1920×1280 native panel, 100% OS scale, no touch, no apps) | League client + Live Client API on `:2999`; runs five relay agents (screen, LCU, Live-Client, MCP server, hotkey listener) that feed Legion. Chrome on the secondary display showing the dashboard at `https://legion-rc:8888/` |
| **Peer** | `peer-host` / `<peer-tailnet-ip>` | — | — | Separate Peer-VIP project on a different machine and network. Cross-Claude peer; reachable via `core.bridge.send()` |

mkcert-signed cert SAN covers all of `legion-rc`, `100.70.22.55`, `legion-rc.tailc150de.ts.net`, `192.168.8.230`, `localhost`, `127.0.0.1` — no `-SkipCertificateCheck` workarounds needed from any tailnet node. Refresh with `tools/regen_rc_cert.ps1`.

---

## Architecture

```
main.py                   entry: logging, key, DevRuntime, MetricsCache, web_dashboard, OverlayApp
overlay.py                shim → app/__init__.py
app/                      OverlayApp orchestrator (Tk-free, asyncio-native since T2 #8)
  __init__.py             ~300L orchestrator
  _loop.py                AppLoop — asyncio scheduler + ensure_loop()/get_loop() singleton
  _health_monitor.py      heartbeat
  _remediation.py         restart hooks, panel rebuild stubs
  _state_authority.py     state envelope + win-pct
  _overlay_manager.py     dashboard-only shell (50L; Tk windows removed in T2 #6)
  _game_lifecycle.py      game start/end, worker dispatch
coaches/                  BaseCoach (async _poll_loop + _vision_loop) + per-mode variants
  _base_coach.py          shared poll/vision loops, debounce, hotkey reg
modes/                    shared_vision (relay screen-grab client used by coaches)
core/                     game_snapshot, sr_aram_worker, tft_worker, theme, hotkeys, log_setup,
                          metrics_cache, prom_metrics (zero-dep Prometheus exposition),
                          obs_publisher (opt-in OBS-WS push), decision_detector, vision_tracker,
                          bridge (RC↔Peer outbound + config), bridge_monitor (auto-pong sidecar)
tft/                      TFT engine (state_reader, live_analysis, coach_engine, data, pbe)
ops/                      rc_supervisor, rc_self_monitor, rc_dev_runtime, runtime/health.json,
                          tls/ (mkcert leaf + key), local_paths.json (gitignored bridge config)
lcu/                      LCU client, auto-accept, rune writer, postgame collector (all async)
agents/                   Phase 3 framework: supervisor.py (:8890/:8891) + Agents 0-7 + Daemon Slayer
data/                     coaching artifacts (atomic-written, polled by dashboard)
web_dashboard.py          145L barrel → dashboard/ package
dashboard/                _state_builder, _champ_select, _liveclient, _writers, _diagnostics,
                          _bridge_log, _dispatch, _handler, server, routes_*, _static
moon_vision_server.py     21-LOC entrypoint shim — delegates to vision_server.main
vision_server/            :8889 vision server pkg (frame cache + Sonnet vision + Tesseract OCR)
tools/                    Game-PC agents, cross-Claude bridge tooling, boot scripts, cert regen
scripts/                  data pipeline (patch-day refreshes)
_archive/                 dated quarantine of removed code (e.g. ui/ package, modes overlays)
```

See [`CLAUDE.md`](./CLAUDE.md) for live operational context (paths, hard rules, restart workflow, frozen file list, where the truth lives).

---

## Coaching pipeline

Frames are captured on Game-PC (`tools/gamepc_screen_agent.py`, PIL `ImageGrab` every 2s) and POSTed to Legion's vision server with a shared `X-RC-Token`. Coaches on Legion fetch the latest cached frame and route it by cost tier:

1. **Live Client snapshot** — fast-path. Many fields (gold, KDA, level) come from `:2999/liveclientdata/allgamedata` on Game-PC and travel as JSON; no vision call needed.
2. **Tesseract OCR** — region-bound, deterministic. Default regions in `data/vision_regions.json`; runtime crop preview at `/api/ocr-crop?field=NAME`.
3. **Claude Sonnet** — full-frame visual reasoning when a region read isn't enough (wave state, fog-of-war inference, item-spike timing, end-screen reads).
4. **Daemon Slayer** — runs before Haiku on ARAM (and in-progress for other modes): `rank_for(champion, level, owned_items, mode)` returns DPS-ranked next-item candidates (`delta_dps`, `gold`). These are injected into the user turn so Haiku reasons about real math, not static tier lists. ARAM system prompt was trimmed 37% after removing pre-DS hardcoded item rules that DS now covers.
5. **Claude Haiku** — final-mile coaching tips. Streamed onto the dashboard with `kind=task` decision tags when the detector flagged a moment.

`vision_tracker` derives fog-of-war from Live Client position freshness on SR-style maps and stamps `last_seen_zone="on_bridge"` for shared-vision modes (ARAM/KIWI) where Riot's API doesn't expose positions.

---

## Phase 3 agent framework

A second long-running process stack (`agents/supervisor.py`) runs alongside the main RC process on Legion. It owns a roster of 8 specialized agents, exposes an HTTP API at `:8890` (proxied as `/api/analyze` on the dashboard), and a WebSocket relay at `:8891`. A PID lock in `agents/state/lockfile` prevents duplicate launches.

| Agent | Name | Role |
|---|---|---|
| **0 — Gatekeeper** | `agent0_gatekeeper/evaluator.py` | Policy gate for cross-machine tasks. Evaluates against 6 criteria; returns accept/reject. Rejection reasons 1/2/3/6 → dead-letter immediately; 4/5 → auto-retry-once. Permitted ops in `allowed_ops.json`; target machines in `target_allowlist.json`. |
| **1 — Lead Scheduler** | `agent1_lead/scheduler.py` | Single writer of `agents/state/task_queue.jsonl`. In-memory priority queue with append-only JSONL persistence; replays on startup to recover state. Hard gates (kinds 1,7,8) → needs explicit approval; soft gate via Agent 0 (kind 5, cross-machine); ungated kinds → ready immediately. |
| **2 — Backend Ingest** | `agent2_backend/` | Consumes `game-summary` tasks → inserts rows into mode DB. WebSocket server for real-time updates. SMB push for cross-machine sync. Win/loss wired to live coaching JSON. |
| **3 — Testing** | `agent3_testing/suite/` | Comprehensive pytest suite (19 test files) covering all agents, core modules, game ingest, audit probes, and 10 regression rounds. |
| **4 — Coach Mentor** | `agent4_coach_mentor/analyzer.py` | Replays matches in mode DB. Rolls per-champion aggregates into `adaptation_buckets`; bumps `matchup_modifiers` sample counts per-champion × per-mode. Activates matchup modifiers once sample threshold is reached. Autonomous writes for aggregates; propose-and-queue only for coach prompts or UI changes. |
| **5 — UI Agent** | `agent5_ui/champion_fallback.py` | Champion fallback when Riot's Live Client API (`:2999`) is unreachable. Three-signal chain: LCU champ-select → most recent match history row → most recent user input mentioning a champion. Served at `/api/locked-champion` with brief caching. |
| **6 — Auditor** | `agent6_auditor/_audit_probes.py` | Security audit probes — verifies weaknesses empirically (path traversal, subdir substring matching, dotfiles). Source quality ratings in `source_quality.json`. |
| **7 — Context / NL Parser** | `agent7_context/input_parser.py` | Translates user free-text (dashboard or CLI) into tasks via Agent 1's scheduler. Rule-based fast path (regex + keywords, ~80% coverage) with Haiku LLM fallback. Never dispatches agents directly — only files tasks. Runs as a warm session maintained by the supervisor during play windows. |

### `agents/state/` — coordination layer

- `task_queue.jsonl` — append-only log of every task status transition (~828 KB); Agent 1's source of truth on restart
- `lockfile` — PID lock, heartbeated every 5s; duplicate supervisor launches abort on stale check
- `resolved_decisions.json` — locked topology decisions (phase3-1.1): machine IPs, install root, Moon-PC decommission record

---

## Cross-Claude infrastructure

Three Claudes coordinate over a Tailscale-secured bridge:

- **Transport** — Tailscale free Personal plan, MagicDNS hostnames, direct peer-to-peer; HTTPS with mkcert-signed cert (Game-PC has the root CA trusted)
- **Auth** — 43-char urlsafe-base64 bearer token in each side's `ops/local_paths.json` (gitignored); same secret on both ends. Bearer is the actual auth gate; TLS provides confidentiality
- **Wire format** — JSON envelopes per [`docs io RC peer/RC_BRIDGE_CONTRACT.md`](./docs%20io%20RC%20atx/RC_BRIDGE_CONTRACT.md): `{source, summary, kind, id?, target?, body?, in_reply_to?}`
- **Inbox** — `POST /api/bridge/inbox` (Bearer-guarded; 503 if unconfigured, 401 on bad token, 400 on bad JSON, 200 on accept)
- **Outbound** — `from core import bridge; bridge.send(source=..., summary=..., kind=..., target=..., body=...)` returns `(ok, detail)` and never raises
- **Audit trail** — every inbound + outbound entry persists to `dashboard/_bridge_log.bridge_log` deque + `ops/runtime/bridge_log.jsonl`; bridge freshness is a Prometheus gauge (`rc_bridge_gamepc_result_age_seconds`) and a colored dot on the home dashboard

Fully bidirectional and operator-typeable: `bridge_task.py --target gamepc "<prompt>"` and the result lands back via the bridge without operator-mediated relay.

### Skills (`.claude/commands/`)

Repo-level slash commands shipped to all 3 nodes via `/agent/`:

- **`/process-bridge-tasks`** — drain the bridge inbox, action each `kind=task` envelope, post results back via `bridge_post_result.py`. Per-node variants (Legion / Game-PC / Peer) handle local path differences.
- **`/diagnose`** (2026-05-03, mattpocock-derived) — systematic 5-phase debugging loop: REPRODUCE → MINIMIZE → HYPOTHESIZE → INSTRUMENT → FIX. Replaces ad-hoc investigation when a coach mode regresses or a watcher pattern declines.
- **`/caveman`** (2026-05-03, mattpocock-derived) — ultra-compressed output mode (~75% token reduction). Use for headless cross-Claude tasks, when daily token cap is approaching, or when the operator says "be brief".
- **`/process-incoming-lessons`** — Phase 2-receiver of the cross-Claude learning sync.
- **`/wrap`** — end-of-session checkpoint (git clean, push, peer-loop liveness probe, frozen-file gate).
- **`/game-monitor`** — live-game tutor tick (gates on `mode_key` + `liveclient`; 3-5 line surface).

### Bridge Watcher daemon (2026-05-03)

The interactive `/loop /process-bridge-tasks` cron pattern was replaced by a
silent Python daemon (`tools/bridge_watcher.py`) that polls the bridge,
classifies envelopes, and either auto-actions whitelisted tasks via a
headless `claude --print` sub-process or escalates to a pending-queue file
the operator drains via `/process-bridge-tasks`. Full plan:
[`tools/BRIDGE_WATCHER_PLAN.md`](./tools/BRIDGE_WATCHER_PLAN.md).

| Phase | What | Status |
|---|---|---|
| **0 — MVP** | daemon, classifier, escalation queue, `GET /api/bridge/pending`, `RC-BridgeWatcher` scheduled task | ✅ live on Legion |
| **1 — rollout** | `bridge_watcher_install.ps1` one-liner installer, per-node config, UserPromptSubmit hook for no-dashboard nodes | ✅ installed on Game-PC + Peer |
| **2 — auto-action** | `claude --print --bare` invocation with restricted tool allowlist, intent-verb frozen-file gate, 16 KB body cap with on-disk overflow, daily `$/USD` cap | ✅ `read` lane live on Legion |
| **3 — ops lane** | tightened `bash_restricted` (no `powershell -c *`, no `py *.py`), `restart_trigger.txt` in `escalate_always`, `bypassPermissions` for headless | ✅ `ops` lane live on Legion |

Hard rules baked into the watcher:
- `Edit` / `Write` / `NotebookEdit` are NEVER in any auto-action allowlist
- Frozen-file gate uses **intent-verb** matching (write verbs near the path) — read queries on frozen files are fine, write attempts escalate
- Per-call budget is `min(config.per_call_budget_usd, remaining_daily_cap)`
- Auto-action defaults to **OFF**; opt in via `--enable-auto-action-lanes <read|read,ops>`
- Pending queue is dedupe-keyed by `task_id` (or `source::ts` composite) so the same envelope never escalates twice
- Heartbeat exposes `auto_actions_since_boot`, `auto_ok_since_boot`, `auto_err_since_boot`, `tokens_used_today_usd` for acceptance-criteria measurement

---

## Bring-up

### Legion (the brain)

1. Python 3.14 at `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
2. `python -m pip install -r requirements.txt`
3. Drop your Anthropic API key in `API-Key-Claude.txt` at the repo root (gitignored)
4. (Optional, for the cross-Claude bridge) Create `ops/local_paths.json` from `ops/local_paths.example.json` with the shared bearer + peer URL
5. Run `start_claude.ps1` (or the **Claude RC** desktop shortcut) — starts the `RC-Supervisor` and `RC-VisionServer` scheduled tasks idempotently and launches a Claude Code session in this repo

### Game-PC (the eyes and hands)

One-line bootstrap from any Game-PC PowerShell session (idempotent, self-elevating):

```powershell
iex (iwr https://legion-rc:8888/agent/gamepc_boot.ps1).Content
```

This fetches all five agents + the `start_gamepc_claude.ps1` launcher + the `process-bridge-tasks.md` slash command (deployed to `~/.claude/commands/`), provisions the inbound firewall rule for the MCP server (TCP 8892), kills any zombie listeners, starts whatever isn't healthy, installs at-logon scheduled tasks (`RC-LCU`, `RC-LiveClientRelay`, `RC-MCP-Server`, `RC-HotkeyListener`, `RC-GamePCBoot` for the bootstrap itself), and spawns a visible Windows Terminal running the bridge Claude session.

### Dashboard surface

Chrome on Game-PC's secondary display, pointed at `https://legion-rc:8888/`. Design baseline: **standard 1920×1080 with Chrome chrome present** (titlebar + URL bar + bookmarks bar visible — usable viewport ≈ 1920×~920). F11 fullscreen is optional; the layout is a flex-column with `main { flex: 1 1 auto }` so the main content area auto-grows into whatever vertical space is recovered. The mkcert root CA is already trusted on Game-PC, so the cert validates cleanly with no flags.

---

## Engineering

Multi-tier engineering audit completed across spring 2026. Each tier item shipped with a restart-and-verify gate; PIDs and verification records are in `WAKEUP_NOTES.md`.

| Tier | Status | Highlights |
|---|---|---|
| **1 — load-bearing infra** | ✅ 5/5 | sqlite per-thread cache, liveclient consolidation, log retention, task-queue compaction, dashboard split |
| **2 — architecture & reliability** | ✅ 5/6 (#9 deferred) | dashboard helper-shake (web_dashboard.py → 145L barrel), tkinter shim removal, bridge auto-flow watchdog, **#8 daemon threads → asyncio (C1–C5 complete)** — `tk.Tk()` gone, all 5 module pollers + 3 LCU pollers + BaseCoach loops on the AppLoop. #9 (DB compression on 1.7 GB rewind_history.db) avoided as high-blast-radius / low-benefit |
| **3 — technologies** | ✅ 5/5 | OBS WebSocket publisher (opt-in), Prometheus `/metrics` (zero-dep), portalocker swap, decisions API decouple, PyInstaller spec |
| **4 — UI polish** | ✅ 3/3 | SSE for `/api/state` (eliminates ~30 fetches/min when idle), loadout diff highlight, recent coach calls panel + dedicated sub-page |

Production code is **genuinely tkinter-free** (zero `import tkinter` in production tree; archived inert files live under `_archive/2026-05-01-audit/`). Every long-running poller in production rides the AppLoop; remaining threading is deliberate (`ThreadingHTTPServer`, Win32 hotkey poll, `asyncio.to_thread` worker offloads for blocking I/O).

Test surface: `tests/phase2_smoke/` (TFT worker, SR/ARAM worker) + `tests/snapshot_regressions/` (state-authority shape).

---

## Roadmap

See [`ROADMAP.md`](./ROADMAP.md) for the full milestone ledger.
Highlights of what's open after the 2026-05-03 Bridge Watcher ship:

### Cross-Claude learning sync (2026-05+) ← Phase 4 remains

Operator goal: lessons learned on one machine apply to the others overnight, with provenance memories and a SessionStart wake-up summary. Vision doc: [`docs io RC peer/CROSS_CLAUDE_LEARNING_SYNC_VISION_2026-05-02.md`](./docs%20io%20RC%20atx/CROSS_CLAUDE_LEARNING_SYNC_VISION_2026-05-02.md).

- **Phase 1 — schema + filter contract.** ✅ Both sides agreed on the `cross_project: true` + `applies_when` memory frontmatter, the `kind=lesson` envelope, and the sender/receiver filter tables.
- **Phase 2 — sender + receiver.** ✅ `core/lessons_sender.py` + `tools/lessons_send.py` (scan memory dir, send `kind=lesson` via bridge, dedupe via `lessons_sent.jsonl`). `core/lessons_receiver.py` + `tools/lessons_pull.py` + `tools/lessons_post.py` + `.claude/commands/process-incoming-lessons.md` (schema gate, `does_not_apply_when` pre-triage, apply/queue/discard, provenance memory + MEMORY.md pointer, ack to peer).
- **Phase 3 — wake-up surface.** ✅ `tools/rc_facts.py` `_lessons_summary()` probe added — SessionStart now surfaces "N lessons synced from peer in last 24h: M applied, K queued, L discarded" when the ledger is non-empty.
- **Phase 4 — polish (open).** Auto-revert if applied lessons cause test failures; lesson confidence scoring; symmetry check ("did the lesson take?").

The remaining Polish items below are tracked separately:

- **Push channel for bridge inbox** — replace 2s polling on the bridge monitor with an in-process notify in `bridge_post()` so the monitor sees inbound in <10ms. Touches frozen `dashboard/_bridge_log.py`.
- **PowerShell 7 migration** — bundle with a future "ops day"; PS 5.1 quirks haven't blocked anything.
- **Bridge Watcher artifact rotation** — `ops/runtime/bridge_action_artifacts/` grows monotonically. Add a daily cleanup (delete artifacts older than 7 days, or whose task_id is in the processed-ids ledger).
- **Auto-ops verb expansion** — current Legion `auto_ops_verbs` are conservative (4 entries). Once Phase 3 success rate clears 95%, add: `tail .* log` → `Bash(type tail-N)`, `restart agent .*` → `schtasks /Run /TN`, `verify .*` → `curl health`.

### Bridge Watcher hardening (2026-05+)

- **Acceptance-criteria measurement.** Plan §11 calls for ≥90% success on auto-read and ≥95% on auto-ops. Need to accumulate ~50+ real-traffic samples and graph success rate per-pattern; downgrade specific patterns to escalate-only if they drag the rate down.
- **Sliding 24h-window counters.** Today the heartbeat ships `*_since_boot` counters (reset on watcher restart) plus deprecated `*_24h` aliases. A real 24h sliding window would let `escalations_per_24h` be a meaningful SLO.
- **Push notifications for escalations.** Plan §8 specifies one PushNotification per new escalation with a 3/hr/node throttle. Not implemented; today escalations only surface via the operator's UserPromptSubmit hook on next prompt.
- **Dashboard panel for `/api/bridge/pending`.** Endpoint serves the queue; no UI consumes it yet. Add a "Pending Bridge Tasks" card on the home dashboard with Accept/Defer/Dismiss actions.
- **Auto-action restraint by node load.** When RC-Supervisor or RC main process is degraded, suppress auto-action (escalate everything) so the watcher doesn't compete for resources.

### Tiered vision calibration (🟡 in progress)

Tesseract regions in `data/vision_regions.json` use 1920×1080 defaults — needs calibration against actual in-game frames + coach-side routing logic that calls Tesseract for cheap fields and only escalates to Sonnet when the region read is missing or low-confidence. The endpoints exist (`/api/ocr`, `/api/ocr-crop`); the gating logic doesn't yet.

### Daemon Slayer engine — current state and remaining work

**Coverage complete**: 547/547 DDragon purchasable items, ENGINE_VERSION 0.65.0, 1151 tests. All phases of item modeling complete. 3 items permanently deferred (Lightning Braid, Kinkou Jitte, Mejai's Arena mirror — schema limits). s174 adds the Tank EHP scorer (`ehp.py`); s175 adds the Bruiser hybrid scorer (`hybrid.py`); s176 adds the CS archetype-picker UI + `rank_for_primary_archetype()` dispatcher (`core/archetype_picks.py` + `dashboard/routes_archetype.py` + 6-button picker in champ_select.js My Pick card); s177 adds Phase 4a champion ability ingest (`agents/daemon_slayer/abilities.py` + `tools/daemon_slayer_abilities_extract.py`) — 171/172 champions / 927 ability forms / 98.4% ok parse; data-only, Phase 4b's `ability_dps.py` evaluator follows. Four layers of the six-archetype plan from `NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md` shipped; coach integration + Mage scorer follows.

**Coach wire-in (complete):**
- ✅ ARAM — DS-before-Haiku; picks in user turn; pre-DS hardcoded item rules removed (−37% system prompt)
- ✅ Arena + Brawl — DS-before-Haiku (commit b4609b4)
- ✅ SR (`coach_integration.py`) — DS-before-Haiku (commit b4609b4); calibration logging + `daemon_slayer_picks` JSON output wired

**Phase 7 — calibration**: validate engine output against `rewind_history.db` outcomes; tune model constants. Not started; blocked on having enough live DS-guided games logged.

---

## Operational notes

- `API-Key-Claude.txt`, `ops/local_paths.json`, runtime state under `ops/runtime/`, and `ops/tls/*` are all gitignored
- All overlay file writes are atomic (`tmp.write_text(); tmp.replace(target)`); `os.replace` carries a retry-with-backoff to handle Windows transient `WinError 5` when readers have the destination open
- Restarts: `echo restart > restart_trigger.txt`; supervisor picks it up within 1s. Hard fallback: `taskkill /F /PID <pid>` then `restart.bat`. **Never `Stop-Process`** (hangs the MCP pipe).
- Always `py_compile` before restart — syntax errors crash silently under `pythonw.exe`
- Frozen files (listed in `CLAUDE.md`) require explicit user approval to modify; they're load-bearing and regression-prone
- The supervisor is now hardened against a Windows venv pythonw stub bug: it latches the observed PID on first valid heartbeat instead of trusting the Popen pid
- Session workflow: scoped sessions, not long-lived ones. End each task with a commit + `WAKEUP_NOTES.md` hand-off + memory save for non-obvious learning. `/clear` between focus areas

---

## RC Tutor — Future Direction

RC is the engineering foundation. **RC Tutor** is the eventual packaged product: a second-screen AI coaching companion for League of Legends (and potentially other Riot games) that any player can install and run, not just someone willing to wire up a two-machine tailnet.

### What RC Tutor would be

- **Standalone install** — single-machine mode; the "Legion brain / Game-PC eyes" split compresses to one box. Vision relay runs locally; Daemon Slayer engine ships bundled.
- **Always-on second screen** — dashboard on a secondary monitor, tablet, or as a windowed overlay alongside the game. Not an Overlay Platform M inject — no ToS ambiguity.
- **Patch-day auto-update** — item data and builds refresh automatically on patch. The `data_pipeline.py` infrastructure and DDragon integration already exist; the scheduled trigger is a config toggle away.
- **LLM coaching with real math** — most coaching tools show you tier lists. RC Tutor shows you *why* an item wins: Daemon Slayer computes actual DPS curves for your champion vs. the enemy comp you're facing, then Haiku explains the decision in plain language.
- **Live vision** — screen capture feeds into Tesseract OCR for cheap reads (gold, health, timer) and Sonnet for reasoning (wave state, fog inference, item spike detection). Vision calibration is in progress.
- **Multi-mode** — SR, ARAM, Arena, TFT, Brawl. All modes are already implemented in the coaching layer.

### Decisions needed before a general release

1. **Distribution channel** — Overlay Platform M SDK (largest existing user base, but sandboxed and privacy-opaque) vs. standalone installer (full control, but no discovery) vs. a companion web app (no install, limited capabilities).
2. **Riot ToS compliance** — second-screen approach (reading the API, not injecting into the game) is the safe path. The overlay/inject approach has historically been grey-area for Overlay App E and others.
3. **Pricing model** — freemium (free tier without LLM backend, paid for AI coaching) vs. subscription vs. one-time license. The Anthropic API cost is real at scale — the Daemon Slayer engine offloads cheap queries to local math, reserving LLM budget for reasoning calls.
4. **Onboarding** — current setup requires per-machine config. A wizard-style install flow (API key + machine type selection) is needed before any public release.
5. **Privacy / data model** — RC is fully local; no telemetry. That's a selling point vs. cloud-first competitors, but requires clear communication.
6. **Scalable update pipeline** — the patch-day refresh works manually; needs a background auto-update service (similar to how Overlay App E patches its databases) with version pinning and rollback.
7. **Multi-account support** — scaffold exists (`RC_ACCOUNT_ID` env var, per-account ratings dirs); needs a UI switcher and clean onboarding for secondary accounts.

### Where RC is on that path

| Capability | Status |
|---|---|
| LLM coaching (all modes) | ✅ live |
| Second-screen web dashboard | ✅ live (Chrome on secondary display, 1920×1080 baseline) |
| Daemon Slayer DPS engine | ✅ 547 items, 1151 tests, ENGINE 0.65.0; `:8893` service; all 4 coaches wired (DS-before-Haiku); dead-unique filter live; Tank EHP scorer (s174) + Bruiser hybrid scorer (s175) ship first 2 of 6 archetype scorers + s176 ships the CS archetype-picker UI + `rank_for_primary_archetype()` dispatcher + s177 Phase 4a Meraki champion ability ingest (927 forms, 98.4% ok) |
| Vision relay (screen → Sonnet) | ✅ live; OCR calibration in progress |
| Rune auto-writer | ✅ live (LCU integration) |
| Champ-select live coaching | ✅ live |
| Replay analysis | ✅ live (rewind_history.db, 2,846 matches) |
| Match history + adaptation | ✅ live |
| Standalone PyInstaller bundle | 🟡 spec exists; not polished |
| Patch auto-update pipeline | 🟡 manual trigger; scheduling wired |
| Single-machine mode (no split) | 🔴 requires vision relay refactor |
| Public install wizard | 🔴 not started |
| Paid billing / licensing | 🔴 not started |

---

## License

All rights reserved. Personal use only.

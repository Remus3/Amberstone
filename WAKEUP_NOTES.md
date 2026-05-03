# s27 thread roll-up — 2026-05-01 (sessions 27 → 27u, condensed)

> 21 sub-sessions over a single day. **Outcome:** every Tier 1-3 audit
> item shipped, plus Tier 4. Tier 2 only #9 (DB compression, avoided)
> remains. Below is the commit ledger; per-session restart PIDs,
> bootstrap sections, and design rationale that's now visible in code
> are dropped. Reusable patterns are listed at the end.

## Commit ledger (s27 → s27u)

| Sub-session | Commit | Audit | Summary |
|---|---|---|---|
| s27 | 778971d | T2 #5 | dashboard helper-shake: state builder → `dashboard/_state_builder.py` |
| s27 | 6d89a62 | T2 #6 | champ-select brief → `dashboard/_champ_select.py` |
| s27 | aa341cc | T2 #7 | `_Handler` + supervisor proxy constants → `dashboard/_handler.py` (web_dashboard.py becomes pure barrel module) |
| s27 | 22248fe | T2 #7 | bridge auto-flow watchdog: `/api/health/all` `bridge` block w/ age + green/yellow/red |
| s27 | 36edb82 | T3 #14 | `core/coaching_data_lock` → portalocker (msvcrt → portalocker) |
| s27 | c3a68e5 | T4 #17 | loadout diff highlight (amber ring on items differing across variants) |
| s27 | 21997e3 | T3 #11 | OBS WebSocket publisher (264L, opt-in via `config/coach_settings.json`) |
| s27 | 0caedc7 | T4 #16 | SSE `/api/state-stream` route + `EventSource` subscriber |
| s27 | 55332c7 | T4 #18 | `/api/decisions/log?limit=N` + Recent Coach Calls panel |
| s27 | ffcfba9 | T3 #13 | `riot-commander.spec` PyInstaller spec (opt-in starter) |
| s27 | 8337d63 | T3 #15 | `/api/decisions` GET/POST instantiate `DecisionStore()` directly (decouple from singleton) |
| s27b | 3740dff | chore | untrack runtime `coach_settings.json`; ship `coach_settings.example.json` |
| s27b | fa9dc45 | T3 #15 | DecisionLoop daemon thread → `agents/supervisor.py`; `_decisions_critical_section()` cross-process lock |
| s27c | 27e8a43+9a162a2+(docs) | T2 #6 | tkinter shim removal — −968 lines across 12 source files + 5 docs (overlay manager, coach overlay attach/detach, ui aram pregame deiconify) |
| s27d | c9191a3 | T3 #12 | `core/prom_metrics.py` zero-dep + `dashboard/routes_metrics.py` `/metrics`, ~0.3 ms render |
| s27g | (T2 #8 C1) | T2 #8 | replace `tk.Tk()` with asyncio scheduler. New `app/_loop.py` AppLoop (~95L). Delete `ui/aram_pregame_panel.py` (~700L dead since T2 #6) |
| s27h | (T2 #8 C2) | T2 #8 | repo-wide `import tkinter` archive (not delete) — 13 files / ~5000 LOC moved to `_archive/2026-05-01-audit/{ui,modes,tft,core}/`. **Production tree is tkinter-free.** |
| s27i | (T2 #8 C3) | T2 #8 | `_base_coach._poll_loop` + `_vision_loop` → `async def`; `_run_coach`/`_run_vision` via `asyncio.to_thread`. `app._loop.get_loop()` singleton accessor. |
| s27j | (T2 #8 C4) | T2 #8 | 5 module pollers (`liveclient_cache`, `vision_tracker`, `obs_publisher`, `metrics_cache`, `log_retention`) → `spawn_task(_loop_async())` w/ daemon-thread fallback. `ensure_loop()` factory in main.py. |
| s27k | (push) + (vision_tracker fix) | bug | `_compute_enemies` line 303 — `pos = p.get("position") or {}` failed when Live Client emits `position: "NONE"` (string, truthy). `isinstance(pos, dict)` guard. Fixed 2-day stale `vision_state.json` + 1856-per-day debug spam. |
| s27l | (vision_tracker shared-vision) | feature | `_SHARED_VISION_MODES = frozenset({"ARAM","KIWI"})`. Alive enemies in shared-vision modes get `visible=True`; SR fog path untouched. |
| s27m | (coach-calls sub-page) | feature | Recent Coach Calls moved off home page → `/coach-calls` sub-page via existing view-router (`VIEW_IDS` += "coach-calls"; `body[data-view="coach-calls"]` CSS). |
| s27n | (on_bridge zone label) | feature | Shared-vision branch stamps `last_seen_zone="on_bridge"` (no coords available — honest constant). |
| s27o | (push) + screenshot verify | ops | Pushed `eaa35a8..29ed1e1`; closed s27m's deferred visual verify of `#coach-calls` sub-page. |
| s27p | (MAP STATE pill) | feature | Split pill render: SR uses `renderMinimapCanvases` position-based, shared-vision uses `refreshVisionOverlay` from `vs.summary.visible_count/dead_count`. `_sharedSig` change-detection avoids 500 ms heart-pulse. |
| s27q | (push) | ops | `git push origin main` `29ed1e1..957dab7`. |
| s27r | (revert) | docs | Implemented per-enemy alive/dead greying via orphan team-strip render fns; reverted on verify — DOM IDs (`enemy-strip-row` etc.) **never existed** in served HTML. Memory `reference_orphan_team_strips` written. |
| s27s | (T2 #8 C5) | T2 #8 | LCU pollers async: `lcu_client` (frozen, pre-approved), `lcu_rune_writer`, `lcu_postgame_collector`. `threading.Event` retained for postgame cross-thread trigger. **T2 #8 fully complete (C1–C5).** |
| s27t | (memory update) | docs | s27s "easy" team-strip candidate killed: 2nd blocker found (server emits `enemy_team`, JS reads `enemy_comp` — no rename layer). `reference_orphan_team_strips` updated to flag both blockers prominently. |
| s27u | (CLAUDE.md sync) | docs | Removed stale "TFT vision broken post-migration" claim; both `tft/tft_vision_reader.py` + `tft/tft_ocr_reader.py` were already on `/latest-frame` relay. |

## Final audit state at end of s27u

- Tier 1 ✅ 5/5 (sqlite per-thread cache, liveclient consolidation, log retention, task-queue compaction, web_dashboard split)
- Tier 2 ✅ #5/#6/#6/#7 + #8 C1–C5 — only #9 (DB compression, avoided — high blast radius on 1.7 GB rewind_history.db) remains
- Tier 3 ✅ 5/5 (#11 OBS, #12 Prometheus, #13 PyInstaller, #14 portalocker, #15 decisions process move)
- Tier 4 ✅ 3/3 (#16 SSE, #17 loadout diff, #18 recent coach calls)

## Reusable patterns established (file pointers)

- **AppLoop singleton accessor** — `app/_loop.py:get_loop()` returns `Optional[AppLoop]`. Subsystems branch: scheduler path → `spawn_task(_loop_async())`, fallback → daemon thread. Used by every async-converted poller. `ensure_loop()` lets pre-OverlayApp subsystems create the loop early; `OverlayApp.__init__` reuses it.
- **`asyncio.to_thread` offload** — wrap blocking I/O (Anthropic SDK, Tesseract, HTTP) inside async loops to keep AppLoop responsive. Mode coaches' sync `_run_coach`/`_run_vision` dispatch via this.
- **`threading.Event` for cross-thread async wakers** — when senders live on multiple threads (e.g. postgame trigger), use `threading.Event` + `await asyncio.to_thread(event.wait, timeout)`. Pure-AppLoop senders should prefer `asyncio.Event`.
- **Sub-page via view-router** — add VIEW_IDS/LABELS in `web/js/dashboard.js`, menu button + `<section id="view-X" class="view-section" hidden>` in `web/index.html`, then 3 visibility rules in `web/css/dashboard.css` for `body[data-view="X"]`. No lazy-fetch hook needed if data is polled globally.
- **`_archive/YYYY-MM-DD-audit/<area>/`** — move dead files via `git mv` (preserves history). Per `reference_archive_dir`, never delete on a multi-file purge — reversible.
- **Idempotent dashboard renders** — stash signature on container, skip rebuild if unchanged. Avoids 500 ms heart-pulse + flicker. (`_sharedSig` cache in s27p is the canonical example.)
- **Static-asset edits don't need RC restart** — `web/*` are served per-request by `dashboard/server.py`. Edge picks up via Ctrl+F5.
- **Live Client `position` field** — emits `"NONE"` (string, truthy) for ARAM and dead/loading SR players. Always `isinstance(pos, dict)` before `.get()`. The `or {}` idiom **does not protect** because `"NONE"` is truthy.
- **Verify DOM exists before adding rendering code** — `curl -sk https://127.0.0.1:8888/ | grep -i 'target-id'` is the 5-second check. s27r's revert is the cautionary tale.
- **Doc-sync discipline** — only update living docs (CLAUDE.md, README, ROADMAP, INFOGRAPH) on refactors; never rewrite dated audit/handoff ledgers (`feedback_no_history_rewrite`).

## Out-of-T2-#8 / intentional threading

- `dashboard/server.py` ThreadingHTTPServer — out of scope; would need aiohttp/Hypercorn rewrite.
- `core/hotkeys.py` Win32 polling — no benefit from converting.
- `agents/supervisor.py` Phase 3 — already async; isolated process.
- `tft_coach.py` / `tft_pbe_coach.py` — not BaseCoach subclasses; separate refactor.

---

# s28 hand-off — 2026-05-02 (RC↔Peer bridge live; inheritance arc closed)

> Long session, two arcs. **Arc 1**: Peer-VIP inheritance — RC sent the
> WT/PS7 + session-control discipline + bridge contract; Peer sent back
> a parity report showing they applied nearly everything verbatim plus
> two bug fixes RC mirrored. **Arc 2**: cross-Claude bridge stood up
> end-to-end over Tailscale. RC ↔ Peer now exchanging acks/asks/notes
> via `/api/bridge/inbox` without operator file relay. Currently
> running RC PID 11836; supervisor PID 10796. **5 commits this session,
> all pushed (origin/main at `7307e6a`).**

## What just shipped this session (in order)

| Commit | Type | Summary |
|---|---|---|
| `a38d002` | docs | Seed `docs io RC peer/` with 5 durable inheritance docs (3 Peer originals + RC update + WT inheritance). `.gitignore` patterns for `*ASKS*`/`*BUNDLE*`/`*POST_UPDATE*` so round-trip scratch auto-ignores. |
| `3b22bce` | fix | `ops/rc_supervisor.py`: pythonw stub pid latch + `os.replace` retry-with-backoff. Both bugs surfaced by Peer's first multi-child supervisor smoke; RC mirrored defensively. Frozen-file edit (authorized). Activated via supervisor restart (taskkill 4996 + `schtasks /Run RC-Supervisor` → adopted Main 3312 cleanly). |
| `64de1ca` | docs | WT inheritance hardening (explicit pwsh profile block per Peer's parity-reply flag) + session control inheritance + bridge contract from Peer. |
| `7e80513` | feat | RC bridge: `core/bridge.py` (config readers + outbound `send()` via stdlib urllib) + `dashboard/routes_bridge.py` `/api/bridge/inbox` POST (Bearer guard) + `/api/bridge/status` GET + `ops/local_paths.example.json` template. Activated via Main restart. |
| `7307e6a` | chore | `.gitignore` hardening: `*SECRET*`, `*HANDSHAKE*`, `*PIVOT*`, `*REPLY*`, `*TOKEN*`, `*KEY*` patterns + `ops/local_paths.json` (the actual secret store). |

## RC restart state

- **Main PID 11836** (was 3312 → 9432 → 2956 → 11836 across four
  restarts: bridge endpoint activation, bridge URL IP form, bridge URL
  MagicDNS form, plus the supervisor activation cycle). Each restart
  verified clean (`last_reload_ok=true`, new pid).
- **Supervisor PID 10796** (was 4996 — replaced once this session via
  `taskkill /F` + `schtasks /Run RC-Supervisor` → adopted running Main).
  msvcrt byte-range lock cleanly released and reclaimed.

## Cross-Claude bridge — operational state (new since s27u)

- **Transport**: Tailscale free Personal plan. Both nodes in tailnet
  `tailc150de.ts.net` under `<operator-email>`. Direct
  peer-to-peer (`tailscale status` shows "active; direct").
  - **RC** = `legion-rc.tailc150de.ts.net` / `100.70.22.55`
  - **Peer** = `peer-host.tailc150de.ts.net` / `<peer-tailnet-ip>`
    (renamed from `desktop-ctbma25` mid-setup — see
    `reference_tailscale_magicdns_rename.md`)
- **Auth**: 43-char urlsafe-base64 bearer in each side's
  `ops/local_paths.json` (gitignored). Identical on both sides.
- **Endpoints live**: RC inbox `/api/bridge/inbox` (POST, Bearer-guarded,
  503/401/400/200 path); RC outbound `from core import bridge;
  bridge.send(...)`; Peer symmetric.
- **Path-name asymmetry**: RC's read endpoint is at `/api/bridge` (legacy
  pre-contract); Peer's at `/api/bridge/messages` (per contract). Tracked
  in `feedback_rc_peer_bridge_live.md`. Future v1 alignment is a 2-line
  add (route the same handler at both paths).
- **First handshake**: bidirectional, `ts ~1777745800`. Peer→RC and
  RC→Peer both `(True, 'ok')`, both persisted to bridge logs.
- **Live use**: operator's "ask peer what's next" → bridge → Peer replied
  via bridge → answer parsed, no operator-mediated file relay needed.
  This is the new pattern.

## Memory entries written this session

- `reference_pythonw_launcher_stub` — pid mismatch under venv pythonw stub
- `reference_os_replace_winerror5` — Windows transient PermissionError on rename
- `reference_rc_peer_bridge` — endpoint + config + opt-in semantics
- `feedback_rc_peer_bridge_live` — bridge live timestamp + path asymmetry
- `reference_tailscale_magicdns_rename` — Tailscale hostname-rename gotcha

## Operational backlog

- **Bridge monitor mirror** — Peer shipped their `bridge_monitor_agent.py`
  (commit `b2e30b5`, always-on auto-pong sidecar). RC needs the
  symmetric agent. Design spec landed at
  `docs io RC peer/PEER_VIP_BRIDGE_MONITOR_FOR_RC_2026-05-02.md`
  (now tracked — committed in s28). **Top of next-session queue.**
- **Cloud routine deadline 2026-05-10** — 8 days. Origin/main is current
  through `7307e6a`. Repo OAuth still untested on private
  `Remus3/riot-commander` (per `project_verify_github_access_cloud_routine`).
- **Game-PC `/loop /process-bridge-tasks`** — old Legion↔Game-PC bridge
  separate from the new RC↔Peer bridge. Watchdog still surfaces silence;
  Game-PC-side fix.
- **Tiered vision** still 🟡 (CLAUDE.md priority 3, unchanged).

## Next-session candidates (ranked)

1. **Bridge monitor mirror** — design doc in hand. RC stack uses different
   agent base than Peer (no multi-child supervisor on RC). Adapt to RC's
   pattern: probably a daemon thread spawned from `dashboard/server.py`
   alongside `vision_tracker` and `obs_publisher` — same shape as those.
   Filter: `ts > last_seen_ts AND not source.startswith("rc") AND source
   != "self-test"`. Auto-pong gate: `kind=task AND
   summary.strip().lower()=="ping" AND target.lower()=="rc"`. Reply with
   `source="rc-monitor", kind="result", summary="pong",
   in_reply_to=<original-id>`. State at `data/bridge_monitor_state.json`,
   atomic-written, mirrors Peer's shape.
2. **Push-channel for bridge inbox** (v1 conversation) — replace the
   2s polling with an internal SSE/push from `_bridge_log.bridge_post()`
   so the monitor sees inbound in <100ms instead of <2s. Peer mentioned
   this as their v1 thinking too. Touches frozen `dashboard/_bridge_log.py`.
3. **Cloud routine OAuth verification** — open `claude.ai/code/routines/<id>`
   and confirm GitHub token is valid for `Remus3/riot-commander` ahead of
   2026-05-10 fire.
4. **Path-name alignment** — add `/api/bridge/messages` as a second
   matcher on RC's existing `_serve_bridge` handler so Peer's contract
   path also resolves on RC (1-line change in `dashboard/routes_bridge.py`
   GET_ROUTES table).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list).
2. Read this hand-off (s28).
3. Read `docs io RC peer/PEER_VIP_BRIDGE_MONITOR_FOR_RC_2026-05-02.md` —
   the design spec for the mirror.
4. Read memory: `reference_rc_peer_bridge`, `feedback_rc_peer_bridge_live`,
   `reference_tailscale_magicdns_rename`.
5. **Bridge is opt-in but currently ON** — `core/bridge.is_configured()`
   returns True; `ops/local_paths.json` has the bearer + Peer URL. To
   send a one-off message: `from core import bridge;
   bridge.send(source='rc', summary='...', kind='note', target='peer')`.
6. **Don't restart the supervisor** unless you have a reason — it's at
   PID 10796 with the new patches active and works. Main restarts via
   `restart_trigger.txt` are fine.

---

# s29 hand-off — 2026-05-02 15:05 (Game-PC on tailnet + RC bridge_monitor live)

> Two-arc session, both operator-driven via the now-live cross-Claude
> bridge. **Arc 1**: Game-PC joined the tailnet as `gamepc-rc`
> (`100.95.66.128`); RC's bridge tooling flipped from `192.168.8.230`
> LAN IP to `legion-rc` MagicDNS. **Arc 2**: RC's symmetric bridge
> monitor sidecar (top of s28's next-session queue) shipped, smoke
> verified, auto-pongs `kind=task summary=ping target=rc` in <100 ms.
> Currently running RC PID 9832; supervisor still 10796.

## What just shipped this session (in order)

| Type | Files | Summary |
|---|---|---|
| network | (Tailscale on Game-PC, no repo change) | Game-PC installed Tailscale 1.96.3, joined tailnet `tailc150de.ts.net` as `gamepc-rc` (`100.95.66.128`). `tailscale ping` to legion-rc: 0% loss, 8 ms. `https://legion-rc:8888/api/bridge/status` from Game-PC → 200. Three-node tailnet now: legion-rc / peer-host / gamepc-rc. |
| chore (uncommitted at hand-off) | `tools/bridge_*.py` (7), `tools/scheduled_boot_verify.py`, `tools/bridge_setup.ps1`, `tools/gamepc_boot.ps1`, `tools/rc_facts.py` | Bridge tooling URL constants flipped `https://192.168.8.230:8888` → `https://legion-rc:8888`; `rc_facts` Game-PC MCP probe → `http://gamepc-rc:8892/health`. Section headers in `rc_facts` now read `Legion (legion-rc · 100.70.22.55 · 192.168.8.230)` — all three identities side-by-side. LAN refs intentionally retained for LCU/MCP/screen-relay paths and cert/UNC scripts (those aren't "bridge" config). |
| feat (uncommitted at hand-off) | `core/bridge_monitor.py` (NEW, ~210 LOC), `main.py` (frozen, +8 lines) | RC's mirror of Peer's `bridge_monitor_agent.py`. Daemon-thread/AppLoop poller (mirrors `core/vision_tracker.py` lifecycle); polls `dashboard._bridge_log.bridge_since()` every 2 s; filters `source.startswith("legion")`, `source.startswith("rc-monitor")`, `source == "self-test"`; auto-pong gate `kind=task summary=ping target=rc` → `bridge_post(source="rc-monitor", summary="pong", kind="result", body={replier:"rc-bridge_monitor", in_reply_to_summary:"ping", auto:true}, in_reply_to=<id>)`. State at `ops/runtime/bridge_monitor_state.json` (atomic-write w/ `os.replace` retry-with-backoff); cold-boot starts `last_seen_ts=time.time()` so historical entries don't replay; warm-restart hydrates from disk. |

## RC restart state

- **Main PID 9832** (was 11836). Single restart this session via
  `restart_trigger.txt` to activate `core.bridge_monitor`. `last_reload_ok=true`.
- **Supervisor PID 10796** — unchanged from s28.
- **Bridge monitor live**: log line at boot
  `bridge_monitor started (poll=2.0s, async, last_seen_ts=1777752207)`.
  Smoke: simulated `peer-test` ping → auto-pong fired in **+0.09 s**;
  state file shows `inbound_count=1, auto_pong_count=1, recent[1]`.

## Cross-Claude bridge — operational state

- **Tailnet**: 3 nodes now (was 2 in s28).
  - `legion-rc` / `100.70.22.55`
  - `peer-host`  / `<peer-tailnet-ip>`
  - `gamepc-rc` / `100.95.66.128` *(new this session)*
- **RC↔Peer bridge**: unchanged from s28; still opt-in, live.
- **RC↔Game-PC bridge**: still on the legacy in-process `dashboard/_bridge_log.py`
  + Game-PC `/loop /process-bridge-tasks`. Game-PC's `/loop` rebooted
  fresh this session — last result 332 s ago at probe, healthy.
  Game-PC's installed copies of `tools/bridge_*.py` still point to the
  LAN IP; they self-update to `legion-rc` on next `gamepc_boot.ps1` re-pull.
- **Bridge monitor scope**: only watches the RC↔Peer-shape bridge log
  (the same `dashboard/_bridge_log.py` deque the dashboard's
  `/api/bridge` POST writes into). Game-PC's task/result entries
  ride the same log so the monitor sees them too — but `summary=="ping"`
  with `target=="rc"` is the *only* auto-action; everything else is
  log-only, exactly per spec.

## Memory entries written this session

None (the URL flip + monitor build are both code; no surprising or
non-obvious facts to commit to memory). The s28 `feedback_rc_peer_bridge_live`
remains the authoritative bridge-state memory.

## Operational backlog (delta from s28)

- ✅ ~~Bridge monitor mirror~~ (shipped; was top of s28 queue)
- **Cloud routine deadline 2026-05-10** — 8 days. Push the s29 commits
  before the routine fires.
- **Push-channel for bridge inbox (v1)** — promote from "next-candidate"
  if 2 s polling latency ever bites. Currently Peer→RC ping latency is
  bounded by the polling interval; first smoke landed at +0.09 s only
  because the post happened mid-polling-interval.
- **Game-PC bridge tooling re-pull** — Game-PC still has the old `192.168.8.230`
  copies. Non-breaking (LAN IP works), but tasking Game-PC to re-run
  `gamepc_boot.ps1` would normalize them to `legion-rc`.
- **Path-name alignment** (`/api/bridge/messages` as alias for `/api/bridge`)
  — unchanged from s28.

## Next-session candidates (ranked)

1. **Push s29 commits** — URL flip + monitor land as two commits
   (chore + feat). 8 days to cloud routine deadline.
2. **Game-PC re-pull** — task Game-PC's Claude to `iex (iwr
   https://legion-rc:8888/agent/gamepc_boot.ps1).Content` (note: also
   updated to use the tailnet hostname) so Game-PC's local
   `bridge_pull_tasks.py` etc. switch off the LAN IP.
3. **Bridge monitor v1 (push channel)** — replace polling with
   in-process notify in `bridge_post()` so the monitor sees inbound in
   <10 ms. Touches frozen `dashboard/_bridge_log.py`.
4. **Tiered vision** — still 🟡, unchanged from s28.
5. **CLAUDE.md sync** — the post-2026-04-19 topology section still
   names `192.168.8.230` / `192.168.8.237` as the canonical addresses.
   Now that all three nodes have stable tailnet identity, the doc
   could lead with the tailnet names. Low priority — the LAN IPs are
   still valid.

## Bootstrap for next session

1. Read `CLAUDE.md` (frozen list + restart workflow)
2. Read this hand-off (s29) + s28
3. `git status` — confirm s29 commits land before any new work; push
   ahead of the 2026-05-10 cloud-routine fire
4. Bridge monitor is **live and self-managing** — no action needed.
   To verify: `cat ops/runtime/bridge_monitor_state.json` shows
   `inbound_count` ticking up if any non-legion source has posted.

---

# s30 hand-off — 2026-05-02 16:13 (one-click bootstrap end-to-end + cross-Claude learning-sync vision shipped)

> Long arc-completing session. Started with "send Tailscale setup to
> Game-PC" and ended with three Claudes on three machines, all
> auto-launched with `/loop /process-bridge-tasks`, all `--dangerously-
> skip-permissions`, all on the same tailnet, all visually distinct
> via colored statuslines, and a strategic doc capturing the vision
> for autonomous bidirectional learning sync (Phase 1+ in the next
> session). **5 commits this session, all about to be pushed.**
> Currently running RC PID 980; supervisor still 10796.

## What just shipped this session (in order)

| Commit | Type | Summary |
|---|---|---|
| `7223afe` | chore | Bridge tooling URL constants flipped from `192.168.8.230` LAN IP to `legion-rc` Tailscale MagicDNS; rc_facts.py probe to gamepc-rc. Game-PC joined tailnet earlier in session as `gamepc-rc` (`100.95.66.128`). |
| `c4c9e07` | feat | `core/bridge_monitor.py` (~210 LOC) — RC's mirror of Peer's bridge_monitor sidecar. Daemon-thread/AppLoop poller, 2s cadence, atomic state at `ops/runtime/bridge_monitor_state.json`, auto-pongs `kind=task summary=ping target=rc` per Peer spec. Smoke-verified `+0.09s` round-trip. |
| `87cd4aa` | docs | s29 hand-off for the bridge-monitor + URL-flip arc. |
| `645e041` | feat | `tools/start_gamepc_claude.ps1` (~60 LOC) — idempotent launcher. Window-title sniff for "Game-PC bridge"; if absent, spawns Windows Terminal in `C:\RC-Agent\` running `claude --name "Game-PC bridge" "/loop 1m /process-bridge-tasks"`. argv prompt = first user message → /loop runs immediately on session start. `gamepc_boot.ps1` extended: pulls launcher alongside agents, calls it after pinning, installs `RC-GamePCBoot` logon-trigger task. `dashboard/routes_static.py` allowlist updated. |
| `1a43e67` | feat | `--dangerously-skip-permissions` added to the auto-launched Claude. The /loop bridge processor is fully autonomous; no human in the loop to answer permission prompts. |
| `4c2514d` | feat | `gamepc_boot.ps1` self-closes after 60s — `Start-Sleep 60; [Environment]::Exit(0)` at end. Operator gets a beat to read the green output, then the launcher window kills itself. Bridge Claude window stays (separate WT process). |
| `1542af1` | docs | `docs io RC peer/CROSS_CLAUDE_LEARNING_SYNC_VISION_2026-05-02.md` — operator-set roadmap for autonomous bidirectional learning. 4 phases: schema → sender/receiver → SessionStart wake-up summary → polish. Vision doc shipped to Peer via bridge with kind=note + acknowledgement protocol in §8. |

## Out-of-band changes (not committed — gitignored secrets)

- **TLS cert regenerated** with mkcert. Old SAN was `[localhost, 192.168.8.230, 127.0.0.1]`; new SAN adds `legion-rc`, `100.70.22.55`, `legion-rc.tailc150de.ts.net`. Same root CA — Game-PC's existing trust store entry remained valid (no re-import needed). RC restarted to pick up new leaf. `iwr https://legion-rc:8888` from Legion AND Game-PC now returns 200 with **no** `-SkipCertificateCheck` flag. Memory `reference_rc_dashboard_https` still accurate but the LAN-IP form is no longer the only trusted name.
- **`~/.claude/settings.json`** — added `statusLine` block on Legion. Cyan `[Legion]` tag + model + cwd basename + ctx%. Mirror snippets bridge-shipped to Peer (magenta `[Peer]` — confirmed merged) and Game-PC (yellow `[Game-PC]` — confirmed merged).
- **Game-PC desktop**: new `RC Agent claude.lnk` shortcut with iex bootstrap target + RunAs admin flag (byte-flip `[0x15] |= 0x20`). Old `RC-Agent Claude.lnk` (the wt.exe/launch.ps1 form) is now redundant — operator will hand-delete after verifying the new one.

## Cross-Claude bridge — operational state

- **Tailnet**: still 3 nodes, all stable (`legion-rc`, `peer-host`, `gamepc-rc`).
- **RC↔Peer**: bridge live and bidirectional. Today's exchange in this session covered: cert verification, statusline propagation, bootstrap pattern propagation (4 messages from Peer → 4 replies from RC), `/process-bridge-tasks` skill spec (full 7-question reply), verbatim pieces (.lnk byte-flip + start_gamepc_claude.ps1 + iex args + /agent/ allowlist mechanism), and finally the learning-sync vision doc. Peer is async — replies will land via the bridge as they're processed; nothing time-sensitive.
- **RC↔Game-PC**: bridge fully automated. Game-PC's `/loop 1m /process-bridge-tasks` is on the auto-launched Claude session; reboot self-restores via `RC-GamePCBoot` scheduled task. Cert-trusted iwr on both sides. Multiple round-trips this session — last result fresh.
- **bridge_monitor sidecar**: counters at `inbound_count=N` (whatever the smoke + any later inbounds have stacked up). Auto-pong gate hit cleanly on simulated ping; not yet exercised by a real Peer ping (Peer hasn't probed RC's auto-pong half — they could, low-priority test).

## Peer catch-up status (at hand-off)

In flight (Peer is async, no /loop polling required):

- ✅ Magenta `[Peer]` statusline merged into `~/.claude/settings.json` (confirmed render `[Peer] Claude Sonnet 4.6 · Peer-VIP ctx:13%`)
- ⏳ `/loop 1m /<bridge-task-skill>` argv pattern — Peer will integrate into `tools/claude-peer.ps1`. Awaiting their `/process-bridge-tasks` equivalent name decision.
- ⏳ Desktop .lnk byte-flip RunAs — Peer has the snippet verbatim, will create their own shortcut. Operator already minimizes their bootstrap window (5s self-close in claude-peer.ps1, vs RC's 60s).
- ⏳ Cross-Claude learning-sync vision ack — awaiting `kind=ack` from Peer confirming alignment on §1-§6, OR `kind=ask` flagging divergences.
- 🟡 Cert SAN refresh on Peer side — flagged as optional; only relevant if Peer wants tailnet-hostname access to their own dashboard.

## Memory entries written this session

None — knowledge is captured in code (`core/bridge_monitor.py`, `tools/start_gamepc_claude.ps1`) and in the strategic doc (`docs io RC peer/CROSS_CLAUDE_LEARNING_SYNC_VISION_2026-05-02.md`). Per CLAUDE.md memory rules, code patterns derivable from the current project state don't get duplicate memories.

The `cross_project: true` frontmatter convention from §3 of the vision doc will become the trigger for new cross-project memories once Phase 1 ships.

## Operational backlog (delta from s29)

- ✅ ~~Game-PC tailnet join~~ (shipped, 100.95.66.128)
- ✅ ~~Bridge tooling on tailnet hostnames~~ (commit `7223afe`)
- ✅ ~~Cert SAN refresh~~ (out-of-band, mkcert regen)
- ✅ ~~Game-PC one-click bootstrap~~ (commits `645e041`, `1a43e67`, `4c2514d` + desktop .lnk via bridge-task)
- ✅ ~~Cross-Claude statusline parity~~ (Legion done, Peer merged, Game-PC merged)
- ⏳ **Peer learning-sync vision ack** — async; will land via bridge.
- ⏳ **Cross-Claude learning sync Phase 1** — schema agreement + filter contract. Next session candidate (high-value but not blocking League work).
- ⏳ **Cloud routine deadline 2026-05-10** — 8 days. The s30 push covers everything through `1542af1`.
- ⏳ **Game-PC `/process-bridge-tasks` slash-command deploy** — currently MANUAL one-time copy from `/agent/` to `~/.claude/commands/`. Should be folded into `gamepc_boot.ps1`'s pull list. Low-priority (works today, deploy is one-time-per-machine).
- 🟡 **Tiered vision** — still 🟡, unchanged from s29.

## Next-session candidates (ranked)

1. **League of Legends work on RC** — operator's stated next focus. Substrate complete; nothing infra-blocking.
2. **Cross-Claude learning sync Phase 1** — agree on `cross_project: true` frontmatter + lesson schema with Peer. Small doc PR each side. Pre-req for Phase 2 (sync agents).
3. **`/process-bridge-tasks` auto-deploy in `gamepc_boot.ps1`** — fold the slash-command into the agent pull list. ~5min change.
4. **Cert SAN doctrine** — when next regenerating any RC cert, default-include all three Legion identity forms (LAN IP, tailnet IP, tailnet short hostname, tailnet FQDN). Could codify in a `tools/regen_rc_cert.ps1` helper if it gets done more than once.
5. **CLAUDE.md sync** — the post-2026-04-19 topology section still names `192.168.8.230` / `192.168.8.237`. With three stable tailnet identities, the doc could lead with `legion-rc` / `gamepc-rc` and treat LAN IPs as parenthetical fallback. Low priority.

## Bootstrap for next session

1. Read `CLAUDE.md` (frozen list + restart workflow)
2. Read this hand-off (s30) + s29
3. `git status` — push ahead of 2026-05-10 cloud-routine fire if not already pushed by s30 wrap
4. **Bridge state to check before doing cross-project work:**
   - `cat ops/runtime/bridge_monitor_state.json` — confirm sidecar is ticking
   - Look for `kind=ack` from Peer on the learning-sync vision (search bridge log for `summary~="cross-Claude sync vision"`)
   - If Peer has shipped Phase 1 schema doc on their side, read it before starting RC's Phase 1 work
5. **For League work**: substrate is invisible — just code as normal. The bridge auto-flow on Game-PC handles dispatched tasks transparently; operator-typed `bridge_task.py --target gamepc ...` calls work without further setup.

---

# s31 hand-off — 2026-05-02 20:58 (Phase 2 complete + dashboard OWNED fix + cron echo silenced)

> Long arc-completing session driven by mid-game ops. Phase 2 of the
> cross-Claude learning sync went from skeleton to fully-roundtripped
> (lesson sent → Peer classified 'applied' → ack ledgered) in ~20 min.
> Then live-game tutoring drove three real fixes: dashboard OWNED panel,
> rune writer Phase Rush stale data, and the per-tick echo loop in the
> bridge_fetch hook. **4 new commits, all pushed-pending.**

## What just shipped this session (in order)

| Commit | Type | Summary |
|---|---|---|
| `06b2454` | feat(bridge) | Phase 2 receiver + sender wiring. `core/lessons_receiver.py` (~280 LOC) — schema_version + does_not_apply_when auto-gates inline, post_decision() writes provenance memory + MEMORY.md pointer + acks via `bridge.send()`. `core/lessons_sender.py:send_now()` replaces dry-run with real `bridge.send()` + lessons_sent.jsonl ledger writes. CLIs at `tools/lessons_pull.py` / `tools/lessons_post.py` / `tools/lessons_send.py`. End-to-end smoke verified: opted `reference_os_replace_winerror5` in via `cross_project: true`, sent → Peer classified 'applied' (tooling/infra/config) → wrote `synced_8964b21fc86d.md` → acked with `took: true`. Ledger flip recorded. |
| `3a449a8` | fix(dashboard) | `web/js/dashboard.js:1649` — OWNED panel falls through to `p.owned_items` (array) when string forms (`items_display`/`items`) absent. Coach files don't populate string forms; only liveclient_summary writes the array. Edge needs Ctrl+F5 to pick up the new JS bundle. |
| `9c3121e` | fix(bridge) | `tools/bridge_fetch.py` UserPromptSubmit hook drops self-authored entries (`source == 'legion'`). Stop hook posts every legion response back to bridge log; previous `bridge_fetch` re-surfaced those legion entries on every cron tick → echo storm. Also: advance `last_seen` unconditionally so empty-peer windows don't re-fetch stale data. |
| `d86c222` | fix(runes) | Phase Rush keystone removed in patch 16.9.1; ID 8230 is now Stormraider's Surge. 6 champ entries in `rune_recommendations_{sr,aram}.json` still pointed at 'Phase Rush' (Ezreal SR + Kennen/Taliyah/Ryze/Singed/Lillia ARAM). Replaced with Arcane Comet (Sorcery, 8229) — closest functional analog. No restart needed; rune writer reads JSON per champ-select. |

## Out-of-band changes (uncommitted, runtime artifacts)

- `~/.claude/projects/.../memory/reference_os_replace_winerror5.md` — added `cross_project: true` + `applies_when` + `does_not_apply_when: [linux, darwin]` frontmatter for the smoke. Lives outside repo per memory-dir convention.
- `.claude/commands/process-incoming-lessons.md` — slash command (gitignored, on-disk only, mirrors `process-bridge-tasks` deploy pattern).
- `ops/runtime/lessons_sent.jsonl` + `lessons_received.jsonl` — append-only ledgers (gitignored under `ops/runtime/`).
- Cron jobs (in-memory, session-only): `ad48df9d` bridge tick (1m), `0a917b3b` game-monitor tick (2m). Auto-expire 7 days; die when this Claude session ends.

## Cross-Claude bridge — operational state

- Bridge tick echo: ~95% reduction. Idle ticks now show only the cron's 2-line prompt body + a one-word reply ('tick OK' or empty). Bridge-activity hook fires only when Peer or Game-PC have new content.
- Phase 2 receiver: live, tested, ready for inbound from Peer.
- Outstanding Peer task: `summary='How did you make /loop fire silently?'` (sent 20:55 via `core.bridge.send()`). Peer async; reply arrives as `kind=result` with their pattern.
- Peer findings sent earlier this session (still on bridge log):
  - Outbound visibility: Peer's receiver was pulling `legion-rc:8888/api/bridge` and not seeing RC's outbound; their fix was reading their own local `data/bridge_messages.jsonl` mirror. RC's receiver doesn't hit this — we read OUR `/api/bridge` for inbound.
  - applies_when matcher: Peer's `_applies_locally` was substring-match against the joined applies_when string; first attempt classified my smoke lesson as 'discarded' until they switched to two-stage clause-then-token-OR matching. Schema-level discussion deferred to a Phase 1 addendum.
  - MEMORY.md auto-load: applied lessons must append a pointer line. RC's receiver does this (`_append_to_memory_index`); Peer flagged it after hitting the gap on their side.

## Coach-pipeline bugs surfaced (non-blocking, deferred)

- **SR coach `ally_comp/enemy_comp` sticky-from-previous-game**. Mid-Jinx-game I observed `coach.ally_comp = ['Twitch', 'Caitlyn', 'Zoe', 'Pantheon']` (last game's comp) while the actual game was Jinx + Rakan + Shyvana + Seraphine + Mordekaiser. `clear_pregame` + `refresh` cleared `pregame` but not `ally_comp/enemy_comp`. The writer that initially populates these doesn't re-fire on game-start; only on draft event. Coach panels were blank for the first 5 minutes of the game until the engine eventually caught up. Likely needs a coach-engine reset path on `mode_key` transition into `game`.
- **Dashboard top-bar CS/KDA/win/items WS-bound fields**. Separate from the OWNED fix that just shipped. Top bar shows 'CS 0' / blank KDA / blank win even when liveclient has live values. This is a different WS push channel that's either not firing or not bound. Worth chasing as a follow-up; likely a field-name mismatch precedent (similar to `enemy_team` vs `enemy_comp`).
- **Coach action label decay**. `action: BASE LOW HP` persisted for 2+ minutes after RC backed and was at full HP. The action string is a separate field from immediate/next/watch which DO refresh; the action label has slower turnover. Cosmetic but misleading.

## RC restart state

- RC PID unchanged from session start (still PID 980 from earlier today). All commits are JS / data / standalone tool / new module changes — no frozen-file edits, no restart triggered.
- Supervisor PID 10796 (unchanged from s30).
- Bridge monitor sidecar still ticking via `core/bridge_monitor.py` per its 2s poll.

## Memory entries written this session

None — knowledge captured in code (3 fixes + Phase 2 receiver) and in this hand-off. Per CLAUDE.md memory rules, code patterns derivable from current state don't get duplicate memories.

## Operational backlog (delta from s30)

- ✅ ~~Phase 2 receiver + sender~~ (shipped, smoke-verified)
- ✅ ~~Phase Rush stale data~~ (fixed, 6 champs)
- ✅ ~~Bridge fetch echo storm~~ (filtered self)
- ✅ ~~OWNED panel binding~~ (array fallback added; needs Ctrl+F5 to activate in Edge)
- ⏳ **Peer silent-loop pattern** — async response pending
- ⏳ **Cloud routine deadline 2026-05-10** — 8 days. 4 commits this session need pushing.
- ⏳ **SR coach sticky comp bug** — defer to RC restart cycle
- ⏳ **Dashboard top-bar WS staleness** — separate WS push channel investigation
- ⏳ **Edge Ctrl+F5 for OWNED activation** — operator action when convenient
- ⏳ **Receiver gap from Peer**: 'applied lessons must also append to MEMORY.md' — RC already does this. No action needed; logged for symmetry-of-spec context.

## Next-session candidates (ranked)

1. **Push s31 commits** — cloud routine deadline 2026-05-10 (8 days). 4 commits stacked on origin/main.
2. **Peer silent-loop pattern apply** — once their reply lands via bridge, mirror their suppression mechanism. Saves ~2 lines per cron tick beyond the current echo-storm fix.
3. **SR coach sticky comp bug investigation** — read coach-engine code path on game-start transition. Likely a one-shot reset that's missing the new-game trigger.
4. **Dashboard top-bar WS staleness** — diff the field names that the WS push emits vs what the JS reads for the header pills (CS / KDA / win-pct / items panel header). Memory `reference_orphan_team_strips` documents a similar precedent.
5. **CLAUDE.md / WAKEUP_NOTES roll-up** — gradually decommission older s28-s30 hand-offs from the active queue once their findings are absorbed into memories or commits.

## Bootstrap for next session

1. Read `CLAUDE.md` (frozen list + restart workflow)
2. Read this hand-off (s31) + s30
3. `git status` + `git push origin main` (4 unpushed commits)
4. **Bridge state:** check `ops/runtime/lessons_sent.jsonl` for any new acks since session close. The Phase 2 round-trip works — any new opted-in memories will fire on next `lessons_send.py` invocation.
5. **Cron jobs are dead** — session-only, gone with this Claude session. If ongoing tick coverage desired, re-issue the two `/loop` commands.
6. **For League work**: dashboard OWNED panel needs Ctrl+F5 in Edge to pick up the JS fix. Other than that, substrate unchanged from s30.

---

## s31 late follow-up — 2026-05-02 21:08 (Peer Finding A response + 3 coach/bridge fixes)

> Three more commits after the s31 doc landed. All driven by Peer's
> Finding A reply ("Legion's endpoint only logs chatter kinds") plus
> the coach-pipeline bugs surfaced during the Jinx + Caitlyn games.
> **All three need RC restart to activate.**

| Commit | Type | Summary |
|---|---|---|
| `a4df4a4` | fix(bridge) | `dashboard/_bridge_log.py` deque maxlen 100 → 500. Peer claimed RC's `/api/bridge` GET only surfaces `note/ping/ack` — actually root cause is the deque's 100-entry cap getting flushed by high `kind=note` volume from every legion chat reply (Stop hook posts 1 note per response). Disk JSONL has 368 entries (53 task + 33 result + 11 ack + 5 ask + 265 note + 1 ping); deque was capping at 100 most-recent. Both `_bridge_log` init and `bridge_hydrate_from_disk` slice now reference the new constant. |
| `dc73303` | fix(coach) | `coach_integration._write_fields` now force-overwrites `ally_comp`/`enemy_comp` from `self._last_state` every coach call. Mid-Jinx-game we saw `coaching_data.json` had ally_comp from a prior unrelated match — the read-merge-write cycle preserved it because Claude's response shape doesn't include comps. Direct assignment (not setdefault) — current state always trumps disk. |
| `7d6483d` | fix(coach) | `coach_integration._run` now stashes `_last_gs` (raw game_reader output with unprefixed `kda`/`cs`/`level`/`gold`/`game_time_s`/`hp` keys); `_write_fields` mirrors them into `coaching_data.json`. Dashboard top-bar pills (CS / level / gold / KDA / game time) read these from the WS `/push` channel which broadcasts raw coaching JSON without liveclient overlay. Also captures `items`/`owned_items`/`enemy_team` so the OWNED-panel fix from `3a449a8` actually fires through the WS push path, not just /api/state polling. |

**Restart-required summary:**
- `a4df4a4` (deque) — module-level state captured at import; needs restart.
- `dc73303` + `7d6483d` (coach) — `coach_integration` is loaded once; needs restart.
- All three commits land cleanly via standard `restart_trigger.txt` workflow.
- Operator action when convenient between games.

**Operational status post-fix:**
- ✅ Peer Finding A understood + deque cap raised
- ✅ Coach sticky comp fixed (no more "previous game's ally_comp")
- ✅ Dashboard top-bar pills (CS/KDA/level/gold/game-time) populate via WS push
- ✅ OWNED panel populates via WS push (was previously /api/state-only)
- ⏳ **All gated on RC restart**

**Next-session candidates (revised):**
1. **RC restart** — activate the 3 coach/bridge fixes. Verify top-bar populates + ally_comp matches current game.
2. **Coach action label decay** — `BASE LOW HP` action label persists 2+ minutes after the user has based + healed. Action field is updated less frequently than immediate/next; needs a turnover trigger (maybe HP-pct-based override).
3. **Game-PC re-pull tooling** — s30 backlog item; non-urgent.
4. **Cert SAN doctrine helper** — s30 backlog; codify in tools/regen_rc_cert.ps1 if used again.
5. **CLAUDE.md / WAKEUP_NOTES roll-up** — gradually decommission older s28-s30 hand-offs.

---

# s32 hand-off — 2026-05-02 21:33 (RC restart activates s31 fixes + s27 roll-up)

> Brief between-games session. Arena run concluded (final tick: 1v6
> CONCEDE/STALL → MATCH OVER). With `liveclient` empty and the user
> back on client, the s31-late-followup gate opened. Two pieces shipped:
> RC restart to activate the three uncommitted s31 fixes, and the s27
> thread roll-up that had been queued since s31. Mid-session live-tutor
> ticks (eight `/game-monitor` invocations) generated additional
> evidence on top-bar mirror gap.

## What shipped

| Commit | Type | Summary |
|---|---|---|
| `86a3bca` | docs | Roll up s27 thread (sessions 27 → 27u, 21 sub-sessions) into one dense block: commit ledger (29 rows), final audit state, reusable patterns w/ file pointers. **−1530 lines / 76% reduction (2024 → 493 lines).** s28-s31 + s31-late preserved verbatim. Drops per-session restart PIDs, bootstrap sections, restart-verification batteries, and resolved "what's still tkinter-shaped" sub-sections. |

## RC restart state

- **Main PID 980 → 8868** via `restart_trigger.txt` (between-games window).
- `last_reload_ok=true`, `ui_pulse_age_s=1.4`, `game_poll_worker_age_s=1.5`, all
  6 dashboard endpoints 200 (`/api/state`, `/api/health/all`, `/api/decisions`,
  `/api/decisions/log`, `/metrics`, `/api/vision-state`).
- Mode: `client` (post-game, lobby).

## s31 fixes activation status

- ✅ `a4df4a4` deque maxlen 100→500 — **verified active**. `/api/bridge?limit=500`
  returns 397 entries with all 7 kinds present (note 291, task 53, result 33,
  ack 11, ask 5, ping 1, lesson 3). Pre-fix the deque would have capped at 100;
  task/result/ack would have been flushed by the dominant note volume.
- ✅ `dc73303` ally_comp force-overwrite — **loaded, latent**. Will fire on next
  coach call in a real game; current mode is `client`.
- ✅ `7d6483d` raw stats mirror — **loaded, latent**. Same — only writes to
  `coaching_data.json` during an actual game.

## Mid-session evidence collected (8 game-monitor ticks during arena run)

The arena game preceding this restart produced fresh examples of the WS-push
mirror gap that the s31 fixes target. Worth keeping in mind for the next
in-game verification window:

- **Top-bar pills (`CS`, `KDA`, `level`, `gold`, `game time`)** stayed at `--`
  for entire match except for one tick where CS partially mirrored
  (`CS 0 · 0.0/m`). Inconsistent, suggesting partial activation. Pre-fix raw
  stats only land via /api/state polling, not WS push.
- **`RIGHT NOW` pill vs `coach.action`** — diverged at least twice during the
  run. Worst case: dashboard showed `FORFEIT / SURVIVE` ("DO NOT FIGHT") while
  coach.action had moved to `CAMP PHASE` (mild conditional engage). User
  reading the dashboard would have acted on a stale, more-urgent warning.
- **OWNED panel** — populated and reflected build progress correctly during
  active rounds (5-6 items including Phantom Dancer, Hexoptics C44 marked
  "ready"). Item-build push channel is healthier than coach push channel.
- **Final `CONCEDE / STALL` tick** — dashboard + state matched perfectly. The
  push channel CAN sync; mismatch resolves on next coach call.

Next game post-restart should confirm these gaps are closed (or not).

## Audit completion (unchanged)

Tier 1 ✅ 5/5 · Tier 2 ✅ #5/#6/#6/#7 + #8 C1-C5 ✅ + #9 (avoid) · Tier 3 ✅ 5/5 · Tier 4 ✅ 3/3.

s32 was an ops/doc session, not an audit item.

## Operational backlog

- **1 unpushed commit** (`86a3bca` roll-up). Cloud routine deadline 2026-05-10
  — 8 days away. Push at convenience.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~2h stale per
  `rc_bridge_gamepc_result_age_seconds=7195`. Same Game-PC-side issue.
  Watchdog correctly surfacing; fix is on Game-PC Claude.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06
  (4 days away).

## Next-session candidates

1. **Push s32 commit** — `git push origin main` (one commit since last push).
2. **Verify s31 fixes mid-game** — next game should show top-bar pills
   populating live and coach.action / RIGHT NOW staying in sync. If gaps
   persist, the fixes need re-investigation.
3. **Coach action label decay** — s31 backlog item, unchanged.
4. **Game-PC re-pull tooling** — s30 backlog, non-urgent.
5. **Cert SAN doctrine helper** — s30 backlog.
6. **CLAUDE.md sync** — topology section still names `192.168.8.230` /
   `192.168.8.237` LAN IPs as canonical; tailnet hostnames could lead.
   Low priority.

## Bootstrap for next session

1. Read `CLAUDE.md` (frozen list + restart workflow).
2. Read this hand-off (s32) + s31 + s31-late.
3. WAKEUP_NOTES is now 76% smaller; s27 thread is one block at top, then
   s28-s32 chronologically.
4. **In-game verification owed:** when the next real game starts, confirm
   the top-bar pills populate (CS / KDA / level / gold / game time) and
   that `coach.action` matches `RIGHT NOW` continuously, not just on
   sporadic ticks. If still desynced, the WS push channel needs a
   separate fix beyond `7d6483d`.

## s32 in-game verification result (2026-05-02 21:45) — `7d6483d` partial

Live arena verification (Kai'Sa, 65% WIN, round 8 → death at round 24)
surfaced that `7d6483d` only fixes the SR path:

- ✅ `a4df4a4` deque maxlen 100→500: confirmed live (`/api/bridge?limit=500`
  returns all 7 kinds, 397 entries)
- 🟡 `7d6483d` raw stats mirror: **only patched `coach_integration.py:_write_fields`
  (SR path)**. Per-mode coaches in `coaches/*.py` write their own coaching JSON
  files without the mirror block. Disk inspection during live arena game:

  | File | game_time_s | cs | kda | level | gold |
  |---|---|---|---|---|---|
  | `coaching_data.json` (SR) | – | – | – | – | – |
  | `data/arena_coaching_data.json` | ✓ | – | – | – | – |
  | `data/aram_coaching_data.json` | ✓ | – | ✓ | – | – |
  | `data/brawl_coaching_data.json` | – | – | – | – | – |

  Dashboard JS at `web/js/dashboard.js:2647-2675` reads `p.cs / p.kda /
  p.gold / p.game_time_s` from the WS push payload (which is the
  per-mode coaching JSON). When those fields are missing, the
  `if (typeof p.cs === "number")` guards hide the pills → `--` symptom.
  `/api/state` showed all values populating correctly because state-builder
  overlays liveclient via a different code path; the WS push reads file
  content directly.

  **Fix scope for next session:** lift the mirror block out of
  `coach_integration._write_fields:1076-1090` into a shared helper
  (e.g. `core/coaching_data_lock` already imports here) or duplicate it
  into each mode coach's write path. Verify per-mode by disk inspection
  during a live game in each mode.

- 🟡 `dc73303` ally_comp force-overwrite: not verified in this run
  (arena's coach text strip showed correct partner names, but `ally_comp`
  array on `/api/state` stayed `None` — likely arena uses the partner
  name instead of an ally_comp array). SR/ARAM verification still owed.

## Dashboard ↔ coach action mismatch (separate from 7d6483d)

Mid-arena observed multiple times: `coach.action` field on `/api/state`
diverged from `RIGHT NOW` pill on dashboard. Direction varied — sometimes
dashboard ahead (next coach call refreshed it before /api/state caught up),
sometimes API ahead (cached coaching JSON pre-empts the API overlay). Not
addressed by any current commit. Probably the same root cause as the
mirror gap: state-builder overlay path vs WS push path read different
sources at different cadences. May resolve naturally if the mirror fix
lifts everything onto a single source of truth.

## Coach action label decay — investigation scope (2026-05-02 22:00)

s31/s32 candidate "BASE LOW HP action label persists 2+ minutes after
based + healed" was scoped (read-only, no code change yet). Root cause:
`coach_integration.py:_write_fields` does `current.update(fields)` —
which only overwrites `action` when the parsed Haiku response contains
an `Action: X` line. Haiku occasionally returns responses missing the
action field (today's 22:00 tick observed `action: "I NEED TO FLAG A
CRITICAL ISSUE WITH THIS SCENARIO:"` — clearly a meta-comment that
slipped past the parser). When a clean response lands without action,
the prior value survives → 2+ minute staleness symptoms.

Two fix approaches for next session:

1. **Always-clear** (~3 LOC): in `_write_fields` after `current.update(fields)`,
   explicitly clear `current["action"] = ""` when `"action" not in fields`.
   Forces every coach response to either set or clear. Side effect:
   transient empty action between calls.
2. **HP-premise check** (~10 LOC): if existing action contains "LOW HP" /
   "BASE" / "RECALL" and `_last_gs.hp_pct > 70`, invalidate. Targeted but
   needs an action-text → premise-condition mapping. More surgical.

Same pattern applies to per-mode coaches (arena/aram/brawl) which have
the same structure — `current.update({...})` writes whatever the prompt
parsed, no decay. Could be lifted into the same `_base_coach.py` helper
module as a `_clear_stale_action(payload, gs)` companion to
`mirror_live_stats`.

## s32 fix shipped 2026-05-02 21:55 — mirror_live_stats helper (c58e689)

Generalizes the SR-only s31 mirror block into a 4-line helper applied
to all per-mode coaches:

- `coaches/_base_coach.py` — added `mirror_live_stats(payload, state)`:
  None-skip writes for `cs / kda / level / gold`, plus mapping
  `state['game_seconds']` → `payload['game_time_s']`.
- `coaches/arena_coach.py:366` — calls `mirror_live_stats(current, state)`
  after the `current.update({...})` block in `_run_round`.
- `coaches/aram_coach.py:752` — same pattern in `_run_coach`.
- `coaches/brawl_coach.py:355` — same pattern in `_run_coach`.

**Activation gated on RC restart between games.** SR path
(`coach_integration.py:_write_fields`) was already patched in `7d6483d`
and stays untouched.

After restart, mid-game verification owed: capture `data/{arena,aram,
brawl}_coaching_data.json` during play and confirm `cs / kda / level /
gold / game_time_s` all populate. Dashboard top-bar pills should show
real values instead of `--`. If still `--`, the WS push channel needs
deeper inspection (cache invalidation, mtime detection in
`agents/agent2_backend/file_ingest.py:_check_one`).

## c58e689 ACTIVATED (RC restart 2026-05-02 22:04, PID 8868 → 10452)

Triggered between full arena games (mode=client, liveclient empty).
Restart verification clean: `last_reload_ok=true`,
`ui_pulse_age_s=0.4`, `game_poll_worker_age_s=1.0`, all 6 dashboard
endpoints 200, `from coaches._base_coach import mirror_live_stats`
loads cleanly.

Mid-game verification still owed. Next arena/aram/brawl run is the
test window. If pills populate as expected, this thread closes; if
still `--`, drop down to file_ingest mtime detection or WS push
fanout.

---

# s33 boot — 2026-05-02 22:13 (session-start stub)

> Fresh session ~9 min after the s32 c58e689 activation restart. RC
> running PID 10452, supervisor 10796 (unchanged since s28). Nothing
> shipped yet — this entry is the open-thread carry-forward.

## Bridge polling armed

- Set up session-only cron `02fb5bef`: `*/1 * * * *` → `/process-bridge-tasks`.
  Auto-expires in 7 days; dies with this Claude session. Initial run
  showed 0 pending tasks for legion. Game-PC bridge gauge ~2 min stale
  per `rc_facts` (`Last gamepc bridge result: 130s ago`) — healthy.

## Carried forward from s32

1. **Mid-game verification owed for c58e689** — next arena/aram/brawl
   run, capture `data/{arena,aram,brawl}_coaching_data.json` and confirm
   `cs / kda / level / gold / game_time_s` populate live. Dashboard
   top-bar pills should be real numbers, not `--`. If still `--`, drop
   into `agents/agent2_backend/file_ingest.py:_check_one` mtime detection
   or WS-push fanout.
2. **Coach action label decay** — scoped in s32 (197a71b). Two fix
   approaches drafted: always-clear (~3 LOC) vs HP-premise check
   (~10 LOC). Same bug exists in per-mode coaches (arena/aram/brawl) —
   could lift into a `_clear_stale_action()` companion to
   `mirror_live_stats` in `coaches/_base_coach.py`.
3. ~~**Push pending**~~ — false alarm; `git log origin/main..HEAD` empty
   at session start. All s32 commits already on remote. Cloud routine
   deadline 2026-05-10 (8 days) is covered.
4. **dc73303 ally_comp force-overwrite verification** — still owed in a
   real SR/ARAM game (arena run only had partner-name string, no array).
5. **Dashboard ↔ coach action mismatch** — separate from the mirror
   fix; may resolve naturally once mirror lifts everything onto a single
   source-of-truth read path. Re-check after next game.

## Bootstrap for next session

1. Read `CLAUDE.md` (frozen list + restart workflow).
2. Read s32 + s33 boot stub.
3. `git status` — likely 6 unpushed commits unless this session pushes.
4. **No restart needed** — c58e689 is already live (PID 10452,
   `last_reload_ok=true`). Just wait for the next League/arena game.

## s33 idle window — 22:13 → 22:22 (9 cron ticks, no inbound)

- Bridge cron `02fb5bef` fired ~9 times, every result `count=0`. Game-PC
  bridge gauge crept 130s → 692s (~11.5 min stale). Within normal range
  for an idle window — Game-PC LCU still `phase=Lobby`, Liveclient relay
  empty. No game queued.
- Mid-game verification of c58e689 / dc73303 / coach-action mismatch
  remain queued; nothing to test until operator drops a game.
- No commits, no restarts, no memory writes this window. RC state
  unchanged: PID 10452 alive, mode=client, supervisor 10776.

## s33 backlog drain — 22:34 (2 fixes shipped, 4 already-done audit)

Operator instruction "continue with all backlog". Six items inventoried;
four discovered as already-shipped, two implemented:

| Type | File | Summary |
|---|---|---|
| fix(coach) | `coach_integration.py:1115` | Action label decay — `if "action" not in fields: current["action"] = ""` after `current.update(fields)`. SR coach only; per-mode coaches already do `fields.get("action", "").upper()` which clears stale state on missing field. Closes the s31/s32 "BASE LOW HP persists 2+ minutes" bug. |
| feat(bridge) | `dashboard/routes_bridge.py:211` | `/api/bridge/messages` route alias on `_serve_bridge`. Peer uses contract path; RC kept legacy `/api/bridge`. Now both resolve. Closes s28 path-name asymmetry item. |

Already-done audit (no action required):
- **Push pending** — false alarm; `git log origin/main..HEAD` empty at
  session start. All s32 commits already on remote.
- **`/process-bridge-tasks` auto-deploy in `gamepc_boot.ps1`** — already
  shipped commit `0943827`; `process-bridge-tasks.md` in the SLASH_COMMANDS
  pull array; allowlist in `dashboard/routes_static.py:126` covers it.
- **Cert SAN doctrine helper** — `tools/regen_rc_cert.ps1` already
  exists with the canonical 6-name SAN list; CLAUDE.md references it.
- **CLAUDE.md topology refresh** — the doc already leads with tailnet
  hostnames + has the explicit "Prefer tailnet hostnames in new code"
  guidance; LAN IPs already parenthetical fallback.

**Restart-required summary:** both new fixes need RC restart to activate
(coach_integration loaded once; routes_bridge loaded once). Operator-driven
between games via standard `restart_trigger.txt` workflow.

**Mid-game verification owed (post-restart):**
- Watch `coach.action` in `data/coaching_data.json` during SR play —
  prior "stuck on BASE LOW HP" should now turn over to "" between calls
  when Haiku omits the action line.
- `curl -k https://127.0.0.1:8888/api/bridge/messages?limit=10` should
  return 200 with the same payload as `/api/bridge?limit=10`. Peer can
  drop the path-asymmetry workaround once they confirm.

## s33 backlog round 2 — 22:54 (RC restart + arena advisor + Game-PC re-pull)

Operator restarted RC ("restart rc") between games. Activations:
- ✅ `0302fc7` action-clear: live for next SR coach call
- ✅ `0fcf102` `/api/bridge/messages` alias: smoke-tested live (returns
  same payload as `/api/bridge`); Peer can drop their path-asymmetry
  workaround whenever they re-fetch RC's contract spec
- PID 10452 → 12140 (clean, `last_reload_ok=true`)

Then operator: "continue with all backlog". Two more items shipped:

**c58e689 verified (post-arena game disk inspection):**
`data/arena_coaching_data.json` showed `kda='3/6/12'`, `level=17`,
`gold=300`, `game_time_s=1352.47` — all populating ✅. `cs` is
correctly absent because `_parse_arena_state` doesn't emit it (arena
has no minion CS — confirmed at `arena_coach.py:545-562`). Top-bar
should hide that pill cleanly. **Thread closes for arena**; SR/ARAM
verification still owed.

**Arena per-round item advisor (`f05c4de`):**

The "items always the same recommendation" bug the user surfaced
mid-arena: arena coach's `current.update({...})` never touched
`item_build`, so the curated champ-select build (joined `full_build`
from `aram_champion_builds.json`) was frozen across all rounds and
opponents.

Shipped `coaches/_arena_item_advisor.py` (193 LOC):
- Pure rule-based, no Haiku
- Reads `aram_champion_builds.json` + DDragon tags
- Filters owned items via substring dedup (ARAM idiom)
- Counts alive opponents' tank/healer types
- Anti-tank pivot: tanks ≥ 2 → push first matching anti-tank item
  (Lord Dominik's, Mortal Reminder, Black Cleaver, Liandry, etc.)
  to position 0
- Anti-heal pivot: healers ≥ 2 → push first antiheal item
  (Mortal Reminder, Executioner, Morellonomicon, Bramble, etc.) to
  position 0
- Returns top 6, [] on unknown champion (coach leaves item_build
  untouched)

Hooked into `arena_coach._run_coach` after `current.update(...)`,
guarded by try/except. RC restart 12140 → 10028 activated.

Defaults chosen (called out to operator at decision time):
- Healer threshold: 2+
- Finished items only (no components)
- 6-item cap
- `is_next_opponent` punted (parser at arena_coach.py:524 sets False
  unconditionally; using all-alive-opponents as proxy for next 1-3
  rounds since arena pairings rotate)

**Known v1 gap:** When champion's `full_build` doesn't contain any
matching anti-X item, the pivot is a no-op. E.g. Caitlyn vs 4 healers
keeps Lord Dominik's at position 1 even though her `vs_healing` recipe
in JSON says "Mortal Reminder replaces Lord Dominik's if 2+ sustain
enemies". Fix needs a substitution table or vs_X recipe parser. v2
followup.

**Game-PC bridge tooling re-pull dispatched (`task-6d7285cef438`):**
Asks Game-PC's `/loop` Claude to re-run `gamepc_boot.ps1`, which
self-pulls `tools/bridge_*.py` from `https://legion-rc:8888/agent/`
and normalizes the legacy `192.168.8.230` LAN-IP refs to `legion-rc`
tailnet hostname. Closes the s30 backlog item. Result will land async
via bridge.

**Backlog state:** What's left and genuinely actionable next session:
- ⏳ Mid-game verification of `dc73303` (ally_comp force-overwrite) —
  needs SR or ARAM game (arena run earlier didn't exercise the
  ally_comp array; arena uses partner-name string)
- ⏳ Dashboard ↔ coach action mismatch — needs in-game observation
- ⏳ Arena advisor v2 — vs_X recipe substitution for cases where
  full_build lacks the pivot item; augment-aware reranking; component
  recommendations when gold < 1500g
- ⏳ Peer silent-loop pattern — async, awaiting Peer bridge reply
- ⏳ Cross-Claude learning sync Phase 1 — schema doc agreement with Peer
- ⏳ SR coach sticky comp on game-start — partially mitigated by
  `dc73303`; deeper fix would reset on `mode_key` transition into game
- ⏳ Tiered vision calibration — needs in-game frame
- ⏳ Push channel for bridge inbox — touches frozen `dashboard/_bridge_log.py`

## s33 round 3 — 23:25 (Kraken anchor + arena v2 + Peer dispatches + GPC chatter discipline)

**Kraken anchor — two surfaces audited:**

User observed Kraken Slayer suggested on "nearly all AD champs". Two
sources audited and fixed:

| Commit | File | Change |
|---|---|---|
| `b400e42` | `coach_integration.py` | CHAMPION_PROFILES — replaced 2 over-cites: Nilah (`BotRK + Kraken+PD` → `BotRK + Bloodthirster + Phantom Dancer`); Miss Fortune (`Lethality + Kraken (anti-tank)` → `Lethality + Lord Dominik's (vs tanks)`). Kept Zeri/Varus/Kalista where Kraken is genuinely core (on-hit/AS scaling). |
| `f978d76` | `aram_coach.py:232` | The bigger lever — every ARAM coach call reads "(e.g. Infinity Edge, Kraken Slayer)" as the example pair, biasing Haiku toward Kraken via recency anchoring. Swapped Kraken → Bloodthirster. Single-token change with broad effect. |

Both gated on RC restart (arena_coach + aram_coach loaded once). Activated
in this session's restart cycle.

**Arena advisor v2 — substitution support (`bb3eb82`):**

v1 (f05c4de) anti-heal pivot only re-ordered items already in
`full_build`. Caitlyn's curated build has Lord Dominik's Regards but
no Mortal Reminder, so vs 2+ healers the pivot was a no-op.

v2 adds `_HEAL_SUBSTITUTIONS` map — when build LACKS any antiheal,
swap a build item to its antiheal equivalent before pushing to front.
Currently one entry: `Lord Dominik's Regards → Mortal Reminder`
(universally favorable swap — same anti-armor role + adds Grievous
Wounds). New helpers: `_has_match()`, `_substitute_in_build()`.

Smoke pass:
- Caitlyn vs 4 healers: Mortal Reminder #1 (was no-op)
- Caitlyn vs 4 tanks: LDR #1 (no regression)
- Mixed lobby: Mortal Reminder wins (heal pivot last; Mortal IS anti-armor)
- Vayne vs healers: existing Mortal Reminder promoted (no sub needed)

Scope intentionally narrow — AP substitutions deferred (typically
inserts, not swaps); tank subs skipped (most builds already include
anti-tank).

**Peer dispatches:**
- `kind=ask` sent: please post `kind=result`/`kind=ack` when finishing
  tasks (with `in_reply_to` when applicable). Lets Legion see Peer's
  task lifecycle.
- `kind=note` sent: continue with current Peer-VIP work; the ack-request
  applies going forward.
- Both async; replies will surface in next prompt's bridge fetch.

**Game-PC chatter discipline (`task-7bd22d1391e9` — applied):**

Game-PC's `/loop` was posting intermediate thinking ("Let me report
back to Legion", "Nothing on Game-PC is actively posting...") in
addition to the actual result. Suggested they pull Legion's canonical
`process-bridge-tasks.md` skill to mirror our "exit silently on empty"
discipline. They confirmed at 23:22:19: "applied: canonical
process-bridge-tasks.md fetched and installed". Watch for tighter
behavior on subsequent ticks.

**RC state:**
- 3 restarts this session: 10452 → 12140 (s33-backlog-fixes) → 10028
  (s33-arena-advisor) → 176 (s33-kraken-audit) → 8120 (s33-aram-anchor-and-arena-v2)
- All clean, all `last_reload_ok=true`
- Supervisor still 10796 (unchanged since s28)

**Session commit ledger (chronological):**

| Commit | Type | Summary |
|---|---|---|
| `0302fc7` | fix(coach) | SR action-clear when Haiku omits field |
| `0fcf102` | feat(bridge) | `/api/bridge/messages` alias for Peer contract |
| `ba4dabf` | docs | s33 boot stub + idle window |
| `f05c4de` | feat(arena) | per-round item advisor v1 |
| `6997bf0` | docs | s33 round 2 (restart, c58e689 verify, advisor, GPC re-pull) |
| `b400e42` | fix(coach) | Kraken anchor — 2 CHAMPION_PROFILES audited |
| `f978d76` | fix(coach) | ARAM Kraken example → Bloodthirster |
| `bb3eb82` | feat(arena) | advisor v2 — substitution support |
| (this) | docs | s33 round 3 |

8 commits, all pushed to origin/main.

## s33 backlog item — UI

- **Pre-game lobby top-bar pills** — when on the lobby page (`mode_key=client`,
  `lcu.phase=Lobby` or `Matchmaking`), the dashboard's top-bar pills include
  CS / KDA / level / gold / game-time pills that aren't meaningful pre-game.
  They should hide when no live game is in progress. Likely a JS-side
  visibility gate keyed off `liveclient_present` or `lcu.phase` in the
  lobby/matchmaking view-router. Captured 2026-05-02 mid-session per operator
  observation.



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
  - **Partial fix shipped `baee8c7` (s33)** — `web/js/dashboard.js` early-return
    in `renderHeader(p)` hides `lvl-pill / vis-pill / ult-pill / cs-pill /
    gold-pill` and blanks `gameTime` when `state.mode === "client"`.
    Needs Ctrl+F5 in Edge to activate.
  - **Followup observed 2026-05-03 00:50** — operator still sees Zoi (champion
    pill?), gametime, cs, vs, gold on lobby page. Either (a) Edge hasn't
    Ctrl+F5'd to pick up `baee8c7`, or (b) there's a "Zoi" pill (likely the
    champion-name pill — separate DOM element not in baee8c7's scope) that
    needs the same `state.mode === "client"` gate. Audit `web/index.html`
    for any other pill IDs in the top bar; extend the `inGamePills` array
    in `renderHeader(p)`. UI-dev note for next session.

## s33 round 4 — build data refresh (patch 26.9)

Operator request: research arena/aram-mayhem/SR itemization for current
patch + update base builds for all champs (multi-source comparison).

**Phase 0 — Research (4 docs):**
- `docs/ARENA_META_RESEARCH_2026-05-02.md` — Arena Season 2 launch,
  augment-level system, anvil RNG breaks linear full_build schema
- `docs/SR_ITEMIZATION_CHANGES_2026-05-02.md` — Mythic system gone since
  V14.1; Opportunity + Trailblazer removed in 26.9; Statikk Shiv hybrid
  AD/AP rework; Voltaic Cyclosword ability-trigger; Doran's Bow + Helm +
  Gluttonous Greaves added. Patch URL slug is `26-9` not `16-9`.
- `docs/ARAM_MAYHEM_RESEARCH_2026-05-02.md` — Permanent separate queue;
  AS cap 5.0; per-player augments; Mayhem-only items (Atma's Reckoning,
  Rite of Ruin, Sword of Blossoming Dawn, Stat Bonus); KIWI internal
  name maps to MODE_ARAM in RC currently — Mayhem-aware coach path is
  a separate followup.
- `docs/BUILD_REFRESH_STRATEGY_2026-05-02.md` — Phased plan; only
  aggregator A/aggregator K/aggregator J+aggregator C survive automated fetch; existing
  cmd_aram_builds() silently no-ops because aggregator B API is now 403.

**Phase 1 (multi-source top-30 per mode):** 3 parallel agents, ~25 min each.
| Agent | Champs | Source | Issues found |
|---|---|---|---|
| SR top-30 | 31 | aggregator A + aggregator C cross-ref | Hexoptics on Ashe/Caitlyn (later confirmed legitimate per DDragon dual-IDs) |
| ARAM top-30 | 30 | aggregator K + aggregator A | Clean (pre-filtered Hexoptics from Senna) |
| Arena top-30 | 34 | aggregator J | Smolder Galeforce reference text (cleaned) |

**Phase 2 (next-30 single-source):** 3 parallel agents.
| Agent | Champs | Source | Issues |
|---|---|---|---|
| SR next-30 | 30 | aggregator A | Clean (no Opportunity/Galeforce in any 26.9 build) |
| ARAM next-30 | 40 | aggregator K | Clean (Naafiri/Pyke/Talon/Yuumi got default vs_X swaps) |
| Arena next-30 | 29 | aggregator J | 6 stale Opportunity/Galeforce refs (substituted to Voltaic Cyclosword / Phantom Dancer) |

**New tooling shipped this round:**
- `scripts/validate_build_data.py` — cross-mode item contamination guard.
  Respects DDragon dual-IDs (Hexoptics 2523 vs 222523, Sundered Sky
  6610 vs 226610, Overlord's Bloodmail 2501 vs 447111 — same display
  name, different IDs per map). Auto-detects mode from `_meta.scope`.
- `scripts/merge_refresh_builds.py` — folds phase JSONs into canonical
  files with field-preserving merge.
- `scripts/parse_external_arena.py` — Phase 2 reusable arena parser
  (Nimble extract → schema fields).

**Canonical files state after merge (`a2fce4c`):**
- `aram_champion_builds.json` — 167 entries (66 updated, 4 new)
- `sr_champion_builds.json` — 73 entries (was 18 — gained 56 new from Phase 1+2)
- `arena_champion_builds.json` — **NEW** 63 entries with arena-specific
  schema (`ideal_core_priority` + `prismatic_priority` +
  `build_changing_augments` + `best_duos` + `arena_meta`)

**Arena coach wire-in (`590af3e`):**
`coaches/_arena_item_advisor.py` now reads from
`arena_champion_builds.json` first (uses `ideal_core_priority`), falls
back to `aram_champion_builds.json` `full_build` for the ~100 champs
not yet in arena dataset. Anti-heal + anti-tank pivots + LDR→Mortal
substitution all still work on either path. Activated PID 8120 → 4272.

**Phase 3 IN FLIGHT:** 3 parallel agents fetching missing tail champs:
- SR tail: 103 champs (aggregator A single-source)
- ARAM tail: 7 champs (aggregator K — small gap)
- Arena tail: 109 champs (aggregator J single-source)
~30 min total. Will land in `data/meta_build/refresh_2026-05-02/{sr,aram,arena}_tail.json`,
then re-run merge_refresh_builds.py.

**My over-correction documented:** Earlier this session I removed
"Hexoptics C44" from Caitlyn/Jhin/Varus/Zeri ARAM full_build thinking
it was arena-only. Per DDragon `data/meta/ddragon_items.json`,
Hexoptics has TWO ids: 2523 (SR/ARAM-available) and 222523 (Arena-only).
Same for Sundered Sky and Overlord's Bloodmail. Stats sites referencing
these in SR/ARAM builds mean the SR/ARAM variant. The cleanup outcome
is fine since Phase 1 ARAM data has alternative builds for those champs,
but the contamination filter is now corrected (only items with NO
SR/ARAM-available alias-id are flagged: Reaper's Toll, Arcane Sweeper,
Goliath, Mystic Punch, Shardblade, etc.).

**Session commit ledger (s33 round 4 additions):**

| Commit | Summary |
|---|---|
| `66520a0` | docs: 4 itemization research docs + surgical Hexoptics fix in ARAM |
| `a2fce4c` | feat(builds): patch 26.9 build data refresh — SR + ARAM + Arena |
| `590af3e` | feat(arena): advisor reads from arena_champion_builds.json (wire-in) |

11 commits this session, all pushed.

**Backlog after Phase 3 lands:**
- Mayhem-specific build file (4th canonical) — research done in
  ARAM_MAYHEM doc; needs `mayhem_champion_builds.json` + Mayhem coach
  routing change (KIWI → Mayhem coach not ARAM coach)
- All standard mid-game verifications still owed
- Pre-game lobby top-bar pill hide
- Arena `is_next_opponent` parser fix (advisor v3 enhancement)
- Arena augment-aware reranking (advisor v3)

---

## s34 hand-off — 2026-05-03 (bridge-watcher Phase 4-5 + /done family)

Single-day session, two arcs.

**Arc 1 — Bridge-pending dashboard triage (Phase 4-5):**
- `d499239` — `view-bridge-pending` sub-page lists watcher escalations
  (task_id / from / kind / summary / reason / prompt). 20s poll,
  idempotent sig-based renders. Menu badge shows pending depth.
- `164c649` — `routes_bridge_pending_actions.py` (sibling of frozen
  `routes_bridge_pending.py`) handles `POST /api/bridge/pending/<id>/
  {accept,defer,dismiss}`. accept=stamp claimed_by; defer=ttl+24h;
  dismiss=remove (watcher's processed_ids dedup prevents re-add).
  Smoke-tested all paths + 400/401/404.

**Arc 2 — Fleet health + /done ritual:**
- `1557e8f` — `routes_health_peer.py` `POST /api/health/peer/<node>`
  (Bearer auth, mirrors `/api/bridge/inbox`). `/api/health/all` rollup
  gains `peers` section. `tools/bridge_watcher_health_publisher.py`
  sidecar (60s poll → POST, exponential backoff). `/done` skill picks
  up `/process-incoming-lessons` to drain inbound lessons.
- `803a29f` — publisher script on /agent/ allowlist.
- `080c10c` — `/done` skill: auto-commit + push + wrap checks +
  ready-for-/clear banner. Sibling of `/wrap` with auto-commit guard.
- `s34-final` — `done-gamepc.md` + `done-peer.md` peer variants. Game-PC
  variant skips git (no repo, agents pull from Legion). Peer variant
  mirrors Legion structure with `<peer-vip-root>` placeholder for
  portability.

**Doc syncs:** `8cc602d` adds `/api/bridge/pending` GET+POST to CLAUDE.md
endpoint listing. `983e9f6` ROADMAP marks read-only panel shipped.

**Bridge ops:**
- Game-PC + Peer already had `--enable-auto-action-lanes read` — opt-in
  dispatch was a no-op, both confirmed via bridge replies.
- Publisher deploy dispatched to both peers; results pending session-end.

**Things tomorrow-you should NOT redo:**
- Lobby top-bar pill fix is in `bb4cff9` (already shipped earlier today,
  before the WAKEUP ledger note about it). Don't re-investigate.
- `--enable-auto-action-lanes read` is already enabled on Game-PC + Peer.
  Don't re-dispatch.
- `RC-BootVerify-2026-05-03` is a stale one-time task that already fired
  its (failed) trigger. Operator can delete; no code action.

**Open for next sessions:**
- Mayhem coach routing (multi-day arc; research in
  `docs/ARAM_MAYHEM_RESEARCH_2026-05-02.md`)
- Bridge Watcher Phase 5+ (sliding-window counters, push notifications
  — most need frozen-file edits)
- Dashboard UI surface for `/api/health/all` peers section (currently
  API-only)
- Confirmation that peer publishers landed (deploy tasks dispatched
  at end of session)

---

## s35 hand-off — 2026-05-03 (publisher 401 fix + /done fleet rollout)

Short follow-up session — picked up s34's "publisher landed?" open item.

**Arc 1 — Game-PC publisher 401 root cause + fix:**
- Peer publisher worked; Game-PC's sent token-rejected every minute. Logs
  confirmed `health peer auth reject from 192.168.8.237` once/min.
- Root cause: `tools/bridge_watcher_health_publisher.py:_resolve_token`
  fallback chain only checked legacy aliases (`rc_peer_bridge_secret`,
  `bridge_secret`, `shared_secret`) — never the canonical
  `bridge_shared_secret` that `core/bridge.py:65` reads. Peer masked it
  because Peer-VIP has its own `core.bridge` import path that bypasses
  the fallback entirely.
- `ec5a30e` — added `bridge_shared_secret` first in the lookup chain;
  legacy aliases retained for backward compat.
- Game-PC's local file used `bridge_secret` key with the wrong VALUE
  (32-char X-RC-Token, not the 43-char canonical). Dispatched the
  canonical secret via bridge task body (transit: TLS over Tailscale,
  rest: gitignored Legion inbox + Game-PC's RC-Agent dir — same trust
  boundary as `local_paths.json` itself).
- Game-PC confirmed: publisher 401→200, age_s=10, stale=false.

**Arc 2 — /done command on peers:**
- Peer + Game-PC didn't have `/done` installed. Dispatched install tasks
  to both:
  - Game-PC: pull `done-gamepc.md` → `~/.claude/commands/done.md`
    (wrap-only variant, no git).
  - Peer: pull `done-peer.md` → `~/.claude/commands/done.md`, replace
    `<peer-vip-root>` placeholder (8 occurrences → `C:\Peer-VIP`).
- Both confirmed installed.
- `abdeb46` — `gamepc_boot.ps1` `SLASH_COMMANDS` restructured from
  string array to `{src, dst}` pair list so peer-variant skills can be
  served under their full name and land at the user-facing slash name
  without an extra rename. `/done` now persists across Game-PC reboots.

**Housekeeping:**
- Unregistered stale `RC-BootVerify-2026-05-03` scheduled task (one-shot
  with `py.exe` PATH issue same as the old `RC-PatchRefresh` bug).
  Anomaly should clear on next `rc_facts.py` probe.

**Things tomorrow-you should NOT redo:**
- Publisher token-key fallback now includes canonical key — don't
  re-investigate 401s of the same shape unless a new peer with
  no `core.bridge` and no token file is added.
- `/done` is wired into `gamepc_boot.ps1`; only Peer needs to add the
  pull to its own bootstrap (out of RC's scope; Peer-side decision).
- `RC-BootVerify-2026-05-03` deleted; if a new dated `RC-BootVerify-*`
  task appears, it's a fresh operator-created one — NOT a recurring
  resurrection.

**Open for next sessions** (from s34, still pending):
- Mayhem coach routing (multi-day arc; research in
  `docs/ARAM_MAYHEM_RESEARCH_2026-05-02.md`)
- Bridge Watcher Phase 5+ (sliding-window counters, push notifications)
- Dashboard UI surface for `/api/health/all` peers section
  (currently API-only)

---

## s36 hand-off — 2026-05-03 (Fleet UI + Mayhem P1 + Daemon Slayer engine plan)

Three arcs, two shipped + one designed:

**Arc 1 — Fleet Health dashboard sub-page (`42dd733`).** Closes the s34
"UI for /api/health/all peers" open item. Mirrors bridge-pending pattern:
view-router entry + `/api/health/peer` poll every 30s + idempotent
sig-based render. Border-left color coding for OK/STALE/DOWN/NO DATA.
Menu badge counts stale peers. Live-verified in Edge fullscreen via
Game-PC capture — both Peer + GAMEPC peers show fresh OK cards.

**Arc 2 — Mayhem Phase 1 (`32db190`).** Closes the design-recommendation
arc by FIXING A LIVE BUG: `aram_coach.py:550` checked `"MAYHEM" in
gm.upper()` against Riot's actual live string `"KIWI"` — Haiku has been
getting "ARAM coach" prompts for every Mayhem game since the queue went
permanent. New `core/mayhem_detect.py` (single-source-of-truth helper
covering KIWI/MAYHEM/ARAM_MAYHEM aliases) + `is_mayhem_mode` boolean
surfaced into coach output payload + prompt's `mayhem_tag` substitution
now actually fires. Activates next RC restart. Phase 2+ deferred.

**Arc 3 — Daemon Slayer build engine (designed, not started).** Operator
authorized full local port replacing `_arena_item_advisor` + Haiku
item-rerank logic with a dedicated process on `:8893`. Deep-dived
lolmath.net/itemop architecture: their Chrome extension is 400 bytes of
CORS-bypass rules (no backend API), entire algorithm runs as client-side
JS on Cloudflare Pages. Algorithm chunk (`14.ejgq2van4b.js`, 730KB)
contains scenario configs as cleartext object literals — regex-extractable.
DDragon = item/champion data; Riot patch notes = changelog upstream;
lolmath = scenario reference only. **Locked design**:
1. Engine name = **Daemon Slayer**
2. HTTP-only on `:8893` (WS deferred)
3. Patch cadence = on DDragon version change only (hourly poll, harvest on diff)
4. Phase 4 item priority = Top-30 first session, remaining roster segmented across following sessions

7 phases, ~6-10 weeks total; Phase 1+2+3 = ~2 weeks → first user-visible.
Full design + locked decisions in `project_daemon_slayer_engine.md`.

**Memory writes (5):**
- `reference_riot_ca_cert_install.md` — install-cert.cmd is Riot's LoL
  Game Engineering CA root, browsers need it for `:2999`, RC doesn't
- `reference_lolmath_architecture.md` — no backend API, static SPA,
  algorithm is client-side JS; full reverse-engineering is reading
  bundles not network calls
- `project_yunara_duplicate_matches.md` — Home → Recent 5 shows 3 Yunara
  rows that are ONE disconnect-reconnect match; investigate whether
  Riot's giving us separate match_ids or RC's reader is duping
- `project_lcu_pengu_pregame_postgame.md` — operator parking-lot to
  explore Pengu Loader's Discord/GitHub for richer LCU pre/post-game
  data; research-first
- `project_daemon_slayer_engine.md` — full engine design, all 4 locked
  decisions, 7-phase plan

**Things tomorrow-you should NOT redo:**
- Don't re-research lolmath's architecture — verdict in
  `reference_lolmath_architecture.md` is final: no API, just CORS shim.
  Don't waste time looking for endpoints.
- Don't rename Daemon Slayer or re-litigate the 4 locked design
  decisions — operator chose them. Re-bikeshedding costs context.
- Don't try to re-implement Mayhem detection — `core/mayhem_detect.py`
  is the canonical helper. Add new consumers (vision_tracker, etc.) by
  importing it; don't re-detect by raw string.
- Fleet UI already renders peer cards correctly — don't duplicate the
  data path. If you want extra fields (auto_actions_24h, etc.), they're
  already in `/api/health/peer` body — extend `renderFleet()` cells
  array, not the backend.

**Open for next sessions:**
- **Daemon Slayer Phase 1 step 1**: probe lolmath chunk
  `14.ejgq2van4b.js` to validate scenario records are regex-extractable
  without a real JS parser. Bounded: a few greps + a sample extract.
  If feasible → write `tools/daemon_slayer_extract.py`.
- All s34/s35 carryover items (Mayhem coach future phases, Bridge
  Watcher Phase 5+) still apply.

**Bridge state at session end:** RC PID 9740 alive, supervisor 10796,
Game-PC + Peer peer publishers OK (~10s heartbeat ages on Fleet UI).
Bridge loop verified live on both peers via liveness probe
(`task-3ff94f7dae59` round-tripped in <90s). No game in progress.

---

## s37 hand-off — 2026-05-03 (Daemon Slayer Phase 1 step 1 shipped)

One arc: probed lolmath's `14.ejgq2van4b.js` chunk, validated regex+json5
extraction is feasible (no JS parser needed), then wrote
`tools/daemon_slayer_extract.py`. Verdict ledger:

- 196/196 top-level bindings parse with substitution table + 2-pass
  spread/wrapper resolver. 172/172 champions covered, including all
  variant-bearing forms (Kayn Rhaast + Shadow Assassin, Aphelios,
  Akali, Nasus, Shaco, Udyr, Varus, Veigar).
- Live extraction shipped: `data/daemon_slayer/16.9.1/{champions,items,
  scenarios,manifest}.json` + `current.txt`. 4.6MB total.
- Three hardcoded DDragon-id aliases needed (`wukong`→`MonkeyKing`,
  `nunuWillump`→`Nunu`, `renataGlasc`→`Renata`).

**Commit:** `91f611a feat(daemon-slayer): Phase 1 data extractor`,
pushed `904e65f..91f611a main -> main`.

**Surprise findings (saved to memory):**
- lolmath shipped a major chunk reorg since the operator's design
  doc was written. The named `14.ejgq2van4b.js` is still served and
  still has scenarios, but a NEW 1.58MB chunk `0hjv4iwvdtcrm.js`
  carries 12 additional JSON.parse blocks (ARAM modifiers,
  damage-type distribution per champ, skill orders, embedded
  DDragon catalog). All pure JSON, trivially extractable. Listed
  as Phase 1.5 candidates in `reference_lolmath_extract_topology.md`.
- Chunk hashes rotate on every lolmath rebuild — discovery MUST
  be content-based, not filename-based. `statPreference:` is the
  uniquely strong anchor (175 hits in scenarios chunk, 0 elsewhere).

**Memory writes (1):**
- `reference_lolmath_extract_topology.md` — chunk topology, parser
  strategy, alias map, Phase 1.5 candidates.

**Things tomorrow-you should NOT redo:**
- Don't re-probe whether scenarios are extractable — verdict is
  proven, code is in `tools/daemon_slayer_extract.py`. 196/196
  bindings, 172/172 champions.
- Don't hardcode chunk filenames anywhere. `statPreference:` content
  anchor is the contract.
- Don't expand the alias map without proof — adding spurious
  aliases silently breaks valid champions. Add only when a real
  champion shows up in `byLolmathKey` but not `byDDragonId`.

**Open for next sessions:**
- **Daemon Slayer Phase 2**: stat-only naive Python ranker (3-5 days
  per design). Reads `data/daemon_slayer/16.9.1/*.json`, no engine
  server yet.
- **Daemon Slayer Phase 1.5 (optional)**: harvest the 12 JSON.parse
  blocks from the new lolmath chunk for ARAM modifiers + damage-type
  distribution + skill orders. Pure JSON, ~30 minutes of work.
- All s34/s35/s36 carryover items still apply.

**Bridge state at session end:** RC PID 9740 alive, mode=client,
no game in progress. Liveness probe `task-9b88bf5d18eb` dispatched
to gamepc; result ridden in banner below.

---

## s38 hand-off — 2026-05-03 (Daemon Slayer Phase 2 step 1 shipped)

One arc: Phase 2 step 1 — engine foundation. `agents/daemon_slayer/`
package shipped with data loader, scaling math, item-stat aggregator,
champion+items resolver, CLI, and 33 unit tests.

**Module layout:**
```
agents/daemon_slayer/
├── __init__.py            ENGINE_VERSION = "0.2.1"
├── __main__.py            python -m agents.daemon_slayer entrypoint
├── data_loader.py         DataSnapshot.load(patch=None) — reads current.txt
├── stats.py               CHAMPION_SCALING_RULES + ITEM_STAT_KEY_MAP (data-driven)
├── engine.py              build_champion(snap, id, level, items, mode) -> ResolvedStats
├── cli.py                 stats subcmd; dps/rank subcmds stubbed exit 64
└── tests/                 33 tests, 0.2s, all green
```

**CLI smoke:**
```
$ python -m agents.daemon_slayer stats Aatrox --level 11 --items 6692,3006
Aatrox (Aatrox) — lvl 11 — mode SR — gold spent 4000
items: 6692, 3006
  hp 1790 | armor 86 | mr 52.5 | ad 120 | as 0.977 | ms 390 ...
```
Math hand-verified across hp/armor/mr/ad/as/ms/crit/lifesteal at lvl
1, 11, 18 with diverse 1-6 item builds.

**Key design choices (saved to memory):**
- Data-table-driven extensions: add a stat = append to
  `CHAMPION_SCALING_RULES`; add an item stat = append to
  `ITEM_STAT_KEY_MAP`. Engine code never grows for new stats.
- AS combine special-case: items pct stacks alongside per-level bonus
  on base AS (not multiplicative on the leveled value).
- MS combine: explicit (base + flat) × (1 + pct).
- Mode hook present (`mode="SR"|"ARAM"|"ARENA"`) — emits a note for
  non-SR; ARAM/ARENA modifier table plug-in deferred to Phase 1.5/2.2.
- Lifesteal/spellvamp = additive pct; crit caps at 1.0 post-stack.
- DPS + rank subcmds are stubs returning exit 64 to make the unfinished
  state explicit.

**Test surface:**
- 8 data_loader tests — pointer resolves, counts match manifest, alias
  IDs resolve (MonkeyKing/Renata), missing IDs raise.
- 12 stats tests — linear scaling, AS scaling, level guards, item
  aggregation including unknown-DDragon-key passthrough.
- 13 engine tests — naked Aatrox lvl 1+18, Bloodthirster, Berserker's
  AS stacking at lvl 1+18, Eclipse AD, IE crit cap, gold spend,
  to_dict/format_table, error paths.

**Surprise findings:**
- Bloodthirster (id 3072) is +15% lifesteal in 16.9.1; the 22-prefix
  arena variant (223072) is +18%. Don't assume the prefixed IDs are
  canonical — they're augmented arena variants with stronger stats.
- Plated Steelcaps (3047) is +25 armor, not +20. Eyeball math is
  fragile; always cross-check against the actual stat block.

**Commit:** `feat(daemon-slayer): Phase 2 step 1 — engine foundation`
(pending — about to push).

**Memory writes (1):**
- `reference_daemon_slayer_engine_arch.md` — module map + extension
  points + don't-redo list + cross-check protocol.

**Things tomorrow-you should NOT redo:**
- Don't add scaling math by editing `engine.py` — the extension is
  appending a `ScalingRule` to `CHAMPION_SCALING_RULES`. Same for item
  stats via `ITEM_STAT_KEY_MAP`.
- Don't re-derive AS/MS combine math — pinned in `_combine_items` with
  a regression set across lvl 1/11/18.
- Don't re-litigate the package layout — locked at `agents/daemon_slayer/`
  with the 6 modules above. CLI sub-cmd names (`stats`/`dps`/`rank`)
  are part of the contract; renaming breaks future scripts.

**Open for next sessions:**
- **Daemon Slayer Phase 2 step 2**: ability-rotation DPS using
  scenario weights (`snapshot.scenarios(champ_id)` returns the lolmath
  early/mid/late blocks). 3-5 days per design.
- **Daemon Slayer Phase 1.5 (optional)**: harvest the 12 JSON.parse
  blocks from new lolmath chunk for ARAM modifiers + damage-type
  distribution + skill orders. ~30 minutes; useful for Phase 2 step 2
  mode-aware DPS.
- All s34/s35/s36/s37 carryover items still apply.

**Bridge state at session end:** RC PID 9740 alive, mode=client,
no game in progress. No bridge activity needed this session.

---

## s39 hand-off — 2026-05-03 (Daemon Slayer Phase 1.5 shipped)

One arc: harvested the three Phase 1.5 datasets from lolmath's data chunk
(`0hjv4iwvdtcrm.js`, 1.58MB) and merged them into the per-champion
`lolmath` block in `champions.json`. 172/172 coverage across all three
new fields.

**What's new per champion (under `lolmath`):**
- `aram_modifiers` — `{aramDamageTaken, aramDamageDealt, aramHealing,
  aramShielding, aramTenacity, aramAbilityHaste, aramAttackSpeed}`
- `damage_distribution` — `{physical, magical, trued}` (sums to ~1.0)
- `skill_order` — 18-entry list of `Q`/`W`/`E`/`R` strings

**Extractor changes (`tools/daemon_slayer_extract.py`):**
- `discover_chunk_url` → `discover_chunks(scen_override, data_override)`
  returns both URLs in a single enumeration pass; URL-keyed body cache
  (`_CHUNK_BODIES`) avoids refetching during dual-anchor scoring.
- New `extract_data_chunk(chunk, url)` reuses `_extract_json_parse_string`
  with anchors `aramDamageTaken` / `"trued":` / `["Q","E","W"` (verified
  unique in payload[:80] across all 12 JSON.parse blocks).
- `LolmathExtract` extended with 5 new fields; `build_champions_payload`
  emits the three sub-fields under each `lolmath` block.
- Manifest bumped to `phase: 1.5`, sources split into
  `lolmath_scenarios_chunk` + `lolmath_data_chunk`, counts include the
  three new datasets.
- New CLI flag `--data-chunk-url` for autodiscovery override.

**Validation:**
- All 33 engine tests still green (data_loader passthroughs new fields).
- Spot-check Aatrox/Yunara/Wukong/Renata/Nunu/KSante — values match
  lolmath's live UI (Yunara `aramDamageDealt: 0` reflects current launch
  nerf, Renata `aramDamageTaken: 1.05` reflects current nerf, etc.).
- Coverage: 0 missing across 172 champions for all three fields.

**Surprise findings:**
- Block 5 (damage distribution) keys are DDragon ids (`Aatrox`,
  `MonkeyKing`, `KSante`) — no lolmath alias dance needed for the data
  chunk. The alias map (`wukong → MonkeyKing`, `nunuWillump → Nunu`,
  `renataGlasc → Renata`) only applies to the scenarios chunk.
- Pre-existing `scenarios.json` churns on re-extract because the
  two-pass resolver's parse order is non-deterministic across runs.
  Functionally identical content; cosmetic diff. Not Phase 1.5's bug.

**Commit:** `feat(daemon-slayer): Phase 1.5 — ARAM modifiers, damage
distribution, skill orders`.

**Things tomorrow-you should NOT redo:**
- Don't re-probe the data chunk's JSON.parse blocks. The 12-block
  topology + the 3 anchors are pinned in
  `reference_lolmath_extract_topology.md` and the extractor constants
  (`ARAM_MODIFIERS_ANCHOR`, `DAMAGE_DISTRIBUTION_ANCHOR`,
  `SKILL_ORDER_ANCHOR`).
- Don't add new champion sub-fields by editing
  `build_champions_payload` ad-hoc — extend `LolmathExtract` + the
  data-chunk extractor cleanly, mirroring the Phase 1.5 pattern.
- The scenarios.json churn on re-extract is cosmetic. Don't chase it
  as a bug; if determinism matters, sort `byDDragonId` keys at emit
  time. Not currently load-bearing.

**Open for next sessions:**
- **Daemon Slayer Phase 2 step 2**: mode-aware DPS using
  `snapshot.scenarios(champ_id)` weights × Phase 1.5
  `aram_modifiers` for ARAM. Skill order can drive realistic
  ability-rotation simulation. Damage distribution informs
  armor-vs-MR build prioritization. 3-5 days per design.
- All s34/s35/s36/s37/s38 carryover items still apply.

**Bridge state at session end:** RC PID 9740 alive, mode=client,
no game in progress. Bridge unused this session.

## s40 hand-off — 2026-05-03 20:21 (Daemon Slayer Phase 2 step 2 shipped)

One arc: Phase 2 step 2 — auto-attack DPS over lolmath rotation scenarios + ARAM mode hooks.

**What shipped (commit `68d31de`):**
- `agents/daemon_slayer/dps.py` — `compute_dps()` returns `DpsResult` with weighted DPS over early/mid/late phases. Per-rotation: `attacks = basic + basicTime * AS`, `avg_dmg = AD * (1 + crit*0.75) * armor_factor * mode_dmg_mult`, weighted by lolmath rotation `weight`. Phase auto-selected from level (≤6 early, 7-12 mid, 13+ late).
- `engine.py` — added `_apply_mode_modifiers()` hook called after `_combine_items`. ARAM `aramAttackSpeed` multiplies bonus AS only (currently no champion has AS != 1 in 16.9.1 data).
- `cli.py` — `dps` subcmd: `python -m agents.daemon_slayer dps Aatrox --level 11 --items 6692,3006,3072,3031 --mode ARAM --target-armor 80`. JSON output via `--json`.
- `__init__.py` — `ENGINE_VERSION 0.2.1 -> 0.3.0`.
- 60/60 unit tests green (27 new dps + 4 mode-hook tests).

**Regression pins** in `tests/test_dps.py`:
- Aatrox lvl 1 naked early-phase DPS = 26.10 (matches hand-calc to 0.01)
- Yunara `aramDamageDealt=0` → DPS=0 in ARAM (hard-disable pin)
- Aatrox `aramDamageDealt=1.05` exactly scales SR DPS in ARAM
- 100 armor halves DPS, -100 armor amplifies 1.5x
- 5x IE clamps crit at 100%, avg per-hit = AD * 1.75

**Things tomorrow-you should NOT redo:**
- Don't add ability damage to `compute_dps` — that's Phase 4 conditional effects (formulas not in snapshot yet).
- Don't hardcode IE +40% crit damage. `DEFAULT_CRIT_BONUS=0.75` is the no-IE baseline; Phase 4 lands an effects registry that detects IE.
- Don't add per-mode aramHealing/aramShielding/aramTenacity/aramDamageTaken/aramAbilityHaste at the stat layer — they belong in their respective consumers (sustain calc, EHP calc, AH lookup), not in build_champion.

**Open for next sessions:**
- **Daemon Slayer Phase 2 step 3**: item ranker. Filter `snapshot.items` by `maps` (mode validity), `gold.total`, `into` (upgrade path); score candidates by `compute_dps` delta. CLI `rank` is still a stub.
- All s39 carryover items still apply.

**Bridge state at session end:** RC PID 9740 alive, mode=client, lobby phase. Game-PC bridge loop confirmed alive (loop liveness probe round-tripped in ~117s).

---

## s41 hand-off — 2026-05-03 20:23 (Daemon Slayer Phase 2 step 3 shipped)

One arc: Phase 2 step 3 — item ranker. CLI `rank` no longer a stub.

**What shipped:**
- `agents/daemon_slayer/rank.py` — `rank_items()` returning `RankResult` with sorted `RankedItem` rows. Filter chain: already-equipped → optional whitelist → `purchasable + gold.total>0` → mode validity (`maps[MODE_MAP_ID[mode]]`) → terminal-only (`into` empty, opt-out) → budget cap. For each survivor, `compute_dps(current+candidate)` and the delta vs. baseline is the score. `MODE_MAP_ID` = `{SR:11, ARAM:12, ARENA:30}`. Sort keys: `delta` (default) or `efficiency` (`delta_dps / (gold/1000)`).
- `cli.py` — `rank` subcmd live: `python -m agents.daemon_slayer rank Aatrox --level 11 --target-armor 80 --top 8`. Flags: `--items` (current build), `--budget`, `--top`, `--sort delta|efficiency`, `--include-components`, `--only`, `--slots`, `--mode`, `--target-armor`, `--target-mr`, `--phase`, `--json`.
- `__init__.py` — `ENGINE_VERSION 0.3.0 → 0.4.0`.
- 86/86 unit tests green (26 new rank + 60 prior).

**Regression pins** in `tests/test_rank.py`:
- Aatrox lvl 11 SR vs. 80 armor: top-5 must contain at least one of `{IE 3031, BT 3072, Stormrazor 3097, Shieldbow 6673}` (stat-only DPS finishers in 16.9.1).
- `delta = new_dps - baseline_dps` to 4 decimal places.
- Sort-by-delta and sort-by-efficiency yield non-identical orderings on the same query.
- Yunara ARAM mode_mult=0 → all deltas exactly 0; rank still produces rows with the warning note.
- 6 already-equipped raises `ValueError` (no slot for candidate).
- SR snapshot terminal candidate count in 100-300 range (175 in 16.9.1).
- Negative-delta rows have efficiency exactly 0 (no "best regression" surfacing).

**Things tomorrow-you should NOT redo:**
- Don't add Riot's actual gold-efficiency-by-stat formula here — `dps_per_1k_gold` is the simple, stable proxy. Riot stat-weights belong in a separate optional rank mode if ever wanted.
- Don't filter `into` for the *destination* item's components — DDragon's `into` field on a component points at its upgrades, which is what we use. Filtering "things components turn into" is the correct read of the design hint.
- Don't paper over the duplicate `The Collector` (3000g) ids `6676` / `667666` — that's the snapshot-side `items_index.json byName picks 22-prefixed alias IDs` issue (memory `reference_items_index_alias_ids`). Pipeline fix scheduled separately; rank surfaces both because both are in the snapshot.
- Don't add ability damage to delta math — same Phase 4 boundary as before.

**Open for next sessions:**
- **Daemon Slayer Phase 3**: HTTP server `:8893` — wrap stats/dps/rank in routes for the dashboard; coach-side consumers (item recommendation in champ-select brief / mid-game upgrade nudge).
- **Phase 2 step 4 (optional)**: full-build ranker — instead of "next item", search the 6-item Cartesian product (or beam search) for the highest end-state DPS within a gold ceiling. N×DPS × 6 gets pricey; heuristics needed.
- All s37/s38/s39/s40 carryover items still apply.

**Bridge state at session end:** RC PID 9740 alive, mode=client, lobby phase. No game this session.

---

## s42 hand-off — 2026-05-03 20:45 (Daemon Slayer Phase 3 shipped)

One arc: Phase 3 — local HTTP engine on `:8893`. Wraps stats/dps/rank
in JSON routes; snapshot loaded once at startup; index page documents
the API. Stdlib `ThreadingHTTPServer` (matches RC's `dashboard/server.py`
pattern; no FastAPI/aiohttp dep despite design doc's earlier nod —
zero new deps is the cleaner read).

**What shipped (commit `3f67550`):**
- `agents/daemon_slayer/server.py` (~390L) — `Handler`,
  `start_server(...)`, `serve_forever(...)`, `_SnapshotCache` (process-
  global single-snapshot holder; tests inject via `start_server(snapshot=)`).
- `cli.py` — `serve` subcommand: `python -m agents.daemon_slayer serve
  --host 0.0.0.0 --port 8893`. Defaults host=127.0.0.1, port=8893.
- `__init__.py` — `ENGINE_VERSION 0.4.0 → 0.5.0`.
- `tests/test_server.py` — 20 new tests (request/response over
  `urllib.request` against an in-process server on port 0). 106/106
  green total.

**Routes:**
- `GET  /`          — HTML index w/ live patch + curl example
- `GET  /health`    — `{status, engine_version, patch, champions, items}`
- `GET  /snapshot`  — patch + counts + manifest excerpt
- `POST /stats`     — `{champion, level, items?, mode?}`
- `POST /dps`       — `+ {target_armor?, target_mr?, phase?}`
- `POST /rank`      — `+ {budget?, slots?, top?, sort?,
                            include_components?, only?}`
GET equivalents accept the same fields as query params (`items`
comma-separated). All responses `Cache-Control: no-store`.

**Error mapping:**
- 400 — JSON parse failure, missing required field, bad enum value
- 404 — unknown champion or item id (KeyError from engine)
- 422 — engine ValueError (e.g. 6 items already equipped + slots=6)
- 500 — anything unexpected

**Smoke verified live (port 8893):**
```
GET /health → {"status":"ok","engine_version":"0.5.0","patch":"16.9.1",
                "champions":172,"items":705}
POST /stats Aatrox lvl 11 + Eclipse + Boots → hp 1790, ad 120, as 0.977, gold 4000
POST /dps Aatrox lvl 11 ARAM + 4 items vs 80 armor → weighted_dps 86.38,
          phase mid, mode_multiplier 1.05
POST /rank Aatrox lvl 11 + Boots vs 80 armor top 5 →
   3031 IE +25.27dps  /  3072 BT +20.15  /  2523 Hexoptics +19.29  /
   6673 Shieldbow +19.29  /  3097 Stormrazor +19.28
```

**Design choices worth pinning:**
- Bind **127.0.0.1 by default** (loopback only). Daemon Slayer doesn't
  hold secrets but no need to expose it on LAN until something else
  asks for it. CLI takes `--host 0.0.0.0` to opt in.
- Snapshot loaded once at `start_server`. Hot-reload on patch change
  is **Phase 7** (alongside the supervisor entry that runs DS as a
  separate process under `RC-DaemonSlayer` scheduled task).
- POST is the contract; GET is a developer/test convenience. Both
  share the same `_route_*` handlers (query-string body merge).
- All four `_opt_*` coercion helpers accept the JSON-native form
  AND the query-string scalar form. `items` accepts list-of-strs,
  list-of-ints, or comma-separated string.
- Tests share one server instance across the suite (single 30 ms
  snapshot load amortized over 20 tests, ~2.7s total).

**Things tomorrow-you should NOT redo:**
- Don't add FastAPI/aiohttp. The original design doc mentioned
  "FastAPI/aiohttp" but RC's convention is stdlib `http.server` and
  the routes are simple enough that the dep cost is unjustified.
  20 tests pin the contract.
- Don't wire DS into RC's main process as a daemon thread. The
  design's Phase 7 has it as a **separate process** (analogous to
  `moon_vision_server.py` under `RC-VisionServer`). Keep it
  standalone; restart-isolated; the supervisor entry is its own task.
- Don't add hot-reload here. Snapshot mtime polling lands cleanly
  in Phase 7 once the supervisor wraps the lifecycle.
- Don't bind to 0.0.0.0 by default. Loopback is the right default
  until something cross-machine actually needs it.
- The `_SnapshotCache` is a **process-global singleton**. Don't try
  to make it per-request or per-thread — engine math is pure on
  immutable data, no race.

**Open for next sessions:**
- **Phase 4**: per-item conditional effects (passives, on-hits) —
  Top 30 by pickrate first, long-tail segmented. 15-30 days. This
  is where Riot patch notes start mattering (effects change patch
  to patch). DPS math will then reflect IE +40% crit damage,
  Stormrazor energized, Shieldbow lifesteal, etc. Big phase.
- **Phase 5/6/7**: Mayhem augments / Arena augments / coach wire-in
  + supervisor entry + retire `_arena_item_advisor`.
- **Phase 2 step 4 (optional)**: full-build ranker (Cartesian/beam
  search to find the best 6-item end-state within a gold ceiling).
  Skipped for now in favor of Phase 3 user-visibility milestone.
- All s37/s38/s39/s40/s41 carryover items still apply.

**Memory:** No memory write needed this session — Phase 3 is straight
extension of `reference_daemon_slayer_engine_arch.md`'s extension
points (CLI subcmd + new module). The "things not to redo" list
above captures the design decisions; if any become surprising in
Phase 4+, write them then.

**Bridge state at session end:** RC PID 9740 alive, mode=client,
lobby phase. No game this session. DS server stopped after smoke
test (PID 12180 killed); no scheduled task installed yet (Phase 7
work).

**/done close-out (s42):** Working tree clean. 2 commits this session
both already on origin (`f067ce6..5029deb`). No background tasks. No
pending lessons. Bridge gamepc loop alive (probe `task-824521a49ae8`
round-tripped in 31s). RC pid 9740 alive, last_reload_ok=true,
restart_trigger empty. Lobby — safe to /clear.

## s43 hand-off — 2026-05-03 (Daemon Slayer Phase 4 thin slice shipped)

One arc: Phase 4 thin slice — five marquee items now carry conditional
effects on top of their stat blocks. Schema is the deliverable; the
five-item table is the proof it threads end-to-end.

**What shipped (commit `d71ffc3`):**
- `agents/daemon_slayer/effects.py` (~140L) — `ItemEffect` +
  `PeriodicProc` dataclasses, `ITEM_EFFECTS` dict, `collect_effects()`,
  `total_crit_damage_bonus()`. Schema guards: `damage_type` must be
  `physical|magical`; exactly one of `every_n_attacks` / `every_n_seconds`
  set; both raise `ValueError` at construction.
- `agents/daemon_slayer/dps.py` — new `_periodic_proc_dps()` helper;
  `_rotation_attack_dps()` and `_phase_weighted_dps()` plumbed with
  `crit_bonus` + `effects` + `target_mr`. `compute_dps()` builds
  the effects list once, sums crit-damage bonuses into the per-rotation
  crit_bonus, surfaces fired effects in `DpsResult.notes`.
- `agents/daemon_slayer/__init__.py` — `ENGINE_VERSION 0.5.0 → 0.6.0`.
- `tests/test_effects.py` — 22 new tests.
- `tests/test_dps.py` — two pre-existing IE tests updated to reflect
  now-correct +30% crit-damage math (schema-aware via `ITEM_EFFECTS["3031"]`).
- 128/128 green.

**Items pinned (patch 16.9.1):**
| ID | Name | Effect |
|---|---|---|
| 3031 | Infinity Edge | `crit_damage_bonus=0.30` |
| 3072 | Bloodthirster | `defensive_only=True` (Ichorshield — no DPS) |
| 3097 | Stormrazor | Energized: 120 magic dmg every 4.0s |
| 6672 | Kraken Slayer | Bring It Down: 100 physical dmg every 3rd attack |
| 6673 | Immortal Shieldbow | `defensive_only=True` (Lifeline — no DPS) |

**Smoke (Aatrox lvl 11 + Berserker's vs 80 armor):**
| Item | s42 +dps | s43 +dps | Δ |
|---|---|---|---|
| 3031 IE | 25.27 | 27.82 | +30% crit damage adds 2.55 over rotation |
| 3097 Stormrazor | 19.28 | 49.28 | magic proc vs 0 MR is huge — pin MR>0 in real coach calls |
| 6672 Kraken | (off top-5) | 22.88 | now slots in front of BT |
| 3072 BT | 20.15 | 20.15 | unchanged (no effect entry) |
| 2523 Hexoptics | 19.29 | 19.29 | unchanged (no effect entry) |

**Design choices worth pinning:**
- **Constants over callables** at the thin-slice layer. `bonus_damage`
  is a fixed float, not a `Callable[[stats, target], float]`. Future
  Phase 4 expansion will need callable scaling for items like Kraken
  (real formula: `60 + 65% bonusAD + missing-HP%`) — but constants are
  honest about being patch-pinned approximations and keep the schema
  easy to read for the next ~25 marquee items. Promote to callable
  when the first item demands it.
- **Magical procs use `target_mr`, not `target_armor`.** Routed via
  `damage_type` enum on `PeriodicProc`. Mode damage multiplier
  (`aramDamageDealt`) applies to procs too — they're still "Aatrox
  damage."
- **`defensive_only=True` items still get an entry.** Two reasons:
  (1) the note surfaces in `DpsResult.notes` so a user reading a rank
  output can SEE that BT's lifesteal-shield was acknowledged and not
  silently DPS-counted; (2) future review ("did we forget to model
  X?") becomes a one-grep check.
- **Engine doesn't enforce per-item uniqueness.** Two IEs in a build
  stack `crit_damage_bonus` to 0.60. Tested explicitly in
  `test_two_ies_stack_crit_damage` so a future "one IE only" rule has
  to be a deliberate change, not an accidental one.
- **Existing IE tests in `test_dps.py` were factually wrong** under the
  old engine — they encoded the assumption that IE adds no crit-damage
  bonus. Updated in this commit to import `ITEM_EFFECTS["3031"]`
  directly so the test description matches reality. Keep this pattern
  for Phase 4 expansion: tests that hand-calculate item math should
  reference the effect table, not duplicate constants.

**Things tomorrow-you should NOT redo:**
- Don't add `bonus_damage` as a callable yet. Wait for the first item
  whose damage truly depends on champion stats or target HP (likely
  Kraken's real formula or Voltaic Cyclosword's energized scaling).
  Then expand the schema; backport the existing five.
- Don't try to model on-hit lifesteal/sustain in this layer. Sustain
  is a separate calculation (EHP-adjacent), not a DPS layer.
- Don't bind effects to a per-mode toggle. Item legality is already
  filtered by `rank.MODE_MAP_ID`; if an item is in the build, the
  effect applies regardless of mode. ARAM damage multiplier already
  attenuates proc damage via `mode_dmg_mult`.
- Don't move `ITEM_EFFECTS` into `data/daemon_slayer/<patch>/`. The
  table is hand-curated from patch notes / community wikis, NOT
  extracted from DDragon. Keep it as Python constants under version
  control with the engine — the patch-bump diff is the artifact.

**Open for next sessions:**
- **Phase 4 expansion**: next 25 items by pickrate. Likely candidates
  to model first: Voltaic Cyclosword (energized + slow), Statikk Shiv
  (energized chain lightning), Rapid Firecannon (energized range +
  damage), Black Cleaver (% armor shred — interacts with target_armor
  per stack), Lord Dominik's (% armor pen — same), Phantom Dancer
  (lifeline + ghosting on low HP — defensive_only initially).
  Promote `bonus_damage` to callable when the first stat-scaling
  item lands.
- **Phase 5/6/7**: Mayhem augments / Arena augments / coach wire-in
  + supervisor entry + retire `_arena_item_advisor`. Phase 4 thin
  slice is just enough conditional math to make Phase 7 coach calls
  meaningfully better than the s42 baseline; further Phase 4 items
  raise the ceiling.
- **Phase 2 step 4 (still optional)**: full-build ranker. Now even more
  worth deferring — beam search over Phase 4-aware DPS will find
  builds the Phase 3 single-slot ranker can't see (e.g. IE+Stormrazor
  synergy).

**Memory:** No new memory write needed — Phase 4 thin slice is straight
extension of `reference_daemon_slayer_engine_arch.md`'s extension
points (new module + new dataclass). Schema decisions documented above
will graduate to memory if Phase 4 expansion surprises us.

**Bridge state at session end:** RC PID 9740 still alive (no restart
this session — engine work is offline). Bridge gamepc loop alive per
s42 close-out. Working tree clean after `d71ffc3`. Lobby. Safe to /clear.

## s44 hand-off — 2026-05-03 (Daemon Slayer Phase 7 narrow + Phase 4 expansion)

Three-arc session, all DS work. **Arc 1**: Phase 7 narrow — supervisor
entry on :8893 (RC-DaemonSlayer scheduled task) + arena coach
companion-field wire-in. **Arc 2**: Phase 4 expansion — schema bump
(CallContext + callable bonus_damage + armor pen layer) and 25 new
items in `ITEM_EFFECTS`. **Arc 3**: User shared the Phase 8+ vision
(SR Draft Theatre with 3-build profile, in-game panel replacement,
Max Build toggle, dedicated DS sub-page) — captured as ordering plan
for after Phase 5/6/7.

**What shipped (commit `<TBD>`):**
- `tools/start_daemon_slayer.py` + `ops/RC-DaemonSlayer.xml` +
  `tools/install_daemon_slayer_task.ps1` — boot launcher, Windows
  scheduled task (BootTrigger SYSTEM HighestAvailable), idempotent
  install script. `:8893/health` returns 200 on boot now.
- `core/daemon_slayer_client.py` — thin urllib wrapper for `/health`,
  `/rank`, `/dps`. 250 ms connect / 500 ms read timeouts; engine-down
  → returns None (callers branch on it).
- `core/daemon_slayer_resolver.py` — items_index.json byName resolver
  with mtime-based reload cache. `Infinity Edge` → `223031`,
  `Berserker's Greaves` → `223006`. (22-prefix is the Arena alias;
  see `reference_items_index_alias_ids.md`.)
- `coaches/arena_coach.py` — adds `daemon_slayer_picks` companion
  field next to existing `item_build`. Engine-down → field absent;
  `_arena_item_advisor` stays the source of truth for `item_build`
  until Phase 6 (Arena augments) lands. Phase 7 is the wire-in
  pattern proof, not the retirement.
- `agents/daemon_slayer/effects.py` — Schema bump:
  - `CallContext(base_ad, bonus_ad, level, target_armor, target_mr)`.
  - `PeriodicProc.bonus_damage` is now `float | Callable[[CallContext], float]`.
    `resolve_damage(ctx)` is the consumer interface; constants pass
    through, callables evaluate.
  - New `ItemEffect` fields: `armor_reduction_pct` (Black Cleaver),
    `armor_pen_pct` (LDR/MR), `armor_pen_flat` (lethality).
  - `effective_target_armor(armor, effects)` applies reduction → %pen
    → flat pen pipeline. Passthrough when no modifiers; no-op on
    already-negative armor (preserves test cases of the armor curve).
  - 25 new entries in `ITEM_EFFECTS`. Total 30.
- `agents/daemon_slayer/dps.py` — Plumbed `CallContext` through
  `_periodic_proc_dps` / `_rotation_attack_dps` / `_phase_weighted_dps`.
  `compute_dps` builds CallContext once + applies `effective_target_armor`
  before passing into the rotation loops. Surfaces a "effective target
  armor X → Y after reduction + pen" note when a modifier fired.
- `agents/daemon_slayer/engine.py` — `ResolvedStats.base_stats`
  exposes the leveled pre-item stat dict (needed by spellblade-style
  callables that scale off `base_ad`). Backward-compat default = `{}`.
- `agents/daemon_slayer/__init__.py` — `ENGINE_VERSION 0.6.0 → 0.7.0`.
- `agents/daemon_slayer/tests/test_effects_expansion.py` — 33 new tests.
- 161/161 green (was 128).

**Items pinned in this expansion (patch 16.9.1):**

| ID | Name | Effect |
|---|---|---|
| 3087 | Statikk Shiv | Energized chain ~110 magic / 3s (constant) |
| 3094 | Rapid Firecannon | Energized shot ~120 magic / 3s (constant) |
| 3091 | Wit's End | Fray on-hit `15 + (lvl-1)*65/17` magic (callable) |
| 3085 | Runaan's Hurricane | 2 bolts on-hit `0.6 * bonus_ad` physical (callable) |
| 3078 | Trinity Force | Spellblade `2.0 * base_ad` physical / 3s (callable) |
| 6699 | Voltaic Cyclosword | Energized `100 + 0.25 * bonus_ad` physical / 4s (callable) |
| 6610 | Sundered Sky | Lightshield `20 + 2.0 * base_ad` physical / 8s (callable) |
| 3124 | Guinsoo's Rageblade | Phantom Hit `0.5 * bonus_ad` physical / 3 attacks (callable) |
| 3036 | Lord Dominik's | armor_pen_pct=0.35 |
| 3033 | Mortal Reminder | armor_pen_pct=0.30 (+ GW heal-cut not modeled) |
| 3071 | Black Cleaver | armor_reduction_pct=0.30 (5 stacks sustained) |
| 13 defensive_only | Phantom Dancer, The Collector, Navori Flickerblade, Youmuu's, Edge of Night, Serpent's Fang, Opportunity, Sterak's Gage, Maw, Hullbreaker, Frozen Heart, Chemtech Putrifier, BotRK, Terminus, Eclipse | (BotRK/Eclipse/Terminus deferred to Phase 4+ when target HP modeling lands; The Collector deferred for execute math) |

**SR rank smoke (Aatrox lvl 11 + Berserker's vs 80 armor, top 8):**
1. Stormrazor +49.28 (magic vs MR=0)
2. Statikk Shiv +48.45
3. Rapid Firecannon +44.25
4. Trinity Force +32.93
5. Voltaic Cyclosword +29.65
6. Wit's End +28.57
7. Infinity Edge +27.82
8. Kraken Slayer +22.88

Magic procs dominate at MR=0 (expected — coach should pin realistic
target_mr). Trinity rises fast on spellblade scaling.

**Design choices worth pinning:**
- **Schema is callable-friendly but not callable-required.** Existing
  constants (IE +0.30 crit dmg, Stormrazor 120, Kraken 100) didn't
  change shape. Only items that demanded scaling went callable. This
  keeps the table easy to scan and the patch-bump diff small.
- **`base_ad` exposed via `base_stats` dict, not a separate field.**
  Future scaling stats (base_ap, base_hp) can flow through the same
  channel without a schema bump.
- **Armor pen pipeline order matches League:** reduction first
  (BC stacks → multiplier on target_armor), then % pen (LDR/MR,
  multiplicative on what remains), then flat (lethality, additive
  subtraction). Floor at 0 — but only when a modifier fired.
  Negative-armor inputs (test cases of the armor curve) pass through.
- **Pen no-op on already-negative armor.** League rule: pen helps when
  target has armor; if target is already shredded below zero, pen
  doesn't amplify further. The test for this is in
  `EffectiveTargetArmorTests.test_negative_armor_no_op_with_pen`.
- **defensive_only entries still get notes.** Same reasoning as s43:
  the note surfaces in `DpsResult.notes` so a user reading a rank
  output SEES that BotRK / Eclipse were acknowledged but DPS-skipped
  (target HP not modeled). One-grep check for "did we forget X?"
- **Phase 6 (Arena augments) before retiring `_arena_item_advisor`.**
  Arena prismatics + augments aren't in the engine yet, so a hard
  retire would regress arena coaching. The wire-in writes a companion
  field; replacement happens after Phase 6 puts the missing context
  into the engine.

**Things tomorrow-you should NOT redo:**
- Don't re-extract the snapshot to fix `attackdamageperlevel=0`.
  Surfaced this session: ALL champions in 16.9.1/champions.json have
  `attackdamageperlevel=0`. Pre-existing extractor gap, not Phase 4.
  Promote `tools/daemon_slayer_extract.py` to fill perlevel fields
  in a Phase 1.5 session — meanwhile, base_ad scaling is correct
  per the data we have (constant-by-level), under-estimating late
  game AD by ~50-90 for melee bruisers.
- Don't write tests that hand-calculate proc DPS expecting specific
  numbers. Test directionally (with > without, scaling > non-scaling).
  The rotation weights × phase × armor_factor × mode_mult chain has
  too many moving pieces; specific numbers couple tests to engine
  internals.
- Don't add magic_pen analogues to the armor pen layer in Phase 4.
  No magic-pen items in the marquee 25; defer the symmetric layer
  until Void Staff / Sorcerer's Shoes / Cryptbloom land.
- Don't touch `_arena_item_advisor` in this phase. Phase 6+ replaces
  it; companion field is the proof point for now.

**User vision capture for Phase 8+ (don't re-prompt — this is decided):**

Map of user-asked features → planned phase:

| Feature | Phase | Notes |
|---|---|---|
| Mode-aware engine (SR/ARAM/Arena) | Done (Phase 2-3) | TFT separate; Brawl pending |
| Mayhem augments | 5 | currently treated as plain SR |
| Arena augments | 6 | needed before `_arena_item_advisor` retire |
| Coach wire-in pattern proof | 7 (done) | arena `daemon_slayer_picks` field |
| **SR Draft Theatre** | 8 | LCU draft subscription + 3-build profile (primary, alt-playstyle, experimental) + runes/spells writer + push-to-League. **Operator-additive**: user-curated experimental builds APPEND, never overwrite — all shown pre-game + all pushed to League. |
| In-game Item Build Panel replacement (rename → Daemon Slayer Builder) | 9 | replaces SR/ARAM "next items" output |
| DS dedicated sub-page | 9 | mirrors Item Build Panel + "why" + flag-for-review |
| Decision logging schema (DS picks → match outcome join) | 9 | extends existing `agents/decision_log/` |
| Max Build toggle (sell-and-rebuy late-game) | 10 | needs late-game predicates: Baron up + 50min + nexus exposed + GA-CD + 6k excess gold |
| Post-game outcome join + analysis sweep | 11 | leverages `lcu/lcu_postgame_collector.py` + rewind_history.db |

User UX rule (hands-off default): all 3 builds auto-push to League
without confirmation. Operator only touches Loadouts page to add an
experimental build (additive) for a specific champion. Issues come
to me for review via flag-for-review buttons on the DS sub-page.

**Open for next sessions:**
- **Phase 2 step 4 (top of next-session queue)**: full-build
  beam-search ranker. Now strictly more useful with Phase 4 expansion
  — beam search will find IE+Stormrazor / TriForce+Sundered Sky
  synergies the single-slot ranker can't see. Foundation for Phase 8's
  3-build profile (alt-playstyle + experimental need beam to enumerate)
  and Phase 10's Max Build re-optimization (beam search with sell-back
  cost function).
- **Phase 5 (Mayhem augments)**: Mayhem mode is rotating SR with
  augments. Augment table extraction + augment-aware engine hook +
  modify rank to consider augment effects.
- **Phase 6 (Arena augments)**: Same shape as Phase 5 but Arena
  augments + prismatic items. Once shipped, `_arena_item_advisor`
  gets retired and `item_build` defaults to DS.
- **Phase 1.5 (extractor fix)**: backfill `attackdamageperlevel` and
  other perlevel fields in champions.json. Currently all zero — late
  game AD under-estimated.

**Memory:** No new memory entries this session. Phase 4 expansion is
straight extension of `reference_daemon_slayer_engine_arch.md`'s
extension points. User vision for Phase 8+ captured in this hand-off
table; promote to a memory entry once Phase 5/6/7 close and we're
actively building Phase 8.

**Bridge state at session end:** RC engine on :8893 is now boot-managed
via RC-DaemonSlayer scheduled task. Main RC PID unchanged (no main
restart needed — engine is its own process). Bridge gamepc loop alive.
Working tree pre-commit: ~10 files changed, ~600 lines net new across
DS engine + tests + ops.

## s45 hand-off — 2026-05-03 22:14 (Daemon Slayer Phase 2 step 4 — beam search)

Single-arc session. Phase 2 step 4 (top of s44's next-session queue)
shipped: full-build beam-search ranker. Engine 0.7.0 → 0.8.0.

**Commit:** `03346b6` — `feat(daemon-slayer): Phase 2 step 4 — full-build beam-search ranker`. Pushed `4f4e76d..03346b6 main -> main`.

**What shipped:**
- `agents/daemon_slayer/beam.py` (~290L) — `beam_search_build()` returns
  `BeamResult` with top-N complete builds. Per generation: expand every
  surviving beam by every candidate, dedupe by `frozenset(item_ids)`,
  score via `compute_dps`, keep top `beam_width`. Defaults: width=10,
  top_n=10, slot_count=6, boots_unique=True.
- `agents/daemon_slayer/server.py` — `POST /beam` + `GET /beam` routes.
- `agents/daemon_slayer/cli.py` — `python -m agents.daemon_slayer beam <champ>`.
- `agents/daemon_slayer/tests/test_beam.py` — 29 new tests; 190/190 green
  (was 161, +29).

**Smoke results (Aatrox lvl 11, target_armor=80, SR):**
- 6-slot, beam_width=10: **220 ms wall**, 8652 evaluations. Top build:
  `Stormrazor + Statikk Shiv + IE + LDR + Mortal Reminder + Runaan's`
  (+355.3 DPS over baseline). Beam finds the IE+Stormrazor+Statikk +
  pen-layer synergy that single-slot greedy can't see in one pass.
- `total_budget=12000g`: search exhausts at depth 4/6 cleanly (the budget
  literally can't fit 6 full DPS items at this patch's prices).
- `beam_width=1` ≈ greedy (single survivor each layer).

**Design choices worth pinning:**
- **Pre-filter the candidate pool ONCE** at the top of `beam_search_build`,
  not per beam expansion. Boots-tag flag and total gold cached on each
  pool entry. Per-beam check is then O(1) per candidate (set membership
  for already-picked, plus boots-already-in-beam). 175 → 169 after
  consumable filter; 8.6k evals at width=10 stays sub-second.
- **`frozenset(item_ids)` dedup is the trick that makes this fast.** Two
  beams reaching the same item set in different orders score once. With
  width=10 and 6 slots, dedup hits run at ~50% by depth 5.
- **Consumables filter (Health Potion, Control Ward, etc.) is required
  for beam search but NOT for single-slot rank.** Greedy never picks
  them (zero delta), but with a tight `total_budget` beam search would
  otherwise stuff empty slots. Filter signal: `consumed: True` OR
  `"Consumable" in tags`. Trinkets (3340/3363/3364) already excluded
  upstream by `total=0` gate.
- **Boots-uniqueness on by default.** Test `boots_unique=False` admits
  multi-boot builds when whitelist forces it (verified with terminal
  enchanted boots 3168-3175). `boots_unique=True` correctly caps every
  returned build at ≤1 boot item.
- **`current_item_ids` pinning works as expected** — every result
  contains the seed; depth_reached == slot_count − len(seed).
- **Search-exhausted note is informational, not an error.** When budget
  or whitelist prunes everything, return whatever depth got reached;
  the caller can branch on `depth_reached < slot_count`.

**Things tomorrow-you should NOT redo:**
- Don't re-debug "boots-double test failed" — boots have `into` paths
  and were filtered as components by default. Use the terminal
  enchanted boots IDs (3168-3175) when forcing multi-boot scenarios.
- Don't change `clamp_level` to silently clamp — it raises
  ValueError on out-of-range, matching the shape of the rest of the
  engine. Test was wrong, not the function.
- Don't add a `consumables_filter=False` parameter to expose the
  consumable filter as toggleable. There's no real-world build that
  contains a Health Potion as one of the 6 slots; if a caller really
  wants one, they pass it via `current_item_ids`.

**Engine version: 0.7.0 → 0.8.0.** The `RC-DaemonSlayer` scheduled task
was restarted mid-session (taskkill on the 6188 → 9492 → 12176 → new
PID; `/health` confirms 0.8.0 live with `/beam` routing).

**Next-session candidates (ranked):**
1. **Phase 5 (Mayhem augments)** — Mayhem mode is rotating SR with
   augments. Augment table extraction + augment-aware engine hook +
   beam-search awareness of augment effects. Beam search is now
   strictly more useful with augments since combos shift the ranking.
2. **Phase 6 (Arena augments)** — Same shape as Phase 5 but for Arena.
   Once shipped, `_arena_item_advisor` retires and arena coach's
   `item_build` defaults to DS picks (currently companion field).
3. **Phase 1.5 (extractor fix)** — backfill `attackdamageperlevel` and
   other per-level fields in champions.json (still all zero in 16.9.1
   per s44 finding). Late-game AD currently under-estimated by ~50-90
   for melee bruisers; beam search can't compensate without per-level data.
4. **Phase 8 SR Draft Theatre kickoff** — LCU draft subscription +
   3-build profile (primary, alt-playstyle, experimental). Beam search
   is the foundation: for `top_n=3` it returns three distinct high-DPS
   builds that can map to the 3-build profile slots. Pre-coach phase 8.

**Things NOT to redo:**
- s44's "should beam_width be high or low?" — settled at 10. Lower bound
  beats greedy meaningfully; higher than 20 doesn't measurably change
  the top-5 ranking on the test scenarios. Tune later if needed.
- The "filter consumables in single-slot rank too" question — already
  considered and rejected. Greedy ranks them at zero delta; they sort
  to the bottom. Only beam search needs the filter.

**Memory:** No new entries written. Beam is a straight extension of
`reference_daemon_slayer_engine_arch.md`'s extension points (the engine
module map already names `rank.py` as a sibling of `dps.py`/`engine.py`;
`beam.py` slots in next to `rank.py`).

**Bridge state at session end:** RC main pid=9328 alive=true reload_ok=true.
Engine on :8893 0.8.0 / `/beam` live. Bridge gamepc loop alive
(probe `task-876e96057406` round-tripped in <90s). Working tree clean
post-commit.

## s46 hand-off — 2026-05-03 (Daemon Slayer Phase 1.5 — Meraki AD-perlevel backfill)

Single-arc session, plus a Phase 6 prep note. Phase 1.5 (perlevel field
backfill, item #3 on s45's queue) shipped.

**Commit:** `9b85723` — `feat(daemon-slayer): Phase 1.5 — Meraki perlevel
backfill for AD growth`. Pushed `329cb1c..9b85723 main -> main`.

**Findings — DDragon data hole:**
- 100% of champions (172/172) have `attackdamageperlevel: 0` in DDragon
  16.9.1 (both bulk and per-champion endpoints). Riot stopped exporting
  AD growth even though in-game value is non-zero.
- Other zero perlevel fields are legitimate game state: Jhin AS=0
  (passive converts items only), Thresh armor=0 (souls grow it),
  Briar HP-regen=0 (passive only), every champion's crit growth=0
  (Riot deprecated globally).
- Net effect: late-game DPS modeling was massively wrong. Aatrox lvl 18
  was reading AD=60 (should be 145). 50-85 AD missing for melee
  bruisers across the board. Beam search rankings post-lvl 11 were
  unreliable.

**What shipped:**
- `tools/daemon_slayer_extract.py` (+86L) — `fetch_meraki_perlevel_overlay()`
  helper; sequential HTTP to `cdn.merakianalytics.com/.../champions/<id>.json`,
  ~48s for 172 champions. Overlays only when DDragon has 0 (preserves
  legitimate zeros). Manifest gets new `meraki_perlevel_backfill` block
  with provenance.
- `data/daemon_slayer/16.9.1/champions.json` — regenerated; 169/172
  champions filled. Yunara + Zaahen too new for Meraki (404), retain
  DDragon 0 — safe degradation.
- `agents/daemon_slayer/tests/test_engine.py` — `test_eclipse_ad_adds_to_aatrox`
  was asserting on the bug (lvl 11 + Eclipse = 120). Updated to assert
  the correct value (170). Test comment even acknowledged the bug.
- 190/190 tests green. Live engine on :8893 restarted (PID 1856 → new),
  `/stats?champion=Aatrox&level=18` confirms ad=145.0.

**Memory:** Added `reference_arena_arcane_sweeper_trinket.md` — Arena's
Arcane Sweeper occupies the trinket slot, NOT a regular item. DS item
ranker/beam search must exclude it from candidate pool when mode=ARENA.
Same conceptual bucket as SR's `3340/3363/3364` trinkets (already
excluded by `total=0` gate). Verify Arcane Sweeper has same `total=0`
signal — if not, explicit id filter needed in Phase 6.

**Phase 6 prep — augment data source recon:**
- `https://raw.communitydragon.org/latest/cdragon/arena/en_us.json` is
  clean: 219 Arena (cherry) augments with full `dataValues`/`calculations`
  blocks. Suitable for direct extraction.
- KIWI/Mayhem augments: NO clean cdragon dump exists. Only raw bin.json
  UI config files (`game/gameplay.kiwiaugmentselection.bin.json` etc.).
  Would need a custom parser for Riot game data format.
- Decision queued: swap Phase 5 ↔ Phase 6 order. Arena augments first
  (clean data + Arena coach already in production wanting DS as primary
  driver). Mayhem augments deferred until clean data source found OR
  bin.json parser justified.

**Things tomorrow-you should NOT redo:**
- Don't re-probe DDragon for `attackdamageperlevel` — confirmed 0 for all
  172 champions in both bulk and per-champion endpoints. Meraki is the
  source of truth for this field.
- Don't try to backfill `critperlevel` from Meraki — it's 0 in-game (Riot
  deprecated it), DDragon is correct. Backfill would silently wrong
  the math.
- Don't add other perlevel fields to the overlay — `armorperlevel: 1
  zero`, `hpregenperlevel: 1 zero`, `attackspeedperlevel: 2 zero` are all
  genuine game state. Verified in s46.
- Don't try `cdragon/mayhem/en_us.json` or `cdragon/kiwi/en_us.json` —
  both 404. Only `arena` and `tft` have clean dumps.
- Don't reach for `cherryaugments.json`/`strawberryaugments.json`/
  `swarmaugments.json` paths — all 404 in current cdragon. The arena
  dump at `cdragon/arena/en_us.json` is the working path.

**Engine version unchanged: 0.8.0.** Phase 1.5 is a data-only fix; engine
code didn't change. Server picked up new champions.json on restart.

**Next-session candidates (ranked):**
1. **Phase 6 (Arena augments)** — extract from `cdragon/arena/en_us.json`,
   add augment-aware engine hook (overlay augment stats on
   `compute_stats`), filter Arcane Sweeper from item candidate pool, wire
   beam search to consider augment combos. Once shipped,
   `_arena_item_advisor` retires; arena coach `item_build` defaults to
   DS picks (currently companion field).
2. **Phase 5 (Mayhem augments)** — DEFERRED until either (a) clean cdragon
   dump appears or (b) bin.json parser justified. Current path = no
   clean source; engine treats Mayhem as plain SR (still useful).
3. **Phase 8 (SR Draft Theatre kickoff)** — LCU draft subscription +
   3-build profile. Beam search foundation already in place from s45.

**Bridge state at session end:** RC main pid=9328 alive=true reload_ok=true.
Engine on :8893 0.8.0 live. Working tree clean post-`9b85723`.

## s47 hand-off — 2026-05-03 (Daemon Slayer Phase 6 step 2+3 — Arena augments wired into engine)

Continuation of s46 (operator said "continue" after /done). Phase 6
(Arena augments) shipped through engine integration. Engine 0.8.0 → 0.9.0.

**What shipped (uncommitted at write-time, will land alongside in single
commit):**
- `tools/daemon_slayer_extract.py` — new `fetch_arena_augments()` helper;
  pulls cdragon arena en_us.json (219 augments). Manifest gets
  `arena_augments` provenance block.
- `data/daemon_slayer/16.9.1/arena_augments.json` — first augment snapshot
  (219 entries, rarity 0/1/2/4 = silver/gold/prismatic/hero).
- `agents/daemon_slayer/augments.py` (new, ~140L) — `Augment` dataclass,
  rarity constants (`RARITY_SILVER/GOLD/PRISMATIC/HERO`),
  `compute_augment_stats()` overlay function. Tier-1 stat-overlay registry
  has 3 verified entries: TheBrutalizer (+20 AD), CelestialBody (+1000 HP),
  WitchfulThinking (+60 AP).
- `agents/daemon_slayer/data_loader.py` — `DataSnapshot` now loads
  `arena_augments.json` (tolerates absence for older snapshots);
  `arena_augment(key)` accepts int id OR apiName string.
- `agents/daemon_slayer/engine.py` — `build_champion(augments=[...])`
  parameter; overlay applied additively after items, before mode modifiers.
  `ResolvedStats.augments` field + `to_dict()` surfaces. Unknown registry
  augments add an informational note.
- `agents/daemon_slayer/cli.py` — `stats` subcmd has `--augments` flag.
- `agents/daemon_slayer/server.py` — `/stats` POST accepts `augments` param.
- `agents/daemon_slayer/__init__.py` — `ENGINE_VERSION 0.8.0 → 0.9.0`.
- `agents/daemon_slayer/tests/test_augments.py` (new, ~120L) — 17 tests
  covering data layer + overlay registry + engine integration.

**Test count: 207/207 green** (was 190 → +17 augment tests).

**Smoke:** `py -m agents.daemon_slayer stats Aatrox --level 11 --mode ARENA
--augments TheBrutalizer,WitchfulThinking` → AD=130 (was 110), AP=60 (was 0).

**Decisions worth pinning:**
- **Overlay applied AFTER items, BEFORE mode modifiers.** Augments are
  arena-only in practice; ARAM mode modifiers don't co-apply. Order is:
  base+level → +items → +augments → mode mods.
- **Unknown augments are silent zero-overlay, not errors.** Registry grows
  incrementally; 3 entries today, more later. Caller passing an
  unregistered apiName (e.g. ApexInventor) gets a note, not a failure.
  This means the arena coach can pass the full augment list without
  pre-filtering against the registry.
- **Augment IDs come from cdragon "latest", not patch-pinned.** cdragon
  doesn't version-pin per-patch dumps for arena. arena_augments.json
  carries `fetched_at` timestamp; ids are stable across cdragon revs but
  rotation contents change. Don't write tests asserting exact ID-to-name
  mappings — the existence checks via apiName are stable.
- **The 5 rarity-4 "meta" augments** (CraftingPrisStatAnvil,
  CraftingSellAugment, ReplaceAugment, CraftingAugmentSlot,
  GainStatAnvil) sit alongside the 11 GoH (Guardian of Heaven) hero
  augments. Test was loosened to count GoH only.
- **Lethality from TheBrutalizer is silently dropped.** Not a canonical
  stat key in the engine yet. Add to `RESOLVED_STAT_ORDER` in
  `stats.py` when the engine grows pen modeling.
- **Arena restart deferred — user is mid-Arena game.** Live :8893 still
  serves 0.8.0 / no augment awareness; arena coach companion field
  unaffected. Restart `RC-DaemonSlayer` after game ends OR at the next
  natural restart point. Activation is one command:
  `taskkill /F /PID <:8893 listener>; schtasks /Run /TN RC-DaemonSlayer`.

**Things tomorrow-you should NOT redo:**
- Don't add Statikk/TankItUp/AllOfASudden to the registry — those
  apiNames don't exist in the cdragon dump (I guessed wrong in s47).
  Real flat-stat candidates discovered by audit: TheBrutalizer,
  CelestialBody, WitchfulThinking are confirmed; BigBrain has AP=1
  (ratio anchor, not real flat AP); Vulnerability/TankItOrLeaveIt grant
  CritChance=0.25 but conditionally; Chauffeur grants AS+haste with a
  movement-penalty tradeoff. To extend the registry safely: probe
  `dataValues` index 0 and verify the augment description matches a
  pure additive grant.
- Don't try `cdragon/cherryaugments.json` or
  `cdragon/cherry/en_us.json` paths — they're 404. The arena dump
  lives at `cdragon/arena/en_us.json`.
- Don't gate `augments=[...]` to `mode=ARENA` — engine takes them
  regardless, by design (caller responsibility). This keeps the API
  surface clean for future modes that might reuse arena augments.
- Don't try beam-search-with-augments yet — that's Phase 7-ish work
  (augment-aware beam scoring). Augments are operator-curated, not
  optimized.

**Engine version: 0.8.0 → 0.9.0.** Bump justified: new capability layer
(augment-aware stat resolution) with public API surface change
(ResolvedStats.augments field, /stats and CLI now accept augments).

**Next-session candidates (ranked):**
1. **Arena restart + arena_coach wire-up** — restart RC-DaemonSlayer to
   activate 0.9.0 on :8893. Then update `coaches/arena_coach.py` to pass
   detected augments into `daemon_slayer_picks` HTTP calls. The augment
   apiName list comes from LCU postgame data or live game polling.
   Operator will need to confirm where in arena flow we read picked augments.
2. **Phase 6 step 4 — Arcane Sweeper trinket filter.** Per
   `reference_arena_arcane_sweeper_trinket.md`, exclude Arcane Sweeper
   from the item candidate pool when `mode=ARENA`. Confirm whether
   `total=0` gate already catches it OR an explicit id filter is needed.
3. **Phase 6 step 5 — registry expansion.** Audit the remaining ~85
   flat-stat candidates I surveyed (`SlapAround` adaptive force,
   `Dematerialize` adaptive, `Marksmage` AP-from-AD ratio, etc.). Each
   needs a per-augment verification pass.
4. **Phase 5 (Mayhem augments)** — STILL DEFERRED. No clean cdragon
   dump; would need bin.json parser. Skip until either appears.

**Bridge state at session end:** RC main pid=9328 alive=true reload_ok=true.
Engine on :8893 STILL on 0.8.0 (deferred restart — see above).
Working tree at write-time has Phase 6 changes uncommitted; will land in
single commit. User in mid-Arena (lcu.phase=InProgress, mode_key=arena).

## s48 hand-off — 2026-05-03 23:20 (DS engine activated 0.9.0 → 0.9.1; Phase 6 step 4 trinket filter)

Short follow-on to s47. Restart of RC-DaemonSlayer activated Phase 6
work; Arcane Sweeper trinket filter shipped on top.

**Shipped (commit `5701664`, pushed `f82c180..5701664`):**
- Restart of RC-DaemonSlayer task — engine 0.9.0 active on :8893 (was
  0.8.0 / deferred restart from s47).
- Phase 6 step 4: `ARENA_TRINKET_IDS = frozenset({"3348"})` in
  `agents/daemon_slayer/rank.py` + `strip_arena_trinkets()` helper.
  Both `rank_items` and `beam_search_build` strip trinket from
  `current_item_ids` before the slot-count check; surface a note in
  result.notes when stripped. Patch bump 0.9.0 → 0.9.1.
- 215/215 tests green (was 207, +8 trinket cases).
- Smoke verified: `/rank` with sweeper-padded inventory now returns
  ranked picks instead of 422 ValueError.

**Decisions worth pinning:**
- Trinket strip happens in `rank.py` (not `engine.py`). Engine accepts
  the id and gets zero stats, so build_champion is unaffected. The
  bug was strictly in the slot-count guard — fix lives at the smallest
  scope that catches it.
- Patch bump (not minor). Behavior change is internal; server endpoints
  + client signatures unchanged.

**s47's #1 (arena_coach augment wire-up) reclassified as BLOCKED:**
- `coaches/arena_coach.py:617` hard-codes `"augments": []` in the
  lifecycle state builder. Vision detects augments on the select panel
  but never persists into running state.
- Engine/server/client plumbing for augments through `compute_dps` /
  `rank_items` / `/dps` / `/rank` is forward-compatible but useless
  without upstream persistence.
- New memory: `project_arena_augments_not_persisted.md` describes the
  blocker + what upstream fix needs (side-channel for picked augments
  + name→apiName mapping).

**Things tomorrow-you should NOT redo:**
- Don't re-investigate `state["augments"]` source — it's hardcoded `[]`
  by design, not a missing wire. See the new memory.
- Don't try to add Arcane Sweeper to a candidate filter — it's already
  excluded by `_is_purchasable` (gold.purchasable=False). The bug was
  current_item_ids padding only.
- Don't try to add `augments` param to `compute_dps`/`rank_items` until
  the upstream persistence is in place — wasted plumbing otherwise.

**Next-session candidates (ranked):**
1. **Phase 6 step 5 — registry expansion.** Audit ~85 flat-stat
   augment candidates; per-augment verification pass against cdragon
   `dataValues`. Expand `agents/daemon_slayer/augments.py`'s tier-1
   stat-overlay registry. Independent of upstream persistence work.
2. **Augment persistence (the actual blocker for s47#1).** Side-channel
   for `_handle_augment_select` to write picked augments + lifecycle
   reads them; name→apiName mapping table. Then arena_coach wire-up
   becomes a 5-line change. Probably 1-2 sessions.
3. **Phase 5 (Mayhem augments)** — STILL DEFERRED. Same reason as
   s47: no clean cdragon dump.
4. **Galeforce stale entry in items.json** — the `/rank` smoke
   surfaced "Galeforce" id 446671 in the top-3 picks; per
   `reference_galeforce_removed`, Galeforce was banned. The DS items
   snapshot (16.9.1) needs cleanup OR the engine needs a deny-list.
   Possibly a Phase 1.5 follow-up to the extractor.

**Bridge state at session end:** RC main pid=9328 alive=true reload_ok=true.
Engine on :8893 NOW 0.9.1 (Phase 6 + step 4 active). User in Lobby
(safe to /clear). Game-PC bridge auto-flow loop verified alive
(reply latency ~40s on the §4 liveness probe).

## s49 hand-off — 2026-05-04 (Phase 6 closed: step 5 activated + step 6 augment persistence shipped)

Single-arc session — closed out the Phase 6 (Arena augments) arc through
the upstream wire-up that s48 marked BLOCKED.

**Shipped (commit `483a272`, not yet pushed):**
- Restart of RC-DaemonSlayer activated 0.9.2 (Phase 6 step 5 — 7 new
  augment overlays + crit cap from `d2bb840`). Verified in /stats: stacked
  4× crit augments cap at 1.0 cleanly.
- Phase 6 step 6 (0.9.2 → 0.9.3): augments now thread through `compute_dps`
  + `rank_items` (engine), `_route_dps` + `_route_rank` (server),
  `dps_for` + `rank_for` (client). Baseline AND per-candidate evaluations
  both apply the overlay, so rank deltas remain coherent.
- `coaches/arena_coach.py` — module-level `_augment_name_map()` lazy
  display→apiName resolver (266 entries; tolerates apostrophes).
  `self._picked_augments` list on the Coach instance, reset in
  `_reset_extra`. `_handle_augment_select` now resolves Haiku's "Take:"
  to apiName and appends; `_on_state_received` injects into
  `state["augments"]`; `_run_coach` passes to `_ds_client.rank_for(...)`.
  Artifact JSON now exposes `augments_picked` field.
- Tests 226 → 232 (+4 augments-through-dps/rank, +2 server routes).
- Memory: `reference_galeforce_removed` scope-narrowed (Arena re-skin
  446671 is legitimate, not stale data); `project_arena_augments_not_persisted`
  flipped to RESOLVED with v2 deferred (vision-confirmed augment slots).

**Decisions worth pinning:**
- v1 augment source = Haiku recommendation, not vision-confirmed click.
  Player can deviate. v2 = HUD-overlay reading after the panel disappears.
  Honest about confidence in the memory.
- Augments stored as apiName list on the Coach instance, NOT a side-channel
  JSON. Artifact JSON's `augments_picked` is the dashboard/postgame view.
- Galeforce 446671 stays in the candidate pool — it's an Arena (map 30)
  re-skin that survived the SR/ARAM scrub. The s48 cleanup item is
  dismissed, not deferred.

**Things tomorrow-you should NOT redo:**
- Don't add a side-channel JSON for picked augments — instance state on
  Coach is the storage. See updated `project_arena_augments_not_persisted`.
- Don't deny-list Galeforce id 446671 — see updated `reference_galeforce_removed`.
- Don't re-add `augments=` kwarg to engine/server/client surfaces — already
  there in `compute_dps`, `rank_items`, `/dps`, `/rank`, `dps_for`, `rank_for`.
- Don't rebuild the name map for every call — it's lazy + cached at
  module level (`_AUG_NAME_MAP_CACHE`).

**Next-session candidates (ranked):**
1. **Augment vision v2** — read post-pick HUD augment slots so picks
   reflect actual click. Real precision win for arena coaching. Probably
   touches `ArenaVisionReader.PROMPT` + a new vision call cadence after
   panel disappears.
2. **Phase 8 (SR Draft Theatre kickoff)** — fresh arc, beam search
   foundation already in place from s45.
3. **Phase 5 (Mayhem augments)** — STILL DEFERRED (no clean cdragon dump).

**Bridge state at session end:** RC main pid=9328 alive=true reload_ok=true.
Engine on :8893 NOW 0.9.3 (Phase 6 fully active). LCU phase=EndOfGame
(safe to /clear). Working tree has WAKEUP_NOTES.md (this update) +
data/ratings/last_arena.json (runtime, untouched this session).

## s50 hand-off — 2026-05-04 (Augment Vision v2 — HUD reconciliation shipped)

Single-arc session. Closed s49's #1 next-session candidate: the v1
"Haiku-recommendation" augment list now has a vision-confirmed override
that fires within 12s of any pick.

**Shipped (single commit, not yet pushed; engine version unchanged):**
- `coaches/arena_coach.py`:
  - `ArenaVisionReader.PROMPT` extended with `augment_hud_slots: []` —
    Sonnet returns currently-equipped augment names from the HUD tray.
  - `Coach._reconcile_augment_hud(vision_state)` — new method, fires from
    `_run_vision` after augment_select / anvil branches. All-or-nothing
    override semantics: every slot must resolve via `_resolve_augment_apiname`,
    else no-op (preserves Haiku list to avoid wiping a known-good record on
    a partial Sonnet read). On override: `_picked_augments = resolved`,
    artifact `augments_picked` rewritten, `augments_source = "vision_hud"`.
  - `_handle_augment_select` now stamps `augments_source = "haiku_rec"` so
    the artifact carries provenance from the moment of the first pick.
  - "Vision agrees with Haiku" path: list unchanged, source still flips to
    `vision_hud` (confidence upgrade reflected without a no-op write).
- `tests/phase2_smoke/test_arena_augment_hud.py` — 7 new unit tests bound
  to the real `Coach._reconcile_augment_hud` via a `_StubCoach` shim that
  avoids pulling Anthropic + the BaseCoach lifecycle. Covers: override
  when all resolve, confirm path, partial-resolve preservation, empty/missing
  HUD no-op, dedup within vision slots, full player-deviation override.
- Memory `project_arena_augments_not_persisted.md` — bumped from "RESOLVED
  via Haiku" to "RESOLVED with vision-confirmed v2" with the two-tier
  confidence model documented + the all-or-nothing rationale.

**Test state:** 307/307 green (`agents/daemon_slayer/tests/` 226 + 7 new
arena augment HUD + 74 phase2_smoke from prior). No engine bump — engine
unchanged; behavior change is upstream of the engine's augments= kwarg.

**Decisions worth pinning:**
- Override is all-or-nothing on slot resolution. A single unresolved slot
  preserves Haiku's list. Picking "max-length wins" or "merge" was
  considered + rejected — too easy for a misread to corrupt a confirmed
  pick list.
- Vision source flips to `vision_hud` even when it agrees with Haiku,
  because the dashboard / postgame should know the picks were
  vision-confirmed (tier-2 confidence) not just Haiku-predicted.
- Cadence: no second vision poll. Reuses the existing 12s
  `_VISION_INTERVAL` tick. Worst-case staleness between pick + override = 12s.
- Tests stub the resolver via `mock.patch.object(arena_coach,
  "_resolve_augment_apiname", ...)` — independent of cdragon snapshot
  rotation. Faster + reproducible across patch refreshes.

**Things tomorrow-you should NOT redo:**
- Don't replace the all-or-nothing guard with "merge" or "max-length
  wins" — see updated memory rationale.
- Don't add a separate vision-call cadence for HUD slots — the prompt
  field rides the existing 12s tick.
- Don't gate `_reconcile_augment_hud` on `_picked_augments` being
  non-empty — the reconciler is idempotent + always-on by design (a
  player's first pick happens mid-game; reconciler must catch it).
- Don't import the full Coach class in tests — the `_StubCoach` shim
  pattern keeps the test independent of Anthropic + BaseCoach lifecycle.

**Activation:** Change is in `coaches/arena_coach.py` — RC main loads it
on next restart. Live activation requires `echo restart > restart_trigger.txt`.
DEFERRED to next user request (no live arena game in progress, LCU=Lobby).

**Next-session candidates (ranked):**
1. **Phase 8 — SR Draft Theatre kickoff.** Fresh arc, beam search
   foundation already in place from s45. LCU draft subscription +
   3-build profile (primary, alt-playstyle, experimental) + runes/spells
   writer + push-to-League. Operator-additive: user-curated experimental
   builds APPEND, never overwrite. Multi-session arc — start with `/clear`
   and a planning pass.
2. **Phase 5 (Mayhem augments)** — STILL DEFERRED (no clean cdragon dump).
3. **Activate v2 in production** — `echo restart > restart_trigger.txt`
   when RC is between games. Verify next arena run that
   `data/arena_coaching_data.json` shows `augments_source` flipping to
   `vision_hud` after the post-pick HUD vision tick.

**Bridge state at session end:** RC main pid=9328 alive=true reload_ok=true.
Engine on :8893 still 0.9.3 (no engine change this session). LCU
phase=Lobby (safe to /clear). Working tree pre-commit:
- `coaches/arena_coach.py` (~50 lines added)
- `tests/phase2_smoke/test_arena_augment_hud.py` (new, 130 lines)
- `WAKEUP_NOTES.md` (this s50 hand-off)
- `data/ratings/last_arena.json` + `last_sr.json` (runtime, untouched)

**/done close-out (2026-05-04):** committed + pushed `0894e5a..3c0fc8c
main -> main`. LCU phase=Matchmaking at session-end (queueing, no
in-game state lost on /clear). **Game-PC bridge auto-flow loop is
DEAD** — 90s liveness probe (task-1311d83782c3) timed out. Re-run
`/loop /process-bridge-tasks` on Game-PC at next session start, or
results will pile up unread.

## s51 hand-off — 2026-05-04 (Daemon Slayer Phase 8 backend complete: P8-1..P8-4)

Single-arc session. Phase 8 (SR Draft Theatre) backend is now fully
shipped over four discrete commits — engine-backed profile generator,
user-curated additive store, and LCU spells writer hardening, all on
top of a route + state-flag thin slice. Frontend (P8-5/P8-6) deferred
to a fresh session.

**Shipped (4 commits, all pushed `1e17ee4..97f94e0 main -> main`):**
- `8ff001e` P8-1: `coaches/sr_draft_profile.py` stub + `dashboard/routes_sr_draft.py` POST `/api/sr-draft/profile` + `lcu.champ_select.sr_draft` flag derivation in `_state_builder` for queue ids {400,420,430,440}.
- `13c2e5e` P8-2: engine-backed body — 3 `/beam` calls per profile-pull (primary/alt/experimental), TTL cache by (champ, role, allies_sig, enemies_sig), mtime-aware `data/daemon_slayer/sr_draft_presets.json`, role normaliser with MID/BOT/ADC/SUP/JG aliases, graceful URLError/HTTPError handling.
- `fd9fc4f` P8-3: `coaches/sr_user_builds.py` CRUD on `data/daemon_slayer/user_builds.json` (gitignored, 8-hex IDs, atomic write w/ WinError-5 retry, mtime cache, threading.Lock) + `dashboard/routes_sr_user_builds.py` (GET ?champion= + POST action-keyed for list/add/update/delete) + route-layer merge in `routes_sr_draft._serve_sr_draft_profile_post`. Operator-additive invariant preserved — sr_draft_profile.py never reads or writes user_builds.json; merging happens at the route, kind="engine"/kind="user" tags differentiate.
- `97f94e0` P8-4: `lcu/lcu_pregame.py` SPELLS_BY_ROLE table + `spells_for_role()` helper + `set_summoner_spells(*, current_pair=None)` keyword-only kwarg for idempotent skip when target matches current. Backwards-compat preserved (one existing positional caller in lcu_rune_writer.py:468 unaffected).

**Test state:** 63/63 phase8_smoke green (15 stub + 18 engine + 19 user-builds + 11 spells). 75/75 phase2_smoke regression green across all 4 RC restarts. Engine on :8893 still 0.9.3 (no engine change this session).

**Decisions worth pinning:**
- **Plan agent picked Phase 8 over Phase 5.** Phase 5 (Mayhem augments) still blocked on cdragon dump.
- **Polling not WebSocket** for `/lol-champ-select/v1/session` — gamepc_lcu_agent already polls and surfaces via `/api/state`; no second WS subscriber.
- **JSON not SQLite** for user_builds — operator-edit affordance, project convention (mirrors champion_loadouts.json/experimental_builds.json), atomic-write idiom already exists.
- **Merge at route layer, not in build_profile()** — keeps the engine generator pure.
- **Frozen-file edits avoided.** Plan flagged `lcu_rune_writer.py`'s shard3=5002 SR bug + `_write_page` rune-name collision; both deferred. SR-draft variants will route through `/api/loadout/apply` which calls `set_summoners` independently of the rune writer's poll loop, dodging the conflict.

**Things tomorrow-you should NOT redo:**
- Don't propose ARAM bench-swap auto-recommendation — already in `champ_select_coach.swap`.
- Don't touch `lcu_rune_writer.py` for Phase 8 — architecture pivot routes around it.
- Don't bump engine version for the UI commits — `/beam` shape is stable; no engine change needed for P8-5/P8-6/P8-7.
- Don't merge user builds inside `sr_draft_profile.py` — operator-additive invariant requires merge at route layer only.
- Don't add a second `_state_builder` import path for `sr_draft` flag — the single derivation in `build_state()` covers all callers.

**Activation status:** All 4 commits live as of pid=8104 (last_reload_ok=true). `POST /api/sr-draft/profile` returns 3 engine + N user profiles end-to-end; `POST /api/sr-draft/user-builds` CRUD works; `lcu.champ_select.sr_draft` true on draft-queue states.

**Next-session candidates (ranked):**
1. **P8-5 — `cs-build-list` UI extension for SR draft.** Now unblocked (depended on P8-2 + P8-3, both done). ~300 LOC of `web/js/dashboard.js`. Gate the new chooser on `state.lcu.champ_select.sr_draft===true`; debounced fetch of `/api/sr-draft/profile`; render 3 engine rows + N user rows w/ keystone + start/core/final columns; click → new `/api/sr-draft/apply` (mirrors `_serve_loadout_apply_post` at routes_loadout.py:62). UI work — requires browser screenshot via `mcp__gamepc__capture_monitor` per `feedback_screenshot_after_ui_changes`.
2. **P8-6 — User-build CRUD UI sub-page.** Independent of P8-5; only depends on P8-3. Add `view-user-builds` via the established sub-page pattern in `web/index.html` + VIEW_IDS in dashboard.js + 3 CSS rules.
3. **P8-7 — E2E push-to-League integration test.** Blocked on P8-5 (apply route). Verify rune-page name uniqueness (`RC: <Champ> primary (SR)` etc) so concurrent variants don't clobber each other via `_write_page`'s delete-all-RC-pages step.
4. **Activate v2 in production** for the *arena* augment vision flow (still relevant from s50; v2 reconciler ships with current RC so just needs an arena game to verify `augments_source` flips to `vision_hud`).

**Bridge state at session end:** RC main pid=8104 alive=true reload_ok=true. Engine on :8893 still 0.9.3. LCU phase=Lobby (safe to /clear). Working tree post-commit:
- 4 commits pushed; only `data/ratings/last_*.json` runtime mutations dirty (auto-mutated, skipped).

**/done close-out (2026-05-04):** auto-committed nothing (only runtime junk pending); pushed `1e17ee4..97f94e0 main -> main` (4 commits). **Game-PC bridge auto-flow loop is DEAD** — fresh 90s liveness probe (task-294ce6e18cff) returned 0 replies, task not queued on Game-PC side either. Re-run `/loop /process-bridge-tasks` on Game-PC at next session start.

## s52 hand-off — 2026-05-04 (Phase 8 step 5: SR Draft Theatre chooser UI)

Single-arc session. Closed P8-5 — the operator-facing chooser UI plus
the apply route that translates a chosen profile into LCU commands.
Committed + pushed `1d59425` on top of s51's backend.

**Shipped (commit `1d59425`, pushed `8509533..1d59425 main -> main`):**
- `dashboard/routes_sr_draft.py`: POST `/api/sr-draft/apply` route +
  helpers `_build_page_name` (unique per `<Champ>+<key>`),
  `_build_item_set` (apply_item_set wrap), `_build_rune_cmd`
  (delegates to frozen `lcu_rune_writer.build_perk_ids`). Each variant
  gets a distinct rune page so concurrent saves don't clobber via the
  rune writer's RC: delete sweep.
- `web/index.html`: `#cs-srdraft-block` sibling of `#cs-loadout-block`
  with role chip selector (auto/top/jungle/middle/bottom/utility) +
  status line + `#cs-srdraft-list`.
- `web/js/dashboard.js` (~280L): `_srDraft` state + `_srDraftRenderRows`,
  `_srDraftFetchProfile` (1.5s debounce on `(champ|role|allies|enemies|queue)`
  signature), `_srDraftOnRowClick`, `_srDraftMaybeRender`. Hooks into
  `applyChampSelectOverlay` alongside the existing loadout chooser.
  Per-row engine stat line (dps + gold) for at-a-glance comparison;
  `engine`/`user` kind tags differentiate the two profile sources.
- `web/css/dashboard.css` (~34L): role chip wrapper, kind tag styling,
  engine-stats line. Reuses existing `.cs-build-row` primitive.
- `tests/phase8_smoke/test_sr_draft_apply.py` (12 new tests): 400 paths,
  full happy-path enqueue, push_* flag suppression, unique page-name
  builder, item-set shape, fallback notes when runes fail.

**Test state:** 75/75 phase8_smoke green (was 75 before; 12 new tests
exercise the new apply route — replacing the equivalent shape-only
stub coverage). 75/75 phase2_smoke regression green.

**Decisions worth pinning:**
- **Sibling block, not replacement.** SR-draft chooser sits BELOW the
  existing loadout chooser, so user-curated `champion_loadouts.json`
  variants stay visible during draft. Both are valid pre-pick targets.
- **Role chip in header, not auto-derived.** `gamepc_lcu_agent.py`
  doesn't surface `assignedPosition`; rather than touch the LCU agent
  this session, the chooser exposes a 6-option `<select>` (auto /
  TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY) saved to localStorage. Auto = role=null,
  engine generator picks BOTTOM rune defaults. Plumbing role through
  the LCU agent is a P8-5.5 follow-up.
- **Shard3=5002 SR rune writer bug knowingly ridden.** Per s51 plan,
  apply route routes through the frozen rune writer; the documented
  shard issue (`project_rune_writer_shard3_not_applied`) is engine
  scope, not Phase 8 scope. Unique page name dodges the variant-clobber
  half of the dodge though.
- **Apply route trusts pre-resolved item_ids.** Profiles arrive with
  `item_ids` already resolved (engine output OR `_resolve_item_ids`
  inside `sr_user_builds.format_for_display`). Apply route doesn't
  re-resolve — keeps the UI-side push thin.

**Things tomorrow-you should NOT redo:**
- Don't replace the SR-draft block by overwriting `#cs-build-list` —
  user-curated `champion_loadouts.json` variants stay visible by design.
- Don't auto-derive role from `cs.my_team` heuristics; the role chip
  is the operator's source of truth this session. If/when the LCU agent
  surfaces `assignedPosition`, it can pre-populate the chip default.
- Don't add `set_uid` per-champion conflict resolution — the existing
  set_uid `RC-<champ>-sr-<key>` is uniquely keyed per (champion, profile)
  and the LCU agent's apply_item_set replaces by uid.
- Don't bump the engine version — Phase 8 step 5 is dashboard + route
  layer; engine on :8893 remains 0.9.3.

**Activation status:** Static assets (HTML/CSS/JS) are served
per-request and live now (no Edge restart needed beyond Ctrl+F5). The
new POST route requires RC reload to register. **DEFERRED — operator
mid-Arena game** (`has_game=True`, `mode=arena`). Restart at next
between-games window via `echo restart > restart_trigger.txt`. Visual
verify post-restart: enter a draft queue (400/420/430/440), confirm
`#cs-srdraft-block` appears below `#cs-loadout-block` with engine + user
rows. Mid-Arena Game-PC dashboard capture confirmed no regression in
existing chooser (block correctly hidden when sr_draft===false).

**Next-session candidates (ranked):**
1. **Activate P8-5 + first draft verify.** `echo restart > restart_trigger.txt`
   when between games. Confirm new POST route reachable; confirm UI
   renders + click→apply path round-trips end-to-end through gamepc_lcu_agent.
2. **P8-5.5 — surface `assignedPosition` from gamepc_lcu_agent.py.**
   Add `role` to `_team_picks` + champ_select payload so the role chip
   pre-populates from LCU rather than localStorage default. Single-line
   add to `tools/gamepc_lcu_agent.py`; deploy via `gamepc_boot.ps1`.
3. **P8-6 — User-build CRUD UI sub-page.** Independent of P8-5;
   `view-user-builds` via the established sub-page pattern.
   Operator-facing add/edit/delete for `data/daemon_slayer/user_builds.json`.
4. **P8-7 — E2E push-to-League integration test.** Now unblocked
   (apply route shipped). Real arena/draft with all 3 engine variants
   pushed back-to-back, verify rune pages have distinct names + items
   apply correctly.
5. **Activate arena augment v2 in production** — still relevant from
   s50; reconciler ships with current RC, just needs an arena game to
   verify `augments_source` flips to `vision_hud`.

**Bridge state at session end:** RC main pid=8104 alive=true
reload_ok=true. Engine on :8893 still 0.9.3 (no engine change this
session). LCU phase=InProgress (mid-Arena). Working tree post-commit:
- `1d59425` pushed; only `data/ratings/last_*.json` runtime mutations
  dirty (auto-mutated each game tick, skipped from commit).

## s53 hand-off — 2026-05-04 (Phase 8 step 6: User Builds CRUD sub-page)

Single-arc session. Closed P8-6 — operator-facing CRUD UI for the
additive user-curated SR draft builds. Pure frontend (HTML/CSS/JS); no
RC restart required since `/api/sr-draft/user-builds` shipped in P8-3.
Committed + pushed `30ddf46` on top of s52.

**Shipped (commit `30ddf46`, pushed `cc58cf5..30ddf46 main -> main`):**
- `web/index.html`: `view-user-builds` section (~90L) with toolbar
  (champion datalist + add btn + status hint) and two-pane layout —
  left ub-build-list, right ub-form-pane (hidden until + Add or Edit).
  Form fields cover label/role/keystone/primary/secondary/spell-d/
  spell-f/items/notes to mirror `sr_user_builds._normalize_record`.
- `web/js/dashboard.js` (~290L): `_UB` state object, `_userBuildsWireOnce`,
  `_userBuildsFetchAndRender`, `_userBuildsOpenForm/Save/Delete/Close`,
  `_ubChampionPicked` with localStorage sticky champ
  (`rc-ub-last-champ`), datalist populated from `/api/champions` cache,
  300ms debounce on champion input, items as one-per-line textarea.
  VIEW_IDS gained "user-builds"; applyView dispatch added.
- `web/css/dashboard.css` (~120L): `.ub-toolbar`, `.ub-layout` 2-pane
  grid, `.ub-build-row`, `.ub-form-grid`, `.ub-btn-{primary,ghost,danger,tiny}`,
  `.ub-form-status.{ok,error}`. 3 view-router rules added (main hide,
  view-user-builds show, home-overlay hide).

**Decisions worth pinning:**
- **Items as free-text textarea** (one per line). Server's
  `_resolve_item_ids` does ddragon lookup; UI doesn't need autocomplete.
- **Champion picker as datalist, not select.** Cheaper than rendering
  170+ option elements in DOM; lets operator type-narrow.
- **localStorage sticky champion** (`rc-ub-last-champ`) — operator
  almost always returns to the same champion they were curating.
- **Form pane hidden by default** — list is the primary surface;
  + Add / Edit buttons reveal the form. Keeps the layout calm when
  the operator is just browsing.
- **No new tests.** Backend already covered by 75/75 phase8_smoke;
  this is pure UI. Visual smoke deferred (operator mid-Arena).

**Things tomorrow-you should NOT redo:**
- Don't add a new POST route for user-builds — `/api/sr-draft/user-builds`
  already does CRUD via action-keyed payload (P8-3, `routes_sr_user_builds.py`).
- Don't make the items field anything fancier than a textarea — server
  resolves names; autocomplete adds no value to a power-user UI.
- Don't pre-populate the champion picker from in-game state — operator
  curates between games for upcoming champions, not for the current
  picked one. Sticky last-edited via localStorage is the right default.
- Don't bump the engine — Phase 8 step 6 is dashboard-only.

**Activation status:** Static assets — Edge Ctrl+F5 picks up. New POST
route already live (P8-3 work). Curl-confirmed all 3 served assets
contain new code (3 HTML hits, 11 JS hits, 5 CSS hits). Visual verify
deferred — operator mid-Arena (`mode=arena, has_game=true,
liveclient.game_time=8:02 round`). Mid-Arena dashboard capture
confirmed no regression (existing UI unchanged; Edge still on old JS).

**Next-session candidates (ranked):**
1. **P8-5 + P8-6 visual verify.** Post-game Ctrl+F5, navigate to
   "User Builds" menu item, add a test build for a champion, then
   enter a draft queue (400/420/430/440) to confirm it appears in
   the SR-draft chooser as `kind=user`. Confirms both halves of the
   end-to-end loop.
2. **P8-5.5 — surface `assignedPosition`** from `gamepc_lcu_agent.py`
   so the role chip pre-populates from LCU instead of localStorage
   default. Single-line add to LCU agent's `_team_picks`; deploy via
   `gamepc_boot.ps1`. Cross-machine task.
3. **P8-7 — E2E push-to-League integration test.** Now unblocked
   (apply route shipped P8-5). Real arena/draft with all 3 engine
   variants pushed back-to-back, verify rune pages have distinct
   names + items apply correctly.
4. **Activate arena augment v2 in production** — still relevant from
   s50; reconciler ships with current RC, just needs an arena game to
   verify `augments_source` flips to `vision_hud`.

**Bridge state at session end:** RC main pid=9488 alive=true
reload_ok=true (no restart this session — pure frontend). Engine on
:8893 still 0.9.3. LCU phase=N/A in /api/state but liveclient
game_time=8:02 (mid-Arena). Game-PC bridge auto-flow loop ALIVE —
fresh probe (task-94931d114aec) returned reply within ~28s.

**/done close-out (2026-05-04):** auto-committed nothing new (only
runtime junk pending — `data/ratings/last_*.json` auto-mutated every
game tick, skipped). 1 commit shipped this session, already pushed
`cc58cf5..30ddf46`. No background tasks active. 0 pending lessons
from peers.

## s54 hand-off — 2026-05-04 (Phase 8 step 5.5: LCU assignedPosition → SR-draft role chip)

Single-arc session. Closed P8-5.5 — the SR-draft chooser role chip
now pre-populates from LCU's `assignedPosition` instead of localStorage,
so an operator dropping into a draft queue sees the engine generator
keyed to the lane LCU assigned them rather than their last-saved
default. Touched `tools/gamepc_lcu_agent.py` + `web/js/dashboard.js`.

**Shipped (commit `49008ab`, pushed `7c3f795..49008ab main -> main`):**
- `tools/gamepc_lcu_agent.py`: `_team_picks()` now surfaces
  `"assignedPosition": p.get("assignedPosition") or ""` for every
  player in `myTeam` + `theirTeam`. One-line addition; LCU API field
  is one of `top|jungle|middle|bottom|utility` (lowercase) or `""`
  for blind/ARAM queues.
- `web/js/dashboard.js`:
  - `_srDraft.userEdited` flag (default `false`) tracks whether the
    operator manually changed the role chip this session.
  - `_srDraftRoleFromLcu(cs)` helper finds the local player in
    `cs.my_team` (matched by `cs.local_cell`), upper-cases
    `assignedPosition`, alias-coerces (MID→MIDDLE, BOT/ADC→BOTTOM,
    SUP/SUPPORT→UTILITY, JG→JUNGLE), returns one of the 5 canonical
    role keys or `""`.
  - `_srDraftWireRoleSelectOnce` change handler sets
    `_srDraft.userEdited = true` so explicit operator picks lock out
    LCU pre-population for the rest of the session.
  - `_srDraftMaybeRender`: if `!userEdited && lcuRole`, sets the
    `<select>` value to `lcuRole` and uses it for the fetch; else
    falls through to the chip's current value (which mirrors
    `localStorage`).

**Decisions worth pinning:**
- **LCU wins on auto-fill, operator wins on explicit edit.** Once the
  operator manually picks a role this session, LCU pre-population
  stays out of their way until the page reloads. Reset semantic is
  page-load (intentional — drafts are short).
- **No backend change.** `sr_draft_profile._normalize_role` already
  accepts lowercase + alias spellings via `.upper()` + alias map, so
  the role string flows through unchanged. No engine bump.
- **No JS test infra in this project; skipped.** The `_srDraftRoleFromLcu`
  helper is small + unit-testable in shape, but adding a JS test runner
  is out of scope for one helper. Visual smoke deferred (see below).
- **assignedPosition is a no-op for blind/ARAM/Arena queues.** Returns
  `""`; the dashboard fallback to localStorage preserves existing
  behavior. No regression risk for non-draft queues.

**Deploy notes (Game-PC redeploy required):**
- The dashboard JS change is live immediately (web/* served per-request).
- `gamepc_lcu_agent.py` had to be re-pulled on Game-PC + the long-lived
  agent process restarted before the new field flows into `/api/state`.
- **Direct-deploy path used** (bridge auto-action lane hijacked the
  initial bridge task; see "Things tomorrow-you should NOT redo"):
  1. Pulled `https://legion-rc:8888/agent/gamepc_lcu_agent.py` →
     `C:\RC-Agent\gamepc_lcu_agent.py` via `curl.exe -sk` on Game-PC
     (PowerShell's `Invoke-WebRequest` failed with "underlying
     connection closed" — Game-PC's `Invoke-WebRequest` is broken on
     this RC HTTPS endpoint despite same-cert mkcert install; curl
     works fine).
  2. `taskkill /F /PID` on the two existing agent processes (the
     `schtasks /End /TN RC-LCU` did NOT kill them; per CLAUDE.md
     hard rule).
  3. `schtasks /Run /TN RC-LCU` returned `Last Result: -2147024894`
     (= ERROR_FILE_NOT_FOUND) because the task command is `py
     C:\RC-Agent\gamepc_lcu_agent.py` and `py` doesn't resolve in
     scheduled-task context outside of boot — same root cause as
     `project_rc_patchrefresh_fixed.md` on Legion. Fix is to swap
     `py` for absolute python.exe path in `tools/gamepc_boot.ps1:192`
     (NOT done this session; see backlog below).
  4. Started agent directly via
     `C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe
     C:\RC-Agent\gamepc_lcu_agent.py` (Start-Process, hidden window).
     Confirmed alive after 4s; confirmed `lcu.ts` advancing on
     Legion's `/api/state`.

**Verification status:**
- Code change verified: served `/agent/gamepc_lcu_agent.py` contains
  the new field; served `/js/dashboard.js` contains all three new
  tokens (`userEdited`, `_srDraftRoleFromLcu`, `P8-5.5`).
- Agent restart verified: fresh process running on Game-PC with the
  new code; `lcu.ts` on `/api/state` is current.
- End-to-end verification (assignedPosition flowing through) **NOT**
  done this session — operator was mid-game (LCU phase=InProgress,
  `champ_select.my_team` empty by definition mid-game). First draft
  queue (400/420/430/440) after this session will validate.

**Things tomorrow-you should NOT redo:**
- Don't dispatch the deploy via `bridge_task.py --target gamepc` —
  the Game-PC bridge_watcher classifier matched the prompt to an
  `auto-read` lane (probably keyword like "verify" or "Select-String"),
  spawned a Claude subprocess that died with `^C` (exit code
  3221225786 = STATUS_CONTROL_C_EXIT, "claude subprocess output
  unparseable"), and posted a result entry blocking `/loop /process-bridge-tasks`
  from picking the task up. Bridge auto-action flow was hijacked.
  Use direct `mcp__gamepc__run_powershell` instead OR craft prompts
  that hit the frozen-intent gate to force escalation.
- Don't try `Invoke-WebRequest` from Game-PC PowerShell against
  RC's `:8888` HTTPS — fails with "underlying connection closed"
  even with TLS12 + cert-validation override. Use `curl.exe -sk`
  instead. Probably a schannel/SNI quirk; not investigated.
- Don't restart RC-LCU via `schtasks /Run /TN RC-LCU` after a manual
  kill — the `py` launcher fails ERROR_FILE_NOT_FOUND under
  scheduled-task context. The task only works at boot when WindowsApps
  PATH is rich. Until `tools/gamepc_boot.ps1:192` is patched to use
  absolute `python.exe`, manual restarts must use `Start-Process` with
  the absolute path.
- Don't add a JS test runner just for `_srDraftRoleFromLcu` — the
  helper is too small to justify infra. Visual smoke at next draft
  is enough.
- Don't reset `_srDraft.userEdited` between drafts — the page-load
  reset semantic is intentional. Operator who explicitly chooses
  SUP for one draft probably wants SUP for the next draft of the
  session too.

**Operational backlog (carried + new):**
- **gamepc_boot.ps1 `py` → absolute python.exe** (NEW). Same fix
  pattern as `project_rc_patchrefresh_fixed.md`. Affects all 5+
  agent tasks on Game-PC (RC-LCU, RC-LiveClientRelay, RC-MCP-Server,
  RC-HotkeyListener, RC-ScreenAgent-*). Low priority since they all
  work at boot; only manual mid-session restarts hit the bug.
  Operator-mutable, not frozen.
- **Bridge auto-action lane vs. operator deploy tasks** (NEW). The
  bridge_watcher classifier on Game-PC matched a deploy prompt to
  `auto-read` and tried to execute it as a Claude subprocess. The
  subprocess died with `^C`; result was posted to bridge log
  blocking the `/loop /process-bridge-tasks` pickup. This is a
  classifier false-positive that needs investigation, but
  bridge_watcher_classify.py is **frozen** per CLAUDE.md — needs
  explicit operator approval to touch. Workaround: use direct MCP
  for cross-machine deploys.
- All s53 backlog items unchanged (P8-5/P8-6 visual verify, P8-7
  E2E push test, arena augment v2 activation).

**Activation status:**
- Legion-side: dashboard.js change live (Edge picks up via Ctrl+F5);
  no RC restart needed (no Python code changed on Legion side, the
  static asset is served per-request).
- Game-PC-side: new agent running fresh PID under absolute python
  path; will survive normal operation; if rebooted, the boot script's
  `schtasks /Run RC-LCU` should succeed (boot-time PATH is rich).

**Next-session candidates (ranked):**
1. **First draft visual verify** — when operator next enters a draft
   queue (400/420/430/440), confirm:
   - `cs.my_team[i].assignedPosition` populated with one of
     `top|jungle|middle|bottom|utility` for each picker (Edge devtools
     console: `await fetch('/api/state').then(r=>r.json()).then(j=>console.table(j.lcu.champ_select.my_team))`).
   - SR-draft role chip auto-selects the local player's role on initial
     render.
   - Manually changing the chip locks out further LCU auto-fill.
2. **gamepc_boot.ps1 `py` → absolute python.exe** — 1-line patch
   matching `project_rc_patchrefresh_fixed.md`. Tiny win; eliminates
   manual-restart footgun.
3. **P8-7 E2E push-to-League integration test** — now unblocked
   (apply route + role pre-population both shipped). Real arena/draft
   with all 3 engine variants pushed back-to-back, verify rune pages
   have distinct names + items apply correctly.
4. **Activate arena augment v2 in production** — still relevant from
   s50; reconciler ships with current RC, just needs an arena game
   to verify `augments_source` flips to `vision_hud`.

**Bridge state at session end:** RC main pid=9488 alive=true
reload_ok=true (no Legion restart this session). Engine on :8893
still 0.9.3. LCU phase=InProgress (mid-arena). Game-PC LCU agent
freshly restarted (pid=15696, started 02:40:07 via direct
`Start-Process` not scheduled task). Working tree post-commit:
- `49008ab` pushed; only `data/ratings/last_*.json` runtime mutations
  dirty (auto-mutated each game tick, skipped from commit).

## s55 hand-off — 2026-05-04 (Phase 4 expansion batch 2: 10 defensive_only SR legendaries)

Single-arc continuation of s54. Picked Phase 4 expansion as the next
DS arc that's actionable without a live draft queue. Closes coverage
gap on 10 high-pickrate SR legendaries that the s44 (b44ed02)
"Phase 4 expansion 25 marquee items" batch left uncovered.

**Shipped (commit `994ceb1`, pushed `4e6f20a..994ceb1 main -> main`):**
- `agents/daemon_slayer/effects.py`: 10 new `defensive_only` entries
  in `ITEM_EFFECTS` — `6333` Death's Dance, `3161` Spear of Shojin,
  `3508` Essence Reaver, `3084` Heartsteel, `3083` Warmog's Armor,
  `3139` Mercurial Scimitar, `3026` Guardian Angel, `3102` Banshee's
  Veil, `3157` Zhonya's Hourglass, `6631` Stridebreaker.
- `agents/daemon_slayer/tests/test_effects_expansion.py`: new
  `DefensiveOnlyBatch2Tests` class (3 methods × 10 items table-driven
  = covers presence + flag + zero-on-every-DPS-field + note
  non-emptiness for all 10). `CoverageCountTests` lower bound bumped
  `>=30` → `>=40`.
- `agents/daemon_slayer/__init__.py`: docstring narrative refreshed
  (13 → 23 defensive_only items); `ENGINE_VERSION 0.9.3 → 0.9.4`
  (patch bump matching the convention from Phase 6 step 5 `d2bb840`
  which bumped patch for the augment overlay registry expansion).

**Test state:** 235/235 daemon_slayer tests green (was 232; +3
DefensiveOnlyBatch2Tests methods). 75/75 phase8_smoke regression
green. Phase4 expansion suite alone: 36/36 green.

**Coverage delta (SR legendaries, purchasable, no upgrade, total>=2500):**
29/122 (24%) → 39/122 (32%). 83 SR legendaries remain uncovered;
top still-uncovered by gold cost include Rabadon's Deathcap (3089,
needs an AP-amp layer the engine doesn't have yet), Ravenous/Titanic
Hydra (3074/3748, AoE cleave not modeled), Dusk and Dawn (2510),
Bastionbreaker (2520), Endless Hunger (2517), Overlord's Bloodmail
(2501) — those four are the new ARENA-tier prismatic items, classify
later.

**Decisions worth pinning:**
- **All 10 are defensive_only.** None of these items have a clean
  per-attack DPS proc that fits the existing `PeriodicProc` shape
  without schema bumps. Death's Dance bleed = damage storage (not
  amplification); Spear of Shojin = CDR stacks; Essence Reaver =
  mana refund + CDR; Heartsteel = single-target charged slam (not
  in DPS rotation); Warmog's = out-of-combat regen; the rest are
  pure utilities (cleanse/revive/spellshield/stasis/active dash).
- **Patch bump (0.9.3 → 0.9.4), not minor.** No schema change, no
  API change, no engine code change. Pure data-table addition.
  Precedent: Phase 6 step 5 `d2bb840` (registry expansion = patch).
  Minor-bump precedent (`0.6.0 → 0.7.0` on b44ed02) was justified
  by schema bump (CallContext + callable bonus_damage); doesn't
  apply here.
- **Test pattern: table-driven not per-item.** s47/s49's expansion
  tests are per-item assertions; 10 items × 4 fields = 40 lines of
  near-identical asserts. New `DefensiveOnlyBatch2Tests.EXPECTED`
  dict + 3 loop tests is tighter and surfaces missing items by name
  in the assertion message.
- **Notes are crisp + structured.** Every entry's note explains
  WHY it's defensive_only with a model gap callout — "target HP not
  modeled in Phase 4", "AoE cleave not modeled", "CDR not modeled".
  This makes the table grep-friendly when future schema work lands
  (e.g. "search for 'target HP not modeled' to find promotion
  candidates when Phase 4+ adds target_hp to CallContext").

**Things tomorrow-you should NOT redo:**
- Don't try to add Rabadon's Deathcap as a defensive_only or via
  ITEM_EFFECTS — its AP amp passive isn't a periodic proc; it's a
  multiplicative stat layer. Engine would need a per-item
  stat-multiplier mechanism (analogous to mode modifiers) to model
  it. Skip until that hook lands.
- Don't add Hydras (Ravenous 3074 / Titanic 3748) as periodic procs
  — their cleave damage is real but only fires on AoE and against
  multiple targets, neither of which DPS scoring models (single-target
  by design). They'd need a ScenarioContext extension for "expected
  enemies in cleave radius". Mark defensive_only only when the
  scenario hook makes the model-gap explicit.
- Don't bump CoverageCountTests' lower bound past `>=40` until the
  next batch lands. Future expansion batches should keep the floor
  fresh; lifting the floor here would mean a future regression
  (someone removing entries) wouldn't trip the test.
- Don't try to extend `CallContext` with `ap` for spellblade/Nashor's
  variants this session — that's a schema bump that needs a minor
  version, plus the engine's stats path doesn't surface AP as
  cleanly as `bonus_ad`. Worth doing as a focused next session.

**Activation:** `RC-DaemonSlayer` scheduled task restart required
to load 0.9.4 on :8893. Operator currently mid-arena
(`liveclient.game_time=18:24`, phase=InProgress). DEFERRED per s47
precedent — restart at next between-games window via:
```
schtasks /End /TN RC-DaemonSlayer  &&  schtasks /Run /TN RC-DaemonSlayer
```
or via `Start-Process` with absolute python path if the scheduled
task hits the same `py` launcher bug as RC-LCU did (s54 backlog).

**Operational backlog (carried + new):**
- All s54 backlog items unchanged: gamepc_boot.ps1 `py → python.exe`
  patch; bridge auto-action lane false-positive on deploy prompts.
- **AP-aware CallContext** (NEW) — add `ap: float` field to
  `effects.CallContext` so spellblade variants (Lich Bane 3100,
  Nashor's Tooth 3115) and AP-scaling on-hits can promote out of
  defensive_only. Schema bump = minor version. ~6 items unlock per
  session.
- **Magic pen layer** (NEW) — add `magic_pen_pct` /
  `magic_pen_flat` fields to `ItemEffect` and an
  `effective_target_mr()` function mirroring `effective_target_armor`.
  Unlocks Void Staff (3135), Cryptbloom (3137), Sorcerer's Shoes
  (3020 boot), Haunting Guise components. Schema bump = minor
  version. Symmetric to the existing armor pen pipeline.

**Next-session candidates (ranked):**
1. **First draft visual verify of P8-5.5** (carried from s54). Needs
   operator in draft queue 400/420/430/440. Confirms:
   - `cs.my_team[i].assignedPosition` populated.
   - SR-draft chooser role chip auto-selects from LCU.
   - Manual chip change locks out auto-fill.
2. **Phase 4 batch 3: AP-aware CallContext + spellblade variants**.
   Schema bump (0.9.4 → 0.10.0). Add `ap` to CallContext, then
   promote Lich Bane / Nashor's Tooth / Hextech Gunblade out of
   defensive_only into proper periodic entries. ~5-7 items unlocked.
3. **Phase 4 batch 4: magic pen layer**. Schema bump (probably
   alongside #2 if both ship same session). Unlocks Void Staff /
   Cryptbloom / Sorcerer's Shoes / Haunting Guise. Symmetric to
   armor pen — same `EffectiveTargetArmorTests` pattern reused.
4. **gamepc_boot.ps1 `py → python.exe` patch** (carried from s54).
   1-line patch matching `project_rc_patchrefresh_fixed.md`.
5. **P8-7 E2E push-to-League integration test** (carried from s53).
   Needs actual draft queue.
6. **Activate arena augment v2 in production** (carried from s50).
   Needs arena game.

**Bridge state at session end:** RC main pid=9488 alive=true
reload_ok=true (no Legion restart this session). Engine on :8893
STILL on 0.9.3 — 0.9.4 will activate at next RC-DaemonSlayer
restart. LCU phase=InProgress (mid-arena, game_time=18:24). Working
tree post-commit:
- `994ceb1` pushed; only `data/ratings/last_*.json` runtime mutations
  dirty (auto-mutated each game tick, skipped from commit).
- Game-PC LCU agent still running at PID 15696 (s54-spawned,
  uptime ~7 min as of session end) — `assignedPosition` field will
  flow when operator next enters a draft queue.

---

## s56 hand-off — 2026-05-04 (Phase 4 batch 3: AP-aware CallContext + spellblade)

Two-step session. Closed s55's deferred 0.9.4 activation, then shipped
the s55 backlog candidate #2 (AP-aware CallContext + spellblade
variants) end-to-end. Operator was idle (LCU phase=None, no liveclient)
so the engine restart window was open.

**Step 1 (cleanup):** RC-DaemonSlayer restart on a clean
`schtasks /End` + `schtasks /Run` cycle — engine on :8893 jumped
0.9.3 → 0.9.4 in ~4s. No PID coordination drama; the bare scheduled
task adopted cleanly.

**Step 2 — shipped (commit `12542c8`, pushed `479ea45..12542c8 main -> main`):**

- `agents/daemon_slayer/effects.py`: `CallContext.ap: float = 0.0`
  appended (default keeps every existing callable backward compatible).
  Two new periodic entries:
  - `3100` Lich Bane — Spellblade `0.75 * c.base_ad + 0.50 * c.ap`
    magic, `every_n_seconds=3.0` (same cadence approximation as
    TriForce — real CD 1.5s, gated by ability frequency in rotation).
  - `3115` Nashor's Tooth — Icathian Bite `15.0 + 0.20 * c.ap` magic,
    `every_n_attacks=1` (per-basic on-hit).
  Five new defensive_only entries with explicit model-gap notes:
  `3146` Hextech Gunblade (active), `6655` Luden's Echo (ability-bound),
  `4633` Riftmaker (combat-state amp), `4645` Shadowflame (target HP),
  `3128` Deathfire Grasp (active + target HP).
- `agents/daemon_slayer/dps.py`: 2-line plumb — `ap = float(stats.get("ap", 0.0))`
  + `ap=ap` kwarg into the per-`compute_dps` `CallContext` build.
- `agents/daemon_slayer/__init__.py`: docstring narrative refreshed
  (ap field call-out + 28 defensive_only count); `ENGINE_VERSION
  0.9.4 → 0.10.0`. Minor bump precedent: batch 1's 0.6.0 → 0.7.0
  (also CallContext schema change). Patch bump (s55) was data-only;
  this is a schema bump.
- `agents/daemon_slayer/tests/test_effects_expansion.py`: +14 tests
  in 3 new classes —
  - `CallContextApTests` (3) — default-zero, callable resolves against
    ap, combined base_ad+ap (mirrors Lich Bane formula).
  - `SpellbladeAndOnHitApTests` (8) — periodic-present + non-defensive,
    raises DPS bare→item, MR matters, scales with stacked AP. For
    Nashor's the AP-scaling test pairs Nashor + Lich Bane vs Nashor +
    Bloodthirster (no AP, same gold-ish) and asserts the AP companion
    wins.
  - `DefensiveOnlyBatch3Tests` (3 × 5 items table-driven) — same
    pattern as batch 2's `DefensiveOnlyBatch2Tests`. Fields zero,
    notes non-empty, `defensive_only=True`.
  - `CoverageCountTests` floor `>=40 → >=47`.

**Test state:** 249/249 daemon_slayer tests green (was 235; +14 from
this batch matches the math: 3+8+3=14). py_compile pre-commit hook
passed; no new warnings beyond the standard CRLF lint.

**Live engine verify (post-restart `schtasks /End` + `schtasks /Run`):**
```
GET  /health                          → 0.10.0 ok
POST /dps {champion:Aatrox, items:[3100], level:11}  → 91.23 (bare 47.07; +94%)
POST /dps {champion:Aatrox, items:[3115], level:11}  → 67.54 (+44%)
```
Notes surface on both responses ("Lich Bane: Spellblade ~75% base AD…",
"Nashor's Tooth: Icathian Bite on-hit…").

**Coverage delta:** ITEM_EFFECTS 40 → 47 entries (+7). Pickrate-weighted
SR legendary coverage stable around 32% (the batch is mostly midrange
AP items rather than top-pickrate marquee items). Real win is unlocking
two AP DPS items the engine previously couldn't model at all — Lich
Bane especially is mandatory on a number of AP bruisers and the
defensive_only fallback was severely underestimating their build value.

**Decisions worth pinning:**
- **`ap` default 0.0 keeps all pre-batch callables backward-compatible.**
  No call-site changes needed in any existing callable lambda — they
  bind by name (`c.base_ad`, `c.bonus_ad`, `c.level`) so the new
  optional field is invisible to them. Tests with `CallContext(...)`
  positional + missing ap continue to pass. Matches Python dataclass
  ergonomics.
- **Real-CD vs rotation-cadence approximation.** Lich Bane's real
  spellblade CD is 1.5s (haste-modified). In active League rotations
  the cadence is closer to 3s because it's gated by how often the
  champion casts an ability. Used the same approximation as TriForce
  (`every_n_seconds=3.0`) — under-counts on high-cast champs (Cassio,
  Anivia) and over-counts on low-cast (split-pushers). Fix would need
  a per-rotation `ability_casts_per_second` from lolmath scenarios;
  out of scope.
- **Hextech Gunblade as defensive_only.** Its on-hit was removed from
  the live game; current iteration is purely active-damage Lightning
  Bolt + omnivamp stat. Not a DPS-rotation contributor.
- **Riftmaker's HP→AP conversion is invisible to current stats.**
  `Void Infusion` (2% bonus HP → AP) would feed back into Lich Bane /
  Nashor's procs if modeled. Engine `aggregate_item_stats` doesn't do
  cross-item stat-derived stats; would need a 2nd-pass in
  `engine.build_champion`. Worth a follow-up if AP-bruiser builds
  start showing up wrong in user feedback.

**Things tomorrow-you should NOT redo:**
- Don't add Luden's Echo as a periodic — its 6 echo bolts trigger on
  ability cast, not basic attack, and don't fit the on-hit shape.
  Marking defensive_only with the "ability-bound" note is correct.
- Don't try to scale Wit's End or Trinity Force off `ap` — both are
  AD on-hits, no AP scaling in the live patch. The new `ap` field is
  for **AP-scaling** procs only.
- Don't bump `CoverageCountTests` floor past 47 until the next batch
  lands — same logic as s55. Future batches keep raising the floor.

**Activation:** Engine on :8893 already at 0.10.0 (this session
restarted it). No further action needed.

**Bridge state at session end:** RC main pid=9488 alive=true
reload_ok=true (no Legion main-RC restart this session; only the
RC-DaemonSlayer scheduled task was bounced). Engine on :8893 = 0.10.0
live. LCU phase=None (no game in progress). Working tree clean except
runtime `data/ratings/last_*.json` mutations.

**Operational backlog (carried + new):**
- All s54/s55 backlog items unchanged: gamepc_boot.ps1 `py → python.exe`
  patch; bridge auto-action lane false-positive on deploy prompts.
- **Magic pen layer** (carried from s55) — symmetric to armor pen
  pipeline. Add `magic_pen_pct` / `magic_pen_flat` fields to ItemEffect
  + `effective_target_mr()` mirror. Unlocks Void Staff (3135),
  Cryptbloom (3137), Sorcerer's Shoes (3020), Shadowflame's pen stat
  (4645). Schema bump = minor version. Same `EffectiveTargetArmorTests`
  pattern reused. **Top of next-session ranking — closest unlock to
  this batch's AP items.**
- **Riftmaker HP→AP cross-item derivation** (NEW) — would need a
  2nd-pass in `engine.build_champion` so `bonus_hp * 0.02` lands in
  `stats["ap"]`. Single-item effect but architecturally invasive.
  Defer until user feedback flags AP-bruiser build mis-rankings.

**Next-session candidates (ranked):**
1. **Phase 4 batch 4: magic pen layer** (carried from s55 — moved up
   from #3 to #1 because it directly extends this session's AP work
   and unlocks 4 well-known AP items). Schema bump (0.10.0 → 0.11.0).
   ~2-4 hour scope; mirrors `effective_target_armor` exactly.
2. **First draft visual verify of P8-5.5** (carried from s54+s55).
   Still blocked on operator entering a draft queue (400/420/430/440).
3. **gamepc_boot.ps1 `py → python.exe` patch** (carried). 1-line
   matching `project_rc_patchrefresh_fixed.md`.
4. **P8-7 E2E push-to-League integration test** (carried from s53).
   Needs actual draft queue.
5. **Activate arena augment v2 in production** (carried from s50).
   Needs arena game.
6. **Riftmaker HP→AP cross-derivation** (NEW; defer per above).

---

## s57 hand-off — 2026-05-04 (Phase 4 batch 4: magic pen layer + 4 AP items)

Single-arc continuation of s56. Picked the s56 backlog candidate #1
(magic pen layer) — closest unlock to s56's AP-aware CallContext, and
the symmetric pipeline mirror to the existing armor pen work. LCU
still idle (operator post-game), so engine restart window stayed open.

**Shipped (commit `d4a9fdc`, pushed `7b00f9f..d4a9fdc main -> main`):**

- `agents/daemon_slayer/effects.py`:
  - `ItemEffect` gains `magic_pen_pct: float = 0.0` and
    `magic_pen_flat: float = 0.0` fields (defaults preserve every
    existing entry's behavior).
  - New `effective_target_mr(target_mr, effects)` function — exact
    mirror of `effective_target_armor` minus the reduction layer (no
    magic-side Black Cleaver in current patch). % pen lands first,
    then flat pen, then floor at zero. Negative-MR passthrough kept
    for armor-curve test-harness symmetry.
  - 4 new entries:
    - `3135` Void Staff — `magic_pen_pct=0.40`
    - `3137` Cryptbloom — `magic_pen_pct=0.30` (Life from Death heal
      on takedown noted as not-modeled)
    - `3020` Sorcerer's Shoes — `magic_pen_flat=12.0`
    - `4645` Shadowflame — `magic_pen_flat=15.0` (PROMOTED out of
      batch-3 defensive_only; Cinderbloom magic-crit on <40% HP
      still not modeled, but the pen stat IS now)

- `agents/daemon_slayer/dps.py`:
  - Imports `effective_target_mr`.
  - Computes `target_mr_eff` once per `compute_dps` call alongside
    the existing `target_armor_eff`.
  - Plumbs `target_mr_eff` into `CallContext.target_mr` AND into the
    per-phase weighted-DPS math (`_phase_weighted_dps` already takes
    `target_mr` as `target_mr_for_magical`; just changed what we pass).
  - New note line: `effective target MR X → Y after magic pen` —
    surfaces only when MR was actually reduced.

- `agents/daemon_slayer/__init__.py`: docstring narrative refreshed
  (magic pen layer call-out + 27 defensive_only count, down 1 because
  Shadowflame promoted); `ENGINE_VERSION 0.10.0 → 0.11.0`. Schema-bump
  precedent matches s56 (CallContext.ap addition).

- `agents/daemon_slayer/tests/test_effects_expansion.py`:
  - **DefensiveOnlyBatch3Tests** EXPECTED shrunk 5 → 4 (Shadowflame
    out). Docstring updated to call out the schema-promotion path.
  - **EffectiveTargetMrTests** (9 tests) — passthrough + negative
    preserved + per-item % pen + per-item flat pen + composition
    (Void → Sorc) + zero-floor. Mirrors `EffectiveTargetArmorTests`
    structure exactly.
  - **MagicPenItemTests** (9 tests) — DPS impact via Lich Bane proc
    (Void), via Nashor's proc (Cryptbloom + Sorc + Shadowflame),
    Shadowflame-promoted-not-defensive-only sentinel, MR note surfaces
    when reduced + absent when not, armor pen stays independent of
    magic pen.
  - **CoverageCountTests** floor `>=47 → >=50`.

**Test state:** 267/267 daemon_slayer tests green (was 249 at end of
s56; +18 = 9 + 9 from the two new test classes). py_compile pre-commit
hook passed; same standard CRLF lint warnings, no new ones.

**Live engine verify (post-restart `schtasks /End` + `schtasks /Run`):**
```
GET  /health                                                       → 0.11.0 ok
POST /dps {champion:Aatrox, items:[3100],         target_mr:100}   →  69.15
POST /dps {champion:Aatrox, items:[3100, 3135],   target_mr:100}   →  84.57
```
Notes on the second response include both
`effective target MR 100.0 → 60.0 after magic pen` and the Lich
Bane / Void Staff entries. End-to-end pipeline confirmed.

**Coverage delta:** ITEM_EFFECTS 47 → 50 entries. Three new items
(Void Staff, Cryptbloom, Sorcerer's Shoes) plus Shadowflame's
defensive_only → live promotion. The four are all common SR / Arena
AP staples — Void Staff in particular is the gold standard "second
or third item" pen pickup for any AP champ.

**Decisions worth pinning:**
- **No `mr_reduction_pct` field added.** Symmetry with the armor
  pipeline tempted me, but no live patch-16.9 item populates it
  (Malignance's MR reduction is ult-bound burn, not a passive item
  modifier). Premature abstraction; add when the first item demands
  it. Note in the function docstring + the `magic_pen_*` field comment
  documents the extension point.
- **Shadowflame's promotion path is the canonical example.** Items
  that ship as `defensive_only` because their *primary* effect isn't
  modeled can still get promoted to live entries when a *secondary*
  stat (here: 15 flat magic pen) becomes plumbable. The note string
  evolves from "magic crit on <40% HP (target HP not modeled)" to
  "15 flat magic pen + Cinderbloom magic crit <40% HP (target HP
  not modeled)" — the unmodeled piece is documented explicitly so
  future schema work knows what's still missing.
- **Negative-MR passthrough kept.** Tests of the armor curve itself
  pass negative resists; a pen item shouldn't flip "target shredded
  to -50 MR by external means" into something weaker. Same call as
  `effective_target_armor`, same justification.
- **`target_mr_eff` in CallContext (not raw `target_mr`).** Callable
  `bonus_damage` lambdas inspecting `c.target_mr` get the
  pen-adjusted value, matching what the proc actually deals against.
  No live callable does this yet, but symmetric with how
  `target_armor` is already pen-adjusted in the context.

**Things tomorrow-you should NOT redo:**
- Don't add Sorcerer's Shoes to a separate "boots" effect table —
  the engine treats boots like any other item (no boots-uniqueness
  inside the effects table; that's enforced separately by beam
  search). Single-item pen entry is sufficient.
- Don't try to model Shadowflame's Cinderbloom in this batch — it's
  target-HP gated (<40%) which is the same Phase 4+ hook that
  unblocks Eclipse, BotRK, The Collector, Hydras. When that lands,
  promote them all together.
- Don't bump `CoverageCountTests` floor past 50 until the next batch
  lands.
- Don't add Malignance (3118) magic pen entry — it has MR reduction
  via ult-bound Hatefog, which is conceptually different from passive
  pen and would need either a `mr_reduction_pct` field (not added
  this batch) or a per-ult conditional layer.

**Activation:** Engine on :8893 already at 0.11.0 (this session
restarted it). No further action needed.

**Bridge state at session end:** RC main pid=9488 alive=true
reload_ok=true (no Legion main-RC restart this session; only the
RC-DaemonSlayer scheduled task was bounced for the second time today).
Engine on :8893 = 0.11.0 live. LCU phase=None (no game in progress).
Working tree clean except runtime `data/ratings/last_*.json` mutations.

**Operational backlog (carried + new):**
- All s54/s55/s56 backlog items unchanged: gamepc_boot.ps1 `py →
  python.exe` patch; bridge auto-action lane false-positive on
  deploy prompts.
- **Target HP modeling** (NEW + already implicit in s55/s56) — the
  single biggest unlock left. A `target_max_hp` and / or
  `target_current_hp_pct` field on `CallContext` would unblock
  Eclipse (3092), BotRK (3153), The Collector (6676), Ravenous /
  Titanic Hydra (3074 / 3748), Heartsteel (3084), Shadowflame
  Cinderbloom (4645), Deathfire Grasp (3128). 7+ items in one schema
  bump. Needs scenario data — does lolmath emit "target HP" in
  scenarios, or does the engine make an assumption (e.g.
  "1800 HP @ lvl 11")? Research before coding.
- **MR reduction layer** (NEW) — `mr_reduction_pct` field if
  Malignance gets reworked into a passive layer, or if a future
  item ships with a Black-Cleaver-style MR shred. Currently empty
  pipeline.
- **Riftmaker HP→AP cross-derivation** (carried from s56).

**Next-session candidates (ranked):**
1. **Phase 4 batch 5: target HP modeling** (NEW). Schema bump
   (0.11.0 → 0.12.0). Highest unlock yield of any single batch
   left. Research scope on lolmath scenarios first.
2. **First draft visual verify of P8-5.5** (carried). Still blocked
   on operator draft queue.
3. **gamepc_boot.ps1 patch** (carried). 1-liner.
4. **P8-7 E2E push-to-League integration test** (carried).
5. **Activate arena augment v2 in production** (carried).
6. **Riftmaker HP→AP cross-derivation** (carried).

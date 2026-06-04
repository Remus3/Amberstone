# LCU Phase-Change Capture Watcher - Architecture Proposal

**SHIPPED 2026-05-27 (item 207).** Implementation files:
- `tools/gamepc_phase_watcher.py` (classifier + Debouncer + capture orchestrator + WAMP loop)
- `tools/gamepc_phase_watcher_install.ps1` (Game-PC scheduled task installer)
- `tests/test_gamepc_phase_watcher.py` (64 stub-driven tests + drift guards)
- `tests/test_vision_frame_event_meta.py` (3 tests covering /upload-frame event_meta extension)
- `vision_server/_frame.py` (extended to accept optional `event_meta` field; backward-compatible)
- `data/event_captures/` (sidecar destination; distinct from `data/coaching_data/`)

**Operator scope-fork answers locked at ship time:**
- Q1 capture target: BOTH monitors per event (game 1920x1080 + dashboard 1920x1280; classified by resolution per [[reference_gamepc_monitor_index_volatility]])
- Q2 debounce: per (topic, sub_phase, queue_id) per gameflow cycle; `Debouncer.reset_cycle()` called on EndOfGame transition
- Q3 frame format: JPEG q75 (inherits gamepc_screen_agent.py contract)
- Q4 Cherry urgency: standard debounce (operator can flip `CHERRY_NO_DEBOUNCE = True` later)
- Q5 bridge envelope: YES emit `kind=ui_capture` envelope (`source=gamepc`, `target=legion`)

**Live deployment OWED:** Game-PC operator runs `tools/gamepc_phase_watcher_install.ps1` once. Prereqs: `py -m pip install bettercam websocket-client` on Game-PC. First live cycle should land event-tagged frames in vision server `/latest-frame?source=game-pc-event-game` (or `-dashboard`) and JSON sidecars under `data/event_captures/`.

The original architecture proposal follows below for design-record purposes.

---

Scoping doc only. Implementation deferred to a separate scoped session. Operator green-light + answers to open questions required before code lands.

## Goal

Replace the current polling-then-manual-capture pattern with an event-driven watcher that fires `mcp__gamepc__capture_monitor` (or local equivalent) at the exact moment a champ-select / augment / post-game UI is on screen. Eliminate the "missed the timing window" friction recorded in items 165 / 184 / 187 (Cherry augment scaffold) and the recurring carry "live UI capture OWED at next operator-driven match-list-populated session".

## Current behavior

- `tools/gamepc_lcu_agent.py` polls `/lol-gameflow/v1/gameflow-phase` and `/lol-champ-select/v1/session` at `AUTO_INTERVAL = 0.5s` cadence.
- Captures happen out-of-band: either an operator-typed `mcp__gamepc__capture_monitor` call OR a Legion-side script triggered after a phase change is observed downstream in `/api/state`.
- Round-trip from "phase change occurs on Game-PC" to "capture command lands on Game-PC" goes Game-PC LCU -> :8889 vision relay POST -> Legion `:8888` state -> operator notices -> capture command -> Game-PC. Sub-second phases (augment picker open / champ-select B card transition / post-game splash) routinely close before the round-trip completes.
- ITEMS 165 + 184 + 187 carries: pages #11/12/13 Active Match + Cherry augment endpoint discovery OWED at next live window precisely because the polling timing keeps missing.

## Proposed architecture

Local watcher on Game-PC that subscribes to LCU push events via WAMP WebSocket and fires capture immediately on relevant phase transitions. No Legion round-trip for the capture decision.

```
+------------------+         +-------------------+         +------------------+
| LCU (League)     | --WAMP->| gamepc_phase_     | --POST->| vision_server     |
| wss://riot:pwd@  |         | watcher.py        |         | (Legion :8889)    |
| 127.0.0.1:<port> |  push   | (NEW; Game-PC)    |  frame  |                  |
+------------------+         +-------------------+         +------------------+
                                      |
                                      | local capture
                                      v
                             +-------------------+
                             | DXGI screenshot   |
                             | (on-demand,       |
                             | NOT the continuous |
                             | screen agent)     |
                             +-------------------+
```

Why a NEW file (`tools/gamepc_phase_watcher.py`) instead of extending `tools/gamepc_lcu_agent.py`:
- Agent is non-frozen but high-touch (item 180 redeploy + Cherry scaffold + ARAM bench + spell chooser changes accumulated there). Separating WAMP subscription concerns lets the polling agent stay polling-shaped while the watcher owns event-driven shape.
- WAMP subscription needs `wss://` + lockfile-auth + WAMP-JSON v2 protocol + reconnect loop. New module, focused responsibility.
- Failure isolation: if WAMP subscription dies, the polling agent keeps the dashboard alive. If polling dies, WAMP keeps captures landing. Two independent processes, both Game-PC scheduled tasks.

## Event taxonomy

Subscribe to these LCU endpoints (`/lol-...` paths in WAMP topic form):

| Topic | Trigger | Capture intent |
|---|---|---|
| `/lol-gameflow/v1/gameflow-phase` | transition to `ChampSelect` | capture #8 SR / #9 ARAM / #10 Arena champ-select baseline |
| `/lol-champ-select/v1/session` | `timer.phase` transitions PLANNING -> BAN_PICK -> FINALIZATION | per-phase B card transitions (item 184 carry) |
| `/lol-cherry-game-intra-event/v1/augments` | non-empty `available[]` first observed | Cherry augment picker (item 187 Slice C carry) |
| `/lol-cherry-game-intra-event/v1/augment-select` | response on PATCH | confirm Cherry selection landed |
| `/lol-gameflow/v1/gameflow-phase` | transition to `InProgress` | capture #11/12/13 Active Match baseline (item 184 carry) |
| `/lol-gameflow/v1/gameflow-phase` | transition to `WaitingForStats` | capture #14/15/16 PGR baseline (item 182/183 carry) |
| `/lol-lobby/v2/lobby` | first non-null lobby + per-queue-id transitions | capture #7 Pre-Game Lobby per queue (closes item 180 Arena 1750 + Practice Tool 3140 visual coverage) |

Capture debounce: 1 capture per (topic, sub_phase, queue_id) tuple per gameflow cycle. Re-fire only on the next cycle (post-game -> EndOfGame -> back to Lobby).

## Data flow per capture event

1. WAMP push arrives on watcher.
2. Watcher classifies into `(topic, sub_phase, queue_id)` tuple.
3. Debounce gate: skip if already fired this cycle.
4. Local screenshot via DXGI (single-frame, not the continuous screen agent).
5. POST to `:8889/upload-frame` with extra meta: `{"event": "<topic>", "sub_phase": "<phase>", "queue_id": <int>, "captured_at": "<iso>"}`.
6. Legion dashboard tags the frame as event-driven; UI audit ritual subagent can subscribe to event-tagged frames specifically.
7. Optional: write a paired JSON sidecar at `data/event_captures/<topic>_<sub_phase>_<queue_id>_<iso>.json` with the LCU session payload at capture time (separate from the frame's PNG).

## Files (when implementation lands)

```
tools/gamepc_phase_watcher.py            NEW (~400 LOC; WAMP client + classifier + capture trigger)
tools/gamepc_phase_watcher_install.ps1   NEW (~30 LOC; registers Game-PC scheduled task)
tests/test_gamepc_phase_watcher.py       NEW (TDD-first per CLAUDE.md; fixture WAMP payloads)
docs/_archive/LCU_PHASE_CAPTURE_WATCHER_PLAN.md  this doc, archived post-ship
vision_server/_http.py                   EXTEND /upload-frame to accept event-meta JSON sidecar
data/event_captures/                     NEW directory for paired PNG + JSON sidecars
```

`tools/gamepc_lcu_agent.py`: UNTOUCHED. Polling stays as-is. Watcher is additive.

`vision_server` (Legion): minor extension only. The `/upload-frame` route already accepts a frame POST; add optional `event_meta` form field. Backward-compatible (existing polling-agent uploads work unchanged).

## LCU WAMP authentication

Per public LCU surface: connect to `wss://riot:<password>@127.0.0.1:<port>/` where password + port live in `LeagueClient/lockfile`. WSS cert is self-signed by Riot - same `verify=False` posture the polling agent already uses for HTTPS. Subscription frame is WAMP-JSON v2: `[5, "OnJsonApiEvent_<URI>"]` where the URI uses `_` instead of `/` (e.g. `lol-gameflow_v1_gameflow-phase`).

## Test strategy (TDD-first per CLAUDE.md)

1. Recorded WAMP payload fixtures captured from a live champ-select / Arena / SR cycle.
2. `tests/test_gamepc_phase_watcher.py` unit-tests the classifier with no live LCU (replay fixtures into a fake socket).
3. Drift guard: any new gameflow phase string surfaced by the fixture must be explicitly classified or the test fails (catches "RiotBlitz" / "Cherry-prefix" / future event-mode strings).
4. Live smoke: 1 manual cycle through Practice Tool 3140 -> capture sidecar + PNG appears in `data/event_captures/`.
5. Operator runs `RC_LIVE_WAMP=1 py -m pytest tests/test_gamepc_phase_watcher.py::LiveSmokeTests` once with League running to verify subscription handshake end-to-end.

## Failure modes + recovery

| Failure | Recovery |
|---|---|
| LCU restart (lockfile rotated) | watcher re-reads lockfile + reconnects with exponential backoff capped at 30s |
| Game-PC reboot | scheduled task with at-logon trigger restarts watcher |
| WSS handshake reject (League not launched) | watcher idles + retries every 10s; no error spam in logs |
| DXGI capture exception | log + skip the single capture; don't tear down subscription |
| `:8889/upload-frame` POST fails | retry-with-backoff 3x, drop after; do NOT block on next event |

## Out-of-scope

- Continuous screen-agent replacement (the existing 2s polling-frame upload stays; this watcher is event-augment, not replacement).
- Capture compression / pixel-pipeline changes.
- Adding a Legion-side dispatcher (operator-triggered captures keep working via the manual `mcp__gamepc__capture_monitor` path).
- TFT-specific phase wiring (event taxonomy above is SR / ARAM / Arena only; TFT augment timing can be a sibling watcher later).
- Replay phase captures (handled by `rewind_history.db` writer post-game already).

## Don't-redo (lock these for implementation)

- The watcher runs on Game-PC, not Legion. Capture decisions live where the capture surface lives.
- WAMP topics are subscribed using the `OnJsonApiEvent_<uri>` form, not the legacy `/messaging` HTTP poll.
- DXGI on-demand single-frame capture only. Do NOT reintroduce the continuous screen-agent loop in this watcher; it creates + releases per event.
- Sidecar JSON path is `data/event_captures/<topic>_<sub_phase>_<queue_id>_<iso>.json` - distinct from `data/coaching_data/` so it does NOT leak into coach-prompt context.
- New file `tools/gamepc_phase_watcher.py`; do NOT fold into `gamepc_lcu_agent.py`.

## Open questions for the implementation session

1. **Capture target naming:** does the operator want `monitor 1` (dashboard) or `monitor 0` (game) captured per event? Per [[reference_gamepc_monitor_index_volatility]] the index swaps across reboots; the watcher must select by RESOLUTION (1080 = game, 1280 = dashboard) not index. For champ-select / augment picker / lobby, the GAME monitor is the right target. Confirm.
2. **Debounce window:** 1 capture per (topic, sub_phase, queue_id) tuple per gameflow cycle - or also time-bound (no second capture within N seconds even across topics)?
3. **Frame format:** PNG (lossless, ~2-4 MB / 1080p frame) or JPEG q85 (~200-400 KB)? Dashboard frame upload from `gamepc_screen_agent.py` is JPEG q75 - inherit?
4. **Cherry augment urgency:** item 187 Slice C scaffold needs a live-Arena augment-pick capture to verify the 4-endpoint priority chain. Should the watcher's FIRST live deployment be operator-driven during a real Arena queue (no debounce, capture every augment available[] transition)?
5. **Bridge note on event-driven capture:** should the watcher also emit a kind=ui_capture envelope onto the Legion bridge so the UI-audit-ritual subagent on Legion auto-spawns when an event-tagged frame lands?

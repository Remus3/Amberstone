# Electron Shell + In-Game Overlay - Architecture

Status: PLAN (no code yet). Authored 2026-05-28. Owner decision doc for moving
RC from "Chrome on a second display" to a stabilized, single-screen, in-client +
in-game product while development continues.

This is topology-agnostic by design (see Principle 1). It does not depend on,
and does not block, the Legion 1-PC consolidation (s169 option B).

-------------------------------------------------------------------------------

## 1. Goal

Remove the hard requirement for a second physical display. Deliver RC content on
the same screen the operator plays on, in three render surfaces:

| # | Surface | When | Technique | Difficulty |
|---|---------|------|-----------|------------|
| A | Companion / pop-out window | Client open, out of match, or League not running | Electron BrowserWindow, frameless, resizable, dockable beside client | Easy |
| B | In-game overlay | During a live match | Transparent always-on-top Electron window over the Borderless game, hotkey toggle, click-through <-> interactive | Medium-hard |
| C | In-client injected panels | Lobby / champ-select / post-game inside the client UI | Pengu Loader plugin into the client CEF browser | Medium (3rd-party dependency) |

Operator pain points this solves:
- Not noticing content changes while in a match (B).
- Interactive accessibility for on-the-fly DS weight tweaks, spell-usage
  notify, item-build reorder, fast A+B coach (B, interactive mode).
- A dockable companion for the client/idle states without a 2nd monitor (A).
- The Zed/Mayhem-style native in-client panels (C).

-------------------------------------------------------------------------------

## 2. Principle 1 - origin is config, not code (settles the consolidation fork)

The frontend is already origin-agnostic:
- Every API call is relative: `fetch("/api/...")` (`web/js/main.js` throughout).
- WebSocket derives host from the page: `location.hostname` (`web/js/ws_client.js:4`).
- Only DDragon image URLs are absolute, and those are the public CDN (correct).

Therefore the backend origin is a single value the Electron shell decides at
load time:

```
RC_ORIGIN = https://legion-rc:8888      # thin-client over tailnet (now)
RC_ORIGIN = https://127.0.0.1:8888      # after 1-PC consolidation (later)
```

Consequence: build the overlay now against Legion. When/if the consolidation
happens, flip `RC_ORIGIN` to localhost. No Electron rework, no JS change. The
two efforts are fully decoupled. Store `RC_ORIGIN` in the Electron app's config
(`%APPDATA%/RiotCommander/config.json`) with a Settings field to change it.

Cert: dashboard is mkcert self-signed HTTPS. Electron loads it with a scoped
`certificate-error` handler that trusts only `RC_ORIGIN`'s host (not a blanket
`ignore-certificate-errors`).

-------------------------------------------------------------------------------

## 3. Component map

```
Legion
  Electron shell (rc-shell)            <- NEW, this project
    +-- main process
    |     - window manager (companion / overlay)
    |     - global hotkey registration
    |     - polls RC_ORIGIN /api/state for mode_key + lcu phase
    |     - drives the window state machine (sec 5)
    +-- companion window  (Surface A)  loads RC_ORIGIN/            (full dashboard)
    +-- overlay window    (Surface B)  loads RC_ORIGIN/?overlay=1  (compact panels)

  League client (Riot CEF)
    +-- Pengu plugin (Surface C)       fetches RC_ORIGIN/api/... , renders panel

  RC backend  (Legion now / localhost later)  -- UNCHANGED
    :8888 dashboard/api   :8889 vision   :8893 daemon slayer   ws /push
```

Nothing in the Python backend changes for A or B. C needs only CORS allowance on
the API for the client's origin (one header, see sec 6).

-------------------------------------------------------------------------------

## 4. Surface details

### 4A. Companion / pop-out window (easy, ship first)
- `BrowserWindow`: `frame:false`, resizable, `alwaysOnTop:false` (or pin toggle),
  remembers position/size in config.
- Loads `RC_ORIGIN/` - the existing full dashboard, unchanged.
- Window-size presets (mirror the Mayhem pic): Compact / Standard / Large / Custom.
- "Dock beside client" = position the window adjacent to the client window rect
  (read client bounds from LCU `/riotclient` or via win32 window enumeration).
- Replaces the Chrome tab. This alone removes the 2nd-display need for all
  out-of-match use and is a 1-2 day spike.

### 4B. In-game overlay (the core ask)
- `BrowserWindow`: `transparent:true`, `frame:false`, `alwaysOnTop:true`
  (`"screen-saver"` level), `skipTaskbar:true`, `focusable` toggled with mode,
  full-screen-bounds over the primary monitor (the game monitor; pick by
  resolution per `reference_gamepc_monitor_index_volatility`, not index).
- Loads `RC_ORIGIN/?overlay=1` - a compact panel subset, not the 1920 grid
  (the viewport is hardcoded `width=1920` in `web/index.html:5`; the overlay
  needs its own layout - see sec 7).
- Two interaction states:
  - PASSIVE: `setIgnoreMouseEvents(true, {forward:true})` - clicks pass through
    to the game; panels are read-only HUD. Default.
  - ACTIVE: `setIgnoreMouseEvents(false)` - panels accept clicks for DS weight
    tweaks / A+B coach / build reorder. Toggled by hotkey.
- REQUIRES League in Borderless. Exclusive Fullscreen hides any overlay and
  risks the lockup (`feedback_gamepc_league_fullscreen_lockup`). Borderless is
  already the operator's locked setting.
- Change-notification: when a panel's content changes mid-match (DS rebuild,
  new spike, A+B prompt), pulse the overlay (flash/sound/edge glow) so the
  operator notices without staring - this is the "didn't notice mid-game" fix.

### 4C. In-client injected panels (Pengu, lower priority)
- Pengu Loader plugin (JS) injected into the client's CEF browser. Renders a
  panel/tab inside lobby / champ-select / profile (the Zed AGGREGATOR D + Mayhem
  "UI INJECTIONS" style).
- Fetches `RC_ORIGIN/api/...` and renders with the same tokens.css design system.
- Cannot draw over the live D3D game (that is Surface B's job) - Pengu only
  reaches the client CEF.
- Dependency: operator installs Pengu Loader on Legion. Plugin ships in-repo
  under `pengu/`. Prior research: `project_lcu_pengu_pregame_postgame`.
- Defer until A + B are stable; it is the most fragile (breaks on client patches).

-------------------------------------------------------------------------------

## 5. Window state machine (Electron main process)

Poll `RC_ORIGIN/api/state` (already exists; the game-monitor skill uses it) and
react to `mode_key` + LCU phase:

```
phase/mode_key                       companion        overlay
----------------------------------   --------------   --------------------
League not running                   show (if open)   hidden
client idle / lobby                  show             hidden
champ-select                         show             hidden (or C panel)
in match (mode_key in {sr,arena,     auto-hide        SHOW (passive)
  aram,tft,brawl} + liveclient)
post-game                            show             fade out
```

Hotkeys override auto-behavior:
- `Alt+Shift+O` - toggle overlay show/hide
- `Alt+Shift+A` / `Ctrl+Shift+A` - toggle overlay PASSIVE <-> ACTIVE
- `Alt+Shift+C` (out-of-game) / `Ctrl+Shift+B` (in-game) - cycle overlay panel
  set (coach / build / threat)
- In-game vs out-of-game: the `Alt+Shift+*` binds use Electron `globalShortcut`,
  which does NOT deliver while League holds foreground focus. The `Ctrl+Shift+*`
  binds are owned by the Win32 `tools/hotkey_listener.py` (RegisterHotKey), which
  DOES deliver in-game; it stamps a signal file under `ops/runtime/` that the
  rc-shell main process polls (`startActiveToggleWatch` / `startPanelCycleWatch`).
  Use `Ctrl+Shift+B` in-game to reach the build panel (B not C: Ctrl+Shift+C is
  commonly bound by other apps - Discord / Overlay Platform M / DevTools). (Alt binds
  rebindable in companion Settings.)

The auto-hide of the companion when a match starts keeps everything to one
screen: companion for idle, overlay for the match.

-------------------------------------------------------------------------------

## 6. Backend touch points (minimal)

- A + B: zero backend changes. Electron loads the served dashboard as-is.
- B overlay route: add `?overlay=1` handling in `web/js/main.js` boot to select
  a compact layout + panel subset (frontend-only; no Python).
- C only: API responses need `Access-Control-Allow-Origin` for the client's CEF
  origin (`https://...riotgames` scheme). One header in `dashboard/_handler.py`,
  gated to the client origin. Not needed for A/B (same-origin load).
- Optional: a tiny `/api/shell/ping` for the Electron main process to confirm
  backend reachability and show a "backend offline" state in the shell.

-------------------------------------------------------------------------------

## 7. Overlay frontend layout (the 1920 problem)

The dashboard viewport is fixed `width=1920` and authored for a full 1920x1080
panel grid. An overlay is a strip/corner, not a full screen. Do NOT scale the
whole grid down. Instead:

- `?overlay=1` sets `body[data-shell="overlay"]`.
- A new `web/css/overlay.css` defines a compact, single-column or corner-dock
  layout that reuses the existing panel components (right_now, coach_choices,
  build_order, cc_*_threat, map_state, archetype_nudge_chip) at overlay density.
- The panel JS is unchanged; only the container CSS + which panels mount differ.
- Reuses the v2.1 token scale already in `tokens.css`.
- This is its own UI-audit-ritual page per `feedback_phase3_fixture_ritual`.

-------------------------------------------------------------------------------

## 8. Stabilization (the "usable while still developing" half)

"Stable" = the daily-driver shell does not break when you push backend/frontend
changes. Achieved by:

1. Shell loads the LIVE dashboard (chosen this session). ADR-008 asset-hash
   auto-reload means UI edits appear in the shell with no shell rebuild. Dev
   loop is unchanged.
2. The shell itself versions and auto-updates on its own cadence
   (electron-updater + GitHub Releases), decoupled from RC backend versioning.
   You only rebuild the shell when the WINDOWING changes, which is rare.
3. Pin the dashboard contract the overlay depends on: `/api/state` shape +
   `mode_key` values + the overlay panel set. A smoke test asserts the overlay
   route renders against the mock fixtures (`web/data/ui_mock/*`).
4. Release channels: `stable` (operator daily) vs `dev` (you, while iterating).
   Companion Settings switches channel.
5. Crash isolation: overlay window crash must not take down the companion or the
   game. Separate renderer processes; main process restarts a dead overlay.

-------------------------------------------------------------------------------

## 9. Risk register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Overlay capture surface | LOW | Overlay is a DWM compositor window, NOT DXGI capture - so it does not add a frame-capture surface. Do NOT add frame capture to the shell. Keep League Borderless. Hide overlay on the WaitingForStats/resolution-swap edge. |
| Vanguard anti-cheat | MEDIUM | RC reads only Live Client :2999 + LCU lockfile (official), no game-memory reads, no input injection into the game. Same bar Overlay App E/aggregator A/Overlay App F clear with transparent overlays. State this explicitly; do not add memory reads. |
| Exclusive Fullscreen hides overlay | MEDIUM | Borderless is mandatory and already the locked setting. Shell detects fullscreen and shows a "switch to Borderless" hint. |
| Focus steal mid-fight | MEDIUM | Default PASSIVE click-through; ACTIVE only on explicit hotkey; auto-revert to PASSIVE after N seconds idle. |
| Overlay perf cost mid-game | LOW-MED | Compact panel subset, throttle polling to the existing cadence, GPU-light CSS (no heavy blur/animation in overlay.css). |
| Monitor index volatility | LOW | Pick the game monitor by resolution (1080), not index (`reference_gamepc_monitor_index_volatility`). |
| Backend unreachable (Legion off) | LOW now | Shell shows "backend offline"; resolved permanently by consolidation later. |

-------------------------------------------------------------------------------

## 10. Phased roadmap

Each phase is its own session(s). Acceptance = the listed proof.

- **Phase 0 - this doc.** DONE on merge.
- **Phase 1 - Companion shell (Surface A).** `rc-shell/` Electron project, single
  frameless window loading `RC_ORIGIN/`, config file, size presets, position
  memory, scoped cert trust. Proof: window docks beside client, full dashboard
  renders, survives a backend push without shell rebuild.
- **Phase 2 - Window state machine + hotkeys.** Main process polls `/api/state`,
  auto show/hide companion, register global hotkeys. Proof: companion auto-hides
  on match start, hotkeys fire.
- **Phase 3 - Overlay window (Surface B, passive).** Transparent always-on-top
  window, `?overlay=1` + `overlay.css` compact layout, click-through, monitor
  pick by resolution. Proof: HUD visible over a Borderless match, clicks pass to
  game, stable across a full game + game-end.
- **Phase 4 - Overlay interactivity (Surface B, active).** ACTIVE mode toggle,
  change-pulse notifications, wire DS weight tweak / A+B coach / build reorder
  controls. Proof: operator changes a DS weight from the overlay mid-match.
- **Phase 5 - Stabilization.** electron-updater + Releases, stable/dev channels,
  overlay-route smoke test, crash isolation. Proof: operator runs `stable`
  channel daily while you push to `dev`.
- **Phase 6 - In-client panels (Surface C, optional).** Pengu plugin under
  `pengu/`, CORS header, client-injected panel. Proof: panel renders inside
  champ-select.

-------------------------------------------------------------------------------

## 11. Open decisions (deferred, do not block Phases 1-5)

- 1-PC consolidation timing (s169 option B). Orthogonal per Principle 1. When
  done, flip `RC_ORIGIN` to localhost.
- Surface C inclusion at all (depends on tolerance for the Pengu dependency +
  client-patch fragility).
- Interactivity depth in Phase 4 (which controls are overlay-editable vs
  companion-only).
- Pulse/notify modality (visual edge-glow vs sound vs both).

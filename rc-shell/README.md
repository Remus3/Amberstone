# rc-shell - Riot Commander companion shell (Electron, Phase 1)

A thin Electron window that wraps the existing Riot Commander dashboard. This is
**Phase 1** of `docs/ELECTRON_OVERLAY.md`: a frameless, always-on-top
companion / pop-out window so the dashboard is visible during a game on a single
screen, without a second display or alt-tabbing a browser tab.

It is a **thin client**: it owns a window, not the app. Every panel, fetch, and
WebSocket already works in a browser; the shell just points a `BrowserWindow` at
the dashboard origin and remembers where you put it.

## What it does

- One frameless, always-on-top window loading `RC_ORIGIN`.
- Remembers window position + size + preset across launches (clamped on-screen).
- Trusts ONLY the RC origin's self-signed (mkcert) certificate - scoped, never
  globally disabled.
- Small app menu (focused-window only): size presets + always-on-top toggle +
  reload. No global hotkeys (those are Phase 2).

## What it does NOT do (Vanguard-safe)

- No transparent in-game overlay, no click-through (Phase 3+).
- No global hotkeys (Phase 2+).
- No DXGI / frame capture, no game-memory reads, no input injection - ever.
- No Pengu / in-client panels (Phase 6).

It loads a URL. That is all - the same bar Overlay App E / aggregator A / Overlay App F clear.
`contextIsolation` is on, `nodeIntegration` is off, the preload is empty.

## Run

```
cd rc-shell
npm install     # pulls electron (devDependency)
npm start       # launches the companion window
```

> The visual launch is **operator-verified**. This build host may be headless
> and has restricted outbound network, so `npm install` (which downloads the
> Electron binary) may not run here. The headless-verifiable parts are
> `node --check` on every source file and the pure-logic unit tests
> (`npm test`), which run with NO Electron installed.

```
npm test        # node --test test/  (pure logic, no electron needed)
```

## RC_ORIGIN (config, not code)

The window loads `RC_ORIGIN`. This single value is the only thing that changes
between the 2-PC and 1-PC topologies - no JS, no panel, no Electron code change.

```
RC_ORIGIN=https://legion-rc:8888   # default (2-PC topology, today)
RC_ORIGIN=https://127.0.0.1:8888   # after 1-PC consolidation (ADR-011)
```

Override it for a single launch:

```
# Windows PowerShell
$env:RC_ORIGIN = "https://127.0.0.1:8888"; npm start

# bash
RC_ORIGIN=https://127.0.0.1:8888 npm start
```

Precedence: `env RC_ORIGIN` > saved state > default.

## Size presets

| Preset   | Size       | Use                 |
|----------|------------|---------------------|
| compact  | 380 x 720  | narrow side-dock    |
| standard | 520 x 900  | default             |
| tall     | 640 x 1040 | full panel set      |

Switch from the **Shell** app menu (Ctrl+1 / Ctrl+2 / Ctrl+3 while focused).

## Layout

```
rc-shell/
  package.json        electron devDependency + start/test scripts
  src/
    main.js           Electron main process (window lifecycle, cert, presets)
    config.js         PURE config core (no electron) - defaults/presets/resolve/clamp
    store.js          PURE persistence (no electron) - atomic JSON read/write
    preload.js        context-isolated preload (empty for Phase 1)
  test/
    config.test.js    node:test - resolveConfig precedence, clamp, presets
    store.test.js     node:test - round-trip, missing/corrupt file tolerance
  README.md
  .gitignore
```

`config.js` and `store.js` carry no Electron import on purpose - they are the
testable core. `main.js` wires them to the Electron runtime.

## Window state file

Persisted to `<userData>/rc-shell-state.json` (per-OS-user app data). Delete it
to reset window position/size. A missing or corrupt file is tolerated (the shell
falls back to defaults, never crashes).

## Overlay (Phase 2/3)

The shell surface-switches between the companion window (out of a game) and a
transparent always-on-top in-game overlay, driven by the dashboard `mode_key`
polled from `RC_ORIGIN/api/state`:

- `src/overlay_state.js` - the PURE (node:testable) state machine: `mode_key` ->
  companion / overlay, plus the hidden override, the overlay-route URL, and the
  show/hide actions. No Electron import.
- `main.js` creates the overlay `BrowserWindow` (transparent, frameless,
  always-on-top, click-through by default), registers global hotkeys
  (`Alt+Shift+O` show/hide, `Alt+Shift+A` toggle click-through), and runs the
  poll loop. Hotkeys use RegisterHotKey under the hood (anti-cheat-safe).

Vanguard-safe: the overlay is a DWM compositor window only - NO DXGI / frame
capture, NO game-memory reads, NO input injection. The game must run Borderless
(an exclusive-fullscreen game hides any compositor overlay).

The overlay's compact layout (the `?overlay=1` route) + interactive controls
(Phase 4) + electron-updater (Phase 5) + optional Pengu panels (Phase 6) are
still pending - see `docs/ELECTRON_OVERLAY.md`. Visual launch (`npm start`) is
operator-gated.

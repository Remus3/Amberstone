# rc-shell - Amberstone companion shell (Electron, Phase 1)

A thin Electron window that wraps the existing Amberstone dashboard. This is
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
`contextIsolation` is on, `nodeIntegration` is off, `sandbox` is on. The
preload (`src/preload.js`) exposes only a small allow-listed `rcShell` bridge
(overlay settings, widget layout, window controls), and since PKG-6 every one
of its channels answers only the shell's own windows on the RC origin.

## Run

```
cd rc-shell
npm ci          # the tracked package-lock.json pins electron + electron-builder
npm start       # launches the companion window (no service host - see below)
```

## Launcher (PKG-6)

The shell is also the app's LAUNCHER (`docs/PACKAGING_PLAN.md` sections 3 and
4). Decisions live in `src/launcher.js` (pure, node:testable); `main.js`
applies them.

- **Start**: at launch the shell spawns ONE windowless child, the service host
  `ops/launcher/service_host.py`, as
  `<python> -I <root>/ops/launcher/service_host.py --root <root> --profile <p>
  --parent-pid <shell pid>`. The host owns every RC service inside one Windows
  job object (supervisor + dashboard :8888, vision :8889, DS :8860, LCU agent,
  Live Client relay, hotkey listener). If a healthy RC already serves :8888
  (the pre-cutover scheduled tasks), the host attaches and starts nothing.
- **Starting view**: a small framed local window (`src/starting.html`, no
  bridge, strict CSP) shows the service states from
  `ops/runtime/launcher_status.json` until `GET <origin>/api/health` answers;
  then the normal companion / overlay surfaces take over. Closing it quits.
- **Quit**: the shell writes `stop` to the host's stdin and waits up to 25 s;
  a host that has not exited is ended, and its job object takes every service
  with it. Nothing outlives the app.
- **Never at boot**: no Run key, Startup-folder shortcut, scheduled task or
  Electron login-item setting - a test pins it. Services start when the APP
  starts.
- **Which launches start the host**: a packaged build always (opt-out
  `--no-host` or `RC_SHELL_NO_HOST=1`). A checkout launch (`npm start`,
  `launch_overlay.bat`) only when a profile is named: `--profile dev` (or
  `RC_LAUNCHER_PROFILE=dev`). Before the section-5 cutover the RC-* scheduled
  tasks own the agents on Legion, so a plain checkout launch stays a thin
  client exactly as before.
- **Backend root**: `--rc-root <dir>` > `RC_ROOT` > the packaged
  `resources/backend` > this checkout (`src/rc_root.js`). The hotkey signal
  files (Ctrl+Shift+A / B / O) are read under `<root>/ops/runtime`.
- **Interpreter**: `RC_PYTHON` (absolute) > `<root>/python-embed/python.exe` >
  (checkout launch only) `%LOCALAPPDATA%\Programs\Python\Python314\python.exe`.
- **TLS**: an https origin is trusted only when it presents the install's own
  leaf, `<root>/ops/tls/rc.pem` (SHA-256 pin, re-read on a miss so a renewed
  leaf needs no relaunch; expiry is not checked). With no pin file, normal
  certificate validation (including the OS store) applies - never a blanket
  accept. The packaged default is plain http on loopback.
- **Token**: once the host has provisioned `ops/runtime/dash_token.txt`, the
  shell adds `X-RC-Token` to its windows' requests for the RC origin only.
- **Shell updates**: a downloaded update installs on quit; the Shell menu's
  "Relaunch to update when idle" relaunches only when no game is live.

### Packaging

```
python tools/build_portable.py            # backend -> dist/portable_staging
                                          # (embedded runtime included)
cd rc-shell
npm run dist:dir                          # unpacked app in rc-shell/dist/win-unpacked
npm run dist                              # NSIS installer (operator-gated publish)
cd ..
python tools/package_portable.py
python tools/run_packaged_smoke.py --shell-dir rc-shell/dist/win-unpacked
```

`electron-builder.yml` copies `dist/portable_staging` to `resources/backend`
(real files beside `app.asar`). `productName` is `Amberstone Shell` in both
`package.json` and the builder config, so a checkout launch and a packaged
launch share one userData folder; the first launch after this change copies
the old `rc-shell` state file across once.

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
if the game host ever moves - no JS, no panel, no Electron code change.

```
RC_ORIGIN=https://127.0.0.1:8888   # default (Legion 1-PC, ADR-011)
RC_ORIGIN=https://rc-host:8888     # the machine's tailnet name (per-host config)
```

Override it for a single launch:

```
# Windows PowerShell
$env:RC_ORIGIN = "https://127.0.0.1:8888"; npm start

# bash
RC_ORIGIN=https://127.0.0.1:8888 npm start
```

Precedence: `env RC_ORIGIN` > the origin the service host reports it serves >
saved state > default. Every candidate is validated first (`src/config.js`
`validateOrigin`): http(s) on loopback, or https on a host named in the
per-host `ops/local_hosts.json`.

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
  package.json        electron devDependency + start/test/dist scripts
  electron-builder.yml  packaging (backend in resources/backend, icon, NSIS)
  assets/icon.ico     the app icon (original drawing, no third-party asset)
  src/
    main.js           Electron main process (windows, launcher wiring, cert, presets)
    launcher.js       PURE launcher decisions (host plan, token, sender, relaunch)
    rc_root.js        PURE backend-root resolution + signal / cert / config paths
    tls_pin.js        PURE leaf-certificate pin decision
    service_status.js PURE launcher_status.json parse + the shell's view
    config.js         PURE config core (no electron) - defaults/presets/resolve/clamp
    store.js          PURE persistence (no electron) - atomic JSON read/write
    preload.js        context-isolated preload (the allow-listed rcShell bridge)
    starting.html     the launcher's starting / error view (+ starting_page.js)
  test/               node:test suites, enumerated in package.json scripts.test
  README.md
  .gitignore
```

`config.js` and `store.js` carry no Electron import on purpose - they are the
testable core. `main.js` wires them to the Electron runtime.

## Window state file

Persisted to `<userData>/rc-shell-state.json` (per-OS-user app data;
`<userData>` = `%APPDATA%\Amberstone Shell` since PKG-6). Delete it
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
- `src/overlay_toggle.js` + `src/overlay_toggle.html` - the in-game overlay
  ON/OFF icon: a tiny movable `focusable:false` always-on-top window; a tap
  hides / shows the overlay content, the icon stays up. Position (per display)
  and the ON/OFF choice persist in the state file; `Ctrl+Shift+O` (via
  `tools/hotkey_listener.py`) is the in-game keyboard twin.

Vanguard-safe: the overlay is a DWM compositor window only - NO DXGI / frame
capture, NO game-memory reads, NO input injection. The game must run Borderless
(an exclusive-fullscreen game hides any compositor overlay).

The overlay's compact layout (the `?overlay=1` route) + interactive controls
(Phase 4) shipped in earlier slices; electron-updater channels (Phase 5) are
below. Optional Pengu panels (Phase 6) are still pending - see
`docs/ELECTRON_OVERLAY.md`. Visual launch (`npm start`) is operator-gated.

## Updates (Phase 5)

The shell versions and auto-updates on its own cadence (electron-updater +
GitHub Releases), decoupled from RC backend pushes - you only rebuild the
shell when the windowing changes.

Two release channels:

| Channel | Rides                        | Who                  |
|---------|------------------------------|----------------------|
| stable  | full GitHub Releases only    | operator daily       |
| dev     | prerelease + full Releases   | iterating developer  |

Channel precedence: `env RC_SHELL_CHANNEL` > saved state > `stable` (same
shape as `RC_ORIGIN`). Switch live from the **Shell** menu - the two
"Update channel" radio items persist the choice and re-check immediately;
"Check for updates now" forces a check on demand.

Update behavior is deliberately quiet: checks start ~15s after boot and then
every 4 hours; downloads are automatic; the install happens on natural app
quit (`autoInstallOnAppQuit`) - the shell NEVER restarts itself mid-session,
because the operator may be in a game. All update events log to the console
only (no dialogs, no focus steal).

Updates disable themselves gracefully (a console line, nothing else) when:

- the shell is not packaged (a `npm start` dev launch), or
- the `electron-updater` package is absent (bare checkout without
  `npm install`).

WIP / operator-gated: packaging (`npx electron-builder`, see
`electron-builder.yml`) and publishing GitHub Releases are operator actions -
no packaged shell Release exists yet. The repo is public, so update checks
read the Releases feed without a token; `GH_TOKEN` is needed only to publish.

## Crash isolation (Phase 5)

Each window runs its own renderer process, so a page crash is already
contained - the companion, the overlay, and the game never share fate. On top
of that, `src/crash_guard.js` (PURE, node:testable) decides what the main
process does when a renderer dies (`render-process-gone`):

- restartable reasons (`crashed`, `oom`, `abnormal-exit`, `launch-failed`,
  `integrity-failure`) reload ONLY the dead window;
- `killed` / `clean-exit` are deliberate terminations - never resurrected;
- a crash LOOP converges: more than 3 restartable crashes per window within
  60s flips to give-up (the window hides) instead of strobing a half-dead
  HUD over a live game. The budget is per-window and rolls off after 60s.
- an `unresponsive` renderer is logged, never killed (a load hitch recovers
  on its own).

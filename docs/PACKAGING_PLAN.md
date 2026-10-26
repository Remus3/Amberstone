# Packaging plan - the installable, live-updatable Amberstone app

Status: LIVING SPEC (ROADMAP row PKG). Phase 1 = Q/A + spec, written
2026-10-26 (session 141). Wave A (PKG-1, -2, -3, -4, -5, -8) landed the same
session (section 4 status); PKG-1b landed after it (4859c9405..1ca036c77);
PKG-6 and PKG-7 are open. Each later
wave updates this file in place.

Operator intent (2026-10-25, memory `project_packaged_app_requirements`),
all binding:

1. A packaged output another person can install and run with no Claude
   session wiring it up.
2. Live-updatable from local edits or GitHub with minimal or no restart.
3. NEVER starts at boot: no ONLOGON / boot task, Run key or Startup shortcut.
4. RC's local services start when the app launches: supervisor + app loop,
   dashboard :8888, vision :8889, DS :8860, the LCU agent, the Live Client
   relay and the hotkey listener.
5. No Overlay Platform M (ow-electron) dependency - operator ruling
   2026-10-25, "do what they are doing; not utilize their software as a
   dependency". `rc-shell/` is already stock Electron, so this holds today.
6. The launcher eventually replaces the RC-* ONLOGON tasks; that cutover is
   an OPERATOR step (section 5), never done by a lane.

Related: `docs/OVERLAY_COMPLIANCE_PLAN.md` (the Overlay Platform M
submission plan; its ow-electron verdict applies only if RM-189 is ever
pursued), `docs/ELECTRON_OVERLAY.md` (shell phases), ROADMAP RM-189 (public
distribution gates), `docs/adr/ADR-006-riot-api-key-policy.md`,
`docs/adr/ADR-008-unified-asset-hash.md`.

## 1. Q/A STATUS as of 2026-10-26

Scope read: `rc-shell/` (package.json, electron-builder.yml, src/, test/),
the frozen `ops/rc_supervisor.py` + `scripts/restart.bat` +
`core/hot_reload.py` restart path (read only), `docs/OPERATIONS.md`
scheduled tasks, the existing portable/installer tools, the dashboard bind
and TLS path, and the dependency payload.

Test run: rc-shell's own suite (`node --test` over the exact file list in
`rc-shell/package.json` `scripts.test`, Node v24, no npm install) passed in
full before and after this slice, plus the pytest guards
`tests/test_rc_shell_node_suite_rm342.py` and
`tests/test_rc_shell_test_script_covers_the_dir_rm212.py`. Counts are in the
commit message, not restated here (CLAUDE.md: doc counts go stale).

Already right (keep): every window runs `contextIsolation: true`,
`nodeIntegration: false`, `sandbox: true`; the toggle icon has its own
least-privilege preload, a sender check and a strict CSP
(`rc-shell/src/overlay_toggle.html:5`); overlay actions and toggle actions go
through allow-list validators; cert trust is scoped to the origin host, not
global; a single-instance lock exists (`rc-shell/src/main.js:1711`); updates
install on natural quit, never mid-game (`rc-shell/src/main.js:267`).

### 1a. MUST-FIX (blocks a working or safe packaged install)

- M1 FIXED (b9c0e0f63). `shell.openExternal` received ANY url from
  `window.open` / target=_blank on both bridge-carrying windows, so a page
  could launch any registered protocol handler (file:, ms-settings:,
  search-ms:, custom schemes). Now only http(s) passes:
  `rc-shell/src/nav_guard.js` + `openExternalSafe` at
  `rc-shell/src/main.js:477`. Test `rc-shell/test/nav_guard.test.js`.
- M2 FIXED (b9c0e0f63). No `will-navigate` guard on the companion or overlay
  window, so an in-window navigation to another origin kept the `rcShell`
  preload bridge (IPC to main) on a foreign page. `guardNavigation` at
  `rc-shell/src/main.js:494`, wired at `rc-shell/src/main.js:584` and
  `rc-shell/src/main.js:705`: same-origin stays, cross-origin http(s) opens
  in the default browser, anything else is dropped.
- M3 HELPERS LANDED (PKG-3 61c3ceed3), WIRING OPEN (PKG-6). The three Win32
  hotkey signal files are still resolved as `__dirname/../../ops/runtime/*`
  (`rc-shell/src/main.js:1557`, `rc-shell/src/main.js:1588`,
  `rc-shell/src/main.js:1619`); in a packaged build `__dirname` is inside
  `resources/app.asar/src`, so Ctrl+Shift+A / B / O silently stop working
  in-game. `rc-shell/src/rc_root.js` `resolveRcRoot` (argv, env, bundled
  root; packaged with no root = null) + `signalPaths` replace them.
- M4 Fresh-machine origin mismatch. The shell defaults to
  `https://127.0.0.1:8888` (`rc-shell/src/config.js:25`) but the dashboard
  serves plain HTTP when `ops/tls/rc.pem` + `rc-key.pem` are absent
  (`dashboard/server.py:585`, `dashboard/server.py:593`). Producing the pair
  needs mkcert plus `tools/regen_rc_cert.ps1`, so a fresh install shows a
  blank shell and the poll never surfaces the overlay. Fix in section 3.6;
  PKG-3 `resolveConfig` already takes the host-served origin (PKG-6 wires it).
- M5 FIXED (PKG-5 f3690023f, d2fb1c125). The dashboard binds `::`
  (`dashboard/server.py:42`) and the `RC_DASH_TOKEN` gate is inert (set
  nowhere, `dashboard/_handler.py:699`). With no token, a control POST now
  passes only for a loopback, same-machine or tailnet peer or an
  `RC_DASH_CONTROL_NETS` range, else 403 (`dashboard/server.py:128`);
  `RC_DASH_BIND` picks the bind (packaged 127.0.0.1). Three endpoints joined
  the control set (`dashboard/_handler.py:136`: auto-accept,
  vision-reference, coach-choice) and vision-reference ingest is confined
  to `data/vision_calib_reference`. The per-install token stays 3.6 (V3).
- M6 FIXED (PKG-4 c066cb0ca, dea18d069). The old hand list omitted
  `web_dashboard.py`, `app/`, `dashboard/`, `web/`, `agents/`.
  `tools/build_portable.py` now ships the git index minus reasoned
  exclusions, requires every backend process's import closure, refuses LFS
  pointers, a dirty source and unlisted boot signatures, ships every
  tracked `.gitignore` (the updater reads the install's own) and builds
  `python-embed/` from the pinned zip + hashed lock. Artifacts:
  `Amberstone-*`.
- M7 FIXED (PKG-8 79fec0b5f, d9c5f2a47). `rc-shell/package-lock.json` is
  tracked (`!rc-shell/package-lock.json` at `.gitignore:282`, over the
  repo-wide ignore at `.gitignore:277`), copied byte-level from the main
  checkout; `tests/test_third_party_notices_pkg.py` fails when it drifts
  from `rc-shell/package.json`. Build with `npm ci`.
- M8 PARTIAL: the PKG-2 updater landed; the shell calls it in PKG-6.
  `rc-shell/electron-builder.yml:30` packages only `src/**/*` +
  package.json and electron-updater updates only that shell, so the
  backend needs its own path (section 3.4).
- M9 PARTIAL: the PKG-1 service host landed; the shell spawns it in
  PKG-6. Today the shell starts nothing at launch
  (`rc-shell/src/main.js:1746`); RC's services start only from scheduled
  tasks, two of them at boot (`RC-DaemonSlayer` at boot as SYSTEM,
  `RC-DSKeepalive` at startup; `docs/OPERATIONS.md` "Scheduled tasks").
  That violates intents 3 and 4 (section 3.1, PKG-1 + PKG-6).
- M10 Licence payload needs a recorded ruling before ANY distribution (the
  CLAUDE.md gate: RC is Apache-2.0 and public; the wrapper does not clear
  the payload). Copyleft items found in what would ship:
  - Electron's runtime carries `ffmpeg.dll` (LGPL-2.1, dynamically linked,
    unmodified) and `LICENSES.chromium.html`.
  - The opencv-python wheel carries `opencv_videoio_ffmpeg500_64.dll`
    (LGPL-2.1). RC never calls `VideoCapture` / `VideoWriter` (grep is empty
    outside tests), so the bundle builder strips that DLL.
  - certifi is MPL-2.0 (file-level copyleft, shipped unmodified). truststore
    is already a dependency, so dropping certifi is an option.
  Everything else is permissive: npm closure of electron-updater = MIT / ISC
  plus argparse (Python-2.0) and sax (BlueOak-1.0.0); Python closure = MIT /
  BSD-3 / Apache-2.0 / PSF-2.0 / MIT-CMU (Pillow) / mixed-permissive (numpy).
  lazy-val ships no LICENSE file (MIT declared in its package.json), so its
  attribution must be generated. Ruling needed: "unmodified, dynamically
  linked LGPL runtime DLLs shipped inside an installer, with their licence
  texts" is distribution, not vendoring into the tree; the gate's
  DO-NOT-VENDOR line is about source in the repo. The ruling is
  operator-gated (section 4); the PKG-8 notices generator fails on each
  copyleft item until a recorded ruling id covers it.

### 1b. SHOULD

- S1 Blanket TLS trust. `certificate-error` accepts ANY certificate for the
  origin host (`rc-shell/src/main.js:1694`) and the poll runs
  `rejectUnauthorized: false` for any origin (`rc-shell/src/main.js:1483`).
  Pin the install's own leaf fingerprint instead: `rc-shell/src/tls_pin.js`
  `pinDecision` landed (PKG-3 61c3ceed3); wiring is PKG-6.
- S2 FIXED (PKG-3 61c3ceed3). `RC_ORIGIN` or a saved `origin` accepted any
  scheme and host, and the preload bridge plus the cert trust follow it.
  `validateOrigin` (`rc-shell/src/config.js:183`) now allows http(s) on
  loopback or https on a host named in `ops/local_hosts.json`; until PKG-6
  passes `localHosts`, only loopback passes.
- S3 IPC trusts every sender except the toggle channel
  (`rc-shell/src/main.js:1213`). Check `event.senderFrame` origin against the
  resolved origin on every `rcShell` channel (defense in depth behind M2).
- S4 Unsigned installer and updates. `rc-shell/electron-builder.yml` has no
  signing config; electron-updater then checks only the sha512 in
  `latest.yml` over HTTPS, and SmartScreen warns on every install. Signing
  certificate = operator decision (cost); until then document unsigned.
- S5 No app icon: `rc-shell/electron-builder.yml` declares none, so the
  default Electron icon ships. N8 asset provenance wants an RC-own icon.
- S6 userData split. `rc-shell/package.json:2` names the app `rc-shell`
  while `rc-shell/electron-builder.yml:25` says `Amberstone Shell`, so a dev
  launch and a packaged launch keep window / overlay state in different
  folders. Add `productName` to package.json (one-time state migration).
- S7 Kill-by-image scripts. `scripts/restart.bat:7`, `scripts/kill.bat:5`
  and `ops/launch_new_system.bat:18` run `taskkill /F /IM pythonw.exe`, which
  on a user's machine kills unrelated Python apps. The launcher stops only
  what it owns (job object, owned PIDs); these scripts stay operator-only and
  out of the bundle.
- S8 A boot-start installer still ships. `ops/install_startup.bat:15` and
  `ops/install_startup.bat:29` create a Startup-folder shortcut to
  `ops/rc_league_watcher.ps1`, the exact thing intent 3 forbids. Exclude it
  from every bundle; retire it with the cutover.
- S9 Task coupling in the restarters. The frozen supervisor relaunches Phase
  3 only through `schtasks /Run RC-Phase3-Supervisor`
  (`ops/rc_supervisor.py:482`); on a machine without that task it fails each
  cooldown (bounded by its breaker) and logs noise. `DsWatchdog` prefers
  `schtasks /Run RC-DaemonSlayer` and RAISES, with no direct-child fallback,
  when the task exists but is disabled (`core/daemon_slayer_client.py:258`).
  So the cutover must UNREGISTER tasks, never disable them (section 5).
- S10 PATH-resolved interpreter. `ops/rc_config.json` sets `python_exe` and
  `app_cmd` to bare `pythonw.exe`. The launcher hands the supervisor a
  generated per-install config (the supervisor takes `--config`; absolute
  values are per-host overrides) naming the bundled interpreter.
- S11 Keyless start. `start.bat:53` refuses to start without an Anthropic
  key while `main.py:45` only logs and continues. "Usable without Claude"
  means the packaged app starts keyless (DS math, deterministic coach) and
  coach panels show the friendly degraded message (CLAUDE.md error rule).
- S12 The shipped runtime is built from the hashed `requirements.txt`, never
  copied from a dev interpreter: the canonical dev interpreter currently
  trails several pins (measured 2026-10-26).
- S13 Tesseract is external (`core/vision_tesseract.py:31`, default under
  `%ProgramFiles%\Tesseract-OCR`). A fresh machine lacks it and vision OCR
  escalates to Sonnet (cost). Bundle it (Apache-2.0; audit its payload) or
  offer it as an optional first-run download.
- S14 The release bundle must carry the real LFS laning tables, not the
  133-byte pointer (`docs/OPERATIONS.md` "Git LFS"), or the laning coach
  fails soft to live Haiku.
- S15 The :8888 responses carry no `Content-Security-Policy` header (grep
  of `dashboard/` is empty). The shell loads that origin with a preload
  bridge, so add a `script-src 'self'` policy in the packaged profile.
  Blocked until the inline `<script>` blocks at `web/index.html:12` and
  `web/index.html:2521` move out or are hashed (PKG-5 deferred it).

### 1c. NICE

- N1 `sanitizeWidgetLayout` caps neither id count nor id length
  (`rc-shell/src/overlay_state.js:766`), so a page can bloat the state file.
- N2 `will-quit` (`rc-shell/src/main.js:1768`) clears no handle of the three
  200 ms signal-file intervals (`rc-shell/src/main.js:1571` and siblings).
- N3 No `app.setAppUserModelId` call, so toasts and taskbar grouping are
  unnamed in a packaged build.
- N4 Three 200 ms file polls for hotkey signals; once the launcher owns the
  hotkey listener, one watcher or a local pipe replaces them.
- N5 `rc-shell/README.md:29` still says "the preload is empty" (false since
  OVL1) and the Run section assumes `npm install`.
- N6 `rc-shell/node_modules` still holds electron 44.5.1 against the 44.9.1
  pin (regen blocked by EBUSY while the overlay runs), so a dev launch runs
  an older runtime than a packaged one.

### 1d. What a fresh machine lacks today

- Python 3.14 with the hashed lock installed (`docs/OPERATIONS.md` "Python
  interpreter"). Packaged answer: embedded runtime (section 3.5).
- `ops/tls/rc.pem` + `rc-key.pem` (mkcert + `tools/regen_rc_cert.ps1`).
  Packaged answer: loopback HTTP by default, TLS only for opt-in LAN.
- `API-Key-Claude.txt` (optional after S11) and `API-Key-Riot.txt`
  (personal key, single-user by ADR-006 - never shipped, see section 6).
- `ops/local_hosts.json` - not needed; code defaults to loopback.
- Git hooks (`scripts/install_hooks.py`) - dev only; a packaged install has
  no git. Needed only in linked-checkout mode (section 3.4).
- Tesseract (S13), the real LFS tables (S14), long-path config for a clone
  (`docs/OPERATIONS.md` "Fresh clone").
- The RC-* scheduled tasks - deliberately NOT recreated; the launcher
  replaces them.

## 2. Process model today (measured)

- `RC-Supervisor` (logon, HIGHEST) runs the frozen `ops/rc_supervisor.py
  --config ops/rc_config.json`, which owns `main.py` (dashboard :8888 + app
  loop), restarts it on `restart_trigger.txt`, accepts JSON requests in
  `ops/runtime/supervisor_requests/` (`restart`, `rollback`, `shutdown`,
  `reset_circuit_breaker`; `ops/rc_supervisor.py:1309`), and applies signed
  transactional deploys with backup + verify + rollback
  (`ops/rc_transactional_deploy.py`).
- Inside `main.py`: `core/hot_reload.py` restarts RC (via the trigger) when
  a LOADED module changes and defers while a game is live
  (`core/hot_reload.py:551`); `VisionWatchdog` respawns `:8889` with
  `sys.executable` (`dashboard/_vision_watchdog.py:141`); `DsWatchdog`
  relaunches `:8860` through its task, or as a direct `sys.executable` child
  where no task is registered (`core/daemon_slayer_client.py:365`).
- ADR-008: any `web/` asset edit changes the asset hash and every open page
  reloads itself within ~4 s - no restart.
- LCU agent, Live Client relay and hotkey listener exist ONLY as ONLOGON
  tasks; nothing restarts them.
- `rc-shell` is a thin client: it loads the origin, polls `/api/state`, and
  reads hotkey signal files the listener writes into `ops/runtime/`.

## 3. Target architecture

### 3.1 Launcher process model

One user-facing executable, the Electron shell, is the launcher. It spawns
ONE child, a Python service host, and the host owns every RC process:

    Amberstone.exe (Electron main: launcher + companion/overlay/toggle UI)
      single-instance lock (exists)
      -> service host: <python> -I ops/launcher/service_host.py
             --root <backend> --parent-pid <electron pid>
         Windows Job Object, KILL_ON_JOB_CLOSE; every child inside it:
           rc_supervisor.py --config <generated per-install config>
             -> main.py (:8888, app loop, hot_reload)
                -> moon_vision_server.py (:8889, via VisionWatchdog)
                -> DS server (:8860, via DsWatchdog, direct child)
           tools/lcu_agent.py, tools/liveclient_relay.py,
           tools/hotkey_listener.py (restart-on-exit with backoff)
           (dev profile only) python -m agents.supervisor (:8890 / :8891)

Why a Python host and not Node `child_process`: a Job Object is a few
ctypes calls in Python and needs a native module in Node; the host reuses
RC's process hygiene (CREATE_NO_WINDOW on every console child, stop by owned
PID, never `taskkill /IM`) and is testable under pytest. Electron spawns one
windowless child and reads its status file.

Status surface: the host writes `ops/runtime/launcher_status.json`
atomically, one entry per service with a kit-vocabulary state, pid, port,
restart count and last error. The shell shows a starting view until
`/api/health` answers, then the normal surfaces.

### 3.2 Start and stop

- Launch: Electron `whenReady` spawns the host; the host generates the
  supervisor config (absolute interpreter, S10), provisions per-install
  secrets on first run (dashboard token, deploy key via
  `ops/rc_transactional_deploy.py:153` `ensure_key`), then starts services
  in order supervisor -> agents. Vision and DS come up through RC's own
  watchdogs, as today.
- Quit: Electron `before-quit` tells the host to stop (stdin line). The
  host writes a `shutdown` supervisor request (graceful: main.py stopped by
  owned PID), stops the agents, waits a bounded grace, then terminates the
  job. Anything left - including grandchildren the watchdogs spawned - dies
  with the job.
- Crash: if Electron dies, the host sees the parent pid gone and runs the
  same stop. If the host dies, the job handle closes and Windows kills every
  child. No orphan can outlive the app.
- Never at boot: no Run key, no Startup shortcut, no task, no
  `app.setLoginItemSettings({openAtLogin: true})`. The NSIS installer makes
  Start-menu and optional desktop shortcuts only. A guard test pins this
  (PKG-6).

### 3.3 Single instance and attach mode

- Electron's `requestSingleInstanceLock` (exists) plus a host pid lock in
  `ops/runtime/service_host.pid`.
- Attach mode: if `:8888` is already served by a healthy supervisor (Legion
  before the cutover, or a dev run), the host starts NOTHING and only
  reports. This is what makes the cutover safe to stage: the packaged app
  can run beside the old tasks with no double start (the frozen supervisor
  already refuses a second copy of itself through its PidLock and adopts a
  healthy running app instance).

### 3.4 Update channels and the no-restart reload path

- Linked-checkout channel (operator, dev): the launcher's backend root is a
  git checkout. Python edits reach RC through `core/hot_reload.py` (restart
  ~5 s, held while a game is live); `web/` edits reload pages via ADR-008
  with no restart. Processes hot_reload does not cover (vision, DS, agents,
  Phase 3) get a stale-code check in the host, modelled on the frozen
  supervisor's Phase 3 watcher: a service whose import-chain mtime is newer
  than its start is restarted alone, only when no game is live. Shell
  `rc-shell/src` edits are the only true app restart: the launcher offers
  "relaunch when idle" and never relaunches during a game.
- Release channel (other users): each GitHub Release carries
  (a) the NSIS shell installer + `latest.yml` (electron-updater, existing,
  installs on quit) and (b) `backend-<ver>.zip` + `backend-<ver>.json`
  (per-file sha256, minimum shell version, payload allow-list). The
  launcher checks (b) on the same stable / dev channel as the shell,
  verifies every sha256, stages under `ops/runtime/staging/<ver>/`, and
  writes a SIGNED deploy request (`ops/rc_transactional_deploy.py:197`
  `sign_request`). The frozen supervisor applies it with its existing
  backup + verify + rollback whenever the app is healthy
  (`ops/rc_supervisor.py:1421`); it never checks for a live game, so the
  updater owns that deferral: apply and rollback refuse while a game is
  live (`ops/launcher/updater.py:1123` `_check_game`, CLI exit 3). A
  web-only release needs no restart at all (ADR-008).
- State never travels in a payload: `data/` runtime artifacts, `logs/`,
  `ops/runtime/`, both key files and `ops/local_hosts.json` are outside the
  allow-list (the deploy worker already refuses the key file on both sides
  of the copy), and so is every `.gitignore`: the install's own ignore
  files decide what is per-install (`ops/launcher/updater.py:608`
  `IgnoreRules`).
- Publishing a GitHub Release stays operator-gated (none exists yet;
  `rc-shell/electron-builder.yml` header).

### 3.5 How Python ships

Decision: EMBEDDED. The bundle carries a CPython embeddable distribution
(PSF licence) in `python-embed/` (the layout `start.bat`,
`scripts/restart.bat` and `tools/build_portable.py` already probe for),
with site-packages installed from the hashed `requirements.txt` by
`pip --require-hashes --target` at build time, and the unused
`opencv_videoio_ffmpeg*.dll` stripped (M10). Version = 3.14, the one the
dev tree runs (the lock resolves for 3.11 to 3.14); PKG-4 pins the
python.org 3.14.4 embeddable zip by sha256.

Rejected: "Python required". Asking a user to install 3.14, run pip against
a hashed lock and fix PATH is exactly the wiring intent 1 removes.
Linked-checkout mode may still point at the canonical dev interpreter.

### 3.6 First run on a fresh machine

- Packaged profile binds the dashboard to loopback and serves plain HTTP
  when no cert exists (Chromium treats 127.0.0.1 as a secure context). The
  host reports the served origin, and the shell uses exactly that (fixes
  M4). LAN / tailnet access is an opt-in that requires a cert (the existing
  mkcert path) and turns TLS pinning on (S1).
- A per-install `RC_DASH_TOKEN` is generated on first run and set in the
  services' environment; the shell attaches it as `X-RC-Token` to requests
  for its own origin only (`session.webRequest.onBeforeSendHeaders`), so the
  control endpoints are no longer open even if LAN is enabled (fixes M5).
- A local settings page (a file page with a strict CSP, like
  `rc-shell/src/overlay_toggle.html`) takes the optional Anthropic key; the
  host writes it through the `core/anthropic_key.py` conventions. No Riot
  key is ever shipped (section 6).

## 4. Build slices

Every slice: own worktree, TDD, ruff on generated Python, touched tests only,
read-only verifier before merge. No slice touches a frozen file; a slice
that finds it needs one stops and asks (operator approval required).

Status 2026-10-26 (`git log 2d3e1c85b..86627008a`):

- LANDED: PKG-1 (bf2b9bdef, 2890fb026; RM-258 sanction eb90635d5), PKG-2
  (79ce0e9cd, 50f935416, 86627008a), PKG-3 (61c3ceed3), PKG-4 (c066cb0ca,
  dea18d069), PKG-5 (f3690023f, d2fb1c125: a peer-address gate instead of
  a loopback bind + token; CSP deferred, S15), PKG-8 (79fec0b5f, d9c5f2a47).
- LANDED after wave A: PKG-1b (below; 4859c9405..1ca036c77).
- OPEN: PKG-6, PKG-7.

- PKG-1 Service host. Files: `ops/launcher/__init__.py`,
  `ops/launcher/service_host.py`, `ops/launcher/services.json`,
  `tests/test_launcher_service_host.py`. Accept: fake services start inside
  one job; parent death kills all of them; graceful stop writes a
  `shutdown` supervisor request before terminating the job; attach mode
  starts nothing when a healthy supervisor holds :8888; restart-on-exit
  backoff is bounded; every child spawned with CREATE_NO_WINDOW; no
  `taskkill /IM`; status file written atomically. Tier-1.
- PKG-1b First-run provisioning (new, after PKG-1). Files:
  `ops/launcher/first_run.py`, `ops/launcher/service_host.py`,
  `ops/launcher/services.json`, `tests/test_launcher_first_run.py`.
  Accept: per-install secrets created on first launch, never shipped - at
  least the vision token (`import app` raises without
  `config/vision_token.txt` or `RC_VISION_TOKEN`, PKG-4 finding) and the
  deploy key (`ensure_key`) the updater needs; idempotent; plus the
  HostLog rotation residual named in eb90635d5. Tier-1.
- PKG-2 Backend updater. Files: `ops/launcher/updater.py`,
  `tests/test_launcher_updater.py` (merge after PKG-1 for the package
  `__init__`). Accept: manifest parse with schema check; a sha256 mismatch
  or a path outside the allow-list refuses the whole update; staging is
  atomic; the deploy request verifies with the per-install key; apply is
  deferred while a game is live; no network in tests (local fixture
  release). Tier-1.
- PKG-3 Shell pure modules. Files: `rc-shell/src/rc_root.js`,
  `rc-shell/src/tls_pin.js`, `rc-shell/src/service_status.js`,
  `rc-shell/src/config.js`, `rc-shell/test/rc_root.test.js`,
  `rc-shell/test/tls_pin.test.js`, `rc-shell/test/service_status.test.js`,
  `rc-shell/test/config.test.js`, `rc-shell/package.json`. Accept:
  backend-root resolution (env, argv, dev fallback; packaged with no root =
  null, never `__dirname/../..`); fingerprint pin decision; status-file
  parse to surface states; origin validation (S2). Node tests in the
  enumerated script. Tier-1.
- PKG-4 Bundle builder. Files: `tools/build_portable.py`,
  `tools/build_python_embed.py`, `tools/package_portable.py`,
  `tools/build_installer.py`, `tests/test_build_portable_bundle_pkg.py`.
  Accept: inclusion derived from the git index minus an explicit dev-only
  exclusion list (tests, docs, ops/loop, ops/fleet_kit, .github, agent test
  dirs, scratch); the import closure of `main.py`, `web_dashboard.py`,
  `moon_vision_server.py` and the three agents is inside the bundle; no key
  file, no `ops/runtime/`, no `ops/install_startup.bat`, no LFS pointer;
  artifacts named `Amberstone-*`; embedded runtime built from the hashed
  lock with the opencv ffmpeg DLL stripped. Tier-1.
- PKG-5 Packaged dashboard profile. Files: `dashboard/server.py`,
  `tests/test_dashboard_bind_profile_pkg.py`. Accept: bind host from an
  environment variable defaulting to today's `::` (Legion unchanged); the
  launcher profile binds loopback; a CSP header in the packaged profile
  (S15); live probe after merge (`/api/state` answers on loopback, a LAN
  address refuses). Tier-1 plus restart verify.
- PKG-6 Shell launcher wiring (wave B, after PKG-1 + PKG-3). Files:
  `rc-shell/src/main.js`, `rc-shell/electron-builder.yml`,
  `rc-shell/README.md`, `rc-shell/test/launcher_wiring.test.js`,
  `rc-shell/package.json`. Accept: host spawned at launch and stopped on
  quit; signal paths from `rc_root.js` (M3); TLS pin (S1); IPC sender check
  (S3); token header for the own origin only; starting view until healthy;
  relaunch-when-idle for shell updates; extraResources carry the backend +
  `python-embed`; productName aligned (S6); icon (S5); a guard that no code
  or builder option enables start at login. Tier-1, operator visual check.
  Wiring checklist from wave A:
  - `resolveRcRoot` + `signalPaths` (M3); `resolveConfig(saved, env,
    {localHosts, servedOrigin})` (S2, M4); `pinDecision` in
    `certificate-error` and the poll (S1; the pin ignores expiry - decide
    renewal); `shellView` for the starting view.
  - `will-redirect` + `will-frame-navigate` handlers (V2).
  - On Legion launch the host with `--profile dev` (keeps the `::` bind).
  - Updater CLI `check` / `stage` / `apply` / `finish`; exit 3 = game live,
    retry later; `recover()` when the app does not come back; restart the
    named services it reports (the supervisor restart never reaches them).
  - Inject `X-RC-Token` before any `dash_token_gate=true` (V3 callers).
  - Calibrator ingest help text (`web/vision_calibrator.html:84`): files
    must live in `data/vision_calib_reference`.
  - CSP (S15) is blocked by the `web/index.html` inline scripts.
  - `tools/bootstrap_env_check.py` still expects `scripts/restart_clean.bat`.
  - Acceptance: `tools/run_packaged_smoke.py` over a real build.
- PKG-7 Cutover tooling, no execution (wave B). Files:
  `tools/launcher_cutover.ps1`, `tests/test_launcher_cutover_ps1.py`,
  `docs/OPERATIONS.md`. Accept: `-WhatIf` is the default; it exports each
  task's XML before touching it; it UNREGISTERS (never disables) exactly
  the section-5 list; `-Rollback` re-imports the XML; PS 5.1 ParseFile
  clean, ASCII + LF. Running it is the operator step. Tier-1.
- PKG-8 Lockfile + third-party notices. Files: `.gitignore` (negate
  `rc-shell/package-lock.json`), `rc-shell/package-lock.json`,
  `tools/build_third_party_notices.py`,
  `tests/test_third_party_notices_pkg.py`. Accept: the lock is tracked and
  copied byte-level from the main checkout's current lock (never
  regenerated while the overlay holds node_modules); every production npm
  and Python dependency maps to an allow-listed licence or a recorded
  ruling id; copyleft entries fail without the M10 ruling; the notices file
  is generated into the build output, not tracked. Tier-1.

Wave A (parallel, disjoint): PKG-1, PKG-3, PKG-4, PKG-5, PKG-8, then PKG-2
on top of PKG-1. Wave B: PKG-6 and PKG-7. The eight slices are NOT disjoint
as a set: PKG-6 shares `rc-shell/package.json` with PKG-3 and rebases onto
it (V1 below).

### Verifier findings (s141)

Read-only verifier pass over this spec before the wave A / B builders. Each
item binds the named slice.

- V1 Slice overlap. `rc-shell/package.json` is in both PKG-3 and PKG-6
  (both add test files to its enumerated `test` script). They sit in
  different waves, so wave A is disjoint, but PKG-6 must rebase onto
  PKG-3's `package.json`, never start from today's.
- V2 Nav guard gaps (PKG-6). Only `will-navigate`
  (`rc-shell/src/main.js:502`) and `setWindowOpenHandler`
  (`rc-shell/src/main.js:498`) are wired today. PKG-6 adds `will-redirect`
  and `will-frame-navigate` handlers applying the same `nav_guard.js`
  decision. Theoretical while the dashboard sends no 3xx, but the guard
  must not depend on that.
- V3 M5 design conflict (PKG-5, with PKG-6 and the section-5 cutover).
  - A loopback-only packaged bind cuts off the documented
    `https://rc-host:8888` tailnet view once the launcher replaces the
    scheduled tasks on Legion, unless Legion's profile keeps a
    tailnet-reachable bind (the section 3.6 opt-in, set before cutover).
  - A per-install `RC_DASH_TOKEN` 401s every plain-browser control POST
    that sends no `X-RC-Token`; the shell's own-origin header injection
    covers shell windows only. Gated callers with no token header (grep
    2026-10-26): `web/js/main.js:174`, `web/js/panels/champ_select.js:61`
    and `web/js/panels/champ_select.js:214` (all `/api/lcu-cmd`),
    `web/js/panels/champ_select.js:3402` and
    `web/js/panels/item_build.js:435` (both `/api/loadout/apply`), plus
    every gated POST in the still-served `web/legacy_index.html` (its
    `postJSON` at `web/legacy_index.html:2736` sends none). The other
    gated callers already send `localStorage.rc_dash_token`.
  - The recording `<video>` (`web/index.html:1698`, served by
    `dashboard/routes_recordings.py` behind the same gate) cannot send a
    header (BACKLOG RM-679(a): short-lived signed URL vs cookie).
  - PKG-5 must name and handle each of these callers before a token is
    ever set.

### Operator-gated (no lane runs these)

- M10 licence ruling: the two LGPL ffmpeg DLLs (Electron `ffmpeg.dll`; the
  opencv videoio DLL, stripped by default) and certifi (MPL-2.0).
- Code-signing certificate (S4) and the first GitHub Release publish.
- RM-189 gates and the ADR-006 reopen (section 6).
- The ONLOGON cutover with its XML backup (section 5).
- Live hotkey check from the unelevated launcher, with an unelevated and
  then an elevated window focused.
- LAN-refusal live check from a second device (a control POST from a LAN
  peer gets 403, PKG-5).

## 5. ONLOGON-to-launcher cutover (OPERATOR-GATED)

Scheduled-task writes are operator territory; no lane, loop or slice runs
any step here. The packaged app must have passed attach mode (3.3) first.

1. Stage 0, no system change: run the packaged app in attach mode beside
   the existing tasks and confirm the shell, the status view and the update
   check.
2. Stage 1, OPERATOR STEP (elevated): `tools/launcher_cutover.ps1` without
   `-WhatIf` exports each task's XML to a gitignored backup folder under
   `ops/runtime/`, then UNREGISTERS `RC-Supervisor`, `RC-LCUAgent`,
   `RC-LiveClientRelay`, `RC-HotkeyListener`, `RC-Phase3-Supervisor`,
   `RC-DaemonSlayer` and `RC-DSKeepalive` (plus `RC-LiveFlipWatcher` if the
   operator wants it launcher-owned). Unregister, never disable (S9). Dev
   and fleet tasks (Mission Control, the moon-sync poller, CI watchdog,
   inbox responder, data-pipeline and replay tasks, the proxy and quota
   utilities) are not the app and stay. Deleting the disabled bare
   `RiotCommander` task stays the operator's separate call.
3. Stage 2 proof: sign out and back in; nothing RC listens on :8888 /
   :8889 / :8860 (never-at-boot). Launch the app: all services up and
   `launcher_status.json` healthy. Quit: no RC process left.
4. Rollback: `tools/launcher_cutover.ps1 -Rollback` re-imports the XML.
5. Record: `docs/OPERATIONS.md` scheduled-task table and its live count,
   plus `tools/rc_facts.py` expectations, change in the same commit as the
   cutover record.

Elevation: `RC-Supervisor` ran HIGHEST and DS ran as SYSTEM; the launcher
runs unelevated. PKG-1 measures whether any service actually needs
elevation before the cutover (expected: none).

## 6. Distribution gates (OPERATOR-GATED)

Running the packaged build on the operator's own box needs none of these.
Giving it to anyone else needs all of them:

- ADR-006 reopen: the Riot key is a personal, single-user key and the ADR
  says redistribution reopens it. A shared build ships no Riot key; Riot-API
  features degrade (or take a user-supplied key) until a production key
  exists.
- RM-189: Riot developer-portal registration, a public site, Terms of
  Service and Privacy Policy for a production key; B4-f live-advice ruling.
- M10 licence ruling recorded (PKG-8) and a generated notices file shipped.
- Code-signing decision (S4) and the first GitHub Release publish.
- Asset provenance audit of everything in the bundle (OVERLAY_COMPLIANCE_PLAN
  N8; `NOTICE` already records the tracked third-party data).

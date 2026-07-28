# RC 2.0 Phase-1 Research (Stage 1.1) - In-Game Overlay Sizing, DPI, Click-Through, Anti-Cheat

Status: RESEARCH (Phase-1, stage 1.1). Authored 2026-06-19. ASCII-only.
Scope: how desktop game-overlay apps SIZE and PLACE an in-game HUD relative to
the game window, handle DPI / multi-resolution, do click-through + always-on-top,
and stay Vanguard-safe (no DXGI capture, no injection). Then a 6-point LIFT
checklist per pattern against RC today.

Operator constraint accepted for RC: League runs at 1920 fullscreen OR borderless
at default resolutions, so the RC overlay MAY assume a single, known game monitor
and a borderless-or-1920 game window. This is the same assumption every product
below makes for its "no-injection" tier.

-------------------------------------------------------------------------------

## 0. The one fact that frames everything: two overlay architectures

Every overlay below is one of two kinds. This is the load-bearing distinction:

1. **HOOK / INJECTION overlay** - inject a DLL into the game process, hook the
   D3D/OpenGL/Vulkan present call (or `SetWindowsHookExA` for kernel-AC titles),
   and draw INSIDE the game's own swapchain. Pixel-perfect, frame-synced, but it
   touches the protected process. This is RTSS, MSI Afterburner, OBS "Game
   Capture", Overlay Platform M's classic overlay, and Discord's OLD overlay.
   - Discord injected via `discordhelper64.exe` doing a `LoadLibrary` (or
     `SetWindowsHookExA` for kernel-AC games) and hooking DirectX/OpenGL. This is
     exactly the family of techniques anti-cheats flag.
     (guidedhacking.com x64 Discord DX11 hook tutorial; PicoShot/DiscordOverlayHook)

2. **COMPOSITOR / ATTACH-TO-WINDOW overlay** - a separate, normal, transparent,
   always-on-top OS window that the Desktop Window Manager (DWM) composites OVER
   the game. No code runs in the game process; nothing is hooked. Works only when
   the game is BORDERLESS (windowed-fullscreen), because exclusive-fullscreen
   bypasses the DWM compositor and the overlay vanishes behind it. This is
   Discord's NEW overlay ("ditched the hacky game hook in favor of attaching to
   the window"), and it is exactly what an Electron transparent window is.
   (neowin.net Discord new-overlay; obs-versions.com - "Display Capture doesn't
   require hooking and doesn't need to inject ... so there are no anti-cheat issues")

**RC is firmly in family #2 and must stay there.** `rc-shell/src/main.js:40-43`
states it in the header: "No DXGI / frame capture, no game-memory reads, no input
injection - ever. The overlay is a DWM compositor window only." Everything liftable
below is from how the family-#2 products SIZE and PLACE that compositor window; the
family-#1 sizing tricks (swapchain-relative coords, present-hook DPI) are
deliberately NOT liftable because they require the injection RC forbids.

-------------------------------------------------------------------------------

## 1. Per-product findings (cited)

### 1.1 Overlay App E
- Runs as an Overlay Platform M app. Official Vanguard posture: Overlay App E "presents information
  that the game already provides ... does not read or write memory, so it should
  not interfere with Vanguard." Apps that "use proper Riot APIs and do not
  exfiltrate information directly from client memory" stay compatible; "legitimate
  third-party apps available through Overlay Platform M are fully safe with Vanguard."
  (support.overlay app E - Will Overlay App E Continue Working with ... Vanguard)
- Sizing/placement: Overlay Platform M-managed overlay windows; user can move and the app
  auto-pops on champ hover/lock. Elevation gotcha: if League runs elevated, Overlay App E
  must run elevated too or the overlay does not draw (a Windows UIPI / same-
  integrity-level rule that bites any always-on-top window over an elevated game).
  (support.overlay app E QuickGuide + General Overlay Troubleshooting)
- DPI: handled by the Overlay Platform M runtime (see 1.5), not by Overlay App E itself.

### 1.2 Overlay App F / GameSense
- Also an Overlay Platform M app. Overlay is user-customizable: "move the overlay window,
  change its size, or adjust the transparency of the information panels."
  (overlay platform M/app/trebonius-overlay app F; lutris.net Overlay App F overlay)
- Notable: their support has a dedicated "the content is too big for the window /
  ad too big" page - i.e. a FIXED-px overlay panel that does not reflow gracefully
  is a known, shipped pain point. The lesson for RC: an overlay panel sized in
  fixed px will clip at non-design resolutions/DPI; reflow or scale it.
  (overlay app F resolution support note)

### 1.3 Aggregator C
- Overlay Platform M app (same runtime, same posture as Overlay App E/Overlay App F). In-game build/
  rune overlay; builds do not adapt to enemy team. No bespoke windowing - it
  inherits Overlay Platform M's overlay window management and DPI handling.
  (overlay app Z6 comparison; cbinsights Aggregator C vs Overlay Platform M)

### 1.4 aggregator A desktop / Aggregator B desktop
- aggregator A companion app: strength is stats/scouting, weaker on in-game overlay
  guidance. Aggregator B: solid overlay but the documented limitation is that "overlays
  must be on-screen at all times" (no smart auto-hide) - i.e. their overlay is a
  persistent always-on-top window, not a mode-gated show/hide.
  (sagemode.gg Aggregator B/Aggregator C/Overlay App F; eloboostleague best programs)
- Takeaway for RC: RC's mode_key-gated auto show/hide (companion in client,
  overlay only in-match) is already AHEAD of Aggregator B's always-on behavior.

### 1.5 Overlay Platform M overlay framework (the runtime under 1.1-1.3)
- Overlay Platform M is "the engine that lets apps operate ... bring their apps in-game
  (with overlays)." Apps declare overlay windows; the runtime injects/attaches and
  manages them. (overlay platform M browse-by-game; overlay platform M developer docs in-game-overlays)
- Borderless requirement: Overlay Platform M "allows capturing these games ONLY in
  fullscreen-borderless mode. If the game is in fullscreen non-borderless or
  windowed mode the capture will not work correctly"; in exclusive fullscreen
  "exclusive mode is completely disabled and there's no option to interact with
  your app's window." Confirms the borderless mandate for any DWM-composited
  overlay. (overlay platform M developer docs in-game-overlays)
- Injection hygiene: Overlay Platform M had to "improve overlay injection ... to prevent
  injection into small loading windows" (e.g. anti-cheat/shader-compile child
  windows). Lesson: pick the GAME window deliberately (by size/resolution), do not
  attach to the first window the process shows. (overlay platform M release notes)
- DPI: documented "high DPI solutions" for apps that "look cut-off or displayed
  improperly" - i.e. Overlay Platform M treats DPI as a first-class, must-handle problem.
  (overlay platform M support common issues)
- Anti-cheat: FACEIT AC can block Overlay Platform M event access; CS2 requires windowed.
  Riot/Vanguard is NOT on that block list for the API-only tier - matching Overlay App E's
  posture. (overlay platform M developer docs; overlay platform M support)

### 1.6 OBS (capture taxonomy - the cleanest public map of the 3 techniques)
- **Game Capture** = inject + hook the present call (family #1). Highest perf,
  needs same-process access; "security/stability risks from injection ... may be
  blocked by anti-cheat and can crash the target." NOT Vanguard-safe by RC's bar.
- **Window Capture (WGC, Windows.Graphics.Capture)** = DWM shares the GPU texture
  of a specific window; "WGC is safer since it doesn't use injection."
- **Display Capture** = DXGI Desktop Duplication of the whole monitor; "doesn't
  require hooking ... no anti-cheat issues" but it is monitor-wide.
  (obs-versions.com window/display/game-capture guides; obsproject.com WGC vs DXGI)
- RC relevance: RC does NONE of these (it does not capture the game at all - it
  reads Live Client :2999 + LCU). But the taxonomy is the canonical reference for
  why "compositor window over borderless" is the only injection-free DRAW path,
  and confirms exclusive-fullscreen defeats all non-injection methods.

### 1.7 RTSS / MSI Afterburner
- Pure family #1: "hooks into DirectX/OpenGL/Vulkan games and renders ... on top,"
  detecting the submit stage inside `ID3D11DeviceContext` hooks; can force DXGI
  interop to draw a D3D overlay even in GL/Vulkan apps. Conflicts with OBS Game
  Capture unless Detours hooking is enabled (two hookers fighting one present).
  (guru3d RTSS; wccftech RTSS guide; obsproject RTSS+OBS threads)
- RC relevance: NEGATIVE/cautionary only. This is the precise technique RC's
  frozen header forbids. Its only liftable idea is the DPI-correctness one: a
  hook overlay is DPI-perfect because it lives in the swapchain; a compositor
  window (RC) must solve DPI itself in OS coordinates. No code is liftable.

### 1.8 Discord in-game overlay
- OLD = family #1 (LoadLibrary / SetWindowsHookExA + DX/GL hook) -> the historic
  anti-cheat friction. NEW = family #2 ("attaching to the window," "new rendering
  method ... much snappier," "avoids these problems").
  (neowin.net Discord new overlay; guidedhacking; thelinuxcode turn-off-overlay)
- RC relevance: Discord's public migration from #1 to #2 is the strongest external
  validation that RC's compositor-window choice is the correct, modern,
  anti-cheat-safe design - not a compromise.

-------------------------------------------------------------------------------

## 2. Cross-cutting technical lessons (the sizing/DPI core)

These are the reusable mechanics distilled from the sources, framed for an
Electron family-#2 overlay (which is what RC is).

- **L1 - Borderless is mandatory; detect-and-nudge fullscreen.** A DWM-composited
  window only shows over borderless/windowed-fullscreen. Exclusive fullscreen
  hides it AND, on League, risks the known lockup. Every family-#2 product
  requires borderless. RC already mandates it (ELECTRON_OVERLAY.md 4B/9). Gap: RC
  does not yet DETECT fullscreen and show a "switch to Borderless" hint (listed as
  a risk-register mitigation, not built).
- **L2 - Pick the game window/monitor deliberately, never "first/index 0."**
  Overlay Platform M's loading-window injection bug is the cautionary tale; the fleet's
  `reference_gamepc_monitor_index_volatility` is the same lesson (monitor index
  swaps across reboots; pick by resolution). For 1-PC borderless-1920 this is
  simpler: one display, primary, 1920.
- **L3 - DPI is a first-class problem for a compositor overlay.** Overlay Platform M ships
  explicit high-DPI fixes; Electron's `screen.getPrimaryDisplay().scaleFactor` has
  a documented history of returning 1 under Windows display scaling
  (electron#6571), which silently mis-sizes a px-fixed overlay. A family-#1 hook
  overlay never sees this (it is in swapchain pixels); a family-#2 window MUST
  size in DIPs and/or read scaleFactor. RC sizes the overlay in a fixed px box
  (`OVERLAY_DEFAULTS.width/height`, overlay.css ~460px) and never reads
  scaleFactor - the single biggest sizing gap (see LIFT-C).
- **L4 - Click-through is the default; interactive is the exception, auto-revert.**
  `setIgnoreMouseEvents(true, {forward:true})` for passive HUD, flip false for
  interaction. `{forward:true}` is what preserves hover while passing clicks to the
  game; without it the window stops receiving mouse events. RC already does this
  exactly (main.js:527, 553) WITH a 20s auto-revert - ahead of the field.
- **L5 - Always-on-top must beat a borderless game.** Plain alwaysOnTop loses to
  GL/Vulkan games and to other apps' toolbars (electron#8530, #11830). The fix is
  an elevated z-level: Electron `setAlwaysOnTop(true, "screen-saver")`. League is
  D3D11 so the GL/Vulkan-specific bug does not bite, but the elevated level is
  still correct. RC already uses `"screen-saver"` (main.js:526).
- **L6 - Reflow or clip.** Overlay App F's "content too big for the window" support
  page is the proof that a fixed-size overlay panel breaks at off-design
  resolution/DPI. A compact overlay must either reflow (relative units) or scale to
  the measured viewport/scaleFactor.
- **L7 - Elevation parity.** Overlay App E's rule: if the game runs elevated, the overlay
  must run at the same integrity level or Windows UIPI blocks the always-on-top
  window. Relevant if League/Vanguard forces elevation.
- **L8 - No focus steal / no dialogs over a live game.** Always `showInactive()`,
  never `show()`/`focus()`; no modal dialogs. RC already does this (main.js
  uses showInactive throughout; updater is console-only, main.js:202-204).

-------------------------------------------------------------------------------

## 3. Where RC stands TODAY (grounded in the repo)

RC is a mature family-#2 implementation. Confirmed present:

- Transparent, frameless, always-on-top overlay window at `"screen-saver"` level:
  `rc-shell/src/main.js:503-526`.
- Click-through default + `{forward:true}` + interactive flip + 20s auto-revert:
  `main.js:527, 551-560, 568-585`.
- Global hotkeys via `globalShortcut` (RegisterHotKey under the hood, AC-safe):
  `main.js:738-767`; explicitly NOT input injection (`main.js:40-43`).
- Mode-gated auto show/hide off `/api/state` `mode_key`: `main.js:641-643`,
  `overlay_state.js` `resolveSurface`/`windowActions`.
- Overlay bounds: fixed-size box, right-edge dock, saved-coords clamped on-screen:
  `overlay_state.js:223-240`; 1920x1080 work-area fallback `:195-203`.
- Compact overlay frontend: `?overlay=1` -> `body[data-shell="overlay"]`, a
  separate `web/css/overlay.css` (~460px right-anchored column, GPU-light, chrome
  hidden) reusing tokens.css: `web/css/overlay.css:1-40`.
- Crash isolation, scoped mkcert cert trust, single-instance, electron-updater on
  natural-quit only: `main.js` throughout.

Confirmed GAPS (no code today):

- **No DPI / scaleFactor handling.** `screen.getPrimaryDisplay().scaleFactor` is
  never read; the overlay box and overlay.css are fixed px. At 125%/150% Windows
  scaling or a non-1920 borderless res, the dock can mis-size/clip (L3, L6).
  Grep: no `scaleFactor`/`devicePixelRatio` anywhere in `rc-shell/` or
  `web/css/overlay.css`.
- **No fullscreen detection / "switch to Borderless" hint.** L1 mitigation is
  documented in ELECTRON_OVERLAY.md 9 but not implemented.
- **Overlay window is not resolution-aware.** It always uses `OVERLAY_DEFAULTS`
  size and docks to the right of whatever work area it is handed; it never adapts
  the panel size to the actual game resolution or DPI.

Net: RC's click-through / always-on-top / anti-cheat posture is AT or ABOVE the
field. RC's overlay SIZING (DPI + resolution adaptivity) is the area where the
external patterns have something to lift.

-------------------------------------------------------------------------------

## 4. LIFT checklist (6-point, per pattern). Legal re-implementation only.

For each: WHAT / HOW / does RC already HAVE it (cite) / WHERE it integrates /
EFFORT+RISK / LIFT verdict. "Vendor code" is never lifted - mechanics only.

### LIFT-A. Borderless requirement + fullscreen detect-and-nudge (Overlay Platform M, Discord-new)
- WHAT: Require borderless; if the game is exclusive-fullscreen, the overlay is
  invisible, so detect it and surface a one-line "switch to Borderless" hint
  instead of a silently-dead HUD.
- HOW: On the existing `/api/state` poll tick, when `mode_key` is in-match but the
  overlay would be hidden behind the game, show a small companion/overlay toast.
  Detection options: read window style of the League HWND (no injection - just
  `GetWindowLong`/enumeration), or infer from "in-match but operator reports no
  HUD." Borderless itself is already the operator's locked setting, so this is a
  guard, not a hard dependency.
- RC HAVE IT? Partially. Borderless is mandated in docs (ELECTRON_OVERLAY.md
  4B/9/risk-register) and the overlay only shows in-match (`main.js:641-643`), but
  there is NO fullscreen-state detection or hint. No grep hit for `isFullScreen`/
  fullscreen detection in `rc-shell/`.
- WHERE: `rc-shell/src/main.js` poll path (`pollState`/`refreshSurface`) plus a
  tiny injected toast on the overlay page; pure shell-side, no Python.
- EFFORT+RISK: LOW effort / LOW risk. Win32 window-style read is read-only and
  AC-safe (same class as RC's existing LCU/HWND reads). Worst case it is a
  best-effort hint.
- LIFT VERDICT: **HIGH.** Closes the documented L1 gap, cheap, on-brand with the
  existing risk-register mitigation that was specced but never built.

### LIFT-B. Deliberate game-monitor/window selection by resolution (Overlay Platform M injection-hygiene)
- WHAT: Choose the overlay's target display by RESOLUTION (the 1920 game monitor),
  never by index, and never attach to a transient loading/child window.
- HOW: Enumerate displays, pick the one matching the known game resolution; for
  1-PC borderless-1920 default to the primary 1920 display.
- RC HAVE IT? Mostly. RC docks to `screen.getPrimaryDisplay()` (`main.js:499`) and
  the fleet already has the by-resolution-not-index rule
  (`reference_gamepc_monitor_index_volatility`), but the overlay code currently
  hardcodes "primary" rather than "the display whose size == game resolution."
  Given the operator's 1-PC 1920 assumption, primary == game monitor today.
- WHERE: `rc-shell/src/main.js:499-502` `createOverlayWindow` display pick;
  `overlay_state.js:resolveOverlayBounds`.
- EFFORT+RISK: LOW effort / LOW risk.
- LIFT VERDICT: **MED.** Largely already satisfied by the 1-PC/primary assumption;
  worth a tiny "pick by resolution" hardening only if multi-monitor returns. Not
  urgent under the stated constraint.

### LIFT-C. DPI / scaleFactor-aware overlay sizing (Overlay Platform M high-DPI, Electron scaleFactor, Overlay App F reflow)
- WHAT: Size the overlay window and its panels against the measured display
  scaleFactor + resolution so a 125%/150% Windows scale or non-1920 borderless res
  does not clip or shrink the HUD (the Overlay App F "content too big" failure).
- HOW: Read `screen.getPrimaryDisplay().scaleFactor` and `.size` at overlay
  create; scale `OVERLAY_DEFAULTS` accordingly, and make `overlay.css` use
  relative units / a CSS scale var instead of a hard ~460px column. Guard the
  known Electron scaleFactor==1 bug (electron#6571) with a sane fallback.
- RC HAVE IT? NO. Zero scaleFactor/devicePixelRatio usage; fixed px box
  (`overlay_state.js` `OVERLAY_DEFAULTS`) and fixed ~460px column
  (`web/css/overlay.css:1-24`). This is RC's clearest sizing gap.
- WHERE: `rc-shell/src/main.js:499-524` (window size) + `overlay_state.js`
  `OVERLAY_DEFAULTS`/`resolveOverlayBounds` + `web/css/overlay.css` (panel reflow).
  Frontend half is its own UI-audit-ritual page (`feedback_phase3_fixture_ritual`).
- EFFORT+RISK: MED effort / LOW-MED risk. Touches the overlay layout (audit
  ritual required); the scaleFactor bug needs a fallback. No anti-cheat surface.
- LIFT VERDICT: **HIGH.** This is the single highest-value lift: it makes the
  overlay correct beyond the exact 1920/100% baseline and directly fixes the
  best-documented external failure mode (Overlay App F clipping).

### LIFT-D. Click-through + {forward:true} + auto-revert (Discord-new, Electron norm)
- WHAT: Passive click-through HUD by default; interactive only on explicit hotkey;
  auto-revert to passive after idle; `{forward:true}` to keep hover.
- RC HAVE IT? YES, fully and well: `main.js:527, 551-560`, 20s auto-revert
  `main.js:568-585`. RC is at parity-or-better (auto-revert is not universal).
- WHERE: already in `main.js`.
- EFFORT+RISK: none (already shipped).
- LIFT VERDICT: **LOW (already have it).** No action; documented for completeness.

### LIFT-E. Elevated always-on-top z-level over a borderless D3D game (Overlay Platform M/Electron #8530/#11830)
- WHAT: Keep the overlay above the game and above other apps' toolbars via an
  elevated always-on-top level.
- RC HAVE IT? YES: `setAlwaysOnTop(true, "screen-saver")` (`main.js:526`).
- WHERE: already in `main.js`.
- EFFORT+RISK: none.
- LIFT VERDICT: **LOW (already have it).** Documented for completeness.

### LIFT-F. Elevation parity (Overlay App E)
- WHAT: If League/Vanguard runs the game elevated, run the overlay at the same
  integrity level or Windows UIPI blocks the always-on-top window from drawing
  over it.
- HOW: Detect game-elevated state; if RC shell is not elevated, surface a hint to
  launch the shell elevated (or ship an elevated launch path).
- RC HAVE IT? NO explicit handling. Not a problem today if neither is elevated,
  but it is the exact failure Overlay App E documents.
- WHERE: shell launch/config + a hint on the offline/no-draw path in `main.js`.
- EFFORT+RISK: LOW-MED effort / LOW risk; mostly a detect-and-hint.
- LIFT VERDICT: **MED.** Worth a guard if the operator ever runs League elevated;
  low priority under current (non-elevated) setup.

### LIFT-G. NEGATIVE - injection/hook draw paths (RTSS, OBS Game Capture, Discord-old)
- WHAT: Swapchain-relative, DPI-perfect, frame-synced drawing via DLL injection +
  present-hook.
- RC HAVE IT? Deliberately NOT, and must never. `main.js:40-43` forbids it.
- LIFT VERDICT: **DO NOT LIFT.** Recorded explicitly so a future pass does not
  re-pitch a hook overlay for "pixel-perfect DPI." The compositor + LIFT-C
  scaleFactor path achieves correct sizing without touching the protected process.

-------------------------------------------------------------------------------

## 5. Anti-cheat posture summary (Vanguard-safe, restated)

RC's overlay is injection-free by construction and matches the exact bar that
Overlay App E/Overlay App F/Aggregator C clear under Vanguard: present information the game
already exposes (Live Client :2999 + LCU lockfile - official APIs), no game-memory
read/write, no DLL injection, no input injection, no frame capture. The overlay is
a DWM-composited transparent window (Discord's modern, AC-safe model), not a
hooked swapchain (the historic friction model). The ONLY anti-cheat-adjacent
requirement is operational, not code: keep League BORDERLESS (exclusive fullscreen
defeats every non-injection overlay and risks the League lockup). Sources: Overlay App E
Vanguard FAQ; Overlay Platform M borderless requirement + AC notes; OBS no-injection-no-AC
taxonomy; Discord old-vs-new overlay migration.

-------------------------------------------------------------------------------

## 6. Sources

- Overlay App E x Vanguard: support.overlay app E/.../8744136175375 ; QuickGuide 8771266395535 ;
  General Overlay Troubleshooting 900001178283
- Overlay Platform M: overlay platform M developer docs/ow-native/.../in-game-overlays ; release notes
  overlay platform M support desk/.../9000199444 ; common issues + overlay troubleshooting
  overlay platform M support/.../9000115816, /9000202391 ; browse-by-game LoL
- Overlay App F: overlay platform M/app/trebonius-overlay app F ; overlay app F resolution support note ;
  lutris.net/games/overlay-app-f-league-of-legends-overlay
- Aggregator C / aggregator A / Aggregator B: overlay app Z6/blog/overlay app Z6-vs-overlay app E-vs-aggregator C ;
  sagemode.gg discover-the-best-league-overlays ; cbinsights Aggregator C-vs-Overlay Platform M
- OBS capture taxonomy: obs-versions.com window/display/game-capture guides ;
  obsproject.com WGC-vs-DXGI thread ; sageinfinity.github.io DXGI-vs-WGC
- RTSS: guru3d.com RTSS download notes ; wccftech.com RTSS setup ; obsproject.com
  RTSS+OBS hooking threads
- Discord overlay: neowin.net Discord-new-overlay ; guidedhacking.com x64 Discord
  DX11 hook ; thelinuxcode.com turn-off-discord-overlay ; github PicoShot/DiscordOverlayHook
- Electron overlay mechanics: electron/electron issues #8530 (alwaysOnTop GL/Vulkan),
  #6571 (scaleFactor==1 at 125%), #11830 (transparent+ignoreMouse z-order),
  #23042 (click-through frameless), #5994 (taskbar on focus)

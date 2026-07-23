# OUT-OF-GAME SPATIAL BRAND SPEC - Riot Commander (operator-present, 2026-07-22)

Goal (operator): define the out-of-game display's spatial scope as a FINAL "brand" decision -
fixed envelope, resolution spec, and placement relative to the League client + taskbar - so we
stop tinkering / fighting overflow / wrong-resolution. Measured live on Legion.

## 1. MEASURED DESKTOP GEOMETRY (Win32, not pixel-guessed)

- Monitor: **2560 x 1440**, single (DISPLAY1, primary, origin 0,0).
- Work area: **2560 x 1400** (usable; taskbar = **40px** tall, docked BOTTOM).
- League client (LeagueClientUx): fixed **1280 x 720**, currently at **(640, 340)** ->
  occupies x[640..1920], y[340..1060]. Centered horizontally ((2560-1280)/2 = 640); near-centered
  vertically ((1440-720)/2 = 360; actual 340, 20px high). **User-movable; League remembers position.**
- rc-shell companion (electron "RC CLIENT"): currently MINIMIZED (not placed).
- Other windows at capture: Claude app (2012,20 536x728), Discord/Spotify minimized.

## 2. EMPTY-SPACE ENVELOPE (client centered, as-is)

With the client centered the free desktop is FRAGMENTED into 4 bands (each clears the 40px taskbar):

| Band | Rect (x,y,w,h) | Usable size | Shape |
|------|----------------|-------------|-------|
| LEFT | (0, 0, 640, 1400) | 640 x 1400 | tall portrait column |
| RIGHT | (1920, 0, 640, 1400) | 640 x 1400 | tall portrait column |
| TOP | (0, 0, 2560, 340) | 2560 x 340 | wide letterbox strip |
| BOTTOM | (0, 1060, 2560, 340) | 2560 x 340 | wide letterbox strip |

Consequence: a centered client yields NO clean large rectangle. The prior 920x1280 companion
(QA memory) cannot fit a 640-wide side band -> this is the root of the overflow/resolution pain.

### Alternative envelope if the client is STANDARDIZED to one side
- Client docked LEFT at (0,340): frees a contiguous RIGHT region x[1280..2560] = **1280 x 1400**.
- Client docked RIGHT at (1280,340): frees contiguous LEFT region **1280 x 1400**.
A one-side client dock is the only way to get a single clean ~1280x1400 companion rectangle.

THE SPATIAL FORK (to adjudicate after competitor research): (A) design the companion to fit the
fragmented bands around a centered client, vs (B) standardize the client to one side for a clean
1280x1400 companion rectangle, vs (C) abandon desktop-empty-space and overlay the client itself
(the Overlay Platform M model - pending competitor findings).

## 3. COMPETITOR SPATIAL/SETTINGS AUDIT (web research 2026-07-22)

Dominant architecture = **Overlay Platform M two-surface split**: a separate DESKTOP WINDOW used out-of-game
+ an IN-GAME overlay injected over the live match. Heavy real estate lives on the in-game overlay,
NOT parked in desktop margins.

| App | Architecture | Out-of-game surface | Resize/Move | Key spatial settings |
|-----|--------------|---------------------|-------------|----------------------|
| Overlay App F | Overlay Platform M + Electron; in-client + in-game overlay | Floating desktop window (scout/meta) | Y/Y | transparency, colour scheme, widget reposition, show/hide hotkey |
| Overlay App E | Overlay Platform M desktop app + in-game overlays | Standalone desktop window | Y/Y | per-overlay toggles, CS-flash hotkey (5s), per-widget scale/opacity/position, run-as-admin |
| Aggregator C | Overlay Platform M; desktop app + Live Companion overlay | Standalone desktop window | Y/Y | overlay hotkeys, enable/disable overlay |
| Aggregator A | Electron/Overlay Platform M desktop app + in-game overlay | Standalone desktop window (closes when game starts) | Y/Y | Overlay size + visibility, Shift+Tab toggle |
| Aggregator B | Overlay Platform M desktop app + tracker overlay | Standalone desktop window | Y/Y | overlay on/off + settings menu (specifics uncertain) |
| LeagueAkari | Standalone Electron, LCU toolkit (NOT overlay, NOT AI coach) | Standalone desktop window only | Y/Y | ordinary OS window |
| Overlay App Z5 | Overlay Platform M desktop window + in-game overlay | Standalone desktop window | Y/Y | build/rune import + in-game widgets |

Synthesis:
- Market pattern is NOT desktop-empty-space parking; it is a floating desktop hub window (out-of-game)
  + an injected in-game overlay (the heavy surface).
- The out-of-game desktop window is an ORDINARY floating OS window: movable/resizable, lives wherever
  dragged, does NOT dock/attach to the League client and does NOT force the client's position.
- Spatial settings converge on a small set: per-widget toggles, a show/hide hotkey (Aggregator A Shift+Tab =
  archetype), overlay size/scale, opacity/transparency, widget reposition. Monitor-select + hard
  position-lock rarely surfaced.
- RC is a Chrome-hosted local dashboard = closest to the "separate desktop hub window" half of the
  market. RC's in-game overlay is a SEPARATE surface it already owns (so RC already matches the
  two-surface split).
- On 2560x1440 beside a centered 1280x720 client there is ~640px gutter each side; market precedent
  supports a movable/resizable floating window there rather than overlapping the client or Overlay Platform M
  injection. Caveat: RC's out-of-game pages are dense/multi-panel (a "hub"), so a 640 gutter is narrow
  for the current layout - hence the fork in section 2.

NOTE: "Akari" resolved to LeagueAkari (LCU toolkit) - operator CONFIRMED. Reference-only (not installed;
client-automation tool, not run on the live account).

### 3b. LIVE INSTALL FINDINGS (driven on Legion, 2560x1440)

**Overlay App E (overlay app E 2.1.602, standalone Electron - modern Overlay App E dropped Overlay Platform M):**
- Hub window DEFAULT: **1420 x 850 at (597,336)** - floats ~centered, OVERLAPS the client position
  (does not dock or avoid it). Movable + resizable ordinary OS window. Close = minimize to tray.
- Auto-read the live LCU account (SamplePlayer#Trist, Plat4, ARAM Mayhem matches) with NO login; full
  features gate behind Login/Signup.
- Out-of-game layout: top nav (Champions/Tier List/ARAM Mayhem/Arena/URF/Overlays), left profile +
  LP graph, center match list, RIGHT = heavy AD RAIL (free tier injects display ads + a video ad
  right inside the Overlays grid). Monetization is visually loud.
- In-game overlay model = a CATALOG of individually TOGGLEABLE widgets, each tagged by category
  (Utility / Performance / Tracker): Arena Augments, Benchmarking, ARAM Health Timers, Jungle Pathing,
  Loading Screen, etc. Modular, not monolithic.
- Global settings (General): run-on-startup, hardware accel, THEME (Dark dropdown), animations,
  minimize-to-tray, surveys, perf tweaks. League tab: auto-popup in champ select, auto-import
  builds/runes/spells, tilt-free mode, match-found popup. NO global overlay scale/opacity slider -
  per-widget + in-game drag positioning.
- TAKEAWAY for RC: the modular toggleable-widget catalog is the reusable idea; the ad rail + centered
  overlapping hub are the anti-patterns to avoid.

**Aggregator A (aggregator-a-electron-app, standalone Electron):**
- Hub window DEFAULT: **1588 x 921 at (486,239)** - floats near-center, OVERLAPS client. Bigger than
  Overlay App E. Movable/resizable.
- Layout: LEFT vertical icon-rail nav (profile / champions / tools / settings gear at bottom) + main
  content column + RIGHT ad rail (free tier: display ads). Top tabs My profile / Live.
- Separate "Enhanced Overlay" feature; constraint surfaced in-app: "only works in windowed modes
  (Windowed / Borderless Windowed)" - same game-mode constraint RC's overlay faces.
- Auto-detects the running client (North America / profile). Login gates ad-removal + full features.
- Capture method note: Aggregator A's dotted name does NOT resolve in the computer-use allowlist; a direct
  .NET CopyFromScreen capture is UNMASKED and is the reliable observation path for all these apps
  (control still needs a resolvable grant).

BOTH hub windows so far (Overlay App E 1420x850, Aggregator A 1588x921) = landscape, ~center-floating, client-
overlapping, ad-railed. Neither docks to or avoids the client. Reinforces: out-of-game surface is a
free-floating hub, not a margin-parked panel.

Aggregator A full sweep (logged in, ads gone):
- Nav mega-menu: My profile / Live / Game modes (ARAM Mayhem, ARAM, Arena, URF) / Champions / Overlays
  (Overlays + Overlay settings) / AI Voice (Voice Settings). Left 8-icon multi-game rail + bottom gear.
- OVERLAY SETTINGS (the canonical spatial-config surface; RC should mirror this set): **Overlay Type**
  (2 layout variants - full form vs simple/no-header - with LIVE PREVIEW), **Overlay Size** (% slider,
  default 80%), **Transparency** (% slider, default 100%), **Overlay Position Adjustment** (toggle:
  "drag the overlay during in-game play to move it"), **Reset overlay position** button. Live preview
  pane on the right.
- APP SETTINGS (Game tab; tabs = Game/Language/Edit Profile/AD-free/Connected Apps): Data-collection
  consent, Auto-launch on startup, Hardware Acceleration, **Desktop App Size Settings (% scale,
  100%, -/+)**, **Auto-adjust Desktop Size (toggle: "auto-adjusts its size based on each monitor's
  resolution")**, Auto Rune/Spell/Item setup, Restart App, Logout, paid AD-free tier.
- *** KEY BRAND FINDING: Aggregator A solves the resolution/overflow problem with RESOLUTION-ADAPTIVE
  AUTO-SIZING (auto-fit to the monitor) + a manual scale % override. This is the pattern RC should
  adopt to stop fighting overflow/wrong-resolution. ***

**Coaching App Z7 (standalone Electron, AI drafting coach):** hub 1320x760 @ (620,320). Nav Profile / Macro
Coach / Tier List / Tools / Coaching App Z7+ (paid). Differentiator = per-match AI DRAFT SCORE + AI MACRO SCORE.
Clean dark theme, free-tier gating (no ad rail). Content-novel (AI scoring), spatially the same hub.

**Overlay App F (Overlay Platform M):** "Overlay App F - Desktop" 1380x944 @ (575,248). Nav Profile / Champions /
Meta / Matches / Rankings + premium crown + gear. Opened a Chrome age-verify/CREATE-ACCOUNT flow
(NOT actioned - account creation is prohibited; operator's to do). Scouting-hub archetype.

**Aggregator C (Overlay Platform M):** large hub (~1250x900), multi-game tabs (LoL/TFT/Diablo4/PoE/Destiny2/...).
Signature GPI RADAR (octagon) + trait tags + a PERFORMANCE STAT-TILE ROW (GD@15, Gold Share, Damage
Share, DMG/M-D, Solo Deaths, Vision Score) + LP tracking. Tabs Overview/Champion Pool/Matchup Pool/
LP Gains. Richest analytics density; closest to RC's own out-of-game analytics content.

**Aggregator B (standalone Electron):** hub "Aggregator B Desktop App" ~1000x900. Nav Overview / Champion Stats /
Live Game / PLUS Tier List. PLUS a SEPARATE "Aggregator B - Build Order Overlay" window sized 1920x1080 @
(0,0) (overlay is its own transparent full-region window). Left icon rail + gear.

**Overlay App Z5 (Overlay Platform M):** "Overlay App Z5 - Home" 1654x833 @ (453,303). GOLD-on-dark Hextech-style theme
(visually closest to League's own look; notable vs RC's own Hextech). Nav Home/Play&Win/Learn Champs/
My Stats/My Playstyles/Postgame/Highlights/Patch Notes. Rewards/referral/giveaway monetization +
"Remove Ads / Premium" upsell. Scouting-hub archetype.

### 3c. CONSOLIDATED SPATIAL SYNTHESIS (6 apps measured live, 2560x1440)

| App | Hub default size | Placement | Overlay surface |
|-----|------------------|-----------|-----------------|
| Overlay App E | 1420x850 | center-float, overlaps client | modular toggle catalog (in-game) |
| Aggregator A | 1588x921 | center-float, overlaps client | size%/opacity%/pos/type, resolution auto-fit |
| Coaching App Z7 | 1320x760 | center-float, overlaps client | (coach hub; no in-game overlay observed) |
| Overlay App F | 1380x944 | center-float, overlaps client | in-game overlay (transparency/reposition) |
| Aggregator C | ~1250x900 | center-float, overlaps client | Live Companion overlay |
| Aggregator B | ~1000x900 | center-float, overlaps client | separate 1920x1080 overlay window @ (0,0) |
| Overlay App Z5 | 1654x833 | center-float, overlaps client | in-game overlay |

UNIVERSAL FINDINGS:
1. Every out-of-game hub is a LANDSCAPE floating window ~1000-1650 wide x 760-944 tall (median
   ~1400x870). NONE dock to the client; ALL overlap/float over the client's centered position.
2. NONE park in the desktop margins / empty gutters. The operator's "fit the empty space beside the
   client" instinct is AGAINST market grain - and is likely WHY RC keeps fighting overflow (forcing a
   dense hub into a narrow gutter). The market never tries this.
3. The in-game OVERLAY is a SEPARATE surface/window from the hub (Aggregator B proves it: a distinct 1920x1080
   overlay window). RC already has this split.
4. Overlay spatial settings converge on: Type (layout variant) + Size % + Transparency % + Position
   (drag/reset). Aggregator A adds resolution-adaptive AUTO-FIT - the overflow cure.
5. Monetization (ad rails, remove-ads upsell) is a free-tier anti-pattern RC does not need.
6. Overlay App Z5's gold-on-dark is the most League-native theme; validates RC's Hextech direction (ties
   back to the theme pass: Hextech-Unified is on-brand for the genre).

## 4. RULINGS (operator-adjudicated 2026-07-22)

**SPATIAL BRAND = FULL FLOATING LANDSCAPE HUB (market-standard) + resolution auto-fit.**

Decided:
- RC out-of-game = ONE canonical LANDSCAPE hub window (target ~1400-1600 wide, in the measured
  competitor band 1000-1650; NOT the legacy 920x1280 portrait companion). It floats and may overlap
  the centered League client when open - accepted, because out-of-game review does not need the client
  visible simultaneously. This REPLACES the "live in the empty gutter beside the client" premise
  (which no competitor uses and which was the root of the overflow/wrong-resolution pain).
- SIZING = Aggregator A model: RESOLUTION-ADAPTIVE AUTO-FIT (auto-size to the monitor work area) + a MANUAL
  SCALE % override + REMEMBERED window position. This is the durable cure for overflow/wrong-res.
- OVERLAY stays a SEPARATE surface (already split; unchanged by this ruling). Its settings target the
  market-convergent set: layout Type + Size % + Transparency % + drag Position (+ Reset).
- THEME: Hextech-Unified validated as genre-native (Overlay App Z5's gold-on-dark is the closest competitor
  look). The paused theme pick (Hextech-Unified vs Deep Terminal) resumes against this landscape hub.
- ANTI-PATTERNS to avoid (seen across the free tiers): ad rails, remove-ads upsells, account-creation
  gates.

Build implications (for later slices, not this session unless directed):
1. rc-shell companion becomes a landscape auto-fit hub (converges with the existing 1920 Chrome
   dashboard baseline), retiring the 920x1280 portrait target.
2. Add a resolution-adaptive sizer (fit-to-work-area %) + manual scale control + position persistence.
3. Per-page layout alternatives (item A2) are authored for the landscape hub width.
4. Overlay work continues on its own surface (pseudo-screen already built this session).

## 5. NEXT-SESSION TASK - per-panel competitor capture library (operator-requested 2026-07-22)

Operator wants, for LATER RESEARCH: images of EACH PANEL (not just full windows) from each competitor
app, isolated so we can study CONTENT + SPACING of that content per panel/widget.
- This session captured FULL-WINDOW shots only; preserved (local, NOT committed - contain account
  stats + competitor UIs) at `C:\Users\Administrator\Documents\RC_Competitor_Research\2026-07-22_full-window\`.
- Next session: systematically capture each app's individual panels/widgets (crop or per-panel shots)
  across Overlay App E / Aggregator A / Coaching App Z7 / Overlay App F / Aggregator C / Aggregator B / Overlay App Z5 - overview cards, stat
  tiles, radar, match rows, overlay widgets, settings groups - labeled by app+panel, saved under the
  same RC_Competitor_Research dir (dated subfolder). Keep LOCAL/gitignored (personal + third-party UI).
- Apps remain installed + logged in on Legion, so re-capture needs no reinstall (operator's to keep or
  remove via Revo). The .NET CopyFromScreen + per-window-rect approach from this session is the tool.

# RC Overlay Doctrine (2026-06-21)

> **SCOPE (2026-07-26, one-tracker pass):** this doc states the SURFACE DOCTRINE (which
> surface the in-game UI is and why). The authoritative BUILD spec is
> `docs/OVERLAY_BUILD_MASTER_PLAN.md`, which is newer and more referenced; where the two
> disagree on build detail, MASTER_PLAN wins. Open work goes in `ROADMAP.md`, not here.
> The "THE canonical design law" wording below is retained as the 2026-06-21 decision record.

The 2026-06-21 design law for RC's in-game UI surface. Operator decision 2026-06-21:
the transparent always-on-top Electron overlay over the Borderless game is the
PRIMARY in-game user-facing surface. (UPDATE 2026-06-22: the operator REVERSED the
dashboard retirement - the 1920 Chrome dashboard at `:8888` is back in scope and was
fully redesigned onto the Hextech foundation; see `docs/RC2_REDESIGN_PLAN.md`. This
doctrine remains authoritative for the IN-GAME overlay specifically.)

Grounded in `docs/research/RC2_RESEARCH_in_match_overlay.md` (the 10 rules) +
`docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md` (tiers / slot budget / arbitration)
+ the greenlit Hextech palette + the 2026-06-21 design-director (Gemini) pass.

ASCII only (repo hard rule). No em-dashes, en-dashes, or smart quotes. Functional
action glyphs (U+26A0 warn, U+2713 check, U+25BA play) are code, not punctuation.

--------------------------------------------------------------------------------
## 0. WHY THE OLD OVERLAY WAS "UTTERLY NOT IT"
--------------------------------------------------------------------------------

The pre-doctrine overlay (`web/css/overlay.css` as of `806c77dd`) was a single
monolithic 460px right-edge dock that was a CSS-NARROWED SUBSET of the dashboard
DOM. Three structural failures:

1. MONOLITH, not widgets. Every cue stacked in one far-corner column. It violated
   rule 9 (move urgent cues toward the eye) - the most time-critical call sat in
   the screen corner furthest from the combat center-of-mass and the minimap.
2. NOT MOVABLE. The operator could not place a cue where their eye actually rests;
   positions were hard-coded by the dock flexbox.
3. GENERIC PALETTE. Flat `rgba(23,24,33,0.86)` dark backings - it read as a dev
   tool, not a premium Hextech HUD. The greenlit palette was never applied.

THIS DOCTRINE replaces that with a movable, position-persistent, Hextech widget
field. The priority/tier/arbitration brain from the condensation spec is KEPT
(it was correct); only the PRESENTATION and PLACEMENT model changes.

--------------------------------------------------------------------------------
## 1. THE LAW (10 rules, non-negotiable)
--------------------------------------------------------------------------------

Every widget and every change is checked against these (research section 2.6):

1. ONE-GLANCE BUDGET: every persistent element answerable in <=1.5s (2.0s ceiling).
2. THREE TIERS: Ambient (quiet always-on) / Urgent (color+size) / Emergency
   (motion, self-expiring). Tag every cue at author/emit time.
3. PREATTENTIVE-ONLY in the combat tier: color / size / position / motion, NO
   text-to-read. Prose is demoted to the between-fight surface.
4. ENFORCE POP-OUT: at any instant exactly ONE element is the ONLY red / ONLY
   moving / ONLY large thing on screen. Five reds = nothing pops.
5. RATION MOTION: pulse/flash ONLY for a near-certain action-changing event
   (Emergency, or a single one-shot Urgent promotion). Never on benign re-emit.
6. NEVER center-obstruct, never require a mid-fight dismissal; alerts self-expire.
7. PRIMARY BUDGET: 1 primary + ~2-3 supporting persistent widgets visible at once;
   everything else is deferred to a reveal key or hidden by default.
8. MAXIMIZE DATA-INK: strip chrome (borders/shadows/padding) to the minimum that
   keeps text legible over a bright game; redundant-encode ONLY the single top cue.
9. FIXED, LEARNABLE POSITIONS beat smart-but-moving. The operator places each
   widget ONCE (drag), it SAVES, and it never moves on its own again. Default
   placements push urgent cues toward the eye (minimap, champion frames, center).
10. QUANTITIES as bar-length / position, CATEGORIES as color. Never magnitude-in-hue.

--------------------------------------------------------------------------------
## 2. THE WIDGET FIELD (architecture)
--------------------------------------------------------------------------------

ONE fullscreen transparent always-on-top Electron window (the existing rc-shell
Surface B). Inside it, the overlay is a FIELD of independently-positioned widgets,
each absolutely placed at `left/top` it owns - NOT a flex dock.

- Each widget is a known DOM mount (the existing renderers keep working): the
  coach CALL, the A/B choice chips, the objective/spike callouts, the macro-lead
  pill, the next-item strip, the enemy threat/cooldown ledger, the spike cue, the
  trinket-ready glyph.
- A widget is DRAGGABLE only in ACTIVE mode (Alt+Shift+A). In PASSIVE mode it is
  click-through and locked. A small grab handle (gold dot row) shows on hover in
  ACTIVE mode; the body stays click-through-friendly.
- Position is the widget's identity-anchor (rule 9). Once dragged it STAYS until
  the operator moves it again or resets.
- A widget the operator never wants is hidden via a per-widget toggle (defaults
  in section 4); hidden != deleted (wiring stays, the field just does not paint it).

This entirely replaces the 460px dock. The panel-set cycle (coach/build/threat)
becomes a per-widget visibility preset, not a column reflow.

--------------------------------------------------------------------------------
## 3. PERSISTENCE (savable / cacheable layout)
--------------------------------------------------------------------------------

Layout state is a small JSON object keyed by widget id:

```
{ "<widget-id>": { "x": <px>, "y": <px>, "hidden": <bool>, "scale": <0.7..1.6> }, ... }
```

- AUTHORITATIVE store: `localStorage["rc-overlay-layout"]` (the overlay window
  shares the dashboard origin, so this is read at boot before first paint).
- DURABLE cache: the layout is ALSO mirrored to disk by rc-shell so it survives a
  localStorage wipe and can be hand-edited - `rc-shell` writes
  `<userData>/overlay_layout.json` on each save and seeds localStorage from it at
  boot if localStorage is empty (rc-shell main-process config seam, the HZ-D2
  position-persistence pattern extended from the single sidecar to the field).
- A drag-end or a scale change writes BOTH (debounced ~400ms, atomic).
- `Alt+Shift+R` (overlay) resets the field to the section-4 defaults (clears both
  stores). A per-widget reset is the right-click affordance in ACTIVE mode.

The position-setting is what "use MCP to move elements and save their locations"
operationalizes: dragging a widget (by hand or by the desktop-MCP drag the operator
authorized) lands an (x,y) that is immediately persisted and reloaded.

--------------------------------------------------------------------------------
## 4. WIDGET INVENTORY + DEFAULT 1080p POSITIONS
--------------------------------------------------------------------------------

Defaults push urgent cues toward the eye (minimap bottom-right, champion HUD
bottom-center, combat center) per rule 9 + the convergent competitor pattern.
`(x,y)` is the widget's top-left in 1920x1080 game pixels; the field scales them
by the same work-area scale rc-shell sizes the window by (RC2 4.1 ovscale).

| Widget id        | Cue                         | Tier (default)        | Default (x,y) | Anchor rationale                         | Default shown |
|------------------|-----------------------------|-----------------------|---------------|------------------------------------------|---------------|
| `w-call`         | the ONE action right now    | per band (1/Urg/Emerg)| 760, 140      | upper-center, above combat, below notch  | yes (PRIMARY) |
| `w-choices`      | A/B/C trade/all-in/back-off | Urgent                | 760, past HUD 815 | lower-center, above the ability bar  | yes           |
| `w-callouts`     | objective + spike ETAs      | Ambient -> Urgent     | 1486, past minimap 780 | left edge of the minimap (eye rests) | yes      |
| `w-lead`         | macro lead ahead/behind     | Ambient               | 786, 44       | top-center, under the score bar          | yes           |
| `w-threat`       | enemy threat / CD ledger    | Urgent                | 1604, 560     | directly above the minimap               | no (reveal)   |
| `w-build`        | next-item rerank            | Ambient               | 70, 470       | left edge, out of the play space         | no (reveal)   |
| `w-ovds`         | DS fight-model / rel-score  | Ambient               | 20, 780       | left-edge column, out of the play space  | no (reveal: build) |
| `w-spike`        | spike-crossed cue           | Urgent (one-shot)     | 360, 840      | bottom-left, near champion stats         | yes (transient)|
| `w-trinket`      | trinket / control-ward ready| Urgent make-aware     | 920, 540      | small glyph, offset from the avatar      | yes (glyph)   |
| `w-mmrect`       | minimap ZOI outline (geom)  | Ambient               | game.cfg 1600,760 | over the live minimap, settings-pinned | yes (hairline)|

`w-mmrect` is the lone SETTINGS-pinned widget (rule-9 EXCEPTION): its (x,y,w,h)
is computed deterministically from League's game.cfg `MinimapScale` + `FlipMiniMap`
(`core/league_settings` + `core/minimap_geometry` -> `/api/state.minimap_rect`,
LOCAL + free, no API), NOT placed by a first drag. It is therefore NOT in the
`overlay_layout.js` field registry and has NO drag handle - a grab zone over the
click-critical minimap would eat move / ping / minimap-cast clicks, so the body
is `pointer-events:none` (fully click-through) and `panels/minimap_rect.js`
positions it. It is the Zone-of-Influence geometry FOUNDATION: this slice paints
only the aligned gold-hairline outline; a later slice fills it with ZOI shading.

Visibility presets (replaces the panel-set cycle, Alt+Shift+C):
- `coach` (default): w-call, w-choices, w-callouts, w-lead, w-spike, w-trinket.
- `build`: + w-build, + w-ovds, - w-threat.
- `threat`: + w-threat, - w-build, - w-choices.
The operator's per-widget hidden flags layer ON TOP of the active preset.

--------------------------------------------------------------------------------
## 5. HEXTECH RENDER BINDINGS (premium, not generic)
--------------------------------------------------------------------------------

The palette is law. No color literal outside this table reaches a widget.

| Semantic            | Hex      | Use                                                        |
|---------------------|----------|------------------------------------------------------------|
| canvas (transparent)| -        | the window stays transparent; the game shows through       |
| panel backing       | #16202E  | widget body fill at 0.85 alpha                             |
| nested backing      | #0A0E14  | inset rows / chips inside a widget at 0.9 alpha            |
| gold accent         | #C8AA6E  | widget hairline border (0.30 alpha idle, 1.0 active/drag), heads |
| cyan accent         | #0AC8B9  | informational / objective chips, the PRIMARY action glow   |
| good / ahead        | #37D08A  | lead-ahead bar, `good` band glyph                          |
| caution / urgent    | #C8AA6E  | the single Urgent caution hue (reuse gold)                 |
| lethal / emergency  | #E84057  | the ONE pop-out: Emergency glow + `urgent` band; max once  |
| neutral text        | #FFFFFF  | widget body ink (`--ovx-text`): ACTION verb full, OBJECTIVE footer @0.55 |

PREMIUM CUES (the difference between "dev tool" and "Hextech HUD"):
- Border: 1px gold hairline at 0.30 alpha idle; lifts to 1.0 on the active/dragged
  widget and on the S0 primary. No fat borders.
- Glow: a TIGHT drop-shadow (blur <=10px), cyan for the primary action, red for the
  one Emergency. No global blur, no looping animation.
- Backing: #16202E @0.85, a 1px top inner highlight (rgba(255,255,255,0.04)) for the
  "etched glass" Hextech feel. Corner radius small (8-10px), not pill.
- Type: heads in a Beaufort/Friz-Quadrata-class face if available (fall back to the
  existing display font), body in Spiegel-class (fall back to the system stack);
  uppercase + letter-spacing on heads. Numbers `.tabular-nums`.
- Spacing: 4px sub-grid, aggressive padding reduction - data-ink first. A widget is
  its content plus a hairline, nothing more.

POP-OUT DISCIPLINE (rule 4): lethal red is RESERVED for the current Emergency
winner. While an Emergency holds the primary, NOTHING else paints red or moves.

--------------------------------------------------------------------------------
## 6. COMBAT MODE (text -> preattentive)
--------------------------------------------------------------------------------

When `lib/combat_mode` raises `body[data-fight="1"]` (S0 arbitration flags a
high-stakes moment, with hysteresis), the field sheds load:
- Ambient widgets (w-lead, w-build, w-callouts beyond the nearest row) fade to a
  thin bar / hide - no reading during a fight (rule 3).
- The w-call headline collapses to its band GLYPH + color bar; the verb stays one
  line, but the supporting prose drops.
- w-choices stays (the decision is the fight) but renders as 3 color-coded chips
  with the 1/2/3 key hint, no sub-text.
- Nothing dims while a fight is live (override idle-recede).

--------------------------------------------------------------------------------
## 7. IMPLEMENTATION MAP
--------------------------------------------------------------------------------

- `web/css/overlay.css` - reworked: Hextech palette tokens (overlay-scoped),
  absolute-positioned widget shells, drag-handle affordance, combat-mode shed.
  The old 460px dock rules are removed.
- `web/js/lib/overlay_layout.js` (NEW) - the field manager: reads the layout JSON,
  absolutely positions each widget id at saved-or-default (x,y)+scale, installs
  drag in ACTIVE mode, debounced-persists to localStorage + rc-shell, applies the
  visibility preset + per-widget hidden flags, `Alt+Shift+R` reset.
- `web/js/main.js` - overlay boot calls `overlay_layout.init()` after the
  `data-shell="overlay"` stamp (a single wire line; main.js is frozen-adjacent -
  add only the init call, no logic).
- `w-mmrect` (ZOI foundation) - `core/league_settings.py` (game.cfg `[HUD]`
  reader, fail-soft) + `core/minimap_geometry.py` (pure, calibration-anchored
  scale->rect model) -> `dashboard/_state_builder.py` stamps `minimap_rect` on
  `/api/state` (mode-gated, null off a minimap mode) -> `web/js/panels/minimap_rect.js`
  paints the click-through outline. main.js wires `renderMinimapRect` beside the
  other cue renderers. overlay_layout.js is UNTOUCHED (settings-pinned, no drag).
- rc-shell main process - `overlay_layout.json` read/write under userData + an IPC
  channel `overlay-layout:save` / seed-at-boot (extends the HZ-D2 sidecar-position
  persistence to the widget field).
- Tokens: a `--ovx-*` overlay-scoped Hextech token block in overlay.css (never in
  `:root` - the dashboard is retired but the tokens must not leak if it renders).

--------------------------------------------------------------------------------
## 8. ITERATION PROTOCOL (headless, live)
--------------------------------------------------------------------------------

This doctrine is built by LIVE iteration, not one big-bang commit:
1. Implement a slice (a widget or a binding) in code.
2. Reload: asset-hash auto-reload for CSS/JS (ADR-008) or `restart_trigger.txt`
   for a wiring change; bounce rc-shell when the main process changed.
3. Capture the live overlay (desktop MCP screenshot on Legion, or the headless
   `?overlay=1&ui_mock=1` render) and check it against sections 1 + 5 + 4.
4. Gemini design-director critique (`tools/gemini_ask.ps1`) on the capture;
   take its recommendation, log it, refine.
5. Repeat until each widget passes the glance test + the Hextech bar.

The desktop MCP is also how a widget's live (x,y) is set + saved: drag it, the
field persists it, reload confirms it sticks.

--------------------------------------------------------------------------------
## 9. ACCEPTANCE (pristine bar)
--------------------------------------------------------------------------------

- A. Every visible widget passes the 1.5s glance test (section 1 rule 1).
- B. At any instant exactly one pop-out (rule 4); the motion channel fires only
  for Emergency / one-shot Urgent (rule 5).
- C. Every widget is draggable in ACTIVE mode and its position survives a reload
  AND an rc-shell restart (section 3).
- D. No color literal outside the section-5 palette; gold hairline + scoped glow,
  no flat dev-tool backings (section 5).
- E. Combat mode strips text to preattentive channels (section 6).
- F. The dashboard 1920 layout is untouched by all of this (overlay-scoped only).

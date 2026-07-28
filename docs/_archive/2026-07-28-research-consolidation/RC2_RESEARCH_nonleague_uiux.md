# RC 2.0 Phase-1 Research - Non-League UI/UX + Design-Language References

Stage 1.9. Grounded, cited survey of transferable design language from OUTSIDE
League of Legends: glanceable HUD/heads-up design, dark operational dashboards,
trading-terminal density, modern design systems, micro-interaction/motion, dark
color theory, and accessibility/contrast. Every external claim carries a URL.
ASCII only (repo hard rule: no em-dashes, en-dashes, or smart quotes).

Authored 2026-06-19. Scope: research only. This doc edits nothing else.

---

## 0. RC's current design-token system (ground truth)

Read from the repo before surveying anything external, so each LIFT verdict is
measured against what RC actually has today.

Two CSS layers, intentionally additive (do NOT conflate them):

1. **Primitives / base palette** - `web/css/panels/base.css` owns the original
   chrome tokens consumed everywhere: `--good`, `--bad`, `--gold`, `--surface`,
   `--surface-2`, `--surface-alt`, `--surface-head`, `--text`, `--text-dim`,
   `--radius-sm`, `--shadow-card`, plus the `*-soft` tints
   (`--good-soft` / `--gold-soft` / `--bad-soft`). Confirmed in use at
   `web/css/panels/primitives.css:26,41,107-109,135`.
2. **Semantic token layer** - `web/css/tokens.css` (the file the operator
   flagged). ADDITIVE, opt-in per panel. Groups:
   - Semantic colors: `--signal-good #6ec977` / `--signal-warn #f1b04a` /
     `--signal-bad #ff5050` / `--signal-dim` / `--signal-info` / `--signal-gold`
     plus `-soft` rgba variants (`tokens.css:31-39`).
   - Font scale, 7 tiers: `--fs-xs 16px` .. `--fs-display 46px`
     (`tokens.css:49-55`). Floors per `feedback_font_size_viewing_distance.md`.
   - 8px spacing grid, 8 rungs `--space-1 4px` .. `--space-8 48px`
     (`tokens.css:64-71`).
   - Panel chrome: `--panel-padding`, `--panel-radius 18px`,
     `--panel-gap` (`tokens.css:79-85`).
   - Interaction: `--hit-min 42px`, `--focus-ring`, `--tooltip-*`
     (`tokens.css:91-95`).
   - Fresh-update pulse: `--pulse-good/warn/bad` box-shadow glows
     (`tokens.css:100-102`) + the `@keyframes coach-pulse-good/warn/bad`
     (`tokens.css:114-125`).
   - `.tabular-nums` utility class (`tokens.css:108`).

**What RC already does well (so we do not re-pitch it):**
- Semantic status triad (good/warn/danger) exists in BOTH layers.
- Tabular numbers utility exists (`tokens.css:108`) and is used live in
  `web/legacy_index.html` (~15 sites) and `primitives.css:105,120`.
- A fresh-update glow affordance exists and is wired:
  `web/css/panels/right_now.css:40-42` applies `coach-pulse-*` at **0.8s**
  ease-in-out (note: the tokens.css comment says 1.2s; the live consumer is
  0.8s - a doc/code drift worth a one-line fix).
- Overlay has its own edge-pulse mirror `ov-pulse-edge`
  (`web/css/overlay.css:273-279`, 1.2s one-shot).
- Surface tones exist (`--surface`, `--surface-2`, `--surface-alt`,
  `--surface-head`) - a partial tonal-elevation vocabulary.

**The biggest gaps (preview of the HIGH-lift findings):**
- `prefers-reduced-motion` is honored in exactly ONE panel
  (`web/css/panels/input_activity.css:473`). ~12 other animated panels
  (item_build, map_state, grid, right_now, overlay, home ...) do NOT branch on
  it. This is an accessibility + polish gap with a near-zero-cost fix.
- No formalized two-tier (primitive -> alias) contract: the two layers coexist
  but panels reference a mix of `--good` and `--signal-good` ad hoc.
- Status is encoded by COLOR ALONE in most panels (no redundant shape/glyph),
  which fails WCAG 1.4.1 and red-green color blindness.

---

## How to read each finding

Every pattern below uses the 6-point LIFT checklist:

- **WHAT** - the pattern in one line.
- **HOW** - the mechanism / technique.
- **RC HAVE?** - does RC already have it (grep result, cite file:line).
- **WHERE** - where it would integrate in RC.
- **EFFORT+RISK** - rough cost and blast radius.
- **LIFT** - HIGH / MED / LOW verdict (HIGH = high value, low cost, do it).

---

## Section A - Glanceable HUD / heads-up design

### A1. Sim-racing shift lights: progressive peripheral encoding

- **WHAT** - Encode a time-critical value as a segmented color-zoned meter
  (green -> yellow -> red fill) read in peripheral vision, not as a precise
  number. A building sequence lets the user anticipate; a single binary flash
  causes a panic reaction.
- **HOW** - Sim shift lights cap at ~5-7 segments ("the most you can comfortably
  distinguish in your peripheral vision") and reserve a distinct blink for the
  redline act-now state. The fill RATE alone communicates urgency.
- **RC HAVE?** - Partial. RC has spike/cooldown curve panels
  (`web/css/panels/spike_curve.css`, `cooldown_watch.css`) but they render as
  charts, not glanceable zoned bars. No 5-7-segment peripheral meter exists.
  No grep hit for a segmented gauge primitive.
- **WHERE** - Objective-spawn timers (drake/baron), recall windows, and power-
  spike countdowns in the overlay (`web/css/overlay.css`) and the `right_now` /
  `next` panels. A horizontal segmented bar filling toward a threshold.
- **EFFORT+RISK** - MED. New CSS primitive (a fl-grid of N segments, each tinted
  by a JS-set `--fill` ratio). No backend change; data already exists. Low risk
  (additive panel).
- **LIFT - MED.** Strong glanceability win for timers, but it is net-new UI, not
  a token tweak. Best slotted into the overlay redesign, not a quick pass.
- Cite: Ecliptech Shift-I, https://ecliptech.com.au/shift-i/

### A2. Aviation HUD: declutter-as-a-mode (conformal symbology)

- **WHAT** - A "fight mode" that automatically strips the overlay to the single
  act-now cue during high-stakes moments, the way a HUD auto-declutters at an
  unusual attitude and retains only recovery-critical info.
- **HOW** - FAA AC 25-11B sec 5.10.3: clutter "causes increased flightcrew
  processing time"; include a graphic element "only if it adds useful
  information content [or] reduces interpretation time." Conformal symbology
  "should not obscure or significantly hinder" detection of the real-world scene
  (treat the live game as the outside scene). Use narrow, sharp, halo-free
  marks; minimize transparency overlap.
- **RC HAVE?** - No. The overlay (`web/css/overlay.css`) renders a fixed layout;
  there is no grep hit for a state-driven "declutter" / "fight" mode. Overlay
  has `box-shadow:none` discipline already (`overlay.css:68,138`) which is the
  right instinct.
- **WHERE** - Overlay state machine. A `body.fight` (or `.combat`) class that
  hides non-essential bands via CSS, surfacing only the danger cue + the one
  action. Driven by existing combat-trigger detection.
- **EFFORT+RISK** - MED. CSS is cheap (a class toggling display); the gating
  logic needs a clean "in a fight" signal from the game reader. Risk: a
  mis-fired mode that hides info mid-fight - needs a conservative trigger.
- **LIFT - MED.** High glanceability payoff and directly on-brief
  ("non-distracting"), but depends on a reliable combat trigger.
- Cite: FAA AC 25-11B, Electronic Flight Displays,
  https://www.faa.gov/documentlibrary/media/advisory_circular/ac_25-11b.pdf

### A3. Apple Watch complications: fixed tile templates, ring gauges

- **WHAT** - Constrain panels to a small set of fixed tile TEMPLATES
  (ring-gauge / single-big-number / sparkline) rather than free-form layouts.
  Constraint is the feature: it forces a sub-second read.
- **HOW** - Apple HIG: complications "deliver essential information instantly"
  with no interaction; gauge/ring styles suit "current values within a range."
  Pre-constrained families (Circular, Graphic, Corner) remove layout guesswork.
  Color "is not the only differentiator."
- **RC HAVE?** - Partial. RC has a `cost-tile` pattern
  (`primitives.css:104-109`) and a 7-tier font scale that already supports a
  "big number" tile (`--fs-stat`, `--fs-display`). No ring/arc gauge primitive
  (no grep hit for `conic-gradient` gauge).
- **WHERE** - A bounded-value ring (HP %, CS-vs-benchmark, gold diff) using a
  pure-CSS `conic-gradient` donut. Slots into `home`, `op_score`,
  `player_gpi` tile grids.
- **EFFORT+RISK** - LOW-MED. A `conic-gradient(var(--good) <pct>, var(--surface-2)
  0)` donut is ~15 lines of CSS + one JS var write. Additive, low risk.
- **LIFT - MED.** A clean, cheap glanceable primitive RC lacks; pairs with A1.
- Cite: Apple HIG - Complications,
  https://developer.apple.com/design/human-interface-guidelines/complications/

### A4. Automotive cluster: always-visible core vs contextual band

- **WHAT** - Split the surface into a tiny ALWAYS-ON core (1-2 values) and a
  CONTEXTUAL band that surfaces detail only in its relevant phase. The car
  cluster shows only speed + charge always; nav/ADAS appear on demand.
- **HOW** - The cluster's power "stems from peripheral vision, alerting drivers
  even when not looking directly at it," but "must balance drawing attention
  with distraction." Designers pick context-driven layouts over 40 configurable
  ones ("design over configuration").
- **RC HAVE?** - Partial. RC already routes views by game phase
  (champ_select / active_match / pgr_* panels exist as separate views). But
  within the live overlay there is no explicit always-on-core vs contextual-band
  split; it is one fixed layout.
- **WHERE** - Overlay layout. Define a permanent core (top action +
  danger/HP) and a contextual band that swaps content by phase (laning ->
  objective -> teamfight). Reuses A2's state machine.
- **EFFORT+RISK** - MED. Layout refactor of the overlay; no data change. Risk:
  moderate (touches the live overlay the operator watches mid-game).
- **LIFT - MED.** Principled overlay structure; bundle with A2/A4 into one
  overlay-redesign session rather than piecemeal.
- Cite: The Turn Signal, "The Problem With Digital Instrument Clusters,"
  https://www.theturnsignalblog.com/the-problem-with-digital-instrument-clusters-and-how-to-design-a-better-one/

---

## Section B - Dark operational dashboards + density

### B1. Grafana: threshold-driven status colors + the 5-second rule

- **WHAT** - Drive every status color from an explicit NUMERIC threshold table
  (ok / warn / danger), not ad-hoc per-panel CSS. A viewer should grasp health
  in ~5 seconds.
- **HOW** - Grafana's stat-panel threshold model: define a 3-tier table and map
  a metric's current value to a status; styling becomes declarative per metric.
  Grafana also warns stacked/overlapping series "can be misleading, and hide
  important data."
- **RC HAVE?** - Partial. RC has the color VOCABULARY (`--signal-good/warn/bad`,
  the `.cost-tile-banner.ok/warn/over` pattern at `primitives.css:107-109`) but
  thresholds are computed ad hoc per panel in JS, not from a shared table.
- **WHERE** - A small shared `statusFor(value, thresholds)` JS helper that
  returns `good|warn|bad`, mapping to a `--status` var on the element. Consumed
  by op_score, player_gpi, cost-tile, cooldown_watch.
- **EFFORT+RISK** - LOW. One helper + adopt incrementally. No backend change.
- **LIFT - HIGH.** Cheap, removes scattered magic numbers, and makes the
  status system consistent and auditable. Pure win for a vanilla-JS dashboard.
- Cite: Grafana dashboard best practices,
  https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/
  ; Configure thresholds,
  https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-thresholds/
  ; 5-second rule, https://customerscience.com.au/customer-experience-2/designing-actionable-dashboards-the-5-second-rule-for-executives/

### B2. Datadog: labeled grid sections + symmetric scan path

- **WHAT** - Organize density into NAMED CSS-grid sections (Overview / Combat /
  Objectives / Status) rather than a flat field of equal tiles; keep a symmetric
  2-column grid so the eye has a stable scan path at 1920 wide.
- **HOW** - Datadog: "Avoid cluttered designs with too many small widgets
  competing for attention"; every widget must be "grounded in a question." Put
  the at-a-glance snapshot in a top Overview band; demote detail to collapsible
  groups.
- **RC HAVE?** - Partial. RC uses a CSS grid (`web/css/panels/grid.css`) and
  view-routing, but panels are not grouped under explicit named section bands
  with an Overview-first hierarchy.
- **WHERE** - The main dashboard grid container. Wrap panels in
  `<section data-band="overview|combat|...">` with grid-area assignment.
- **EFFORT+RISK** - MED. HTML/CSS restructure of the grid; touches the main
  layout (the operator's primary screen). Medium risk, fully visual.
- **LIFT - MED.** Real legibility gain but it is a layout project; gate behind a
  UI-audit pass per the per-page ritual.
- Cite: Datadog executive dashboards,
  https://www.datadoghq.com/blog/datadog-executive-dashboards/

### B3. Bloomberg Terminal: dense + tabular + redundant status cues

- **WHAT** - For an EXPERT single user, density is the win - but never encode
  status by HUE ALONE. Pair every red/green value with a +/- sign, an up/down
  arrow glyph, or an icon, so the meaning survives grayscale and color blindness.
  Use a stable, learnable label grammar (short fixed keys at fixed positions).
- **HOW** - The Terminal "trades modern consumer UX norms for speed, density,
  predictability." Green = up, red = down by convention, but Bloomberg also uses
  bright blue and bright orange and treats color as a signal that "must not stand
  alone" (their color-accessibility work adds redundant cues). Tabular numbers
  stop live values from jittering: with proportional figures "when a number
  flips from 11:11 to 12:23, the whole string can shift horizontally."
- **RC HAVE?** - Mixed. Tabular nums: YES (`tokens.css:108`,
  `primitives.css:105,120`, ~15 sites in legacy_index). Redundant status cues:
  NO - status is color-only across panels (no grep hit for an arrow/sign glyph
  tied to good/bad). The operator IS the single expert user, so density is apt.
- **WHERE** - Every status-colored stat: prepend a sign/arrow/icon. Add a
  `.tabular-nums` to any remaining live-updating numeric cell not yet carrying it.
- **EFFORT+RISK** - LOW. Glyphs are content/CSS-pseudo additions; tabular-nums
  is already a class. Additive, near-zero risk.
- **LIFT - HIGH.** Directly fixes the WCAG 1.4.1 color-only gap (see C5),
  cheap, and the density posture matches a solo-expert tool.
- Cite: Bloomberg color accessibility,
  https://www.bloomberg.com/ux/2021/10/14/designing-the-terminal-for-color-accessibility/
  (bot-blocked to automated fetch; corroborated by the Quora Terminal-density
  discussion https://www.quora.com/Why-do-Bloomberg-terminals-have-such-non-standard-interfaces
  ) ; tabular-nums, https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric

### B4. NOC single-pane-of-glass: exception-first hierarchy

- **WHAT** - When everything is nominal the screen stays visually QUIET
  (neutral/dim); any warn/danger escalates loudly via color + motion. Surface
  what is WRONG, not everything that is normal.
- **HOW** - INOC: data must be "glanceable," with "low cognitive load and high
  ability to indicate 'hey, there's a problem - you need to dig.'" Reserve
  saturated success/warn/danger + a subtle pulse strictly for state changes that
  need action; render steady-state values in low-contrast neutral text.
- **RC HAVE?** - Partial. RC has `--text-dim` for quiet steady state and the
  pulse keyframes for change, but no enforced "quiet-by-default, loud-on-
  exception" policy; several panels animate continuously (e.g.
  `item_build.css:164` `nextUpPulse ... infinite`, `map_state.css:391`
  `deepZoneWarn ... infinite`).
- **WHERE** - A motion/color policy doc + audit: steady state = no animation +
  dimmed text; reserve infinite loops for genuine danger only (overlaps D4).
- **EFFORT+RISK** - LOW-MED. Mostly an audit + trimming a few `infinite`
  animations to one-shots. Low risk.
- **LIFT - MED.** Aligns the whole dashboard with calm-tech (D4); cheap but
  spans many panels so it is a sweep, not a one-liner.
- Cite: INOC NOC dashboards, https://www.inoc.com/blog/noc-dashboards

---

## Section C - Design systems, dark color theory, accessibility

### C1. Material 3: tonal surfaces (elevation via lightness, not shadow)

- **WHAT** - Express elevation primarily through TONE-based surface color, not
  box-shadow. Higher emphasis = a lighter/tonally-distinct surface in dark mode.
- **HOW** - M3 replaced elevation +1..+5 overlays with named container roles:
  `surface`, `surface-container-low/-/-high/-highest`. Cards sit on a lighter
  container tone to read as raised. Shadows are nearly invisible on dark
  surfaces anyway, so lightness carries the depth cue.
- **RC HAVE?** - Partial. RC has `--surface`, `--surface-2`, `--surface-alt`,
  `--surface-head` (a nascent tonal ramp) but ALSO leans on `--shadow-card`
  (`primitives.css:43`) and assorted `box-shadow` glows. No formal
  low/high/highest container tier.
- **WHERE** - Extend the token set into an explicit 4-step container ramp in
  `tokens.css`; migrate panels to pick a container tone for elevation instead of
  a shadow.
- **EFFORT+RISK** - MED. Additive tokens are cheap; migrating consumers is the
  cost. Low risk if additive and opted into per panel.
- **LIFT - MED.** Modernizes the elevation model and reads better on dark/OLED,
  but it is a gradual migration, not a quick token add.
- Cite: M3 tone-based surfaces,
  https://m3.material.io/blog/tone-based-surface-color-m3 ; M3 elevation,
  https://m3.material.io/styles/elevation

### C2. Apple HIG: dark mode is adapted, not inverted; semantic + tiered text

- **WHAT** - Author SEMANTIC color tokens (purpose, not literal hue) and give
  text 4 hierarchy tiers; hand-tune the dark palette (never algorithmically
  invert - a "danger = red" must not flip to green).
- **HOW** - Apple: a common mistake is "supporting sufficient contrast in your
  light mode interface, but forgetting to support sufficient contrast in a dark
  interface"; gray-on-black "may be more difficult to read for those with low
  vision." Semantic colors expose primary/secondary/tertiary/quaternary levels.
- **RC HAVE?** - Partial. RC has 2 text tiers (`--text`, `--text-dim`) and a
  hand-authored dark palette (good - not inverted). Missing the
  tertiary/quaternary text steps for finer hierarchy.
- **WHERE** - Add `--text-secondary` / `--text-tertiary` between `--text` and
  `--text-dim` in `tokens.css`; adopt where panels currently fake hierarchy with
  opacity.
- **EFFORT+RISK** - LOW. Two new tokens + opt-in. Near-zero risk.
- **LIFT - MED.** Cheap and improves at-distance hierarchy, but lower urgency
  than the status/motion gaps.
- Cite: Apple HIG Dark Mode,
  https://developer.apple.com/design/human-interface-guidelines/dark-mode ;
  Dark interface criteria,
  https://developer.apple.com/help/app-store-connect/manage-app-accessibility/dark-interface-evaluation-criteria/

### C3. Fluent 2: two-tier tokens (primitive ramp -> semantic alias)

- **WHAT** - Separate raw values from meaning. Layer 1 = a primitive ramp
  (`--neutral-900`, `--green-400`); Layer 2 = aliases that reference them
  (`--surface: var(--neutral-900)`, `--status-success: var(--green-400)`).
  Components consume ONLY aliases.
- **HOW** - Fluent: global tokens are "context-agnostic and store raw values";
  alias tokens "add semantic meaning." Swapping a theme (or a high-contrast
  variant) re-points aliases without touching component CSS. Status is a
  first-class alias category (success/warning/danger).
- **RC HAVE?** - Partial / the central architectural gap. RC HAS both a base
  palette (base.css) and a semantic layer (tokens.css), but they are not wired
  as primitive -> alias: `--signal-good` is a literal `#6ec977`
  (`tokens.css:31`) rather than `var(--green-400)`, and panels mix `--good` and
  `--signal-good`. No single source of truth.
- **WHERE** - Refactor `tokens.css` so `--signal-*` reference a small primitive
  ramp, and converge `--good`/`--signal-good` duplication onto one alias set.
- **EFFORT+RISK** - MED. A token-architecture refactor touching base.css +
  tokens.css + every consumer's variable names. Medium risk (broad, visual);
  do it as a dedicated pass with a screenshot audit.
- **LIFT - MED.** Correct long-term foundation and unblocks theming, but it is
  the heaviest item here; sequence it AFTER the cheap HIGH-lift wins.
- Cite: Fluent 2 design tokens, https://fluent2.microsoft.design/design-tokens ;
  Fluent 2 color, https://fluent2.microsoft.design/color

### C4. Dark color science: no pure black, desaturate accents, no pure white

- **WHAT** - Base surface = near-black gray (#121212), NOT #000; body text =
  off-white (~#E6E6E6), NOT #FFF; desaturate accent/status colors vs their
  light-mode values so they stop "vibrating" on dark.
- **HOW** - Pure #000 + #FFF text yields excessive contrast, eye strain, and
  text halation (glow/bloom); fully saturated hues "create optical vibrations
  on a dark background." Google's #121212 surface "uses just 0.3% more power than
  pure black" on OLED while reading far better. Reduce accent saturation ~20
  points.
- **RC HAVE?** - Need to verify exact hex values in base.css, but the signal
  colors are already moderately desaturated mid-tones (`--signal-good #6ec977`,
  not a pure `#00ff00`), which is on the right track. Worth a quick audit that
  no panel uses `#000` background or `#fff` body text.
- **WHERE** - A values audit of base.css surface/text hexes; nudge any pure
  black/white found.
- **EFFORT+RISK** - LOW. A grep-and-tweak of literal `#000`/`#fff`. Low risk.
- **LIFT - MED.** RC is mostly already compliant; value is in verifying +
  locking it, not a big change.
- Cite: atmos.style dark-mode best practices (cites the #121212 / 0.3% OLED
  figure and ~20-point desaturation),
  https://atmos.style/blog/dark-mode-ui-best-practices

### C5. WCAG / APCA contrast + color-blind-safe status

- **WHAT** - Hold body text >= 4.5:1 against the surface and every status color /
  glyph / chart stroke >= 3:1 (SC 1.4.11 treats status dots and chart marks as
  graphical objects). NEVER encode status by hue alone (SC 1.4.1): pair
  success/warn/danger with a distinct shape, glyph, or label.
- **HOW** - WCAG 2.x: 4.5:1 normal text, 3:1 large text / UI components. APCA
  (WCAG 3 method) warns 2.x "far overstates contrast for dark colors to the
  point that 4.5:1 can be functionally unreadable when a color is near black" -
  so spot-check key dark-mode text with an APCA tool (target ~Lc 75 for body).
- **RC HAVE?** - Mixed. RC has a focus ring (`--focus-ring`, `tokens.css:95`)
  and a moderate palette, but status is COLOR-ONLY across panels (the same gap
  as B3) - this is a real WCAG 1.4.1 miss. No evidence of an APCA pass.
- **WHERE** - Two actions: (1) add redundant glyphs/labels to status (shared
  with B3); (2) a one-time contrast audit of text-on-surface and status-dot
  pairs (the `health-dot` family at `primitives.css:135-136` is a prime check).
- **EFFORT+RISK** - LOW for the glyph fix; LOW-MED for the audit. Low risk.
- **LIFT - HIGH.** Accessibility + at-a-glance legibility at viewing distance is
  exactly the brief; the color-only fix is cheap and high-value.
- Cite: WCAG SC 1.4.3,
  https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html ; SC 1.4.11,
  https://www.w3.org/WAI/WCAG21/Understanding/non-text-contrast.html ; SC 1.4.1,
  https://www.w3.org/WAI/WCAG20/Understanding/visual-audio-contrast-without-color
  ; Why APCA, https://git.apcacontrast.com/documentation/WhyAPCA

---

## Section D - Micro-interaction / motion (lightweight CSS)

### D1. Micro-interactions: subtle one-shot feedback, 100-500ms

- **WHAT** - Use motion as SUBTLE feedback to overcome change blindness (static
  updates near the edge of focus go unnoticed), not as delight/spectacle. Keep
  status pings short - one-shot, not infinite.
- **HOW** - NN/G: "Motion is most often appropriate as a form of subtle feedback
  for microinteractions"; "the duration of most animations should be in the
  range of 100-500 ms." Restart a keyframe on each data update with a reflow
  poke: `el.classList.remove('fresh'); void el.offsetWidth; el.classList.add
  ('fresh');`.
- **RC HAVE?** - Yes, mostly right. The `coach-pulse-*` glow at
  `right_now.css:40-42` is a one-shot at 0.8s (inside the 100-500ms..sub-second
  band, good). But several panels loop `infinite` (`item_build.css:164,168`,
  `map_state.css:391,397`) which D1/D4 would trim. Note the tokens.css comment
  says "1.2s" while the consumer is 0.8s - a doc/code drift.
- **WHERE** - Standardize a single one-shot "fresh" animation utility; replace
  infinite loops (except danger) with class-toggle + reflow-poke one-shots.
- **EFFORT+RISK** - LOW. A small utility class + targeted edits. Low risk.
- **LIFT - MED.** RC is already close; the win is consistency + trimming loops,
  plus fixing the 0.8s/1.2s doc drift.
- Cite: NN/G animation purpose,
  https://www.nngroup.com/articles/animation-purpose-ux/ ; NN/G animation
  duration, https://www.nngroup.com/articles/animation-duration/

### D2. Motion accessibility: prefers-reduced-motion (REPLACE, do not just kill)

- **WHAT** - Honor the OS "minimize non-essential motion" setting, but REPLACE
  the pulse with a static tint/hold so the "fresh data" meaning survives for
  reduced-motion users (do not merely delete the animation).
- **HOW** - MDN: prefers-reduced-motion detects a user who "prefers an interface
  that removes, reduces, or replaces motion"; it exists for vestibular reasons.
  Pattern:
  `@media (prefers-reduced-motion: reduce){ .tile.fresh{ animation:none;
  box-shadow:0 0 0 2px var(--good); } }`
- **RC HAVE?** - Barely. Grep finds `prefers-reduced-motion` in exactly ONE file
  (`web/css/panels/input_activity.css:473`), and that one nukes all animation to
  0.01ms globally - it does not REPLACE the status signal. ~12 other animated
  panels (right_now, item_build, map_state, grid, overlay, home, bridge_pending)
  do not branch on it at all.
- **WHERE** - A global reduced-motion block in `tokens.css` that swaps each
  `coach-pulse-*` for a static tinted ring; remove per-panel inconsistency.
- **EFFORT+RISK** - LOW. One media block + targeted static fallbacks. Near-zero
  risk (only affects reduced-motion users).
- **LIFT - HIGH.** Single cheapest accessibility win with the widest current
  gap; directly on-brief (non-distracting, accessible) and almost free.
- Cite: MDN prefers-reduced-motion,
  https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion

### D3. GPU-cheap animation: compositor-only (transform / opacity)

- **WHAT** - Animate only compositor-friendly properties so frames never re-run
  layout or paint - critical for an overlay that polls telemetry while
  animating. Prefer opacity on a pseudo-element halo over animating box-shadow
  spread.
- **HOW** - web.dev: "restrict animations to opacity and transform to keep
  animations on the compositing stage." box-shadow technically repaints, so the
  cheapest glow is a `::after` halo whose OPACITY animates:
  `.tile::after{ box-shadow:0 0 12px var(--good); opacity:0; will-change:opacity }`
  then animate `.tile.fresh::after` opacity. Set `will-change` only when measured,
  never globally.
- **RC HAVE?** - No. RC's `coach-pulse-*` keyframes animate `box-shadow` directly
  (`tokens.css:114-125`) - functional but repaints each frame. No pseudo-element
  halo pattern in the repo.
- **WHERE** - Rework the pulse keyframes onto an opacity-animated `::after`
  layer; especially in the overlay (`overlay.css`) where frame budget competes
  with polling.
- **EFFORT+RISK** - LOW-MED. Keyframe + pseudo-element refactor; visual parity
  needs a screenshot check. Low risk.
- **LIFT - MED.** Perf-correctness win, mostly invisible to the eye; do it when
  touching the pulse system for D1/D2 anyway (bundle the three).
- Cite: web.dev high-performance CSS animations,
  https://web.dev/articles/animations-guide

### D4. Calm technology: periphery-to-center, motion as the exception

- **WHAT** - Steady state = NO motion; motion is the exception that means "look
  here now," then recedes. Encode severity in the glow's DECAY/INTENSITY (good =
  a single soft fade in the periphery; danger = a brief brighter pulse that pulls
  to center then recedes). Reserve looping motion for genuine danger only.
- **HOW** - Amber Case: "Technology should require the smallest possible amount
  of attention"; "a calm technology will move easily from the periphery of our
  attention, to the center, and back." This is the governing constraint for a
  coach overlay during a live game.
- **RC HAVE?** - Partial. RC's intent matches (one-shot coach pulse, dimmed
  steady text) but it is violated by the `infinite` loops noted in B4/D1
  (`item_build` next-up + can-afford pulses, `map_state` zone warnings loop
  forever, pulling the eye continuously).
- **WHERE** - The same motion-policy sweep as B4: convert non-danger infinite
  loops to one-shots; keep `deepZoneWarn`/danger states as the only sustained
  motion.
- **EFFORT+RISK** - LOW-MED. Edit a handful of `animation: ... infinite` rules.
  Low risk.
- **LIFT - MED.** Ties the whole motion system to a coherent principle; cheap
  but multi-panel, so a sweep.
- Cite: Amber Case, Principles of Calm Technology, https://calmtech.com/

---

## Top-3 HIGH-lift findings (do these first - cheap + high value)

1. **D2 - prefers-reduced-motion done right.** RC honors it in ONLY one panel
   (`input_activity.css:473`) and that one just zeroes animation rather than
   replacing the signal. Add a global block in `tokens.css` that swaps each
   `coach-pulse-*` for a static tinted ring. Near-zero risk, widest gap,
   accessibility win directly on-brief.

2. **B3 + C5 - redundant status cues (kill color-only).** Status is encoded by
   hue alone across panels, failing WCAG 1.4.1 and red-green color blindness.
   Prepend a sign/arrow/glyph (or label) to every good/warn/danger value
   (Bloomberg + WCAG converge here). Cheap pseudo-element/content additions; the
   solo-expert density posture is already apt.

3. **B1 - threshold-driven status helper (Grafana model).** Replace scattered
   per-panel JS magic numbers with one shared `statusFor(value, thresholds)`
   that maps to a `--status` var. Removes drift, makes the status system
   auditable, adopt incrementally. Pure vanilla-JS win.

## Sequencing note

The three HIGH items are all token/utility scoped (low blast radius) - ship them
before the structural MED items (C3 two-tier refactor, A2/A4 overlay redesign,
B2 grid sectioning), which each warrant a dedicated session + the per-page
UI-audit ritual. Fix the 0.8s/1.2s coach-pulse doc drift (`tokens.css` comment
vs `right_now.css:40`) as a free Tier-0 cleanup while in the motion code.

---

## Full source list (deduplicated)

- Ecliptech Shift-I - https://ecliptech.com.au/shift-i/
- FAA AC 25-11B - https://www.faa.gov/documentlibrary/media/advisory_circular/ac_25-11b.pdf
- Apple HIG Complications - https://developer.apple.com/design/human-interface-guidelines/complications/
- The Turn Signal (instrument clusters) - https://www.theturnsignalblog.com/the-problem-with-digital-instrument-clusters-and-how-to-design-a-better-one/
- Grafana best practices - https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/
- Grafana thresholds - https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-thresholds/
- 5-second rule (Customer Science) - https://customerscience.com.au/customer-experience-2/designing-actionable-dashboards-the-5-second-rule-for-executives/
- Datadog executive dashboards - https://www.datadoghq.com/blog/datadog-executive-dashboards/
- Bloomberg color accessibility - https://www.bloomberg.com/ux/2021/10/14/designing-the-terminal-for-color-accessibility/
- Bloomberg Terminal density (Quora) - https://www.quora.com/Why-do-Bloomberg-terminals-have-such-non-standard-interfaces
- MDN font-variant-numeric - https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric
- INOC NOC dashboards - https://www.inoc.com/blog/noc-dashboards
- M3 tone-based surfaces - https://m3.material.io/blog/tone-based-surface-color-m3
- M3 elevation - https://m3.material.io/styles/elevation
- M3 color roles - https://m3.material.io/styles/color/roles
- M3 state layers - https://m3.material.io/foundations/interaction/states/state-layers
- Apple HIG Dark Mode - https://developer.apple.com/design/human-interface-guidelines/dark-mode
- Apple HIG Color - https://developer.apple.com/design/human-interface-guidelines/color
- Apple dark interface criteria - https://developer.apple.com/help/app-store-connect/manage-app-accessibility/dark-interface-evaluation-criteria/
- Fluent 2 design tokens - https://fluent2.microsoft.design/design-tokens
- Fluent 2 color - https://fluent2.microsoft.design/color
- Fluent 2 elevation - https://fluent2.microsoft.design/elevation
- atmos.style dark-mode best practices - https://atmos.style/blog/dark-mode-ui-best-practices
- Supercharge pure black/white - https://supercharge.design/articles/pure-black-and-pure-white-in-ui-design
- WCAG SC 1.4.3 Contrast Minimum - https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html
- WCAG SC 1.4.11 Non-text Contrast - https://www.w3.org/WAI/WCAG21/Understanding/non-text-contrast.html
- WCAG SC 1.4.1 Use of Color - https://www.w3.org/WAI/WCAG20/Understanding/visual-audio-contrast-without-color
- APCA Why APCA - https://git.apcacontrast.com/documentation/WhyAPCA
- WCAG 3.0 draft - https://www.w3.org/TR/wcag-3.0/
- NN/G animation purpose - https://www.nngroup.com/articles/animation-purpose-ux/
- NN/G animation duration - https://www.nngroup.com/articles/animation-duration/
- MDN prefers-reduced-motion - https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion
- web.dev high-performance CSS animations - https://web.dev/articles/animations-guide
- Amber Case Principles of Calm Technology - https://calmtech.com/

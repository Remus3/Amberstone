# RC 2.0 Phase 3.1 - IN-MATCH Overlay Priority-Info Condensation Spec (Glance Test)

Implementable spec the 3.2 (structure/density) and 3.3 (typography/hit-targets/
hierarchy) UI-agent passes build against. Derives from
`docs/research/RC2_RESEARCH_in_match_overlay.md` (10 rules, 3 tiers, L1-L6 lift)
and the greenlit Hextech theme in `docs/design/RC2_DESIGN.html`.

ASCII only (repo hard rule). No em-dashes, en-dashes, or smart quotes. Action
glyphs (U+26A0 warn, U+2713 check, U+25BA play) are functional code, not banned
punctuation - they stay.

Authored 2026-06-20. Ground truth re-verified this session: `web/css/overlay.css`,
`web/js/panels/right_now.js:471-509`, `web/js/panels/active_match.js`,
`web/js/panels/callouts.js`.

--------------------------------------------------------------------------------
## 0. SCOPE + ACCEPTANCE (the glance test)
--------------------------------------------------------------------------------

PROBLEM (from research section 5): RC's engine already out-computes all four
competitors. The RC2 in-match overlay work is PRESENTATION + PRIORITY, not feature
build. The 460px right dock currently renders every live cue at flat priority with
no arbitration over the scarce mid-fight slots, and pulses on every benign re-emit.

THIS SPEC delivers the missing priority model: a fixed tier + slot assignment for
every cue, a single-winner arbitration for the primary slot, preattentive render
bindings against the Hextech palette, and a motion-rationing rule.

ACCEPTANCE (glance test, research rule 1 + 2.1):
- A1. Every PERSISTENT overlay element is answerable in <=1.5s (2.0s hard ceiling).
- A2. At any instant, exactly ONE element holds pop-out (the ONLY red / ONLY moving
  / ONLY large thing). Research rule 4.
- A3. The combat tier carries NO text that must be READ - color / size / position /
  motion only. Research rule 3. Prose is demoted to the between-fight surface.
- A4. The overlay holds 1 primary + at most 3 supporting persistent slots; anything
  else is deferred to the dashboard or a non-combat reveal. Research rule 7.
- A5. The .ov-pulse / per-band pulse fires ONLY for the Emergency tier (and a
  single-shot Urgent promotion), never on a same-band benign re-emit. Research rule 5.

Out of scope here (owned by later stages): minimap-anchored coordinate projection
(L1, Phase 4.x overlay-sizing), opacity/scale sliders (L5, Phase 4.4 settings),
the dashboard-coexistence fix (E1 done / Phase 3.4), CV laning verdicts (Phase 5).

--------------------------------------------------------------------------------
## 1. THE THREE TIERS (formalized)
--------------------------------------------------------------------------------

Every cue carries a tier tag at author/emit time (research rule 2). The tier
decides render channel, slot eligibility, and motion budget.

| Tier | Meaning | Channel (preattentive) | Motion | Persists? |
|------|---------|------------------------|--------|-----------|
| AMBIENT | Quiet always-on context; updates without drawing the eye | position + small icon + bar-length; muted slate/gold | none | yes |
| URGENT | Acts in the next few seconds or loses value; color + size | hue bin (caution/lethal) + larger type + fixed slot | one-shot promotion pulse on CROSS only | yes (slot 1) |
| EMERGENCY | Must change action in ~1s or die / lose objective | motion (pulse) + pop-out color + size | self-expiring pulse, rationed | transient, self-expires |

Tier ENTRY rules (the interrupt gate, research 2.5): a cue escalates to EMERGENCY
only if "the player must change action in the next ~1s or lose value" is TRUE.
Else it sits AMBIENT, escalating to URGENT when its own crossing-edge fires (spike
crossed, objective ETA <= window, lethal-incoming computed). On exit (edge passes)
it falls back one tier, never two.

Mapping to existing code bands (`right_now.js:472,491-508` classifyAction):
- `urgent` band  -> EMERGENCY tier (glyph U+26A0, pulse rn-pulse-bad).
- `fight`  band  -> URGENT tier    (glyph U+25BA, pulse rn-pulse-warn).
- `good`   band  -> AMBIENT tier    (glyph U+2713, pulse rn-pulse-good DROPPED under A5; see section 5).
- `empty`        -> no render.

ACTION FOR 3.2/3.3: the band->tier map above becomes the single source. Today the
pulse fires for all three bands on any text change (`right_now.js:490-500`); this
spec narrows it (section 5).

--------------------------------------------------------------------------------
## 2. THE SLOT BUDGET (1 primary + 3 support)
--------------------------------------------------------------------------------

The 460px dock (`overlay.css:55-179`) is re-budgeted as a FIXED, learnable column
(research rule 9). Top-to-bottom, highest priority at the eye-line top:

| Slot | Role | Mount today | Tier eligibility |
|------|------|-------------|------------------|
| S0 PRIMARY | the ONE action right now | `#rn-action` headline / `#rn-choices` A+B chips | URGENT or EMERGENCY winner only |
| S1 SUPPORT-A | imminent objective / spike ETA | `#rn-callouts` (callouts.js, <=3 rows -> CLAMP to 2) | AMBIENT, promotes to URGENT on ETA cross |
| S2 SUPPORT-B | macro lead direction | `#rn-lead` pill | AMBIENT |
| S3 SUPPORT-C | next-item / recall affordance | `.am-pane-build` top row + recall chip | AMBIENT |

Everything else stays HIDDEN in the base subset and reachable via panel-set cycle
(`overlay.css:181-267`: coach / build / threat) or the dashboard companion (E1).
Spike strip, ward heat, spike curve, CDS ledger, MAP pane remain gated
(`overlay.css:82-95`) - confirmed correct under rule 7.

SLOT INVARIANT (3.2 must enforce): S0 renders the single arbitration winner ONLY.
If two cues both qualify EMERGENCY, S0 shows the higher-priority one (section 4)
and the loser is demoted to its AMBIENT home slot - never two pop-outs (A2).

CALLOUT CLAMP: callouts.js renders up to 3 rows (`callouts.js:64-96`). At overlay
density that is 3 competing ETA chips; clamp the overlay subset to the 2 nearest-ETA
rows so S1 stays a 1.5s read. Dashboard keeps all 3.

--------------------------------------------------------------------------------
## 3. CUE INVENTORY -> TIER / SLOT / SOURCE / RENDER CHANNEL
--------------------------------------------------------------------------------

The full in-match cue set with its assignment. SOURCE cites the live producer.
CHANNEL is the preattentive encoding (research 2.2: magnitude = bar/position,
category = color bin, NEVER magnitude-in-hue).

| Cue | Tier (default) | Slot | Source (file:line / field) | Channel |
|-----|----------------|------|----------------------------|---------|
| Coach headline action | per band (section 1) | S0 | coach.action / classifyAction `right_now.js:472` | glyph + size; color = band bin |
| A+B trade/all-in/back-off choices | URGENT | S0 | coach.choices, `coach_choices.js` -> `#rn-choices` | 3 chips, fixed order, key-hint 1/2/3 |
| Objective ETA (drake/baron/herald) | AMBIENT -> URGENT on cross | S1 | `core/event_callouts.py:76-79`, `callouts.js:83-96` | label + ETA chip (NOW or M:SS), bar = time-to |
| Inhibitor / camp respawn | AMBIENT | S1 | `event_callouts.py:328-332` | ETA chip |
| Macro lead (ahead/behind/even) | AMBIENT | S2 | `callouts.js:111-130` `#rn-lead` | left-border accent (good/bad) + magnitude tag; NOT hue-coded number |
| Spike crossed (level/item) | URGENT (one-shot) | S0 promote | `spike_markers.js` crossing edge | single Urgent cue, self-expire; full strip stays dashboard-only |
| Next-item rerank | AMBIENT | S3 | POST /api/ds-preview, `active_match.js:291-378` | top-1 item icon + name; rest in build set |
| Recall / back-timing | AMBIENT -> URGENT on affordable | S3 | `recall_callout()` `event_callouts.py:281` | chip "back now" when core item affordable |
| Enemy MIA / gank-warn | URGENT | S1 banner | `active_match.js:888-906` | caution-bin band, count of missing |
| Lethal incoming (low HP at fight) | EMERGENCY | S0 | coach.fight_rule + hp threshold (game-monitor contract) | pop-out red + pulse, self-expire |
| Enemy cooldown ledger | AMBIENT | threat set only | `cd_ledger.js`, `cooldown_watch.js:97-134` | gated; not in base subset (ToS-hot, research 3) |
| Trinket/ward ready (L2) | AMBIENT make-aware | S2-adjacent glyph | cooldown feed `active_match.js:398-405` | one-shot pulse on ready edge; tiny glyph (Phase 4 build) |

DEFERRED to dashboard / panel-set (not in the 4-slot budget): spike curve, ward
heat strip, full spike-marker strip, MAP pane, full DS analysis cluster, full
3-row callouts. All already gated in `overlay.css`.

--------------------------------------------------------------------------------
## 4. PRIMARY-SLOT ARBITRATION (single winner for S0)
--------------------------------------------------------------------------------

When more than one cue qualifies for S0 in the same tick, a deterministic priority
score picks ONE (enforces A2). Higher wins; ties break by smaller ETA then by the
listed order.

```
PRIORITY (S0 eligibility, descending):
  100  EMERGENCY: lethal-incoming / must-flash-now (coach fight_rule + hp band)
   90  EMERGENCY: objective steal/contest window NOW (drake/baron ETA == NOW and contestable)
   80  URGENT:    A+B choices present (a decision is on the clock)
   70  URGENT:    spike crossed this tick (one-shot, ~4s self-expire)
   60  URGENT:    coach.action band == fight
   40  AMBIENT:   coach.action band == good (headline only, no promotion)
    0  empty
```

RULES:
- The S0 winner is the max-priority eligible cue. All losers render in their
  AMBIENT home slot (S1-S3) or not at all - never a second pop-out.
- A one-shot URGENT (spike crossed, 70) outranks a steady `fight` headline (60) for
  its self-expire window, then yields back.
- EMERGENCY (>=90) always preempts; on preempt, the displaced URGENT cue keeps its
  glyph in its home slot WITHOUT pulse.
- If S0 is empty (priority 0) the slot collapses to zero height (no lonely glyph,
  `right_now.js:503` already guards the lonely play-triangle).

ACTION FOR 3.2: implement this as a pure function `selectPrimary(state) -> {cue,
tier, priority}` in a new `web/js/lib/overlay_priority.js`; right_now.js + callouts.js
consume it instead of each independently deciding to pulse. TDD: a fixture table of
N states -> expected winner.

--------------------------------------------------------------------------------
## 5. MOTION RATIONING (A5, research rule 5 + 2.5)
--------------------------------------------------------------------------------

Today: `.action` pulses on EVERY band on text change (`right_now.js:490-500`), and
`.ov-pulse` fires on any rendered-content change (`overlay.css:269-280`,
overlay_pulse.js). That is alarm-fatigue by construction (research 2.5: 80-99% of
over-fired alerts get tuned out).

NEW RULE:
- EMERGENCY tier (priority >=90): pulse FIRES (rn-pulse-bad / .ov-pulse), self-expires.
- URGENT one-shot promotions (spike crossed 70, choices-newly-present): a SINGLE
  pulse on the crossing edge only, never re-pulse while the condition persists.
- URGENT steady (`fight` 60) and AMBIENT (`good` 40): NO pulse. Color + glyph update
  silently (make-aware / change-blind ladder rung).
- Reduced-motion (design-system E8, prefers-reduced-motion): pulse swaps to a static
  ring, per `RC2_DESIGN.html:348`. Already an accepted pattern.

EDGE DETECTION: pulse keys off a CROSS (false->true of the tier's entry predicate),
not off text inequality. right_now.js already tracks `dataset.raw` for change; extend
to track the prior TIER and fire only on an into-EMERGENCY or one-shot-URGENT edge.

--------------------------------------------------------------------------------
## 6. HEXTECH RENDER BINDINGS (greenlit palette)
--------------------------------------------------------------------------------

From `RC2_DESIGN.html:556` Hextech Tactical. Bind discrete category bins to color,
magnitude to bar/position (research 2.2, rule 10). No new literals beyond tokens.css.

| Semantic | Hextech hex | Use |
|----------|-------------|-----|
| base (transparent canvas) | #0A0E14 | page bg (overlay stays transparent; panels use alpha backing) |
| panel backing | #16202E | dock pane alpha fill (replaces rgba(23,24,33,.86)) |
| gold accent | #C8AA6E | AMBIENT headings, primary-slot frame, neutral emphasis |
| cyan accent | #0AC8B9 | informational / objective chips, links |
| good / ahead | #37D08A | lead-ahead border, `good` band glyph |
| caution | #C8AA6E gold | URGENT bin (spike, fight, MIA) - reuse gold as the single caution hue |
| lethal / behind | #E84057 | EMERGENCY pop-out, lead-behind border, `urgent` band |

POP-OUT DISCIPLINE (A2): lethal red (#E84057) is RESERVED for the current S0
EMERGENCY winner. No other element may paint red while an EMERGENCY holds S0. Gold
= caution, cyan = info, green = good; red appears at most once on screen.

MAGNITUDE: HP fraction, cooldown remaining, gold lead, time-to-objective render as
bar length or position. The lead pill keeps its left-border state accent
(`overlay.css:169-174`) but the magnitude TAG is text, never a hue ramp.

--------------------------------------------------------------------------------
## 7. PER-ELEMENT GLANCE-TEST ACCEPTANCE (measurable, for 3.3)
--------------------------------------------------------------------------------

Each persistent element gets a measurable pass bar the 3.3 typography/hit-target
audit checks against the game-distance baseline (read in Chrome at game distance,
overlay floors already pinned in `overlay.css:177-233`).

- S0 headline: single line, font 48-56px (existing `.action`), 1 glyph prefix, band
  color bin, line-clamp 2 then ellipsis. Read test: action verb parseable in <1.0s.
- S0 choices: exactly 3 chips, fixed L-to-R order (trade / all-in / back-off), each
  with a 1/2/3 key hint; hit target >= 44px tall in ACTIVE mode.
- S1 callouts: <=2 rows, each = label + ETA chip; ETA chip >= 13px (floor at
  `overlay.css:178`). Read test: nearest objective ETA in <1.0s.
- S2 lead: one pill, direction by left-border bin + 1 magnitude tag; <=13px source pill.
- S3 build: top-1 item icon + name only in base subset; full strip in build set.
- No element below the 13px overlay floor; no element requires horizontal scan
  beyond 460px.

--------------------------------------------------------------------------------
## 8. HANDOFF TO 3.2 / 3.3
--------------------------------------------------------------------------------

- 3.2 (structure/density) OWNS: `web/js/lib/overlay_priority.js` (section 4
  selectPrimary + tier map), the callout 2-row clamp, the slot-budget DOM order,
  and re-pointing right_now.js / callouts.js pulse decisions at the shared selector.
  TDD: fixture state table -> expected S0 winner + expected pulse fire/no-fire.
- 3.3 (typography/hit-targets/hierarchy) OWNS: the Hextech color-bin bindings
  (section 6), the per-element acceptance bars (section 7), the 5-phase fixture
  audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) + Claude_Preview
  vs /api/state at `?overlay=1`.
- Both ship behind the existing overlay subset (no live-default flip needed); the
  pulse-narrowing is a behavior change -> Tier-1 (one module) verification, shadow
  any band->tier reclassification before committing.

--------------------------------------------------------------------------------
## 9. OPEN QUESTIONS (deferred, not blocking 3.2/3.3)
--------------------------------------------------------------------------------

- Q1. Minimap-anchored ETA chips (L1) need screen-coordinate projection -> Phase 4.1
  overlay-sizing/DPI. The chip CONTENT spec here (label + ETA + bar) is reusable when
  the projection lands.
- Q2. Lethal-incoming (priority 100) needs an explicit hp-at-fight predicate; confirm
  the field is in coach.fight_rule or derive from liveclient hp + active-combat flag.
  Grep before wiring (no assumed surface).
- Q3. Trinket-ready glyph (L2) is a Phase 4 build add; tier (AMBIENT make-aware) and
  pulse rule (one-shot on ready edge) are fixed here.

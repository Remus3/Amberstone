# RC 2.0 Phase-1 Research (stage 1.5): IN-MATCH Overlay References

Topic: what in-game overlays show DURING a live League match, how they keep it
glanceable + non-intrusive, and which patterns RC can legally lift. Overlay-centric
framing: the lean glanceable HUD over the game is RC's primary in-game surface.

ASCII only (repo hard rule). All external claims carry an inline source URL.
Authored 2026-06-19. Companion docs: RC2_RESEARCH_lobby.md, RC2_RESEARCH_timeline.md.

--------------------------------------------------------------------------------
## 0. RC's CURRENT in-game overlay surface (ground truth, cited file:line)
--------------------------------------------------------------------------------

RC already ships an in-game overlay (the OVL1 / HZ-D1 Electron shell). It is not a
greenfield. Establishing the current info set so the lift checklist below can say
"already HAVE it" accurately.

FORM FACTOR (what the overlay physically is):
- A transparent always-on-top Electron window over the Borderless game, Surface B.
  `docs/ELECTRON_OVERLAY.md:20`.
- The web layer is the SAME dashboard served at `?overlay=1`; main.js stamps
  `body[data-shell="overlay"]` on the first frame so `web/css/overlay.css` owns the
  layout before any 1920 grid paints. `web/js/main.js:59-66`.
- Footprint: a compact single-column dock ~460px wide, anchored to the RIGHT edge.
  `web/css/overlay.css:8-13`, `web/css/overlay.css:64` (width:460px).
- Click-through state machine: PASSIVE = `setIgnoreMouseEvents(true,{forward:true})`
  (clicks pass to the game); ACTIVE = `setIgnoreMouseEvents(false)` (panels take
  clicks). `docs/ELECTRON_OVERLAY.md:104-107`.
- Hotkeys: `Alt+Shift+O` show/hide, `Alt+Shift+A` PASSIVE<->ACTIVE,
  `Alt+Shift+C` cycle panel set (coach / build / threat / map).
  `docs/ELECTRON_OVERLAY.md:145-147`.
- Auto-revert to PASSIVE after N idle seconds, default 20s, clamp [3,120]. This is
  the anti-focus-steal guard. `web/js/lib/overlay_settings.js:23,27-31`,
  `docs/ELECTRON_OVERLAY.md:212`.
- Panel-set subsetting: coach / build / threat each narrow which panes show.
  `web/css/overlay.css:181-213`.
- GPU-light by rule: no blur, no looping animation; canvas widgets (spike curve,
  ward heat, DS cluster) are hidden in overlay. The ONLY motion is a one-shot
  `.ov-pulse` edge glow on content change (~1.2s). `web/css/overlay.css:17-20,86-95`,
  `web/css/overlay.css:269-280` (ov-pulse-edge keyframe).

WHAT THE OVERLAY SHOWS TODAY (the rendered subset):
The overlay shows the CALL pane + BUILD pane from `#view-active-match` plus the
deterministic callouts / lead / A+B-choice mounts from `#right-now`.
`web/css/overlay.css:10-16`.

1. RIGHT NOW / coach CALL (the headline action). active_match.js renders
   immediate -> action -> objective -> next as labeled lines.
   `web/js/panels/active_match.js:245-250`. The dashboard headline path
   (right_now.js) classifies the action into urgent/fight/good bands, prefixes a
   priority glyph, and one-shot pulses on text change.
   `web/js/panels/right_now.js:472-509`.
2. Deterministic OBJECTIVE / SPIKE CALLOUTS (server-computed, ZERO LLM). Up to 3
   rows, each line + an ETA chip ("NOW" or "M:SS"). `web/js/panels/callouts.js:64-96`,
   `web/js/panels/callouts.js:132-149`. Source generator `core/event_callouts.py`
   carries hardcoded SR objective spawns: dragon 5:00 (300s cadence), Rift Herald
   14:00, Baron 20:00, plus inhibitor respawn (300s). `core/event_callouts.py:76-79`,
   `core/event_callouts.py:328-332`.
3. MACRO LEAD projection pill (ahead/behind/even + magnitude tag).
   `web/js/panels/callouts.js:49-57,111-130`.
4. A+B coach CHOICES (Alt+1/2/3 hotkey-selectable trade / all-in / back-off chips).
   `web/js/panels/coach_choices.js` mounts to `#rn-choices`; right_now.js hides the
   prose Immediate slot when choices exist. `web/js/panels/right_now.js:526-527`.
5. BUILD pane: live DS next-item rerank (POST /api/ds-preview every 4s), top-5 item
   strip, OWNED row, conditional DEFENSE picks, enemy THREATS damage-mix strip.
   `web/js/panels/active_match.js:291-378`.
6. RECALL / back-timing directive: `recall_callout()` emits a "you can afford your
   next core item" back-timing signal. `core/event_callouts.py:281` and
   `dashboard/_deterministic_coaching.py:57-63`.

WHAT IS COMPUTED but currently HIDDEN in the overlay subset (dashboard-only):
- Power-spike MARKERS strip (level 6/11/16 + item 1/2/3, crossed/next/future).
  `web/js/panels/spike_markers.js:129-208`. Hidden in overlay: `overlay.css:88`.
- Spike-curve sparkline (team power over time). Hidden in overlay: `overlay.css:87`.
- Enemy summoner-spell + ult COOLDOWN LEDGER (the CDS pane / cd_ledger). Hidden in
  the base subset, re-enabled ONLY in the `threat` panel set.
  `web/css/overlay.css:81-85,206-210`, renderer `web/js/panels/cd_ledger.js`.
- Cooldown-WATCH card (per-enemy highest-threat hard-CC ability + base CD,
  GET /api/cooldown-watch). `web/js/panels/cooldown_watch.js:97-134`.
- Ward-coverage heat strip + the live MAP pane with enemy dots / MIA / gank-warn
  band. `web/js/panels/active_match.js:659-918`. Hidden in overlay: `overlay.css:82`.

NET: RC's engine already PRODUCES nearly every competitor in-game feature (objective
timers, power spikes, enemy cooldowns, ward coverage, jungle/MIA tracking,
next-item, recall timing). The RC2 gap is almost entirely PRESENTATION: most of it
is computed but gated out of the 460px overlay, and the overlay has no information
PRIORITY model deciding what earns the scarce mid-fight slots. That reframes this
research from "what to build" to "what to surface, in what priority, glanceably".

--------------------------------------------------------------------------------
## 1. What competitor in-game overlays show DURING a match
--------------------------------------------------------------------------------

Four apps studied: Overlay App F (on Overlay Platform M), Overlay App E, Aggregator C (on Overlay Platform M),
Aggregator A Desktop. Findings condensed; per-claim source URLs inline.

### 1.1 Objective timers (drake / baron / herald) + enemy jungle camps

- Overlay App E: strongest documented timer suite - "Know exactly when Jungle Camps,
  Inhibitors, and Dragon respawn times are in real time"; camp timers AUTO-START
  when a camp is cleared and render as a MINIMAP overlay (drawn on/near the minimap).
  https://review-site-z9.invalid/blog/game-analytics/overlay-app-e-gg-overlay-review ,
  https://overlay-app-e.invalid/overlays/lol?select=minimapTimer
- Aggregator A: jungle monster + Scuttle respawn timers drawn ON the minimap, but
  "Herald/Baron excluded"; inhibitor respawn timers for both sides; ARAM health-relic
  timers. https://aggregator-a.invalid/desktop/en/overlays/lol
- Overlay App F: "Jungle and Objective Timers" (dragon/baron/herald wrapped under
  "major objective respawn times"); enemy camp respawn is the headline jungle
  feature. https://overlay-platform-m.invalid/app/overlay-app-f
- Aggregator C: "jungle timers" listed, plus objective COUNTS (towers/drakes/elder/
  barons) as a stat comparison - not confirmed as live spawn countdowns.
  https://overlay-platform-m.invalid/app/aggregator-c
- KEY CONTEXT: as of patch 25.17 Riot shipped NATIVE jungle camp timers into the
  base client; community + Riot both call the native version "too powerful", so the
  flagship third-party jungle-timer feature is now partly redundant.
  https://www.pcgamesn.com/league-of-legends/lols-new-jungle-timers-are-making-tracking-too-easy-and-riots-on-the-case

### 1.2 Jungle tracking / enemy jungler pathing

- NONE of the four does live enemy-jungler POSITION prediction. Aggregator A draws a
  STATIC most-common path for YOUR selected champ on the minimap (not the enemy's
  live route). https://aggregator-a.invalid/desktop/en/overlays/lol . overlay-app-f/overlay-app-e give camp
  timers the player uses to INFER pathing.
  https://www.pcgamesn.com/league-of-legends/lols-new-jungle-timers-are-making-tracking-too-easy-and-riots-on-the-case
- RC already does better than all four here: live MIA badges + a gank-warning band
  when an enemy is missing past threshold. `active_match.js:888-906`.

### 1.3 Summoner-spell + ultimate cooldown trackers ("flash tracker")

- Overlay App E: tracks enemy summoner spells AND enemy ultimates (event-triggered, e.g.
  "When you see Zed activate Death Mark, Overlay App E starts a timer"); also shows TEAMMATE
  ult timers on ally portraits.
  https://review-site-z9.invalid/blog/game-analytics/overlay-app-e-gg-overlay-review
- Overlay App F: enemy ULTIMATE tracker only, MANUAL click-to-start, does not account
  for Ability Haste (approximate); no flash/summoner tracking documented.
  https://www.dexerto.com/league-of-legends/popular-league-of-legends-add-on-criticized-for-adding-cheat-feature-players-think-should-be-banned-3142237/
- Aggregator A: the spell/skill tracker overlay was REMOVED "due to policy changes by
  Riot Games ... an unavoidable removal in accordance with Riot's policies".
  https://aggregator-a.invalid/help/articles/48461098284953-The-spell-skill-tracker-overlay-is-no-longer-available
- Aggregator C: a "Summoner Spell Timer" is named; no live enemy-ult tracker
  documented. https://overlay-platform-m.invalid/app/aggregator-c

### 1.4 Recall / back-timing prompts

- NONE of the four documents a recall/back-timing prompt. RC's `recall_callout()` is
  a genuine differentiator. https://aggregator-a.invalid/desktop/en/overlays/lol ,
  https://aggregator-c.invalid/lol-overlay/

### 1.5 Build / next-item prompts live in-game

- Overlay App E: imports builds/runes/summoners; suggests item builds by champion/role/meta;
  live damage calc on shop hover ("how much damage your abilities deal post-purchase").
  https://review-site-z9.invalid/blog/game-analytics/overlay-app-e-gg-overlay-review
- Aggregator C: "Gold to Next Item Tracker" live overlay tool + pre-match build paths.
  https://overlay-platform-m.invalid/app/aggregator-c
- Aggregator A: static popularity-derived item builds + skill order in overlay (no
  gold-to-next-item). https://aggregator-a.invalid/desktop/en/overlays/lol
- Overlay App F: build/rune import + tracking. https://overlay-platform-m.invalid/app/overlay-app-f

### 1.6 Power-spike / item-spike cues + live macro

- Aggregator C: strongest - live "powerspike notifications" plus per-role early/mid/late
  spike advice via the Tab+W Game Overview. https://overlay-platform-m.invalid/app/aggregator-c ,
  https://aggregator-c.invalid/lol-overlay/
- Overlay App E: shop-hover damage preview is the closest analog (item-impact, not a timeline
  spike alert). https://review-site-z9.invalid/blog/game-analytics/overlay-app-e-gg-overlay-review
- Aggregator A: no LoL power-spike feature (its "Spike Tracker" is Valorant-only).
  https://aggregator-a.invalid/desktop/en/overlays/lol
- RC already computes a richer spike model than any of them (level + item markers
  AND a per-minute team power curve with DPS), just hidden in overlay. See 0 above.

### 1.7 Ward / vision reminders

- Overlay App E: a TRINKET-READY cue - "highlighting your trinket when it's ready to be used"
  (a single pulse, not a paragraph). https://overlay-app-e.invalid/overlays/lol
- Aggregator A: control-ward usage COUNTER only; no suggested spots.
  https://aggregator-a.invalid/desktop/en/overlays/lol
- Overlay App F / Aggregator C: vision as post-hoc stats, no live placement reminder.
  https://overlay-platform-m.invalid/app/overlay-app-f
- NONE suggests WHERE to ward. RC has the ward-heat strip (coverage-by-lane) which is
  closer to a reminder than anything competitors ship.

### 1.8 Teamfight / positioning cues

- Direct "stand here / focus this" cues are largely ABSENT across all four (and are
  the ToS-riskiest class - see 3). Overlay App E ally-ult-on-portrait timers are the closest
  fight-readiness cue. RC's A+B trade/all-in/back-off choices + fight_rule + target
  priority already occupy this space.

### 1.9 On-screen FORM, footprint, opacity, glanceability philosophy

- Overlay App E: NOT one monolithic HUD and NOT hold-TAB. A set of independent, element-
  ANCHORED widgets (minimap region, ally portraits, shop, corner counters) toggled a
  la carte; at least one (CS) supports a momentary keybind to flash it on for 5s.
  https://overlay-app-e.invalid/overlays/lol , https://overlay-app-e.invalid/lol/in-game
- Aggregator A: split between minimap-drawn markers (timers, jungle path) and a toggleable
  stats/build panel; master toggle Shift+Tab (customizable; first key must be
  Ctrl/Shift/Alt); overlay size freely adjustable.
  https://aggregator-a.invalid/help/articles/48465006797721-How-to-enable-or-disable-the-in-game-overlay ,
  https://aggregator-a.invalid/help/articles/48464972983449-How-to-adjust-the-overlay-size
- Aggregator C: hotkey-gated TAB overlay (hold Tab + Q/W/E/S for sub-panels); draggable;
  has SCALING + TRANSPARENCY sliders + per-panel disable.
  https://aggregator-c.invalid/support/articles/5318411048205-How-can-I-change-the-overlay-position
- Overlay App F: Overlay Platform M in-game overlay drawn over League "without tabbing out";
  exact form/opacity not documented.
  https://www.pcgamesn.com/league-of-legends/overlay-app-f-overview
- DESIGN PHILOSOPHY: no app publishes a glanceability manifesto. The CONVERGENT
  pattern is: render info WHERE THE EYE ALREADY LOOKS (timers ON the minimap, ult
  timers ON portraits, a single trinket HIGHLIGHT pulse) rather than in a far-corner
  panel; plus a-la-carte toggles + momentary-reveal keybinds + transparency/scaling
  sliders as the non-intrusiveness levers. NO app documents a click-through toggle
  (RC's PASSIVE/ACTIVE machine is ahead here).

--------------------------------------------------------------------------------
## 2. Information PRIORITY + glanceable HUD design (cited UX literature)
--------------------------------------------------------------------------------

The hard question for an overlay-centric RC2 is not "what can we show" (RC computes
almost everything) but "what earns a scarce mid-fight slot, and how is it rendered so
it reads in a 1-2 second glance". The literature gives concrete, citable rules.

### 2.1 The glance budget is ~1.5-2.0 seconds

- NHTSA Visual-Manual Driver Distraction Guidelines: tasks should be doable with
  glances away from the primary scene of 2 seconds or less, cumulative 12s or less;
  the occlusion method uses a series of 1.5-second glances.
  https://www.federalregister.gov/documents/2012/02/24/2012-4017/visual-manual-nhtsa-driver-distraction-guidelines-for-in-vehicle-electronic-devices
  APPLY: treat 2.0s as the hard ceiling, 1.5s as the target, for ANY single overlay
  element. Eyes-off-the-fight == eyes-off-the-road == death/value risk.
- Glanceable = absorbed with minimal cognitive load while attention stays on the
  foreground task; if a panel must be READ, it has already failed.
  https://en.wikipedia.org/wiki/Ambient_device

### 2.2 Preattentive processing: only sub-250ms-parseable cues survive a fight

- Tasks parseable in under 200-250ms are "preattentive", processed in parallel BEFORE
  conscious attention; bounded because an eye movement takes >=200ms to initiate.
  https://www.csc2.ncsu.edu/faculty/healey/PP/
  APPLY: the mid-fight tier must use ONLY preattentive channels - color/hue (threat
  tier), size (importance), fixed position (identity), motion (emergencies). Anything
  requiring reading, counting, or comparison will NOT land in combat.
- POP-OUT requires a UNIQUE feature; a conjunction of shared features forces slow
  serial search. "A red circle among blue circles" pops; mixed features do not.
  https://www.csc2.ncsu.edu/faculty/healey/PP/
  APPLY: the single most-urgent cue must be the ONLY red / ONLY moving / ONLY large
  thing on the overlay at that instant. If five things are red, nothing pops.
- Channel hierarchy: MOTION is strongest, then COLOR dominates SHAPE.
  https://www.csc2.ncsu.edu/faculty/healey/PP/
  APPLY: reserve motion for the top emergency tier (rare); color for threat/urgency;
  icon/shape for low-priority categorical identity.
- Encode MAGNITUDE as bar length / position, NEVER as hue - people do not perceive
  colors as ordered. https://www.nngroup.com/articles/dashboards-preattentive/
  APPLY: HP fraction, cooldown remaining, gold lead = bar/position; color = discrete
  threat bins only (safe / caution / lethal).

### 2.3 What earns PERMANENT screen space (progressive disclosure + data-ink)

- Progressive disclosure: show only the few most-important items up front; defer the
  rest to a secondary view. Crucially - too much in the primary view stops the truly
  important thing from standing out and slows the user.
  https://www.nngroup.com/articles/progressive-disclosure/
  APPLY: the always-on overlay = primary (next action, key cooldown, imminent threat).
  Full build path, detailed stats, post-trade analysis = secondary, shown between
  fights or on a key. Budget ~1 primary + 2-3 supporting persistent slots; every
  addition WEAKENS the rest. (RC's panel-set cycle is already a disclosure mechanism.)
- Decide primary-vs-secondary by FREQUENCY-OF-USE, measured not guessed - rank
  candidates by how often a cue actually changes the next action.
  https://www.nngroup.com/articles/progressive-disclosure/
- Data-ink ratio: every pixel must be the data itself or a behavior-changing cue;
  strip borders, shadows, panel chrome, decoration - chrome competes for the glance.
  https://infovis-wiki.net/wiki/Data-Ink_Ratio

### 2.4 Game-HUD placement + clutter

- Diegetic / contextual HUDs work best when info sits in a PREDICTABLE FIXED spot or
  near where the player already looks; fixed-and-learnable beats smart-but-moving
  (the player stops "searching"). Dead Space's avatar-mounted health is the canonical
  win; Far Cry 2's player-uncontrolled fade in/out was a failure.
  https://medium.com/@salamatizm/the-minimal-hud-paradox-how-dreams-of-diegetic-game-interfaces-often-lead-to-cluttered-nightmares-e9cf7fae9d73 ,
  https://www.gamedeveloper.com/design/game-ui-discoveries-what-players-want
  APPLY: this is the single strongest argument to MOVE RC cues toward the eye - timers
  near the minimap, cooldowns near champion frames - the exact convergent competitor
  pattern in 1.9. The 460px right-dock is the far-corner anti-pattern for the most
  urgent cues; keep the dock for between-fight depth, but the emergency tier should
  live near the combat center-of-mass.
- A coaching overlay MAY be denser than a pure-immersion HUD (the player opted into
  help) - but every element must be tiered essential-vs-optional, with the optional
  ones faded during combat. https://www.gamedeveloper.com/design/game-ui-discoveries-what-players-want

### 2.5 Alerting / interruption: motion is a scarce resource

- Use a graded notification ladder (Ignore / Change-blind / Make-aware / Interrupt /
  Demand-attention); match intensity to urgency.
  http://www.madpickle.net/scott/pubs/p321-matthews.pdf
  APPLY: most RC coaching = Change-blind/Make-aware (updates quietly, no motion). Only
  genuine emergencies (lethal incoming, dragon-steal window, must-flash-now) escalate
  to motion/flash. Assign each coaching message a tier at author time.
- Motion/flash is the boy-who-cried-wolf channel; overuse causes alarm fatigue and
  missed real alerts (clinically 80-99% of monitor alarms are false; staff
  desensitize). The fix is to raise the VALUE of each alert, never add more.
  https://psnet.ahrq.gov/perspective/reducing-safety-hazards-monitor-alert-and-alarm-fatigue
  APPLY: ration RC's pulse channel ruthlessly. RC today pulses the action headline on
  EVERY text change (right_now.js:490-500) - under this rule, that should fire only
  for the urgent band, not for every benign re-emit.
- Never center-screen-obstruct and never require a click to dismiss mid-fight; an
  alert that lingers/obstructs is worse than none. Alerts should self-expire and sit
  off the combat center-of-mass.
  https://www.designer-daily.com/the-design-of-interruption-ethical-patterns-for-notifications-and-attention-management-211140
- Interrupt gate: "does the player need to change their action in the next ~1s or lose
  value?" If no, demote to a quiet make-aware update.
  https://www.atlassian.com/incident-management/on-call/alert-fatigue

### 2.6 The 10 synthesized rules for the RC2 combat overlay

1. ONE-GLANCE BUDGET: every persistent element answerable in <=1.5s (2.0s ceiling).
2. THREE TIERS: Ambient (quiet, always-on) / Urgent (color+size) / Emergency
   (motion, self-expiring). Tag each coaching message at author time.
3. PREATTENTIVE-ONLY in the combat tier: color/size/position/motion, NO text-to-read.
4. ENFORCE POP-OUT: the top cue is the ONLY red / ONLY moving / ONLY large thing.
5. RATION MOTION: flash only for near-certain action-changing events.
6. NEVER center-obstruct or require mid-fight dismissal; alerts self-expire.
7. PRIMARY BUDGET: 1 primary + ~2-3 supporting persistent slots; defer the rest.
8. MAXIMIZE DATA-INK: strip chrome; redundant-encode ONLY the single top cue.
9. FIXED, LEARNABLE POSITIONS beat smart-but-moving; move urgent cues toward the eye.
10. QUANTITIES as bar/position, CATEGORIES as color - never magnitude-in-hue.

--------------------------------------------------------------------------------
## 3. Riot ToS / approved-app boundary (load-bearing constraint)
--------------------------------------------------------------------------------

Overlay Platform M's own Riot compliance guide for developers explicitly FORBIDS, for approved
apps: ultimate timers ("strictly forbidden ... unfair advantage"), tracking of enemy
ability cooldowns AND summoner-spell cooldowns, notifications that alert on a power
spike, and notifications that DICTATE player action based on game state.
https://overlay-platform-m.invalid/dev/native/guides/game-compliance/riot-games/
Corroborated by Aggregator A's forced removal of its spell/skill tracker "in accordance with
Riot's policies".
https://aggregator-a.invalid/help/articles/48461098284953-The-spell-skill-tracker-overlay-is-no-longer-available

WHY THIS DOES NOT BLOCK RC (but must be recorded): RC is a SINGLE-PLAYER LOCAL tool
reading the Riot-sanctioned Live Client Data API at :2999 (ADR-006, ADR-011); it is
not a distributed Overlay Platform M/approved app and does not face the approval regime. RC also
already ships enemy cooldown ledgers + power-spike markers + "do X now" prompts.
THIS IS AN AWARENESS FLAG for any future public-distribution pivot (see
project_pre_release_name_scrub) - the exact features Riot polices are the ones RC
leans on. If RC2 ever ships as a public approved app, the enemy-cooldown ledger,
ult/summoner trackers, power-spike alerts, and action-dictating prompts are the
re-scope surface. Legal re-implementation ONLY throughout this doc.

--------------------------------------------------------------------------------
## 4. LIFT checklist (6-point, per external pattern)
--------------------------------------------------------------------------------

Format: WHAT / HOW / RC ALREADY HAS (file:line) / WHERE it integrates / EFFORT+RISK /
LIFT verdict. Legal re-implementation only.

### L1. Minimap-anchored objective + camp timers (Overlay App E / Aggregator A)
- WHAT: dragon/baron/herald + jungle-camp respawn countdowns rendered ON or beside the
  minimap, where the eye already rests.
- HOW: draw timer chips at minimap-adjacent screen coords; auto-start camp timers on
  Live Client kill events.
- RC ALREADY HAS: the DATA (objective spawns `core/event_callouts.py:76-79`; the live
  MAP pane with projection `active_match.js:659-918`) but renders timers as TEXT
  callout rows in the right dock (`callouts.js:83-96`), not anchored to the minimap;
  and the MAP pane is HIDDEN in overlay (`overlay.css:82`).
- WHERE: move/duplicate the callout ETA chips onto the overlay map pane; un-gate
  `.am-pane-map` for a "map" panel set with timer chips.
- EFFORT+RISK: MED effort (coordinate projection already exists in
  `active_match.js:850-853`), LOW risk (pure presentation of data RC owns).
- LIFT: HIGH. This is the single highest-value glanceability win - it directly applies
  rule 9 (move cues to the eye) and matches the convergent competitor pattern, using
  data RC already computes.

### L2. Trinket-ready single-pulse vision reminder (Overlay App E)
- WHAT: a one-shot highlight/pulse when the player's trinket (or control ward) is off
  cooldown, instead of a vision paragraph.
- HOW: Live Client summoner/trinket cooldown -> when it crosses ready, fire the
  existing `.ov-pulse` one-shot on a small ward glyph.
- RC ALREADY HAS: the pulse primitive (`overlay.css:269-280`), the cd_ledger that
  tracks cooldowns (`cd_ledger.js`), and a ward-heat strip (`ward_heat.js`). No
  trinket-ready cue specifically.
- WHERE: a tiny always-on ward glyph in the overlay dock or near the minimap; drive
  off the cooldown feed already threaded via ctx.cooldowns (`active_match.js:398-405`).
- EFFORT+RISK: LOW effort, LOW risk.
- LIFT: HIGH. Cheap, glanceable, fills a vision-reminder gap no competitor fully
  covers, and is a textbook rule-2 Make-aware cue (no reading required).

### L3. Live "what to do now" power-spike + macro cue (Aggregator C)
- WHAT: a live spike notification + a one-line macro read ("you spike now - fight"),
  the one area Aggregator C genuinely leads.
- HOW: surface the already-computed spike markers + lead projection as a single
  preattentive Urgent-tier cue when a spike crosses.
- RC ALREADY HAS: spike markers (`spike_markers.js`), spike curve, lead projection
  (`callouts.js:111-130`), A+B fight choices. The spike strip is HIDDEN in overlay
  (`overlay.css:88`).
- WHERE: promote a single "spike crossed" Urgent cue into the overlay coach pane on
  the crossing tick (self-expiring), keep the full strip for the dashboard.
- EFFORT+RISK: MED effort (needs the tiering/crossing-edge logic, not just unhide),
  LOW-MED risk (tune so it does not over-fire - rule 5).
- LIFT: HIGH. Matches the one competitor strength, on data RC owns; the work is the
  PRIORITY/tier model (section 2), not new compute.

### L4. Enemy ult/summoner cooldown glance (Overlay App E / Overlay App F)
- WHAT: enemy flash/ult availability shown compactly (Overlay App E event-triggered;
  Overlay App F manual-click).
- RC ALREADY HAS: the cd_ledger / cooldown-watch fully built
  (`cd_ledger.js`, `cooldown_watch.js:97-134`), exposed only in the `threat` panel set.
- WHERE: already wired - this is a panel-set/priority decision, not new build.
- EFFORT+RISK: LOW effort, but ToS-HOT for any future public app (section 3).
- LIFT: MED. Technically near-free for RC's local use, but flagged MED because it is
  the most ToS-sensitive class if RC ever distributes - lift the PRESENTATION, keep
  the awareness flag.

### L5. A-la-carte toggle + transparency/scaling sliders (Aggregator C / Aggregator A / Overlay App E)
- WHAT: per-element show/hide + opacity + scale, so the user tunes intrusiveness.
- RC ALREADY HAS: panel-set cycling (`overlay.css:181-213`), a pulse-notify toggle +
  active-revert-seconds setting (`overlay_settings.js:23`). No opacity or scale slider,
  no per-element toggle.
- WHERE: extend `overlay_settings.js` schema with opacity + scale; wire to the dock
  panes' alpha/transform.
- EFFORT+RISK: LOW-MED effort, LOW risk.
- LIFT: MED. Standard table-stakes non-intrusiveness lever; nice but lower-value than
  L1-L3 because RC already has the click-through machine they lack.

### L6. Static most-common jungle path on minimap (Aggregator A)
- WHAT: draw YOUR champ's statistical jungle route on the minimap.
- RC ALREADY HAS: jungle pathing exists as a STAT field (`st-jungle-path` in
  right_now.js:332), and RC already does superior LIVE MIA/gank tracking
  (`active_match.js:888-906`).
- WHERE: the overlay map pane.
- EFFORT+RISK: LOW-MED effort, LOW risk - but low value since RC's live tracking
  already dominates a static path, and it only helps the jungle role.
- LIFT: LOW. De-prioritize; RC's live tracking is strictly better.

--------------------------------------------------------------------------------
## 5. Bottom line for RC2
--------------------------------------------------------------------------------

RC's in-game ENGINE already out-computes all four competitors (objective timers,
power spikes, enemy cooldowns, live MIA/gank tracking, next-item, recall timing -
section 0). The RC2 in-match overlay work is therefore a PRESENTATION + PRIORITY
project, not a feature-build project:

1. Apply the information-priority model (section 2.6): tier every cue, budget the
   460px dock to ~1 primary + 2-3 supporting slots, push the Emergency tier toward the
   minimap/champion frames (rule 9), and ration the motion/pulse channel (rule 5).
2. Lift the two convergent competitor PATTERNS RC lacks: minimap-anchored timers (L1)
   and a single-pulse trinket/vision reminder (L2) - both HIGH lift, both on data RC
   owns, both directly serving glanceability.
3. Match Aggregator C' one genuine lead with a tiered live spike/macro cue (L3).
4. Record the Riot ToS boundary (section 3) against the cooldown-tracker / power-spike
   / action-dictating features for any future public-distribution pivot.

Sources are cited inline throughout. No competitor code is lifted - legal
re-implementation of public-data presentation patterns only.

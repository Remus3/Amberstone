# RC 2.0 - Operator Q/A TODO + Future List

> RC 2.0 Phase 8.1 deliverable (Stage 8.1 of `docs/RC2_PLAN.md`). Authored 2026-06-19.
> ASCII only - no em-dashes, en-dashes, or smart quotes (repo hard rule).
>
> PURPOSE: one consolidated decision queue the operator can Q/A AFTER the RC2 build
> stage. Synthesized from `docs/RC2_PLAN.md`, the 9 `docs/research/RC2_RESEARCH_*.md`
> files, `docs/DS_COMPLETENESS_GAP.md`, `ROADMAP.md` open items, and `BACKLOG.md`.
> De-duplicated against what the RC2 phases already cover - items the RC2 plan already
> schedules are tagged `[RC2 Pxx]` so the operator knows they are in-flight, not new.
>
> HOW TO USE: each item carries a one-line description, EFFORT (S/M/L), VALUE
> (high/med/low), DEPENDENCY, SOURCE (file or research doc), and a crisp Q/A PROMPT to
> answer yes/no/defer. Within each section, highest-value-lowest-effort items come
> first. The TOP 10 DECISIONS shortlist is at the end.
>
> KEY for tags:
> - `[RC2 Pxx]` = already a stage in the RC2 plan (Phase xx); listed for context + to
>   let the operator confirm/re-scope, not re-discover.
> - `[NEW]` = surfaced by research/gap analysis but NOT yet a plan stage.
> - `[FLIP]` = code is SHIPPED default-OFF; the decision is a live-game eyeball + toggle,
>   not new code. These all route through `docs/LIVE_GAME_GATED_SYNC.md`.
> - `[GATED]` = blocked on a live game, a data source, or operator product judgment.

---

## SECTION 1 - OVERLAY / IN-GAME UX

The single largest RC2 theme. Research verdict (RC2_RESEARCH_in_match_overlay.md): RC's
engine already OUT-COMPUTES all four competitors (objective timers, power spikes, enemy
cooldowns, MIA/gank, next-item, recall). The work is PRESENTATION + PRIORITY, not new
features. Highest-value-lowest-effort first.

1. **Single-pulse trinket/vision-ready cue (L2).** [NEW] One-shot `.ov-pulse` on a ward
   glyph when trinket/control-ward comes off cooldown - no vision paragraph. EFFORT S /
   VALUE high. DEP: none (pulse primitive + cd feed already exist). SRC:
   RC2_RESEARCH_in_match_overlay.md L2. Q: ship the trinket-ready single-pulse cue now
   (S, fills a gap no competitor fully covers) or defer?

2. **Dashboard STAYS while overlay active (fix the disappear bug).** [RC2 P3 stage 3.4]
   The operator-named bug: the dashboard currently vanishes when the overlay shows.
   EFFORT M / VALUE high. DEP: none. SRC: RC2_PLAN.md stage 3.4, operator directive. Q:
   confirm 3.4 (dashboard + overlay coexist) is in-scope for the build now, or is the
   2nd-window/toggle model enough?

3. **Ration the motion/pulse channel (rule 5).** [NEW] RC pulses the action headline on
   EVERY text change (right_now.js:490); the literature says flash only for the urgent
   band or it becomes alarm-fatigue noise. EFFORT S / VALUE high. DEP: tier-tagging each
   coach message. SRC: RC2_RESEARCH_in_match_overlay.md 2.5/rule 5. Q: restrict the
   overlay pulse to the urgent tier only (S) or keep pulsing on every re-emit?

4. **Minimap-anchored objective + camp timers (L1).** [NEW] Move the dragon/baron/herald
   + camp ETA chips ONTO/beside the overlay map pane (where the eye already rests) instead
   of text rows in the right dock. EFFORT M / VALUE high. DEP: un-gate `.am-pane-map` in
   overlay; coord projection already exists. SRC: RC2_RESEARCH_in_match_overlay.md L1,
   rule 9. Q: build minimap-anchored timer chips now (M, the single biggest glanceability
   win) or keep the right-dock text callouts?

5. **DPI / scaleFactor-aware overlay sizing (LIFT-C).** [RC2 P4 stage 4.1] RC sizes the
   overlay in a fixed ~460px box and never reads `scaleFactor` - clips at 125/150% Windows
   scaling or non-1920 borderless (the documented Overlay App F failure). EFFORT M / VALUE
   high. DEP: overlay UI-audit ritual. SRC: RC2_RESEARCH_overlay_sizing.md LIFT-C, stage
   4.1. Q: make the overlay DPI/resolution-adaptive now (M) or accept the exact-1920/100%
   baseline only?

6. **Fullscreen detect-and-nudge "switch to Borderless" hint (LIFT-A).** [NEW] A DWM
   overlay is invisible under exclusive fullscreen; today RC shows a silently-dead HUD.
   Read the League HWND window style (read-only, AC-safe) and surface a one-line hint.
   EFFORT S / VALUE high. DEP: none. SRC: RC2_RESEARCH_overlay_sizing.md LIFT-A. Q: add
   the borderless-nudge guard now (S, closes a specced-but-unbuilt mitigation) or rely on
   the operator always running Borderless?

7. **Live spike/macro "what to do now" cue, tiered (L3).** [NEW] Promote a single
   self-expiring Urgent cue into the overlay coach pane on a spike-crossing tick (matches
   Aggregator C' one genuine lead). EFFORT M / VALUE high. DEP: the tier/crossing-edge model.
   SRC: RC2_RESEARCH_in_match_overlay.md L3. Q: surface a tiered spike-crossed cue (M, tune
   so it does not over-fire) now or defer to the priority pass?

8. **Settings UI: change everything WITHOUT hotkeys.** [RC2 P3/P4 stages 3.5/4.4] Operator
   directive: every setting changeable from a surface, not only hotkeys. EFFORT M / VALUE
   high. DEP: overlay settings schema (partly exists: pulse toggle + revert seconds). SRC:
   RC2_PLAN.md 3.5/4.4, operator directive. Q: confirm the no-hotkey settings surface scope
   - per-element toggle + opacity + scale sliders + panel-set picker all in?

9. **"Fight mode" declutter (A2/A4).** [NEW] A `body.fight` class that strips the overlay
   to the single act-now cue during combat (aviation-HUD declutter-as-a-mode). EFFORT M /
   VALUE med. DEP: a reliable "in a fight" signal from the game reader. SRC:
   RC2_RESEARCH_nonleague_uiux.md A2/A4. Q: build an auto-declutter fight mode (M, needs a
   conservative combat trigger so it never hides info mid-fight) or keep one fixed layout?

10. **Opacity + scale + per-element toggle sliders (L5).** [NEW] Table-stakes
    non-intrusiveness levers competitors ship; RC has the click-through machine they lack
    but no opacity/scale slider. EFFORT S-M / VALUE med. DEP: extend overlay_settings.js.
    SRC: RC2_RESEARCH_in_match_overlay.md L5. Q: add opacity/scale/per-element sliders now
    or fold into the settings-surface stage (item 8)?

11. **Segmented peripheral timer meter (A1) + ring gauges (A3).** [NEW] A 5-7-segment
    color-zoned bar for objective/recall/spike countdowns, read in peripheral vision; plus
    pure-CSS conic-gradient ring gauges for HP%/gold-diff. EFFORT M / VALUE med. DEP:
    overlay redesign. SRC: RC2_RESEARCH_nonleague_uiux.md A1/A3. Q: add the segmented-meter
    + ring-gauge primitives (M, best slotted into the overlay redesign) or skip?

12. **Always-on-core vs contextual-band overlay structure (A4).** [NEW] A permanent core
    (top action + danger/HP) and a band that swaps by phase (laning -> objective ->
    teamfight). EFFORT M / VALUE med. DEP: the fight-mode state machine (item 9). SRC:
    RC2_RESEARCH_nonleague_uiux.md A4. Q: restructure the overlay into core+contextual bands
    (M, bundle with items 9/11) or keep the flat 460px dock?

13. **Elevation parity guard (LIFT-F).** [NEW] If League runs elevated, the overlay must
    match integrity level or Windows UIPI blocks it. Not a problem today (neither elevated).
    EFFORT S-M / VALUE low. DEP: none. SRC: RC2_RESEARCH_overlay_sizing.md LIFT-F. Q: add
    the elevation-parity detect-and-hint (S) or leave it until League is ever run elevated?

14. **Pick overlay display by RESOLUTION not index (LIFT-B).** [NEW] Already satisfied by
    the 1-PC primary==game-monitor assumption; only matters if multi-monitor returns. EFFORT
    S / VALUE low. DEP: none. SRC: RC2_RESEARCH_overlay_sizing.md LIFT-B. Q: harden
    display-pick-by-resolution now or leave under the current 1-PC constraint?

---

## SECTION 2 - DASHBOARD / SURFACES (home, lobby, champ-select, PGR, history, timeline)

Cross-cutting research finding: RC's plumbing is best-in-class; the gaps are
presentation/insight, almost all reusing data already on disk. Ordered by value/effort
within each surface group.

### 2A. HOME

15. **Recent-form W/L color strip + real season WR.** [NEW] Replace the "(needs Riot key)"
    stub - `rewind_history.db` has `tracked_win` for ~2846 matches. A last-20 W/L pip strip
    + true WR. EFFORT LOW-MED / VALUE high. DEP: capture win on end-of-game ingest (the
    keystone, see item 18). SRC: RC2_RESEARCH_home_profile.md P-B, RC2_RESEARCH_history.md
    P2. Q: add the W/L strip + real WR now (retires a stub using data on disk) or defer?

16. **Score DECOMPOSITION under the hero grade.** [NEW] Render the already-returned
    `post_game_rubric.components` (+ carry_share / obj_participation) as per-axis sub-bars so
    the single 0-100 is explainable. EFFORT LOW / VALUE high. DEP: none (data already
    computed). SRC: RC2_RESEARCH_pgr.md section 2. Q: surface the score decomposition now
    (cheap, most coaching-useful aggregator-G-flavored add) or keep the bare number?

17. **Weekly summary digest card.** [NEW] A "this week you..." card synthesizing the
    existing this_week + 14d trends + Good/Bad/Ugly tips. EFFORT S-M / VALUE med. DEP: none
    (all inputs in the payload). SRC: RC2_RESEARCH_home_profile.md P-G. Q: build the weekly
    digest card (good ROI, fully local) or skip?

18. **Rank/tier/LP identity header.** [GATED] The one universal element RC lacks - but the
    operator plays mostly ARAM/Arena/event modes where solo rank is stale/absent. EFFORT M /
    VALUE med. DEP: LCU ranked read + a graceful "Unranked" state. SRC:
    RC2_RESEARCH_home_profile.md P-A. Q: add a rank/LP header WITH an empty-state fallback,
    or skip it because the operator is not a ladder grinder?

19. **Champ-pool table per-champ trend arrow.** [NEW] Extend THIS WEEK rows with a
    recent-vs-baseline KDA arrow + "best results" badge (logic already exists at
    main.js:1540). EFFORT S / VALUE med. DEP: none. SRC: RC2_RESEARCH_home_profile.md P-E.
    Q: add the per-champ trend arrow (small additive polish) now or skip?

20. **GPI single-match dot on the longitudinal radar.** [NEW] Overlay this match's 8 axis
    values on the existing player_gpi radar so the post-game shows which axis the game moved.
    EFFORT LOW-MED / VALUE med. DEP: none (radar + axis math exist). SRC:
    RC2_RESEARCH_pgr.md section 3. Q: add the this-match radar dot now or defer?

### 2B. LOBBY

21. **Last-session recap on home/lobby.** [NEW] Today's W/L + streak + tilt nudge pre-queue;
    session-boundary rules already defined. EFFORT LOW-MED / VALUE high. DEP: own data only.
    SRC: RC2_RESEARCH_lobby.md Pattern B. Q: add the last-session recap (fills a confirmed
    gap, zero external dep) now or defer?

22. **Finish ready-check auto-accept.** [NEW] Connect the existing Auto-Accept toggle (Phase
    A, state-only) to the already-wrapped read+accept calls so a pop is not missed while
    reading the dashboard. EFFORT LOW / VALUE high. DEP: none. SRC: RC2_RESEARCH_lobby.md
    Pattern E. Q: wire auto-accept live now (finishes a half-built UI the operator already
    sees) or leave manual?

23. **Duo synergy at the lobby for a 2-man party.** [NEW] Re-stage the already-shipped
    `/api/duo-synergy` to fire when a party >= 2 forms (currently champ-select-only). EFFORT
    LOW-MED / VALUE high. DEP: gate on lobby.members.length. SRC: RC2_RESEARCH_lobby.md
    Pattern C. Q: surface duo synergy at the lobby now (reuses a shipped data lane) or keep
    it champ-select-only?

24. **Party/Top8 recent-form chips (scoped player tags).** [NEW] Overlay App F-style tags but
    only for YOUR party + Top 8 (enemies are not visible until champ select). EFFORT MED /
    VALUE med. DEP: tag heuristics over rewind_history.db + a route. SRC:
    RC2_RESEARCH_lobby.md Pattern A. Q: add party/Top8 recent-form chips (limited value at
    lobby) now or defer to champ-select scouting (item 27)?

### 2C. CHAMP-SELECT

25. **Counter-picks vs the LIVE enemy comp (P2).** [NEW] The top champ-select lift: a "pick
    X into this comp" list for the operator's slot. 80% of plumbing exists (counters index +
    live enemy ids + suggestions panel + ban-intent click). EFFORT LOW-MED / VALUE high. DEP:
    may need a global counters blend for unfaced champs. SRC: RC2_RESEARCH_champ_select.md
    P2. Q: build live counter-picks (highest payoff-to-effort, wins the glance) now or defer?

26. **Ban-suggestion reason labels + ally AD/AP damage-profile (P7 + P8).** [NEW] Label each
    suggested ban with its reason (your-losses / lane-meta / global) and add an SR ally AD/AP
    balance read ("we need more AP"). EFFORT LOW-MED / VALUE med. DEP: champion-tags index
    already classes champs. SRC: RC2_RESEARCH_champ_select.md P7/P8. Q: fold reason-labels +
    SR ally damage-profile into the counter-picks slice (item 25) or skip?

27. **Enemy/ally player scouting table (P4).** [GATED] Overlay App F's whole moat: per-player
    rank + mains + tags during champ-select, legal via RC's Riot key (ADR-006). EFFORT
    MED-HIGH / VALUE med. DEP: 10-player Riot fan-out in a 30s window - rate-limit + cache +
    partial render. SRC: RC2_RESEARCH_champ_select.md P4. Q: build the scouting table now
    (Riot-rate-limited, phase it ranks->mains->tags) or defer to FUTURE?

28. **Arena augment tier ratings keyed to champion (P6).** [GATED] Grade each offered augment
    (UI slots + intent-write already work; needs an augment-tier dataset; DS does not model
    Arena augments). EFFORT MED / VALUE med. DEP: an augment-tier data source (Riot forbids
    augment WINRATE; pick-rate is allowed). SRC: RC2_RESEARCH_champ_select.md P6. Q: source
    an augment-tier table and ship the rating (a real timed sub-decision) or defer?

29. **Live per-pick draft win-% (P1, Draft Tool L).** [GATED] The most-differentiated competitor
    feature but RC's 2846-match DB is far too sparse for SR champ-pair cells - it would be a
    confident wrong number without a large dataset. EFFORT MED-HIGH / VALUE med. DEP: a
    credible champ-pair dataset (or frame as "draft notes" not a single %). SRC:
    RC2_RESEARCH_champ_select.md P1. Q: build a draft advantage meter ONLY if a dataset is
    adopted, otherwise close it - which?

30. **Auto rune/spell/item import toggle + fix RuneWriter game-2 bug.** [NEW] Import is fully
    shipped; the deltas are an AUTO toggle (push without a click each game) and the known bug
    that RuneWriter fires only on the first champ-select per RC session. EFFORT LOW / VALUE
    high (reliability). DEP: the bug fix needs an RC restart (not frozen). SRC:
    RC2_RESEARCH_champ_select.md P3, memory reference_runewriter_dies_after_game1. Q: fix the
    RuneWriter first-CS-only bug (higher value than any new feature) and add the auto-toggle
    now?

### 2D. POST-GAME REVIEW (PGR)

31. **Normalized carry-metrics bundle (damage-per-gold + damage-per-death + vision-per-min +
    SV ratio + @15 column).** [NEW] All inputs already in the roster + match_metrics; the
    highest-value PGR gap (damage-per-gold is the most honest carry metric). EFFORT LOW /
    VALUE high. DEP: one extra timeline frame lookup for @15. SRC: RC2_RESEARCH_pgr.md
    sections 4/5/8. Q: ship the normalized carry-metrics bundle now (cheap, high signal) or
    defer?

32. **aggregator-G-style PGR reframe (the long-standing big UI item, s220).** [GATED] The
    single-match richer layout; the 0-100 score is an RC heuristic with NO Claude/Riot dep,
    staged S2-S5, each its own session + UI-audit ritual. Most of the surface already ships.
    EFFORT M-L / VALUE high. DEP: a live standard-queue game + the per-page UI-audit ritual.
    SRC: ROADMAP/CLAUDE settled, RC2_RESEARCH_pgr.md section 0. Q: schedule the remaining PGR
    reframe stages now or keep deferred until a live SR game window?

33. **Timeline OP-Score trajectory (per-phase curve in the roster).** [NEW] aggregator A recomputes
    the score on a 5min/3min cadence; RC's is final-only. Reuses timeline_frames + the
    op_score.js curve primitive. EFFORT MED / VALUE med. DEP: none (data + primitive exist).
    SRC: RC2_RESEARCH_pgr.md section 1. Q: add the per-phase OP-score curve or leave the
    final-only score?

34. **carry-efficiency grade-axis fold (default-ON re-baseline).** [FLIP] gold_share + KP are
    already a DISPLAY stat and a DEFAULT-OFF grade fold (`compute_role_grade
    (carry_efficiency=True)`). The decision is the Tier-2 grade re-baseline. EFFORT S / VALUE
    med. DEP: a product/calibration sign-off (re-grades historic rows). SRC: BACKLOG R2 item
    1, DS_COMPLETENESS_GAP a2. Q: flip carry_efficiency grading default-ON (re-baselines
    grades) or keep it display-only?

### 2E. HISTORY

35. **Result-first history row (win color + KDA).** [NEW] The biggest scannability win for
    the least code - add `win` to the row SELECT + a left-border tint. Unblocks the W/L strip,
    result filter, and per-session W-L headers. EFFORT LOW / VALUE high. DEP: win must be
    stored on the match row (see item 18). SRC: RC2_RESEARCH_history.md P1. Q: add the
    win-colored history row now (land this first; it unblocks 3 other items) or defer?

36. **History list filters (champion / queue / result).** [NEW] Zero filters today on a
    2846-match archive; the Loadouts view already ships the exact filter widget to copy.
    EFFORT LOW-MED / VALUE high. DEP: decide filter-then-regroup vs filter-within-session.
    SRC: RC2_RESEARCH_history.md P4. Q: add champion/queue/result filters now or skip?

37. **Per-session W-L header (free after item 35).** [NEW] The session row shows date|Ng|
    duration but not W-L because win is not loaded; trivial once win lands. EFFORT TRIVIAL /
    VALUE med. DEP: item 35. SRC: RC2_RESEARCH_history.md P6. Q: enrich the session header
    with W-L (one string concat) once win is on the row - confirm?

38. **Richer history row (items/CS/grade pip) + expand-in-place accordion.** [NEW] Item icons
    + CS in the row (reuse `_itemImgTag`) and inline expand instead of routing away. EFFORT
    MED / VALUE med. DEP: which DB feeds the row (join rewind for items); UI-audit ritual.
    SRC: RC2_RESEARCH_history.md P3/P5/P7. Q: add the richer row + accordion (after items
    35/36) or keep the routed detail view?

### 2F. TIMELINE

39. **Gold/XP-diff chart + objective/kill event ribbon + "Story" wiring.** [NEW] Highest
    value-to-effort timeline slice: every data primitive is in `timeline_frames`/
    `timeline_events`; reuse the pgr_winprob split-area SVG idiom + existing WPA top_phases
    cards (click-to-highlight). Stay hand-rolled SVG (no charting dep). EFFORT LOW-MED / VALUE
    high. DEP: a thin new route over replay_history; SR perspective-flip logic exists. SRC:
    RC2_RESEARCH_timeline.md Patterns A/B/E. Q: build the gold-diff chart + event ribbon +
    story wiring as one PGR slice now or defer?

40. **Lane @10/@15 breakpoint view + phase bands.** [NEW] Extend pgr_lane_compare.js with a
    minute breakpoint; add 0-14/14-25/25+ phase-band rects behind the gold line. EFFORT
    LOW-MED / VALUE high. DEP: gate to SR (no lanes ARAM/Arena). SRC: RC2_RESEARCH_timeline.md
    Patterns C/D. Q: add the @10/@15 lane view + phase bands or defer behind item 39?

41. **Teamfight kill-clustering ribbon + map death heatmap.** [NEW] Cluster nearby kills into
    fights; plot kill_pos_x/y on a minimap. EFFORT MED / VALUE low-med. DEP: clustering
    heuristic (net-new); the map-image asset has licensing nuance. SRC:
    RC2_RESEARCH_timeline.md Patterns F/G. Q: build teamfight clustering + death heatmap
    (defer behind A/B/C/E) or park it?

### 2G. DASHBOARD-WIDE DESIGN / DENSITY

42. **prefers-reduced-motion done right.** [NEW] Honored in exactly ONE panel today (and that
    one just zeroes animation). A global tokens.css block that REPLACES each coach-pulse with
    a static tinted ring. EFFORT LOW / VALUE high. DEP: none. SRC: RC2_RESEARCH_nonleague_
    uiux.md D2 (top HIGH-lift). Q: add the global reduced-motion replacement now (cheapest
    accessibility win, widest gap) or skip?

43. **Redundant status cues (kill color-only).** [NEW] Status is hue-only across panels
    (fails WCAG 1.4.1 + red-green color blindness). Prepend a sign/arrow/glyph to every
    good/warn/danger value (Bloomberg + WCAG converge). EFFORT LOW / VALUE high. DEP: none.
    SRC: RC2_RESEARCH_nonleague_uiux.md B3/C5. Q: add redundant status glyphs now or leave
    color-only?

44. **Threshold-driven status helper (Grafana model).** [NEW] One shared `statusFor(value,
    thresholds)` JS helper replacing scattered per-panel magic numbers, mapped to a `--status`
    var. EFFORT LOW / VALUE high. DEP: none; adopt incrementally. SRC: RC2_RESEARCH_nonleague_
    uiux.md B1. Q: add the shared status-threshold helper now or keep ad-hoc per-panel logic?

45. **Quiet-by-default motion sweep (calm-tech).** [NEW] Trim the `infinite` loops
    (item_build nextUpPulse, map_state deepZoneWarn) to one-shots; reserve sustained motion
    for genuine danger; fix the 0.8s/1.2s coach-pulse doc drift. EFFORT LOW-MED / VALUE med.
    DEP: a motion-policy audit across ~12 panels. SRC: RC2_RESEARCH_nonleague_uiux.md B4/D4/
    D1. Q: run the quiet-by-default motion sweep now or leave the looping animations?

46. **Two-tier design tokens (primitive ramp -> semantic alias).** [NEW] The central token-
    architecture gap: `--signal-good` is a literal hex, not `var(--green-400)`, and panels mix
    `--good`/`--signal-good`. Refactor to primitive->alias; unblocks theming. EFFORT MED /
    VALUE med. DEP: heaviest item; needs a dedicated pass + screenshot audit. SRC:
    RC2_RESEARCH_nonleague_uiux.md C3. Q: do the two-tier token refactor (sequence AFTER the
    cheap HIGH wins) or leave the two layers coexisting?

47. **Labeled grid sections + tonal-elevation surfaces + extra text tiers.** [NEW] Datadog
    named bands (Overview/Combat/...), M3 tone-based elevation instead of box-shadow, and
    --text-secondary/-tertiary steps. EFFORT MED (grid) + LOW (tokens) / VALUE med. DEP: main
    layout restructure (grid) needs the UI-audit ritual. SRC: RC2_RESEARCH_nonleague_uiux.md
    B2/C1/C2. Q: restructure the dashboard grid into named sections + tonal elevation, or keep
    the flat grid?

48. **Dark-color values audit (no #000 / #fff / oversaturated accents).** [NEW] RC is mostly
    compliant; verify no panel uses pure black bg or pure white body text. EFFORT LOW / VALUE
    med. DEP: none. SRC: RC2_RESEARCH_nonleague_uiux.md C4. Q: run the dark-values grep-and-
    lock audit now or trust the current near-compliant palette?

---

## SECTION 3 - COACHING ENGINE

The RC2 plan's Phase 5. The north star is Haiku-free laning tuned for local CV.

49. **Haiku-free laning coach tuned for local CV.** [RC2 P5 stage 5.1] Take laning verdicts
    off Sonnet/Haiku and onto the precomputed DS laning tables + local CV signals. EFFORT M /
    VALUE high. DEP: the HZ precompute is shipped + shadow-logging; needs the flip gate. SRC:
    RC2_PLAN.md 5.1/5.2, ROADMAP HZ-* fanout. Q: confirm 5.1 (laning off Haiku for local CV)
    as the Phase-5 centerpiece - build now?

50. **Laning hold-band recalibration (the #1-frequency flip, blocked at agreement).** [GATED]
    The laning precompute-vs-Haiku agreement is 39%->53% (after the report's even-bucket
    half); the verdict vocabulary lacks a `hold`/farm band and is back_off-biased. NEXT: add a
    hold band + soften the back_off threshold in matchup.py (Tier-2), regen the LFS tables,
    re-run the report, confirm agreement climbs BEFORE any flip. EFFORT M (Tier-2) / VALUE
    high. DEP: a real-game shadow corpus; do-not-flip-blind. SRC: BACKLOG laning-precompute
    recalibration, DS_COMPLETENESS_GAP d3. Q: do the Tier-2 hold-band recalibration + regen
    now (product-calibration, not a blind edit) or wait for more shadow data?

51. **ABC choices specificity uplift + condition-change branching.** [RC2 P5 stages 5.3/5.4]
    Operator directive: more specific A/B/C choices + best-path branching when conditions
    change. EFFORT M / VALUE high. DEP: the deterministic choice substrate exists (HZ-C1). SRC:
    RC2_PLAN.md 5.3/5.4, operator directive. Q: confirm the ABC-specificity + condition-
    branching scope - build now?

52. **Mid-game + late-game + objective playbook.** [RC2 P5 stages 5.5/5.6] Operator directive:
    mid/late game plays + objective plays beyond laning. EFFORT M-L / VALUE high. DEP: the
    event_callouts objective spawns exist; needs the macro playbook logic. SRC: RC2_PLAN.md
    5.5/5.6, operator directive. Q: confirm the mid/late/objective playbook scope - build now?

53. **Lost-objective / stagnation response playbook.** [RC2 P5 stage 5.7] Operator directive:
    a response when an objective is lost or the game stagnates. EFFORT M / VALUE high. DEP:
    item 52. SRC: RC2_PLAN.md 5.7, operator directive. Q: confirm the lost-objective/
    stagnation playbook scope - build now?

54. **Same-state Haiku-skip debounce (default-ON flip).** [FLIP] Built DEFAULT-OFF for ARAM
    (RC_ARAM_STATE_DEBOUNCE) + Arena (RC_ARENA_STATE_DEBOUNCE); SR already debounces. Cuts
    redundant live Haiku spend, serves the Haiku-to-ZERO north star. EFFORT S / VALUE med. DEP:
    validate vs a live/replayed game - a too-coarse sig makes the coach go stale mid-fight
    (never trade fidelity for cost). SRC: BACKLOG reliability/hardening. Q: flip the
    ARAM/Arena state-debounce default-ON after a live validation, or keep it off?

55. **Deterministic champ-select brief flip (Haiku-elim).** [GATED] The deterministic brief is
    built + shadow-logged beside the live Haiku brief; flip after reviewing the shadow log.
    EFFORT S / VALUE med. DEP: shadow-log review over a few real champ-selects; do-not-flip-
    blind. SRC: BACKLOG coaching-depth. Q: flip the champ-select brief off Haiku after a
    shadow-log review, or keep the Haiku call?

56. **HZ replay-narrative flip (dormant surface).** [GATED] Substrate + shadow shipped
    (core/precomputed_replay_narrative); the replay-coach served path is untouched because no
    dashboard route invokes it today. EFFORT S / VALUE low. DEP: whether to wire the dormant
    replay-coach UI button at all. SRC: BACKLOG coaching-depth, DS_COMPLETENESS_GAP. Q: wire +
    flip the replay-narrative surface, or leave the replay-coach button dormant?

57. **antiheal/grievous callout membership review.** [NEW] Shipped + deterministic (item 285);
    the open question is whether the operator wants a STANDING "buy antiheal" nudge and
    approves the curated heavy-sustain champion set. EFFORT S (live visual owed) / VALUE med.
    DEP: operator product call on the prescriptive nudge + set membership. SRC: ROADMAP item
    283/285. Q: keep the standing antiheal callout on, and approve the curated sustain-champ
    set?

---

## SECTION 4 - RESPONSIVENESS / PORTS

The RC2 plan's Phase 6. Goal: faster champ-select + UI WITHOUT blowing out ports. The
io-timing-map research already enumerated low-risk levers (L1-L8). Highest value/effort
first.

58. **Faster champ-select poll: RuneWriter 2.0s -> 1.0s (L1).** [RC2 P6 stage 6.2] The
    SLOWEST champ-select cadence governs rune/spell reaction; +1 GET/s only, writes stay
    idempotent. Halves reaction latency. EFFORT S / VALUE high. DEP: none (non-frozen
    lcu_rune_writer.py). SRC: RC2_RESEARCH_io_timing_map.md C/L1. Q: drop RuneWriter to 1.0s
    now (S, low-risk) or leave at 2.0s?

59. **Cache the champ-select-duration gameMode (L2).** [NEW] Stop re-reading
    /lol-lobby/v2/lobby every RuneWriter tick (mode does not change mid-CS); removes a GET/tick
    that funds L1's extra read. EFFORT S / VALUE high. DEP: none. SRC: RC2_RESEARCH_io_timing_
    map.md L2. Q: cache the CS gameMode now (S, pays for L1) or leave the per-tick lobby read?

60. **Halve UI update latency: SSE tick + build_state TTL 1.0s -> 0.5s together (L4).** [RC2
    P6 stage 6.3] Must move together (per the code comment); no new connections (SSE is push);
    :8893 is NOT hit more often (bounded by the 3.0s DS-call TTL). EFFORT S / VALUE high. DEP:
    watch _SLOW_BUILD_WARN_S to confirm build stays under tick. SRC: RC2_RESEARCH_io_timing_
    map.md L4. Q: halve the SSE/build_state cadence now (S, low-risk) or keep 1.0s?

61. **Pooled keep-alive LCU connection (L6).** [GATED] Every LCU/`:2999` reader opens a new
    urllib connection per call (no pooling); a single pooled HTTPSConnection eliminates the
    TIME_WAIT churn that caps how fast any LCU loop can safely run. EFFORT M / VALUE high
    (port-safety payoff). DEP: `lcu/lcu_client.py` is FROZEN - needs operator grant;
    game_reader/poller.py could pilot it first. SRC: RC2_RESEARCH_io_timing_map.md L6. Q:
    grant the frozen-file edit to introduce LCU connection pooling (the real port-safety fix),
    or pilot it only in the non-frozen poller?

62. **Single champ-select reader on 1-PC (L3).** [NEW] Retire the redundant agent loops and
    make LcuClient the single CS reader at 1.0s (or source build_state's CS from in-process
    LcuClient), removing a ~1.0s stage from the render chain. EFFORT M / VALUE med. DEP:
    touches state-builder wiring. SRC: RC2_RESEARCH_io_timing_map.md L3. Q: consolidate to a
    single champ-select reader now or leave the relay hop?

63. **Shared min-interval guard on any consolidated LCU reader (L7) + keep the :2999 self-read
    >= 1.5s floor (L8).** [NEW] Prevent multiple callers from independently pushing past a safe
    rate; document 1.5s as the hard floor for direct Riot reads. EFFORT S / VALUE med. DEP:
    none. SRC: RC2_RESEARCH_io_timing_map.md L7/L8. Q: add the min-interval guard + document
    the :2999 floor now or defer to the pooling work (item 61)?

64. **Port-safety + CPU-footprint regression verify.** [RC2 P6 stages 6.4/6.6] Confirm no
    connection-storm / port-exhaustion / CPU regression after the cadence changes. EFFORT S /
    VALUE high. DEP: items 58-63 landed. SRC: RC2_PLAN.md 6.4/6.6. Q: run the port/CPU
    regression check as the Phase-6 exit gate - confirm?

---

## SECTION 5 - DS ENGINE

Honest verdict from DS_COMPLETENESS_GAP.md: DS is ~90-93% to "truly complete besides patch
updates"; the remaining 7-10% is dominated by VALIDATION, not new engine code. The biggest
single block is the live-flip backlog - all gated on real games.

65. **The 11 flag-ready re-rank seams (DEFAULT-OFF eyeball-and-flip).** [FLIP] DSV2/3/4,
    DSP2/8/11 (dps+burst), RF1/2/3+6, B1, F2 - all built + tested + byte-identical until
    flipped. `ops/audit/ds_perm_swarm/live_flip_eyeball.py` dumps OFF-vs-ON top-6 so all 11
    eyeball in 3 games (SR+ARAM+Arena) without per-seam restarts. DSP11, RF1 (Yasuo), B1 (WIN-
    validated) are already FLIP-READY. EFFORT S each / VALUE high (cumulative). DEP: real games
    + a "saner not different" eyeball. SRC: DS_COMPLETENESS_GAP e. Q: run the 3-game eyeball
    pass and flip the validated seams default-ON, or leave them off?

66. **Wire the shipped-but-unconsumed live producers/consumers (DSP4/5/6/7 + anti-tank P3.2
    live).** [GATED] Consumers/producers are shipped but need the live summoner/rune/ally sets
    PLUMBED into a call site (and the /anti-tank route still calls the static
    `compute_antitank`). EFFORT M / VALUE med. DEP: live call-site wiring + eyeball. SRC:
    DS_COMPLETENESS_GAP e. Q: plumb the 4-5 live producers/consumers to real call sites now or
    defer?

67. **Anivia P revive + Orianna E ally-resist validation flip.** [FLIP/GATED] Revive shipped as
    the EHP-numerator multiplier (apply_passive_revive, DEFAULT-OFF) pending egg-survive
    feedback; Orianna E is a per-ally ball-attached grant needing a live-input wire (not a flag
    flip). EFFORT S / VALUE low. DEP: live feedback. SRC: DS_COMPLETENESS_GAP e. Q: validate +
    flip Anivia revive and wire Orianna E ally-resist, or leave both gated?

68. **Cross-eval systemic clusters A + B (Tier-2 valuation re-tune).** [GATED] Cluster A
    (archetype-vs-ARAM-win divergence; the cs_archetype_picks override exists, needs an off-meta
    decision) and B (generic-marksman-template on AD scorers, largely covered by DSP11+DSP2 -
    only per-champion live re-rank validation remains). EFFORT M / VALUE med. DEP: per-champion
    rewind-WIN validation; may need curation. SRC: DS_COMPLETENESS_GAP a3/d1, project_ds_
    comprehensive_cross_eval. Q: take the A/B clusters as a gated Tier-2 re-tune now or defer?

69. **Static-CD ability-haste consumer (a1) - the only real new engine code.** [GATED] The 6th
    item-225 sidecar; needs a NEW schema seam (a name-bridge + a haste-application model), and
    the wiki static-CD value is unreliable. EFFORT M / VALUE med. DEP: a new schema seam; risk
    med (a wrong CD model silently mis-ranks every caster). SRC: DS_COMPLETENESS_GAP a1. Q:
    build the static-CD haste consumer (genuinely hard new code) or formally defer-permanent
    like the 3 unmodelable items?

70. **Phase-D default-ON flips (apply_passive_damage + the 4 non-every-AA on_hit + per-stack
    assumed_stacks).** [FLIP] Need the structured cadence + a live "saner not different"
    re-rank. EFFORT S each / VALUE med. DEP: real games. SRC: DS_COMPLETENESS_GAP e, ROADMAP DS
    Phase D. Q: run the Phase-D re-rank and flip these default-ON, or leave off?

71. **URF/OFA/USB/NB mode multipliers + F2 cost-ceiling flip (c2/c3).** [FLIP] mode_modifiers
    wires the rotating-mode mults DEFAULT-OFF (gated on actually playing those modes);
    cost_ceiling stops the 6000g Void Immolation floating to rank 1 in ARAM/Arena. EFFORT S /
    VALUE low-med. DEP: playing the modes (mode mults); behavioral not WIN-gated (cost_ceiling).
    SRC: DS_COMPLETENESS_GAP c2/c3. Q: flip cost_ceiling now (ranking-surface cleanup) and the
    mode mults when those modes are played, or defer both?

72. **Live calibration + HZ build-flip / laning-agreement corpus gates.** [GATED] ds_calibration.
    jsonl analysis fires at 50+ games; the HZ build-order flip + laning-agreement gates report
    flip_ready=False (95% CI crosses zero) until rewind_history.db grows. Passive accrual gates,
    not missing code. EFFORT S / VALUE low. DEP: corpus growth (play more games). SRC: DS_
    COMPLETENESS_GAP d2/d3. Q: nothing to do until the corpus fills - acknowledge these are
    accrual-gated and re-run when thresholds hit?

73. **HZ-B build-order table regen to current engine.** [GATED] SR/ARAM regenerated 2026-06-19
    at engine 1.144.0 (item 506); Arena already current. The deferred half is the Tier-2 ENGINE-
    bump-for-provenance regen over a 172-champ content change the operator's per-champion
    discipline wants validated, not shipped blind. EFFORT M / VALUE low. DEP: operator gate;
    games-gated value (feeds hz_build_shadow). SRC: BACKLOG data-pipeline. Q: do the provenance-
    bump regen now or leave the deterministic data refresh as-is (already current)?

74. **Known-frontier data tails (cdragon ratio hard-tail b1, wiki markup b2).** [CLOSED-ish]
    Both need NEW extractor keys and are documented "do not resolve with the current schema" -
    the asymptotic last mile a balance-patched game never fully closes. EFFORT L / RISK high.
    DEP: a brand-new extractor key. SRC: DS_COMPLETENESS_GAP b1/b2, CLOSED list. Q: leave the
    cdragon/wiki data tails as known frontiers (do NOT re-pitch a resolver) - confirm closed?

---

## SECTION 6 - DATA WIRING + PRODUCERS

Surfaces wired in the UI with no live producer, or half-wired data lanes.

75. **Live producers for the ~88 remaining ADAPTATION st-* rows.** [GATED] cs_at_10/csd_at_15
    live producers shipped; the rest of the ~90 `st-*` rows (apm/reaction_time/tilt_meter/
    wall_collision_deaths/...) exist ONLY in post-game match_metrics, so they render a wall of
    "-" in-game. EFFORT M-L / VALUE med. DEP: a live source for each metric (many have none
    mid-game). SRC: ROADMAP item 281 Class B. Q: wire live producers for the adaptation rows
    that CAN be computed mid-game (and hide the rest), or accept the in-game "-" wall?

76. **`/api/ward-heat` producer.** [GATED] Permanently empty - `core.ward_events.record_ward`
    has no producer because Live Client emits no WARD_PLACED. EFFORT M / VALUE low. DEP: a
    ward-event source (vision heuristic, or post-game only from rewind timelines). SRC: ROADMAP
    item 281, BACKLOG Overlay App F warding heatmap. Q: build a vision/post-game ward producer or
    leave ward-heat as a post-game-only feature (binned from rewind_history)?

77. **win captured on end-of-game ingest (the History/Home keystone).** [NEW] match_history.db
    does not store win on the row; rewind has tracked_win. This single field unblocks items 15,
    35, 36, 37. EFFORT LOW-MED / VALUE high. DEP: an end-of-game ingest hook. SRC:
    RC2_RESEARCH_history.md/home_profile.md (the missing keystone). Q: add the end-of-game win-
    capture hook now (unblocks 4 downstream items) or keep reading win from rewind only?

78. **LBAND1 live benchmark-band wire-in.** [GATED] Item 443 shipped the generator (live cs+
    level vs the player's own percentile); this wires it into deterministic-coaching /api/state
    + the overlay, validates vs a real game, then flips. EFFORT S / VALUE med. DEP: a real/
    replayed game; do-not-flip-blind. SRC: BACKLOG R2 LBAND1. Q: wire + validate + flip the
    live benchmark band, or leave the generator unconsumed?

79. **set_augment_intent 4-PATCH endpoint discovery (live Arena).** [GATED] A 4-endpoint PATCH
    chain handler is scaffolded; needs a live Arena 1750 augment phase to discover which
    endpoint the LCU exposes (the KIWI/Mayhem probe was a confirmed negative, does not preclude
    CHERRY). EFFORT S (probe) / VALUE med. DEP: a live Arena game + Game-PC redeploy dance. SRC:
    ROADMAP set_augment_intent. Q: run the live Arena augment-endpoint probe next Arena game or
    leave OCR as the proven path?

80. **CommunityDragon lol-game-data catalog adoption (canonical mode/rune metadata).** [GATED]
    7 CDragon files RC does not consume (summoner-spells, perks, perkstyles, maps, queues,
    game-mode-mutators, champion-rune-recommendations) could ground the CD ledger + give
    canonical mode detection beyond the KIWI/queueId hacks + better PGR rune analysis. EFFORT M
    / VALUE low-med. DEP: triggered by PGR S2 wanting rune analysis or CD-ledger surplus. SRC:
    BACKLOG future-research. Q: adopt the CDragon game-data catalog now or wait for a concrete
    PGR/CD-ledger trigger?

---

## SECTION 7 - HYGIENE / CLEANUP

The RC2 plan's Phase 7. Operator directives: kill the ASCII-violation startup warning + a
project-folder cleanup of files unused >1 week.

81. **ASCII-violation full sweep of old files (kill the startup warning).** [RC2 P7 stage 7.1]
    Operator directive. The retro em-dash purge tooling exists (tools/strip_em_dashes.py); the
    smart-quote retro-sweep is NOT yet done (a separate operator-gated pass). EFFORT M / VALUE
    high. DEP: none. SRC: RC2_PLAN.md 7.1, CLAUDE.md. Q: run the full ASCII + smart-quote retro-
    sweep to silence the startup warning now - confirm scope?

82. **Stale-file census: .md/scripts unused >1 week.** [RC2 P7 stage 7.2] Operator directive.
    Note the clean-baseline memory: whole-tree dead-code re-audits find ~nothing, so scope tight
    or confirm. EFFORT M / VALUE med. DEP: none. SRC: RC2_PLAN.md 7.2, project_codebase_audit_
    clean_baseline. Q: run the >1-week stale-file census now (scoped, since the tree audited
    clean recently) or skip?

83. **Dead-code / unused-asset removal + repo folder reorg.** [RC2 P7 stages 7.3/7.4] Operator
    directive. EFFORT M / VALUE med. DEP: the census (item 82); safety-verified removals only.
    SRC: RC2_PLAN.md 7.3/7.4. Q: do the dead-code removal + folder reorg now or leave the layout?

84. **D1 churn-fix tail: full 362-file mirror de-dup / build-time-gen.** [GATED] The per-commit
    MANIFEST re-stamp churn is fixed (item 506); the full mirror de-dup is deferred (outward-
    facing gist + CI --check coupling, its own session). EFFORT M / VALUE low. DEP: own session
    (gist/CI coupling). SRC: ROADMAP repo-audit follow-up. Q: take the mirror de-dup as its own
    session or leave it deferred?

85. **gamepc_*.py archival.** [GATED] The 2-PC-era agents are out of the live pipeline; archival
    was verify-confirmed NOT-safe in a prior pass (some are non-integral but still referenced).
    EFFORT S / VALUE low. DEP: a dedicated verify slice. SRC: ROADMAP item 269 L8 / CLAUDE
    settled. Q: do a dedicated gamepc archival slice (re-verify safety) or leave the legacy
    agents in place for repurpose?

86. **Verify dual suite green post-cleanup.** [RC2 P7 stage 7.5] EFFORT S / VALUE high. DEP:
    items 81-83. SRC: RC2_PLAN.md 7.5. Q: run the dual-suite green check as the Phase-7 exit
    gate - confirm?

---

## SECTION 8 - RESEARCH LIFTS (NOW / FUTURE / CLOSED)

A consolidated NOW/FUTURE/CLOSED triage of the research-surfaced lifts so the operator can
sweep them as a block. (Items already actioned above are not repeated.)

### NOW (shippable, low-risk, high-value - mostly cross-listed above)
87. The cross-listed HIGH-lift NOW set: items 1 (trinket pulse), 15/21 (W/L + last-session),
    22 (auto-accept), 23 (lobby duo), 25 (counter-picks), 31 (carry metrics), 35/36 (history
    row + filters), 39 (gold-diff chart), 42/43/44 (reduced-motion + status glyphs + threshold
    helper), 58-60 (responsiveness L1/L2/L4). Q: approve the NOW block as a single build wave?

### FUTURE (value but gated on data, a live game, or product judgment)
88. **Player scouting table (27), augment tiers (28), draft win-% (29), rank header (18), GPI
    Player Profile page, timeline teamfight/heatmap (41), MMR/tier-prediction.** Each gated on a
    dataset, a live game, or a product call. SRC: the per-surface research docs. Q: confirm
    these stay FUTURE (act only when their trigger lands) - any to promote to NOW?

### CLOSED (do NOT re-pitch - recorded so they are never re-spent)
89. **The closed set:** every LCU client/codegen repo (inferior to RC's lockfile client; KebsCS
    is reference-only, no license); ZERO Arena/Cherry/Mayhem lobby-create payloads in the corpus
    (must come from live capture); full `.rofl` packet-parse (per-patch Layer-2 RE; a Layer-1
    spike is the only keepable win, logged in BACKLOG); ML win-predictors / CV-minimap / voice /
    riot-offline-mode; the LCU augment MID-GAME API (dead-end, OCR is the path); Arena augment
    WINRATE display (Riot-forbidden; pick-rate only); the persistent counter-pick sidebar
    (clutters 1920x1080; hover-only wins); the aggregator G win-prob curve (RC already has it);
    global tier-list / cross-player MMR / AI-chatbot (single-player by design / counter to the
    Haiku-to-ZERO charter); DS effects.py re-merge / FastMCP rewrite; the DS forward-marker
    scout fanouts (queue provably dry); the cdragon by-level resolver (needs a new schema axis,
    near-zero gain). SRC: BACKLOG CLOSED lists, CLAUDE.md Settled, DS_COMPLETENESS_GAP section 3.
    Q: acknowledge the CLOSED set stays closed - confirm none are reopened by RC2?

---

## SECTION 9 - ASPIRATIONAL / FUTURE

Longer-horizon items from BACKLOG, not scheduled.

90. **Interactive Item Shaper (post-DS-100%).** The DAMAGE/SURVIVABILITY/UTILITY +/- nudge UI on
    top of the scorers; backend primitive (core/shaper.py) shipped + 57 tests; blocked on DS
    reaching 100% coverage + the running-coach wire. EFFORT M-L / VALUE med. DEP: DS completeness
    (Section 5). SRC: BACKLOG coaching-depth. Q: expose the Item Shaper UI once the live-flip
    backlog clears, or keep the primitive unsurfaced?

91. **G6 cost-aware build MODE (cost-ignoring optimum).** Gemini-verdict: leave FUTURE - a raw
    gold cost model conflicts with DS's empirical-WIN anchoring + violates do-not-blind-build. If
    ever revisited, anchor on Meraki gold-per-stat + rewind-WIN spike-timing, never aggregator D.
    EFFORT L / VALUE low. DEP: a WIN-anchored cost model (hard). SRC: BACKLOG DS calibration,
    DSP9. Q: keep G6 cost-aware-build FUTURE (do not build blind) - confirm?

92. **DS target-current-HP% scenario lever flip (lolmath's 50%).** The seam is shipped (scales
    BotRK/Hellfire/Fulmination, byte-identical at 1.0); the flip to a live fight-average current-
    HP value re-ranks + owes an ENGINE bump. EFFORT S / VALUE low. DEP: a product decision on the
    average value. SRC: BACKLOG coaching-depth. Q: flip the current-HP% lever to a fight-average
    or keep 100% (current~=max)?

93. **Arena S2 augment Level-Up + Crafting Round system (patch 26.09).** Schema break for
    arena_coach + cherry-augments OCR (per-augment level 1->3, round-8 Crafting). Pre-stage a
    `level` axis on compute_augment_stats. EFFORT M / VALUE med. DEP: 26.09 PBE confirms the
    schema. SRC: BACKLOG aspirational. Q: pre-stage the Arena S2 level axis now or wait for the
    PBE schema?

94. **Elo log-odds draft-composition aggregator (true team-vs-team).** Shipped as core/draft_elo
    (item ab3f553); the FUTURE tail is sourcing pairwise WR off rewind_history at sufficient
    density for SR. EFFORT M / VALUE low-med. DEP: a denser champ-pair corpus. SRC: BACKLOG
    draft tool L triage. Q: invest in denser draft-Elo pairwise WR, or leave the recent-form proxy?

95. **CI Watchdog arming (auto-fix red CI).** Built + 19 tests, NOT armed: the live `claude -p`
    dispatch wiring is a documented stub; an unattended auto-merge-to-main loop must dry-run a
    live red-main first. EFFORT M / VALUE med. DEP: a live red-main dry-run; do-not-flip-blind.
    SRC: ROADMAP medium-priority. Q: arm the CI watchdog (dry-run a red main first) or leave it
    built-but-disarmed?

96. **Pre-release name-scrub + history rewrite.** Standing prerequisite BEFORE any public
    release/open-source: scrub competitor/outreach names from file content AND full git history
    (force-push pre-authorized). DEFERRED to the release trigger. EFFORT M / VALUE n/a (release-
    gated). DEP: the release/open-source decision. SRC: BACKLOG reliability. Q: nothing until a
    release decision - confirm the scrub stays deferred to that trigger?

97. **Phase 9 - Iteration 2 (Gemini-gated headless).** The RC2 plan's final phase: re-run the
    research + design synthesis delta-focused, final consolidation + the RC 2.0 banner. [RC2 P9]
    EFFORT M / VALUE high (closes the program). DEP: Phases 1-8 drained. SRC: RC2_PLAN.md Phase 9.
    Q: confirm Phase 9 runs once after the build phases drain, then the RC 2.0 banner?

---

## TOP 10 DECISIONS TO MAKE

The highest-leverage operator calls, chosen for value x how much they unblock. Each maps to
an item above.

1. **Dashboard STAYS while overlay active (item 2).** The operator-named disappear bug. Confirm
   it is in the build scope - it is the most-cited overlay grievance.

2. **The 3-game DS live-flip eyeball pass (item 65).** 11 default-OFF seams are built + tested;
   3 games unlock the largest concrete DS-completeness block. Approve the eyeball-and-flip.

3. **end-of-game win capture (item 77).** One field unblocks the W/L strip, real season WR, the
   result-first history row, and per-session W-L headers (items 15/35/36/37). The cheapest
   highest-leverage data wire.

4. **Counter-picks vs the live enemy comp (item 25).** The single highest payoff-to-effort
   champ-select feature; 80% of the plumbing already exists.

5. **Laning off Haiku + the hold-band recalibration (items 49/50).** The Phase-5 centerpiece
   and the #1-frequency flip, currently blocked at 39->53% agreement. Approve the Tier-2 hold-
   band recalibration + regen (not a blind edit).

6. **Responsiveness levers L1/L2/L4 (items 58/59/60).** Three S/low-risk changes that halve both
   champ-select reaction and UI update latency with no new ports. Approve as a batch.

7. **LCU connection pooling (item 61).** The real port-safety fix, but it touches the FROZEN
   lcu_client.py - the program already grants frozen edits, so the call is whether to do it now
   or pilot in the non-frozen poller first.

8. **The cheap accessibility/design HIGH-lifts (items 42/43/44).** reduced-motion-done-right +
   redundant status glyphs + the threshold helper - all low-effort, high-value, low blast radius.
   Approve the design NOW block.

9. **Rank header + player scouting (items 18/27): NOW or FUTURE?** Both are universal competitor
   features but gated (rank is stale for an event-mode player; scouting is Riot-rate-limited).
   Decide promote-or-defer for each.

10. **ASCII retro-sweep to kill the startup warning (item 81).** Operator-directed Phase-7 work;
    confirm the smart-quote sweep scope so the warning goes away for good.

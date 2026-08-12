# DESIGN SYSTEM MAP - Amberstone Dashboard (2026-07-22)

Read-only inventory for the cross-panel theme pass (operator ask #1: optical + coherence, NOT
the old bare-hex compliance hunt). 4-layer cascade: `web/css/panels/base.css` (:root palette)
-> `tokens.css` (semantic --signal-* + scale) -> `hextech.css` / `panels/primitives.css`
(components) -> `overlay.css` (--ovx-* in-game layer). NOTE: the base palette lives in
`panels/base.css`, not `primitives.css`; there is also a second `panels/primitives.css`
(component/card layer).

## 1. PALETTE SOURCE OF TRUTH

### 1a base :root - web/css/panels/base.css
--canvas #0A0E14 (page) :10 | --surface #111722 (panel) :11 | --surface-2 #16202E (raised) :12 |
--surface-3 #1C2A3D (input) :13 | --text #ECF2FF :16 | --dim/--text-dim #8FA3BF :17-18 |
--faint/--text-faint #5C6E88 :19-20 | --border rgba(200,170,110,.16) gold hairline :21 |
--border-soft rgba(200,170,110,.10) :22 | --accent/--gold/--clock #C8AA6E :27,29,47 |
--accent-2 #0AC8B9 teal :28 | --good #37D08A :31 | --bad/--advisory #E84057 :33,40 |
--warn #E8A33D :35 | --info #7CA8FF blue :38 | --glow rgba(10,200,185,.30) :51 |
--radius 16px :54 | --radius-sm 8px :55 | --shadow-card :56.

### 1b semantic - tokens.css
prim rgb parts :34-40 -> --signal-good/warn/bad/dim/info/gold :51-59 (byte-identical to 1a).
--hextech-fill teal->gold :65, --hextech-glow :66, --hextech-border :67, --scrim :134,
--pulse-* :128-130, --focus-ring :123.

### 1c component - hextech.css clean; panels/primitives.css re-introduces literals:
#989aaa dead text :14; win-pill #2A4035/#B5DC8E :21-23; health-dot glows in STALE pre-Hextech
hues rgba(127,209,154,.55)/rgba(245,184,124,.55)/rgba(240,126,139,.65) :120-122.

### 1d overlay - overlay.css (body[data-shell="overlay"])
--ovx-bg 22,32,46=#16202E :23 | --ovx-bg-nested #0A0E14 :24 | --ovx-gold #C8AA6E :25 |
--ovx-cyan #0AC8B9 :26 | --ovx-good #37D08A :27 | --ovx-warn #E8A33D :28 | --ovx-red #E84057 :29 |
--ovx-text 255,255,255 :30 | --ovx-panel-border rgba(gold,.70) :62.

### 1e SAME CONCEPT, DIFFERENT VALUES (theme-swap landmines)
- INFO/blue: dashboard #7CA8FF vs overlay re-point to cyan #0AC8B9 (overlay.css:53) vs ~20 panels
  carrying stale fallback #8a8cf0 indigo (ds_matchup.css:22, build_order.css:106,
  pgr_lane_compare.css:124). THREE info hues.
- DIM: #8FA3BF slate vs overlay rgba(255,255,255,.55) white (overlay.css:54) vs #8a8e9c fallback
  (callouts.css:49). THREE values.
- PANEL BACKING: dashboard --surface #111722 vs overlay --ovx-bg #16202E (== dashboard's RAISED
  surface, one step lighter).
- GOOD/WARN/BAD fallbacks: token values consistent, but panel var(--signal-*, ...) fallbacks still
  carry retired neo-fintech #6ec977/#4ad295/#4ade80, #f1b04a, #ff5050/#f87171 (inert but a second
  palette intent).
- GOLD: #C8AA6E canonical vs --signal-gold fallback #f5b87c (ds_matchup.css:135); rarity gold
  variously #f5b87c/#f5c542/#b88410.

## 2. PANEL ADOPTION AUDIT (coherence problem)

THREE structural chrome systems coexist = root of "panels don't match":
- System G canonical .panel (map_state.css:125): --surface bg, --radius 16, --shadow-card, NO border.
- System H Hextech tactical (hextech.css .hx-card :29; primitives.css .replay-*-pane :152/219):
  --surface + 1px --border GOLD hairline + gold corner brackets.
- System W bespoke "glass": background rgba(20,22,30,0.85) + 1px rgba(255,255,255,0.08) WHITE
  hairline + white-alpha text. Zero gold. THE detached family.

(a) FULLY token-consuming: callouts, coach_choices, cc_blended_ehp_threat, cc_conditional_pressure,
snowball_elasticity, op_score, champ_benchmarks, pgr_winprob, pgr_lane_compare, ds_profile,
ds_relscore, ds_skill_order, capability_gap, active_match, spike_curve.

(b) PARTIAL (a few bespoke literals): duration_winrate (#6cf :113,120,133-134); ds_matchup (#6cf
:181, gold fallback #f5b87c :135); ds_shaper (#6cf :42, #fff :63); build_module (#6cf
:56,115,142,197,201; #6ad06a :186,189); build_order (#4ade80 :211,213); coach_decisions (#F07E8B
:69,138; #000 :151); right_now (leftover lavender #cbb8ff/#1b1726/#2a2140/#e6dcff/#9a8fb5 :131-148);
objective_gauges (--og-drake:#E8A33D one-off :29); objective_chips (fintech rgba tints :48-58);
augment_reco (rarity #6b7280/#b88410/#a855f7 :120-122).

(c) OFFENDERS (own palette / off-theme):
- champ_select_view.css WORST: full Tailwind palette ~60+ literals (#6366f1/#818cf8 indigo, #fb923c,
  #fca5a5, #c4b5fd, #6ee7b7, #93c5fd, #f0abfc, #fde68a, #67e8f9, #22d3ee, #a78bfa, #f97316,
  #a855f7/#c084fc, greens #44ff88/#0a2014/#2c6a3c/#15803d + bespoke surfaces). Reads as a different
  product.
- cd_ledger.css: fully bespoke blue/red/grey #5b8dff/#f07e8b/#9fbcff/#ffa5af/#cfd2dc + surfaces. No
  tokens.
- draft_elo.css: bespoke status trio #ff8080/#f1c878/#80e090 :83-93,173-216 instead of --signal-*.
- item_build.css: fluorescent yellow #F5FF00 your-lane pip :378 + glow :382; wave verbs
  #5BC0F8/#4DD0A8/#FF4646 !important :429-438. Clashes hardest with gold.
- ds_statcheck.css ORPHAN: references NON-EXISTENT tokens (--signal-strong/-mute, --border-1,
  --accent as blue) so GitHub-dark fallbacks PAINT: #e6edf3, #9aa7b3, #0f1620, #2a3441, #4493f8.
  Entirely off-theme at runtime.
- ward_heat.css (#80b8ff/#ff8080), header.css (rank-tier palette :1453-1462), home.css (lock green
  #44ff88, tier borders :148-156).
- RARITY drift (4 definitions): last_match.css:1414-1417, pgr_loadout.css:119-122,
  augment_reco.css:120-122, champ_select_view.css:2460-2476.

(c-structural) System-W glass family (bespoke chrome, tokens for status only): player_gpi,
player_snapshot, personal_build, personal_context, ds_knobs, ds_sweep, ds_combo, spike_markers,
team_context, overlay_ds_controls - all rgba(20,22,30,.85) bg + rgba(255,255,255,.08) white hairline
+ white-alpha text. WHITE hairline vs GOLD --border is the single most visible "don't belong" cue.

## 3. CONTRAST PAIRS (WCAG AA 4.5:1 normal / 3:1 large)
--text #ECF2FF on --surface ~15.8:1 PASS | --dim #8FA3BF ~6.97:1 PASS |
--faint #5C6E88 on --surface ~3.45:1 FAIL normal (powers captions + tooltip body base.css:78-82) |
--faint on --canvas ~3.72:1 FAIL | glass white .55 ~6.2:1 PASS | glass white .45 ~4.4:1 marginal
FAIL (player_gpi.css:263, spike_markers.css:141, personal_build.css:80) | glass white .35 ~3.1:1
FAIL (ds_knobs.css:96, overlay_ds_controls.css:74) | glass white .30 ~2.6:1 FAIL (player_gpi.css:233)
| #6cf ~9:1 pass but off-hue | #F5FF00 ~19:1 passes but optically harsh.
WEAK TIER: --faint (3.4-3.7:1) + glass captions <=.45 white (2.6-4.4:1). Body --text/--dim healthy.

## 4. PANEL CHROME CONSISTENCY
G .panel: --surface bg, NO border, 16px, --shadow-card, no brackets.
H hx-card/replay: --surface, 1px gold --border, 16/18px, --shadow-card, gold brackets.
W glass: rgba(20,22,30,.85), 1px white hairline, 10-12px local, no shadow, no brackets.
Divergences: tokens.css --panel-radius 18 vs canonical .panel --radius 16 (two radius systems);
grid paddings hand-set 6px 18px 14px (grid.css:12); glows/shadows in STALE fintech RGB
(127,209,154 / 240,126,139 / 245,184,124) recur map_state.css:223-259, item_build.css:163-498,
primitives.css:120-122, right_now.css:52, grid.css:68 (Hextech solids ringed by fintech halos).

## 5. OVERLAY vs DASHBOARD DIVERGENCE
Identical: good/warn/bad/gold. DIFFERENT: info (dashboard blue #7CA8FF vs overlay cyan #0AC8B9,
overlay.css:53); dim (slate #8FA3BF vs white .55, :54); panel bg (--surface #111722 vs --ovx-bg
#16202E, one step lighter); panel border (gold a.16/none vs a.70, 4x stronger). overlay.css:39-47
comment is STALE (claims :root signals are old fintech; tokens.css already re-points them).

## EXECUTIVE SUMMARY - 5 worst coherence offenders
1. TWO competing border systems: gold hairline (token panels) vs white hairline (glass DS family:
   player_gpi/ds_sweep/ds_knobs/ds_combo/player_snapshot/personal_build/spike_markers/team_context/
   overlay_ds_controls). Most visible mismatch.
2. champ_select_view.css on a foreign Tailwind palette (~60+ literals, zero tokens). Largest single-
   file divergence.
3. ds_statcheck.css silently renders GitHub-dark via non-existent-token fallbacks.
4. Stale-hue drift: Hextech solids ringed by retired fintech glows + ~20 panels carrying stale
   fallbacks encoding a second palette.
5. Overlay feels like a different theme: info blue vs cyan, dim slate vs white, lighter backing +
   4x stronger gold border. Plus bespoke status trios (draft_elo, item_build #F5FF00, cd_ledger) +
   4 conflicting rarity palettes.

CONTRAST for any candidate: --faint #5C6E88 fails AA normal (~3.4:1, powers tooltip body); glass
captions <=.45 white fall to 2.6-4.4:1.

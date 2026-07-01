# Dark-Values Audit - 2026-07-01 (OQ6 / QA48)

Grep-and-lock audit of every hardcoded dark/saturated color literal in
web/css (pattern: 6- or 3-digit hex starting 0/1/2; rgba(0,0,0,x) shadows
out of scope). Classified by a 5-group parallel agent fan-out, 2026-07-01.

Verdicts: 132 hits = 1 EXACT-LOCK (applied - byte-identical swap to a
token) + 94 RESKIN-CANDIDATE (old fintech/tailwind palette survivors whose
Hextech replacement token is named below; each is a VISIBLE change, so the
re-skin is operator-gated FUTURE - do NOT bulk-apply without a pick) + 37
JUSTIFIED (token definitions themselves, deliberate categorical one-offs
like the s212 indigo this-is-yours system and violet/magenta build badges,
stub.css legacy). The lock mechanism = tests/test_dark_values_ratchet_oq6.py
pins per-file literal counts as ceilings - new dark literals fail CI;
re-skins lower the pins.

Biggest offender: champ_select_view.css (52 hits, 42 re-skin candidates -
an old-palette skin predating the RC2 Hextech redesign).

## web/css/overlay.css (5 hits: 0 lock / 0 reskin / 5 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 23 | #16202E | doc comment on --ovx-bg parts definition (body[data-shell=overlay]) | JUSTIFIED | - | Hex appears only in the /* */ comment documenting the rgb-parts token value (rule 3). |
| 24 | #0A0E14 | doc comment on --ovx-bg-nested parts definition | JUSTIFIED | - | Comment-only hex documenting the --ovx-bg-nested rgb parts; token definition line. |
| 26 | #0AC8B9 | doc comment on --ovx-cyan parts definition | JUSTIFIED | - | Comment-only hex documenting the --ovx-cyan rgb parts; token definition line. |
| 143 | #16202E | prose comment in section 4 widget-shell header block | JUSTIFIED | - | Doc-comment reference to the backing color; the rule itself uses rgba(var(--ovx-bg), 0.58) at line 168. |
| 171 | #0A0E14 | prose comment describing the 1px dark stroke in .ovx-widget frame | JUSTIFIED | - | Doc-comment only; the actual stroke uses rgba(var(--ovx-bg-nested), 1) at line 176. |

## web/css/panels/active_match.css (3 hits: 0 lock / 3 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 146 | #14141c | background: var(--surface, #14141c) in .am-map-figure.am-map-noimg | RESKIN-CANDIDATE | var(--surface) | inert stale fintech fallback; live --surface is #111722 - sync fallback byte or drop |
| 225 | #1d1d28 | background: var(--surface-2, #1d1d28) in .threat-strip .threat-row | RESKIN-CANDIDATE | var(--surface-2) | inert stale fintech fallback; live --surface-2 is #16202E - sync or drop |
| 232 | #14141c | background: var(--surface, #14141c) in .threat-strip .threat-portrait | RESKIN-CANDIDATE | var(--surface) | inert stale fintech fallback, same as line 146; sync to #111722 or drop |

## web/css/panels/ban_suggest_toggle.css (3 hits: 0 lock / 3 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 111 | #2a2f37 | border: 1px solid #2a2f37 in .bs-row | RESKIN-CANDIDATE | var(--border) | raw off-palette slate border, no token reference at all; Hextech gold hairline rgba(200,170,110,.16) |
| 126 | #14171c | background: #14171c in .bs-row-icon | RESKIN-CANDIDATE | var(--surface) | raw neutral dark icon well; nearest Hextech panel bg #111722 (not byte-equal, visual change) |
| 127 | #2a2f37 | border: 1px solid #2a2f37 in .bs-row-icon | RESKIN-CANDIDATE | var(--border) | same raw slate border as line 111; reskin both together with the rgba(26,29,35) row bg sibling |

## web/css/panels/base.css (7 hits: 0 lock / 0 reskin / 7 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 10 | #0A0E14 | --canvas token definition in :root | JUSTIFIED | - | Canonical token definition line - the palette must live somewhere (rule 3). |
| 11 | #111722 | --surface token definition in :root | JUSTIFIED | - | Canonical token definition line for panel bg. |
| 12 | #16202E | --surface-2 token definition in :root | JUSTIFIED | - | Canonical token definition line for raised surface. |
| 13 | #1C2A3D | --surface-3 token definition in :root | JUSTIFIED | - | Canonical token definition line for input/chip well. |
| 14 | #16202E | --surface-head token definition in :root | JUSTIFIED | - | Alias token definition (same value as --surface-2 by design, per inline comment). |
| 15 | #1C2A3D | --surface-alt token definition in :root | JUSTIFIED | - | Alias token definition (same value as --surface-3 by design, per inline comment). |
| 28 | #0AC8B9 | --accent-2 token definition in :root | JUSTIFIED | - | Canonical token definition line for hextech teal secondary accent. |

## web/css/panels/build_module.css (1 hits: 0 lock / 1 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 65 | #1b1d27 | background: var(--surface-2, #1b1d27); in .bm-knob input | RESKIN-CANDIDATE | var(--surface-2) | Stale neo-fintech fallback; --surface-2 #16202E is live so fallback never fires - align fallback to #16202E. |

## web/css/panels/build_order.css (1 hits: 0 lock / 1 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 22 | #2a2f37 | border-top: 1px solid var(--card-border, #2a2f37); in .bo-card | RESKIN-CANDIDATE | var(--border) | --card-border is defined NOWHERE in web/ - this fallback RENDERS live; re-point to gold hairline var(--border). |

## web/css/panels/cd_ledger.css (9 hits: 0 lock / 8 reskin / 1 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 63 | #1d1d28 | background: var(--surface-2, #1d1d28) in .cd-row | RESKIN-CANDIDATE | var(--surface-2) | Dead stale fallback; --surface-2 live=#16202E (base.css:12); sync fallback or drop - zero pixel change. |
| 98 | #2a2a36 | background in .cd-row-initial (24x24 portrait fallback circle) | RESKIN-CANDIDATE | var(--surface-3) | Old fintech well gray; nearest Hextech chip/icon well --surface-3 #1C2A3D. Visual change, operator-gated. |
| 140 | #14141c | background in .cd-chip | RESKIN-CANDIDATE | var(--surface) | Old fintech nested-well dark; nearest Hextech --surface #111722 (chip sits darker than its --surface-2 row). |
| 141 | #2a2a36 | border: 1px solid #2a2a36 in .cd-chip | RESKIN-CANDIDATE | var(--border-soft) | Old fintech gray border; Hextech border token --border-soft rgba(200,170,110,.10) at base.css:22. |
| 166 | #2a2a36 | background in .cd-chip-sigil (14x14 character box) | RESKIN-CANDIDATE | var(--surface-3) | Old fintech well gray; nearest Hextech well --surface-3 #1C2A3D, same family as line 98. |
| 183 | #1a3a24 | background in .cd-chip-ready (green READY pill) | RESKIN-CANDIDATE | rgb(var(--prim-green)) | Off-palette dark-green status well; re-tint via rgba(var(--prim-green),.15)-style mix of Hextech good #37D08A. |
| 184 | #2a6a3a | border-color in .cd-chip-ready | RESKIN-CANDIDATE | rgb(var(--prim-green)) | Off-palette green border; re-derive from --prim-green parts (tokens.css:34) at reduced alpha. |
| 189 | #2a6a3a | background in .cd-chip-ready .cd-chip-sigil | RESKIN-CANDIDATE | rgb(var(--prim-green)) | Same off-palette green as line 184; sigil fill should share the --prim-green-derived READY tint. |
| 196 | #1a1a2c | background in .cd-chip-ult:not(.cd-chip-ready) | JUSTIFIED | - | Deliberate purple ult-chip family (comment L193-194: distinct D/F/R scan); no Hextech purple token exists. |

## web/css/panels/champ_benchmarks.css (4 hits: 0 lock / 4 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 16 | #1c1c24 | background: var(--bg-elevated, #1c1c24) in #bi-bench-mount .cb-mode-btn | RESKIN-CANDIDATE | var(--surface-2) | --bg-elevated undefined anywhere, fallback IS the live value; old fintech dark -> #16202E |
| 17 | #2a2a35 | border: 1px solid var(--border-soft, #2a2a35) in #bi-bench-mount .cb-mode-btn | RESKIN-CANDIDATE | var(--border-soft) | inert stale fallback (--border-soft live in base.css:22); fintech dark, drop or sync |
| 40 | #2a2a35 | border-bottom: 1px solid var(--border-soft, #2a2a35) in .cb-table thead th | RESKIN-CANDIDATE | var(--border-soft) | inert stale fallback under #bi-bench-mount; token defined, fintech dark never fires |
| 48 | #2a2a35 | border-bottom: 1px solid var(--border-soft, #2a2a35) in .cb-table tbody td | RESKIN-CANDIDATE | var(--border-soft) | inert stale fallback under #bi-bench-mount; same drop-or-sync as line 40 |

## web/css/panels/champ_select_view.css (52 hits: 0 lock / 42 reskin / 10 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 329 | #0a2014 | background in .csv-lock-btn | RESKIN-CANDIDATE | var(--good-soft) | Ad-hoc dark-green button well predates Hextech; good-soft is the sanctioned green wash. |
| 330 | #2c6a3c | border: 2px solid in .csv-lock-btn | RESKIN-CANDIDATE | rgba(var(--prim-green), .5) | Muted green border; half-strength prim-green matches the old value's weight. |
| 339 | #0d2c1a | background in .csv-lock-btn:hover | RESKIN-CANDIDATE | var(--good-soft) | Hover shade of the same ad-hoc green well; collapse into good-soft. |
| 419 | #0f2820 | background in .csv-arch-auto.is-active | RESKIN-CANDIDATE | var(--good-soft) | Green active well, off-palette; good-soft is the token equivalent. |
| 420 | #047857 | border-color in .csv-arch-auto.is-active | RESKIN-CANDIDATE | rgba(var(--prim-green), .5) | Tailwind emerald-700 border; nearest Hextech is a half-alpha prim-green. |
| 548 | #1a1230 | linear-gradient stop in .csv-arch-btn.active background | JUSTIFIED | - | s212 v4 deliberate indigo recolor to chromatically separate from green/gold; no Hextech indigo primitive. |
| 590 | #1d1e2d | background in .csv-team-cell.me | JUSTIFIED | - | s212 v7 documented indigo this-is-yours system (pairs #6366f1 border); no indigo prim exists. |
| 736 | #047857 | border-color in .csv-team-cell-tag--tank | RESKIN-CANDIDATE | rgba(var(--prim-green), .5) | Tank chip green border from the tailwind chip family; prim-green half-alpha is nearest. |
| 737 | #2563eb | border-color in .csv-team-cell-tag--bruiser | RESKIN-CANDIDATE | rgba(var(--prim-blue), .5) | Tailwind blue-600 chip border; prim-blue (info #7CA8FF) is the Hextech blue. |
| 761 | #2d7d52 | color in .csv-team-cell-confidence.is-high | RESKIN-CANDIDATE | rgba(var(--prim-green), .6) | Deliberately dimmed green text (s214 v4); express dimming as alpha on prim-green. |
| 761 | #053e2a | border: 1px solid in .csv-team-cell-confidence.is-high | RESKIN-CANDIDATE | rgba(var(--prim-green), .25) | Very dark green hairline on the dimmed pill; quarter-alpha prim-green matches. |
| 787 | #277540 | border: 1px solid in .csv-team-cell-threat--green | RESKIN-CANDIDATE | rgba(var(--prim-green), .5) | Green threat-pill border; rule is display:none in enemies but still live CSS. |
| 1091 | #15803d | border-color in .csv-phase-pill.finalization | RESKIN-CANDIDATE | rgba(var(--prim-green), .5) | Tailwind green-700 border next to var(--good) text; align border to prim-green. |
| 1092 | #2563eb | border-color in .csv-phase-pill.planning | RESKIN-CANDIDATE | rgba(var(--prim-blue), .5) | Tailwind blue-600 border next to var(--info) text; align to prim-blue. |
| 1334 | #181b22 | background in .csv-pr (YOUR RECORD headline card) | RESKIN-CANDIDATE | var(--surface-2) | Neutral fintech-ish dark used as a lifted child on a --surface card; surface-2 is the lift token. |
| 1442 | #277540 | border-color in .csv-pr-chip-icon.is-good | RESKIN-CANDIDATE | rgba(var(--prim-green), .5) | Green chip border; bg already uses var(--good-soft), border should match the system. |
| 1764 | #15803d | border-color in .csv-pb-mood-btn.is-active | RESKIN-CANDIDATE | rgba(var(--prim-green), .5) | Tailwind green-700 active border; text is already var(--good). |
| 1765 | #1a2a20 | background in .csv-pb-mood-btn.is-active | RESKIN-CANDIDATE | var(--good-soft) | Recurring ad-hoc selected-green well (7 occurrences in file); collapse all to good-soft. |
| 2194 | #2c6a3c | border-left: 3px solid in .csv-counter-pick | RESKIN-CANDIDATE | rgba(var(--prim-green), .5) | Green left-accent stripe; same muted green as the lock button border. |
| 2205 | #1d2630 | background in .csv-counter-pick.is-clickable:hover | RESKIN-CANDIDATE | var(--surface-3) | Hover raise off a --surface-2 base; surface-3 is the sanctioned raised well. |
| 2463 | #1a2a20 | background in .csv-build-row.selected | RESKIN-CANDIDATE | var(--good-soft) | Same selected-green well as line 1765. |
| 2535 | #082f3a | background in .csv-build-badge-onhit | RESKIN-CANDIDATE | rgba(var(--prim-teal), .12) | Cyan-dark badge bg; prim-teal (#0AC8B9) is the Hextech cyan family. |
| 2535 | #1e6b80 | border-color in .csv-build-badge-onhit | RESKIN-CANDIDATE | rgba(var(--prim-teal), .5) | Cyan badge border; half-alpha prim-teal matches the weight. |
| 2536 | #2a1010 | background in .csv-build-badge-crit | RESKIN-CANDIDATE | rgba(var(--prim-red), .12) | Red-dark badge bg; prim-red wash is the Hextech equivalent. |
| 2537 | #1f1a30 | background in .csv-build-badge-ap | JUSTIFIED | - | Violet categorical badge hue; palette has no violet primitive - deliberate variant coding, keep. |
| 2538 | #0f2820 | background in .csv-build-badge-tank | RESKIN-CANDIDATE | rgba(var(--prim-green), .12) | Green-dark badge bg (same literal as line 419); prim-green wash. |
| 2538 | #047857 | border-color in .csv-build-badge-tank | RESKIN-CANDIDATE | rgba(var(--prim-green), .5) | Emerald-700 badge border; half-alpha prim-green. |
| 2539 | #2a1030 | background in .csv-build-badge-lethality | JUSTIFIED | - | Magenta categorical badge hue; no magenta primitive in the 7-prim palette - deliberate one-off. |
| 2540 | #2a2010 | background in .csv-build-badge-support | RESKIN-CANDIDATE | rgba(var(--prim-gold), .12) | Gold-dark badge bg; prim-gold wash is the Hextech yellow family. |
| 2541 | #2a1810 | background in .csv-build-badge-experimental | RESKIN-CANDIDATE | rgba(var(--prim-amber), .12) | Orange-dark badge bg; prim-amber (warn) is the nearest Hextech hue. |
| 2546 | #0b1c33 | background in .csv-build-badge-user | RESKIN-CANDIDATE | rgba(var(--prim-blue), .12) | Blue-dark badge bg for user-curated builds; prim-blue wash. |
| 2546 | #2563eb | border-color in .csv-build-badge-user | RESKIN-CANDIDATE | rgba(var(--prim-blue), .5) | Tailwind blue-600 border, third occurrence in file; prim-blue half-alpha. |
| 2578 | #2a1f10 | radial-gradient stop in .csv-build-rune-keystone background | RESKIN-CANDIDATE | rgba(var(--prim-gold), .15) | Gold-tinted disc gradient behind keystone icon; express tint via prim-gold alpha. |
| 2660 | #000 | text-shadow: 0 0 2px in .csv-build-spell.is-swapped::after | JUSTIFIED | - | Black shadow tint on a micro-badge glyph; same class as rgba(0,0,0,x) shadows - keep. |
| 2758 | #1a2030 | background in .csv-build-path-row:hover | RESKIN-CANDIDATE | var(--surface-2) | Neutral hover shade nearest surface-2 (22,32,46); tokenizing keeps the hover-darken intent. |
| 2762 | #1a2a20 | background in .csv-build-path-row.is-active | RESKIN-CANDIDATE | var(--good-soft) | Same selected-green well family. |
| 2776 | #2a4a35 | background in .csv-build-path-row.is-active .csv-build-path-label | RESKIN-CANDIDATE | rgba(var(--prim-green), .30) | Stronger green chip bg under #c8f2d4 text; deeper prim-green wash than good-soft. |
| 2855 | #1a2030 | background in .csv-rune-opt:hover | RESKIN-CANDIDATE | var(--surface-2) | Same neutral hover shade as line 2758. |
| 2859 | #1a2a20 | background in .csv-rune-opt.is-selected | RESKIN-CANDIDATE | var(--good-soft) | Selected-green well family; border already var(--good). |
| 2865 | #2a2415 | background in .csv-rune-opt.is-recommended | RESKIN-CANDIDATE | var(--warn-soft) | Amber-dark recommended well; warn-soft is the token amber wash (border already var(--warn)). |
| 2904 | #1a2a20 | background in .csv-builds-push-btn | RESKIN-CANDIDATE | var(--good-soft) | Green button well; border already var(--good). |
| 2912 | #224a30 | background in .csv-builds-push-btn:hover | RESKIN-CANDIDATE | rgba(var(--prim-green), .30) | Brighter hover state of the green well; deeper prim-green alpha step. |
| 2949 | #1d1e2d | background in .csv-duo-cell.is-me | JUSTIFIED | - | Same s212 v7 indigo this-is-yours system as line 590 (pairs #6366f1 border); no indigo prim. |
| 3040 | #1a1f2a | background in .csv-augment-slot.is-active | RESKIN-CANDIDATE | var(--surface-2) | Neutral dark nearest surface-2; active signal is carried by the warn box-shadow ring. |
| 3042 | #1a2a20 | background in .csv-augment-slot.filled | RESKIN-CANDIDATE | var(--good-soft) | Selected-green well family (filled = done state). |
| 3076 | #1a2a20 | background in .csv-augment-option.is-selected | RESKIN-CANDIDATE | var(--good-soft) | Seventh occurrence of the selected-green well; border already var(--good). |
| 3129 | #2a3f30 | border-color in .csv-arena-cell.locked | RESKIN-CANDIDATE | rgba(var(--prim-green), .35) | Muted green locked border (icon carries full var(--good)); low-alpha prim-green matches. |
| 3168 | #22d3ee | color in .csv-arena-cell-timer | RESKIN-CANDIDATE | var(--accent-2) | Tailwind cyan-400, not byte-equal to teal #0AC8B9; rule is ABI-retained (timer removed s214). |
| 3173 | #000 | text-shadow outline stroke in .csv-arena-cell-timer | JUSTIFIED | - | Black 4-way outline stroke for legibility over art; shadow tint class - keep. |
| 3174 | #000 | text-shadow outline stroke in .csv-arena-cell-timer | JUSTIFIED | - | Black outline stroke, part of the same 4-way text-shadow. |
| 3175 | #000 | text-shadow outline stroke in .csv-arena-cell-timer | JUSTIFIED | - | Black outline stroke, part of the same 4-way text-shadow. |
| 3176 | #000 | text-shadow outline stroke in .csv-arena-cell-timer | JUSTIFIED | - | Black outline stroke, part of the same 4-way text-shadow. |

## web/css/panels/coach_choices.css (1 hits: 1 lock / 0 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 153 | #0a0e14 | color: #0a0e14; in .rc-ack-bubble (dark ink on --signal-good bg) | EXACT-LOCK | var(--canvas) | Byte-equals --canvas #0A0E14 (case-only diff); dark ink on bright ack bubble; swap is visual no-op. |

## web/css/panels/coach_decisions.css (1 hits: 0 lock / 1 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 150 | #000 | color: #000; in .menu-badge (ink on var(--gold) bg) | RESKIN-CANDIDATE | var(--canvas) | Pure black ink on gold badge; sibling ack-bubble uses #0a0e14 for same pattern - align to --canvas. |

## web/css/panels/ds_statcheck.css (3 hits: 0 lock / 3 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 36 | #0f1620 | background: var(--surface-2, #0f1620) in .dss-knob input | RESKIN-CANDIDATE | var(--surface-2) | inert stale fallback; live --surface-2 is #16202E - sync fallback byte or drop it |
| 37 | #2a3441 | border: 1px solid var(--border-1, #2a3441) in .dss-knob input | RESKIN-CANDIDATE | var(--border) | --border-1 undefined anywhere, fallback IS the live value; slate border -> gold hairline base.css:21 |
| 93 | #0f1620 | background: var(--surface-2, #0f1620) in .dss row chip (after .dss-name) | RESKIN-CANDIDATE | var(--surface-2) | inert stale fallback, same as line 36; sync to #16202E or drop |

## web/css/panels/duration_winrate.css (4 hits: 0 lock / 4 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 15 | #1c1c24 | background: var(--bg-elevated, #1c1c24) in #bi-duration-mount .dw-mode-btn | RESKIN-CANDIDATE | var(--surface-2) | --bg-elevated undefined anywhere, fallback IS the live value; old fintech dark, Hextech raised = #16202E |
| 16 | #2a2a35 | border: 1px solid var(--border-soft, #2a2a35) in #bi-duration-mount .dw-mode-btn | RESKIN-CANDIDATE | var(--border-soft) | inert stale fallback (--border-soft defined base.css:22 gold rgba); fintech dark, drop or sync fallback |
| 43 | #1c1c24 | background: var(--bg-elevated, #1c1c24) in #bi-duration-mount .dw-track | RESKIN-CANDIDATE | var(--surface-2) | --bg-elevated undefined, fallback fires live; bar-track well, Hextech raised surface #16202E |
| 44 | #2a2a35 | border: 1px solid var(--border-soft, #2a2a35) in #bi-duration-mount .dw-track | RESKIN-CANDIDATE | var(--border-soft) | inert stale fallback; token resolves to gold-tinted rgba hairline, fintech dark never fires |

## web/css/panels/header.css (5 hits: 0 lock / 1 reskin / 4 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 601 | #1c1c2a | background in .view-section-btn:hover, .view-tab:hover | RESKIN-CANDIDATE | var(--surface-3) | Old fintech purple-slate hover dark; base state is var(--surface-head) #16202E so hover should raise to #1C2A3D well. |
| 1529 | #1a3a3a | background in .lv-rank-platinum | JUSTIFIED | - | Per-tier rank identity tint (teal-dark); 10-tier rank ramp is not expressible in the semantic palette. |
| 1530 | #1a3a2a | background in .lv-rank-emerald | JUSTIFIED | - | Per-tier rank identity tint (green-dark), deliberate one-off in the rank-color ramp. |
| 1531 | #1a2a4a | background in .lv-rank-diamond | JUSTIFIED | - | Per-tier rank identity tint (blue-dark), deliberate one-off in the rank-color ramp. |
| 1534 | #1a3a4a | background in .lv-rank-challenger | JUSTIFIED | - | Per-tier rank identity tint (cyan-dark), deliberate one-off in the rank-color ramp. |

## web/css/panels/home.css (2 hits: 0 lock / 2 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 1342 | #1c1c2a | background: #1c1c2a in .cs-btn:hover | RESKIN-CANDIDATE | var(--surface-3) | fintech hover dark on a --surface-head base; Hextech hover step-up well is #1C2A3D |
| 1343 | #0a2014 | background: #0a2014 in .cs-lock-btn:hover | RESKIN-CANDIDATE | rgba(var(--prim-green), 0.12) | deliberate green-tint well but pairs with off-palette #44ff88; Hextech way = prim-green soft over surface |

## web/css/panels/op_score.css (8 hits: 0 lock / 8 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 23 | #1c1c24 | background: var(--bg-elevated, #1c1c24) in .op-mode-btn | RESKIN-CANDIDATE | var(--surface-3) | --bg-elevated is UNDEFINED under web/ so this fintech fallback RENDERS; repoint var to Hextech button/chip well. |
| 24 | #2a2a35 | border: 1px solid var(--border-soft, #2a2a35) in .op-mode-btn | RESKIN-CANDIDATE | var(--border-soft) | Dead fintech fallback; --border-soft resolves live (base.css:22 gold rgba); sync or drop - no pixel change. |
| 34 | #1c1c24 | background: var(--bg-elevated, #1c1c24) in .op-chart | RESKIN-CANDIDATE | var(--surface-2) | --bg-elevated undefined so fallback renders; chart card belongs on Hextech raised surface --surface-2 #16202E. |
| 35 | #2a2a35 | border: 1px solid var(--border-soft, #2a2a35) in .op-chart | RESKIN-CANDIDATE | var(--border-soft) | Dead fintech fallback; token defined live so literal never renders; sync or drop fallback. |
| 44 | #2a2a35 | stroke: var(--border-soft, #2a2a35) in .op-axis (SVG) | RESKIN-CANDIDATE | var(--border-soft) | Dead fintech fallback; token defined live so literal never renders; sync or drop fallback. |
| 46 | #2a2a35 | stroke: var(--border-soft, #2a2a35) in .op-grid (SVG) | RESKIN-CANDIDATE | var(--border-soft) | Dead fintech fallback; token defined live so literal never renders; sync or drop fallback. |
| 91 | #1c1c24 | background: var(--bg-elevated, #1c1c24) in .op-arc-chip | RESKIN-CANDIDATE | var(--surface-3) | --bg-elevated undefined so fallback renders; chip well maps to Hextech --surface-3 #1C2A3D. |
| 92 | #2a2a35 | border: 1px solid var(--border-soft, #2a2a35) in .op-arc-chip | RESKIN-CANDIDATE | var(--border-soft) | Dead fintech fallback; token defined live so literal never renders; sync or drop fallback. |

## web/css/panels/perf_curve.css (6 hits: 0 lock / 6 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 25 | #1c1c24 | background: var(--bg-elevated, #1c1c24) in .pf-mode-btn/.pf-metric-btn | RESKIN-CANDIDATE | var(--surface-3) | --bg-elevated is UNDEFINED under web/ so this fintech fallback RENDERS; repoint var to Hextech button/chip well. |
| 26 | #2a2a35 | border: var(--border-soft, #2a2a35) in .pf-mode-btn/.pf-metric-btn | RESKIN-CANDIDATE | var(--border-soft) | Dead fintech fallback; --border-soft resolves live (base.css:22 gold rgba); sync or drop - no pixel change. |
| 37 | #1c1c24 | background: var(--bg-elevated, #1c1c24) in .pf-chart | RESKIN-CANDIDATE | var(--surface-2) | --bg-elevated undefined so fallback renders; chart card belongs on Hextech raised surface --surface-2 #16202E. |
| 38 | #2a2a35 | border: 1px solid var(--border-soft, #2a2a35) in .pf-chart | RESKIN-CANDIDATE | var(--border-soft) | Dead fintech fallback; token defined live so literal never renders; sync or drop fallback. |
| 47 | #2a2a35 | stroke: var(--border-soft, #2a2a35) in .pf-axis (SVG) | RESKIN-CANDIDATE | var(--border-soft) | Dead fintech fallback; token defined live so literal never renders; sync or drop fallback. |
| 49 | #2a2a35 | stroke: var(--border-soft, #2a2a35) in .pf-grid (SVG) | RESKIN-CANDIDATE | var(--border-soft) | Dead fintech fallback; token defined live so literal never renders; sync or drop fallback. |

## web/css/panels/pgr_winprob.css (1 hits: 0 lock / 1 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 75 | #14161c | stroke: var(--canvas, #14161c); in .pwp-dot (swing-event dot outline) | RESKIN-CANDIDATE | var(--canvas) | Stale old-fintech fallback; --canvas #0A0E14 is live so fallback dead - align fallback to #0A0E14. |

## web/css/panels/primitives.css (1 hits: 0 lock / 1 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 20 | #2A4035 | background: #2A4035; in .win-pill.win-lead (5-band win-pct gradient) | RESKIN-CANDIDATE | rgba(var(--prim-green), .18) | Neo-fintech-era dark green band bg, paired with #B5DC8E ink on line 21; reskin the pair together. |

## web/css/panels/right_now.css (3 hits: 0 lock / 3 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 132 | #1b1726 | background: #1b1726 in .rn-sr-btn (SR reader violet button) | RESKIN-CANDIDATE | var(--surface-3) | purple-tinted dark, part of off-palette #a78bfa violet family; nearest Hextech well #1C2A3D |
| 143 | #2a2140 | background: #2a2140 in .rn-sr-btn:hover | RESKIN-CANDIDATE | var(--surface-3) | violet hover step of same off-palette family; if violet identity kept, operator may keep as one-off |
| 155 | #181b22 | background: #181b22 in .rn-sr-pill | RESKIN-CANDIDATE | var(--surface-2) | neutral dark near but not byte-equal to tokens (--surface #111722 / --surface-2 #16202E); reskin to raised |

## web/css/panels/spike_curve.css (1 hits: 0 lock / 1 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 18 | #2a2a35 | border-bottom: 1px solid var(--border-soft, #2a2a35); .spike-curve-container | RESKIN-CANDIDATE | var(--border-soft) | Rule-6 named old fintech dark; --border-soft rgba(200,170,110,.10) live so fallback dead - align or drop. |

## web/css/panels/ward_heat.css (1 hits: 0 lock / 1 reskin / 0 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 16 | #2a2a35 | border-bottom: 1px solid var(--border-soft, #2a2a35); .ward-heat-container | RESKIN-CANDIDATE | var(--border-soft) | Same rule-6 old fintech dark as spike_curve.css:18; live token wins - align fallback to gold-soft hairline. |

## web/css/stub.css (9 hits: 0 lock / 0 reskin / 9 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 7 | #000 | background in html, body | JUSTIFIED | - | Orphan terminal-theme stub (zero link/route refs per ops/audit/P2_FINDINGS.md:478); deliberate green-on-black baseline. |
| 11 | #1b4a1b | border-bottom: 2px solid in header | JUSTIFIED | - | Dark-green terminal border, part of the stub's self-contained retro theme; file is a vestigial orphan (DEFER-delete). |
| 17 | #1b4a1b | border: 2px solid in .pill | JUSTIFIED | - | Same terminal-green border family; orphan stylesheet, deletion not reskin is the eventual action. |
| 21 | #1b4a1b | border-color in .pill.connected | JUSTIFIED | - | Terminal-green state border in the orphan stub theme; no Hextech equivalent intended. |
| 29 | #1b4a1b | border: 1px solid in .panel | JUSTIFIED | - | Terminal-green panel border, deliberate one-off theme in the orphan stub file. |
| 29 | #050c05 | background in .panel | JUSTIFIED | - | Near-black green-tinted panel bg, deliberate terminal aesthetic; orphan file, not a Hextech surface. |
| 34 | #1b4a1b | border-bottom: 1px solid in .panel-head | JUSTIFIED | - | Terminal-green divider in the orphan stub theme. |
| 38 | #0f2a0f | border-bottom: 1px dashed in .kv | JUSTIFIED | - | Darker terminal-green dashed row divider; deliberate one-off in the orphan stub theme. |
| 47 | #1b4a1b | border-top: 1px solid in footer | JUSTIFIED | - | Terminal-green footer rule in the orphan stub theme. |

## web/css/tokens.css (1 hits: 0 lock / 0 reskin / 1 justified)

| line | literal | context | verdict | token | note |
|---|---|---|---|---|---|
| 40 | #0AC8B9 | /* #0AC8B9 Hextech teal */ doc comment on --prim-teal definition line | JUSTIFIED | - | Hex lives inside the token-definition doc comment itself (rule 3); the palette must live somewhere. |


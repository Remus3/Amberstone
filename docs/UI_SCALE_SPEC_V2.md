# UI Scale Spec v2.1

Status: DRAFT for back-and-forth approval (2026-05-23). v2.1 = v2's 25%
first-pass plus an operator-directed +15% second-pass on top. NOT YET
CONSUMED by panels - the worked example is the Settings page only this
round. Each subsequent page in the operator's order pulls tokens from
this spec during its own audit pass.

## Goal

Bring the dashboard to a comfortable at-a-glance read on Legion's 1920x1080
monitor at OS scaling 100% + Chrome at 100% (no browser zoom, no
CSS transform: scale, no body { zoom }). All four lazy mechanisms are
explicitly OFF-LIMITS. The page slider in Settings (`#set-zoom`) is
removed; `localStorage.rc-zoom` is no longer read OR written; the
`body { zoom: 1.0 }` declaration is removed from `base.css`; the tooltip
placement code in `web/js/main.js` and the champ-select popup workaround
no longer compensate for any body-zoom factor. The zoom feature is
fully retired - do not reintroduce it.

The scaling factor is **~44% from v1 baseline** (operator-directed:
25% first-pass + 15% second-pass) applied per-element with integer-pixel
landings (so glyphs do not anti-alias halfway through a sub-pixel).
Header / hero / stat values may bump more aggressively where the
existing floor was unread at viewing distance; chip metadata may bump
less where the floor was already at the 11-13px lower bound.

## Constraints (hard rules)

- No `transform: scale(N)` on a page or panel wrapper.
- No `body { zoom: 1.X }`. The `base.css L145 body { zoom: 1.0 }` rule
  stays for now (1.0 is the no-op identity) but no slider can change it.
- No `:root { font-size: 20px }` rem hack. Existing CSS uses px throughout;
  shifting to rem mid-flight is a separate refactor and not part of this
  spec.
- No browser-zoom dependency in operator workflow. Chrome stays at 100%.
- Floors per `feedback_font_size_viewing_distance.md`: 13 / 15 / 18 px for
  tertiary / secondary / primary text grades. No new size lands below the
  applicable floor.
- 8-px spacing grid stays sacred. Off-grid values (2/4/5/6/7) flagged in
  the wave-1 audit remain target for cleanup; no new off-grid values
  introduced.
- ASCII-only authored text per CLAUDE.md no-em-dash rule.

## Typography matrix

Five existing tiers + two new tiers (`--fs-stat` for prominent numeric
displays, `--fs-display` for hero headlines like the lobby clock or the
post-game-review verdict block). Targets land on integer pixels.

| Token              | v1   | v2 (25%) | v2.1 (+15%) | Net   | Grade           | Floor      | Example consumers                              |
| ------------------ | ---- | -------- | ----------- | ----- | --------------- | ---------- | ---------------------------------------------- |
| `--fs-xs`          | 11px | 14px     | **16px**    | +45%  | chip metadata   | >=13 OK    | `.settings-card-head`, `.diag-conn-row`, footer|
| `--fs-sm`          | 13px | 16px     | **18px**    | +38%  | secondary text  | >=13 OK    | `.view-section-sub`, table headers, dim labels |
| `--fs-md`          | 15px | 19px     | **22px**    | +47%  | body text       | >=18 OK    | `.settings-row`, body paragraph, list rows     |
| `--fs-stat` NEW    | -    | 22px     | **26px**    | NEW   | stat values     | -          | role-grade panel numbers, KDA cells, CS counts |
| `--fs-lg`          | 20px | 25px     | **29px**    | +45%  | section heads   | -          | `.view-section-head h2`, panel titles          |
| `--fs-xl`          | 27px | 32px     | **37px**    | +37%  | display heads   | -          | hero headline / right-now action text          |
| `--fs-display` NEW | -    | 40px     | **46px**    | NEW   | hero / verdict  | -          | lobby clock, PGR verdict, scoreboard hero      |

The body base of 27px in `base.css:131` was an upstream anchor for the
1.33 body-zoom era and is now decorative (every panel overrides). The
declaration stays in place since every panel overrides it; the
`body { zoom: 1.0 }` line itself was deleted.

## Spacing matrix

The 8-px grid is preserved. Three existing rungs retain their pixels;
two new rungs are added at the top of the scale to support the new panel
padding/gap targets.

| Token        | Pixels | Delta | Use                                              |
| ------------ | ------ | ----- | ------------------------------------------------ |
| `--space-1`  | 4px    | same  | micro padding (checkbox internal, dot spacing)   |
| `--space-2`  | 8px    | same  | tight gap inside a row, label-to-input pair      |
| `--space-3`  | 12px   | same  | tight panel internal gap                         |
| `--space-4`  | 16px   | same  | standard panel internal gap, default row padding |
| `--space-5`  | 24px   | same  | inter-card gap, section break                    |
| `--space-6`  | 32px   | same  | major layout gap, view-section vertical breathe  |
| `--space-7` NEW | 40px | NEW | hero-block padding, breathing room around heads  |
| `--space-8` NEW | 48px | NEW | view-section top spacing on large landing pages  |

The 25%-up canonical shift means consumers move one rung up: a panel that
previously used `padding: 12px 14px` now uses `padding: 16px 20px`
(rung-up where 20px lands cleanly on the 4-px sub-grid), and an
inter-card grid gap of 14px becomes 20px.

## Panel rules

NEW token group, opt-in per panel. Values bumped +15% over v2 first-pass:

| Token                  | v2     | v2.1     | Note                                |
| ---------------------- | ------ | -------- | ----------------------------------- |
| `--panel-padding`      | 16px   | **20px** | default; was 12-14 across panels v1 |
| `--panel-padding-comp` | 12px   | **14px** | compact variant (tooltip, dense)    |
| `--panel-padding-loose`| 24px   | **28px** | hero / landing                      |
| `--panel-gap`          | 12px   | **14px** | inter-row gap inside panel          |
| `--panel-gap-tight`    | 8px    | **10px** | dense table rows                    |
| `--panel-radius`       | 16px   | **18px** | replaces the old `--radius-sm`      |
| `--panel-radius-sm`    | 8px    | **10px** | for chips, tags, inputs             |

Cards lift to `--panel-radius` 18px; chips/tags stay at 10px so the
visual hierarchy reads (small thing = small radius). No
`box-shadow: 0 0 12px ...` outside the existing pulse keyframes.

## Interaction rules

NEW token group, opt-in. Values bumped +15% over v2 first-pass:

| Token              | v2    | v2.1     | Note                                                  |
| ------------------ | ----- | -------- | ----------------------------------------------------- |
| `--hit-min`        | 36px  | **42px** | minimum hitbox edge for buttons, toggles, slider thumb|
| `--hover-pad`      | 6px   | **8px**  | inflated hit area via `::before` pseudo or padding    |
| `--tooltip-offset` | 10px  | **12px** | distance from anchor to tooltip edge                  |
| `--tooltip-delay`  | 250ms | 250ms    | hover-in delay (existing JS uses 300ms; new default)  |
| `--focus-ring`     | `0 0 0 2px var(--signal-info)` | unchanged | keyboard focus outline             |

Checkbox / toggle / slider thumb minimums are 18-20px visual but the
interactive target is `--hit-min` (36px) via padded `<label>` wrappers.
Tooltip data-tt attributes stay; only the hover-coverage CSS changes.

## Dummy data architecture

Operator-selected: dev-only toggle in Settings, default OFF.

Mechanism:

1. New Settings row in DISPLAY card: `Dev UI mock data` checkbox.
2. Wires to `localStorage.rc-ui-mock` and `document.body.dataset.uiMock`.
3. Each panel that wants mock data reads `document.body.dataset.uiMock`
   in its renderer (when value is `"1"` and the panel sees no live
   data, render deterministic mock instead of empty/null state).
4. Mock data fixtures live at `web/data/ui_mock/*.json`. Loaded by
   panels on demand. Page-by-page audit pass adds fixtures only for
   pages the audit is currently on - no preemptive bulk authoring.

Mock fixtures must cover (per audit ritual checklist below):

- Full populated state (SR match with all participants/items/builds).
- Empty state (`-` or "no data" rendered).
- Overflow state (long champion names, long summoner names).
- Edge cases (disconnected player, missing rank, ARAM vs SR vs Arena).

## UI audit ritual v2

Per-page checklist replacing the existing implicit pass:

1. **Readability check** - can the operator read the headline / numbers
   from typical viewing distance (3-5 ft on the secondary monitor)? If
   any value still reads as a squint, bump one tier up or check the
   floor.
2. **Density check** - is whitespace balanced? No dead zones, no
   crammed regions. Section breaks at `--space-5` (24px) or above.
3. **Alignment check** - vertical rhythm; numbers in stat columns use
   `.tabular-nums`; row baselines line up.
4. **Interaction check** - hover hitboxes >= `--hit-min`; tooltip
   positions stable when content overflows; no accidental overlap
   between adjacent triggers.
5. **State coverage check** - exercise live + mock (via the dev toggle)
   + empty + overflow. Long-name champion + disconnected player + 0/0/0
   KDA edge.
6. **Animation check** - hover transitions feel proportional to the
   new sizes; existing pulse keyframes still read at the new scale; no
   tiny micro-animations that get lost.
7. **Regression check** - any of the 27 panel CSS files that reference
   this page render correctly? Specifically: `champ_select_view.css`
   popup workaround for the old body-zoom 1.33 must NOT reintroduce
   misalignment now that zoom is permanently 1.0.

The audit subagent runs through this checklist on each page; the
operator approves at the end of each page; then we move to the next.

## Per-page execution order (operator-locked)

1. Settings  (this round - worked example)
2. User Builds
3. Replay
4. History
5. Session
6. Home
7. Pre-Game Lobby
8. Champ Select - SR
9. Champ Select - ARAM
10. Champ Select - Arena
11. Active Match - SR
12. Active Match - ARAM
13. Active Match - Arena
14. Post Game Review - SR
15. Post Game Review - ARAM
16. Post Game Review - Arena

## Things explicitly out of scope for v2

- Density modes (compact / comfortable / broadcast). The token shape
  permits a future flip via `:root[data-density="broadcast"]` but no
  multi-mode switch ships in v2. Single Comfortable target.
- Sweeping the 583 hardcoded `font-size:` declarations across the
  29 CSS files. Each page audit pass sweeps its own panels only.
- Migrating from px to rem. Existing px chain stays.
- Reworking the popup-positioning workaround in
  `web/js/panels/champ_select.js:268-274` and
  `web/css/panels/champ_select_view.css:636-640` (stale comments from
  the body-zoom 1.33 era). Audit-ritual step 7 covers regression
  testing on the champ-select page when its turn arrives in the order.

## Per-component-class targets (Settings page worked example)

The Settings page exercises these specific token consumers (v2.1 values):

| Element                                      | v1                     | v2.1                          |
| -------------------------------------------- | ---------------------- | ----------------------------- |
| `.view-section-head h2` (page title)         | 17px                   | `var(--fs-lg)` 29px           |
| `.settings-body` grid gap                    | 14px                   | `var(--space-6)` 32px         |
| `.settings-card` padding                     | 12px 14px              | `var(--panel-padding)` 20px   |
| `.settings-card` border-radius               | `var(--radius-sm)` 8px | `var(--panel-radius)` 18px    |
| `.settings-card-head`                        | 11px                   | `var(--fs-xs)` 16px           |
| `.settings-card-head` margin-bottom          | 10px                   | `var(--space-4)` 16px         |
| `.settings-card-head` padding-bottom         | 5px                    | `var(--space-2)` 8px          |
| `.settings-row` font-size                    | 13px                   | `var(--fs-md)` 22px           |
| `.settings-row` padding                      | 6px 0                  | `var(--space-3) 0` (12px 0)   |
| `.settings-row` gap                          | 10px                   | `var(--space-3)` 12px         |
| `.settings-row` interactive target           | ~30px                  | `var(--hit-min)` 42px         |
| `.settings-row input[type="checkbox"]`       | 14x14                  | 24x24                         |
| `.settings-row select / input[type="range"]` | max-width 240px        | max-width 360px               |
| `.settings-row select` padding               | -                      | `--space-2 --space-3`         |
| `.settings-row .dim` (sub-label)             | inherited              | `var(--fs-sm)` 18px           |

## Per-component-class targets (User Builds page #2, 2026-05-23)

The User Builds view (`#view-user-builds` / `.ub-*` classes in
`web/css/panels/header.css:1867`) exercises these consumers (v2.1 values):

| Element                                | v1                     | v2.1                                       |
| -------------------------------------- | ---------------------- | ------------------------------------------ |
| `.ub-toolbar` gap                      | 10px                   | `var(--space-3)` 12px                      |
| `.ub-toolbar` padding                  | 6px 0 12px             | `var(--space-2) 0 var(--space-4)` (8 0 16) |
| `.ub-toolbar input[type=text]` width   | flex 0 1 260px         | flex 0 1 360px                             |
| `.ub-toolbar input[type=text]` padding | 6px 10px               | `var(--space-2) var(--space-3)` (8 12)     |
| `.ub-toolbar input[type=text]` font    | 14px                   | `var(--fs-md)` 22px                        |
| `.ub-toolbar input[type=text]` h-min   | -                      | `var(--hit-min)` 42px                      |
| `.ub-toolbar input[type=text]` radius  | 4px                    | `var(--panel-radius-sm)` 10px              |
| `.ub-hint` font                        | 12px                   | `var(--fs-sm)` 18px                        |
| `.ub-btn` padding                      | 6px 14px               | `var(--space-2) var(--space-4)` (8 16)     |
| `.ub-btn` font                         | 13px                   | `var(--fs-sm)` 18px                        |
| `.ub-btn` h-min                        | -                      | `var(--hit-min)` 42px                      |
| `.ub-btn` radius                       | 4px                    | `var(--panel-radius-sm)` 10px              |
| `.ub-btn-tiny` padding                 | 3px 9px                | `var(--space-1) var(--space-3)` (4 12)     |
| `.ub-btn-tiny` font                    | 12px                   | `var(--fs-xs)` 16px                        |
| `.ub-btn-tiny` h-min                   | -                      | 0 (row-scoped; floor relaxed)              |
| `.ub-layout` gap                       | 14px                   | `var(--space-5)` 24px                      |
| `.ub-list-pane / .ub-form-pane` pad    | 12px 14px              | `var(--panel-padding)` 20px                |
| `.ub-list-pane / .ub-form-pane` radius | `var(--radius-sm)` 8px | `var(--panel-radius)` 18px                 |
| `.ub-list-head` font                   | 11px                   | `var(--fs-xs)` 16px                        |
| `.ub-list-head` margin-bottom          | 8px                    | `var(--space-3)` 12px                      |
| `.ub-count` font                       | 11px                   | `var(--fs-xs)` 16px                        |
| `.ub-build-list` gap                   | 6px                    | `var(--space-2)` 8px                       |
| `.ub-build-list` max-height            | 540px                  | 720px                                      |
| `.ub-build-row` gap                    | 8px                    | `var(--space-3)` 12px                      |
| `.ub-build-row` padding                | 8px 10px               | `var(--space-3)` 12px                      |
| `.ub-build-row` radius                 | 4px                    | `var(--panel-radius-sm)` 10px              |
| `.ub-build-row` h-min                  | -                      | `var(--hit-min)` 42px                      |
| `.ub-build-meta` gap                   | 2px                    | `var(--space-1)` 4px                       |
| `.ub-build-label` font                 | 14px                   | `var(--fs-md)` 22px                        |
| `.ub-build-sub` font                   | 12px                   | `var(--fs-sm)` 18px                        |
| `.ub-form-head` font                   | 11px                   | `var(--fs-xs)` 16px                        |
| `.ub-form-head` margin-bottom          | 10px                   | `var(--space-4)` 16px                      |
| `.ub-form-grid` gap                    | 10px 12px              | `var(--space-3) var(--space-4)` (12 16)    |
| `.ub-field` font                       | 12px                   | `var(--fs-sm)` 18px                        |
| `.ub-field > span` font                | 11px                   | `var(--fs-xs)` 16px                        |
| `.ub-field input/select/textarea` pad  | 6px 9px                | `var(--space-2) var(--space-3)` (8 12)     |
| `.ub-field input/select/textarea` font | 14px                   | `var(--fs-md)` 22px                        |
| `.ub-field input/select/textarea` rad  | 4px                    | `var(--panel-radius-sm)` 10px              |
| `.ub-field input / select` h-min       | -                      | `var(--hit-min)` 42px                      |
| `.ub-field textarea` min-height        | 110px                  | 200px                                      |
| `.ub-form-status` padding              | 6px 10px               | `var(--space-2) var(--space-3)` (8 12)     |
| `.ub-form-status` font                 | 13px                   | `var(--fs-sm)` 18px                        |
| `.ub-form-status` radius               | 4px                    | `var(--panel-radius-sm)` 10px              |
| `.ub-form-actions` gap                 | 10px                   | `var(--space-3)` 12px                      |
| `.ub-form-actions` margin-top          | 12px                   | `var(--space-4)` 16px                      |

**Mock fixture:** `web/data/ui_mock/user_builds.json` ships 5 build
records covering full populated state, sub-line variants
(role/keystone/no-role), overflow (long label tests ellipsis), and
minimal (1 item / no role / no keystone). Renderer in
`web/js/main.js::_userBuildsFetchAndRender()` consults
`document.body.dataset.uiMock === "1"` after the live fetch; if live is
empty and mock is on, it loads the fixture via `/data/ui_mock/user_builds.json`
and renders with "(MOCK)" suffix on the label + count chip + hint.

**Audit ritual additions:** the `?ui_mock=1` URL-search param now also
flips `body.dataset.uiMock` for the page's lifetime (wired in
`web/js/main.js` boot restorePrefs). This lets headless-Chrome audit
captures hit the populated mock state without writing to localStorage
on the interactive browser - critical for the per-page sweep
ritual when remote-driving the dashboard via screenshot. The companion
flag `?ub_form=mock` (also wired to the user-builds view-router branch)
auto-opens the form pane with the first mock-fixture build pre-loaded
so the rune builder + spell chooser render without a click.

## User Builds form-pane augmentation (page #2 sub-feature, 2026-05-23)

Operator-requested mid-round: extend the Add/Edit form with a tabbed
rune-page builder + summoner-spell chooser. The previously free-form
`Keystone` / `Primary tree` / `Secondary tree` text inputs become
read-only and are populated by the builder; existing save-shape
preserved (additive `runes.minor_primary[]` + `runes.minor_secondary[]`
lists in `coaches/sr_user_builds.py::_normalize_record`).

| Element                          | Purpose                                                                  |
| -------------------------------- | ------------------------------------------------------------------------ |
| `.ub-sp-chooser` (card)          | Wraps the spell-slot pair + 11-cell grid                                 |
| `.ub-sp-slot` (D / F)            | Click to activate; auto-flips after each pick                            |
| `.ub-sp-grid` (11-cell)          | Flash / Ignite / Heal / Ghost / Barrier / Exhaust / Cleanse / TP / Smite / Clarity / Mark |
| `.ub-sp-cell.active`             | Selected slot border tint                                                |
| `.ub-rp-builder` (card)          | Wraps the 5-tree tab row + primary + secondary panes                     |
| `.ub-rp-tabs` (5 tabs)           | Domination / Inspiration / Precision / Resolve / Sorcery icons + names   |
| `.ub-rp-primary` (4 rows)        | Row 0 = keystones (single-pick); rows 1-3 = minor (one per row)          |
| `.ub-rp-sec-trees`               | Pill row of 4 OTHER trees (primary tree is disabled)                     |
| `.ub-rp-secondary` (3 rows)      | Minor rows only (game rules: no keystone); up to 2 picks total           |
| `.ub-rp-summary`                 | Compact one-line preview of all current rune picks                       |

Data source: `/api/dictionary/runes` (already exposed by
`dashboard/routes_dictionary.py:215`, serves the pinned 16.10.1
`data/meta/ddragon_runes.json`). DDragon image base hardcoded to
`/data/ddragon/16.10.1/img/` (kept in lockstep with the dictionary
patch). Tree icons under `Styles/720[0-4]_<TreeName>.png`; rune icons
under `Styles/<TreeName>/<RuneKey>/<icon>.png` per the
runesReforged.json `icon` field.

Schema extension (additive, backward compatible):

```json
"runes": {
  "keystone":        "Hail of Blades",
  "primary":         "Domination",
  "secondary":       "Precision",
  "minor_primary":   ["Cheap Shot", "Eyeball Collection", "Ultimate Hunter"],
  "minor_secondary": ["Triumph", "Coup de Grace"]
}
```

Round-trip: `_userBuildsOpenForm` reads `runes.minor_primary` /
`minor_secondary` into the in-module `_RP` state; `_ubReadForm` writes
back into the same shape; `_normalize_record` coerces to a list of
trimmed strings (empty list if missing). The downstream consumer
(`format_for_display`) still only emits keystone + tree names so the
champ-select chooser surface is unchanged.

## Cleanup deltas committed by Settings round (v2.1)

- `web/index.html` - REMOVED the Zen mode `<label class="settings-row">`
  row (operator-directed; the Z hotkey + `body[data-zen]` data attr
  remain functional via main.js).
- `web/index.html` - REMOVED the zoom slider row + its label/span/output.
- `web/js/panels/dev.js` - REMOVED the zoom slider wiring; replaced with
  the `set-ui-mock` checkbox wiring.
- `web/js/main.js` (boot restorePrefs) - REMOVED the
  `body.style.zoom = savedZoom` restore + comment block updated.
- `web/js/main.js` (prefs-chip rebuild) - REMOVED the rc-zoom flag
  branch; replaced with rc-ui-mock flag.
- `web/js/main.js` (Shift+R reset) - REMOVED the
  `localStorage.removeItem("rc-zoom")` line.
- `web/js/main.js` (prefs-chip click reset) - REMOVED the
  `localStorage.removeItem("rc-zoom")` line.
- `web/js/main.js` (tooltip `place()` function) - REMOVED the
  `getComputedStyle(document.body).zoom` divisor; the function now
  operates on plain viewport CSS pixels for the cursor and the tip.
- `web/css/panels/base.css` - REMOVED the
  `body { zoom: 1.0 }` declaration entirely + comment block updated to
  document that the zoom feature is retired.
- `localStorage.rc-zoom` - no code path reads OR writes this key
  anymore. If a browser carried it from a prior session it sits unused
  until the user clicks the prefs-chip or hits Shift+R (which still
  clears rc-zen / rc-header-lock and reloads).
- The `champ_select.js:268-274` popup workaround (appending to `<html>`
  instead of `<body>` to bypass body-zoom) is left intact - the popup
  still appends to `<html>` which is harmless once zoom is gone, and
  reworking the positioning is in scope for the Champ Select pages
  (#8/9/10 in the order).

## Open questions for the operator (this draft round)

(numeric targets above are concrete; below are forks worth a callout)

A. **`--fs-md` target** - I picked 19px (the analysis recommended 18px
   for body). Both clear the 15-px floor; 19 is a touch denser
   (consistent +27% with `--fs-xs`), 18 is what the analysis matrix
   used. Either is defensible. Default: 19. Flip request?

B. **`--fs-stat` placement** - 22px sits between `--fs-md` (19) and
   `--fs-lg` (25). Some panels (role grade card, replay grid CS/gold
   column) already render at 20-22px; this token formalizes that rung.
   Default: ship as 22. Flip request?

C. **`--panel-radius` 16px** - the existing `--radius-sm` is 8px and
   `--radius` (panel-level) maps to roughly 12px via the primitives
   layer. 16px reads more "card" and less "tile"; the analysis called
   for it. Default: ship at 16. Flip request?

D. **Hero / display tier 40px (`--fs-display`)** - reserves a tier for
   the lobby clock / PGR verdict block. Not consumed in the Settings
   round. The number is a placeholder for now; we can finalize when the
   page that uses it (Pre-Game Lobby or PGR) lands in the order.

E. **Card padding `16px`** - the analysis suggested `defaultPadding: 20`.
   I went with `--space-4` (16px) because the grid is sacred. A
   `--panel-padding-loose` at 24px is available for hero / landing
   cards if 16 feels cramped after the worked example. Flip request?

## What this round delivers

1. This spec doc (you are reading it).
2. `web/css/tokens.css` extended additively with v2 tokens (all
   pre-existing tokens retained; new tokens layered).
3. Settings page refactored against the v2 tokens.
4. Settings page screenshot from Legion monitor.

Nothing else gets touched. The 15 remaining pages from the operator's
order are deferred until the spec + Settings render are approved.

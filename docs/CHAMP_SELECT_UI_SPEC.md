# Champ Select UI redesign spec (page #8, SR)

Operator-directed 2026-05-31. Six changes. Grounded in the live render
(`web/js/panels/champ_select.js`, `web/css/panels/champ_select_view.css`,
`web/js/panels/build_order.js` + `.css`, `web/index.html` champ-select grid
~L1045-1160). Ambiguous points are resolved with a STATED DEFAULT - correct any
before implementation. Page change => UI-audit subagent BEFORE commit (hard rule).

Layout today (index.html grid):
- `.csv-card-allies` head "Daemon Slayer Build Archetype + Picks": `#csv-archetype-target` + `#csv-picks-target` (PICK cells).
- `.csv-card-pickban` head "Pick & Ban Recommendations": `#csv-pickban-body` (BAN + ALLY PICKS BY ROLE).
- `.csv-card-mypick` head "My Pick": `.csv-mypick` = build chooser (`_csvBuildVariantRowsHtml`) + DS-vs-Enemy-Comp card (`build_order.js`) + summoner strip.
- `.csv-card-enemies` head "Enemies": `#csv-enemies-list` (`.csv-team-list`).
- `.csv-card-suggestions` head "Assessment": assessment + YOUR RECORD (`_csvRenderPersonalRecordBlock`, `.csv-pr`) + CC mounts (`#csv-sugg-cc-conditional-pressure` + cc_blended).

## 1. Ban panel - kill the vertical stretch
The BAN sub-panel (`.csv-pb168-bans` / `.csv-pb168-section`) stretches vertically
with no visual reason. CSS only: stop the section growing - `align-self: start` /
`height: max-content`, drop any `flex: 1` / tall `min-height` on `.csv-pb168-bans`.
File: `champ_select_view.css`.

## 2. DS vs Enemy Comp - remove collapse, go horizontal
`build_order.js buildOrderCardHtml`: delete the collapse/expand state machine
(`_boExpanded`, `.bo-expander`, `data-bo-toggle`, the `rc:build-order-toggle`
listener, the collapsed one-line branch). Always render the full ordered build
HORIZONTALLY - items in a single row (icon + name/delta), wrap as needed - not
the vertical numbered list. Keep the `save + push to client` button + no-double
chip. File: `build_order.js`, `build_order.css` (flex-row `.bo-slots`).

## 3. SR BUILD CHOOSER - cards-left + nested rune panel + per-category push (THE BULK) [SHIPPED 2026-06-01, item 240 part-3 - LIVE PUSH VERIFICATION STILL OWED]
SHIPPED 2026-06-01 (item 240 part-3): build + mock-render + unit tests landed.
3a-3e implemented in web/js/panels/champ_select.js + champ_select_view.css. The
per-category LCU push wiring is in place (apply route push_runes/push_items/
push_summoners gating + set_summoner_spell for spells) but a LIVE champ-select
push has NOT been verified (operator was mode=client). Live verification of the
[PUSH] button + the 3 auto-push checkboxes against a real LCU rune page + item
shop + summoner-spell slots is still owed. Spec below is the as-built contract.

3a. Layout: build-variant cards move LEFT; add a nested panel to their right
    showing the RUNE choices that pair with each build card. Two columns inside
    the chooser. Files: `_csvBuildVariantRowsHtml` (2399) + new rune render +
    `champ_select_view.css`.
3b. Rune selection is INDEPENDENT + sticky. Borders:
    - GREEN border = the user's current rune selection (sticky).
    - Distinct accent border (DEFAULT: amber) = the rune RECOMMENDED for the
      currently-selected item-build card, shown ONLY when it differs from the
      user's current selection. If the user is already on the recommended rune,
      it is just green (no second color).
    - Changing the item-build card does NOT change the user's rune selection;
      it only re-points which rune is "recommended" (amber).
3c. Pre-selection on champ lock: the LAST-USED item build + rune for THIS
    champion are pre-selected (sticky/green) so the operator is not re-choosing
    every champ select. Persist `champion -> {variantKey, runeKey}` in
    localStorage. `_csvSavedChoice(myName)` already persists the variant; add the
    rune key alongside it.
3d. Header control on the "SR BUILD CHOOSER" panel title: one small `[PUSH]`
    button + 3 inline checkboxes `[x] Runes [x] Spells [x] Build`. RIGHT-aligned
    to the panel title, matching the title typography. Checkbox states persisted
    in localStorage (global), last-state remembered. DEFAULT first-run: all
    UNCHECKED (opt-in; nothing auto-pushes until the operator marks one).
3e. Push semantics:
    - A checkbox going unchecked -> checked => IMMEDIATELY save + push that
      category to the LCU client.
    - While a category is checked, a subsequent selection change in that category
      also pushes it (kept in sync).
    - Unchecking => stop auto-pushing that category (fires no push).
    - `[PUSH]` button => manual force-push of ALL currently-checked categories
      now (fallback to the automatic save+push).
    - Per-category LCU commands (already supported by the agent): Runes ->
      `apply_runes`; Spells -> `set_summoner_spell` (both slots from the
      variant); Build -> `apply_item_sets_batch` (the selected build). Reuse the
      `lcuCmd` path + `_csvMaybePushBuildsToLCU` plumbing.
    Files: `champ_select.js` (chooser render + new wiring + persistence),
    `champ_select_view.css`, possibly `dashboard/routes_loadout.py` /
    `tools/gamepc_lcu_agent.py` only if a per-category cmd is missing.

## 4. Assessment - move per-enemy % into the Enemies panel, drop YOUR RECORD
The per-enemy win% lives in `pr.vs_enemies[] = {champId, wr_pct, games}` (today
rendered as the VS chip row inside `_csvRenderPersonalRecordBlock`). Move that
wr_pct to the LEFT of each champion icon in the Enemies panel (`#csv-enemies-list`
/ `_csvRenderEnemies`), joined by champId. Then REMOVE the YOUR RECORD block
(`_csvRenderPersonalRecordBlock` + its `.csv-pr` mount) entirely - it is "remove"
(tear the render), the `pr` payload + `vs_enemies` data wiring STAYS (it now
feeds the enemies panel). Files: `champ_select.js` (enemies render + drop the pr
block), `champ_select_view.css`.

## 5. CC Chain + Conditional CC cards -> center panel
Move the CC mounts (`#csv-sugg-cc-conditional-pressure` = cc_conditional_pressure.js,
+ the cc_blended_ehp_threat mount) OUT of `.csv-card-suggestions` (Assessment)
and INTO the center `.csv-card-mypick` body, BELOW the DS-vs-Enemy-Comp build
card. Files: `web/index.html` (relocate the mount divs), `champ_select.js` (mount
wiring if the render targets them by id).

## 6. Allies picks by role -> match the Enemies panel styling
`_csvRenderAllyRolesHtml` (3207, rendered into the `.csv-pb168-expl` section)
should use the SAME typography + content styling as the Enemies panel
(`.csv-team-list` rows: champ icon + name, consistent type scale). Files:
`champ_select.js` (allies-roles render markup) + `champ_select_view.css` (reuse /
mirror the enemies row classes).

## Verify
`?ui_mock=1#champ-select` mock fixture (`web/data/ui_mock/champ_select_sr.json`) +
Legion monitor capture. Then the 5-phase visual-hierarchy audit subagent
(STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY); resolve every
MUST-FIX in the same slice before commit. The per-category LCU push needs a live
champ-select to fully verify (operator was mode=client); mock covers render.

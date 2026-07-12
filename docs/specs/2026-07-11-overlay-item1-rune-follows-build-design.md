# Item 1 - Rune-Follows-Build (champ select) - Design Spec

Status: interaction model APPROVED by operator 2026-07-11 (mockup v1/v2 iterations).
Next step: a grounded implementation plan (mapped to champ_select.js + the LCU push path).

## Goal

During champ select, the recommended rune page follows the operator's selected
item build, while leaving the operator free to override the page (situationally),
persist a preferred page per build, and author custom builds - all without losing
sight of what the recommended page was.

## Interaction model (approved)

### 1. Runes follow the item build
- On champ pick, or when the operator changes the selected item build, RC loads
  that build's RECOMMENDED rune page (or the operator's SAVED default for that
  build, if one exists).
- Each item build carries one recommended rune page (its default).

### 2. Rune panel = side toggle of all pages
- The rune panel is a SIDE panel (mirrors the generic item-builder panel during
  champ select) listing EVERY rune page available for the champ as a toggle/list.
- The recommended page for the CURRENTLY-selected build is starred.
- The operator can switch to any listed page (an override) - e.g. run an AP item
  build but pick the AD rune page.

### 3. Override + save-default
- Selecting a non-recommended page = an override. It is STICKY while the operator
  stays on the current build, and does NOT re-force the recommended page.
- Changing the build (rule 1) or starting a NEW game discards an unsaved override
  and reloads the recommended (or saved default). Save is the only way to persist.
  [Confirm: an unsaved override is dropped when you switch builds - the v2 mockup
  instead kept it per-build across switches within one game.]
- A "save as default for this build" button persists the current page as the
  default for that champ + build, across future games AND other modes.
- The recommended page is ALWAYS shown/marked even when a different page is in use,
  so the operator always knows what the recommended was if they went situational.

### 4. Custom user builds
- The operator can author custom builds (item build + rune tree).
- A custom build surfaces as a choice for the champ, NESTED in the same panel as
  the generic item builds; its rune page appears in the same rune panel.
- The custom build's authored rune page = its recommended for that build slot.
- DEDUP: if the custom build's runes match an existing page 1-for-1, it reuses that
  page (no duplicate entry). If the operator later alters the custom build so its
  rune page differs by even one subrune, it surfaces as a distinct page.

### 5. Push toggles -> Settings
- The push runes / items / spells toggles move OUT of the build panel into the
  Settings menu, pre-selected ON unless the operator has saved them OFF.

## Data model (conceptual - real mapping is the implementation plan's job)
- Rune pages: champ -> { pageId: { name, tree, keystone, subrunes[], custom? } }.
- Item builds: champ -> [ { name, items[], recommendedPageId, custom? } ].
- Saved default: (champ, buildId) -> pageId. Persisted; survives games + modes.
- Session override: (champ, buildId) -> pageId. Cleared on new game.
- Dedup key: a custom page reuses an existing pageId iff its full rune set (tree +
  keystone + every subrune id) matches; otherwise it mints a new pageId.

## Out of scope (this spec)
- The custom-build CREATOR / authoring UI - designed separately.
- Final Hextech visual styling - an implementation detail; the mockups are
  behavior prototypes, not final visuals.

## To resolve in the implementation plan (grounded in code)
- Where per-build recommended rune pages come from today (build_order / rune data)
  and how a build maps to its recommended page.
- LCU rune-page push wiring: the existing champ_select.js _csvApplyLoadout /
  push-category path and its push flags.
- Storage for custom builds + saved defaults (localStorage mirror vs on-disk).
- The Settings relocation of the push toggles (default-ON-unless-saved-off).
- The exact dedup comparison (tree + keystone + subrune id list).

## Mockups
v1 and v2 were rendered inline during the 2026-07-11 design session as interactive
behavior prototypes (champ tabs Jinx / Ezreal / Malphite; build cards; side rune
toggle; override; save-default; new-game reset; custom-build dedup).

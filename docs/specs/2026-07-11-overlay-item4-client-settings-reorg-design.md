# Item 4 - Settings Menu Reorg ("Client Settings") + Opacity Split - Design Spec

Status: operator intent captured 2026-07-11 (this is the item-4 "DS Controls reorg"
strip-spec). Intent-level - GROUND against the real Settings menu (overlay_ds_controls.js
+ the settings surface) before building. The in-game DS Settings panel reorg + other
panels are a SEPARATE later iteration round (operator: "once we start that process of
iteration when you push the current plan").

## A. "Client Settings" panel (renamed from "Champ Select")
Rename the Champ Select settings panel to "Client Settings" and consolidate, each as its
own item:
- Champ-select settings (existing content stays).
- Pre-Game Lobby (moved in as its own item).
- Post Game Review (moved in). Sub-renames:
  - "Rank-Tier Comparison" -> "Rank-Tier".
  - "baseline window (prior games)" -> "Baseline Games".
- Voice (moved in).

## B. Removed from Settings
- Coaching actions (not needed / not required).
- Headless loop (not needed / not required).
- Data / Metrics (not surfaced as a panel).

## C. Slated for removal (NOT yet - keep for now)
- API Spend Gates - removed once RC is full LLM-deterministic + local CV/OCR/etc.
  (leave in place until that migration lands; flag, do not remove now).

## D. Panel Visibility (reworked)
- Purpose: show / hide the in-game overlay panels, on/off BY MODE.
- Bidirectional sync: toggling a panel's visibility while in-game syncs to this menu,
  and toggling here syncs to the in-game overlay.
- REMOVE the "Out-of-Game" category. Its purpose (letting the operator change these
  contextually while not in a game) is now served by the in-game <-> settings sync above.

## E. Opacity split (global, in-game overlay) [item-7 territory]
Today: a single global opacity dims the whole overlay panel.
Change: split into two layers, each with its own slider -
- Panel BACKGROUND opacity: the background is the opacity-affected visual (dims with
  the slider).
- CONTENT opacity: item icons, words, buttons stay at full visibility by default, on
  their OWN separate slider.
So the operator can dim the panel background while content stays crisp.

## To resolve when grounding (pre-build)
- Map each named item above to the real Settings menu section (overlay_ds_controls.js
  _settingsHtml / _wireSettings) - confirm "Coaching actions", "Headless loop", "API
  Spend Gates", "Data/Metrics", "Champ Select", "Post Game Review", "Voice", "Panel
  Visibility", "Out-of-Game" all exist as named sections and cite their anchors.
- Panel Visibility per-mode + bidirectional sync mechanism (reuse the overlay_settings
  bridge + the per-widget hide path in overlay_layout.js _setHidden/_toggleHidden).
- Opacity split: today --rc-overlay-opacity dims the whole panel; the split needs the
  panel background as a separate layer from content (CSS restructure) with two vars/sliders.

## Related tracks
- Item 1 rune-follows-build moves the push runes/items/spells toggles into Settings
  (default ON) - see 2026-07-11-overlay-item1-rune-follows-build-design.md.
- Item 8 rank-tier selector + relocated role override land in DS Settings - see
  2026-07-11-overlay-item8-rank-tier-stats-panel.md.
- NEXT iteration round: in-game DS Settings panel reorg + other panels.

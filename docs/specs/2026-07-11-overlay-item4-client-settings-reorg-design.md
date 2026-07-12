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

## F. DS Controls panel + Overlay Options panel + lock model (confirmed 2026-07-11)

### DS Controls panel (overlay_ds_controls.js) - knobs only
Display ONLY the 4 DS combat knobs: Enemy armor, Enemy MR, Gold cap, Fight len (s).
REMOVE all else from this panel: reranked item rows (the build panel is enough), reset
item status (-> the item radial's home), Coach/Build/Threat panel-set, Interact now,
Re-arrange, Show dashboard, Keep dashboard, Pin on top, Separate windows, Change pulse
toggle (pulse STAYS ON by default), Auto-passive, Hover to interact. Drop the CONTROLS
but keep underlying behavior at sane defaults; pin exact defaults at grounding (these
drive rc-shell/hotkey behavior - visual removal, not feature rip-out, unless dead).

### Overlay Options panel (overlay_layout.js launcher menu) - the hub
The existing in-game per-panel show/hide/opacity/scale menu becomes the hub for:
- per-panel show/hide + scale (existing);
- per-panel OPACITY SPLIT: background opacity + content opacity, two sliders PER PANEL
  (supersedes section E's "global" framing - it is per-panel, here);
- the item-8 RANK-TIER SELECTOR + ROLE OVERRIDE (both shifted here; synced to the
  out-of-game Client Settings per item 8).

### Lock model (replaces the global Hover-to-interact / ACTIVE toggle)
- Panels are movement-LOCKED by default (no accidental mid-fight drags).
- Opening the Overlay Options panel globally UNLOCKS all panels for move + rearrange.
- Closing it re-LOCKS everything.
- While locked, only specific per-panel elements stay clickable - the interactable
  element + its hit area defined PER PANEL (the panel-by-panel pass, next).

## Related tracks
- Item 1 rune-follows-build moves the push runes/items/spells toggles into Settings
  (default ON) - see 2026-07-11-overlay-item1-rune-follows-build-design.md.
- Item 8 rank-tier selector + role override land in the Overlay Options panel (NOT DS
  Controls) - see 2026-07-11-overlay-item8-rank-tier-stats-panel.md + section F.
- Items 6 (enemy-spell click->countdown) + 3 land in the panel-by-panel interactable pass.

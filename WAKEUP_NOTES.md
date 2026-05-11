# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s165 wrap — 2026-05-10 (flow_03 mode-conditional Champ Select — central + enemies for all 4 modes)

Phase 3 step 3 follow-up from s164. Champ-select view's central panel (My Pick + Build Chooser) and enemies panel now branch per mode (SR / ARAM / Arena / Brawl). Allies + Pick&Ban panels LOCKED per operator — untouched. Single commit shipped: `91a42e1` (1112 ins / 34 del across 7 files, 3 new).

## What shipped (s165)

### Mode-detection plumbing
- New `_csvDetectMode(cs)` helper → `sr|aram|arena|brawl` from `queue_id` + `is_aram`/`is_brawl` flags (450/920 → ARAM, 1700/1710 → Arena, 480 or `is_brawl` → Brawl, default SR).
- `renderChampSelectView()` stamps `section.dataset.csMode = mode`; CSS branches via `#view-champ-select[data-cs-mode="..."]` selectors.
- Sub-line now shows mode label (SR DRAFT / ARAM / ARENA / BRAWL) instead of just queue id.

### `_csvRenderTeam()` — opts arg
- 6th positional `opts` arg added: `{ cellCount, showGuess, allowRolePip }`. Backward-compat with the previous 5-arg call sites (defaults: cellCount=5, showGuess=true, allowRolePip=true).
- ARAM/Brawl ally + enemy lists pass `showGuess: false, allowRolePip: false` — drops the (guess) annotation and role pip since those modes have no role assignment.

### Central pane variants (`_csvRenderCentralPane`)
- SR: existing My Pick + 3-variant SR Build Chooser (Lethal Tempo default / Press the Attack / Hail of Blades). Was empty placeholder.
- ARAM: My Pick + 5-cell horizontal Bench (`csv-bench`) under My Pick + ARAM Build Chooser. Click bench cell → fires `bench_swap` LCU command + visual pulse feedback.
- Arena: card header text swaps to "My Duo + Augments". Duo header (me + duo, 2 cells side-by-side), 3 augment slots (silver/gold/prismatic with active-round highlight), augment options list. Click option → fires `set_augment_intent`.
- Brawl: My Pick + Brawl Build Chooser (same 3-variant template as ARAM since builds are nearly identical).

### Enemies panel
- SR: unchanged (5 cells with role pips + (guess)).
- ARAM/Brawl: 5 cells, no role/guess. **Bug fix**: enemy summ block was `position:absolute; left:50%` from SR layout, which clipped champion names ("/eigar" / "12irand" overlap). CSS override resets to `position:static; justify-self:end` on `[data-cs-mode="aram"]`/`[="brawl"]` so the lock/timer flows naturally to the right edge.
- Arena: dedicated `_csvRenderEnemiesArena()` renders 3 sub-team cards stacked (TEAM 2 / TEAM 3 / TEAM 4, each with 2 champion cells).

### Grid relayout for non-SR modes
- `[data-cs-mode="aram"]` / `[="arena"]` / `[="brawl"]` hide the Pick&Ban panel and change grid-template-areas to `"allies mypick enemies"` (single row) so allies fills the freed row-2 space. SR keeps the 2-row layout.

### Fixtures (3 new)
- `data/sim/flow_03b_aram_select.json` — qid 450, is_aram=true, 5v5 (Garen/Malphite/Vayne/Taric/Volibear vs Veigar/Lux/Brand/Karthus/Soraka), bench=[MasterYi, Amumu, Irelia, Jinx, Pyke], Vayne mid-pick (37s timer).
- `data/sim/flow_03c_arena_select.json` — qid 1700, 4 arena_teams (me=Vayne+Taric, then Sett+Veigar / Garen+Lux / Annie+Mordekaiser), augments.options has 3 silver candidates, my_slots all empty (PICKING silver).
- `data/sim/flow_03d_brawl_select.json` — qid 480, is_brawl=true, 5v5 no roles.

### CSS additions (~450 lines)
- `.csv-bench` / `.csv-bench-cell` (horizontal strip with hover + is-pending pulse)
- `.csv-build-row` (radio-style variants, 14px checkbox + label + runes + 6 item icons; 24px item cells)
- `.csv-duo-row` / `.csv-duo-cell` (Arena allies, ME = indigo, DUO = green when locked, hourglass colors for hovering)
- `.csv-augment-slot` (silver/gold/prismatic borders, active-round inset shadow, filled-state bg)
- `.csv-augment-option` (clickable rows with tier-colored left border)
- `.csv-arena-team` (sub-team card with TEAM N head + 2-cell grid row)

## Files touched (s165)

- `web/js/panels/champ_select.js` — `_csvDetectMode`, `_csvRenderCentralPane`, `_csvBenchHtml/Wire`, `_csvBuildVariantsFor/RowsHtml/Wire`, `_csvArenaPaneHtml`, `_csvWireArenaAugments`, `_csvRenderEnemiesArena` added; `_csvRenderTeam` gained opts arg; `renderChampSelectView` rewritten for mode branching.
- `web/css/panels/champ_select_view.css` — appended ~450 lines of mode-conditional + new-block styles.
- `web/index.html` — 2 cache-buster bumps (CSS 2026051100 → 2026051111; JS 2026051041 → 2026051110).
- `data/sim/manifest.json` — 3 new entries.
- `data/sim/flow_03b/c/d_*.json` — 3 new fixtures.

## Phase B follow-ups (LCU agent on Game-PC)

The dashboard fires these but `tools/gamepc_lcu_agent.py` hasn't been updated yet:
- `bench_swap` — already supported (was used by legacy ARAM bench in `#cs-overlay`). Verify it still works from the new view.
- `set_augment_intent` — NEW. Needs LCU endpoint discovery (Cherry/Arena augment-pick verb). Currently no-ops.

Plus the agent needs to populate:
- `cs.bench` (already done for ARAM)
- `cs.arena_teams` + `cs.augments.{my_slots, options, current_round}` — entirely new for Arena. Fixture-only today.
- `cs.is_brawl` — set when LCU queue_id is 480.

Real build-chooser variants (currently static placeholders) come from `/api/loadout/list` — wire-up is also Phase B.

## What's deferred

Operator did NOT ask for an audit pass on this work — just the mode-conditional layout. Visual-hierarchy audit subagent ritual from `feedback_phase3_fixture_ritual.md` applies if operator declares the page done; this session is more of a step-3 follow-up than a fresh page. Defer until operator signals.

## Next session opener

- Tomorrow-you: if operator wants the visual audit on the 4 modes, run subagent per ritual.
- If operator wants Phase B wiring instead, target `tools/gamepc_lcu_agent.py` — add `set_augment_intent` handler + populate `cs.arena_teams` + `cs.augments` from LCU `/lol-cherry/v1/*` endpoints (need to discover the exact path).
- Either path is fine — both unblock real-fire testing of the new view.

---

# s164 wrap — 2026-05-10 (Champ Select view scaffold — flow_03 + Pick/Ban panel + trade popup)

Long UI iteration session. Phase 3 step 3 — built the new top-level `view-champ-select` page from scratch and iterated heavily on every panel. Single commit shipped: `c0e6043` (1986 ins / 4 del across 10 files, 3 new files).

## What shipped (s164)

### View scaffold + routing
- New `champ-select` view added to `VIEW_IDS` / `VIEW_LABELS` (between `lobby` and `active-match`).
- `<section id="view-champ-select">` in `web/index.html` with 3-col grid: Allies + Pick&Ban Recommendations (col 1), My Pick + Build Chooser (col 2), Enemies (col 3).
- Auto-promotes on `phase=ChampSelect` when `?cs=1` / `localStorage.csView='1'`. Legacy `#cs-overlay` hidden when on the new view.
- `header.css` `body[data-view="champ-select"]` rules for showing the section + hiding the main panels + home-overlay.
- New CSS file `web/css/panels/champ_select_view.css` (742 lines) — all `.csv-*` styles for the new view.

### Ally team panel
- 5 rows with champion icon (32px) | champion name | username | role pip layout.
- Username column hardcoded at `--csv-champname-col: 90px` (after iterations: 88→110→100→90 nudges). The hardcoded value aligns the lock/timer column near "A" of "Allies" header on the 1920-wide viewport. JS-based alignment was attempted multiple times (Range API, span wrap, clone, canvas measureText) — all returned wrong values due to body's `zoom: 1.33` and Chromium quirks; final solution is the hardcoded var.
- Self-row gets the gold "BOT" pip styling matching the pick/ban panel's role chip.
- Lock 🔒 / live countdown (cyan blue + 1px black outline, no "s" suffix per operator) at the start of the summoner col. Both share an 18px right-aligned slot so the timer's right edge never exceeds the lock's right edge.
- Click on username opens the SWAP/TRADE popup. Champion-icon and role-pip clicks were wired then explicitly removed per operator — only username triggers trades now.

### Enemy team panel
- Same row template + 2px gold/red active-round border via inset box-shadow.
- Lock/timer absolutely positioned at `left: 50%` (centered vertically under the "ENEMIES" title); role pip placed in grid col 4 explicitly so it doesn't auto-flow into the now-empty 1fr summ col.
- "(guess)" italic gray tag added between centered lock/timer and the role pip — vertically aligned across all rows.

### Pick & Ban Recommendations panel
- Lives in left column below the Allies card. Panel header removed (operator preferred PICK/BAN labels in the role row as the column markers).
- Header row: PICK label (col 1) + role chip removed + BAN slot (col 3, BAN sits in a 70px sub-slot right-aligned so the distance from BAN-right to panel-right mirrors PICK-left to panel-left).
- 3 pick rows (Performance / Mastery / Meta) — each is a 3-col grid: champ-col (icon + name, source label moved into the reason col header) | reason col (PERFORMANCE/MASTERY/META label + 1-line WHY text) | bans col (3 ban suggestions w/ icon + pct + name).
- Mood toggle row: PICK ONE label + 4 two-line buttons (Comfort Pick / Limit Test / Something New / Comp Synergy). Default Comfort; persists in `sessionStorage.csv-mood`.
- Quick-select clicks: ban icon → `set_ban_intent`, pick icon → `set_pick_intent`. Pick clicks gated on `cs.phase === "FINALIZATION"` OR `cs.my_completed` (operator: "no accidentally banning my own champion"). Once selected: red border on selected, others get `.is-disabled` (pointer-events: none + dimmed) so the operator can't switch their committed choice.
- Border colors: pick = green, ban = red, both selected and on hover.

### Trade popup (SWAP / TRADE)
- Singleton appended to `<html>` (NOT `<body>`) to bypass body's `zoom: 1.33` — `transform: scale(1.33)` with `transform-origin: 0 0` provides matching visual size without scaling its own position values.
- Structure: SWAP/TRADE header row above 3 equal-width buttons (`flex: 1 1 0; min-width: 88px;`). Buttons: champion name (uppercase) / Nth Pick / role (TOP/JUNGLE/MID/BOTTOM/SUPPORT). Pick-order button hides on non-SR-draft modes (`cs.sr_draft === false`).
- Render-then-measure positioning: park off-screen → measure with `visibility: hidden` → compute final left+top → reveal. Horizontally centered on the ALLIES panel; vertically attached just below the clicked username (originally tried username-center but operator's iterations on zoom revealed the offset issue).
- Buttons fire: CHAMPION → `trade_request`, Nth PICK → `request_pick_order_swap`, ROLE → `request_position_swap`.
- LED-dot animation explored (clockwise pseudo-element traveling around cell perimeter every 3s) but removed — wasn't rendering reliably due to body zoom + the cell's containing-block constraints.

### Sim fixtures
- `data/sim/flow_02_lobby_with_others.json` — clone of flow_01 with reframed meta + caption for the canonical 14-step fixture series (Phase 3 step 2).
- `data/sim/flow_03_champ_select.json` — SR Ranked draft mid-pick, Vayne locked BOT, 4 ally + 3 enemy picks done, 6 bans in, 22s on timer, `active_round: { type: "pick", cell_ids: [3, 6] }` so Lulu + enemy LeeSin show the gold border.

## Phase B follow-ups (LCU agent on Game-PC)

The dashboard fires these LCU commands but `tools/gamepc_lcu_agent.py` doesn't yet handle them. Each currently no-ops:
- `set_ban_intent` — set the user's current ban-action champion intent
- `set_pick_intent` — set the user's current pick-action champion intent
- `request_position_swap` — initiate lane swap with target cell
- `request_pick_order_swap` — initiate pick-order swap with target cell
- `trade_request` already supported (used by legacy ARAM bench swap) — verify it works for SR champion trades too

Plus the dashboard expects `cs.active_round` to be populated by the LCU agent based on the LCU's `actions[]` array — currently fixture-only.

## What's deferred (next session per operator)

> "do /done /clear and continue in another session the central panel and the enemies panel redesign for ALL Game modes. *these changes are not going to be just for SR -> I am taking the extra time to do the needed changes for compensating what i can for all the other games modes.*"

Central panel (My Pick + Build Chooser) and enemies panel redesign for ALL game modes (SR draft, ARAM, Arena, Brawl) — explicit operator request. The current scaffold uses SR draft assumptions throughout; ARAM/Arena need mode-specific layouts (no bans, different team sizes, bench swaps, etc.).

## Files touched (s164)

- `data/sim/manifest.json` — added flow_02 + flow_03 entries.
- `data/sim/flow_02_lobby_with_others.json` (new) — 436 lines.
- `data/sim/flow_03_champ_select.json` (new) — 88 lines.
- `web/css/dashboard.css` — added `@import './panels/champ_select_view.css';`.
- `web/css/panels/champ_select_view.css` (new) — 742 lines, all `.csv-*` styles.
- `web/css/panels/header.css` — 3 lines (data-view rules for showing the new section + hiding main + home-overlay).
- `web/index.html` — 61 lines (menu entry + section markup + cache buster bump).
- `web/js/lib/state.js` — 4 lines (VIEW_IDS + VIEW_LABELS).
- `web/js/main.js` — 16 lines (_viewAutoDerive + applyView + handleLcuEnvelope hooks + onState re-fire).
- `web/js/panels/champ_select.js` — 627 lines (renderChampSelectView + _csvRenderTeam + _csvRenderPickBan + _csvShowTradeChoice + helpers).

## Next session opener

Start with flow_03 loaded (`?sim=flow_03_champ_select&cs=1`). Per operator: "the central panel and the enemies panel redesign for ALL Game modes". Central panel = My Pick + Build Chooser pane in the middle column. Enemies panel = right column. Both need mode-conditional layouts that handle SR draft (current scaffold) + ARAM (no bans, bench swaps available) + Arena (2v2v2v2, augments) + Brawl (random 5v5). The Pick & Ban panel and Allies panel are LOCKED — don't re-iterate.

---

# s163 wrap — 2026-05-10 (Pre-Game Lobby v3 polish + conflict UI + AVG/Match grade)

Long UI iteration session on `flow_01_lobby_solo`. Operator-driven incremental polish per the Phase 3 fixture ritual; visual-hierarchy audit subagent ran mid-session and surfaced 5 must-fix items, all addressed. **Page locked for both solo + multi-member states** (placeholder-driven; no separate flow_02 fixture pass needed). Single commit shipped: `e316291` (913 ins / 181 del across 7 files).

## What shipped (s163)

### Layout / visual polish
- **PARTY title true-centered with rank pip** (col 4 grid placement on the title with same template as rows).
- **Top-2 champs in PARTY** (was top-3) so role/rank columns vertically line up with MY TOP 8.
- **Fonts above 13px floor** per `feedback_font_size_viewing_distance.md`: rank pips 9→13px, role pip 11→13px, lv-mc-cat 10→13px, lv-mc-avg-lbl 9→11px, lv-top8-rank-pip 10→13px (with 2/6→1/4 padding tighten + letter-spacing 0 to fit "Diamond IV 30 LP" without truncation).
- **6px gap** between PARTY col 2 (lane prefs) and col 3 (role pip).
- **"live" sub-label hidden** when healthy; only renders on error with bumped 14px red `.is-error` styling.
- **Drop shadow** on `.app-tooltip` and `.lq-mode-menu` (2-layer rgba black) — popovers visually float above content they overlap.
- **Page fits 1080-viewport without scrollbar** — trimmed `.view-section` (margin 4→2, padding 8/4 → 4/2) and `.view-section-head` (margin/padding 8/6 → 4/4).
- **QUEUE panel stretches** to match PARTY height; CHANGE LOBBY MODE button gets even space-evenly buffer.

### MY TOP 8
- **Names left-aligned, tag (notes) right-aligned**.
- **Rank tier color coding** extended from PARTY via shared `.lv-rank-*` (Iron→Challenger).
- **Single green hue for in-party rows** (reverted s162's per-member color matrix); same hue mirrored onto matching PARTY rows via new `.is-top8-mate` class.
- **Unranked entries → "LVL ### : Unranked"** with italic dim treatment, matching PARTY's `.lv-party-empty`.
- Online/offline dot removed from search row.

### PARTY panel
- **Self-row mirror**: col 2 renders operator's `_LV.prefPrimary`/`_LV.prefSecondary` lane icons (mirrors QUEUE picker); col 3 renders DB-assessed role pip (`m.assessed_role` field, fallback `m.preferred_role`).
- **5-slot renderer** with dashed `.is-placeholder` rows for empty seats — auto-populates/depopulates on LCU push.
- **Leader crown swapped** to real League captain-icon-crown PNG (CommunityDragon mirror, downloaded to `web/icons/lobby/captain-icon-crown.png`, served via new `/icons/lobby/` static route in `routes_static.py`).
- **Copy SVG**: 📋 → Phosphor copy-simple (currentColor inheritance via `.lv-copy-svg`).
- **Level → LVL** abbreviation in unranked fallback.
- **Role shorthand normalizer** `_roleShort()`: JGL/JG/JUNGLE → JNG, SUPP/UTILITY/SUPPORT → SUP.

### Primary-lane CONFLICT detection (s162 v15)
- Pre-pass in `_renderPartyMembers` builds a `conflictMap` over (self, members) Primary lane prefs. Non-FILL collisions get classed `is-conflict-self` (red, when self involved) or `is-conflict-other` (orange, no self). Re-runs on every `_setLanePref` change.
- **Self-side**: red 2px outline on Primary lane icon (PARTY) + matching member's; QUEUE Primary button gets red border + diagonal "CONFLICT" pseudo-element overlay (rotate -30deg, 55% opacity bad-color).
- **Non-self pair**: both icons get orange outline; QUEUE button stays clean.

### MAINS panel
- **Overall now 2x2 grid**: `[Games] [K/D/A — D in red]` over `[W - L] [N.NN KDA]`.
- **AVG/Match grid** (renamed from "Averaged"): row 1 `KP% / Vision / CS`, row 2 `AVG 5 / Dmg / CS-per-min`. **Gold dropped**, Vision moved up.
- **AVG 5 grade letter** (S/A/B/C/D, 17px / 900 weight, color-coded — gold/green/info/clock/bad). New `_avg5RankClass()`.
- **KP% 5-tier color bands** (s162 v10) — ≥70 S gold, 60-69 A info, 50-59 B good, 40-49 C clock, <40 D bad.
- **Total games sums per-mode** (RIFT + ARAM + ARENA from `overall.modes`); hover tooltip is a 3-col table via new `data-tt-html` attr on the games span (tooltip system patched to honor it via mouseover selector + innerHTML render path).

### Lane picker
- **Primary/Secondary swap** when picking same role for both — operator-side conflict resolution.
- **Lane popup icons fixed** — root cause was missing `/icons/positions/` static route (was 404'ing); added to `routes_static.py` + `/icons/lobby/`.

## Files touched (s163)

- `dashboard/routes_static.py` — `/icons/positions/` + `/icons/lobby/` routes (+2 lines).
- `data/sim/flow_01_lobby_solo.json` — new fields: `position_preferences`, `assessed_role`, `kp`, `avg5`, `dmg`, `cs_per_min`, `modes` (rift/aram/arena breakdown).
- `web/css/panels/base.css` — tooltip drop shadow (8 lines).
- `web/css/panels/header.css` — extensive (+408 lines).
- `web/index.html` — title spans for grid placement, AVG/Match label, search-row dot removed, cache busters bumped 2026051037 → 2026051050.
- `web/js/main.js` — extensive (+571 lines): `_LV_ICON_CROWN` + `_LV_ICON_COPY` constants, `_roleShort` helper, `_kpTierClass` + `_avg5RankClass` band helpers, `_mcOverallHtml` + `_mcAveragedHtml` + `_mcGamesCellHtml` extracted helpers, `_top8FormatRank` unranked path, conflict pre-pass, IIFE refactor for placeholder slots, `data-tt-html` tooltip path.
- `web/icons/lobby/captain-icon-crown.png` — new asset (2995 bytes, CommunityDragon).

## Phase B follow-ups (LCU agent on Game-PC)

LCU agent (`tools/gamepc_lcu_agent.py`) needs to forward into `state.latest.lcu`:
- `lobby.local_member.assessed_role` — most-played role from rewind_history.db (drives self-row PARTY col 3 pip).
- `lobby.local_member.position_preferences.first/.second` — read direction (current code is write-only via `_setLanePref`).
- `main_champs.champions[].averaged.kp` — kill-participation %, computed per champion.
- `main_champs.champions[].averaged.avg5` — last-5-match performance grade (S/A/B/C/D), rubric: KDA + KP% + DMG share + CS @10/20 + win/loss → percentile bucket.
- `main_champs.champions[].averaged.dmg` + `.cs_per_min` — already wired in fixture.
- `main_champs.champions[].overall.modes` — `{rift, aram, arena}` per-mode game counts + wins (drives total games + tooltip breakdown).
- `party_mains[*].averaged.*` + `overall.modes` — same as above for non-self members.
- `party.members[*].position_preferences` — already wired in fixture; needs LCU read path.

## Next session

Per operator: page is **locked**, ready to apply for live Lobby/Pre-Game.
Next session opens with **flow_02_lobby_with_others** — per s162 ritual, this is mostly a renaming pass since flow_01 already exercises 5-member layout. Then move to **flow_03 Champ-Select**.

# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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

---

# s162 wrap — 2026-05-10 (Pre-Game Lobby page redesign — flow_01 ready for review)

Long UI session. Operator-driven incremental redesign of the entire Lobby view as Phase 3 step 1 of the 14-fixture game-flow build per `feedback_phase3_fixture_ritual.md`. Operator signaled end-of-page with **"Page done — ready for review"** + plans `/done` + `/clear`. Next session **opens with the visual-hierarchy audit** before moving to step 2.

## What shipped (Phase 1 + 2 prep work)

- **Phase 1 — live menu cleanup:** removed Loadouts, Diagnostics, Coach Calls, Bridge Pending, Fleet view sections + dropdown entries. Backend routes preserved (ops tools depend). VIEW_IDS pruned in `web/js/lib/state.js`.
- **Phase 2a — dev panel slim:** dropped RC log tail + Vision Status cards from `view-dev`; only Sim Fixtures list remains.
- **Phase 2b — sim banner de-banner:** layout-pushing DEV PREVIEW banner replaced with a fixed-position corner pill (top-right). `?banner=0` URL param suppresses the pill entirely for clean screenshots.
- **Phase 2c — fixture archive:** 46 prior fixtures moved to `data/sim/_archive/`; manifest reset to `version: 3` with empty `fixtures: []`.
- **Sim mode EventSource stub:** when `?sim=…` is active, `window.EventSource` is replaced with an inert FakeEventSource so the live `/api/state-stream` SSE doesn't race the FakeSocket fixture replay (was causing fixture data to be overwritten by live LCU during dev preview).

## What shipped (Phase 3 step 1 — flow_01_lobby_solo)

### Layout / typography
- All panel titles unified at 15px white centered uppercase (`.lv-panel-title` / `.lv-friends-title`). Section header is `Pre-Game Lobby · live`; per-panel titles render INSIDE each card (NORMAL DRAFT, PARTY, YOUR MAINS / PARTY MAINS tabs, My Top 8).
- View dropdown menu entry renamed `Lobby` → `Pre-Game Lobby` (also `VIEW_LABELS` updated).
- Vertical buffer trimmed across the whole view: `.view-section` margin-top 12→4, padding-top 16→8; `.lobby-view-card` padding 14→8; lobby grid row-gap 14→4 (col-gap kept 14); `.view-section-head` margin/padding-bottom 14/10→8/6.
- `data-view`-based hide rule for in-game pills (champion/zone/cs/vis/gold/lvl/ult/win/game-time): visible only on `view="active-match"` or `view="last-match"`. Replaces the brittle `data-mode="client"` gate that didn't fire in the LCU-says-SR-but-LCU-phase=Lobby state.

### QUEUE panel
- 6-button action strip: `[Accept On/Off] [Party Open/Closed] [Primary Lane] [Secondary Lane] [Cancel Queue] [Find Match]`. Static 110×64px buttons, 2-line content centered. Cancel = red filled, Find Match = green filled with gold pulse animation when `search_state === "Searching"`.
- Lane picker popup repositioned ABOVE the lane-pair wrapper, centered on Primary+gap+Secondary midpoint. Hover shows full UPPERCASE lane name (TOP/JUNGLE/MIDDLE/BOTTOM/SUPPORT/FILL) above icons.
- FILL primary → secondary auto-pinned to FILL; primary FILL→specific role → secondary becomes "needs-pick" (X marker dashed border).
- Change Lobby Mode dropdown: 4-column grid (SR / ARAM / Rotating / TFT). 16 queue choices. Co-op vs AI + Tutorial removed per operator. Click-outside closes.
- queue-block uses `justify-content: space-evenly` so buttons-row + Change Lobby Mode are mirrored vertically (equal space top/middle/bottom).

### Mains panel (YOUR MAINS / PARTY MAINS tabs)
- Tab toggle: green border = selected / red border = deselected. Default tab driven by `lobby.party_size` (1 → YOUR, ≥2 → PARTY); operator-toggle wins once clicked.
- 5-section card layout per row: `Champion (icon + 📋 copy) · Mastery · Recent · Overall (2x2: games / W-L / WR% / total KDA) · Averaged (Gold/CS/Vis on top, H/S/Tnk on bottom)`.
- Summoner name centered above Mastery # (operator's name on YOUR MAINS, party member's name on PARTY MAINS — pulled from fixture or `lobby.members[non-self][i]`).
- Username color palette via `data-color-idx` (self → lavender, members 1–4 → mint/amber/teal/coral). Same idx links Party panel rows to PARTY MAINS cards.
- YOUR MAINS shows 4 cards (operator's top mastery champs). PARTY MAINS shows 4 party-member cards (placeholder when solo).
- Click PARTY MAINS card OR Party row → cross-highlight both with white border (`.is-selected`). Doc click clears.
- Copy clipboard format: `Moonbeam - Vayne - Mastery 8 : 388 K points · 47 Games All-Time · 60% WR`.

### Party panel (top-right)
- Title `PARTY` centered above member rows. Member-count subtitle dropped.
- Per-row 6-col grid: `name | icon-spacer | role | rank | top-3-champs-for-role | actions`. Role + rank shifted LEFT one col vs prior layout to make room for the new top-3-champs col.
- Top-3 champs render as truncated 4-char-max names joined with ` | ` (e.g., `Vayn | Jinx | Kai`). Operator flagged truncation review for next session (4 vs 5 chars).
- Names display short (no `#tag`); copy actions still write the full Riot ID.
- YOU pip removed (border accent on self row signals it). LEADER pip moved RIGHT into actions group, changed ★ → 👑 crown, sized like kick/promote (26×26).
- Right-side actions: `[👑 if leader] [📋 copy] [⬆ promote — leader only] [✕ kick — leader only]`. Promote/Kick fire `window.confirm()`.
- Unranked rendering: `Level NNN : Unranked` (in solo too).
- Peak rank shows season label (e.g., `Peak: S 15 Master 142 LP`) — best of this season vs last season.
- 5 members fit comfortably (gap 1px). Override scoped to party panel only — home.css's auto-fit grid no longer wraps the rows into 2 columns.

### My Top 8 panel (was Recently Played With)
- Repurposed entirely. Existing `_renderFriendsRecent` + Recently Played CSS preserved IN main.js for reuse on a future panel.
- Title: `My Top 8`. Always renders 8 shells (filled or 50%-opacity dashed placeholders).
- Each filled row: `name | games | role | rank | tag | online dot | ➕ invite | ▲▼ reorder | ✕ remove`.
- Add via search input at bottom (Enter or ➕). Rejects duplicates. 9th-attempt prompts to remove someone first ("You need to remove someone from your Top 8, who will it be?" with numbered list).
- User tag click → `prompt()` to edit. Remove → `confirm()`. Reorder via ▲▼ swap with neighbor. Invite → `confirm()` then Phase B pushes LCU.
- Persistence: `localStorage.rc-top8-list`. Sim mode reads `lcu.top8` from fixture first (fixture wins, doesn't pollute operator's localStorage).
- Top 8 rows whose riot_id matches a current party member get `is-in-party` class with light green tint + green border. Tint clears when they leave.
- Search row drops the games/role/rank/tag/dot preview cells (`grid-column: 1/6` on the input) so the operator has 5× wider typing area.

## Bug fixes landed (cross-cutting)

- **handleChampSelect ReferenceError chain** (`b...c5...`): `panels/champ_select.js` was calling `renderLobbyPanel`, `renderHomePanel`, `_viewResolveAndApply`, `_maybeRefreshLobbyView` — all defined in main.js's module scope, none imported. Every call threw `ReferenceError`, silently swallowed by SSE try/catch → lobby view never re-rendered after `state.latest.lcu` was set, even when the operator was in a real lobby. Fix: orchestration moved to a new `handleLcuEnvelope(lcu)` wrapper in main.js that calls handleChampSelect for the champ-select-specific bits and the cross-cutting renders directly. All 4 call sites updated (WS onmessage, SSE handler, HTTP fallback x2). Eliminated the "refresh loses lobby data" behavior the operator hit repeatedly.
- **home-overlay + lobby-overlay leakage:** `renderHomePanel` and `renderLobbyPanel` now hard-gate on `body.dataset.view === "home"` so the overlays don't leak onto Lobby/Dev/etc. views (was previously firing because `_homeShouldShow(lcu)` returned true based on phase alone).
- **Background agent (separate session):** `67e50d2 fix(icons): resolve Kai'Sa + DDragon-rename champion icons on home view` — `_resolveChampId` made authoritative across home-view recent-5 / Tonight's Pick / hero motif / dev replay panel.

## Phase B follow-ups (DO NOT START until operator OKs)

LCU agent on Game-PC (`tools/gamepc_lcu_agent.py`) needs to forward into `state.latest.lcu`:
- `lobby.members[].summoner_level` (for Unranked fallback display)
- `lobby.members[].rank` + `peak_rank` (with `season` label) — Riot Personal-tier API key already approved (FU04, ADR-006, see `core/riot_api.py` from s148)
- `lobby.members[].position_preferences` + `lobby.party_type` (for new lane picker + party-toggle write-back)
- `lobby.members[].top_role_champs` (top 3 champs per role from rewind_history.db)
- `lobby.local_member.auto_accept` (LCU `/lol-matchmaking/v1/ready-check/auto-accept`)
- `main_champs` + `party_mains` (top-1 champ per non-self member, joined w/ champion-mastery)
- `top8` enrichment (online status from `/lol-chat/v1/friends`, games count + role from rewind_history.db) — Phase A reads operator-curated localStorage list

LCU push commands needed (`/lcu-cmd` queue):
- `lobby.set_party_type` · `lobby.set_position_prefs` · `lobby.set_auto_accept` · `lobby.invite_player` · `lobby.kick_member` · `lobby.promote_leader` · `lobby.create_practice_tool`

Other follow-ups:
- **Truncation review** for Party panel top-3-champs col (currently 4-char max — operator flagged 4 vs 5 char review).
- **Settings page hex palette** for editable per-member username colors (linked to the existing `[data-color-idx]` system).
- **Brawl removal sweep** — chip already spawned (Riot deprecated Brawl).
- The relocated `_positionLobbyTitles` JS helper is now a no-op stub — kept for any orphan callers; safe to delete in a cleanup pass.

## Files touched (s162)

- `web/index.html` — heavy rewrite of view-lobby section markup; cache buster `?v=2026051001` → `2026051037`.
- `web/css/panels/header.css` — extensive (view-section + lobby card + queue-block + mains + party + Top 8 + Recently Played styles).
- `web/css/panels/active_match.css`, `panels/team_context.css`, `panels/input_activity.css`, `dashboard.css` — comment updates only (Edge → Chrome, baseline 1920×1080).
- `web/js/main.js` — handleLcuEnvelope wrapper, lobby view render rewrites, Top 8 CRUD, Mains tabbed panel, party row 6-col grid, click-to-select, copy-to-clipboard format, JS-based title positioning (later removed), color palette via data-color-idx, friends-recent code preserved as `_renderFriendsRecent`.
- `web/js/panels/champ_select.js` — handleChampSelect cleaned (orchestration moved out).
- `web/js/lib/state.js` — VIEW_IDS pruned + label rename.
- `web/js/sim.js` — corner pill replaces banner, EventSource stub, fixture-driven `lcu` envelope replay.
- `web/js/panels/dev.js` — render simplified (log tail + vision dropped); preview link clears `#hash`.
- `data/sim/flow_01_lobby_solo.json` — new fixture: solo (sort of — 5 members for layout testing) with `lcu.lobby.members`, `main_champs`, `party_mains`, `friends_recent`, `top8`, position prefs, ranks, peak ranks, top role champs.
- `data/sim/manifest.json` — reset, lists `flow_01_lobby_solo` only.
- `data/sim/_archive/` — 46 prior fixtures moved here.

## Next session — review-first per ritual

Per `feedback_phase3_fixture_ritual.md`, when operator declares fixture done:
1. **Run visual-hierarchy audit subagent** on the rendered Pre-Game Lobby view (sim fixture `flow_01_lobby_solo`). Capture monitor 0 first; brief the agent with the screenshot + relevant CSS files + the spec lineage (operator wants tight density, viewing-distance fonts per `feedback_font_size_viewing_distance.md`, neo-fintech palette). Format: prioritized must-fix / consider / looks-good. ≤250 words.
2. **Review with operator** — they decide per-item.
3. **Iterate fixes** inline. Re-screenshot.
4. After alignment, **start Phase 3 step 2 (`flow_02_lobby_with_others`)** — the spec there is mostly identical to step 1 but explicitly multi-member from the start. Likely a renaming pass since the current `flow_01_lobby_solo` is already showing 5 members for layout dev.

---

# s161 wrap — 2026-05-10 (s153–s161 chain: SR-lobby flicker + Active Match scaffold + ZEN/DEV/tooltip polish)

Long live-fire session. Operator was mid-Arena game when it started, finished SR draft mid-session, lobbied between games. Nine commits, three independent bug chains plus Active Match step 1.

## What shipped

### Mode-flicker chain (closed)
- **s153 (`96bf4ee`)** — `dashboard/_state_builder.py` mirrors the s150 LCU lobby/CS pre-flip into the corresponding `*_mode` / `has_game` flag on the envelope-local copy of `health` so HTTP `/api/state`'s `onHealth` resolver sees in-game flags during the pre-flip window. Tests: `tests/preflip_mode/test_state_builder_preflip.py` +4.
- **s157 (`0e3d87a`)** — same mirror for the WS push path. Discovered s153 only patched HTTP — supervisor's `agents/agent2_backend/file_ingest.py` reads `health.json` raw and broadcasts to `:8891/push`, bypassing the mirror. Extracted `resolve_mode_key` + `apply_preflip_mirror` helpers in `_state_builder.py` and called them from `_check_one` (with `loop.run_in_executor` so the sync `lcu_summary` HTTP doesn't block the supervisor event loop). 25/25 existing preflip tests still green. **Verified live**: pill flipped CLIENT → SR and held steady across 35s.
- **s158 (`bd0c88e`)** — mode/view transition log. `setMode` and `applyView` now stamp into `window.__rcDebugLog` ring buffer (50 entries) + `console.log [rc-mode] [rc-view]` lines + a floating `#rc-dbg` overlay activated by `?dbg=1` URL or `localStorage.rcDebug='1'`.

### LCU agent (Game-PC `C:\RC-Agent\gamepc_lcu_agent.py`)
- **s154 (`3a3bf58`)** — queue_id fallback to `/lol-gameflow/v1/session.gameData.queue.id` when the CS-session endpoint omits `gameData` during BAN_PICK. Without this, `champ_select.queue_id=0` → `cs.sr_draft=False` → DS engine-profile chooser stayed hidden during draft. Repo + deployed copy both patched; agent restarted (pid 11072 → 15476).
- **s155 (`5c39b9b`)** — `lock_pick` race-tolerance: cast `actorCellId`/`localPlayerCellId` to int explicitly; treat "already locked on requested champ" as success (handles dashboard-button vs in-game-button race + apply_runes/apply_item_set serializing ahead of lock_pick). Dashboard `champ_select.js` lock button now polls the agent reply via `lcuPollResult` and stamps `cs-my-state` with `✓ LOCK SENT` / `✓ ALREADY LOCKED` / `✗ Lock failed: <err>`. Agent restarted (pid 15476 → 10508).

### Daemon Slayer "ds not loaded at all" chain (closed)
- **s156 (`6c4a940`)** — two stacked failures, each silently swallowed by SR coach's DEBUG-level except:
  1. Champion-id format mismatch — coaches feed display name (`Kai'Sa`) but DDragon/DS keys are DDragon-ID (`Kaisa`). Fix: `agents/daemon_slayer/server.py` builds a lazy reverse map (display→ID, cached per snapshot) and all 4 champion-taking routes (`/stats`, `/dps`, `/rank`, `/beam`) resolve through it. Covers MonkeyKing/Wukong, Renata/Renata Glasc, Nunu/Nunu & Willump, and the apostrophe family (Kai'Sa, K'Sante, Rek'Sai, Cho'Gath, Kha'Zix, Vel'Koz, Kog'Maw, Bel'Veth). +8 server tests.
  2. Trinkets eat 6-slot DS budget — once user bought 5 components + Farsight, `resolve_many` returned 6 ids and `/rank` refused with HTTP 422. Fix: `core/daemon_slayer_resolver.py` adds `resolve_inventory` (drops 3340/3363/3364 trinkets, 2003/2031/2055 wards/potions, 2138-2140 elixirs); SR coach `coach_integration/_coach.py:281` switched. +7 resolver tests. **Live verified**: `daemon_slayer_picks=5` populated within 2 coach ticks; `#ds-pill` rendered `◆ Stormrazor +116dps`.

### Active Match view (step 1 scaffold)
- **s159 (`3f72795`)** — new view ID `active-match` in `VIEW_IDS` + `VIEW_LABELS`. Menu entry between Lobby and Last Match. `<section id="view-active-match">` in `web/index.html` with 3 panes (CALL · BUILD · MAP). `web/css/panels/active_match.css` (new). `web/js/panels/active_match.js` (new) exports `renderActiveMatch(payload, ctx)` + `activeMatchEnabled()` flag check (`?am=1` URL or `localStorage.activeMatch='1'`, sticky once URL flag fires). `main.js _viewAutoDerive` auto-promotes to `active-match` when enabled AND in-game. Dispatcher hook in `onState`.
- **s160 (`57886e1`)** — grid restructure per operator: 2 columns instead of 3. Left column stacks CALL on top of BUILD (1.1fr); right column is MAP spanning both rows (2fr — ~2× s159 width). Template: `grid-template-areas: "call map" / "build map"`.
- **s161 (`8a857c4`)** — ZEN pill removed from footer prefs-chip (`_refreshPrefsChip` no longer pushes `zen:off`). DEV banner toggle (`#dev-banner-toggle`) hidden permanently with inline `display:none !important` (element preserved so JS hooks resolve). `.app-tooltip` font bumped 14→17px / line-height 1.4→1.45 / max-width 400→480 / padding 8 14→10 16. CSS cache-buster bumped twice this session (2026042614 → 2026051000 → 2026051001).

## Key decisions

- **Pre-flip mirror lives at the envelope layer, not in RC's app-state.** `_state_builder.py` and `file_ingest.py` both compute the mirror at emit-time. `app/_health_monitor.py` (frozen) keeps writing the raw `health.json` — tweaking RC's `_arena_mode/_aram_mode` flags during lobby would have side-effected other RC code paths that assume those mean "real game in progress."
- **DS server gets the resolver, not the clients.** Server-side display-name resolution at `agents/daemon_slayer/server.py:215` benefits all coaches (SR + ARAM + Brawl + Arena) without 4 parallel client-side patches. `resolve_many` stays untouched for calibration / mirror callers; new `resolve_inventory` is the inventory-only sibling.
- **Active Match opt-in via flag, not a default flip.** `?am=1` + sticky localStorage so the operator can A/B against the existing layout before it becomes default. Steps 2-5 will refine the layout in-place — no UI risk to non-opted-in users.
- **CSS cache-buster bumped twice.** Browsers cached the s159 layout after the s160 grid rewrite; a single `?v=` bump per session is fine, two is fine when content actually changes mid-session.

## Follow-up still open (NOT shipped)

- **`web/js/panels/map_state.js:720`** — bare `gameTime.textContent` reference, line 721 is `MM.gameTime.textContent`. Pending since s151. Fires once per second; ~200 console errors per session. Fix: delete line 720.
- **Bridge-pending view** — operator wants kept (the `routes_bridge_pending.py` route IS frozen per CLAUDE.md so don't delete) but moved off the main view dropdown into a hidden access button on the Dev panel. Step 5 of the Active Match plan handles this.
- **Fleet view** — operator wants removed entirely. Step 5 of the plan.

## What's next — Active Match steps 2–5 (operator-locked)

Operator's locked decisions from this session, before /clear:
- All in-game modes share the layout (`sr / aram / arena / brawl`). TFT excluded.
- STATS panel removal scope: in-game only; preserve for last-match.
- NEXT folds into RIGHT NOW as a continuous block (reformat content, simplify).
- Build sequence is the agreed Day 1–5; tonight shipped Day 1 only.

### Step 2 — DS engine in BUILD pane (icons + owned-as-text + per-tick rerank)

`web/js/panels/active_match.js#renderActiveMatch` BUILD branch needs:
- **Item icons**, left-to-right by DS priority (highest delta_dps first).
- Use the existing icon-resolver pattern from `web/js/panels/item_build.js` (look for `_iconForItem` / `dataDragon` URL builder — already handles 16.9.1 patch).
- **Owned items as plain text** — operator quote: "the purchased items can be a list/text view - i know i have them I bought them in game." Comma-separated, single line, dim color.
- **DS picks must update on every coach tick AND on every shop buy.** Currently `_last_ds_rows` is set only inside the SR coach's per-tick path (`coach_integration/_coach.py:297`). Two ways to add shop-buy responsiveness:
  - (a) Cheap: re-rank inside `renderItemBuild`/`renderActiveMatch` when `state.latest.sr.items` differs from the items the picks were computed against.
  - (b) Expensive but more correct: add a fast `/api/ds-rerank` endpoint on the dashboard that calls `daemon_slayer_client.rank_for` synchronously with the current items+champion+level. Frontend hits it whenever owned items change.
  - **Recommend (a)** for v1 — `daemon_slayer_picks` is already keyed by champion+items in the JSON, the JS can detect drift and just re-render from a cached rank_for response. Keep server simple.

### Step 3 — Enemy-comp threading

`coach_integration/_coach.py:280-288` calls `rank_for` with hardcoded `target_armor=80.0`, no `target_mr`, no `target_max_hp`, no `target_bonus_hp`. That's why DS picks "never differ on enemy composition." Fix:
- Compute `target_armor` / `target_mr` from the enemy team's owned items + each enemy champion's base armor/MR @ current level. Sum of (enemy_armor + enemy_bonus_armor_from_items) / 5.
- Compute `target_max_hp` / `target_bonus_hp` similarly. Existing helper at `core/daemon_slayer_resolver.total_bonus_hp` already does the bonus-HP sum from item ids.
- Pull enemy items from `state.latest.sr.enemy_team` (each row has `items` per `coach_integration/_coach.py` payload shape — verify by reading `coaching_data.json` mid-game).
- ARAM/Brawl/Arena coaches have similar hardcoded values — same threading pattern.
- New tests: `tests/phase2_smoke/test_enemy_comp_threading.py` with synthetic enemy team payloads → verify `rank_for` is called with non-zero target_armor/mr/bonus_hp.

### Step 4 — Static SR map + ZOI/threat overlay

MAP pane currently shows placeholder text. Replace with:
- `<img src="/static/map_sr.png">` (need to source/commit a clean static SR map asset under `web/img/map_sr.png`). Repeat for `map_aram.png`, `map_arena.png`, `map_brawl.png` — all 4 modes.
- Overlay `<canvas>` or `<div>` layer absolutely-positioned over the img, painting:
  - **Red** ZOI threat (enemy projected position circles)
  - **Yellow** gank lane corridors (high-traffic ward gaps)
  - **Purple** MIA pings (recent enemy-out-of-vision events from `vision_tracker`)
  - **White** ward dots (existing `data/vision_state.json`)
- `vision_tracker.py` already publishes `data/vision_state.json` with timestamps + positions. Source: `reference_vision_tracker` memory.
- Operator quote: "the map is not being used for the intended purpose either - I would rather a STATIC map of the mode, and the ZOI threat / gank / MIA / hard coloring." Hard coloring = solid fills, not the soft heat-map gradients in the current minimap render.

### Step 5 — Zen-lock + RIGHT NOW fold + housekeeping

- **Zen mode locked while in-game.** Currently zen is a manual toggle. When `state.mode in {sr,aram,arena,brawl}` AND view is `active-match`, force `body[data-zen="1"]`. Restore previous zen state when view changes or game ends.
- **NEXT folded into RIGHT NOW.** Operator wants a single continuous block, not two adjacent panels. Tonight's CALL pane already concats `action / objective / next` — refine the formatting. STATS removed in-game per operator.
- **Bridge-pending → dev panel button.** Don't delete `routes_bridge_pending.py` (frozen). Drop the `bridge-pending` entry from `VIEW_IDS` and from `#view-menu`. Add a `<button id="dev-open-bridge-pending">` inside `#view-dev` that toggles a `<details>` block (or pops a modal) showing the bridge-pending content. Hidden from main directory.
- **Fleet view deletion.** Drop `fleet` from `VIEW_IDS`, remove `<section id="view-fleet">`, drop the menu entry, delete `web/js/panels/fleet.js` if it exists. Save the operator a click in the dropdown.
- **CSS cleanup.** Remove `body[data-view="bridge-pending"] *` rules from `header.css` after the entry is gone. Same for `body[data-view="fleet"]`.

## What NOT to redo

- **Pre-flip mirror is at the envelope layer** (HTTP `_state_builder.py` + WS `file_ingest.py`). Don't go patching `app/_health_monitor.py` (frozen) or RC's app-state to set `_arena_mode` during lobby.
- **DS resolver is server-side** (`agents/daemon_slayer/server.py`). Don't add a client-side champion-id normalizer.
- **`resolve_inventory` is the new inventory-only path.** `resolve_many` keeps the full set for calibration/mirror callers — don't change its behavior.
- **Active Match auto-promote is `?am=1`-gated.** Don't flip it to default-on until steps 2–5 land and operator confirms.

## Live state at /clear

- RC pid 14884 (last restart for s156 SR coach pickup), `last_reload_ok=true`.
- DS server respawned for s156, `engine_version=0.60.0`, `patch=16.9.1`, 705 items, 172 champs.
- Phase-3 supervisor restarted for s157 (pid was 16436 at last check).
- Game-PC LCU agent restarted twice (pid 11072 → 15476 → 10508).
- Cross-Claude bridge healthy at session start (gamepc + peer daemons alive).

## Blockers
- None.

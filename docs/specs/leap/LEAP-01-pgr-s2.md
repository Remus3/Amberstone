# LEAP-01 - Post Game Review reframe, stage S2 (single-match richer LAYOUT)

> P3 AMENDMENT (judge panel 2026-07-17, supersedes conflicting text below):
> winprob (promoted to the #2 hierarchy slot in D2/D3) is SR-ONLY mode-gated inside
> _setPhases (web/js/panels/last_match.js:1476, skip at :1466-1472) - it self-hides on
> ARAM/Arena. Treat winprob as a NAMED mode-gated element in D5 alongside lane-compare;
> the ARAM/Arena layout must reserve/collapse its slot per the SCOPE-3 no-hole rule + AC8.

Status: SPEC (Fable 5 forward-leap portfolio, 2026-07-16). No code in this file.
Owner of execution: one cold Opus 4.8 (Max20) session, effort high.
Scope discipline: this spec is self-contained. A session with ONLY CLAUDE.md +
this file has everything it needs. Do not re-derive scope from chat or memory.

--------------------------------------------------------------------------------
## GOAL
--------------------------------------------------------------------------------

front-load the thinking into specs; execution sessions are typing, not deciding.

Reframe the per-match Post Game Review view (`#view-last-match`) from its current
hero + 3-tab split (Build / Graph / AI Analysis) into ONE cohesive aggregator-G-style
single-scroll richer layout with a clear top-to-bottom information hierarchy. This
is a PRESENTATION / COMPOSE effort over already-shipped panels and routes. It adds
NO new scoring, NO new routes, NO new data engine, and touches NO database schema.

The one-line operator intent: when I open Post Game Review I should see, in one
scroll, "how did I do (verdict) -> when did the game swing -> how did my lane go ->
was my build/skills good -> full scoreboard" - without clicking a tab to find the
win-prob graph or the lane matchup.

--------------------------------------------------------------------------------
## EVIDENCE (ground truth, cited; probed 2026-07-16)
--------------------------------------------------------------------------------

Current PGR page (what exists today):
- Menu entry "Post Game Review", `data-view="last-match"` - `web/index.html:48`.
- View container `#view-last-match` - `web/index.html:1680`.
- Rendered by `renderLastMatch(data)` - `web/js/panels/last_match.js:415`; fetch
  `fetchAndRenderLastMatch()` from `/api/last-match` - `last_match.js:378`.
- Hero band `.lm-hero` with `#lm-hero-score` (0-100), `#lm-hero-role-grade`, KDA,
  result + grade badges, detailed-stats grid (Gold% / Vision / CS / Tanked / KP%)
  - `web/index.html:1724-1795`.
- Player-snapshot card `#pgr-snapshot-card` "folds in + replaces #lm-hero-score,
  the standalone #lm-hero-role-grade display, and the 5-bar" - `web/index.html:1690-1694`;
  GPI radar sibling `#pgr-gpi-radar` - `web/index.html:1700`.
- 3-TAB split `#lm-tabbed-section`, tabs Build / Graph / AI Analysis, persistence
  key `rc-pgr-tab` - `last_match.js:276-334`. Comment at `last_match.js:285`:
  "s220 PGR S4: tabs reframed 4 -> 3 (build / graph / ai-analysis)".
- Team scoreboard `#lm-tc-table` (`lm-tc-*` rows) - `last_match.js:686-746`.

Already-shipped PGR panels (COMPONENTS to reuse, NOT rebuild - old S2-S5 wave,
LEDGER items 275 / 276 / 277, 2026-06-02; catalog in `docs/PGR_REFRAME_S2.md`):
- `renderPgrBuildWpa(data)` career item-WPA + skill-WPA strip - called at
  `last_match.js:444`; panel `web/js/panels/pgr_build_wpa.js`.
- `renderPgrLoadout(data)` descriptive runes/augments + spells - `last_match.js:447`;
  `web/js/panels/pgr_loadout.js`.
- `renderPgrLaneCompare(data)` lane / role head-to-head - `last_match.js:450`;
  `web/js/panels/pgr_lane_compare.js` (mode-aware; hides for ARAM / Arena).
- `renderPgrWinprob(matchId, operatorTeam)` / `renderWinprob(...)` inline-SVG
  win-prob "phases that mattered" curve, mount id `pgr-winprob-mount` -
  `web/js/panels/pgr_winprob.js:27,266,293`.
- `_setPhases(m, enriched)` early/mid/late phase cards - `last_match.js:453`;
  `web/js/panels/post_game_phases.js`.
- `renderPlayerSnapshot(...)` snapshot card -> `#pgr-snapshot-card`
  (`web/js/panels/player_snapshot.js`, LEDGER 782).

Data sources (ALL local, ZERO Claude, ZERO live Riot; already wired):
- `/api/last-match` - `dashboard/routes_last_match.py` - rosters + KDA + items +
  grade + `enriched` (incl. per-participant `at_n` gold@N / cs@N) + `quick_review`.
- `/api/post-game-rubric` `total_score` - `dashboard/routes_post_game_rubric.py` -
  the EXISTING role-weighted STAT 0-100 rubric powering `#lm-hero-score`.
- `/api/post-game-wpa` - `dashboard/routes_post_game_wpa.py` - per-frame win-prob.
- `/api/item-wpa` (`dashboard/routes_item_wpa.py`), `/api/skill-wpa`
  (`dashboard/routes_skill_wpa.py`) - the build-WPA lenses.
- Store: `data/rewind_history.db` (participants + timeline_frames) - the enriched
  stats source; S2 consumes it ONLY through the routes above (no new SQL).

The two-scores distinction (load-bearing for the S2/S3 boundary):
- EXISTING `#lm-hero-score` = `_setHeroScore` (`last_match.js:436`) fed by
  `routes_post_game_rubric.total_score`, a role-weighted STAT rubric. SHIPPED.
- The NEW aggregator-G-style headline score is a DIFFERENT number and is DEFERRED to
  S3 (`docs/PGR_REFRAME_S2.md:32-36`; CLAUDE.md Settled). S2 keeps the existing
  hero score verbatim and introduces NO new scoring math.

Downstream trigger (not part of S2): Draft Tool Z8 second-opinion "pick up after
PGR S2 lands" - `BACKLOG.md:145`. Swing-moment localizer folds into later PGR
work, not S2 - `BACKLOG.md:182`.

Reconciliation note (documented drift - read before you "discover" it):
CLAUDE.md Settled calls the PGR reframe "biggest pending non-engine item" and
stages it S2-S5, YET an earlier S2-S5 wave already SHIPPED the pgr_* panels above
(they are bolted onto the 3-tab render). There is NO contradiction to resolve in
code: the panels exist and work. What is NOT done is the COHESIVE single-scroll
richer LAYOUT that composes them. LEAP re-scopes the staging around that gap (see
SCOPE). Do not treat the shipped panels as missing, and do not rebuild them.

--------------------------------------------------------------------------------
## SCOPE + NON-SCOPE
--------------------------------------------------------------------------------

IN SCOPE (S2 = LAYOUT / COMPOSITION only):
1. Restructure `#view-last-match` into ONE vertical single-scroll layout with the
   hierarchy below. Retire the Build / Graph / AI-Analysis TAB split; the panels
   that lived behind tabs become always-visible stacked sections (optionally with
   lightweight in-page anchor jumps - see DESIGN DECISIONS).
2. Order the existing panels into the aggregator G single-match hierarchy:
   (a) HERO verdict band (existing hero + snapshot card + existing 0-100).
   (b) WIN-PROB SWING graph (`renderPgrWinprob`, mount `pgr-winprob-mount`) -
       promoted OUT of the Graph tab to the top, right under the hero.
   (c) LANE / ROLE matchup (`renderPgrLaneCompare`) - SR only; auto-hidden on
       ARAM / Arena by the panel's existing mode gate.
   (d) BUILD graded (`renderPgrBuildWpa`) + LOADOUT strip (`renderPgrLoadout`;
       Arena shows augments).
   (e) PHASES cards (`_setPhases`).
   (f) TEAM SCOREBOARD (`#lm-tc-table`).
   (g) Quick review / takeaway + review-nav button retained.
3. Mode-adaptive single page: SR / ARAM / Arena render from the same layout with
   mode-conditional blocks (the existing panels already self-hide by mode; S2 must
   ensure the layout does not leave a hole when a block hides - "-" sentinel /
   reserved slot, no reflow).
4. Responsive pass at the 1920x1080-with-Chrome-chrome baseline (usable viewport
   ~1920x920); `main` flex-grows into extra height; no `100vh` pinning added.
5. Update `web/data/ui_mock/last_match_{sr,aram,arena}.json` if the reframed layout
   needs any fixture field it does not already carry (prefer reusing existing
   fields; the fixtures already drive all shipped panels).
6. 5-phase fixture UI audit BEFORE commit (mandatory - see VERIFICATION).

NON-SCOPE (explicitly out; each has an owner / stage):
- The NEW aggregator-G-style headline 0-100 score = S3. S2 MUST NOT pre-build it, must
  not add a new scoring formula, and must not touch `_setHeroScore` math. (See
  GHOST LIST + CLAUDE.md Settled.)
- New routes, new panels, new fetches, new DB columns, new SQL. S2 is compose-only.
- Rewriting any pgr_* panel's internals or the WPA lenses.
- Draft Tool Z8 integration (downstream of S2 landing - `BACKLOG.md:145`).
- Swing-moment / "biggest swing" annotation localizer (later PGR stage -
  `BACKLOG.md:182`).
- Overlay item 4 / item 8 and any live-gated overlay work (Lane U owns those; see
  GHOST LIST).

S3-S5 SEQUENCING MAP (LEAP re-scope; S2 owns only its row):
- S2 (THIS spec): single-scroll richer LAYOUT + hierarchy + mode-adaptivity +
  responsive. Layout only.
- S3: the NEW aggregator-G-style headline 0-100 score - an RC heuristic over enriched
  stats (blends the existing stat rubric with a WPA-swing term), NO Claude / NO
  Riot live dependency. Replaces / augments the hero score. This is the score the
  Settled line defers.
- S4: swing-moment evidence - annotate the win-prob graph with the biggest-swing
  phases (the net-new Overlay App E lift, `BACKLOG.md:182`) + deeper "phases that mattered"
  drill-down.
- S5: polish - ARAM / Arena layout variants, tablet / narrow responsive, and the
  dedicated per-page audit tail carried in `ROADMAP.md:52`.

--------------------------------------------------------------------------------
## DESIGN DECISIONS (pre-answered - execute, do not re-open)
--------------------------------------------------------------------------------

D1. Tabs vs single-scroll: SINGLE-SCROLL. Remove the `#lm-tabbed-section` tab
    switching; stack the former tab panels as sections. Keep a slim sticky in-page
    anchor row (Verdict / Swing / Lane / Build / Team) ONLY if it costs no new
    dependency and passes the audit; if it complicates the audit, ship pure scroll.
    Fallback if a session finds single-scroll regresses density badly: keep the
    section order but collapse long sections behind native `<details>` (already
    used at `last_match.js` hero-stats-details), NOT a tab controller.

D2. Hierarchy (top -> bottom), one column on the 1920 baseline:
    HERO verdict -> WIN-PROB SWING graph -> LANE matchup (SR) -> BUILD graded +
    LOADOUT -> PHASES -> TEAM SCOREBOARD -> quick-review/takeaway + review button.
    Rationale: verdict first (what happened), swing second (aggregator G headline),
    lane third (the 1v1 story), build fourth (the actionable change), scoreboard
    last (reference). Matches `docs/PGR_REFRAME_S2.md:38-56` intent that the old
    pass only partly delivered by keeping tabs.

D3. Reused panels + their mounts (compose, do not modify internals):
    | Section | Function | Mount / anchor | Module |
    |---|---|---|---|
    | Hero + snapshot | `_setHero` / `_setHeroScore` / `renderPlayerSnapshot` | `.lm-hero` / `#pgr-snapshot-card` | last_match.js / player_snapshot.js |
    | Win-prob swing | `renderPgrWinprob` | `#pgr-winprob-mount` | pgr_winprob.js |
    | Lane matchup | `renderPgrLaneCompare` | its own container | pgr_lane_compare.js |
    | Build graded | `renderPgrBuildWpa` | its own container | pgr_build_wpa.js |
    | Loadout | `renderPgrLoadout` | its own container | pgr_loadout.js |
    | Phases | `_setPhases` | phases container | post_game_phases.js |
    | Scoreboard | team-comp render | `#lm-tc-table` | last_match.js |
    S2 moves WHERE these mount in the DOM and CSS grid; it does NOT change what
    they render. The render calls already run every `renderLastMatch` pass
    (`last_match.js:425-453`), so no fetch wiring changes - only DOM placement.

D4. Data fields surfaced (already available - no new query): hero uses champion,
    mode, KDA, result, grade, Gold% / Vision / CS / Tanked / KP% (`index.html`
    hero grid). Enriched `at_n` (gold@N / cs@N / at_n_minute) already feeds
    lane-compare. Loadout uses runes (perks) / summoner spells / augments already
    surfaced by `/api/last-match` + the dictionaries. Per `docs/PGR_REFRAME_S2.md:29`
    all of these come THROUGH the existing routes - S2 writes no new `rewind_history.db`
    access.

D5. Mode adaptivity: one page for SR / ARAM / Arena. Lane-compare hides on
    ARAM / Arena (existing panel gate); the layout reserves no lane slot on those
    modes (block absent, siblings do not shift). Arena loadout shows augments
    (existing `_isAugmentMode` in pgr_loadout.js). Drive all three via
    `?ui_mock=1&mode={sr|aram|arena}#last-match`.

D6. Styling: extend `web/css/panels/last_match.css` (`lm-*` rules) with the new
    grid / stack; keep the four pgr_*.css files untouched (they own their panel
    internals). Use v2.1 semantic tokens + 8px spacing. Font floors >= ~13 / 15 /
    18px (`tests/test_pgr_child_panel_floor_guard.py` is the guard). "-" sentinel
    for any absent value; reserved slot so absence never reflows siblings.

D7. Tab-persistence cleanup: `rc-pgr-tab` localStorage key + `_migrateLegacyTab`
    become dead once tabs are gone. Remove the tab controller code and its key
    read; leave a one-line comment noting the S2 single-scroll reframe so a future
    reader does not re-add tabs by cargo-cult. Update
    `tests/test_last_match_tabs_reframe_dom.py` to characterize the NEW structure
    (do not silently delete it - rewrite it as the single-scroll regression).

--------------------------------------------------------------------------------
## TESTABLE ACCEPTANCE CRITERIA
--------------------------------------------------------------------------------

AC1. `?ui_mock=1&mode=sr#last-match` shows hero, win-prob graph, lane matchup,
     build-WPA, loadout, phases, and scoreboard ALL visible in one scroll with NO
     tab click. `#lm-tabbed-section` no longer switches (grep: no active-tab class
     toggling remains, or the element is gone).
AC2. Every reused panel still mounts and renders unchanged: `#pgr-snapshot-card`,
     `#pgr-winprob-mount`, lane-compare, build-WPA, loadout, phases, `#lm-tc-table`.
     Their DOM tests stay green: `tests/test_pgr_build_wpa_panel_dom.py`,
     `test_pgr_lane_compare_panel_dom.py`, `test_pgr_loadout_panel_dom.py`,
     `test_pgr_winprob_panel_dom.py`.
AC3. DOM order top-to-bottom matches D2 (assert node order in the snapshot /
     DOM test).
AC4. Hero 0-100 is the EXISTING `_setHeroScore` value; `git diff` shows NO new
     score-math function and NO change to the rubric consumption.
AC5. `git diff --stat dashboard/` is EMPTY (no route change); no new `fetch(` call
     added in `last_match.js` beyond the existing ones.
AC6. At 1920x920 (Chrome-chrome baseline) `main` flex-grows; NO `100vh` added; the
     page body never scrolls horizontally (wide blocks scroll inside their own
     `overflow-x:auto`).
AC7. `tests/test_pgr_child_panel_floor_guard.py` green (font floors held).
AC8. No reflow on data absence: ARAM / Arena (lane-compare hidden) and any thin
     block render "-" or a reserved slot; siblings do not shift. Verified across
     all three `?ui_mock` modes.
AC9. `tests/test_last_match_tabs_reframe_dom.py` updated to the new single-scroll
     structure and green; `tests/snapshot_panels/test_last_match_view.py` +
     `test_pgr_review_r30.py` green (update snapshots deliberately if layout order
     changed).
AC10. Gates: `node --check` on touched JS clean; the last_match + pgr DOM test
     group green; 5-phase fixture audit 0 MUST-FIX; live `?ui_mock=1` capture for
     sr / aram / arena reviewed.
AC11. 0 non-ASCII bytes in every touched file; no em / en dashes; no smart quotes.

--------------------------------------------------------------------------------
## R5 TIER + VERIFICATION SCOPE
--------------------------------------------------------------------------------

TIER: Tier-1-plus UI reframe (web/* visual, multi-file, no schema / engine /
scorer / ENGINE_VERSION). NOT Tier-2. Therefore:
- NO full dual suite. NO DS `:8893` restart. NO Share mirror (Daemon Slayer
  untouched).
- MANDATORY because it is a UI page change (CLAUDE.md "UI Fixture Ritual",
  `feedback_phase3_fixture_ritual`): the 5-phase fixture audit BEFORE the commit,
  every MUST-FIX resolved in the same slice:
  STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY.
- Run ONCE (R6), trust the exit code: `node --check` on touched JS; the focused
  DOM test group (last_match_* + pgr_* panel DOM + the two snapshot_panels PGR
  tests + the floor guard); the tab-reframe regression.
- Visual proof: `?ui_mock=1&mode={sr,aram,arena}#last-match` on live `:8888`
  (Chrome on Legion). ADR-008 auto-reload serves web/{js,css} changes with no RC
  restart. If a state change is needed, `echo restart > restart_trigger.txt`.
- If (and only if) a fixture field must be added and a route serializer changes to
  match (not expected), that route file's change escalates to Tier-2 for that file
  only - grep first, and prefer a fixture-only edit.

--------------------------------------------------------------------------------
## FILES TOUCHED (grep-verified)
--------------------------------------------------------------------------------

MODIFY:
- `web/js/panels/last_match.js` - the layout orchestrator: remove the tab
  controller (`last_match.js:276-334`), re-place the reused panel mounts into the
  single-scroll order, drop the `rc-pgr-tab` persistence.
- `web/index.html` - `#view-last-match` markup (`:1680`) + hero (`:1724`) +
  `#lm-tabbed-section`: restructure into stacked sections; move `pgr-winprob-mount`
  and the lane / build / loadout / phases containers out of tab panels.
- `web/css/panels/last_match.css` - `lm-*` grid / stack rules for the new layout;
  responsive at the 1920 baseline.
- `tests/test_last_match_tabs_reframe_dom.py` - rewrite as the single-scroll
  regression (was the tab-structure assertion).
- `web/data/ui_mock/last_match_{sr,aram,arena}.json` - ONLY if a needed field is
  missing (prefer no change).

DO NOT MODIFY (reuse as-is):
- `web/js/panels/pgr_build_wpa.js`, `pgr_loadout.js`, `pgr_lane_compare.js`,
  `pgr_winprob.js`, `post_game_phases.js`, `player_snapshot.js`.
- `web/css/panels/pgr_build_wpa.css`, `pgr_lane_compare.css`, `pgr_loadout.css`,
  `pgr_winprob.css`.
- `dashboard/routes_last_match.py`, `routes_post_game_rubric.py`,
  `routes_post_game_wpa.py`, `routes_item_wpa.py`, `routes_skill_wpa.py`.

--------------------------------------------------------------------------------
## EST SESSIONS + MODEL
--------------------------------------------------------------------------------

- Estimated sessions: 1-2 (1 if the single-scroll re-place + audit is clean; a 2nd
  only if the fixture-audit surfaces a hierarchy MUST-FIX that needs a CSS grid
  rework).
- Model: claude-opus-4-8, effort HIGH.
- One portfolio item per session; `/clear` on entry; no mid-run operator questions
  (log ambiguity + proceed with the D1-D7 recommendation).

--------------------------------------------------------------------------------
## DONE RITUAL
--------------------------------------------------------------------------------

1. Run the 5-phase fixture audit; resolve every MUST-FIX IN THIS SLICE before commit.
2. `node --check` touched JS + focused DOM test group green (run once, trust exit).
3. Confirm ASCII-clean (0 non-ASCII) on every touched file.
4. Commit with an ASCII-only message via a tmpfile: write the message file, then
   `git commit -F <tmpfile>` (never a piped or double-quoted here-string; the
   precommit gate blocks banned glyphs + net-new ruff).
5. Append ONE newest-first per-item entry to `docs/LEDGER.md` (NOT CLAUDE.md, which
   is CI size-budgeted < 60KB). Do not rewrite existing LEDGER history.
6. `git push`; confirm CI green before declaring done.
7. No DS Share mirror, no ENGINE bump (Daemon Slayer untouched).

--------------------------------------------------------------------------------
## GHOST LIST (do NOT investigate / do NOT build - each wastes a session)
--------------------------------------------------------------------------------

- Do NOT pre-build the 0-100 headline score. The NEW aggregator G score is S3 and is
  Settled-deferred. S2 keeps the existing `_setHeroScore` / rubric `total_score`
  verbatim and adds NO scoring math.
- No Claude and no Riot live-API dependency anywhere in PGR. Every field is local
  (`rewind_history.db` via the existing routes). Do not add a coach call or a Riot
  fetch.
- `web/js/dashboard.js` is DEAD CODE (only `/js/main.js` is loaded). Do not edit,
  read for guidance, or "fix" it.
- No em / en dashes, no smart quotes - 7-bit ASCII in every authored byte.
- Frozen files untouched (`main.py`, `app/*`, `core/game_snapshot.py`,
  `lcu/lcu_client.py`, `ops/rc_supervisor.py`, etc. - full list in CLAUDE.md).
  None are in FILES TOUCHED.
- Do NOT modify existing `docs/LEDGER.md` history (append-only, newest-first).
- Live-gated overlay work is OUT of scope (no in-game overlay, no live-game
  validation gate in this session).
- Lane U owns overlay item 4 (Client Settings reorg) and item 8 (rank-tier stats
  panel) - do NOT touch those surfaces or their specs.
- Design baseline is 1920x1080 WITH Chrome chrome (usable ~1920x920). `main`
  flex-grows; do NOT pin anything to `100vh` or a fixed 1280 height.
- Font floors ~13 / 15 / 18px - do not shrink below; `test_pgr_child_panel_floor_guard.py`
  is the guard.
- No reflow on data absence: use the "-" sentinel / a reserved slot; a missing
  block (mode-hidden lane-compare) must not shift its siblings.
- Do NOT rebuild the shipped pgr_* panels (build-WPA / winprob / lane-compare /
  loadout / phases / snapshot). They are components to re-place, not re-author.
- Do NOT re-defend or re-litigate the old 3-tab design as settled - the LEAP
  intent is single-scroll (D1). Just execute the reframe.
- Draft Tool Z8 is a DOWNSTREAM trigger ("after PGR S2 lands"), not part of S2.
- Do NOT recompute DS coverage prose or touch Daemon Slayer - this is a UI-only slice.

# RC2 research consolidation - group G1 (8 files)

QA'd 2026-07-28 against HEAD. All 8 source files landed in ONE commit `03dfb1ba`
("docs(rc2): Phase 1 research complete") and have NEVER been touched since
(`git log -2 --` per file = 1 commit each), so every open item in them is
>5 weeks stale and pre-dates the entire RC2 E-batch, the Hextech overlay
redesign, and the 2026-07-04 companion/overlay arch decision.

Two standing corrections that apply across all 8 files:

- **`docs/RC2_QA_CONSOLIDATED.md` (2026-06-20) already reconciled 97 of these
  items once.** It is itself now stale - I re-probed every row it called OPEN
  and found at least 8 have shipped since (history filters, W/L pip strip,
  two-tier tokens, GPI match dot, ban reason labels, ally AD/AP mix, session
  W-L header, dark-values ratchet). Do NOT copy its verdicts forward.
- **LEDGER 767 (2026-07-04) retired `web/` + `dashboard/` as standalone
  visuals**: all UI/UX now targets the rc-shell companion window + the in-game
  overlay. Any 1920-Chrome-dashboard framing in these docs is obsolete.

Verdict legend: SHIPPED / SUPERSEDED / STILL OPEN / LIVE-GATED / REFUTED /
DUPLICATE-OF. Effort S/M/L given only for STILL OPEN.

---

## docs/research/RC2_RESEARCH_champ_select.md

| ITEM | VERDICT | EVIDENCE | EFF |
|---|---|---|---|
| P1 Live per-pick draft win-% via a new `/api/draft-advantage` route | SHIPPED (different name) | `core/draft_score.py` + `dashboard/routes_draft_score.py` + `tests/test_routes_draft_elo.py`, `tests/_draft_elo_fixture.py`; QA_CONSOLIDATED item 29 | - |
| P2 Counter-picks vs the LIVE enemy comp in the Suggestions panel | SHIPPED | `web/js/panels/champ_select.js:1064-1084` `_csvRenderCounterPicks` -> `GET /api/champ-select/counter-picks?top=5`; route in `docs/API.md:54`; `docs/RC2_PLAN.md:93` E4 DONE | - |
| P3 AUTO-toggle for rune/spell/item push + fix RuneWriter first-CS-only bug | SHIPPED | `lcu/lcu_rune_writer.py` re-arm path (QA_CONSOLIDATED item 30 cites `lcu_rune_writer.py:581`); `_cached_lobby_mode` re-init at `lcu/lcu_rune_writer.py:694` proves the per-CS reset exists | - |
| P4 Enemy/ally PLAYER scouting table (rank / mains / behaviour tags) | SHIPPED | `dashboard/routes_scouting.py` + `tests/test_routes_scouting.py`; E9 | - |
| P5 Per-bench-cell ARAM tier / win-rate annotation | STILL OPEN | `_csvBenchHtml` `web/js/panels/champ_select.js:1338-1341` renders champion cells only; grep `bench.*tier\|tier.*badge\|meta.?tier\|winrate.*badge` over `champ_select.js` = **no matches**. Data-gated (RC has no ARAM WR tier feed) | S |
| P6 Arena augment tier ratings on the offered options | SHIPPED | `augment_recommender.py` (QA_CONSOLIDATED item 28); live-OCR half still gated | - |
| P7 Ban-suggestion REASON labels | SHIPPED | `web/js/panels/champ_select.js:3852` `_csvBanReasonLabel`, consumed at `:4126` | - |
| P8 Ally AD/AP damage-profile read for SR draft | SHIPPED | `dashboard/routes_pickban.py:234` `_compute_team_damage_mix` + `:1206` `GET /api/champ-select/team-damage-mix`; consumer `web/js/panels/champ_select.js:1106-1122` ("LIFT 1b, 2026-06-22"); bar CSS `web/css/panels/champ_select_view.css:1803` | - |
| P9 Global meta tier / winrate badge on picks | STILL OPEN | same empty grep as P5. The doc's own verdict was LOW and it is gated on a meta-tier feed RC does not maintain. Recommend recording as declined, not as work | S |

## docs/research/RC2_RESEARCH_overlay_sizing.md

| ITEM | VERDICT | EVIDENCE | EFF |
|---|---|---|---|
| LIFT-A Fullscreen detect + "switch to Borderless" one-line hint | STILL OPEN | grep `fullscreen\|Borderless\|WS_POPUP\|isFullScreen\|GetWindowLong` over `rc-shell/src/*.js` returns **only comments** (`main.js:64,566,580,622,626,661`, `overlay_state.js:19-20`) - zero HWND style read, zero hint UI | S |
| LIFT-B Pick the overlay display BY RESOLUTION, not "primary"/index | STILL OPEN | `screen.getAllDisplays()` appears once, `rc-shell/src/main.js:933`, and only to bail when `displays.length > 1`; the overlay still pins to `getPrimaryDisplay()`. Doc itself notes 1-PC primary == game monitor, so value is near-zero today | S |
| LIFT-C DPI / scaleFactor-aware overlay sizing + relative-unit overlay.css | SHIPPED | `rc-shell/src/overlay_state.js:339-389` `normScaleFactor` + DIP box + explicit electron#6571 guard; `main.js:577` reads `primary.scaleFactor`; tests `rc-shell/test/overlay_state.test.js:803-835` incl. "bad scaleFactor guarded to 1". The doc's "Grep: no scaleFactor anywhere in rc-shell/" is FALSE today | - |
| LIFT-F Elevation-parity (Windows UIPI) detect-and-hint | STILL OPEN | no integrity-level probe anywhere in `rc-shell/src/`; only match for "integrity" is the unrelated `crash_guard.js:31` `"integrity-failure"` crash-reason string. Doc's own value note: irrelevant while neither process runs elevated | S |
| LIFT-D click-through + {forward:true} + auto-revert / LIFT-E screen-saver z-level | SHIPPED | the doc already records both as already-have; unchanged in `rc-shell/src/main.js` | - |
| LIFT-G never lift an injection/hook draw path | REFUTED as work | not an item - it is a standing fence, already encoded in the frozen `rc-shell/src/main.js:40-43` header. Carry it into the consolidated doc as a fence line, not a row | - |

## docs/research/RC2_RESEARCH_history.md

| ITEM | VERDICT | EVIDENCE | EFF |
|---|---|---|---|
| P1 Result-first row (win/loss colour on the History row) | SHIPPED | `web/js/main.js` `_historyMatchRowEl` sets `li.dataset.result` + `result-win`/`result-loss` from `m.win`, with the "WIN-CAPTURE keystone (item 77)" comment; ingest guard `tests/test_history_win_capture.py` | - |
| P2 Last-20 W/L pip strip + real season WR (retire "needs Riot key") | SHIPPED | `web/js/main.js:3473-3509` `_homeRenderWlStrip` + `web/css/panels/home.css:158-190` `.home-wl-pip`; season WR is real at `main.js:2262` `history-season-wr` from `season_stats.win_rate`; builder docstring `dashboard/builders.py:39-40` returns `{results, wins, losses, win_rate}` | - |
| P3 Expand-in-place accordion match detail | STILL OPEN | `_historyRenderMatches` (`web/js/main.js`) appends `_historyMatchRowEl(m)` only; row body has no hidden detail node and click calls `_wireMatchRowToHistoricalPgr` which ROUTES AWAY. grep `hist-match-detail\|hist-expand\|accordion` over `web/js/main.js` + `web/index.html` = **no matches** | M |
| P4 List filters (champion / queue / result) | SHIPPED | `web/index.html:1282-1302` full `#history-filter-bar` (champion select, mode select, All/W/L result buttons, S-F grade buttons, match count); wiring `web/js/main.js:2217-2354`; QA_CONSOLIDATED called this OPEN - it is stale | - |
| P5 Richer row payload (item icons, CS, per-game score pip) | STILL OPEN | `_historyMatchRowEl` innerHTML is exactly grade pip + `champion . mode` + KDA + timestamp - no items, no CS, no score. Confirmed by reading the whole function | M |
| P6 Per-session W-L in the session header | SHIPPED | `web/js/main.js:2025-2026` and `:2072-2073` build the head as `MATCHES . date . Ng . <wlLabel>` from `_sessionWL(s).label` | - |
| P7 Per-game op-score as the row scan key + sort toggle | STILL OPEN | the numeric score exists (`web/js/panels/op_score.js`, `GET /api/op-score-curve`) but the History row still shows a letter grade pip and there is no sort control: grep `history-sort\|sort-by-score` = **no matches**. Lowest value of the three | S |

## docs/research/RC2_RESEARCH_home_profile.md

| ITEM | VERDICT | EVIDENCE | EFF |
|---|---|---|---|
| P-A Rank / tier / LP identity header on home | SHIPPED | `lcu/lcu_ranked.py` + `tests/test_lcu_ranked.py` + `tests/test_home_rank_identity.py`; E9 | - |
| P-B Recent-form colour-coded W/L strip on home | DUPLICATE-OF history P2 | same `_homeRenderWlStrip` at `web/js/main.js:3473-3509`; both docs describe one build | - |
| P-D GPI-style skill radar with per-axis advice | SHIPPED | `core/player_gpi.py` + `web/js/panels/player_gpi.js` (radar polygon `:204`, spokes `:208`, and the single-match overlay dot `gpi-match-dot` at `:247` that QA_CONSOLIDATED item 20 still listed as OPEN) | - |
| P-E Champion-pool per-champ trend arrow | SHIPPED | QA_CONSOLIDATED item 19 cites `main.js:1600` recent-vs-baseline arrow; hot/cold champ list live in the adapt panel | - |
| P-G Weekly summary digest card | REFUTED | It was BUILT (LEDGER 733, 2026-07-01, `_home_weekly_digest` + `_MODE_BENCH`) and then DELIBERATELY REMOVED four days later (LEDGER 767, 2026-07-04 home QA rework, ruling C2 "REMOVED Weekly Digest as a this-week dupe"). Removal is now pinned by deletion-guard tests `tests/test_home_weekly_digest.py:27-44` and `tests/test_home_weekly_digest_dom.py:30-52`. Re-proposing it would fail CI | - |
| P-H MMR / tier prediction | REFUTED | doc's own verdict is LOW/out-of-scope, and CLAUDE.md Settled lists ML win-predictors as CLOSED. No corpus exists | - |
| P-C composite score + word tag / P-F "what to play tonight" | SHIPPED | doc already records both as already-have | - |

## docs/research/RC2_RESEARCH_in_match_overlay.md

| ITEM | VERDICT | EVIDENCE | EFF |
|---|---|---|---|
| L1 Objective / camp respawn timers rendered where the eye rests | SHIPPED (different anchor) | `web/js/panels/objective_gauges.js` + `objective_chips.js`; `web/css/panels/objective_gauges.css:1-25` documents the OQ16 DRAKE/BARON/ELDER ring-dial cluster with exact ETA in each centre; registered as `w-objgauges` in `web/js/lib/overlay_layout.js:96`. Delivered as a peripheral gauge cluster, NOT drawn on the minimap - the `w-mmrect` minimap rect (`web/js/panels/minimap_rect.js:146`) is the ZOI overlay, separate | - |
| L2 Trinket-ready single-pulse vision cue | SUPERSEDED | it shipped as the `w-trinket` glyph widget (`web/css/overlay.css:597-611`) and was then REMOVED 2026-07-05 (`web/js/lib/overlay_layout.js:65` "w-trinket / Ward Cue removed 2026-07-05"). Replaced by the always-on TRINKET rule line in the NEXT BUY widget (`web/js/lib/next_buy_model.js:22-30`, `web/css/panels/next_buy.css:74-80`) | - |
| L3 Live spike-crossed "do now" Urgent cue | LIVE-GATED | code shipped: `web/js/panels/spike_cue.js`, `web/css/panels/spike_cue.css`, widget `w-spike` tier `urgent` at `web/js/lib/overlay_layout.js:73`. QA_CONSOLIDATED item 7: producer feed unwired + over-fire eyeball owed; routes through `docs/LIVE_GAME_GATED_SYNC.md` | - |
| L4 Enemy ult/summoner cooldown glance (panel-set decision) | SHIPPED | `cd_ledger.js` / `cooldown_watch.js` still built; overlay is now a widget registry with per-widget placement + persistence (`overlay_layout.js`), so the panel-set gating this item complained about is gone. ToS awareness flag (section 3) should carry forward as a fence line | - |
| L5 A-la-carte toggle + transparency / scaling sliders | SHIPPED | `web/js/lib/overlay_settings.js:59-210` `overlayOpacity` (clamped, applied as `--rc-overlay-opacity` + window-level in main.js); per-widget drag/persist via `overlay_layout.js`; QA_CONSOLIDATED item 10 cites `85d6b29e` | - |
| L6 Static most-common jungle path on the minimap | REFUTED | doc's own verdict is LOW ("RC's live MIA/gank tracking is strictly better"); it only helps the jungle role, which is not the operator's | - |
| Section 2.6 - tier every cue, ration the pulse channel to the urgent band | SHIPPED | `web/js/lib/overlay_priority.js` (`shouldPulse`, QA item 3) + tiers baked into the registry (`overlay_layout.js:51,73,96` `tier: "primary"|"urgent"|"ambient"`) + `web/js/lib/combat_mode.js` | - |

## docs/research/RC2_RESEARCH_lobby.md

| ITEM | VERDICT | EVIDENCE | EFF |
|---|---|---|---|
| A Party / Top-8 recent-form tag chips | STILL OPEN | grep `lv-duo\|party.*form\|top8.*chip\|recent_form` over `web/` = **no matches**; `_renderTop8` (`web/js/main.js:5475`) and `_renderPartyMembers` (`:4549`) still emit IGN + rank/peak/role + action pips only, and the only Top-8 signal is the `.is-top8-mate` hue | M |
| B Last-session / today's record recap + tilt nudge at the LOBBY phase | SUPERSEDED | the capability shipped on the SESSION view, not the lobby: `_renderSessionTrend` `web/js/main.js:1893-1950` (grade trajectory, Cooling off / Heating up / Fatigue check at 2.5h+, `#session-trend`), plus the home last-20 strip. Only the lobby-phase PLACEMENT is unbuilt; recommend recording as a placement question, not a build | - |
| C Duo-synergy hint for a 2-man party at the lobby | REFUTED | the premise ("re-stage the already-shipped champ-select duo grid") is false: the duo-synergy grid was REMOVED from champ select by item 213, pinned by `tests/test_champ_select_item213.py:10` "(E) the ally-picks-by-role panel replaced the duo-synergy grid". `/api/duo-synergy` is still route-registered (`dashboard/_dispatch.py:80,141`) but grep `api/duo-synergy` over `web/js/` = **zero consumers**. There is nothing to re-stage; this is a new build on a dead lane | - |
| E Finish ready-check auto-accept (wire the toggle to the endpoints) | SHIPPED | E6 `_syncAutoAccept` (QA_CONSOLIDATED item 22, `main.js:5344`); UI live at `web/index.html:830-833` `#lv-auto-accept` | - |
| F Mode-specific lobby PREP content (per-queue prep block) | STILL OPEN | `web/index.html:820-1005` lobby view is queue controls + lane prefs + members + mains + Top 8 only; no per-mode prep block. Doc's own verdict was MED with the caveat that most ARAM prep is only meaningful after the bench appears in champ select | M |
| G Friends / invites / party management | SHIPPED | doc already records as fully built | - |
| H Gameflow SESSION WebSocket instead of `/phase` polling | REFUTED | doc's own verdict is LOW ("do not pursue unless a concrete latency problem appears"), and the responsiveness program went the other way entirely - RM-03/E12 built the in-process snapshot port (`dashboard/_lcu_inprocess.py`) rather than a WS | - |
| Inbound `/lol-lobby/v2/lobby/invitations` shown as a UI list | STILL OPEN | grep `invitations` over `web/js/main.js` = **no matches**. Doc itself calls it a "minor possible add" | S |

## docs/research/RC2_RESEARCH_io_timing_map.md

| ITEM | VERDICT | EVIDENCE | EFF |
|---|---|---|---|
| L1 Drop `RuneWriter.POLL_INTERVAL` 2.0s -> 1.0s | SHIPPED | P6.2; QA_CONSOLIDATED item 58 "POLL_INTERVAL <=1.0s" | - |
| L2 Cache the lobby `gameMode` for the champ-select duration | SHIPPED | `lcu/lcu_rune_writer.py:553` `self._cached_lobby_mode`, hit at `:891-892`, populated `:897-898`, reset `:694`. QA_CONSOLIDATED called this OPEN (item 59) - stale; `ROADMAP.md` RM-03 confirms "QA59/L2 already shipped as `_cached_lobby_mode`" | - |
| L3 Single champ-select reader on 1-PC / source `build_state` in-process | LIVE-GATED | BUILT DARK 2026-07-20 (`9eb76879`): `lcu/snapshot_shape.py` + `dashboard/_lcu_inprocess.py`, gated `RC_LCU_INPROCESS=1` at `dashboard/_state_builder.py:79-87`, tests `tests/rc2_l3/test_lcu_inprocess_l3.py`. Only the G1-00 live confirm is owed (`ROADMAP.md` RM-03 -> `docs/LIVE_GAME_GATED_SYNC.md` G1-00 CHECK 2) | - |
| L4 SSE tick + `build_state` TTL 1.0s -> 0.5s together | SHIPPED | P6.3; QA_CONSOLIDATED item 60 cites `e9b1a5d0` `_STATE_CADENCE_S` | - |
| L5 Leave the fallback LCU poller at 2.0s | REFUTED as work | explicitly a no-op flag ("no change needed"); carry as a fence line, not a row | - |
| L6 Pooled keep-alive LCU connection | SHIPPED and DEFAULT-ON | `core/lcu_pool.py:19-43` - `RC_LCU_POOL` defaults `"1"` since the E7 flip 2026-06-30, validated over a live game; `RC_LCU_POOL=0` restores the byte-identical legacy path. QA_CONSOLIDATED item 61 (GATED-LIVE, "OFF") is stale | - |
| L7 Shared min-interval guard around a consolidated LCU reader | SHIPPED | `core/lcu_pool.py:143` `MinIntervalGuard` (QA item 63) | - |
| L8 Keep the `:2999` self-read throttle at >= 1.5s (documented floor) | SHIPPED | same guard/doc slice as L7 (QA item 63); `vision_server/_relay.py` throttle unchanged | - |

## docs/research/RC2_RESEARCH_nonleague_uiux.md

| ITEM | VERDICT | EVIDENCE | EFF |
|---|---|---|---|
| A1 Sim-racing 5-7 segment peripheral zoned meter for timers | SUPERSEDED | the glanceable-timer role was filled by the OQ16 ring dials (`web/css/panels/objective_gauges.css:1-25`), and segmented-bar primitives already exist for confidence (`web/css/panels/build_insights.css:10,357` 5-segment; `coach_choices.css:8` 3-segment; `grid.css:35` 3-segment phase strip). A separate shift-light primitive has no remaining consumer | - |
| A2 Aviation-style declutter-as-a-mode ("fight mode") | SHIPPED | the COMBAT SHED: `web/js/lib/combat_mode.js` (+ `combat_mode.test.mjs`); policy documented `web/css/overlay.css:12,352,719-739` incl. per-widget shed exemptions the operator tuned on 2026-06-29/30; kind tagging at `web/js/panels/active_match.js:2220` | - |
| A3 Ring / arc gauge primitive (conic-gradient donut) | SHIPPED | `web/css/panels/build_module.css:142` `conic-gradient(#6cf var(--ring-pct,0%) ...)`; full SVG ring dials in `objective_gauges.js` | - |
| A4 Always-on core + phase-contextual band split | SHIPPED | the widget registry IS the split: `web/js/lib/overlay_layout.js:51,73,96` assigns every widget `tier: primary|urgent|ambient` with fixed learnable coords; combat shed drops the ambient tier | - |
| B1 Threshold-driven `statusFor(value, thresholds)` helper | SHIPPED | `web/js/lib/status.js:43` `statusFor` + `statusVar`, dual ESM/CJS export `:74-80` (E8) | - |
| B2 Named/labelled grid sections with an Overview-first band | STILL OPEN | grep `data-band\|grid-section` over `web/index.html` + `web/css/panels/grid.css` = **no matches**. NOTE: largely mooted by LEDGER 767 - the 1920 dashboard grid is no longer a shipped visual surface, so this should probably be recorded as declined rather than open | M |
| B3 + C5 Redundant status cues (kill colour-only encoding, WCAG 1.4.1) | SHIPPED | `web/css/tokens.css:152` triangle glyphs (E8, QA item 43); consumers e.g. `web/css/panels/build_insights.css:10,357` "(WCAG 1.4.1, never hue alone)" | - |
| B4 Quiet-by-default / exception-first motion policy | STILL OPEN | grep `animation:.*infinite` over `web/css` returns **9 live loops**: `header.css:845,3238,3554`, `map_state.css:230,236`, `item_build.css:164,168`, `objective_gauges.css:152,156`. `item_build` nextUpPulse + canAffordPulse are the clearly non-danger ones. Several now sit behind `prefers-reduced-motion` blocks, which is mitigation not the policy | S |
| C1 M3 tone-based surface container ramp (elevation via lightness) | STILL OPEN | grep `--surface-container` over `web/css` = **no matches**; still `--surface`/`--surface-2`/`--surface-alt`/`--surface-head` plus `--shadow-card` | M |
| C2 Extra text hierarchy tiers | SHIPPED | `web/css/panels/base.css:16,18,20` now carries three tiers `--text` / `--text-dim` / `--text-faint`, the last annotated "ternary / captions - WCAG-AA raised (4.88:1 on --surface)" | - |
| C3 Two-tier tokens (primitive ramp -> semantic alias) | SHIPPED | `web/css/tokens.css:51-59` - `--signal-good: rgb(var(--prim-green))`, `--signal-warn: rgb(var(--prim-amber))`, `--signal-bad: rgb(var(--prim-red))` plus the `-soft` rgba aliases. The doc's central "architectural gap" (literal `#6ec977`) is closed; QA_CONSOLIDATED item 46 is stale | - |
| C4 Dark-values audit (no pure `#000`/`#fff`) + lock artifact | SHIPPED | `tests/test_dark_values_ratchet_oq6.py` is the ratchet/lock the item asked for (referenced live in LEDGER 767's cleanup) | - |
| D1 One-shot fresh-feedback utility + fix the 0.8s/1.2s doc drift | SHIPPED | drift fixed in place: `web/css/tokens.css` pulse comment now reads "(Drift fix 2026-06-19: this comment formerly said 1.2s while the only consumer was 0.8s...)"; consumer `web/css/panels/right_now.css:33-34` at 0.8s one-shot | - |
| D2 `prefers-reduced-motion` done right (REPLACE, not delete) | SHIPPED | `web/css/tokens.css:189-213` global block that swaps each `coach-pulse-*` for a static ring; adopted by 7 further panels (`spike_cue.css:64`, `objective_gauges.css:166`, `map_state.css:249`, `item_build.css:260`, `header.css:849,3247,3563`) vs the ONE panel the doc found | - |
| D3 Compositor-only pulse (opacity-animated `::after` halo) | STILL OPEN | `web/css/tokens.css:152-162` keyframes still animate `box-shadow` directly; grep `will-change: *opacity\|halo` over `tokens.css`+`overlay.css` = **no matches**. Doc's own note: "mostly invisible to the eye" | S |
| D4 Calm-technology motion policy | DUPLICATE-OF B4 | same 9 infinite loops, same sweep | - |

---

## Roll-up

**63 actionable items extracted across 8 files.**

| Verdict | Count |
|---|---|
| SHIPPED | 40 |
| STILL OPEN | 12 |
| REFUTED | 6 |
| SUPERSEDED | 3 |
| LIVE-GATED | 2 |
| SHIPPED-as-fence (LIFT-G, io L5) | 2 (counted in SHIPPED/REFUTED above) |
| DUPLICATE-OF | 2 (home P-B = history P2; D4 = B4) |

Roughly **two thirds of these docs' open items have shipped since 2026-06-19**,
which is the headline finding: the docs are safe to archive, and the residue is
small, cheap, and mostly cosmetic.

### STILL OPEN, best-first

1. **history P3 - expand-in-place accordion match detail.** [M] Highest real UX
   value left in the set; the backend (`/api/last-match?match_ts=`) and the
   whole `historical_pgr` renderer are already free, only the in-list mount
   target + one-open-at-a-time state are missing.
2. **history P5 - richer History row (item icons, CS, per-game score).** [M]
   Row is still `[grade] champ . mode | KDA | ts`; the item-icon helper and the
   score heuristic both already exist elsewhere. Pairs naturally with P3 as one
   slice behind the UI-audit ritual.
3. **nonleague B4/D4 - quiet-by-default motion sweep.** [S] 9 live
   `animation: ... infinite` loops; trimming the two non-danger `item_build`
   ones is a near-free calm-tech win on the surface the operator watches.
4. **lobby A - party / Top-8 recent-form tag chips.** [M] Genuinely unbuilt and
   the only lobby-phase insight lift left; data (`rewind_history.db`) is local.
5. **overlay LIFT-A - fullscreen detect + "switch to Borderless" hint.** [S]
   Cheap, AC-safe read-only Win32 guard against a silently-dead HUD. The single
   best safety-per-line item in the overlay group.
6. **lobby F - per-mode lobby prep block.** [M] Structural queue branching
   already exists; only the content is missing. Doc's own caveat (ARAM prep is
   really a champ-select thing) caps the value.
7. **history P7 - promote the numeric op-score into the row + a sort toggle.**
   [S] Score already computed; this is a render + one control.
8. **nonleague C1 - M3 tonal surface-container ramp.** [M] Correct long-term
   elevation model; sequence it with the E11 Hextech reskin, never alone.
9. **nonleague D3 - move the pulse onto an opacity-animated `::after` halo.**
   [S] Perf correctness in the overlay frame budget; invisible to the eye.
10. **lobby - surface inbound `/lol-lobby/v2/lobby/invitations` as a UI list.**
    [S] Trivial, self-contained, real QoL.
11. **champ-select P5 - per-bench-cell ARAM tier annotation.** [S] Blocked on an
    ARAM WR tier feed RC does not maintain. Record as data-gated.
12. **nonleague B2 - labelled grid sections / Overview-first band.** [M]
    Recommend DECLINING: LEDGER 767 retired the 1920 dashboard grid as a
    shipped visual surface, so this targets a surface nobody looks at.

Also-declined-but-listed for completeness (LOW by the docs' own verdicts, and
still unbuilt): champ-select P9 meta-tier badge [S], overlay LIFT-B
display-pick-by-resolution [S], overlay LIFT-F elevation-parity guard [S].

### LIVE-GATED (needs the operator in a real game)

1. **in-match L3 - spike-crossed "do now" Urgent cue.** Arbitration + widget
   shipped (`spike_cue.js`, `w-spike` urgent tier); the producer feed is unwired
   and an over-fire eyeball is owed. Already tracked in
   `docs/LIVE_GAME_GATED_SYNC.md`.
2. **io-timing L3 - single champ-select reader on 1-PC.** Built DARK behind
   `RC_LCU_INPROCESS` (`dashboard/_state_builder.py:79-87`); owes the G1-00 live
   confirm - flag ON in a live champ-select, byte-compare `lcu.champ_select`,
   adjudicate the auto-accept-pill divergence.

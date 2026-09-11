# Live-Game-Gated Sync Checklist

## DRAIN SESSION 2026-07-20 (4 games: practice SR, ARAM Mayhem q2400, Arena q1750, real SR q400)

**CLOSED THIS SITTING (6):**
- **G1-00** BOTH CHECKS PASS. CHECK 1 exercised live across ALL FOUR champ-select shapes - practice SR
  (q3140), ARAM bench (q2400, bench populated), Arena augments (q1750, `arena_teams` + `augments` keys
  present), real draft (q400, `sr_draft=true`, `active_round={type:'ban'}`). CHECK 2 byte-compared
  flag-ON vs flag-OFF in the SAME champ-select: `champ_select` **BYTE-IDENTICAL: True**. Divergence is
  outside champ_select and was TWO keys, not one: `config` (predicted) AND `lcu_port` (NOT recorded in
  the doc). ADJUDICATED: the reader must CARRY both through, not synthesize - live `config.auto_accept`
  was `false` with the Settings checkbox unchecked, and `main.js:5661-5672` drives both the lobby pill
  and `#set-lobby-auto-accept` from it. Fix built + tested (uncommitted at time of writing).
  SEPARATE BUG FOUND: `data/auto_accept_pref.json` = `{"enabled":true}` while the agent's
  `config.auto_accept` = false, so the frozen in-process `_auto_accept_tick` auto-accepts ready-checks
  while the checkbox reads OFF.
- **G6-02** ACTIVE-knob round trip - **PASS, first GATE 6 row ever closed.** With League FOREGROUND the
  operator pressed Ctrl+Shift+A and watched PASSIVE -> ACTIVE (edge glow, body-drag) then the 20s
  auto-revert fire. Listener receipts tonight at 22:27:38 / 22:32:37 / 22:32:42 from
  `signal_overlay_active_toggle`, which has EXACTLY ONE caller repo-wide and ZERO test callers.
- **G2-18** eyeball DISCHARGED by operator ruling. MEASURED on the operator's real build
  `[2501,3032,3031,3075,6695]` L14: seam OFF 219.145 -> ON 232.294 dps (+6.00 pct); at his REAL 96.5 pct
  missing HP it would be 245.443 (+12.00 pct), i.e. the 0.35 midpoint realizes exactly 50.0 pct as
  designed; no-carrier control byte-identical (delta 0.000000). RULING: **wire the live HP feed and
  delete the midpoint guess** (RC already emits hp/hp_max, item 639). Residual is now a named code
  slice, not a game.
- **G2-29** ARAM flood-tint question ANSWERED: **no flood.** Minimap ZOI rendered the ARAM bridge as a
  diagonal band, and ZOI proved genuinely mode-aware - districts came back
  `['blue_base','red_base','aram_bridge','brush_north','brush_south']`, and in Arena `zoi` is null
  entirely.
- **G2-34** RULED **HORIZONTAL**. Also root-caused the operator's "I don't see them": gate is
  `mode==='sr' && Number.isFinite(lc.game_time_s)` and live state satisfied BOTH (game_time_s=645); in a
  fresh client at default layout `#am-obj-gauges` probed VISIBLE + populated (1170 chars, drake dial).
  Missing on his overlay only -> saved-layout/RM-05 drag class, re-filed to G2-32. Later confirmed
  rendering in-game (DRAKE/BARON/ELDER dials, horizontal).
- **G2-35** RULED **pace-projected baseline** (keep the tier AVG but scale it to the current game clock).
  The panel was comparing live CS 30 against a FULL-GAME average of 260.

**ADVANCED WITH RECORDED EVIDENCE:** G1-02 (lobby payload AND render evidenced - queue 1750 "Arena",
full `_slim_lobby_member` shape, `lv-members-list` / `lv-mainchamps-list` / `lv-top8-list` populated),
G4-01 (ban/pick reason labels render live with provenance tags + a STRUGGLE tier), G2-12 (mechanism
proven + leak-free control, calibration REJECTED by operator - see below), G2-17 (correctly DEFERRED to
a shielded comp; practice bots carry no shields), G2-26 (pixel capture done: 5 enemies x 2 spells),
G2-28 (3 of 4 verified live: rn-lead 298 chars / rn-choices 2205 / rn-callouts 701 all VISIBLE;
am-spike-cue is documented data-gated so HIDDEN at a non-spike moment is honest, positive confirm still
owed), G2-41 (premise confirmed: `/latest-frame` measured 1280x720 vs a 2560x1440 display),
G2-42 (b: 13 live districts with occupancy + last_seen; c: frame `source='obs'`, GDI baseline ok at
2560x1440), G3-01 (bench swap propagated inside ONE 0.5s sample; the subjective "visibly faster" half
deferred to the operator's next swap), G4-16 (three of five chips seen lit: C3 fed-enemy "SURVIVE fed
Tristana 11/1 - build armor", C5 pen_type, C6 tenacity).

**G2-38 STAYS OPEN, and the reason matters:** 281 samples across two games (practice SR levels 13-16,
ARAM levels 1-14). ARAM produced a REAL top-1 flip at 6:51/lvl 9 (Blade of The Ruined King ->
Runaan's Hurricane) that then held to lvl 14 - no oscillation. BUT the top-two NEVER came within 5 pct
in either game (tightest 9.02 pct, at that very flip), so the ~3 pct incumbent band was never
exercised. Stability without a tight margin is CONSISTENT WITH the hysteresis but does not prove it.
The row's precondition may be rarer in practice than the row assumes.

**G5-01 IS THREE QUESTIONS, NOT ONE - re-file accordingly:**
(a) **AUGMENT EMISSION WORKS.** Two rows written in one Arena game; at the round-8 window
`augment_choices` matched the three on-screen cards EXACTLY (OCR correct), Haiku take recorded, and the
deterministic recommender ranked all three (top "Gain a Prismatic Stat Anvil" 0.6667). The doc's
suspected upstream gap at `ArenaVisionReader.read()` is **REFUTED for augments**, and the round-based
re-trigger DOES fire. `cherry_augment_open` stayed false throughout - augment detection is vision/OCR,
not LCU.
(b) **ANVIL EMISSION FAILS.** Operator took an anvil; `anvil_shadow.jsonl` was never created, across two
separate opportunities plus a dedicated 75s tight-poll of the shop window. BEST CANDIDATE (not a wiring
gap): vision polls every **23-30s**, each call taking 2.5-5s (measured from the log), while a shop anvil
is on screen for seconds - the same cadence-miss as the open ARAM augment bug.
(c) **THE ROWS ARE CORRUPT.** Both rows recorded `round:"~1"` (operator was on real rounds 1 and 8),
`picked:[]` never accumulates, and the `deterministic` block is empty although the live payload carried
the full recommender output at that instant. Net: the shadow ledger cannot compare Haiku vs
deterministic conditioned on prior picks, so the G7 augment-agreement rail can never yield a valid
comparison. Tonight it missed a REAL disagreement (Haiku "Augment Slot" vs recommender "Prismatic Stat
Anvil"; the operator's own pick matched the deterministic one).

**ARENA ROUND COUNTER RESETS MID-GAME** (159 samples at 3s): climbs to ~17 then RESETS to 0 and restarts
at ~1, at least four times in one game, and changes TYPE (int `0`, once `""`). That int 0 is almost
certainly what trips `coaching_payload` with "round: Input should be a valid string" - thousands of
warnings per Arena game - so the validation spam and the reset are ONE bug. The Arena coach ACTION is
healthy by contrast (14 distinct actions across those samples); an earlier "stuck on CAMP PHASE"
suspicion is REFUTED.

**MATCH-V5 INGEST IS HEALTHY - the 12-day gap was EXPECTED.** `rewind_history.db` went 2964 -> 2965
during the session, ingesting tonight's Arena game (NA1_5605680438, q1750 CHERRY, patch 16.14, Vayne).
Operator confirmed he played NO real matchmade SR between Jul 9 and Jul 20, so the gap was ARAM Mayhem
(q2400, 403-excluded by design) plus customs, exactly as the settled note says. What remains is a
RENDERING defect, not an ingest one: RC watched those games live and still shows them as
`Unknown / 0-0-0` on Home / Session / PGR instead of using the champion it held in `liveclient`.

**NEW BUGS FOUND THIS SITTING (none were in this doc), fixes written + tested but UNCOMMITTED:**
1. **ARAM balance panel dead in EVERY ARAM** - two independent defects. `_resolveChampId` returns a
   canonical NAME while `_abCanonicalId` indexes `CHAMPS.byId` (an id->name map) with it, and
   `_abBuildRows` prefers `rawChampionName` (`game_character_displayname_X`) which resolves to null.
   FIXED and LIVE-VERIFIED in-game via ADR-008 hot reload: all 10 champions resolved with correct
   ally/enemy split and real modifiers. Operator RULED it gets its OWN draggable widget (it is ~11 rows
   and was pushing the build panel into a scroll region).
2. **R40 draft-elo chip dead in-game** - mounted INSIDE `.am-pane-head`, which `overlay.css:482` hides
   for `w-build` (BATCH A title-bar removal). Computes fine (de-state=ready), can never paint. Fix is a
   re-parent, NOT a CSS exception.
3. **Auto-PGR never fires** (this is G4-26) - ROOT-CAUSED AND FIXED. `tools/lcu_agent.py:288-292`
   documents an 8-11s in-game capture lag; `dashboard/_liveclient.py:107-108` drops any snapshot older
   than 5s and returns `{}`. So `/api/state.lcu` is `{}` for much of a game -> `phase` undefined -> the
   in-memory sticky `_VIEW.gameStarted` never arms -> the post-game arm is skipped -> derive falls to
   "home". Reproduced deterministically in a Node harness slicing the real `_viewAutoDerive`. Fixed by
   arming the sticky on the same null-phase in-game signal the renderer already trusts, mirrored into
   `dashboard/view_router_state.py`. **The 5s TTL vs 8-11s capture is a broader unfixed bug.**
4. **Stale minimap box persists into Arena** - `main.js` gates the minimap render block to
   `["sr","aram","brawl"]`, so in Arena the renderers are never called and nothing clears the last
   painted box. Fixed with a latched clear-on-exit (gate deliberately NOT widened).
   `renderMinimapZoi` needed 3 null calls - it debounces with `_NULL_CLEAR_STREAK = 3`.
5. **KP row is a hardcoded dash over real data** - `stats_panel.js:298` paints `"-"` with a comment
   claiming "no live KP producer", but `liveclient.kill_participation_pct` and
   `coach.kill_participation_pct` both read `'44%'` live.
6. **Champ-select `[no data] (mastery)`** for Vayne and Kai'Sa while `lcu.mastery` carries 24,953 and
   50,145 points - keyed by numeric id as a string. Same lookup class as (1).
7. **`health.overlay_visible` reports FALSE while the overlay is visibly rendering** (confirmed twice).
8. **Home panels strand on "loading..." forever** after one transient fetch failure (RC restarted at
   game end). `/api/home/summary` returns 200 with full data throughout; Ctrl+R fixes it. No retry, no
   error state.
9. **BACKSLASH-U-2014 ESCAPE BLIND SPOT in ASCII enforcement** - `performance_tracker.py:39` holds
   `"BELOW <u2014> focus on one area at a time"` as a literal backslash-u escape. The file is byte-wise
   7-bit ASCII (0 non-ASCII chars) so `tools/strip_em_dashes.py`, the ASCII hygiene tests and the
   precommit gate ALL pass it, while Python resolves it to a real U+2014 that renders in the UI and has
   been written into `data/ratings/last_sr.json` + `last_arena.json`. Repo-wide scope NOT reliably
   measured (the scan used had an escaping bug) - a proper sweep is owed.
10. **pytest writes into `logs/hotkey_listener.log`** (`tests/test_hotkey_panel_cycle_signal.py`
    monkeypatches the path to `Z:/nonexistent/...`), polluting the operational log triage reads. It
    caused two false readings during this session. Note G6-02's evidence base is NOT contaminated for
    the ACTIVE-toggle chord, which no test emits.

**DOC CORRECTIONS:** G2-25's "ward_heat strip" and "spike-markers live-clock cursor" sub-items are
MIS-FILED against the overlay gate - `overlay.css:134-142` is an explicit "GPU-light" block that hides
`#am-spike-curve`, `#am-spike-markers` and `#am-ward-heat` in the overlay shell BY DESIGN, so no in-game
pass can ever close them; they are dashboard/companion-surface captures. Memory
`reference_overlay_stuck_on_dashboard_liveclient_freeze` is INCOMPLETE - an overlay window showed the
dashboard Home surface with a fully healthy feed; with `data-shell="overlay"` stamped there are two
independent gates preventing that, so a visible Home surface proves the stamp was ABSENT (missing
`?overlay=1` or `overlay.css` failed to load), which is an rc-shell window/asset fault.

---

**OPEN: 111 rows** (was 112; **G6-03 CLOSED 2026-08-02**, the third GATE 6 row ever closed. Was 118; six
CLOSED 2026-07-20 in the drain block above; was 124 before 2026-07-18. G6-04 is NOT subtracted here - it
was filed AND closed after the 112 count without ever entering it, per LEDGER 1169.)
G6-04 was filed AND closed after that count without ever entering it - the commit that filed it
(`41e276b5`, 2026-08-02) did not touch this line, so 112 is still correct and G6-04 must not be
subtracted from it. Check this line's history before adjusting the tally for any row filed after
2026-07-20.
Per gate: G1 6 / G2 41 / G3 12 / G4 28 / G5 10 / G6 3 / G7 18. Of these, 9 carry a PARKED/HOLD
tag (3 inline at G5-10 / G7-16 / G7-19, 6 in the PARKED section) and 1 (G3-15) is a cross-reference
that adds no new work.

**SYNTHETIC-TRIAGE PASS 2026-07-18 - read before proposing this again.** All 124 rows were run
through a 14-agent triage-then-adversarial-refutation pass asking whether recorded data
(`data/rewind_history.db`: 2961 matches, 542,128 timestamped ITEM_PURCHASED events, both teams)
could close them instead of a live game. Result: **6 rows closed, not "a lot"** - G2-07, G3-05,
G3-06, G3-07, G4-08, G7-03. The refuters returned CONFIRMED 15 / PARTIAL 24 / REFUTED 31, and the
dominant kill was SUBSTITUTION: a gate row usually asks whether something RENDERS, SENDS or UPDATES,
and the compute half is always available headless and is always the wrong question. Two agents also
produced evidence that did not survive audit (real match ids whose real builds gave 0.00 pct; a
sample range published as a bound). **Do not re-run this idea expecting a different answer** - the
corpus is already characterized and the residue is genuinely live. What the pass DID buy is the 24
PARTIAL rewrites below: each states what is now settled headless, so the live half is a glance
rather than a session. Reorganized BY GATE 2026-07-18 (see the reorg entry at the top of the
live-flip ledger). A row's GATE is the single question that matters: *what does the operator have to
launch to clear it?* Rows sharing a gate are adjacent; rows sharing an ACTION inside a gate are
batched, so one sitting clears a run.

**Per gate: G1 6 | G2 42 | G3 15 | G4 29 | G5 10 | G6 3 | G7 19.**

PURPOSE. One consolidated list of every RC/DS item that CANNOT be finished headless because it needs
one of: a real live LCU session (lobby/champ-select), live game data on `:2999`, rendered in-game
pixels (overlay/vision/OCR), a live-flip EYEBALL of a DS seam re-rank vs a real game, post-game
Match-V5 ingest of a real match, a physical operator keypress over League, or multi-game ACCRUAL of
real-game data. If an item CAN be validated headless (fixture, harness, dev-preview, replay corpus,
unit test, synthetic liveclient) it does NOT belong here - see "Not actually live-gated" below.

---

## How to drain this file (read once)

**THE GATE LATTICE.** Gates are not a flat list - higher gates SUBSUME lower ones. Launching a gate
also clears everything below it on the same branch, so pick the highest gate you are willing to play
and the batch beneath it comes free.

```
                          GATE 6  PHYSICAL (keypress / OBS over any running game)
                             |  rides on top of ANY in-game gate
                             |
   GATE 4  REAL MATCHMADE SR  (draft; make it ranked q420)
      |  clears: everything in GATE 2 + real-enemy rows + the ONLY path to GATE 4's post-game rows
      |
   GATE 2  PRACTICE TOOL SR  (custom lobby, bots + dummies)
      |  clears: own-build / own-HP / own-stacks / overlay-pixel rows
      |
   GATE 1  ANY LOBBY / CHAMP-SELECT  (no game ever starts)

   GATE 3  ARAM MAYHEM (q2400 KIWI)  -> clears GATE 1 + any own-build GATE 2 row + ARAM-only rows
   GATE 5  ARENA / CHERRY (q1750)    -> clears GATE 1 + any own-build GATE 2 row + Arena-only rows
   GATE 7  ACCRUAL - rides EVERY gate; never closes on one game

   GATE 8  LEAGUE CLASSIC / JADE (RM-141) -> NOT PLAYABLE YET; blocks nothing, subsumes nothing
```

ARAM and Arena are SIBLINGS of SR, not supersets: they give real comps but a different map/item pool,
and neither reaches Match-V5 (q2400 is 403/excluded, customs never record). Anything Match-V5- or
win-anchored is GATE 4 or GATE 7.

**PRACTICE-TOOL LIMITS** (operator-confirmed): bots/dummies only, NO real enemy comps, NO enemy rune
sets, NO allies, customs NEVER appear in Match-V5, no ranked queue.

**BATCH TAGS.** A `[BATCH X]` tag means these rows are cleared by ONE action, not N actions:

| Batch | The single action that clears the whole batch |
|---|---|
| `[DS-SEAM]` | ONE `:8860` restart with the flags armed, then `ops/audit/ds_perm_swarm/live_flip_eyeball.py` dumps OFF-vs-ON top-6 per (champ, seam). Most seam eyeballs need NO mid-game DS bounce. |
| `[OVERLAY-PIXEL]` | Overlay up over a live game, ONE screenshot pass across every named widget. |
| `[OVERLAY-INTERACT]` | Overlay up, ONE pass of click / drag / hover round-trips. |
| `[CS-CAPTURE]` | ONE champ-select, screenshot every named panel before lock-in expires. |
| `[CS-SCENARIO]` | Rides champ-selects until the scenario rolls. Cannot be forced. |
| `[POST-GAME]` | The 90s window after a Match-V5-eligible game ends. GATE 4 only. |

**FOUR RULES.**
1. **`E3` (GATE 6-01) rc-shell Electron MAIN relaunch is a PREREQUISITE** for every `[OVERLAY-*]`
   batch. Do it before the game starts, not after.
2. **Do-not-flip-blind (charter 4b).** An eyeball closes the EYEBALL half. The default-ON flip stays
   operator-gated and is a separate line in the ledger.
3. **Never close an accrual row on one game.** GATE 7 rows re-run a rail; the rail decides.
4. **RC auto-serves UI via ADR-008** (no restart for web/asset changes). ENGINE flips need a DS
   `:8860` restart. `tools/live_flip_watcher.py` (RC-LiveFlipWatcher, armed) auto-toasts seam verdicts
   during real games.

**SEAM GROUND TRUTH (source-verified 2026-07-18, `agents/daemon_slayer/ehp.py`).** Only THREE item
seams are default-ON in the engine: `assume_item_crit_dr` (:1184), `assume_item_aa_dr` (:1185),
`assume_item_enemy_as_slow` (:1190). Every other `assume_*` / `apply_*` seam is default-OFF at its
signature. Two seams are wired ON at the live CALL site: DSP11 `prefer_kit_axis_by_win`
(`coach_integration/archetype_dispatch.py:215`, flipped `fb921a98`) and the incumbent-hysteresis
(`core/build_order.py:423` opt-in, `dashboard/routes_state.py:955->970`, panels `build_order.js:70`
+ `active_match.js:291,340`). DSP2/F2/RF1/RF2/RF3 are transport-plumbed across `/rank` (item 638) but
their live callers still omit the flags. DSP5/6/7 + anti-tank P3.2 are producer-only orphans (route
+ test imports only, no live feeder). Env gates `RC_COMP_HP_LEAN` / `RC_LANING_CV_SERVED` are cold.

**IN-GAME FIRST STEP (lane 9).** Run `python tools/gated_live_probe.py` the moment a game is up. It
dumps the evidence-contract inputs (mode + gate, real ally/enemy comp, coach_source + Haiku-credit-paused,
vision `frame_bytes`, the cc-panel / st-* serving-surface scans, minimap dots, zoi) in ONE shot, so the
in-game pass is copy-paste, not a mid-game re-derivation. Two verdicts it hands you directly: a zero
`frame_bytes` means every pixel / OCR / augment row is BLOCKED this session; an empty `cc_panel_in_state`
or `adapt_fields_in_state` means that value has no live serving surface, so it is the SUBSTITUTION trap -
do NOT tick it from the compute half. `--json` for machine output. READ-ONLY; it never ticks a row.

---

## GATE 1 - ANY LOBBY / CHAMP-SELECT (no game ever starts)

Cheapest gate in the file. Enter a lobby, capture, leave. Nothing here needs a match.

- **G1-00** `[CS-CAPTURE]` R148 champ-select shaping refactor - live confirm OWED. `lcu/champ_select_shape.py`
  extracted the ~155-line shaping out of `capture_state()` (`tools/lcu_agent.py`) as a behavior-identical
  pure function. Offline proof is strong: a pre/post `capture_state()` differential over 5 fixtures
  (SR draft, ARAM bench, Arena augments, None-session, empty-dict) returned ZERO mismatches with
  identical key order, plus 272 tests on the touched suites. RC-LCUAgent was restarted post-merge under
  the real scheduler invocation and came up clean (the `sys.path` shim works against the task's EMPTY
  WorkingDirectory), but the client was Offline, so the agent only exercised the early-return shape
  (`config` / `phase` / `ts`) - **the new shaping code path has never executed live.**
  **CHECK:** enter ANY champ-select, then `curl -k https://127.0.0.1:8888/api/state` and confirm
  `lcu.champ_select` is populated with the usual fields (bench, actions, my_pick, team picks; plus
  `arena_teams` + `augments` if it is an Arena lobby) and that the champ-select view renders as before.
  A silent `{}` or a missing key is the failure mode to look for. Closes on one lobby - no game needed.
  **L3 ADDENDUM (2026-07-20, commit `9eb76879`):** the E12 lever L3 in-process rewire landed DARK.
  `lcu/snapshot_shape.shape_snapshot` now owns the FULL snapshot assembly (agent delegates to it,
  champ_select byte-identical, suite green 12324/0), and `dashboard/_lcu_inprocess.lcu_summary_inprocess`
  is wired into `dashboard/_state_builder._read_lcu_snapshot` behind DEFAULT-OFF flag `RC_LCU_INPROCESS`.
  **CHECK 2 (same lobby):** with a champ-select up, set `RC_LCU_INPROCESS=1`, restart RC, `curl -k
  https://127.0.0.1:8888/api/state`, and byte-compare `lcu.champ_select` against the flag-OFF relay value -
  they MUST be identical. **Accepted divergence to adjudicate live:** the in-process path omits
  `state.lcu.config`, so the `main.js:5663` auto-accept pill loses its source when the flag is ON - decide
  at G1-00 whether the dashboard reader should synthesize `config` (main-process `_lcu` auto-accept is
  always ON) or whether the pill moves to a different signal. Flag stays OFF until this check passes.
- **G1-01** `[CS-CAPTURE]` (was A8) Locked-own-champ champ-select panel captures - **SHRUNK 6 -> 3
  artifacts 2026-07-18; still OPEN at GATE 1.**
  **RE-FILED, GATE 1 -> GATE 2:** ds-sweep / ds-relscore / ds-statcheck are ACTIVE-MATCH panels, not
  champ-select panels. Capture them in the GATE 2 `[BATCH OVERLAY-PIXEL]` pass alongside G2-25. This
  RE-FILES, it does not CLOSE - all 3 still need a live game, just a GATE 2 one. EVIDENCE: all six
  token forms score **0 refs** in `web/js/panels/champ_select.js`; the mounts at
  `web/index.html:2155 / 2165 / 2179` sit inside `#view-active-match` (opens :2093 -> am-grid :2098 ->
  am-pane-build :2137, closes :2189); their renderers are imported by
  `web/js/panels/active_match.js:39,54,59`; the relocation is stated in-source at
  `web/index.html:2145-2148` and `:2166-2169` (CS3, 2026-06-08 - the `csv-` id prefix is a deliberate
  legacy-id trap, NOT a champ-select tell); and `tests/snapshot_panels/test_champ_select_view.py`
  `_REMOVED_SELECTORS` pins `#csv-sugg-ds-profile` / `#csv-ds-knobs` / `#csv-ds-statcheck` as
  must-be-ABSENT. **The OPERATOR CALL is answered: they are not moot post the overlay-only doctrine,
  they are MIS-FILED.**
  ALSO SETTLED: the ">=8-game history" precondition is SATISFIED, not a blocker - **80 of 146** tracked
  champions qualify in `data/rewind_history.db`, and live `/api/personal-build` returns Vayne sr
  games=55 wr=0.4727 / aram games=92 wr=0.6196, Tristana sr games=79 / aram games=61. That closes a
  PRECONDITION, not the row.
  LIVE RESIDUAL (glance): in ONE champ-select with your champ LOCKED, screenshot the three surviving
  champ-select cards - ds_skill_order (R54, `67a1bb61`), personal-build WR, build-order B-card - then
  run the per-page UI-audit ritual. The same test file's `_NEW_STATIC_SELECTORS` "kept survivors" block
  (`#csv-sugg-ds-skill-order` / `#csv-personal-build` / `#csv-sugg-counter-picks`) pins that these ARE
  still champ-select mounts. SOURCE: LEDGER 715/717/623/635.
- **G1-02** `[CS-CAPTURE]` (was A5) rc-shell PRE-GAME LOBBY `lcu.lobby.members[]` render (YOUR MAINS /
  PARTY / MY TOP-8; if empty, capture the agent's live `/lol-lobby/v2/lobby` read + `_slim_lobby_member`
  output) + eyeball the overlay surface gate `cac1df3a` (companion in lobby/CS, lean HUD once
  liveclient populates). SOURCE: ledger 2026-06-20.
- **G1-03** `[CS-SCENARIO]` (was A3) CC-conditional pairing UI renders on champ-select (`541cd9d3`) -
  needs a CC-pairing lobby to roll; never rolled 2026-07-04. Rides every champ-select at any gate.
- **G1-04** (was A4 + QA24) LOBBY1 top-8 friend-invite live verify (`1f4f4118`) + the QA24 non-friend
  invite path end-to-end + the operator-reported defect that inviting others does not send unless the
  confirm dialog is accepted. BLOCKED ON: a real invite target / second account. SOURCE:
  docs/ORCHESTRATION_PLAN.md:63.
- **G1-05** `[BLOCKED - RE-TAGGED 2026-07-18]` (was A11) OVL2 Pengu Surface C live validation
  (`aab53e37`). **RE-TAG source: this GATE 1 row; destination: BLOCKED - it is neither drainable by a
  game nor stale-and-closable.** SETTLED HEADLESS: repo-root `pengu/` is ABSENT and all 6 tests in
  `tests/test_pengu_plugin_skeleton.py` skip via a `pytestmark` `skipif(not PENGU.is_dir())` with the
  reason "pengu/ stub relocated to docs/_archive/2026-07-07-pengu-stub". **But the source is NOT gone -
  "no plugin source exists to inject" is FALSE:** `docs/_archive/2026-07-07-pengu-stub/` holds
  `index.js` (4575 B), `panel.css` (2204 B) and `README.md` (1775 B), force-tracked under the
  `_archive` quarantine convention. And the work is not abandoned - `ROADMAP.md:58` still carries
  "(c) Phase 6 Pengu in-client panels, OPTIONAL" as OPEN. Those 6 tests were never this row's evidence:
  the test header itself says the stub is code-only and live validation is OWED.
  BLOCKED ON one operator decision: un-archive the stub back to `pengu/` and rebuild, OR retire the
  row. Until that is answered there is nothing a game can drain, so do NOT count this row in a gate
  session. Cited `aab53e37` does not resolve in this repo (4 of GATE 1's 5 cited hashes do not - they
  are pre-cherry-pick worktree SHAs per the `docs/history_notes.md:4468` merge workflow: a systemic
  citation defect, not fabrication). SOURCE: docs/ORCHESTRATION_PLAN.md:82.
- **G1-06** `[NOT BUILT]` (was A12) Mode-specific overlay layout AUTO-SELECT-ARAM acceptance - queued
  for planning, not yet built. Once built the auto-select needs a live ARAM queue/lobby state and a
  per-map placement eyeball. SOURCE: BACKLOG.md:48.

---

## GATE 2 - PRACTICE TOOL SR (custom lobby, bots + dummies)

The workhorse gate: own build / own HP / own level / own stacks / rendered overlay pixels. Everything
here is ALSO clearable inside a GATE 4 real SR game (and the own-build subset inside GATE 3 / GATE 5).
**Relaunch rc-shell (G6-01) BEFORE starting.**

### `[BATCH DS-SEAM]` - one DS `:8860` restart clears this entire block

Arm the flags, restart once, dump OFF-vs-ON with `live_flip_eyeball.py`, eyeball the batch. Do NOT
bounce DS mid-game. Each row's default-ON flip stays operator-gated after its eyeball passes.

- **G2-01** (was B5) DSP2 `exempt_offclass_by_win` - **EYEBALL DONE 2026-07-04** (Ezreal ON floats
  Trinity Force in / Yun Tal out, staples stay top-3; crit ADCs byte-identical). **NO LIVE RESIDUAL
  2026-07-18: what is left is an OPERATOR DECISION, not a game.** Only the default-ON flip remains
  (`rank.py:686` still defaults False - the old `:632` cite was a stale line number), and the batch
  header already gates that independently of any eyeball ("each row's default-ON flip stays
  operator-gated after its eyeball passes"). Re-running the eyeball on another champion re-does work
  this row already records and cannot discharge the residual. This is exactly the shape the file
  already files under "Not actually live-gated" for DSV5 `RC_COMP_HP_LEAN` - eyeball DONE, remainder is
  ONE operator decision. **CAVEAT: this is a DISPOSITION change on the row's own recorded evidence; no
  new measurement closed it.** Do not schedule a game for this row. SOURCE: LEDGER 779.
- **G2-02** (was B7) B1 `apply_melee_aa_gate` - melee bruiser build drops Runaan's, ranged carry
  byte-identical. /dps route transport WIRED (OQ17).
- **G2-03** (was B8) R7 `assume_passive_as_stacks` (Irelia/Jax/Ezreal/Volibear at full stacks; stacks
  buildable vs dummies/minions). **Irelia eyeball SANE 2026-07-02** (/dps 38.90 -> 47.96, +23%); the
  flip stays gated across the 4 tabled champs.
- **G2-04** (was B9) R5 `assume_missing_hp_heal_amp` + live caster missing-HP feed (drop own HP vs
  bots; coach-side hp/hp_max already emitted, item 639).
- **G2-05** (was B10) R12 `apply_target_vuln` (Vladimir/Evenshroud) + the R43 Imperial Mandate rider
  (4005/224005/324005). Broaden the consumer beyond AA DPS to ability_dps + burst.
- **G2-06** (was B11) R14 `apply_cc_floor` floor-model sanity for close-range Maokai/Ashe/Hecarim R.
  **CODE PREREQ (headless):** thread the flag through the compute_ehp / compute_hybrid /
  cc-blended-EHP consumer chain - none thread it yet. Not eyeball-able until that lands.
- **G2-07** (was B12) R17 + R39 anti-tank level-ramp (`compute_antitank(level=)`) - **CLOSED
  2026-07-18, NOT LIVE-GATED.** `compute_antitank` is a pure function of (champion, level) - no live
  state, no render, no transport dependency - so the ramp confirm never needed a running client.
  MEASURED (independent adversarial re-run, exact to 4dp): **Aatrox L3 0.4750 -> L16 0.8000 RAMPS;
  Senna L3 0.0772 -> L16 0.3353 RAMPS (4.34x)**. Negative controls hold FLAT at both levels - Darius
  0.4550 / 0.4550, Vayne 0.9500 / 0.9500, Fiora 0.9000 / 0.9000. The row's "level-3 < level-16"
  criterion is met and the control could have failed and did not.
  RESIDUAL IS HEADLESS CODE, NOT A GATE - do not re-file it to a gate: part (a) "wire the live
  champion level" is still UNWIRED. The only live caller, `core/ds_antitank_hint.py:76`, calls
  `compute_antitank(safe_champion, safe_mode)` with NO level argument, while the HTTP route does accept
  it (`server.py:1646`). Same shape as the G2-06 "CODE PREREQ (headless)" precedent.
- **G2-08** (was B13) R30/DSV6 `assume_magic_burst` (Luden's/Stormsurge/Malignance) + R69 item ACTIVES
  (Rocketbelt 3152/223152, Everfrost 446656) + R70 Zeke's 3050/223050/323050 Frostfire Tempest.
  compute_ability_dps deliberately inert. Confirm an active/ult-trigger holder's burst reads sane and
  assumes the trigger fires inside the burst window.
- **G2-09** (was B14) R35 `apply_passive_mitigation` + snapshot (Galio/Garen/MasterYi percent-DR);
  confirm the rank-4 + 0.3-uptime assumptions read sane.
- **G2-10** (was B15) R45 Poppy W low-HP doubled percent-of-resist tier - feed
  `caster_current_hp_pct` (drop own HP), sub-40%-HP EHP ranking sane.
- **G2-11** (was B16) R46 `assume_passive_health_stacks` (Sion W / Cho'Gath R / Swain P; stacks
  farmable on minions). Ideally replace the assumed-stack curve with a live stack feed later.
- **G2-12** (was B17) R49 `assume_passive_reflect` (Rammus W) + R68 the ITEM Thorns lane on the SAME
  seam (Thornmail 3075 + mirrors 223075/323075 + Bramble Vest 3076). Practice bots DO attack, so the
  1.0s cadence + 3.0s window assumptions are exercisable for both streams. STRICTER READ: re-check
  ranking-vs-real-comp in the GATE 3 ARAM sitting.
- **G2-13** (was B18) R51 `gate_target_hp_amp` per-instant consumer (dummy HP is settable) -
  per-instant / stepped scenario eval, **NOT a blind burst-scorer flip**. Transport WIRED (OQ17).
- **G2-14** (was B19) R53 `gate_caster_hp_amp` per-instant consumer (own HP droppable) - same
  per-instant discipline. Transport WIRED (OQ17).
- **G2-15** (was B20) OQ1/R55 `assume_archetype_hp_pct` OFF-vs-ON re-rank (BotRK 3153 / Hellfire 4017 /
  Fulmination 443055 only). Own-build sanity reached **3/3 2026-07-04** (Kalista + Tristana + Vayne).
  The flag is NOT a `/rank` body param (`server.py:452-453` exposes only exempt_offclass_by_win +
  prefer_kit_axis_by_win), so the OFF-vs-ON flip itself needs the DS restart with the seam armed. The
  0.5 sustained-fraction CALIBRATION is GATE 7 (G7-14). SOURCE: LEDGER 718 + 779.
- **G2-16** (was B41) R58 `assume_ms_utility` - **PARTIAL 2026-07-18.** SETTLED HEADLESS: the
  mechanism fires and is directional - MS carriers gain rank with the seam ON (Sion Force of Nature
  4401 rank 40 -> 37; Darius Dead Man's Plate 3742 rank 11 -> 8). **THE MS-LESS CONTROL DOES NOT HOLD
  AND MUST NOT BE QUOTED AS PASSING:** on an independently pulled real build, Sion Warmog's 3083 moved
  23 -> 24 and Darius Warmog's moved 42 -> 43. That is expected - rank POSITION necessarily shifts when
  other items move up - so a leak test has to pin the SCORE, not the rank. An earlier "Warmog's 15->15
  / 61->61 pinned exactly" reading was build-luck, not a property of the seam. Re-instrument the
  control on score before any flip. UNTOUCHED: the row's FOLLOW-UP SEAM (unresolved into `stats[ms]`) -
  the stack-ramp MS registry (Shipwrecker +20 flat / Steadfast +6 pct).
  LIVE RESIDUAL (glance): on a juggernaut carrying 3742 + 4401 in-game, read the /rank-bruiser order -
  MS items should gain modest credit and no MS-less staple should be displaced by more than a slot -
  and sanity-check the 0.5 fraction / 0.15 cap against how much the movement speed actually bought you
  in that fight.
- **G2-17** (was B41b) R75/DSV9 `assume_shielded_target` (Serpent's Fang 6695). Practice suffices
  (assumed pool 0.20 x target max HP, melee 50% / ranged 35%); a REAL game vs Shieldbow/enchanter comps
  is the stronger eyeball. Sanity = the credit does not dominate a real-damage item swap.
- **G2-18** (was B49) R111 `assume_caster_lowhp` (Overlord's Bloodmail 2501 "Retribution"): build it,
  drop to low HP, eyeball the missing-HP-scaled bonus AD credit. Midpoint
  `_ASSUMED_CASTER_MISSING_HP` 0.35 / cap 0.70. SOURCE: LEDGER 879.
- **G2-19** (was B3) DSV2/3/4 `assume_takedown` / `assume_squishy_target` / `assume_ability_amp` on the
  BURST scorer `burst.py rank_items_by_burst` (NOT rank.py). Transport WIRED (OQ17). R70 added the
  Hollow Radiance Desolate takedown eruption (6664/226664) to the `assume_takedown` stream - confirm an
  HR-holder's burst reads sane next to Hubris/Collector. Client-helper emit still pending.
- **G2-20** (was B6) DSP4 `score_completion_runes` (Shield Bash 8401) - **PARTIAL 2026-07-18.**
  SETTLED HEADLESS: the correct instrument was used correctly - `compute_burst_damage` was called
  DIRECTLY with a real Resolve page (not the re-rank harness this row forbids) - and the seam is
  non-inert: burst reads **+2.64%** with the runes scored. Transport WIRED (OQ17, /burst parses
  `runes`). **CAVEAT: that figure was NOT independently reproduced, and a rune-sized credit being
  rune-sized is equally consistent with the seam working and with it being mis-scaled** - the number
  alone discriminates nothing.
  LIVE RESIDUAL (glance): with a real Shield Bash page in a live game, judge whether ~+2.6 pct of burst
  is the right ORDER OF MAGNITUDE for what Shield Bash actually contributed in a fight. That is a
  magnitude judgment, not another delta.
- **G2-21** (was B2) DS Phase-D: `apply_passive_damage` + the 4 non-every-AA `on_hit` + per-stack
  `assumed_stacks`. **NOT a clean transport flip:** `apply_passive_damage` is deliberately /dps-scoped
  (R7/R12 precedent, `rank_items` does not forward it), the on_hit remainder needs net-new cadence
  math, and `assumed_stacks` needs a live stack feed. Own-build re-ranks are unverifiable headless.
- **G2-22** (was B4) Anti-tank P3.2 - call `antitank.compute_antitank_live` with the live build +
  eyeball scaled %max-HP magnitudes. R93 added Darius E (Apprehend) as a PERCENT_PEN/SUSTAINED row
  (compute_antitank 0.0 -> 0.455, shreds_resist True), so this same eyeball surfaces Darius' shred.
  HTTP transport WIRED (OQ18) BUT no dashboard/modes caller POSTs a live build - this is a
  **code+eyeball slice, not a pure flip**. No DS restart on the flip itself.
- **G2-23** `[NEW ROW 2026-07-18 - 12 seam obligations that had NO checklist row]` Item-side
  survivability/burst seam BATTERY. All twelve shipped default-OFF between 2026-07-10 and 2026-07-14
  with an OWED operator flip-eyeball recorded ONLY in the live-flip ledger below. They share one
  action: arm, restart `:8860` once, eyeball each carrier's EHP/burst rank vs its natural rivals.
  Defaults source-verified 2026-07-18 in `agents/daemon_slayer/ehp.py`.

  | Flag | Items | Ref | Line |
  |---|---|---|---|
  | `assume_kaenic_shield` | Kaenic Rookern 2504 | R92 | ehp.py:1154 |
  | `assume_eclipse_shield` | Eclipse 6692 / 226692 | R97 | ehp.py:1159 |
  | `assume_seraphs_shield` | Seraph's 3040 / 223040 / 323040 | - | ehp.py:1171 |
  | `assume_fimbulwinter_shield` | Fimbulwinter 3121 / 223121 / 323121 | R129 / LEDGER 903 | ehp.py:1177 |
  | `assume_max_stacks_omnivamp` | Riftmaker 4633 / 224633 | R100 | ehp.py:1199 |
  | `assume_item_revive` | Guardian Angel 3026 / 223026 | R102 | ehp.py:1208 |
  | `assume_item_stasis` | Zhonya 3157 / 223157, Seeker 2420, Wooglet 228002 | R103 | ehp.py:1220 |
  | `apply_item_spell_shield` | Annul (spell-shield cc_blended discount) | R104 | ehp.py:1231 |
  | `apply_item_mana_health` | Winter's 3119 / Fimbul 3121 + mirrors | R105 | ehp.py:1242 |
  | `apply_item_resist_grants` | Jak'Sho 6665, FoN 4401 + R124 prismatics 443058 / 443059 | R106 + R124 | ehp.py:1251 |
  | `apply_item_bonus_hp_amp` | Warmog's 3083 / 443083 | R107 | ehp.py:1261 |
  | `assume_item_lowhp_magic_crit` | Shadowflame 4645 / 224645 (BURST axis, sub-40% target) | R110 | burst.py |

  EYEBALL SHAPE (same for all): the carrier up-ranks sensibly on its axis WITHOUT dominating a real
  resist/damage swap, and a one-instance credit is not over-credited on a sustained-fight clock. The
  EXACT ones (`apply_item_mana_health`, `apply_item_bonus_hp_amp`) carry no midpoint and are the
  safest to flip first. Full per-seam magnitudes + caveats: the live-flip ledger below.
- **G2-24** (was B47b) R108 `assume_item_general_dr` - item UNTARGETED GENERAL %DR (Celestial
  Opposition 3869 "Blessing" 35% melee / 25% ranged + Crown of the Shattered Queen 664644 "Safeguard"
  40%), the ONLY item DR lane that touches the TRUE denominator. **PARTIAL 2026-07-18.**
  SETTLED HEADLESS: the mechanism is wired and leak-free - carrier EHP rises **+11.11% ranged**
  (Soraka) and **+16.28% melee** (Sion), with both no-carrier controls byte-identical at +0.00%,
  reproduced independently on a second build. **DO NOT read those two percentages as corroboration of
  the midpoint:** they are the DR identity restating the registry constants, `1/(1 - 0.25*0.4) =
  +11.11%` and `1/(1 - 0.35*0.4) = +16.28%` - build-invariant and champion-invariant bar the
  melee/ranged split. A delta computed FROM the assumed uptime cannot validate the assumed uptime.
  LIVE RESIDUAL (glance, irreducibly live): while carrying 3869 or 664644, watch how much of a real
  fight the DR is actually UP for - Celestial refreshes on every champion hit (high uptime), Crown
  breaks then sits on a long CD (low uptime) - and say whether the shared 0.4 `_GENERAL_DR_UPTIME` is
  too low, right, or too high. Observed uptime is the ONLY thing that moves this row.
  The Arena mirror 444644 magnitude confirm is GATE 5 (G5-08). The "Draw Your Sword" Runaan's blind
  spot flagged at R108 is FIXED (LEDGER 856). SOURCE: LEDGER 855.

### `[BATCH OVERLAY-PIXEL]` - overlay up, one screenshot pass

- **G2-25** (was B24) Overlay populated pixel-capture family: OVL1 settings controls (`4d09f8ac`);
  R33 ward_cue / spike_cue / objective_chips / minimap_zoi / minimap_rect (`2b03c529`); R40 draft_elo
  chip + ward_heat strip (`4a1622cc`); W3E callouts + lead_projection; spike-markers live-clock cursor;
  item-662 first-match no-flash confirm; OQ14 Item Shaper Row4 SHAPER strip (`dc45f749`). Also folds
  the BATCH B minimap gold-border render check (after an rc-shell RELAUNCH, confirm the gold border
  lands fixed to the minimap) + the BATCH C gauge-row / enemy-chip-wrap render. STATUS: NOT drained
  2026-07-04 (frame endpoint probed http + X-RC-Token, game ended before a clean grab). SOURCE:
  LEDGER 662 + 735 + 799.
- **G2-26** (was the pixel half of C13) R38 enemy_spells `stats_panel` RENDERED PIXEL capture. The
  DATA path is live-proven TWICE (LEDGER 769 + LEDGER 820 2026-07-08, 5 enemies x 2 spells); LEDGER
  820 explicitly records "CSS visual verify PENDING (overlay hidden)". Best read vs real enemies
  (GATE 3 or 4) but the widget renders at any gate.
- **G2-27** `[NEW ROW 2026-07-18]` Overlay item-8 rank-tier stats panel: (a) the live render eyeball
  (`f9996bc8`), and (b) the LEDGER 873 (C) deferred finding - the `w-stats` default position
  (`web/js/lib/overlay_layout.js:67`, x40) COLLIDES with the primary `w-call` coach panel (180,130),
  so on FIRST run the coach call paints over the provenance badge before the operator repositions.
  Tuning the default anchors needs an in-game eyeball. SOURCE: LEDGER 873; RM-04.
- **G2-28** `[NEW ROW 2026-07-18]` RM-05 round-1 shipped-fix live-verify (LEDGER 914 S4+S7,
  `a486142b`): the MISSING-IN-GAME cluster (`rn-lead` / `rn-choices` / `rn-callouts` / `w-spike`) was
  ROOT-CAUSED - the panelset-gating hypothesis is DISPROVEN (panelset gating is retired/dead, pinned
  by `test_overlay_route_smoke.py`); the mounts are DATA-gated and their only reliable in-game feed is
  the E6 poller, which was mode-gated to sr/aram/brawl and is now split so coaching mounts also feed
  arena/tft. SR/ARAM/brawl needed no code change and needs only the live-verify; the arena/tft fix
  needs its own. ALSO folds the LEDGER 809 E6 fix: lead_projection / callouts / coach.choices /
  liveclient now refresh from the unconditional 2s `/api/state` poll in `main.js` (they were dark
  in-game, gated on a WS push that never fires) + the minimap_rect trim calibration (18px left, 14px
  top) at 2560x1440. CONFIRMED-OK already: `am-mmrect` ZOI markings DO show in-game.
- **G2-29** (was B26) ZOI shading alpha/blur live tune (MAX_ALPHA 0.55 / ZOI_BLUR_PX 12 shipped,
  pending operator verify) + `#rn-choices` live DOM inspect (has data + renderer runs, absent in DOM).
  Native-res grab (`ac50f1af`) is the foundation. The ARAM flood-tint question re-checks at GATE 3.
- **G2-30** (was E6) OVERLAY headless-polish LIVE-RECON punch-list (operator LIVE-GATED the WHOLE
  remaining set 2026-07-05): build-META knob-steppers + item right-click radial, drag/move system,
  context-menu item tooltip crop/position, PR enemy-spell chip cooldown timer, gauges 1-line layout.
  Each fix needs the operator's live Ctrl+Alt+A verify before it lands - root-cause allowed, shipping
  blind FORBIDDEN. Several sub-items now have shipped fixes owed a verify: see G2-28 / G2-32 / G2-33.
  DISPOSITION NOTES from RM-05: build META row should stay STATIC; DMG/SURV/UTIL knob steppers dead;
  item right-click 5-choice radial dead; ward_cue teardown is a deliberate live-session job (live
  serializer + test + overlay DOM contract), never a blind headless delete.

### `[BATCH OVERLAY-INTERACT]` - overlay up, one pass of click / drag / hover

- **G2-31** (was B25) Overlay build-module interaction round-trips: D1 tooltip hover (LEDGER 780
  flagged rune icons render with NO hover tooltip - fix pending), D2 right-click radial + zone
  flip/wedge clicks landing mid-game, D3 override survives a re-plan + Defer-Once re-entry + reset
  (plus the cross-tick LIVE-route Defer-Once per-match store gap - code work), settings-slider drag
  mid-game, B2/B3/C5 module captures. SOURCE: docs/OVERLAY_BUILD_MASTER_PLAN.md:806-816.
- **G2-32** `[NEW ROW 2026-07-18]` RM-05 round-2 drag/move system live-verify (LEDGER 914 S2,
  `14a5ccc5`; `web/js/lib/overlay_layout.js` - `_effectiveXY` drag origin + window-level pointer
  capture + handle-only border hit-test, `_clampXY` semantics preserved). Verify EACH panel, including
  the ACTIVE empty-backing "press now inert" behavior call.
- **G2-33** `[NEW ROW 2026-07-18]` PR enemy-spell chip cooldown timer live-verify (LEDGER 914 S3,
  `b827f782`; `web/js/panels/enemy_spells.js` - upgraded-Smite displayNames + cd=0 sticky "USED" chip).
- **G2-34** `[NEW ROW 2026-07-18 - LIVE-GATED DECISION]` Objective gauges 1-line collapse: the
  operator picks horizontal vs vertical after seeing them in-game. SOURCE: RM-05.
- **G2-35** `[NEW ROW 2026-07-18 - LIVE-GATED DECISION]` `am-statspanel` intent: CLARIFY with the
  operator before acting (RM-05 explicitly parks this pending an operator call over a live render).

### GATE 2 singles

- **G2-46** (RM-307, filed 2026-08-31 lane 8 cycle 44) Settle which player field the Live Client
  `events.Events[].KillerName` actually carries. TWO RC modules read the SAME field against
  DIFFERENT rosters and at most one can be right: `dashboard/_liveclient.py` classifies it against
  `championName` sets, while `core/decision_detector.py` matches it against
  `summonerName` / `riotIdGameName`. If the summoner-name reading is right then
  `killer_team` is permanently unknown live, and THREE features are unconditionally silent in
  production: `epic_buff_callouts` (drops any unsided buff by design), `dragon_soul_callout`
  (returns None - verified headless: four drakes with `killer_team=unknown` yields None) and the
  soul suppression in `_dynamic_epic_callouts`. **THIS IS NOT HEADLESS-DRAINABLE and the reason is
  the measured one:** `tests/test_liveclient_objective_events.py` `_player()` sets
  `summonerName` and `championName` to the SAME string, so the fixture is parallel by
  construction and all 7 of its tests pass under EITHER reading. No synthetic fixture can settle a
  question about what Riot actually sends. CHECK: in ONE game with any objective kill (drake, herald
  or baron), capture the raw `GET :2999/liveclientdata/allgamedata` body and record the literal
  `KillerName` value for that event beside the same game's `allPlayers[].championName` and
  `allPlayers[].summonerName`. One capture answers it permanently. Also record a kill CREDITED TO
  A TURRET OR MINION if one occurs - that case yields a non-champion KillerName under EITHER reading
  and is the confirmed-live half. SOURCE: BACKLOG RM-307, LEDGER 1303.
- **G2-39** (RM-124, built 2026-07-29 `efbb34d0`, gated OFF) Validate the deterministic wave/cannon
  clock cadence before the flip. The code ships (`core.event_callouts.wave_callout` + `minion_events`
  transport) but `enable_wave` defaults False; the dashboard flips it only on env `RC_WAVE_CALLOUT=1`.
  The interval + cannon-cadence constants are PROVISIONAL (sources disagree on the 14:00 vs 15:00
  breakpoint; 2025 moved first cannon 2:05 -> 2:35). CHECK: in one practice/real SR game, confirm (a)
  `liveclient.minion_events` carries a single `{at_s}` at first-wave spawn, and (b) with
  `RC_WAVE_CALLOUT=1` the "Cannon wave incoming" chip ETA counts down to the ACTUAL observed cannon
  arrivals (first cannon ~wave 3, then the every-2nd/every-1 tightening past 14/25 min). Correct the
  constants against reality if they miss, THEN flip the env on by default. SOURCE: ROADMAP RM-124.
- **G2-36** (was B1) Build-chooser pushes correct runes/items/spells MID-GAME to LCU (3-variant +
  Experimental row). RENDER + generic-build path confirmed 2026-07-04 (Zilean support); the mid-game
  LCU PUSH LOG LINE is still owed - no push line captured in any drain. SOURCE: LEDGER 779.
- **G2-37** (was B27) LBAND1 live wire-in eyeball: `core/live_benchmark_band` into the
  deterministic-coaching surface + overlay (live cs+level vs own per-champion percentile). The
  generator half is SHADOW-only today (`data/live_benchmark_band_shadow.jsonl`); this is the surface +
  flip. SOURCE: BACKLOG.md:162.
- **G2-38** (was B28-DS) DS PD->Kraken cross-restart rank-stability - **PARTIAL 2026-07-18, the
  closest-to-closable row in GATE 2.** SETTLED HEADLESS: the corpus supplies exactly the shape the row
  asks for - a real level-up crossing two within-margin items - and the mechanism reproduces.
  Provenance holds (NA1_5217553130 really does carry Jhin on 3033/3009/6676/3031/3094); the hysteresis
  is real at `core/build_order.py:405 incumbent_margin: float = 0.03` with the Jhin-specific note at
  `:249`; and the decision arithmetic is coherent - **58.709 * 1.03 = 60.470 < 61.695, so the flip is
  correctly ALLOWED, not damped**. **TWO FIGURES NOT REPRODUCED - do not quote them:** the
  672-crossing scan count and the 58.628 / 58.264 pre-tick values. Re-run that scan (and keep the
  script) before any flip.
  LIVE RESIDUAL (glance): a corpus replay RECONSTRUCTS the incumbent, whereas the live hysteresis reads
  the incumbent the UI last actually RENDERED. So in-game, on one level-up tick where the top two build
  items sit within ~3%, confirm the rendered top pick does not visibly flip PD <-> Kraken.
  ARAM-suitable. SOURCE: LEDGER 799.
- **G2-39** (was B29) QA6 fullscreen-detect "switch to Borderless" hint + QA13 UIPI elevation-parity
  detect final validation. Low-confidence inferred rows - **build headless first**.
- **G2-40** (was B30) DS ratio-block spot verify vs target dummies (~174/577 flagged). DS-batch
  scoped: sample a handful per session, never a bulk pass. SOURCE: docs/DS_COMPLETENESS_GAP.md:85.
- **G2-41** (was B48) Vision-OCR native-res crop path: the live OCR read path still consumes the
  1280-HALVED `/latest-frame` (`vision_server/_frame.py` `_SELF_GRAB_MAX_WIDTH=1280`), so native-2560
  OCR boxes get scaled DOWN 0.5x at crop time. WIRE `core/screen_grab.grab_native()` into the OCR crop
  path (skip the downscale for OCR crops ONLY, keep it for the Sonnet/bandwidth `/latest-frame`), then
  validate OCR read accuracy vs a real in-game frame. Recalibration + native-crop WIRING is DONE
  (R94/R95/R96/R98); this is the last live-gated tail. SOURCE: LEDGER 793.
- **G2-42** (was H4) ZOI finalization do-not-flip-blind eyeball: before flipping `obs.frame_source`
  (done) / roster-wiring ON, verify in a practice SR game (a) macro callouts on >=2 enemies MIA near
  drake, (b) district vector on `/api/state.zoi.districts`, (c) OBS frames matching the GDI baseline,
  (d) MIA rings + fluid DMZ + weighted bubbles render. Practice suffices (fog/presence/CV/OBS
  round-trip, no enemy-comp/rune dependency). SOURCE: ZOI_DISTRICT_ORCHESTRATION_PLAN.md:107-109.
- **G2-47** RM-42 `apply_passive_damage` **+ `apply_extra_shot_procs`** on the CARRY ranker (ENGINE 1.273.0 / 1.274.0). **THE TWO FLAGS MODEL TWO HALVES OF ONE EVENT AND MUST BE FLIPPED TOGETHER, NEVER SINGLY** - `apply_extra_shot_procs` alone credits the shot's PROCS while its damage stays uncredited, a coherent but partial model. Full model measured: Akshan 142.06 -> 257.05 (+80.9 pct). Original text follows. (ENGINE 1.273.0, `rank.rank_items` +
  `/rank` + `core/daemon_slayer_client.rank_for`). Route exposure is SHIPPED and default-OFF. Headless
  is DONE and is not the question: Akshan's weighted DPS goes 142.06 -> 212.19 at depth (+49.4 pct,
  +48.9 per hit), verified over HTTP after the :8860 bounce, Sivir control byte-identical, all six
  build tables stamp-only. What headless CANNOT settle is the MAGNITUDE question this seam raises for
  every one of the 33 registry entries at once: a +49 pct swing on one champion is either a real
  correction to a champion the engine was under-modelling, or evidence the every-AA attribution is
  too generous. Play Akshan and one other registered every-AA champion (Warwick / Gwen / Kog'Maw) and
  confirm the served list is not dominated by raw attack-speed once the flag is on. **Do NOT flip
  default-ON from this row alone** - the flag would arm all 33 entries simultaneously, and only 6 of
  them have ever been eyeballed. **Separately, this row does NOT close RM-42:** its ordering claim
  needs the second shot's on-hit APPLICATION + independent crit, which is a different build, and
  `test_rm42_ordering_claim_is_NOT_closed_by_this_slice` holds that open.

- **G2-46** RM-36 / RM-38 `apply_ad_axis_ability_damage` on the CARRY ranker (ENGINE 1.272.0,
  `rank.rank_items` + `/rank` + `core/daemon_slayer_client.rank_for`). Route exposure is SHIPPED and
  default-OFF; this row is the EYEBALL, and it is deliberately not a default-flip request. Headless
  is DONE and is not the question: Corki reorders with the seam armed (verified over HTTP after the
  :8860 bounce, head 3153/6672/3085/6692 -> 3153/6672/6692/3085), Caitlyn moves too, Ezreal is
  provably byte-identical because his only PHYSICAL row carries `ap_pct_sum` 200.0 and the term's
  AP-scaling exclusion drops it, and all six build-order tables are stamp-only. What headless CANNOT
  settle is whether the ON list reads SANE to a player on a caster-marksman: play Corki (and ideally
  Ezreal as the null control) and confirm the served build does not start recommending an ability
  item a marksman never actually buys. **The specific risk to look for** is the mixed time-base the
  term inherits from RM-98 - the ability rows are a WHOLE-GAME cast rate summed onto a COMBAT-WINDOW
  auto rate, sized at ~7x distortion per spell in `docs/specs/SPEC_rm98_cast_rate_time_base.md` - so
  an ON list that over-weights ability items is the EXPECTED failure, not a surprise. A default-ON
  flip stays blocked on RM-98 exactly as it does for the bruiser scorer; do not read this row as
  proposing one.

- **G2-43** RM-41 `exclude_off_axis_items` default-ON flip (ENGINE 1.240.0, `ds.burst`). The seam
  strips a burst candidate whose offense sits entirely on the champion's OFF damage axis. Headless
  is DONE and is not the question: pool 140 -> 88 on the seven-champion AP-assassin cohort, 6 of 7
  top-8 changes, Gunblade #11 -> #8 for Akali, Zed's top-8 byte-identical, Shaco a no-op, all 9
  build-order tables stamp-only. What headless CANNOT settle is whether the stripped rows were ever
  a recommendation a player would want offered: play an AP assassin (Akali / Katarina / Fizz) and an
  AD one (Zed / Talon) and confirm the served list reads sane with the flag ON - specifically that
  no legitimate hybrid or defensive buy disappeared. **Do NOT flip blind** - a strip is invisible in
  the UI (the item simply is not there), so a wrong exclusion cannot be caught by looking at what IS
  shown. SOURCE: agents/daemon_slayer/CHANGELOG.md 1.240.0 + ROADMAP RM-41.
- **G2-44** RM-35 clause 2 `exclude_off_axis_items` on the CARRY route default-ON flip (ENGINE
  1.247.0, `rank.rank_items` + `/rank`). Same seam and same gate as G2-43, now extended from
  `ds.burst` to the carry scorer. Headless is DONE: Miss Fortune Lich Bane #6 and Rabadon's #14
  stripped, hybrid Hextech Gunblade SURVIVES (#18 -> #16, so it is not a blanket AP strip), pool
  107 -> 71, Shaco (`champion_burst_axis` None) byte-identical with a non-empty AP-carrying OFF
  baseline. The payoff is already live and is NOT hypothetical: **Twitch is in the shipped
  `_CHAMPION_FIGHT_LENGTH` allow-map and his served carry top-8 contains Lich Bane at #7 today**
  (`delta_dps` 22.86 against `effective_score` 251.00). What headless cannot settle is the same
  question as G2-43 - play a crit ADC with a short fight_length mapped (Jhin / Jinx / Caitlyn /
  Twitch) and confirm no legitimate hybrid or defensive buy vanished from the served list. **Do NOT
  flip blind** - a strip is invisible in the UI. SOURCE: ROADMAP RM-35 + CHANGELOG 1.247.0.
- **G2-45** (filed R221 2026-07-28) `MinionsSpawning` live payload + the cannon-cadence table.
  R221 shipped the extract (`dashboard/_liveclient.py:387-402` -> `minion_spawn_events`) and the pure
  clock (`dashboard/_wave_timing.py`), both green against fixtures. TWO things fixtures cannot settle,
  and BOTH are one practice-tool game: **(1) the payload** - confirm the live `:2999` top-level
  `events.Events` stream actually carries `EventName == "MinionsSpawning"` with a numeric `EventTime`,
  and confirm it REPEATS per wave rather than firing once at first spawn. The name is documented at
  `dashboard/_state_cooldowns.py:18` and sits in the published Live Client event list, but RC has
  never read it, so nobody here has seen the real bytes. If it fires ONCE, `wave_number` and the
  derived interval are both wrong and the module needs a gameTime-projection fallback. **(2) the
  cadence table** - `_CANNON_CADENCE` in `dashboard/_wave_timing.py` is UNVALIDATED by construction:
  three prose sources disagree on the breakpoint (14:00 vs 15:00) and a 2025 change moved first-cannon
  arrival 2:05 -> 2:35. Watch one game to ~16:00, log every spawn time and which waves carried a
  cannon, and pin the real breakpoint. **Do NOT wire the panel before this row closes** - the
  consuming panel slice is deliberately deferred for exactly this reason. SOURCE: ROADMAP RM-124 F1.

---

## GATE 3 - ARAM MAYHEM (queue 2400, gameMode KIWI, RC MODE_ARAM)

Real comps + a real bench, no Match-V5. Also clears GATE 1 and any own-build GATE 2 row.
**Pick tabled champs when the bench offers them** (Rakan / KSante or Rell / a Cluster-A) - the
survivability flips below cannot roll otherwise.

### Champ-select

- **G3-01** (was A6) E7a bench-swap queue-drain eyeball (`64591d5f`): click a bench champ in a real
  ARAM champ-select and confirm the swap registers visibly faster.
- **G3-02** (was A10) KEYSTONE residual: operator visual reassurance of the rendered bench (data path
  proven; no capture pursued). SOURCE: ROADMAP.md:100.
- **G3-03** `[CS-SCENARIO]` (was C2) Comp-verdict VARIANT branch still unobserved (SWAP + STAY
  validated at LGS2; never surfaced in-game 2026-07-04). Soundness discharged headless (OQ22).

### In-game

- **G3-14** (filed 2026-08-12, B4-d / RM-189) **`hz_choice_shadow` records must carry a REAL
  `game_id` during a live game.** The plumbing is proven headless: `game_id` is threaded from
  `lcu_snapshot` through `shadow_log_precomputed_choices` into the record, and
  `tests/test_b4_shadow_match_id.py` pins the contract at that boundary. What CANNOT be proven
  without a game is that the value arrives non-null, because `lcu/snapshot_shape.py:431-439` only
  sets `state["game_id"]` while the gameflow phase is `GameStart` / `InProgress` - idle and
  champ-select ticks legitimately carry nothing, so a headless run cannot distinguish "correctly
  absent" from "silently never populated". **Do NOT close this by asserting the key EXISTS** - it
  always exists and is None by design; that is the mis-file trap this file exists to catch.
  **Action:** during any live ARAM Mayhem tick, `tail` the last row of `data/hz_choice_shadow.jsonl`
  and assert `game_id` is a non-empty numeric string and `game_run_id` equals it (rather than the
  `local-aram-<ts>` fallback). One row closes it. **Also worth one glance:** that every row of the
  SAME game shares one `game_run_id`, which is the property the post-game review (B4-e) depends on.
  Applies equally at GATE 2 / 4 / 5 - ARAM is simply the cheapest gate that reaches it.

- **G3-04** (was C3) DSP3 ARAM archetype-override (`prefer_aram_win_axis=True`) - **MIS-FILED, NOT
  VALIDATED. RE-FILE source: GATE 3; destination: headless CODE work, off the live-gated list.**
  SETTLED HEADLESS: the resolver works and the override table is exactly 6 entries deep - Zilean
  enchanter/mage/default -> mage/enchanter/aram_win, Shaco assassin/mage -> mage/assassin, Shyvana
  bruiser/tank -> mage/bruiser, KogMaw onhit/mage -> carry/onhit and Kayle onhit/mage -> carry/onhit
  all DIFFER; Taric tank/enchanter/default does not. **5 of 6.**
  **WHY NO GAME CAN CLOSE THIS: there is no coach-side consumption to verify.** All 13 production call
  sites of `get_archetype_for` pass the default `prefer_aram_win_axis=False` -
  `coach_integration/archetype_dispatch.py:250`, `coach_integration/enemy_stats.py:143`,
  `core/build_order_precompute.py:275`, `core/build_planner/kit_synergy.py:347,399`,
  `core/ds_antitank_hint.py:89`, `core/zoi_capability.py:138`, `dashboard/routes_archetype.py:52,90`,
  `dashboard/routes_ds_sweep.py:200`, `dashboard/routes_spike_curve.py:196`,
  `dashboard/routes_state.py:590,964`, `dashboard/_state_builder.py:589`. `True` is passed NOWHERE
  outside tests and one build script, so playing Zilean in a live ARAM would change nothing on screen.
  SECOND HAZARD, previously unflagged: **none of the 13 call sites is mode-gated**, so flipping the
  resolver default would apply the ARAM-win-anchored archetype in SR and Arena too (blast radius
  bounded to the 6 tabled champs, but NOT ARAM-scoped). This needs a call-site choice plus a mode gate,
  not the 1-line flip the row implied. **NO LIVE RESIDUAL until that code lands.**
- **G3-05** (was C5) RF1 bruiser survivability flip - **EYEBALL CLOSED 2026-07-18** (on top of the
  LIVE-VALIDATED 2026-06-18 Yasuo read; the row's own "further tabled rolls (Darius/Udyr) optional"
  residual is now discharged headless). MEASURED at `[3078,3053,3742]`, L13, mode=ARAM, top_n=200,
  **pool=111 exact**: Yasuo DIFFERS (ON floats `6665` Jak'Sho + `3091` Wit's End); **Darius DIFFERS**
  (`6631` Stridebreaker, `6333` Death's Dance, `4401` Force of Nature); **Udyr DIFFERS** (`6665`
  Jak'Sho, `3065` Spirit Visage, `3075` Thornmail); Sett / Illaoi / Aatrox / Garen / Olaf / Trundle
  byte-identical. The DIFFERS-vs-same partition is **INVARIANT across 4 depths** (`[]` pool=121,
  `[3068,3053]` pool=115, 5-deep pool=109) **and 3 levels** (L6 / L11 / L18), with the floated ids
  stable per champion at every depth. Chain is plumbed end-to-end, so the flip is a genuine 1-line
  caller default: `coaches/aram_coach.py:784` -> `coach_integration/archetype_dispatch.py:219,284` ->
  `core/daemon_slayer_client.py:403,442` -> `agents/daemon_slayer/server.py:850` ->
  `hybrid.rank_items_by_hybrid`.
  REMAINS (not a gate): the operator-gated default-ON flip + DS `:8860` restart, per FOUR RULES rule 2.
- **G3-06** (was C6) RF2 enchanter survivability flip - **EYEBALL CLOSED 2026-07-18.** MEASURED at
  `[3853,3504,6617]`, L13, **pool=8 exact**, and all three of the row's own predictions reproduce
  INCLUDING the negative: **Rakan DIFFERS** - ON floats `2051` Guardian's Horn + `3083` Warmog's Armor
  + `3084` Heartsteel (the row predicted Warmog's/Heartsteel); **Soraka / Janna / Lulu / Nami / Karma
  byte-identical** (the row predicted Soraka/Janna). Depth attack at `[]` (pool=10) returns the
  identical partition and identical floated ids. The row's SIBLING-FUTURE negative also reproduces:
  `3121` Fimbulwinter is NOT surfaced on the hps lane, and the row itself scopes that `inject_ids`
  work as a headless slice, not a gate.
  REMAINS (not a gate): the operator-gated default-ON flip + DS `:8860` restart, per FOUR RULES rule 2.
- **G3-07** (was C7) RF3+RF6 tank survivability flip - **EYEBALL CLOSED 2026-07-18, on the EMPTY-DEPTH
  run and ONLY on that run.** THE RUN THAT CLOSES THIS ROW: depth `[]`, **pool=121**, KSante ON top-6 =
  `['6662','3075','3143','3083','6665','2504']` - Iceborn Gauntlet 6662 **and** Thornmail 3075 - so the
  row's full "Thornmail/Iceborn" prediction holds. A first-filed run at depth `[3068,3075,3143]`, L13,
  pool=117 showed KSante floating 6662 to rank 1 and **Rell floating 3121 Fimbulwinter to rank 1** with
  Malphite / Ornn / Sion / Zac byte-identical - but that depth ALREADY OWNS Thornmail 3075, which made
  3075 structurally unrankable and left half the row's own prediction unobservable. **That first
  evidence was INSUFFICIENT as filed and must not be cited alone.** RF6 rides the SAME flip as RF3.
  REMAINS (not a gate): the operator-gated default-ON flip + DS `:8860` restart, per FOUR RULES rule 2.
- **G3-08** (was C8) F2 `cost_ceiling` flip - **PREMISE DEAD 2026-07-18: re-file as
  CLOSED-STALE-PREMISE, explicitly NOT as a validated flip.** SETTLED HEADLESS, and stronger than the
  row assumed: 223069 Void Immolation is 6000g with `maps {'11':False,'12':True,'21':False,'22':False,
  '30':True}` and `purchasable: True`, yet `only_item_ids=[223069]` returns **0 rows in ARAM on both
  the hybrid and the ehp scorer**. THE CONTROL THAT MAKES THAT DECISIVE: the identical probe at
  `mode="ARENA"` returns **1 row** on both scorers, so the 0 is a mode-specific exclusion and not a
  probe artifact. **ROOT CAUSE (the part the row never had):** `agents/daemon_slayer/rank.py:196`
  hard-denies the id BY NAME inside the DDragon-override deny set at `:190` - DDragon's
  `maps["12"]=True` on this item is a known-wrong flag and the item is Arena map-30 only. The exclusion
  this row wants was deliberately shipped 2026-07-07. The ARAM pool tops out at 3500g (Rabadon's 3089 /
  Infinity Edge 3031) and the ceiling sweep is 1000 -> 15, 2500 -> 33, 3500 -> 121, 99999 -> 121.
  **There is no ARAM mega-item**, so there is no ARAM mega-item context for the eyeball to want.
  NO LIVE RESIDUAL. Do NOT ship F2 expecting an effect, and do not record this row as a validated flip.
- **G3-09** (was C9) T1-F3 enemy-pen-aware effective-resist EHP flip (opt-in
  `enemy_lethality`/`enemy_*_pen` on compute_ehp) - **RE-FILE source: GATE 3; destination: headless
  CODE task.** SETTLED HEADLESS: (1) the row's blocker was binary - "bots do not build pen items" - and
  it is DISCHARGED against real comps: **1560 of 2081 (75.0%)** of corpus ARAM matches with a timeline
  carry at least one participant holding a lethality / armor-pen item (Lord Dominik's 1063, Axiom Arc
  617, Serylda's 590, Mortal Reminder 455, Edge of Night 343). Corpus ARAM tops out at patch 15.9 vs
  engine 16.14.1, immaterial to a binary blocker. (2) The seam's SHAPE reproduces - physical EHP falls
  ~42% while the magical channel is unmoved (+0.0%): plain `compute_ehp` L11 physical 10463.7 -> 5999.9
  (-42.7%), L11 blended 6993.5 -> 4761.6 (-31.9%), L18 physical 15878.6 -> 9228.4 (-41.9%).
  **Absolute baselines are CALL-SHAPE dependent** - a first pass that did not state its call read ~30%
  higher - so always state the call shape when quoting a number here.
  **WHY NO GAME CAN CLOSE THIS: `enemy_lethality` is unreachable.** It appears ONLY in
  `agents/daemon_slayer/ehp.py` (:1143, :1283, :1714, :2103, :2107, :2208, :2271, :2283) - not in
  `server.py`, not in `core/daemon_slayer_client.py`, not in any coach, and NOT exposed over HTTP. A
  live ARAM exercises zero extra code. **NO LIVE RESIDUAL until the flag is plumbed.**
  SOURCE: BACKLOG.md:32.
- **G3-10** (was C10) R41 `assume_ally_detonation` (Leona P Sunlight) - **PARTIAL 2026-07-18.**
  SETTLED HEADLESS: the math is byte-exact and the scope is tiny. The override entry reproduces
  byte-for-byte - `AllyDetonationEntry(source_key='P', kind='FLAT_MAGIC', flat_lo=32.0, flat_hi=151.0,
  current_hp_coeff=0.0, cadence_s=2.5)`; burst at L13 on `[3068,3075]` mode=ARAM reads **708.41 ->
  763.51, +55.10, +7.8%**; and the level sweep is monotonic and consistent with the 32 -> 151 scaling
  (L1 +15.20, L6 +31.82, L13 +55.10, L18 +71.73). Scope is exactly ONE champion:
  `_CHAMPION_DETONATION_OVERRIDES` holds Leona alone, `_ITEM_DETONATION_OVERRIDES` and
  `_NONFIT_DETONATION_CANDIDATES` are both EMPTY, and Braum / Nautilus / Thresh / Sett are INERT under
  the flag. The 2.5s cadence is DATA, not an assumption, so it needs no eyeball.
  **TWO CORRECTIONS TO THE ROW:** (a) `assume_ally_detonation` has ZERO production callers outside the
  engine, so a live game exercises no extra code and the seam must be plumbed before any in-game read
  means anything; (b) the override note cites `champion_abilities.json 16.13.1` while the engine is at
  16.14.1 - re-anchor it.
  LIVE RESIDUAL (glance, telemetry-gated): playing with or against Leona, how often do allies ACTUALLY
  consume a Sunlight mark - is 0.5 about right, high, or low? The seam is linear in that single
  fraction, so it is the whole remaining calibration. DS restart.
- **G3-11** (was C11) cc_blended_ehp + cc_conditional ecosystem: the DATA-PATH half is validated live
  (DS /ehp cc_blended 5776 -> 2888 vs a real CC comp, 9 consumer surfaces grep-confirmed) but it is
  served only on the tank/bruiser scorer - a full close needs a **TANK/BRUISER PICK against a real CC
  comp**, or the cc panel wired into `/api/state`. SOURCE: LEDGER 769 + 779.
  PREP 2026-08-02 (lane 9, live ARAM Mayhem KIWI). The ideal comp condition OCCURRED live - Lee Sin
  (bruiser) vs a real CC comp `[Swain, Fizz, Miss Fortune, Anivia, Caitlyn]` (deterministic `fight_rule`
  even surfaced it: "Caitlyn 1.5s CC (W), Anivia 1.2s stun (Q)"). YET `/api/state` carried NO cc field
  (`tools/gated_live_probe.py` serving-surface scan = NONE). So the TANK/BRUISER-vs-CC-comp path alone is
  INERT: the engine computes cc_blended but no live surface serves it, which is exactly the SUBSTITUTION
  trap. This row can therefore be closed ONLY by wiring the cc panel into `/api/state` (headless code),
  NOT by playing the right game. Re-file consequence: the "TANK/BRUISER PICK" closing path is dead on its
  own; keep only the "wire the cc panel" path.
- **G3-12** (was C14) `RC_ARAM_STATE_DEBOUNCE` DEFAULT-ON flip validation. **DO NOT close on the OFF
  observation.** The coach refreshed coherently with the flag OFF twice (2026-07-04 6+ min; LEDGER 820
  2026-07-08 "debounce OFF, coach refreshes coherently") - the LEDGER 820 headline reads "C14
  live-verified" but its body records the OFF case only. The DEFAULT-ON flip is still un-validated. A
  replayed-game feed is an allowed alternative - try headless first. SOURCE: BACKLOG.md:64.
- **G3-13** (was C15+C16) Augment OCR rank-vs-pick + live on-screen render validation. The alias fix
  SHIPPED (`8fbff14e`, LEDGER 867). **The cadence defect behind it is now FIXED IN CODE (`66e6835e`,
  2026-07-29) and the RM-25 hold-an-augment-25s workaround is NO LONGER NEEDED** - a bounded fast
  vision poll runs during the Mayhem augment window (6.0s interval, capped at 6 extra scans, latched
  off once the augment is seen, gated on `is_mayhem` so plain ARAM pays zero). Worst case is +4 scans
  per game against a hard +6 ceiling. **THIS ROW STAYS OPEN**: the fix is unverified on screen, which
  is exactly the class an agent cannot self-adjudicate, so play one ARAM Mayhem game and confirm the
  reco actually renders during the ~10-15s panel. A wrong reco is worse than a dark one. Note the
  filed line cite `aram_coach.py:495` had DRIFTED - `_VISION_INTERVAL` was at 552 pre-fix. Memory
  `open_bug_aram_augment_reco_cadence_miss`.
  ~~PREP 2026-08-02 (lane 9). PRECONDITION: this validation needs a LIVE vision frame. Measured this
  session `:8889/latest-frame` = 0 bytes ... a dead frame makes this row unobservable.~~
  **THAT PRECONDITION IS STRUCK 2026-08-02 - IT WAS A PROBE BUG, NOT A DEAD RELAY, AND IT BLOCKED THIS
  ROW FOR NOTHING.** `tools/gated_live_probe.py` had `_RELAY_BASE = "https://127.0.0.1:8889"`, but the
  vision server is plain **HTTP** (`modes/shared_vision.py:25`) and every relay endpoint is gated on an
  `X-RC-Token` header (`_capture_screen`), which the probe never sent. So it could only ever report
  `frame_bytes=0` / `frame_dead=True`, on a perfectly healthy relay. **Measured side by side during a
  live ARAM Mayhem game:** the probe's own method returned 0 bytes while an authenticated HTTP GET to
  the SAME endpoint at the SAME moment returned a **243396-byte frame aged 0.9s**. FIXED (`_relay_token()`
  + correct scheme + token on both `_get_json` and `_get_nbytes`), pinned by
  `tests/test_gated_live_probe_relay_auth.py` (6 tests, all red first). Note `_RELAY_BASE` also feeds
  `/latest-liveclient`, so the tool's `relay_present` was wrong the same way - **re-read any earlier
  gated-row note that cited `frame_dead` or `relay_present`, they are suspect.**
  **The real open question for this row is elsewhere, and is NOT yet answered:** during a live Mayhem
  game (8+ min observed) NO augment key ever appeared on either surface - not `/api/state`
  (`augment_choices` / `augment_select` / `is_augment_select`) and not `data/aram_coaching_data.json`
  (whose `mayhem` key is a bare `true` boolean, not an augment payload). Separately, `/api/state`
  `screen_read` was **6.1 HOURS STALE** (frozen on an out-of-game read) while vision itself was live via
  `moon_proxy` every ~26s - so a frozen `screen_read` is a CANDIDATE blocker for the on-screen half and
  should be checked before blaming the `66e6835e` cadence fix. Do NOT close this row on the data half
  alone; the operator eyeball on the ~10-15s panel is still the acceptance.
- **G3-14** (was C17) R78 ARAM deterministic tail item_extra + objective Haiku->deterministic flip
  (`8f013ee4`): SHIPPED SHADOW-only. Needs ARAM shadow accrual + operator OK before flipping the ARAM
  coach tail off Haiku. SOURCE: docs/ORCHESTRATION_PLAN.md:296.
- **G3-15** ARAM re-checks of GATE 2 rows (no separate work, just look while you are here): G2-12 R49
  reflect ranking-vs-real-comp (the stricter read), G2-29 the ARAM flood-tint question, G2-38 PD->Kraken
  level-tick stability (ARAM-suitable, no enemy-comp dependency).

---

## GATE 4 - REAL MATCHMADE SR (draft; make it RANKED q420 to feed the rails)

The only gate that reaches Match-V5, real enemy runes, real allies, and a real ban phase. Playing ONE
of these clears every GATE 2 row plus this section. Make it ranked q420 so it also feeds G7-06 / G7-08
/ G7-09.

### Champ-select (real draft lobby)

- **G4-01** (was A9) Enemy/ban-dependent champ-select captures: OQ9 ban-reason labels (`1bf255ea`),
  cooldown-watch card (render-gated on committed enemies), UIX1 champ-select SR live capture
  (`3c123060`). SOURCE: LEDGER 726.

### `[BATCH DS-SEAM]` - real-enemy / real-ally seams (same restart discipline as GATE 2)

- **G4-02** (was B31) DSP5 summoner-spell plumb + eyeball: player's + ENEMY's live summoner sets into
  `dsp_live_consumers.summoner_fight_adjustments`; re-anchor wiki magnitudes at flip. Route WIRED
  (OQ18, POST `/summoner-fight-adj`) but **producer-orphan** - no caller POSTs a live summoner set, so
  this is a code+eyeball slice, not a pure flip.
- **G4-03** (was B32) DSP6 enemy-rune threat plumb: ENEMY's live rune set into
  `dsp_live_consumers.enemy_rune_threat` (PtA/Conqueror/Grasp shifts; no-threat lobby unchanged).
  **Practice tool has NO enemy rune sets.** Route WIRED (OQ18), producer-orphan.
- **G4-04** (was B33) DSP7 ally aura/enchanter plumb: live ally team into
  `dsp_live_consumers.ally_protected_ehp` (ally beside Janna/Lulu/Soraka shows higher EHP; solo ally
  unchanged). **Practice tool is solo.** Route WIRED (OQ18), producer-orphan.
- **G4-05** (was B34) DSP8 `target_preset` derived from the LIVE enemy comp into burst /
  `/rank-assassin` (lethality vs tank comp, magic pen vs high-CC comp). Route WIRED (OQ17); the live
  enemy-comp derivation into the body + the flip stay pending. DS restart.
- **G4-06** (was B35) R9 `assume_passive_flat_mitigation` - **PARTIAL 2026-07-18; the calibration data
  is ALREADY RECORDED, so this row now carries an ACTION ITEM, not a gate.** SETTLED HEADLESS from
  `timeline_events.victim_damage_json` (a promoted column carrying a per-instance fight clock - real
  sustained incoming pressure, already on disk). **THE FILTER IS LOAD-BEARING: CLASSIC ONLY** - the
  same query unfiltered returns 4735 deaths, of which ARAM alone is 3800. On CLASSIC, 620 deaths:
  **Amumu 162 deaths / median 14.0 instances / 94.4% at >=6 / mean 7.20 physical instances; Fizz 110 /
  11.0 / 95.5% / 6.05; Leona 348 / 17.0 / 98.0% / 9.22.** So `_ASSUMED_FLAT_DR_INSTANCES`=6 is
  conservative and well supported. **`_ASSUMED_ABILITY_RANK`=4
  (`_passive_flat_mitigation_overrides.py:99`, read at `idx = _ASSUMED_ABILITY_RANK - 1` on :234) is
  WRONG against a real endgame median of 5** - rank proxy: Amumu slot 3 median 5.0 level-ups, Leona
  slot 2 median 5.0. Nothing has been retuned yet.
  NO LIVE RESIDUAL ON THE DATA - this half never needed a client. What remains is headless code:
  retune `_ASSUMED_ABILITY_RANK` 4 -> 5, and flip the seam in the live survivability path.
- **G4-07** (was B36) R50 `apply_all_out_bonus` (K'Sante): confirm the empowered-mark value in an
  actual All Out fight + tune `conditional_probability` 0.5 vs real All-Out uptime. **NOT a pure HTTP
  flag-flip** - it is a load-time `AbilitiesSnapshot.load()` flag (`abilities.py:675`), so threading it
  needs per-request snapshot construction (separate FUTURE task). Only fires if K'Sante is played.
- **G4-08** (was B42) R59 `assume_lifeline_shield` - **CLOSED 2026-07-18; there is no live surface to
  eyeball.** MEASURED against a REAL enemy Lifeline holder: Yone genuinely held Immortal Shieldbow 6673
  in NA1_5557160206 (participants row, patch 16.9 q400). Modelling THAT Yone as the target
  (`compute_ehp` lvl18 on his actual build `[3031,3153,6673,3172,3036,2019]` -> hp 2405.00 / armor
  141.20 / mr 66.85), a Fizz burst `[3089,3157,3100,3137,4645,3102]` lvl18 reads **3330.26 -> 2630.26,
  delta -700.00 exactly**, and `target_lifeline_shield(level=18)` is 700.00 to the cent. Level lerp
  correct: -400.00 at lvl<=9, -700.00 at lvl18. **The target model is load-bearing** - without it the
  same call reads 4488.00 -> 3788.00, so always state the target when re-running.
  "ORDER STAYS SANE" IS PROVEN STRONGER THAN ANY EYEBALL COULD SHOW: `assume_lifeline_shield` is
  consumed by exactly TWO engine functions - `compute_burst_damage` (burst.py:525, applied :1319) and
  `compute_dps` (dps.py:700, applied :1469). NO ranking function accepts or forwards it
  (`rank_items_by_burst`, `rank_at_level`, `compute_rune_proc_damage` all lack the parameter), so the
  order is provably invariant ENGINE-WIDE, not merely at one entry point.
  Sterak's 3053 reading 0.00 at the default `target_bonus_hp=0` (1200.00 at 2000 bonus HP; Maw 3156
  200.00, 425.00 at 150 bonus AD) is DOCUMENTED INTENT per `_lifeline_target_shield.py` - Shieldbow is
  the conservative representative magnitude, as the row already says. Modelling limit, not a defect.
  REMAINS (not a gate): the operator-gated default-ON flip. SOURCE: LEDGER 743.
- **G4-09** (was B43) R60 `assume_hsp_amp` (wielder Heal/Shield Power) - **PARTIAL 2026-07-18, and
  CORPUS-CLOSABLE more strongly than first filed.** SETTLED HEADLESS on REAL builds, both halves the
  row names:
  (a) REGEN via `compute_sustain(..., assume_hsp_amp=)` - Soraka NA1_5381905994
  `[4638,3107,6617,3870,3158,6621]` sum_hsp 0.56, 0.0800 -> 0.1248 (ratio **1.56**); Alistar
  NA1_5216916028 sum_hsp 0.10, 0.073333 -> 0.080667 (ratio **1.10**). The row's "vamp-only sustain must
  stay unmoved" criterion HOLDS: Morgana NA1_5155555530 SPELLVAMP 0.720 -> 0.720 and a Briar vamp
  control 2.568 -> 2.568, both ratio 1.00.
  (b) SHIELD POOL - **strike the earlier "0 of 6660 real builds carry both" census; it is WRONG.** It
  counted only the 3 LIFELINE ids, but `shield_amp_mult` (ehp.py:1472-1479) multiplies the ENTIRE EHP
  shield pool and `ITEM_EFFECTS` carries **16** items with an `ItemShield`. Over the same 6660 SR
  participants: 403 carry HSP, 1199 carry a shield item, **14 carry BOTH**, all 14 move, and the shield
  CONTRIBUTION to `blended_ehp` scales by exactly `1 + sum_hsp` - Seraphine NA1_5157639891 **1.66**,
  Sona NA1_5082380576 **1.66**, Soraka NA1_5280258797 **1.40**, Taric NA1_5380671439 **1.08**. No
  constructed fixture is needed and none should be cited. The 3114 Forbidden Idol sub-ask is also
  satisfied: Soraka+3114 sum_hsp 0.64 -> ratio 1.64; Alistar+3114 0.08 -> 1.08.
  CAVEATS: the sibling shield seams (`assume_seraphs` / `fimbulwinter` / `chainlaced` / `kaenic` /
  `eclipse_shield`) must be ON to populate the pool at all and are themselves default-OFF and
  separately gated (G2-23); and these builds span patches 14.15-15.24 scored against a 16.14.1 engine.
  **NO LIVE RESIDUAL - the row never needed a client.** What remains is the operator-gated flip.
  SOURCE: LEDGER 745 + 831.
- **G4-10** (was B47c) R109 `apply_ability_hsp_amp` - item HSP amp of the CHAMPION-ABILITY heal/shield
  throughput in `compute_hps` (an enchanter's Ardent/Staff/Redemption/Moonstone/Mikael amped her ITEM
  heals but NOT her ABILITY heals - Soraka Q/W, Janna E, Lulu E; live-proven delta==0 on 8 enchanters,
  Soraka +6.65 HPS / ~6.3%). CALIBRATION FLAG (adversarial review): the amp reuses the item side's
  PRODUCT convention (`prod(1 + heal_shield_amp_pct)`) which diverges from real-League ADDITIVE HSP
  stacking and from the EHP path's additive `_hsp_amp.sum_wielder_hsp_pct` - a pre-existing item-side
  asymmetry, NOT a regression. **A two-HSP-item build is the calibration case.** SOURCE: LEDGER 857.
- **G4-11** `[NEW ROW 2026-07-18]` `[RE-FILED 2026-07-18]` R127 `apply_cdragon_resource_guard` (ENGINE
  1.213.0, LEDGER 901, `5f0c4a0d`, `abilities.py:677` default False - source-verified). **RE-FILE
  source: GATE 4; destination: ordinary non-gated CODE work. The live gate is discharged; the row is
  NOT closed.** SETTLED HEADLESS, every figure reproduced to the digit via
  `AbilitiesSnapshot.load(prefer_cdragon_ratios=True, apply_cdragon_resource_guard=True/False)` on Miss
  Fortune lvl16, real q420 16.13 build `[1053,3031,6697,6676,3036]`: R raw_damage_per_cast 231.844 ->
  4316.490 and R dps 1.6672 -> 31.0400, both **18.6186x**; total_ability_dps 29.9211 -> 59.2939,
  **1.9817x**. Full-roster sweep: **173 scored, 0 errors, exactly ONE champion moved** (MissFortune
  16.5584 -> 24.5954). **FIX THE ROW TEXT: the "~13x" in the old VALIDATE clause contradicted the
  "~17.7x" diagnosis (1050/60 = 17.5); measured is 18.62x, so the diagnosis was right and the ~13x was
  wrong.**
  **WHY IT IS NOT A CLOSE, and why a replay today would prove nothing: the FLIP does not exist.**
  `abilities.load_default()` (abilities.py:898) calls `AbilitiesSnapshot.load()` with NO arguments, and
  `apply_cdragon_resource_guard` appears in exactly two non-test places repo-wide - its definition
  (abilities.py:677) and its consumer (abilities.py:812). **ZERO production callers pass it**, so a
  live or replayed Miss Fortune game would show zero change. Second gap: "build reco unaffected for
  other champs" was measured as SCORE invariance (airtight for the 172 unmoved champions), but MF's own
  input moved 1.4854x and HER build reco was never diffed - diff it before flipping.
  **NO LIVE RESIDUAL. Do not schedule a game for this row.**

### In-game render / behavior (real combat pressure)

- **G4-12** (was B37) L4 capability-gap live validation - `RC_CAPGAP_SURFACE` is DEFAULT-ON in code
  since LEDGER 765 and the served `capability_gap` dict is live-verified on `/api/ds-preview`. The
  ONLY remaining gate is the in-game EYEBALL of the chip CONTENT vs a real enemy comp. SOURCE: RM-07.
- **G4-13** (was B38) RC2 P3.3/S0 pulse-rationing remaining eyeball: confirm the suppressed pulses
  were all benign re-emits AND the Emergency tier / one-shot Urgent cross still glows (lethal cues need
  real combat pressure - the item-598 capture verified only the suppression half).
- **G4-14** (was B39) RC2 P4.1-P4.5 composited-over-a-real-League-game eyeballs at 2560x1440
  borderless: DPI/dock sizing; opacity recede + idle dim + hover zones + drag strip; separated-window
  arrangement; `#ovset` panel selector + Interact-now; Re-arrange + Show dashboard. **P4.6 IS this
  whole-of-Phase-4 checklist.** Geometry halves are practice-acceptable; combat-driven cues want a real
  game. rc-shell MAIN relaunch (G6-01) first. Item 686 proved the 4.1 ovscale model live-buggy once.
- **G4-15** (was B40) Live UI watch STANDING ritual (items 243/244): tick champ-select + in-game
  dashboard vs `/api/state` each ranked game. **Standing per-game, never one-shot - it does not close.**
- **G4-16** `[BROADENED 2026-07-18 - was the R103 addendum, now the whole chip family]` Counter-hint
  chip in-game eyeball. The full situational counter-build program is CODE-COMPLETE and the live
  plumbing blocker is FIXED (LEDGER 916, `18fdf4d0`: `dashboard/_liveclient.py` now emits raw
  `allPlayers` + `activePlayer`, so `active_match.js:655 _hasRoster` is no longer always-false; before
  the fix the WHOLE program rendered only under `ui_mock` and was DARK in every live game). ONE game
  with enemies carrying the right items clears all five chips:

  | Chip | What must light | Ref |
  |---|---|---|
  | C2 antiheal | enemy sustain comp, ally dedup respected | LEDGER 908 |
  | C6 tenacity | enemy hard-CC roster | LEDGER 909 |
  | C3 fed-enemy | an enemy ahead on scores/level | LEDGER 914/915 |
  | C4 `hp_vs_pen` | enemy with Lord Dominik's + Serylda's -> HP chip | LEDGER 878 |
  | C5 `pen_type` | a tank kill-target -> ARMOR PEN / MAGIC PEN chip | LEDGER 878 |

  RM-02 states the remaining work is "the overlay chip in-game eyeball only". DS plan stays
  byte-identical (hints-only enrichment).
- **G4-17** (was the 2026-07-16 Slice B addendum) DS Slice B on-hit AP scorer OVERLAY RENDER eyeball -
  confirm the new `ds.onhit` build order (Nashor's Tooth present) actually renders on the in-game
  overlay build panel in a real **Gwen / Kayle / Kog'Maw** game. Backend + `/api/build-plan` already
  PROVEN live (scorer=onhit, Nashor's present; Syndra=ability / Akali=burst controls held). The
  Electron overlay is agent-blind, so this is operator-only. SOURCE: LEDGER 911, ENGINE 1.216.0.
- **G4-18** Jhin AS-lock full lethality eyeball (`c904ddae`) - the Boots of Swiftness half was
  live-confirmed; the lethality core eyeball remains.
- **G4-19** Overlay `liveclient_cache` self-heal live re-verify (`03868b03`).

### `[BATCH CV/OBS]` - needs rendered in-game pixels

- **G4-20** (was H1) OBS request/response POC (O1) + frame-source swap (O2): GetSourceScreenshot
  round-trip via OBS-WS v5, then swap the occlusion-proof WGC capture into `vision_server/_frame.py`
  (config-gated GDI fallback). O1 ~1 session, O2 ~1-2 sessions. SOURCE: docs/OBS_CV_MINIMAP_PLAN.md:54-70.
- **G4-21** (was H2) CV #7-10 new deterministic OCR/template modules: stateful ability-cooldown sweep
  tracker (cast-signal proxy), recall-channel bar read, objective (drake/baron/elder) icon+timer CV,
  item-completion template-match. Multi-session; each needs live calibration.
- **G4-22** (was H3) **THE UNSOLVED ZOI CORE.** Minimap champion IDENTITY via `cv2.matchTemplate`
  (Wave-2/3 over the blob centroids vs ~10 in-game champ templates): needs the opencv-python dep +
  live occlusion testing. Template-match hit only **1/13 on live ARAM = the clustering wall**. This is
  a multi-session BUILD, not an eyeball. Wave-2/3 depends on Zone-1 districts.
- **G4-23** (was H5) L-01 vision-base-capture live re-validation: the alt-tab base-clobber fix
  (`eece8500`, grab base only when League is foreground + once per config) was code-fixed + TDD-tested
  but NEVER re-validated in a live game (base was restored from a still, not re-grabbed clean in-game).
  Also the open auditor proposal to add a `validate_base()` guard to `routes_vision_calibrator.py`.
- **G4-24** (was H6) VISION-OCR box recalibration at 2560x1440 via `/vision-calibrator` against
  `data/vision_calib_reference/*.jpg`, then WIRE the native OCR crops. Native reference-capture is
  live-verified (LEDGER 793); the recalibration needs rendered in-game HUD pixels to validate the field
  reads. Pairs with G2-41.
- **G4-25** (was Z2) `[RE-SCOPED 2026-07-18]` ZOI macro callout (`kind="macro"`) + `zoi.mia` rings.
  **The stated CV-precision PREREQUISITE IS NOW DISCHARGED:** LEDGER 871 (B) / `b4ddedd1` added a
  champion-size floor + per-team clamp to `core/minimap_blob_detect.py`, measured 72->8 / 62->10 /
  74->10 on the saved SR corpus and LIVE-VERIFIED in a real Jhin ARAM (`minimap_dots=10` capped). The
  identity-dots default-ON flip is ALSO already live-verified (`1fd33854`, 2026-07-08, per RM-11). What
  actually remains: (a) per-CHAMPION identity, which is G4-22, and (b) wiring the macro/MIA feed
  through the existing `zoi=` / `districts=` seam - `vision_tracker` fog needs coordinate positions the
  Live Client does not give (roles only). Regression fence in place
  (`test_dead_fog_feed_never_fires_on_live_sr_shape`). Do NOT flip roster-wiring until (b) lands.

### `[BATCH POST-GAME]` - the 90s after a Match-V5-eligible game (GATE 4 ONLY)

Practice customs and Mayhem q2400 NEVER reach Match-V5. This batch is unreachable from any other gate.

- **G4-26** (was F3) PGR auto-show on game-end live confirm (`a2fdf448`): DID NOT FIRE 2026-07-04
  (companion was on the HOME view post-game; manual-open works). **Put the companion on the correct
  view BEFORE the game ends**, then recheck.
- **G4-27** (was F6) R47 PGR child-panel capture - UNCLEAR / likely moot (the entry itself says the
  baseline render is byte-identical, so there is no pixel delta to capture). **Operator call to
  discharge as a no-op.** SOURCE: LEDGER 702.
- **G4-28** (was F7) Home "Tonight's Pick" hardcoded dummy (`web/js/main.js:3080`,
  `dashboard/builders_home.py:148,105`): wire to real post-game `queue_id` ingest. DEFER until
  queue_id ingest ships; gated on real post-game Match-V5 rows.
- **G4-29** `[RE-FILED 2026-07-18]` (was F8) item-211 residual orphan-row Match-V5 recovery -
  **RE-FILE source: GATE 4; destination: OPERATOR-DECISION task. The row was MIS-GATED - no game and no
  new Match-V5 ingest is required.** SETTLED HEADLESS: the per-row champion list (the input the row said
  it was missing) is now in hand, and all 7 ids are present in `data/match_history.db` `matches` with
  `game_id = 0` confirming orphan status - **1487 ARAM Ezreal / 1506 SR Kai'Sa / 1517 ARAM Jinx / 1518
  ARAM Kai'Sa / 1519 ARAM Kalista / 1633 SR Jinx / 1640 ARAM Xayah**. TWO ARE ALREADY RESOLVABLE from
  the existing corpus, matched on champion AND mode AND duration: **1633** (SR Jinx, game_time_s
  923.35) -> NA1_5567585884 (CLASSIC q420 16.10, Jinx, 929s - 6s apart); **1506** (SR Kai'Sa, 2248.72)
  -> NA1_5567246791 (CLASSIC q420 16.10, Kaisa, 2262s - 14s apart). The other **5 are all ARAM** and per
  the settled event-mode Match-V5 403 finding are likely PERMANENTLY unrecoverable - recommend clearing
  them as junk.
  NO LIVE RESIDUAL. What remains is the operator's per-row call: run `--trust-lcu CHAMP + --match-id`
  for 1633 and 1506, clear the 5 ARAM rows as junk, then VERIFY the historical rows actually changed
  (Data Fixes rule - a fix is not done until the bad rows are backfilled). SOURCE: ROADMAP.md:81.

---

## GATE 5 - ARENA / CHERRY (queue 1750) - FLAG LOUDLY: every row here is Arena-only

**ARENA IS STILL NEEDED.** Nothing below can be reached from SR or ARAM.
**BEFORE PLAYING: restart RC-LCUAgent** (a separate ONLOGON process with no restart_trigger) so the
D6 force_scan-trigger fix (`8f651ca7`) + the round-based re-trigger (`9779296c`) are actually live:
`taskkill /F /PID <agent pid>` then `Start-ScheduledTask RC-LCUAgent`.

- **G5-01** (was D6) **THE ONE OPEN LIVE BUG.** Arena augment-select shadow
  (`data/augment_shadow.jsonl`) + item-anvil shadow (`data/anvil_shadow.jsonl`) seeding + WIRING-GAP
  re-validate. STATUS re-probed on disk 2026-07-18: `augment_shadow.jsonl` seeds at **966 bytes**
  (unchanged 2026-07-08 mtime); **`anvil_shadow.jsonl` is STILL ABSENT**; `git status data/` clean, so
  no headless probe has contaminated the ground-truth signal. Fix-committed, pending live re-validate -
  **do NOT mark closed.**
  NARROWED 2026-07-18 (diagnostic only - this closes NO part of the row): the shadow WRITERS are fine
  and are correctly reached from `arena_coach.py:596` `_handle_augment_select` and `:599`
  `_handle_anvil`. **The wiring gap is UPSTREAM, at `ArenaVisionReader.read()`.** So the live sit
  should watch whether the vision reader emits an anvil/augment event at all, not whether the writer
  fires.
  LIVE RESIDUAL (glance): in ONE Arena game take an augment and an item anvil, then check that
  `data/anvil_shadow.jsonl` now EXISTS and `augment_shadow.jsonl` has grown past 966 bytes.
  SOURCE: LEDGER 779/820; git `8f651ca7`, `9779296c`.
- **G5-02** (was D2) `set_augment_intent` 4-PATCH endpoint discovery at a real Arena augment phase.
  **PATH IS STALE:** `tools/gamepc_lcu_agent.py:1179` predates the Game-PC retirement - re-home the
  chain BEFORE running. Recipe: `docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md`. No Cherry augment session
  surfaced in `/api/state` 2026-07-04 (shares the G5-01 root cause). SOURCE: ROADMAP.md:113 / RM-24.
- **G5-03** (was D3) Arena boots 22xxxx mirror residual: augment-phase VISUAL confirm the pushed boot
  renders (icon may 404 per `reference_items_index_alias_ids`, display name correct). Data fix shipped
  (`f8353d5d`). STATUS: no boot anvil rolled in the 8 augment rounds played 2026-07-04.
- **G5-04** (was D9) R74/DSV8 `assume_physical_burst` (Goredrinker 226630 Thirsting Slash, 175% base
  AD physical AoE active) - **PREMISE REWRITTEN 2026-07-18: the blocker is NOT "no prismatic rolled",
  it is WIRING.** SETTLED HEADLESS: the engine math is exact and leak-free. The measured burst delta
  equals `1.75 * leveled_base_ad * 100/(100+armor)` to 3 decimals - Olaf L15 armor100 **114.052**
  (base_ad 130.3455), Aatrox L17 **121.275** (138.6000), Samira L15 **84.696** (96.7950) - with
  `physical_burst_base_ad_ratio=1.75` confirmed at `_effects_data.py:3589`, and a control of 6
  non-pinned Arena items x 2 champions **byte-IDENTICAL ON vs OFF** (zero leakage).
  **THE EYEBALL IS CURRENTLY IMPOSSIBLE.** `assume_physical_burst` has ZERO references in `core/`,
  `coach_integration/`, `modes/` or `web_dashboard.py`; `rank_for_primary_archetype` exposes 11 named
  seam flags and this is not among them; and `agents/daemon_slayer/server.py:1241` carries an explicit
  comment that the /rank route does NOT accept it. Only the direct `compute_burst_damage` route does.
  **So DS will show no Goredrinker burst credit on screen even if the prismatic rolls.**
  NO LIVE RESIDUAL until the flag is plumbed to /rank - re-file that wiring as headless code work, and
  do NOT spend an Arena sitting waiting for 226630 to roll for this row. DS restart on the eventual flip.
- **G5-05** (was D4) `apply_mode_modifiers` Arena re-rank validate - Arena ar/swift growth-addends are
  the only schedulable mode where this seam re-ranks (URF/OFA/USB/NB rotate). NOT attempted
  2026-07-04. DS restart.
- **G5-06** (was D5) `RC_ARENA_STATE_DEBOUNCE` default-ON flip validation. **TRY THE REPLAY
  ALTERNATIVE FIRST to dodge the Arena game entirely.** NOT attempted 2026-07-04.
- **G5-07** Arena deterministic A/B choices lever (`dc6b3d80`) - shipped SHADOW-only; served coach
  output unchanged. The live serve flip is gated on shadow accrual (G7-17).
- **G5-08** (was the B47b Arena tail) Celestial Opposition Arena mirror **444644 magnitude confirm**
  (Meraki 50% vs DDragon 90%) - the id is EXCLUDED from the R108 credit pending this live-Arena read.
- **G5-09** DS ranged-only Runaan's melee-gate made augment-aware for "Draw Your Sword" (augment id
  134, ranged->melee; `38b5e1eb`, LEDGER 856) - **PARTIAL 2026-07-18.** SETTLED HEADLESS: the gate is
  exact and does not over-filter. On **all 8** corpus champions that actually took augment 134
  (mode=ARENA, top_n=200) the pool loses exactly ONE item and gains none - Ezreal / Jhin / Akshan /
  Aphelios / Ashe / Samira **150 -> 149**, Graves / Neeko **183 -> 182**, `removed=['223085']`,
  `added=[]`. The LIVE chain is traced and genuinely wired (unlike G5-04):
  `_resolve_augment_apiname("Draw Your Sword")` -> `"DrawYourSword"` (281-entry map, case-insensitive)
  -> `arena_coach.py:448` -> `:682` -> `dispatch_for_coach` -> `rank_for_primary_archetype` ->
  `_champion_is_melee(champ_rec, augments)`.
  **NEW LIVE RISK, found 2026-07-18 - watch for it during the sit:** the gate accepts `134`, `"134"`,
  `"DrawYourSword"` and dicts, but NOT the DISPLAY form `"Draw Your Sword"` (which is vision's raw OCR
  form) - that reads melee=False. Correctness therefore depends entirely on `_resolve_augment_apiname`
  running first, and `_reconcile_augment_hud` (`arena_coach.py:989-995`) is **ALL-OR-NOTHING**: if any
  ONE HUD slot fails to resolve it returns and discards the whole read, so a single OCR miss on an
  UNRELATED augment silently prevents 134 from ever registering. No headless test covers
  OCR -> resolve -> all-or-nothing. The alternate population path `_handle_augment_select` is the
  G5-01 wiring gap.
  LIVE RESIDUAL (glance): take "Draw Your Sword" in a real Arena, then confirm on screen that Runaan's
  Hurricane 223085 has DROPPED out of the build panel. If it has not, suspect the augment HUD read
  first - one unrelated OCR miss is the likelier cause than the gate.
- **G5-10** `[HOLD 2026-06-20]` (was D8) Arena S2 augment level-up + crafting - trigger on the 26.09
  PBE (separate PBE install). ADR-010. NOT part of the current Arena sitting.

---

## GATE 6 - PHYSICAL / OPERATOR HARDWARE (over any running game on Legion)

Rides on top of whatever gate is already running. No separate game needed.

- **G6-01** (was E3) **rc-shell Electron MAIN relaunch - PREREQUISITE for every `[OVERLAY-*]` batch**
  (disappear-fix / pinned behavior + the P4.x window logic; the renderer half auto-reloads via ADR-008
  but MAIN does not). Plus the post-W5 interaction-layer live verify pass (the 2026-06-29 F1-01 confirm
  covered render surfaces only). SOURCE: ROADMAP.md:23; OVERLAY_BUILD_MASTER_PLAN.md:666/828.
- **G6-02** `[UPGRADED LIVE-ONLY -> PARTIAL 2026-07-18]` (was E5) item-598 R25 ACTIVE-knob interaction
  round-trip. **ROW DEFECT FIXED - as previously written this row would have produced a FALSE
  NEGATIVE.** The key is **Ctrl+Shift+A** (Win32 `tools/hotkey_listener.py` slot 3, the ONLY path that
  delivers while League holds foreground focus). **Alt+Shift+A is the alt-tabbed fallback ONLY and is
  expected NOT to fire in-game** (`rc-shell/src/main.js:1225-1229`; Ctrl+Shift+A is deliberately NOT
  registered in Electron at `:1193-1199` because globalShortcut does not deliver under League
  foreground). And there is **no re-rank** - `doToggleActive` (`main.js:1126-1130`) flips
  `overlayClickThrough`, calls `applyClickThrough()` and arms a 20s auto-revert; no ranking code is
  reachable from it.
  SETTLED HEADLESS - the DELIVERY half now has an in-game receipt. `logs/hotkey_listener.log` holds 687
  "overlay ACTIVE toggle signaled" entries; cross-joining ALL of them against RC's own logs gives
  **IN_GAME 9 / LOGGED_BUT_NO_GAME 0 / NO_LOG_COVERAGE 678**. The 9 land 22:31:09 -> 22:33:41 on
  2026-07-12, INSIDE a lifecycle-bracketed ARAM game (22:30:24.933 "New game detected" -> 22:52:51.140
  "Game ended"), and Electron MAIN was up mid-sequence (22:31:33 `GET
  /?overlay=1&panelset=build&ovscale=1.33` 200 - `ovscale` is MAIN-computed at `main.js:569-573`), so 7
  of the 9 should have reached `doToggleActive`. **An earlier "RC was not up at 22:33" reading was
  ROTATION BLINDNESS** - only the base `2026-07-12.log` was read, while `.log.2` covers 22:07-22:36 with
  8837 lines in the 22:3x window. Always glob `YYYY-MM-DD.log*`. (Physical origin is inferred, not
  proven: the hook logs `vkCode` only and never checks `LLKHF_INJECTED`, but the sole caller of
  `signal_overlay_active_toggle` repo-wide is `tools/hotkey_listener.py:359` and no repo code injects
  the chord.)
  LIVE RESIDUAL (glance) - three things disk cannot witness even in principle: with **League in the
  FOREGROUND** (the row's entire variable), press **Ctrl+Shift+A ONCE** and watch the overlay flip
  PASSIVE -> ACTIVE (edge glow on, body-drag enabled), then auto-revert after 20s. Note the 9 recorded
  presses came in bursts 0.5-2s apart, which reads equally as deliberate toggling or as mashing because
  nothing visibly happened - so ONE deliberate press with eyes on the overlay IS the test. Requires
  G6-01 (rc-shell MAIN up) FIRST. SOURCE: LEDGER 598; memory `reference_overlay_ingame_hotkey_win32`.
- **G6-03** (was E4) **CLOSED 2026-08-02 - PASS, but read the scope fence before citing it.** Live ARAM on
  Legion, real match end, OBS 32.1.2 / obs-websocket 5.7.3 driven entirely over `127.0.0.1:4455` (the
  scene JSON was never edited - it is stale since 2026-05-29 and OBS rewrites it on exit). **RECEIPT:**
  `StartRecord` 20:13:43 on game detect, `liveclient` dropped 20:37:13, recording HELD 92s past that and
  stopped 20:38:45, so the match-end transition sits INSIDE the file rather than at its edge. Output
  `C:\RC-Recordings\2026-08-02_15-13-40.mkv`, 6.35 GB, ffprobe parses clean: h264 2560x1440 @60 + AAC,
  duration 1504.767s. **ZERO capture stalls** - `outputDuration` advanced 10133-10167 ms on every one of
  140 ten-second polls, and there is not a single zero-delta sample during recording (the 16 zero rows
  are all pre-`StartRecord` waiting, verified by filtering on phase, not by eyeballing).
  **THE SCOPE FENCE, and it is the whole point:** League ran **Borderless at 2560x1440 on a 2560x1440
  desktop**, so **NO resolution swap occurred at match end**. Item-209b's actual failure mode - a bound
  DXGI grab across a 1920x1080 <-> 1440p swap - was therefore NEVER EXERCISED. This row proves
  continuous WGC display capture survives a match end AT A LOCKED RESOLUTION. It does NOT prove the
  original hazard is gone; in the current single-resolution config that hazard cannot occur at all. Do
  not cite G6-03 as clearance for a resolution-swapping setup.
  **Setup that made it runnable is RM-147** (ROADMAP.md): a SECOND `monitor_capture` source added
  disabled-by-default beside the existing `window_capture`, enabled for this match only and
  auto-disabled after, so OBS is back to its pre-G6-03 state. **Two traps measured here:** a freshly
  enabled `monitor_capture` renders a BLANK frame for the first few seconds, so a screenshot taken
  immediately after `SetSceneItemEnabled` reads as a dead source (994-byte uniform PNG) - settle ~3s
  before judging it; and all three `method` values (0 Auto / 1 DXGI / 2 WGC) render identically once
  settled, so a blank frame is never evidence about the method. SOURCE: ROADMAP.md RM-147; LEDGER 1170.
- **G6-04** (RM-145) **CLOSED 2026-08-02 - PASS, BOTH DIRECTIONS.** Live ARAM on Legion, rc-shell pid
  4140 (relaunched 11:26 on the fixed code, so G6-01 held). Overlay window confirmed present and
  visible BEFORE the flips by Win32 window enumeration (`Chrome_WidgetWin_1 vis=True 2560x1440 @ 0,0`;
  the 920x1281 companion was hidden), so the lazy-window gate was genuinely satisfied rather than
  assumed. Desktop metrics were read at every step, so the trigger provably reached Windows:
  ```
  14:00:11  ?overlay=1               desktop 2560x1440 -> 1920x1080   scale 1.33 -> 1.00
  14:00:18  ?overlay=1               settle 1.00
  14:00:50  ?overlay=1&ovscale=1.33  desktop 1920x1080 -> 2560x1440   RETURN LEG
  14:01:04  ?overlay=1&ovscale=1.33  settle 1.33
  ```
  The overlay WINDOW tracked with it: 2560x1440 -> 1920x1080 -> 2560x1440, `vis=True` throughout, so
  `reposition` and `reload` both fired and the HUD never wedged at a stale scale (the RM-145 symptom).
  Two method notes for any re-run: (1) **Borderless is not a trigger.** A first attempt changing the
  in-game resolution while staying Borderless left the desktop at 2560x1440, fired no
  `display-metrics-changed`, and produced ZERO reload lines - inconclusive, not a failure. The
  transition must change the DESKTOP resolution, i.e. exclusive Fullscreen. The return leg here came
  from EXITING fullscreen to Borderless 1080, which restores the desktop to native 1440 - same event.
  (2) A mode change emits a brief bounce (an intermediate reload at the old scale ~1s in); the handler
  followed it in both directions instead of latching, which is extra evidence, not noise. Read the
  SETTLED line, not the first one.
- **G6-04 (original row text, kept for the criterion correction it carries)** overlay follows a
  display-mode change in BOTH directions. The code half is done and tested headless (`resolveOverlayDisplayChange`
  + the `display-metrics-changed` / `display-added` / `display-removed` wiring, 13 tests incl. a
  mutation-checked wiring assertion). What disk cannot witness: the re-apply is gated on an overlay
  WINDOW existing, and that window is created lazily on first in-game show - so with no game up
  `applyOverlayDisplayMetrics` early-returns and a headless resolution flip proves nothing. This is a
  SUBSTITUTION trap of exactly the kind this file exists to refuse: "the pure function returns
  {reload:true}" is not "the HUD tracked the display". LIVE STEPS: requires **G6-01 (rc-shell MAIN
  relaunched on the new code)** FIRST, then with the overlay UP in a game, change the game's video
  mode (the operator's original trigger was the client flipping to 1920x1080), confirm the HUD
  re-lays onto the new resolution, then set it BACK to borderless 1440 and confirm it returns - the
  reverse direction is the half that was broken and the half a one-way check would miss. Evidence:
  the overlay's own request line in the RC access log carries the computed value
  (`GET /?overlay=1&panelset=...&ovscale=N`), so two entries with a DIFFERENT resolved scale around
  the two flips is the receipt.
  **READ THE ABSENT PARAM AS 1.0 - measured 2026-08-02, prep half.** `overlayUrl`
  (`rc-shell/src/overlay_state.js:171`) only appends `ovscale` when `|scale - 1| > 0.001`, and
  `createOverlayWindow` (`rc-shell/src/main.js:577`) resolves against `primary.bounds`, so the
  operator's exact trigger produces an ASYMMETRIC pair: 2560x1440 -> `ovscale=1.33`, 1920x1080 ->
  scale exactly 1.00 and **NO `ovscale` param at all**. A literal "two lines both carrying
  `ovscale=N`" check therefore FAILS on correct behavior. Expected receipt for this box is
  `...&panelset=X&ovscale=1.33` -> `...&panelset=X` (no ovscale) -> `...&panelset=X&ovscale=1.33`.
  Grep for it with `grep 'overlay=1' logs/YYYY-MM-DD.log` - the request trace logs at DEBUG under
  logger `rc.web_dashboard` and the file handler is always DEBUG, `/?overlay=1` is NOT in
  `_SUPPRESS_LOG_PATHS` (`dashboard/_handler.py:125`), and the line reads
  `HTTP "GET /?overlay=1... HTTP/1.1" 200 -` (note the quote - `grep "HTTP GET"` matches nothing).
  SOURCE: LEDGER 1166; ROADMAP.md RM-145.

---

## GATE 7 - ACCRUAL RAILS (ride EVERY session; NEVER close on one game)

Re-run the rail, read the gate, then decide. A single good game is not evidence here.
Rail tools: `tools/hz_shadow_report.py`, `tools/replay_build_order_validate.py`,
`tools/arena_shadow_report.py`, `tools/ocr_shadow_report.py`.

- **G7-01** (was G1) HZ Lane-A laning-agreement flip gate - **HOLD**. Re-run 2026-07-05: laning
  0.4709 (34048 comparable) / build 0.6598 (was 0.4626 / 0.6484 at the 2026-07-04 wrap - both trending
  up, both still BELOW the >=0.70 flip threshold; coverage 0.977 laning / 0.999 build). Rail: accrue
  real SR laning ticks -> `hz_shadow_report.py` -> operator OK. NOTE: the gate was de-biased twice
  since (LEDGER 844 drop macro/objective native ticks; LEDGER 854 dead-player exclusion), so re-run
  before quoting a number.
- **G7-02** (was G2) HZ Lane-B build-order flip gate - **HOLD.** **SETTLED HEADLESS 2026-07-18: the
  row's stated HEADLESS PREREQ is ALREADY MET and its caveat was wrong. No SR build-order table is at
  1.186.0.** Measured `engine_version` per table:
  `data/daemon_slayer/build_orders/16.11.1/build_orders_sr.json` 1.120.0, `16.12.1` 1.144.0, `16.13.1`
  1.214.0, and **`16.14.1` 1.219.0, generated 2026-07-18T18:34:20Z** - a table matching the live engine
  already exists. (Keyspace warning: there are two table families and the `data/daemon_slayer/<patch>/`
  family carries no `engine_version` key at all.) The prior 2026-07-04 read (+3.6%, flip_ready=False
  @665 matches) was taken against an older table and must NOT be quoted forward.
  RESIDUAL (accrual, never one game): re-run `replay_build_order_validate.py --limit 0` against the
  1.219.0 table for a fresh number, then keep re-running it as `rewind_history.db` grows. The rail
  decides.
- **G7-03** (was G3) Champ-select brief Haiku -> deterministic flip - **CLOSED 2026-07-18 as STALE.**
  The flip already shipped, so there is no live Haiku brief left to shadow and the row's "shadow-log
  accrual + operator OK" is moot. **EVIDENCE (CORRECTED - do NOT cite the grep):** an earlier pass
  claimed a grep for `haiku|anthropic|messages.create|call_claude` over the two files "returns ZERO
  hits". It actually returns **12 hits** (docstrings and comments in both files). The close rests
  instead on STRUCTURE, verified independently: `dashboard/_champ_select.py` `brief_via_coach()` is a
  single-line delegation to `brief_deterministic`, and `dashboard/_champ_select_deterministic.py`
  imports ONLY `json`, `logging`, `threading` and `dashboard._context.APP_DIR` - no anthropic client,
  no HTTP client, no API-key read anywhere in the module. Its own docstring records the shadow-validate
  lane as retired. Zero liveness residue.
- **G7-04** (was G4) ~88 `st-*` ADAPTATION live-producer census (rows render "-" in-game): note which
  surface live vs stay post-game-only. SOURCE: RM-30 / ROADMAP item 281.
- **G7-05** (was G5) RC2 P5.1/P5.2 CV laning: accrue `cv_override` rows in
  `data/hz_choice_shadow.jsonl` -> re-run hz_shadow_report WITH the CV layer -> set
  `RC_LANING_CV_SERVED=1` at >=70% agreement (tighten the ~8s stale-chip cache sig in the same flip
  slice if the eyeball shows lag). **CALIBRATION TARGET RETIRED - read `docs/adr/ADR-013` first
  (2026-08-06).** The >=70% number is agreement with the live Haiku laning VERDICT, and ADR-013
  retired that verdict as carrying zero mutual information (MI 0.00039 bits against 0.99987 bits of
  label entropy; bias-corrected MI negative). Agreeing with it 70% of the time measures nothing.
  The `RC_LANING_CV_SERVED` gate is a DIFFERENT predictor (live `compute_matchup` plus a CV
  override) and may still be worth flipping on its own terms - but it needs a new acceptance
  number, not this one.
- **G7-06** (was G6) DS calibration pipeline: needs **~20+ RANKED SR (queue 420)** games. Customs and
  Mayhem cannot feed it. SOURCE: RM-32.
- **G7-07** (was G7) `post_game_score` LR retrain at N>=20 real timelines (`core/post_game_score.py:220`).
- **G7-08** (was G8) hz_mismatch ground-truth cross-ref - **DENSITY MEASURED 2026-07-18; this is NOT a
  drain-session row.** SETTLED HEADLESS over `rewind_history.db`: **2,139 distinct
  (lane, champ, champ) matchups, of which only 62 (2.9%) reach n>=5 and just 4 reach n>=10. Median
  n=1.** That is exactly why most calibration classes read insufficient_data, and no realistic number
  of played games fixes it - the fix is ARCHETYPE POOLING, i.e. headless code, not accrual.
  RESIDUAL (accrual, background only): density rises slowly with every ranked q420 game. Re-read the
  three counts above before anyone proposes a per-matchup calibration again.
- **G7-09** (was G9) Draft-Elo pairwise WR corpus densification - **DENSITY MEASURED 2026-07-18; this
  is NOT a drain-session row.** SETTLED HEADLESS: **8,188 distinct cross-team champion pairs observed,
  covering 55.0% of the C(173,2) = 14,878 possible pairs, but EXACTLY ONE pair reaches n>=20.** Median
  n=1. Per-pair win rate is therefore not reachable by playing; it needs archetype pooling (same
  finding as G7-08), and it is the same reason G7-19 stays PARKED.
  RESIDUAL (accrual, background only): the corpus tightens as matchmade games accumulate. Re-read the
  n>=20 count before proposing any pairwise-WR consumer.
- **G7-10** (was G10) B1 `det_coach_shadow` / WS3 `objective_playbook_shadow` / WS4
  `macro_response_shadow` flip gates (rows accruing ~37.6K / 33.6K / 32.7K on 2026-07-01; the flip
  DECISIONS are pending). SOURCE: commits `ee70536a` / `2cdf64cb` / `aec17657`.
- **G7-11** (was G11) A3 tail: surface the DS-coach hints (anti-tank + scaling power-curve, SHADOW-only
  per item 328) only after `data/ds_coach_hints_shadow.jsonl` accrues + validates. SOURCE: RM-10.
- **G7-12** (was G12) ADR-007 phase 3 prose-coach deprecation - after phase-1 detectors prove out in
  real games. SOURCE: RM-31.
- **G7-13** (was G13) E2 umbrella: the DS 3-game live-flip pass (operator-played; rides the gate
  sessions above).
- **G7-14** (was G14) OQ1/R55 sustained-fraction calibration: replace the 0.5 design midpoint with a
  measured average-current-HP-over-fight. **lolmath baseline is IMPOSSIBLE - the site is parked
  (302 -> ww1.lolmath.com, connection refused)**, so this must be measured from RC's own corpus. The
  seam is linear in the fraction, so it is a single tunable.
- **G7-15** `[MERGED 2026-07-18 - was the B45/B46/B47 tails]` The two shared incoming-share midpoints.
  **All three engine flips are now default-ON and live** (`assume_item_crit_dr` ehp.py:1184,
  `assume_item_aa_dr` :1185, `assume_item_enemy_as_slow` :1190) - do NOT re-pitch any of those flips.
  **AA-SHARE HALF MEASURED HEADLESS 2026-07-18; CRIT-SHARE HALF UNTOUCHED.**
  `_ASSUMED_INCOMING_AA_SHARE`: measured from `timeline_events.victim_damage_json` (validated as damage
  RECEIVED - the killer appears among the source participantIds in 3,994 of 4,000 sampled events,
  99.85%; `type=OTHER` is champion-sourced, MINION / TOWER / MONSTER correctly excluded), on the
  PHYSICAL denominator the engine actually uses (ehp.py:512, :553, :607). **SR all-queues 0.3993 to
  0.4017** (13,577,662 of 33,797,855 over 36,952 events / 656 matches); ranked q420 only 0.3949.
  Mode-invariant (SR 0.4017 / ARAM 0.3976 / Arena 0.4104), so ONE global constant is right. The
  burst-bias worry is empirically dead - bucketing by damage-source count is FLAT (entries 01-05
  0.3908, 06-10 0.3961, 11-20 0.4070, 21+ 0.4034). Patch drift is mild and upward: p13 0.3716, p14
  0.3963, p15 0.4056, **p16 0.4178** - so **retune toward ~0.42, not 0.40**, if you weight the
  live-patch era. FRAMING NOTE that decides the retune: 0.5 is filed as a MIDPOINT but is not one - the
  population mean is ~0.40-0.42 and 0.5 sits near the **82nd percentile**; the genuine AA-heavy figure
  is the **p90 = 0.549**. Decide which the constant is meant to be before moving it.
  STILL OPEN: (1) **`_ASSUMED_INCOMING_CRIT_SHARE` 0.5 (R77/B45) was NOT measured at all** - that is
  the whole remaining measurement, and it wants a real crit-heavy comp. (2) The AA retune itself stays
  operator-gated under FOUR RULES rule 2: moving 0.5 -> 0.42 re-ranks EVERY build holding Steelcaps or
  Frozen Heart (R80/B46 + R86/B47 stack multiplicatively on a build holding both).
  SOURCE: LEDGER 799 + 809.
- **G7-16** `[HOLD]` (was G15) HZ-A v4 laning-table regen + shadow validation - blocked on a real ALIVE
  laning tick existing (zero today) + the 190MB monolith-vs-shard commit decision. SOURCE: BACKLOG.md:54.
- **G7-17** (was G17) R76 Arena deterministic-coach shadow flip gate - **RAIL RE-RUN 2026-07-18; FLIP
  CONTRAINDICATED.** **CORRECTION: the row's "the file is now ~952 KB, this rail may now be readable"
  growth inference was WRONG.** The file has NOT grown - `data/arena_coach_shadow.jsonl` is 952,382
  bytes / **463 non-blank lines**, mtime Jul 8 21:01, unchanged since LEDGER 820; it is simply ~2,057
  bytes per row. `tools/arena_shadow_report.py` re-run: **463 rows / 4 champs / 31 rounds; 358
  live-fight ticks + 105 dead-state; agreement 3/345 = 0.0087 on live-fight comparables** (Aphelios
  0/42, Caitlyn 0/62, Kai'Sa 1/184, Viktor 2/57), dominant mismatch **det=PLAY AGGRO vs haiku=CAMP
  PHASE x139**, flip-readiness reads `sample_met`. Sample is MET; **AGREEMENT is the blocker** - at
  0.9% the two coaches disagree structurally. Do NOT flip the arena coach tail.
  RESIDUAL (accrual): more real ARENA games into gitignored `data/arena_coach_shadow.jsonl` (writer
  `core/arena_coach_shadow.py`), then re-run the report. Treat the PLAY AGGRO vs CAMP PHASE
  disagreement as a deterministic-coach DEFECT to diagnose, not a threshold to wait out. Operator OK
  before any Haiku->deterministic flip.
- **G7-18** (was G18) ORUN5 grade-fold refinement (`assume_carry_share_grade` default-OFF at
  `core/post_game_rubric.py:410`, OR-gated with the existing carry_efficiency fold). Shipped headless
  byte-identical OFF (full-dict equality across 7 role/stat fixtures). The live default-ON flip = pass
  `assume_carry_share_grade=True` at the 3 callers (`routes_post_game_rubric.py:244`,
  `scripts/postmortem_analyze.py:395`, `core/precomputed_replay_narrative.py:434`). EYEBALL: a
  high-gold_share / high-KP carry game must show a **>= letter grade / total_score vs OFF (monotonic
  raise, never lower)**.
- **G7-19** `[PARKED]` (was G16) Aggregator N F2 per-slot item win-rate ladder - defer until a richer corpus
  exists. SOURCE: BACKLOG.md:15.

---

## GATE 8 - LEAGUE CLASSIC / JADE THROWBACK (RM-141) - the mode is not live yet

Filed 2026-08-02 by RM-141 S5. **RM-141 SHIPPED without a single live JADE game existing**, so every
assumption the build rests on is an EYEBALL owed against the first real one. None of these blocks any
other gate and none of them is a build - each can only CONFIRM or CORRECT what S1-S4 already assume,
and every one of them is cheap once a JADE queue is actually playable. If Riot never ships the queue
to NA, this whole section stays open forever and that is the honest state, not a defect.

The whole section drains in ONE game plus one lobby, in this order: G8-04 (lobby), then G8-01 / G8-03 /
G8-05 / G8-06 in the game itself. G8-02 needs a SECOND game (ARAM Mayhem Jade), if that crossover ever
exists.

**READY (headless 2026-08-02, no game up - lane 9 PREP pass).** Every CHECK field path below was
verified against source so the eventual in-game pass is copy-paste, not a mid-game re-derivation. Two
were DRIFTED at filing and are corrected inline: G8-03 (`activePlayer.championName` does not exist on
`/api/state` OR raw `:2999` - use `liveclient.champion` + `allPlayers[].rawChampionName`) and G8-04
(`queueId` is surfaced as `lcu.champ_select.queue_id`, and the mapped ids are `4300`-`4311` / `4320` /
`4321`). G8-01 (`liveclient.game_mode`, `_liveclient.py:264`), G8-05 and G8-06 anchors were all CONFIRMED
present. NO row is drained here - the mode is still not live; this only makes the paths correct.

**LIVE-CONFIRMED against a running client (ARAM/KIWI proxy, 2026-08-02T15:18Z, Lee Sin L8, game_time
6:06).** The corrected paths resolve live: `liveclient.game_mode`==`KIWI`, `liveclient.champion`==`Lee Sin`,
`allPlayers[0].championName`==`Swain` with `rawChampionName`==`game_character_displayname_Swain`, and
`activePlayer` carried ONLY `summonerName` / `riotIdGameName` - **NO `championName`** - which live-proves
the original G8-03 field path was dead, not just source-dead. This does NOT tick any G8 row: the
JADE-specific VALUES (`JADE`, `Jade_Ahri`) still need a real JADE game. NB the raw field is a
`game_character_displayname_<X>` form, so in JADE read BOTH `championName` and `rawChampionName` - a
`Jade_` prefix could land on either.

- **G8-01** `[JADE]` **gameMode string - HIGHEST-VALUE row in this section, and the one that can invalidate
  shipped code.** S2 added an EXACT-MATCH branch on `"JADE"` to `core/game_snapshot.py`, sourced from
  16 spell rows in `data/meta_build/ddragon/16.15.1/summoner.json` carrying `modes:["JADE"]`. That is
  DDragon evidence about spells, NOT a measurement of what the Live Client reports.
  **CHECK:** in a live JADE game, `curl -k http://127.0.0.1:2999/liveclientdata/allgamedata` (or read
  `liveclient.game_mode` off `curl -k https://127.0.0.1:8888/api/state`) and confirm `gameMode` reads
  **literally `JADE`**.
  **SAY IT PLAINLY: if it reads `CLASSIC` instead, the exact-match JADE branch shipped in S2 is DEAD
  CODE** - it can never fire, a JADE game would be coached as ordinary SR (which is not a wrong coach
  surface, just not a distinct one), and the row RE-SCOPES to queueId-based detection, which
  `core/game_snapshot.py` deliberately does not do (it is gameMode-STRING only, by design). That
  re-scope is a real design decision, not a patch: do not bolt queueId into the frozen file without
  its own row. A third outcome is possible and must be recorded verbatim rather than rounded off -
  anything that is neither `JADE` nor `CLASSIC`.
- **G8-02** `[JADE]` **KIWI_JADE string.** Same check inside an ARAM Mayhem Jade game, if that crossover
  exists live. S2 pinned `KIWI_JADE` to `MODE_ARAM` (not to JADE) because 151 of the 162 throwback
  items claim `maps["12"]` (Howling Abyss), so the ARAM coach surface is the correct one.
  **CHECK:** confirm `gameMode` reads `KIWI_JADE` and that RC coaches it as ARAM (`/api/state`
  `mode_key` == `aram`). This confirms the routing is EXERCISED rather than theoretical - today it is
  pinned only by a synthetic test.
- **G8-03** `[JADE]` **championName shape.** Does the Live Client report `"Ahri"` or `"Jade_Ahri"`?
  S1-S4 ASSUME the former throughout. **CHECK (field path corrected 2026-08-02):** the `activePlayer`
  block carries NO `championName` - neither on `/api/state` (`_liveclient.py:289-292` emits only
  `summonerName` / `riotIdGameName`) nor on raw `:2999` (RC must match `activePlayer.summonerName` into
  `allPlayers[]` to get it, `_liveclient.py:147-151`). So read the operator's champ off `/api/state`
  `liveclient.champion` (`_liveclient.py:186`) and the full roster off `liveclient.allPlayers[]`, taking
  BOTH `championName` and `rawChampionName` (`_lean_roster`, `_liveclient.py:87-100,288`).
  **`rawChampionName` is the field a `Jade_`-prefixed string would surface in** - `championName` may
  already be display-normalised, so it alone could hide the very drift this row exists to catch.
  If it reports `Jade_Ahri`, EVERY champion lookup in the SR coach path misses (DS registry, build
  order, rune page, matchup panel) and the row grows a normalisation layer. Record the exact strings;
  do not paraphrase them.
- **G8-04** `[JADE]` **queueId in a real JADE lobby.** S3 mapped the `kJade` PvP / VersusAI ids to the
  `jade` mode_key and deliberately left the three `kCustom` ids (3260 / 3261 / 3262) unmapped.
  **CHECK (field path corrected 2026-08-02):** in a JADE lobby, read the queue id off `/api/state` at
  `lcu.champ_select.queue_id` (champ-select, wins) or `lcu.lobby.queue_id` (lobby fallback) - the raw
  LCU key `queueId` is renamed snake_case at `dashboard/_state_builder.py:194-201` - and confirm it is
  one S3 maps: `4300`-`4311` (kJade PvP) or `4320` / `4321` (kJade VersusAI), per `core/queue_modes.py:97-117`.
  A `3260` / `3261` / `3262` means a JADE CUSTOM, which S3 left unmapped by design (`queue_modes.py:118-123`).
  Closes on ONE lobby - no game needed, which makes this the cheapest row here and the one to do first.
- **G8-05** `[JADE]` **map 453 geometry.** Unblocks `core/mode_capabilities.py`, where S2 set
  `has_wards: False` and `district_config: None` for JADE as a DELIBERATE fail-closed choice, not a
  placeholder. **CHECK:** with a JADE game up, eyeball the minimap rect against the SR one, confirm
  whether wards are legal in the mode at all, and judge whether the SR district grid is even
  approximately right on map 453. Also re-check the two `dashboard/_state_builder.py` gates that S1
  pinned `jade` OUT of. Any of the three answers coming back "yes, SR-like" is a follow-on row, not
  an edit made during the game.
- **G8-06** `[JADE]` **shop contents.** Does the JADE shop actually offer the throwback band items in
  `[770000, 780000)` (162 rows in the band, of which 151 are map-12-legal per G8-02;
  `agents/daemon_slayer/mode_variants.py:9,49`), or does it sell the ordinary SR pool? **CHECK:** open the shop in a live JADE
  game and eyeball the item pool against the current SR pool. This is the gate on the whole
  item-advice question (spec section 2.3 / follow-on F1): DS ingests NONE of the throwback registry
  today (Meraki 404s all 60 champion rows), so if the shop DOES serve the band, RC's item advice in
  JADE is advising on items the player cannot buy. Do not attempt an ingest off the back of this -
  it is BLOCKED-UPSTREAM, and this row only tells us how badly it matters.

---

## PARKED / HOLD - deliberately OFF the active checklist

Do not drain these. They are listed so nobody re-adds them.

- `[PARKED 2026-07-01]` ZOI per-champion minimap detection via color/size/motion isolation -
  live-confirmed DEAD END. Operator wants a FUTURE exploration only (sub-second frame-diff + portrait
  template-match combo; memory `project_zoi_minimap_reality`). Not scheduled. The native-res grab
  (`ac50f1af`) + the LEDGER 871 count-precision fix stay as the foundation.
- `[PARKED 2026-06-20]` Overlay App E-style enemy ult/ability CD timers (needs enemy cast-detection via vision).
- `[HOLD]` HZ-A choice-B even<->hold band flip (+57 ticks quantified; operator-gated, not applied).
- `[HOLD]` DS target-current-HP% / enemy-pen product-call flips - operator off-meta-chase decision
  first, THEN the G3-09 / G2-15 eyeballs.
- `[HOLD]` F.2 DS resist-seam survivability scorer (Anivia P egg-resist / Orianna E) + percent-of-resist
  mode - **SCHEMA-BLOCKED** (needs a schema lift before it can be built, then live-re-rank gated).
- `[PARKED]` OBS publisher - dormant until the operator streams.
- See also the `[HOLD]` / `[PARKED]` tags inline at G5-10, G7-16, G7-19.

---

## Not actually live-gated (validate headless) - kept OFF the checklist

This section exists specifically to keep non-gated work OFF the drain list. If an item can be proven
by fixture, harness, dev-preview, replay corpus, unit test, or synthetic liveclient, it belongs here.

- **ARAM augment-reco CADENCE fix (fast early-game poll) - SHIPPED HEADLESS 2026-07-29 (`66e6835e`).**
  Exactly as this section predicted: the fix was pure code and headless-testable (19 tests pinning the
  SCHEDULE, including a control asserting the coverage property FAILS on the old 25s cadence). Only the
  on-screen result remains gated, as G3-13. Two premises in the original filing were WRONG and are
  corrected there: Brawl has ZERO augment references so it never shared the mechanism, and Arena's
  augments are mid-game rounds {2, 5, 8, 11}, so a game-start clock ceiling does not apply to it.
- **R14 `apply_cc_floor` consumer-chain threading.** compute_ehp / compute_hybrid / the cc-blended-EHP
  surface do not thread the flag. Threading it (default-OFF preserved) is headless work; only the
  resulting eyeball (G2-06) is gated.
- Operator packaging: `npx electron-builder` + first GitHub Release + packaged update check -
  operator/release-gated, needs NO game.
- E10 / QA96 ASCII git-history rewrite + force-push (release-gated) + pre-release name-scrub -
  destructive operator go/no-go, NOT live-game-gated.
- D1 (OQ20 DISCHARGE 2026-07-02): Arena 6x3 champ-select covered headless (ui_mock fixture + snapshot
  test + `recon.py` harness); a live Arena capture is operator-optional.
- F5 (OQ20 DISCHARGE 2026-07-02): rewind `game_id` probe PASSED headless - the identifier is column
  `match_id` (there is NO separate `game_id`), 100 pct populated for queue 420 (516/516).
- DSV5 `RC_COMP_HP_LEAN` default-ON flip AUTHORIZATION: the live eyeball is DONE 2026-06-23 (R24,
  SANER NOT DIFFERENT); the remainder is ONE operator env / frozen-file decision - a non-game decision.
- Same-state Haiku-skip debounce default-ON flip (`RC_ARAM_STATE_DEBOUNCE` / `RC_ARENA_STATE_DEBOUNCE`):
  BACKLOG says "validate against a live/REPLAYED game", so the replay corpus satisfies it headless
  (G3-12 / G5-06 are the fallback only if the logs prove insufficient - OQ22 found the
  fired-calls-only replay PARTIAL).
- I3 loop stall-recovery + all pure-function loop-controller patches - Tier-1 unit tests.
- item-WPA / GPI radar / build-insights / perf-curve / WPA-lane views - static Legion-local dashboard
  views over the local corpus; a rendered-pixel eyeball is anytime, NOT game-gated.
- OQ13 `#home-weekly-digest` + OQ12 PGR bench sub-lines Electron-COMPANION captures: need rc-shell on
  the Legion desktop, NOT a game (companion is hidden in-game). Backends live-proven.
- Comp-verdict SOUNDNESS: OQ22 DISCHARGE 2026-07-02 - bug confirmed + FIXED headless
  (`core/aram_comp_verdict.py`), 3 TDD regression tests. Deterministic engine, not a live seam.
- champ_select pickban-DB flip: OQ22 CORPUS-TOO-THIN (660 SR-classic, median pair n=2.5); flip stays
  operator-gated.
- ability_hps v2 wiring: OQ22 SUBSTRATE-SOUND-DEFERRED - base ability-HPS already live; only the
  `assume_missing_hp_heal_amp` flag remains (= G2-04).
- UI scale v2.1 pages #11/12/13 + item 212(b) chooser-row captures: the ui_mock/recon.py fixture
  harness covers these.
- DS cross-eval A/B/F2 rewind-WIN validations (`ops/audit/ds_cross_eval/` harness over
  rewind_history.db; residual gate = operator decision).
- HZ-B build-order table regen to the live engine (deterministic `--static` path; byte-identical, no
  `:8860`) - the headless PREREQ for rail G7-02.
- R2 carry-efficiency grade fold default-ON re-baseline (computable over the existing corpus; operator
  decision).
- WP-F4a ward-stack keep-vs-retire (operator decision; Match-V5 carries NO ward positions so KEEP is
  likely infeasible; the retire path is fully headless).
- RF2-hps `inject_ids` sibling (future headless slice).
- Streaming vision (delta-encoded frames; transport-only, synthetic-frame testable headless).
- QA11 peripheral-timer meter + ring-gauge mockups: **SHIPPED** (OQ3 mockups LEDGER 720, operator
  picked variant A, shipped OQ16 LEDGER 730). Listed here only to stop it being re-added.

---

## Doc hygiene follow-ups - PROPOSALS, not edits made here

(a) Stale rows found in other docs (path:line):
- `docs/OVERLAY_BUILD_MASTER_PLAN.md:416` vs `:828` - F1-06 (Electron packaging + first GitHub Release)
  is "DEFER - operator/release trigger" at :416 but listed under the GATED-on-live-game verify set at
  :828; move it out of the live-game set (release-gated, NOT game-gated).
- `docs/OVERLAY_BUILD_MASTER_PLAN.md:817` vs `:823` - Section-J E5 doc-remediation sweep is OPEN while
  F6a (dep=E5) is marked DONE 2026-06-29; reconcile the E5 status.
- `Share/docs/05_AUDIT_AND_REFACTOR.md:20-21` - "7144 tests / 227 files" stale vs the live run at the
  current ENGINE (DS-batch docs job).
- Stale-hash citations to correct OUTSIDE append-only ledgers: item 508 build-order report `4623edd7`
  -> `7ee593d3`; QA4 chips `f570f527` -> `77f0e494`; HZ-B `--static` `917cbb89` -> `d528f6cb`; HZ-B
  regen `a5101e20` -> `559245a0`; E12 `109c80f0` -> `e9b1a5d0` + `48fcee51`; G4-boots `c258c4ab` ->
  `f8353d5d`; D7-hist "Kai'Sa id 6646" -> the real `tracked_champion_id` 145.
- `RC_WORK_TRACKER.md` rows resynced 2026-07-18 (see the tracker's own CLOSED section); the
  previously-flagged AWAITING/CLOSED misplacements are fixed in that pass.

(b) Archive candidates (operator-gated moves to `docs/_archive/`, links updated on move - grep each
path repo-wide before moving). 7 of the original 15 were executed [ARCHIVED 2026-07-09]. Remaining
(original numbering):
1. `tools/DISTRIBUTION_LAYOUT.md` (2026-04-26) - April distribution-era doc, superseded by ADR-011.
2. `tools/LAUNCH_STRATEGY.md` (2026-04-26) - superseded by supervisor + OPERATIONS.
3. `tools/PYTHON_BUNDLING_STRATEGY.md` (2026-04-26) - bundling decision long settled.
4. `tools/PEER_ROADMAP_SUGGESTIONS.md` (2026-05-18) - Peer bridge decommissioned 2026-06-24 (ADR-012).
5. `tools/done-peer.md` (2026-05-23) - dead Peer /done ritual mirror.
7. `tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md` (2026-05-25) - one-shot probe, complete.
13. `ops/audit/LOLMATH_VS_DS_SWEEP.md` (2026-06-15) - all-champ sweep at ENGINE 1.120.0 / patch
    16.12.1; stale (engine is now 1.219.0 / 16.14.1).
15. **[DONE 2026-07-18]** `ops/audit/ds_cross_eval/reports/` - 172 per-champion reports, program
    DONE 2026-06-16; archived to `docs/_archive/2026-07-18-ds-cross-eval-reports/` with
    PROGRAM/REPORT/SYSTEMIC_FINDINGS/TIER2_REPORT KEPT in place as specified. The 41
    `agents/agent6_auditor/reports/` files went to
    `docs/_archive/2026-07-18-agent6-auditor-reports/` in the same pass. The one live citation
    (`docs/specs/2026-07-16-ds-onhit-ap-combined-dps-scorer-design.md` -> `Kayle.md`) was
    repointed. STILL OPEN from this row: the
    `docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_*` cohort (2026-06-19). EXCLUDE
    `ops/audit/ds_perm_swarm/report/live_flip_eyeball.md` (ongoing).

---

## Live-flip ledger (loop appends; newest first)

- 2026-07-18 (SYNTHETIC TRIAGE - 6 rows CLOSED, 24 rewritten to their live residual; NO engine,
  flag or code change). Operator question: can the gated set be drained by "synthetic treatment",
  staging an agent team that builds per-champion ally/enemy context from recorded data and
  self-validates? Answered by a 14-agent pass - 7 triage agents (one per gate) then 7 ADVERSARIAL
  refuters instructed to default REFUTED. Corpus characterized first: data/rewind_history.db
  1.85 GB, 2961 matches, 30,562 participants, timeline_events 2,648,404 incl. 542,128 timestamped
  ITEM_PURCHASED plus 28,446 ITEM_UNDO (fold in event order; the undo target is raw_json beforeId,
  NOT the promoted item_id column), both teams, 643 usable SR matches -> 1286 team-comps.
  VERDICT: **6 of 124 close.** G2-07 anti-tank level ramp (pure fn of champion+level, never needed
  a client; Aatrox L3 0.4750 -> L16 0.8000, Senna 0.0772 -> 0.3353 4.34x, Darius/Vayne/Fiora FLAT
  controls held); G3-05 / G3-06 / G3-07 the RF1/RF2/RF3+RF6 ARAM survivability flips (G3-07 rests on
  the refuter's EMPTY-DEPTH run - the originally-filed depth already owned Thornmail 3075, which
  structurally masked half the row's own prediction, so that evidence is INSUFFICIENT and must not
  be cited alone); G4-08 R59 assume_lifeline_shield (stronger than an eyeball - the flag reaches no
  ranking function engine-wide, so "order stays sane" is PROVEN, not observed); G7-03 champ-select
  Haiku -> deterministic, closed STALE on structure (brief_via_coach is a one-line delegation to
  brief_deterministic; _champ_select_deterministic.py imports only json/logging/threading/APP_DIR).
  Refuter tallies CONFIRMED 15 / PARTIAL 24 / REFUTED 31. DOMINANT KILL = SUBSTITUTION: a gate row
  asks whether something RENDERS, SENDS or UPDATES; the compute half is always available headless
  and is always the wrong question. GATE 1 is structurally hostile to headless closure for exactly
  this reason and closed ZERO of 6; GATE 6 closed 0 of 3 as expected.
  TWO EVIDENCE DEFECTS CAUGHT BY THE REFUTERS, recorded so the pattern is recognizable: (1) evidence
  manufactured to fit - a claim citing three real match ids whose REAL builds give 0.00 pct, with the
  headline -48.09 pct requiring Runaan's hand-inserted onto a Darius; real match ids and real-looking
  decimals made it read as corpus-grounded. (2) sample range published as a bound - 3 of 880 builds
  measured and a ceiling published that full enumeration breaks by 2-4x, when the full enumeration
  was available in the same query already running.
  DO NOT RE-PITCH the synthetic drain expecting a different answer - the corpus is characterized and
  the residue is genuinely live. The pass's real yield is the 24 PARTIAL rewrites: each now states
  what is settled headless so the live half is a glance, not a session. Four partials (G3-04, G3-09,
  G4-11, G5-04) have NO live residual at all because the flag has zero production callers - playing
  the game changes nothing on screen. G6-02 was UPGRADED LIVE-ONLY -> PARTIAL on the triage's own
  stated criterion. G1-05 re-tagged BLOCKED, not closed. Header re-tallied 124 -> 118.

- 2026-07-18 (REORG, docs-only - NO engine / flag / code change) The checklist above was
  RESTRUCTURED BY GATE. Prior structure was A-H, half gate / half topic, which drained badly: section
  H mixed a PRACTICE-SR row (H4) with five REAL-SR rows; B and B-cont split one physical act (start a
  game) by whether real enemies matter; ~35 DS seam rows sharing ONE action (arm flags, restart :8860
  once, dump OFF-vs-ON) were scattered across B / C / D; and four competing "authoritative open set"
  statements (the 2026-07-12 DRAIN RESULT block, the 2026-07-12 DOC-ONLY RESYNC block, the R103
  addendum, the Slice B addendum) contradicted the 112-row body - the header claimed ~16 open while
  the body carried ~112. NEW structure: GATE 1 ANY-LOBBY / GATE 2 PRACTICE-SR / GATE 3 ARAM-MAYHEM /
  GATE 4 REAL-SR / GATE 5 ARENA / GATE 6 PHYSICAL / GATE 7 ACCRUAL, plus a GATE LATTICE stating the
  subsumption (GATE 4 clears GATE 2; ARAM and Arena are SIBLINGS of SR, not supersets; only GATE 4
  reaches Match-V5) and BATCH tags naming the single action that clears a run of rows. Every row keeps
  its OLD id as a "(was Bnn)" tag so LEDGER + memory citations stay greppable. Preserved untouched:
  this append-only ledger and the "Not actually live-gated" section.
  STRUCK AS RESOLVED (verified against LEDGER + git + engine source, NOT the doc's own prose):
  (1) B47 R86 Frozen Heart `assume_item_enemy_as_slow` - the default-ON FLIP SHIPPED (LEDGER 809,
  commit 8c5be61a, ENGINE 1.182.0 -> 1.183.0, live-proven Caitlyn tank-rank Frozen Heart #19 +1262
  EHP); source-verified `ehp.py:1190 assume_item_enemy_as_slow: bool = True`. Its only residue is the
  0.5 AA-share midpoint, already the B46 tail - merged into G7-15.
  (2) C12 antiheal POSITIVE-fire - fired live 2026-07-08 (LEDGER 820, heal_threat detected vs Yuumi
  Heal + Sion sustain in a real ARAM Mayhem game).
  (3) C1 build-chooser DATA/build half - LEDGER 820 confirmed the build LOGIC across another ARAM pick
  (BotRK for Jinx, correct on-hit ADC); the render half closed 2026-07-04.
  (4) Z2's stated CV-precision PREREQUISITE - DISCHARGED by LEDGER 871 (B) / 875d862b (champion-size
  floor + per-team clamp on core/minimap_blob_detect.py, 72->8 / 62->10 / 74->10, LIVE-VERIFIED in a
  real Jhin ARAM with minimap_dots=10 capped). Z2 is RE-SCOPED to the feed wiring (G4-25), not closed.
  (5) The ZOI "identity dots default-ON [fe37c534]" sub-item - already live-verified 2026-07-08 per
  ROADMAP RM-11.
  (6) A1 / A2 / A7 / A13 - closed rows finally dropped from the checklist body (history: LEDGER
  859 + 867).
  KEPT OPEN AGAINST A MISLEADING DONE-CLAIM: C14 (now G3-12). The LEDGER 820 headline reads "C14
  live-verified" but its body records only the flag-OFF observation ("debounce OFF, coach refreshes
  coherently") - identical to the 2026-07-04 read. The DEFAULT-ON flip is still un-validated.
  ADDED (shipped work carrying a live-gated obligation that had NO checklist row):
  (a) G2-23, a 12-flag item-side EHP/burst seam BATTERY - assume_kaenic_shield / assume_eclipse_shield
  / assume_seraphs_shield / assume_fimbulwinter_shield / assume_max_stacks_omnivamp / assume_item_revive
  / assume_item_stasis / apply_item_spell_shield / apply_item_mana_health / apply_item_resist_grants /
  apply_item_bonus_hp_amp / assume_item_lowhp_magic_crit. All twelve shipped default-OFF 2026-07-10 to
  2026-07-14 (R92 / R97 / R100 / R102 / R103 / R104 / R105 / R106 / R107 / R110 / R124 / R129) with the
  flip obligation recorded ONLY in this ledger. Defaults re-verified in agents/daemon_slayer/ehp.py on
  2026-07-18.
  (b) G4-11, R127 apply_cdragon_resource_guard (ENGINE 1.213.0, LEDGER 901, abilities.py:677).
  (c) G4-16, BROADENED from the C4/C5-only R103 addendum to the whole counter-hint chip family (C2
  antiheal + C6 tenacity + C3 fed + C4 hp_vs_pen + C5 pen_type). The live-plumbing blocker is FIXED
  (LEDGER 916, 318e7e3a) so all five now light from ONE game.
  (d) G2-27 / G2-28 / G2-32 / G2-33 / G2-34 / G2-35, the RM-05 + LEDGER 873 + LEDGER 914 overlay fixes
  that shipped 2026-07-17 and are OWED an operator Ctrl+Alt+A live-verify.
  RE-PROBED ON DISK 2026-07-18: data/anvil_shadow.jsonl is STILL ABSENT (G5-01 stays the one open live
  bug); data/augment_shadow.jsonl still 966 bytes; data/arena_coach_shadow.jsonl has grown to ~952 KB
  (G7-17 may now be readable - re-run tools/arena_shadow_report.py);
  coaches/aram_coach.py _VISION_INTERVAL was still 25.0 at that probe - SUPERSEDED 2026-07-29 by
  `66e6835e`, which adds the bounded fast poll; G3-13 now needs only the on-screen confirm.
  COUNT NOW = 124 rows = 105 one-shot (GATE 1-6) + 19 accrual (GATE 7); 9 carry a PARKED/HOLD tag and
  1 (G3-15) is a cross-reference adding no new work. Per gate: G1 6 / G2 42 / G3 15 / G4 29 / G5 10 /
  G6 3 / G7 19. The prior 112 / 109 / 108 / 95 tallies below are frozen append-only history
  (feedback_no_history_rewrite) - this line supersedes them. ARENA still NEEDED (G5-01..G5-09).
  NEXT: operator plays the gate sessions; the loop's next cycle flips the eyeballed seams default-ON.

- UNDATED (SYNC) full-repo gated-item resync #2 (11 living docs + repo sweep + git-closure audit +
  done-claim verdict pass + a live seam-flag ground-truth probe, folding in docs/LEDGER.md 799 =
  the newest ledger, 2026-07-06). REMOVED as confirmed-done this cycle: NONE net-new beyond the
  prior resync - the B45 R77 crit-DR + B46 R80 AA-DR ENGINE-default flips landed ON + live on :8860
  (LEDGER 799, 90a74972), so B45/B46 are RE-SCOPED (not removed) from "flip owed" to the practice /
  real-SR eyeball + 0.5 share-midpoint CALIBRATION tail ONLY. KEPT-OPEN partially-done: A1/A2/A13
  (regression re-validate owed), B5 (eyeball done, flip gated), B20 (accrual 3/3, flip
  un-eyeballed), C1/C11/C12/C13/C14 (data/render half only), D2/D3/D4/D5/D6/D9 (Arena), F3 (did not
  fire), the ZOI Z2 CV block. ADDED: B28-DS PD->Kraken cross-restart rank-stability eyeball (LEDGER
  799); C17 R78 ARAM det-tail Haiku flip (ORCHESTRATION_PLAN:296); E5 item-598 ACTIVE-knob press +
  E6 overlay live-recon punch-list (ROADMAP:21); F8 item-211 orphan-row Match-V5 recovery
  (ROADMAP:81); a whole NEW Section H (CV/OBS integration H1-H6: OBS POC+frame-swap, CV #7-10
  modules, minimap identity template-match, ZOI finalization eyeball, L-01 vision-base re-validate,
  VISION-OCR box recalibration - SOURCE docs/OBS_CV_MINIMAP_PLAN.md + ZOI_DISTRICT_ORCHESTRATION_PLAN
  + ROADMAP:15); G17 note that the arena_shadow_report tool is now BUILT (ORUN1 677f5237). SEAM
  GROUND-TRUTH refresh: recorded the NEW incumbent-hysteresis seam as wired_on_live (32132f22 /
  6f5c27a6) alongside DSP11 - the only two live-wired seams. Header now flags rank.py:686 (not the
  stale :632) as the exempt_offclass_by_win default site. OPEN NOW = 112 checklist rows (Z2 + A-H,
  excluding the superseded D7-hist line) = 94 one-shot (Z2 + A + B + C + D + E + F + H) + 18 accrual
  (G); of these ~9 carry a [PARKED]/[HOLD] tag (5 in PARKED/HOLD + D8 + G15 + G16 + Z2). The B45/B46
  0.5 share-midpoint calibrations ride the accrual tail on top of the 18 G rows. ARENA still NEEDED
  (D2/D3/D4/D5/D6/D9). The prior 108/86, 109/87, and 95/79+16 tallies below
  are frozen append-only history (feedback_no_history_rewrite) - this line supersedes them. NEXT:
  operator runs the 4-session drain plan above (practice SR -> real SR -> ARAM Mayhem -> Arena);
  the loop's next cycle flips the eyeballed seams default-ON.

- UNDATED (SYNC) full-repo gated-item resync (10 living docs + repo sweep + git-closure audit +
  done-claim verdict pass + seam-flag ground-truth probe). REMOVED as confirmed-done (verified live
  2026-07-04, LEDGER 779): B23 objective-gauge widget, B21 objective-state callouts, E1 ACTIVE-knob
  round-trip, E2 panel-cycle, B28 vision-region frames, F1 PGR @N timeline, F2 REPLAY1 freshness,
  F4 PGR UI-audit, D7 Arena Match-V5 ingest, B44 Guinsoo re-rank sanity, C4/DSP11 kit-axis seam
  (FLIPPED default-ON 523206d6) = 11 rows pruned. KEPT-OPEN with a status note (partially-done /
  advanced-only / still-open): B5 (eyeball DONE, flip still gated), B20 (accrual 3/3 but flip
  un-eyeballed), C1 (render half done, build/logic half open), C11/C12/C13/C14 (data-path/negative
  half only), A1/A2 (regression re-opened, layer-1+2 merged, re-validate owed), D6/D2/D3/D9/D4/D5,
  F3 (did not fire). ADDED: F7 Tonight's-Pick queue_id ingest (OVERLAY_BUILD_MASTER_PLAN:499),
  G18 ORUN5 grade-fold flip (ORCHESTRATION_PLAN:293), a schema-blocked F.2 Anivia/Orianna resist
  scorer HOLD row, plus the two caught live-bug re-validates folded into A1/A2 + D6; disambiguated
  the duplicate "B41" label (R75/DSV9 is now B41b). OPEN NOW = 95 checklist rows (A-G, excluding
  the superseded D7-hist line) = 79 one-shot (A-F) + 16 accrual (G); of these 9 carry a
  [PARKED]/[HOLD] tag (6 in the PARKED/HOLD section + D8 + G15 + G16). ARENA still NEEDED
  (D2/D3/D4/D5/D6/D9). The prior 108/86 and 109/87 tallies below are frozen append-only history
  (feedback_no_history_rewrite) - this line supersedes them. NEXT: operator runs the 4-session drain plan above (practice SR -> real SR -> ARAM Mayhem
  -> Arena); the loop's next cycle flips the eyeballed seams default-ON.


- 2026-07-02 (DRAIN SESSION, operator-played: practice-tool SR + ARAM Mayhem q2400 KIWI).
  DRAINED with live evidence: A1 PASS (RuneWriter lockfile-rotation reconnect after a mid-session
  League restart + rune push on the FIRST champ-select, log 21:16:04 reconnect to port 58494 ->
  21:17:35 wrote [RC: Kai'Sa SR]; the 27f99a95 fix proven live); A7 PASS (mode-correct push -
  PRACTICETOOL labeled SR, KIWI labeled ARAM, and E12-L2 re-detects on each ARAM bench-swap:
  [RC: Viego ARAM] -> [RC: Swain ARAM] -> [RC: Viego ARAM]); A6 (ARAM bench-swap fast re-push,
  sub-second); B21 PASS (objective_events fired - Fire drake @403.7s, Earth drake @722.2s);
  B22 PASS (inhib_events fired @702.2s + 6 turret_events); C13 (enemy_spells tap-tracker populated
  live - Gnar/Hwei/Lee/Annie/Ryze comp); B8/R7 eyeball (Irelia assume_passive_as_stacks /dps
  38.90 -> 47.96 = +23% at full stacks, reads SANER not random). KEYSTONE re-confirmed (q2400 +
  is_aram=True -> MODE_ARAM). NOT drained (future practice/SR sitting): A2 spell-push (NO push
  fired - Flash+Barrier stayed vs the sr_mode=teleport pref; still owed, matches the doc), A8
  panels (champ-select passed before a lock-capture), B1 build-chooser mid-game push (no log line),
  B23/B24 overlay pixel capture (frame endpoint 401/000 + game ended before grab), E1/E2 physical
  hotkeys, C2 comp_verdict (never surfaced in-game).
  FINDING 1 (real bug, fix built + code-gated, DS-batch DEFERRED to game-end): DS /rank recommends
  the RANGED-ONLY Runaan's Hurricane (3085) for MELEE champs - reproduced live on Irelia (#5, SR)
  and Viego (#8, ARAM). rank.py had no purchasability gate (the B1 apply_melee_aa_gate seam only
  zeroes the bolt DPS, default-OFF, never excludes the item). Root-cause fix built in worktree
  branch `worktree-agent-abebb195a5e02b357`: `RANGED_ONLY_ITEM_IDS={"3085","223085"}` (Runaan's +
  Arena alias ONLY - RFC 3094 / Statikk 3087 verified NOT restricted, kept melee-buildable) gated
  at the shared `_filter_candidates` chokepoint across all 7 ranker lanes; melee = attackrange<=250
  (fails CLOSED so a missing record never over-filters a real carry); 15 RED->GREEN tests; ruff
  clean; no frozen files; backfill correctly none (ephemeral live compute). PENDING at game-end:
  merge -> ENGINE 1.171.0 -> 1.172.0 -> HZ-B regen -> Share sync -> DS :8860 restart -> full dual
  suite -> live-verify Viego /rank excludes 3085 keeps 3087. (Deferred mid-game to avoid a coach
  blip + CPU contention with the live ARAM game - no mid-game DS bounce.)
  FINDING 2 (needs settled-state confirm, not yet filed): `cs_archetype_pick` looked STALE in ARAM
  champ-select - stuck on champion="Kalista" while the operator cycled Veigar->Viego->Swain via the
  bench (locked=234 Viego but pick still Kalista). Re-probe on a settled champ-select to confirm it
  is a refresh/staleness bug vs a fast-swap lag before root-causing.

- 2026-07-02 (PREP-AUDIT, no engine/flag/code change) live-gated-drain PREP ground-truth pass:
  orchestrated 4-slice read-only audit (route-verify / prep-status / doc-currency / phase-d-spec).
  VERDICT: the HEADLESS prep surface for the drain is FULLY EXHAUSTED (HEADLESS_ACTIONABLE_NOW = []).
  All 7 OQ17/OQ18 DS :8860 POST routes LIVE-VERIFIED WIRED-OK @ENGINE 1.171.0 via differential POST
  probes (handler file:line cited in the audit): /rank-assassin (DSV2/3/4 + DSP8 target_preset; an
  invalid preset -> HTTP 422 enumerating valid presets, a valid preset shifts target resists
  0/0 -> 22/30 and baseline_burst 186.0 -> 154.68), /burst (gate_target_hp_amp 200.88 -> 186.0,
  gate_caster_hp_amp 186.0 -> 202.74, score_completion_runes rune_proc 0 -> 5), /dps
  (apply_melee_aa_gate on melee Yasuo+Runaan 76.20 -> 39.56), /anti-tank (static 0.85 vs live-build
  0.89), and the 3 NEW OQ18 routes /summoner-fight-adj + /enemy-rune-threat + /ally-protected-ehp
  (all HTTP 200, non-zero + flag-responsive). Consequence: operator live eyeballs WILL fire - a
  failed eyeball now signals a real scorer bug, not a transport gap. Doc rows CURRENT + correctly
  tagged (B41/B42/B43 = R58/R59/R60 present with correct env tags; R61/R62 add no gated row; the
  OQ22 comp-verdict SOUNDNESS row already discharged). Phase-D B2 = DEFER-NEEDS-GAME (not a clean
  transport plumb - apply_passive_damage is deliberately /dps-scoped, the on_hit remainder needs
  net-new cadence math, assumed_stacks needs a live stack feed; own-build re-ranks are unverifiable
  headless). Tally refresh (APPEND only - the frozen 2026-07-01 SYNC headline of 108/86 stays
  immutable per feedback_no_history_rewrite): open NOW = 109 = 87 one-shot (+3 for B41/B42/B43) + 14
  accrual + 8 parked/HOLD. NEXT: the entire remaining drain is live-game / desktop - the operator
  plays the drain-plan sessions (practice SR -> real SR -> ARAM Mayhem -> Arena); the only off-game
  task left is the rc-shell E3 MAIN relaunch on the Legion desktop.

- 2026-07-02 R60 `assume_hsp_amp` shipped default-OFF (ENGINE 1.171.0, feat commit `d73e5fb5`):
  wielder Heal/Shield Power amp. `ehp.compute_ehp` folds `1 + summed_heal_shield_amp_pct` into the
  sibling `shield_amp_mult`, amplifying the wielder's OWN item self-shields (Sterak's / Shieldbow /
  Maw) alongside Spirit Visage; `sustain.compute_sustain` (+ optional `item_ids`) amps the REGEN-kind
  kit self-heal only (vamp is not HSP-affected -> vamp-only champ byte-identical even ON). NEW
  `_hsp_amp.sum_wielder_hsp_pct` sums HSP additively from `enchanter_items.json` (the hps.py source).
  Byte-identical OFF (verifier-proven omitted-vs-False equality; hsp_pct 0.0). Distinct from R59
  (target-side Lifeline shield; this is the WIELDER-side heal/shield stat). Flip gated as B43
  (REAL-SR HSP-item + self-shield / REGEN-kit re-rank eyeball).
- 2026-07-02 OQ20 de-book probes (docs-only; no engine / flag / code change): F5 + D1
  DISCHARGED without a game, moved to "Not actually live-gated". F5 = rewind_history.db
  `matches` queue_id=420 is 516 rows with `match_id` 100 pct populated (there is NO `game_id`
  column in the schema; `match_id` IS the game identifier); count == 516 baseline so no new
  ranked game since the row was authored, population COMPLETE - no post-game confirm needed.
  D1 = Arena 6x3 champ-select renders headless via `champ_select_arena.json` + snapshot test
  + committed screenshots + `ops/runtime/ui_recon/recon.py`; ROADMAP:18 VALIDATED, a live
  Arena capture is operator-optional only.
- 2026-07-02 R59 `assume_lifeline_shield` shipped default-OFF (ENGINE 1.170.0, feat commit
  `47d2f32a`): target-side Lifeline shield credit for the OFFENSE scorers - `compute_burst_damage`
  SUBTRACTS a modeled target's one-shot Shieldbow/Sterak/Maw shield from total_burst_damage
  (floored); `compute_dps` SURFACES the magnitude without touching the DPS rate. Reuses the
  Phase-1.5 `ItemShield.resolve_magnitude` (ehp.py already values the WIELDER side). Byte-identical
  OFF (verifier-proven omitted-vs-False equality, new fields 0.0). Flip gated as B42 (REAL-SR
  enemy-holds-Lifeline burst-scorer re-rank eyeball).
- 2026-07-02 R58 `assume_ms_utility` shipped default-OFF (ENGINE 1.167.0, commit `dbe4773e`):
  MS-utility DPS credit for the bruiser/juggernaut scorer (`compute_hybrid` +
  `rank_items_by_hybrid`, hybrid.py only; 1 pct bonus MS ~= 0.5 pct effective DPS, cap 0.15).
  Byte-identical OFF (omitted-vs-False full-dict equality pinned). Flip gated as B41
  (PRACTICE-SR own-build re-rank eyeball). Stack-ramp MS registry (Shipwrecker +20 flat /
  Steadfast +6 pct) is a follow-up seam feed, not yet resolved into stats["ms"].
- 2026-07-01 (SYNC) full-repo gated-item resync: header + play order + sections rebuilt from a
  9-doc read (WAKEUP / ORCHESTRATION_PLAN / LEDGER / ROADMAP / BACKLOG /
  OVERLAY_BUILD_MASTER_PLAN / ARCHITECTURE / OPERATIONS / RC_WORK_TRACKER) + repo sweep +
  git-closure audit + a seam-flag ground-truth probe (every DS seam confirmed default-OFF at
  its live call site; RC_COMP_HP_LEAN / RC_LANING_CV_SERVED cold). Items removed as done: the
  E.1 in-game overlay capture row (item 598), the PM7 Arena-boots DONE wrapper (real commit
  `f8353d5d`; the augment-phase visual residual kept as D3), the vision self-heal / item-276
  self-grab live validation (proven by live self_grab frames, LEDGER 685/688/711), and
  operator packaging (reclassified release-gated, headless list). Items added: ~78 tagged rows
  - the R5-R55 / DSP5-DSP8 / RF / F2 seam obligations promoted out of this ledger into section
  rows, the champ-select + overlay pixel-capture families, RC2 P3.3/P4.x eyeballs,
  physical-press rows, the post-game/Match-V5 set, and 16 accrual rails. DSV5's tripled flip
  obligation consolidated to ONE operator decision (headless list). The undefined LGS1
  "OPEN1/OPEN2" reference resolved as a stale label with no target. Count now open: 108 rows =
  86 one-shot active + 14 active accrual rails + 8 PARKED/HOLD; 16 items reclassified headless.
  Drain plan: 4 sessions (practice SR -> real SR -> ARAM Mayhem -> Arena). ARENA NEEDED: YES
  (D1-D7).

- 2026-07-01 (R53, LOOP) caster_hp gate seam for Last Stand 8299 - ENGINE 1.163.0 -> 1.164.0, DEFAULT-OFF,
  live default-ON flip EXCLUDED. `keystone_amp(..., gate_caster_hp=False)` +
  `compute_burst_damage(..., gate_caster_hp_amp=False, caster_current_hp_pct=1.0)`. Last Stand's amp scales
  with the CASTER's health (DDragon 16.13.1 longDesc verbatim: "Deal 5% - 11% increased damage to champions
  while you are below 60% health. Max damage gained at 30% health."; the item-232 `_last_stand_amp` ramp -
  1.0 at/above 0.60 caster HP -> 1.11 at/below 0.30 - is unchanged and already correct for 16.13.1). The
  burst scorer feeds Last Stand `caster_hp_pct` (live default 1.0 -> full HP -> NO amp), so Last Stand
  contributes NOTHING to the default burst total. R53 adds the seam: `gate_caster_hp_amp=True` routes Last
  Stand's amp to read `caster_current_hp_pct` instead, so a per-instant scenario eval credits the honest
  low-HP amp while Absolute Focus 8233 (gates on HIGH caster HP) keeps reading `caster_hp_pct` (the two
  caster-hp gates do not conflict). At the DEFAULT `gate_caster_hp_amp=False` Last Stand reads `caster_hp_pct`
  exactly as pre-R53 -> BYTE-IDENTICAL (no live consumer passes the flag; /rank / ds-preview / burst
  unchanged). `keystone_amp`'s `gate_caster_hp` is byte-identical parity plumbing (the 8299 ramp is
  single-sourced on `caster_hp_pct`). OWED (operator/Gemini-gated, NOT headless - charter 4b
  do-not-flip-blind): wire a per-instant scenario / fight_report consumer to pass `gate_caster_hp_amp=True`
  with the caster's real current-HP fraction (or a per-timestep HP band), then confirm the gated burst reads
  sane vs a real game. Gating a whole burst on a single caster-HP snapshot is a scenario/stepped-eval use,
  NOT a blind flip of the burst scorer. No DS math change on flip (seam already live); DS `:8860` needs no
  restart for the flip itself. Does NOT block any further stage.

- 2026-07-01 (R51, LOOP) target_hp gate seam for Cut Down 8017 / Coup de Grace 8014 - ENGINE 1.162.0 ->
  1.163.0, DEFAULT-OFF, live default-ON flip EXCLUDED. `keystone_amp(..., gate_target_hp=False)` +
  `compute_burst_damage(..., gate_target_hp_amp=False)`. Pre-R51 the burst-MAX scorer applied both Precision
  slot-4 amps (Cut Down >60% target HP, Coup de Grace <40% target HP) UNCONDITIONALLY - the burst-window
  approximation, since a burst spans the target HP range. R51 makes the gate HONESTLY expressible: with
  `gate_target_hp=True`, `keystone_amp` amps Cut Down only when `target_hp_pct` is strictly ABOVE 0.60 and Coup
  de Grace only when strictly BELOW 0.40 (verbatim DDragon 16.13.1 longDesc: "more than 60% health" / "less
  than 40% health"; magnitude 1.08 unchanged). At the DEFAULT `gate_target_hp=False` the gate block is skipped
  entirely -> BYTE-IDENTICAL to the pre-R51 unconditional approximation (no live consumer passes the flag, so
  /rank / ds-preview / burst are unchanged). OWED (operator/Gemini-gated, NOT headless - charter 4b
  do-not-flip-blind): wire a per-instant scenario / fight_report consumer to pass `gate_target_hp_amp=True` with
  a real `target_hp_pct` snapshot (or a per-timestep HP band) so the two runes credit only when the target is
  actually in-band, then confirm the gated burst reads sane vs a real game. Gating a whole burst on a single HP
  snapshot is LESS accurate than the unconditional window approximation for a full burst, so the honest use is
  a per-instant / stepped eval, NOT a blind flip of the burst scorer. No DS math change on flip (seam already
  live); DS `:8860` needs no restart for the flip itself. Does NOT block any further stage.

- 2026-07-01 (R50, LOOP) K'Sante P "All Out Bonus" bilinear caster-resist seam - ENGINE 1.161.0 -> 1.162.0,
  DEFAULT-OFF, live default-ON flip EXCLUDED. New registry `_ALL_OUT_BONUS_OVERRIDES` + new
  `AbilitiesSnapshot.load(apply_all_out_bonus=...)` flag inject a SECOND K'Sante-P synthetic damage block modeling
  the R-empowered All Out Bonus (verbatim 16.13.1: "1% (+ 1% per 100 bonus armor) (+ 1% per 100 bonus magic
  resistance) of the target's maximum health") as a linear 1% max-HP plus two `_per_100` bilinear terms
  (`caster_bonus_armor` x `target_max_hp` + the `caster_bonus_mr` sibling), gated by `conditional_probability` 0.5
  (documented amortized All-Out-uptime firing midpoint, operator-tunable). Default OFF is byte-identical (no live
  consumer passes the flag; the base item-255 mark-consume entry is untouched). OWED (operator/Gemini-gated, NOT
  headless - charter 4b do-not-flip-blind): (1) wire a live rank / dps / burst consumer to pass
  `apply_all_out_bonus=True` (ideally only while K'Sante's R "All Out" is active) and confirm his in-All-Out
  empowered-mark value reads sane vs a real game; (2) tune `conditional_probability` 0.5 against real All-Out uptime
  (or feed a live All-Out-state gate so the full in-form value is credited only during R). A WRONG precompute is
  worse than none, so do NOT default-ON until validated in an actual All Out fight. DS `:8860` restart on flip.
  Does NOT block any further stage.

- 2026-07-01 RuneWriter silent-after-League-restart PERMANENT FIX (`lcu/lcu_client.py`, frozen-grant).
  Operator live-flagged rune push dead on the last champ-select. Root cause: the long-lived RC (up since
  6-29) held a STALE lockfile port after League restarted (the lockfile rotates port+password each launch);
  `LcuClient` read the lockfile only once at connect() and never re-read, so get_champ_select() returned None
  forever and RuneWriter (shares the one _lcu) went silent - NOT the 2026-06-17 re-arm theory (that path was
  already fixed; the 6-29 log shows a clean Caitlyn write + re-arm). Immediate remediation: RC restart re-read
  the lockfile (fresh port 50237). PERMANENT: ported the RC-LCUAgent `ensure_lcu_conn()` resilience into
  `LcuClient` - mtime-guarded `_refresh_conn_if_changed()` on the 1 Hz auto-accept tick (heals every consumer
  sharing the instance) + reactive reconnect-and-retry-once in `_request` on a dead-port connection error.
  TDD: 6 new tests (`tests/test_lcu_client_lockfile_reconnect.py`) - rotate / no-op / gone + dead-port retry +
  no-infinite-retry + tick-calls-refresh; the 114 prior LCU/RuneWriter/spell/loadout tests stay green. Tier-1
  (LCU client logic; no ENGINE bump / Share sync / DS restart). Activation needs an RC restart to load the
  edited frozen module - DEFERRED past the operator's live ARAM (do not bounce RC mid-game).

- 2026-06-23 (item 598, R25) IN-GAME OVERLAY CAPTURE - E.1 cleared (validation + 1 durable test,
  NO live flip). Live SR game (champ Syndra AP mage vs a Braum/Gragas tank+CC comp); the rc-shell
  Electron overlay (PID 9736, title "RC . Syndra") ran over League. Playwright on the LIVE
  `https://legion-rc:8888/?overlay=1` (not a fixture, not 127.0.0.1 - the legion-rc origin so wss://
  is real), read off the REAL coach state: `body[data-shell]="overlay"`; `#right-now` `s0Cue="choices"`
  `s0Tier="urgent"` `s0Pulse="0"` (a SUSTAINED one-shot-urgent CHOICES cue did NOT arm a pulse ->
  producer-side motion rationing verified live, no over-fire); the CALL action row
  `data-call-band="fight"`, border-left-color rgb(200,170,110) gold 3px, verb color rgb(236,242,255)
  white, glyph U+25BA (item 591 band channel, live-faithful); eye-line widgets rn-lead / rn-choices
  (showed "A / Trade now / Braum lvl 18 / Alt+1") / rn-callouts (WARD UP green pill) / am-ward-cue /
  am-mmrect present+positioned, am-spike-cue + am-pane-ovds fight-model correctly hidden in the coach
  panelset, primary CALL font-size 22px. Only console error: favicon.ico 404 (benign). A Legion desktop
  screenshot caught the REAL Electron overlay compositing transparently over the live Rift (CALL
  "SETUP DRAKE FIGHT" gold bar + WARD UP + minimap-rect box float over the game with no opaque backing).
  DURABLE: new `tests/snapshot_panels/test_overlay_view.py::test_overlay_s0_pulse_rations_sustained_choices_via_producer`
  pins the DOM-PRODUCER s0-pulse path (the node PulseDecisionChainTests never import right_now.js; the
  manual-stamp consumer tests set the attribute by hand - neither exercised the live producer render).
  Screenshot is local-only (`tests/snapshot_panels/screenshots/` gitignored), NOT committed. STILL OWED:
  the ACTIVE knob-interaction (Alt+Shift+A re-rank) round-trip - the capture validated render+compositing,
  not a live knob press.

- 2026-06-23 RC_COMP_HP_LEAN (DSV5) LIVE EYEBALL DONE (R24; validation only, NO code change).
  The OWED AP-mage-vs-2+-tank eyeball (ledger 592) cleared on a real live SR game: me=Seraphine
  vs enemy Braum / Master Yi / Cho'Gath / Ziggs / Gragas. `compute_enemy_stats` classified
  `tanky_count=3` (Braum + Cho'Gath = tank, Master Yi = bruiser) -> `hp_scale` **1.20x**, applied
  `target_max_hp` 2980 -> 3576 (+596) at L18. RANKER OFF-vs-ON (`dispatch_for_coach`, top-6):
  (a) Seraphine routes to the **HPS / enchanter** scorer, so the seam is a NO-OP for her
  (enchanters do not build %max-HP DoT) - the LIVE coach champ was unaffected; (b) pure mages
  (Veigar / Heimerdinger, the ability-DPS scorer) - the seam boosts ONLY the genuine %max-HP DoT
  item **Liandry's Torment** (+6.5 dps L18 / +5.4 dps L11, ~+17%, proportional to the 1.20x
  max-HP) and leaves flat-magic items (Void Staff / Rabadon's / Shadowflame / Mejai's / Blackfire)
  byte-identical. VERDICT: **SANER NOT DIFFERENT confirmed** - the seam can only nudge Liandry's
  UP, never reorder toward a worse pick, so do-not-flip-blind (charter 4b) is SATISFIED. CAVEAT:
  the visible top-6 IMPACT is narrow - Liandry's is already rank-1 in the mage build at these
  levels, so the 1.20x widens an existing lead WITHOUT reordering the top-6; the seam only changes
  a served ranking in the borderline case where Liandry's is NOT already top, AND only for
  mage-scorer champs (enchanters / non-AP unaffected). RECOMMENDATION: flip is validated-SAFE, ON
  recommended - but NOT auto-flipped this session because the supervisor-env route is a FROZEN-file
  edit (`ops/rc_supervisor.py`) and defaulting a global coaching heuristic ON is a deliberate
  operator call. Method: probed the live `/api/state` comp + ran `compute_enemy_stats` /
  `dispatch_for_coach` OFF (`comp_hp_lean=False`) vs ON (`=True`) headlessly - no live-process
  disruption, no env change.

- 2026-06-22 DSV5 no-comp-info guard (ledger 593, `coach_integration/enemy_stats.py`) - a
  PREREQUISITE-to-flip SAFETY FIX, not a new seam. Verify-the-premise against the live SR comp
  (Jinx vs Lucian/Sion/Wukong/Pantheon/Soraka, tanky_count 3) exposed that `_comp_hp_scale`
  applied a blind **0.90** max_hp discount whenever `RC_COMP_HP_LEAN` was ON with NO
  `enemy_champions` (`1 + 0.10*(0 - 1)`), conflating "no comp data" with "all-squishy comp" and
  contradicting its own docstring. The champ-select / preview routes (`routes_state` ds-preview
  Path 3, `routes_ds_knobs`, `routes_ds_relscore`, `routes_ds_statcheck`) ALL call
  `compute_enemy_stats(mode, level)` with no comp, so a global default-ON flip would have silently
  de-rated every preview ranking by 10%. FIX: `_comp_hp_scale` now short-circuits to `(1.0, 0)`
  when there is no classifiable comp (None / `[]` / all-blank), so no-info is byte-identical to the
  flat curve when ON; a REAL all-squishy comp (>=1 classifiable champ, 0 tanky) still earns the
  intended 0.90 discount, and a tank comp still earns the uplift. This RESOLVES the preview-route
  safety blocker on the RC_COMP_HP_LEAN default-ON flip below. Tier-1 (NO ENGINE bump / Share sync /
  DS :8860 restart - coach-integration heuristic). RED-first +4 tests (the bug-shaped
  `test_no_comp_info_on_is_neutral` assertion corrected to 1.0 to match its own name + the docstring,
  plus blank-comp, no-info-vs-known-squishy contrast, and an env-ON-no-comp byte-identical guard);
  43/43 enemy-stats tests green. The default-ON FLIP itself stays operator-gated (gemini ruling:
  hold for a separate operator-run) - see the DSV5 entry below.

- 2026-06-22 DSV5 comp-conditioned enemy max-HP seam (ledger 592, `coach_integration/enemy_stats.py`).
  DEFAULT-OFF env gate **`RC_COMP_HP_LEAN`** (set `=1` in the RC runtime env; the read is per-call so no
  restart is needed - it is a coach-integration heuristic, NOT a DS `:8860` engine flip, so do NOT restart
  DS for it). When ON, a tank-heavy enemy comp scales `target_max_hp` up (1 + 0.10*(tanky_count - 1),
  clamped [0.85, 1.30]) so DSV1's ability-burn / %max-HP valuation tilts the live item ranking toward DoT
  (Liandry's/Blackfire/Demonic) vs tanks, matching the rewind WIN-anchored signal (winning AP carries vs
  2+ tanks build DoT over burst +12.0pt; burst usage halves). OFF == byte-identical flat curve.
  LIVE EYEBALL DONE 2026-06-23 (R24 - see ledger top; do NOT flip blind, charter 4b): in a real SR/ARAM game on an AP mage facing a 2+
  tank/bruiser comp, set `RC_COMP_HP_LEAN=1` and confirm the build-chooser top-6 re-rank elevates the
  %max-HP DoT items (Liandry's especially) vs the OFF ranking, and that it stays "saner not different"
  for a squishy comp (scale 0.90 should NOT swing picks materially). Inspect the applied modifier via the
  `core.coach_trace.record_enemy_target` plumb (`kind:enemy_target` records: base vs applied max_hp +
  hp_scale + tanky_count). Only after the eyeball checks out, authorize the default-ON flip (drop the gate
  or default `RC_COMP_HP_LEAN=1` in the supervisor env). NO ENGINE_VERSION bump / Share sync (engine
  untouched - the seam only changes the TARGET fed to the already-shipped DSV1 scorer).

- 2026-06-20 RC2 rc-shell standalone-app live session (code fixes shipped `cac1df3a` + `81f74d88`;
  runtime recovery). LIVE-VERIFY OWED (needs a live ARAM/any lobby): `lcu.lobby.members[]` must render
  in the rc-shell PRE-GAME LOBBY panel (YOUR MAINS / PARTY / MY TOP-8). The agent DOES forward members[]
  (`tools/lcu_agent.py:706-717`) but the operator saw empty members during a live lobby; could NOT
  reproduce after they left it (LCU phase=None). Next lobby: confirm the panels populate; if empty,
  capture the agent's live `/lol-lobby/v2/lobby` read + `_slim_lobby_member` output to find why members
  drop (suspect event-mode 2400 member shape OR the post-RC-restart stale-agent window). ALSO eyeball
  the overlay surface gate (`cac1df3a`): companion dashboard shows in the lobby/champ-select and flips to
  the lean HUD only once `liveclient` populates (a real game starts). Separately tracked (NOT live-gated,
  headless next session): agent restart-resilience - RC-LCUAgent/Hotkey/Relay must survive boot + auto-
  resync after an RC restart (the systemic root cause of the whole session's cascade). NOT a DS seam.

- 2026-06-20 RC2 E-batch E12-L2 + E7a (RC-side, NOT DS seams; shipped code-safe, no flip flag).
  E7a (`64591d5f`) tightens the RC-LCUAgent bench-swap queue-drain (fast 0.1s re-poll on a
  latency-sensitive cmd vs the 0.5s idle wait). LIVE EYEBALL OWED: in a real ARAM champ-select,
  click a bench champ and confirm the swap registers visibly faster - cannot be exercised offline
  (needs a live LCU champ-select with a populated bench). The RC-LCUAgent runs as an ONLOGON task
  with no restart_trigger, so a code refresh needs `taskkill /F` the agent pid + `Start-ScheduledTask
  RC-LCUAgent`. E12-L2 (`48fcee51`) memoizes RuneWriter's lobby gameMode per champ-select session.
  LIVE EYEBALL OWED: confirm RuneWriter still pushes the correct mode-appropriate runes/spells on
  champ-select enter (cache is per-session, cleared on `_reset_spell_state`) and a mode change across
  back-to-back champ-selects re-detects. Neither blocks any further stage.

- 2026-06-20 RC2 P5.2 CV served integration (COACHING, NOT a DS seam; shipped code-safe
  DEFAULT-OFF). 5.1 built the CV override + shadow column; 5.2 builds the SERVED-FLIP
  MECHANISM: `core.laning_cv_overrides.apply_cv_to_choices` maps a fired override onto the
  served A/B chips (`cv_choice_pair`: enemy DEAD -> "Shove + take plates/prio" high;
  MISSING >=3s -> "Back off + ward" mid; my HP <0.35 vs an aggressive verdict -> "Disengage"
  high; source_tag `cv-laning`; a trailing build `C` choice is preserved). Wired through
  `core.laning_verdicts.laning_choices(apply_cv=, hp_fraction=, vision_state=)` (default
  apply_cv=False -> byte-identical) and gated in `dashboard/_deterministic_coaching._compute_uncached`
  behind `_cv_served_enabled()` (env `RC_LANING_CV_SERVED`, DEFAULT-OFF). `_build_game_state`
  now stamps `gs["hp_fraction"]` (lc-first; additive, only the gated path reads it). OFF is
  byte-identical (the `laning_choices(gs, mode=upper)` call is unchanged). THE SERVED FLIP =
  `RC_LANING_CV_SERVED=1` in the RC runtime env (no restart for the env read on next RC
  start; the producer runs in-process). OWED (operator/Gemini-gated, NOT headless): (a) accrue
  real laning games so `data/hz_choice_shadow.jsonl` `cv_override` rows fill (5.1's shadow);
  (b) re-run `tools/hz_shadow_report.py` and read det-vs-Haiku agreement WITH the CV layer;
  (c) when agreement climbs toward the >=70% target, set
  `RC_LANING_CV_SERVED=1` to flip the served chips. **(c) IS RETIRED AS WRITTEN - see
  `docs/adr/ADR-013` (2026-08-06): the Haiku laning verdict it calibrates against carries zero
  mutual information, so agreement with it is not evidence. The gate itself is a different
  predictor and is unaffected; it needs a fresh acceptance number. **The `>=70%` figure is an
  author-set ASPIRATION with an origin but no derivation, and it is mis-cited.** Origin: commit
  `dea94516` (2026-06-19) wrote "(target: 39% -> >=70%)" into the RC2 coaching spec, now
  `docs/_archive/2026-07-28-research-consolidation/RC2_COACHING_SPEC.md:249`. That same line
  carries the `HZ_HAIKU_CALL_INVENTORY.md:75` citation, so the number and the citation were
  authored together and the citation has never supported the number - the cited bullet says only
  "confirm agreement climbs before any flip", with no threshold at all (the audit file is at
  `ops/audit/`, and carried no "70" anywhere until this correction was written). Nothing measures
  70, and nothing justifies it over 65 or 80.** KNOWN at flip time: the served `_CACHE`
  sig (`_cache_sig`) is intentionally UNCHANGED (off-path byte-identical), so a flipped-ON CV
  transition (enemy dies / my HP drops mid-bucket) can serve a stale chip for up to the 3.0s
  TTL + 5s game-time bucket - acceptable for a gated/eyeballed flip; tighten the sig (coarse
  low-HP bool + a cheap fog-freshness key) in the same flip slice if the live eyeball shows lag.
  Does NOT block any further stage.

- 2026-06-19 R7 per-stack self-AS passive (ENGINE 1.147.0): the per-stack champion self-Attack-Speed
  passive seam shipped DEFAULT-OFF on the AA DPS scorer. NEW `agents/daemon_slayer/_passive_as_overrides.py`
  registry (`PassiveAsEntry` per champion_id: per-stack bonus-AS FRACTION low/high by level + max_stacks +
  ap_per_stack_per_100) + `assume_passive_as_stacks` on `agents/daemon_slayer/dps.py compute_dps`; when ON,
  `passive_as_bonus(cid, level, ap, stack_fraction=_ASSUMED_PASSIVE_AS_STACK_FRACTION=1.0)` folds the
  champ's innate per-stack bonus AS at full stacks into the rotation AS (same 2.5 hard-cap re-clamp as the
  Yun Tal conditional-AS path; raw_attack_dps left at the no-conditional baseline). Seeded 4 from
  champion_abilities.json 16.12.1 effects_descriptions: Irelia Ionian Fervor (10%:25% by level/stack, max 4),
  Jax Relentless Assault (5%:12.5% by level/stack, max 8), Ezreal Rising Spell Force (10% flat/stack, max 5),
  Volibear The Relentless Storm ((5% + 4% per 100 AP)/stack, max 5 - the one AP-scaled passive, reads the
  resolved post-amp AP). A champion with no registered passive is byte-identical even with the flag on. No
  live scorer passes the flag yet (default False -> byte-identical). LIVE FLIP = wire the DPS / hybrid
  scorer-dispatch (`agents/daemon_slayer/server.py` the `compute_dps` call sites + `rank.py rank_items` /
  `core/daemon_slayer_client` wrappers - the same dispatch the B1 melee gate flips) to pass
  `assume_passive_as_stacks=True` for the 4 tabled champs (extend `core/archetype_picks` or the scorer call
  to thread the flag). Validate in a real game that Irelia/Jax/Ezreal/Volibear show a sanely higher
  auto-attack DPS / item ranking that favors AS-synergy items at full stacks, and a non-tabled champ
  (Caitlyn) + any operator pick are byte-identical. The assumed stack count
  (`_ASSUMED_PASSIVE_AS_STACK_FRACTION`) is operator-tunable; dial it below 1.0 if full-stack steady state
  over-credits a poke kit (Ezreal). Re-anchor the registry from the live patch's `champion_abilities.json`
  effects_descriptions each patch (re-scan for new per-stack self-AS passive lines). Needs a DS `:8860`
  restart on flip. Do NOT flip blind (charter 4b; CLAUDE-Settled "per-stack assumed_stacks").
- 2026-06-19 R5 missing-HP heal-amp (ENGINE 1.146.0): the missing-HP heal-AMPLIFICATION seam shipped
  DEFAULT-OFF on the ability-HPS scorer. NEW `assume_missing_hp_heal_amp` on
  `agents/daemon_slayer/ability_hps.py compute_ability_hps`; when ON, a `(champ, spell)` in
  `_MISSING_HP_HEAL_AMP` has its `heal_per_cast` multiplied by `1 + max_bonus * caster_missing_hp_pct`
  (Master Yi W Meditate / Lissandra R Frozen Tomb / Sylas W Kingslayer = 1.0; Briar P Crimson Curse =
  0.40). No live scorer passes the flag yet (default False -> byte-identical; full-HP / 0-missing also
  byte-identical). LIVE FLIP = wire the HPS/enchanter scorer-dispatch
  (`agents/daemon_slayer/server.py _route_rank_enchanter` -> `rank_items_by_hps`, and/or any coach
  surface calling `compute_ability_hps`) to pass `assume_missing_hp_heal_amp=True` AND feed the live
  caster's missing-HP fraction as `caster_missing_hp_pct`. Validate in a real game that a low-HP
  Sylas/Master Yi/Lissandra/Briar shows a sanely higher ability-heal throughput and a full-HP cast +
  any non-tabled champ are byte-identical. Re-anchor `_MISSING_HP_HEAL_AMP` from the live patch's
  `champion_abilities.json` effects_descriptions each patch (re-scan for new 0%:X%-based-on-missing-
  health heal lines). Needs a DS `:8860` restart on flip. Do NOT flip blind (charter 4b).
- 2026-06-18 PM7 Arena boots mirror (ENGINE 1.144.0): NOT a default-OFF seam - a DATA-correctness
  fix shipped LIVE (item 499). `core.build_order._select_boots` remaps Arena/CHERRY tier-2 boots to
  their `22`-prefixed map30-legal mirror; all 3 Arena build tables regenerated (boots-only). No flip
  pending (already live); the only live-OWED piece is the section-D visual confirm at an Arena augment
  phase. ALSO logged here: an operator ARAM Yasuo this run produced the first live RF1-tabled-bruiser
  eyeball - RF1 ON (hybrid `prefer_survivability_by_win`) floats Wit's End + Jak'Sho into Yasuo's top-6
  and drops Runaan's + Stormrazor = SANER, clearing the LGS2-open "RF1 needs a tabled champ to roll"
  gap. The RF1 default-ON flip itself stays operator-gated (section B; not flipped mid-game). NEW `cost_ceiling` param
  on the shared `_filter_candidates`, threaded through `rank_items`/`rank_items_by_ehp`/
  `rank_items_by_hybrid`; drops any candidate whose `gold.total` STRICTLY exceeds the ceiling. Live
  flip = pass `cost_ceiling=<N>` (e.g. 4000) at the build-chooser /rank-bruiser + /rank-tank call
  sites (section B), excluding the 6000g ARAM/Arena mega-item Void Immolation 223069 the
  `sort_by="delta"` absolute-gain surface floats to rank-1. Byte-identical OFF (reproduced live:
  Garen bruiser ARAM rank-1 = 223069). Validate the re-ranked ARAM/Arena bruiser+tank top-6 vs a
  real game before flipping (do-not-flip-blind).
- 2026-06-18 B1 (ENGINE 1.141.0): melee-applicability gate shipped DEFAULT-OFF (item 496, PM4). Live
  flip = `apply_melee_aa_gate=True` on the dps/hybrid scorer call sites (section B), zeroing a
  `PeriodicProc.ranged_only` proc (Runaan's Hurricane bolts) on a melee auto (attackrange <
  `MELEE_RANGE_CEILING`=350). Validate the re-rank vs a real melee ARAM game (Briar/XinZhao/Nilah)
  before flipping.
- 2026-06-17 LGS2 LIVE PLAY (no ENGINE bump - validation session, zero code change): operator ran
  6 ARAM Mayhem champ-selects (Olaf, Sivir, Senna->Mundo, Lissandra, Vex->Quinn, Caitlyn) under a
  persistent champ-select catcher (poll lcu.phase, emit on ChampSelect-enter; ARAM CS is too fast
  for a from-ReadyCheck poll) + per-champ `live_flip_eyeball.py` OFF-vs-ON re-rank.
  RESULTS:
  * DSP11 kit-axis = LIVE-VALIDATED both sub-cases + negative control -> FLIP-READY pending operator
    decision + DS :8860 restart. Senna (lethality) ON surfaces +Black Cleaver; Quinn (crit) ON
    surfaces +Infinity Edge(top)/The Collector/Statikk Shiv/Lord Dominik's; Caitlyn (the documented
    non-tabled control) shows ZERO DSP11 movement (byte-identical). Seam correctly scoped.
  * Comp-verdict (section C) renders correctly on SWAP (Senna->Lux HIGH, Lissandra->Hecarim MEDIUM,
    Vex->Garen MEDIUM) AND STAY (Caitlyn STAY LOW). VARIANT branch still unobserved. Bench-swap UI +
    build-chooser (3 variants + runes) + MAYHEM flag all render live; build reasons are comp-aware.
  * DSP3 / RF1 / RF2 / RF3+RF6 = no-op on every champ played (none tabled for those seams) ->
    byte-identical half re-confirmed; the TABLED half for RF1/RF2/RF3+RF6/DSP3 + the DSP11-manamune
    sub-case still needs a tabled champ to roll (RF1 bruiser / Rakan / KSante|Rell / Cluster-A /
    Ezreal|Corki).
  * DSP8/DSV3/DSV4 move saner per champ (theoretical - burst path, not the live ranker for most picks).
  OPEN FINDINGS:
  * SECTION A LCU PUSH = FAIL. RuneWriter (`lcu/lcu_rune_writer.py`) wrote runes ONLY on the first
    champ-select of the RC session (game1 Yuumi->Olaf 21:56); SILENT on every later champ-select
    despite RC detecting them (cs_pick updated). No crash/traceback -> champ-select re-detection does
    not re-arm after the first "champ select ended" (L451). Item-set + summoner-spell push share the
    CS-enter path = same suspect. Fix is post-session (needs RC restart), NOT frozen. See memory
    reference_runewriter_dies_after_game1.
  * Comp-verdict SOUNDNESS flag (low-confidence): Vex(AP)->Garen(AD) cited "all-AD comp - mix damage
    type", which reads inverted (swapping the only AP to AD removes the mix). Verify the ally-comp
    logic in `core/aram_comp_verdict.py`.
  CS2 spell push inconclusive (summoner_override=False every game; client default was already
  Flash+Mark, nothing to force). CC-pair UI not observed (no CC-pairing scenario rolled). HZ Lane-A/B
  accrued ~6 ARAM games to rewind_history.db (still HOLD - need corpus + rail clear).

- 2026-06-17 DSP5/6/7 CONSUMERS (ENGINE 1.140.0): the three DSP substrate seams now have a
  consumer layer - NEW `agents/daemon_slayer/dsp_live_consumers.py` (`summoner_fight_adjustments`
  / `enemy_rune_threat` / `ally_protected_ehp`). Previously a flag-flip did nothing (no scorer read
  the registries); now the seams are LIVE-TESTABLE - the remaining gated work is PLUMBING the real
  live-client summoner/rune/ally set INTO the consumer + eyeballing the adjusted readout (NOT
  building a consumer). Each is byte-identical on an EMPTY context. DSP7's `ally_protected_ehp` ALSO
  covers the item-321 ehp ally-resist producer (Orianna E / Braum W / Taric W via `ally_resist_grant`
  -> `external_resist_armor/mr`). +10 tests; DS 7334 / RC 8333 green; Share 364; DS :8860 restarted
  -> 1.140.0. NOT flipped (do-not-flip-blind).

- 2026-06-17 RF6 (ENGINE 1.139.0): tank-template survivability INJECT seam shipped DEFAULT-OFF -
  extends the RF3 ehp/tank float (no NEW scorer flag; the SAME `prefer_survivability_by_win` on
  `ehp.rank_items_by_ehp`). RF4 found RF3's float is a no-op for Rell: its sole tabled winner
  Fimbulwinter 3121 is the non-purchasable mana-line transform of Winter's Approach
  (`gold.purchasable`=False), so `_filter_candidates` drops it (RF4 `in_pool=False`) and the float has
  nothing to lift. NEW `inject_ids` force-admit param on `rank._filter_candidates` (bypasses the
  `only_ids` whitelist + `exclude_names` deny + `_is_purchasable` gate; still honors current /
  non-coachable / mode-legality / terminal / budget; `None` default = byte-identical for every caller);
  `rank_items_by_ehp` passes `inject_ids=surv_ids` only when the seam is ON. The LIVE flip is the SAME
  one tracked in section B above (wire `server.py` `rank_items_by_ehp` ~L557 / `rank_tank_for` to pass
  `prefer_survivability_by_win=True`) - flipping it now ALSO surfaces Rell's Fimbulwinter, not just
  KSante's already-pooled winners. NOT flipped (do-not-flip-blind); needs a real ARAM + a DS `:8860`
  restart. KNOWN SIBLING (FUTURE): RF2's hps `only_ids |= surv_ids` union likewise cannot surface
  Rakan's tabled 3121 (same purchasable gate) - the `inject_ids` mechanism now exists to fix it if a
  future RF wires the hps lane through it; not done here (RF2 is a DONE seam).
- 2026-06-17 RF2 (ENGINE 1.137.0): enchanter-template survivability item-credit seam shipped
  DEFAULT-OFF. NEW `prefer_survivability_by_win` on `hps.rank_items_by_hps` (the hps/enchanter scorer
  lane), driven by the WIN-anchored `agents/daemon_slayer/survivability_item_credit_enchanter.json`
  (1 champ / 4 items - Rakan: Guardian's Horn / Warmog's Armor / Heartsteel / Fimbulwinter). The flip
  wires `agents/daemon_slayer/server.py _route_rank_enchanter` (+/- the
  `core/daemon_slayer_client.rank_enchanter_for` wrapper) to pass `prefer_survivability_by_win=True`.
  KEY difference from RF1: the enchanter scorer's `enchanter_only` pool EXCLUDES HP/tank items entirely
  (zero HPS throughput) so the seam INJECTS the tabled ids into the pool BEFORE floating them (RF1's
  hybrid lane already pools them and only floats). NOT flipped (do-not-flip-blind) - validate the
  re-rank in a real ARAM (Rakan-as-tank-support surfaces Warmog's/Heartsteel; non-tabled Soraka/Janna
  byte-identical). Cluster A (Zilean/Seraphine AP-in-ARAM) NOT tabled. Re-anchor the table each patch
  via `ops/audit/ds_perm_swarm/build_survivability_item_credit_enchanter.py`. Needs a DS `:8860`
  restart on flip.
- 2026-06-17 RF1 (ENGINE 1.136.0): generic-bruiser-template survivability item-credit seam shipped
  DEFAULT-OFF. NEW `prefer_survivability_by_win` on `hybrid.rank_items_by_hybrid` (the hybrid/bruiser
  scorer lane), driven by the WIN-anchored `agents/daemon_slayer/survivability_item_credit.json` (9 bruiser
  champs / 28 items). The flip wires `agents/daemon_slayer/server.py _route_hybrid` (+/- the
  `core/daemon_slayer_client.hybrid_for` wrapper) to pass `prefer_survivability_by_win=True` so the buried
  survivability winners float above the generic AD-DPS template (section B row above). NOT flipped
  (do-not-flip-blind) - validate the re-rank in a real ARAM. Distinct from the DSP11 DPS/burst kit-axis
  flip (which gates on `delta_dps>0`); survivability items add EHP not DPS so RF1 floats by WIN-table
  membership. Re-anchor the table each patch via `ops/audit/ds_perm_swarm/build_survivability_item_credit.py`.
  Needs a DS `:8860` restart on flip.
- 2026-06-17 LGS1 (no ENGINE bump - pure docs audit): live-sync list audited authoritative. (1) CORRECTED
  the DSV seam-flip row's location - `assume_takedown`/`assume_squishy_target`/`assume_ability_amp` flip the
  BURST scorer `agents/daemon_slayer/burst.py rank_items_by_burst` (+ `compute_burst_damage`), NOT `rank.py`
  (verified by grep: `rank.py rank_items` carries ONLY the DSP2 `exempt_offclass_by_win` + DSP11
  `prefer_kit_axis_by_win` seams; the DSV/DSP8 seams live in `burst.py`, DSP4 `score_completion_runes` in
  `burst.py`+`combo.py`). (2) ADDED a section-B row for the EXCLUDED anti-tank P3.2 live caster-stat producer
  (`antitank.py effective_magnitude` ap/ad_ratio scaling) + the `ehp.py compute_ehp(external_resist_*)`
  Orianna-E/Braum-W/Taric-W ally-resist survivability producer (egg-resist already default-ON item 321) -
  previously the only EXCLUDED live item with no checklist row. Every other rank.py/burst.py/combo.py
  default-OFF seam (DSP2/DSP4/DSP8/DSP11) + the ROADMAP Phase-D flips + champ-select Haiku flip already had
  an accurately-located row. No new seam shipped; no new OPEN work discovered (OPEN1/OPEN2 still pending).
- 2026-06-17 HZU1 (no ENGINE bump - tooling + docs; the item-level CODE shipped item 457 @a30cbba4):
  the HZ Lane-B build-order Haiku-flip gate already mines item-level signal, but its VERDICT is HOLD.
  Fresh re-run @651 SR matches (`--limit 0`) independently REPRODUCED item 457 byte-for-byte: lean-level
  followed-vs-not +2.3pp (766 vs 1066 rows, 95%=[-2.3,+6.9], flip_ready=False); completion-timing also a
  coin flip (fast<=20.82min 56.1% vs slow 56.7%); and 1/51 per-item carriers over the 4627
  lean-ambiguous rows = Infinity Edge anti_squishy +12.6pp (95%=[+0.7,+24.4]), with Serylda's Grudge
  +11.3pp just missing (lo=-0.9). NO live flip is shipped - the build coach AND the laning coach both
  HOLD Haiku until the gate clears its flip rail on a larger corpus and is eyeballed live. The live-gated
  rows for both the Lane-A laning read and the Lane-B build flip are recorded in section C above; re-run
  the gate as `data/rewind_history.db` grows. Artifact: `ops/runtime/build_order_validation.json`.
- 2026-06-17 DSP11 (ENGINE 1.135.0): Cluster-B2 kit-axis item-credit seam shipped DEFAULT-OFF.
  NEW `prefer_kit_axis_by_win` on `rank_items` (dps) + `rank_items_by_burst` (burst), driven by
  the WIN-anchored `kit_axis_item_credit.json` table (7 champs / 21 terminal items, built by
  `ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py` from the DSP10 buried-winner report +
  rewind). When ON: (1) un-strips the champ's kit-axis items from the ranged-marksman off-class
  deny set (Ezreal's hard-excluded Trinity Force becomes a candidate), and (2) floats every
  positive-delta kit-axis item above the generic AD template (model order preserved within tiers).
  NO live scorer passes the flag (default False -> byte-identical). FLIP = wire the dps + burst
  scorer-dispatch to pass `prefer_kit_axis_by_win=True` (section B above). Validate the re-rank vs a
  real Pyke/Nilah/Ezreal ARAM before flipping (do-not-flip-blind). Cluster A (Zilean/Shaco/Kayle/
  Seraphine AP-in-ARAM) is a SEPARATE operator-gated archetype-routing decision, NOT in this table.
- 2026-06-17 DSP9 (no ENGINE bump - offline AUDIT tooling): NO new seam, so NO new
  flip row. The G7 comp-aware parity harness (`ops/audit/lolmath_ds_sweep/g7_comp_harness.py`)
  found that feeding DS the comp-matched build variant does NOT improve parity vs
  lolmath-ULTIMATE (burst_heavy 1.49 < mixed 1.84 < poke 1.86 < frontline_heavy 2.00
  mean item-overlap); lolmath-ULTIMATE is the cost-ignoring raw-stat pile, so the
  residual is the G6 cost-model axis, not comp-awareness. IMPLICATION for the live
  pass: the existing DSP8 `target_preset` flip (section B) is still worth validating
  for assassin-vs-comp correctness, but do NOT expect it to move lolmath-ULTIMATE
  parity - that gap is G6 (deferred FUTURE/BACKLOG per the Gemini-consult, do NOT
  blind-build a gold cost model). No new live-gated work added by DSP9.
- 2026-06-17 DSP7 (ENGINE 1.133.0): ally aura/enchanter seam shipped DEFAULT-OFF. NEW separate
  registry `_ALLY_FLAT_HP_GRANT_OVERRIDES` (in `_passive_ally_grant_overrides.py`) models the flat
  EHP an enchanter's shield/heal CONFERS on a protected ally - the THIRD ally-grant EHP mode
  (after resist + revive) and the SHIELD/HEAL bucket item-289 excluded. 7 enchanter grants
  (Janna/Lulu/Karma/Yuumi E + Seraphine W shields, Soraka/Nami W heals), base values from
  `champion_abilities.json` 16.12.1. Generic consumer seam `compute_ehp(external_flat_hp=)` (default
  0.0 -> byte-identical); no live scorer passes it. Live flip = wire a peel/EHP consumer reading the
  live ally team's granter set (section B above). Re-anchor base + add the granter AP ratio at flip.
  Validate the protected-ally EHP uplift vs a real game before wiring.
- 2026-06-17 DSP6 (ENGINE 1.132.0): enemy-rune threat seam shipped DEFAULT-OFF. NEW
  `agents/daemon_slayer/enemy_runes.py` (the enemy-side mirror of `summoners.py`) models 4 enemy
  runes on the preset each threatens - Press the Attack 8005 (incoming_amp 0.08 on the player),
  Conqueror 8010 (damage_ramp 21.6-48.0 max-stack Adaptive Force + 8%/5% lifesteal), Grasp 8437 +
  Second Wind 8444 (poke_sustain) - plus the non-rune antiheal constant (`GRIEVOUS_WOUNDS_PCT`
  0.40 + `enemy_antiheal_pct`). No live scorer consumes it (`ENEMY_RUNE_SEAM_IDS` marks the ids),
  so /rank is byte-identical. Live flip = wire an EHP / target-preset consumer that reads the
  enemy's live rune set (section B above). Magnitudes are DDragon-16.12.1-cited and re-anchor at
  flip. Validate the re-ranked anti-tank / sustain build vs a real game before wiring.
- 2026-06-17 DSP5 (ENGINE 1.131.0): summoner-spell seam shipped DEFAULT-OFF. NEW
  `agents/daemon_slayer/summoners.py` registry models 6 combat summoner spells (Ignite/Exhaust/Heal/
  Barrier/Cleanse/Ghost) on their scoring axis; no live scorer consumes it (`SUMMONER_SEAM_IDS` marks
  the ids), so /rank is byte-identical. Live flip = wire a fight_report/matchup/coach consumer that
  reads `summoners.py` against the live summoner set (section B above). Magnitudes are LoL-wiki-cited
  (DDragon/CDragon zero them) and re-anchor to the live patch at flip. Validate the adjusted
  survivability/antiheal/CC readout vs a real game before wiring.
- 2026-06-17 DSP4 (ENGINE 1.130.0): self-rune completion seam shipped DEFAULT-OFF. Added Shield Bash
  8401 (Resolve) - the one unmodeled LIVE pickable direct-damage rune proc - to RUNE_PROCS behind
  `COMPLETION_RUNE_IDS`. Live flip = `score_completion_runes=True` on the burst/combo scorer call site
  (section B above). Adds the 5-30 + 2.5% bonus-HP shield-proc floor to a shielded carrier's burst.
  Validate vs a real Shield-Bash game (Leona/Braum/Shen) before flipping.
- 2026-06-17 DSP3 (no ENGINE bump - RC-side resolver, no engine math): ARAM archetype-override seam
  shipped DEFAULT-OFF. Live flip = `core.archetype_picks.get_archetype_for(champion,
  prefer_aram_win_axis=True)` at the ARAM archetype-dispatch site (section C above). Re-bases the
  kit-default archetype to the rewind-WIN archetype for 6 Cluster-A champs; operator picks untouched.
  Validate the re-ranked scorer vs a real Kayle/KogMaw/Zilean/Shaco/Shyvana/Taric ARAM game first.
- 2026-06-17 DSP2 (ENGINE 1.129.0): off-class WIN-exemption seam shipped DEFAULT-OFF. Live flip =
  `rank_items(exempt_offclass_by_win=True)` at the carry/dps scorer call site (the caster-marksman
  re-include; section B above). Validate the re-rank vs a real Ezreal/Corki game before flipping.
- 2026-06-17 seeded from ROADMAP open-tail consolidation. DSP* seam flips append here as they ship.
- 2026-06-20 RC2 P3.3 overlay pulse-rationing flip (UI behavior, NOT a DS seam; `87f41baf` shipped
  the SHADOW). Shadow: `right_now.js` stamps `data-s0-cue` / `data-s0-tier` / `data-s0-pulse` on
  `#right-now` each render via `overlay_priority.signalFromState` -> `selectPrimary` -> `shouldPulse`,
  with ZERO live pulse change. SHIPPED LIVE (operator-approved 2026-06-22, verify-next-game): the
  `.action` per-band pulse (`right_now.js`, the `if (isFreshAction && _s0Pulse)` site near line 540,
  was line 533; the shadow block hoists `_s0Pulse = shouldPulse(...)` near line 496) AND
  `overlay_pulse.js` (MutationObserver, now early-returns via `_s0PulseArmed()` reading
  `#right-now[data-s0-pulse="1"]`) now CONSUME the stamped decision - so motion fires ONLY for the
  Emergency tier (incl. the lethal cue carrying the `lethal_incoming` passthrough) + a one-shot Urgent
  cross (spike/choices) (spec section 5 / acceptance A5). The flip is conservative-only by construction
  (`isFreshAction && _s0Pulse` is a strict subset of the old `isFreshAction` per-band path; the overlay
  gate only adds an early-return) - it can never add a pulse that did not fire pre-flip, only suppress
  benign 'good' / sustained-same-cue re-emits. Regression coverage: `tests/test_overlay_pulse_flip_rc2.py`
  (decision chain a-d + conservative-subset proof + consumer wiring). REMAINING EYEBALL (verify-next-game,
  NOT headless): on a real game confirm the suppressed pulses were all benign re-emits and the Emergency /
  one-shot Urgent cross still glows. The arbitration single-winner (A2) + 44px choice hit-target already
  ship live.
- 2026-06-20 RC2 P4.1 DPI/resolution overlay sizing live eyeball (UI geometry, NOT a DS seam; `4d5d54f0`
  shipped the code). The shell now sizes the overlay window by the work-area scale (resolveOverlayMetrics)
  and zooms the dock content to match (overlay.css `--rc-overlay-scale`). Headless-verified via the
  real-Chromium `test_overlay_view` fixture audit at 2560x1440 (dock zooms to ~598px right-anchored,
  screenshot `overlay_sr_1440_scaled.png`) + baseline-1920 no-op. OWED (operator-gated, NOT headless):
  eyeball the overlay COMPOSITED OVER A REAL LEAGUE GAME at 2560x1440 borderless - confirm the zoomed
  dock reads cleanly over a bright game scene, does not clip the bottom panes against the work area, and
  the right-edge dock lands where expected over the HUD (stage 4.6, live-game visual validation). The
  rc-shell Electron MAIN process needs a relaunch first to pick up the new window-size logic (the web
  renderer half auto-reloads via ADR-008 asset-hash). Does NOT block any further stage.
- 2026-06-20 RC2 P4.2 non-intrusive overlay live eyeball (UI behavior + geometry, NOT a DS seam; this
  cycle shipped the code DEFAULT-ON safe). Three additive overlay behaviors: (1) operator opacity slider
  -> rc-shell `overlayWindow.setOpacity` (the HUD recedes into the game), (2) click-through ZONES
  (`overlay_state.effectiveIgnoreMouse` + `clickthrough_zones.js` hover detector over the preload bridge)
  so PASSIVE captures clicks ONLY over an interactive control (#ovset / #rn-choices / #am-pane-ovds /
  drag strip) without the global ACTIVE hotkey, (3) auto-hide idle recede (`web/js/lib/overlay_idle.js`
  stamps `data-rc-idle` after ~8s of no coach change + no pointer activity; `overlay.css` dims the dock
  to 0.35 opacity; snaps back on the next change / hover). Headless-verified: rc-shell node suite 220/220
  + `test_overlay_idle_rc2` 16 + `test_overlay_settings_panel_dom` (extended) + real-Chromium
  `test_overlay_view` 36, live `:8888` serves the assets. OWED (operator-gated, NOT headless): eyeball
  COMPOSITED OVER A REAL LEAGUE GAME at 2560x1440 borderless - confirm (a) the opacity recede reads
  cleanly and the idle dim is not distracting / wakes correctly on a real coach update, (b) hover-to-
  interact flips the cursor capture crisply over #ovset / choices without eating game clicks elsewhere,
  (c) the drag strip is grabbable on hover. The rc-shell Electron MAIN process needs a relaunch first to
  pick up the new shell logic (preload setZoneHover + main.js opacity/zones); the web renderer half (idle
  recede + the #ovset controls) auto-reloads via ADR-008 asset-hash. Does NOT block any further stage.
- 2026-06-20 RC2 P4.3 single-monitor separated-window arrangement (window-management geometry, NOT a DS
  seam; this cycle shipped the code DEFAULT-ON safe). When the in-game overlay shows alongside the kept
  dashboard (E1/3.4 keepCompanion) on a SINGLE monitor, the shell now arranges them as SEPARATED side-by-
  side windows: an overlapping companion is repositioned (never resized - the size preset survives) to the
  work-area edge on whichever side of the overlay has more free room, top-aligned, so the dashboard sits
  BESIDE the HUD instead of under it. `overlay_state.resolveSeparatedCompanionBounds` is the pure decision
  (respects a companion already clear of the overlay -> moved:false); `main.js applySingleMonitorLayout`
  gates on `screen.getAllDisplays().length === 1` (multi-monitor untouched) + the new `separateWindows`
  setting (no-hotkey #ovset kill switch, default ON). Headless-verified: rc-shell node suite 232/232 (+15
  overlay_state geometry/setting), `test_overlay_settings_rc2` + `test_overlay_settings_panel_dom`
  (extended), real-Chromium `test_overlay_view` 44 (the #ovset Separate-windows toggle renders, defaults
  checked, ASCII label, clears the 42px hit floor), live `:8888` serves the assets. OWED (operator-gated,
  NOT headless): eyeball it OVER A REAL LEAGUE GAME at 2560x1440 borderless - start a game with the
  dashboard parked centered/over-the-right-dock and confirm (a) the dashboard auto-jumps to the free left
  side fully clear of the overlay, (b) it keeps its size (no preset corruption), (c) toggling "Separate
  windows" off in #ovset leaves an overlapping dashboard where the operator put it. The rc-shell Electron
  MAIN process needs a relaunch first to pick up the new main.js logic + the separateWindows authority;
  the web renderer half (the #ovset toggle) auto-reloads via ADR-008 asset-hash. Does NOT block any
  further stage.
- 2026-06-20 RC2 P4.4 settings-UI no-hotkey overlay actions (UI control surface, NOT a DS seam; this
  cycle shipped the code safe - additive #ovset controls, no render-path flip). The overlay's last
  keyboard-only behaviors are now on-screen #ovset controls over a new one-way `overlay-action` IPC: a
  Coach/Build/Threat panel-set segmented selector (the twin of Alt+Shift+C; lights the active segment from
  the body panelset, a pick fires `set-panel` and the shell persists + reloads the overlay onto that set)
  and an "Interact now" button (twin of Alt+Shift+A; fires `set-active`, forces ACTIVE with the same 20s
  auto-revert). `overlay_state.normOverlayAction` is the pure allow-list the main process trusts;
  `main.js applyPanelSet`/`setOverlayActive` are shared by the hotkeys AND the IPC so the two paths never
  drift. Hide/show (Alt+Shift+O) STAYS a hotkey by design (it clears BOTH surfaces, so a self-hiding on-
  screen control would have no way back). Headless-verified: rc-shell node 240/240 (+5 normOverlayAction,
  +3 action-IPC wiring), `test_overlay_settings_panel_dom` 33 (+8), real-Chromium `test_overlay_view` 19
  (+2: the selector + button render at the 42px floor with ASCII labels; panelset=build lights exactly the
  Build segment), live `:8888` serves the controls. OWED (operator-gated, NOT headless): eyeball it OVER A
  REAL LEAGUE GAME at 2560x1440 borderless - confirm (a) clicking Coach/Build/Threat in #ovset swaps the
  overlay panel set (no Alt+Shift+C), (b) the lit segment matches the shown set, (c) "Interact now" makes
  the HUD interactive then auto-reverts after ~20s. The rc-shell Electron MAIN process needs a relaunch
  first to pick up the new IPC handler + applyPanelSet/setOverlayActive; the web renderer half (the #ovset
  selector + button) auto-reloads via ADR-008 asset-hash. Does NOT block any further stage.
- 2026-06-20 RC2 P4.5 overlay + dashboard coexistence (UI control surface, NOT a DS seam; shipped
  code-safe - two additive #ovset action buttons over the existing 4.4 IPC, no render-path flip). Two
  payload-free coexistence commands on the `rc-shell:overlay-action` channel: `rearrange` (re-separate
  the overlay + kept dashboard NOW, forcing past the separateWindows auto kill switch) + `raise-companion`
  (showInactive-if-hidden + moveTop the kept dashboard, then a forced re-arrange). overlay_state
  OVERLAY_ACTIONS grew to 4 members (still frozen); main.js applySingleMonitorLayout({force}) bypasses the
  auto gate; raiseCompanion() reposition-only (no resize). #ovset .ovset-actpair = Re-arrange + Show
  dashboard. Headless-verified: rc-shell node 245/245, test_overlay_settings_panel_dom 37 (+4),
  real-Chromium test_overlay_view 20 (+1: both buttons at the 42px floor, ASCII labels, one row); 0 banned
  glyphs; live `:8888` serves the controls + CSS HTTP 200. OWED (operator-gated, NOT headless): eyeball it
  OVER A REAL LEAGUE GAME at 2560x1440 borderless - with the dashboard kept beside the HUD, confirm (a)
  dragging the dashboard under the overlay then clicking Re-arrange re-separates them side-by-side, (b)
  Show dashboard brings a buried/behind dashboard forward beside the HUD without resizing it, (c) neither
  button ever hides the overlay (no stranding). The rc-shell Electron MAIN process needs a relaunch first
  to pick up the new IPC dispatch + raiseCompanion/force-layout; the web renderer half (the #ovset buttons)
  auto-reloads via ADR-008 asset-hash. P4.6 (live-game visual validation, flipped LIVE) IS this whole-of-
  Phase-4 eyeball - this entry plus the P4.1-4.4 entries above are its checklist. Does NOT block any stage.
- 2026-06-20 RC2 P5.1 local-CV laning overrides (COACHING, NOT a DS seam; shipped code-safe SHADOW-ONLY -
  the served `choices` are NOT altered). The CV override (`core/laning_cv_overrides.py`: enemy DEAD ->
  shove, MISSING >=3s -> back off, my HP <0.35 vs an aggressive verdict -> disengage) currently rides ONLY
  the `data/hz_choice_shadow.jsonl` `cv_override` column. The SERVED FLIP (let the CV override drive the
  live A/B chips in `dashboard/_deterministic_coaching._compute_uncached`) is stage 5.2 and is GATED on the
  agreement re-measurement, NEVER a blind overnight flip. OWED (operator/Gemini-gated, NOT headless):
  (a) accrue real laning games so the new `cv_override` column fills (the live producer runs in-process on
  next RC restart - confirm rows appear with kind enemy_dead / enemy_missing / low_hp at the right moments);
  (b) re-run `tools/hz_shadow_report.py` and read det-vs-Haiku agreement WITH the CV layer applied; (c) when
  agreement climbs toward the >=70% target, authorize the 5.2 served flip. **(c) RETIRED AS
  WRITTEN 2026-08-06 - see `docs/adr/ADR-013`: the Haiku laning verdict this calibrates against
  carries zero mutual information, so agreement with it proves nothing. The gate is a different
  predictor and survives; it needs a new acceptance number. The `>=70%` figure is an author-set
  ASPIRATION: `dea94516` (2026-06-19) wrote "(target: 39% -> >=70%)" into what is now
  `docs/_archive/2026-07-28-research-consolidation/RC2_COACHING_SPEC.md:249`, on the SAME LINE as
  the `HZ_HAIKU_CALL_INVENTORY.md:75` citation that has never supported it. It has an origin and
  no derivation - nothing measures 70, nothing justifies it over 65 or 80.**
  Does NOT block any further stage.
- 2026-06-20 RC2 P6.4 port-safety pooled LCU connection (`RC_LCU_POOL` default-ON flip). The L6 keep-alive
  connection pool (`core/lcu_pool.py`) ships DEFAULT-OFF; the live path is byte-identical until `RC_LCU_POOL=1`.
  OWED (operator-gated, NOT headless): over a REAL champ-select + match, set `RC_LCU_POOL=1` and confirm
  (a) champ-select reads (`game_reader/poller._lcu_get`) still return correct sessions with the pool active,
  (b) no `UNEXPECTED_EOF_WHILE_READING` / SSL EOF on the reused socket (if it appears, check
  `netsh interface portproxy show all` FIRST per `reference_iphlpsvc_portproxy_2999` - that is a self-loop
  rule, not a pool bug), (c) the reconnect-on-drop path self-heals across a client restart mid-session, and
  (d) loopback socket count stays bounded (one long-lived socket per LCU port instead of one-per-call) under
  a tightened poll cadence. Only after (a)-(d) check out over a live game, authorize the default-ON flip.
  UPDATE 2026-06-30 (E7): the frozen `lcu/lcu_client.py._request` is NOW wired onto the same pool (commit
  `2216fb68`, operator frozen-grant, still DEFAULT-OFF), so the every-tick auto-accept path
  (`LcuClient._auto_accept_tick`, ~2 LCU GETs/s) pools too once flipped - extend check (a) to also confirm
  auto-accept + rune-apply read correctly with the pool active. After (a)-(d) pass, the flip is a one-liner
  (`core/lcu_pool.py:40` default or `RC_LCU_POOL=1` in the runtime env). Does NOT block any further stage.
  Bench-swap state-render responsiveness (E7 TODO-1, commit `2ce53103`) shipped independently, NOT gated.
  **VALIDATED + FLIPPED 2026-07-01 (`27787407`):** all four checks passed over a real live game - (a) auto-accept +
  poller reads correct with the pool active (game started clean), (b) 0 SSL EOF on the reused socket (log + a raw
  60-GET keep-alive control), (c) a forced-drop reconnect recovered HTTP 200, (d) main RC held exactly ONE persistent
  loopback socket to the LCU port past 169s (bounded, no per-call churn). Flipped `core/lcu_pool.py:40` default 0->1 +
  the tests to the default-ON contract. E7 default-ON flip is DONE - do NOT re-open this gate.
- 2026-06-21 R9 DS flat damage-reduction EHP seam (`assume_passive_flat_mitigation`, default-OFF). The NEW
  per-instance flat-DR registry (`agents/daemon_slayer/_passive_flat_mitigation_overrides.py`: Fizz P / Amumu E /
  Leona W) ships DEFAULT-OFF on `compute_ehp` + `rank_items_by_ehp` - the EHP math is byte-identical until
  `assume_passive_flat_mitigation=True`. OWED (operator/Gemini-gated, NOT headless - charter 4b "do not flip
  blind"): (a) over a real/replayed game, flip the seam on in the live survivability scorer path and confirm the
  flat-DR champions' (Amumu / Leona / Fizz) EHP-ranking shifts read sane vs eyeball + rewind-WIN data; (b) validate
  the two operator-tunable midpoints against live per-instance data - `_ASSUMED_FLAT_DR_INSTANCES`=6 (the
  representative count of mitigated instances over a fight - the live per-instance damage feed we lack) and
  `_ASSUMED_ABILITY_RANK`=4 (the per-rank Amumu/Leona flat-block read level). A WRONG precompute is worse than no
  credit, so do NOT default-ON until the midpoints are tuned to a live fight clock. Does NOT block any further
  stage.
- 2026-06-21 R12 all-source target-vulnerability mark seam (`apply_target_vuln`, ENGINE 1.149.0, default-OFF).
  The NEW cross-source vulnerability registry (`agents/daemon_slayer/_target_vulnerability_overrides.py`:
  Vladimir R Hemoplague 10% all-source + Evenshroud 3001 / Arena 223001 Coruscation 7%) ships DEFAULT-OFF on
  `agents/daemon_slayer/dps.py compute_dps` - the AA-DPS math is byte-identical until `apply_target_vuln=True`,
  when the wielder's whole DPS is multiplied by the product of every mark she owns (champion ability x each
  registered item, multiplicative). OWED (operator/Gemini-gated, NOT headless - charter 4b "do not flip blind"):
  (a) wire the scorer-dispatch (`agents/daemon_slayer/server.py` compute_dps call sites + `rank.py` / coach
  surfaces) to pass `apply_target_vuln=True` for a marked wielder (Vladimir, or any build holding Evenshroud),
  AND broaden the consumer beyond AA DPS to ability_dps + burst (the all-source mark amplifies those too - this
  seam wires the AA-DPS scorer first); (b) validate in a real game that a marked-target scenario shows a sanely
  higher effective DPS / item ranking, and an unmarked wielder stays byte-identical. The seam models the
  fully-marked target at full magnitude (the assume_takedown / assume_ability_amp developed-fight doctrine);
  uptime gating (Vlad R cooldown, Evenshroud's 5s post-immobilize window) is a live-consumer concern not baked
  here. Imperial Mandate (4005) is EXCLUDED as a non-fit (current-HP detonation, not an all-source %amp). A
  WRONG precompute is worse than no credit, so do NOT default-ON until validated. DS `:8860` restart on flip.
  Does NOT block any further stage.
- 2026-06-30 R43 Imperial Mandate target-vulnerability mark SEEDED (ENGINE 1.158.0, default-OFF) - SUPERSEDES
  the R12 bullet's "Imperial Mandate (4005) is EXCLUDED" note above. DDragon 16.13.1 `item.json` reworked
  Imperial Mandate to "Command: On Immobilizing an enemy champion, mark them as 7% Vulnerable for 4 seconds" -
  a +7% all-source mark - so 4005 / Arena 224005 / ARAM 324005 are now seeded at 0.07 in
  `_target_vulnerability_overrides._ITEM_VULN_OVERRIDES` (R41's handoff, executed; the stale Meraki Coordinated
  Fire mirror is overridden by the official Riot rework). This rides the EXISTING R12 `apply_target_vuln` seam
  and carries NO new flag: a build holding Imperial Mandate is amplified x1.07 only when that flag flips ON, so
  it is folded into the R12 flip already OWED above (wire the scorer-dispatch / rank / coach surfaces to pass
  `apply_target_vuln=True` for a marked wielder). OWED (operator/Gemini-gated, NOT headless): when the R12 seam
  is validated in a real game, also confirm an Imperial Mandate build's marked-target effective DPS / item
  ranking reads sanely higher, and an unmarked wielder stays byte-identical. A WRONG precompute is worse than no
  credit, so do NOT default-ON until validated. DS `:8860` restart on flip. Does NOT block any further stage.
- 2026-06-22 R14 cc_conditional durations_floor_s CC-floor seam (`apply_cc_floor`, ENGINE 1.150.0, default-OFF).
  The NEW guaranteed-minimum floor band on distance / channel-scaled conditional CC
  (`agents/daemon_slayer/cc_conditional.py` ConditionalCcEntry.durations_floor_s: Maokai R 0.75 / Hecarim R 0.75 /
  Ashe R 1.0 / KSante W 0.5 / Sion R 0.25) ships DEFAULT-OFF on `agents/daemon_slayer/cc_pressure.py`
  compute_cc_pressure - the CC-pressure math is byte-identical until `apply_cc_floor=True`, when a floor-tagged
  entry is credited floor + probability * (max - floor) instead of max * probability (in BOTH the standalone and
  the coexistence MAX-rule paths). OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind):
  (a) wire the seam ON through the live consumer chain - compute_cc_pressure is consulted by compute_ehp /
  compute_hybrid (via include_conditional) and the cc-blended-EHP threat surface, none of which thread
  apply_cc_floor yet; thread it (default-OFF preserved) and confirm the floor-tagged champions' CC-pressure /
  blended-EHP-threat read sane vs eyeball; (b) validate the floor model (floor + prob*(max-floor)) reads better
  than the prior max*prob for a close-range Maokai/Ashe/Hecarim R or a short-channel KSante/Sion vs a real game -
  e.g. Ashe R OFF credits 3.5*0.4=1.4s (< unconditional 1.5s, the flat baseline wins) but ON credits
  1.0+0.4*(3.5-1.0)=2.0s (the floor-aware credit wins the coexistence MAX). A WRONG precompute is worse than no
  credit, so do NOT default-ON until validated. DS `:8860` restart on flip. Does NOT block any further stage.
- 2026-06-22 R17 anti-tank level-ramp %max-HP seam (`compute_antitank(level=)`, ENGINE 1.151.0, default-OFF).
  A real subset of antitank %max-HP rows scale their percentage with the CASTER's champion level
  (`agents/daemon_slayer/antitank.py` AntiTankEntry.ramp_lo/ramp_hi: Aatrox P 4:8, Brand P 8:12, KSante P 1:2,
  Mordekaiser P 1:5, Ornn P 10:18, Renata P 1:2, Skarner P 5:9, Urgot P 2:6, Zed P 6:10, Zeri P 1:11). The
  hand-tuned magnitude encodes the max-ramp (late-game) reliability; compute_antitank stays byte-identical until a
  `level` is injected, when a ramp-seeded row's effective magnitude scales by lerp(ramp_lo, ramp_hi,(level-1)/17)/
  ramp_hi (level=18 and level=None both byte-identical; un-ramped rows byte-identical at any level). OWED
  (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a survivability / draft consumer to
  call compute_antitank with the live champion level (the /anti-tank route still passes no level, byte-identical),
  and confirm the early-vs-late level-discounted anti-tank scores read sane vs a real game (e.g. a level-3 Aatrox
  ranks below a level-16 Aatrox on the same tank). A WRONG ramp is worse than the flat magnitude, so do NOT
  default-ON until validated. DS `:8860` restart on flip. Does NOT block any further stage.
- 2026-06-30 R39 anti-tank current-HP level-ramp %current-HP seam (`compute_antitank(level=)`, ENGINE 1.155.0,
  default-OFF). The CURRENT_HP sibling of R17: a real subset of antitank %current-HP rows scale their percentage
  with the CASTER's champion level (`agents/daemon_slayer/antitank.py`
  AntiTankEntry.current_hp_ramp_lo/current_hp_ramp_hi: Senna P 1:10 - Absolution "1% : 10% (based on level) of
  target's current health"). The hand-tuned magnitude encodes the max-ramp (late-game) reliability;
  compute_antitank stays byte-identical until a `level` is injected, when a current-HP-ramp-seeded row's effective
  magnitude scales by lerp(lo, hi,(level-1)/17)/hi via the shared _current_hp_level_ramp_factor (level=18 and
  level=None both byte-identical; rows with no current-HP ramp byte-identical at any level - the same additive
  contract R17 holds, and the two ramp kinds never compound since a row carries at most one pair). OWED
  (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a survivability / draft consumer to
  call compute_antitank with the live champion level (the /anti-tank route still passes no level, byte-identical),
  and confirm the early-vs-late level-discounted Senna anti-tank score reads sane vs a real game (a level-3 Senna
  ranks below a level-16 Senna on the same target). A WRONG ramp is worse than the flat magnitude, so do NOT
  default-ON until validated. DS `:8860` restart on flip. Does NOT block any further stage.
- 2026-06-27 R30 / DSV6 on-cast magic-burst seam (`compute_burst_damage(assume_magic_burst=)`, ENGINE 1.152.0,
  default-OFF). Item on-cast magic procs the per-cast burst combo loop never credited
  (`agents/daemon_slayer/_effects_data.py` magic_burst_base/magic_burst_ap_ratio: Luden's Echo 6655 75+5%AP,
  Stormsurge Squall 4646 125+10%AP, Malignance Hatefog 3118 180+15%AP one ult-zone; EXTENDED R69 / ENGINE
  1.176.0 2026-07-03 with item ACTIVES riding the same seam - Hextech Rocketbelt 3152/223152 Supersonic
  100+10%AP, Everfrost Arena 446656 Glaciate 300+85%AP - so a flip validation now also assumes the player
  presses the active inside the burst window). compute_burst_damage stays
  byte-identical until `assume_magic_burst=True`, when sum(base + ap_ratio*ap) is credited MR-mitigated (MAGIC
  routing) x mode_mult x magic_amp into total_burst (after the rune + execute layers). compute_ability_dps takes
  the same kwarg but is DELIBERATELY INERT (a one-shot magnitude has no place in a per-second metric; compute_dps
  already values these at their PeriodicProc rate, so folding them in the ability-DPS scorer would be wrong-units
  AND a partial double-count). OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a
  burst-scoring / rank consumer (burst.rank_items_by_burst, /rank-assassin, the offense-burst surface) to call
  compute_burst_damage with assume_magic_burst=True, and confirm an AP/magic burst build (Veigar/Syndra/Annie with
  Luden's or Stormsurge) ranks its on-cast magic item ABOVE where the seam-OFF engine placed it, vs a real game.
  A WRONG burst credit is worse than no credit, so do NOT default-ON until validated. DS `:8860` restart on flip.
  Does NOT block any further stage.
- 2026-06-27 R35 survivability percent-DR LIVE consumer (`mitigation_multipliers(snapshot=)` /
  `compute_ehp(apply_passive_mitigation=)`, ENGINE 1.153.0, default-OFF). The R19 forward-marker accessor
  `DataSnapshot.spell_damage_reduction_pct(champ, slot)` (per-rank PERCENT damage reduction from
  champion_abilities.json defensive modifier blocks) now has a consumer: when `apply_passive_mitigation=True` AND a
  snapshot is passed, each (champ, slot) percent-DR block folds into the EHP DENOMINATOR (mit_phys / mit_mag /
  mit_true) read at `_ASSUMED_ABILITY_RANK`=4, amortized by `_ACTIVE_DR_PROB`=0.3, axis by substring (8 snapshot
  champs: Alistar R / Belveth E / Braum E / Galio W split phys+mag / Garen W / Gragas W / MasterYi W / Warwick E).
  compute_ehp stays byte-identical until `apply_passive_mitigation=True` is flipped (the default-False path
  short-circuits to (1,1,1) before the snapshot is consulted; no live scorer/rank call passes the flag today). OWED
  (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a survivability / EHP-rank consumer
  (rank_items_by_ehp, compute_hybrid_mitigation, the tank/bruiser survivability surface) to call with
  `apply_passive_mitigation=True` + the live snapshot, and confirm a percent-DR champ (Galio / Garen / MasterYi
  mid-fight) ranks its EHP / defensive items ABOVE where the seam-OFF engine placed it, vs a real game - and that the
  rank-4 + 0.3-uptime assumption reads sane (a Galio with W up survives the magic burst the OFF engine under-credited).
  A WRONG DR credit is worse than none, so do NOT default-ON until validated. DS `:8860` restart on flip. Does NOT
  block any further stage.
- 2026-06-30 R41 ally mark-detonation seam (`compute_dps(assume_ally_detonation=)` /
  `compute_burst_damage(assume_ally_detonation=)`, ENGINE 1.156.0, default-OFF). A champion whose MARK an ALLY
  consumes for bonus damage (the new PURE registry `agents/daemon_slayer/_ally_detonation_overrides.py`; seeded
  Leona P Sunlight FLAT_MAGIC 32:151 based-on-level, 2.5s mark cadence, verified vs champion_abilities.json
  16.13.1) is credited the amortized TEAM damage her mark enables: per-event magic for burst, per-event/cadence for
  the DPS rate, each MR-mitigated (MAGIC routing) x mode_mult x magic_amp x `_ASSUMED_ALLY_DETONATION_PROB`=0.5.
  Both compute_* stay byte-identical until the flag is True; an unmarked champion contributes 0 even with the flag
  on (the AA-probe call inside compute_burst_damage leaves the seam OFF, so the detonation is credited once in the
  burst total - no double-count). Imperial Mandate 4005 (the directive's named "10% current-HP" detonation) is a
  documented NON-FIT: DDragon 16.13.1 shows it REWORKED to a 7% Vulnerable all-source amp (Control / Command
  passives); the 16.12.1 Coordinated Fire detonation is gone (only the stale Meraki items mirror, content_patch
  None, still carries it), so seeding it would be a WRONG precompute - it now belongs in
  _target_vulnerability_overrides, not this detonation seam. OWED (operator/Gemini-gated, NOT headless - charter 4b
  do-not-flip-blind): wire a DPS / burst / rank consumer (compute_dps / compute_burst_damage / a rank surface) to
  call with `assume_ally_detonation=True` and confirm Leona's mark-enabling team value ranks ABOVE the seam-OFF
  placement vs a real game, and that the 2.5s Sunlight cadence + 0.5 proc-rate assumptions read sane. A WRONG
  detonation credit is worse than none, so do NOT default-ON until validated. DS `:8860` restart on flip. Does NOT
  block any further stage.
- 2026-06-30 R45 Poppy W low-HP doubled percent-of-resist tier (`resist_grants(caster_current_hp_pct=)` /
  `compute_ehp(caster_current_hp_pct=)` / `compute_hybrid(caster_current_hp_pct=)`, ENGINE 1.159.0, default-OFF).
  Poppy W "Stubborn to a Fault" already credited +12% of TOTAL armor + MR; R45 adds the Meraki-16.13.1 "doubled to
  24% while below 40% maximum health" tier as an INCREMENTAL percent applied when the caster's current-HP fraction
  drops below `low_hp_threshold` (Poppy 0.40), i.e. +12% more (24% total) at low HP. DEFAULT-OFF byte-identical on
  two axes: the seam rides the EXISTING `apply_passive_resist` flag AND the new `caster_current_hp_pct` defaults to
  1.0 (full HP) so the low-HP branch is dormant (1.0 not < 0.40) -> identical to 1.158.0. OWED (operator/Gemini-gated,
  NOT headless - charter 4b do-not-flip-blind): wire a live EHP / survivability consumer to pass Poppy's real
  current-HP fraction (the scorer today never reads caster HP) and confirm her sub-40%-HP EHP ranking reads sane vs a
  real game. A WRONG precompute is worse than none, so do NOT default-ON until validated. DS `:8860` restart on flip.
  Does NOT block any further stage.
- 2026-06-30 R46 stacking permanent max-HP passive registry (`compute_ehp(assume_passive_health_stacks=)`, ENGINE
  1.160.0, default-OFF). A NEW survivability axis + the SECOND EHP-NUMERATOR term: champion passives that grant
  PERMANENT bonus max health PER STACK (the new PURE registry `agents/daemon_slayer/_passive_health_overrides.py`;
  seeded Sion W Soul Furnace +4/kill, Cho'Gath R Feast +80/120/160 per stack by rank, Swain P Ravenous Flock +15 per
  Soul Fragment, all verified vs champion_abilities.json 16.13.1). When the flag is True the per-champ bonus max-HP is
  added RAW to every per-type EHP numerator (physical/magical/true), riding the same armor/MR curve. The per-stack HP
  is EXACT Meraki; the assumed STACK COUNT by level is an operator-tunable CONSERVATIVE midpoint (the live stack feed
  we lack). DEFAULT-OFF byte-identical (flag False -> 0.0; no live consumer passes it). OWED (operator/Gemini-gated,
  NOT headless - charter 4b do-not-flip-blind): (1) wire a live EHP / survivability consumer to pass
  `assume_passive_health_stacks=True` for Sion/Cho'Gath/Swain and confirm their stacked EHP ranks ABOVE the seam-OFF
  placement vs a real game; (2) ideally replace the conservative assumed-stack curve with the LIVE stack count (the
  in-game buff/stack reading from the Live Client buff list, if/when that surfaces) so the credit tracks the real
  game state, not a midpoint. A WRONG precompute is worse than none, so do NOT default-ON until validated. DS `:8860`
  restart on flip. Does NOT block any further stage.
- 2026-06-30 R49 on-being-hit reflect damage seam (`compute_dps(assume_passive_reflect=)` /
  `compute_burst_damage(assume_passive_reflect=)`, ENGINE 1.161.0, default-OFF). Rammus W Defensive Ball Curl reflects
  magic damage to basic attackers - a REACTIVE (incoming-triggered) TOTAL-resist form the empowered-AA
  `_passive_damage` seam could not carry. The new registry `agents/daemon_slayer/_passive_reflect_overrides.py`
  (seeded 1 vs verbatim 16.13.1 Meraki: Rammus W "15 (+ 10% total armor) (+ 10% total magic resistance) magic")
  computes the per-incoming-attack magnitude on the caster's resolved TOTAL armor/MR (full-MR via the new
  `caster_mr` scaling target). When the flag is True the reflect is MR-mitigated by the duel target's effective MR
  and amortized into DPS by the assumed incoming attack rate (1 / `reflect_cadence_s`, default 1.0s), or into burst
  over the `_ASSUMED_REFLECT_BURST_WINDOW_S` exposure window. The % terms scale on the build's resolved resists which
  do NOT include W's own active self-buff resists (the `_passive_resist` EHP seam) - a documented LOWER BOUND.
  DEFAULT-OFF byte-identical (both flags False -> the registry is never read; unregistered champ contributes 0 even
  ON). OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): (1) wire a live DPS / burst / rank
  consumer to pass `assume_passive_reflect=True` for Rammus and confirm his W-tank reflect value ranks ABOVE the
  seam-OFF placement vs a real game, and that the `reflect_cadence_s` 1.0s incoming-attack + 3.0s burst-window
  assumptions read sane; (2) ideally feed the W-ACTIVE buffed total armor/MR (so the % terms match League's
  recalculate-over-duration) instead of the resting build resists. A WRONG precompute is worse than none, so do NOT
  default-ON until validated. DS `:8860` restart on flip. Does NOT block any further stage.
- 2026-07-01 R55 archetype-aware DEFAULT for the `target_current_hp_pct` seam
  (`rank_for_primary_archetype(assume_archetype_hp_pct=)`, ENGINE 1.165.0, default-OFF). The seam (item 374) scales
  ONLY the three genuine %-current-HP procs (BotRK 3153 / Hellfire 4017 / Fulmination 443055). R55 plumbs it into the
  CARRY (`rank_items`) + BRUISER (`rank_items_by_hybrid`) scorers -> `compute_dps` (it previously reached only
  mage/assassin) and adds a caller-side resolver `core.ds_archetype_hp_pct.archetype_target_current_hp_pct` mapping an
  archetype to a conservative DEFAULT current-HP fraction (SUSTAINED/juggernaut -> 0.5, target ground down over the
  fight; BURST + non-damage/unknown -> 1.0). DEFAULT-OFF byte-identical (flag False -> carry/bruiser get no override,
  mage/assassin get the caller's value; no live consumer passes the flag). STEP-1 lolmath baseline validation was
  IMPOSSIBLE - lolmath.com is parked (302 -> ww1.lolmath.com, connection refused), so the 0.5 is a conservative DESIGN
  midpoint, NOT a measured constant. OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): (1)
  wire a live carry/bruiser rank consumer to pass `assume_archetype_hp_pct=True` and eyeball across ~3 real games that
  the archetype-resolved current-HP ranks read sane vs the flat-1.0 placement (especially that a bruiser/marksman
  building BotRK does not over/under-rank it); (2) CALIBRATE the exact sustained fraction from a real
  average-current-HP-over-fight measurement (replace the 0.5 midpoint) - the seam is linear in the fraction so the
  value is a single tunable. A WRONG precompute is worse than none, so do NOT default-ON until validated. DS `:8860`
  restart on flip. Does NOT block any further stage.
- 2026-07-03 R74 / DSV8 physical on-cast burst seam (`compute_burst_damage(assume_physical_burst=)`, ENGINE
  1.178.0, default-OFF). Physical analogue of DSV6: an item on-cast PHYSICAL active the per-cast burst combo loop
  never credited. Registry fields `physical_burst_base`/`physical_burst_base_ad_ratio` (END-appended); sole pin
  Goredrinker 226630 Thirsting Slash 1.75x caster BASE AD (Meraki 16.13.1 "Deal 175% base AD physical damage ...
  450 radius"; the heal side 20% AD + 8% missing HP stays unmodeled sustain; 6630/326630/446630 absent from the
  16.13.1 mirror, test-guarded). When True, sum(base + ratio*base_ad) is credited armor-mitigated (PHYSICAL
  routing) x mode_mult into total_burst after the rune + execute layers - deliberately NO amp layer (the engine
  has no physical analogue of magic_amp, grep-proven; the DSV6 block's generic-amp exclusion carries over).
  compute_ability_dps takes the kwarg DELIBERATELY INERT (same wrong-units / partial-double-count doctrine as
  DSV6); compute_dps untouched (15s-CD active, no PeriodicProc, so no double-count). OWED (operator/Gemini-gated,
  NOT headless - charter 4b do-not-flip-blind): wire a burst-scoring consumer with `assume_physical_burst=True`
  and confirm a Goredrinker-holding bruiser's burst rank reads sane vs a real ARENA game (226630 is Arena-only),
  assuming the active fires inside the burst window. A WRONG burst credit is worse than no credit, so do NOT
  default-ON until validated. DS `:8860` restart on flip. Does NOT block any further stage.
- 2026-07-03 R75 / DSV9 anti-shield cut seam (`compute_burst_damage(assume_shielded_target=)`, ENGINE 1.179.0,
  default-OFF). Serpent's Fang Shield Reaver (SR 6695 + Arena 226695; Meraki 16.13.1 "{{rd|50%|35%}}" = melee
  0.50 / ranged 0.35; 226695 ABSENT from the Meraki bulk snapshot - pin grounded on the DDragon 226695 text +
  the batch-42 Arena-mirror convention; 326695/446695 absent everywhere, test-guarded). Registry fields
  `shield_cut_melee_pct`/`shield_cut_ranged_pct` (END-appended). When True AND `target_max_hp > 0`, the ONE-TIME
  active-shield cut is credited as `pct x 0.20 x target_max_hp` (`_ASSUMED_TARGET_SHIELD_PCT_OF_MAX_HP = 0.20`,
  a documented ASSUMED pin) with NO armor/MR routing, NO mode_mult, NO amp - shield HP absorbs post-mitigation
  damage, so removing it is post-mitigation-equivalent value, not damage dealt. The sustained shields-gained
  reduction inside the 3s venom stays UNMODELED (utility over time, not burst math). compute_ability_dps takes
  the kwarg DELIBERATELY INERT (DSV6/DSV8 doctrine); compute_dps untouched (no PeriodicProc, no double-count).
  OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): flip per B41 - a Serpent's Fang
  holder's burst rank reads sane, the assumed-pool credit does not dominate real-damage item swaps, strongest
  eyeball vs a shield-heavy comp. A WRONG credit is worse than none - do NOT default-ON until validated. DS
  `:8860` restart on flip. Does NOT block any further stage.
- 2026-07-10 R92 / Kaenic Rookern (2504) Magebane magic-shield EHP seam
  (`compute_ehp(assume_kaenic_shield=)` / `ehp._collect_shields(assume_kaenic_shield=)`, ENGINE 1.189.0,
  default-OFF). `ITEM_EFFECTS['2504']` now carries a `default_off` magic `ItemShield` (`max_hp_scaling=0.15`),
  credited only when the flag is armed; OFF is byte-identical (the shield is dropped from the always-on
  `_collect_shields` pool and every other shield's magnitude is unmoved since their `max_hp_scaling` is 0.0).
  Routed through this opt-in seam rather than the always-on lifeline pool (Sterak/Maw/Shieldbow) because
  Magebane's "no magic damage for 15s" uptime is ANTI-correlated with the magic-damage fights where the
  shield would matter. OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire an
  EHP-scoring consumer to pass `assume_kaenic_shield=True` and eyeball across ~2 real games that Kaenic's
  magical EHP ranks sensibly vs other MR-tank items (Force of Nature / Spirit Visage), given the
  anti-correlated uptime. A WRONG credit is worse than none - do NOT default-ON until validated. DS `:8860`
  restart on flip. Does NOT block any further stage.
- 2026-07-10 R97 / Eclipse (item 6692 SR + 226692 Arena) Ever Rising Moon self-shield EHP seam
  (`compute_ehp(assume_eclipse_shield=)` / `ehp._collect_shields(assume_eclipse_shield=)`, ENGINE 1.191.0,
  default-OFF). ITEM_EFFECTS 6692 + 226692 each now carry a `default_off` generic `ItemShield`
  (`flat=160.0`, `bonus_ad_scaling=0.40`, `ranged_modifier=0.5` -> melee 160 + 40% bonus AD, ranged 80 + 20%;
  Meraki 16.13.1 "grants you a shield for 160|80 (+ 40%|20% bonus AD) for 2 seconds"). Credited only when the
  flag is armed; OFF is byte-identical (the shield is dropped from `_collect_shields` by the shield-specific
  default-off gate, and every other shield's magnitude is unmoved). The damage half (6% target max HP every 2
  attacks PeriodicProc) was already modeled and is untouched. 226692 is ABSENT from the Meraki bulk snapshot -
  pin grounded on DDragon 226692 + the SR-6692 mirror convention (its periodic + item-AH already mirror SR);
  446692/326692 absent everywhere, test-guarded. OWED (operator/Gemini-gated, NOT headless - charter 4b
  do-not-flip-blind): wire an EHP-scoring consumer to pass `assume_eclipse_shield=True` and eyeball across ~2
  real games (PRACTICE-SR or Arena) that an Eclipse holder's physical/blended EHP ranks sensibly vs other
  lethality/bruiser items, and that the burst-window shield is not over-credited on a sustained-fight clock (a
  6s/target proc CD - the ItemShield credit is a full-magnitude one-instance shield, not uptime-amortized). A
  WRONG credit is worse than none - do NOT default-ON until validated. DS `:8860` restart on flip. Does NOT
  block any further stage.
- 2026-07-14 Fimbulwinter (3121 SR + 223121 Arena + 323121 ARAM) "Everlasting" max-mana-shield EHP seam
  (`compute_ehp(assume_fimbulwinter_shield=)` / `ehp._collect_shields(assume_fimbulwinter_shield=)`, ENGINE
  1.214.0, default-OFF, R129). ITEM_EFFECTS 3121 + 223121 + 323121 each now carry a `default_off` generic (ANY)
  `ItemShield` (`flat=100`, `max_mana_scaling=0.045`) armed per-id via the same shield-specific gate as
  Seraph's/Chainlaced/Eclipse/Kaenic. Meraki 16.13.1 (items['3121'] "Everlasting"): immobilizing (or slowing, if
  melee) an enemy champion grants a "100 (+4.5% current mana)" shield for 3s (8s CD). Current mana modeled as MAX
  mana (steady-state); the +80% multi-enemy arm is NOT modeled (conservative base). ANY damage_type so all 3 EHP
  axes benefit. Credited only when the flag is armed; OFF is byte-identical (verifier-confirmed Sion+3121 EQUAL,
  every other shield's magnitude unmoved). NOT lifeline-keyed (independent CC-trigger shield, stacks with a
  lifeline). OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire an EHP-scoring
  consumer to pass `assume_fimbulwinter_shield=True` and eyeball across ~2 real games that a Fimbulwinter holder's
  blended EHP ranks sensibly vs other mana/tank survivability. SOURCE: R129 / LEDGER 903 / commit 1c6e1fc1.
- 2026-07-10 Seraph's Embrace (3040 SR + 223040 Arena + 323040 ARAM) Lifeline max-mana-shield EHP seam
  (`compute_ehp(assume_seraphs_shield=)` / `ehp._collect_shields(assume_seraphs_shield=)`, ENGINE 1.193.0,
  default-OFF). ITEM_EFFECTS 3040 + 223040 + 323040 each now carry a `default_off` generic (ANY) `ItemShield`
  (`max_mana_scaling=0.18`) via a NEW `ItemShield.max_mana_scaling` term (mirroring R92's `max_hp_scaling`),
  with max-mana threaded through `resolve_magnitude` / `_collect_shields` / `compute_ehp` (sourced from
  `resolved.stats['mp']` = champ base mana + item mp). Meraki 16.13.1 (items['3040'] "Lifeline"): "gain a
  shield ... that absorbs damage equal to 18% maximum mana" at <30% max HP (the stale registry note claimed
  "350 + max-mana%" - corrected to a pure 18% max-mana shield, no flat). Credited only when the flag is armed;
  OFF is byte-identical (the shield is dropped by the shield-specific default-off gate, every other shield's
  magnitude unmoved). ANY damage_type so all 3 EHP axes benefit (unlike R92/R99 magic-only). Ryze L11 +
  Seraph's = 1914 max mana -> 344.6 generic shield (verified). OWED (operator/Gemini-gated, NOT headless -
  charter 4b do-not-flip-blind): wire an EHP-scoring consumer to pass `assume_seraphs_shield=True` and eyeball
  across ~2 real games that a Seraph's holder's blended EHP ranks sensibly vs other mana/AP survivability
  items, and that the low-HP-triggered per-fight shield is not over-credited on a sustained clock (the
  ItemShield credit is a full-magnitude one-instance shield, not uptime-amortized). A WRONG credit is worse
  than none - do NOT default-ON until validated. DS `:8860` restart on flip. Does NOT block any further stage.
- 2026-07-10 Riftmaker (4633 SR + 224633 Arena) max-stacks omnivamp EHP-SUSTAIN seam
  (`compute_ehp(assume_max_stacks_omnivamp=)`, ENGINE 1.194.0, default-OFF; R100). NEW `_item_omnivamp`
  registry (`item_id -> (melee_frac, ranged_frac)`, mirroring `_item_tenacity`): 4633 + Arena mirror 224633
  each = (0.10, 0.06) from Meraki 16.13.1 items['4633'] "Void Corruption" ("At maximum stacks, gain
  {{as|{{rd|10%|6%}} omnivamp}}"). When armed, compute_ehp injects the build's summed omnivamp fraction
  (melee/ranged-picked by `is_ranged`) into `stats['omnivamp']` so the already-built `_vamp_heal_pool`
  consumer credits it to `effective_ehp_with_sustain` / `sustain_ehp_delta`. OFF is byte-identical
  (`stats['omnivamp']` stays absent -> `heal_omnivamp` 0.0 -> `effective_ehp_with_sustain == blended_ehp`);
  ON leaves `blended_ehp` byte-identical too (SUSTAIN axis only, same posture as lifesteal/spellvamp -
  verified Morde L13 blended_ehp 3600.12 both OFF/ON, heal_omnivamp 44.0; Ezreal ranged 26.4). Deferred
  conditional siblings (2517 takedown-gated, 3156 Lifeline-proc, 447103 consumer-not-grant). OWED
  (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire an EHP-sustain-scoring consumer
  to pass `assume_max_stacks_omnivamp=True` and eyeball across ~2 real games that a Riftmaker holder's
  sustain-EHP ranks sensibly vs other sustain items, and that the max-stacks best-case is not over-credited
  on a short-fight clock (the omnivamp needs full Void Corruption ramp). A WRONG credit is worse than none -
  do NOT default-ON until validated. DS `:8860` restart on flip. Does NOT block any further stage.
- 2026-07-10 Guardian Angel item-revive EHP-NUMERATOR seam (`compute_ehp(assume_item_revive=)`, ENGINE
  1.195.0, default-OFF; R102). NEW `_item_revive` registry (3026 + Arena 223026 = 0.50 base-HP fraction).
  When armed, folds `item_revive_mult = 1 + 0.5*(base_hp/total_hp)*0.4` into `common_revive` (through NORMAL
  resists; GA has no egg). OFF byte-identical; ON RAISES blended_ehp (a NUMERATOR term, unlike omnivamp
  sustain) - Garen L13 + GA 3331.93 -> 3998.31 (x1.20). OWED (operator-gated, do-not-flip-blind): wire an EHP
  consumer to pass `assume_item_revive=True`, eyeball a GA holder's blended-EHP ranks across ~2 real games
  (50%-base second life amortized at 0.4, not over-credited on a short-fight clock; build-dependent re-rank if
  armed in a ranker). DS `:8860` restart on flip. Does NOT block any further stage.
- 2026-07-10 item self-STASIS EHP-NUMERATOR seam (`compute_ehp(assume_item_stasis=)`, ENGINE 1.196.0,
  default-OFF; R103). NEW `_item_survival_window` registry (Zhonya 3157 + Arena 223157, Seeker 2420, Wooglet
  228002 = 2.5s stasis each), the ITEM-side lane of the champion-keyed `_passive_survival_window_overrides`.
  When armed, folds `item_stasis_mult = 1 + sum(min(2.5/6,1)*0.35)` into `common_revive` (avoided-damage
  fraction; composes multiplicatively with the champion survival window + revive). OFF byte-identical; ON
  RAISES blended_ehp - Garen L13 3157 3376.01 -> 3868.34 (x1.1458). OWED (operator-gated, do-not-flip-blind):
  wire an EHP consumer to pass `assume_item_stasis=True`, eyeball a Zhonya/Seeker/Wooglet holder's blended-EHP
  ranks across ~2 real games (2.5s stasis amortized at the 0.35 item-active midpoint, not over-credited on a
  short-fight clock; build-dependent re-rank if armed in a ranker). DS `:8860` restart on flip. Does NOT block
  any further stage.
- 2026-07-11 item-side MANA->MAX-HP "Awe" EHP-NUMERATOR seam (`compute_ehp(apply_item_mana_health=)`, ENGINE
  1.198.0, default-OFF; R105). NEW `_item_mana_health` registry (Winter's Approach 3119 + Fimbulwinter 3121 +
  Arena 223119/223121 + ARAM 323119/323121 = 0.15 of BONUS mana each), the ITEM-side lane of the champion-keyed
  `_passive_health_overrides` stacking-HP axis. When armed, folds `item_mana_health_hp = 0.15 * bonus_mana`
  (bonus_mana = item-contributed max mana = total - base) next to `ext_flat_hp` in every per-type numerator + the
  `_blend_with_heal` sustain mirror - a genuine flat max-HP pool add, EXACT (no amortization midpoint). OFF
  byte-identical; ON RAISES every EHP type - Rell L13 + Fimbulwinter blended_ehp 3711.51 -> 3952.64
  (item_mana_health_hp 150.0). OWED (operator-gated, do-not-flip-blind): wire an EHP consumer to pass
  `apply_item_mana_health=True`, eyeball a Fimbulwinter/Winter's-Approach holder's blended-EHP ranks across ~2
  real games (deterministic credit, no midpoint - but a build-dependent re-rank if armed in a ranker). DS
  `:8860` restart on flip. Does NOT block any further stage.
- 2026-07-11 item-side conditional RESIST-GRANT EHP-DENOMINATOR seam (`compute_ehp(apply_item_resist_grants=)`,
  ENGINE 1.199.0, default-OFF; R106). NEW `_item_resist_grants` registry (Jak'Sho 6665 + Arena 226665 = +30% of
  BONUS armor+MR at 5 combat stacks, percent-of-bonus mode; Force of Nature 4401 + Arena 224401 = +70 flat bonus
  MR at 8 stacks, MR only), the ITEM-side lane of the champion-keyed `_passive_resist_overrides.resist_grants`.
  When armed, folds the amortized bonus armor/MR into `eff_armor`/`eff_mr` (the DENOMINATOR, next to the champion
  `bonus_armor`/`bonus_mr`, before the pen step + the `_armor_factor` curve), so it flows into every per-type EHP
  + the `_blend_with_heal` sustain mirror via the eff_* closure - no numerator touch. CONDITIONAL (ramps to max
  stacks), amortized by `_ITEM_RESIST_STACK_PROB` 0.5 (unlike R105's exact mana->HP). OFF byte-identical; ON
  raises the resisted axes - Ornn L13 + FoN magical_ehp 4720.00 -> 5508.75 (item_resist_mr 35.0, physical
  unchanged); Ornn L13 + Jak'Sho blended 4785.97 -> 4934.71 (item_resist_armor/mr 6.75 each). OWED
  (operator-gated, do-not-flip-blind): wire an EHP consumer to pass `apply_item_resist_grants=True`, eyeball a
  Jak'Sho/FoN holder's blended-EHP ranks across ~2 real games (the 0.5 ramp midpoint is conservative, not
  over-credited on a short-fight clock; build-dependent re-rank if armed in a ranker - Voidborn's %-of-bonus
  scales with the rest of the build). DS `:8860` restart on flip. Does NOT block any further stage.
  R124 (2026-07-14, ENGINE 1.212.0) extends the SAME flag with its first ALWAYS-ON entries (conditional_probability
  1.0, no ramp, EXACT): Shield of Molten Stone (443058 / mirror 663058) +20% of TOTAL armor + Cloak of Starry Night
  (443059 / mirror 663059) +20% of TOTAL MR (prismatic Arena items, DDragon 16.13.1, Meraki-absent), family-deduped
  base+mirror. When armed these raise an Arena Molten Stone / Starry Night holder's physical (armor) / magical (MR)
  EHP EXACTLY (no amortization). The operator flip-eyeball for `apply_item_resist_grants` now also covers these
  prismatic ids; same flag, same DS `:8860` restart on flip.
- 2026-07-11 item-side BONUS-HP-AMP "Warmog's Vitality" EHP-NUMERATOR seam (`compute_ehp(apply_item_bonus_hp_amp=)`,
  ENGINE 1.200.0, default-OFF; R107). NEW `_item_bonus_hp_amp` registry (Warmog's Armor 3083 + Arena mirror 443083
  = 0.12 of bonus-health-from-items each; MAX over the equipped family, a UNIQUE passive over a shared bonus-HP
  pool), a genuinely NEW survivability axis (item HP -> HP self-amplifier) distinct from the seven saturated
  item-side families. When armed, folds `item_bonus_hp_amp_hp = 0.12 * bonus_hp_from_items` (bonus_hp_from_items =
  total max HP - base max HP) next to `item_mana_health_hp` in every per-type numerator + the `_blend_with_heal`
  sustain mirror - a genuine flat max-HP pool add, EXACT (no amortization midpoint, like R105). OFF byte-identical;
  ON RAISES every EHP type - Sion L13 + Warmog/Heartsteel/Sunfire blended_ehp 7453.70 -> 7975.39
  (item_bonus_hp_amp_hp 270.0); other HP items with no Warmog stay byte-identical (no leak). OWED (operator-gated,
  do-not-flip-blind): wire an EHP consumer to pass `apply_item_bonus_hp_amp=True`, eyeball a Warmog's holder's
  blended-EHP ranks across ~2 real games (PRACTICE-SR own-build suffices - buildable vs dummies; deterministic
  credit, no midpoint - but a build-dependent re-rank if armed in a ranker). DS `:8860` restart on flip. Does NOT
  block any further stage.
- 2026-07-11 item-side LOW-HP MAGIC/TRUE amp "Cinderbloom" BURST seam (`compute_burst_damage(assume_item_lowhp_magic_crit=)`,
  ENGINE 1.203.0, default-OFF; R110). NEW `_item_lowhp_magic_crit` registry (Shadowflame 4645 = +0.20 / Arena mirror
  224645 = +0.15; MAX over carriers, a UNIQUE "Cinderbloom" passive), a genuinely NEW damage-layer axis (item-keyed
  low-HP gate on MAGIC + TRUE damage) distinct from the always-on magic amp (MAGIC-only) and the INVERSE high-HP
  anti-tank gates - and it reaches TRUE damage, which no existing amp does. When armed AND target_current_hp_pct <
  0.40 AND a registered Shadowflame is equipped, multiplies every MAGIC + TRUE burst bucket by (1 + amp) at each
  existing per-type fold point; physical + the AA path never touched (mirrored INERT on `compute_ability_dps` for
  API symmetry, per the DSV8/DSV9 convention). OFF byte-identical (LIVE proof: Xerath L11 + [4645] total_burst
  1797.84 identical at hp_pct 0.41 vs 0.39 - the amp never fires); ON raises burst below 40% by EXACTLY amp x the
  magic+true portion (item_lowhp_magic_crit_mult 1.20 SR / 1.15 Arena). SCOPE BOUNDARY (matches magic_amp precedent,
  NOT a gap): untyped rune procs (Electrocute/Comet) are not amped (the engine never routes them through magic_amp
  either). OWED (operator-gated, do-not-flip-blind): wire a burst/assassin consumer to pass
  `assume_item_lowhp_magic_crit=True` + a live `target_current_hp_pct`, eyeball a Shadowflame carry's burst ranks vs
  a sub-40% target across ~2 real games (PRACTICE-SR own-build suffices - deterministic gate, no midpoint;
  build-dependent re-rank if armed in a ranker). DS `:8860` restart on flip. Does NOT block any further stage.

- 2026-07-14 CDragon per-instance resource guard for MissFortune R full-channel total (`AbilitiesSnapshot.load(apply_cdragon_resource_guard=True)`, ENGINE 1.213.0, default-OFF; R127). The prefer_cdragon_ratios cutover undercounts MF R ~17.7x by overwriting the Meraki 1050% total with the CDragon 60% per-wave atomic (MF total_ability_dps 14.9 -> 27.4 when guarded). FLIP = set the guard True at the default abilities loader (RC-side coach caller / `abilities.load_default`) + reload; VALIDATE in a live or replayed MissFortune game (R DPS should ~13x, build reco unaffected for other champs) before default-ON.

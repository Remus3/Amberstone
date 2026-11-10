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
owed; superseded 2026-08-12 by B4, which hides all three in a live game by design, and w-spike was
deleted 2026-08-11 - see the struck G2-28), G2-41 (premise confirmed: `/latest-frame` measured 1280x720 vs a 2560x1440 display),
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
that adds no new work. G3-03 was BLOCKED ON WIRING on 2026-10-24 until RM-850 shipped the same day
(`14f804fc2`, LEDGER 1816); it is drainable again. G3-13 was BLOCKED ON WIRING on 2026-10-24
until RM-860 shipped the next day (`9b51bc90f` + `32f625d4c`, LEDGER 1832); it is drainable again
(re-tagged 2026-10-27, s144 lane gated cycle 8). G1-03 was re-tagged the same day (draft lobby
only); no count moved. G4-02 / G4-03 / G4-04 / G4-05 were tagged BLOCKED ON WIRING on 2026-11-06
(s144 lane gated cycle 81: no RC producer sends any of the four DSP5-DSP8 live inputs at local
main `ba0df749f`; the AGE CHECK sits in G4-02); no count moved. G2-13 / G2-14 were tagged BLOCKED
ON WIRING on 2026-11-06 (s144 lane gated cycle 83: no live RC caller sends the `/burst` HP gate
seams or the `runes` they need; the AGE CHECK sits in G2-13); no count moved. G2-04 / G2-10 were
tagged BLOCKED ON WIRING on 2026-11-06 (s144 lane gated cycle 84: no live caller arms the R5 heal
amp, the registered champions never reach the enchanter scorer, and no EHP route or ranker carries
the R45 `caster_current_hp_pct`; each row holds its own AGE CHECK); no count moved. G2-08 / G2-17 /
G2-20 were tagged BLOCKED ON WIRING on 2026-11-06 (s144 lane gated cycle 85: `assume_magic_burst`,
`assume_shielded_target` and `score_completion_runes` are parsed by `/burst` only and no live RC
caller arms them on a route that reads them; the AGE CHECK sits in G2-08); no count moved. G2-11 /
G2-18 / G2-19 were tagged BLOCKED ON WIRING on 2026-11-06 (s144 lane gated cycle 86: nothing in RC
calls `/ehp`, no DS route parses `assume_caster_lowhp` and the ruled live HP feed is unshipped, and
no live caller arms the DSV2/3/4 burst seams; each row holds its own AGE CHECK); no count moved.
G2-09 / G2-12 were tagged BLOCKED ON WIRING on 2026-11-06 (s144 lane gated cycle 87: four DS routes
parse `apply_passive_mitigation` but no live RC caller arms it, and no DS route parses
`assume_passive_reflect`, RM-1391 still OPEN; each row holds its own AGE CHECK); no count moved.
G2-02 / G2-03 / G2-05 / G2-06 / G2-15 / G2-16 were tagged BLOCKED ON WIRING on 2026-11-06 (s144
lane gated cycle 88: the three `/dps`-only seams have no live caller of `dps_for` and die on the
`/rank` wire, `/ehp` has no RC caller for `apply_cc_floor`, `assume_archetype_hp_pct` is an RC-side
flag no live caller sets, and no live dispatch arms `assume_ms_utility`; the shared AGE CHECK sits
in G2-02, the others in their own rows); no count moved.
G4-07 / G4-10 were tagged BLOCKED ON WIRING on 2026-11-06 (s144 lane gated cycle 89: no DS
route parses the load-time `apply_all_out_bonus`, and `/hps` alone parses `apply_ability_hsp_amp`
with no RC caller of `hps_for`; each row holds its own AGE CHECK). G4-06 and G4-11 got an AGE
CHECK only (still no live residual); no count moved.
G4-14 got an AGE CHECK on 2026-11-06 (s144 lane gated cycle 90: the full-screen overlay of
2026-06-21 removed the P4.1 dock and the premise of the P4.3 / P4.5 separation, and the P4.4 panel
selector is a reload only; the P4.2 + Interact-now eyeballs stay open under a stated predicate); it
stays OPEN; no count moved.
G4-15 got an AGE CHECK and a per-game card on 2026-11-06 (s144 lane gated cycle 91: the in-game
surface is the overlay, not the dashboard, since 2026-06-27; champ select stays on the companion); it
is standing and never closes; no count moved.
The 2026-08-12 `hz_choice_shadow` game_id row was filed as a SECOND "G3-14"; it is G3-16 since
2026-10-24 and, like G6-04, was never in the 111 (its commit `0dc5dbd0d` did not touch this line).
G5-11 (the focus-board Arena team layout, filed 2026-10-27 by s144 lane gated cycle 11) was never in
the 111 either; do not add it to this tally or to the per-gate figures. Nor was G1-07 (the RM-881 (b)
lobby duo-synergy read-back, filed 2026-10-27 by s144 lane gated cycle 16).

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

**TFT GAME (lane 9, s134).** `/api/state` alone does not say a TFT game is up: RC can read `mode_key`
`client` with an empty `liveclient` while `lcu.phase` is `InProgress` (measured 2026-10-25, game
1000000911, queue 1090). When the interactive TFT QA recorder is running, run
`python tools/gated_tft_qa_summary.py <repo>/ops/runtime/tft_qa/<match_dir>` (`--json` for machine
output). It prints the RC pid timeline (each pid change mid-match is a restart), the mode timeline,
how many InProgress samples RC did NOT read as tft and the callout tags it served then, plus event and
frame counts. READ-ONLY on the recorder files; a summary is the INPUT to the evidence contract, never
the evidence itself.
The TFT game process is the standalone Unreal client `TFTClient-Win64-Shipping.exe` (plus
`TFTClient.exe`), NEVER `League of Legends.exe`, and NOTHING listens on `:2999` (`docs/TFT_PROGRAM.md`
measured fact 1; empty `liveclient` in every recorder sample of matches 20261025-070350 and -081234).
So "no `League of Legends.exe`" plus "`:2999` refused" is NOT a launch stall and NOT "no game": the
game-up discriminator is `tasklist` showing `TFTClient-Win64-Shipping.exe` while `lcu.phase` is
`InProgress` (measured 2026-10-25 08:24 local, game 1000000913, queue 1090: process started 08:12:30,
beside LCU gameflow-phase updates at 08:12:29). Every TFT row whose probe needs `liveclient`, `:2999`
or `health.has_game` is BLOCKED by that, not drainable.
`:8889/latest-frame` answers JSON (`b64` plus meta), not raw image bytes: decode with
`base64.b64decode(body["b64"])` before handing it to Pillow.
In TFT that frame is also STALE or ABSENT almost all the time, so a TFT row whose probe needs a fresh
`:8889` frame (the S6 read-back, any TFT OCR / vision-reader live half) is not drainable on demand: a
fresh frame appears only now and then (match -081234 has `self_grab` frames at 08:12:35, 08:12:59 and
08:20:54 local, cause not measured; likely an admitted image briefly holding focus). The GDI
self-grab foreground gate admits only `vision_server/_frame.py` `_GAME_CONTENT_IMAGES` (League, the
RC shell, `electron.exe`), which omits `tftclient-win64-shipping.exe`; the OBS frame source (config
`frame_source` true, OBS running) is tried first and also yields nothing, since `not_foreground` is
counted only after it returns None. Measured 2026-10-25 08:31 local, game 1000000913, queue 1090:
foreground image `tftclient-win64-shipping.exe`; `:8889` `/stats` `capture_skip.not_foreground` 158
(last_ts 1792935074.6); `/latest-frame/meta` `ts` still 1792934454.5 (08:20:54, 618 s old). The
recorder agrees: at 08:31 all 49 `game` rows in match 20261025-081234 `frames.jsonl` carried `why`
`vision_stale_<age>` (min age 40.0 s), and all 80 in match -070350 carry `vision_status_404`.
Expected unblock (unmeasured: nobody has yet seen a GDI grab of the TFT client pass the blank check)
= add the TFT image to that set and to its mirror `tools/screen_agent.py` `GAME_CONTENT_IMAGES`
(pinned by `tests/test_vision_capture_fail_closed_y03.py`), then restart the SEPARATE `:8889` vision
process between games (an RC restart does not reload it); or point the OBS capture source at the TFT
client.
**UPDATE 2026-10-25 08:56 local (lane 9 cycle 11): both blocks above are LIFTED live (the first
only in part: `:2999` rows stay blocked).** Main
`852b85e4b` (S134 P0: standalone TFT client routed to `MODE_TFT`, `tftclient-win64-shipping.exe` in
`_GAME_CONTENT_IMAGES` and its `tools/screen_agent.py` mirror, a `tft_standalone` live source) is
running: RC pid 20228 (`ops/runtime/health.json` started 13:45:24 UTC), the `:8889` process up since
about 08:46:44 local (`/stats` `uptime_s` 669 at 08:57:52). Measured in game 1000000912 (recorder
match 20261025-085349, start 08:53:49 local): `/api/state` at 08:56:13 had `mode_key` `tft`,
`liveclient.source` `tft_standalone`, `liveclient.game_time` `2:23`, `lcu.phase` `InProgress`;
`health.json` `has_game` true; `:2999` still refused (curl `000`). So "in game" for TFT is again
readable from `/api/state` (`mode_key` `tft` plus a non-empty `liveclient`), but `liveclient` is RC's
own standalone summary (keys `board_size`, `board_str`, `game_id`, `game_mode`, `game_time`,
`game_time_s`, `hp`, `live_api`, `players_alive`, `source`, `standing`), NOT the `:2999` schema: a
row whose probe names a `:2999` field path (`activePlayer`, `allPlayers`, `events`) stays blocked.
Frames: `/latest-frame/meta` `ts` 1792936573.46 was 0.11 s old at the 08:56:13 GET, `source`
`self_grab`, 1280x720 jpeg; `/stats` `capture_skip` `blank` 0, `not_foreground` 7 (last_ts
1792936478.4 = 08:54:38 local, about 49 s into the match); recorder `frames.jsonl` of that match: all 12 `vision` rows
`self_grab`, `frame_age_s` 0.1 .. 4.8, none carrying a `why`. The "expected unblock" is therefore
MEASURED: a GDI grab of the TFT client passes the blank check (the 08:56:13 `/latest-frame` decodes
with Pillow 13.0.0 to JPEG RGB 1280x720, luma range 1 .. 253). A TFT
row needing a fresh `:8889` frame is now drainable on demand while a game is up. Reverses if: a TFT
match's `vision` frame rows carry `vision_stale_*` / `vision_status_404` again.
**New block, same game (lane 9 cycle 11, filed as RM-902): every TFT Haiku call fails.**
`logs/2026-10-25.log` 08:53:55 .. 08:56:46 local: 18 lines `Error code: 400 ... invalid_request_error
... This API key is not scoped to a workspace, so this request must include the
anthropic-workspace-id header` (13 `rc.tft.coach` `tft_coach_engine.py:744`, 5 `rc.tft.vision`
`tft_vision_reader.py:252`), zero in the 2026-10-20 .. -24 logs, and no TFT row in
`data/spend/2026-10-25.json` (only `agent7_warm`, 35 calls, written 03:04). `/api/state` stayed
degraded, not raw (no error text; `coach.action` None at 08:57:24). So a TFT row whose predicate is a
Haiku coach line or a Haiku vision read (and RM-681's per-path 1.x read-back for the TFT coach path)
is BLOCKED on the RC process's API key, not drainable, until a TFT game shows a non-error
`rc.tft.coach` reply. Reverses if: a TFT game's log shows `rc.tft.coach` calls with no 400.
**UPDATE 2026-10-25 20:46 local (lane 9 cycle 29): the RM-902 block above is LIFTED; its own
reversal condition was met in a live TFT game.** Predicate (the line above, written before this
look): a TFT game's log shows `rc.tft.coach` calls with no 400. Game 1000000914, queue 1090 Normal
TFT (recorder match 20261025-162857: `MATCH_START.json` `start_iso` 2026-10-25T21:28:57+00:00,
`MATCH_END.json` `end_iso` 22:05:22+00:00, `last_game_time_s` 2171.8). Log file names below are as
of 20:46 local; the log rotated at 20:47 and each suffix moved up one (`.log` -> `.log.1`, `.log.1`
-> `.log.2`, `.log.2` -> `.log.3`), so re-check by timestamp, not by name. `logs/2026-10-25.log`
16:28:57 .. 17:06:00 local: 133 lines `TFT coach response in <n>ms` (first 16:29:00.829, last
17:05:06.801) and zero `Error code: 400` / `invalid_request_error` lines, `rc.tft.vision` included.
That log line is written only after `self._client.messages.create` returns
(`tft/tft_coach_engine.py` `TftCoachEngine._run`), and the SDK raises on a 400, so each line is a
returned Haiku reply. Independent corroboration: `data/spend/2026-10-25.json` `by_purpose.tft_coach`
`calls` 548 equals the day's 548 `TFT coach response in` lines over the three day logs
(`.log.2` 0, `.log.1` 176, `.log` 372). Day timeline: last workspace 400 at 09:28:14.951
(`.log.1`), first reply at 10:44:10.870 (`.log.1`). Scope: this lifts the BLOCK only. It ticks no
row: a row whose predicate is a Haiku coach line that RENDERS (overlay, dashboard panel) still needs
its own render evidence, and a parsed reply is not guaranteed (`.log` 14:00:08.923 `TFT: no fields
parsed from response`). Reverses if: a later TFT game's log shows an `rc.tft.coach` or
`rc.tft.vision` 400 again.

**S6 READY (lane 9, s144 cycle 1, PREP only, no game up; NOT ticked): vision decodes a live League
frame under Pillow 13 (`cef8bfd22` pinned 13.0.0).** Any League game (GATE 2 / 3 / 4 / 5; IN-GAME =
`mode_key` sr / aram / arena / brawl AND a non-empty `liveclient`). Predicate, stated before any game.
Verdicts: PASS iff (a), (b) with `meta.source` `obs`, and (d) hold in ONE game; PARTIAL iff (a) and
(b) hold with `meta.source` `self_grab`; FAIL-SIGNAL if (e) is seen; anything else is NOT-YET. Only
PASS drains S6. PARTIAL and FAIL-SIGNAL are recorded beside this row, never ticked or struck.
- (a) PROCESS SIDE, `python tools/gated_vision_pillow.py --json`, run TWICE: once just before and
  once just after (b)'s readback. Both runs: exit 0 (exactly one listener), the same `pid` AND the
  same `create_time`, that `create_time` earlier than (b)'s `meta.ts` (the frame was served by THIS
  process, not by one a restart replaced), `stats_tie.same_process_after_get` and
  `stats_tie.uptime_matches_create_time` both true (the tool re-reads the listener after its `/stats`
  GET and checks `uptime_s` against `create_time`, so the counters below are THIS pid's),
  `pil_loaded` true (a `PIL\_imaging*.pyd` is mapped IN the `:8889` listener process), and `s6` reads
  `single_pillow_dist` true, `version_is_13.0.0` true, `installed_before_process_start` true. The
  after-run must read `stats.frame_upload.calls` = 0: no `/upload-frame` in that process's whole life
  (it read 0 at the idle baseline; `tools/screen_agent.py` and `tools/phase_watcher.py`, the two
  uploaders, have no scheduled task). A non-zero count makes the game NOT-YET: a lifetime count of
  one pinned process cannot be gamed by timing, where a start / end bracket could. `pil_loaded` alone
  is not a decode: a header-only read (`/upload-frame`, `/vision`) imports Pillow too.
- (b) FRAME, `python tools/gated_frame_readback.py --json` between the two (a) runs: exit 0, `age_s`
  <= 5, `pillow.format` JPEG, `pillow.width` and `pillow.height` > 0, `pillow.luma_extrema` span > 0
  (not blank), and `meta.width` / `meta.height` NOT null. `meta.source` decides the verdict: on an
  `obs` frame `vision_server/_frame.py` `_maybe_obs_frame` runs `Image.open` plus `img.load()` IN the
  vision process and sets `width` / `height` only after the whole block succeeds (its `except` serves
  the raw bytes with both None), so an `obs` frame with a non-null `meta.width` is an in-process
  DECODE - provided it did not arrive through `/upload-frame`, which copies `source` from the request
  body and, since `393c7f512` (RM-1046), takes `width` / `height` from a Pillow HEADER read of the
  payload (`_frame_dims`; the body's claim only when that header is unreadable) - a header read, never
  a decode (`handle_upload_frame`); (a)'s count of 0 rules that out (`_stats.py` `_record` bumps
  `calls` on every upload the handler sees, accepted or refused; a 401 or bad-length POST that
  `do_POST` turns away never reaches it, and never caches a frame either). Context only, never a verdict input: record whether
  (a)'s `create_time` is before or after the vision respawn that loads `393c7f512`; `_maybe_obs_frame`
  is unchanged by it. A `self_grab` frame is `ImageGrab.grab()` plus a JPEG ENCODE in-process, never a
  decode.
- (c) Context only, never a verdict input: the `stats.vision` / `stats.ocr` rows of (a). A `vision`
  success does not prove a decode: `_inference.py` `_crop_to_primary` reads only the header of a
  frame at or under 1920x1080 (a `self_grab` / `obs` frame is at most 1280 wide) and forwards the
  original after any `Image.open` failure other than a bomb or `MemoryError`, which still records
  `ok=True` once Sonnet's reply
  parses. `ocr` has no League caller (`core/moon_proxy.py` `ocr_crops` has no production caller).
- (d) IN-GAME at the readback: `/api/state` read within the same minute shows `mode_key` sr / aram /
  arena / brawl and a non-empty `liveclient`; record `liveclient.game_mode`, `liveclient.game_time`,
  the read time and the listener pid. Known limit: the `obs` lane has no foreground gate, so (b)
  proves a decode of what OBS captured; that it shows League rests on (d) plus the OBS source
  (default `Game Capture`, `core/obs_frame_source.py`), and the tick line says so.
- (e) FAIL-SIGNAL (re-opens the `cef8bfd22` question for a measured re-check; it closes and strikes
  nothing): with (a)'s pid pinned and `frame_upload.calls` 0, readback exit 3 with `Pillow could not
  decode` (exit 3 with `reply carried no image bytes` is NOT-YET), or an `obs` frame with
  `meta.width` null that the probe decodes (Pillow in the vision process failed somewhere in open /
  load / resize / encode); or, in the VISION log `moon_vision_server.log` (not `logs/<date>.log`;
  `vision_server/_config.py` `_LOG_PATH`, `RC_VISION_SERVER_LOG` overrides), a traceback naming
  `PIL` during the game. A `Vision crop failed` line there is context only: any token holder can
  write one with a junk `/vision` body.
- (f) CODE VERSION (s144 gated c19, PREP; record it in the tick line). The (b) / (e) text above
  describes `_maybe_obs_frame` WITHOUT the true-audit OBS-lane fix RM-1108 (on lane/true-audit,
  NOT landed on main at 2026-10-28 04:29 local). Test which code the listener runs by SYMBOL, not
  sha (a landing can rewrite it): the fix defines `_downscaled` in `vision_server/_frame.py`, so
  check that file at the checkout the (a) pid started from, and only count it as loaded when
  (a)'s `create_time` is after that code reached the checkout. With the fix loaded: (b) still
  holds, more strongly - every `obs` frame is fully decoded (`Image.open` plus `img.load()`), and
  `width` / `height` are always set, or the function returns None. But the (e) arm "an `obs` frame
  with `meta.width` null" can no longer occur. A vision-process Pillow failure on an OBS payload
  (open, load, resize or encode) now returns None. The GDI path then runs: it serves a
  `self_grab` frame (verdict PARTIAL, not FAIL-SIGNAL), or it refuses with its own `capture_skip`
  (`not_foreground`, `blank`). The OBS failure's only trace is a `log.debug` line ("obs frame
  undecodable, falling back to GDI" or "obs frame lane failed, falling back to GDI"). The vision
  log runs at INFO (`vision_server/_config.py` `basicConfig`), so that line is never written, and
  the OBS failure itself records no `capture_skip`. So with the fix loaded, a PARTIAL
  while OBS is enabled cannot tell "OBS yielded nothing" apart from "vision Pillow could not
  decode the OBS bytes". Record PARTIAL and leave the row open; do NOT read it as Pillow 13
  passing or failing. The (e) readback-exit-3 and PIL-traceback arms are unchanged. Gap filed as
  RM-1054 (cycle report).
Evidence contract: value = the four `s6.*` booleans, the two `stats_tie.*` booleans of each (a) run,
both (a) pids and `create_time`, the dist-info
name, `meta.source`, `meta.ts`, `meta.width` / `meta.height`, the probe's frame facts and the
after-run `frame_upload.calls`; source = the two tools' JSON (fields above); timestamp = the readback
`wall` and `liveclient.game_time`; predicate = this paragraph.
SUBSTITUTION check (answer it in the tick line): (b) alone is the probe's OWN Pillow decoding bytes
the relay served, NOT the vision process decoding anything - the compute half, and the whole of the
read-back as first filed (`tools/gated_frame_readback.py` docstring), so the filed S6 UNDERSTATES its
own question. (a) ties the loaded module to the vision process (memory map, not `pip show`, not this
checkout's interpreter); only the `obs` arm of (b) shows that process decoding a frame. If OBS is not
the frame source in the game (config `frame_source` false, or OBS yields nothing so the frame reads
`self_grab`), S6 cannot reach PASS that game: record PARTIAL and leave the row open. Synthetic
reach: no verdict holds without (d)'s live game window; inside it, a token-holding `/upload-frame`
with `source` `obs` would satisfy (b)'s frame facts, and (a)'s pinned pid plus its lifetime count of
0 exclude it (every upload is counted, `handle_upload_frame`; nothing outside the test helpers lowers
`_stats`). Not retro-fittable: (a)'s map and (b)'s frame are only readable while live.
Idle baseline (2026-10-27 07:3x local, no game): the listener started 2026-10-26 20:45 local, Pillow
13.0.0 METADATA dated 2026-10-22; `pil_loaded` false (no capture since start: `capture_skip`
`not_foreground` 2), `frame_upload.calls` 0, so `s6` reads `pil_loaded_in_process` false and its
other three checks None until a frame is taken. Positive control: the same reader on its own process
after `from PIL import Image` maps `site-packages\PIL` and reads `pillow-13.0.0.dist-info` version
13.0.0. Prior partial evidence (not a drain): the TFT
game of 2026-10-25 08:56 above decoded a `self_grab` frame in the PROBE under 13.0.0 ((b) probe half
only, TFT, not League). Reverses if: the vision server stops importing Pillow lazily (then (a)
proves nothing about use), `_maybe_obs_frame` stops gating `width` / `height` on a successful decode,
or `/upload-frame` stops recording `frame_upload`.
**S6 RE-CHECK (lane 9 PREP s144 cycle 106, 2026-11-08, source read at `7c6151f18`; NOT a tick;
PASS, (a), (b), (d) and the SUBSTITUTION check above unchanged).** (1) **`393c7f512` is a pre-rewrite
twin**, not reachable from HEAD or `main`: `.git/filter-repo/commit-map` maps it to `a1655b0c6`
(same subject, same committer time 2026-10-28 01:03:28 -0500); read `a1655b0c6` wherever (b) says
`393c7f512`. (2) **(f) is stale: RM-1108 HAS landed** (`692eec5fd`, 2026-10-30), so the "With the
fix loaded" branch of (f) is the live one: `_downscaled` `vision_server/_frame.py:254`, full decode
`Image.open` `:217` plus `img.load()` `:218` inside `_maybe_obs_frame` `:175`, and the (e) arm "an
`obs` frame with `meta.width` null" can no longer occur. (3) **The RM-1054 gap (f) describes is
CLOSED in code**: `095bc1820` (RM-1054) counts an OBS payload Pillow cannot decode as
`obs_lane.undecodable` (`_frame.py:220`) and any other lane failure, the re-encode included, as
`obs_lane.error` (`:243`); `5d84faab4` (RM-1214) and `b45f95028` (RM-1215) add the fetch reasons
`ws_error`, `auth`, `timeout`, `no_reply`, `source_missing`, `request_failed`, `bad_payload`
(`vision_server/_stats.py` `OBS_LANE_FAILURES` `:66-68`, via `_note_obs_fetch_failure`
`_frame.py:248`) and `gdi_lane` (`unavailable`, `error`); `/stats` serves both blocks (`get_stats`
`_stats.py:183`, keys `:195-196`). Each descends from the one before it (`692eec5fd` <
`095bc1820` < `5d84faab4` < `b45f95028`, all ancestors of `main`). `tools/gated_vision_pillow.py`
already passes them through in BOTH (a) runs (`stats_counters` `:146`, `obs_lane` `:159-170`, the
fetch reasons only when the server has them; `gdi_lane` `:171-174`), so the (a) JSON now carries
them with no tool change. CODE VERSION by symbol, read from the pinned listener's own `/stats` (not
this checkout): `stats.obs_lane` present = RM-1054 or later (so RM-1108 too); `stats.obs_lane.bad_payload`
present = RM-1215. (4) **Added predicate, stated before any game, for a listener whose
`stats.obs_lane` carries `bad_payload`** (on an older listener (f) stands as written). Delta = the
after-run's count minus the before-run's, same pinned pid. A `self_grab` (PARTIAL) game reads:
PARTIAL / OBS-EMPTY iff any fetch reason rose (record which; OBS yielded no frame, not a Pillow
signal); FAIL-SIGNAL (re-opens `cef8bfd22` for a measured re-check, closes and strikes nothing,
since bad OBS bytes give the same count) iff `obs_lane.undecodable` rose; `obs_lane.error` rising is
context only (it also counts non-Pillow failures such as the `core.obs_frame_source` import); every
`obs_lane` counter flat means no counted OBS failure in the window (for example flag off, a frame
from an earlier fetch, a blank OBS frame counted in `capture_skip.blank`, or an OBS fetch that names
no reason): PARTIAL as before. Lifetime counts that did not move between the two runs are
context, never a verdict input (the lane runs on every fetch, in game or not). A `gdi_lane` rise with no
frame served is NOT-YET. None of this can reach PASS: only an `obs` frame does. (5) **Cites re-read at
HEAD, all hold:** `handle_upload_frame` `_frame.py:455` (refusals `_record` `:472`, success `:579`),
`_frame_dims` `:433` (header read `:446`, used `:522`); `_crop_to_primary`
`vision_server/_inference.py:192` (header-only read and the 1920x1080 pass-through still forward the
original); `_LOG_PATH` `vision_server/_config.py:26`, `RC_VISION_SERVER_LOG` `:31`, `basicConfig`
INFO `:40-41`; OBS source default `Game Capture` `core/obs_frame_source.py:222`; `ocr_crops`
`core/moon_proxy.py:191` still has no production caller. (6) **Idle run** (2026-11-08 11:18 local,
`python -B tools/gated_vision_pillow.py --json`): exit 1, `nothing listens on :8889`; `:8888`,
`:2999` and `:8889/health` all curl 000, `ops/runtime/launcher_status.json` `halted` (last updated
2026-11-01T02:17:21Z). The 2026-10-27 listener and its baseline are gone; the next listener starts
from code carrying all four commits above, provided its checkout is at or past `b45f95028`.

**RM-752 follow-up READY (lane 9, s144 cycle 2, PREP only, no game up; NOT ticked): does Riot's
`:2999` accept a TLSv1_2-floor, default-cipher handshake, so `tools/liveclient_relay.py` can drop its
deliberate TLSv1 floor plus `ALL:@SECLEVEL=0` ciphers?** The question is the `Reverses if:` of
`docs/OPERATIONS.md` "TLS protocol floor (RM-752)" (LEDGER 1744; PKG WA8). Any League game (GATE 2 / 3
/ 4 / 5, or Jade once it is live). A TFT game can never answer it: the standalone TFT client serves no
`:2999`.
Probe: `python tools/gated_tls_2999_probe.py --json`, run TWICE at least 30 s apart. Each run makes
one GET of `/liveclientdata/gamestats`
per context, in this order: `relay` (the relay's own context rebuilt: TLSv1 floor, SECLEVEL=0),
`floor12` (`core/tls_policy.py` `client_context_noverify()`: TLSv1_2 floor, default ciphers),
`floor12_legacy` (TLSv1_2 floor, SECLEVEL=0 ciphers) and `tls13_only` (context only). `gamestats`
carries no player names or ids, and the tool prints JSON keys, never values.
Predicate, stated before any game. Both runs give the same `verdict`, and each run reads:
- `in_league_game` true. The tool computes it from four reads:
  - `/api/state` reads `mode_key` sr / aram / arena / brawl / jade with a non-empty `liveclient`,
    both before and after the handshakes.
  - `listener.names` (before) and `listener_after.names` are each exactly
    `["League of Legends.exe"]`.
  - `past_loading` is true: `state_before.game_time_s`, the numeric field, is above 0.
    `game_time` is only the `m:ss` display string.
- `relay_parity` true: a fail-closed pin. The tool hashes the canonical parse tree of every
  top-level relay statement that is TLS-relevant: it builds or tunes `_ssl_ctx`, makes a request,
  imports or names a TLS / HTTP module, or names `LIVE_URLS` / `fetch_live` / `_try_one`. Today
  that is the imports, `LIVE_URLS`, the `_ssl_ctx` block, `_try_one`, `fetch_live`, `upload` and
  `loop`. The hash must equal `_RELAY_TLS_SHA256`, which was set when `relay_context()` was checked
  against that code.
  - Any change there reads false, including a later override, an `options |=`, an alias, the
    floor moved under an `if` or into a function, a request that passes another context, and
    https dropped from `LIVE_URLS` or skipped in `fetch_live`.
  - Comments, formatting and non-TLS code do not count.
  - Out of its reach: a write through `globals()` or `sys.modules`, the process environment
    (`OPENSSL_CONF`), and another module's code that the relay calls into.
  - The same digest was measured on Python 3.12.13 and 3.14.4.
- `results[relay]` is OK. OK = `handshake` true, `status` 200, and `json_keys` contains `gameTime`.
  REJECTED = `handshake` false with `error_class` `ssl` or `reset`.
Then the verdict is:
- RAISE iff `floor12` is OK.
- RAISE-FLOOR-KEEP-CIPHERS iff `floor12` is REJECTED and `floor12_legacy` is OK.
- KEEP iff both are REJECTED.
- NOT-YET otherwise, including refused, timeout, a 404 during loading, and a run where the `relay`
  control itself fails.
A timeout is never a rejection. On this box a connect to a closed loopback port takes about 2 s.
Idle baseline 2026-10-27 08:2x local: every context was `refused` at 2023 .. 2062 ms, the verdict
NOT-YET, exit 1, `relay_parity` true. The relay's own log reads the same way. `fetch_live` keeps
only the LAST scheme's error, so every failure line is `http://1 -> ...`, refused or timed out (808
of them: 385 refused, 423 timed out).
Re-run idle 2026-11-08 11:48 local (s144 gated c107): the same - all four contexts `refused` at
2008 .. 2013 ms, `listener` empty, `past_loading` false, verdict NOT-YET, exit 1, Python 3.14.4,
OpenSSL 3.0.19 27 Jan 2026. `relay_parity` still reads true after the two relay commits since the
pin, both non-TLS: `a9fb7c7c5` (RM-828 (b)) and `71a51eee5` (RM-1710, LF log handler).
`TLS_MIN_VERSION` is unmoved at `core/tls_policy.py:27`, and `client_context_noverify` is
unchanged. `8373d2571` (RM-1175) only adds `client_context_verified`. The relay log now holds 902
`http://1` failure lines (387 refused, 475 timed out), its last line 2026-10-31 20:25.
What each verdict licenses (the merger's act, not the lane's; nothing is changed on a probe):
- RAISE meets the `Reverses if:` as written. Raise the relay inline to TLSv1_2, because it is
  served standalone and cannot import `core/`. Drop SECLEVEL=0. Then, in the next League game,
  read the relay back: the `liveclient_envelope.source` is `agent_push` with `age_s` < 3. That
  read-back is its own check and is not implied by this probe.
- RAISE-FLOOR-KEEP-CIPHERS: raise `minimum_version` only, and record the negotiated cipher.
- KEEP: the OPERATIONS keep stands, now on a measurement rather than the relay's old comment.
  Record `results[relay].tls_version`.
Evidence contract:
- value = the verdict; per context `handshake`, `tls_version`, `cipher`, `status`, `json_keys`
  and `error_class`; `relay_parity`; `listener.names` and `listener_after.names`;
  `past_loading`; the `python` and `openssl` strings;
  `liveclient_envelope.source` and `age_s`
- source = the tool's JSON
- timestamp = `wall`, `state_before.game_mode` and `state_before.game_time_s`
- predicate = this paragraph
SUBSTITUTION check (answer it in the tick line). The question is itself a handshake question, so a
probe answers it directly; this is not the compute half of something that RENDERS. What is
substituted is the CLIENT: the probe's interpreter, not the relay process, and a rebuild of the
relay's context, not the relay's object.
- Measured 2026-10-27 (read-only `schtasks /Query /XML`, paths compared in-process and never
  printed): the RC-LiveClientRelay task runs this repo's `tools/liveclient_relay.py`, byte-equal
  to the main checkout. It runs under `pythonw.exe` from the same install directory as the
  probe's `python.exe` (3.14.4, OpenSSL 3.0.19 27 Jan 2026). So the probe's OpenSSL is the
  relay's. STALE since the 2026-10-31 launcher cutover (s144 gated c107, S144-G-95): read-only
  `schtasks /Query /TN RC-LiveClientRelay` on 2026-11-08 answers "cannot find the file", and no task
  starts the relay. The rc-shell service host spawns it: `ops/launcher/services.json:48`
  (`liveclient_relay`, argv `tools/liveclient_relay.py`, both profiles), started as
  `[service_python()] + [<root>/tools/liveclient_relay.py]` (`ops/launcher/service_host.py:1391`
  `_resolve_argv`). `service_python()` (`ops/launcher/service_host.py:485`) is the `pythonw.exe`
  beside the host's own `python.exe`. The shell picks the host's interpreter
  (`rc-shell/src/launcher.js:254` `resolvePython`) as `RC_PYTHON`, then the canonical Python314
  (checkout launch only), then `<root>/python-embed` (packaged, or a checkout without the canonical
  one). So the probe's OpenSSL is the relay's ONLY for a checkout launch on the canonical
  interpreter with `RC_PYTHON` unset, and the relay's copy is the resolved backend root's, not
  necessarily the main checkout's.
- The day-of comparison (replaces the task read; read-only; paths compared in-process and never
  printed): `ops/runtime/launcher_status.json` reads `profile` `dev` and `mode` `owned`, and its
  `services` entry `liveclient_relay` reads `state` `running` with a `pid`. That pid's process
  (read-only `Get-CimInstance Win32_Process -Filter "ProcessId=<pid>"`) has `ExecutablePath` in
  the probe's `sys.executable` directory, and the file its `CommandLine` script path names has
  the same bytes as the main checkout's `tools/liveclient_relay.py`. Any other answer - `mode` `attach` or `blocked`,
  the relay entry not `running`, another directory (`RC_PYTHON` or `python-embed`), another copy -
  and the verdict is NOT-YET for the relay question. The probe still ran its handshakes, but
  under an OpenSSL the relay may not load. Record which leg failed. Idle 2026-11-08: `state`
  `halted` (updated 2026-11-01T02:17:21Z), relay entry `halted`, `pid` null, so there is
  nothing to compare.
- The tick line records `openssl` and the day-of comparison.
- `relay_parity` pins the relay's TLS-relevant code, which the rebuild was checked against.
- Who owns the port: `listener` and `listener_after` must each name League of Legends.exe alone,
  so a portproxy self-loop (memory `project_iphlpsvc_portproxy_2999`) or any other `:2999` listener
  reads NOT-YET. Known limit: it is a NAME check, with no exe path or signature, so a renamed
  process on `:2999` plus a pushed `liveclient` payload would pass. That takes deliberate forgery,
  not a fixture, and the tick line says so.
Synthetic reach: a loopback TLS server reproduces every verdict. `tests/test_gated_tls_2999_probe.py`
does RAISE and RAISE-FLOOR-KEEP-CIPHERS with real handshakes, and a TLSv1_1-only loopback server
gave KEEP on this box. That is why no verdict counts without `in_league_game` and the League-owned
listener. What the probe does NOT show is that a RAISED relay then delivers: that is the follow-on
read-back above.
Prior evidence on disk, not a drain:
- The relay log `logs/liveclient_relay.log` (first line 2026-08-03) holds 0 `fetch recovered`
  lines. That is silent, not negative: `data/match_history.db` holds no League game after its
  ARAM row of 2026-08-02 (every later row is TFT), so the relay has not faced a live `:2999`
  since logging began. Re-read 2026-11-08 (read-only): still 0 `fetch recovered` in 1181 lines,
  and still no League row after 2026-08-02. The newest row is TFT, 2026-10-25.
- The in-process readers (`vision_server/_relay.py` `_fetch_liveclient_direct`, using
  `ssl._create_unverified_context()`, which has a TLSv1_2 floor on 3.14; and `game_reader`
  `_get`) swallow every exception. So their existence still proves nothing.
Reverses if: the relay's TLS-relevant code changes (`relay_parity` then reads false, and
`tests/test_gated_tls_2999_probe.py` names the re-pin),
`core/tls_policy.py` `TLS_MIN_VERSION` moves, or the relay starts under another interpreter or from
another copy of the relay (since the 2026-10-31 cutover: the service host's `service_python()` or
backend root changes, `RC_PYTHON` is set, or a launch falls to `python-embed`; the day-of
comparison above catches each).

**AUTO-RELOAD SWEEP (s144 gated c21, RM-1055, PREP; NOT a tick).** The dashboard reloads itself
when a watched web asset changes (`web/js/main.js`: the `/api/ui-version` poller and the
`_hotReloadInit` `/api/asset-stamp` poller), so a merger landing that writes `web/` mid-game can
void a predicate that counts browser-sent requests or grades a dashboard render inside a window.
Two READY rows have that shape and now carry the before / after read with its NO_RESULT rule:
G1-07 (duo GET count and the DUO PICKS render) and G3-13 (the on-screen augment block). The other
READY / PREP rows below cannot be moved by a reload. Each predicate reads a server-side artifact, a
non-browser endpoint, a game-client screen, or a page-driven shadow jsonl graded on row contents,
never on row count: S6 (the vision process's frame decode), the RM-752 follow-up (the `:2999` TLS
handshake of the relay), G4-30 (Y-01; the match DB and the day log), RM-292 (c)
(`tft_live_data.json` keys), LT-02r (recorded `tft_qa` evidence and game frames), TFT-15 (LCU GETs
and the client planner), the GATE 8 READY block (`/api/state` and raw `:2999` field paths), G3-12
(PREP; `data/aram_coaching_data.json` `game_time_s` vs the probe's own `/api/state` read), G3-16
(`data/hz_choice_shadow.jsonl`, appended by `dashboard/_state_builder.py` `build_state`, so a
reload may add rows, but the predicate grades each row's `game_id` and `game_run_id`), the RM-869
live half (the coaching files' vision fields), G5-11 (the LCU subteam roster, the relay's Live
Client capture and the `focus_board` column of `data/arena_coach_shadow.jsonl`; nothing renders)
and G7-17 (`tools/arena_shadow_report.py` over that same jsonl, which `build_state` also appends
to, de-duplicated by round and action; its on-screen checks are game-client cards). An RC restart is
a different event and each row's own restart rule covers it. A NEW row whose predicate counts
browser requests or watches a render over time copies the G1-07 paragraph.

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
  **AGE RE-CHECK (s144 lane gated cycle 135, 2026-11-09, S144-G-122; PREP only, nothing ticked, nothing
  struck; no game: :8888 curl empty at 2026-11-09T08:12-06:00, RC halted since 2026-10-31).** THIS ROW
  IS ALREADY CLOSED - DO NOT RE-DRAIN IT. Both CHECKs passed live on 2026-07-20 and are recorded in the
  DRAIN SESSION 2026-07-20 block at the top of this file (CHECK 1 across all four champ-select shapes,
  q3140 / q2400 / q1750 / q400; CHECK 2 `champ_select` BYTE-IDENTICAL: True flag-ON vs flag-OFF). The
  per-gate "G1 6" in the OPEN paragraph never counted it: that line was written 2026-07-18
  (`2a7010203`), when only G1-01 to G1-06 existed; G1-00 was filed 2026-07-20 (`03409f03b`) and G1-07
  on 2026-10-27 (`7a16a47a6`). Only this in-place row was never marked; the other closed-that-night
  rows G2-34 / G2-35 are struck in place. TALLY NOTE (not edited here): G1-00 was filed without raising
  the 118, and the same night's drain subtracted all six closures including G1-00 (118 -> 112), so
  that step likely removed one row 118 never held; the per-gate line also sums to 118, not 111.
  The ADJUDICATED divergence is answered and shipped: the reader CARRIES `config` and `lcu_port`
  through (`dashboard/_lcu_inprocess.py`, block "config + lcu_port (G1-00 CHECK 2 follow-up,
  2026-07-20)", landed in `51dfc0cef`; pinned by `tests/rc2_l3/test_lcu_inprocess_config_port_l3.py`).
  The SEPARATE auto-accept bug (pref file `enabled:true` vs agent `config.auto_accept` false) was fixed
  by RM-1222 (`5e40fcccc`, 2026-10-31; `tests/test_lcu_agent_auto_accept_pref_sync_rm1222.py`). Both
  files: 25 passed at HEAD this cycle. NOT done and NOT this row: the flag flip. `RC_LCU_INPROCESS`
  is still DEFAULT-OFF (`dashboard/_state_builder.py` `_read_lcu_snapshot` reads `== "1"`) and since the
  2026-10-31 cutover it reaches RC by env inheritance only (see the EXTERNAL-LIFT row that cites
  `child_environment`); no ROADMAP / BACKLOG row owns a default flip. A drainer in a champ-select
  spends nothing here.
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
  **READY (lane 9 PREP s144 cycles 37-38, source read at `20ad30c7b`, re-diffed at `fc123ec87`: only
  the LOCK IN hold / focus carry moved, no card path; NOT a tick).** Three corrections to
  the residual, measured in source before any game: (1) the "build-order B-card" is no longer a card -
  B6 + B7 (QA 2026-07-03 slice A) merged it into the build chooser as the ORDERED SEQUENCE strip
  `#csv-builds-seq` inside `.csv-builds` (`web/js/panels/champ_select.js` `_csvBuildSeqStripHtml`;
  `tests/snapshot_panels/test_champ_select_view.py` `test_champ_select_merged_build_section`), and
  `#csv-sugg-counter-picks` in `_NEW_STATIC_SELECTORS` is a different card; (2) the DS skill order and
  personal build cards render on the SR path ONLY (`renderChampSelectView` calls `_csvRenderSuggestions`
  only when the mode is `sr`; `_csvRenderSuggestionsNonSr` never touches them), so the residual needs
  an SR DRAFT or blind select, not any lobby; (3) `my_champion` is the locked id OR the hover
  (`lcu/champ_select_shape.py`) and every card draws for a hover too, so LOCKED is graded on
  `my_completed` true. A fourth, REPRODUCED 2026-10-30 in headless Chromium through the page's own
  `renderChampSelectView` on the `?ui_mock=1&mode=sr` fixture: lock champion A, then a new select with
  no pick, then lock A again - BOTH the DS skill order and the personal build card stay HIDDEN with A's
  payload cached. Both renderers skip a repaint on an unchanged payload signature, and the champ-select
  gates hide the card directly on "no champion yet" without clearing that signature (RM-1162, from the s144 gated c38 report).
  So on the operator's long-lived rc-shell page the SECOND champ select on the same champion is
  expected to FAIL; that is the defect, not a probe error. (The `_csvComputeSig` render gate is NOT a
  cause: `_csvScheduleRender` clears the section signature before every post-fetch re-render.)
  **PROBE (read-only):** `python tools/gated_g101_cs_cards.py snippet` prints an async expression; in
  the real dashboard tab (operator Chrome DevTools console, or headless Chromium on
  `https://127.0.0.1:8888`), with the champ-select view up and your champion LOCKED, run it and save the
  JSON to `ops/runtime/g101/<n>.json` (gitignored). It reads `/api/state` itself (keeps only `lcu.phase`,
  `queue_id`, `is_aram`, `my_champion`, `my_champion_locked`, `my_completed` - never a puuid, a player
  name or another player's pick), maps the id to a slug through `/data/champions_index.json`, reads THE
  PAGE'S OWN cached payloads by importing `/js/panels/ds_skill_order.js` and
  `/js/panels/personal_build.js` (the same module instances the page loaded; only their getters run),
  waits two animation frames plus 0.5 s, then reads the three mounts (rendered box, text, row / chip
  counts), the host card box, page age, tab visibility, and when each route last answered (resource
  timing). Then `python tools/gated_g101_cs_cards.py grade --evidence ops/runtime/g101/<n>.json` (exit 0
  PASS, 1 FAIL, 3 INCONCLUSIVE, 2 bad input). Field paths: `/api/state` -> `lcu.champ_select.my_completed`
  / `my_champion` / `queue_id`; DOM `#csv-sugg-ds-skill-order .dsso-max`, `#csv-personal-build .pbw-row`,
  `#view-champ-select .csv-builds[data-champion]`, `#csv-builds-seq[data-bo-state]`.
  **PREDICATE (stated now, per card; the row PASSes iff all three PASS, FAILs iff any FAILs):** common
  gates first - origin `https://...:8888`, `ui_mock` off, `lcu.phase` == `ChampSelect`, `my_completed`
  true with `my_champion` > 0 (and equal to `my_champion_locked` when sent), a queue the page's own
  `_csvDetectMode` maps to `sr` (not an Arena or ARAM id, `is_aram` false; a custom SR lobby counts), page age >= 10 s,
  `#view-champ-select` and the cards' host `.csv-card` with rendered boxes, tab visible; any miss is
  INCONCLUSIVE. DS skill order PASS iff its box is rendered (w, h > 0; a box wins over a `hidden`
  attribute), title `Skill order`, `Max: <Q|W|E|R>( > ...)*`, `Ult: <n>(/<n>)*`, and the champion / Max /
  Ult text equal the page's cached payload for this champion. "Rendered" is a non-empty box; a card
  below the fold still PASSes with a printed note (scroll it into view for the screenshot). Personal build PASS iff rendered, title
  `Your best build`, a sub line `<champion>: items you win with ...` matching the page's payload and
  `.pbw-row` count == the payload's item count >= 1. Strip PASS iff `.csv-builds` is for this champion
  and mode, `#csv-builds-seq` `data-bo-state` `ready`, tag `ORDERED SEQUENCE`, 1 to 7 chips, rendered.
  FAIL iff a mount is absent (`.csv-builds` absent for a locked champion; the strip absent inside it);
  or shown but malformed; or a ready strip with no box; or a card HIDDEN while the page's own cache holds
  a non-empty payload for this champion (DOM read after the cache read, or the page's own fetch answered
  >= 5 s before, status 2xx or unrecorded) AND the build chooser already carries this champion's slug -
  HIDDEN_WITH_DATA, the RM-1162 shape. The page renders from its pushed state (about every 2 s), not
  from the snippet's own `/api/state` read, so a chooser still drawn for another pick is state lag,
  INCONCLUSIVE (verifier c37). INCONCLUSIVE also: no
  payload cached yet; a payload with no content (`ok` false / no `max_order`; personal build below its
  sample threshold - hidden BY DESIGN, the confidence is printed); rendered text not equal to the
  payload (render lag); a strip still `loading` ("computing...") or `empty` - the `empty` state is
  unreachable (RM-1163, same report) and the page's build-order cache key needs the archetype, which the
  snippet cannot read, so a stuck strip is never graded FAIL.
  **IDLE SMOKE (2026-10-30, no game, read-only page loads in headless Chromium):** the live dashboard
  graded INCONCLUSIVE `NOT_IN_CHAMP_SELECT` (phase None). On the ui_mock SR fixture the snippet read all
  three cards populated (skill order Q > W > E, 6 personal-build rows, 6 strip chips) and the module
  import returned the page's own caches (one entry each). With `/api/state` stubbed to a locked copy of
  the fixture and the provenance substituted in scratch (not committed), a fresh page graded PASS on all
  three cards, and a page driven through lock / no-pick / lock graded FAIL HIDDEN_WITH_DATA on the skill
  order and personal build cards (strip PASS). That proves the selectors, the cache read and both grade
  paths only; ui_mock makes it NOT evidence.
  **DRAIN STEPS (SR draft or blind, own champion LOCKED):** (a) wait about 5 s after the lock with no
  pick change, then on the page as it is (no reload) run the snippet,
  save, grade - a FAIL here on a second same-champion select is RM-1162 live evidence, keep it; (b)
  press F5, wait about 15 s with no pick change, run the snippet, save, grade. The PASS bundle plus its
  `captured_at`, queue id and per-card lines is the render evidence; no champion id goes into this file.
  The per-page UI-audit ritual the residual also asks for stays an operator-present act (it needs a
  screenshot; a lane takes none).
  **SUBSTITUTION CHECK:** `tests/test_gated_g101_cs_cards.py` reaches PASS from hand-built bundles and
  from the real renderers' markup drawn under node with a stub element - neither saw the dashboard. A
  GET of `/api/ds-skill-order` / `/api/personal-build` or a POST of `/api/build-order` is compute only,
  and the page-cache tie proves only that the drawn text is THIS champion's. Only a bundle from the real
  tab, origin, lock and page age checked, ticks this.
- **G1-02** `[CS-CAPTURE]` (was A5) rc-shell PRE-GAME LOBBY `lcu.lobby.members[]` render (YOUR MAINS /
  PARTY / MY TOP-8; if empty, capture the agent's live `/lol-lobby/v2/lobby` read + `_slim_lobby_member`
  output) + eyeball the overlay surface gate `bc4625d8` (companion in lobby/CS, lean HUD once
  liveclient populates). SOURCE: ledger 2026-06-20.
  **AGE RE-CHECK + READY (lane 9 PREP s144 cycle 122, 2026-11-09, S144-G-109; NOT a tick, NOT a
  re-open).** Status: the DRAIN SESSION 2026-07-20 record at the top of this file ("ADVANCED WITH
  RECORDED EVIDENCE") evidenced the lobby payload and the three list renders (queue 1750). Two halves
  are still owed: (i) the overlay surface-gate eyeball, which no record in this file shows as seen; (ii)
  a render re-confirm, because RM-326 (LEDGER 1324, 2026-09-04) put a signature gate on the party-list
  render AFTER that evidence. (1) CITE DRIFT: `bc4625d8` above (and `b9cb0092` on G1-04) do not resolve
  at HEAD (`git cat-file -t` fails; neither string is in `<git common dir>/filter-repo/commit-map`;
  cause not measured). Matched by date + subject + files, an inference and not a map: `3439a028c`
  (2026-06-20, "fix(rc-shell): overlay HUD only on a live game, not a pre-flipped lobby mode_key";
  touches `rc-shell/src/main.js`, `overlay_state.js`, `test/overlay_state.test.js`; an ancestor of
  HEAD). For G1-04 the LOBBY1 fix is `a890a5524` (2026-06-08, same method). Current homes: the gate
  `liveGameFromState` at `rc-shell/src/overlay_state.js:137` (true when `liveclient` is a non-empty,
  non-array object, OR, since S134 T1 at `:150-157`, when `mode_key` is "tft" and `lcu.phase` is
  "InProgress": a TFT match leaves `liveclient` empty), `surfaceForMode` `:113`, `resolveSurface`
  `:119`, `GAME_MODES` `:35-37` (sr, aram, arena, tft, brawl, game); `rc-shell/src/main.js` `pollState`
  polls `/api/state` (4000 ms socket idle timeout, `:1659`), sets `lastInGame` at `:1667` and calls
  `refreshSurface` (`:1629-1631`), which reaches `applySurface` (`:1574`). Payload:
  `lcu/snapshot_shape.py:500-537` builds `state["lobby"]` from `_slim_lobby_member` (`:195`, wire dict
  at `:248`); `/api/state` carries that snapshot as `lcu` (`dashboard/_state_builder.py:1086`), so the
  field path is `lcu.lobby.members[]`. Render mounts: `web/index.html:945` `#lv-members-list`, `:987`
  `#lv-mainchamps-list`, `:1000` `#lv-top8-list`; `_renderPartyMembers` `web/js/main.js:5169` (empty
  text "no members visible - LCU agent needs to forward lcu.lobby.members[]" at `:5180`, signature
  `ul.dataset.lvPartySig`), `_renderMainChamps` `:4897`, `_renderTop8` `:6345`. (2) PREDICATE DEFECT,
  the June "flips to the lean HUD" is no longer the whole rule: `applySurface` layers two persisted
  settings over the surface. `keepCompanion` (`overlay_state.js:322`, default false `:529`) keeps the
  companion SHOWN in game, and the overlay content toggle (`overlay.toggle.visible`,
  `rc-shell/src/overlay_toggle.js:129-137`, applied at `:324-331`) keeps the HUD HIDDEN when OFF. Both
  live in `<appData>/Amberstone Shell/rc-shell-state.json` (one path, no space before the file name) as
  `overlay.settings.keepCompanion` and `overlay.toggle.visible`. Baseline read this cycle (idle,
  read-only): keepCompanion false, toggle.visible true (file mtime 2026-10-31T21:17 local). A re-confirm
  that does not read them first false-FAILS the moment the operator moves either. (3) OVERLAP: RM-1384
  (GATE 2, an operator DECISION owed: the overlay window in champ select and loading) may change the
  champ-select half; if RM-1384 lands a code change, re-read `liveGameFromState` before using the CS
  half below. PROBE (stated before any game; all reads): before the lobby, read keepCompanion = K and
  toggle.visible = V from the state file above (absent -> false / true). In a real LCU lobby (phase
  Lobby), `curl -sk https://127.0.0.1:8888/api/state` -> `lcu.phase`, `lcu.lobby.queue_id`,
  `len(lcu.lobby.members)`, `lcu.lobby.party_size`, and the KEY NAMES of `lcu.lobby.members[0]`; in the
  same minute, a DOM read of the lobby view (the rc-shell companion, or headless Chromium on the same
  origin) -> count of `#lv-members-list li.lobby-member-row:not(.is-placeholder)` (with members
  non-empty the render always draws `PARTY_MAX_SLOTS` = 5 rows, `web/js/main.js:5033`, and an empty slot
  is `lobby-member-row is-placeholder`, `:5246-5250`) and whether `#lv-mainchamps-list` /
  `#lv-top8-list` hold rows. Then the rc-shell window state in lobby, in champ select, and once
  `liveGameFromState` turns true; from game start until the surface flips, sample the `/api/state`
  response time every 2 s (`curl -sk -o /dev/null -w "%{time_total}"`). PREDICATE: PASS iff (a) members
  is non-empty (`party_size` is `len(members)` at `lcu/snapshot_shape.py:535`, so it is no separate
  check); (b) the non-placeholder row count equals len(members), and the "no members visible" text is
  ABSENT while members is non-empty; (c) in lobby and champ select (`liveclient` empty and `lcu.phase`
  not InProgress in the same poll) the companion is shown and the overlay HUD is not; (d) once
  `liveGameFromState` turns true (`liveclient` non-empty; in TFT, `lcu.phase` InProgress instead), the
  HUD shows iff V is true, the companion stays shown iff K is true, AND the overlay ON/OFF icon window
  shows (it shows on the OVERLAY surface whatever V is, `overlay_toggle.js:330`; without it, K true + V
  false would look exactly like the lobby state and a shell that never flips would pass), within the
  bound below. BOUND for (d), measured from the code, not a guess: about 10 s when the poll that
  straddles game start succeeds (up to 4000 ms in flight - a socket idle timeout, `main.js:1659`, not a
  hard cap - then the base `pollMs` 2000 ms wait, `overlay_state.js:48`, then up to 4000 ms more); about
  12 s after one failed poll (`nextPollDelay(1, 2000)` = 4000 ms, `overlay_state.js:270-281`); about 24
  s after two (the wait doubles); and NO fixed ceiling while polls keep failing (each further failure
  adds up to 4 s in flight plus a wait capped at `pollMaxMs` 15000, `:49`). A just-created overlay
  window also waits for its ready-to-show before the first show, and that window is created lazily at
  the flip (`createOverlayWindow`'s one call site, `main.js:1597`), so the first game after a shell
  launch pays its first paint too. RULE: the row asks whether the surface flips, not how fast, so (d)
  PASSES on the expected state and records the delay. A timing FAIL needs the surface still wrong 30 s
  after `liveGameFromState` turns true with every sampled `/api/state` time 4 s or less (30 s covers two
  failed polls, about 24 s, plus that first paint). If any sample is over 4 s there is no fixed bound: a
  late flip is the 2026-07-11 slow-poll class, recorded with its delay, NOT a FAIL of this gate; a
  surface that NEVER flips before the game ends is a miss either way. Halves (c) and (d) both assume no
  panic hide is active (`resolveSurface` `:119-123` hides both windows), and (d) assumes `mode_key` is
  in `GAME_MODES`; record both. A lobby of more than 5 members (TFT or custom) is out of scope for half
  (b): the render draws at most `PARTY_MAX_SLOTS` rows. FAIL on any miss, and on (c) with the HUD up
  while `mode_key` is pre-flipped and `liveGameFromState` is false (the exact bug `3439a028c` fixed).
  EVIDENCE CONTRACT: per read, the value (counts, key names, queue_id, surface), the source
  (`/api/state`, DOM read, window state), an ISO timestamp, and the context (LCU phase, K, V). Record
  KEY NAMES and COUNTS only, never a `puuid`, `riot_id` or summoner name value (RM-906). SUBSTITUTION
  CHECK: NOT evidence - the `ui_mock` lobby snapshot (`tests/snapshot_panels/test_lobby_view.py`), the
  shell unit tests (`rc-shell/test/overlay_state.test.js`,
  `rc-shell/test/overlay_phase_contract.test.js`), a payload read with no render read, a render read
  from a different minute than the payload, a `mode_key` value alone (it pre-flips in the lobby), or a
  browser tab standing in for the rc-shell window on half (c)/(d). Half (c)/(d) is a window-state
  question, so the glance or a window enumeration IS the test; the compute half answers the wrong
  question.
- **G1-03** `[RE-FILED 2026-10-24: CS-SCENARIO -> CS-CAPTURE, draft lobby only]` (was A3) CC-conditional
  pairing UI renders on champ-select (`a685a530`) - ~~needs a CC-pairing lobby to roll; never rolled
  2026-07-04. Rides every champ-select at any gate.~~ **MIS-FILED TAG (lane 9 PREP s133, source read at
  `373c693bb`, adversarial pass PARTLY -> corrected below; NOT a tick).** The ally CC-PAIRING card (B12)
  was REMOVED from champ select 2026-07-03, the day before "never rolled": `web/js/panels/champ_select.js:49-53`
  and `:2113`, `web/index.html:1151-1153`, pinned absent by `tests/snapshot_panels/test_champ_select_view.py:56`
  and `tests/test_cs3_panel_relocation_dom.py:60` (backend `/api/cc-pairing` stays). `a685a530` does not
  resolve and is not in `.git/filter-repo/commit-map`. The ONLY surviving champ-select CC-conditional
  surface is the pressure chip `#csv-sugg-cc-conditional-pressure` (`web/index.html:1133-1135`, renderer
  `web/js/panels/cc_conditional_pressure.js:147`, gate `champ_select.js:1788-1819`, reached every render via
  `_csvRenderTeamAnalysis` `:1947`), and it has NO CC scenario gate: route "scored" = did not raise
  (`dashboard/routes_cc_conditional_pressure.py:205-224`), zero CC on both sides still answers ok in the
  `warn` tier (`:247-249`). Its one real gate is a MODE condition: hidden while `their_team` is empty
  (`champ_select.js:1796-1799`; `lcu/champ_select_shape.py:436` passes LCU `theirTeam` through), so expect
  HIDDEN in blind ARAM / Mayhem select (LCU behaviour, not proven in source - record it, not a fail).
  **CHECK (any DRAFT champ-select once one enemy pick is visible, e.g. q400 / q420):** predicate stated
  first - PASS iff `lcu.champ_select.their_team[]` has a `championId > 0` on `/api/state` AND the rendered
  champ-select view shows `#csv-sugg-cc-conditional-pressure` with `hidden` false and a non-empty
  `data-cc-cond-tier` in {`good`, `warn`, `bad`}; FAIL = still hidden with both rosters committed. A GET
  of `/api/cc-conditional-pressure` is the COMPUTE half only (SUBSTITUTION) - never tick from it.
  **READY (lane 9 PREP s144 cycle 36, source read at `b14160751`; NOT a tick).** The predicate above is
  TIGHTENED before any game, for two traps measured in source: (1) `web/index.html` ships the chip with
  `data-cc-cond-tier="warn"` already set, so a non-empty tier attribute proves nothing on its own; (2) the
  chip sits inside the TEAM ANALYSIS drawer `#csv-ta-body`, which is COLLAPSED by default
  (`champ_select.js` `_csvTaOpen` reads sessionStorage `csv-ta-open`; `if (body) body.hidden = !open;`),
  so `hidden` false on the chip is not "renders". A third trap, reproduced under node: the renderer
  skips a repaint when the payload signature is unchanged (`cc_conditional_pressure.js`
  `renderCcConditionalPressure`, the `_CCP_SIG` early return), but the gate hides the chip directly
  without clearing that signature, so a chip hidden once stays hidden for a later identical payload -
  a hidden chip is graded only on a dashboard RELOADED in this lobby. A fourth, MEASURED 2026-10-30 in
  headless Chromium on the `?ui_mock=1&mode=sr#champ-select` fixture: the SHOWN `#view-champ-select`
  keeps its `hidden` attribute while its computed display is `block`, so view and chip are graded on
  rendered boxes (`getClientRects`), never on a `hidden` attribute. A fifth: "committed" ids include
  HOVERS (`lcu/champ_select_shape.py` `_team_picks`, `championId` = locked or `championPickIntent`), and
  a hover change starts a route fetch that resource timing does not list until it ends, so the page's
  last LISTED fetch can be for the previous roster with the same counts - the tie is by NAME and mode.
  **PROBE (one command each, read-only):** `python tools/gated_g103_cc_pressure.py snippet` prints an
  async expression; in the real dashboard tab (operator Chrome DevTools console, or headless Chromium
  on `https://127.0.0.1:8888`), with the champ-select view up, run it and save the returned JSON to
  `ops/runtime/g103/<n>.json` (gitignored). It reads `/api/state` itself (keeps only `lcu.phase`,
  `lcu.champ_select.queue_id` and the committed `my_team[]` / `their_team[]` `championId`s - never a
  puuid or a player name), maps those ids to champion slugs through `/data/champions_index.json` (the file
  the page's own `resolveChampNames` reads), the view / drawer / chip DOM, the chip box, `performance.now()` as page age, and the
  `/api/cc-conditional-pressure` URL the PAGE last fetched (resource timing), re-fetched once for a tie.
  Then `python tools/gated_g103_cc_pressure.py grade --evidence ops/runtime/g103/<n>.json` (exit 0 PASS,
  1 FAIL, 3 INCONCLUSIVE, 2 bad input).
  **PREDICATE (stated now):** PASS iff origin `https://...:8888`, `ui_mock` off, `lcu.phase` ==
  `ChampSelect`, >= 1 ally and >= 1 enemy `championId > 0`, `#view-champ-select` rendered, the chip not
  hidden with tier in {good, warn, bad} AND the matching label (FAVORABLE / EVEN / AT RISK) AND both
  rows "Enemy can chain on one target" / "You can chain on one target" reading `<n>.<n>s` AND a verdict
  line, AND on screen (the chip's rendered box is visible with width and height > 0), AND tied to THIS
  roster: the page's last route URL (resource timing) carries this roster's ally / enemy names and mode
  (the queue -> mode map of the `champ_select.js` gate) and the rendered tier / seconds match its body
  within 0.05 s. FAIL iff the chip is captured as absent (`chip_present` false); or shown but malformed
  (tier / label / rows / verdict captured and wrong or null); or populated with the drawer proven OPEN
  (`#csv-ta-body` hidden false) and no rendered box; or hidden (attribute set AND no rendered box - a
  rendered box wins over the attribute) in a VISIBLE tab on a page reloaded in this lobby and captured
  10 to 90 s after the reload, with the page's last route fetch SEEN, tied to this roster by name and
  mode, its status 2xx or unrecorded, and its body `ok` true. A field the bundle never captured, any tie
  missing or off, no route fetch seen, a background tab, a non-2xx page fetch or a non-ok body is
  INCONCLUSIVE (a request still in flight is not listed; a non-ok body hides the chip BY DESIGN - file
  that against the route, not this row).
  INCONCLUSIVE: drawer COLLAPSED (click the TEAM ANALYSIS head, capture again), BLIND (no enemy pick:
  ARAM / Mayhem select - record, not a fail), not in ChampSelect, or a provenance miss.
  **IDLE SMOKE (2026-10-30, no game, read-only page loads in headless Chromium):** the live dashboard
  graded INCONCLUSIVE `NOT_IN_CHAMP_SELECT` (phase None; chip hidden yet `data-cc-cond-tier` already
  `warn`, trap 1 seen live). On the ui_mock SR fixture the snippet read a populated chip (FAVORABLE, two
  rows, verdict line), box 0 x 0 with the drawer shut (COLLAPSED) and about 538 x 143 after a click on
  `#csv-ta-head`, and the page's own route URL was found and re-fetched ok; the fixture's ids mapped
  through `/data/champions_index.json` tied to that URL by name and mode (5 + 5, SR). That run proves the
  selectors, the box read and the name tie only; ui_mock makes it NOT evidence.
  **DRAIN STEPS (draft lobby, q400 / q420):** wait for the first enemy pick, press F5 on the dashboard,
  wait about 15 s with no pick or hover change, open TEAM ANALYSIS, run the snippet, save, grade. One PASS bundle plus its
  `captured_at`, queue id and verdict line is the evidence; do not paste champion ids into this file.
  **SUBSTITUTION CHECK:** `tests/test_gated_g103_cc_pressure.py` reaches PASS from hand-built bundles and
  from the real renderer's markup drawn under node with a stub element - neither saw the dashboard. A
  route GET (or the route body inside the bundle) is compute only; the tie just proves the rendered
  numbers are THIS roster's. Only a bundle from the real tab, origin and page age checked, ticks this.
  **AGE RE-CHECK (lane 9 PREP s144 cycle 137, 2026-11-09, S144-G-124; source read at `918a0c916`; NOT a
  tick, NOT a re-open; still READY for a draft lobby).** The READY predicate, the five traps and the probe
  hold; only line cites moved. (1) THE PREDICATE HOLDS: the gate `_csvRenderCcConditionalPressure`
  (`web/js/panels/champ_select.js:1925-1957`, was 1788-1819) still hides the chip when either side has no
  `championId > 0` (`:1934-1937`, was 1796-1799) and maps the queue to the same SR / ARENA / KIWI / ARAM
  modes (`:1947-1952`); it is reached from `_csvRenderTeamAnalysis` (`:2077`, call at `:2084`; that
  function is called at `:877` and `:1123`, not the old `:1947`). The drawer default is unchanged
  (`_csvTaOpen` `:1999`, sessionStorage key `csv-ta-open` `:1998`, `if (body) body.hidden = !open;`
  `:2097`), and the whole `#csv-team-analysis` block is hidden when no chip in it is visible (`:2090-2091`),
  which the snippet already captures. (2) TRAPS 1 AND 3 HOLD: `web/index.html:1142-1144` (was 1133-1135)
  still ships `data-cc-cond-tier="warn" hidden`; `renderCcConditionalPressure`
  (`web/js/panels/cc_conditional_pressure.js:147`, unchanged) still returns early on an equal
  `_CCP_SIG` (`:151`) and the gate still sets `block.hidden = true` without clearing it, so the
  reload-in-this-lobby rule stays. (3) THE PROBE STILL MATCHES THE DOM: every class the snippet reads
  (`cc-conditional-pressure-row`, `-row-label`, `-row-value`, `-tier`, `-verdict`) is in the renderer
  markup (`cc_conditional_pressure.js:183-196`), the route prefix `/api/cc-conditional-pressure?` is the
  page's own fetch (`:82`), and `web/data/champions_index.json` exists; `tests/test_gated_g103_cc_pressure.py`
  ran 97 passed at `918a0c916` (compute half only, see SUBSTITUTION CHECK). (4) CITE DRIFT, no
  behaviour change: route `_side_conditional` is `dashboard/routes_cc_conditional_pressure.py:206-243`
  (was 205-224; a failed per-champion compute is skipped, so "scored" still means "did not raise"),
  zero conditional CC on both sides still answers ok in `warn` at `:268-270` (was 247-249), and both
  sides unscored is `ok` false `no_champions` (`:257-262`), which hides the chip by design;
  `lcu/champ_select_shape.py:438` (was 436) passes `theirTeam` through `_team_picks` (`:261`), which still
  surfaces `championPickIntent` hovers (`:289`, trap 5). The B12 removal notes are `champ_select.js:49-53`
  (unchanged) and `:2279-2280` (was 2113) and `web/index.html:1160-1162` (was 1151-1153); the absence
  pins `tests/snapshot_panels/test_champ_select_view.py:56` and `tests/test_cs3_panel_relocation_dom.py:60`
  hold. `a685a530` still does not resolve and is not in the commit map. (5) PREREQUISITE: the probe needs
  the live dashboard on `https://127.0.0.1:8888`, which no task starts since the 2026-10-31 launcher
  cutover (rc-shell `--profile dev` only); at 2026-11-09T09:13-06:00 the :8888 curl was empty and
  `:2999` answered nothing, so no game and no lobby this window.
- **G1-04** (was A4 + QA24) LOBBY1 top-8 friend-invite live verify (`b9cb0092`) + the QA24 non-friend
  invite path end-to-end + the operator-reported defect that inviting others does not send unless the
  confirm dialog is accepted. BLOCKED ON: a real invite target / second account. SOURCE:
  docs/ORCHESTRATION_PLAN.md:63.
  **AGE RE-CHECK + READY (lane 9 PREP s144 cycle 133, 2026-11-09, S144-G-120; NOT a tick, NOT a
  re-open; still BLOCKED on a second player).** The row bundles THREE halves and they no longer share a
  status. (1) CITE DRIFT: `b9cb0092` does not resolve at HEAD, and neither does the 2026-07-01 resync's
  `1f4f4118` (`git cat-file -t` fails on both); the LOBBY1 fix is `a890a5524` (2026-06-08, "fix(lobby):
  LOBBY1 - resolve Top 8 / friends invites past dead by-name endpoint", same date + subject match as
  G1-02's note). `docs/ORCHESTRATION_PLAN.md:63` no longer holds LOBBY1: the row now lives at
  `docs/ORCHESTRATION_FINDINGS_ARCHIVE.md:66`. `tools/gamepc_lcu_agent.py` is gone; the code is
  `tools/lcu_agent.py`. Current homes: resolver `_resolve_invitee_summoner_id` `tools/lcu_agent.py:454`
  (order: summoner_id, puuid via `summoners-by-puuid-cached`, a `/lol-chat/v1/friends` scan, then the
  legacy by-name GET at `:512-520`), handler `lobby.invite_player` `:1152-1171` (POST
  `/lol-lobby/v2/lobby/invitations` body `[{"toSummonerId": <id>}]`, envelope `ok` / `err` / `riot_id`
  / `summoner_id` / `resolved_via`), allowlist `dashboard/routes_loadout.py:107` and `:164`; UI click
  `web/js/main.js:6491-6506` in the `_renderTop8` (`:6345`) wiring, result poll `lcuPollResult` `:191`
  -> `/api/lcu-cmd-result?id=` (`dashboard/routes_loadout.py:776`, relayed from :8889); offline pins
  `tests/test_lobby_invite_resolution.py` (stubbed `lcu_request`, live arm behind `RC_LIVE_LOBBY=1`).
  (2) LOBBY1 FRIEND HALF - still owed live, predicate below. (3) QA24 NON-FRIEND HALF - PREDICTED TO
  FAIL by code reading, so this is a code defect first and a live check second. The Top 8 add-flow
  stores `riot_id` only (`web/js/main.js:6543-6545`, no summoner id, no puuid), and the click sends
  `summoner_id: target.summoner_id || target.summonerId || 0` (`:6501`), so a non-friend entry reaches
  only the legacy by-name GET, which the resolver's own docstring (`tools/lcu_agent.py:457-458`) says
  404s on current clients: the result is `ok: false`, "could not resolve summoner". The offline test
  `test_falls_back_to_by_name_when_not_a_friend` (`tests/test_lobby_invite_resolution.py:163`) stubs
  that dead route as answering, so it is green while proving nothing about a current client. A
  measured Riot ID route already exists in the repo: `/lol-summoner/v1/alias/lookup?gameName=&tagLine=`
  (`tft/tft_scouting.py:39-40`, "verified on the local account 2026-10-25"; call at `:942`). Filed as a
  MERGER FOLLOW-UP for a code lane, not built here (outside the gated write set). (4) CONFIRM-DIALOG
  CLAUSE - CLASS-2 CANDIDATE (intended behaviour filed as a defect). `if (!window.confirm(...)) return;`
  at `web/js/main.js:6495` is the designed gate before an outbound social action, present since the
  invite was first wired (`eaafc97c7`, 2026-05-12, s171). The clause entered this row in the
  2026-07-18 reorganisation (`7fc017450`) with no source; it is not in the A4 text of 2026-07-01 nor in
  the archived LOBBY1 row. Only a dialog that never SHOWS would be a defect, and that is what the live
  half checks; "does not send unless accepted" is the spec. PROPOSAL only: drop the clause or reword it
  to "the confirm dialog shows and gates the POST"; a human edits the row.
  PROBE (attended lobby with a second player who is a friend, plus one non-friend Riot ID in Top 8):
  before clicking, read `curl -sk https://127.0.0.1:8888/api/state` -> `lcu.phase` (Lobby) and
  `lcu.lobby.members[]` count; click Invite on the friend row; note whether the dialog shows; press OK;
  read the envelope from `/api/lcu-cmd-result?id=<id>` (the id is the `/api/lcu-cmd` POST reply; a 404
  `pending` is normal for the first poll); then a read-only LCU `GET /lol-lobby/v2/lobby/invitations`
  (no RC route serving it was found this cycle; the attended session runs it), or the second player's
  word that the invite arrived; repeat once with
  Cancel and once on the non-friend row. FIELD PATHS: `result.ok`, `result.resolved_via`,
  `result.summoner_id`; invitations list `toSummonerId` + `state`. PREDICATE, stated before any game:
  friend PASS iff the dialog shows, OK yields `result.ok == true` with `resolved_via == "friends"`, and
  the invitations list (or the invitee) shows that summoner id within 10 s; Cancel PASS iff no new
  invitation row appears. Non-friend: the PREDICTED value is `ok == false`, "could not resolve
  summoner"; recording that value CONFIRMS the defect in (3), it does not drain QA24. QA24 drains only
  after the resolver gains a working non-friend route, with the same predicate and
  `resolved_via` naming that route. EVIDENCE CONTRACT: the envelope JSON, the invitations read, an ISO
  timestamp, queue id and lobby phase; no Riot ID, summoner id or puuid of a real player copied into
  this file (RM-906): write "friend", "non-friend" and the `resolved_via` value only.
  SUBSTITUTION CHECK: `tests/test_lobby_invite_resolution.py` reaches every envelope shape from stubs,
  and `ok: true` from the agent only means the POST returned no error - it is compute plus transport,
  not delivery. Only the invitee's client (the second player seeing the invite, or the invitations list
  showing the row) answers SENT; an `ok: true` alone does not tick the friend half.
- **G1-05** `[BLOCKED - RE-TAGGED 2026-07-18]` (was A11) OVL2 Pengu Surface C live validation
  (`7ddada96`). **RE-TAG source: this GATE 1 row; destination: BLOCKED - it is neither drainable by a
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
  session. Cited `7ddada96` does not resolve in this repo (4 of GATE 1's 5 cited hashes do not - they
  are pre-cherry-pick worktree SHAs per the `docs/history_notes.md:4468` merge workflow: a systemic
  citation defect, not fabrication). SOURCE: docs/ORCHESTRATION_PLAN.md:82.
  **AGE RE-CHECK (lane 9 PREP s144 cycle 136, 2026-11-09, S144-G-123; NOT a tick, NOT a re-open; still
  BLOCKED on the same operator decision, so do not count it in a gate session).** Three facts in the
  2026-07-18 re-tag no longer hold, and one rationale it inherited was never true. (1) THE 6 TESTS ARE
  GONE, not skipping: `tests/test_pengu_plugin_skeleton.py` was deleted at `9a6160f06` (2026-08-06,
  RM-119 B4 skip audit, finding 4 "PENGU REMEDY WITHDRAWN; MODULE RETIRED INSTEAD": pointing a live
  guard at `docs/_archive/**` would un-retire quarantined content, and reviving `pengu/` is a product
  decision that slice did not own). Per that commit's non-vacuity record, a re-injected `pengu/` skipif
  fails `tests/test_skip_condition_hygiene.py` as `ROTTED: was-tracked-now-gone=pengu`, so whoever un-archives
  must restore the module from git with the stub, not re-add the skip. (2) THE STUB IS UNCHANGED: the
  archived blobs are 1728 / 4463 / 2137 B (README.md / index.js / panel.css), identical at HEAD and at
  the rename `d0689e736` (2026-07-07, `pengu/ -> docs/_archive/2026-07-07-pengu-stub/`, 100 percent
  rename), and the same at the build `43107004f`, so the stub has never changed. The 1775 / 4575 / 2204
  recorded above are not a content change: they read as CRLF working-copy sizes (blob + one byte per
  line, 45 / 110 / 67 lines, gives 1773 / 4573 / 2204 - exact for panel.css, 2 B short for the other
  two, a gap not explained here). (3) CITE DRIFT: `7ddada96` does not resolve; the OVL2
  build is `43107004f` (2026-06-15, "feat(pengu): OVL2 Pengu Surface-C plugin stub + client-origin-gated
  CORS"; the archive table's `aab53e37` does not resolve either). `docs/ORCHESTRATION_PLAN.md:82` no
  longer holds OVL2: it is `docs/ORCHESTRATION_FINDINGS_ARCHIVE.md:85` (DONE, "live validation OWED").
  `ROADMAP.md:58` is now `ROADMAP.md:155`, RM-15 OPEN (c) "Phase 6 Pengu in-client panels, OPTIONAL" -
  still open. (4) MIS-CITED RATIONALE: the rename commit `d0689e736` gives "settled dead-end per
  CLAUDE.md", but the only Pengu line in CLAUDE.md, then (`d0689e736:CLAUDE.md` line 213) and now
  (Settled, research-list CLOSED negatives), is "Pengu `league-client-mcp` = NO" - a different repo (an
  MCP server judged thinner than RC's LCU client), not the Pengu Loader panel. No Settled line closes
  this row; the operator decision stands as the only blocker. (5) THE SERVER HALF IS STILL SHIPPED and
  is now an orphan consumer: `dashboard/_handler.py:175-176` (comment names `pengu/`, absent) and the
  `_cors_allowed_origin` echo at `:589-596`, pinned by `tests/test_handler_cors.py`. Retiring the row
  would leave that gate with no in-repo client; un-archiving would reuse it. Both are the decision.
  **READY-WHEN-UNARCHIVED (stated before any client session; GATE 1, League client at home, no game).**
  PRECONDITIONS: stub back at `pengu/` and installed into Pengu Loader by the operator; RC up (the
  `/api/state` probe answers). PROBE: in the League client UX devtools console run
  `(() => { const p = document.getElementById("rc-pengu-panel"); return p && [...p.querySelectorAll("[data-field]")].map(e => e.dataset.field + "=" + e.textContent); })()`
  and, at the same minute, `curl -sk https://127.0.0.1:8888/api/state` -> `mode_key`.
  PREDICATE: PASS iff the panel exists, `status=live`, and `mode=` equals the curl `mode_key`
  (`client` at home); then a second read at least 4 s later (2 x `POLL_MS` 2000) still reads `live`.
  FAIL iff the panel is absent, or `status=RC offline - retrying` while the curl answers (a CORS or
  certificate refusal in the client's browser; record the console error - the mkcert root being trusted
  by the client's embedded browser is UNMEASURED). EVIDENCE: the field list, the curl `mode_key`, ISO
  time, `lcu.phase`. SUBSTITUTION CHECK: `tests/test_handler_cors.py` proves the server echoes a
  loopback origin, and a desktop Chrome tab loading `index.js` proves the script runs in Chrome; neither
  is the client UX. Only the panel read inside the League client ticks this.
- **G1-06** `[NOT BUILT]` (was A12) Mode-specific overlay layout AUTO-SELECT-ARAM acceptance - queued
  for planning, not yet built. Once built the auto-select needs a live ARAM queue/lobby state and a
  per-map placement eyeball. SOURCE: BACKLOG.md:48.
  **AGE RE-CHECK (lane 9 PREP s144 cycle 127, 2026-11-09, S144-G-114; NOT a tick, NOT a re-open; still
  NOT BUILT, so nothing here is drainable yet).** The filing bundles THREE halves and they no longer
  share a status. (1) CITE DRIFT: `BACKLOG.md:48` is now `BACKLOG.md:1907` (the row "Mode-specific
  overlay settings (SR vs ARAM) + mode-specific out-of-game stats overlay", queued `cf8353d7b`,
  2026-06-30). (2) PER-MODE OVERLAY LAYOUT - NOT BUILT. `web/js/lib/overlay_layout.js:36` `LS_KEY`
  "rc-overlay-layout" holds ONE `_layout` object keyed by widget id (`:293`, read `:296`, write
  `:305`); the only per-game split is TFT vs League (`_isTftNow` `:187` off `body[data-ovx-game]`,
  `_inGame` `:199`), which chooses WHICH widget set is on the field, never WHERE, so SR, ARAM and Arena
  share one arrangement. Do not mistake `web/js/panels/panel_visibility.js` (per-mode dashboard panel
  VISIBILITY, contexts in-game-sr / -aram / -arena / -tft / out-game) for it: shipped, a show / hide
  gate, not a layout store, not this row. (3) OUT-OF-GAME STATS MODE SELECTOR - BUILT, manual:
  `38dc1bf9d` (2026-07-04, "feat(home): SR/ARAM/ARENA mode tabs - FE half"), `web/index.html:217`
  `#home-mode-tabs` (ALL / SR / ARAM / ARENA), `web/js/main.js:3402` `_homeModeTabLoad` (localStorage
  `rc-home-mode-tab`, whitelist, default ALL), `:3990` `_homeApplyModeTab`, fetch
  `/api/home/summary?mode=<tab>` at `:3942-3943` (ALL sends no `mode`); pinned by
  `tests/snapshot_panels/test_home_mode_tabs.py`. (4) AUTO-SELECT ARAM - NOT BUILT: `_homeApplyModeTab`
  has exactly two callers, the tab click `:4387` and the startup restore `:4389`; nothing feeds it
  `lcu.lobby.queue_id` or `mode_key`.
  **DESIGN TRAP for whoever builds (4), recorded so it does not ship invisible:** the view router sends
  Lobby / Matchmaking / ReadyCheck to the `lobby` view (`web/js/main.js:796`) and ChampSelect to
  `champ-select` (`:788`), and the home overlay paints only on the home view (`:4194-4203`, plus
  `_homeShouldShow` `:3411`). So "auto-select ARAM when queued" cannot be SEEN while queued: it is first
  observable on the return to home (lobby left, dodge, or post-game). The build has to name its driver
  (the lobby `queue_id` at queue time, persisted, vs the last game's mode on return) and its precedence
  over a manual pick (the filing says "stays manually switchable").
  **READY-WHEN-BUILT (stated before any lobby; GATE 1 for (4), GATES 2 + 3 for (2)).** (4) PRECONDITIONS:
  ui_mock OFF (the mock path ignores the filter, `:3936-3941`); before queueing, click SR on the home
  tabs and record `#home-overlay[data-mode-tab]` = "SR". Then enter an ARAM lobby (`lcu.lobby.queue_id`
  450 or 2400), leave it, and on the home view read `#home-overlay[data-mode-tab]`,
  `.home-mode-tab[data-hmode="ARAM"]` `aria-selected`, and the next `/api/home/summary` request line
  in `<main>/logs/<day>.log`. PASS iff the attribute reads "ARAM", that button is aria-selected "true",
  and the request carries `?mode=ARAM`, all after a recorded "SR" pre-state. FAIL iff it still reads
  "SR". The steps assume the build drives off the lobby `queue_id`; if it drives off the last game's
  mode instead, replace "enter an ARAM lobby, leave it" with "finish an ARAM game, return home" before
  running, else a correct build reads FAIL. (2) per-map placement: drag one widget in an ARAM game, then
  in an SR game; PASS iff each mode
  restores its own position and the ARAM drag did not move the SR one. EVIDENCE: the three values,
  their selectors, the ISO time and the lobby `queue_id`. SUBSTITUTION CHECK: the tab state lives in
  per-browser localStorage, so an "ARAM" left by an earlier manual click passes the DOM read with the
  auto-select never running - that is why the recorded SR pre-state is part of the predicate; a
  `tests/snapshot_panels` run or a mock lobby proves the handler COMPUTES, not that a real ARAM queue
  DROVE it.
- **G1-07** `[LOBBY-PARTY, READY 2026-10-27 - s144 lane gated cycle 16; PREP only, nothing ticked]`
  RM-881 (b) (QA23) live read-back: the lobby view re-fires `/api/duo-synergy` when the party reaches 2.
  SHIPPED headless `a503ce413` (s144 queue lane, LEDGER 1951): `web/js/panels/lobby_duo_synergy.js`
  `duoSynergyQuery` (null while solo, in a non-SR queue or before the lobby lands; `my_role` = `sup` iff
  the local member's first lane preference is `UTILITY`, else `bot`; `top_n=4`) and
  `createLobbyDuoSynergy` (ONE fetch per party episode, so the 2 s lobby refresh never re-fires it),
  called from `web/js/main.js` `_lobbyViewRefresh` via `_lvDuoCtl().update(lobby)`; renders into
  `#lv-duo-synergy` under the PARTY roster. The BACKLOG RM-881 header says the live party >= 2
  read-back is still owed; no row carried it. **Needs a real second player** (same blocker as G1-04): a
  custom or practice lobby is not an SR queue and bots are not party members, so neither fires it.
  **PRECONDITIONS:** an SR queue lobby (`web/js/main.js` `SR_QUEUE_IDS`: 400 / 420 / 430 / 440 / 480 /
  700 and the co-op ids) with party_size >= 2; the dashboard on the Lobby view (`main.js` routes phase
  Lobby / Matchmaking / ReadyCheck to `lobby`; the fetch runs only from that view); ui_mock OFF; count
  the open dashboard clients on the Lobby view (rc-shell = 1; every extra tab fires its own GET). Keep
  the window ONE stable episode: form the party once, do not change the lane preference, do not reload
  the page (a re-formed party, a role flip and back, or a reload each re-fire by design).
  **PROBE (copy-paste, from a worktree; read-only):** note the clock when the second player joins
  (`<since>`), wait 10 s (the tool grades a window under 10 s NO_RESULT), then
  `curl -sk https://127.0.0.1:8888/api/state > _scratch/g107_state.json` and
  `python tools/gated_rm881_duo_lobby.py --state _scratch/g107_state.json --since <since> --until <now>
  --clients <n>` (reads `<main>/logs/<day>.log`). Field paths: `/api/state` -> `lcu.phase`,
  `lcu.lobby.party_size`, `lcu.lobby.queue_id`,
  `lcu.lobby.local_member.position_preferences.first_preference`; the day log's request trace
  (`dashboard/_handler.py` `Handler.log_message`, DEBUG, always written to the file; the route is not in
  `_SUPPRESS_LOG_PATHS`).
  **PREDICATE, SENT half (stated before any lobby):** PASS iff the window holds 1 .. `<n>` trace lines
  `GET /api/duo-synergy?my_role=<expected>&top_n=4` and every one answered 200. FAIL iff no duo-synergy
  GET appears while other trace lines do, a mock-fixture fetch appears, an expected GET answered non-200,
  or more than `<n>` expected GETs inside any 10 s span (the 2 s lobby refresh re-firing). NO_RESULT iff
  the window holds no HTTP trace line at all (the trace was not captured - silence proves nothing), the
  captured state is not a duo SR lobby, or more than `<n>` expected GETs lie further apart than that (the
  window spans more than one episode or a reload: narrow it and re-run). The tool reads the day log and
  its size-rotated `.log.<n>` siblings. A GET with another `my_role` is printed, not graded (a lane-preference change
  re-fires by design). Idle baseline 2026-10-27 23:40: `lcu.phase` None, `lcu` = config / phase / ts only
  -> tool `lobby NO_RESULT` exit 1; the 2026-10-27 day log held 7 trace lines (`/api/health/all`,
  `/api/mains`) and 0 duo-synergy GETs, all parsed by the tool.
  **PREDICATE, RENDERED half (operator present - a drain session screenshot; a lane takes no capture):**
  PASS iff within 10 s of the PASS trace line the Lobby view shows the `DUO PICKS` block under the PARTY
  roster with a BOT and/or SUPPORT row holding at least one cell with a champion name and an `NN.N%`
  rate. FAIL iff the block is absent with a duo SR lobby up, `loading duo picks...` persists past 10 s,
  or it reads `duo picks unavailable right now` (record the route's status from the trace line).
  **EVIDENCE CONTRACT:** the tool's printed `sent` block (times, query, status - no peer address is
  printed), the `/api/state` capture's party_size / queue_id / first_preference values, the screenshot
  path with its capture time, and the queue name; no Riot id or summoner name copied into this doc.
  **SUBSTITUTION CHECK:** a GET of `/api/duo-synergy` from a shell, the 19 `node --test` cases and the
  `tests/snapshot_panels/test_lobby_duo_synergy_rm881.py` headless render all prove the COMPUTE half or a
  mock-fed render - none says the operator's dashboard SENT the request. Worse, a shell GET or a headless
  Chromium load of `:8888` inside the window adds its OWN trace line and can fake the SENT half: run no
  probe GET of the route between `<since>` and `<until>`, and treat any extra client as `--clients`.
  **AUTO-RELOAD VOIDS THE WINDOW (s144 gated c20, PREP; stated before any lobby):** the page reloads
  itself on any served-asset change, through two pollers in `web/js/main.js`: `/api/ui-version`
  (ADR-008, `dashboard/_static.compute_asset_hash`) and the `_hotReloadInit` `/api/asset-stamp`
  poller (3 s, off only when `localStorage.rc_hot_reload` is `0`). A reload re-fires the duo GET by
  design. So a merger landing that writes any watched asset (`web/index.html`, `web/css/**/*.css`,
  `web/js/**/*.js`) inside the window (RM-1089 and the lane/uiux web commits were unlanded at
  2026-10-28 05:00 local) makes two episodes. The tool can
  then grade FAIL (more than `<n>` expected GETs inside 10 s) or NO_RESULT. Read
  `curl -sk https://127.0.0.1:8888/api/ui-version` and `curl -sk https://127.0.0.1:8888/api/asset-stamp`
  just before `<since>` and again at `<until>`. Both routes are in `dashboard/_handler.py`
  `_SUPPRESS_LOG_PATHS`, so these reads add no trace line. Both walk the same
  `dashboard._static.asset_fileset()`, but `v` hashes whole-second mtimes, so a sub-second change
  shows only in `mtime`. A changed `v`, or ANY change in `mtime` (stricter than the poller's own
  0.5 s threshold, because the poller compares against its page-load baseline, not against the
  `<since>` read), makes the window NO_RESULT whatever the tool printed: re-run on a fresh
  window, never tick or FAIL on it. Both before / after pairs go into the tick line.
  **PORTRAITS ARE NOT GRADED (s144 gated c20):** each cell writes the champion name and the rate
  as text spans beside the portrait (`web/js/panels/lobby_duo_synergy.js` `_cellHtml`), so a blank
  tile never fails the RENDERED half. Code without the queue-lane fix RM-1089 ("the duo block
  re-renders its portraits when the champion index lands after the duo response"; on lane/queue,
  NOT landed on main at 2026-10-28 05:00 local) has a known race. If the duo response arrives
  before `/data/champions_index.json` loads, every cell keeps a blank tile until the next duo
  controller state change (party back to solo, or a role change). Check for the fix by SYMBOL,
  not sha: the `rc:champs-ready` listener in `main.js` calls `_lvDuoRender(_LV.duo.state())`. Record which code the page ran and whether the tiles were blank.
  With the fix loaded, blank tiles that are still there 10 s after the block first rendered are a
  separate finding for the report, never a G1-07 FAIL.
  Tool: `tools/gated_rm881_duo_lobby.py` (tests `tests/test_gated_rm881_duo_lobby.py`; trace lines built
  by the real `Handler.log_message` through the day log's own format, the SR set parsed from the real
  `main.js`).
  **AGE RE-CHECK (s144 lane gated cycle 134, S144-G-121; PREP only, nothing ticked; no game:
  :8888 and :2999 curl 000 at 2026-11-09T07:42-06:00).** NOT stale; the probe and both predicates
  stand. Cite drift: `a503ce413` is not on main; the landed commit is `6c7dd2030` (same subject).
  RM-1089 HAS LANDED on main as `730c76523`, and the `rc:champs-ready` listener in `main.js` calls
  `_lvDuoRender(_LV.duo.state())`. That makes the PORTRAITS paragraph's "NOT landed" clause stale: a
  page served from main runs the fix, so tiles still blank 10 s after the block first rendered are
  the separate finding, never a FAIL. The AUTO-RELOAD caveat about unlanded web commits now means
  whatever is unlanded at drain time; read the two before / after pairs exactly as written.
  NEW PRECONDITION: RC must be RUNNING. `ops/runtime/launcher_status.json` read `state` `halted`,
  `reason` `stdin_stop` (last written 2026-10-31 21:17 local), while the stale
  `ops/runtime/health.json` still read `alive: true`, so health.json alone does not show RC is up.
  Check that :8888 answers and that the drain day's `logs/<day>.log` exists before `<since>`. There
  is no day log after 2026-10-31 because RC has not run since then; the log path did not move. The
  2026-10-31 log holds request-trace lines written at 21:16-21:17 local, after the service host's
  recorded start (`launcher_status.json` `services[].started` 2026-11-01T00:13Z). Their format is
  `<peer> HTTP "GET <path> HTTP/1.1" <status> -`, with the peer prefix written by `Handler._peer`.
  PARSE CHECK, NOT EVIDENCE: the grader was given a hand-built duo-lobby state (no lobby existed)
  and the window 21:16:00-21:17:20 of that log. It counted 31 trace lines, the same as a grep
  count, and printed `sent FAIL` / `no GET /api/duo-synergy`, so it reads the post-cutover format.
  Still true at HEAD: `/api/ui-version` and `/api/asset-stamp` are in `_SUPPRESS_LOG_PATHS`, and
  `/api/duo-synergy` is not. `TOP_N` is 4, `UTILITY` maps to `sup`, and the `DUO PICKS`,
  `loading duo picks...` and `duo picks unavailable right now` strings are unchanged.
  `tests/test_gated_rm881_duo_lobby.py`: 14 passed at HEAD.

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
- **G2-02** `[BLOCKED ON WIRING 2026-11-06]` (was B7) B1 `apply_melee_aa_gate` - melee bruiser build drops Runaan's, ranged carry
  byte-identical. /dps route transport WIRED (OQ17).
  **AGE CHECK (lane 9 PREP s144 cycle 88, S144-G-79; source read at local main `86ed5e52d`, no game
  up; NOT a tick). Producer-orphan, shared by G2-02, G2-03 and G2-05: all three seams are parsed by
  `/dps` only, the one client function that sends them there has no live caller, and the live path
  that carries two of them posts to `/rank`, which drops them.** Measured with `inspect.signature`:
  `compute_dps` takes `apply_melee_aa_gate`, `assume_passive_as_stacks` and `apply_target_vuln`;
  `rank_items` takes none of the three; `compute_hybrid` takes `apply_melee_aa_gate` but
  `rank_items_by_hybrid` does not. In `agents/daemon_slayer/server.py` the only parse sites are in
  `_route_dps` (`_opt_bool(body, ...)` for all three), whose own comment says `rank_items()` does not
  forward them. In `core/daemon_slayer_client.py`, `dps_for` emits all three when True, but no code
  file outside `tests/` calls it. `rank_for` emits `assume_passive_as_stacks` / `apply_target_vuln`
  into the `/rank` body and `rank_for_primary_archetype` forwards both on its carry branch only;
  `_route_rank` reads neither key, so both die on the wire. The arming points are unarmed too:
  `coach_integration/archetype_dispatch.py` `dispatch_for_coach` takes both (default False) and no
  coach passes them; `dashboard/routes_state.py` `_DS_PREVIEW_SEAM_BOOLS` lists both and no `web/`
  `.js` file sends either. `apply_melee_aa_gate` has no dispatcher parameter, no ds-preview entry and
  no RC caller at all. PRECONDITION for return to the drain list: a live producer posts the flag to
  `/dps` (a `dps_for` caller), or a Tier-2 change threads it into `rank_items` + `/rank` (or
  `rank_items_by_hybrid` + `/rank-bruiser` for the melee bruiser case), and the outbound body is
  recorded with `ts` and the Live Client `gameData.gameTime` it read. Predicate stated NOW, graded
  only after that lands, in one practice-tool SR game on a melee champion holding Runaan's Hurricane
  3085: PASS iff a recorded body to a route that parses `apply_melee_aa_gate` carries it `true` with
  an item list that contains 3085 and equals the active player's `:2999`
  `allPlayers[].items[].itemID` within 10 s of game time of the body. The "drops Runaan's" eyeball
  is written when the producer names its surface. SUBSTITUTION CHECK: as G2-04 (an in-process
  `compute_dps` call, a hand-POSTed `/dps` body or a DS unit test answers COMPUTES, not SENT).
- **G2-03** `[BLOCKED ON WIRING 2026-11-06]` (was B8) R7 `assume_passive_as_stacks` (Irelia/Jax/Ezreal/Volibear at full stacks; stacks
  buildable vs dummies/minions). **Irelia eyeball SANE 2026-07-02** (/dps 38.90 -> 47.96, +23%); the
  flip stays gated across the 4 tabled champs.
  **AGE CHECK (s144 cycle 88, S144-G-79): producer-orphan, measured in G2-02.** The 2026-07-02
  Irelia figure is a `/dps` compute read; no live RC path sends the flag to a route that reads it
  (the carry dispatch sends it to `/rank`, which drops it). The four registry keys are Irelia, Jax,
  Ezreal and Volibear (`agents/daemon_slayer/_passive_as_overrides.py` `_PASSIVE_AS_OVERRIDES`).
  Predicate stated NOW, graded only after a producer lands, in one practice-tool SR game on one of
  the four: PASS iff a recorded body to `/dps` (or a successor route that parses the key) carries
  `"assume_passive_as_stacks": true` with `champion` equal to the `championName` of the `:2999`
  `allPlayers[]` row whose `riotId` equals `activePlayer.riotId`, read within 10 s of game time of
  the body. Substitution check as G2-02.
- **G2-04** `[BLOCKED ON WIRING 2026-11-06]` (was B9) R5 `assume_missing_hp_heal_amp` + live caster missing-HP feed (drop own HP vs
  bots; coach-side hp/hp_max already emitted, item 639).
  **AGE CHECK (lane 9 PREP s144 cycle 84, RM-1673; source read at local main `ba0df749f`, no game
  up; NOT a tick). The FEED is live, the FLAG is not, and the registered champions never reach the
  scorer that reads either.** Measured: the four coach callers of `dispatch_for_coach`
  (`coach_integration/_coach.py`, `coaches/aram_coach.py`, `coaches/arena_coach.py`,
  `coaches/brawl_coach.py`) all pass `caster_hp` / `caster_hp_max`, and the dispatcher turns them into
  `caster_missing_hp_pct` (`coach_integration/archetype_dispatch.py` "R5 self-HP" block); none of
  them, nor the one other caller (the read-only grader `tools/gated_g505_mode_mods.py`), passes
  `assume_missing_hp_heal_amp`, whose dispatcher default is False. Outside `agents/daemon_slayer/` and
  tests, the flag appears only in that dispatcher, in `core/daemon_slayer_client.py`
  (`rank_enchanter_for` and its forward in `rank_for_primary_archetype`'s enchanter branch) and in
  the `/api/ds-preview` pass-through list `_DS_PREVIEW_SEAM_BOOLS` (`dashboard/routes_state.py`),
  which no `web/` file sends. The engine amp is inert while the flag is False
  (`agents/daemon_slayer/ability_hps.py`: `if assume_missing_hp_heal_amp and heal_per_cast > 0.0`), and
  the hps path calls `compute_ability_hps` with `resolve_target_relative=False`, so a forwarded
  `caster_missing_hp_pct` alone changes nothing on `/rank-enchanter`. Second gap: the seam rides the
  ENCHANTER branch only, and the amp registry `_MISSING_HP_HEAL_AMP` holds MasterYi W, Lissandra R,
  Sylas W and Briar P, whose `core.archetype_picks.get_archetype_for` primaries read bruiser, mage,
  mage and bruiser (DDragon defaults; the main checkout's gitignored `data/cs_archetype_picks.json`
  read as an empty dict at 2026-11-06T03:12-06:00; none of the four is in
  `core/aram_archetype_override.json`). So dropping own HP on any of the four in a practice game
  changes nothing RC ranks today, flag or no flag. PRECONDITION for return to the drain list: a
  producer arms `assume_missing_hp_heal_amp` live AND a registered champion's ranking reaches a scorer
  that reads it (an operator archetype pick of `enchanter`, or the seam carried to the branch those
  champions use; either is a code or operator change, not a game), and the outbound body is recorded
  with `ts` and the Live Client `gameData.gameTime` it read. Predicate stated NOW, graded only after
  that lands, in one practice-tool SR game on a registered champion: PASS iff a recorded
  `/rank-enchanter` (or successor) body carries `assume_missing_hp_heal_amp: true` and a
  `caster_missing_hp_pct` within 0.02 of `1 - currentHealth / maxHealth` from a `:2999`
  `activePlayer.championStats` read within 10 s of game time of the body, AND at least one such body
  has `caster_missing_hp_pct` >= 0.40. SUBSTITUTION CHECK: `live_flip_eyeball.py`, a hand-POSTed body,
  a DS unit test or a fixture answers whether the engine COMPUTES the amp; only the producer's own
  recorded body joined to a `:2999` read at the same game time answers whether RC SENT it.
- **G2-05** `[BLOCKED ON WIRING 2026-11-06]` (was B10) R12 `apply_target_vuln` (Vladimir/Evenshroud) + the R43 Imperial Mandate rider
  (4005/224005/324005). Broaden the consumer beyond AA DPS to ability_dps + burst.
  **AGE CHECK (s144 cycle 88, S144-G-79): producer-orphan, measured in G2-02; the "broaden" half is
  unshipped.** `apply_target_vuln` is still read only by `compute_dps`; by `inspect.signature` no
  public `ability_dps` or `burst` function takes it. The registry
  (`agents/daemon_slayer/_target_vulnerability_overrides.py`) keys Vladimir (R, 0.10), Evenshroud
  3001 / 223001 (0.07) and the R43 Imperial Mandate rider 4005 / 224005 / 324005 (0.07). Predicate
  stated NOW, graded only after a producer lands, in one practice-tool SR game on Vladimir or
  holding Evenshroud or Imperial Mandate: PASS iff a recorded body to `/dps` (or a successor route
  that parses the key) carries `"apply_target_vuln": true` and either `champion` Vladimir or an item
  list that contains 3001 or 4005 and equals the active player's `:2999` items, from a read within
  10 s of game time of the body. Substitution check as G2-02.
- **G2-06** `[BLOCKED ON WIRING 2026-11-06]` (was B11) R14 `apply_cc_floor` floor-model sanity for close-range Maokai/Ashe/Hecarim R.
  **CODE PREREQ (headless):** thread the flag through the compute_ehp / compute_hybrid /
  cc-blended-EHP consumer chain - none thread it yet. Not eyeball-able until that lands.
  **AGE CHECK (s144 cycle 88, S144-G-79; local main `86ed5e52d`, no game up; NOT a tick). The CODE
  PREREQ line above is half stale; the row is now producer-orphan.** RM-201 threaded `apply_cc_floor`
  into `compute_ehp` (it rides the per-enemy `compute_cc_pressure` call and is AND-gated with
  `include_conditional`), and `server.py` `_route_ehp` parses it. By `inspect.signature` no ranker
  or hybrid entry point takes it (`rank_items_by_ehp`, `compute_hybrid` and `rank_items_by_hybrid`
  do not; besides `compute_ehp` only the per-enemy helper `cc_pressure.compute_cc_pressure` does),
  as the route comment says. The only client sender, `ehp_for` (emits `apply_cc_floor`,
  `include_conditional` and `enemies`), has no caller outside `core/daemon_slayer_client.py` and
  `tests/` - the same `/ehp` orphan as G2-11. PRECONDITION for return to the drain list: an RC
  caller posts `/ehp` with `apply_cc_floor`, `include_conditional` and a non-empty `enemies` list
  in a live game (or a Tier-2 change threads the floor into a ranker the dispatcher calls), and the
  outbound body is recorded with `ts` and `gameData.gameTime`. Predicate stated NOW, graded only
  after that lands, in one practice-tool SR game against Maokai, Ashe or Hecarim bots: PASS iff a
  recorded `/ehp` body carries both flags `true` and an `enemies` list naming exactly the
  `championName` values of the `:2999` `allPlayers[]` rows on the other team, read within 10 s of
  game time of the body, and that list holds at least one of the three. SUBSTITUTION CHECK: as
  G2-04 (an in-process `compute_ehp` call or a hand-POSTed `/ehp` body answers COMPUTES, not SENT).
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
- **G2-08** `[BLOCKED ON WIRING 2026-11-06]` (was B13) R30/DSV6 `assume_magic_burst` (Luden's/Stormsurge/Malignance) + R69 item ACTIVES
  (Rocketbelt 3152/223152, Everfrost 446656) + R70 Zeke's 3050/223050/323050 Frostfire Tempest.
  compute_ability_dps deliberately inert. Confirm an active/ult-trigger holder's burst reads sane and
  assumes the trigger fires inside the burst window.
  **AGE CHECK (lane 9 PREP s144 cycle 85, RM-1674; source read at local main `ba0df749f`, no game
  up; NOT a tick). Producer-orphan, shared by G2-08, G2-17 and G2-20: all three seams are parsed by
  `/burst` only, and no live RC caller arms any of them on a route that reads it.** Measured with
  `inspect.signature`: `compute_burst_damage` takes `assume_magic_burst`, `assume_shielded_target`
  and `score_completion_runes`; `rank_items_by_burst` takes none of the three; `compute_combo` takes
  `score_completion_runes` only. In `agents/daemon_slayer/server.py` the parse sites are
  `_route_burst` (`_opt_bool(body, "assume_magic_burst" / "assume_shielded_target" /
  "score_completion_runes", False)`); `_route_rank_assassin` says in its own comment that the R30 /
  R74 / R75 seams are `/burst`-scoped and does not parse them. Callers: the SR / ARAM / Arena /
  Brawl coaches call `dispatch_for_coach` with no `assume_magic_burst` (default False), and every
  `/api/ds-preview` body in `web/js/panels/active_match.js` and `champ_select.js` carries champion /
  mode / level / items (plus `enemies` or `archetype`) and no seam key. Even when armed, the assassin
  branch forwards it to `rank_assassin_for` -> `POST /rank-assassin`, which drops it (the client's
  own comment says this is by design: the lever reaches the engine through `burst_for`).
  `core/daemon_slayer_client.py` `burst_for` can send all three, but its one live caller,
  `core/death_recap.py` `fetch_ds_profiles`, sends champion, level, items, mode and the target
  resists / max HP only; the direct in-process `compute_burst_damage` caller
  `dashboard/routes_spike_curve.py` passes none of the three either. The R69 / R70 rows ride the same seam (their `_effects_data.py` notes name
  `assume_magic_burst`, read on 3152, 223152 and 3050). PRECONDITION for return to the drain list:
  a producer sends `assume_magic_burst: true` to `/burst` (or a Tier-2 change threads it into
  `rank_items_by_burst` and `/rank-assassin`) for a live holder of a trigger item, and records the
  outbound body with `ts` and the Live Client `gameData.gameTime` it read. Predicate stated NOW,
  graded only after that lands, in one practice-tool SR game: PASS iff a recorded body carries
  `assume_magic_burst: true` and an item list that contains the held trigger item id and equals the
  active player's `allPlayers[].items[].itemID` from a `:2999` read within 10 s of game time of the
  body, AND the response for that body carries the `notes` entry `burst.py` writes only when the
  magic-burst damage is above 0 (it ends "assume_magic_burst seam)"). The "reads sane" eyeball is written when the
  producer names its surface. SUBSTITUTION CHECK: a hand-POSTed `/burst` body,
  `live_flip_eyeball.py`, a fixture or a DS unit test answers whether the engine COMPUTES the
  credit; only the producer's own recorded outbound body, joined to a `:2999` read at the same game
  time, answers whether RC SENT it for the live build.
- **G2-09** `[BLOCKED ON WIRING 2026-11-06]` (was B14) R35 `apply_passive_mitigation` + snapshot (Galio/Garen/MasterYi percent-DR);
  confirm the rank-4 + 0.3-uptime assumptions read sane.
  **AGE CHECK (lane 9 PREP s144 cycle 87, S144-G-78; local main `20db38d67`, no game up; NOT a tick).
  The routes carry the seam; no live RC caller arms it.** In `agents/daemon_slayer/server.py`
  `_route_ehp`, `_route_rank_tank`, `_route_hybrid` and `_route_rank_bruiser` each parse
  `_opt_bool(body, "apply_passive_mitigation", False)` and forward it; `compute_ehp` always holds the
  `DataSnapshot`, so the "+ snapshot" half needs no transport. In `core/daemon_slayer_client.py`
  `rank_tank_for`, `ehp_for`, `rank_bruiser_for` and `hybrid_for` emit the key when True, but the one
  live dispatcher, `rank_for_primary_archetype`, has no such parameter and its tank and bruiser
  branches call `rank_tank_for` / `rank_bruiser_for` without it; `core/defensive_picks.py` calls
  `rank_tank_for` without it; `dashboard/routes_state.py` `_DS_PREVIEW_SEAM_BOOLS` does not list it;
  no code file (`.py` / `.js` / `.mjs`) outside `agents/daemon_slayer/`,
  `core/daemon_slayer_client.py` and `tests/` names it. The three registry champions resolve to the archetypes those routes serve
  (`core/archetype_picks.py` `get_archetype_for`, DDragon default: Galio tank, Garen and MasterYi
  bruiser), so the gap is the producer, not the route. The rank-4 (`_ASSUMED_ABILITY_RANK = 4`) and
  0.3 (`_ACTIVE_DR_PROB = 0.3`) assumptions live in
  `agents/daemon_slayer/_passive_mitigation_overrides.py` and stay unexercised in every live ranking.
  PRECONDITION for return to the drain list: the dispatcher (or the panel's `/api/ds-preview` seam
  list) arms `apply_passive_mitigation` for a live Galio / Garen / MasterYi ranking, and the outbound
  body is recorded with `ts` and `gameData.gameTime`. Predicate stated NOW, graded only after that
  lands, in one practice-tool SR game on one of the three: PASS iff a recorded `/rank-tank` (Galio)
  or `/rank-bruiser` (Garen / MasterYi) body carries `"apply_passive_mitigation": true` with
  `champion` equal to `activePlayer` `championName` from a `:2999` read within 10 s of game time of
  the body; record `activePlayer.abilities.W.abilityLevel` from that read beside the assumed rank 4
  (the gap is the evidence for the rank-4 eyeball, written when the producer names its surface).
  SUBSTITUTION CHECK: as G2-04 (an in-process `compute_ehp` call or a hand-POSTed `/rank-tank` body
  answers COMPUTES, not SENT).
- **G2-10** `[BLOCKED ON WIRING 2026-11-06]` (was B15) R45 Poppy W low-HP doubled percent-of-resist tier - feed
  `caster_current_hp_pct` (drop own HP), sub-40%-HP EHP ranking sane.
  **AGE CHECK (lane 9 PREP s144 cycle 84, RM-1673; local main `ba0df749f`, no game up; NOT a tick).
  No EHP route, no EHP ranker and no RC caller carries `caster_current_hp_pct`.** Measured with
  `inspect.signature`: `compute_ehp` and `compute_hybrid` take it, `rank_items_by_ehp` and
  `rank_items_by_hybrid` do not; in `agents/daemon_slayer/server.py` the only parse site is
  `_route_burst` (`_opt_float(body, "caster_current_hp_pct", 1.0)`), so `/ehp`, `/rank-tank` and
  `/rank-bruiser` drop it; inside the engine the only forward INTO `compute_ehp` is from
  `compute_hybrid` (`compute_ehp` hands it on to `resist_grants`; `burst.py` keeps its own R53 use).
  Outside the engine and tests it is named only by `core/daemon_slayer_client.py` `burst_for` (the
  G2-13 producer-orphan). Poppy's primary reads tank (`get_archetype_for`, DDragon default), whose
  dispatch branch posts `/rank-tank`. So the doubled tier stays dormant at its 1.0 default in every
  live ranking, whatever HP the operator drops to. PRECONDITION for return to the drain list: the EHP
  ranker and its route thread `caster_current_hp_pct` (a Tier-2 engine change), a producer sends the
  live own HP fraction for Poppy, and the body is recorded with `ts` and `gameData.gameTime`.
  Predicate stated NOW, graded only after that lands, in one practice-tool SR game on Poppy: PASS iff
  a recorded tank-ranking body carries `caster_current_hp_pct` within 0.02 of
  `currentHealth / maxHealth` from a `:2999` read within 10 s of game time of the body, AND at least
  one such body is below 0.40 (the tier threshold); the "EHP ranking sane" eyeball is written when the
  producer names its surface. SUBSTITUTION CHECK: as G2-04 (an in-process `compute_ehp` call answers
  COMPUTES, not SENT).
- **G2-11** `[BLOCKED ON WIRING 2026-11-06]` (was B16) R46 `assume_passive_health_stacks` (Sion W / Cho'Gath R / Swain P; stacks
  farmable on minions). Ideally replace the assumed-stack curve with a live stack feed later.
  **AGE CHECK (lane 9 PREP s144 cycle 86, RM-1675; source read at local main `ba0df749f`, no game
  up; NOT a tick). Producer-orphan: the seam is parsed by `/ehp` only, and nothing in RC calls
  `/ehp`.** Measured: `agents/daemon_slayer/server.py` `_route_ehp` parses it
  (`_opt_bool(body, "assume_passive_health_stacks", False)`); `_route_rank_tank`'s own comment says
  the seam exists on `compute_ehp` alone, so parsing it there "would read a key that dies before the
  engine call", and the tank ranker never reads it. `core/daemon_slayer_client.py` `ehp_for` emits
  it when True, but `ehp_for` has no caller outside its own module and no JS body posts to `/ehp`,
  so no live RC surface asks `/ehp` anything, armed or not. The stack COUNT is still the assumed
  by-level curve (`_passive_health_overrides.py` `assumed_stacks_by_level`); no live stack feed
  exists. PRECONDITION for return to the drain list: an RC producer calls `/ehp` (or a Tier-2 change
  threads the seam into `rank_items_by_ehp` and `/rank-tank`) with
  `assume_passive_health_stacks: true` for a live Sion / Cho'Gath / Swain and records the outbound
  body with `ts` and the Live Client `gameData.gameTime` it read. Predicate stated NOW, graded only
  after that lands, in one practice-tool SR game on one of the three: PASS iff a recorded body
  carries `assume_passive_health_stacks: true`, that champion, and a level equal to
  `activePlayer.level` from a `:2999` read within 10 s of game time of the body, AND the producer
  names the surface the result renders on (the "ranking sane" eyeball is written against that
  surface). CALIBRATION READ (does NOT tick): on a page with no max-HP rune or shard, the same
  `:2999` read's `activePlayer.championStats.maxHealth` minus base, per-level and item HP is the live
  stack HP the assumed curve stands in for; record both - the gap is the evidence for the "live
  stack feed" follow-up. SUBSTITUTION CHECK: as G2-04 (an in-process `compute_ehp` call answers
  COMPUTES, not SENT).
- **G2-12** `[BLOCKED ON WIRING 2026-11-06]` (was B17) R49 `assume_passive_reflect` (Rammus W) + R68 the ITEM Thorns lane on the SAME
  seam (Thornmail 3075 + mirrors 223075/323075 + Bramble Vest 3076). Practice bots DO attack, so the
  1.0s cadence + 3.0s window assumptions are exercisable for both streams. STRICTER READ: re-check
  ranking-vs-real-comp in the GATE 3 ARAM sitting.
  **AGE CHECK (lane 9 PREP s144 cycle 87, S144-G-78; local main `20db38d67`, no game up; NOT a tick).
  No DS route parses the flag and no RC caller sends it, so no practice game can exercise either
  stream.** Re-measured: the only code files naming `assume_passive_reflect` are
  `agents/daemon_slayer/dps.py`, `agents/daemon_slayer/burst.py` and
  `agents/daemon_slayer/_passive_reflect_overrides.py` (plus tests), with zero hits in `agents/daemon_slayer/server.py`, `core/` and `web/`;
  `tests/test_ds_parity_map.py` `_UNREACHABLE_OK` still lists it for `/burst` and `/dps`. This is
  the same finding the G3-15 PREP AUDIT leg (3) recorded at `412042dc8`, unchanged at this HEAD, and
  RM-1391 (wire the consumer, Tier-2 engine route) is still OPEN in `BACKLOG.md`. The 2026-07-20
  "mechanism proven + leak-free control" advance in the header is the Python-API compute half (the
  +8.963 pct pre-factor delta G3-15 leg (3) cites), not a rendered or sent read. PRECONDITION for return to the drain list: RM-1391
  lands (route parse or `/rank*` forward, an RC caller for thorn carriers, the two parity-map
  entries deleted in the same slice), and the outbound body is recorded with `ts` and
  `gameData.gameTime`. Predicate stated NOW, graded only after that lands, in one practice-tool SR
  game: PASS iff a recorded body to the route the slice wires carries `"assume_passive_reflect": true`
  for a build whose `:2999` `allPlayers[]` row (active player, within 10 s of game time of the body)
  is Rammus or holds 3075 / 223075 / 323075 / 3076, AND a recorded body for a no-carrier build in the
  same game does not carry the flag (or ranks byte-identical OFF vs ON). The cadence / window eyeball
  and the ranking-vs-real-comp read are G3-15 leg (3), whose predicate already stands. SUBSTITUTION
  CHECK: as G3-15 leg (3) (a direct `compute_dps` / `compute_burst_damage` call with the flag set,
  or `live_flip_eyeball.py`, answers COMPUTES, not SENT).
- **G2-13** `[BLOCKED ON WIRING 2026-11-06]` (was B18) R51 `gate_target_hp_amp` per-instant consumer (dummy HP is settable) -
  per-instant / stepped scenario eval, **NOT a blind burst-scorer flip**. Transport WIRED (OQ17).
  **AGE CHECK (lane 9 PREP s144 cycle 83, RM-1672; source read at local main `ba0df749f`, no game
  up; NOT a tick). Producer-orphan, for both G2-13 and G2-14: the transport is wired, but no live
  RC caller sends either seam or the inputs it reads, so dropping own HP or a dummy's HP in a
  practice game changes nothing RC computes today.** Measured: both seams are parsed by `/burst`
  only (`agents/daemon_slayer/server.py` `_route_burst`: `gate_target_hp_amp`,
  `gate_caster_hp_amp`, `caster_current_hp_pct`, `target_current_hp_pct`, `runes`). Outside
  `agents/daemon_slayer/`, no tracked `.py` / `.js` / `.mjs` file (tests aside) names
  `gate_target_hp_amp`, `gate_caster_hp_amp` or `caster_current_hp_pct` except
  `core/daemon_slayer_client.py` `burst_for`, which puts them on the body. The one live
  `burst_for` caller, `core/death_recap.py` `fetch_ds_profiles`, sends champion, level, items,
  mode and the three target resists / max HP only: no `runes`, no caster HP pct, no gate flag
  (the body's `target_current_hp_pct` is `burst_for`'s full-HP default 1.0, never a read). The
  one direct in-process `compute_burst_damage` caller outside DS, `dashboard/routes_spike_curve.py`
  (scorer `burst`), passes none of them either, and the `compute_combo` paths
  (`dashboard/routes_ds_combo.py`, `core/laning_scenario_precompute.py`) forward no gate flag or
  caster HP pct. And the engine gates are inert without `runes`
  carrying Cut Down 8017 / Coup de Grace 8014 (target gate) or Last Stand 8299 (caster gate)
  (`burst_for` docstring, measured at 1.253.0). The game-side inputs differ by row: own HP is
  on the Live Client (`activePlayer.championStats.currentHealth` / `maxHealth`) and the own page
  under `activePlayer.fullRunes.generalRunes[].id` (also `/liveclientdata/activeplayerrunes`
  `generalRunes`, which `game_reader/snapshot_normalizer.py` already reads); a target's CURRENT HP is not (per the Riot
  Live Client schema, not re-measured this cycle, `allPlayers[]` carries no health field), so
  the G2-13 target HP can only be a stepped scenario axis or a vision read, never a `:2999`
  read. PRECONDITION for return to the drain list: a producer lands that sends a live own
  `runes` set to `/burst` with the gate seam(s) and records its outbound body (a log line or
  shadow row carrying `ts` and the Live Client `gameData.gameTime` it read). Predicates stated
  NOW, graded only after that lands, each in one practice-tool SR game: G2-14 PASS iff a
  recorded body carries `gate_caster_hp_amp: true`, a `runes` set equal to
  `activePlayer.fullRunes.generalRunes[].id` and a `caster_current_hp_pct` within 0.02 of
  `currentHealth / maxHealth` from a `:2999` read within 10 s of game time of the body, AND at
  least one such body has `caster_current_hp_pct` below 0.60 (the Last Stand ramp starts there);
  G2-13 PASS iff a recorded body carries `gate_target_hp_amp: true`, such a `runes` set, and a
  `target_current_hp_pct` the producer itself labels with its source (a named scenario step or
  a timestamped vision read); a body carrying a target HP with no named source FAILS. The
  on-screen eyeball halves are written when the producer names its surface. SUBSTITUTION CHECK:
  a hand-POSTed `/burst` body, `live_flip_eyeball.py`, a fixture or a DS unit test answers
  whether the engine COMPUTES the gate; only the producer's own recorded outbound body, joined
  to a `:2999` read at the same game time, answers whether RC SENT the live HP and page.
- **G2-14** `[BLOCKED ON WIRING 2026-11-06]` (was B19) R53 `gate_caster_hp_amp` per-instant consumer (own HP droppable) - same
  per-instant discipline. Transport WIRED (OQ17), producer-orphan. Re-measured 2026-11-06: no
  live caller sends `gate_caster_hp_amp`, `caster_current_hp_pct` or `runes`; AGE CHECK,
  precondition and predicate in G2-13.
- **G2-15** `[BLOCKED ON WIRING 2026-11-06]` (was B20) OQ1/R55 `assume_archetype_hp_pct` OFF-vs-ON re-rank (BotRK 3153 / Hellfire 4017 /
  Fulmination 443055 only). Own-build sanity reached **3/3 2026-07-04** (Kalista + Tristana + Vayne).
  The flag is NOT a `/rank` body param (`server.py:452-453` exposes only exempt_offclass_by_win +
  prefer_kit_axis_by_win), so the OFF-vs-ON flip itself needs the DS restart with the seam armed. The
  0.5 sustained-fraction CALIBRATION is GATE 7 (G7-14). SOURCE: LEDGER 718 + 779.
  **AGE CHECK (s144 cycle 88, S144-G-79; local main `86ed5e52d`, no game up; NOT a tick). The
  sentence above is STALE; the row is producer-orphan.** `target_current_hp_pct` IS now a `/rank`
  body param (`server.py` `_route_rank`: `_opt_float(body, "target_current_hp_pct", 1.0)`, forwarded
  to `rank_items`), and `_route_rank_bruiser` parses it too. `assume_archetype_hp_pct` is not a DS
  key at all: it is an RC-side flag of `rank_for_primary_archetype` (`core/daemon_slayer_client.py`)
  that resolves `core/ds_archetype_hp_pct.py` `archetype_target_current_hp_pct` (0.5 for a sustained
  archetype, 1.0 otherwise) into `target_current_hp_pct`, so the OFF-vs-ON flip needs no DS restart.
  No live caller sets it: `dispatch_for_coach` has no such parameter, `_DS_PREVIEW_SEAM_BOOLS` does
  not list it, `core/archetype_mismatch.py`'s call omits it, and no code file outside those two core
  modules and `tests/` names it. PRECONDITION for return to the drain list: a live producer arms it
  (a dispatcher parameter or a ds-preview seam entry), and the outbound body is recorded with `ts`
  and `gameData.gameTime`. Predicate stated NOW, graded only after that lands, in one practice-tool
  SR game on a champion RC dispatches as carry or bruiser and holding 3153, 4017 or 443055: PASS iff
  a recorded `/rank` or `/rank-bruiser` body carries `"target_current_hp_pct": 0.5` with an item
  list that equals the active player's `:2999` items within 10 s of game time of the body. The
  OFF-vs-ON re-rank eyeball is written when the producer names its surface. Substitution check as
  G2-02.
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
  `[BLOCKED ON WIRING 2026-11-06]` **AGE CHECK (s144 cycle 88, S144-G-79; local main `86ed5e52d`,
  no game up; NOT a tick). Producer-orphan: the LIVE RESIDUAL above has no live surface today.**
  `server.py` `_route_hybrid` and `_route_rank_bruiser` parse `assume_ms_utility`, and
  `rank_bruiser_for` / `hybrid_for` emit it, but `rank_for_primary_archetype` has no such parameter
  and its bruiser branch calls `rank_bruiser_for` without it; `hybrid_for` has no caller outside
  `core/daemon_slayer_client.py` and `tests/`; no dispatcher parameter or `_DS_PREVIEW_SEAM_BOOLS`
  entry names it (the only other hit outside the engine, the client and tests is the static mock
  `web/mock/addendum_a_concepts.html`). So the in-game `/rank-bruiser` order cannot show the seam.
  PRECONDITION for return to the drain list: a live producer arms it on a `/rank-bruiser` (or
  `/hybrid`) call, and the outbound body is recorded with `ts` and `gameData.gameTime`. Predicate
  stated NOW, graded only after that lands, in one practice-tool SR game on a juggernaut: PASS iff
  a recorded `/rank-bruiser` body carries `"assume_ms_utility": true` with an item list that
  contains 3742 or 4401 and equals the active player's `:2999` items within 10 s of game time of the
  body. The score-pinned MS-less control above stays a headless re-instrument before any flip.
  Substitution check as G2-02.
- **G2-17** `[BLOCKED ON WIRING 2026-11-06]` (was B41b) R75/DSV9 `assume_shielded_target` (Serpent's Fang 6695). Practice suffices
  (assumed pool 0.20 x target max HP, melee 50% / ranged 35%); a REAL game vs Shieldbow/enchanter comps
  is the stronger eyeball. Sanity = the credit does not dominate a real-damage item swap.
  Re-measured 2026-11-06 (RM-1674): producer-orphan, AGE CHECK in G2-08 - `/burst` is the only
  parse site, `burst_for` can send it, and no live caller does. The seam is also inert without
  `target_max_hp > 0` (`burst.py`: `if assume_shielded_target and target_max_hp > 0`). Predicate
  stated NOW, graded only after a producer lands: PASS iff a recorded body carries
  `assume_shielded_target: true`, a `target_max_hp` above 0 that the producer labels with its source,
  and an item list containing 6695 that equals the active player's `:2999` items within 10 s of
  game time, AND the response carries the `notes` entry written only when the shield-cut damage is
  above 0 (it ends "(assume_shielded_target seam)"). Substitution check as G2-08.
- **G2-18** `[BLOCKED ON WIRING 2026-11-06]` (was B49) R111 `assume_caster_lowhp` (Overlord's Bloodmail 2501 "Retribution"): build it,
  drop to low HP, eyeball the missing-HP-scaled bonus AD credit. Midpoint
  `_ASSUMED_CASTER_MISSING_HP` 0.35 / cap 0.70. SOURCE: LEDGER 879.
  **AGE CHECK (lane 9 PREP s144 cycle 86, RM-1675; source read at local main `ba0df749f`, no game
  up; NOT a tick). The eyeball half is already DISCHARGED by operator ruling (the G2-18 entry in the
  DRAIN SESSION 2026-07-20 block at the top of this file: +6.00 pct at the 0.35 midpoint on the
  operator's real build, RULING "wire the live HP feed and delete the midpoint guess"). What remains
  is that ruling's code slice, and it has not shipped.** Measured: no DS HTTP route parses
  `assume_caster_lowhp` (zero hits in `agents/daemon_slayer/server.py`); only the in-process
  `compute_dps` and `compute_burst_damage` take it (`burst.py` forwards it to
  `total_missing_hp_bonus_ad`), and no RC module outside `agents/daemon_slayer/` names it, so no
  live caller can arm it. `dps.py` `total_missing_hp_bonus_ad` still reads the fixed
  `_ASSUMED_CASTER_MISSING_HP` 0.35 and takes no caster HP input, so the ruled live feed is absent.
  The dashboard's `caster_missing_hp_pct` preview float (`dashboard/routes_state.py`
  `_DS_PREVIEW_SEAM_FLOATS`) is the R5 heal-amp input on the HPS lane, not this seam. BACKLOG
  RM-1338 (DS patch 16.21.1 -> 16.22.1) cuts Retribution 12 pct -> 10 pct; the +6.00 / +12.00 pct
  figures in the drained entry were measured at the 12 pct value still current at 16.21.1. PRECONDITION for return to the drain list: a DS
  route parses the seam with a live caster HP fraction in place of the midpoint, and an RC producer
  sends `currentHealth / maxHealth` for a Bloodmail holder, recording the outbound body with `ts`
  and `gameData.gameTime`. Predicate stated NOW, graded only after that lands, in one practice-tool
  SR game holding 2501: PASS iff two recorded bodies each carry the seam ON and a caster HP fraction
  within 0.02 of `activePlayer.championStats.currentHealth / maxHealth` from a `:2999` read within
  10 s of game time of that body, one at a fraction of 0.99 or above and one below 0.65, AND the
  Retribution credit in the responses (the field the producer names when it lands) is 0 for the
  first and positive for the second. SUBSTITUTION CHECK: as G2-08 (an
  in-process `compute_dps` call, or the drained midpoint measurement, answers COMPUTES, not SENT).
- **G2-19** `[BLOCKED ON WIRING 2026-11-06]` (was B3) DSV2/3/4 `assume_takedown` / `assume_squishy_target` / `assume_ability_amp` on the
  BURST scorer `burst.py rank_items_by_burst` (NOT rank.py). Transport WIRED (OQ17). R70 added the
  Hollow Radiance Desolate takedown eruption (6664/226664) to the `assume_takedown` stream - confirm an
  HR-holder's burst reads sane next to Hubris/Collector. Client-helper emit still pending.
  **AGE CHECK (lane 9 PREP s144 cycle 86, RM-1675; source read at local main `ba0df749f`, no game
  up; NOT a tick). Producer-orphan, and "client-helper emit still pending" is STALE: the helpers
  emit, but no live caller arms them.** Measured: `agents/daemon_slayer/server.py`
  `_route_rank_assassin` parses `assume_takedown`, `assume_squishy_target`, `assume_ability_amp` and
  `target_preset`; `_route_burst` parses `assume_takedown` and `assume_ability_amp`.
  `core/daemon_slayer_client.py` `rank_assassin_for` emits all three when True and `burst_for` emits
  `assume_takedown` / `assume_ability_amp`. Callers: the one live `rank_assassin_for` call (the
  assassin branch of `rank_for_primary_archetype`, reached from `dispatch_for_coach`) passes none of
  the three, and `rank_for_primary_archetype` takes none of them; `dashboard/routes_state.py`
  `_DS_PREVIEW_SEAM_BOOLS` lists none; `burst_for`'s one live caller (`core/death_recap.py`
  `fetch_ds_profiles`) sends none. `ops/audit/ds_perm_swarm/live_flip_eyeball.py` arms them
  in-process only. The client's own comment adds two traps for a future producer: with the default
  `target_max_hp` 0.0 the Collector arm of `assume_takedown` is never credited, and any positive
  `target_armor` disables `assume_squishy_target`. PRECONDITION for return to the drain list: a
  producer sends `assume_takedown: true` to `/burst` for a live build with a
  sourced `target_max_hp` above 0, recording the outbound body with `ts` and `gameData.gameTime`.
  Predicate stated NOW, graded only after that lands, in one practice-tool SR game holding Hollow
  Radiance 6664: PASS iff a recorded body carries `assume_takedown: true`, a `target_max_hp` above 0
  that the producer labels with its source, and an item list equal to the active player's `:2999`
  items within 10 s of game time of the body, AND that body's `/burst` response carries the `notes`
  entry `compute_burst_damage` writes for the eruption (it starts "Hollow Radiance Desolate
  eruption +"); the "reads sane next to Hubris / Collector" eyeball is written against the
  producer's named surface. SUBSTITUTION CHECK: as G2-08 (`live_flip_eyeball.py`, a hand-POSTed
  body or a DS unit test answers COMPUTES, not SENT).
- **G2-20** `[BLOCKED ON WIRING 2026-11-06]` (was B6) DSP4 `score_completion_runes` (Shield Bash 8401) - **PARTIAL 2026-07-18.**
  SETTLED HEADLESS: the correct instrument was used correctly - `compute_burst_damage` was called
  DIRECTLY with a real Resolve page (not the re-rank harness this row forbids) - and the seam is
  non-inert: burst reads **+2.64%** with the runes scored. Transport WIRED (OQ17, /burst parses
  `runes`). **CAVEAT: that figure was NOT independently reproduced, and a rune-sized credit being
  rune-sized is equally consistent with the seam working and with it being mis-scaled** - the number
  alone discriminates nothing.
  LIVE RESIDUAL (glance): with a real Shield Bash page in a live game, judge whether ~+2.6 pct of burst
  is the right ORDER OF MAGNITUDE for what Shield Bash actually contributed in a fight. That is a
  magnitude judgment, not another delta.
  Re-measured 2026-11-06 (RM-1674): producer-orphan, AGE CHECK in G2-08.
  `/burst` is the only route that parses `score_completion_runes`; no live caller sends it, and
  `burst_for`'s one live caller sends no `runes` at all. The dashboard combo route
  (`dashboard/routes_ds_combo.py`) passes the request's `runes` into `compute_combo` but never the
  flag, so `burst.py` filters Shield Bash 8401 OUT of the scored set there (`if
  score_completion_runes or _rid not in COMPLETION_RUNE_IDS`); `core/laning_scenario_precompute.py`
  passes neither. So no live surface shows a Shield Bash credit to judge. Predicate stated NOW,
  graded only after a producer lands: PASS iff a recorded body carries `score_completion_runes:
  true` and a `runes` set that contains 8401 and equals `activePlayer.fullRunes.generalRunes[].id`
  from a `:2999` read within 10 s of game time of the body; the magnitude glance above is then made
  against that body's response. Substitution check as G2-08.
- **G2-21** (was B2) DS Phase-D: `apply_passive_damage` + the 4 non-every-AA `on_hit` + per-stack
  `assumed_stacks`. **NOT a clean transport flip:** `apply_passive_damage` is deliberately /dps-scoped
  (R7/R12 precedent, `rank_items` does not forward it), the on_hit remainder needs net-new cadence
  math, and `assumed_stacks` needs a live stack feed. Own-build re-ranks are unverifiable headless.
  **AGE RE-CHECK + READY (lane 9 PREP s144 cycle 124, 2026-11-09, S144-G-111; NOT a tick, NOT a
  re-open; no game, RC :8888 not answering, read at `d2d4840f1` + this lane, DS ENGINE 1.291.0,
  patch 16.22.1).** (1) CITE DRIFT, the first clause is STALE: `apply_passive_damage` is no longer
  /dps-scoped. RM-42 wired it into `rank_items` (`agents/daemon_slayer/rank.py:1001`, forwarded to
  BOTH `compute_dps` calls at `:1252` and `:1378`, rationale comment `:1184-1193`), and the server
  parses it on exactly three routes: `/dps` (`_route_dps`, `agents/daemon_slayer/server.py:706`,
  default False), `/rank` (`_route_rank`, `:868`, default False) and `/rank-onhit`
  (`_route_rank_onhit`, `:2223`, default TRUE). No other route parses it, so the bruiser and mage
  scorers never see it. On the RC side `rank_for` (`core/daemon_slayer_client.py:728`, body key only
  when True at `:834-835`) and `rank_for_primary_archetype` (`:3058`) default False. Outside
  `core/daemon_slayer_client.py`, `agents/daemon_slayer/` and `tests/` the flag is named only by the
  hand-run `tools/gated_ds_flag_eyeball.py` (`:10`, `:97`, the G2-47 eyeball), so the ONE live-app
  sender is the onhit branch, which hard-codes `apply_passive_damage=True` into `rank_onhit_for`
  (`:3406`). The carry half of this clause is now G2-47's row (GATE 2 below: RM-42 on the CARRY ranker,
  flipped TOGETHER with `apply_extra_shot_procs`, never singly). (2) THE ROW HOLDS on the
  other two clauses, and its scope is LARGER than filed. The every-AA allowlist
  `_AA_ROUTED_ON_HIT_KEYS` (`agents/daemon_slayer/_passive_damage_overrides.py:1205`) now holds 6
  keys (Warwick P, Orianna P, Gwen P, Kayle E, KogMaw W, Akshan P); the registry
  `_PASSIVE_DAMAGE_OVERRIDES` holds 34 entries, 26 with cadence `on_hit`, so 20 on_hit entries stay
  unrouted, not 4. The 4 the row names (Lux, Ziggs, Akali, Kha'Zix) are all still unrouted (measured
  in-process this cycle); `compute_dps` reads only the allowlist (`dps.py:1632-1660`,
  `aa_routed_on_hit_entry`). `assumed_stacks` is a build-time constant on 4 per-stack entries
  (Orianna 1.0 and Kai'Sa 2.0 on_hit, Darius 3.0 and Twitch 3.0 dot; fold at
  `_passive_damage_overrides.py:1123`) and no RC module reads or feeds a stack count. Both are
  ENGINE (Tier-2) code first; no game can drain them today. (3) WHAT A GAME CAN SEE TODAY:
  `core.archetype_picks.get_archetype_for` resolves Gwen / Kayle / KogMaw to primary `onhit`
  (default source, measured this cycle), so a live game on one of those three already sends the flag
  True through `/rank-onhit`; that render is G4-17's row (`tools/gated_g417_onhit_render.py`), not
  this one. Akshan and Kai'Sa resolve to `carry` (flag False on the wire), Warwick to `bruiser` and
  Orianna to `mage` (routes that do not parse it), so the allowlist credit for Akshan / Warwick /
  Orianna reaches no live surface at all. NO SECOND PREDICATE HERE: the Akshan carry flip is graded
  under G2-47 and its READY block (`tools/gated_ds_flag_eyeball.py --row G2-47`), never twice. The
  one thing this row adds to that grade is a WIRE check, stated now and graded only after a producer
  flips the carry flag (a merger follow-up, not this lane's): in a live SR or ARAM game on Akshan,
  PASS iff a timestamped record of the `/rank` request body carries BOTH `apply_passive_damage: true`
  and `apply_extra_shot_procs: true`, `champion` equal to the canonical id of my roster row's
  `championName` (`/api/state` -> `liveclient.allPlayers[]`, matched to `liveclient.activePlayer` as
  `tools/gated_g417_onhit_render.py` `_me_row` does) and `item_ids` equal to
  `liveclient.owned_item_ids` from an `/api/state` read within 10 s of game time of the body. FAIL if
  either key is absent (the default-OFF path ran, or one half of the event flipped singly).
  EVIDENCE: the body, the `/api/state` read, both timestamps, `game_time_s`, mode and queue.
  SUBSTITUTION: a hand-run eyeball body (that tool sends the flags itself) or a `/rank` reply
  computed with the flags on answers only whether the seam COMPUTES; it proves nothing about whether
  RC SENT it, and an onhit render on Gwen / Kayle / KogMaw is G4-17's evidence, never this row's.
  PROPOSAL, NOT A MOVE: the cadence-math and stack-feed
  clauses are engine work with no live half until a stack source exists (no RC reader of one exists;
  whether `:2999` exposes one was NOT probed this cycle, no game was up); a human may move them under
  "Not actually live-gated" or to the DS roadmap.
- **G2-22** (was B4) Anti-tank P3.2 - call `antitank.compute_antitank_live` with the live build +
  eyeball scaled %max-HP magnitudes. R93 added Darius E (Apprehend) as a PERCENT_PEN/SUSTAINED row
  (compute_antitank 0.0 -> 0.455, shreds_resist True), so this same eyeball surfaces Darius' shred.
  HTTP transport WIRED (OQ18) BUT no dashboard/modes caller POSTs a live build - this is a
  **code+eyeball slice, not a pure flip**. No DS restart on the flip itself.
  **AGE RE-CHECK + READY (lane 9 PREP s144 cycle 123, 2026-11-09, S144-G-110; NOT a tick, NOT a
  re-open; no game, read at `279bf6f16`, DS ENGINE 1.291.0, patch 16.22.1).** (1) THE ROW HOLDS: the
  producer is wired and the consumer is not. `compute_antitank_live`
  (`agents/daemon_slayer/antitank.py:823`) is reached only through `_route_antitank`
  (`agents/daemon_slayer/server.py:2696`; the live branch at `:2731-2738` runs when `item_ids` is
  non-empty; route table `:3258`). No RC module POSTs `/anti-tank` (`git grep` of the literal
  `/anti-tank`, and of `compute_antitank_live`, in `*.py` / `*.js` / `*.mjs` outside
  `agents/daemon_slayer/` and `tests/`: 0 hits each), and every RC consumer of the axis calls the
  STATIC `compute_antitank` (`antitank.py:730`) in-process with no stats: `core/ds_antitank_hint.py:97`
  (`build_antitank_hint`), reached from `dashboard/_deterministic_coaching.py:1373` (ARAM),
  `core/ds_coach_shadow.py:45` (the A3 shadow log behind `coaches/_base_coach.py`
  `_shadow_log_hints`), `core/ds_capability_gap.py:106` and `core/build_order_variants.py:253`; plus
  `core/comp_coverage.py:219` directly. Nothing in a live game carries a build into this axis, so no
  game can drain the row today: it is a CODE slice first. (2) SCOPE NARROWED (measured this cycle,
  in-process, `DataSnapshot.load()`): the Darius clause needs no live build at all.
  `compute_antitank("Darius")` = 0.455, top_kind PERCENT_PEN, shreds_resist True (R93 reproduces), and
  `compute_antitank_live(snap, "Darius", 11, ["3071"])` is also 0.455: Darius E carries no caster-stat
  ratio, so a build cannot move it and the static path already surfaces the shred. Only the
  seeded-ratio rows move with a build: Gwen 0.85 -> 0.915 (L11, ["3089"]; same in ARAM), Kog'Maw 0.926
  -> 0.952 (L11, ["3089"]), Vi 1.11 -> 1.1629 and Camille 0.745 -> 0.7918 (L11, ["3071"]); Vayne 0.95 is
  unchanged (control). (3) PROPOSAL, NOT A MOVE: the "eyeball scaled %max-HP magnitudes" half is a
  compute over an item list, so any synthetic build answers it headless (the numbers above are that
  eyeball); it is a candidate for "Not actually live-gated" below, for a human to move. What stays
  live is TRANSPORT only, and only after a producer lands. PREDICATE (stated now, graded only after a
  producer lands; the code half is a merger follow-up, not this lane's): in a live SR or ARAM game on
  a seeded-ratio champion (Gwen / Kog'Maw / Vi / Camille) holding at least one AP or AD item, PASS iff
  a timestamped record of the request body the producer sent to `/anti-tank` carries `champion` equal
  to the canonical id of my roster row's `championName` (`/api/state` -> `liveclient.allPlayers[]`,
  matched to `liveclient.activePlayer` as `tools/gated_g417_onhit_render.py` `_me_row` does), an
  `item_ids` set equal to `liveclient.owned_item_ids` (fallback: that row's `items[].itemID`) from a
  `/api/state` read within 10 s of game time of the body, and a `level` equal to
  `liveclient.activePlayer.level` from that read; and the surface the producer feeds shows the reply's
  `antitank_score` / `top_kind`. FAIL if `item_ids` is absent or empty while the build is not (the
  static path ran), or if the set differs. EVIDENCE: the body, the `/api/state` read, both timestamps,
  `game_time_s`, mode and queue. SUBSTITUTION: a DS reply computed by hand from the live item list
  answers only whether the axis COMPUTES; it proves nothing about whether RC SENT the build, and a
  rendered score that equals the static `compute_antitank` value is the static path, not this row.
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

  **AGE RE-CHECK + READY (lane 9 PREP s144 cycle 125, 2026-11-09, S144-G-112; NOT a tick, NOT a
  re-open; no game, RC :8888 not answering, read at `d2d4840f1` + this lane, DS ENGINE 1.291.0,
  patch 16.22.1).** (1) DEFAULTS HOLD: all twelve are still default False. The eleven EHP flags are
  `compute_ehp` keyword defaults (`agents/daemon_slayer/ehp.py:1418` kaenic, `:1423` eclipse, `:1435`
  seraphs, `:1441` fimbulwinter, `:1464` omnivamp, `:1473` revive, `:1485` stasis, `:1496`
  spell_shield, `:1507` mana_health, `:1516` resist_grants, `:1526` bonus_hp_amp), and the burst one
  is `agents/daemon_slayer/burst.py:542`. CITE DRIFT: the Line column above is stale by about +264
  (it predates the RM-118 / R194 growth of `compute_ehp`); use these. (2) THE ROW'S ACTION IS STALE:
  "arm, restart `:8860` once" arms nothing. Every one of these is a per-request body key read by
  `_opt_bool(body, key, False)` (`agents/daemon_slayer/server.py:542`) with no env or config
  default, so a DS restart changes no reply; a flip is a CODE change (an engine default or an RC
  sender), never a restart. (3) TRANSPORT, the row is LARGER than filed: the twelve split three ways.
  (a) `/ehp` ONLY (6): kaenic, eclipse, seraphs, fimbulwinter, revive, stasis are parsed only by
  `_route_ehp` (`server.py:1119-1123`, `:1053-1054`); `/rank-tank` does not parse them and the ranker
  `rank_items_by_ehp` (`ehp.py:3194`) has no such kwarg, so they can never move a RANKED list. (b)
  RANKER-REACHABLE (5): spell_shield, mana_health, resist_grants, bonus_hp_amp are parsed by `/ehp`,
  `/rank-tank` (`server.py:1272-1283`), `/hybrid` (`_route_hybrid`, `:1563-1574`) and
  `/rank-bruiser` (`_route_rank_bruiser`, `:1716-1727`); omnivamp only by `/ehp` and `/rank-tank`
  (`:1011`, `:1294`) and is SUSTAIN-only, invisible unless `score_by="sustain"` (comment
  `server.py:1005-1010`; `/rank-bruiser` accepts only blended / cc_blended, `:1698-1700`).
  spell_shield moves only `cc_blended_ehp` (`ehp.py:1490-1496`), so it is invisible under the
  default `score_by="blended"` on either ranker's sort order (the bruiser row's `hybrid_score` field
  does read `cc_blended_ehp` when enemies are sent, `agents/daemon_slayer/hybrid.py:1384-1388`).
  (c) NO ROUTE (1): `assume_item_lowhp_magic_crit` is named by no route in `server.py` (not
  `_route_burst` either) and by nothing under `core/` (git grep this cycle); its only consumer is
  `compute_burst_damage` (`burst.py:542`, `:847`) and `ability_dps.py:1508-1518` keeps it
  documented-inert, so no served list can ever show it. (4) NO LIVE SENDER for any of the twelve:
  `ehp_for` (`core/daemon_slayer_client.py:1131`) and `hybrid_for` have no non-test caller, and the
  three ranker senders forward none of them: the tank branch of `rank_for_primary_archetype`
  (`/rank-tank`, `:3168-3180`), its bruiser branch (`rank_bruiser_for` -> `/rank-bruiser`,
  `:3212-3229`) and `recommend_defensive_items_via_ehp` (`/rank-tank`, `core/defensive_picks.py:351`,
  call `:402`), which itself has no production caller. So a game today shows NONE of the twelve on
  any surface, ON or OFF, and nothing here is drainable until a producer flips one. READY (graded
  only after a flip; a merger follow-up, not this lane's): for a flag in group (b), in a live SR game
  on a champion whose primary archetype is `tank` or `bruiser`
  (`core.archetype_picks.get_archetype_for`), PASS iff a timestamped record of the matching
  `/rank-tank` or `/rank-bruiser` request body carries the flipped key `true`, `champion` equal to
  the canonical id of my roster row's `championName` (`/api/state` -> `liveclient.allPlayers[]`,
  matched to `liveclient.activePlayer`) and `item_ids` equal to `liveclient.owned_item_ids` from an
  `/api/state` read within 10 s of game time of the body, AND (omnivamp only, `/rank-tank` only)
  `score_by` is `"sustain"`, (spell_shield only) `score_by` is `"cc_blended"`. FAIL if the key is
  absent (the default path ran) or the score_by gate does not match (armed but invisible). The
  EYEBALL itself is then the human read of the served list, never this predicate. EVIDENCE: the
  body, the `/api/state` read, both timestamps, `game_time_s`, mode and queue. SUBSTITUTION: a
  hand-built `/ehp`, `/rank-tank` or `/rank-bruiser` POST with the flag on answers only whether the
  seam COMPUTES; it proves nothing about whether RC SENT it, and a reply under
  `score_by="blended"` is not evidence for spell_shield or omnivamp. Groups (a) and (c) have NO
  predicate: they need a ranker kwarg (a) or a route (c) first, which is DS engine work (Tier-2),
  not a game. PROPOSAL, NOT A MOVE: a human may file (a) and (c)
  as DS seam rows and narrow this battery to group (b).
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
  **AGE CHECK (lane 9 PREP s144 cycle 129, S144-G-116; source read at local main `d2d4840f1`, DS
  16.22.1 / ENGINE 1.291.0, no game up (RC :8888 refused at 2026-11-09T05:07); NOT a tick). The
  mechanism half holds, the seam has NO live producer, and the live residual does NOT wait on one.**
  Holds: `_item_general_dr._GENERAL_DR_UPTIME` is still `0.4`; `_ITEM_GENERAL_DR` still maps `3869`
  to `(0.35, 0.25)` and `664644` to `(0.40, 0.40)`, with `444644` as the Arena mirror. At 16.22.1
  `items.json` still lists 3869 Celestial Opposition (maps 11 and 453), 664644 Crown of the
  Shattered Queen (map 11) and 444644 (map 30 only). DDragon's 3869 prose carries no magnitude
  ("Reduce incoming champion damage for 2 seconds after taking damage from a champion"); the 35%/25%
  is Meraki's `{{rd|35%|25%}}` in the 16.22.1 `items_meraki.json`. 664644's DDragon prose still says
  40%. Producer-orphan, measured with `inspect.signature`: the DS functions that take the flag are
  `ehp.compute_ehp`, `ehp.rank_items_by_ehp`, `hybrid.compute_hybrid` and
  `hybrid.rank_items_by_hybrid`, and `server.py` parses it in `_route_ehp`, `_route_rank_tank`,
  `_route_hybrid` and `_route_rank_bruiser`. The client functions `rank_tank_for`, `ehp_for`,
  `rank_bruiser_for` and `hybrid_for` take it, but `rank_for_primary_archetype` and
  `dispatch_for_coach` do not. The tank and bruiser branches of `rank_for_primary_archetype` call
  `rank_tank_for` / `rank_bruiser_for` without it, and `core/defensive_picks.py` calls
  `rank_tank_for` without it. `_DS_PREVIEW_SEAM_BOOLS` does not list it, and no `web/` file and no
  code file outside DS, the client and `tests/` names it. So no live recommendation reads the 0.4
  today. That bounds what the row is WORTH (a different uptime would move no live surface until a
  producer lands), but not whether it can DRAIN: the residual is an observation of the GAME's own
  buff uptime, not of anything RC sends. READY, so the drain is copy-paste. Practice-tool SR
  (GATE 2), the operator holding 3869 or 664644 and taking hits from bots in a fight. The Live Client
  API carries no buffs (`dashboard/_liveclient.py:334`), so the source is pixel: GET
  `http://127.0.0.1:8889/latest-frame` with `X-RC-Token`, plus `/latest-frame/meta` `ts` for each
  sample, at about 1 s. FIGHT WINDOW, fixed before the game: from the first `:2999`
  `activePlayer.championStats.currentHealth` drop while an enemy champion is in the frame to the last
  such drop, closed by a 3 s gap with no drop. u = (samples in the window whose buff bar shows the
  Blessed / Safeguarded icon) / (samples in the window). PREDICATE, stated NOW: at least 10 samples
  in one window; u in [0.30, 0.50] means 0.4 is RIGHT, u > 0.50 means TOO LOW and u < 0.30 means TOO
  HIGH. Report one u per item; 3869 and 664644 are graded separately and are not averaged. EVIDENCE:
  u, n, the item id, the window's start and end `gameData.gameTime`, and each sample's frame `ts`
  checked against `gameTime` (a frame older than 2 s is dropped, not counted). Frames are 1280x720
  (G2-41), so a sample whose buff bar cannot be read is dropped and counted in the report, never
  scored as absent. SUBSTITUTION CHECK: a DS `/ehp` or `/rank-tank` delta with the flag on restates
  `1/(1 - dr * 0.4)` and so answers COMPUTES, not UPTIME. A dashboard render answers neither. One
  screenshot of the icon proves it can be up, not how long it stays up. The Arena 444644 magnitude
  stays GATE 5 (G5-08, re-checked s144 S144-G-105).

### `[BATCH OVERLAY-PIXEL]` - overlay up, one screenshot pass

- **G2-25** (was B24) Overlay populated pixel-capture family: OVL1 settings controls (`f621168d`);
  R33 ward_cue / spike_cue / objective_chips / minimap_zoi / minimap_rect (`2b03c529`); R40 draft_elo
  chip + ward_heat strip (`4a1622cc`); W3E callouts + lead_projection; spike-markers live-clock cursor;
  item-662 first-match no-flash confirm; OQ14 Item Shaper Row4 SHAPER strip (`dc45f749`). Also folds
  the BATCH B minimap gold-border render check (after an rc-shell RELAUNCH, confirm the gold border
  lands fixed to the minimap) + the BATCH C gauge-row / enemy-chip-wrap render. STATUS: NOT drained
  2026-07-04 (frame endpoint probed http + X-RC-Token, game ended before a clean grab). SOURCE:
  LEDGER 662 + 735 + 799.

  **AGE RE-CHECK + READY (lane 9 PREP s144 cycle 126, 2026-11-09, S144-G-113; NOT a tick, NOT a
  re-open, nothing struck; no game, RC :8888 and :2999 not answering, read at `d2d4840f1` + this
  lane).** The family is SMALLER than filed: of its 14 subjects, 6 can no longer be captured on the
  overlay at all, and 8 are live. CITE DRIFT: `f621168d` is a pre-rewrite hash absent from
  `.git/filter-repo/commit-map`; OVL1 is `7db1ebbe4` (git log --grep OVL1). (1) NO OVERLAY HALF
  LEFT (a human moves these; this lane does not strike):
  (a) **ward_cue**: no renderer. There is no `web/js/panels/ward_cue.js`; the widget was dropped
  2026-07-05 because Live Client exposes no ward cooldown (`web/js/lib/overlay_layout.js:74-75`,
  "w-trinket / Ward Cue removed"); `#am-ward-cue` in `web/index.html` is an orphan mount nothing fills.
  (b) **spike_cue**: deleted for Riot compliance (`docs/OVERLAY_COMPLIANCE_PLAN.md` row B3;
  `web/js/main.js` comment above `renderStatsPanel` in the live dispatch, "Do not reinstate").
  (c) **W3E callouts + lead_projection**: CLASS 2. B4-b blanks both TOP-LEVEL keys while a game is
  live (`dashboard/_state_builder.py:455-457` `LIVE_SUPPRESSED_ENVELOPE_FIELDS`, applied at `:1053`),
  because both feeds are imperatives (spike lines, "Drake spawns 5:00 - set up vision", "Big lead:
  dive or roam"). A POPULATED in-game capture would be the compliance regression; the in-game
  check INVERTS (predicate (P1) below).
  (d) **spike-markers live-clock cursor**: NOT BUILT (`web/js/panels/spike_markers.js:10-14` and
  `:200-201`, "v1 omits it"), and `#am-spike-markers` is `display:none` on the overlay
  (`web/css/overlay.css:197`).
  (e) **ward_heat strip**: `display:none` on the overlay (`web/css/overlay.css:198`, the GPU-light
  block); it paints only on the 1920 dashboard, so it is not an overlay subject.
  (f) **BATCH C enemy-chip-wrap**: its subject is the enemy summoner-spell chip (LEDGER 799 BATCH C
  item 3), deleted for Riot compliance (row B1); nothing named enemy-chip remains in `web/`.
  (2) LIVE, with the render path at HEAD (all `body[data-shell="overlay"]`, rc-shell overlay ON):
  (g) OVL1 settings strip `#ovset` in w-ovds (`web/js/panels/overlay_ds_controls.js:255-300`):
  `#ovset-pulse` "Change pulse" and `#ovset-revert` "Auto-passive (s)" [3..120] are still there,
  plus later rows (rank tier, role, keep, pin, separate, zones, opacity). The revert value is also
  G6-02's knob; a G6-02 pass does not capture this strip, and this capture does not tick G6-02.
  (h) objective_chips `#am-obj-chips` inside w-call, live dispatch `web/js/main.js:1688`, shows
  only while a respawn is pending (`liveclient.objective_events`, `objective_chips.js:112-122`).
  (i) minimap_rect `#am-mmrect` (w-mmrect, `main.js:1681`) with the BATCH B gold hairline
  `web/css/overlay.css:804-816` (2px gold 0.85; its `::before` is off, `:817`), and (j) minimap_zoi
  `#am-zoi-canvas` (`main.js:1685`). Both need top-level `minimap_rect`, built only for `mode_key`
  sr / aram / brawl (`dashboard/_state_builder.py:845-851`), so never in Arena or TFT.
  (k) objective gauges `#am-obj-gauges` (w-objgauges, `main.js:1692`): BATCH C's one-row 3-dial
  layout; SR only (`objective_gauges.js:253-256`, null unless `mode == "sr"` and a game clock).
  (l) draft_elo chip `#am-draft-elo` in w-build (`overlay.css:572-600`, fetch `/api/draft-elo`,
  `draft_elo.js:54`). (m) SHAPER row `bm-shaper` in w-build (`web/js/panels/active_match.js:1019-1021`,
  `renderShaperStrip`, fetch `/api/ds-shape`). (n) item-662 first-match no-flash: rc-shell
  `shouldShowOverlayNow` (LEDGER 662); observed once at the FIRST match launch after an rc-shell
  relaunch, by eye, not from a frame.
  **CAPTURE-SOURCE TRAPS (state them before any game):** `:8889/latest-frame` is a GDI BitBlt of the
  desktop, so it DOES include the overlay layer, but only while `obs.frame_source` is OFF: when that
  flag is on, the OBS frame REPLACES it and never shows the overlay (`vision_server/_frame.py:183-191`).
  The frame is also downscaled to 1280 wide (`_frame.py:93`), so the 2px minimap hairline is about
  1.3px there; grade (i) on a full-resolution operator capture, not on the relay frame.
  **PROBE (copy-paste, from a worktree, read-only; a practice SR game, overlay ON, after a dragon is
  taken):** `curl -sk https://127.0.0.1:8888/api/state > _scratch/g225_state.json`, then
  `curl -s -H "X-RC-Token: $TOK" http://127.0.0.1:8889/latest-frame/meta` (frame `ts`) and the
  frame itself into `_scratch/` (never committed). Field paths: `mode_key`, `liveclient.game_time_s`,
  `liveclient.objective_events`, `minimap_rect`, `zoi`, `callouts`, `lead_projection`.
  **PREDICATES (stated before any game):** (P1) CLASS-2 inverse, a SENT check graded on
  `/api/state` alone: PASS iff, with `liveclient` non-empty, `callouts == []` and
  `lead_projection == {}`; FAIL on any non-empty value (the B4-b blanking leaked). (P2) per live
  subject (g)-(m): PASS iff its precondition holds in the SAME state read (mode sr; for (h) a pending
  respawn in `objective_events`; for (i)/(j) a non-null `minimap_rect`, and for (j) a non-null
  `zoi`) AND the frame, whose `ts` is within 10 s of the state read, shows the widget's own text or
  hairline at its registry anchor (`overlay_layout.js` WIDGETS `x`/`y`, or a dragged position)
  with no clip at the viewport edge. A precondition that does not hold is NO-RESULT, never PASS.
  (P3) for (n): PASS iff no full-screen flash before the widgets settle at the first match launch.
  **SUBSTITUTION CHECK:** the `/api/state` read answers only whether the data was SENT; it is never
  evidence that a widget RENDERED (except P1, whose subject IS the sent envelope). A ui_mock render,
  a headless Chromium overlay render, a node test or a dashboard (non-overlay) screenshot is the
  compute half and drains nothing.
- **G2-26** (was the pixel half of C13) ~~R38 enemy_spells `stats_panel` RENDERED PIXEL capture. The
  DATA path is live-proven TWICE (LEDGER 769 + LEDGER 820 2026-07-08, 5 enemies x 2 spells); LEDGER
  820 explicitly records "CSS visual verify PENDING (overlay hidden)". Best read vs real enemies
  (GATE 3 or 4) but the widget renders at any gate.~~ **MIS-FILED, CLASS 1: the subject is gone from
  the tree (lane 9 PREP s144 c65, RM-1511, source read at `cf2b410bb`, 2026-11-05; NOT a tick, no
  game involved).** C13 was "R38 enemy_spells tap-tracker + stats_panel populated in-game capture",
  both born in `c2d2fe453` (2026-06-28). Neither half is capturable as filed: (1) the enemy_spells
  tap-tracker was DELETED for Riot compliance in `538c61e4b` (2026-08-11: panel
  `web/js/panels/enemy_spells.js`, the `enemy_spells` producer in `dashboard/_liveclient.py`, the
  `#am-enemyspells` mount, CSS and its tests), because Riot's third-party rules ban "Tracking of enemy
  summoner spells cooldowns" (`docs/OVERLAY_COMPLIANCE_PLAN.md`, row B1 "DONE - deleted"). The removal
  is guarded INVERTED: `tests/snapshot_panels/test_overlay_view.py`
  `test_overlay_has_no_banned_cue_mounts` fails if `#am-enemyspells` renders,
  `tests/test_am_grid_child_placement.py` `EXPECTED_DIRECT_CHILDREN` was re-baselined 13 -> 10 for it,
  and the producer comment in `dashboard/_liveclient.py` reads "Do not reinstate the enemy_spells key".
  A capture of it would need the banned surface back. (2) The `stats_panel` half was REWORKED, chiefly
  by `ee3d6c90f` (WP-A4b, 2026-06-28) and then item-8 `a553450be` (2026-07-12; the row's `f9996bc8` is
  its pre-rewrite twin, not reachable from HEAD),
  into the "You vs rank average" panel (`web/js/panels/stats_panel.js` header), whose live render
  eyeball is already owed as **G2-27 (a)**; it is not a separate row. The
  2026-07-20 drain's "G2-26 pixel capture done" (head of doc) predates the removal and stands as
  history only. No live half is left here. Moving the row to "Not actually live-gated" is a human doc
  edit.
- **G2-27** `[NEW ROW 2026-07-18]` Overlay item-8 rank-tier stats panel: (a) the live render eyeball
  (`a553450be`; the row's original `f9996bc8` is its pre-rewrite twin, not reachable from HEAD), and
  (b) ~~the LEDGER 873 (C) deferred finding - the `w-stats` default position
  (`web/js/lib/overlay_layout.js:67`, x40) COLLIDES with the primary `w-call` coach panel (180,130),
  so on FIRST run the coach call paints over the provenance badge before the operator repositions.~~
  Tuning the default anchors needs an in-game eyeball. SOURCE: LEDGER 873; RM-04.
  **(b) STALE BY AGE, the filed collision is gone (lane 9 PREP s144 c66, RM-1512, source read at
  `f81f7d463`, 2026-11-05; NOT a tick, no game).** The 2026-07-27 collision sweep `edf32faa9` (R198)
  moved `w-stats` from (40,250) to (1670,220) in the `WIDGETS` array of `web/js/lib/overlay_layout.js`
  (its own comment: the 240px panel "cannot clear w-call (180..390 x) on either side inside the 482px
  left gutter"), and the same commit added `tests/test_overlay_default_layout_collision.py`, which
  crosses that array with the `overlay.css` `--ovx-w` map and fails on ANY overlapping or off-screen
  default pair (only w-arambalance vs w-objgauges is exempt). Re-run this cycle: 4 passed, exit 0. So
  the default-vs-default half of (b) is machine-guarded and closed; what that guard cannot see is the
  League HUD under the overlay. The residual eyeball folds into (a) as CHECK (a2) below.
  **(a) READY (same cycle; NOT a tick).** Precondition: a live SR or ARAM game, overlay shell up,
  rank tier set in DS Settings (`rc-pgr-rank-tier`), and the field at DEFAULTS (Alt+Shift+R once, or
  confirm `localStorage["rc-overlay-layout"]` holds no `w-stats` entry), else the box is wherever the
  operator dragged it and (a2) measures nothing. Probes, all read-only:
  P1 `curl -sk https://127.0.0.1:8888/api/state` -> `liveclient.level`, `liveclient.cs`,
  `liveclient.kda`, `liveclient.kill_participation_pct`, `liveclient.game_time_s`, `mode_key` (the
  panel's You column and bracket read the liveclient keys through `renderStatsPanel(lc, opts)` in
  `web/js/panels/stats_panel.js`, its mode comes from the poll's `state.mode`, and it hides unless
  `liveclient.hp_max` is non-zero);
  P2 `curl -sk "https://127.0.0.1:8888/api/rank-tier-bench?tier=<tier>&mode=<SR|ARAM>&bracket=<early|mid>"`
  -> `ok`, `source`, `n`, `stats.cs.avg`, `stats.kda.avg`, `stats.kp.avg` (bracket = early under
  14 min of `game_time_s`, else mid);
  P3 the rendered overlay itself, seen by the operator or an attended drain capture of the overlay
  window, timestamped against P1's `game_time_s` (a lane never captures).
  CHECK (a1) PASS iff, in one P1 window: `#am-statspanel` is visible; its You cells show LVL =
  `liveclient.level` and CS = `liveclient.cs` (within one `/api/state` poll of `main.js`); the
  badge reads `<Tier> estimate` when P2 `source` is `static`, `<Tier> live avg` when it is `live`,
  or `<Tier> -` when P2 `n` is 0 (`no benchmark` is PASS only in Arena); and each Avg cell equals
  the matching P2 `stats.*.avg` or shows `-` exactly where that avg is null. FAIL = hidden with `hp_max` non-zero, a You cell that disagrees with P1, or
  a badge or Avg that disagrees with P2. CHECK (a2) PASS iff, at defaults, the panel box at design
  (1670,220), 240 wide, paints over no League HUD element the operator must read (the right-edge
  kill feed / announcement column and the top-right score strip are the candidates); FAIL names the
  covered element, and the fix is a new default anchor plus a re-run of the collision guard.
  EVIDENCE CONTRACT: the cell values, P1 and P2 bodies with their fetch times, the game mode, queue and
  `game_time_s`, and the overlay sighting with its time. SUBSTITUTION: P1 and P2 prove only that the
  inputs COMPUTED; a `?ui_mock=1` render, a `node --test` pass or the collision guard proves the
  renderer and the geometry against fixtures. Only P3, matched cell by cell to P1/P2 from the same
  window, answers whether the panel RENDERED the live values over a live HUD. A `:8889/latest-frame`
  is NOT P3 unless the drain first shows that frame carries the overlay layer.
- **G2-28** `[NEW ROW 2026-07-18]` ~~RM-05 round-1 shipped-fix live-verify (LEDGER 914 S4+S7,
  `a486142b`): the MISSING-IN-GAME cluster (`rn-lead` / `rn-choices` / `rn-callouts` / `w-spike`) was
  ROOT-CAUSED - the panelset-gating hypothesis is DISPROVEN (panelset gating is retired/dead, pinned
  by `test_overlay_route_smoke.py`); the mounts are DATA-gated and their only reliable in-game feed is
  the E6 poller, which was mode-gated to sr/aram/brawl and is now split so coaching mounts also feed
  arena/tft. SR/ARAM/brawl needed no code change and needs only the live-verify; the arena/tft fix
  needs its own. ALSO folds the LEDGER 809 E6 fix: lead_projection / callouts / coach.choices /
  liveclient now refresh from the unconditional 2s `/api/state` poll in `main.js` (they were dark
  in-game, gated on a WS push that never fires)~~ + the minimap_rect trim calibration (18px left, 14px
  top) at 2560x1440. CONFIRMED-OK already: `am-mmrect` ZOI markings DO show in-game.
  **MIS-FILED BY AGE, CLASS 1: the behaviour it asks to see was REVERSED for Riot compliance (lane 9
  PREP s144 c67, RM-1513, source read at `a9b178c27`, 2026-11-05; NOT a tick, no game).** The row
  wants the four mounts POPULATED in a live game; two compliance commits since filing make a populated
  mount in a live game a defect. (1) `w-spike` is gone: `538c61e4b` (B3, 2026-08-11) deleted the
  power-spike cue mount (`web/index.html` am-grid comment "Do not reinstate";
  `docs/OVERLAY_COMPLIANCE_PLAN.md`). (2) B4 (RM-189, two commits, 2026-08-12) blanks all three
  remaining feeds while a game is live, server-side and client-side: B4-b `f2b7c4bae` added
  `dashboard/_state_builder.py` `LIVE_SUPPRESSED_ENVELOPE_FIELDS = ("callouts", "lead_projection")`
  via `suppress_live_envelope`, and B4-a `25540abab` had already put `"choices"` in
  `LIVE_SUPPRESSED_FIELDS` via `suppress_live_directives` (cite corrected s144 c93, S144-G-84:
  `git show 25540abab` / `f2b7c4bae -- dashboard/_state_builder.py` add each symbol; both gated on
  `core/live_game_gate.py` `is_live_game`, any of `LIVE_GAME_FLAGS` = has_game / aram_mode /
  arena_mode / tft_mode / brawl_mode), and B4-b's `web/js/lib/live_directive_gate.js`
  `directivesAllowed` gates `renderLead` / `renderCallouts` (`web/js/panels/callouts.js`) and `renderCoachChoices`
  (`web/js/panels/coach_choices.js`) to the clear-and-hide branch. The S7 split itself (reachable as
  `e6ac21b0e` + merge `a87e6ef11`; the row's `a486142b` is its pre-rewrite twin, not reachable from
  HEAD) still stands in `web/js/main.js` `pollMinimap`, so the arena/tft poll now feeds those
  renderers only for them to hide. The 2026-07-18 "3 of 4 verified live" at the head of this doc
  predates B4 and stands as history only. Re-run this cycle: `tests/test_b4_client_directive_gate.py`
  + `tests/test_b4_live_directive_suppression.py` 46 passed, 82 subtests, exit 0. The minimap_rect
  trim calibration half is NOT struck: `minimap_rect` is in neither B4 list, so it stays owed as filed.
  **RESIDUAL READY, the INVERSE check (same cycle; NOT a tick).** What no fixture can show is that a
  REAL live tick is blanked, and TFT is the mode where it already failed once (S134 T1, 2026-10-25:
  SR callouts painted through a live TFT match with `liveclient` {}). Precondition: a live game in any
  mode, overlay shell up; Arena and TFT are the windows this row was filed for and are worth the most.
  Probes, all read-only: P1 `curl -sk https://127.0.0.1:8888/api/state` -> `mode_key`, `liveclient`
  (empty or not), `lcu.phase`, `callouts`, `lead_projection`, `coach.choices`, with its fetch time;
  P2 `ops/runtime/health.json` -> `has_game`, `aram_mode`, `arena_mode`, `tft_mode`, `brawl_mode`,
  INFORMATIONAL ONLY, never graded: the server gate reads a SERVED copy, not this file -
  `apply_standalone_tft_mirror` sets `tft_mode` on the served copy only (standalone-client TFT), and
  `_gate_health` adds `has_game` when `unidentified_live` (both `dashboard/_state_builder.py`), so a
  correctly blanked TFT or unresolved-mode game can show all five disk flags false;
  P3 the rendered overlay, seen by the operator or an attended drain capture of the overlay window
  (a lane never captures), timestamped against P1. LIVE = P1 `mode_key` in sr / aram / arena / tft /
  brawl with a non-empty `liveclient`, or a non-feed mode (tft, unresolved) with `lcu.phase`
  `InProgress` (the `isLiveGame` predicate). CHECK PASS iff, in one LIVE window: P1 `callouts` is
  `[]`, `lead_projection` is `{}` and `coach.choices` is `[]` (keys present, blanked), and P3 shows
  none of `#rn-lead` / `#rn-callouts` / `#rn-choices`.
  FAIL (a compliance defect, not a polish item): any of the three feeds non-empty in a LIVE window
  (the server leaked even if the client gate hid the mount - the content is on the wire; record P2
  beside it as a diagnostic), or a mount visible. Champ select (`lcu.phase`
  `ChampSelect`, `liveclient` {}) is NOT live and may legitimately show all three; it is no evidence
  either way. EVIDENCE CONTRACT: P1 and P2 bodies with fetch times, mode, queue, `game_time_s` (or
  the TFT stage), and the P3 sighting with its time. SUBSTITUTION: the B4 tests prove the predicate
  and the blanking on fixtures, and a `?ui_mock=1` render proves the renderer; only a P1 body from a
  real live tick answers whether the SERVED feed was blanked, and only P3 answers whether the mount
  stayed hidden over a live HUD. Moving the struck half to "Not actually live-gated" is a human edit.
- **G2-29** (was B26) ZOI shading alpha/blur live tune (MAX_ALPHA 0.55 / ZOI_BLUR_PX 12 shipped,
  pending operator verify) + `#rn-choices` live DOM inspect (has data + renderer runs, absent in DOM).
  Native-res grab (`ac50f1af`) is the foundation. The ARAM flood-tint question re-checks at GATE 3.
  (s144 c67, RM-1513: the `#rn-choices` live DOM inspect is moot in a live game: B4 blanks
  `coach.choices` and hides the mount by design, so "absent in DOM" in-game is the PASS; see G2-28.)
- **G2-30** (was E6) OVERLAY headless-polish LIVE-RECON punch-list (operator LIVE-GATED the WHOLE
  remaining set 2026-07-05): build-META knob-steppers + item right-click radial, drag/move system,
  context-menu item tooltip crop/position, PR enemy-spell chip cooldown timer, gauges 1-line layout.
  Each fix needs the operator's live Ctrl+Alt+A verify before it lands - root-cause allowed, shipping
  blind FORBIDDEN. Several sub-items now have shipped fixes owed a verify: see G2-28 / G2-32 / G2-33.
  (s144 c65, RM-1511: the "PR enemy-spell chip cooldown timer" sub-item is DEAD, not owed: the
  tracker was deleted for Riot compliance in `538c61e4b`; see the struck G2-33.)
  DISPOSITION NOTES from RM-05: build META row should stay STATIC; DMG/SURV/UTIL knob steppers dead;
  item right-click 5-choice radial dead; ward_cue teardown is a deliberate live-session job (live
  serializer + test + overlay DOM contract), never a blind headless delete.
  **AGE CHECK (lane 9 PREP s144 c130, S144-G-117, source read at `8d7fe9b27`, 2026-11-09; NOT a
  tick, no game involved).** The punch-list's primary source is the 2026-07-05 LIVE-RECON PUNCH-LIST
  in `docs/ROADMAP_HISTORY.md` (operator eyeball of the real overlay in a practice SR game); the
  RM-05 entry there (2026-07-17) is a later status write-up that restates it and names the tooltip
  sub-item more narrowly than this row: "context-menu/radial tooltip cropped icon + far positioning
  (plain hover tooltip is fine)". **"dead" in the disposition notes means "does not work", not
  "remove":** the 07-05 recon files all three under BUGS - "build META row should stay STATIC (the
  meta build does not shift per state tick); the DMG/SURV/UTIL knob +/- steppers do not work; the
  item right-click 5-choice radial ... does not work". Eight subjects, re-measured one by one:
  (1) build-META row STATIC - OWED A LIVE CHECK (CHECK M). Code read only: in
  `web/js/panels/active_match.js` the Meta / Ultimate rows get `noDelta: true` and no `onOverride`
  (no radial, no delta badge) and the `_cycleMeta` handler is gone from that file (stale comments in
  `web/js/lib/overlay_item_radial.js` still name it). But the Meta row's CONTENT is
  `_maybeRefreshBuildOrder` (POST `/api/build-order`), re-fetched whenever level or owned items change
  and at least every `_BUILD_ORDER_COOLDOWN_MS` (8 s), and both static rows go through
  `_bmPartitionOwned` (owned first). Whether it "does not shift per state tick" is not settled by
  reading the code.
  (2) DMG/SURV/UTIL knob steppers "do not work" - STILL SHIP, OWED A LIVE CHECK (CHECK S), and the
  last live report after a fix is a FAILURE: `74416df5a` (2026-07-06, "dead DMG/SURV/UTIL counters:
  the shaper strip now carries data-rc-zone") came the day after the recon, but LEDGER 859
  (2026-07-11) re-reports "DMG/SURV/UTIL +/- + shaper knobs have no visible effect (root-cause)", and
  LEDGER 860's panel-interactable map does not list them. `active_match.js` still appends the
  `bm-shaper` row via `renderShaperStrip` (`web/js/panels/ds_shaper.js` sets `data-rc-zone`), and no
  `body[data-shell="overlay"]` rule hides `.bm-shaper` (`web/css/overlay.css` hides only the FIGHT
  MODEL `.bm-row.bm-knobs`). No later commit is named here as the fix for "no visible effect".
  (3) item right-click radial "does not work" - STILL SHIPS, owed a live check under G2-31 (D2 / D3).
  No click-zone fix was needed: that wiring PREDATES the recon (the LIVE strip and the ring were both
  made `data-rc-zone` in `0a7ea058f`, 2026-06-29; `74416df5a` only carried the attribute into the
  3-row redesign). Two radial fixes shipped after the recon: `320126f2d` (2026-07-11, LEDGER 860,
  MUTE drops the item from LIVE rows + condensed ring) and `eccb6be29` (2026-07-12, LEDGER 870, the
  center-wedge overlap, after the operator live-QA'd the overlay from screenshots). LEDGER 870
  implies the ring OPENED live by then (an inference from the record, not new evidence); whether a
  wedge click lands is G2-31 D2, and the likely remaining live defect is the position, sub-item (5). This REFUTES the premise of G2-31's "OPERATOR CALL FIRST" (it read
  "dead" as a remove ruling); see the note added there.
  (4) drag/move system - owned by G2-32 (AGE CHECK + READY, with `tools/gated_g232_layout_diff.py`).
  (5) context-menu/radial "cropped icon + far positioning" - ROOT CAUSE ON DISK (Class 1), a code fix
  owed before any live check is worth running: `overlay_item_radial.js` `_open` copies the body zoom
  onto the ring (`r.style.zoom = String(_bodyZoom())`, ring mounted on `<html>`, `position:fixed`),
  measures it post-zoom, clamps in SCREEN px, then writes `style.left/top` WITHOUT dividing by the
  zoom. `web/js/lib/overlay_tooltip.js` `_place` has the identical mount and zoom, and divides by z
  for exactly this symptom ("tooltip appeared far right/below the anchor at any overlay ovscale !=
  1", fix `9f96ff3de`, 2026-06-29) - which is why "plain hover tooltip is fine" and the radial is not.
  At body zoom z the ring renders z-times right/down of the cursor (far positioning) and past the
  clamp near the right/bottom edge (cropped). At z = 1 (`--rc-overlay-scale` at the 1920 baseline,
  `overlay.css` `body[data-shell="overlay"]` `zoom`) the defect is invisible.
  (6) PR enemy-spell chip cooldown timer - DEAD (above, RM-1511).
  (7) objective gauges 1-line layout - CLOSED, RULED HORIZONTAL 2026-07-20 (G2-34, struck).
  (8) ward_cue teardown - the widget went 2026-07-05 (`d0ca9945`, recon-confirmed gone) and the
  orphan `web/js/panels/ward_cue.js` headless in `8c9560951` (2026-07-09); the "live-session job"
  wording is the 2026-07-12 correction in the same ROADMAP_HISTORY block. What remains reads by no client:
  `dashboard/_liveclient.py` still sets `out["ward_cue"] = compute_ward_cue(...)` and
  `web/index.html` keeps a `hidden` `#am-ward-cue` div that no script fills (git grep over `*.py`,
  `*.js`, `*.mjs` outside `core/ward_cue.py`, `tests/` and `docs/` finds no reader). A
  `Not actually live-gated` CANDIDATE for a HUMAN to move (a field nothing reads needs no game to
  delete); a lane does not move it.
  READY, the live-checkable rest (one overlay-up pass, operator present; a lane never clicks or
  captures). Precondition: a live SR or ARAM game, rc-shell overlay up, `w-build` visible.
  P1 `curl -sk https://127.0.0.1:8888/api/state` -> `mode_key`, `liveclient.gameData.gameTime`,
  fetch time. P2 in the overlay page console: `getComputedStyle(document.body).zoom` (record z).
  CHECK R (sub-item 5, only after the zoom fix lands): with z != 1,
  right-click a LIVE-row icon near the widget's right edge; PASS iff `#rc-item-radial`'s
  `getBoundingClientRect()` centre is within 12 px of the click point (or clamped 6 px inside the
  viewport) and the whole ring is inside `innerWidth` x `innerHeight`; FAIL = ring offset by about
  (z - 1) x the click coordinates, or clipped. With z = 1 record "not reproducible at z = 1"; that is
  neither a pass nor a fail. CHECK M (sub-item 1): watch the Meta Build row for at least 30 s (three
  refetch windows) with no level-up and no purchase; PASS iff its item order is identical at every
  sighting; FAIL = the order changes while neither level nor owned items changed. After a purchase the
  only allowed change is the bought item moving to the owned-first block. CHECK S (sub-item 2): click `+` on DMG; PASS iff the
  `.bm-shaper-val` for DMG steps by 1 within about 1 s and the game did not take the click (no
  move order); FAIL = no step, or the click went through to the game. EVIDENCE CONTRACT: P1 body with
  fetch time, mode, game_time, z, and per check the click point, the ring rect or the value before /
  after, and the sighting time. SUBSTITUTION: `tests/test_overlay_d2_item_radial.py` is grep-style
  (it asserts the word `zoom` appears, not the arithmetic), and `ds_shaper.test.mjs` drives a DOM
  shim; neither saw the click-through overlay, so neither answers whether the ring LANDED under the
  cursor or the step LANDED in game. Nothing ticked; no count moved.

### `[BATCH OVERLAY-INTERACT]` - overlay up, one pass of click / drag / hover

- **RM-1272** `[NEW ROW 2026-11-05]` phase surfaces and hotkey reminders, live half; the build read a mock capture only (`?ui_mock=1`, LEDGER 2031). CHECK in a real game after an rc-shell relaunch: reminders show Ctrl+Shift+A on `w-launcher` and `w-build`; the read-only IPC returns the shell's binding map; the field strips to the launcher over the end-of-game screen; hidden `w-lead` and `w-callouts` stay hidden. Not counted in the OPEN figure above.
- **RM-1384** `[NEW ROW 2026-11-05]` the overlay window in champ select and loading, a DECISION owed to a live session (operator, chat 2026-11-05, VERBATIM: "RM-1384 - NOT SURE - WAIT FOR LIVE GATED"; LEDGER 2054; row in `BACKLOG.md`, OPEN). `liveGameFromState` (`rc-shell/src/overlay_state.js`) is unchanged by RM-1272, so the phase table's champ select and loading rows are true of the field but paint no pixel in normal play, and the companion carries them. CHECK in one session that passes through champ select and a loading screen (a practice-tool lobby does both), rc-shell relaunched: record whether the overlay window shows in each phase and whether it should, against the S134 T1 measured rule; if it should, read the phase table back live in both phases. Gated on a live session, never closed synthetically. Not counted in the OPEN figure above.
- **G2-31** (was B25) Overlay build-module interaction round-trips: D1 tooltip hover (LEDGER 780
  flagged rune icons render with NO hover tooltip - fix pending), D2 right-click radial + zone
  flip/wedge clicks landing mid-game, D3 override survives a re-plan + Defer-Once re-entry + reset
  (plus the cross-tick LIVE-route Defer-Once per-match store gap - code work), settings-slider drag
  mid-game, B2/B3/C5 module captures. SOURCE: docs/OVERLAY_BUILD_MASTER_PLAN.md:806-816.
  **AGE CHECK + PARTIAL READY (lane 9 PREP s144 c69, RM-1514, source read at `1748d5494`, 2026-11-05;
  NOT a tick, no game involved).** The SOURCE cite is stale: that file is now 351 lines; D1-D3 sit in
  its Section J table (`docs/OVERLAY_BUILD_MASTER_PLAN.md` "D1 item tooltip" / "D2 right-click
  radial" / "D3 override state + reset", all DONE). Per sub-item:
  (D1) STALE BY AGE, the "fix pending" half: LEDGER 781 (the next item after 780, same day) shipped the
  rune hover titles, reachable as `8e90bfd5a` (`web/js/panels/build_insights.js` `_runeTitle`, used
  in the rune tab row; user-builds `web/js/main.js` near :2836). Those are DASHBOARD surfaces, and the
  LEDGER 780 sighting was the dashboard user-builds section, so it was never an overlay build-module
  item. The overlay D1 is the ITEM tooltip (LEDGER 675): READY below.
  (D2, D3) OPERATOR CALL FIRST, not struck: RM-05's live-recon disposition (2026-07-17,
  `docs/ROADMAP_HISTORY.md` RM-05 entry, restated in G2-30 above) reads "item right-click 5-choice
  radial dead", and the removal never landed: `web/js/panels/active_match.js` still passes
  `onOverride` on the LIVE row and `installItemRadial` is still called for it (both in
  active_match.js; `web/js/lib/overlay_item_radial.js` `_WEDGES` = EARLY / LATE / DEFER / KEEP / MUTE).
  The radial is the only writer of the override store (`web/js/lib/item_overrides.js` header), so D3
  stands or falls with it. Live-verifying D2 / D3 would grade a surface the operator ruled dead. The
  operator picks: remove the radial (then D2 + D3 strike as a human edit) or keep it (then the checks
  below stand).
  **CORRECTION (lane 9 PREP s144 c130, S144-G-117, 2026-11-09): the premise above is refuted.** The
  primary source, the 2026-07-05 LIVE-RECON PUNCH-LIST in `docs/ROADMAP_HISTORY.md`, files the radial
  under BUGS ("the item right-click 5-choice radial ... does not work"); RM-05's "dead" restates that
  bug, it is not a remove ruling; no operator ruling to remove the radial was found, and LEDGER 870
  (2026-07-12) shows the radial kept and fixed after an operator live QA (center-wedge overlap).
  D2 / D3 are owed a live check, not an operator call; run CHECK D2/D3 below, after the radial zoom
  fix named in G2-30 sub-item (5).
  (D3 Defer-Once re-entry) CANNOT PASS TODAY, by construction (Class 1, the answer is on disk): the
  client `deferItem` only sets `deferred` and `applyItemOverrides` sinks it with a fixed bias, with no
  owned-count baseline (`item_overrides.js`); the server route builds a fresh `ReplanLoop()` per
  request and its own comment says cross-tick Defer-Once re-entry is OWED ("this per-request loop only
  sinks a deferred item that tick", `dashboard/routes_build_plan.py`, WP-D3 block). Only
  `core/build_planner/replan.py` `ItemOverrideStore.reconcile` re-enters, and no live route keeps one
  across ticks. That is code work (filed as RM-1515 in the s144 c69 report), so the re-entry check
  waits on it; override-survives-a-re-plan and the reset control are still checkable.
  READY, the live-checkable rest (one overlay-up pass, operator present; a lane never clicks or
  captures). Precondition: a live SR or ARAM game (P1 below LIVE), rc-shell overlay up, `w-build`
  visible with a non-empty LIVE row. P1 `curl -sk https://127.0.0.1:8888/api/state` -> `mode_key`,
  `liveclient.gameData.gameTime`, fetch time. CHECK D1: hover one LIVE-row item icon and hold;
  PASS iff `#rc-item-tip` paints the item's name within about 0.5 s (`overlay_tooltip.js`
  `SHOW_DELAY` 350 ms) and hides after the cursor leaves; FAIL = no tip, a tip for a different item,
  or a tip clipped by the widget edge. CHECK D2/D3 (only if the operator keeps the radial): right-click
  an icon; PASS iff `#rc-item-radial` opens over the icon with the five labels, a LATE click moves
  that icon one slot later in the row on the next repaint and it holds through at least two 4 s re-rank ticks
  (an override surviving a re-plan), MUTE removes it, and the reset control in the DS controls
  (`overlay_ds_controls.js`, `clearItemOverrides`) restores the canonical order; FAIL = no radial, the
  click also dismisses the overlay, or the order snaps back on the next tick. EVIDENCE CONTRACT: the P1
  body with fetch time, mode, game_time, and for each check the item name, the slot before and after,
  and the sighting time. SUBSTITUTION: `tests/test_overlay_d2_item_radial.py` and
  `tests/test_item_overrides_persist.py` prove the store and the reorder on fixtures; only an
  over-the-HUD sighting answers whether the click LANDED in the click-through overlay and the order
  SURVIVED a live re-rank. Settings-slider drag and the B2/B3/C5 captures stay as filed.
- **G2-32** `[NEW ROW 2026-07-18]` RM-05 round-2 drag/move system live-verify (LEDGER 914 S2,
  `14a5ccc5`; `web/js/lib/overlay_layout.js` - `_effectiveXY` drag origin + window-level pointer
  capture + handle-only border hit-test, `_clampXY` semantics preserved). Verify EACH panel, including
  the ACTIVE empty-backing "press now inert" behavior call.
  **AGE CHECK + READY (lane 9 PREP s144 c70, RM-1516, source read at `b27fc4c34`, 2026-11-05; NOT a
  tick, no game up: :8888 and :2999 both refused at 04:30 local).** The row's `14a5ccc5` is the
  pre-rewrite twin of merge `54e4a93c0` (same subject, not reachable from HEAD), whose fix commit is
  `2d23c012e` (2026-07-17). NOT STALE: all three fixes stand at HEAD
  in `web/js/lib/overlay_layout.js` - (a) `_installDrag` `begin` anchors at `_effectiveXY` (clamp plus
  the tall-widget bottom anchor); (b) `begin` binds window-level `pointermove` / `pointerup` /
  `pointercancel` and marks the widget `data-rc-zone` for the drag, `end` unbinds and restores; (c)
  the ACTIVE body `pointerdown` returns on `t === el` (edge press = handle-only) and on a press whose
  nearest `.ovx-widget` is another widget. Later edits to the file do not reopen it: `fd2c31ff3`
  (RM-126) latched the binds per element without changing the drag law; `577118dbc`, `16b9f1de9` and
  the RM-1272 commits touch the menu, TFT widgets and hotkey hints. The G6-02 close (2026-07-20) saw
  ACTIVE body-drag ENABLE; it did not drag panels, so nothing here is evidenced yet.
  PER-PANEL SCOPE, measured: in a feed mode the in-game phase paints every game-family widget
  (`web/js/lib/overlay_phase.js` `PHASE_WIDGETS` has no in-game list), but B4 hides `#rn-lead`,
  `#rn-callouts` and `#rn-choices` in a live game (see the struck G2-28), and neither out-of-game
  list names `w-lead` or `w-callouts`. So `w-lead` and `w-callouts` cannot be dragged in any live
  phase (scope note, not a strike; moving them off this row is a human edit), and `w-choices` only
  in champ-select / loading. The live set is: `w-call`, `w-build` (tall), `w-ovds`, `w-stats`,
  `w-nextbuy`, `w-objgauges` (SR only), `w-arambalance` (ARAM only), `w-launcher` (its own
  tap-vs-drag path, `_installLauncher`, 4 px threshold), plus `w-choices` in champ-select.
  ONE-COMMAND PERSIST READ (NEW `tools/gated_g232_layout_diff.py`, read-only; tests
  `tests/test_gated_g232_layout_diff.py`). A drop persists after a 400 ms debounce (`_persist`) to
  `localStorage` and through `rc-shell:overlay-layout:set` (`rc-shell/src/main.js`) to
  `overlay.widgetLayout` in `<userData>/rc-shell-state.json`, `<userData>` = `<appData>/<productName>`.
  Before the pass: `python tools/gated_g232_layout_diff.py snap > <scratch>/g232_before.json`; after:
  `python tools/gated_g232_layout_diff.py diff <scratch>/g232_before.json` (add `--width W --height H`
  in design px, i.e. the overlay window size over its `ovscale`, to check the upper clamp bound).
  Verdicts: PERSISTED (exit 0), CLAMP_BREACH (exit 3, any stored x or y below 0, or a MOVED panel
  past W/H minus 48), NO_EVIDENCE (exit 4). Idle smoke this cycle: NO_EVIDENCE, 11 league-scope widgets UNMOVED,
  stale saved ids `w-enemyspells` / `w-spike` reported and ignored.
  CHECKS (precondition: P1 `curl -sk https://127.0.0.1:8888/api/state` shows a live SR or ARAM game,
  rc-shell overlay up; record `mode_key`, `liveclient.gameData.gameTime`, fetch time; operator
  present - a lane never drags). Per panel in the live set, after the snap:
  (A, symptom a) PASSIVE, grab the small handle; PASS iff the panel does not jump on the first
  move and tracks the cursor 1:1 (also once at a panel scale other than 1, and for `w-build` once
  after it has been dropped in the lower half, i.e. bottom-anchored). (B, symptom b) mid-drag, sweep
  the cursor well off the handle and across League; PASS iff the drag continues and the overlay
  does not go click-through until the release. (C, symptom c) ACTIVE (Ctrl+Shift+A), press the
  panel's empty border / backing and move; PASS iff NOTHING moves (the "press now inert" call), and
  a content press drags only that panel, never an overlapping one. THE BEHAVIOUR CALL is the
  operator's: an inert border press is the shipped design; if it reads as broken, file it, do not
  tick. (D) the launcher: a tap toggles the menu, a drag past 4 px moves it, and a press on a menu
  row gap does not move the launcher. Then run the diff: PASS for the persist half iff every
  dragged panel reads MOVED, none CLAMP_BREACH, and the undragged ones read UNMOVED.
  EVIDENCE CONTRACT: the P1 body with fetch time, mode, game_time; per panel the A-D sighting with
  time; the diff output with both `state_mtime` values. SUBSTITUTION: `web/js/lib/overlay_layout.drag.test.mjs`
  and `rc-shell/test/overlay_layout_drag.test.js` prove the law on a DOM stub, and a PERSISTED diff
  only proves a drop reached disk through the live IPC; neither shows the panel FOLLOWED the cursor,
  that the window stayed interactive mid-drag, or that a border press stayed inert over a live HUD.
  Those are the eyeball halves, and the row does not close without them.
- **G2-33** `[NEW ROW 2026-07-18]` ~~PR enemy-spell chip cooldown timer live-verify (LEDGER 914 S3,
  `b827f782`; `web/js/panels/enemy_spells.js` - upgraded-Smite displayNames + cd=0 sticky "USED" chip).~~
  **MIS-FILED, CLASS 1: the code under test was deleted (lane 9 PREP s144 c65, RM-1511, source read at
  `cf2b410bb`, 2026-11-05; NOT a tick, no game involved).** Both files the S3 fix changed (`941653494`
  on HEAD; the row's `b827f782` is its pre-rewrite twin, not reachable from HEAD),
  `web/js/panels/enemy_spells.js` and `web/js/panels/enemy_spells_timer.test.mjs`, were removed by the
  Riot-compliance commit `538c61e4b` (2026-08-11) and no commit since re-adds them (`git log
  538c61e4b..HEAD -- web/js/panels/enemy_spells.js` is empty). The chip timer is the banned surface
  itself: `docs/OVERLAY_COMPLIANCE_PLAN.md` row B1 names `enemy_spells_timer.test.mjs` under "Tracking of
  enemy summoner spells cooldowns" and rules "DELETE the enemy-side tracker entirely. No manual-click
  carve-out is documented; do not assume one.", and the producer comment in `dashboard/_liveclient.py`
  adds "a manual tap-to-count-down tracker is still an enemy cooldown timer". Same inverted guards as
  G2-26. Verifying this row live would mean reinstating a banned
  surface, so it can never drain; the matching G2-30 sub-item is dead for the same reason. Moving the
  row to "Not actually live-gated" is a human doc edit.
- **G2-34** `[NEW ROW 2026-07-18 - LIVE-GATED DECISION]` ~~Objective gauges 1-line collapse: the
  operator picks horizontal vs vertical after seeing them in-game. SOURCE: RM-05.~~
  **CLOSED 2026-07-20, RULED HORIZONTAL (LEDGER 987, drain commit `51dfc0cef`; the ruling and the
  in-game render evidence are in the dated drain block at the head of this doc). Strike recorded by
  lane 9 PREP s144 c71, source read at `d5e56f44d`, 2026-11-05; NOT a tick, no game involved.** The
  ruled shape stands at HEAD: `web/css/panels/objective_gauges.css` `.obj-gauges .og-grid` is
  `grid-template-columns: repeat(3, 1fr)` ("One horizontal row of 3 dials"), and the dial set in
  `web/js/panels/objective_gauges.js` is DRAKE / BARON / ELDER. Nothing is owed on this row; an
  "I don't see them" report is the saved-layout class and belongs to G2-32.
- **G2-35** `[NEW ROW 2026-07-18 - LIVE-GATED DECISION]` ~~`am-statspanel` intent: CLARIFY with the
  operator before acting (RM-05 explicitly parks this pending an operator call over a live render).~~
  **DECISION CLOSED 2026-07-20, RULED "pace-projected baseline" (LEDGER 987, drain commit
  `51dfc0cef`): keep the tier AVG but scale it to the current game clock, because the panel compared
  live CS 30 against a full-game average of 260. THE RULING NEVER SHIPPED (lane 9 PREP s144 c71,
  source read at `d5e56f44d`, 2026-11-05; NOT a tick, no game involved).** At HEAD
  `web/js/panels/stats_panel.js` `_paintBench` paints the route's raw `stats[k].avg` with no clock
  term; `_bracketFor` only picks the cache key ("early" under 840s, else "mid"), and
  `core/rank_tier_bench.py` documents both brackets as "identical estimate values in the seed
  (bracket-agnostic)". Measured in `data/rank_tiers/rank_tier_averages.seed.json`: gold SR cs avg
  205 in BOTH brackets (ARAM 55 in both); `core/rank_tier_source.py` has no real endpoint wired, so
  the seed is the only source. So at 5:00 the panel still sets a live CS near 35 against 205 - the
  exact defect the operator ruled on. The ruling is carried in dated QA files
  (`docs/qa/UI_UX_QUEUE_2026-07-21.md`, `docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md`). The second is
  read by the headless UI/UX lane (`tools/headless-uiux.md` section 2 names it the master ruling
  ledger) and by ROADMAP RM-122, but no ROADMAP or BACKLOG row carries the slice itself (no
  am-statspanel / stats_panel / pace-projected hit in either; their two case-insensitive `cs_per_min` hits are
  unrelated rows, the ROADMAP F2 note on `core/lead_projection.py` and BACKLOG RM-376). That QA
  file's "CONTRADICTION TO RECONCILE" note still
  calls G2-34 / G2-35 open here; this strike supersedes it. The residual is a CODE SLICE, not a
  game: filed provisionally as RM-1660 for the merger to mint (UI lane). The seed carries NO
  game-length field, so the slice must not invent one: the seed's own origin,
  `web/js/panels/last_match.js` `_RANK_TIER_AVERAGES`, carries a per-tier `cs_per_min` (gold SR 6.8,
  gold ARAM 4.6), and pace cs = `cs_per_min` x `game_time_s` / 60 capped at the full-game `cs`
  avg; kda / kp stay unscaled since they are ratios; keep the `estimate` badge; the 5-phase UI
  audit applies. READY, for after that slice lands (SR practice or real, any role, a tier set in
  DS Settings):
  - PROBE: `curl -sk https://127.0.0.1:8888/api/state` -> `liveclient.game_time_s` and the live
    `cs`; then read the rendered `.sp-bench-cell[data-c="cs"]` text in `#am-statspanel` (text-first,
    computed DOM, not a pixel read).
  - PREDICATE, stated before any game: take two samples at least 5 game-minutes apart, BOTH before
    20:00 game time (so a correct cap at the full-game avg cannot read as a fail). The rendered cs
    Avg cell is strictly larger at the later sample, and at the first sample it reads below the
    full-game value (205 for gold SR). The kda / kp Avg cells are equal at both samples. FAIL if
    the cs Avg is the same at both samples. SR only: every SR tier reaches its cap near 30:00,
    but every ARAM tier reaches it near 12:00 (gold 55 / 4.6), so an ARAM check needs both
    samples before 12:00.
  - EVIDENCE: both rendered values, both `game_time_s` values, the tier, mode and queue, the ISO
    time of each sample.
  - SUBSTITUTION CHECK: a unit test of the scaling helper answers whether it COMPUTES, not whether
    the overlay RENDERS the scaled value; only the rendered cell text read in a live game counts.
    A bench cell of "-" (no tier set, Arena, fetch miss) is NO_EVIDENCE, never a pass.

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
  **READY (lane 9 PREP s144 cycle 39, source read at `d043c33b1`; NOT a tick).** The row is
  UNDERSTATED and its premise is imprecise. There are FIVE `KillerName` readers, not two, and they
  read DIFFERENT event types, so "the same field, at most one can be right" holds only if
  ChampionKill and the objective events carry the same form:
  `dashboard/_liveclient.py` (objective events, raw `championName` only; feeds
  `core/event_callouts.py` `epic_buff_callouts` :788, `dragon_soul_callout` :1006 and
  `_dynamic_epic_callouts` :291 through `objective_events.killer_team`, dragon / baron takes only;
  `voidgrub_callout` :861 and `core/macro_response.py` read the same `killer_team`);
  `core/decision_detector.py` `_team_of` (ChampionKill only, `detect_postfight_objective`; compares
  `summonerName` OR `riotIdGameName`, so a present `summonerName` shadows the bare game name);
  `core/live_event_deriver.py` `_killer_team` (objective events; `championName` or raw
  `summonerName` / `riotId` / `riotIdGameName`); `core/death_recap.py` `resolve_player`
  (ChampionKill; folded player names, then a unique champion); `game_reader/snapshot_normalizer.py`
  `_dragon_tally` (DragonKill, not Elder; folded player AND champion names, mirror keys dropped).
  The RM-601 fixture is split the same way (ChampionKill killers are player names, objective
  killers champion names), so a split wire would make the dashboard and the detector BOTH right.
  The question is the RM-673 half of LX-02 (section `EXTERNAL-LIFT INTAKE live halves`), widened to ChampionKill:
  ONE capture set answers both rows; G2-46 adds no separate capture step, only a wider window
  (a champion kill, and a DRAKE or BARON take for `silent_features` - grubs alone leave it open).
  PROBE: take the LX-02 relay captures exactly as that row says (from the main checkout, at least
  two `curl -sf` captures of `http://127.0.0.1:8889/latest-liveclient` at least 60 s apart, the
  last after a champion kill AND a grub or drake take, into gitignored
  `ops/runtime/liveclient_captures/`), then run
  `python tools/gated_g246_killer_readers.py ops/runtime/liveclient_captures/ --json` (read-only;
  it never prints a name). Three readers are the REAL production functions called on the capture
  (`_team_of`, `derive_events`, `resolve_player`); `dashboard/_liveclient.py` and
  `snapshot_normalizer.py` cannot be imported without a vision token, so those two are MIRRORS,
  pinned against their source by `tests/test_gated_g246_killer_readers.py`.
  FIELD PATHS: `events.Events[].EventName` / `.KillerName` / `.EventID` / `.DragonType`;
  `allPlayers[].championName` / `.summonerName` / `.riotIdGameName` / `.riotId` / `.team`;
  `activePlayer.summonerName` / `.riotIdGameName` / `.riotId`; the relay wrapper `ts`.
  PREDICATE (stated before any game): `g246.verdict` NO_RESULT unless `valid` (`synthetic=0`,
  `duplicates=0`, `payloads>=2`, `relay_ts_span_s>=30`, `distinct_game_times>=2` - one relay body
  re-stamped with a new `ts` is one read; a raw unwrapped file has no `ts` and is NO_RESULT); PARTIAL = ChampionKill or objective killers still have no `champion` / `player` form
  (re-capture after the missing kind); MIXED = one class carries both forms (record
  `forms_by_event`, file it, close nothing); SETTLED = each class is CHAMPION or PLAYER, recorded
  as `championkill_form` + `objective_form`, with `row_premise` SAME_FORM or FORM_BY_EVENT
  (FORM_BY_EVENT refutes the row's "at most one can be right"). Per reader, over killers in
  roster-member form only (`no_self`, `ambiguous`, `both`, turret / minion / monster killers are
  counted, never graded): RESOLVES / BLIND / PARTIAL / NO_DATA. `silent_features` is graded on
  the dashboard reader over DragonKill / BaronKill roster-member killers ONLY
  (`dashboard_epic_counts`): CONFIRMED (BLIND there: the three callouts above are unconditionally
  silent live; file the reader fix) / REFUTED (it RESOLVES) / UNDETERMINED (incl. a grub-only
  capture, which cannot decide them; a BLIND dashboard on HordeKill is a `voidgrub_callout`
  filing instead). Every BLIND reader in `blind_readers` is a
  filing on that reader, decided by THIS capture; a turret or minion kill shows up as
  `forms_by_class.*.nonplayer` (the row's "confirmed-live half").
  EVIDENCE CONTRACT: the tool's JSON (`g246`, `readers`, `dashboard_epic_counts`,
  `forms_by_class`, `forms_by_event`, `self_identified`, `payloads`, `relay_ts_span_s`,
  `distinct_game_times`, `game_modes`, `game_time_max`), each capture file's mtime, the queue, and the main checkout HEAD plus `ops/runtime/health.json` `pid` / `started_at`.
  SUBSTITUTION CHECK: every verdict above comes out of hand-built payloads in the test file, and
  the RM-601 fixture reads `synthetic=1` / NO_RESULT, so a verdict proves nothing unless the files
  came off the live relay during the played game (the same three look-alikes as LX-02: a fixture
  copy, a duplicate file, the stale relay cache with one `ts`; a fixture copy with its `_comment`
  and `Synthetic` names edited away is NOT caught by the tool, only by the mtime and provenance). The tool answers the WIRE FORM and
  how each reader RESOLVES it; whether a callout then RENDERS on screen is a separate on-screen
  check this row does not close. The row's "verified headless" dragon-soul line stays a compute
  fact, not evidence.
- **G2-39** (RM-124, built 2026-07-29 `efbb34d0`, gated OFF) Validate the deterministic wave/cannon
  clock cadence before the flip. The code ships (`core.event_callouts.wave_callout` + `minion_events`
  transport) but `enable_wave` defaults False; the dashboard flips it only on env `RC_WAVE_CALLOUT=1`.
  The interval + cannon-cadence constants are PROVISIONAL (sources disagree on the 14:00 vs 15:00
  breakpoint; 2025 moved first cannon 2:05 -> 2:35). CHECK: in one practice/real SR game, confirm (a)
  `liveclient.minion_events` carries a single `{at_s}` at first-wave spawn, and (b) with
  `RC_WAVE_CALLOUT=1` the "Cannon wave incoming" chip ETA counts down to the ACTUAL observed cannon
  arrivals (first cannon ~wave 3, then the every-2nd/every-1 tightening past 14/25 min). Correct the
  constants against reality if they miss, THEN flip the env on by default. SOURCE: ROADMAP RM-124.
  **READY (lane 9 PREP s144 cycle 40, source read at `4672d4945`; NOT a tick).** Three measured
  facts reshape the check. (1) The chip half of (b) CANNOT render in a live game, flag on or off:
  B4 (RM-189) blanks the served `callouts` while a game is live (`dashboard/_state_builder.py:453`
  `LIVE_SUPPRESSED_ENVELOPE_FIELDS`, applied at `:1053` `suppress_live_envelope`) and the client
  gate `web/js/lib/live_directive_gate.js` hides the mount; the row's line "Cannon wave incoming -
  match the push" is the kind of imperative B4 exists to stop. The only live record of the wave row
  is the pre-suppression shadow log `data/det_coach_shadow.jsonl` (`core/det_coach_shadow.py:99`,
  field `callouts`; deduped on a 5 s game-time bucket plus level and item count, so a bucket can
  hold more than one record; `mode` is the RAW dashboard mode_key, and `client` / `game` are SR
  for the callout generator, so the grader keeps all three), and only while the RC process
  runs with `RC_WAVE_CALLOUT=1` (`dashboard/_deterministic_coaching.py:867`, read from the process
  env, so turning it on is an RC restart: a main-session act, never a lane's). (2) Live Client
  sends ONE MinionsSpawning event per game (`dashboard/_liveclient.py:517-527` keeps every one;
  `core/event_callouts.py:595` `_wave_anchor_s` takes the earliest); no later wave or cannon is in
  any feed, so the truth for (b) is an OBSERVATION: the game clock when a cannon wave LEAVES the
  nexus. The clock predicts the SPAWN (`wave_callout` :616 walks spawn times), not the lane
  arrival, so a lane-arrival read lags by the walk time from the nexus and is the wrong comparand. (3) The cadence
  question needs no flag and no restart: `schedule --anchor <the (a) value>` calls the production
  `wave_callout` itself, so the observed spawns can be graded against it from the anchor alone;
  the flag only adds proof that the live wiring computed the same row.
  PROBE (read-only; `tools/gated_g239_wave_clock.py`, tests `tests/test_gated_g239_wave_clock.py`):
  (a) after game clock 1:10, save `curl -sk https://127.0.0.1:8888/api/state` to a gitignored file
  and run `python tools/gated_g239_wave_clock.py state <file> --json`; (b) note the game clock at
  which at least three cannon waves leave the nexus, one per bracket if the game is long enough
  (`every3` before 14:00, `every2` 14:00-25:00, `every1` after), then run
  `python tools/gated_g239_wave_clock.py schedule --anchor <anchor_s> --until 1800` and, if RC ran
  with the flag, `python tools/gated_g239_wave_clock.py shadow data/det_coach_shadow.jsonl --since
  <ISO game start WITH its UTC offset> --observed <m:ss,m:ss,...> --json` (a naive or date-only
  `--since` is refused, exit 2: read as UTC it would let an earlier game's rows in). With anchor 65.0 the predicted cannon
  spawns are 2:05, 3:35, 5:05 ... 12:35, then 14:30, 15:20 ... 24:30, then 25:20, 25:45 ...; the
  14:00 step keeps the wave index parity from the anchor, so 14:05 is NOT a cannon under the
  current constants - a provisional choice this game settles too.
  CONTESTED (s144 cycle 47): fact (2) rests on a code comment that the same function contradicts
  for the R221 extract ("emits it once per wave"); see the G2-45 READY block, whose `stream`
  verdict decides it - grade (a) only after it.
  FIELD PATHS: `/api/state` -> `liveclient.minion_events[].at_s`, `liveclient.game_time_s`,
  `callouts[].kind`; shadow record `ts` / `mode` / `game_time_s` / `callouts[].kind == "wave"` /
  `.eta_s` (implied spawn = `game_time_s + eta_s`).
  PREDICATE (stated before any game): (a) PASS = `ANCHOR_OK` (exactly one event, `at_s` in
  55-95 s); `ANCHOR_MULTI` / `ANCHOR_BAD` / `ANCHOR_MISSING` after 1:10 = FAIL, recorded with the
  value. (b) PASS = every observed cannon spawn within 3 s of a predicted one (`MATCH`), per
  bracket observed; a bracket the game never reached stays OPEN, not passed. `MISS` = correct the
  constants for that bracket (a Tier-1 code change with the observed times as its test data), never
  a flip. `served_wave_rows` must read 0 in game (B4); a non-zero count is its own B4 defect.
  EVIDENCE: the anchor value + saved-state file mtime + game clock; each observed spawn as `m:ss`
  with how it was read (operator glance or a `:8889/latest-frame` whose `meta.ts` was checked
  against `liveclient.game_time_s`); mode + queue (Practice Tool or GATE 4); main HEAD.
  SUBSTITUTION CHECK: the shadow `implied` set and the `schedule` output are both RC's OWN
  arithmetic; agreement between them proves the row was COMPUTED live, never that the cadence is
  right. Only observed spawns taken from the game itself can make (b) pass. A Practice Tool game
  with minions toggled, or with any time skip / fast-forward, moves the clock off the anchor: use
  default Practice Tool settings or a GATE 4 game, and say which. The "THEN flip the env on by
  default" step is MOOT on screen while B4 stands (the row would still be blanked live); it would
  change only the shadow record and the 3-row cap (`max_n=3`, so the wave row can push a sooner
  row out of the record). Filed for a human as a hygiene proposal (lane report RM-1167); NOT
  struck here. This id is also used twice in this gate (the QA6 / QA13 row below; RM-1166).
- **G2-36** (was B1) Build-chooser pushes correct runes/items/spells MID-GAME to LCU (3-variant +
  Experimental row). RENDER + generic-build path confirmed 2026-07-04 (Zilean support); the mid-game
  LCU PUSH LOG LINE is still owed - no push line captured in any drain. SOURCE: LEDGER 779.
  **READY (lane 9 PREP s144 cycle 41, source read at `946280252`; NOT a tick).** Four measured facts
  shape the check. (1) The mid-game push is ITEMS ONLY by design, so "runes/items/spells MID-GAME"
  overstates the row: the in-game switcher (`web/js/panels/item_build.js` `_ibMaybeRenderBuilds` ->
  row click `_ibOnRowClick` -> `_ibPushItems`) POSTs `/api/loadout/apply` with `push_runes: false,
  push_summoners: false, push_items: true`, and the panel's own comment says runes + summoners are
  locked at game start. The rune / spell pushes are champ-select acts (GATE 1), not this row; NOT
  struck, narrowed here with the reason. (2) The route (`dashboard/routes_loadout.py`
  `_serve_loadout_apply_post`) queues the resolved `apply_item_set` command on `:8889/lcu-cmd`;
  `tools/lcu_agent.py` `drain_once` runs it and logs `  [cmd] apply_item_set -> {result}` (or
  `[cmd-exc]`) to `logs/lcu_agent.log` (format `%(asctime)s %(levelname)s %(message)s`, local wall
  clock); a good result is `{'ok': True, 'set_uid': 'RC-...', 'title': ...}`. The dashboard logs
  only a FAILED enqueue, so the agent log is the one push record. (3) Measured 2026-10-31 over
  `logs/lcu_agent.log` + `.log.1`: ZERO `apply_item_set ->` lines ever, and every
  `apply_item_sets_batch` line (14, the champ-select batch, a DIFFERENT verb) reads
  `no_lcu` - the owed line has never been written, so the drain is the first. (4) Neither B4 list
  (`dashboard/_state_builder.py` `LIVE_SUPPRESSED_FIELDS`, `LIVE_SUPPRESSED_ENVELOPE_FIELDS`) names
  the item build, so the switcher is not blanked live; it shows only with at least two build rows
  for the champion (`_ibFetchAndRender`, `rows.length < 2` hides it) and mode `sr` / `aram` /
  `brawl` (`_ibMaybeRenderBuilds`).
  PROBE (read-only; `tools/gated_g236_loadout_push.py`, tests `tests/test_gated_g236_loadout_push.py`):
  in game, save `curl -sk https://127.0.0.1:8888/api/state` to gitignored `s1.json`; click a build
  row in ITEM BUILD (`_ibOnRowClick` clears the applied key, so any row click pushes, but a click
  while the panel reads `pushing...` is dropped); wait 5 s (the agent drains every 0.5 s,
  `CMD_INTERVAL`); save the state again to
  `s2.json`; then run `python tools/gated_g236_loadout_push.py log logs/lcu_agent.log --before-state
  s1.json --after-state s2.json --champion "<champion display name>" --json` (if the log rolled over in the
  window, run it on `logs/lcu_agent.log.1` too).
  FIELD PATHS: `/api/state` -> `lcu.phase`, `liveclient.game_time_s`, `mode_key`; agent log line
  `<ts> INFO   [cmd] apply_item_set -> {...}` -> `ok`, `set_uid`, `title`.
  PREDICATE (stated before any game): PASS = `PUSH_OK`: both state files grade IN_GAME (`lcu.phase`
  InProgress or a non-empty `liveclient`; never `mode_key` alone) and at least one `apply_item_set`
  line inside [mtime(s1), mtime(s2)] carries `ok: True` with a `set_uid` starting `RC-<norm>-`, where
  `<norm>` is the champion name lowercased with every non-alphanumeric dropped
  (`coaches/loadout_resolver.py` `_norm`, which both resolvers use: Kai'Sa -> `RC-kaisa-`).
  `PUSH_FAILED` (a line, no good result: record the `err`, e.g. `no_lcu`) and `NO_PUSH` (no line: the
  agent did not run or the click was deduped) are FAIL, recorded with the value; `NOT_MID_GAME` or
  `BAD_WINDOW` = re-take, not a verdict on the row.
  EVIDENCE: the push line's local time, `set_uid` and `title`; the two state file mtimes with
  `liveclient.game_time_s` from each; mode + queue + champion; the status text the panel showed;
  main HEAD.
  SUBSTITUTION CHECK: the panel's green `check <label>` is NOT evidence: the route answers `ok`
  when the command was QUEUED on `:8889`, before the agent ran it, so it proves the click COMPUTED
  and SENT a command, not that the LCU took it. The agent line is the LCU's own answer to the PUT.
  It still does not prove the in-game shop SHOWS the set mid-match (the agent's comment says it
  does; nothing measured it): record a shop glance as an observation beside the evidence, never as
  the pass.
- **G2-37** (was B27) LBAND1 live wire-in eyeball: `core/live_benchmark_band` into the
  deterministic-coaching surface + overlay (live cs+level vs own per-champion percentile). The
  generator half is SHADOW-only today (`data/live_benchmark_band_shadow.jsonl`); this is the surface +
  flip. SOURCE: BACKLOG.md:162.
  **READY (lane 9 PREP s144 cycle 42, source read at `033e96e6b`; NOT a tick).** Four measured facts
  shape the check. (1) The EYEBALL half is NOT drainable as filed: no surface exists. The only
  served-code files that name the bander are the shadow path (`core/live_benchmark_band_shadow.py`,
  `dashboard/_deterministic_coaching.py` `shadow_log_live_benchmark_band`, called from the
  deterministic block of `dashboard/_state_builder.py`); no `web/` or `rc-shell/` file, and not
  `overlay.py`, reads a band (`live-bench` / `live_benchmark_band` appear in none; the test scans all
  three and fails on purpose when a surface ships). Building the surface and the flip is headless
  BUILD work; filed as a move proposal (RM-1169), NOT moved or struck here - a human moves it. Any
  surface built later also meets B4 (RM-189): riding `coach.action` / `immediate`
  (`LIVE_SUPPRESSED_FIELDS`) or the det envelope `callouts` (`LIVE_SUPPRESSED_ENVELOPE_FIELDS`) blanks
  it live. The band line is descriptive, not imperative (`core/live_benchmark_band.py` `_line`: "CS at
  10: below your <champion> median."), so whether B4 should admit it is an adjudication the build
  owes before an eyeball can exist. (2) The SOURCE cite is stale: `BACKLOG.md` carries no LBAND1 / B27
  text at this HEAD; the history is LEDGER 443 / 445 / 446 / 447. (3) The GRADEABLE live half is the
  shadow writer. The live log holds 3495 rows, the last on 2026-08-02 (UTC), and every SR-family
  shadow (`det_coach`, `objective_playbook`, `macro_response`) also stops on 2026-08-02, so no SR game
  has run since: a gap in play, not a writer stall. The writer was rewritten after that last row
  (`0ca196762`, 2026-10-30, s144 true-audit: one lock over the dedup check, the append and the sig
  update; strict field vocabularies), so the rewritten writer has never been seen live. Positive
  control on the real log: the grader reports `FAIL duplicates=1020` over all 3495 rows, exactly the
  true-audit's pre-fix count, so its duplicate detector sees the real defect shape. It also reports
  78 rows whose `ts` steps back, every one under 3 ms: the old writer stamped `ts` before taking any
  lock, and the rewrite stamps it inside the lock, so on the new writer a backward step reopens F1 as
  surely as a duplicate does. The same run raises no other reason, so the value and vocabulary checks
  raise no false failure on 3495 real writer rows. (4) A row fires
  only on an SR-family `mode_key` (`sr` / `client` / `game`) with `liveclient.champion` present, a
  clock within 45 s of 10:00 (`cs_at_10`, `level_at_10`) or 15:00 (`cs_at_15`), and a champion with
  at least 5 personal games (`core/live_benchmark_band.py` `_MIN_GAMES`); the log already covers 14
  champions (Caitlyn, Kai'Sa, Jhin among them). ARAM / Arena / TFT never fire it.
  PRECONDITION: RC runs code carrying `0ca196762` (`git merge-base --is-ancestor 0ca196762 HEAD` in the
  main checkout, and `ops/runtime/health.json` `started_at` later than its landing; measured
  2026-10-31: `started_at` 2026-10-31T06:32:32Z). Otherwise a row comes from the OLD writer and grades
  nothing about this row.
  PROBE (read-only; `tools/gated_g237_lband_shadow.py`, tests `tests/test_gated_g237_lband_shadow.py`):
  note the local time with its UTC offset at game load; play one SR game (practice tool counts) past
  15:45 on a champion with history; then run `python tools/gated_g237_lband_shadow.py shadow
  data/live_benchmark_band_shadow.jsonl --since <load time ISO, with offset> --champion "<Live Client
  display name>" --json`.
  FIELD PATHS: shadow row -> `ts`, `mode`, `champion`, `game_time_s`, `cs`, `level`,
  `bands[].checkpoint` / `metric` / `band` / `value` / `source_tag`.
  PREDICATE (stated before any game): PASS = verdict `PASS`: at least one row since load, at least one
  at checkpoint 10, every row strict JSON with SR-family mode, in-window clock, in-vocabulary band and
  metric, `source_tag` `live-bench`, the named champion only, and ZERO consecutive duplicate rows
  (same writer sig), every band `value` equal to the row's own `cs` / `level`, and, from the first
  in-window row's preceding pre-`--since` row onward, no unparseable or ts-less line (a torn append)
  and no `ts` that steps backward. FAIL = any violation, a duplicate first (it
  reopens true-audit F1) UNLESS the pair straddles an RC restart (`health.json` `started_at` between
  the two `ts`: the writer's dedup memory is per process, so that pair is a re-take, not F1; so is a
  backward step that coincides with a system clock change, e.g. a time sync, in the window).
  `NO_RESULT` = no row: if RC was up and the game passed 10:45 on a champion with 5+ games, that is a
  FAIL of the writer, not a re-take; otherwise re-take. A checkpoint-15-only FAIL when RC was not up
  at 10:00 is likewise a re-take.
  EVIDENCE: the `--json` line; the game's mode, queue, champion and game time at the 10:00 and 15:00
  windows from `/api/state` -> `liveclient.game_time_s`; `health.json` `pid` + `started_at`; main HEAD.
  SUBSTITUTION CHECK: a PASS proves the band COMPUTED and was LOGGED by the rewritten writer. It does
  NOT prove anything RENDERED - nothing can until the surface is built - so it never ticks the eyeball
  half, and the row stays open on that half. The `--champion` filter and the `--since` time are what
  stop a row from an earlier game being read as this one; grade without either and the result is not
  evidence.
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
  **READY (lane 9 PREP s144 cycle 43, source read at `a84005f35`; NOT a tick).** Five measured facts
  shape the check. (1) The surface is the in-game BUILD panel's "Meta Build" row (`bm-meta`,
  `web/js/panels/active_match.js` `_maybeRefreshBuildOrder` -> `POST /api/build-order`); it is NOT a
  coach field, so B4 (`LIVE_SUPPRESSED_FIELDS`, `dashboard/_state_builder.py`) does not blank it and
  the row is drainable. The top pick is engine call 1 = the first UNOWNED item in that row (boots are
  injected AFTER slot 1, `core/build_order.py` boots step, and dropped from the incumbent). The
  "Ultimate Build" row is fixed at level 18 with no items, so a level-up never exercises it. (2) The
  incumbent is CLIENT state, not server state: `_incumbentIds` echoes the order that client last
  received, and the route only reads `payload.get("incumbent")`. A page reload, an ADR-008 asset hot
  reload or an RC restart that reloads the overlay empties it, so the first plan after one is GREEDY -
  that is what "cross-restart" means here, and a flip on that first plan is not a hysteresis failure.
  (3) `/api/build-order` returns only the CHOSEN delta per slot (`BuildStep.to_dict`), never the
  runner-up, so whether a tick is in band cannot be read off the route or the panel; it needs the
  slot-1 ranked rows. `capture` reads the panel's inputs off `/api/state` (`_renderAmBuildBody`:
  champion = coach payload `champion`, level = `parseInt(level) || 1`; in a live game the payload is
  the coaching-file push or SSE frame, the HTTP poll's `st.coach` only a fallback, and the mode is
  `main.js` `state.mode`, read here as `mode_key`). The panel's level-up is therefore a COACH-level
  change (the header level pill), which can lag the Live Client level in the stats panel. Items:
  `_amOwnedItemIds` uses `liveclient.owned_item_ids` when it is non-empty, else the player's
  `allPlayers[].items`, else the coach payload's `items_display`; `capture` replicates only the first,
  so a glance with an empty `owned_item_ids` (`items_source` `none`) is never graded. It posts that body (no incumbent; the ranked rows do not depend on it) to the
  RUNNING route, takes the enemy target stats from the response's `target_stats` (in-game the route
  resolves them from RC's warm Live Client cache, which a fresh process cannot see: its cache starts
  empty and falls back to the mode/level curve), re-runs the production `plan_build_order` with them
  and a recording `rank_fn`, and sets `rows_match` only when the re-run's greedy order equals the
  route's AND `items_source` is `owned_item_ids`. (4) The rule is `_pick_top_safe`: keep the incumbent while
  `inc_delta > 0` and `top_delta <= inc_delta * (1 + 0.03)`; the margin default now sits on
  `plan_build_order` / `_pick_top_safe` (the row's `:405` cite is stale), and the row's `:249`
  "Jhin-specific note" is the Jhin -> Swiftness BOOTS default, not a hysteresis note. The grader reuses
  `_pick_top_safe` itself and pins the 0.03 default and the row's own arithmetic (58.709 * 1.03 <
  61.695 -> flip allowed). (5) A held pick causes no visible repaint, and the panel paints a new plan
  only after its POST returns (up to 5 engine calls at the route's 2.0 s timeout; an old-level POST
  still in flight blocks the re-fire, so up to two such plans) and the next `onState` repaint (a
  coaching-file push or SSE frame); so a glance soon after the level-up can show the OLD order and read
  as HELD. The grader therefore grades no glance under `MIN_SETTLE_S` = 30 s after the HEADER level
  pill changed (2 x 10 s plus a 10 s repaint allowance: a floor for the panel's own latency, not a
  proven bound). The
  2026-07-20 drain's tightest gap was 9.02 pct, three times the band, so the precondition is rare:
  expect `NO_RESULT` more often than not.
  PROBE (`tools/gated_g238_top_pick_flip.py`, tests `tests/test_gated_g238_top_pick_flip.py`): when
  the overlay's HEADER level pill changes (not the stats panel), note the moment; wait at least 30 s
  (and stay before the next level-up, item purchase or enemy purchase); glance at the overlay's Meta Build row; then at once run `python
  tools/gated_g238_top_pick_flip.py capture --rendered <first unowned item id SEEN> --since-levelup-s
  <seconds since the header level changed> >> <drain evidence dir>/g238_glances.jsonl` (GET `/api/state`,
  one compute-only POST to the running route, then DS `:8860` rank calls; no RC state write, no LCU
  call; drain session only, never PREP). Take one glance before the first graded level-up so the
  incumbent is recorded. Add `"reload": true` by hand to a glance when the page, an asset or RC
  reloaded since the previous one. After the game: `python tools/gated_g238_top_pick_flip.py grade
  <drain evidence dir>/g238_glances.jsonl --json`; `band <saved rank json> --incumbent <id>` explains
  one tick offline.
  FIELD PATHS: glance -> `ts`, `level` (coach level), `items`, `items_source`, `game_time_s`,
  `rendered_top`, `since_levelup_s`, `ranked[].item_id` / `delta` / `shares_dead_unique`,
  `greedy_order`, `route_order`, `rows_match`, `target_source`; grade -> `verdict`,
  `ticks[].in_band` / `outcome` / `gap_pct` / `skip`, `tightest_gap_pct`.
  PREDICATE (stated before any game): a graded TICK = two consecutive glances with a level rise, the
  same owned items, no reload, and on the later glance `rows_match` true and `since_levelup_s` at
  least 30; the earlier glance's rendered top is the incumbent. IN BAND = the incumbent is eligible,
  is not the greedy top, has a positive delta, and the greedy top beats it by no more than 3 pct. PASS
  = at least one in-band tick and every in-band tick rendered the incumbent (HELD). FAIL = any in-band
  tick rendered the challenger (FLIPPED) or an item that is neither (OTHER). `NO_RESULT` = no in-band
  tick: re-take, and record `tightest_gap_pct` beside the 9.02 baseline.
  EVIDENCE: the `grade --json` line, the glance file, the game's mode / queue / champion / game time
  per tick from `/api/state` -> `liveclient`, `health.json` `pid` + `started_at`, main HEAD.
  SUBSTITUTION CHECK: the ranked rows prove only that the band COMPUTED; the `rendered_top` field is
  the only render evidence and must be what the operator SAW on the overlay, never a value copied
  from `greedy_order`, `route_order`, `/api/build-order` or a second client. A headless browser or
  second dashboard tab runs its OWN incumbent chain, so its DOM grades a different chain from the one
  on screen. `rows_match` ties the rows to the route's plan for the panel's inputs, not to the
  panel's own call: a glance across an enemy purchase (target stats move) can still pair the rendered
  pick with rows the panel never saw, so re-take that tick; so can the route's 8 s Live Client cache
  gate switching `target_source` between live stats and the curve, so a tick whose `target_source`
  is not the live-items source is suspect. RESIDUAL (not closable by the tool): the
  panel keeps its old order when its own POST fails (`j.ok` false), so a HELD on a tick where the
  route was failing is stale; a `capture` that refuses ("route gave no plan") voids that tick, and an
  intermittent DS error in the RC log during the window voids it too.
- **G2-39** (was B29) QA6 fullscreen-detect "switch to Borderless" hint + QA13 UIPI elevation-parity
  detect final validation. Low-confidence inferred rows - **build headless first**.
  **READY, BLOCKED ON BUILD (lane 9 PREP s144 cycle 53, source read at `c85a76ae0`; NOT a tick).** No
  game can drain this row today, because neither feature exists. Three facts measured at idle on
  2026-11-01; (2) and (3) change the build.
  (1) NOT BUILT. `docs/RC2_QA_CONSOLIDATED.md` still has QA6 and QA13 OPEN, and a grep of tracked
  source finds no reader of `WindowMode`, no `GWL_STYLE` / `WS_POPUP` read and no `TokenElevation`
  read (`build` below, with positive controls in its test; an empty grep is a claim about those
  patterns only). The filed "final validation" has no subject.
  (2) THE QA13 PREMISE LOOKS STALE. `docs/RC2_QA_CONSOLIDATED.md` says "neither process elevated
  today". Measured: the shell's token is ELEVATED, as is this tool's process, with `EnableLUA` 1,
  `ConsentPromptBehaviorAdmin` 0 and no `FilterAdministratorToken`. The rc-shell overlay was down and
  the game was not running, so NEITHER process QA13 names is measured. QA13's concern is the OVERLAY
  matching the game (`docs/_archive/RC2_TODO_QA.md` item 13), so the tool grades the overlay, not RC's
  Python process. UIPI blocks lower integrity from higher, so an elevated overlay cannot be blocked by
  a user-launched game. PRUNE CANDIDATE for a human once `uipi` below reads `NO_BLOCK_POSSIBLE`; not
  struck here. RESIDUAL the tool does not read: the hotkey listener (a Python child of the service
  host, not told apart by image name) and the integrity level itself (`TokenElevation` is the proxy).
  (3) THE ON-DISK VALUE IS FULLSCREEN, AND THE QA6 SIGNAL IS UNPROVEN. game.cfg `[General]` holds
  `WindowMode=0` today (mtime 2026-10-25, no `Width` / `Height`), and PersistedSettings.json carries
  no `WindowMode`. The operator-corrected encoding is 0 = Fullscreen, 1 = Windowed, 2 = Borderless
  (`docs/history_notes.md`, the RM-147 close). So the file says the next game may start in the mode
  `rc-shell/README.md` says hides the overlay; whether the file is current is unmeasured. CONFIRM THE
  WINDOW MODE DROPDOWN IN THE CLIENT BEFORE THE NEXT LIVE SESSION (memory
  `feedback_gamepc_league_fullscreen_lockup`: League resets it on some patches and driver updates; the
  memory's lockup story is scope-fenced to the retired Game-PC, its Borderless rule is not). Never edit
  game.cfg from a lane. As for the signal: the QA row proposes an HWND read, but a borderless window
  and a fullscreen one under flip-model optimizations can show the same `WS_POPUP` + full-monitor bits
  (a hypothesis, untested), and a game.cfg read is the other candidate, needing no window call at all.
  CHECK (any game, any mode, game FOREGROUND, rc-shell up, from the main checkout):
  `python tools/gated_b29_window_parity.py > <evidence>/b29_ingame.json`, then once more after the game
  to `<evidence>/b29_after.json`. Read-only. A process handle opens only for an allowlisted image
  (`OPENABLE_IMAGES`: the shell and the rc-shell overlay, on a pid `tasklist` just listed under it), and
  the tool takes no pid argument, so it never targets a League, Riot or Vanguard image and the game's
  own token stays unread on purpose (one gap: a listed pid recycled in the moment before the open would
  get a limited-query handle). Field paths: `build.qa6.state`, `build.qa13.state`,
  `cfg.window_mode`, `cfg.mtime`, `window.style`, `window.covers_monitor`, `window.foreground`,
  `window.quns`, `window_grade.verdict`, `elevation.overlay`, `elevation.uipi`.
  PREDICATES, stated before any game. These are DESIGN verdicts for the build and none closes the row.
  SIGNAL: `window_grade.verdict` AGREE = game.cfg was consistent with the window in this one state: it
  says nothing about the arm not played, and mode 2 + popup_full cannot exclude a flip-model fullscreen,
  so pair it with the operator's statement of the dropdown. DISAGREE = game.cfg is not a usable signal
  alone; the hint must not be built on it without a second source. AMBIGUOUS (mode 0, popup + full
  monitor) = a stale cfg and a flip-model fullscreen look alike; add the operator's statement. NO_RESULT
  = no evidence (no game window, not foreground, unlabelled mode, unknown state), never a pass. `cfg`
  differing between the in-game and after-game reads means the file moved during the game: the in-game
  read is void as a predictor, so record both. UIPI: `NO_BLOCK_POSSIBLE` = every overlay process is
  elevated, so QA13 has nothing to detect in that run. `GAME_TOKEN_NEEDED` = an overlay process is not
  elevated, QA13 stays live and needs a separate decision on reading the game's token. CAVEAT, unmeasured
  (no Electron was up): Chromium's sandboxed children may read non-elevated or unreadable under an
  elevated main process, which would give `GAME_TOKEN_NEEDED` or `UNKNOWN`. That errs away from a pass,
  so read the `elevation.overlay` rows before acting on either verdict. `OVERLAY_DOWN` / `UNKNOWN` = no
  evidence.
  AFTER THE BUILD (RM-1292 in the cycle report; the builder writes the selector here). QA6 PASS iff
  BOTH arms are recorded, each with the sample above and a timestamped frame: the hint renders in a game
  the operator states is Fullscreen, and is absent in one stated Borderless. The Borderless arm alone is
  PARTIAL, never a pass: a hint that never renders satisfies it. The Fullscreen arm is the operator's
  choice alone; no lane or drain asks for it, so the row can stay PARTIAL indefinitely. QA13 PASS iff
  the hint renders with an elevated game and a non-elevated overlay, stated and sampled, and is absent
  with both elevated. On this box that pairing would need a deliberately different launch, also the
  operator's choice alone; if nobody makes it, QA13 stays OPEN or is pruned by a human, never passed by
  a `NO_BLOCK_POSSIBLE` read. Until a build lands, `build.*` reads NOT_BUILT or CANDIDATE, and CANDIDATE
  is only a pointer for a human to read.
  EVIDENCE CONTRACT: both JSON files, the UTC timestamp, mode, queue and `liveclient.game_time_s` from
  one `/api/state` read beside the first sample, plus the predicate line above.
  SUBSTITUTION CHECK: does this answer whether the HINT RENDERED, or only whether a signal exists? Only
  the second: every verdict above is design evidence, so no sample ticks this row. A fixture, the
  idle sample and a dashboard-computed value are not evidence that a hint rendered. `self` and `shell`
  are not the overlay's token: `elevation.uipi` reads only `elevation.overlay`.
- **G2-40** (was B30) DS ratio-block spot verify vs target dummies (~174/577 flagged). DS-batch
  scoped: sample a handful per session, never a bulk pass. SOURCE: docs/DS_COMPLETENESS_GAP.md:90.
  **READY (lane 9 PREP s144 cycle 50, source read at `ad30d3adb`; NOT a tick).** Three measured facts
  reshape the check. (1) The filed "~174/577" is the item 351 census of 2026-06-08 and cannot be
  re-derived: the sidecar `cdragon_ability_ratios.json` persists `resolution` and `calc_type` per block,
  not the fallback reason. At 16.21.1 it holds 550 fallback and 865 mechanical blocks, which is 262
  fallback abilities and 143 clean control abilities. Do not quote 174 as a live count. (2) A fallback
  block carries no ratios and its `name` does not pair to an engine block, so the sample unit is the
  ABILITY and the number under test is the engine's own damage block, from the bare
  `AbilitiesSnapshot.load()` the routes default to (the ability-base-overrides flag is not modelled).
  (3) No reader in the repo takes a damage-dealt field from the Live Client payload, so the deciding
  number is combat text only.
  PROBE (`tools/gated_g240_ratio_spot.py`, read-only: GETs the relay `/latest-liveclient`, and writes
  only a new `--out` path it is given). In Practice Tool, on a full-HP target dummy, with no stacks built:
  1. Play a champion whose `plan` has a non-empty `sample_order` (85 fallback-holding champions have
     none at 16.21.1: no gradeable block under a same-type control; `python
     tools/gated_g240_ratio_spot.py plan --champion <id>` works before the game). Read the dummy's armor, MR and max HP in game; a value you cannot read voids
     the sample. A resist above 0 is refused unless penetration is proven absent: no real item owned,
     flat fields 0, percent fields 0.0 or 1.0 (which of those means "none" is unmeasured, and how the
     client reports a self-granted penetration is unmeasured too). So at a resist above 0 an AP-ratio
     block has no item AP behind it and may grade `BASE_ONLY`: read `weakest_ratio_part` before casting. Name
     the block a full-HP dummy will really show; a `Maximum` block usually is not one.
  2. BEFORE each cast, lock the prediction, one new file per block, naming the block one combat-text
     number will show: `python tools/gated_g240_ratio_spot.py capture --key Q --block "<block>"
     --target-armor A --target-mr M --target-max-hp H --out <evidence-dir>/q.json` (the directory must
     exist). Take a same-type `control` ability whose `predicted` reads at least 67, levelling or raising
     the stat first if it does not, then the fallback abilities in `plan`'s `sample_order`, skipping none
     for looking wrong. `--snapshot FILE` is a rehearsal only: its record says
     `source: file` and `grade` voids it.
  3. Cast, read the number, and after the session run `python tools/gated_g240_ratio_spot.py grade
     <evidence-dir>/q.json=<observed> ...` with EVERY captured sample. `grade` re-derives each record's
     role, type, prediction and ratio part from the engine and refuses a mismatch or another DS patch,
     but it cannot see a sample left off its command line, so dropping a missed control is the
     operator's to avoid.
  FIELD PATHS: `data.activePlayer.championStats` (`attackDamage`, `abilityPower`, `maxHealth`, `armor`,
  `magicResist`, `resourceMax`, `moveSpeed`, `physicalLethality`, `magicPenetrationFlat`,
  `armorPenetrationPercent`, `magicPenetrationPercent`), `data.activePlayer.level`,
  `data.activePlayer.abilities.<K>.abilityLevel`, `data.allPlayers[].rawChampionName` and `items`,
  `data.gameData.gameMode` (must be `PRACTICETOOL`), `data.gameData.gameTime`. The stat names are the ones
  `game_reader/snapshot_normalizer.py` reads and `rawChampionName` is the one `core/focus_board_live.py`
  reads. A missing stat, level or game time refuses and never reads as 0; penetration fields and `items`
  are needed only at a resist above 0.
  PREDICATE (stated before any game): a sample MATCHes when |observed - predicted| <= max(2, 3 percent
  of predicted), with predicted = engine `_evaluate_block` at the live rank and stats, times the engine
  `dps._armor_factor` of the resist. A control checks only the resist of its own damage type, so a MAGIC
  or PHYSICAL sample needs a control of that type (TRUE has no resist; any control serves), and it must
  predict at least 66.7 (2 / 0.03): below that the absolute floor is wider than 3 percent, so a wrong
  resist would pass the control and miss on a bigger sample, and such a control grades `WEAK`. A MATCH whose
  `weakest_ratio_part` is within that same tolerance is `BASE_ONLY` and does not count: a ratio times zero
  tests nothing, and another ratio on the block cannot cover for it. A miss inside twice the tolerance is `NEAR_MISS`, neither a pass nor a finding, because a
  control that just passes can still hide that much resist error and rounding. `SAMPLE_OK` = at least
  one fallback MATCH, no fallback MISMATCH, NEAR_MISS or VOID, under a clean passing same-type control for the
  same champion, target and patch whose implied game start is within 120 s (a heuristic for "same game").
  `FINDING` = a fallback miss past that band under such a control, base-only samples included.
  `INCOMPLETE` = anything else: a missing or missed same-type control voids that sample, match and miss
  alike, and a rehearsal is void. An `UNPREDICTABLE` sample (engine marks the block unparsed, the type is
  MIXED or unknown, it or a form sibling scales on target state, which no control proves, or its name
  repeats in the form, so the name cannot say which number it is) says nothing with or without a control:
  it cannot pass or find, and it does not block a clean pass beside it. Over 5 fallback samples
  in one `grade` run is refused as a bulk pass. `FINDING` is a CANDIDATE, not a verdict on DS: the tool models one block on
  a clean dummy, not every floor, proc or stack, so read the ability's in-game text first, then file a DS
  data defect on that one ability if it stands. It does not re-pitch a calc-graph resolver (closed,
  DS_COMPLETENESS_GAP b1).
  EVIDENCE CONTRACT: per sample the observed combat-text value, the capture record (predicted, `weakest_ratio_part`,
  rank, stats, target, `ds_patch`, `source`, `game_time_s`, wall-clock `captured_at`), plus the client patch,
  read by hand because the tool cannot see it (a client ahead of `ds_patch` voids a MISMATCH until DS
  catches up). `SAMPLE_OK` does not close the row: it is DS-batch scoped, so record which abilities were
  sampled and leave it open.
  SUBSTITUTION CHECK: `capture`, `plan` and `census` are compute; none of their output is evidence, and
  the tests only pin the arithmetic and refusals. The only live fact is a number the GAME drew, read
  from combat text by the operator, on screen or off a frame whose wall-clock `ts` is after the record's
  `captured_at` (`tools/gated_frame_readback.py` reports a frame's image facts and relay metadata and
  saves nothing; it extracts no text, so it cannot read the number). Any figure DS or the
  dashboard shows is compute or an end-of-game total, so reading one instead of combat text is the
  substitution kill. The record is a local JSON file: hand-editing `source`, `captured_at` or `game_time_s` would pass
  `grade`, so the tool stops mistakes, not a forger.
- **G2-41** (was B48) Vision-OCR native-res crop path: the live OCR read path still consumes the
  1280-HALVED `/latest-frame` (`vision_server/_frame.py` `_SELF_GRAB_MAX_WIDTH=1280`), so native-2560
  OCR boxes get scaled DOWN 0.5x at crop time. WIRE `core/screen_grab.grab_native()` into the OCR crop
  path (skip the downscale for OCR crops ONLY, keep it for the Sonnet/bandwidth `/latest-frame`), then
  validate OCR read accuracy vs a real in-game frame. Recalibration + native-crop WIRING is DONE
  (R94/R95/R96/R98); this is the last live-gated tail. SOURCE: LEDGER 793.
  **READY (lane 9 PREP s144 cycle 45, source read at `cfa461dfb`; NOT a tick).** Four measured facts
  reshape the check. (1) The premise still holds and the row is a BUILD-THEN-VALIDATE row, not a
  validate-only one: `core/screen_grab.grab_native` (`:108`) has NO production caller (`git grep -w
  grab_native -- '*.py'` outside `tests/` names only its own module and this row's tool). The coach
  OCR path is `modes/shared_vision._capture_screen` (`:58`, GET `:8889/latest-frame`) ->
  `core/vision_routing.read_or_escalate` (`:97`) -> `core/vision_tesseract.read_fast_fields`
  (`:644`), and that frame is downscaled to `vision_server/_frame.py` `_SELF_GRAB_MAX_WIDTH` (1280,
  `:85`; the OBS lane mirrors it), so the 2560 profile's boxes are cut at 0.5x (`_scale_bbox`; the R98
  guard pins gold `[1463,1407,1549,1433]` -> `(731,703,774,716)`). The "WIRING is DONE" sentence above
  is about the native PROFILE wiring (R94/R98), not about `grab_native`. (2) The wiring must NOT be
  done blind, and the decision input is an A/B on ONE live game, not a post-wire eyeball: does OCR
  read the HUD better off a native grab than off the halved frame? (3) `read_fast_fields` cannot run
  that A/B in one process: `timer` is a slow field read on one call in `_SLOW_MODULO` (5) and
  otherwise served from the module-global `_slow_cache`, so the second frame would report the
  FIRST frame's clock; `_DROP_FIELDS` is module-global too (`dashboard/routes_diag.py` `/api/ocr`
  saves and restores it for that reason). The tool runs the same per-field crop + parse
  (`_regions` / `_decode_img` / `_scale_bbox` / `_crop` / `_parse_field`) on each frame directly.
  (4) The calibrated profiles under `data/vision_profiles/` are gitignored and per machine: run from
  a lane worktree the probe loads a seed or the legacy 1920 table, so the tool refuses a decisive
  verdict unless `load_profile()` source is `profile`. PROBE (main checkout, game up, League in the
  foreground, HUD visible - not the shop, not the scoreboard, not dead): `python
  tools/gated_g241_ocr_native.py --samples 8 --interval 3 --json`. One sample = `:2999`
  `/liveclientdata/allgamedata` truth read 0 (`activePlayer.currentGold` floored, `activePlayer.level`,
  `gameData.gameTime`), the relay frame (its envelope `ts`, `source`, `width`, `height`), a native
  grab (skipped when League is not the foreground window or the desktop is locked), truth read 1.
  It refuses with exit 2 BEFORE any capture when `:2999` gives no `activePlayer`. PREDICATES (stated
  now, in `grade_value`): level MATCH iff level0 == level1 == OCR (VOID if the level changed);
  gold VOID if `|gold1 - gold0| > 3 g/s x span + 2` (a kill or a buy inside the sample), else MATCH
  iff OCR lies in `[min(g0,g1) - 3 x lead - 2, max(g0,g1) + 2]` (lead = how far the frame predates
  read 0); timer MATCH iff the `m:ss` OCR in seconds lies in `[floor(gt0 - lead) - 1, floor(gt1) +
  1]`; a relay frame older than `--max-age` (2 s), with no envelope `ts`, or with a `ts` more than
  0.5 s in the future is VOID for the halved path; a NONE (no read) counts as a miss. VERDICT over
  fields with >= 3 valid samples on BOTH paths: `HALVED_BETTER` (any field) -> do NOT wire, look at
  the native grab; `NATIVE_BETTER` (>= on all, higher on one by >= 2 samples' worth, because one buy
  or kill between the relay frame and read 0 can cost the older halved frame a sample the VOID rules
  cannot see) -> file the
  wiring slice behind a default-OFF flag, then re-read THIS row with the flag on; `NO_GAIN` -> the
  halved frame already reads these fields, wiring buys nothing measured - propose striking the tail
  with the evidence; `NO_RESULT` (too few valid samples, zero matches on both paths, or regions not
  a calibrated profile) -> re-take. EVIDENCE CONTRACT: the JSON verbatim per sample (values, both
  frame sizes, relay `source` and `age_s`, `gt`, grades), the `regions` block (`source`, `base`,
  `hud_color_installed`), the wall time, mode and queue. SUBSTITUTION CHECK: this answers whether
  OCR READS the live HUD better at native resolution - a compute over REAL pixels against `:2999`
  truth, which is the question the row asks before wiring; it does NOT answer whether a wired path
  is better in production (the relay frame may be `source='obs'`, the probe's HUD colour layer is
  its own `active_config_key()` install, and the probe bypasses the slow-field cadence the coach
  path keeps). Only `gold` / `level` / `timer` have a `:2999` truth; every other OCR field stays
  ungraded by this tool. A verdict from a fixture frame, a saved still or `data/vision_calib_reference/`
  is not evidence. Tool tests: `tests/test_gated_g241_ocr_native.py` (no screen, relay or `:2999`
  touched; pins the predicates, the refuse-before-capture gate, and the three source facts above).
- **G2-42** (was H4) ZOI finalization do-not-flip-blind eyeball: before flipping `obs.frame_source`
  (done) / roster-wiring ON, verify in a practice SR game (a) macro callouts on >=2 enemies MIA near
  drake, (b) district vector on `/api/state.zoi.districts`, (c) OBS frames matching the GDI baseline,
  (d) MIA rings + fluid DMZ + weighted bubbles render. Practice suffices (fog/presence/CV/OBS
  round-trip, no enemy-comp/rune dependency). SOURCE: ZOI_DISTRICT_ORCHESTRATION_PLAN.md:107-109.
  **READY (lane 9 PREP s144 cycle 46, source read at `12f2f3bb1`; NOT a tick).** (b) and (c) already
  carry recorded evidence (header, 2026-07-20: 13 districts, frame `source='obs'`; (c) was flipped
  live in LEDGER 796), so the open halves are (a) and (d). Five measured facts reshape them.
  (1) The SR fog feed is STILL DEAD, so (a) and the MIA-ring half of (d) are BLOCKED-BUILD, not
  live-gated: `core/vision_tracker.py` `_compute_enemies` (`:301`) coerces a non-dict `position` to
  `{}` (`:316`), so with the role string the client sends, `x == z == 0` and the first sighting
  (`:345`) never happens - every enemy keeps `missing_for_s=None`. Nothing feeds the minimap identity
  dots (`zoi.champion_dots`, `dashboard/_state_builder.py:912`) back into the tracker, and
  `zoi.mia` (`:971`) reads that same tracker. The macro tree needs >= 2 enemies at `MIN_MIA_S` 8.0 s
  (`core/macro_decision_tree.py:44`, `:93`). Measured on disk: the 9950 SR-equivalent records
  (`mode` sr / client / game) in `data/det_coach_shadow.jsonl` since 2026-07-05T00:00:00-05:00
  carry 0 `kind == "macro"` rows. The fence
  `tests/test_macro_decision_tree.py::test_dead_fog_feed_never_fires_on_live_sr_shape` still pins it.
  (2) The DMZ half of (d) is BLOCKED-BUILD too: `_state_builder.py:886` calls `compute_zoi` with no
  roster, and `core/zoi_influence.compute_zoi` adds `dmz` (`:401`) only when a roster is passed - the
  key is ABSENT, so no game can show it. (3) (a) can never be read on `/api/state.callouts` in a live
  game: `LIVE_SUPPRESSED_ENVELOPE_FIELDS` (`_state_builder.py:453`) blanks `callouts` (applied at
  `:1053`); the only record is the pre-suppression shadow log (`core/det_coach_shadow.py:99`).
  (4) `zoi` is built only when `mode_key` is `sr` or `aram` (`_state_builder.py:882`) and minimap dots
  exist (League focused); an SR game read under `client` serves no `zoi`. (5) `RC_ZOI_IDENTITY` now
  defaults ON (`core/minimap_blob_detect.py:255`; its `:487` docstring and LEDGER 796 still say OFF),
  and the CV over-detection LEDGER 796 named as the feed prerequisite was cut to <= 10 dots by
  `e14bde6ef` (per that commit; not re-measured live here). DRAINABLE NOW: the bubble half of (d) and
  a (b) re-check. PROBE (main checkout, practice SR, League focused, >= 3 saves across 2 minutes):
  `curl -sk https://127.0.0.1:8888/api/state > g242_state_<n>.json`, copy `data/vision_state.json`
  to `g242_vs_<n>.json` at the same moments, then `python tools/gated_g242_zoi_check.py state
  g242_state_*.json --json`, `... fog g242_vs_*.json --json`, and after the game `... shadow
  data/det_coach_shadow.jsonl --since <game start ISO with offset> --until <game end> --json`. Never
  commit the saves (they hold summoner names; RM-906). `fog` counts only SR `game_mode` copies
  (`CLASSIC` / `RANKED` / `PRACTICETOOL` / `JADE`, restating `core/sr_aram_worker.py:229`) and only
  ALIVE enemies (an ARAM or dead enemy carries a numeric clock that says nothing about the SR feed);
  `shadow` passes only the objective-danger tag `macro_objective_danger` (a gank-warning row is
  counted apart). PREDICATES (stated now): (b) PASS iff `state` reports `B_OK` (`zoi.districts` and
  `zoi.districts_fused` each carry all 13 SR ids) - a SHAPE check only, since `presence_payload`
  emits all 13 rows whenever `zoi` is built; it re-checks (b), it does not prove the counts right.
  (d-bubbles) the payload half
  is `BUBBLES_PRESENT`; the RENDER half needs a timed overlay minimap frame (frame `ts` vs
  `liveclient.game_time_s`) or the operator's confirm that the shaded bubbles sit on the dots - a
  payload alone does NOT tick it. (a) and (d-MIA) stay OPEN while `fog` reports `FEED_DEAD`. Once a
  feed is built: (a) PASS iff `fog` `mia_ge_min_max` >= 2 at a moment the drake is within 60 s AND
  `shadow` reports `MACRO_SEEN` for that window; (d-MIA) needs `state` `MIA_RINGS` plus the render
  read. (d-DMZ) stays OPEN while `state` reports `DMZ_NOT_WIRED`. EVIDENCE CONTRACT: the three JSON
  outputs verbatim, the wall times of each save, mode, queue and `game_time_s`, and the overlay frame
  path + `ts` for any render claim. SUBSTITUTION CHECK: `state` and `fog` answer whether the payload
  was COMPUTED and SERVED; they do NOT answer whether the overlay RENDERED it (the row asks render
  for (d)), and `shadow` answers whether a macro row was COMPUTED, never whether it reached the
  screen (B4 blanks it live). A fixture state, a synthetic `vision_state.json` or a replayed snapshot
  is not evidence. Tool tests: `tests/test_gated_g242_zoi_check.py` (hand-built inputs; pins the
  verdicts and facts (1)-(3), with a coordinate-position positive control and a roster-wired `dmz`
  control).
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
  **READY (lane 9 PREP s144 cycle 48; NOT a tick):** see the shared DS-flag eyeball READY block
  under G2-44 (one tool, `tools/gated_ds_flag_eyeball.py --row G2-47`).

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
  **READY (lane 9 PREP s144 cycle 48; NOT a tick):** see the shared DS-flag eyeball READY block
  under G2-44 (one tool, `tools/gated_ds_flag_eyeball.py --row G2-46`).

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
  **READY (lane 9 PREP s144 cycle 48; NOT a tick):** see the shared DS-flag eyeball READY block
  under G2-44 (one tool, `tools/gated_ds_flag_eyeball.py --row G2-43`).
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
  **READY - shared DS-flag eyeball block for G2-43 / G2-44 / G2-46 (RM-36) / G2-47 (lane 9 PREP s144
  cycle 48, source read at `6b36d2dd8`; NOT a tick, and NOT a default-flip request).** Four measured
  facts shape all four rows. (1) The flags never reach the screen today: `_route_rank` parses
  `exclude_off_axis_items`, `apply_ad_axis_ability_damage`, `apply_passive_damage` and
  `apply_extra_shot_procs` off the body with default False, `_route_rank_assassin` parses
  `exclude_off_axis_items` the same way (`agents/daemon_slayer/server.py`), and `rank_for` /
  `rank_assassin_for` (`core/daemon_slayer_client.py`) default every one of them False and emit it
  only when set. So the ON list is something the drain COMPUTES in the live context and the
  operator READS; no glance at the panel can show it. (2) A strip is invisible, so the useful
  output for G2-43 / G2-44 is what LEFT the top-8 and what left the whole pool. The route does not
  cap `top`, so the tool asks for 200 rows and the pool is complete when fewer come back; a strip
  seam that ADDS a candidate to a complete pool is an ANOMALY, not a judgement call. (3) The carry
  chokepoint `rank_for_primary_archetype` forwards `champion_fight_length` (Twitch / Jhin / Jinx /
  Caitlyn 0.5, `core/ds_champion_fight_length.py`), so the tool sends the same value on `/rank`;
  it does NOT replay the chokepoint's squishy-target swap or its post-call window filter, so the
  OFF list need not equal the rendered Meta Build row (that function also re-ranks over a wider
  coherence window and drops ranged off-class rows after the call) - the rows grade the flag's DELTA in a live
  context, never the panel. (4) G2-47's two flags are paired by construction: a pair whose ON body
  lacks either one is rejected as malformed. PROBE (main checkout, any SR game, the champion on the
  row, once at or after level 11): `python tools/gated_ds_flag_eyeball.py capture --row <ROW> >>
  <evidence dir>/ds_flag_pairs.jsonl` (inputs off `/api/state` the way the Meta Build panel reads
  them: `coach.champion`, `coach.level`, `liveclient.owned_item_ids`, `mode_key`; two compute-only
  POSTs to DS `:8860`, no state write), then after the game `python tools/gated_ds_flag_eyeball.py
  grade <evidence dir>/ds_flag_pairs.jsonl --row <ROW> --json`. Grade rejects, without grading and
  without an ANOMALY, a pair whose body mode is not `SR` and a pair whose `items_source` is not
  `owned_item_ids` (an empty `liveclient.owned_item_ids`: the panel then falls back to item sources
  the tool does not replicate), so a capture taken in an ARAM game or before the item read is up
  never counts toward coverage (s144 c49, RM-1290). COVERAGE (machine-checked, one live
  pair from each group): G2-43 one of Akali / Katarina / Fizz AND one of Zed / Talon; G2-44 one of
  Jhin / Jinx / Caitlyn / Twitch; G2-46 Corki (Ezreal optional, and when present it MUST come back
  with an identical top-8, the null control); G2-47 Akshan AND one of Warwick / Gwen / Kog'Maw.
  PREDICATES (stated now, before any game): the tool's `NEEDS_EYEBALL` is the precondition, never
  the tick (it has no PASS verdict). G2-43 / G2-44 PASS iff, for every graded pair, the operator
  reads `left top` plus the stripped-pool list and names NO item in them they would actually buy on
  that champion in that game (a hybrid or defensive buy); FAIL iff they name one (record which). For
  Twitch, Lich Bane leaving the top-8 is the measured headless expectation, not a FAIL. G2-46 PASS
  iff no item in Corki's `entered top` is an ability item a marksman never buys; an ON list that
  over-weights ability items is the EXPECTED failure (RM-98 mixed time base) and is a FAIL, not a
  surprise. G2-47 PASS iff the ON top-8 is not dominated by raw attack speed, defined now as: fewer
  than 5 of the 8 are attack-speed-primary items by the operator's classification, for Akshan and
  for the second champion. `INCOMPLETE` leaves the row open; `ANOMALY` leaves it open and is filed
  as its own finding. EVIDENCE CONTRACT: the pairs file and the `grade --json` output verbatim, the
  wall time of each capture inside the recorded game window, mode, queue, champion, level and
  `game_time_s`, and the operator's one-line verdict per champion naming the items they judged. The
  pairs hold champion names and item ids only, but stay in the evidence dir, never committed.
  SUBSTITUTION CHECK: the pair answers what the engine COMPUTES with the flag ON in a live context;
  the row asks whether that list READS SANE to a player, and only the operator's read answers it.
  A pair captured with `--champion/--level/--items/--mode` carries no `game_time_s` and is rejected
  as not live, and a PARTIAL override is refused, `--mode` alone included (it would mix a hand-given
  champion or mode with the live game's own inputs); a pair whose `ts` falls outside the recorded game window is not evidence either (the tool
  cannot see a hand-edited `game_time_s`, the window check can). None of the four rows proposes a
  default flip; G2-47 in particular arms every kit-passive registry entry at once. Tool tests:
  `tests/test_gated_ds_flag_eyeball.py` (hand-built rows; pins the bodies, the G2-47 pairing, the
  strip anomaly, the null control, coverage, the partial-override refusal, the SR and
  `items_source` rejections, and against source the four route flag defaults, the route's
  default-20 `top` read passed straight through with no reassignment or min/max clamp in the route
  or in the `rank.py` / `burst.py` rankers, the rankers' `ranked[:top_n]` cut, and the chokepoint's
  `fight_length` forward).
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
  **READY (lane 9 PREP s144 cycle 47, source read at `1ae5a0918`; NOT a tick).** Four measured
  facts reshape the row. (1) The repo states BOTH answers to question (1), inside one function:
  `dashboard/_liveclient.py` `liveclient_summary` builds two extracts from the same `events.Events`
  stream - `minion_events` (RM-124; comment "emits a single MinionsSpawning event at first-wave
  spawn") and `minion_spawn_events` (R221; comment "emits it once per wave") - and both reach
  `/api/state` -> `liveclient` whole (`dashboard/_state_builder.py` envelope key `"liveclient": lc`).
  Neither comment cites a capture. G2-39's READY block and `tools/gated_g239_wave_clock.py` took
  the ONCE reading as measured (`ANCHOR_MULTI` = FAIL); this row's capture decides it for BOTH rows,
  so grade G2-39 (a) only after this verdict. (2) The two clocks part after 14:00 even from the same
  anchor: `core.event_callouts` walks a piecewise 30 / 25 / 20 s interval, `dashboard/_wave_timing.py`
  takes the median observed gap, else the constant `_DEFAULT_WAVE_INTERVAL_S` 30 s. Under ONCE the
  R221 clock therefore projects 30 s waves all game: from anchor 1:05 both put cannons at 2:05, 3:35
  ... 12:35, then `event_callouts` says 14:30, 15:20, 16:10 and `_wave_timing` says 14:35, 15:35,
  16:35 (first divergence = the 9th cannon). That is a MODEL comparison, not evidence for either; a
  game shorter than ~14:40 cannot tell them apart. (3) The cadence table the row grades is
  `_CANNON_CADENCE = ((0.0, 3), (840.0, 2), (1500.0, 1))` - the same 14:00 / 25:00 breaks and parity
  as `event_callouts`, so question (2) for both modules is one observation. (4) `wave_timing` has
  NO production caller (only `tests/test_wave_timing.py`), so nothing on screen can show the R221
  clock; the row is answered from the feed and an observation, never from a render.
  PROBE (read-only; `tools/gated_g245_spawn_stream.py`, tests `tests/test_gated_g245_spawn_stream.py`):
  (1) save `curl -sk https://127.0.0.1:8888/api/state` to a gitignored file at least twice in one
  SR game, the last one at game clock 3:00 or later, and run
  `python tools/gated_g245_spawn_stream.py stream <file1> <file2> ... --json`; (2) note the game
  clock at which each cannon wave LEAVES the nexus (one per bracket if the game runs long:
  before 14:00, 14:00-25:00, after 25:00; the clocks predict the SPAWN, so a lane-arrival read is
  the wrong comparand), then run `python tools/gated_g245_spawn_stream.py clocks --anchor <first
  spawn> [--spawns <the captured spawn times, REPEATS only>] --observed <m:ss,...> --json`.
  FIELD PATHS: `/api/state` -> `liveclient.minion_spawn_events[].spawn_at_s`,
  `liveclient.minion_events[].at_s`, `liveclient.game_time_s`.
  PREDICATE (stated before any game): (1) `ONCE` = exactly one distinct spawn time and the newest
  snapshot is at least 75 s past it (two later waves are due under any interval of 30 s or less);
  `REPEATS` = two or more distinct times, with the median gap reported; either is a PASS of the
  QUESTION and is recorded with its value. `EXTRACTS_DISAGREE` (the two extracts hold different
  times) voids the capture and is its own defect; `FIELDS_MISSING` = the RC build lacks the extracts;
  `TOO_EARLY` / `NO_EVENT` / `NOT_IN_GAME` = re-take. The tool does not check that every snapshot
  is from ONE game; the file mtimes do.
  Consequence: ONCE = the R221 module's "once per wave" premise is false, its `wave_number` past
  14:00 rides the 30 s constant, and the panel stays unwired until it gets a gameTime projection
  (a Tier-1 follow-up, not a flip); REPEATS = G2-39 (a) `ANCHOR_MULTI` is the expected shape and its
  grader needs the earliest-event reading it already uses in production (`_wave_anchor_s`). (2)
  `BOTH_MATCH` / `CALLOUTS_ONLY` / `TIMING_ONLY` / `NEITHER`, each observed cannon within 3 s of a
  predicted SPAWN; a bracket the game never reached stays OPEN. A miss in a bracket = correct that
  module's constants with the observed times as test data (Tier-1), never a flip.
  EVIDENCE: the verdict + spawn times + each file's mtime and game clock; each observed cannon as
  `m:ss` with how it was read (operator glance or a `:8889/latest-frame` whose `meta.ts` was
  checked against `liveclient.game_time_s`).
  SUBSTITUTION CHECK: a passing `tests/test_wave_timing.py`, the `clocks` schedule without
  `--observed`, or a hand-built `/api/state` answers what the code COMPUTES, not what the Live Client
  SENDS; only a saved state from a real game (file mtime inside the game window, `game_time_s`
  advancing across the snapshots) answers (1), and only observed nexus-leave clocks answer (2). A
  synthetic file with the right shape is NOT caught by the tool, only by the mtime and provenance.
  Tool tests: `tests/test_gated_g245_spawn_stream.py` (hand-built inputs; pins the verdicts, that
  each schedule is the production function walked forward, the 14:30 / 14:35 divergence, and the
  source facts (1), (3) and (4)).

---

## GATE 3 - ARAM MAYHEM (queue 2400, gameMode KIWI, RC MODE_ARAM)

Real comps + a real bench, no Match-V5. Also clears GATE 1 and any own-build GATE 2 row.
**Pick tabled champs when the bench offers them** (Rakan / KSante or Rell / a Cluster-A) - the
survivability flips below cannot roll otherwise.

### Champ-select

- **G3-01** (was A6) E7a bench-swap queue-drain eyeball (`eb361c27`): click a bench champ in a real
  ARAM champ-select and confirm the swap registers visibly faster.
  **PREP 2026-10-25 (lane 9 s133 cycle 8, source read at `f210f5cd9`; NOT a tick).** "Visibly faster" is
  not a predicate, so it is restated as a measured latency. E7a re-polls the command queue at 0.1 s
  after a `bench_swap` (`tools/lcu_agent.py:150-151`, `drain_once` `:1681`), and E7 TODO-1 wakes the
  capture loop (`_signal_state_refresh` `:1720`, `_swap_wake` in `_state_push_loop` `:1614`) so the new
  pick lands OFF the 1.0 s capture cadence. Both clocks live in the agent process: the
  `[cmd] bench_swap -> {...}` line in `logs/lcu_agent.log` (T_cmd) and the relay capture
  `GET :8889/latest-lcu` -> `data.ts` (stamped at the end of the shape, `lcu/snapshot_shape.py:598`).
  `/api/state` is NOT the source: it is cached for `RC_STATE_CADENCE_SEC` (0.5 s,
  `dashboard/routes_state.py:207`) and merges captures. Plumbing: `tools/gated_bench_swap_probe.py`
  (tests `tests/test_gated_bench_swap_probe.py`). Idle shape measured 2026-10-25 03:47 local, phase
  `None`: 12 distinct captures in 12 s, median gap 1.031 s (so c_est is about 0.03 s at idle; expect
  more in champ select). The vision token does not resolve inside a lane worktree (no
  `config/vision_token.txt`), so run it from the main checkout.
  **CHECK (any ARAM / Mayhem champ-select with a non-empty bench):** run
  `python tools/gated_bench_swap_probe.py --watch 90`, then click a bench champion on the RC DASHBOARD
  bench strip (`.csv-bench-cell`); a swap made in the League client writes no `[cmd]` line and tests
  nothing. Swap twice if the bench allows. Predicate stated first (the tool docstring is the full
  form). With one agent every natural capture gap is longer than its 1.0 s wait, so a gap under
  0.95 s is the WAKE (absolute: a missed poll only widens gaps and cannot fake one). PASS iff the
  first capture showing the new `champ_select.my_champion` is a WAKE and lands within
  2 x c_est + 0.25 s of T_cmd (c_est = median baseline gap - 1.0 s). FAIL iff the polls were dense
  (no poll gap over 0.3 s) and no WAKE appeared before the new pick, or before a 3 s deadline when the
  champion never changed after an ok POST. NO RESULT, never a pass: a natural tick inside the bound
  (coincidence: under the OLD code a quarter to a half of all clicks look that fast), a WAKE that still
  shows the old champion (LCU applied it late), any capture inside the bound that still shows the
  old champion (a click mid-capture: the woken capture after it can live in the relay for less than
  one poll, so a missed capture can HIDE a wake, though never fake one), an off-cadence capture BEFORE
  the click (a second writer or another wake), or sparse polls. Row PASS = at least one PASS and zero
  FAIL. Two independent verifier passes refuted the first two drafts of this predicate; both sets of
  corrections are in.
  **RE-CHECK (lane 9 PREP s144 cycle 110, 2026-11-08, source read at `07c96e843`; NOT a tick;
  S144-G-98).** The PREP holds, with one new precondition. (i) `f210f5cd9` is a pre-rewrite
  twin: the filter-repo commit-map gives `83c0c2623` (same subject and committer time), on HEAD's
  chain. (ii) The line cites above drifted; read them by symbol: `BENCH_CMD_FAST_INTERVAL = 0.1`
  and `LATENCY_SENSITIVE_CMDS`, `drain_once`, `_signal_state_refresh`, `_swap_wake` in
  `_state_push_loop`, `INTERVAL = 1.0` (all `tools/lcu_agent.py`), `state["ts"] = time.time()`
  at the end of `lcu/snapshot_shape.py` `shape_snapshot`, `RC_STATE_CADENCE_SEC` default 0.5 in
  `dashboard/routes_state.py`. (iii) The swap path is unchanged since `83c0c2623`: an AST compare
  finds `drain_once`, `_signal_state_refresh`, `_cmd_poll_loop`, `capture_state` and the five
  constants (`BENCH_CMD_FAST_INTERVAL`, `LATENCY_SENSITIVE_CMDS`, `_swap_wake`, `INTERVAL`,
  `CMD_INTERVAL`) identical. `_state_push_loop` gains only `_note_live_queue(state)`
  (`d9f082578`, in-memory, no LCU call, between the `ts` stamp and the post, the same on every
  pass, so it cannot make or hide a WAKE). `execute_command` gains only `_loadout_refusal`
  (`bench_swap` is not in `_LEAGUE_LOADOUT_CMDS`) and `r` -> `_r` on five unread LCU-call
  results, the bench-swap POST among them (`275e43c73`). (iv) The
  click path holds: `.csv-bench-cell.is-clickable` -> `lcuCmd` -> POST `/api/lcu-cmd`
  (`dashboard/routes_loadout.py` `_serve_lcu_cmd_post`, allowlisted, `bench_swap` schema
  `championId` int) -> `:8889/lcu-cmd` -> the agent's `drain_once`. (v) T_cmd still comes from
  `logs/lcu_agent.log` (`SafeRotatingFileHandler`, `DEFAULT_BACKUP_COUNT` 2, format
  `%(asctime)s %(levelname)s %(message)s`). Under the service host the agent's stdout goes to
  DEVNULL, so the file is the only copy. Read-only on 2026-11-08: every line matches the probe's
  stamp prefix, no `bench_swap` line yet. `config/vision_token.txt` is still absent from the lane
  worktree, so the run-from-main-checkout rule stands. `tests/test_gated_bench_swap_probe.py`:
  17 passed at `07c96e843`. (vi) NEW PRECONDITION. Since the 2026-10-31 launcher cutover no
  task runs the agent: the rc-shell service host spawns it. Before the champ select, apply the
  LX-01 precondition (3) REPLACEMENT RULE (EXTERNAL-LIFT INTAKE): `launcher_status.json`
  running, and the `lcu_agent` pid tied to the agent by CommandLine and UTC CreationDate. A
  `HEAD` newer than that `started` means older code may be running, so record both. Today the
  launcher has been `halted` since 2026-11-01T02:17:21Z, so no agent runs. With no agent, the
  watch sees no `[cmd]` line and no fresh capture, and reads NO_RESULT, never FAIL (exit 1
  with the relay down too). The 2026-10-25 idle gaps were measured under the task-run agent.
  They are informational only: each verdict takes `g_nat` from its own pre-click baseline
  window, so no re-measure is needed.
- **G3-02** (was A10) KEYSTONE residual: operator visual reassurance of the rendered bench (data path
  proven; no capture pursued). SOURCE: ROADMAP.md:100.
  **PREP 2026-10-25 (lane 9 s133 cycle 8; NOT a tick). PRUNE CANDIDATE for a human.** The KEYSTONE bug
  this residual trails (Mayhem q2400 missing from the ARAM queue set, so the bench never rendered) was
  fixed and proven live 2026-05-17 (`docs/history_notes.md:24438`; the set is now
  `lcu/champ_select_shape.py:60`, `is_aram` `:417`). In the operator's annotated-screenshot triage
  "KEYSTONE residual 'none functional'" carries the operator mark `?` (verify, then prune) and the plan
  disposition PRUNE (`docs/history_notes.md:35846`). Not struck here:
  moving a row is a human call. If it stays, it rides the G3-01 champ-select for free.
  **CHECK:** predicate first - PASS iff the bench strip (`web/js/panels/champ_select.js:1348`
  `_csvBenchHtml`) shows one `.csv-bench-cell` per id, with the `data-bench-id` order equal to
  `champ_select.bench[:10]` from a relay capture taken within 2 s (the G3-01 probe reports it as
  `bench_after`), and every cell shows a champion icon, not `?`. With an empty bench, PASS iff the
  "no bench champs yet" line shows. FAIL = a missing, extra or reordered cell, or no strip at all while
  `champ_select.is_aram` is true.
  **RE-CHECK (lane 9 PREP s144 cycle 111, 2026-11-08, source read at `1385be75b`; NOT a tick;
  S144-G-99).** Still a PRUNE candidate for a human. The predicate holds with one gap closed and
  one precondition added. (i) Cites drifted; read them by symbol. The residual's text now lives
  in `docs/ROADMAP_HISTORY.md` ("Residual: none functional"); `ROADMAP.md` no longer carries it.
  The fix is `docs/history_notes.md` item 87 (2026-05-17 late), and the triage line is row 14
  "KEYSTONE residual" with mark `?`, disposition PRUNE. Its fix commits (`3eb2e2d`, `a5405ee`)
  do not resolve in this clone or in the filter-repo commit-map (a pre-2026-07 cite; Settled).
  The fix is read by symbol instead: `ARAM_QUEUE_IDS` in `lcu/champ_select_shape.py` holds 2400,
  and the shape's `"is_aram"` key reads `queue_id in ARAM_QUEUE_IDS`. (ii) Render gate: the panel
  builds the strip only when `_csvDetectMode(cs)` is `"aram"`. That is `is_aram` or queue
  450 / 920 / 2400, with the Arena queues tested first, and no Arena queue is in the ARAM set. So
  "no strip at all while `is_aram` is true" stays a valid FAIL. (iii) GAP CLOSED. In
  `_csvBenchHtml` a cell shows `?` only when the id is empty or missing from `CHAMPS.byId`
  (`/data/champions_index.json`). The icon is an `<img>` with `onerror` that sets
  `display:none`, so a 404 icon renders as a BLANK cell, not `?`. Read every cell as: one `<img>`
  with `naturalWidth > 0` and a computed `display` other than `none`. A blank cell is a FAIL like
  `?`. (iv) NEW PRECONDITION, the icon mirror. `/data/` is served from `web/` (`routes_static.py`
  `_serve_web_asset`), and `web/data/ddragon/` is a gitignored local mirror. A patch bump that
  moves the tracked index `version` without a mirror refresh blanks EVERY bench icon. Read-only
  2026-11-08 in the main checkout: index version 16.22.1, 173 ids, 0 without a
  `web/data/ddragon/16.22.1/img/champion/<slug>.png`. Re-run that join before the champ select.
  A miss is a setup fault: refresh the mirror (`tools/ddragon_mirror_refresh.py`), do not grade.
  (v) Bench source: the G3-01 probe's `bench_after` is the FULL bench, so compare its first 10.
  It exists only when a dashboard swap reached a new capture. With no swap, read
  `GET :8889/latest-lcu` -> `data.champ_select.bench`, and its `data.ts` must be within 2 s of
  the DOM read. (vi) Evidence source and SUBSTITUTION. Allowed: the operator's own look at the
  rc-shell pane, or a headless Chromium DOM read of `https://127.0.0.1:8888/` during the live
  champ select. Record which, since the second is another client of the same page and state, not
  the operator's pane. NOT evidence: rendering `_csvBenchHtml` against a fixture or a replayed
  relay payload (the compute half). The precondition carried from G3-01 (vi) also binds: the
  launcher has been `halted` since 2026-11-01T02:17:21Z, so no agent and no bench data today.
- **G3-03** `[CS-SCENARIO - UNBLOCKED 2026-10-24 by RM-850; was BLOCKED ON WIRING the same day]` (was C2) Comp-verdict VARIANT
  branch still unobserved (SWAP + STAY validated at LGS2; never surfaced in-game 2026-07-04). Soundness
  discharged headless (OQ22). **WHY IT NEVER ROLLED (lane 9 PREP s133, source read at `373c693bb`,
  adversarial pass CONFIRMED; NOT a tick): it CANNOT roll live.** `core/aram_comp_verdict.py` returns
  `variant` only through `_find_variant` over `state["variants"]` (`:381-383`, `:395-414`, `:333-340`);
  the live panel POST to `/api/aram-comp-verdict` sends only `my_champion` / `my_team` / `their_team` /
  `bench` (`web/js/panels/champ_select.js:1685-1691`; `dashboard/routes_coach.py:208-209` passes it
  verbatim, and `:205-206` documents `variants` / `current_variant` as accepted fields); the
  `/api/champ-select-coach` POST (`champ_select.js:167-177`) sends none either and its `advise_pick` is
  shadow-log only; `coaches/aram_team_analyzer.analyze()` has no importer. The panel already builds the
  variants (`champ_select.js:865` `_csvBuildVariantsFor`) and never posts them. ~~Riding more ARAM lobbies
  drains nothing until **RM-850** (send the variants) lands; do NOT count this row in a gate session
  before then.~~ **UNBLOCKED (lane 9 PREP s133 cycle 4, read at `af8c28fc8`; NOT a tick):** RM-850
  SHIPPED (`14f804fc2`, LEDGER 1816) - `_csvFetchCompVerdict` now POSTs `variants` (via
  `_csvCompVerdictVariants`, `champ_select.js:1654`) and `current_variant` (`:1726`); the main checkout
  holds the commit, and the LIVE-SERVED asset carries it (`GET https://127.0.0.1:8888/js/panels/champ_select.js`
  has 3 `_csvCompVerdictVariants` hits, 2026-10-24T23:48:45-05:00; asset-only, ADR-008, no restart). Ride
  it in the next ARAM / Mayhem champ select. **CHECK (any ARAM / Mayhem champ-select with an all-AD / all-AP or no-sustain
  ally comp):** PASS iff the rendered `.csv-bench-verdict--variant` banner shows `VARIANT -> <key>` with a
  `<key>` from that champion's posted variants; a POST of our own payload is the COMPUTE half only.
  **RE-CHECK (lane 9 PREP s144 cycle 112, 2026-11-08, source read at `dd74f8632`; NOT a tick;
  S144-G-100). RE-BLOCKED: no GENUINE VARIANT is reachable on this box today, and the only
  reachable VARIANT is a keyword false positive.** Line cites above drifted; read by symbol:
  `_csvFetchCompVerdict` POSTs `variants` (the `_csvCompVerdictVariants` rows of
  `_csvBuildVariantsFor`) and `current_variant` (the active chooser key);
  `_serve_aram_comp_verdict_post` (`dashboard/routes_coach.py`) passes the body verbatim to
  `comp_verdict`; the banner class `csv-bench-verdict--${rec}` and `VARIANT -> ${variant_to}` are
  built in `_csvCompVerdictHtml`. Three new facts. (i) ROW SOURCE: `_csvBuildVariantsFor` returns
  only the `POST /api/loadout/list` rows: `list_variants(champ, "aram")` (ONE curated row per
  champion, key `aram-collapsed`, label "Builds for <champ>", 172/172) plus the
  `coaches/sr_user_builds.py` rows (key `userbuild_<id>`, merged for every mode). No producer
  serves `summary`, so the engine matches key + label only. The main checkout's gitignored user
  build store (read-only, 2026-11-08) holds builds for 2 champions (Caitlyn, Vayne; 2 crit rows
  each). (ii) SELF LEAN: `my_team` carries the local cell (`_team_picks` over myTeam in
  `lcu/champ_select_shape.py`), so a damage gap of the type the champion itself leans cannot open.
  Caitlyn and Vayne both lean AD, so their "crit" rows (AD keyword set) never meet a "lacks AD"
  gap. Genuine reachable: 0 of 172. (iii) KEYWORD FALSE POSITIVE: `_variant_addresses` is a
  SUBSTRING test, and "ap" is inside "collapsed", so `aram-collapsed` matches `_AP_VARIANT_KW` for
  all 172. With a userbuild row active on Caitlyn / Vayne and an all-AD ally comp (damage gap
  "ap", no earlier bench-fixable gap), the banner reads `VARIANT -> aram-collapsed`, reason "All-AD
  comp - the Builds for <champ> variant adds magic damage." That is a mis-fire, and the PASS rule
  above would accept it. PROBE (repo root, before the lobby; read-only):
  `python tools/gated_g303_variant_reach.py <champ> [--current <active key>]`; `genuine_gaps`
  non-empty = that champion can roll a genuine VARIANT; `--all --reachable-only` lists them.
  AMENDED PREDICATE (stated before any game): PASS iff the banner shows `VARIANT -> <key>`, `<key>`
  is in the posted keys, AND the probe for that champion and active key reports the gap named by
  the reason with `kind == "genuine"` and `self_closes == false`, and the reason matches the comp
  (all-AD -> magic, all-AP -> physical, no sustain -> healing). A VARIANT on a `kind ==
  "substring"` gap (today `-> aram-collapsed`) is a FAIL (keyword mis-fire), recorded with the
  reason string. EVIDENCE: banner text + reason (operator pane or a headless Chromium DOM read of
  :8888; say which), the live POST response (`variant_to`, `reason`, `gaps_before`), the ISO time,
  queue, and the probe line. SUBSTITUTION: our own POST, the probe, or the engine on a fixture is
  the compute half only. UNBLOCKS when (a) a whole-word keyword match lands in
  `_variant_addresses` (headless code fix; merger follow-up, needs an id) AND (b) the operator saves
  an ARAM build whose label names a damage type the champion does not lean, or sustain (e.g. an
  "AP" row on an AD champion, a "crit" row on an AP one). Precondition carried: launcher
  `halted` since 2026-11-01T02:17:21Z.

### In-game

- **G3-16** (filed 2026-08-12 as "G3-14", B4-d / RM-189; RENUMBERED 2026-10-24 by lane 9 PREP s133
  because G3-14 was already the C17 row below since the 2026-07-18 reorg - the filing commit
  `0dc5dbd0d` added this row and never touched the OPEN count, so like G6-04 it sits OUTSIDE the
  111; LEDGER 1240 still says "G3-14" and is append-only) **`hz_choice_shadow` records must carry a REAL
  `game_id` during a live game.** The plumbing is proven headless: `game_id` is threaded from
  `lcu_snapshot` through `shadow_log_precomputed_choices` into the record, and
  `tests/test_b4_shadow_match_id.py` pins the contract at that boundary. What CANNOT be proven
  without a game is that the value arrives non-null, because `lcu/snapshot_shape.py:431-439` (drifted;
  `:543-557` at `bc5d38dce`, `state["game_id"] = gid` on `GameStart` / `InProgress`) only
  sets `state["game_id"]` while the gameflow phase is `GameStart` / `InProgress` - idle and
  champ-select ticks legitimately carry nothing, so a headless run cannot distinguish "correctly
  absent" from "silently never populated". **Do NOT close this by asserting the key EXISTS** - it
  always exists and is None by design; that is the mis-file trap this file exists to catch.
  **Action:** during any live ARAM Mayhem tick, `tail` the last row of `data/hz_choice_shadow.jsonl`
  and assert `game_id` is a non-empty numeric string and `game_run_id` equals it (rather than the
  `local-aram-<ts>` fallback). One row closes it. **Also worth one glance:** that every row of the
  SAME game shares one `game_run_id`, which is the property the post-game review (B4-e) depends on.
  Applies equally at GATE 2 / 4 / 5 - ARAM is simply the cheapest gate that reaches it.
  **READY (lane 9 PREP s133 cycle 2, source read at `bc5d38dce`; NOT a tick).** The file has had NO
  live row since `2026-08-02T22:34:15Z` (last row; the 2026-08-06 mtime is the RM-158 tag rewrite
  `2bd5714a5`), so the row has never been observable since it was filed - the FIRST row of the next
  game is the evidence. PREDICATE (stated before looking): PASS iff a row with `ts` after the game's
  start has `game_id` matching `^[0-9]+$` and `game_run_id == game_id`; FAIL if `game_run_id` starts
  `local-` (the `_run_id_for` fallback, `core/hz_choice_shadow.py:63`, form `local-<mode>-<ts>`) while
  `/api/state` shows the LCU phase `InProgress`. PROBE (repo root, mid-game):
  `python -c "import json;r=json.loads(open('data/hz_choice_shadow.jsonl',encoding='utf-8').readlines()[-1]);print(r['ts'],r['mode'],r['game_id'],r['game_run_id'])"`
  plus the same-game check: every row since the game's first `ts` shares one `game_run_id`. A row
  only lands on a live tick with `lc.champion` set and mode `sr` / `aram` / `arena`
  (`dashboard/_deterministic_coaching.py:1623-1634`).
  **RE-CHECK (lane 9 PREP s144 c113, S144-G-101; NOT a tick).** Line cites drifted; read by symbol:
  the id is set in `lcu/snapshot_shape.py` `shape_snapshot` (`state["game_id"] = gid`), the
  fallback is `core/hz_choice_shadow.py` `_run_id_for`, the live gate is
  `dashboard/_deterministic_coaching.py` `shadow_log_precomputed_choices` (`lc.get("champion")`,
  `_MODE_KEY_TO_LOWER`; `client` maps to sr).
  (1) `shape_snapshot` now reads the gameflow id on `Reconnect` too (S134 P0), matching
  `dashboard/_state_builder.py` `_IN_GAME_PHASES`; the FAIL clause reads "InProgress" as any of
  `GameStart` / `InProgress` / `Reconnect`. (2) SCOPE WIDER THAN FILED: a leading `local-` run
  then the real id is BY DESIGN (`tests/test_b4_shadow_match_id.py`
  `test_game_id_appearing_mid_game_takes_over`), so "every row of the same game shares one
  `game_run_id`" is false for a correct game. Amended glance: one numeric `game_id` per game, and
  no `local-` row AFTER the first real-id row (that is the LCU id dropping mid-game, which splits
  the B4-e series). (3) A `local-` row also means a STALE relay: `dashboard/_liveclient.py`
  `lcu_summary` returns `{}` when the `:8889/latest-lcu` push is over 5 s old, so record the
  `/api/state` LCU phase on the same pass. (4) A tick `unidentified_live_game` flags (mode
  `client`, empty liveclient, in-game phase) skips the shadow log entirely: no row = NO_RESULT.
  AGE (read-only, main checkout): 58806 rows, last `ts` 2026-08-02T22:34:15Z, ZERO carry a
  `game_run_id` key (all pre-B4-d); none of the in-game shadow logs written on the same tick
  (`det_coach`, `hz_build`, `aram_coach`, `macro_response`, `objective_playbook`) has a row after
  the same second (the vision-tier `fusion` / `ocr` / `vision_merge` logs end 3 s later, same
  game; later files are `champ_select_shadow.jsonl` 2026-09-30, a champ-select log, and four
  `*_test_leak_*` files 2026-09-11), and `data/coach_tick_trace.jsonl`'s 340 rows after it all have
  `game_time` None, `n_events` 0 (idle, last 2026-09-11).
  PROBE (repo root, mid-game; prints counts, never an id):
  `python tools/gated_g316_shadow_game_id.py --since <game start, UTC ISO> --phase <LCU phase>`.
  PASS = one numeric `game_id`, `game_run_id == game_id` on every real row, no `local-` row after
  the first real one. FAIL = mismatch, non-numeric id, `local-` after real, or all `local-` with an
  in-game `--phase`. NO_RESULT = empty window, every row pre-B4-d, two real ids (narrow `--since`).
  Measured today: `--since 2026-08-02T00:00:00Z` -> NO_RESULT (1138 pre-B4-d rows). SUBSTITUTION:
  the tool over a fixture or our own writer call is the compute half; only a live game's rows count.
  Precondition carried: launcher `halted` since 2026-11-01T02:17:21Z (RC down, no rows can land).

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
  **AGE RE-CHECK 2026-11-10 (lane 9 s144 cycle 144, S144-G-131, source read at `b09a7b6fa`; NOT a
  tick).** The MIS-FILED verdict holds; three corrections. (1) STILL DEFAULT-OFF AND UNCONSUMED:
  `inspect.signature(core.archetype_picks.get_archetype_for)` reads `(champion: str,
  prefer_aram_win_axis: bool = False)` (def `core/archetype_picks.py:798`, override branch `:833`),
  and in tracked non-test code no call passes the flag - in tracked `.py` files outside `tests/` the
  name appears only in the resolver itself (def, docstring, branch), two comments
  (`core/archetype_picks.py:113,226`) and the build script's strings (item 3); beyond Python it is
  named only in prose (the table's own `_comment`, `ops/audit/ds_cross_eval/TIER2_REPORT.md`, docs),
  never in a call. The resolver
  takes no mode argument, so the mode-gate hazard holds by signature. (2) COUNT AND CITES DRIFTED: the
  row says "13" but its own list names 14 sites, and all 14 still exist, 13 of them moved:
  `coach_integration/archetype_dispatch.py:380`, `coach_integration/enemy_stats.py:218`,
  `core/build_order_precompute.py:513`, `core/build_planner/kit_synergy.py:590,641`,
  `core/ds_antitank_hint.py:114`, `core/zoi_capability.py:140`, `dashboard/routes_archetype.py:190,242`,
  `dashboard/routes_ds_sweep.py:214`, `dashboard/routes_spike_curve.py:196` (the only cite that held),
  `dashboard/routes_state.py:1155,1581`, `dashboard/_state_builder.py:793`. Five more default-flag
  callers live in `tools/` (`ds_matchdb_mcp_server.py:311,391` via alias `_get_archetype_for`,
  `daemon_slayer_build_orders_generate.py:205`, `ds_cross_eval/probe_champion.py:207`,
  `gated_g238_top_pick_flip.py:340`); a resolver-default flip would reach them too. (3) "ONE BUILD
  SCRIPT" PASSES `True` IS REFUTED: `ops/audit/ds_perm_swarm/build_aram_archetype_override.py` never
  imports the resolver - it names the seam only in its docstring (`:37`) and in the JSON `_comment`
  string it writes (`:211-212`). `True` is passed only in `tests/test_aram_archetype_override.py`
  (`:189,199,212,227`). (4) TABLE REPRODUCES, BUT STALE: `core/aram_archetype_override.json`
  `champions` holds 6 entries, and resolving kit default vs override reads Kayle onhit -> carry,
  KogMaw onhit -> carry, Shaco assassin -> mage, Shyvana bruiser -> mage, Zilean enchanter -> mage
  (DIFFER) and Taric tank -> tank (same): **5 of 6**, as filed. The table's own `patch` field is
  `16.12.1` (file last changed 2026-06-17) while DS serves `16.22.1`, so the rewind-WIN anchors are
  ten patches old; any future flip should rebuild the table first. Still headless code work, not a
  game. Idle: `/api/state` `mode_key` `client`, `liveclient` empty, LCU phase None at 2026-11-10
  00:49 local; no game.
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
  **AGE RE-CHECK 2026-11-09 (lane 9 s144 cycle 138, read at `65c451b5a`; NOT a tick).** The
  measurement and the REMAINS line hold; every chain cite moved. (1) RE-MEASURED in-process (compute
  half only, the same headless class as the 2026-07-18 close, not live evidence): DS snapshot
  `16.22.1`, ENGINE `1.291.0`, `hybrid.rank_items_by_hybrid` at the row's own inputs (items
  `[3078,3053,3742]`, L13, mode ARAM, top_n 200) returns **pool=111 exact** ON and OFF; Yasuo DIFFERS
  (ON floats `6665` + `3091`), Darius DIFFERS (`6631`, `6333`, `4401`), Udyr DIFFERS (`6665`, `3065`,
  `3075`); Garen / Sett / Illaoi / Aatrox / Olaf / Trundle byte-identical - the filed partition and
  floated ids, unchanged. (2) STILL DEFAULT-OFF at every layer (`inspect.signature`):
  `dispatch_for_coach` (23 params), `rank_for_primary_archetype` (47), `rank_bruiser_for` (52) and
  `hybrid.rank_items_by_hybrid` all default `prefer_survivability_by_win=False`, and `git grep`
  finds the key under no file in `coaches/`, so the flip has NOT landed. (3) CHAIN, by symbol (the
  filed `aram_coach.py:784` now lands in `_update_vision_cadence`): `coaches/aram_coach.py:1112` (the
  `_ds_dispatch_for_coach(...)` call, key absent) -> `coach_integration/archetype_dispatch.py:289`
  `dispatch_for_coach` (param `:313`, `seams` entry `:441-442`) -> `core/daemon_slayer_client.py:2995`
  `rank_for_primary_archetype` (param `:3037`; bruiser branch `:3212`) -> `rank_bruiser_for` `:1514`
  (param `:1535`, body key `:1638-1639`) -> `/rank-bruiser` (`agents/daemon_slayer/server.py:3239`)
  -> `_route_rank_bruiser` `:1651` (parsed per request `:1738`, call `:1788`, kwarg `:1825`) ->
  `hybrid.rank_items_by_hybrid` `:938` (param `:977`, resolve `:1274`). The same key also feeds RF3
  (`_route_rank_tank` `:1299`) and RF2 (`_route_rank_enchanter` `:3097`), so a dispatcher-level
  default flip flips all three rows (G3-05 / G3-06 / G3-07) at once. (4) ONE NEW REACH PATH since the
  close: `dashboard/routes_state.py:969` `_DS_PREVIEW_SEAM_BOOLS` lets an `/api/ds-preview` body opt in
  (forwarded at `:1053`), but no file under `web/` sends the key, so no on-screen surface reaches it
  either. (5) RESTART NOTE, not a correction: `/rank-bruiser` already parses the key per request, so
  a flip made at the RC caller (the row's "1-line caller default") needs an RC reload, which since the
  2026-10-31 launcher cutover means an rc-shell relaunch (no task starts RC); the DS `:8860` restart
  is owed only if the flip is made in the engine defaults instead. Idle this cycle: `:8888` curl
  empty at 2026-11-09 09:43 local; no game.
- **G3-06** (was C6) RF2 enchanter survivability flip - **EYEBALL CLOSED 2026-07-18.** MEASURED at
  `[3853,3504,6617]`, L13, **pool=8 exact**, and all three of the row's own predictions reproduce
  INCLUDING the negative: **Rakan DIFFERS** - ON floats `2051` Guardian's Horn + `3083` Warmog's Armor
  + `3084` Heartsteel (the row predicted Warmog's/Heartsteel); **Soraka / Janna / Lulu / Nami / Karma
  byte-identical** (the row predicted Soraka/Janna). Depth attack at `[]` (pool=10) returns the
  identical partition and identical floated ids. The row's SIBLING-FUTURE negative also reproduces:
  `3121` Fimbulwinter is NOT surfaced on the hps lane, and the row itself scopes that `inject_ids`
  work as a headless slice, not a gate.
  REMAINS (not a gate): the operator-gated default-ON flip + DS `:8860` restart, per FOUR RULES rule 2.
  **AGE RE-CHECK 2026-11-09 (lane 9 s144 cycle 139, read at `bcdee4eec`; NOT a tick).** The
  measurement and the REMAINS line hold. (1) RE-MEASURED in-process (compute half only, the same
  headless class as the 2026-07-18 close, not live evidence): DS snapshot `16.22.1`, ENGINE
  `1.291.0`, `hps.rank_items_by_hps` at the row's own inputs (items `[3853,3504,6617]`, L13, mode
  ARAM, top_n 200) evaluates **pool=8 exact** OFF; Rakan DIFFERS (ON floats `2051` + `3083` + `3084`
  to ranks 1-3); Soraka / Janna / Lulu / Nami / Karma byte-identical. Depth `[]` evaluates pool=10
  with the identical partition and floated ids; Rakan's three floats also hold at L6 and L18; `3121`
  Fimbulwinter is surfaced neither OFF nor ON. READING NOTE, not a correction: "pool" is the OFF
  `candidates_evaluated`; ON evaluates 11 (depth `[]`: 13) for Rakan only, because RF2 INJECTS the
  three HP items into the pool before floating them (`hps.py:1008-1018`, unlike the RF1 hybrid lane,
  which only re-orders), so the ON count is pool + injected, not a different pool. (2) STILL
  DEFAULT-OFF at every layer (`inspect.signature`): `dispatch_for_coach` (23 params),
  `rank_for_primary_archetype` (47), `rank_enchanter_for` (16) and `hps.rank_items_by_hps` all
  default `prefer_survivability_by_win=False`, and `git grep` finds the key under no file in
  `coaches/` or `web/`, so the flip has NOT landed. (3) CHAIN, by symbol (the row filed none):
  `coaches/aram_coach.py:1112` (the `_ds_dispatch_for_coach(...)` call, key absent) ->
  `coach_integration/archetype_dispatch.py:289` `dispatch_for_coach` (param `:313`, `seams` entry
  `:441-442`) -> `core/daemon_slayer_client.py:2995` `rank_for_primary_archetype` (param `:3037`;
  enchanter branch `:3354`) -> `rank_enchanter_for` `:2353` (param `:2368`, body key `:2401-2402`)
  -> `/rank-enchanter` (`agents/daemon_slayer/server.py:3246`) -> `_route_rank_enchanter` `:3063`
  (parsed per request `:3097`, kwarg `:3115`) -> `hps.rank_items_by_hps` `:904` (param `:921`,
  resolve `:1012-1015`). G3-05's dispatcher-level note applies here unchanged: one default flip at
  `dispatch_for_coach` flips G3-05 / G3-06 / G3-07 together, and the `/api/ds-preview` opt-in
  (`dashboard/routes_state.py:969` `_DS_PREVIEW_SEAM_BOOLS`, forwarded at `:1053`) has no `web/`
  sender. Idle this cycle: `:8888` and `:2999` curl status `000` at 2026-11-09 10:14 local; no game.
- **G3-07** (was C7) RF3+RF6 tank survivability flip - **EYEBALL CLOSED 2026-07-18, on the EMPTY-DEPTH
  run and ONLY on that run.** THE RUN THAT CLOSES THIS ROW: depth `[]`, **pool=121**, KSante ON top-6 =
  `['6662','3075','3143','3083','6665','2504']` - Iceborn Gauntlet 6662 **and** Thornmail 3075 - so the
  row's full "Thornmail/Iceborn" prediction holds. A first-filed run at depth `[3068,3075,3143]`, L13,
  pool=117 showed KSante floating 6662 to rank 1 and **Rell floating 3121 Fimbulwinter to rank 1** with
  Malphite / Ornn / Sion / Zac byte-identical - but that depth ALREADY OWNS Thornmail 3075, which made
  3075 structurally unrankable and left half the row's own prediction unobservable. **That first
  evidence was INSUFFICIENT as filed and must not be cited alone.** RF6 rides the SAME flip as RF3.
  REMAINS (not a gate): the operator-gated default-ON flip + DS `:8860` restart, per FOUR RULES rule 2.
  **AGE RE-CHECK 2026-11-09 (lane 9 s144 cycle 140, read at `0a7552d7d`; NOT a tick).** The closing
  run and the REMAINS line hold. (1) RE-MEASURED in-process (compute half only, the same headless
  class as the 2026-07-18 close, not live evidence): DS snapshot `16.22.1`, ENGINE `1.291.0`,
  `ehp.rank_items_by_ehp` at depth `[]`, L13, mode ARAM, top_n 200 evaluates **pool=121** OFF and ON
  for KSante, whose ON top-6 is `['6662','3075','3143','3083','6665','2504']` - byte-identical to the
  filed closing run, Iceborn Gauntlet 6662 AND Thornmail 3075; Rell floats `3121` Fimbulwinter to
  rank 1; Malphite / Ornn / Sion / Zac byte-identical. The partition holds at L6 and L18 (KSante
  floats 6662 + 3075 into the top 2 at both; Rell floats 3121 to rank 1 at both). RF6 visible in the
  counts: Rell alone evaluates pool + 1 ON (122), because RF6 INJECTS the non-purchasable 3121 past
  the purchasable gate (`ehp.py:3725` `inject_ids=`), while KSante's ids are already pooled and only
  float (RF3). DRIFT, not a correction of the close: the INSUFFICIENT first-filed depth
  `[3068,3075,3143]` now evaluates pool=118 (filed 117), same partition, KSante 6662 and Rell 3121 to
  rank 1. (2) STILL DEFAULT-OFF at every layer (`inspect.signature`): `dispatch_for_coach` (23
  params), `rank_for_primary_archetype` (47), `rank_tank_for` (52) and `ehp.rank_items_by_ehp` (57)
  all default `prefer_survivability_by_win=False`, and `git grep` finds the key under no file in
  `coaches/` or `web/`, so the flip has NOT landed. (3) CHAIN, by symbol (the row filed none):
  `coaches/aram_coach.py:1112` (the `_ds_dispatch_for_coach(...)` call, key absent) ->
  `coach_integration/archetype_dispatch.py:289` `dispatch_for_coach` (param `:313`, `seams` entry
  `:441-442`) -> `core/daemon_slayer_client.py:2995` `rank_for_primary_archetype` (param `:3037`;
  tank branch `:3167`) -> `rank_tank_for` `:907` (param `:922`, body key `:1056-1057`) ->
  `/rank-tank` (`agents/daemon_slayer/server.py:3237`) -> `_route_rank_tank` `:1202` (parsed per
  request `:1299`, kwarg `:1483`) -> `ehp.rank_items_by_ehp` `:3194` (param `:3227`, resolve
  `:3474-3478` via `survivability_item_ids_tank`, inject `:3725`). G3-05's dispatcher-level note
  applies unchanged: one default flip at `dispatch_for_coach` flips G3-05 / G3-06 / G3-07 together,
  and the `/api/ds-preview` opt-in (`dashboard/routes_state.py:969` `_DS_PREVIEW_SEAM_BOOLS`,
  forwarded at `:1053`) has no `web/` sender. Idle this cycle: `:8888` and `:2999` curl status `000`
  at 2026-11-09 10:44 local; no game.
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
  **AGE RE-CHECK 2026-11-09 (lane 9 s144 cycle 141, S144-G-128; NOT a tick).** The verdict holds, but
  the row's DECISIVE CONTROL IS GONE and two cites drifted. (1) RE-MEASURED in-process (compute half
  only): DS snapshot `16.22.1`, ENGINE `1.291.0`, call shape `rank_items_by_hybrid` /
  `rank_items_by_ehp`, `"Malphite"`, L13, `current_item_ids=[]`, `only_item_ids=[<id>]`, top_n 200.
  223069 is still 6000g, `purchasable: True`, `maps {'11':False,'12':True,'22':False,'30':True,
  '453':False}` (key `21` gone, `453` new) and still returns **0 rows in ARAM on both scorers**.
  (2) CONTROL DRIFT: the filed `mode="ARENA"` control now ALSO returns **0 rows** on both scorers,
  because RM-513 (2026-10-03) added `rank._ARENA_EXCLUDED_ITEM_IDS` (`agents/daemon_slayer/rank.py:278`,
  gate `:814`) - Void Immolation is an augment REWARD in Arena too. The ARAM-vs-ARENA comparison no
  longer separates a deny from a probe artifact. REPLACEMENT CONTROL (counterfactual, same call
  shape): with `rank._ARAM_EXCLUDED_ITEM_IDS` and `rank._ARENA_EXCLUDED_ITEM_IDS` both emptied
  in-process, 223069 returns **1 row** in ARAM and in ARENA on both scorers, and still 0 in SR
  (maps `11` False). So the ARAM 0 is the deny, not the probe. (3) CITE DRIFT: the deny is no longer
  at `rank.py:196` / `:190`; it is `_ARAM_EXCLUDED_ITEM_IDS` at `rank.py:267` (entry `:268`), applied in
  `_filter_candidates` at `:811` before the inject force-admit. The set now holds a SECOND id, 226668
  Ultra Hydra (6000g, maps `12` only, a Mayhem augment reward, NEW 16.17.1): 0 rows ARAM as shipped,
  1 row with the set emptied. Guards are under `agents/daemon_slayer/tests/`
  (`test_aram_mega_item_exclusion_1618.py`, `test_arena_augment_reward_exclusion_rm513.py`), not
  `tests/`. (4) CEILING SWEEP, `rank_items_by_hybrid` ARAM Malphite L13 depth `[]` `cost_ceiling=`:
  1000 -> 15, 2500 -> **34** (filed 33), 3500 -> 121, 99999 -> 121, None -> 121; the pool still tops
  out at 3500g (Infinity Edge 3031 / Rabadon's 3089). The pool is champion-dependent (Lux reads 122 at
  3500 / 99999), so quote the champion with the count. "No ARAM mega-item" still holds for the SHOP
  pool. The row stays CLOSED-STALE-PREMISE with NO LIVE RESIDUAL. Idle: `/api/state` `mode_key`
  `client`, `liveclient` `{}`, `:2999` curl status `000` at 2026-11-09 22:21 local; no game.
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
  **AGE RE-CHECK 2026-11-09 (lane 9 s144 cycle 142, S144-G-129; NOT a tick).** The verdict holds;
  the cites drifted. (1) STILL UNREACHABLE: in tracked code `enemy_lethality` appears only in
  `agents/daemon_slayer/ehp.py` (now `:1407`, `:1667`, `:2311`, `:2725`, `:2729`, `:2835`, `:2898`,
  `:2910`), its DS tests, and `tests/test_ds_parity_map.py:90`, which now MACHINE-GUARDS the gap: the
  `/ehp` entry of `_UNREACHABLE_OK` lists `enemy_lethality`, `enemy_armor_pen_pct`,
  `enemy_magic_pen_flat`, `enemy_magic_pen_pct` and `enemy_shred_pct` as kwargs the route does NOT
  parse. Zero hits in `agents/daemon_slayer/server.py` or `core/daemon_slayer_client.py`. (2) LEXICAL
  NEAR-MISS, not a plumbing: `core/build_planner/situational.py` `enemy_pen` (`:139`, set `:535-543`
  from an enemy pen-item count) feeds the build-plan counter chips (C4, row G4-16) and never calls
  `compute_ehp` (`:477`); it does not reach this seam. (3) SHAPE RE-MEASURED in-process (compute half
  only), DS snapshot `16.22.1`, ENGINE `1.291.0`, call shape `compute_ehp(snap, "Aatrox", level=L)`
  vs the same plus `enemy_lethality=20.0, enemy_armor_pen_pct=0.35` (no items, default mode, default
  shares): L11 physical 2972.6 -> 2179.7 (-26.7%), magical 2475.3 -> 2475.3 (+0.0%), blended
  2724.0 -> 2327.5 (-14.6%); L18 physical 5683.2 -> 4082.3 (-28.2%), magical +0.0%. Physical falls,
  magical is unmoved - the filed shape. The magnitudes differ from the filed -42% because the filed
  call shape was never stated; do not compare the two. (4) SOURCE CITE DRIFT: `BACKLOG.md:32` is now
  an unrelated RM-2071..RM-2075 block and BACKLOG.md no longer mentions T1-F3 (`git log -S"T1-F3"
  -- BACKLOG.md`: last change `03ac01b4a`, "mdclean C3"); the shipped seam is LEDGER item 371.
  Still NO LIVE RESIDUAL until `/ehp` (or an RC caller) passes the pen kwargs. Idle: `/api/state`
  `mode_key` `client`, `liveclient` empty, LCU phase None at 2026-11-09 23:20 local; no game.
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
  **PREP 2026-10-24 (lane 9 s133 cycle 3, measured at HEAD `0ab6d07e6`; NOT a tick).** Correction (a)
  STILL HOLDS: `assume_ally_detonation` appears only in `agents/daemon_slayer/burst.py`, `dps.py` and
  `_ally_detonation_overrides.py` - no DS route, no `core/` / `coaches/` / `dashboard/` caller - so a
  live game still exercises nothing. Correction (b) re-measured: DS serves patch 16.21.1 (engine
  1.290.0), the override note still cites 16.13.1, and
  `data/daemon_slayer/16.21.1/champion_abilities.json` `Leona.P` carries the SAME "32 : 151 ...
  2.5 seconds" text. That is NOT a fresh confirmation: this is the Meraki-sourced ability file, frozen at
  content 25.15 (CLAUDE.md Settled, RM-808). NO DRAIN PATH EVEN AFTER PLUMBING: no RC surface records a
  mark being consumed (INFERENCE, not probed in a game: the Live Client `eventdata` feed lists
  kill / objective / multikill events, no per-hit or mark event), so "how often do allies consume
  Sunlight" has no known probe. Telemetry, not a game, is the missing piece - check the live
  `eventdata` list once in any game before trusting this.
  **AGE RE-CHECK 2026-11-10 (lane 9 s144 cycle 143, S144-G-130, source read at `a87161a42`; NOT a
  tick).** The verdict holds; one more source checked. (1) STILL UNREACHABLE: in tracked non-test code
  `assume_ally_detonation` appears only in `agents/daemon_slayer/burst.py` (`:534` kwarg, `:1261`
  gate), `dps.py` (`:791` kwarg, `:1933` gate) and `_ally_detonation_overrides.py`; zero hits for
  `detonation` in `agents/daemon_slayer/server.py` or `core/daemon_slayer_client.py`. The gap is now
  MACHINE-GUARDED: `tests/test_ds_parity_map.py` `_UNREACHABLE_OK` lists `assume_ally_detonation` under
  both `/burst` (`:88`) and `/dps` (`:89`) as a kwarg the route does NOT parse. A live game still
  exercises nothing. (2) MATH REPRODUCES BYTE-EXACT at DS snapshot `16.22.1`, ENGINE `1.291.0`
  (`/health` agreed), compute half only, call shape `compute_burst_damage(snap, "Leona", L,
  item_ids=[3068, 3075], mode="ARAM")` vs the same plus `assume_ally_detonation=True` (default target
  resists): L1 123.500 -> 138.700 (+15.200), L6 435.765 -> 467.590 (+31.825), L13 708.415 ->
  763.515 (+55.100, +7.8%), L18 966.150 -> 1037.875 (+71.725) - every filed 2-dp number (the filed
  +31.82 / +71.73 are float renderings of the 3-dp deltas). Scope still ONE champion:
  `_CHAMPION_DETONATION_OVERRIDES` = `['Leona']`, `_ITEM_DETONATION_OVERRIDES` and
  `_NONFIT_DETONATION_CANDIDATES` empty; Braum / Nautilus / Thresh / Sett delta 0.0 at L13 under the
  flag. (3) CORRECTION (b) STILL OPEN AND NOT CLOSABLE FROM LOCAL DATA: the entry note
  (`_ally_detonation_overrides.py:122-123`) still cites `champion_abilities.json 16.13.1`; the 16.22.1
  file's `Leona.P` text is unchanged ("2.5 seconds ... 32 : 151 (based on level)") but that file's own
  header reads `meraki_content_patch` `25.15`, so it is the frozen Meraki copy, not a fresh read. The
  two per-patch tie-breakers (CLAUDE.md Settled, RM-808) are silent on it: `cdragon_spell_stats.json`
  (`champions.Leona.spells`) and `cdragon_ability_ratios.json` (`champions.Leona`) hold only `E` /
  `Q` / `R` / `W`, no `P` key, and `wiki_ability_stats.json`
  `Leona/Sunlight` carries only `apiname` / `slot` / `spellshield`, no damage line. So no local source
  confirms 32 : 151 at the live patch; re-anchoring the note to 16.22.1 would launder the Meraki copy
  into a fresh claim. The re-anchor is an engine-data edit (`agents/daemon_slayer/`, DS lane), not this
  doc's. (4) The live residual (how often allies consume the mark) still has no probe; the `eventdata`
  check above is unchanged. Idle: `/api/state` `mode_key` `client`, `liveclient` empty, LCU phase
  None at 2026-11-10 00:19 local; no game.
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
  **READY (lane 9 PREP s144 cycle 115, source read at `a2abb3bb7`; NOT a tick).** AGE re-check, and the
  2026-08-02 PREP is NARROWER than the truth in one place. HOLDS: `/api/state` still carries no cc field
  (`cc_blended` appears in neither `dashboard/_state_builder.py` nor `dashboard/routes_state.py`; pinned by
  `tests/test_gated_g311_cc_blended_chip.py` `test_state_payload_still_carries_no_cc_blended_field`), and
  the coach consumer `core/cc_blended_ehp_context.py` `cc_blended_ehp_impact_line` (called from
  `coaches/aram_coach.py`) is a Haiku PROMPT line, never drawn as such - so the in-game ARAM half still
  needs the wiring above. MISSED: a RENDERED cc_blended_ehp surface has existed since 2026-05-22
  (`ae6deb5e0`, item 139 carry (a)): the champ-select threat chip `#csv-sugg-cc-blended-ehp-threat`
  (renderer `web/js/panels/cc_blended_ehp_threat.js` `renderCcBlendedEhpThreat`, gate
  `web/js/panels/champ_select.js` `_csvRenderCcBlendedEhpThreat`, compute `GET /api/cc-blended-ehp-threat`),
  inside the TEAM ANALYSIS drawer beside the G1-03 conditional chip. It is mode-agnostic in its route
  (SR / ARAM / KIWI / ARENA) but its gate hides it while `their_team` is empty, so it is HIDDEN in blind
  ARAM / Mayhem select (LCU behaviour, not proven in source) and this gate cannot drain it: it drains in
  a DRAFT lobby (q400 / q420, GATE 1), in the same capture as G1-03, and it has no other row in this doc.
  It carries all four G1-03 traps: static `data-cc-tier="warn"` in `web/index.html`, the collapsed
  `#csv-ta-body` drawer, `[hidden]` not being the visibility truth, and the unchanged-signature early
  return in `renderCcBlendedEhpThreat` after the gate's direct hide (reproduced under node by the test
  `test_stale_signature_trap_still_exists`).
  **CHECK (any DRAFT champ select once one enemy pick is visible), predicate stated first:** PASS iff
  `lcu.champ_select.their_team[]` and `my_team[]` each hold a `championId > 0` on `/api/state`, the chip has
  a rendered on-screen box (drawer open), its tier is good / warn / bad with the matching label
  (FAVORABLE / EVEN / AT RISK), both rows read `<n>.<n>s` with an integer EHP caption ("(your EHP n)" on
  "Enemy can chain on you", "(enemy EHP n)" on "You can chain on them"), a verdict line is present, AND
  the page's own last `/api/cc-blended-ehp-threat` URL is for THIS roster by names and mode with the
  rendered tier, seconds (0.05 tolerance) and EHP integers (JS half-up rounding) equal to that URL's body.
  FAIL = chip missing from the DOM, populated but malformed, populated with an open drawer and no box, or
  hidden on a page reloaded 10 to 90 s earlier in this lobby with a visible tab and an ok body for this
  roster. Anything else (blind select, collapsed drawer, render lag, no route fetch seen) = INCONCLUSIVE.
  **PROBE (read-only):** `python tools/gated_g311_cc_blended_chip.py snippet` prints an async expression;
  run it in the real dashboard tab (operator Chrome DevTools console, or headless Chromium against the
  live :8888 - record which), save the JSON, then `python tools/gated_g311_cc_blended_chip.py grade
  --evidence <file>` (exit 0 PASS / 1 FAIL / 3 INCONCLUSIVE / 2 unreadable). The bundle keeps only phase,
  queue id and champion ids - no puuid, no player name (RM-906).
  **EVIDENCE CONTRACT:** value = tier, both chain seconds, both EHP captions; source = the chip DOM plus
  the page's own route URL and its re-fetched body; timestamp = `captured_at` plus phase and queue id;
  predicate = the CHECK above. **SUBSTITUTION:** a GET of `/api/cc-blended-ehp-threat`, the coach prompt
  line, a `?ui_mock=1` fixture page, or this file's tests (which reach PASS from hand-built bundles) are
  the COMPUTE half only - never tick from them. A live PASS would discharge only the champ-select RENDER half; the
  in-game ARAM residual stays "wire a cc panel into `/api/state`" (headless code, not a game).
- **G3-12** (was C14) `RC_ARAM_STATE_DEBOUNCE` DEFAULT-ON flip validation. **DO NOT close on the OFF
  observation.** The coach refreshed coherently with the flag OFF twice (2026-07-04 6+ min; LEDGER 820
  2026-07-08 "debounce OFF, coach refreshes coherently") - the LEDGER 820 headline reads "C14
  live-verified" but its body records the OFF case only. The DEFAULT-ON flip is still un-validated. A
  replayed-game feed is an allowed alternative - try headless first. SOURCE: BACKLOG.md:64.
  **PREP 2026-10-24 (lane 9 s133 cycle 3, measured at HEAD `0ab6d07e6`; NOT a tick).**
  (1) CITE DRIFT: `BACKLOG.md` no longer carries this row (no "same-state" / `STATE_DEBOUNCE` line
  left); the origin record is LEDGER 506 (ARAM seam) + 507 (Arena sibling).
  (2) PRECONDITION, NOT A LANE ACT: the default is still OFF - `coaches/aram_coach.py:62` reads
  `os.getenv("RC_ARAM_STATE_DEBOUNCE", "0") == "1"` ONCE at import, the variable is unset at both User
  and Machine scope, and no launcher under `ops/` / `scripts/` sets it. So no game drains this row until
  RC is restarted with the flag ON (or the default flipped) - an operator / merger act, never the
  watcher's. `config/feature_flags.json` has `aram.live_coaching = allow` (the `_run_coach` gate at
  `:870` passes).
  (3) The REPLAY alternative has NO INPUT today: `tools/aram_raw_replay.py` reads the `ARAM Haiku raw`
  log lines (written at `:1119`), and none of the 15 retained day logs (`logs/2026-10-10.log` onward)
  carries one. Only a fresh ARAM game produces replay input.
  CHECK, predicate stated before any look. PROOF THE FLAG IS ON in the process: at least one
  `ARAM state-debounce: signature unchanged` line in `logs/<date>.log` during the game (`:1082`; it
  is `logger.debug`, and the file handler is always DEBUG, `core/log_setup.py:161`). Zero such lines
  = INCONCLUSIVE (the seam did not run), never a pass. PASS iff, in one ARAM / Mayhem game of 8+ min
  game_time with that proof, sampled every 20-30 s while alive: `data/aram_coaching_data.json`
  `game_time_s` (written at `:1206`) never trails `/api/state` -> `liveclient.game_time_s` (the field
  `tools/gated_live_probe.py:210` reads) by more than 90 s. Bound: the signature carries a 30 s
  game-time band (`:117`), so a re-call is forced within one band plus one 25 s stable poll, plus Haiku
  latency (20 s timeout, stamp taken after the call at `:1254`); the 45 s ceiling is NOT the binding
  term in a live game, so this predicate cannot isolate the ceiling (that half stays on
  `tests/test_aram_state_debounce.py`, past-ceiling case). A skip returns before `safe_write`, so a
  frozen file means no Haiku refresh landed. FAIL only if a lag over 90 s while alive has NO Haiku
  error, budget-gate or kill-switch log line in its window; with one, the sample is INCONCLUSIVE.
  The coherence half stays an operator eyeball. (Adversarial pass 2026-10-24 corrected a first draft
  that bounded the lag on the 45 s ceiling.)
  **TOOL 2026-11-04 (lane 9 s144 cycle 54, source read at `d3bc4ce4c`; NOT a tick).** The CHECK above
  is now one command per half: NEW read-only `tools/gated_g312_aram_debounce_lag.py` (tests
  `tests/test_gated_g312_aram_debounce_lag.py`), the ARAM twin of the G5-06 tool
  `tools/gated_g506_debounce_lag.py`. It imports that tool's mode-neutral pieces and differs only in
  the mode (`mode_key` and trace `mode` both `aram`), the coach file, the three log strings and the
  90 s bound. The G5-06 tool-side preconditions apply unchanged, and each can only turn a PASS into
  INCONCLUSIVE: the required `--since` / `--until` window holds the WHOLE game (first known
  `liveclient.game_time_s` at most 60 s, a clean game-over poll within 35 s of the last known
  sample); known samples (alive, or dead: `hp == 0` with `hp_max > 0`) tile it with no gap over
  35 s; a dead run over 120 s, or a coach file AHEAD of the live clock by over 30 s (another game's
  file), is INCONCLUSIVE.
  (1) CITE DRIFT, line numbers only, behaviour unchanged, `coaches/aram_coach.py` at `d3bc4ce4c`:
  flag read `:61` (was `:62`), the 30 s band `time_band` `:116` (was `:117`), the
  `@safe_coach_output("ARAM")` decorator `:1004` with the `aram.live_coaching` gate `:1008` (was
  `:870`), the debounce log call `:1219-1223` (was `:1082`), the Haiku `timeout=20` `:1246`, the
  `ARAM Haiku raw` log `:1257` (was `:1119`), the `ARAM: no fields parsed` return `:1268`, the
  `game_time_s` write `:1344` (was `:1206`, the DISPATCH state's `game_seconds`), the `safe_write`
  `:1383`, the ceiling stamp `:1390-1393` (was `:1254`). `tools/gated_live_probe.py:210` and
  `core/log_setup.py:161` hold. The test pins the strings and the bound's premises (30 s band,
  25 s `_STABLE_DEBOUNCE_S`, 45 s ceiling, `timeout = 20`, the `aram` trace mode) against the
  source, not line numbers.
  (2) THE 90 s BOUND RE-DERIVED: it holds, but NARROWLY, with about 2 s of margin in the worst
  case (verifier pass 1 of this cycle refuted a first draft that claimed 16 s by ignoring the 5 s
  fast path, the 12 s reactive debounce and the 12 s snapshot age). The file's `game_time_s` is
  the DISPATCH state's game time g0. Once the game clock leaves g0's band (at most g0 + 30 s), the
  next dispatch re-calls whatever the ceiling says. A stable board dispatches every 25 s
  (`_last_coach` is set at dispatch even for a run that then skips, `coaches/_base_coach.py:579`),
  the poll ticks every 1.5 s (`:426`), a Haiku attempt times out at 20 s, and the coach accepts a
  Live Client snapshot up to 12 s old (`:703`), so a dispatch can still read the old band. Worst
  case with single-attempt calls and no slow tick: a call landing at about g0 + 88 s. So every
  delay outside that budget EXCUSES a lag over 90 s instead of failing it: a
  `data/coach_tick_trace.jsonl` `mode=aram` `phase=coach` record over 20000 `dur_ms` (an SDK
  retry, which logs nothing; `coaches/_base_coach.py:669`, always traced, `ts` is the record's
  END), any other `aram` trace phase (`parse` / `on_state` / `tick` / `shadow`, `:446-474` and
  `:587-588`, written over 150 ms) over 1000 `dur_ms` (2000 in cycle 54; lowered by RM-1345,
  below), or a failed coach-file write (`safe_write
  aram_coaching_data.json: ...`, `:100` / `:117`; the ceiling stamp at `:1390` is taken anyway, so
  the next same-band dispatch skips). The non-coach threshold can only turn a FAIL into an
  INCONCLUSIVE.
  SAMPLING RESOLUTION: only the sampled points are graded, so with 25 s polls a true peak up to
  about one interval above 90 s can fall between two samples. A PASS means "no SAMPLED lag over
  90 s", not "the lag never crossed 90 s".
  FALSE-FAIL RESIDUALS, FIXED 2026-11-04 (lane 9 s144 cycle 55, RM-1345, read at `16c48a7cf`; NOT
  a tick). Verifier pass 2 of cycle 54 found two: the poll period is the tick time PLUS the 1.5 s
  sleep (`coaches/_base_coach.py:421-426`), so an unexcused tick under the old 2000 ms threshold
  could push the worst case to about 90.5 s; and the sampler's `/api/state` GET (8 s timeout) runs
  after the coach-file read, so a slow GET adds straight to the measured lag. Fix, in both this
  tool and its G5-06 twin: (a) the non-coach `aram` phase threshold `SLOW_OTHER_MS` is now 1000 ms
  (worst case near 89.5 s); (b) every sample line records `get_s`, the sampler's own monotonic span
  from the coach-file read to the end of the GET; (c) grade keeps an otherwise unexcused lag over
  the bound INCONCLUSIVE, never FAIL, when `lag_s - get_s` is within the bound or the line carries
  no `get_s` (a sample file from the cycle 54 sampler). The 10 s read-as-INCONCLUSIVE rule of
  cycle 54 is retired; a FAIL now means the lag stayed over 90 s after the GET span is discounted.
  (3) CORRECTION TO THE CHECK's FAIL CLAUSE. It names a "budget-gate or kill-switch log line", but
  both gates (`coaches/_base_coach.py:535` / `:547`) and the feature-policy gate (`coaches/aram_coach.py:1008`) return
  SILENTLY, so no such line can exist and a budget-exhausted game would grade FAIL. The tool
  therefore grades an unexcused lag over 90 s FAIL only with `--budget-ok` (the operator asserts the
  daily budget was not exhausted, `aram` was not kill-switched and `aram.live_coaching` was allowed)
  AND a readable `--trace` file; otherwise INCONCLUSIVE. The feature-policy gate also writes a
  disabled placeholder with no `game_time_s`, so its samples read as unknown (a coverage hole), and
  a missing Anthropic client (`coaches/aram_coach.py:1013`, silent) returns before the debounce
  block, so no proof line exists and the game grades INCONCLUSIVE. Log excuses in the `lag_s`
  seconds before the sample: `ARAM coach error` (`core/safe_coach_output.py:35`), `ARAM: no fields
  parsed`, and the failed-write line in (2).
  (4) LIVE HALF, during the ARAM / Mayhem game, from the main checkout, RC started with
  `RC_ARAM_STATE_DEBOUNCE=1` (still unset at User and Machine scope, read 2026-11-04; the
  precondition stays a merger / operator act):
  `python tools/gated_g312_aram_debounce_lag.py sample --interval 25 > <scratch>/g312.jsonl`,
  started before the game clock starts, stopped with Ctrl-C after the game ends. Each poll reads
  `data/aram_coaching_data.json` -> `game_time_s` FIRST, then `/api/state` -> `mode_key`,
  `liveclient.game_time_s`, `liveclient.hp`, `liveclient.hp_max` (`dashboard/_liveclient.py:308`,
  `:327-328`), so a slow GET can only make the measured lag larger; each line also records that
  read-to-GET span as `get_s` (RM-1345), which grade discounts.
  (5) GRADE HALF, after the game: `python tools/gated_g312_aram_debounce_lag.py grade --samples
  <scratch>/g312.jsonl --log logs/<date>.log --since <clock-start HH:MM:SS> --until <end HH:MM:SS>`
  plus `--budget-ok` only on the operator's assertion. Exit 0 PASS, 1 INCONCLUSIVE / NO_RESULT,
  2 FAIL.
  (6) EVIDENCE CONTRACT for the tick: the grade output's max lag (value), the sample file plus the
  field paths above (source), the sample wall times with mode ARAM or Mayhem (queue 2400, KIWI) and
  the game time span (timestamp + context), and the predicate in the CHECK above as corrected in (3).
  SUBSTITUTION CHECK: `tests/test_aram_state_debounce.py` proves the skip FIRES on an unchanged
  signature (compute); only the sampled pair says whether the SERVED file kept pace with the game
  clock. Samples taken with the flag OFF are caught by the zero-proof-line rule (INCONCLUSIVE), and
  an Arena game's samples, proof lines or trace rows are not counted. Idle smoke 2026-11-04 20:19
  local: the dashboard was down, so `sample` read a `URLError` poll (the coach file still held an
  older game's `game_time_s`), and `grade` returned NO_RESULT, exit 1.
  **AGE RE-CHECK 2026-11-08 (lane 9 s144 cycle 116, read at `edeed0091`; NOT a tick).** The CHECK,
  the 90 s bound and the tool stand; two corrections. (1) BEHAVIOUR UNCHANGED since cycle 54:
  `coaches/aram_coach.py` took about 780 churned lines after `d3bc4ce4c`, but on the debounce path
  the only change is RM-1541 (`a2503f89e`), which removed a `try:` / `except Exception:` / `raise`
  wrapper around `_run_coach`'s body and re-indented it (the two diff sides of that file, stripped of
  indentation, differ by exactly those three lines; the decorator already catches). The tool's
  source pins (`tests/test_gated_g312_aram_debounce_lag.py`, 20 passed this cycle) hold.
  `coaches/_base_coach.py` changed only an append `newline=` and three dead `pass` lines; every
  `_base_coach.py` line cite in this row still holds. LINE DRIFT in `coaches/aram_coach.py`, by
  symbol: the flag read `_STATE_DEBOUNCE` is `:62` (was `:61`), the band `time_band` `:117` (was
  `:116`), the `@safe_coach_output("ARAM")` decorator on `_run_coach` `:1005` (was `:1004`), the
  silent missing-client return `if not self._client` `:1014` (was `:1013`), the feature-policy gate
  `if not _fp_ok("aram", "live_coaching")` `:1009` (was `:1008`; the `:1008` cites in the TOOL
  block and in (3) above now land on its import line); the debounce log `:1219-1223`, `timeout = 20`
  `:1246`, `:1257`, `:1268`, `:1344`, `:1383` and `:1390-1393` hold. (2) PRECONDITION ROUTE CHANGED
  by the 2026-10-31 launcher cutover (CLAUDE.md Topology): no scheduled task starts RC now, so "RC
  started with `RC_ARAM_STATE_DEBOUNCE=1`" means the variable must be in rc-shell's environment when
  it spawns `ops/launcher/service_host.py`. The services inherit it: `child_environment` in
  `ops/launcher/service_host.py` starts from `os.environ` and applies only the overrides it is given
  (the `services.json` ones - top-level `env` is `{}`, the `dev` profile overrides only
  `RC_DASH_BIND` - plus first-run provisioning secrets such as `RC_DASH_TOKEN`; none touches this
  flag), and the supervisor's RC `subprocess.Popen` in
  `ops/rc_supervisor.py` passes no `env=`, so RC inherits too. Two routes, both operator / merger
  acts, never the watcher's: set the variable at User scope and relaunch rc-shell from a process
  started after the change, or add `"RC_ARAM_STATE_DEBOUNCE": "1"` to `profiles.dev.env` in
  `ops/launcher/services.json` (a main-session path) and relaunch. Still unset at User and Machine
  scope (read 2026-11-08 about 22:40 local), so the row stays undrainable until one of those lands. The
  flag is read ONCE at import, so a running RC never picks it up; the zero-proof-line rule already
  turns a flag-OFF game into INCONCLUSIVE. Idle this cycle: `:8888` and `:2999` both curl 000
  (RC down, no game).
- **G3-13** `[UNBLOCKED 2026-10-27 by RM-860 + RM-877; was BLOCKED ON WIRING 2026-10-24]` (was
  C15+C16) Augment OCR rank-vs-pick + live on-screen render validation.
  **READY (lane 9 PREP s144 cycle 8, source read at `f073b1ca1`; NOT a tick). The blocker below is
  GONE: RM-860 shipped surface (A) (`9b51bc90f` + `32f625d4c`, LEDGER 1832) and RM-877 retired the
  Haiku fallback (`5d3d1df67`, LEDGER 1845).** What a Mayhem game now does, read at HEAD:
  `coaches/aram_coach.py` `_run_vision` latches `_augment_resolved`, counts the panel
  (`_track_augment_panel`) and calls `_handle_augment_select` BEFORE it loads the artifact (the stale
  write-back that used to clobber the stamp is fixed there); the handler ranks the offered cards with
  `_mayhem_augment_recommendation` -> `core.augment_recommender.recommend(mode="mayhem")` (only when
  `is_mayhem` on the coach's own live-client state) and writes `augment_select: true`,
  `augment_choices` and the `_AUG_RECO_KEYS` (`aug_reco`, `aug_reco_top`, `aug_reco_mode`,
  `aug_reco_stage`, ...) into `data/aram_coaching_data.json`; a scan that explicitly reports
  `augment_select: false` sets the file's flag False. `web/js/panels/augment_reco.js`
  `renderAugmentReco` (called from `web/js/main.js` on every state envelope that drives the
  panels) shows `#ib-aug-reco-block` iff
  `coach.aug_reco` is a non-empty array, headed `PICK NOW` while `augment_select === true` and
  `TOP PICK` after. An offer whose card names do not resolve (`resolve_id`, normalised exact match)
  stamps NOTHING (not even `augment_select` / `augment_choices`) and drops the previous ranking:
  the panel goes DARK and no model call is made (RM-877). A dark block while the in-game augment
  panel is up is a FAIL of this row, and only the operator's glance can record it: the artifact
  of an unresolved offer looks the same as a scan that missed the panel.
  **DRAIN CARD (one ARAM Mayhem q2400 game, from the load screen):**
  (1) `python tools/gated_g313_mayhem_aug.py --samples 45 --interval 4 > <evidence>.jsonl` from
  the repo root at the load screen (about 3 min of samples; the grade goes to stderr), then
  `python tools/gated_g313_mayhem_aug.py --grade <evidence>.jsonl`. Read-only: two local GETs
  (`/api/state`, `:8889/latest-frame/meta` over plain http with the token), no write, no game id.
  (2) PREDICATES, stated before any game (the tool's docstring is the long form): `game` PASS iff
  `mode_key` aram AND `liveclient` non-empty; `mayhem` PASS iff `liveclient.game_mode` is Mayhem
  (`core.mayhem_detect.is_mayhem`, KIWI live; the Live Client, NOT the coach file's `mayhem` key, so
  a stale artifact cannot vouch for itself); `panel` SEEN iff `coach.augment_select` true with
  non-empty `coach.augment_choices`; `reco` PASS iff an open-panel sample has non-empty
  `coach.aug_reco`, `aug_reco_mode` "mayhem" and an `aug_reco_top` whose normalised name
  (`_norm_name`) is an offered card; FAIL iff any open-panel sample's reco is another mode or names
  a card not offered (an OCR alias can trip this - eye it before filing); in a Mayhem game with no
  open-panel sample the verdict is NOT_SEEN (vision missed the panel OR its cards did not resolve
  and the block stayed dark - the glance in (3) decides, and dark on screen is a FAIL); DARK only
  for open-panel samples without a reco (a stale open flag from an earlier panel); `clear` PASS
  iff a later sample has `augment_select` not true, STUCK (FAIL) iff it stays true over 75 s of
  game time; `frame` FRESH iff 0 <= sample time minus the frame meta `ts` <= 10 s for the PASS
  sample (STALE leaves the compute verdict alone; take the glance from a fresher sample). Plain
  ARAM is the negative control: any `aug_reco` in a non-Mayhem game is a FAIL. Exit 0 = reco PASS
  and clear PASS, 1 = no game / not Mayhem / NOT_SEEN / DARK / incomplete, 2 = FAIL.
  (3) ON-SCREEN HALF (the row's actual acceptance, the operator's glance - the tool never passes
  it): while the in-game augment panel is up (about 10-15 s), the dashboard's "Augment pick" block
  shows `PICK NOW` and a top pick that is one of the three cards on screen; after the pick it
  flips to `TOP PICK` (not stuck on PICK NOW).
  **EVIDENCE CONTRACT.** Value = the PASS sample's `aug_reco_top`, `augment_choices`,
  `aug_reco_stage` (1 for the game-start panel when the coach saw it inside `_AUGMENT_WINDOW_S`
  = 45 s, None when RC started mid-game) and the operator's on-screen line; source = `/api/state` ->
  `coach.aug_reco_top` / `coach.augment_choices` / `liveclient.game_mode`, plus the dashboard block
  `#ib-aug-reco-block`; timestamp = the sample `t` + `liveclient.game_time_s`, mode KIWI, q2400;
  predicate = (2) and (3) above. **SUBSTITUTION CHECK:** the tool's PASS proves the coach COMPUTED
  and STAMPED a reco for the offered cards in the window; it does not prove the panel RENDERED it
  or that the cards on screen are the OCR's cards. Only (3), with a FRESH frame, closes the row; a
  green tool run plus a dark or wrong panel on screen is a FAIL.
  **AUTO-RELOAD VOIDS THE GLANCE (s144 gated c21, PREP; stated before any game; the G1-07 trap, swept
  here by RM-1055):** the dashboard reloads itself on any watched asset change (`web/index.html`,
  `web/css/**/*.css`, `web/js/**/*.js`) through two pollers in `web/js/main.js`: `/api/ui-version`
  (every 4 s) and the `_hotReloadInit` `/api/asset-stamp` poller (every 3 s, a 250 ms delay before the
  reload). A merger landing that writes web assets during the game can therefore blank the page inside
  the 10-15 s panel window, and the block stays dark until the first state envelope after the reload
  calls `renderAugmentReco`. That fakes a DARK glance (a false FAIL). It can also fake the flip:
  `renderAugmentReco` (`web/js/panels/augment_reco.js`) includes `augment_select` in its `_lastSig`
  repaint guard, so the cue it paints follows the payload it is handed, but whether an envelope
  reaches it at all is decided upstream in `main.js` (the `driveNow` early return before the render
  calls), and a reloaded page starts that path fresh. A `TOP PICK` seen after a reload therefore
  says nothing about whether the live page would have flipped. A `PICK NOW` glance whose top pick is
  one of the cards on screen is a real render either way. Read
  `curl -sk https://127.0.0.1:8888/api/ui-version` and `curl -sk https://127.0.0.1:8888/api/asset-stamp`
  at the load screen and again after the pick (both routes are in `dashboard/_handler.py`
  `_SUPPRESS_LOG_PATHS`, so the reads add no trace line). A changed `v`, or any change in `mtime`,
  makes a DARK or wrong glance and the whole flip half NO_RESULT (re-run on the next Mayhem game,
  never FAIL or PASS on it); a matching `PICK NOW` glance stands. Both before / after pairs go into
  the tick line.
  **SUPERSEDED HISTORY (kept as written; the blocker it describes is fixed):** **WHY THE ON-SCREEN HALF CANNOT PASS AT HEAD (lane 9 PREP s133 cycle 4,
  source read at `af8c28fc8`, independent adversarial pass CONFIRMED 9 / 9 claims; NOT a tick): the
  Mayhem augment reco has NO render surface.** KIWI maps to ARAM (`core/game_snapshot.py:118`) and one
  coach runs per mode (`core/coach_registry.py:8`, `_aram_mode` -> `coaches.aram_coach`), so
  `coaches/arena_coach.py` never runs in a Mayhem game; `/api/state` `coach` is read from
  `data/aram_coaching_data.json` (`dashboard/_state_builder.py:58`, `:546-547`).
  `coaches/aram_coach.py` `_handle_augment_select` writes only `augment_select` / `aug_take` /
  `aug_why` / `aug_plan` / `augment_choices` (`:1309-1315`) - no tracked `.js` / `.mjs` / `.html`
  (web, rc-shell, lane-widget, atlas) reads any of those five; the one augment panel,
  `web/js/panels/augment_reco.js` `renderAugmentReco`, hides unless `p.aug_reco` is a non-empty array
  (`:80-81`), and `aug_reco` is stamped only by `coaches/arena_coach.py:355-375`. The header augments
  pill is gone (`web/index.html:602-603`). So the cadence fix below can land a correct scan and a paid
  Haiku pick that nothing renders. Also measured: `augment_select` is set True at `:1310` and never
  set False within a game (a renderer keyed on it would stick on "PICK NOW"); the `_augment_resolved`
  latch stops only the fast poll (`:661-670`), the 25 s scans still reach `:791` for later picks.
  Riding more Mayhem games drains nothing on screen until **RM-860** (give the Mayhem reco a render
  surface) lands. **CHECK (after RM-860, ARAM Mayhem q2400, the game-start augment panel):** sample
  `GET https://127.0.0.1:8888/api/state` every 3-6 s from load screen to 0:45; PASS iff, while the
  in-game panel is open, the RM-860 surface renders a pick whose name is one of `coach.augment_choices`
  for that same sample and the vision frame (`:8889/latest-frame/meta` `ts` within 10 s of the sample)
  shows those cards; the `coach` keys alone are the COMPUTE half only. The alias fix
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
  `moon_proxy` every ~26s - ~~so a frozen `screen_read` is a CANDIDATE blocker for the on-screen half and
  should be checked before blaming the `66e6835e` cadence fix.~~ **STRUCK 2026-10-24 (lane 9 PREP s133
  cycle 4, adversarial pass CONFIRMED):** `screen_read` is not on this path - it is
  `data/screen_read.json` (`dashboard/_screen_read.py:37`, read at `dashboard/_state_builder.py:637`),
  nothing under `coaches/` references it, and the ARAM augment scan is the coach's own
  `GameVisionReader.read_tiered` (`coaches/aram_coach.py:776`, frame from `:8889/latest-frame`). A fresh
  `:8889` frame is still a real dependency; the real blocker is the missing render surface above (RM-860). Do NOT close this row on the data half
  alone; the operator eyeball on the ~10-15s panel is still the acceptance.
- **G3-14** (was C17) R78 ARAM deterministic tail item_extra + objective Haiku->deterministic flip
  (`8f013ee4`): SHIPPED SHADOW-only. Needs ARAM shadow accrual + operator OK before flipping the ARAM
  coach tail off Haiku. SOURCE: docs/ORCHESTRATION_PLAN.md:296.
  **ACCRUAL CAVEAT (lane 9 PREP s133 cycle 2, measured on `data/aram_coach_shadow.jsonl`; NOT a
  tick): do not read the accrual off a raw row count.** All 282 rows since `2026-08-03` are NOT ARAM
  game ticks: 282 / 282 carry `enemy_comp == []` (every earlier row with enemies lists exactly 5), `champ`
  Kai'Sa every time across 21 days, and ONE distinct `live_haiku` block across all 282 (the coach file frozen at 2026-08-02; the
  4972 earlier rows carry 2234 distinct blocks). `tools/aram_shadow_report.py` filters on neither
  field, so those rows count toward flip readiness. Filed **RM-852**; ~~until it lands, count only
  rows with a non-empty `enemy_comp`.~~ (caveat RESOLVED: RM-852 read-time exclusion + RM-859
  archive-split `c5c70beb3`, LEDGER 1846; the live file is 4585 rows, `enemy_less_excluded` 0.)
  **PREP (lane 9 s133 cycle 9, 2026-10-25, source read at `6be7956da`, data read-only in the main
  checkout; NOT a tick).** Three findings change what this row can accrue.
  (1) THE OBJECTIVE HALF HAS NO HAIKU BASELINE, EVER. The live ARAM prompt's OUTPUT FORMAT
  (`coaches/aram_coach.py:403-412`) lists Action / Fight rule / Reset / item / Risk / Item build / Item
  extra / Item reasons / Choices - no Objective - and `parse_fields` (`:1262-1266`) never asks for
  "objective", so the artifact's `"objective": flds.get("objective", "")` (`:1340`) is always "".
  Measured: 370 non-dead rows after the live-side reader fix (`e569821e1`, 2026-07-29), 6 ARAM games on
  2026-08-02 (champion + enemy comp groups; 5 champions, Aphelios twice): `objective` det-only 370, live 0. So "Haiku -> deterministic" agreement on `objective`
  can never accrue; the deterministic line ADDS a field the live coach never served. That half is a
  surfacing decision for the operator, not an accrual gate.
  (2) THE FLIP REPORT DOES NOT MEASURE EITHER R78 FIELD. `tools/aram_shadow_report.py` `_FIELDS`
  (`:56-59`) omits `item_extra` and `objective`, though both sides of every row since R78 carry them
  (3581 rows). Inline read: `item_extra` both 218 / det-only 152 over those 370 rows; equal 154 / 218 =
  0.706 case-folded (152 / 218 = 0.697 exact); the deterministic side is always "omit" (by design, `8f013ee4`), live "omit" 152. Filed
  **RM-882** (report the two fields; say "no live baseline" for `objective`, never 0 %).
  (3) THE DETERMINISTIC OBJECTIVE MAY BE READING SEED VALUES, NOT TOWERS. Over all 3581 R78 rows it took
  only two of its six branches: "Poke the enemy tower" 3562, "Enemy tower down" 18 (2026-07-11/12), ""
  1; "Defend your tower" / "Your tower fell" / "Enemy tower is low" never once. Its inputs are the
  artifact's `my_tower_hp` / `enemy_tower_hp` (`dashboard/_deterministic_coaching.py:1350-1351`), seeded
  100 / 100 by `_blank_artifact_data` (`coaches/aram_coach.py:800`) and overwritten only when the
  Sonnet vision read returns a non-null value (`:918-926`). The artifact still holds 100 / 100 from
  the 2026-08-02 game. No ARAM row since 2026-08-02T22:34Z, and `data/aram_coaching_data.json` is
  untouched since that minute too, so the silence is "no ARAM game", not a dead writer.
  **CHECK (next ARAM Mayhem game; predicate stated first).** Sample every 25-30 s while in game:
  `data/aram_coaching_data.json` (main checkout) `my_tower_hp` / `enemy_tower_hp` / `my_team`, and
  `/api/state` -> `liveclient.turret_events` (`[{down_at_s, name}]`, `dashboard/_liveclient.py` `out["turret_events"]` block; it sat at `:422-433` when this was read)
  with `liveclient.game_time_s`. WRITER ALIVE: `data/aram_coach_shadow.jsonl` gains rows with `ts` after
  the game start, `mode` `aram`, a 5-name `enemy_comp` (else FAIL: writer dead; note the line count
  before queueing). TOWER INPUT: on the first `TurretKilled`, read its `name` and decide the side from
  `my_team` (`_T1_` = ORDER, `_T2_` = CHAOS - confirm on that first event, do not assume). PASS iff
  that side's `*_tower_hp` takes at least two DIFFERENT values across the samples from 90 s before to
  60 s after that turret's `down_at_s`, at least one of them below 100 (a value CHANGE inside the
  window; a single held value is not enough, because `:918-926` keeps the last non-null read through
  every null read, so an old reading of another tower can sit there). FAIL iff `my_tower_hp` and `enemy_tower_hp` both read
  exactly 100 at every sample from 90 s before to 60 s after the kill, while the player is alive and
  the frame is fresh (`:8889/latest-frame/meta` `ts`) AND that turret is on screen BELOW FULL HP in at
  least one sampled frame (on screen at full HP, 100 is the right reading) (vision returning null for an off-screen tower is legitimate silence, not a FAIL).
  Any other outcome, a turret that never falls, a dead or tabbed-out player, or a stale frame is NO
  RESULT. Also RECORD (not a predicate): after the kill, "nearest tower"
  (`coaches/aram_coach.py:534-535`) may be the next tower at full HP, so `enemy_tower_hp` may never reach 0
  (`_TOWER_DEAD`, `core/aram_deterministic_coach.py`, `:268` when read) on most kills, though the 18 rows of
  2026-07-11/12 show it has - note which value vision reports after the kill. A FAIL files a row against the vision
  tower read; it does not touch `item_extra`. The `item_extra` half still accrues and still needs the
  operator's OK.
  **TOWER CHECK TOOL - READY (lane 9 PREP s144 cycle 56, source read at `bf3292940`; NOT a tick; it
  grades the CHECK above, so no count moves).** ONE COMMAND, read-only (it writes nothing, prints no
  path, token, game id or champion name), started once the game is past the load screen: `python
  tools/gated_g314_tower_input.py --samples 80 --interval 25 > _scratch/g314.jsonl` (about 33 min;
  Ctrl-C after the first `TurretKilled` plus 60 s ends sampling and grades what was taken; from a
  worktree the relay token comes from the main checkout's config, so the frame age is still read), then `python
  tools/gated_g314_tower_input.py --grade _scratch/g314.jsonl`. Each sample joins `/api/state` ->
  `liveclient.game_time_s` / `hp` / `turret_events`, the main checkout's `data/aram_coaching_data.json`
  (`mode`, `my_team`, `my_tower_hp`, `enemy_tower_hp`, mtime), the LAST row of
  `data/aram_coach_shadow.jsonl` (`ts`, `mode`, `enemy_comp` size) and `:8889/latest-frame/meta` `ts`.
  The grade states the CHECK's predicates as code: `writer` PASS / FAIL (no fresh 5-name ARAM shadow
  row over at least 180 s of sampled game time) / INCOMPLETE; `tower` PASS / HELD_100 / NO_RESULT.
  HELD_100 = both fields exactly 100 at every window sample, the window reaching 60 s before and 30 s
  after the kill with no sample gap over 35 s, the player alive and the frame at most 10 s old at each
  one; it is the CHECK's FAIL only once the operator confirms the turret was on screen below full HP
  in a sampled frame (the tool cannot see pixels, so it never exits FAIL on the tower half; exit 2 is
  writer FAIL only). It reports the side mapping as ASSUMED (`_T1_` ORDER, `_T2_` CHAOS) on every
  result, so the drain still confirms it on that first event, and it RECORDS the field's after-kill
  values and whether it read 0 (`_TOWER_DEAD`, `core/aram_deterministic_coach.py`). IDLE READ
  (2026-11-04 21:14 local, one sample): `/api/state` did not answer (state_ok false), the artifact
  still reads `mode` aram, `my_team` ORDER, 100 / 100, and the shadow tail row is dated 2026-08-02 -
  the 2026-08-02 game, which the tool's game-start cutoff excludes. SUBSTITUTION CHECK: (a) the 25
  synthetic cases in `tests/test_gated_g314_tower_input.py` prove the grader, never a tower read; (b)
  the deterministic `objective` text ("Poke the enemy tower") is DOWNSTREAM of these fields, so
  reading it instead is the compute half; (c) a moved value in the artifact proves the field
  ARRIVED, not that it is the right tower or the right HP - that is the eyeball half; (d) the
  `turret_events` list is the Live Client's, not RC's, so it is the independent clock for the window.
  **RM-869 LIVE HALF - READY (lane 9 PREP s144 cycle 10, source read at `f073b1ca1`; NOT a tick; a
  sub-check of this row, NOT a new row, so no count moves).** RM-869 (`bfa4bbfbe`, LEDGER 1833) moved
  the ARAM and Brawl vision readers off the promptless TFT relay (`USE_RELAY = False`:
  `coaches/aram_coach.py:837` `_build_vision_reader`, `coaches/brawl_coach.py:643` / `:652`), so
  finding (3) above (tower inputs stuck at the 100 / 100 seed) has a shipped upstream fix that no game
  has exercised yet. The fix is LOADED: `ops/runtime/health.json` `started_at` 2026-10-27T12:47:45Z is
  after the landing (committer time 2026-10-25T07:01:01Z), and `bfa4bbfbe` is an ancestor of the main
  checkout's HEAD. The only on-disk trace of the fields is the coaching file: ARAM `_run_vision`
  (`:869`) writes `my_tower_hp` / `enemy_tower_hp` / `wave_pct` / `hp_packs` only when the read is
  non-null (`:920` block); Brawl `_run_vision` (`coaches/brawl_coach.py:245`) writes `event_name` /
  `event_timer` / `event_location` / `my_nexus_hp` / `enemy_nexus_hp` (`:263-269`). A new coach
  instance writes `_blank_artifact_data()` first (`coaches/_base_coach.py:671-678` `_ensure_data`),
  so after that a non-seed value can only be a vision write. ONE COMMAND (read-only, prints no game
  id and no path): `python tools/gated_rm869_vision_fields.py --mode aram --samples 30 --interval 10`
  (Nexus Blitz: `--mode nb --samples 60 --interval 10`), run from a worktree or the main checkout,
  started once the game is past the load screen. PREDICATE (stated before any game): PASS iff a FRESH
  sample (file mtime at or after the cutoff, `mode` `aram` / `brawl`) holds one of those fields at a
  non-seed, non-null, non-empty value (ARAM seeds 100 / 100 / 50 / `[true, true]`; NB seeds `""` / 0 /
  null / 100 / 100). `wave_pct` is the cheapest signal: the wave moves every read, so 50 for a whole
  game is itself suspicious. FAIL iff the tool says SEED_ONLY over at least 10 fresh samples spanning
  at least 4 minutes of game time while the player is alive and the frame is fresh (`:8889/latest-frame/meta`
  `ts`) AND, for ARAM, a tower is on screen below full HP in a sampled frame, or, for NB, an event
  banner is on screen (100 is the prompt's own "not visible" answer for nexus HP, so nexus 100 alone
  is never a FAIL). NO RESULT: no fresh sample (NO_GAME), a dead or tabbed-out player, a stale frame,
  or a Sonnet error / daily cost-gate log line in the window. Restart FAIL (cutoff before the fix) =
  restart RC first, never a row verdict. EVIDENCE: paste the tool's `fields` line (the non-seed values
  it lists), the file it read (`data/aram_coaching_data.json` or `data/brawl_coaching_data.json`,
  main checkout), the sample window in local time, mode / queue and `liveclient.game_time_s` at the
  first hit, and the predicate above. SUBSTITUTION CHECK: (a) a passing
  `tests/test_aram_brawl_vision_relay_rm869.py` proves the flag, not a field reaching disk; (b)
  `data/vision_merge_shadow.jsonl` is NOT evidence either way - `core/vision_routing.py:148-164`
  appends a row only when the escalation answers keys nobody asked for, so a direct read that answers
  its own prompt writes NO row, and "no new rows" can mean fixed or dead; (c) a non-seed value in a
  STALE file (mtime before the cutoff) is the 2026-08-02 game, which the tool excludes; (d) the
  value's truth (does `wave_pct` 62 match the screen?) is a separate eyeball - the RM-869 predicate is
  only "the field ARRIVED", and finding (3)'s tower CHECK above is still the row that grades the tower
  value. URF: `--mode urf` always reports UNOBSERVABLE. Its three prompt keys (`heal_enemies`,
  `poke_phase`, `deaths_visible`) land only in the in-memory `_vision_state` and no code reads them
  (grep at `f073b1ca1`: only the `BrawlVisionReader` prompt, field list and validators name them;
  Nexus Blitz `turret_count_my` / `turret_count_enemy` likewise have no reader), so the URF half has
  no observable live result; filed for the merger (s144 gated cycle 10 report, RM-968). Nexus
  Blitz and URF have no gate in this file (they route to RC `MODE_BRAWL`, `core/game_snapshot.py:127-131`);
  the NB half rides any Nexus Blitz game the operator happens to play. One For All and GAMEMODEX also
  get the NB prompt and write `mode` `brawl`, so an `--mode nb` PASS counts only when the live-client
  `gameMode` at the first hit is `NEXUSBLITZ` (record it in the evidence).
  **RM-869 RE-CHECK (lane 9 PREP s144 cycle 102, 2026-11-07, source read at `b8d0026ad`; NOT a
  tick; PROBE, PREDICATE and SUBSTITUTION CHECK above unchanged).** (1) **Both shas above are
  pre-rewrite twins, not reachable from HEAD or `main`.** `.git/filter-repo/commit-map` maps
  `bfa4bbfbe` to `a79f8a26a` (same subject, same committer time 2026-10-25T07:01:01Z, an empty
  `coaches/` diff between the twins) and `f073b1ca1` to `44532fe1c`; read `a79f8a26a` wherever the
  block above says `bfa4bbfbe`, including "is an ancestor of the main checkout's HEAD" (true of
  `a79f8a26a`, false of `bfa4bbfbe`). The tool keys its restart check on the committer TIME constant
  (`FIX_COMMITTED_UTC`), not the sha, so the rewrite does not move its verdict; its docstring still
  names `bfa4bbfbe`. (2) **Line cites, block-above value then HEAD value:** `_build_vision_reader`
  `coaches/aram_coach.py:837` is now `:839` (its `r.USE_RELAY = False` `:865`); ARAM `_run_vision`
  `:869` is now `:871`; the ARAM `:920` write block (its first key line) is now `:922`
  (`cur = load_json` `:920`, loop `:921`, four keys `:922-925`, non-null guard `:927`); Brawl `USE_RELAY = False` `coaches/brawl_coach.py:643` is now
  `:637` and `r.USE_RELAY = self.USE_RELAY` `:652` is now `:646`; Brawl `_run_vision` `:245` is now
  `:243`; its writes `:263-269` are now `:261-267` (`safe_write` `:268`); `_ensure_data`
  `coaches/_base_coach.py:671` holds and (unchanged since `44532fe1c`) delegates to `_write_blank_artifact` (call `:678`, def `:684`), whose
  `safe_write(self._out, self._blank_artifact_data())` is `:687`, so "a new instance blanks first"
  still holds; `core/vision_routing.py:148-164` holds (`if dropped:` `:148`, `_log_merge_drops`
  `:164`, the JSONL writer `_log_merge_drops` `:225`); `core/game_snapshot.py:127-131` holds. The
  URF / NB unread keys still have no reader (field lists `coaches/brawl_coach.py:604` NB turrets, `:618-619` URF, validators
  `:607-625`, prompt `:579-595`). The line drift is 18 commits on the three coach files since
  `44532fe1c`, mostly lint / cite-to-symbol (e.g. `f7e88a157` ClassVar, `a2503f89e`, `5a6013974`, `1f2504bcd`,
  `7e55c31ae`); the `_run_vision`, `_build_vision_reader` and `_ensure_data` bodies carry no code
  hunk. ONE behaviour change sits on both write paths: `ef2c7db22` (RM-1297) makes `load_json`
  (`coaches/_base_coach.py:64`) return `{}` for a non-object JSON document; that only lets a vision
  write proceed onto an empty dict, so it cannot put a non-seed value on disk without a vision
  read and does not move the predicate. (3) **Idle run** (2026-11-07 ~04:14 local, `python -B
  tools/gated_rm869_vision_fields.py --mode <m> --samples 1 --interval 0`, main checkout's data):
  aram NO_GAME, nb NO_GAME, urf UNOBSERVABLE, each exit 1; restart PASS on cutoff
  2026-11-01T01:33:09Z. That restart PASS is HOLLOW today: `ops/runtime/launcher_status.json`
  reads `halted` (last updated 2026-11-01T02:17:21Z) and `health.json` pid 18724 is not running while it
  still says `alive` true (the cycle 100 dead-RC finding on G7-17). The tool's restart line reads
  `started_at` only, so ADD to the probe's precondition: before the game, `launcher_status.json`
  `state` running and `:8888/api/state` answering 200, else the window is NO RESULT (a dead RC
  writes no coaching file, so a stale `started_at` cannot false-PASS the fields half). The
  coaching files are stale as expected: `data/aram_coaching_data.json` mtime 2026-08-02,
  `data/brawl_coaching_data.json` 2026-04-19, both before the cutoff.
- **G3-15** ARAM re-checks of GATE 2 rows (no separate work, just look while you are here): G2-12 R49
  reflect ranking-vs-real-comp (the stricter read), G2-29 the ARAM flood-tint question, G2-38 PD->Kraken
  level-tick stability (ARAM-suitable, no enemy-comp dependency).
  **PREP AUDIT (lane 9 PREP s144 cycle 57, source read at `412042dc8`; NOT a tick).** The three legs
  are in three different states, so "just look while you are here" applies to ONE of them.
  (1) **G2-29 leg: ANSWERED, nothing to look at.** The 2026-07-20 ARAM Mayhem game answered it (no
  flood; ZOI drew the bridge as a diagonal band with districts `blue_base` / `red_base` /
  `aram_bridge` / `brush_north` / `brush_south`): the drain block at the top of this file, LEDGER 987.
  Re-looking is not a check; only a reversal (a flood seen in a later ARAM game) re-opens it, and then
  as a new observation with a timed frame.
  (2) **G2-38 leg: READY, use the G2-38 row's block (cycle 43) unchanged.** Its tool
  `tools/gated_g238_top_pick_flip.py` takes the mode from `/api/state` `mode_key`, upper-cased
  (`:283`), with no SR gate, and the build panel's `_maybeRefreshBuildOrder`
  (`web/js/panels/active_match.js:444`) has no mode gate (its early returns are a missing champion or
  mode, and the stale / in-flight debounce that hands back the cached order). The
  2026-07-20 drain already rode this panel through an ARAM game (levels 1-14, a real top-1 flip at
  6:51 / level 9), so the surface is measured to render in ARAM. Same PROBE, PREDICATE, EVIDENCE and
  SUBSTITUTION CHECK as that row; add mode ARAM and queue 2400 to the evidence, and record
  `tightest_gap_pct` beside the 9.02 baseline on a `NO_RESULT`.
  (3) **G2-12 leg: NOT LIVE-OBSERVABLE at HEAD, so an ARAM game cannot exercise it.** grep at
  `412042dc8`: `assume_passive_reflect` is a Python keyword only - `agents/daemon_slayer/dps.py`
  (`:792`, fold `:1697`), `agents/daemon_slayer/burst.py` (`:535`, fold `:1292`) and the registry
  `agents/daemon_slayer/_passive_reflect_overrides.py` - with ZERO hits in
  `agents/daemon_slayer/server.py` and no RC caller, and `tests/test_ds_parity_map.py:88-89` pins it
  in `_UNREACHABLE_OK` for both `/burst` and `/dps` (an equality ratchet: wiring it turns that test
  red). No `/rank*` route forwards it either, so no panel, coach field or overlay row carries a
  reflect credit, and "ranking vs the real comp" has no rendered ranking to read. The engine also
  never reads the comp: the incoming cadence is the constant `reflect_cadence_s=1.0`
  (`_passive_reflect_overrides.py:123`) and the shipped ranged factor `_REFLECT_RANGED_EXPOSURE = 0.35`
  (`:81`, applied at `:100`) keys on the WIELDER being ranged, not on the enemies. What the leg
  needs first is the R49 flip-ledger OWED item (1) below: a code slice that wires a live rank
  consumer for the flag (route parse plus an RC caller, with the parity-map line deleted in the same
  slice). Only then does a live read exist: PREDICATE for that later read (stated now): with a
  thorn-carrier build (Rammus, or Thornmail 3075 / Bramble Vest 3076 on a melee tank) the reflect-ON
  rank moves the carrier up by no more than the operator judges the reflect actually paid against
  the auto-attack share of the REAL enemy five (count of enemies whose damage is mainly basic
  attacks, from `/api/state` `liveclient` allPlayers), and a no-carrier control build ranks
  byte-identical OFF vs ON. SUBSTITUTION CHECK: the 2026-07-20 Python-API delta (+8.963 pct, the
  pre-factor figure) or any probe that calls `compute_dps` / `compute_burst_damage` directly with the
  flag set is the compute half and never this read; a reflect number on a route a fresh test client
  hits is not what the operator's panel rendered. Filed RM-1391 (wire-the-consumer code slice,
  Tier-2: engine route); until it lands, G3-15 drains on its G2-38 leg alone.

---

## GATE 4 - REAL MATCHMADE SR (draft; make it RANKED q420 to feed the rails)

The only gate that reaches Match-V5, real enemy runes, real allies, and a real ban phase. Playing ONE
of these clears every GATE 2 row plus this section. Make it ranked q420 so it also feeds G7-06 / G7-08
/ G7-09.

### Champ-select (real draft lobby)

- **G4-01** (was A9) Enemy/ban-dependent champ-select captures: OQ9 ban-reason labels (`1bf255ea`),
  ~~cooldown-watch card (render-gated on committed enemies)~~, ~~UIX1 champ-select SR live capture
  (`18f37d4f`)~~. SOURCE: LEDGER 726.
  **AGE CHECK + READY (lane 9 PREP s144 cycle 82, RM-1671; source read at local main `ba0df749f`,
  no game up, dashboard not answering; NOT a tick). Two of the three parts are dead; one stays open.**
  (b) cooldown-watch card - **STRUCK, CLASS 1: the subject is gone, and must not come back.** The
  champ-select card was removed by the operator's QA 2026-07-03 slice A (B19, LEDGER 765;
  `web/js/panels/champ_select.js` comment at its imports and again above the TEAM ANALYSIS cluster;
  `web/index.html` comment above the personal best-build card), and the backend went with it on
  2026-08-11: `dashboard/routes_cooldown_watch.py` and `agents/daemon_slayer/cooldown_watch.py` are
  both absent at HEAD, deleted by `538c61e4b` "fix(compliance): remove Riot-banned surfaces" (it
  joined enemy CC to enemy ability cooldowns, which Riot's third-party rules ban tracking; see the
  allow-list note in `agents/daemon_slayer/tests/test_cc_conditional_forward_marker.py`). Draining
  it would mean re-adding a banned surface. (c) UIX1 champ-select SR live capture - **STRUCK,
  CLASS 1 (superseded) and not live-gated.** The cite `18f37d4f` does not resolve in this clone
  (`git cat-file -t` fails); the UIX1 commit at HEAD is `7b680e65d` "fix(UIX1): champ-select SR
  fixture-audit cleanups" (LEDGER 434). What it owed was a Claude_Preview VISUAL of a CSS-only
  tokenization ("byte-identical render") that could not attach to the live :8888 - a fixture
  capture, never a game need - and its subject, the YOUR RECORD `.csv-pr-*` block, was removed in
  the same slice A (A4; `web/css/panels/champ_select_view.css` keeps only the removal comment).
  (a) OQ9 ban-reason labels - **OPEN, half its scope is gone, READY below.** The global-suggestion
  half ("meta ban #N", `.csv-sugg-ban-reason`) died with the A2/A7 ghost bans grid in `0b83cce5f`
  (slice A, 2026-07-03); the backend `rank` field in `dashboard/routes_ban_suggestions.py` survives
  with no champ-select reader. What remains is the P&B counter-ban label: `_csvBanReasonLabel` in
  `web/js/panels/champ_select.js` writes `beats you <pct>%` plus ` (<losses>/<encounters>)` when
  encounters > 0 into `.csv-pb168-reason` under each `.csv-pb168-ban` cell of `#csv-pickban-body`,
  and "" when pct <= 0. Its input is NOT enemy- or ban-dependent: it is
  `GET /api/champ-select/pickban-recs?role=<role>&queue=<q>...` (`dashboard/routes_pickban.py`),
  `performance_bans[0..2]` and `struggle_ban`, read from the operator's own match history, so the
  only thing a real draft adds is the assigned role. The 2026-07-20 drain session above recorded
  this row ADVANCED ("render live with provenance tags + a STRUGGLE tier") without a value, source
  or timestamp in the row, so it does not meet the evidence contract. PROBE, in one real draft SR
  champ select (q400 / q420) after role assignment: (1) the exact `pickban-recs` URL the panel
  requested (its `role` and `queue` params) and that response body, with a capture timestamp (the body carries no `ts`); (2) within 5 s of
  it, from the same page, the text of `.csv-pb168-name`, `.csv-pb168-reason` and
  `.csv-pb168-struggle` of each of the 4 `#csv-pickban-body .csv-pb168-ban` cells. PASS iff, for
  each of cells 1-3 whose response row `performance_bans[i]` has pct > 0, the name equals the row's
  `name` and the reason equals the formatter applied to the row's `pct` / `losses` / `encounters`;
  each cell whose row is absent or pct <= 0 has no `.csv-pb168-reason`; and cell 4 matches
  `struggle_ban` by the same rule. At least one cell must carry a non-empty reason, else the pass
  is vacuous: record "no qualifying loss rate at this role" and leave the row open. SUBSTITUTION
  CHECK: the STRUGGLE tag alone proves nothing, because the renderer puts it on cell 4 even when
  `struggle_ban` is null (the placeholder cell reads "-" with STRUGGLE above it), and a unit
  test (`tests/test_ban_reason_labels_oq9.py`) or a fixture-driven render of the formatter answers whether it COMPUTES a label; only the label text
  read off the live page, joined to the response the panel itself fetched at that time, answers
  whether it RENDERED the live rows.

### `[BATCH DS-SEAM]` - real-enemy / real-ally seams (same restart discipline as GATE 2)

- **G4-02** `[BLOCKED ON WIRING 2026-11-06]` (was B31) DSP5 summoner-spell plumb + eyeball: player's + ENEMY's live summoner sets into
  `dsp_live_consumers.summoner_fight_adjustments`; re-anchor wiki magnitudes at flip. Route WIRED
  (OQ18, POST `/summoner-fight-adj`) but **producer-orphan** - no caller POSTs a live summoner set, so
  this is a code+eyeball slice, not a pure flip.
  **AGE CHECK (lane 9 PREP s144 cycle 81, RM-1670; source read at local main `ba0df749f`, no game
  up; NOT a tick). Still producer-orphan, for all four rows G4-02 / G4-03 / G4-04 / G4-05, so no
  game drains any of them today: a real draft only shows that the inputs EXIST.** Measured: outside
  `agents/daemon_slayer/`, no tracked `.py` / `.js` / `.mjs` file (tests aside) names
  `/summoner-fight-adj`, `/enemy-rune-threat`, `/ally-protected-ehp`, `summoner_fight_adjustments`,
  `enemy_rune_threat` or `ally_protected_ehp`; inside it the three consumers
  (`dsp_live_consumers.py`) are called only by their own routes (`server.py`
  `_route_summoner_fight_adj`, `_route_enemy_rune_threat`, `_route_ally_protected_ehp`). DSP8:
  `core/daemon_slayer_client.py` `rank_assassin_for` accepts `target_preset` and puts it on the
  `/rank-assassin` body, but its one caller (`rank_for_primary_archetype`, the `arch == "assassin"`
  branch) never passes it, so no live body carries the key; the only other users are the offline
  `ops/audit/ds_perm_swarm/live_flip_eyeball.py` harness and `tools/live_flip_watcher.py`, which
  pick a preset by hand. The game-side inputs are not the blocker: the Live Client's `allPlayers[]`
  carries each player's `team` and `summonerSpells` (`summonerSpells` measured live, LEDGER 648) and, per the Riot
  Live Client schema (not re-measured this cycle), a keystone under `runes`. The missing piece is
  RC code. PRECONDITION for return to the drain list: a producer lands that sends the live set
  AND records its outbound body (a log line or shadow row carrying `ts` and the Live Client
  `gameData.gameTime` it read). Predicates stated NOW, graded only after that lands, each in one
  real draft SR game (q400 / q420): G4-02 PASS iff a recorded body's self ids equal
  `activePlayer`'s own `allPlayers[]` row `summonerSpells` and its enemy ids equal the other team's,
  from a `:2999` read within 10 s of game time of the body; G4-03 PASS iff the enemy keystones in a
  recorded body equal the other team's `runes.keystone` ids from such a read, and a lobby with no
  PtA / Conqueror / Grasp enemy yields the no-threat response; G4-04 PASS iff the ally set in a
  recorded body equals the own team minus self from such a read; G4-05 PASS iff a recorded
  `/rank-assassin` body carries a `target_preset` equal to the producer's own derivation rule
  applied to that read's enemy team. The on-screen eyeball halves are written when the producer
  names its surface. SUBSTITUTION CHECK: a hand-POSTed DS body, a fixture, the `live_flip_eyeball`
  harness or a DS unit test answers whether the engine COMPUTES on a set; only the producer's own
  recorded outbound body, joined to a `:2999` read at the same game time, answers whether RC SENT
  the live set.
- **G4-03** `[BLOCKED ON WIRING 2026-11-06]` (was B32) DSP6 enemy-rune threat plumb: ENEMY's live rune set into
  `dsp_live_consumers.enemy_rune_threat` (PtA/Conqueror/Grasp shifts; no-threat lobby unchanged).
  **Practice tool has NO enemy rune sets.** Route WIRED (OQ18), producer-orphan. Re-measured
  2026-11-06: still no RC producer; AGE CHECK, precondition and predicate in G4-02.
- **G4-04** `[BLOCKED ON WIRING 2026-11-06]` (was B33) DSP7 ally aura/enchanter plumb: live ally team into
  `dsp_live_consumers.ally_protected_ehp` (ally beside Janna/Lulu/Soraka shows higher EHP; solo ally
  unchanged). **Practice tool is solo.** Route WIRED (OQ18), producer-orphan. Re-measured
  2026-11-06: still no RC producer; AGE CHECK, precondition and predicate in G4-02.
- **G4-05** `[BLOCKED ON WIRING 2026-11-06]` (was B34) DSP8 `target_preset` derived from the LIVE enemy comp into burst /
  `/rank-assassin` (lethality vs tank comp, magic pen vs high-CC comp). Route WIRED (OQ17); the live
  enemy-comp derivation into the body + the flip stay pending. DS restart. Re-measured 2026-11-06:
  `rank_for_primary_archetype` never passes `target_preset`; AGE CHECK, precondition and predicate
  in G4-02.
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
  **AGE CHECK (lane 9 PREP s144 cycle 89, S144-G-80; source read at local main `86ed5e52d`, no
  game up; NOT a tick). Both halves are still undone, and the row still needs no game.**
  `_ASSUMED_ABILITY_RANK = 4` stands in `_passive_flat_mitigation_overrides.py` (the `:99` / `:234`
  cites above have drifted by one line, and the read at `:235` is now clamped) and in its
  kept-in-sync twin `_passive_mitigation_overrides.py`. `/ehp` and `/rank-tank` parse the flag (`server.py`
  `_route_ehp`, `_route_rank_tank`), and `core/daemon_slayer_client.py` `rank_tank_for` / `ehp_for`
  emit it when True. But the live survivability callers never pass it: the tank branch of
  `rank_for_primary_archetype` and `core/defensive_picks.py`'s `rank_tank_for` call omit it, it is
  not in `dashboard/routes_state.py` `_DS_PREVIEW_SEAM_BOOLS`, and `ehp_for` has no RC caller.
  The live flip is therefore also a missing producer, not only a default.
- **G4-07** `[BLOCKED ON WIRING 2026-11-06]` (was B36) R50 `apply_all_out_bonus` (K'Sante): confirm the empowered-mark value in an
  actual All Out fight + tune `conditional_probability` 0.5 vs real All-Out uptime. **NOT a pure HTTP
  flag-flip** - it is a load-time `AbilitiesSnapshot.load()` flag (`abilities.py:675`), so threading it
  needs per-request snapshot construction (separate FUTURE task). Only fires if K'Sante is played.
  **AGE CHECK (lane 9 PREP s144 cycle 89, S144-G-80; source read at local main `86ed5e52d`, no
  game up; NOT a tick). Still unreachable live: no game drains this row today.** The flag is a
  keyword of `AbilitiesSnapshot.load` (now near `abilities.py:1283`; the `:675` cite is stale) and is
  consumed only by `_apply_all_out_bonus_overrides`. No DS route parses `apply_all_out_bonus`, and
  no tracked `.py` / `.js` / `.mjs` outside `agents/daemon_slayer/` (tests aside) names it. The
  server's only flag-ON snapshot holder (`server.py` `_AbilitiesOverrideCache`) builds
  `apply_ability_base_overrides=True` alone. `load_default()` and `data_loader.py` call
  `AbilitiesSnapshot.load()` with no seam flags (`data_loader.py` passes only `patch` / `data_root`). The 0.5 is still the `conditional_probability` of the
  `_ALL_OUT_BONUS_OVERRIDES` `("KSante", "P", 0)` entry. PRECONDITION for return to the drain list:
  the per-request snapshot path lands AND a live caller sets the flag for a K'Sante holder, recording
  its outbound body with `ts` and the `:2999` `gameData.gameTime` it read. Predicate stated NOW,
  graded only after that lands, in one real SR game with a K'Sante: PASS iff a recorded body for
  K'Sante carries `apply_all_out_bonus` true, a `:2999` read within 10 s of game time shows
  `KSante` in `allPlayers[]`, and the DS answer to that body differs from the same body with the
  flag OFF. The uptime half (tune 0.5) cannot be graded from `:2999`: per the Riot Live Client
  schema (not re-measured this cycle) it carries no buff or R-state field and no per-hit damage. Its
  source would be a post-game Match-V5 timeline (`CHAMPION_KILL` `victimDamageReceived`, stored by
  `scripts/rewind_scraper.py` as `victim_damage_json`). Which `spellName` that timeline gives the
  mark consume is NOT measured; reading one is the first step. SUBSTITUTION CHECK: a hand-built
  `AbilitiesSnapshot.load(apply_all_out_bonus=True)` call, a fixture or a DS unit test answers
  whether the engine COMPUTES the bonus; only a producer's recorded body joined to a live read
  answers whether RC SENT it.
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
  **AGE RE-CHECK 2026-11-10 (lane 9 s144 cycle 145, S144-G-132, source read at `134f4c72e`, DS patch
  16.22.1, ENGINE_VERSION 1.291.0; no game up; NOT a tick).** The CLOSED verdict holds and the
  measurement reproduces to the cent; items (2) and (3) are corrections. (1) REPRODUCES: same Yone target build and
  Fizz burst build as above, `compute_ehp` lvl18 -> hp 2405.00 / armor 141.20 / mr 66.85, and
  `compute_burst_damage` lvl18 with that target reads 3330.26 -> 2630.26, delta -700.00; with no
  target modelled it reads 4488.00 -> 3788.00. `target_lifeline_shield` reads 700.00 at lvl18 and
  400.00 at lvl9; Sterak 3053 0.00 at `target_bonus_hp=0` and 1200.00 at 2000; Maw 3156 200.00 and
  425.00 at 150 bonus AD. (2) CITES DRIFTED, CONSUMER SET HOLDS: still exactly two engine consumers,
  both default `False` by `inspect.signature` - `compute_burst_damage` (parameter `burst.py:536`,
  branch `:1385`) and `compute_dps` (parameter `dps.py:793`, branch `:1965`). `rank_items_by_burst`
  (`burst.py:1945`), `rank_at_level` (`ability_dps.py:333`) and `compute_rune_proc_damage`
  (`rune_procs.py:859`) still lack the parameter, and no tracked non-test `.py` file outside
  `burst.py`, `dps.py` and `_lifeline_target_shield.py` names it (prose docs and the DS CHANGELOG do). (3) THE "REMAINS" FLIP IS NOT PENDING: no HTTP
  route parses the flag (`tests/test_ds_parity_map.py` `_UNREACHABLE_OK` lists it under both `/burst`
  and `/dps`, an equality ratchet), and `agents/daemon_slayer/tests/test_stranded_hsp_seam_r197.py`
  `STRANDED_TODAY` records it as operator-CLOSED s232, the conditional-target-state arc (CLAUDE.md
  Settled). No flip is queued and no live residual exists; re-opening needs the operator (or MAIN)
  to re-open s232 in writing. That ledger's reason text says "caster-state lifeline", but the seam
  models the TARGET's shield (`_lifeline_target_shield.py` docstring); a label slip only, outside
  this lane's write set (S144-G-133). The row's first paragraph carries a real match id; this
  re-check does not repeat it, and scrubbing it belongs to RM-906.
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
  **AGE CHECK (lane 9 PREP s144 cycle 132, S144-G-119; source read at lane HEAD `98c59a301` over
  local main `d2d4840f1`, no game up: :8888 and :2999 both curl 000 at 2026-11-09T06:41-06:00;
  NOT a tick). The flip has NOT landed and no RC producer sends the flag.**
  (1) Still DEFAULT-OFF everywhere: `assume_hsp_amp: bool = False` at `ehp.py:1414` and `:3324`,
  `hybrid.py:453` and `:1019`, `sustain.py:347` (`compute_sustain`); `server.py` parses it with
  `_opt_bool(body, "assume_hsp_amp", False)` on four routes only - `_route_ehp` (:1022),
  `_route_rank_tank`, `_route_rank_bruiser`, `_route_sustain`.
  (2) Cite drift: the `ehp.py:1472-1479` cite above is stale; the `hsp_pct` block now sits at
  `ehp.py:1990-2000`, with `shield_amp_mult = heal_amp_mult * (1.0 + hsp_pct)` at `:2000`.
  (3) Census drift: `ITEM_EFFECTS` now holds 549 entries, **20** with a `shield` (the row filed 16).
  The "14 carry BOTH" figure was measured on the 16-item set and was NOT re-run here (a corpus
  re-score is a DS measurement, not a gated one); treat 14 as a lower bound, not a current count.
  (4) Producer: the RC senders are `core/daemon_slayer_client.py` `ehp_for` (:1131), `rank_tank_for`
  (:907) and `rank_bruiser_for` (:1514, forwards at :1676). The only caller in `core/` `coaches/`
  `dashboard/` `modes/` `app/` is `core/defensive_picks.py:402` `rank_tank_for(...)`, which passes
  no `assume_hsp_amp`, so it sends False. The flag is not in `_DS_PREVIEW_SEAM_BOOLS`
  (`dashboard/routes_state.py:969`) and no `web/` file names it.
  PROPOSAL (not a move; a human moves rows): this is a `Not actually live-gated` CANDIDATE. Both
  halves were settled headless on real builds, `:2999` carries no heal or shield throughput field
  (Riot Live Client schema, not re-measured this cycle), so no game can grade the magnitude, and the
  flip itself is an operator decision, not an observation. SUBSTITUTION CHECK: if the flip lands
  and a later row asks whether RC SENT the flag live, that is a producer question in the G4-10
  shape (a recorded outbound body with `ts` joined to a `:2999` items read within 10 s of
  `gameData.gameTime`); a hand-POSTed body or the LEDGER 745 ratios answer only that the engine
  COMPUTES the amp.
- **G4-10** `[BLOCKED ON WIRING 2026-11-06]` (was B47c) R109 `apply_ability_hsp_amp` - item HSP amp of the CHAMPION-ABILITY heal/shield
  throughput in `compute_hps` (an enchanter's Ardent/Staff/Redemption/Moonstone/Mikael amped her ITEM
  heals but NOT her ABILITY heals - Soraka Q/W, Janna E, Lulu E; live-proven delta==0 on 8 enchanters,
  Soraka +6.65 HPS / ~6.3%). CALIBRATION FLAG (adversarial review): the amp reuses the item side's
  PRODUCT convention (`prod(1 + heal_shield_amp_pct)`) which diverges from real-League ADDITIVE HSP
  stacking and from the EHP path's additive `_hsp_amp.sum_wielder_hsp_pct` - a pre-existing item-side
  asymmetry, NOT a regression. **A two-HSP-item build is the calibration case.** SOURCE: LEDGER 857.
  **AGE CHECK (lane 9 PREP s144 cycle 89, S144-G-80; source read
  at local main `86ed5e52d`, no game up; NOT a tick). Producer-orphan: no game drains this row
  today.** `apply_ability_hsp_amp` is parsed by `/hps` only (`server.py` `_route_hps`; the RM-172
  comment there says it is NOT shared with `/rank-enchanter`). Its only RC sender is
  `core/daemon_slayer_client.py` `hps_for`, which has no RC caller. It is not in
  `_DS_PREVIEW_SEAM_BOOLS`, and no `web/` JS sends it (the one `web/` hit is the static mock
  `web/mock/addendum_a_concepts.html`). The calibration question (PRODUCT vs ADDITIVE stacking on a
  two-HSP-item build) is a rules-and-code question: `:2999` carries no heal or shield throughput
  field (per the Riot Live Client schema, not re-measured this cycle), so a game cannot answer it.
  PRECONDITION for return to the drain list: a live caller of `hps_for` (or a forwarding scorer)
  sets the flag for an enchanter holder and records its outbound body with `ts` and the `:2999`
  `gameData.gameTime` it read. Predicate stated NOW, graded only after that lands, in one real SR
  game with an enchanter holding an HSP item: PASS iff a recorded `/hps` body carries
  `apply_ability_hsp_amp` true and its `items` list equals, as a set, that player's `allPlayers[].items[].itemID`
  set from a `:2999` read within 10 s of game time. SUBSTITUTION CHECK: a hand-POSTed `/hps` body,
  the LEDGER 857 delta or a DS unit test answers whether the engine COMPUTES the amp; only the
  producer's recorded body joined to a live read answers whether RC SENT it.
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
  AGE CHECK (lane 9 PREP s144 cycle 89, S144-G-80; source read at local main `86ed5e52d`; NOT a
  tick): still true. The flag's two CODE sites are now the `AbilitiesSnapshot.load` keyword (near
  `abilities.py:1285`) and its consumer (near `:1513`); the `:677` / `:812` / `:898` cites above are
  stale line numbers. `load_default()` still calls a bare `AbilitiesSnapshot.load()`, and no DS
  route or RC caller passes the flag.

### In-game render / behavior (real combat pressure)

- **G4-12** (was B37) L4 capability-gap live validation - `RC_CAPGAP_SURFACE` is DEFAULT-ON in code
  since LEDGER 765 and the served `capability_gap` dict is live-verified on `/api/ds-preview`. The
  ONLY remaining gate is the in-game EYEBALL of the chip CONTENT vs a real enemy comp. SOURCE: RM-07.
  **READY (lane 9 PREP s144 cycle 72, source read at `6bd02cfdd`; NOT a tick; no game up: :8888 and
  :2999 curl 000 at 2026-11-05T20:49-06:00).** AGE CHECK: NOT stale. The flag still defaults ON
  (`dashboard/routes_state.py` `os.environ.get("RC_CAPGAP_SURFACE", "1")`), the chip is not behind the
  B4 live-directive gate (`live_directive_gate.js` blanks the coach imperatives only). It is REPAINTED
  only while live AND while `_amDsSyntheticCs` resolves the coach champion to a numeric id: otherwise
  `renderActiveMatch` (the not-live early return) and `_amRenderDsCluster` (the null synthetic-cs
  return) both return BEFORE the chip call, so its own not-live hide branch never runs and the chip
  KEEPS ITS LAST PAINT; a post-game or lobby page can still show the previous game's gap. Only a
  capture inside a live game counts, and a chip seen after the game ends is a finding to record, not
  a pass (the stale last paint is filed provisionally as RM-1662 for the merger to mint; this live
  read confirms or refutes it: one look at the dashboard after the game ends). It paints twice
  in-game: the dashboard Active Match BUILD pane mount `#am-sugg-capability-gap` (`web/index.html`)
  and, inside the same pane, the overlay widget `w-build` (`overlay_layout.js`; `overlay.css` hides
  only ds-sweep / ds-matchup / ds-combo / ds-relscore there, not this chip). The client caches the
  answer per champion + roster + mode for the life of the page. It posts `/api/state` `coach.champion`
  (`main.js` `coachPayload = st.coach || st`) with `mode_key` upper-cased; the route canonicalises the
  champion (`canonical_champion_id`) before `build_capability_gap`, and the grader's in-process path
  does the same.
  A LIVE-ONLY RISK the eyeball must exclude first: the client posts every `liveclient.allPlayers` row
  whose team differs from `_resolveMyTeam`, and when that resolve finds no name match it returns null
  and the skip never fires, so all 10 players (me and my allies too) are posted as "enemies"; the
  server keeps its own `enemy_team` by a different rule (`dashboard/_liveclient.py`). The stale
  "default-OFF" comments in `active_match.js`, `champ_select.js` and `web/index.html` are filed
  provisionally as RM-1661 (code lane) for the merger to mint, not edited here.
  PROBE (real SR game, ideally a comp with 2 or more heavy-sustain / artillery / tank enemies so a gap
  fires; any time after the roster loads), from the repo root, in one minute:
  (1) `curl -sk https://127.0.0.1:8888/api/state > _scratch/g412_state.json`;
  (2) in a HEADLESS Chromium page on `https://127.0.0.1:8888/` (ignore cert errors, Active Match
  view), opened at least 10 s earlier so its own `/api/ds-preview` fetch has landed, evaluate
  `python tools/gated_g412_capgap_chip.py snippet` and save the JSON as `_scratch/g412_dom.json`
  within 5 s of (1); when (3) first prints a RENDER_MISMATCH whose problems include "gap expected
  but chip not visible", re-run (1) and (2) together once and grade again (the DOM must stay within
  5 s of the state) before it counts as a FAIL;
  (3) `python tools/gated_g412_capgap_chip.py grade --state _scratch/g412_state.json --dom
  _scratch/g412_dom.json --state-ts <epoch of (1)> --json` (expected computed in-process);
  (4) optional cross-check with the SERVED payload, using the `posted_champion` and `enemies` that (3)
  printed: `curl -sk -X POST https://127.0.0.1:8888/api/ds-preview -H "Content-Type: application/json"
  -d '{"champion": "<posted_champion>", "enemies": [<enemies>], "mode": "SR", "level": 6, "items":
  []}' > _scratch/g412_preview.json`, then (3) again with `--preview _scratch/g412_preview.json`; the
  two verdicts must agree;
  (5) the operator, on the overlay `w-build` widget within the same minute: the GAP badge, its axis
  label and verdict line, read aloud or typed; then ONE yes / no: is that gap real for the 5 enemies
  on the scoreboard (e.g. "Anti-heal" against a comp with 2 or more real healers)?
  FIELD PATHS: `/api/state` -> `mode_key`, `lcu.phase` (must be InProgress), `coach.champion`,
  `liveclient.activePlayer`, `liveclient.allPlayers[].team /
  championName`, `liveclient.champion`, `liveclient.enemy_team`, `liveclient.game_time_s`;
  `/api/ds-preview` -> `capability_gap.applies / top_gap / verdict / gaps[].axis`; DOM ->
  `#am-sugg-capability-gap` `hidden`, `data-capgap-axis`, `.capability-gap-axis`,
  `.capability-gap-verdict`, computed `display`, bounding box, `offsetParent`.
  PREDICATE (stated before any game): PASS iff the grader prints RENDER_MATCH (team resolved, exactly
  5 posted enemies equal to the server `enemy_team`, the posted `coach.champion` equal to my roster
  row's champion, chip visible, axis label = the client label of `top_gap`, `data-capgap-axis` =
  `top_gap` (or `none` when empty), verdict text = `verdict`) AND the operator's overlay read names
  the same axis and verdict AND the operator answers yes. FAIL iff ROSTER_BAD, CHIP_ABSENT or
  RENDER_MISMATCH (each prints its named problems; a "chip not visible" mismatch only after the one
  step-(2) re-capture), or the operator answers no (a wrong gap for the
  comp is a content defect: record the 5 enemies and `gaps[]`). NO_GAME, STALE_DOM or
  NO_GAP_CONSISTENT (no gap fired for that comp, chip correctly hidden) = no evidence: re-sample later
  or in another game, never a pass.
  EVIDENCE CONTRACT: the grader JSON (verdict, `my_champion`, `posted_champion`, `enemies`, `top_gap`,
  `axis_label`, `verdict_text`, `gaps`, `game_time_s`, `state_ts`, `dom_ts`, `expected_source`), the
  operator's overlay read with its local time, and the yes / no, with mode, queue and `game_time_s`.
  Champion names only: never a player name, game id or puuid (RM-906).
  SUBSTITUTION: the served `capability_gap` (or the in-process `build_capability_gap`) is the COMPUTE
  half and RENDER_MATCH only shows the dashboard painted what was computed; neither answers the row.
  The row is answered only by the operator's overlay read plus the yes / no that the named gap is real
  for that comp, taken in a live game. A `?ui_mock=1` render seeds the chip from a fixture
  (`AM_MOCK_FIXTURES`) and proves nothing here. Grader: `tools/gated_g412_capgap_chip.py`, tests
  `tests/test_gated_g412_capgap_chip.py`.
- **G4-13** (was B38) RC2 P3.3/S0 pulse-rationing remaining eyeball: confirm the suppressed pulses
  were all benign re-emits AND the Emergency tier / one-shot Urgent cross still glows (lethal cues need
  real combat pressure - the item-598 capture verified only the suppression half).
  **READY (lane 9, s144 cycle 76, PREP only, NOT ticked; no game up: :8888 and :2999 curl status
  000 at 2026-11-05T22:58-06:00).** AGE CHECK: not stale. The rationing is LIVE in code
  (operator-approved 2026-06-22, per the `renderRightNow` and `overlay_pulse.js` comments), and no
  live capture of the glow half exists. Source facts (pinned in
  `tests/test_gated_g413_pulse_ration.py`): (a) `renderRightNow` (`web/js/panels/right_now.js`)
  stamps `data-s0-cue` / `data-s0-tier` / `data-s0-pulse` on `#right-now` on every envelope, and
  `shouldPulse` (`web/js/lib/overlay_priority.js`) arms only on a CUE CROSS into the emergency
  tier (lethal / objective_steal / urgent_headline) or into a one-shot cue (spike / choices).
  (b) On the overlay shell `#rn-action` is HIDDEN (`web/css/overlay.css` hides every
  `#right-now .panel-body` child but rn-lead / rn-choices / rn-callouts), so the headline
  `rn-pulse-*` glow never shows there. The overlay's only glow is `.ov-pulse`
  (`web/js/overlay_pulse.js`: a mount mutation while `data-s0-pulse` is "1", 1500 ms
  per-container throttle, muted by the `pulseNotify` setting), and it lands on `.am-pane-call`,
  because the live CALL pane (`web/js/panels/active_match.js`) is rebuilt with `innerHTML` on
  every envelope in the same dispatch, while rn-lead / rn-choices / rn-callouts are
  signature-deduped. (c) A lethal cross derived from `coach.hp_pct` (above 0 and at most 25 at a fight or urgent band)
  can arm with the headline text unchanged; the headline glow then stays dark by construction,
  so only `.ov-pulse` answers it. (d) A NEW headline under a HELD emergency cue (for example two
  urgent headlines in a row) never pulses, by design; that is the case the operator must judge as
  benign or not, so the grader lists it as `sustained_emergency_new_text`. (e) A same-value
  `dataset` write still queues an attribute mutation record, so the recorder logs every render
  (checked in a headless Chromium dry run on a synthetic page this cycle, `_scratch` only).
  PROBE (real SR or ARAM game, ideally with at least one low-HP fight; repo root): (1) open a
  HEADLESS Chromium page on `https://127.0.0.1:8888/?overlay=1` (ignore cert errors), wait 10 s,
  evaluate `python tools/gated_g413_pulse_ration.py snippet` once (it answers "armed 5 glow
  targets"); (2) leave it recording through real combat, at least 5 minutes of game time;
  (3) `curl -sk https://127.0.0.1:8888/api/state > _scratch/g413_state.json`, and within 5 s
  evaluate `python tools/gated_g413_pulse_ration.py dump` and save the string as
  `_scratch/g413_log.json`; (4) `python tools/gated_g413_pulse_ration.py grade --state
  _scratch/g413_state.json --log _scratch/g413_log.json --state-ts <epoch of (3)> --json`. On
  NO_ARMED keep recording and repeat (3)-(4); a recorder survives until the page reloads.
  PREDICATES, stated before any game: RATIONED (exit 0) iff the page is the overlay shell with
  pulseNotify on, every stamp after the first matches the shipped decision (tier = the cue's tier;
  pulse "1" exactly on an eligible cue cross), every armed stamp got an `.ov-pulse` within 1 s
  (or the CALL pane glowed in the previous 1.5 s: its per-pane throttle), no `.ov-pulse` fired
  while the latest stamp was unarmed, and at least one armed stamp got a glow of its own. FAIL (exit 3): DECISION_DRIFT (a stale
  bundle or moved code: re-read the pins first), GLOW_MISSING, GLOW_LEAK. NO EVIDENCE (exit 4):
  NO_GAME, STALE_LOG, NOT_OVERLAY, MUTED, TOO_SHORT, NO_ARMED.
  EVIDENCE CONTRACT: the grade JSON (`armed` with cue, headline_changed and glows per stamp;
  `suppressed` with cue, prev_cue, headline and class per suppressed headline change;
  `throttled`; `sustained_emergency_new_text`; game_time_s; lcu_phase; state_ts) plus the
  operator's overlay read: at least one lethal or urgent cross seen to glow on the Electron
  overlay, with the game time, and a yes / no that every `suppressed` headline (the
  `sustained_emergency_new_text` ones first) was safe to show without motion.
  SUBSTITUTION CHECK: RATIONED proves a headless page computed the decision and added the glow
  class, the compute-plus-DOM half; it runs its own previous-cue memory, not the operator's
  Electron overlay, and a class change is not a visible glow (the operator's pulseNotify setting
  and widget layout differ there). Only the operator's eyeball of the overlay plus the read of the
  suppressed list ticks G4-13; never tick on the grade alone. Grader:
  `tools/gated_g413_pulse_ration.py`, tests `tests/test_gated_g413_pulse_ration.py`.
- **G4-14** (was B39) RC2 P4.1-P4.5 composited-over-a-real-League-game eyeballs at 2560x1440
  borderless: DPI/dock sizing; opacity recede + idle dim + hover zones + drag strip; separated-window
  arrangement; `#ovset` panel selector + Interact-now; Re-arrange + Show dashboard. **P4.6 IS this
  whole-of-Phase-4 checklist.** Geometry halves are practice-acceptable; combat-driven cues want a real
  game. rc-shell MAIN relaunch (G6-01) first. Item 686 proved the 4.1 ovscale model live-buggy once.
  **AGE CHECK (lane 9 PREP s144 cycle 90, S144-G-81, source read at `a042900db`, 2026-11-06; NOT a
  tick, NOT struck; no game up: :8888 `/api/state` gave no body and the LCU phase was None at
  2026-11-06T21:47-06:00). The live residue is narrower than the row text: two of the five P4
  criteria lost their premise within a week of shipping, and a third was ruled a reload only.**
  (1) P4.1 "zoomed dock, right edge, no clip against the work area": GONE. `d97154449` (2026-06-21,
  the Overlay Doctrine) made the overlay one FULL-SCREEN transparent click-through window over the
  work area, and `98bc288bf` (item 567, the same day) re-sized it to `primary.bounds` so ovscale =
  native height / 1080 (`rc-shell/src/main.js` `createOverlayWindow`), with per-widget positions in
  `web/js/lib/overlay_layout.js`.
  There is no dock left to clip. The scale-tracking half (a display change re-sizes the window and
  reloads it at the new ovscale) is G6-04, CLOSED PASS 2026-08-02, which recorded the window at
  2560x1440 @ 0,0 live. What remains of P4.1 is an eyeball that the widgets read cleanly over a
  bright scene at that zoom.
  (2) P4.3 / P4.5 separated windows: the PREMISE IS DEAD and the code still runs.
  `resolveSeparatedCompanionBounds` (`rc-shell/src/overlay_state.js`) moves an overlapping companion
  to the side of the overlay with more free room. Against a full-screen overlay both rooms are 0, the
  tie goes left, and EVERY companion is moved to the work-area top-left (x = area.x, y = area.y,
  moved true). Measured this cycle with node over the module: overlay 0,0 2560x1440; work areas
  2560x1400 and 2560x1440; 520x900 companions at 1700,200 / 2000,300 / 0,0; all six results were
  0,0 moved true. So P4.3 (a) "fully clear of the overlay" holds for no position, and Re-arrange /
  Show dashboard (P4.5 (a) / (b)) can only park the dashboard top-left under the transparent HUD.
  The node tests on this function (`rc-shell/test/overlay_state.test.js`, the
  `resolveSeparatedCompanionBounds` block) still use a 598 px docked overlay (three docked right, one
  docked left), never a full-screen one, so they pass on a geometry that no longer exists. The
  AUTOMATIC snap is opt-in: `keepCompanion` defaults FALSE since 2026-06-27
  (`OVERLAY_SETTINGS_DEFAULTS`), `separateWindows` defaults true, and `applySurface` runs the auto
  layout only when both windows show. Re-arrange and Show dashboard (`raiseCompanion`) force the
  same snap whatever those settings say.
  (3) P4.4 (a) panel-set selector: a reload only. `applyPanelSet` reloads at `?panelset=NAME`, the
  page stamps `body[data-panelset]`, and no CSS rule keys off it (`bdb583474`, 2026-11-05, RM-1272
  item 10; pinned by `tests/snapshot_panels/test_overlay_hotkey_hints.py`
  `test_panel_sets_change_no_widget`). That commit dropped the hotkey's menu row; the #ovset
  Coach / Build / Threat segment (`web/js/panels/overlay_ds_controls.js` `_settingsHtml`) still
  offers the same no-op. "Swaps the overlay panel set" cannot pass as written; (b) "the lit segment
  matches" is a DOM fact, not a live one.
  (4) Still live and still eyeball-only: P4.2 opacity (`applyOverlayOpacity` -> `setOpacity`;
  default 1, so the recede is opt-in), click-through zones (`applyClickThrough` via
  `effectiveIgnoreMouse`; default ON), idle dim (`web/js/lib/overlay_idle.js`, `IDLE_DELAY_MS` 8000),
  and P4.4 (c) Interact now (`setOverlayActive`, auto-revert `activeRevertSec`, default 20).
  PRECONDITION: the running rc-shell main process started after the newest `rc-shell/src` commit
  it is judged on (G6-01; since the 2026-10-31 launcher cutover any app start does this; record the
  process start time).
  PREDICATE (stated before any game; operator eyeball over a real League game at 2560x1440
  borderless, overlay ON): PASS iff all four hold: (i) at #ovset Opacity 50 the HUD widgets visibly
  dim, and at 100 they return; (ii) PASSIVE with zones ON: a click on open map reaches the game,
  and the cursor over #ovset or a drag handle takes clicks with no Alt+Shift+A; (iii) Interact now
  makes the HUD take clicks, and it drops back to PASSIVE (the active glow goes out) about
  Auto-passive seconds later; (iv) after about 8 s with no coach change and no pointer the widgets
  dim, and the next coach update wakes them. FAIL on any one. P4.3, P4.5 and P4.4 (a) are NOT graded
  by a game; they wait on proposal (A) / (B) below.
  EVIDENCE CONTRACT: per item, pass or fail + local time + `liveclient` gameTime from `/api/state` at
  that minute + the #ovset values in force (opacity, auto-passive, zones) + the rc-shell process
  start time.
  SUBSTITUTION CHECK: a node test, the real-Chromium `test_overlay_view` fixture or an `/api/state`
  read shows the behavior was COMPUTED; only the eyeball over the composited game shows it RENDERED.
  A pass on (ii) with zones OFF says nothing about zones.
  PROPOSALS (a human decides; filed, not edited, because each touches `rc-shell/**` or
  `web/js/panels/`): (A) re-scope the separation rule for a full-screen overlay, or retire it; until
  then a keepCompanion-ON operator gets the dashboard snapped top-left on every in-game show. (B)
  drop or re-point the #ovset panel-set segment, as RM-1272 item 10 dropped the hotkey row. (C)
  re-base the `resolveSeparatedCompanionBounds` node tests on a full-screen overlay.
- **G4-15** (was B40) Live UI watch STANDING ritual (items 243/244): tick champ-select + in-game
  dashboard vs `/api/state` each ranked game. **Standing per-game, never one-shot - it does not close.**
  **READY (lane 9 PREP s144 cycle 91, S144-G-82, source read at `4f1027e1b`, 2026-11-06; NOT a
  tick - a standing row never ticks; no game up: :8888 `/api/state` and :2999 both curl 000 at
  2026-11-06T22:28-06:00).** AGE CHECK: the row's "in-game dashboard" names a surface the operator
  retired for in-game viewing on 2026-06-27 (memories `feedback_electron_overlay_only`,
  `feedback_companion_not_ingame_viewing_source`). In game the operator sees the rc-shell OVERLAY
  (`?overlay=1`, the full-screen transparent HUD); `applySurface` (`rc-shell/src/main.js`) hides the
  companion (the `:8888` dashboard window) on the in-game surface unless the `keepCompanion` setting
  is on, and that defaults OFF (`OVERLAY_SETTINGS_DEFAULTS.keepCompanion: false`,
  `rc-shell/src/overlay_state.js`; the comment above `applySurface` still says "default ON" - stale,
  the defaults object wins). So the ritual is two surfaces per game: the COMPANION at champ select,
  the OVERLAY in game. A companion glance mid-game counts only if the operator turned keepCompanion
  on; record which. The 2026-06-01 item-244 watch that set this ritual checked the build chooser
  (3 paths + userbuild), DS-vs-enemy-comp with no junk rows, the summoners, and the post-game ingest
  row; the post-game half is the G7 rails' business, not this row's.
  **PER-GAME CARD (ranked SR q420 per the gate header; any SR game serves the UI half).**
  (1) CHAMP SELECT, after the local pick locks: `curl -sk https://127.0.0.1:8888/api/state` once.
  PREDICATE (stated before any game): `cs_archetype_pick.champion` is non-empty and names the locked
  champion (stamped from the champ-select `my_champion` id, `dashboard/_state_builder.py`, the
  item-244 F1 fix); the companion's champ-select view (`renderChampSelectView`,
  `web/js/panels/champ_select.js`) shows that champion and a non-empty build chooser. FAIL iff the
  view names another champion than the state, or shows an empty build chooser while the state
  carries a pick.
  (2) IN GAME, past 3:00 game time. In-game = a non-empty `liveclient` or LCU phase InProgress, never
  `mode_key` alone (`tools/gated_live_probe.py` reports in-game iff `mode_key` is in its live set AND
  `liveclient` is non-empty). Run `python tools/gated_live_probe.py --json > <evidence>.json`,
  read `/api/state` `liveclient.level`, `liveclient.cs` and `liveclient.kda` (the "k/d/a" string)
  from one `curl` of the same moment, and within 10 s glance at the overlay Stats widget (`w-stats`,
  `#am-statspanel`) "You" row: `lvl` = `liveclient.level`, `cs` = `liveclient.cs`, `kda` = the RATIO
  (k+a)/max(d,1) of `liveclient.kda` (`renderStatsPanel` -> `_kdaRatio`, `web/js/panels/stats_panel.js`),
  NOT the k/d/a string, shown to 1 decimal by `_fmt` when not whole. PREDICATE: each cell equals
  the state value (kda: the rounded ratio), or trails it by at most one
  game event (a kill or a CS that landed between the curl and the glance). FAIL iff a cell is AHEAD
  of the state, shows another player's value, or holds still across two curls 60 s apart while the
  state moved (an overlay render or poll freeze; NOT G4-19's class, which is the server cache
  collapsing `liveclient` to `{}`, so the state would not move). A "-" cell while the state carries
  the value is a FAIL; "-" with the field null in the
  state is the honest absent state, not a defect.
  (3) EVIDENCE CONTRACT, one line per game appended under this row: both values per field (state and
  painted), the state field path and the widget id, ISO time + `game_time`, mode + queue, and the
  surface (companion / overlay / companion with keepCompanion on). SUBSTITUTION: the probe JSON
  proves only what the server SERVED; this row is the glance that the overlay PAINTED it. A probe
  with no glance records nothing here, and a capture of a view rendered from the same state is the
  substitution kill.
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
  **READY for the two owed chips, C2 antiheal and C4 `hp_vs_pen` (lane 9 PREP s144 cycle 73,
  source read at `08822072c`; NOT a tick; no game up: :8888 and :2999 curl 000 at
  2026-11-05T21:19-06:00).** C3, C5 and C6 stay as seen on 2026-07-20; this block readies only
  the two still owed. AGE CHECK: NOT stale. `_counterChip` still paints `.counter-chip` chips
  (`--ok` when satisfied, else `--gap`; `--high` for severity high) into `.counter-strip` inside
  the BUILD pane `#am-build-body` (`_renderAmBuildBody`); `overlay.css` hides ds-sweep /
  ds-matchup / ds-combo / ds-relscore in the overlay BUILD pane, not this row, so the same
  chips ride the overlay `w-build` widget. Source facts the eyeball must know (pinned in
  `tests/test_gated_g416_counter_chips.py`):
  (a) The hints depend only on the roster, items, scores, levels and the coach `level`, never
  on the champion or the mode (those feed the DS plan); an empty coach champion answers
  `no_champion` with no hints at all.
  (b) C2 fires at `heal_sources >= 2` (`HEAL_THRESHOLD`; curated sustain champions plus
  distinct enemy heal items, `core/heal_threat.py` `count_heal_sources`) and ONLY while no
  my-team item applies Grievous Wounds (`ally_has_antiheal`, its Grievous set includes
  Thornmail, Bramble Vest and Chemtech Putrifier). While `_resolveMyTeam` resolves my team,
  the client's `_extractBpAllyItems` keeps every row on my team, MY OWN ROW INCLUDED, and
  every BASE-id item the chip's `satisfied` test counts as antiheal is also in that Grievous
  set, so the C2 chip does not paint in its `--ok` state: buying the counter (me or an ally)
  makes the chip VANISH. `--ok` is reachable only when the team is unresolved (`ally_items`
  empty while `items`, filled by the server's own name match, still holds my Grievous item;
  the grader refuses that as ROSTER_BAD) or if the feed ever reports a 22-prefixed alias id
  (`_ANTIHEAL_NAMES` matches those by name, the Grievous set holds base ids only). So the C2
  eyeball is a `--gap` chip "ANTIHEAL" with detail "<n> enemy heal sources" while nobody on
  my team owns a Grievous item, and, as the dedup half, the chip gone once one is bought
  (filed provisionally as RM-1663 for the merger to mint or decline: with the team
  resolved the `--ok` state is dark, so the chip never confirms a bought counter; a
  code-lane question, not edited here).
  (c) C4 fires at `enemy_pen >= 0.5` (`PEN_HINT_CUT`; two or more enemy lethality or
  percent-pen items, e.g. Lord Dominik's + Serylda's, saturating at four) AND only when MY
  build already holds armor or MR; satisfied (`--ok`) = my item HP >= 300 (`HP_HINT_FLOOR`).
  A lethality enemy comp against a no-resist build shows no HP chip, correctly.
  (d) Off LCU phase InProgress `renderActiveMatch` returns at the CALL pane, before the BUILD
  pane, so the COUNTER row keeps its last paint after the game ends (same class as
  RM-1662); the fetch fires at once on a roster / item / score key change (unless one is
  in flight) and re-fires every 4 s with no change (`_BUILD_PLAN_COOLDOWN_MS`), landing on
  the next render, so a capture right after a purchase can be one fetch behind. And the
  retain guard (`_shouldRetainBuild`): while the Daemon Slayer, Meta and Ultimate rows are
  all empty (DS :8860 down or empty) and the pane already holds a paint,
  `_renderAmBuildBody` returns before the COUNTER row, so hints that land after the first
  paint never show; the snippet counts the filled row items (`build_items`) and the grader
  calls a freeze over an empty-row or static-placeholder pane RETAINED (no evidence: get DS
  answering first), not a mismatch. A freeze over an earlier FILLED paint (every row cache overwritten later by an
  ok-but-empty reply; the caches are never reset, so DS going down after a filled paint does
  not trigger it) still shows filled rows and grades RENDER_MISMATCH; that is why the one
  re-capture in step (2) uses a FRESHLY opened page, which turns it into RETAINED or a real
  repaint.
  (e) The same live-only roster risk as G4-12: when `_resolveMyTeam` finds no activePlayer
  name match it returns null, all 10 players are posted as enemies and `ally_items` is
  empty, so my own sustain and pen items feed C2 and C4; the grader refuses that first.
  (f) The BUILD pane's repaint signature keys the hints on `criterion:satisfied` only, so a
  chip whose DETAIL changes alone (C2's heal-source count after an enemy heal-item buy) may
  stay on the old text until another signature input moves; the grader names that
  DETAIL_LAG, not RENDER_MISMATCH (filed provisionally as RM-1664, code lane; plausible
  from source, not yet seen live). The grader grades an exact `lcu.phase` InProgress only,
  and its in-process path cannot see a route ok:false (step (4) can, as PLAN_ERROR).
  PROBE (real SR game, or ARAM, with a comp carrying 2 or more sustain sources for C2 and 2
  or more enemy pen items while I hold armor or MR for C4; one minute, repo root):
  (1) `curl -sk https://127.0.0.1:8888/api/state > _scratch/g416_state.json`;
  (2) in a HEADLESS Chromium page on `https://127.0.0.1:8888/` (ignore cert errors, Active
  Match view), open at least 10 s, evaluate `python tools/gated_g416_counter_chips.py snippet`
  and save the JSON as `_scratch/g416_dom.json` within 5 s of (1); on a first RENDER_MISMATCH
  re-run (1) and (2) together once, (2) on a freshly opened page left 10 s (the fetch can be
  one behind, and a fresh page clears a retain-guard freeze), before it counts;
  (3) `python tools/gated_g416_counter_chips.py grade --state _scratch/g416_state.json --dom
  _scratch/g416_dom.json --state-ts <epoch of (1)> --json` (expected computed in-process
  through the route's own helpers);
  (4) optional served cross-check: `python tools/gated_g416_counter_chips.py body --state
  _scratch/g416_state.json > _scratch/g416_body.json`, then `curl -sk -X POST
  https://127.0.0.1:8888/api/build-plan -H "Content-Type: application/json" -d
  @_scratch/g416_body.json > _scratch/g416_plan.json`, then (3) again with `--plan
  _scratch/g416_plan.json`; the two verdicts must agree;
  (5) the operator, on the overlay `w-build` widget within the same minute: the COUNTER chips
  read aloud or typed (label, detail, green or amber), then ONE yes / no per owed chip: is
  ANTIHEAL right for the enemy healers on the scoreboard, and is HP right for the enemy pen
  items shown?
  FIELD PATHS: `/api/state` -> `mode_key`, `lcu.phase` (InProgress), `coach.champion`,
  `coach.level`, `liveclient.activePlayer`, `liveclient.allPlayers[].team / championName /
  items[].itemID / scores / level`, `liveclient.owned_item_ids`, `liveclient.enemy_team`,
  `liveclient.game_time_s`; `/api/build-plan` -> `ok`, `counter_hints[].criterion / label /
  detail / satisfied / severity`; DOM -> `#am-build-body .counter-strip .counter-chip`
  `.counter-chip-label`, `.counter-chip-detail`, class `counter-chip--ok` / `--high`,
  computed `display`, bounding box, `offsetParent`.
  PREDICATE (stated before any game): a chip half PASSES iff the grader prints RENDER_MATCH
  (team resolved, exactly 5 posted enemies equal to the server `enemy_team`, the coach
  champion equal to my roster row, every expected chip painted in order with the same label,
  detail, ok / gap and high state) with `owed_cases` naming it (`antiheal`, `hp_vs_pen`, or
  `antiheal_dedup` for the dedup half), AND the operator's overlay read names the same chip
  AND the operator answers yes. FAIL iff ROSTER_BAD, PANE_ABSENT, PLAN_ERROR or
  RENDER_MISMATCH (after the one re-capture), or the operator answers no (record the 5
  enemies, `inputs` and `expected`). DETAIL_LAG is a finding for RM-1664 (record `expected`
  and `painted`), not a pass; re-capture after my next purchase (owned names are a
  signature input). NO_GAME, RETAINED, STALE_DOM, NO_HINT_CONSISTENT or NO_OWED_CHIP (render
  consistent, but the comp warrants neither owed chip) = no evidence: re-sample in a sustain
  or pen comp, never a pass.
  EVIDENCE CONTRACT: the grader JSON (verdict, `owed_cases`, `my_champion`, `posted_champion`,
  `enemies`, `inputs` with `heal_sources` / `ally_has_antiheal` / `enemy_pen_item_ids` /
  `my_has_resist` / `my_item_hp`, `expected`, `painted`, `game_time_s`, `state_ts`, `dom_ts`,
  `expected_source`), the operator's overlay read with its local time, and the yes / no per
  chip, with mode, queue and `game_time_s`. Champion names and item ids only: never a player
  name, game id or puuid (RM-906).
  SUBSTITUTION: `counter_hints` (served or in-process) is the COMPUTE half, and RENDER_MATCH
  only shows the dashboard painted what was computed; neither answers the row. The row is
  answered only by the operator's overlay read plus the yes / no that the chip is right for
  the comp on screen, in a live game. A `?ui_mock=1` render seeds the roster from a fixture
  and proves nothing here; a chip seen after the game ends is the stale last paint, not a
  pass. Grader: `tools/gated_g416_counter_chips.py`, tests
  `tests/test_gated_g416_counter_chips.py`.
- **G4-17** (was the 2026-07-16 Slice B addendum) DS Slice B on-hit AP scorer OVERLAY RENDER eyeball -
  confirm the new `ds.onhit` build order (Nashor's Tooth present) actually renders on the in-game
  overlay build panel in a real **Gwen / Kayle / Kog'Maw** game. Backend + `/api/build-plan` already
  PROVEN live (scorer=onhit, Nashor's present; Syndra=ability / Akali=burst controls held). The
  Electron overlay is agent-blind, so this is operator-only. SOURCE: LEDGER 911, ENGINE 1.216.0.
  **READY (lane 9, s144 cycle 74, PREP only, NOT ticked; no game up: :8888 and :8860 curl empty
  at 2026-11-05T22:00-06:00, health.json last updated 2026-11-01).** AGE CHECK: the row is not
  stale but its "backend proven" half was proven on the WRONG ROUTE for a render question.
  Source facts (pinned in `tests/test_gated_g417_onhit_render.py`): (a) `/api/build-plan` (LEDGER
  911's live proof) feeds only the per-icon state badges and the COUNTER chips of the BUILD pane
  `#am-build-body`; the three painted item rows come from `POST /api/ds-preview` `ranked` ("Daemon
  Slayer", `.bm-live`, `_maybeRefreshDsPicks`, falling back to the coach payload's
  `daemon_slayer_picks` while the preview cache is empty) and `POST /api/build-order` `order`
  ("Meta Build" `.bm-meta` with my items and level; "Ultimate Build" `.bm-ult` at level 18, no
  items). So no live proof exists yet that the route the Daemon Slayer row paints serves onhit
  with Nashor's. (b) All three routes take the scorer from `get_archetype_for(champion)
  ["primary"]` (the client never sends an archetype): `onhit` for Gwen / Kayle / KogMaw by
  default, but a persisted operator pick in gitignored `data/cs_archetype_picks.json` wins, so only
  the served reply's `scorer` proves the onhit route ran. (c) The Daemon Slayer row = the preview's
  `top` 8 family-deduped, capped at 7 (`_BM_SLOT_CAP`), then the in-memory overrides and MUTE
  (`filterSilenced` DROPS a silenced item from this row only), then owned sorted left; a headless
  page has no overrides. (d) An owned Nashor's is not in the preview's ranked rows, so read it
  BEFORE the buy; a full build answers `build_complete` (scorer `dps`, not a drift). (e) The Meta /
  Ultimate requests echo an `incumbent` for hysteresis that a curl cannot reproduce, so those two
  rows are ADVISORY; only the Daemon Slayer row is graded strictly. Gwen (coherence 1.0, Nashor's
  #5 on `/rank-onhit` in LEDGER 911) is the strongest test; Kayle sits at 0.3.
  PROBE (real SR or ARAM game as Gwen / Kayle / Kog'Maw, before Nashor's is bought, DS :8860 up;
  repo root): (1) `curl -sk https://127.0.0.1:8888/api/state > _scratch/g417_state.json`; (2) in a
  HEADLESS Chromium page on `https://127.0.0.1:8888/` (ignore cert errors, Active Match view, open
  at least 10 s) evaluate `python tools/gated_g417_onhit_render.py snippet` and save the JSON as
  `_scratch/g417_dom.json` within 5 s of (1); (3) `python tools/gated_g417_onhit_render.py bodies
  --state _scratch/g417_state.json` and POST its `ds_preview` body to `/api/ds-preview` (save
  `_scratch/g417_preview.json`), optionally `build_order` and `ultimate` to `/api/build-order`
  (`_scratch/g417_order.json`, `_scratch/g417_ult.json`); (4) `python
  tools/gated_g417_onhit_render.py grade --state _scratch/g417_state.json --dom
  _scratch/g417_dom.json --preview _scratch/g417_preview.json [--order ... --ultimate ...]
  --state-ts <epoch of (1)> --json`. On a first RENDER_MISMATCH re-run (1)-(4) once on a freshly
  opened page (the 4 s preview cooldown can leave the row one fetch behind).
  PREDICATES, stated before any game: RENDER_MATCH (exit 0) iff every supplied reply is ok with
  scorer `onhit`, Nashor's (3115, or a fallback tile named Nashor's Tooth) is painted, visible
  and unclipped in the Daemon Slayer row exactly when the preview ranks it in the shown 7, and
  at least one row paints it. FAIL (exit 3): SCORER_DRIFT, RENDER_MISMATCH, PLAN_NO_NASHOR (no
  reply ranks it: a DS question at this state, not a render bug), NASHOR_DARK, PLAN_ERROR,
  ROSTER_BAD, PANE_ABSENT. NO EVIDENCE (exit 4): NO_GAME, STALE_DOM, NOT_ONHIT_CHAMP, FULL_BUILD,
  NASHOR_OWNED, EMPTY_ROWS.
  EVIDENCE CONTRACT: the grade JSON (scorers, rows_with_nashor, painted and expected ids,
  game_time_s, lcu_phase, state_ts) plus the operator's overlay read: which overlay row shows the
  Nashor's icon, at what game time, and a yes / no that it is the onhit build.
  SUBSTITUTION CHECK: RENDER_MATCH proves the dashboard page painted what the preview computed,
  which is the compute half again; the headless page is not the Electron `w-build` widget (its
  own 412 px width, overrides and MUTE live only in the overlay page), so its clip read is
  dashboard-only. Only the operator's eyeball of the overlay ticks G4-17; never tick on the
  grade alone.
- **G4-18** Jhin AS-lock full lethality eyeball (`c904ddae`) - the Boots of Swiftness half was
  live-confirmed; the lethality core eyeball remains.
  **READY (lane 9, s144 cycle 75, PREP only, NOT ticked; no game up: :8888 curl status 000 at
  2026-11-05T22:28-06:00).** AGE CHECK: not stale. The premise still holds at source:
  `core/ds_champion_fight_length.py` maps `"jhin": 0.5`, the carry branch of
  `rank_for_primary_archetype` (`core/daemon_slayer_client.py`) applies it and serves scorer
  `dps`, Jhin's default primary is `carry`, and `core/build_order.py` keeps `"Jhin": "3009"`
  (Swiftness). Source facts (pinned in `tests/test_gated_g418_jhin_lethality.py`): (a) the three
  painted rows are read exactly as G4-17 reads them; the tool reuses G4-17's DOM snippet, client
  bodies and Daemon Slayer row derivation (family dedupe, 7 cap) by import, so the two cannot
  drift. (b) The burst blend rides only the carry branch, and a persisted operator pick in
  gitignored `data/cs_archetype_picks.json` wins over the default, so only a served scorer `dps`
  proves it ran. (c) "Lethality item" = an engine record with `lethality > 0`
  (`agents/daemon_slayer/_effects_data.py` `ITEM_EFFECTS`; Hubris 6697, The Collector 6676,
  Youmuu's 3142, Axiom Arc 6696 among them). The core the shipped claim names also holds
  Infinity Edge 3031 and Serylda's 6694, which carry no lethality: they are reported as
  `named_core_painted` context, never graded. (d) An owned lethality item is not in the preview's
  ranked rows, so the Daemon Slayer row is compared on non-owned tiles only; a fallback tile with
  no icon is resolved by name to its SR id. (e) Meta / Ultimate are ADVISORY (incumbent
  hysteresis, as in G4-17), and Runaan's (3085) ranked above every lethality item in the preview
  is an advisory line, since the shipped claim puts it below the core.
  PROBE (real SR or ARAM game as Jhin, DS :8860 up; repo root): (1) `curl -sk
  https://127.0.0.1:8888/api/state > _scratch/g418_state.json`; (2) in a HEADLESS Chromium page on
  `https://127.0.0.1:8888/` (ignore cert errors, Active Match view, open at least 10 s) evaluate
  `python tools/gated_g418_jhin_lethality.py snippet` and save the JSON as
  `_scratch/g418_dom.json` within 5 s of (1); (3) `python tools/gated_g418_jhin_lethality.py
  bodies --state _scratch/g418_state.json`, POST `ds_preview` to `/api/ds-preview`
  (`_scratch/g418_preview.json`), optionally `build_order` and `ultimate` to `/api/build-order`
  (`_scratch/g418_order.json`, `_scratch/g418_ult.json`); (4) `python
  tools/gated_g418_jhin_lethality.py grade --state _scratch/g418_state.json --dom
  _scratch/g418_dom.json --preview _scratch/g418_preview.json [--order ... --ultimate ...]
  --state-ts <epoch of (1)> --json`. Take one sample before the first lethality buy and one after
  the second; on a first RENDER_MISMATCH re-run (1)-(4) once on a freshly opened page.
  PREDICATES, stated before any game: RENDER_MATCH (exit 0) iff every supplied reply is ok with
  scorer `dps`, the Daemon Slayer row paints exactly the preview's non-owned lethality items in
  the shown 7, every painted lethality tile is visible and unclipped, and at least one row paints
  one. FAIL (exit 3): SCORER_DRIFT, RENDER_MISMATCH, PLAN_NO_LETHALITY (no reply ranks one: a DS
  question at this state, file it, not a render bug), LETHALITY_DARK, UNMAPPED (Jhin lost his
  fight_length: re-read LEDGER 870 first), PLAN_ERROR, ROSTER_BAD, PANE_ABSENT. NO EVIDENCE (exit
  4): NO_GAME, STALE_DOM, NOT_JHIN, FULL_BUILD, EMPTY_ROWS.
  EVIDENCE CONTRACT: the grade JSON (scorers, fight_length, lethality_expected,
  lethality_painted, rows_with_lethality, named_core_painted, swiftness_rows, advisory,
  game_time_s, lcu_phase, state_ts) plus the operator's overlay read: which lethality icons the
  overlay BUILD rows show, at what game time, and a yes / no that the build reads as the
  lethality-crit path (Hubris / Collector / Youmuu's) rather than a sustained on-hit one.
  SUBSTITUTION CHECK: RENDER_MATCH proves the dashboard page painted what the preview computed,
  the compute half again, and the engine-confirmed "plan_build_order leads Hubris" of LEDGER 870
  is compute too; the headless page is not the Electron `w-build` widget (its own width,
  overrides and MUTE), so its clip read is dashboard-only. Only the operator's eyeball of the
  overlay ticks G4-18; never tick on the grade alone. Grader:
  `tools/gated_g418_jhin_lethality.py`, tests `tests/test_gated_g418_jhin_lethality.py`.
- **G4-19** Overlay `liveclient_cache` self-heal live re-verify (`03868b03`).
  **READY (lane 9, s144 cycle 63, RM-1509, PREP only, no game up: RC :8888 refused, re-probed
  2026-11-05 about 00:50-00:53 -06:00; NOT ticked).** Source facts (pinned in
  `tests/test_gated_g419_cache_freeze.py`): `/api/state.liveclient` IS
  `liveclient_summary()` (`dashboard/_state_builder.py` `"liveclient": lc`), which returns `{}`
  when `snap.data is None or snap.age_s > 5` (`dashboard/_liveclient.py`); `Snapshot.age_s` is
  measured from the RELAY's `ts` (`core/liveclient_cache.py` `observation_age(self.ts, ...)`), not
  from the cache's last fetch. **Three traps the probe closes (two found by the c63 verifiers):**
  (1) an empty `liveclient` has FOUR causes: a frozen cache (THIS row); a stale relay (the separate
  "5s TTL vs 8-11s capture" bug at the head of this doc); `liveclient_summary()` raising, which its
  outer `except` turns into `{}` with nothing logged (end of `liveclient_summary`); and RC's own
  relay fetch failing (401, 2 s timeout, parse, error body: `_fetch_once` publishes `data=None`).
  The probe reads the relay itself, which excludes the stale relay only; the other three stay
  listed in the verdict (`causes_not_excluded`), so it says FREEZE_CANDIDATE, never "frozen". In TFT
  an empty summary is replaced by the `tft_standalone` fill-in (`dashboard/_state_builder.py`,
  `mode_key == "tft"`), which would mask a freeze; the probe counts that source as empty.
  (2) **The commit's own "live-verified: after an RC restart /api/state.liveclient repopulated (29
  keys)" is a SUBSTITUTION:** a supervisor restart is a new process with fresh module state
  (`_task` None), so it never runs `_task_alive()` / `_on_task_done`; the fix path runs only when
  the poll task ends INSIDE a live process. (3) a dev-runtime module reload
  (`ops/rc_dev_runtime.py` `_reload_modules`) also resets `_task` and logs a start with no line of
  its own, so `respawns` voids its read when a result file under `ops/runtime/control/results`
  names `core.liveclient_cache` since the process start (today that module is NOT on the
  dev runtime's safe-reload list, so such a request is refused, and the refusal file still voids
  the read: the guard can only over-void); it counts only the async-task start line (the thread
  fallback is not the fix path).
  PROBE (read-only, any time during the game): `python tools/gated_g419_cache_freeze.py sample
  --samples 60 --interval 2 [--json]` (GETs :8889 `/latest-liveclient` with the token and :8888
  `/api/state`; per sample: relay age, `liveclient` key count, gameMode, gameTime; prints no id).
  Classes: OK (relay age <= 5 s, `liveclient` non-empty), EMPTY_WHILE_FRESH (relay age <= 2.5 s,
  `liveclient` `{}`), RELAY_STALE (relay age > 5 s: not this row), AMBIGUOUS (2.5-5 s or untimed),
  NO_GAME / RELAY_DOWN / DASH_DOWN. Then `python tools/gated_g419_cache_freeze.py respawns`
  (reads the main checkout's `ops/runtime/health.json` `started_at`, that day's log and the
  dev-runtime result files; an async `liveclient_cache started` line more than 90 s after the
  process start, with no module reload since, is an in-process respawn; pass `--log` for a game
  after midnight). Idle smoke this cycle: `sample` = NO_EVIDENCE (RELAY_DOWN x2, RC down);
  `respawns` (final version) = 1 boot start, 0 respawns, 0 module reloads, exit 4.
  PREDICATE (stated before any game): **FAIL CANDIDATE** = `sample` verdict FREEZE_CANDIDATE (3+
  consecutive EMPTY_WHILE_FRESH spanning >= 10 s; since `03868b03` the next `get()`, about 2/s from
  `/api/state`, respawns a dead task, so a healed freeze lasts about a second, and 10 s outlasts a
  few 2 s fetch timeouts) in a real game. It NEVER re-opens `03868b03` by itself: the main session
  triages the three causes (logs/ `rc.liveclient_cache` warnings in the window; whether a fresh
  process clears it, which a freeze or a transient fetch failure would and a summary exception on
  that frame shape would not) and files what it finds.
  **PASS needs all three:** (a) `sample` HEALTHY (>= 10 OK, no candidate streak) over a window that
  covers the moment after any mid-game RC restart (the restart is the main session's or the
  operator's act, never a lane's); (b) `respawns` exit 0 (`self_heal_exercised: true`) in that same
  process, or the row records "self-heal NOT EXERCISED this game" and stays open, because HEALTHY
  alone proves only that nothing froze; (c) the operator's eyeball that the in-game overlay left the
  dashboard (the RENDER half: the Electron overlay is agent-blind, and `health.overlay_visible` is
  known to read FALSE while visible, bug 7 at the head of this doc).
  EVIDENCE CONTRACT: the `sample` JSON verdict + counts + first/last gameTime + gameMode, the
  `respawns` JSON, the local time of any restart, and the operator's one-line overlay statement.
  SUBSTITUTION CHECK: does the evidence show the cache recovered from a task that ended INSIDE a
  live process and the overlay then RENDERED, or only that a fresh process polled? A fresh boot,
  a unit test (`tests/test_liveclient_cache_task_respawn.py`) or a HEALTHY window with no respawn
  line answers the compute half only.

### `[BATCH CV/OBS]` - needs rendered in-game pixels

- **G4-20** (was H1) OBS request/response POC (O1) + frame-source swap (O2): GetSourceScreenshot
  round-trip via OBS-WS v5, then swap the occlusion-proof WGC capture into `vision_server/_frame.py`
  (config-gated GDI fallback). O1 ~1 session, O2 ~1-2 sessions. SOURCE: docs/OBS_CV_MINIMAP_PLAN.md:54-70.
  **AGE CHECK (lane 9 PREP s144 cycle 79, RM-1668, source read at `e3a356f2e`, 2026-11-06; NOT a
  tick, NOT struck; no game up: :8888 and :2999 curl status 000 at 2026-11-06T00:28-06:00): O1 is
  BUILT; O2 shipped on the mechanism its own SOURCE later ruled out, so the row stays an open
  BUILD.** O1 is `core/obs_frame_source.py` (`49dd1ab7a`, 2026-07-05: the OBS-WS
  `GetSourceScreenshot` fetch behind `get_obs_frame`, fail-soft to None). The shipped O2 is the
  OBS-first branch of the self-grab in `vision_server/_frame.py` (`obs_frame_source_enabled` then
  `get_obs_frame`; None, an undecodable frame or a blank frame falls to GDI);
  `core/minimap_blob_detect.py` reads the same lane. LEDGER 796 (2026-07-05, `b4254f2b`) live-validated
  that round trip in practice SR and flipped `obs.frame_source` ON, and the 2026-07-20 drain header
  records G2-42 (c), frame `source='obs'`. BUT the SOURCE this row cites was CORRECTED on 2026-07-28
  (`f6ed5cdd6`, `docs/OBS_CV_MINIMAP_PLAN.md` O2 entry): OBS Game Capture injects
  `graphics-hook64.dll`, the technique Vanguard bars, and ADR-011 (decision 4) already ruled OBS on
  Display Capture (WGC), not Game Capture. The corrected O2 prefers taking Windows.Graphics.Capture
  directly, which was never built (no `.py` in the index names WGC or `windows_capture`), and names a
  BLOCKING PREREQUISITE: confirm the client's Window Mode first (`WindowMode=2` has been recorded as
  three different modes, and WGC is not guaranteed under exclusive fullscreen). Both pieces of live
  evidence above predate that correction, so they prove the OBS round trip, not the corrected swap.
  Idle read (main checkout's gitignored config, 2026-11-06): `obs.frame_source` true,
  `obs.frame_source_name` `Game Capture`, `obs.enabled` false; the gate reads `frame_source` alone
  (`obs_frame_source_enabled`), so the fetch is tried on every self-grab and falls to GDI while OBS
  is down. Whether that OBS source is a Game Capture or a Display Capture source is an OBS-side fact
  the repo cannot read; the name alone does not settle it. Nothing here is drainable by a game: the
  next act is the Window Mode confirmation, then the WGC build. FILING RM-1668 (main session, not
  this row's verdict): the shipped flag ON and the configured source name sit against ADR-011
  decision 4; a human confirms the OBS source type.
- **G4-21** (was H2) CV #7-10 new deterministic OCR/template modules: stateful ability-cooldown sweep
  tracker (cast-signal proxy), recall-channel bar read, objective (drake/baron/elder) icon+timer CV,
  item-completion template-match. Multi-session; each needs live calibration.
  **AGE CHECK (lane 9 PREP s144 cycle 79, RM-1668; NOT a tick): still a BUILD, not drainable.**
  Only the shared substrate for #8 and #10 exists: `core/vision_template_match.py` (`6589690b4`,
  2026-07-10), which its own docstring calls default-OFF and NOT wired into the live loop (importers:
  the atlas precompute, `tools/vision_atlas_validate.py` and the tests). No module exists for #7
  (cooldown sweep) or #9 (recall bar) (`docs/OBS_CV_MINIMAP_PLAN.md:104-107` rows). No game can
  drain a module that is not built or not wired, so there is no probe to ready here.
- **G4-22** (was H3) **THE UNSOLVED ZOI CORE.** Minimap champion IDENTITY via `cv2.matchTemplate`
  (Wave-2/3 over the blob centroids vs ~10 in-game champ templates): needs the opencv-python dep +
  live occlusion testing. Template-match hit only **1/13 on live ARAM = the clustering wall**. This is
  a multi-session BUILD, not an eyeball. Wave-2/3 depends on Zone-1 districts.
  **AGE CHECK (lane 9 PREP s144 cycle 79, RM-1668; NOT a tick): the BUILD shipped, and the 1/13
  is older than it.** `core/minimap_identity.py` (`968a7e667`, 2026-07-05) is the circle-masked
  `cv2.matchTemplate` plus masked-Pearson identity pass, roster-scoped to the Live Client names;
  `1fd338542` (2026-07-08) turned it default ON (`RC_ZOI_IDENTITY`, `core/minimap_blob_detect.py`
  `_identity_enabled`), and it feeds `zoi.champion_dots` (`dashboard/_state_builder.py`). The
  opencv dep is pinned (`requirements.txt`, `opencv-python==5.0.0.93`). The "1/13" line entered this
  doc on 2026-07-06 (`8fb6dc3ac`), before the LEDGER 871 champion-size floor and per-team clamp
  (`b4ddedd1`, 72->8 / 62->10 / 74->10 dots) and before the default-ON flip, so it measures a
  pipeline that no longer runs. What is open is a live RE-MEASURE of identity hit rate on the
  current pipeline, and it has no machine ground truth: the Live Client gives roles, not minimap
  positions. PROPOSED PREDICATE (stated before any game; a human promotes it): over at least 3
  timed overlay minimap frames from one game, the operator labels each visible champion icon, and
  PASS iff at least 70 pct of the `zoi.champion_dots` entries carrying a `champion` tag at that
  frame's `ts` name the icon under them. SUBSTITUTION CHECK: a `champion` tag on a dot, or a
  matcher test on pasted icons, shows only that identity was COMPUTED; whether it is RIGHT needs
  the labelled frame. A frame whose `ts` is not inside the game (load screen, alt-tab) is no result.
- **G4-23** (was H5) L-01 vision-base-capture live re-validation: the alt-tab base-clobber fix
  (`eece8500`, grab base only when League is foreground + once per config) was code-fixed + TDD-tested
  but NEVER re-validated in a live game (base was restored from a still, not re-grabbed clean in-game).
  Also the open auditor proposal to add a `validate_base()` guard to `routes_vision_calibrator.py`.
  **READY (lane 9, s144 cycle 77, RM-1666, PREP only, no game up: RC :8888 and :2999 refused,
  re-probed 2026-11-05 about 23:28 -06:00; NOT ticked).** AGE CHECK: the `validate_base()` half
  is STALE, shipped the same day as the fix (`ffba931c7`, 2026-07-05: `core/vision_profiles.py`
  `validate_base`, called from `dashboard/routes_vision_calibrator.py` `vp.validate_base`), so only
  the live re-validation is left. Source facts (pinned in `tests/test_gated_g423_base_capture.py`):
  the self-grab in `vision_server/_frame.py` calls `save_reference_image(img)` with no force, and the
  auto path saves only when (a) `health.json` `has_game`, (b) the foreground process is
  `League of Legends.exe`, (c) no base still exists yet for the active `config_key`, in that order.
  **Two traps the probe closes:** (1) gate (c) MASKS gate (b): every still under
  `data/vision_calib_reference/` was written 2026-07-05 / 2026-07-06 (two post-date the fix: the
  1.6200 base at 22:45, which this row says was restored from a still, and the 3.0000 base at
  07-06 01:51, auto or manual unknown), none in the four months since, so
  "the base did not change while I alt-tabbed" on a calibrated config is a SUBSTITUTION: the
  once-per-config gate refuses before the foreground is consulted. The check is ARMED only when the
  active config has NO base still at the first sample (a HUD value never played, e.g. a
  MinimapScale missing from the `refs` list, set in the client BEFORE queueing). (2) a forced write
  (the `/vision-calibrator` refresh, `capture_reference`, a named-state ingest) bypasses all three
  gates and looks like an auto write on disk: nobody touches the calibrator during the window.
  **Idle finding (RM-1666, a FILING for the main session, not this row's verdict):** at idle the
  active `config_key` reads `unknown`, because League's game.cfg (mtime 2026-10-25) carries no
  `[General]` Width/Height (its other General keys, `WindowMode` among them, are present), so `core.hud_settings.read_hud_settings` cannot key
  a profile. If an in-game `refs` read still says `unknown`, the self-grab would file the still as
  `unknown.jpg` and every HUD profile lookup falls back; the grader calls that window AMBIGUOUS.
  PROBE (read-only): before queueing, `python tools/gated_g423_base_capture.py refs` (active key,
  `armed`, every still with its write time and sha12); then from the load screen, `python
  tools/gated_g423_base_capture.py watch --samples 150 --interval 2 --json` (per sample:
  `has_game`, foreground-is-League, `armed`, every still's sha12 + meta `ts`). The operator
  alt-tabs to the desktop as soon as the game is in (has_game true) and stays out at least 10 s,
  then returns to League; nothing else.
  PREDICATE (stated before any game): **FAIL** = FAIL_CLOBBER (a new base still with League NOT
  foreground on both bracketing samples), FAIL_NO_GAME (has_game false on both sides),
  FAIL_REGRAB (any still, once seen in the window, changes sha or meta ts, the new still after its
  own write included: gate (c) broken, or a forced write to triage; a still that vanishes VOIDs
  the window), or NO_WRITE_WHILE_ELIGIBLE (armed, in game, League foreground 60 s, no
  write: triage the self-grab capture gates on vision `/status`). **PASS needs both:** (a) `watch`
  PASS_CANDIDATE: armed at the first sample, at least 3 samples spanning 6 s of has_game + NOT
  League + still absent on the SAME config_key (the alt-tab was exercised and nothing was
  written), then exactly one new
  base still for the active key with has_game + League foreground on both bracketing samples and
  its meta `ts` inside the bracket; (b) the operator's eyeball of that still: an in-game HUD frame,
  not a desktop and not a load screen (the pixels are the RENDER half; the grade cannot see them).
  GATE_C_MASKED / NOT_EXERCISED / AMBIGUOUS / VOID / NO_EVIDENCE leave the row open.
  EVIDENCE CONTRACT: the `refs` JSON before the game, the `watch` JSON verdict + bracket +
  `alt_tab` stretch, gameMode + queue, the local time of the alt-tab, and the operator's one-line
  statement about the still. SUBSTITUTION CHECK: does the evidence show the foreground gate
  REFUSED a write during a real alt-tab and then a clean in-game still was written, or only that an
  already-calibrated still sat unchanged? The latter, a unit test (`tests/test_vision_profiles.py`)
  or a manual calibrator capture answers the compute half only. Grader:
  `tools/gated_g423_base_capture.py`, tests `tests/test_gated_g423_base_capture.py`.
- **G4-24** (was H6) VISION-OCR box recalibration at 2560x1440 via `/vision-calibrator` against
  `data/vision_calib_reference/*.jpg`, then WIRE the native OCR crops. Native reference-capture is
  live-verified (LEDGER 793); the recalibration needs rendered in-game HUD pixels to validate the field
  reads. Pairs with G2-41.
  **READY (lane 9, s144 cycle 80, RM-1669, PREP only, no game up: RC :8888 answered an empty body
  and :2999 refused, probed 2026-11-06 about 00:59 -06:00; NOT ticked).** AGE: the recalibration
  half is NOT done for the HUD League reports now. Four measured facts shape the check.
  (1) A calibration is keyed by the FULL HUD `config_key` (`core/hud_settings.py`
  `read_hud_settings`: `WxH` plus the five `_LAYOUT_KEYS` toggles), and `core/vision_profiles.py`
  `load_profile` uses a profile only on an EXACT key match (source `profile`); any other key gets a
  proportional seed (`resolution_seed`, which that docstring calls a starting point, not parity) or
  the 1080p legacy table. (2) The main checkout's gitignored `data/vision_profiles/` holds exactly
  two calibrated profiles, both 2560x1440 at GlobalScale=0.0000, MinimapScale 1.6200 and 3.0000
  (files dated 2026-07-06); `data/vision_calib_reference/` holds 10 base stills, all at
  GlobalScale=0.0000 (2026-07-05 / 2026-07-06). (3) League's game.cfg read at idle today: no
  `[General]` Width/Height (key `unknown`, RM-1666) and layout GlobalScale=1.0000,
  MinimapScale=1.0000. So even with Width/Height back, the live key matches NO profile and NO base
  still (both profiles differ on GlobalScale 1.0000 vs 0.0000 and on MinimapScale), and the coach
  OCR path would crop seed boxes. The cfg may be a client-regenerated default (Width/Height are
  missing), so the values written once a game starts are the ones that count: re-run at the load
  screen. (4) ORDER: a G4-23 base still at the new key first (G4-23 is ARMED exactly then), then
  this row's calibration, then G2-41's A/B (`tools/gated_g241_ocr_native.py` refuses a decisive
  verdict unless `regions.source` is `profile`).
  PROBE (read-only, main checkout, before queueing and again from the load screen): `python
  tools/gated_g424_calib_ready.py` (JSON: live key and layout, profiles, base stills, nearest
  profiles with the differing toggles, the predicted `load_profile` tier, verdict).
  PREDICATE (stated before any game): CALIBRATED (exit 0) = an exact profile exists for the live
  key; READY_TO_CALIBRATE (exit 3) = a base still but no profile; NEEDS_REFERENCE (exit 3) =
  neither, the G4-23 still comes first; KEY_UNKNOWN (exit 4) = nothing can key. **PASS needs both,
  in ONE game:** (a) the tool says CALIBRATED at the key read during that game, the profile file
  written by a calibration after this READY date; (b) `python tools/gated_g241_ocr_native.py
  --samples 8 --interval 3 --json` in the same game with `regions.source == "profile"` and the
  halved path grading gold, level and timer each on >= 3 valid samples with at least 2 of every 3
  valid samples MATCH (PROPOSED bar; a human may set another). Anything less leaves the row open.
  EVIDENCE CONTRACT: the tool JSON before queueing and at the load screen, the profile's
  `config_key` and write time, the G2-41 JSON verbatim, gameMode + queue, wall time.
  SUBSTITUTION CHECK: does the evidence show calibrated boxes READ the live HUD against `:2999`
  truth, or only that boxes were DRAWN? A calibrator save, a profile file, a unit test, OCR over
  `data/vision_calib_reference/` stills (the calibration's own input) or CALIBRATED at an idle key
  the game never ran answers the second only. Grader: `tools/gated_g424_calib_ready.py`, tests
  `tests/test_gated_g424_calib_ready.py`.
  **Idle finding (RM-1669, a FILING for the main session, not this row's verdict):** every
  calibrated profile and base still is at GlobalScale=0.0000, and the idle cfg reads 1.0000. If the
  in-client HUD scale really moved, every coach OCR crop runs on uncalibrated boxes today (the 1080p
  legacy table while the key is `unknown`, a seed once it keys), whatever G2-41 decides. The
  operator confirms the in-client HUD scale and minimap scale; either restore the calibrated values
  or treat this row as a fresh calibration at the new key.
- **G4-25** (was Z2) `[RE-SCOPED 2026-07-18]` ZOI macro callout (`kind="macro"`) + `zoi.mia` rings.
  **The stated CV-precision PREREQUISITE IS NOW DISCHARGED:** LEDGER 871 (B) / `b4ddedd1` added a
  champion-size floor + per-team clamp to `core/minimap_blob_detect.py`, measured 72->8 / 62->10 /
  74->10 on the saved SR corpus and LIVE-VERIFIED in a real Jhin ARAM (`minimap_dots=10` capped). The
  identity-dots default-ON flip is ALSO already live-verified (`1fd33854`, 2026-07-08, per RM-11). What
  actually remains: (a) per-CHAMPION identity, which is G4-22, and (b) wiring the macro/MIA feed
  through the existing `zoi=` / `districts=` seam - `vision_tracker` fog needs coordinate positions the
  Live Client does not give (roles only). Regression fence in place
  (`test_dead_fog_feed_never_fires_on_live_sr_shape`). Do NOT flip roster-wiring until (b) lands.
  **AGE CHECK (lane 9 PREP s144 cycle 79, RM-1668; NOT a tick, NOT struck): no live work of its
  own; both halves are owned elsewhere.** (a) is G4-22 (its age check above). (b) is the same
  question as G2-42 (a) and the MIA-ring half of G2-42 (d), whose READY block (s144 cycle 46)
  measured it BLOCKED-BUILD: the SR fog feed is still dead (`core/vision_tracker.py`
  `_compute_enemies` coerces the role-string `position` to `{}`, so no enemy is ever sighted), the
  `kind="macro"` tree (`core/macro_decision_tree.py`, `e2bb486a3`, 2026-07-05) is already wired in
  `dashboard/_deterministic_coaching.py` over `gs["fog_enemies"]` and so never fires on the live
  shape, and live `callouts` are blanked by `LIVE_SUPPRESSED_ENVELOPE_FIELDS`. The fence named here
  is still in `tests/test_macro_decision_tree.py`. No game can drain this row until a feed is built;
  when one is, the G2-42 (a) / (d-MIA) predicates and `tools/gated_g242_zoi_check.py` are the probe.
  RE-FILE PROPOSAL (a human moves it): fold G4-25 into G2-42 as a cross-reference, the way G3-15 adds
  no new work, so one game is not asked to drain the same feed twice.

### `[BATCH POST-GAME]` - the 90s after a Match-V5-eligible game (GATE 4 ONLY)

Practice customs and Mayhem q2400 NEVER reach Match-V5. This batch is unreachable from any other gate.

- **G4-26** (was F3) PGR auto-show on game-end live confirm (`a2fdf448`): DID NOT FIRE 2026-07-04
  (companion was on the HOME view post-game; manual-open works). **Put the companion on the correct
  view BEFORE the game ends**, then recheck.
  **READY (lane 9, s144 cycle 64, RM-1510, PREP only, no game up: RC :8888 and :2999 refused,
  probed 2026-11-05 about 01:20 -06:00; NOT ticked).** AGE: the 2026-07-04 miss PREDATES the fix.
  The 2026-07-20 drain root-caused it (item 3 at the head of this doc) and `51dfc0cef` landed it:
  the item-281 null-phase in-game promotion now ARMS the sticky (`web/js/main.js`
  `_viewAutoDerive`, the `else if (!phase && live && inGame)` arm; mirror
  `dashboard/view_router_state.py` `update_game_started(..., mode=)`; pinned by
  `tests/test_view_router_postgame_pgr_arm.py`). What is still owed is a live game end AFTER that
  fix. Source facts that shape the check: (1) the arm (`_viewSaveManual("last-match")` +
  `fetchAndRenderLastMatch()`) fires only when an `/api/state.lcu.phase` in EndOfGame /
  PreEndOfGame / WaitingForStats / TerminatedInError / Lobby reaches the page while the sticky is
  `in-progress` (mirror `is_postgame_pgr_edge`); the page reads `state.latest.lcu` and
  `state.mode` (`_viewResolveAndApply`). (2) `/api/state.lcu` is `{}` whenever the relayed LCU
  snapshot is older than 5 s, and the in-game capture runs 8-11 s behind (the "broader unfixed
  bug" in item 3), so a game end whose post-game phase never survives that TTL still misses the
  arm. (3) The overlay shell (`body[data-shell=overlay]`) returns before any derive, so the arm
  can only fire in the COMPANION window. (4) The arm is mode-agnostic (`inGame` covers sr / aram /
  arena / brawl / tft) and the view switch reads no Match-V5 row; only the PGR CONTENT does
  (`/api/last-match`). Whether that lets the row ride a GATE 3 / GATE 5 game end is a human
  re-gating call; the lane did not move it.
  PROBE (read-only; start it with about 2 minutes of game left, it must span the end):
  `python tools/gated_g426_pgr_edge.py sample --samples 240 --interval 1 [--json]` (GETs :8888
  `/api/state` only; per sample: `lcu.phase`, `mode_key`, `liveclient` non-empty; replays the
  stream through the mirror from a `None` sticky, the mid-game-open case the fix targets, with and
  without the fix; prints no id). The game counts as ENDED only when the window runs on 15 s past
  the last live sample with no live data coming back, so keep sampling at least 15 s into the
  stats screen; a post-game phase alone is not an end (a stale one shows up mid-game), nor is a
  liveclient blip that recovers. The END RUN is the final unbroken run of samples that are
  non-live or carry a post-game phase (the cached `liveclient` stays non-empty up to 5 s after
  :2999 stops, so the real post-game phase can land on live samples); the last in-game sample is
  the one just before it. Verdicts: EDGE_DELIVERED (exit 0: ended, and the edge fired inside the
  end run; `fix_path_exercised` is true only when the pre-fix replay did not fire there),
  EDGE_MISSED (exit 3: ended, no end edge; `miss_cause` = `no_postgame_phase` when the page was
  armed at the last in-game sample and no post-game phase fired it, or `not_armed_at_end` when it
  was not armed there, so no phase could fire it), NO_EVIDENCE (exit 4). An edge BEFORE the end
  run fired on a stale mid-game phase, or ended an earlier game in a window that spans two (one
  game per window: only the last is graded); it never counts and is reported as
  `mid_game_edges`. Also read `null_phase_live_samples` (how much of the game ran phase-blind, a
  live measure of the TTL gap) and `last_in_game_to_edge_s`. Model limits: the replay keeps the
  last in-game `mode_key` (`onState` calls `setMode` only for an in-game tag) and cannot see a
  health-envelope change of the page mode. Idle smoke this cycle: NO_EVIDENCE, 3/3 DASH_DOWN (RC
  down).
  PREDICATE (stated before any game): **PASS needs both:** (a) `sample` EDGE_DELIVERED over a
  window that spans the real game end; (b) the operator's eyeball, with the COMPANION (not the
  overlay) left on its auto view (no `#` hash, no manual pick) through the game, that within about
  15 s of the stats screen the companion shows the Post Game Review, and that its match is the one
  just played (champion + result), not the prior match. (a) without (b) leaves the row open.
  **FAIL** = EDGE_MISSED with `no_postgame_phase` (file it against the 5 s TTL, not the arm), or
  EDGE_MISSED with `not_armed_at_end` (file it against the arm / mode signal, not the TTL: the
  page held no in-game mode with live data at the end, or a stale phase reset its sticky), or
  EDGE_DELIVERED and the companion still on Home (the page did not act on a delivered end edge:
  triage the JS arm against its mirror, and the page-mode limit above, before filing), or the PGR
  of the PRIOR match (the 10 s retry did not cover the ingest lag). `mid_game_edges` > 0 in a
  one-game window is a separate finding (the page pinned the PGR mid-game on a stale phase),
  filed on its own and never read as a pass.
  EVIDENCE CONTRACT: the `sample` JSON verdict + `miss_cause` + `edge_phase` +
  `last_in_game_to_edge_s` + `null_phase_live_samples` + `mid_game_edges` + `modes`, the local
  time of the stats screen, the queue, and the operator's one-line statement of the view and
  match the companion showed.
  SUBSTITUTION CHECK: does the evidence show the companion RENDERED the just-played PGR, or only
  that `/api/state` carried a post-game phase the mirror would act on? EDGE_DELIVERED, the mirror
  tests, a manual open (the 2026-07-04 entry already shows manual-open works) or a page reload
  after the game (a fresh page never holds an armed sticky) answer the compute half only.
- **G4-27** (was F6) R47 PGR child-panel capture - UNCLEAR / likely moot (the entry itself says the
  baseline render is byte-identical, so there is no pixel delta to capture). **Operator call to
  discharge as a no-op.** SOURCE: LEDGER 702.
  **MIS-GATED, NOT A GATE 4 ROW (lane 9 PREP s144 cycle 78, RM-1667, source read at `f81e482c7`,
  2026-11-06; NOT a tick, NOT struck; no game up: :8888 and :2999 curl status 000 at
  2026-11-06T00:00-06:00).** Three measured facts. (1) THE "NO DELTA" PREMISE IS HALF TRUE. The R47
  work commit is `43ed22bf1` (LEDGER 702 cites the pre-rewrite `4f4f05d3`). Its `pgr_winprob.css`
  hunk adds a comment only (zero pixels at any width), but its `pgr_loadout.css` hunk DELETES
  `.pld-aug-name { font-size: 13px; }` from inside `@media (max-width: 900px)`, so at a viewport of
  900 px or less the augment names now render at the base `var(--fs-xs, 16px)`
  (`web/css/panels/pgr_loadout.css:114-115`, the media block `:128`). R47's "never rendered" rested
  on the 1920x1080 Chrome dashboard, retired 2026-06-27. The surface today is the frameless
  (`rc-shell/src/main.js:686`) companion, whose presets are compact 380x720, standard 920x1280
  (the default) and tall 1100x1560 (`rc-shell/src/config.js:36-38`). The web side has no
  preset-specific CSS (no `sizePreset` / compact selector under `web/js` or `web/css`), so the
  default and tall presets show no delta, but compact (380) is inside the media block and does.
  (2) NO GAME IS NEEDED EITHER WAY. The PGR panels render from stored post-game data: the
  archive view `#view-historical-pgr` (`web/index.html:2178`, reached from a History row) and
  `#view-last-match` (`:1803`) render whenever RC serves them, with no game up. This is the
  same class as the OQ12 PGR bench-line companion capture already listed under "Not actually
  live-gated". (3) THE CAPTURE WOULD NOT ISOLATE R47 NOW: `pgr_loadout.css` is unchanged since
  `43ed22bf1`, but `pgr_winprob.css` has moved since (`70643997a` RM-531 tokens, `820b5f005`
  RM-638 pins). The CSS contract R47 shipped is held by `tests/test_pgr_child_panel_floor_guard.py`.
  RE-FILE PROPOSAL (a human moves it; the lane does not): out of GATE 4 into "Not actually
  live-gated" as an anytime companion capture, owner the uiux lane. ANYTIME CHECK, predicate stated
  before any look: open one stored match in PGR at the compact preset (or a headless Chromium
  viewport 380 px wide on the same stored match; no `ui_mock` PGR fixture was found, so it needs RC
  serving, not a game); PASS iff every rendered `.pld-aug-name` has a computed
  `font-size` of 16px or more and none overflows its `.pld-row` (`scrollWidth <= clientWidth`);
  then the same at 920 px. An empty loadout strip (no augments in the match) is NO RESULT, not a
  pass. The operator no-op call stays available: the default preset has no delta to see.
- **G4-28** (was F7) ~~Home "Tonight's Pick" hardcoded dummy (`web/js/main.js:3080`,
  `dashboard/builders_home.py:148,105`): wire to real post-game `queue_id` ingest. DEFER until
  queue_id ingest ships; gated on real post-game Match-V5 rows.~~ **MIS-FILED, CLASS 1: the answer is
  on disk (lane 9 PREP s144 c62, RM-1392, source read at `c091668ca`, 2026-11-05; NOT a tick, no game
  involved).** The row is copied from the dummy-data table `docs/OVERLAY_BUILD_MASTER_PLAN.md:165`
  (added `b07498ab1`, 2026-06-28, from the s218 `TODO(s218-dummy-data)` tags of `3626bb00d`,
  2026-05-15). Its cited lines were the Recent-row `items` / `mode_subtype` TODOs, not Tonight's Pick
  code, so the row is mis-labelled as well as stale. Both of its premises are refuted at HEAD:
  (1) Tonight's Pick is NOT a dummy and never read a queue_id. `out["tonight_pick"] =
  _home_tonight_pick(week_rows)` (`dashboard/builders_home.py:339`) takes the top 7-day
  `match_history.db` aggregate by avg KDA (`:441-460`, since `77c5b7297` 2026-04-30); the FE renders
  that payload (`web/js/main.js:3796` -> `_homeRenderCoach` `:3914`). The backend pick is pinned by
  `tests/test_home_tonight_pick_tips.py`; `tests/snapshot_panels/test_home_view.py:127` pins only the
  card's render on mock data.
  (2) The queue_id ingest the row waits on HAS SHIPPED, and needs no Match-V5 row: the s218 dummy
  fields on the Recent rows, `items` (`5f448a789`, 2026-05-16) and `mode_subtype` (A6 `3df627d6e`,
  2026-07-04), read the LCU-ingest `lcu_match_detail` blob (`builders_home.py:254-255`, ARAM Classic
  q450 / Mayhem q2400 split), pinned by `tests/test_home_recent_mode_subtype.py`. Nothing here needs a
  game, so no live half is left. Residue (NOT gated, filed for a repo / uiux lane): two stale
  `TODO(s218-dummy-data)` comments still say the ingest has not shipped (`builders_home.py:232`,
  `web/js/main.js:3336`). Moving the row to "Not actually live-gated" is a human doc edit.
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
  **AGE RE-CHECK (lane 9 PREP s144 cycle 128, 2026-11-09, S144-G-115, read at `c33b5ae45`; NOT a
  tick, NOT a re-open; no game up).** Read-only (`mode=ro`) reads of the main checkout's
  `data/match_history.db` (mtime 2026-10-28) and `data/rewind_history.db`. No Match-V5 id is
  restated here (RM-906). (1) HOLDS: the 7 rows exist unchanged - `game_id = 0`, and champion, mode
  and `game_time_s` (1633 = 923.35, 1506 = 2248.72) as filed. (2) PREDICATE DEFECT: `game_id = 0`
  does NOT confirm orphan status. It is the normal state (item 211 carry (c),
  `docs/ROADMAP_HISTORY.md`: Live Client rarely exposes gameId): 153 of 404 rows carry it, and 103
  non-TFT rows carry it with no `lcu_match_detail` at all. The sharp signature, measured over the
  whole table: these 7 are the ONLY rows with `game_id = 0` AND a `raw_data.lcu_match_detail`, and in
  every one the detail's participants exclude `db.champion`, so they are MISATTRIBUTED (each holds
  another game's blob: 1633 holds a q2400 952 s game), not detail-less. (3) THE 1633 PRESCRIPTION IS
  WRONG AS FILED, so scope is LARGER than filed. The Jinx q420 929 s game named for 1633 is already
  stamped as `game_id` on row **1620** (Jinx SR, saved 2026-05-24 20:53:41 local, `game_time_s`
  1810; its detail lists championId 222 = Jinx, `gameDuration` 929). That game was created at
  20:58:11 local and ended about 21:13:40, AFTER row 1620 was saved and 60 s before row 1633 (21:14:40),
  so 1633 is its true row and 1620 is an 8th misattributed row outside the 7. `--match-id` posts to
  `/api/last-match/ingest`, which matches gameId FIRST (`dashboard/routes_last_match.py`
  `_row_match_by_game_id`, called before the ts-window fallback in `_try_ingest_once`), so it would
  re-stamp row 1620 and leave 1633 unchanged. Recovering 1633 needs row 1620's `game_id` cleared
  first, a DB write that no shipped tool offers; 1620's own game (about 1810 s, ended about 20:53)
  then has no blob. (4) 1506 HOLDS: its Kai'Sa q420 2262 s game is stamped on no row, and the
  fallback can reach 1506 (rank 26 of the newest 50 non-TFT `game_id = 0` rows its query reads; game
  end about 13:30:33 local vs row 13:31:21 = 48 s, inside `INGEST_TS_WINDOW_S = 180`). It still needs
  RC `:8888` up (down at this read) and a Riot key. (5) Cite drift: SOURCE `ROADMAP.md:81` is now
  `ROADMAP.md:156` (the RM-16 carry-forwards line). Verdict unchanged: NOT live-gated, no live
  residual; the operator decision now covers 8 rows (1620 added), and moving the row to "Not
  actually live-gated" stays a human doc edit.
- **G4-30** `[NEW 2026-10-04]` RM-526 / Y-01 Step 0 - the live half of the target-pinned live
  writer (code SHIPPED headless, LEDGER entry for RM-526). Over the next 5 real game ends (include
  at least one Mayhem q2400 and one Match-V5-eligible game), read the writer's INFO lines
  `chain ... attempt N ended <status>` in `logs/` and record per game: target id, final status
  (ok / already_present / event_mode_excluded / parked), attempts used. Also confirm whether the
  LCU EOG block carries `queueId` (if absent, a Mayhem game retries ~19.5 min then parks instead
  of ending `event_mode_excluded` at once). PASS = every eligible game ends `ok` for ITS OWN id and
  no game reports the previous game's id. SOURCE: ROADMAP RM-526.
  **READY (lane 9, s144 cycle 3, PREP only, no game up; NOT ticked).** One command joins the five
  sources per game end. Run it after EACH game ends (the pin holds only the latest game), and once
  more 22 min after the last game ends:
  `python tools/gated_y01_chain_report.py --since <ISO local time the session started> --json`.
  - Sources it reads, all read-only:
    - The game end: `rc.app.lifecycle` "Game ended" (`app/_game_lifecycle.py`).
    - TFT ends are skipped: the "TFT game end: League rewind live-writer skipped" line, or before S134
      N3 the collector's "triggered for mode=TFT".
    - The game's OWN id: `rc.postgame` "postgame: saved match <id>". That is the EOG `gameId`, NOT
      the writer's Match-V5 id list, where the Y-01 defect lived. A "match <id> already stored -
      skip" line never vouches for it: that id was saved before this game ended, which is what a
      stale EOG looks like.
    - The chain end: "rewind_live_writer: chain <chain> attempt <n> ended <status> (<target>)". The
      chain id embeds `scheduled_at`, which joins it to the game end within -2 .. +30 s.
    - The Y-08 receipt: `ops/runtime/rewind_ingest_receipts.jsonl`, joined on `ts - elapsed_s`.
    - The pin: `ops/runtime/last_game_end.json` -> `pin.queue_id_present`. Its Riot ID is never
      read out.
    - The DB row: `data/rewind_history.db` `matches`, opened `mode=ro` only when an `ok` target
      exists. `--no-db` skips it.
  - Field paths: `verdict`; `games[i].{status, attempts, target, own_target, pinned, fallback,
    db_row, verdict, why}`; `pin.{queue_id, queue_id_present, game_mode}`.
  - Ids print as `id:<8 hex of sha256>`, so the output can go into this doc under RM-906, and a
    repeated id still shows. `--show-ids` is for the console only.
  - Exit codes: 0 PASS, 1 INCOMPLETE, 2 FAIL.
  - Predicate, stated before any game. PASS iff all of these hold:
    - At least 5 League game ends since `--since`. TFT ends and VOID ends do not count. A VOID end
      is an RC restart inside the chain window with NO chain end; the daemon Timer drops by design.
      A TFT marker or a restart never hides a game whose chain did end. A game whose chain was never
      scheduled (the Timer-cap line, "rewind_live_writer schedule error", or "rewind live-writer
      trigger error" 0 .. +5 s after this game's own "Game ended") is a FAIL, restart or not. The
      window is tight because a running chain's retry staging writes the same cap line.
    - Every one of them has a chain-end log line and a joined receipt, with `pinned` true and
      `fallback` false.
    - Every one has `target` == `own_target`, whatever its status, so a Mayhem exclude that names
      another game's id fails too.
    - Each one ends `ok` with `db_row` true, or `event_mode_excluded` on any attempt. An attempt
      above 1 only means the pin arrived after the 90 s delay (`lib/rewind_live_writer.py`
      `awaiting_pin_retry_scheduled`).
    - At least one end of each kind.
    - No `target` repeats an earlier game's.
  - Fails and partial results:
    - FAIL: any game that breaks a rule above.
    - The row's queueId sub-question. A pin with neither queueId nor KIWI never excludes: the Mayhem
      game goes on to Match-V5 and parks as `target_not_indexed` after about 19.5 min, which is a
      FAIL. Record `pin.queue_id_present` and `pin.game_mode` from the run made right after the
      Mayhem game: queueId absent with KIWI present still excludes at once.
    - INCOMPLETE, never PASS: a chain still inside its 1290 s window, no "saved match" own-id line
      (including an "already stored" line only), a receipt without a chain-end line, no receipt, the
      DB not checked, or an `already_present` / `short_game` end.
  - Evidence contract:
    - Value: the verdict plus, per game, status / attempts / redacted target and own_target /
      pinned / fallback / db_row.
    - Source: the tool and the five sources above.
    - Timestamp: `now` and `games[i].ended_at`, plus mode / queue from the session.
    - Predicate: the one above.
  - SUBSTITUTION check: a passing `tests/test_ingest_receipt_y08.py` or a hand-made receipt shows only
    that the writer COMPUTES a status. It does not show that a real game end SCHEDULED a chain that
    resolved the right id and LANDED a row.
    - Only live log lines plus `db_row` true answer that. A status `ok` without the DB row is the
      writer's own claim, which is why `db_row` is part of the predicate.
    - Residual limit: own id and pin both come from the same EOG block. If the collector ever pinned
      a STALE EOG that it still logged as "saved match", the two would agree and both be wrong.
      Only the repeat rule (within `--since`) catches that.
  - Idle baseline, 2026-10-27 09:0x local, no `--since`:
    - INCOMPLETE, exit 1: 0 League ends and 5 TFT ends (all 2026-10-25), void 0, receipts 0,
      pin absent.
    - One of the five, 09:28, predates the N3 skip line. Only the collector's "triggered for
      mode=TFT" marks it. Before that marker was read, the tool called it a League FAIL: a positive
      control on real logs.
    - Zero chain-end lines and no receipt file exist in the retained logs (2026-10-13 onward). No
      League game has ended since Y-01 / Y-08 shipped, so the writer has never run live.
  - Reverses if: the parsed log lines or logger names change. `tests/test_gated_y01_chain_report.py`
    pins each source literal, and the `matches` schema or the receipt row shape (`v` 1) also counts.
  **AGE CHECK (lane 9 PREP s144 cycle 131, S144-G-118; source read at local main `d2d4840f1`, no game
  up (RC :8888 refused at 2026-11-09T06:10); NOT a tick). The READY card above holds unchanged; the
  writer has STILL never run live.**
  - Cites, re-read at HEAD: "Game ended", "TFT game end: League rewind live-writer skipped" and
    "rewind live-writer trigger error" in `app/_game_lifecycle.py` under logger `rc.app.lifecycle`;
    "rewind_live_writer schedule error" twice in `lib/rewind_live_writer.py` (logger
    `rc.lib.rewind_live_writer`); "rewind_live_writer: chain %s attempt %d ended %s (%s)" there;
    "postgame: saved match %s" and "postgame: match %s already stored - skip" in
    `lcu/lcu_postgame_collector.py` (logger `rc.postgame`). `DEFAULT_DELAY_S` is still 90.0 and
    `STAGED_DELAYS_S` still (60, 120, 300, 600), so the tool's `CHAIN_WINDOW_S` is still 1290 s
    (1170 + 120) and "about 19.5 min" still holds. `PIN_PATH`, `RECEIPT_PATH` (`lib/ingest_receipt.py`)
    and `DB_PATH` are unchanged.
  - Eight commits touched the five cited source files since READY (`1debadfb0`), none moving a parsed
    literal. `aa8082af8` (2026-10-30) routes `write_game_end_pin` through `core.polled_json`, same
    bytes; `9f3845e32` (2026-11-06) makes the tool's `_platform` call
    `operator_identity.normalize_platform` and read UTF-8 with or without a BOM. The other six
    (`6d2d1a0d4`, `40dcca458`, `daca8a6b0`, `535679309`, `2708e8aec`, `badd1407d`) touch only
    `lcu/lcu_postgame_collector.py` and `lib/ingest_receipt.py`: renames, a merged `with`, comment
    wording and `time.time` to `time.monotonic`. `tests/test_gated_y01_chain_report.py`: 59 passed
    this cycle.
  - Post-cutover log route holds: the 2026-10-31 daily log carries `rc.app.*` lines from the rc-shell
    service host window (19:13 .. 21:17 local), so the `logs/YYYY-MM-DD.log*` source survives the
    launcher cutover. RC has not run since: no daily log after `2026-10-31.log`, and
    `ops/runtime/launcher_status.json` reads `state` halted, `reason` stdin_stop.
  - Idle baseline, 2026-11-09T06:11 local, no `--since`, `--root` the main checkout: INCOMPLETE, exit
    1, the same five TFT ends of 2026-10-25 and 0 League ends; 0 receipts, pin absent. Zero
    chain-end lines in any retained log; retention now starts 2026-10-17, not 2026-10-13.
  - Drain blocker, not a defect: the row needs RC RUNNING (rc-shell `--profile dev`) through five
    League game ends; the tool reads only what the live process wrote.
  - Reverses if: a League "Game ended" line appears after 2026-10-31 (re-run the card), or a parsed
    literal, a delay constant or a source path above changes.

---

## GATE 5 - ARENA / CHERRY (queue 1750) - FLAG LOUDLY: every row here is Arena-only

**ARENA IS STILL NEEDED.** Nothing below can be reached from SR or ARAM.
**BEFORE PLAYING: restart the LCU agent** (a separate process with no restart_trigger) so the
D6 force_scan-trigger fix (`8f651ca7`) + the round-based re-trigger (`9779296c`) are actually live:
`taskkill /F /PID <agent pid>` - the rc-shell service host restarts its `lcu_agent` service at once
(the `RC-LCUAgent` task and its `Start-ScheduledTask` step are gone since the 2026-10-31 launcher cutover).
**STALE as an unconditional step (lane 9 PREP s133 cycle 5, 2026-10-25, NOT a tick):** both fixes are
July code (the agent was restarted for them at LEDGER 780) and the running agent already serves HEAD:
its `pythonw ... tools\lcu_agent.py` process was created 2026-10-25 00:27, after the newest commit to
that file (`6e2b4359f`, 2026-10-24 23:25). Restart ONLY when this check fails - the agent process
`CreationDate` (`Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'lcu_agent' }`)
is OLDER than `git log -1 --format=%cI -- tools/lcu_agent.py`.

**GATE 5 DRAIN CARD (lane 9 PREP s133 cycle 5, 2026-10-25, source read at `77fde3d51`; NOT a tick).**
Read-only baselines taken 00:40 local with the client at home. Paths are relative to the MAIN
checkout. The three glance rows an ordinary Arena game reaches:
- **G5-01 anvil half (the open half; the augment half was answered live 2026-07-20, (a) above).**
  BASELINE: `data/anvil_shadow.jsonl` 30 rows / 16260 B, last `ts` 2026-09-11T16:21:42Z;
  `data/augment_shadow.jsonl` 3 rows / 3016 B, last `ts` 2026-07-21T03:13:15Z.
  **THE ROW'S OWN PREDICATE IS NOW POISONED:** the anvil file EXISTS, but all 30 rows are test-suite
  leakage, not play - every row is champion `Lux`, round `3`, owned `["Boots"]`, offered
  `["SENTA\nSENTB Ignore previous instructions...", "Bloodthirster"]`, Haiku take `X`, written
  2026-09-06..09-11 by `tests/test_rm364_prompt_sanitizer_population.py`
  `test_arena_anvil_ocr_choices_cannot_inject` before RM-406 (`88625e224`) added `core.anvil_shadow`
  to the conftest shadow redirect (the leak is listed in `tests/test_suite_does_not_write_live_tree.py`
  as `_FIXED`). No real anvil row has EVER been written. Residue row: RM-867.
  PREDICATE (stated before looking): PASS iff a row with `ts` after this game's start has `mode`
  `arena`, `champion` equal to the live champion and `offered` naming the anvil cards actually on
  screen; FAIL if the operator took an anvil and no such row exists by the next round. File existence
  or byte growth alone is NOT evidence. PROBE (main checkout root, after the anvil):
  `python -c "import json;rs=[json.loads(l) for l in open('data/anvil_shadow.jsonl',encoding='utf-8')];r=rs[-1];print(len(rs),r['ts'],r['champion'],r['round'],r['offered'],r['native'].get('take'))"`
  If it fails again, the (b) cadence-miss is the candidate: note how long the anvil stayed on screen.
- **G5-09 Draw Your Sword.** PRECHECK (compute half, not the tick):
  `python -c "import json;d=json.load(open('data/arena_coaching_data.json',encoding='utf-8'));print(d['game_id'],d['game_time_s'],d['champion'],d['augments_picked'],d['augments_source'],d['item_build'])"`
  where `augments_picked` must contain `DrawYourSword` (api names, written by `_handle_augment_select`
  `coaches/arena_coach.py:968` or `_reconcile_augment_hud` `:1015-1062`; the all-or-nothing return is
  `:1033-1036`, re-cited from `:989-995`) and `item_build` is a comma-joined DISPLAY-NAME string
  (`:886`), so test for the text `Runaan's Hurricane`, not the id 223085. PREDICATE (the tick): PASS
  iff, after `DrawYourSword` (augment 134) shows in `augments_picked`, the RENDERED build panel (a
  frame whose `ts` is checked against `game_time_s`) lists items and none is Runaan's Hurricane; an
  empty or unrendered panel is NO RESULT, not a pass; if `augments_picked` lacks `DrawYourSword` while
  the HUD shows it, record the HUD-reconcile miss instead (the row's stated likelier cause).
- **G5-03 boots mirror.** Pixel-only: needs a boot anvil to roll (none in 8 rounds 2026-07-04). The
  G5-01 probe above prints `offered`, which names a boot anvil if one rolls; then capture the frame.
Not readied this cycle: G5-05 / G5-06 / G5-08 (each needs a DS flag or a replay design first).
(Cycle 6, 2026-10-25: G5-06 and G5-08 are now readied in their own rows below - G5-06 has a CHECK and
a precondition, G5-08 a one-glance tooltip CHECK plus a "Not actually live-gated" CANDIDATE. G5-05 is
still not readied.) (Cycle 7, 2026-10-25: G5-05 is split and readied in its row - CHECK A, the stat
half, is drainable in any Arena game with an `ar` champion such as Vayne; CHECK B, the coach half,
waits on the RM-875 wiring.)

- **G5-01** (was D6) **THE ONE OPEN LIVE BUG.** Arena augment-select shadow
  (`data/augment_shadow.jsonl`) + item-anvil shadow (`data/anvil_shadow.jsonl`) seeding + WIRING-GAP
  re-validate. STATUS re-probed on disk 2026-07-18: `augment_shadow.jsonl` seeds at **966 bytes**
  (unchanged 2026-07-08 mtime); **`anvil_shadow.jsonl` is STILL ABSENT**; `git status data/` clean, so
  no headless probe has contaminated the ground-truth signal. Fix-committed, pending live re-validate -
  **do NOT mark closed.** (That STATUS is superseded 2026-10-25: the anvil file now exists, but every
  row is test leakage - see the GATE 5 DRAIN CARD above and RM-867.)
  NARROWED 2026-07-18 (diagnostic only - this closes NO part of the row): the shadow WRITERS are fine
  and are correctly reached from `arena_coach.py:596` `_handle_augment_select` and `:599`
  `_handle_anvil`. **The wiring gap is UPSTREAM, at `ArenaVisionReader.read()`.** So the live sit
  should watch whether the vision reader emits an anvil/augment event at all, not whether the writer
  fires.
  LIVE RESIDUAL (glance): in ONE Arena game take an augment and an item anvil, then check that
  `data/anvil_shadow.jsonl` now EXISTS and `augment_shadow.jsonl` has grown past 966 bytes.
  (Both halves of that check are already true on disk and prove nothing; use the DRAIN CARD predicate.)
  2026-10-25 (RM-868, consistent but NOT proven live): the upstream gap is the relay - its TFT schema
  has no `anvil_choices`, so `ArenaVisionReader` could never emit an anvil; the reader now goes direct
  (`USE_RELAY = False`, `d47e9906b`). The DRAIN CARD predicate is the test; G7-17 step (d) runs it.
  SOURCE: LEDGER 779/820; git `8f651ca7`, `9779296c`.
  **RE-CHECK (lane 9 PREP s144 cycle 99, 2026-11-07, source read at `66a922e3b`; NOT a tick, nothing
  struck).** The DRAIN CARD's anvil BASELINE ("30 rows / 16260 B") and its "PREDICATE IS NOW
  POISONED" warning are STALE: RM-867 (`d37e806c1`, LEDGER 1838) renamed the 30 leaked rows to the
  gitignored `data/anvil_rm867_test_leak_2026-09_shadow.jsonl` (16260 B, still on disk) and the writer
  now refuses an injection-probe offer (`core/anvil_shadow.py:195` `offer_is_injection_probe`, defined
  `:256`; the reader skips such rows, `:369`). Measured on the main checkout 02:40 local:
  `data/anvil_shadow.jsonl` is ABSENT (the normal pre-game state, recreated on the first real anvil
  row); `data/augment_shadow.jsonl` 3 rows / 3016 B, last `ts` 2026-07-21T03:13:15Z, mode `arena`,
  round `~1`. The card's `python -c` one-liner crashes with FileNotFoundError on an absent file; use
  `python tools/anvil_shadow_probe.py` (RM-873) instead, which printed
  `FAIL: ... absent (no real anvil row yet)`, exit 1, this cycle. The card's PREDICATE is unchanged
  and is now clean: any row after this game's start is real play. Cites moved: the dispatch is
  `coaches/arena_coach.py:626` `_handle_augment_select` / `:629` `_handle_anvil` (was `:596` / `:599`),
  defs `:936` / `:1091`, `ArenaVisionReader` `:1159`, `USE_RELAY = False` `:1202`; the writer's
  `offered` fields are `core/anvil_shadow.py:189` / `:220` (unchanged).
- **G5-02** (was D2) `set_augment_intent` 4-PATCH endpoint discovery at a real Arena augment phase.
  **PATH IS STALE:** `tools/gamepc_lcu_agent.py:1179` predates the Game-PC retirement - re-home the
  chain BEFORE running. (Re-probed 2026-10-25, lane 9 s133 cycle 5: that file is gone and the chain is
  already re-homed - `tools/lcu_agent.py:800-849` `set_augment_intent`, PATCH then POST
  `/lol-cherry-game-intra-event/v1/augment-select`. The re-home precondition is met; the live discovery
  is still owed.) Recipe: `docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md`. No Cherry augment session
  surfaced in `/api/state` 2026-07-04 (shares the G5-01 root cause). SOURCE: ROADMAP.md:113 / RM-24.
  **RE-CHECK (lane 9 PREP s144 cycle 99, 2026-11-07, source read at `66a922e3b`; NOT a tick, nothing
  struck).** Cites moved: the handler is `tools/lcu_agent.py:938` (`if name == "set_augment_intent"`,
  was `:800-849`), and the chain is FOUR attempts, not "PATCH then POST": PATCH
  `/lol-cherry-game-intra-event/v1/augment-select`, PATCH `/lol-cherry/v1/augment-select`, PATCH
  `/lol-cherry-summoner/v1/augments`, POST `/lol-cherry-game-intra-event/v1/augment-select`
  (`:969-974`), body `{"augmentId", "slotIndex"}`, first 2xx wins. `ROADMAP.md:113` no longer names
  RM-24 (archived, `ROADMAP.md:164`). **The dashboard click cannot fire it live:** the only UI caller
  (`web/js/panels/champ_select.js:3866`, wired at `:1037` on the champ-select Arena pane) needs
  `augments.options`, which `lcu/champ_select_shape.py:469` always sets to `[]`, so no clickable
  option ever renders from live data. The live discovery therefore uses the recipe's MANUAL route
  (`docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md` step 2: POST `/api/lcu-cmd`, `dashboard/routes_loadout.py:849`,
  `{"cmd": "set_augment_intent", "augment_id": <id>, "slot": 0}`) or step 5 (`RC_LIVE_ARENA=1`
  `tests/test_set_augment_intent_handler.py::LiveAugmentSelectIntegrationTests`, which loads
  `tools/lcu_agent.py` directly). That recipe's "Game-PC agent" hop and its whole "Game-PC agent
  redeploy reminder" section are STALE (1-PC, ADR-011): the chain is now :8888 -> :8889
  `/lcu-cmd` queue -> the Legion `tools/lcu_agent.py` (`drain_once` `:1852`). This is an LCU WRITE:
  an operator-present drain only, never a watcher lane. PREDICATE (stated before any game): PASS iff,
  during an in-game Arena augment-pick window, the envelope has `ok: true` and names an `endpoint`
  AND the client shows that augment taken; `ok: false` with all four in `tried` is a RESULT (record
  each status; then the doc's "If all 4 paths 404" list); `ok: true` with no augment taken on screen
  is FAIL (a 2xx that did nothing).
- **G5-03** (was D3) Arena boots 22xxxx mirror residual: augment-phase VISUAL confirm the pushed boot
  renders (icon may 404 per `reference_items_index_alias_ids`, display name correct). Data fix shipped
  (`f8353d5d`). STATUS: no boot anvil rolled in the 8 augment rounds played 2026-07-04.
  **RE-CHECK (lane 9 PREP s144 cycle 97, 2026-11-07, source read at `7ba80f328`; NOT a tick, nothing
  struck).** The "icon may 404" clause is STALE, and was already stale when filed: the memory it cites
  describes a first-seen-wins `byName` and a `web/js/dashboard.js` consumer that is gone (Settled).
  `scripts/data_pipeline.py:288-297` now sorts shorter ids first before `setdefault` (landed
  `537247958`, 2026-05-05, six weeks before `f8353d5d4`), so the panel's name lookup
  (`web/js/lib/items_index.js:34` `_resolveItemId`; Arena `item_build` is display names,
  `coaches/arena_coach.py:907`) resolves boots to the 4-digit id: tracked `web/data/items_index.json`
  (16.22.1) maps `berserkersgreaves` 3006, `sorcerersshoes` 3020, `platedsteelcaps` 3047,
  `mercurystreads` 3111, `ionianbootsoflucidity` 3158, `bootsofswiftness` 3009, `symbioticsoles` 3010,
  `synchronizedsouls` 3013. Even an alias id would not blank: the gitignored local cache
  `<repo>/web/data/ddragon/16.22.1/img/item/` holds 863 PNGs, 176 of them 22-prefixed (both `3006.png`
  and `223006.png` present), and the item tile path retries the DDragon CDN on error
  (`web/js/panels/item_build.js:106-112`, `web/js/main.js:2752-2756`,
  `web/js/panels/active_match.js:2985-2999`). NOT every renderer does: the variant rows
  (`_ibRenderRows`, `item_build.js:412`) take `item_ids` as-is and HIDE the icon on error with no CDN
  retry, so there a 22-prefixed id missing from the local cache would show an empty cell (the
  verifier's catch; not seen live, and the cache holds all 176 alias PNGs today). What stays live: the pushed
  boot APPEARING by name on the rendered Arena build panel once a boot anvil rolls; the G5-01 probe's
  `offered` (`core/anvil_shadow.py:189` / `:220`) names the anvil, then capture a frame whose `ts` is
  checked against `game_time_s`. PREDICATE (the tick): PASS iff a boot named in `offered` (or bought)
  shows on the rendered build panel with a non-blank icon; a blank tile or a missing boot is FAIL; no
  boot anvil this game is NO RESULT.
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
  (Re-probed 2026-10-25, lane 9 s133 cycle 5: the conclusion holds, two cites moved. `core/` now names
  the flag once - `core/daemon_slayer_client.py:2013` `burst_for(assume_physical_burst=False)` - and no
  production caller passes it True; the server comment is now `agents/daemon_slayer/server.py:2049-2053`
  inside `_route_burst`, still /burst-only.)
  NO LIVE RESIDUAL until the flag is plumbed to /rank - re-file that wiring as headless code work, and
  do NOT spend an Arena sitting waiting for 226630 to roll for this row. DS restart on the eventual flip.
  **RE-CHECK (lane 9 PREP s144 cycle 97, 2026-11-07, source read at `7ba80f328`; NOT a tick).** The
  conclusion holds; three cites moved. `burst_for` is now
  `core/daemon_slayer_client.py:2065`, the parameter `:2098` (default False), the body key `:2166-2167`;
  `git grep` finds no other reference under `core/`, `coaches/`, `coach_integration/`, `modes/`,
  `dashboard/`, `app/` or `web_dashboard.py`, and no non-test caller of `burst_for(` at all. The /burst
  comment is `agents/daemon_slayer/server.py:2287-2291` inside `_route_burst` (`:2254`); the pin is
  `_effects_data.py:3848` in the `"226630"` entry (`:3832`). `inspect.signature`:
  `rank_for_primary_archetype` (`core/daemon_slayer_client.py:2991`) has 47 parameters and
  `dispatch_for_coach` 23, neither `assume_physical_burst`; `burst.rank_items_by_burst` lacks it,
  `burst.compute_burst_damage` has it. "DS restart on the eventual flip" STILL HOLDS, unlike G5-05:
  the key is parsed per request only by /burst (`:2291`), which has no on-screen consumer; the /rank
  family does not parse it (`server.py:2930-2932` for /rank-assassin, and `rank_items_by_burst` has no
  such parameter), so plumbing it to a ranked route is DS code and needs the `:8860` restart (an
  adversarial pass refuted this cycle's first draft, which called the clause stale). Still NO LIVE
  RESIDUAL.
- **G5-05** (was D4) `apply_mode_modifiers` Arena re-rank validate - Arena ar/swift growth-addends are
  the only schedulable mode where this seam re-ranks (URF/OFA/USB/NB rotate). NOT attempted
  2026-07-04. DS restart.
  **SPLIT + READIED (lane 9 PREP s133 cycle 7, 2026-10-25, source read at `6c7269ed8`; NOT a tick).**
  The row asks two things. (A) Does Arena really apply the wiki `ar` growth addends the seam adds?
  That is drainable in ANY Arena game now. (B) Does the live coach re-rank with them? That is BLOCKED ON
  WIRING: no live RC path ever sends the flag. The Arena coach's DS call is `coaches/arena_coach.py:699`
  `dispatch_for_coach(mode_engine="ARENA", ...)` -> `coach_integration/archetype_dispatch.py:360`
  `rank_for_primary_archetype(**kwargs)`, and `inspect.signature` says NEITHER has an
  `apply_mode_modifiers` parameter (14 per-scorer `core/daemon_slayer_client.py` functions do, e.g.
  `rank_for`); `core/focus_board_live.py:439` hard-codes `False`. "DS restart" is STALE: the seam is a
  per-request body key (`agents/daemon_slayer/server.py` `_opt_bool(body, "apply_mode_modifiers",
  False)`, e.g. `:482`) gating `engine.py:379-383`, not a DS-side flag; DS `:8860` 1.290.0 serves it.
  COMPUTE HALF (headless, in-process at `6c7269ed8`, NOT evidence): 45 of 171 `wiki_stats` entries carry
  an `ar` block (axes `hp_base` / `hp_lvl` / `arm_base` / `arm_lvl` / `dam_lvl` / `as_lvl`,
  `engine.py:101-108`); `rank.rank_items` level 9, no items, `ARENA`, armor 80 / MR 60 / 2500 HP, flag
  ON vs OFF moves the full order for 42 of 45 and the top 5 for 6 (Akshan, Kindred, KogMaw,
  MissFortune, Quinn, Tryndamere). `build_champion` level 9, no items, OFF -> ON: Vayne (`hp_lvl` -10,
  `dam_lvl` -0.4, `as_lvl` -0.3) HP 1240.52 -> 1173.12, AD 75.839 -> 73.143; Quinn HP 1286.18 ->
  1387.28, AD 77.198 -> 83.938; Tryndamere AD 92.96 -> 86.22. Tristana, Caitlyn, Ezreal, Jhin: no
  `ar` block (CHECK A cannot use them).
  **CHECK A - stat half (any Arena game with an `ar` champion, e.g. Vayne; predicate stated first):**
  at level >= 6, read the relay `curl -s -H "X-RC-Token: $TOK" http://127.0.0.1:8889/latest-liveclient`
  -> `activePlayer.level`, `activePlayer.championStats.maxHealth` / `attackDamage`, and the own row's
  `allPlayers[].items[].itemID`, plus the HUD augments. Record the snapshot with its `gameData.gameTime`.
  After the game, run `build_champion(snap, champ, level, item_ids=<owned>, mode="ARENA",
  augments=<picked>)` with `apply_mode_modifiers` False and True. Let gap = |ON - OFF| on each HP / AD
  axis the champion's `ar` block moves (HP for `hp_base` / `hp_lvl`, AD for `dam_lvl`; armor and attack
  speed are not read). NO RESULT conditions are checked FIRST: a gap under 10 HP or 1.5 AD drops that
  axis, and the whole sample is NO RESULT if no axis is left, if an owned item or augment grants a stat
  on that axis that DS does not model, if the player bought or was granted any Stat Anvil this game
  (Arena-only, e.g. `GainStatAnvil` / `CraftingPrisStatAnvil`; its stat is not in `items[]`), if an
  owned item id is unknown to the snapshot (`build_champion` raises `KeyError`), or if a timed buff or
  stack is up (sample out of combat, full HP, no buff icons). Then, over the axes left: PASS iff on
  every one |live - ON| <= gap / 4 and |live - OFF| > gap / 2. FAIL iff on any one |live - OFF| <=
  gap / 4 (Arena does not apply the addend). Any other outcome is NO RESULT (record the four numbers).
  A PASS on (A) closes
  only the stat half; the coach half stays open.
  **CHECK B - coach half (RM-875 SHIPPED `f5782b25b`; needs RC STARTED with `RC_ARENA_MODE_MODIFIERS=1`,
  read once at import, `coaches/arena_coach.py:84` - a merger / operator restart, never a lane act):**
  a wiring sub-check, not validation of the numbers. Rewritten 2026-10-25 by lane 9 s133 cycle 9
  (RM-879, source read at `6be7956da`); the old text said rows record no enemy stats or augments.
  ROW VINTAGE: since `f5782b25b` the Arena coach's `log_ds_run` call (`coaches/arena_coach.py:742-752`)
  appends `enemy_stats` (the six `core/ds_calibration.py:25-28` `_ENEMY_STATS_FIELDS`), `augments`,
  `engine_version` and `apply_mode_modifiers` after `match_key`, each only when supplied. Rows written
  before it, and every ARAM / SR / Brawl row, carry none of the four. The row records neither
  `caster_hp` nor `caster_hp_max`, so a re-run passes no self-HP (an R5 term the live call had).
  Predicate stated before any look. SAMPLE = a `data/ds_calibration.jsonl` row (main checkout) with
  `mode` `ARENA`, the live champion and a `ts` after this game's start. FLAG PROOF = the row's
  `apply_mode_modifiers` is `true`. A row with `false` was written flag OFF; a row WITHOUT the key was
  written by pre-RM-875 code (the seam did not exist, so an old-vintage row is NEVER re-run). Both are
  NO RESULT; the keyless case is a merger follow-up (RC not restarted onto `f5782b25b`). Re-run
  `dispatch_for_coach(champion, mode_engine="ARENA", level=<row>, item_ids=<row owned_items>,
  enemy_stats=EnemyStats(**<row enemy_stats>), augments=<row augments> or None, top=5)` with
  `apply_mode_modifiers` True and False, and compare `display_rows` `id` order to the row's `ds_picks`
  `item_id` order. PASS iff it equals the ON order and differs from the OFF order. FAIL iff it equals
  the OFF order (with the flag proof present, the flag did not reach the wire). NO RESULT = no ARENA
  row (the writer runs only when the dispatch returns rows, `arena_coach.py:728`), ON and OFF agree,
  the row's `engine_version` differs from `current_engine_version()` at re-run time, or the row
  matches NEITHER order (the missing self-HP is the first suspect). The newest row in that file is
  still 2026-08-02 (an ARAM game; 10469 lines on 2026-10-25); record the baseline line count before
  queueing.
  **RE-READ + TOOL (lane 9 PREP s144 cycle 12, 2026-10-27, source read at `d257c4f43`; NOT a tick).**
  STALE in the SPLIT paragraph above (kept as the cycle 7 record): "BLOCKED ON WIRING ... NEITHER has
  an `apply_mode_modifiers` parameter". Since `f5782b25b` (an ancestor of main) `inspect.signature`
  finds it on BOTH `dispatch_for_coach` and `rank_for_primary_archetype` (15 public
  `core/daemon_slayer_client.py` functions now). The Arena call is at `coaches/arena_coach.py:709` and
  passes the flag at `:721`, and `archetype_dispatch.py:369` forwards it. `core/focus_board_live.py:439`
  still hard-codes `False` (the focus board is not part of G5-05). CHECK B's own cites
  (`arena_coach.py:84`, `:728`, `:742-752`, `ds_calibration.py:25-28`) still hold at HEAD.
  FLAG STATE: no launcher, script or ops file sets `RC_ARENA_MODE_MODIFIERS` (grep over `ops/`,
  `scripts/`, `tools/`). RC started 2026-10-27T19:35:33Z, after `f5782b25b`, so it runs RM-875 code with
  the flag OFF. CHECK B still owes a merger / operator restart under `RC_ARENA_MODE_MODIFIERS=1`.
  TOOL (read-only, `tools/gated_g505_mode_mods.py`; tests `tests/test_gated_g505_mode_mods.py`). It
  implements both predicates above verbatim, and its output is NOT a tick:
  `python tools/gated_g505_mode_mods.py stat --lc <scratch>/g505_lc.json --augments <apiName,...> --clean`
  (CHECK A: the own `allPlayers` row via `activePlayer.riotId`, the champion via `rawChampionName`, the
  in-process DS `build_champion` ON / OFF, and only the HP / AD axes the `ar` block moves). The tool
  cannot see a Stat Anvil, a timed buff or an unmodelled stat. Without `--clean` (the operator's
  assertion that all three are absent) a PASS or FAIL is capped at INCOMPLETE and printed as `would be`.
  `python tools/gated_g505_mode_mods.py coach --since <game load> --champion <id> --rerun` (CHECK B: the
  main checkout's `data/ds_calibration.jsonl`, ARENA rows in the window, vintage split
  `pre_rm875` / `flag_off` / `flag_on`, the engine-version guard, then `dispatch_for_coach` ON / OFF as
  stateless DS `:8860` compute). Exit 0 PASS, 1 INCOMPLETE, 2 FAIL.
  BASELINE at 2026-10-27T21:30-05:00: 10469 lines, newest row still 2026-08-02 (ARAM). The `coach` mode over
  `--since 2026-07-01` reads 615 ARENA rows, all `pre_rm875` (no row carries the key). A smoke re-run
  (synthetic row Quinn, level 9, no items, armor 80 / MR 60 / 2500 HP) gives ON and OFF top-5 orders that
  differ at positions 3-4, so a flag-ON Quinn row would be decidable.
  SUBSTITUTION CHECK: (1) ON != OFF in-process proves only that the engine COMPUTES an addend; CHECK A's
  observed value is the game's `championStats`, never DS output. (2) A re-run that matches itself is
  not evidence; CHECK B's observed value is the order the live coach WROTE (`ds_picks`). (3) A row
  without `apply_mode_modifiers` is never re-run: code from before the seam cannot have sent the flag.
  (4) The dashboard's DS picks panel is NOT evidence for B: it renders the same dispatch output the
  row records, so reading it instead of the row adds nothing.
  **RE-CHECK (lane 9 PREP s144 cycle 95, 2026-11-07, source read at `7f0ffcb87`; NOT a tick).**
  Cites that MOVED (the paragraphs above are kept as their cycles' record): the flag read in CHECK B's
  header is now `coaches/arena_coach.py:85` (was `:84`; the `f7e88a157` ClassVar import at `:21`). The
  dispatch forward cited as `archetype_dispatch.py:360` (SPLIT) and `:369` (RE-READ) is now
  `coach_integration/archetype_dispatch.py:490` `out = _ds.rank_for_primary_archetype(**kwargs)`
  (`7c71cc132` and `a87abc141` took it to `:373`, then `64f126a3a` grew `dispatch_for_coach`); the
  flag enters the shared `seams` dict at `:458-459`, so the flat ranking and the ordered-build
  planner both get it. The SPLIT paragraph's server example `agents/daemon_slayer/server.py:482` is
  now `:678`, the first of 19 `_opt_bool(body, "apply_mode_modifiers", False)` reads, and its engine
  gate `engine.py:379-383` is now `:378-382`. Cites that HOLD: `arena_coach.py:709` (call), `:721`
  (flag passed), `:728` (writer runs only on dispatch rows), `:742-752` (`log_ds_run` with the four
  RM-875 keys);
  `core/focus_board_live.py:439` still hard-codes `False`; `core/ds_calibration.py:25-28`;
  `engine.py:101-108`. `inspect.signature` still finds `apply_mode_modifiers` on `dispatch_for_coach`
  and on `core.daemon_slayer_client.rank_for_primary_archetype` (15 public client functions carry it).
  FLAG STATE unchanged: default `"0"`; `git grep` over `ops/` `scripts/` `tools/` `rc-shell/` finds the
  name only in the G5-05 tool and an old lane report; neither the HKCU nor the HKLM Session Manager
  `Environment` key sets it. BASELINE unchanged: the main checkout's `data/ds_calibration.jsonl` is
  still 10469 lines, newest row 2026-08-02 (ARAM); 710 ARENA rows in all, none carrying the
  `apply_mode_modifiers` key. `python tools/gated_g505_mode_mods.py coach --since 2026-07-01` exits 1
  INCOMPLETE (NO_RESULT): 615 rows, all `pre_rm875`, engine 1.290.0 (= `ENGINE_VERSION`; DS patch
  16.21.1). Its tests pass (33). Both predicates stand as written; CHECK B still owes a merger /
  operator restart under `RC_ARENA_MODE_MODIFIERS=1`, then an Arena game. :8888 `/api/state` gave no
  body at 2026-11-07T00:30-06:00 (no game).
- **G5-06** (was D5) `RC_ARENA_STATE_DEBOUNCE` default-ON flip validation. **TRY THE REPLAY
  ALTERNATIVE FIRST to dodge the Arena game entirely.** NOT attempted 2026-07-04.
  **PREP 2026-10-25 (lane 9 s133 cycle 6, source read at `6af9f081f`; NOT a tick).**
  (1) THE REPLAY ALTERNATIVE HAS NO INPUT. RC has no Arena coach replay tool
  (`tools/aram_raw_replay.py` is ARAM-only; `tools/replay_build_order_validate.py --mode arena` covers
  build-order tables only). None of the 15 retained day logs (`logs/2026-10-11.log` onward) has an
  `arena_coach` or `Arena coaching` line. `data/arena_coach_shadow.jsonl` (617 rows,
  2026-07-05..07-21) holds only `champ` / `round` / `enemy_comp` / `deterministic` / `live_haiku`. The
  signature (`coaches/arena_coach.py:77` `_coach_state_signature`) needs hp, gold, level, kda, items,
  augments, teams, camp and anvil, so the shadow file cannot replay it. Only a fresh Arena game
  produces input.
  (2) PRECONDITION, NOT A LANE ACT: the default is OFF. `:68` reads
  `os.getenv("RC_ARENA_STATE_DEBOUNCE", "0") == "1"` ONCE at import. The variable is unset at User and
  Machine scope, and no `ops/` / `scripts/` launcher sets it. So no game drains this row until RC is
  restarted with the flag ON (an operator / merger act). `config/feature_flags.json`
  `arena.live_coaching = allow`, so the `_run_coach` gate at `:631` (and the `_run_vision` gate at
  `:604`) passes.
  CHECK, predicate stated before any look. PROOF THE FLAG IS ON: at least one `Arena state-debounce:
  signature unchanged` line (`:795`, `logger.debug`; the file handler is always DEBUG,
  `core/log_setup.py:161`) in `logs/<date>.log` during the game. Zero such lines = INCONCLUSIVE, never
  a pass. PASS iff, in one Arena game with that proof, sampled every 20-30 s while the player is
  alive: `data/arena_coaching_data.json` `game_time_s` (written at `:854`; a skip returns at `:799`,
  before the `:893` `safe_write`) never trails `/api/state` -> `liveclient.game_time_s` by more than
  150 s.
  **The ARAM 90 s bound (G3-12) does NOT carry over.** The Arena signature has NO game-time band, so
  on a stable board the 45 s ceiling (`:74`) IS the binding term. `_run_coach` is dispatched every 22
  s on a stable board (`:432`; `coaches/_base_coach.py:566`, `_last_coach` is set at dispatch `:579`,
  even for a run that then skips). The ceiling is measured from a stamp taken AFTER the call
  (`:899-902`). The Sonnet vision read (`:610`) runs on the separate `_vision_loop`
  (`coaches/_base_coach.py:476-528`, every 20 s), off the coach write path. Haiku has a 20 s
  per-attempt timeout (`:810`), plus the SDK's 2 default retries, which log nothing at RC's log
  levels. Worst case with single-attempt calls: three stable dispatches (66-71 s with poll
  quantization) plus one call of up to 20 s, about 91 s. A call slower than about 21 s (a retry)
  pushes the re-call to the fourth dispatch (88-95 s), so the 90 s G3-12 bound sits on the edge here.
  150 s covers one retried call, and a frozen coach still crosses it. The OFF baseline is one dispatch
  plus one call, at most about 45 s.
  FAIL only if a lag over 150 s while alive has, in its window, no `Arena coach error` line
  (`core/safe_coach_output.py:35`, decorator at `:627`), no `Arena: no fields parsed` line (`:821`,
  returns before the write), no `data/coach_tick_trace.jsonl` `mode=arena` `phase=coach` record over
  20000 `dur_ms` (`coaches/_base_coach.py:669`; the coaching call is always traced), the daily budget
  not exhausted, and `arena` not kill-switched. The budget and kill-switch gates
  (`coaches/_base_coach.py:535` / `:547`) return SILENTLY, so read the cost and coach settings, not
  the log. Otherwise the sample is INCONCLUSIVE. A vision-read failure does not touch the write path
  and excuses nothing. The coherence half (does the reused text still fit the board?) stays an
  operator eyeball, as in G3-12.
  **TOOL 2026-10-27 (lane 9 s144 cycles 13-14, source read at `ff32d603f`; NOT a tick).** The CHECK above
  is now one command per half: NEW read-only `tools/gated_g506_debounce_lag.py` (tests
  `tests/test_gated_g506_debounce_lag.py`). It grades the predicates above and adds tool-side
  preconditions, each of which can only turn a PASS into INCONCLUSIVE. Three verifier passes this
  cycle reproduced a false PASS (or a false FAIL) without them:
  (a) WINDOW. `--since` / `--until` (game clock start to game end, local time) are REQUIRED, so a
  proof line or sample from another game cannot count. The window must hold the WHOLE game: the
  first known sample's `liveclient.game_time_s` is at most 60 s, and the first poll after the last
  known sample comes within 35 s and shows the game over (a clean poll whose `mode_key` is not
  arena or that has no live game time; a failed poll does not count).
  (b) COVERAGE. The KNOWN samples tile the window, both edges included, with no gap over 35 s (the
  CHECK's 20-30 s cadence plus 5 s of poll jitter). Known = usable, or dead: `mode_key` arena,
  `liveclient.hp == 0` with `liveclient.hp_max > 0`, and a numeric game time. A failed poll is
  unknown, never dead, so it cannot excuse a gap. `dashboard/_liveclient.py` `_int_or_zero` turns a
  missing `currentHealth` into 0, so a run of dead samples may not span over 120 s.
  (c) STALE FILE. A coach file AHEAD of the live clock by more than 30 s is another game's file, not
  a fresh one.
  (d) SLOW CALL. A `data/coach_tick_trace.jsonl` record's `ts` is the call's END
  (`coaches/_base_coach.py` `_trace_coach_tick`, called from a `finally`), so the call spans
  `ts - dur_ms` to `ts`, and it excuses a lag when that span OVERLAPS the lag window, including a
  call still running at the sample.
  (1) CITE DRIFT, line numbers only, behaviour unchanged: RM-875 (`f5782b25b`) moved
  `coaches/arena_coach.py` lines below about `:740` down by 21 and lines `:77-707` down by 10 after
  `6af9f081f` (so the PREP's `:77` signature is now `:87` and its `:432` is `:442`). At HEAD the
  debounce log call is
  `:815-819` (was `:795`), the `Arena: no fields parsed` return `:842` (was `:821`), the `game_time_s`
  write `:875` (was `:854`), the `safe_write` `:914` (was `:893`), the ceiling stamp `:923`, the
  Haiku `timeout=20` `:831`, `_run_coach` `:638` with the `@safe_coach_output("Arena")` decorator at
  `:637`, and `_run_vision` `:609`. `:68` (flag read) and `:74` (45 s ceiling) hold. The tool's
  test pins the three log strings and the `"arena"` trace mode against the source, so a later drift
  of the STRINGS turns it red; line numbers are not pinned.
  (2) LIVE HALF, during the Arena game, from the main checkout, RC started with
  `RC_ARENA_STATE_DEBOUNCE=1` (the precondition above stays a merger / operator act):
  `python tools/gated_g506_debounce_lag.py sample --interval 25 > <scratch>/g506.jsonl`, started
  before the game clock starts and stopped with Ctrl-C after the game ends. Polls run at a fixed
  rate, so a slow GET does not stretch the cadence. Each poll reads `data/arena_coaching_data.json`
  -> `game_time_s` FIRST, then `/api/state` -> `mode_key`, `liveclient.game_time_s`, `liveclient.hp`,
  `liveclient.hp_max`, so a slow GET can only make the measured lag larger. One JSON line per poll,
  with `lag_s` and the local wall time. A PowerShell 5.1 `>` redirect (UTF-16 with a BOM, CRLF) is
  read back fine. A sample is usable only when `mode_key == "arena"`, `liveclient.hp > 0` (alive)
  and both game times are finite numbers.
  (3) GRADE HALF, after the game: `python tools/gated_g506_debounce_lag.py grade --samples
  <scratch>/g506.jsonl --log logs/<date>.log --since <clock-start HH:MM:SS> --until <end HH:MM:SS>`,
  plus `--budget-ok` only when the operator asserts the daily budget was not exhausted and `arena`
  was not kill-switched (those gates log nothing, so without the assertion an unexcused lag over
  150 s stays INCONCLUSIVE, never FAIL). The excuse window of an over-bound sample is the `lag_s`
  seconds before it; excuses are the two log strings above and an overlapping slow call (d). A
  missing `--trace` file cannot rule a slow call out (trace writes are best-effort), so it keeps an
  unexcused lag INCONCLUSIVE, never FAIL (cycle 14 verifier find). AMENDED 2026-11-04 (cycle 55,
  RM-1345; NOT a tick): every sample line now records `get_s`, the sampler's span from the
  coach-file read to the end of the `/api/state` GET, because the live clock is read at the GET's
  end and so the measured lag over-states the lag at the read by up to that span. An otherwise
  unexcused lag over 150 s is INCONCLUSIVE, never FAIL, when `lag_s - get_s` is within 150 s or
  the line carries no `get_s` (a sample file from the cycle 13-14 sampler).
  Exit 0 PASS, 1 INCONCLUSIVE / NO_RESULT, 2 FAIL.
  (4) EVIDENCE CONTRACT for the tick: the grade output's max lag (value), the sample file plus the
  `/api/state` and coach-file field paths above (source), the sample wall times with mode Arena,
  queue 1750 and the game time span (timestamp + context), and the predicate in the CHECK above.
  SUBSTITUTION CHECK: the unit tests in `tests/test_arena_state_debounce.py` prove the skip FIRES on
  an unchanged signature (compute); they say nothing about whether the SERVED file kept pace with the
  game clock, which only the sampled pair answers. A grade run over samples taken with the flag OFF
  is caught by the zero-proof-line rule (INCONCLUSIVE). Idle smoke at 22:01 local: `sample` read
  `mode_key` client with both game times null, and `grade` returned NO_RESULT, exit 1.
  **RE-CHECK 2026-11-07 (lane 9 s144 cycle 94, S144-G-85, source read at `5f3af5aad`; NOT a tick; no
  game up: :8888 `/api/state` and :2999 both gave curl 000).** (1) CITE DRIFT, line numbers only,
  behaviour unchanged. In the top part of `coaches/arena_coach.py` every cite in this row is now one
  line lower, because `f7e88a157` (RM-1719) added `from typing import ClassVar` at `:21`. The flag
  read is `:69` (was `:68`), the 45 s ceiling `:75` (was `:74`), `_coach_state_signature` `:88` (was
  `:87`) and `_STABLE_DEBOUNCE_S = 22.0` `:443` (was `:442`). `_run_vision` is `:610`, with its
  `live_coaching` gate at `:615`. `_run_coach` is `:639`, under `@safe_coach_output("Arena")` at
  `:638`, with its gate at `:642`. The cycle 13-14 cites further down still hold at HEAD: the
  debounce log `:815-819`, the Haiku `timeout=20` `:831`, `Arena: no fields parsed` `:842`, the
  `game_time_s` write `:875`, the `safe_write` `:914` and the ceiling stamp `:923`. The
  `coaches/_base_coach.py` cites hold too: kill switch `:535`, budget `:547`, dispatch debounce
  `:566`, `_last_coach` `:579`, the coach trace call `:669` and `_vision_loop` `:476`. So do
  `core/log_setup.py:161` and `core/safe_coach_output.py:35`. (2) THE PRECONDITION IS UNCHANGED. The
  default is still `"0"`. `RC_ARENA_STATE_DEBOUNCE` is absent from both the user and the machine
  environment keys (`reg query`, both "unable to find"). In tracked code, only
  `coaches/arena_coach.py`, `tests/test_arena_state_debounce.py` and this row's tool name it. So no
  launcher sets it, the post-cutover `ops/launcher/` included. (3) THE REPLAY INPUT IS STILL ABSENT.
  The 15 retained day logs (now `2026-10-17` to `2026-10-31`) hold no Arena coach line, and
  `data/arena_coach_shadow.jsonl` still has 617 rows. (4) THE TOOL IS STILL GREEN.
  `tests/test_gated_g506_debounce_lag.py` gave 29 passed at `5f3af5aad`, so its string pins still
  match the source. The CHECK, the tool steps and the evidence contract do not change.
  **RE-CHECK 2026-11-08 (lane 9 s144 cycle 117, S144-G-104, source read at `25b5f31fb`; NOT a tick;
  no game up: :8888 `/api/state` and :2999 both gave curl 000).** (1) CITE DRIFT, top of the file
  only, behaviour unchanged. The one commit since `5f3af5aad` that touches `coaches/arena_coach.py`,
  `coaches/_base_coach.py` or `core/safe_coach_output.py` is `81c26322c` (s156 S5 C7). It rewrote
  the module docstring (one line became two) and the Arena system prompt text (2v2v2v2 / pair
  wording and the SR-rune augment list, one line net shorter), and touched no code path. So lines
  `:3` to about `:175` are one lower and everything below is where it was. The flag read is `:70`
  (was `:69`), the 45 s ceiling `_STATE_DEBOUNCE_MAX_STALE_S` `:76` (was `:75`) and
  `_coach_state_signature` `:89` (was `:88`). These hold: `_STABLE_DEBOUNCE_S = 22.0` `:443`,
  `_run_vision` `:610` (gate `:615`), `_run_coach` `:639` under the decorator at `:638` (gate
  `:642`), the debounce log `:815-819`, the Haiku `timeout=20` `:831`, `Arena: no fields parsed`
  `:842`, the `game_time_s` write `:875`, the `safe_write` `:914` and the ceiling stamp `:923`.
  (2) THE PRECONDITION IS UNCHANGED, AND ITS ROUTE IS NAMED. The default is still `"0"`, the
  variable is absent from both the user and the machine environment keys (`reg query`, both
  "unable to find"), and no tracked launcher or config names it. Since the 2026-10-31 launcher
  cutover RC inherits rc-shell's environment: `ops/launcher/service_host.py` `child_environment`
  starts from `os.environ`, and `ops/launcher/services.json` sets only `RC_DASH_BIND` (top-level
  `env` is `{}`). So the flag reaches RC by a User-scope variable plus an rc-shell relaunch, or by
  an `env` entry in `ops/launcher/services.json` (a main-session path); either is a merger /
  operator act, as in G3-12. (3) THE REPLAY INPUT IS STILL ABSENT. The 15 retained day logs
  (`2026-10-17` to `2026-10-31`) hold no `arena_coach`, `Arena coaching` or `Arena state-debounce`
  line, and `data/arena_coach_shadow.jsonl` still has 617 rows. (4) THE TOOL IS STILL GREEN.
  `tests/test_gated_g506_debounce_lag.py` gave 29 passed at this cycle's lane HEAD (its string pins
  still match the source). The CHECK, the tool steps and the evidence contract do not change.
- **G5-07** Arena deterministic A/B choices lever (`dc6b3d80`) - shipped SHADOW-only; served coach
  output unchanged. The live serve flip is gated on shadow accrual (G7-17).
  **AGE CHECK: THE IN-GAME SERVE FLIP IS MOOT WHILE B4 STANDS (lane 9 PREP s144 cycle 92, S144-G-83,
  source read at `d10c2035c`, 2026-11-06; NOT a tick, NOT struck; no game up: :8888 /api/state gave
  no body, the driver's :2999 probe read URLError).** Four measured facts. (1) THE PREMISE PREDATES
  B4. The lever is `dc6b3d80f` (2026-07-06). Operator decision `docs/OVERLAY_COMPLIANCE_PLAN.md`
  section 6c (2026-08-11) moved live coaching to pre-game and post-game. B4-a `25540abab`
  (2026-08-12, RM-189) put `"choices"` in `LIVE_SUPPRESSED_FIELDS` (`dashboard/_state_builder.py:422`).
  `suppress_live_directives` (`:464`, applied at `:1052`) blanks it to `[]` whenever `is_live_game`
  holds, and `arena_mode` is one of `LIVE_GAME_FLAGS` (`core/live_game_gate.py:31`). The client gate
  `directivesAllowed` (B4-b `f2b7c4bae`, same day) hides `#rn-choices` too
  (`web/js/panels/coach_choices.js:211`). So Arena A/B
  chips flipped into the served field would still be blank on screen in every Arena game. A served
  flip could only show outside the game, and that is a pre-game / post-game design question, not a
  GATE 5 sitting. (2) THE ARENA BLOCK'S CHOICES NEVER REACH THE SERVED FIELD TODAY. The lever's
  `choices` (`core/arena_deterministic_coach.py:78` `_ARENA_CHOICE_LABELS`, `_safe_choices` `:232`,
  set in `build_block` at `:374`) is built only inside `shadow_log_arena_coach`
  (`dashboard/_deterministic_coaching.py:1493`). That function hands it to `log_arena_coach` (`:1639`)
  and returns nothing. The served `coach["choices"] = resolve_choices(coach, det)`
  (`dashboard/_state_builder.py:1028`, def `dashboard/_deterministic_coaching.py:1067`) reads
  `compute_deterministic`'s choices, then the native Haiku list, then the synthesizer. It never reads
  the Arena block. (3) G7-17 NEVER MEASURES CHOICES. `tools/arena_shadow_report.py` and
  `tools/gated_g717_arena_readback.py` contain the word `choices` zero times. They gate on ACTION
  class agreement only. The det choices column is a pure function of the det action plus the det
  `fight_rule`: labels and tags come from the action alone, and B's `expected_outcome` is the
  `fight_rule` when one is set (`_safe_choices`). Read-only count
  over the main checkout's `data/arena_coach_shadow.jsonl` (617 rows, `ts` 2026-07-05..2026-07-21,
  all pre-RM-868): 614 rows carry a 2-entry `deterministic.choices`, all tagged `arena_rule`, and all
  614 labels equal `_ARENA_CHOICE_LABELS[action]`. The other 3 rows (all stamped 2026-07-05T00:11Z)
  predate the lever and have no key. So "accrual" of this column adds nothing beyond the `action`
  and `fight_rule` columns the same rows already log, and G7-17 already grades the action. (4) THE HAIKU SIDE HAS NO CHOICES TO COMPARE AGAINST.
  No row has a non-empty `live_haiku.choices`: it is `[]` on 614 rows and absent on the 3 pre-lever
  rows. The writer path exists:
  `coaches/arena_coach.py:867` stores `CoachOutput.from_fields(fields).choices`. But the prompt allows
  `[]` ("an empty array is better than padded choices", `:190`). Telling a Haiku `[]` apart from a
  swallowed malformed array needs the raw response, which no shadow row keeps. So a choices-level
  agreement metric cannot be built from the existing record. That is a MERGER FOLLOW-UP, not a
  gated question.
  WHAT THE LEVER IS NOW: the section-6c "silent capture of decision branch points", in the shadow
  record for a post-game replay. The live residual collapses into two rows that already carry
  predicates. G7-17 (accrual: the READY readback's `cohort` / `report` checks over post-fix rows) and
  G2-28 (the B4 INVERSE check: `coach.choices` is `[]` in one LIVE window, `#rn-choices` hidden).
  READY add-on for the G7-17 sitting (one read-only line, predicate stated before any game). PASS iff
  every post-cutoff row whose `deterministic.action` is one of the five `_ARENA_CHOICE_LABELS` keys
  has exactly 2 `deterministic.choices` entries tagged `arena_rule`. FAIL if any such row lacks them.
  Rows with another action are not counted, and zero counted rows is NO RESULT. Idle smoke this
  cycle: cutoff `2026-07-01T00:00:00+00:00` printed `617 3` (the 3 pre-lever rows), cutoff
  `2026-10-25T06:28:48+00:00` printed `0 0` (no post-fix row yet, so NO RESULT). From the main
  checkout root, with the same UTC cutoff G7-17 uses:
  `python -c "import json,sys;from core.arena_deterministic_coach import _ARENA_CHOICE_LABELS as L;c=sys.argv[1];rs=[json.loads(l) for l in open('data/arena_coach_shadow.jsonl',encoding='utf-8') if l.strip()];rs=[r for r in rs if r['ts']>=c and r['deterministic'].get('action','').upper() in L];bad=[r['ts'] for r in rs if [x.get('source_tag') for x in r['deterministic'].get('choices') or []]!=['arena_rule']*2];print(len(rs),len(bad),bad[:3])" <UTC cutoff>`
  (the cutoff must be UTC `+00:00`, the G7-17 string-compare trap). Evidence contract: value = the
  two counts; source = those rows' `ts` and `round`; timestamp = the cutoff, with mode Arena q1750;
  predicate = this paragraph. SUBSTITUTION CHECK: this answers only that the det branch set was
  COMPUTED and LOGGED in a real Arena game. That is all the section-6c capture claims. It never
  answers whether a chip RENDERED, and under B4 no chip should render in game. A non-empty served
  `coach.choices` in a live Arena window is a G2-28 compliance FAIL, not a G5-07 pass. RE-FILE
  PROPOSAL (a human edits; the lane does not): fold G5-07 into G7-17 as a dependency line, and drop
  "live serve flip" from its text while B4 stands.
  **RE-CHECK (lane 9 PREP s144 cycle 101, 2026-11-07, source read at `0e0673235` on main
  `86ed5e52d`; NOT a tick, NOT struck; no game up: `:8888`, `:2999` and `:8860` all curl 000).**
  Every cite above HOLDS, no drift: `LIVE_SUPPRESSED_FIELDS` `dashboard/_state_builder.py:422`,
  `suppress_live_directives` `:464` applied `:1052`, `resolve_choices` call `:1028`;
  `LIVE_GAME_FLAGS` `core/live_game_gate.py:31`; `directivesAllowed` gate
  `web/js/panels/coach_choices.js:211`; `_ARENA_CHOICE_LABELS` `core/arena_deterministic_coach.py:78`,
  `_safe_choices` `:232`, `build_block` field `:374`; `shadow_log_arena_coach`
  `dashboard/_deterministic_coaching.py:1493`, its `log_arena_coach` call `:1639`, `resolve_choices`
  def `:1067`; `coaches/arena_coach.py:867` (`_choices_list`) and the `[]` prompt clause `:190`.
  Idle re-run of the one-liner (run from the worktree with `python -B` and the main checkout's
  `data/arena_coach_shadow.jsonl` passed by absolute path, so no bytecode lands in the main
  checkout): cutoff `2026-07-01T00:00:00+00:00` -> `617 3`, `2026-10-25T06:28:48+00:00` -> `0 0`,
  `2026-11-01T01:33:09+00:00` -> `0 0` (still 617 rows, still NO RESULT).
  CUTOFF RULE, stated before any game: the add-on's cutoff is the G7-17 readback's `restart` line
  value, copied verbatim (`tools/gated_g717_arena_readback.py` prints it as UTC isoformat WITH
  microseconds, e.g. `2026-11-01T01:33:09.977397+00:00`; shadow rows spell `ts` the same way, UTC
  `+00:00` with microseconds, 617/617, so the string compare orders correctly). It therefore
  inherits the G7-17 DEAD-RC TRAP (G7-17 RE-CHECK, cycle 100): `health.json` still reads `alive`
  true, `pid` 18724 (not running), `started_at` 2026-11-01T01:33:09Z, while `launcher_status.json`
  top `state` is `halted` (`updated` 2026-11-01T02:17:21Z). A stale cutoff cannot false-PASS this
  add-on (a down RC logs no rows, so the count stays 0 = NO RESULT), but the same precondition binds:
  launcher `state` `running` and `:8888` `/api/state` 200 BEFORE the game, else start RC first and
  use the NEW `started_at`.
- **G5-08** (was the B47b Arena tail) Celestial Opposition Arena mirror **444644 magnitude confirm**
  (Meraki 50% vs DDragon 90%) - the id is EXCLUDED from the R108 credit pending this live-Arena read.
  **PREP 2026-10-25 (lane 9 s133 cycle 6, data read at DS 16.21.1; NOT a tick).**
  (1) NAME CORRECTION: 444644 is **Crown of the Shattered Queen**, not Celestial Opposition. DDragon
  `data/daemon_slayer/16.21.1/items.json`, Meraki and
  `agents/daemon_slayer/_effects_data.py:3292-3297` all name it Crown. Celestial Opposition is 3869
  (maps 11 / 453) and has no Arena mirror at 16.21.1. The parent row is G2-24, which covers both
  items, so the label was carried across from there.
  (2) FEEDS AT 16.21.1. DDragon 444644 (maps.30 only, 2750 g): "reducing incoming champion damage by
  90%", "persists for 1.25 seconds". Meraki 444644 (the only Crown row Meraki has): "50%, lingering
  for 3 seconds". Meraki's manifest is `content_patch` 25.15. The SR row 664644 reads 40% / 3 s. The
  exclusion is `agents/daemon_slayer/_item_general_dr.py:139` `_GENERAL_DR_UNSOURCED_MIRRORS`, and
  `agents/daemon_slayer/tests/test_r144_mirror_slice_b.py:255` re-derives the 90 / 50 split every run.
  (3) The R144 reason ("unresolvable headless") predates the 2026-10-24 Settled amendment (RM-808):
  item passive formulas follow live DDragon prose first, CommunityDragon second, Meraki last. Under
  that rule DS seeds DDragon's 90% / 1.25 s. That is a SOURCE choice, not a measurement of the Arena
  value, and DDragon's 444644 prose also renders a malformed "(0s)" cooldown. Meraki's 50% / 3 s is
  the frozen 25.15 text. The headless answer to the row's question is CommunityDragon 16.21 game data
  for 444644 (RM-871 step 1, mandatory). So the row is a "Not actually live-gated" CANDIDATE (filed in
  that section; a human moves it, and only if that data states 90%).
  CHECK, if an Arena game comes first (one glance, predicate stated before looking): open the shop,
  hover Crown of the Shattered Queen, and capture the frame (its `ts` checked against `game_time_s`).
  The read is DDRAGON-90 iff the tooltip says 90% and 1.25 seconds, and MERAKI-50 iff it says 50% and
  3 seconds. Anything else is recorded as read and decides nothing. An untimed or stale frame is no
  result. This check reads the client's STATED magnitude only, which is the same string DDragon
  renders, so it is not independent of DDragon. The uptime residual stays with G2-24.
  **RE-CHECK 2026-11-07 (lane 9 s144 cycle 94, S144-G-85, read at `5f3af5aad`; NOT a tick).** DS is
  still at 16.21.1 (`data/daemon_slayer/current.txt`), so the feed reading in (2) stands, and RM-871
  is still open in ROADMAP NOW. One cite moved, line number only: `_GENERAL_DR_UNSOURCED_MIRRORS` is
  now `agents/daemon_slayer/_item_general_dr.py:140` (was `:139`), and it still lists 444644, at
  `:141`. `agents/daemon_slayer/tests/test_r144_mirror_slice_b.py:255`
  (`test_ddragon_and_meraki_still_disagree_on_444644`) and
  `agents/daemon_slayer/_effects_data.py:3292-3297` hold.
  **RE-CHECK 2026-11-08 (lane 9 s144 cycle 118, S144-G-105, read at `a9da7c32f`; NOT a tick).** DS
  moved to **16.22.1** (`a14fc853e`, RM-1338; `data/daemon_slayer/current.txt`). The 444644 record is
  byte-for-byte the same at 16.22.1 as at 16.21.1 in BOTH feeds (parsed-dict equality, read-only):
  DDragon `data/daemon_slayer/16.22.1/items.json` still reads maps.30 only, 2750 g, "reducing incoming
  champion damage by 90%", "persists for 1.25 seconds after taking champion damage. (0s)" (the
  malformed cooldown stands), and `items_meraki.json` still reads 50% / "lingering for 3 seconds",
  with the manifest's `meraki_items.content_patch` still 25.15. The SR row 664644 still reads 40% /
  3 s, and 3869 Celestial Opposition is still maps 11 / 453 with no Arena mirror. So the 90 / 50
  conflict, the name correction (1) and the CANDIDATE stand; the CANDIDATE's "CommunityDragon 16.21"
  now means the current DS patch (16.22). RM-871 is still open (`[ ]` in ROADMAP NOW). Cites:
  `_item_general_dr.py:140` / `:141` and `test_r144_mirror_slice_b.py:255` hold (that test reads the
  CURRENT patch and passed this cycle, so the disagreement is re-derived at 16.22.1);
  `_effects_data.py:3292-3297` is now `:3295-3304` (line number only). Observation, not a defect
  filed: that entry's `note` paraphrases Safeguard as "90% until first champion damage taken",
  which omits DDragon's 1.25 s persistence; it is `defensive_only`, so no DS number reads it. The
  tooltip CHECK and its predicate are unchanged. G5-09's re-check cites (`:474`, `:715`, `:936`,
  `:988`, `:1037`, `:1058`; `rank.py:364` / `:367` / `:408`) also hold at `a9da7c32f`: the only
  later commit to `coaches/arena_coach.py`, `81c26322c`, did not move them. Nothing ticked; no count
  moved.
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
  **RE-CHECK (lane 9 PREP s144 cycle 96, 2026-11-07, source read at `988483ed2`; NOT a tick).**
  Cites that MOVED (the text above and the drain card's PRECHECK are kept as their cycles' record).
  This row (written at `2a7010203`): `arena_coach.py:448` (`state["augments"] = ...`) is now `:474`;
  `:682` (the `augments=` kwarg into the DS dispatch) is now `:715`; the all-or-nothing block
  `:989-995` is now `:1052-1058` (`return  # all-or-nothing guard` at `:1058`). The GATE 5 drain
  card's G5-09 PRECHECK (written at `b20542413`): `_handle_augment_select`'s `augments_picked` write
  `:968` is now `:988` (method at `:936`); `_reconcile_augment_hud` `:1015-1062` is now `:1037-1084`;
  the all-or-nothing return `:1033-1036` is now `:1055-1058`; the `item_build` join `:886` is now
  `:907`. Whole-file drift, no logic change in the cited lines. The chain HOLDS:
  `coach_integration/archetype_dispatch.py` takes `augments` (`:296`), materialises it once (`:391`)
  and forwards it (`:416`, `:539`); `agents/daemon_slayer/rank.py:408` `_champion_is_melee` checks
  `_augment_forces_melee` first (ids `{134}` at `:364`, api names at `:361`). MEASURED in-process,
  read-only, on a ranged record `{"stats": {"attackrange": 550}}`: `[134]`, `["134"]`,
  `["DrawYourSword"]` and `[{"id": 134}]` read melee True; `["Draw Your Sword"]`,
  `["drawyoursword"]`, `None` and `[]` read False, so the display-form risk above STANDS.
  `_resolve_augment_apiname("Draw Your Sword")` still returns `"DrawYourSword"`; the map now holds 280
  keys (225 api names) from the newest `data/daemon_slayer/<patch>/arena_augments.json` (the 281 above
  was 2026-07-18's snapshot; a data fact, not a guard). CORRECTION to "No headless test covers OCR ->
  resolve -> all-or-nothing": the all-or-nothing half IS pinned, as intended behaviour, by
  `tests/phase2_smoke/test_arena_augment_hud.py` `test_partial_resolve_preserves_haiku` (real
  `Coach._reconcile_augment_hud`, stubbed resolver, `b64599235` 2026-05-04, before this row; the
  method's docstring and the test module's both argue for the guard). What no test covers is the real map plus a vision OCR string, so
  the live glance stays the only check. Predicates unchanged; nothing ticked; no count moved.
- **G5-10** `[HOLD 2026-06-20]` (was D8) Arena S2 augment level-up + crafting - trigger on the 26.09
  PBE (separate PBE install). ADR-010. NOT part of the current Arena sitting.
  **AGE RE-CHECK 2026-11-10 (lane 9 s144 cycle 146, S144-G-134, source read at `998ae3e1f`, DS patch
  16.22.1, ENGINE_VERSION 1.291.0; no game up; NOT a tick; the HOLD tag is left for a human).** (1) THE
  HOLD TRIGGER FIRED BEFORE THE ADR WAS WRITTEN: the cdragon Arena snapshot DS committed for 16.9.1
  (added `c306f56d4` 2026-05-03, pruned `c95396fd4`; read it with
  `git show c306f56d4:data/daemon_slayer/16.9.1/arena_augments.json`) already carries the level-up and
  crafting data: 202 of 219 records have a `MaxLevel` dataValue (1.0 x55, 2.0 x100, 3.0 x47) and three
  Crafting records exist - `CraftingAugmentSlot` ("Unlock your ...th Augment Slot"), `CraftingSellAugment`
  ("Remove an Augment. Gain @AugmentLevelsToGrant@ random Augment Levels") and `CraftingPrisStatAnvil`.
  The tracked 16.22.1 snapshot has 208 of 225 with `MaxLevel` (1.0 x62, 2.0 x103, 3.0 x43) and the same
  three. ADR-010 (dated 2026-05-21) waited on a 26.09 PBE that live data had already passed; no PBE
  install is needed. (2) ADR-010'S PREDICTED SCHEMA IS REFUTED: no record has `levels[]`,
  `dataValuesByLevel` or any record-level key containing "level" (the level data lives INSIDE
  dataValues: `MaxLevel`, `AugmentLevelsToGrant`); both snapshots carry the same ten record keys
  (id, apiName, name, rarity, desc, tooltip, dataValues, calculations, iconLarge, iconSmall). Of the
  dataValues entries, 1003 of 1016 (16.9.1) and 1024 of 1037 (16.22.1) are 7-element lists, the other
  13 scalar 0; 149 / 147 augments have list entries that differ along the list. Which index is which in-game level is NOT on disk (no snapshot older
  than 16.9.1 exists to diff; the `augments.py:92-93` comment calls the axis "stack/level"). (3) THE
  ADR SEAM WAS NEVER ADDED AND ITS CITED SIGNATURE DRIFTED: `compute_augment_stats` (`augments.py:332`)
  takes `(augments, snapshot)`, with no `level` kwarg (ADR-010 cites `(augment_or_id, *, mode=...)`);
  `_v` (`augments.py:94`) reads index 0; `tests/test_arena_s2_augment_leveling.py` does not exist.
  `StatContext.level_index` (`augment_formula_eval.py:148`, read at `:243`) exists, but `git grep`
  finds no tracked non-test `.py` that builds a `StatContext` outside that module, and no tracked
  non-test `.py` / `.js` / `.mjs` names `MaxLevel` or `AugmentLevel`. So every Arena game since
  26.09 has run the level-0 path that ADR-010's Trade-off section describes (fail-soft under-credit of
  a leveled augment). (4) STILL LIVE-GATED: only the index-to-level mapping and the on-screen level
  read. LCU and `:2999` carry no augment data (CLAUDE.md Settled; augment-OCR is the path), and no RC
  producer emits a live augment level, so the live half is blocked on wiring, not on a PBE. READY
  predicate for a later sitting, stated before any game: in an Arena game, read one leveled augment's
  tooltip number off the screen at level 1 and at level 2; PASS iff each value equals exactly one
  entry of that key's 7-element list in the patch's `arena_augments.json`, and two augments give the
  same index for the same level. Evidence: value, augment apiName, level, frame ts and game round.
  PROPOSAL (a human edits; the lane does not): re-tag `[HOLD 2026-06-20]` as BLOCKED ON WIRING with
  this note as the reason. The data-lift half (read `MaxLevel`, thread a level through
  `compute_augment_stats` / `StatContext.level_index`) is a "Not actually live-gated" candidate for the
  DS roadmap (S144-G-135), Tier-2. Nothing ticked; no count moved.
- **G5-11** Focus-board Arena team layout - the GATE 5 verification RM-844 / RM-854 left owed ("shadow-only
  ... until a gated row verifies it in GATE 5", `BACKLOG.md` RM-844). Filed and READIED 2026-10-27 by lane 9 PREP (s144 cycle 11,
  source read at `d257c4f43`; NOT a tick). The shadow column (`core/arena_coach_shadow.py:139`
  `_focus_board_column`) feeds the DS focus board from `core/focus_board_live.py:283` `roster_from_lc`,
  which calls every Live Client player on my `team` (minus me) an ally and every other non-blank team an
  enemy. Its own docstring (`core/focus_board_live.py:32` TEAMS) says "In Arena that makes my partner the
  one ally ... NOT live-verified yet: the gated GATE 5 row owns that." This is that row. It asks ONE
  thing: was the board fed the right teams? Whether its pick is any good is accrual (the G7-17 shape),
  and nothing here renders (the column is shadow-only, nothing is served).
  BASELINE (idle, read-only, 2026-10-27 about 21:00 local): RC `started_at` 2026-10-27T19:35:33Z, after
  RM-854 (`ec2efcc89`, 2026-10-25), so no restart is owed; the kill switch `RC_FOCUS_BOARD_SHADOW`
  defaults ON (only `0` turns it off). `data/arena_coach_shadow.jsonl` holds 617 rows, all
  2026-07-05..07-21, and 0 of them carry a `focus_board` column: no Arena game has run since RM-844.
  WHY PASS MUST NOT BE ASSUMED (a historical observation, not evidence for this row): those 617 rows'
  `enemy_comp` comes from the same `team != my_team` rule (`dashboard/_liveclient.py:284-285`), and its
  sizes are 0 (182 rows), 3 (49), 6 (19), 9 (331), 12 (34) and 15 (2). If each Live Client `team` value
  grouped one duo and every listed group were whole, the enemy count would always be even; 3, 9 and 15
  rule that out for the July rotation, and the sizes fit whole groups of 3. The repo itself records
  live queue 1750 as "Arena 3x6" (`core/queue_modes.py:82`, `lcu/champ_select_shape.py:62`); read as
  6 teams of 3, 15 = 18 - 3 is a CORRECT trio grouping, and then my side holds 2 allies, not 1. The
  size also changes inside one game (12 -> 6 -> 12 within minutes, 2026-07-08), so the listed players
  are not a fixed lobby. So a PASS here may well be a trio PASS - and even then the RM-844 "my partner
  the one ally" / "2v2 team TTK" wording (`core/focus_board_live.py:32` TEAMS) is stale and owed a
  docstring fix. The tool below reads the truth instead of guessing the format.
  DRAIN STEPS (copy-paste; `<scratch>` is any directory outside the repo, never a tracked path):
  (1) in champ select, after every pick locks: `curl -sk https://127.0.0.1:8888/api/state >
  <scratch>/g511_cs.json` (the subteam roster is `lcu.champ_select.arena_teams`, distilled from LCU
  `additionalSubteamData` by `lcu/champ_select_shape.py:180` `arena_teams`, `is_me` on mine); note the
  local time the game loads. (2) in game, after round 1 starts: `curl -s -H "X-RC-Token: $TOK"
  http://127.0.0.1:8889/latest-liveclient > <scratch>/g511_lc.json`. (3) after 3 or more rounds:
  `python tools/gated_g5_focus_layout.py --cs <scratch>/g511_cs.json --lc <scratch>/g511_lc.json
  --since <game load time> --until <game end>` (any ISO form; read-only; exit 0 PASS, 1 INCOMPLETE,
  2 FAIL).
  PREDICATE (stated before any game; the tool implements exactly this). Truth = the `is_me` subteam's
  champions minus me (partners) and every other subteam's champions (enemy cells), mapped from DDragon
  numeric keys to snapshot ids. NO RESULT first: not exactly one `is_me` subteam, no other subteam or
  an empty one (lobby not revealed), a cell with championId 0, or my live champion not in my subteam
  (the two captures are from different games). LAYOUT TEST, on one allies list and one enemies list,
  in order: NO RESULT if an id is unresolved or is in no subteam (another game; my own champion counts
  as known); FAIL iff a player is on the WRONG SIDE - an ally that is not a partner (me included), or
  an enemy beyond the enemy cells as a multiset (a partner counted as an
  enemy; a mirror champion on an enemy subteam is not one); NO RESULT if a partner is merely missing
  (not listed, or skipped by the board for a missing level); else PASS. ROSTER = the layout test on
  `roster_from_lc` over the in-game capture (NO RESULT if the Live Client lists more players than the
  subteams hold). SHADOW = the layout test on each `ok` column's `allies` / `kill_order`, over rows in
  the window (`--since` inclusive, `--until` exclusive) whose `champ` is my champion; one unresolved or
  outside id makes that column NO RESULT before the wrong-side test runs, so it can hide a FAIL but
  never makes a PASS; PASS iff one column passes and none
  fails, FAIL iff any fails, else NO RESULT (only `warming` / `pending` / `throttled`, or no rows -
  then check the kill switch). The row PASSES only when ROSTER and SHADOW both PASS.
  EVIDENCE CONTRACT: the tool's printout is the VALUE (team-value histogram, subteam sizes, partners,
  allies, enemy count, column status counts, `kill_order` lengths); SOURCE = `/api/state` ->
  `lcu.champ_select.arena_teams`, relay `/latest-liveclient` -> `data.allPlayers[].team`, and
  `data/arena_coach_shadow.jsonl` -> `focus_board.allies` / `.kill_order`; TIMESTAMP = both capture
  times plus `data.gameData.gameTime` from the in-game capture, mode `arena`, queue 1750; and this
  predicate. The tool prints champion ids only; never paste a Riot id, game id or puuid.
  SUBSTITUTION CHECK (answer it before the tick): the column's `allies` are made by the very rule under
  test, so the column agreeing with the Live Client grouping proves nothing (circular); a `status` `ok`
  proves only that the board COMPUTED. The one independent source is the LCU subteam roster, a
  different API the rule never reads. If the operator wants a second witness, the in-game HUD names the
  partner. A FAIL is a Tier-1 adapter fix (the partner from a subteam signal, not `team` equality, and
  the same question for `coaches/arena_coach.py` `is_partner`, which uses the same equality); the
  column stays shadow-only either way.
  **RE-CHECK (lane 9 PREP s144 cycle 98, 2026-11-07, source read at `6b092a493`; NOT a tick).** The
  row's read sha `d257c4f43` is not an ancestor of HEAD (a lane sha re-written on landing), so every
  cite was re-read by symbol. MOVED (the text above is kept as cycle 11's record):
  `core/arena_coach_shadow.py:139` `_focus_board_column` is now `:140` (guarded by
  `_safe_focus_board_column` `:193`, called at `:289` and `:297`); `dashboard/_liveclient.py:284-285`
  (the `team != my_team` enemy rule) is now `:388-390` (`my_team` `:388`; the name now passes
  `_str_or`), and the shadow's `enemy_comp` still reads that list (`core/arena_coach_shadow.py:266-269`,
  `lc.get("enemy_team")`); `lcu/champ_select_shape.py:180` `arena_teams` is now `:181`
  (`additionalSubteamData` read at `:193`). HOLD: `core/focus_board_live.py:283` `roster_from_lc`
  (`my_team` at `:298`, the `team == my_team` split at `:320`); `:32` TEAMS still says
  "my partner the one ally" and "the 2v2 team TTK", so the docstring fix owed above is still owed;
  `core/queue_modes.py:82` and `lcu/champ_select_shape.py:62` still read 1750 as "Arena 3x6";
  `KILL_SWITCH_ENV` `RC_FOCUS_BOARD_SHADOW` (`core/focus_board_live.py:108`) still defaults ON
  (`enabled()`, `:152`, only `0` disables). NEW cite: the `coaches/arena_coach.py` `is_partner`
  equality named above is `:1305` (`p.get("team") == my_team_id and p is not me`). BASELINE (idle,
  read-only): `data/arena_coach_shadow.jsonl` in the main checkout still holds 617 rows,
  2026-07-05..07-21, 0 with a `focus_board` column, so no Arena game has run since RM-844; RC's last
  `health.json` `started_at` is 2026-11-01T01:33Z (after RM-854, no restart owed) and :8888 did not
  answer this cycle. `python tools/gated_g5_focus_layout.py --data-root <repo>/data` with no capture
  printed INCOMPLETE (subteams, roster and shadow each NO_RESULT) and exited 1, the idle shape the
  drain expects. Predicate,
  drain steps and substitution check unchanged; nothing ticked; no count moved.
  **RE-CHECK (lane 9 PREP s144 cycle 119, 2026-11-09, source read at `b44d494b5`; NOT a tick).**
  `6b092a493` is NOT an ancestor of HEAD (the pre-rebase copy of S144-G-88, now `2b5a0b771`); the
  drift was read per file with `git log 6b092a493..HEAD`, and the 11 off-line commits
  (S144-G-78..88) touch none of the files below.
  No commit touched `dashboard/_liveclient.py`, `lcu/champ_select_shape.py` or
  `tools/gated_g5_focus_layout.py`. `core/arena_coach_shadow.py` (`36ba25a07`) and
  `core/focus_board_live.py` (`36ba25a07`, `434ee0359`) changed only by dropped `# noqa: BLE001`
  markers and `notes + [...]` respelled as `[*notes, ...]` (ruff ratchets; no behaviour change), so
  every cycle-98 cite in them HOLDS: `_focus_board_column` `:140`, `_safe_focus_board_column` `:193`
  (called `:289`, `:297`), `enemy_team` read `:266-269`; `roster_from_lc` `:283` (`my_team` `:298`,
  split `:320`), `KILL_SWITCH_ENV` `:108`, `enabled()` defined `:150` (its return, the only-`0` test,
  is `:152`). The TEAMS section heading is still `:32` and its text (`:33-37`) still says "my partner
  the one ally" and "the 2v2 team TTK", so the docstring fix is STILL OWED. `dashboard/_liveclient.py`
  `:388-390` and `lcu/champ_select_shape.py:181` / `:193` / `:62` hold. `coaches/arena_coach.py`
  `is_partner` still `:1305` (`81c26322c` changed prompt text only). MOVED: `core/queue_modes.py:82`
  is now `:107` (`7d627b453` grew the module docstring and hardened the id coercion); the 1750 entry
  still maps to `arena` and still reads "Arena 3x6". BASELINE (idle, read-only): :8888 and :2999 did
  not answer (no game; RC down, `health.json` last written 2026-10-31 local, its `started_at`
  2026-11-01T01:33Z unchanged, so no restart since RM-854 is owed);
  `data/arena_coach_shadow.jsonl` in the main checkout still 617 rows, 2026-07-05..07-21, 0 with a
  `focus_board` column (file last written 2026-07-20 local), so still no Arena game since RM-844;
  `RC_FOCUS_BOARD_SHADOW` is unset at User and Machine scope, so after the launcher cutover the
  shadow column stays ON by default with no env route needed. The tool with no capture again printed
  INCOMPLETE (subteams, roster and shadow each NO_RESULT) and exited 1;
  `tests/test_gated_g5_focus_layout.py` 23 passed. Predicate, drain steps and substitution check
  unchanged; nothing ticked; no count moved.

---

## GATE 6 - PHYSICAL / OPERATOR HARDWARE (over any running game on Legion)

Rides on top of whatever gate is already running. No separate game needed.

- **G6-01** (was E3) **rc-shell Electron MAIN relaunch - PREREQUISITE for every `[OVERLAY-*]` batch**
  (disappear-fix / pinned behavior + the P4.x window logic; the renderer half auto-reloads via ADR-008
  but MAIN does not). Plus the post-W5 interaction-layer live verify pass (the 2026-06-29 F1-01 confirm
  covered render surfaces only). SOURCE: ROADMAP.md:23; OVERLAY_BUILD_MASTER_PLAN.md:666/828.
  **AGE RE-CHECK + PROBE (lane 9 PREP s144 cycle 120, 2026-11-09, S144-G-107; NOT a tick).**
  (1) Both SOURCE cites are dead. `docs/OVERLAY_BUILD_MASTER_PLAN.md` is now 351 lines; its live-game
  verify set reads at `:349` ("GATED-on-live-game (verify-pass after W1 + W5, not a cycle): F1-04,
  F1-05, F1-06", F1-01 LIVE-CONFIRMED 2026-06-29). `ROADMAP.md:23` no longer carries it (line 23 is
  blank, `:20-22` are the subplan list); the "rc-shell Electron relaunch owed (live
  disappear-fix/pinned)" clause lives in RM-03 (search that phrase). (2) The interaction-layer half is no longer G6-01's: F1-05 (ACTIVE-knob physical press) is
  G6-02, which PASSED in the DRAIN SESSION 2026-07-20 at the top of this file (the G6-02 row text
  below still reads PARTIAL; the drain-session record is the later one); F1-04 (capability gap,
  `RC_CAPGAP_SURFACE`) is G4-12; F1-06 (packaging) is release-gated, already proposed out of the set
  in "Doc hygiene follow-ups" (a). What remains is the PRECONDITION alone. (3) It was met once on
  record (G6-04, 2026-08-02: rc-shell pid 4140 relaunched 11:26 on the fixed code) and is met again
  by every app start since the 2026-10-31 launcher cutover, so it RECURS and is never ticked closed.
  (4) Three traps: `rc-shell\launch_overlay.bat` names no profile and starts no service
  (`docs/OPERATIONS.md`, launcher section); a packaged `Amberstone Shell.exe` loads the app it was
  built from, not `rc-shell/src`, so its start time proves nothing; and a lane commit's committer time
  can predate the merge that wrote its bytes into the checkout, so the bound also takes file mtime.
  PROBE (one command, read-only, run against the checkout the shell was launched from):
  `python tools/gated_g601_shell_fresh.py --repo <repo>` (from a lane worktree it reads
  WRONG_CHECKOUT). PREDICATE (stated before any game): PASS iff exactly one Electron MAIN process
  (a shell image with no `--type=` switch), its executable is
  `<repo>/rc-shell/node_modules/electron/dist/electron.exe`, its argv names `--profile dev`, and its
  creation time is AFTER max(committer time of the newest commit touching `rc-shell/src`, newest
  mtime of a file under `rc-shell/src`). Exit 0 PASS; 1 INCOMPLETE (NO_SHELL, PROFILE_UNNAMED -
  `RC_LAUNCHER_PROFILE` can name it, read `ops/runtime/launcher_status.json` - or UNKNOWN); 2 FAIL
  (MULTIPLE_MAIN, PACKAGED, WRONG_CHECKOUT, STALE). EVIDENCE: the verdict line, MAIN pid, creation
  time and source bound, with the timestamp, recorded beside the overlay row it gates.
  SUBSTITUTION CHECK: PASS proves only that MAIN runs the current code; it is not evidence that any
  overlay surface rendered, and it never ticks G6-02, G6-04 or an `[OVERLAY-*]` row. BASELINE (idle,
  this cycle): :8888 and :2999 did not answer, no `electron.exe` process, `health.json` `started_at`
  2026-11-01T01:33Z (stale); the tool printed NO_SHELL, exit 1, source bound 2026-11-05T06:13:30Z
  (newest commit `bdb583474`, 2026-11-05T06:12:31Z; newest mtime `rc-shell/src/overlay_toggle_page.js`),
  so the next app start meets the time half.
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
  **AGE RE-CHECK (lane 9 PREP s144 cycle 121, 2026-11-09, S144-G-108; NOT a tick, NOT a re-open).**
  Status: the DRAIN SESSION 2026-07-20 record at the top of this file PASSED this row; the PARTIAL tag
  above is the older 2026-07-18 state. This block only refreshes the cites and the residual predicate
  for any future re-confirmation. (1) Every `rc-shell/src/main.js` cite above has drifted (file now
  2809 lines; RM-1272 commits `9198ca1d8` / `bdb583474` touched it 2026-11-04/05). Current homes:
  `doToggleActive` at `:1871-1875` (flips `overlayClickThrough`, calls `applyClickThrough()`, then
  `scheduleActiveRevert()`); the "Ctrl+Shift+A NOT registered in Electron" comment at `:1961-1965`
  inside `registerHotkeys`; the Alt+Shift+A fallback registration at `:1991-1995`
  (`ov.OVERLAY_DEFAULTS.hotkeyActiveAlt`, `rc-shell/src/overlay_state.js:45`); the Win32 signal
  watcher `startActiveToggleWatch` at `:1924-1926` (`watchSignal("activeToggle", doToggleActive)` at
  `:1925`). `ovscale` is no longer computed at `main.js:569-573`: `ov.resolveOverlayMetrics`
  (`overlay_state.js:425`, called at `main.js:767` / `:897`) yields the scale and `ov.overlayUrl`
  (`overlay_state.js:203-216`) bakes it in at `main.js:835`. Listener side: the "overlay ACTIVE toggle
  signaled" log line is `tools/hotkey_listener.py:216`, `_SLOT_OVERLAY_TOGGLE = 3` at `:339`, and the
  sole non-test caller of `signal_overlay_active_toggle` is `_dispatch_one` at `:482` (was `:359`;
  `git grep` outside `tests/` finds no other). Still no re-rank: nothing in `doToggleActive` reaches
  ranking code. (2) PREDICATE DEFECT, the 20s is a SETTING now: `scheduleActiveRevert`
  (`main.js:1228-1245`) times out after `overlaySettings.activeRevertSec * 1000`, read by
  `overlaySettingsFrom` (`overlay_state.js:692-700`) from `overlay.settings.activeRevertSec` in
  `<appData>/Amberstone Shell/rc-shell-state.json`, clamped to [3, 120] (`:548-556`), default 20
  (`:51`, `:521`) when absent or not a finite number. A future re-confirm that waits a fixed 20s
  false-FAILS the moment the operator moves that setting. Baseline read this cycle (idle, read-only):
  the field is present and reads 20 (file mtime 2026-10-31T21:17 local). (3) Behavior added since
  the PASS: `applyClickThrough` (`main.js:1200-1220`) now also calls
  `overlayWindow.setFocusable(ov.effectiveFocusable(overlayClickThrough))` (S134 N9), so ACTIVE makes
  the overlay window focusable, and the glow is `ind.activeIndicatorSetJS(!overlayClickThrough)`.
  RE-CONFIRM PROBE (stated before any game): before the press, read `activeRevertSec` = N from the
  state file above (absent -> 20). With League FOREGROUND, ONE Ctrl+Shift+A. PREDICATE: PASS iff
  (a) a new "overlay ACTIVE toggle signaled" line lands in `logs/hotkey_listener.log*` (rotating;
  path at `tools/hotkey_listener.py:118`) within 1s of the press, (b) the edge glow appears and a widget body drags, and (c) the glow clears N s (+/- 2 s)
  later with no further press; and League still takes keys after the revert. FAIL on any miss.
  EVIDENCE: the log line and its timestamp, N with its source, the observed revert interval, game
  mode and game_time. SUBSTITUTION CHECK: the log line alone proves DELIVERY to the listener only
  (already settled above); it is not evidence the overlay flipped. The glow plus a drag, seen on
  screen, is the only flip evidence; a G6-01 PASS is a precondition, never a stand-in.
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
  **AGE RE-CHECK 2026-11-10 (lane 9 s144 cycle 151, S144-G-142, source read at `db40bed65`; no game
  up; NOT a tick).** CV rows accrued, the re-run step has no tool, and one game moves
  neither. (1) ACCRUED, THEN STOPPED (the row sets no row-count target): a read-only parse of the main checkout's
  `data/hz_choice_shadow.jsonl` gives 58,806 rows (2 unparseable), 12,417 with a dict
  `cv_override` (`enemy_dead` 11,419, `low_hp` 998; by `mode`: sr 7,963, aram 4,028, arena 306,
  client 120), first CV row 2026-06-21, LAST ROW OF ANY KIND 2026-08-02T22:34:15Z. The sibling
  in-game shadows `data/det_coach_shadow.jsonl` and `data/hz_build_shadow.jsonl` end at the same
  second (22:34:15.3988 / .4038), which points (inferred, not observed) to a common upstream stop
  (no in-game tick reaching `dashboard/_state_builder.py:1004`) rather than a defect in the
  `core/hz_choice_shadow.py` writer; it
  matches the G7-06 rail stall since 08-02. (2) THE NAMED RE-RUN DOES NOT EXIST: `tools/hz_shadow_report.py`
  contains the string `cv` zero times (case-insensitive), and no file under `tools/` reads
  `cv_override`; its only reader is the post-game renderer `core/branch_review.py:238`. "Re-run
  hz_shadow_report WITH the CV layer" therefore needs a CV-aware read-only reader built first, over
  rows already on disk. (3) The flip flag is unchanged: `RC_LANING_CV_SERVED` defaults OFF at
  `dashboard/_deterministic_coaching.py:445`. RESIDUAL: a new acceptance number from the operator or
  MAIN (ADR-013 retired the 70% one), then the CV-aware reader, both offline. Filed as a
  "Not actually live-gated" CANDIDATE only; moving the row is a human doc edit.
- **G7-06** (was G6) DS calibration pipeline: needs **~20+ RANKED SR (queue 420)** games. Customs and
  Mayhem cannot feed it. SOURCE: RM-32.
  **AGE RE-CHECK 2026-11-10 (lane 9 s144 cycle 148, S144-G-138, source read at `4704d777b`; no game
  up; NOT a tick).** The game-count threshold is already met; what the rail lacks is statistical
  power and two stalled feeds, none of which one game moves. (1) THRESHOLD MET: the pipeline is BUILT
  (RM-32, `core/ds_calibration_agreement.py` + `tools/ds_calibration_report.py`, `MIN_BUCKET_N = 20`
  at `core/ds_calibration_agreement.py:78`). Calling `compute_ds_calibration_agreement_from_db`
  in memory (no `--out` write) over the main checkout's `data/ds_calibration.jsonl` and
  `data/rewind_history.db` (opened `mode=ro`) gives `ticks` 10469, `games_in_log` 110 (SR 104, ARENA
  6), `games_joined` 50, of which **25 are queue 420** (14 of them wins), 17 queue 400, 2 SR with a
  null queue, 6 Arena. So "~20+ ranked SR" is satisfied. (2) NOT A VERDICT: cells `SR/dps` n=299
  follow 0.2341 `winrate_delta_shrunk` +0.0677, `SR/unknown` n=96 -0.0926, `ARENA/dps` n=26 -0.0185;
  3 cells dropped below min_n. These are the same SR/dps numbers RM-32 recorded on 2026-07-25 as
  inseparable from noise on one account, so the binding constraint is effect size versus corpus,
  not a game count. (3) PRODUCER SILENT SINCE 2026-08-02: the log's newest `ts` is 2026-08-02
  17:32 local (file mtime the same day); the producer is `core/ds_calibration.py:63 log_ds_run`,
  called from the SR / ARAM / Arena / Brawl coach ticks, so it only grows while a coach tick runs
  in a game. (4) OUTCOME FEED STALLED: the newest `matches.game_creation_ts` in
  `rewind_history.db` is 2026-07-20 and the newest queue 420 game is 2026-06-30; 60 SR games in
  the log (38 June, 21 July, 1 August) do not join. Cause of each miss NOT measured (a practice or
  custom game never reaches Match-V5; an un-run ingest also misses). The automatic per-game writer
  is `lib/rewind_live_writer.py` (`schedule_live_insert`, called at a non-TFT game end from frozen
  `app/_game_lifecycle.py:222-223`, writing through `scripts/rewind_catchup.write_match`); the
  batch writers are `scripts/rewind_catchup.py` and `scripts/rewind_scraper.py` (`INSERT OR IGNORE
  INTO matches`). `agents/agent2_backend/game_ingest.py` writes `data/db/`, not this db. Why the
  live writer added no match after 2026-07-20 (including the 2026-08-02 SR game) was NOT measured;
  a new ranked game joins only once one of these writers lands it. VERDICT:
  the row's stated gate is MET and stale. A residual exists but it is an accrual-plus-ingest rail,
  not a drain row: re-run the report after the ingest has caught up, and decide on the delta's
  confidence, never on a game count. Filed as S144-G-139 (re-word this row's gate to the delta
  bound; measure why `rewind_live_writer` landed no match after 2026-07-20).
- **G7-07** (was G7) `post_game_score` LR retrain at N>=20 real timelines (`core/post_game_score.py:220`).
  **AGE RE-CHECK 2026-11-10 (lane 9 s144 cycle 147, S144-G-136, source read at `cf4681e61`; no game
  up; NOT a tick).** The accrual threshold was met before the row was filed, so this is not a rail
  waiting on games. (1) N IS MET MANY TIMES OVER: read-only (`mode=ro&immutable=1`) over the main
  checkout's `data/rewind_history.db`, with the exact predicate `build_training_samples` uses
  (`has_timeline=1 AND map_id IN (11, 12)`, a team 100 or team 0 label row), gives **2797** labelled
  timelines: **716** on map 11 (SR; queue 420 alone holds 516) and **2081** on map 12 (Howling Abyss:
  2073 queue 450, 7 queue 720, 1 queue 0). Newest `fetched_at` is 2026-07-21; 2712 of them were
  fetched before 2026-05-20. (2) A TRAINED MODEL ALREADY SHIPS: `data/post_game_wpa_model.json`
  (tracked, added in `515248bad` 2026-05-20,
  byte-identical in the main checkout) holds `n_samples` 800 and 13 weights; that commit says "trained
  on 200 SR matches (800 samples)", i.e. 4 frames per match. `dashboard/routes_post_game_wpa.py`
  loads it and labels its answer `"model": "trained"`; the hand-coded `_fallback_prob` that carries
  the TODO runs only when the file is missing or malformed. (3) CITE HOLDS LOOSELY: `:220` is the
  "Fallback estimator" section banner; the TODO itself sits in the `_fallback_prob` docstring at
  `core/post_game_score.py:232`. (4) A NAIVE RETRAIN IS NOT THE SHIPPED ONE: `train_from_db()` calls
  `build_training_samples` without `match_ids`, so it takes every labelled timeline the query returns
  (no LIMIT) and would fit about 2797 matches of which 74 percent are map 12 (map 12 has no dragon,
  baron, herald or grub features), while the shipped model was fit on an SR-only subset of 200. The
  map scope of a retrain is a design decision, not
  something a game answers. VERDICT: NOT ACTUALLY LIVE-GATED - a `Not actually live-gated` candidate
  for a HUMAN to move. The retrain is headless (`train_from_db` reads the DB and writes the model
  file) and is filed as S144-G-137 with its map-scope decision; no game state moves this row.
- **G7-08** (was G8) hz_mismatch ground-truth cross-ref - **DENSITY MEASURED 2026-07-18; this is NOT a
  drain-session row.** SETTLED HEADLESS over `rewind_history.db`: **2,139 distinct
  (lane, champ, champ) matchups, of which only 62 (2.9%) reach n>=5 and just 4 reach n>=10. Median
  n=1.** That is exactly why most calibration classes read insufficient_data, and no realistic number
  of played games fixes it - the fix is ARCHETYPE POOLING, i.e. headless code, not accrual.
  RESIDUAL (accrual, background only): density rises slowly with every ranked q420 game. Re-read the
  three counts above before anyone proposes a per-matchup calibration again.
  **AGE RE-CHECK 2026-11-10 (lane 9 s144 cycle 149, S144-G-140, source read at `6051a971a`; no game
  up; NOT a tick).** The three counts reproduce; the corpus has barely moved and the cross-ref is
  still almost all insufficient_data. (1) DENSITY RE-DERIVED over the main checkout's
  `data/rewind_history.db` opened `mode=ro`: the DB holds 2966 matches (2961 on 2026-07-18), 667 of
  them `game_mode` CLASSIC, all with `has_timeline` 1 (516 queue 420, 141 queue 400). Keying each
  lane that has exactly one champion per side as (lane, sorted champion pair), the same selector
  `tools/replay_matchup_validate.py:177` `select_sr_match_ids` uses: **2,144 distinct matchups,
  63 (2.9%) at n>=5, 4 at n>=10, median n=1, max n=12** (filed: 2,139 / 62 / 4 / 1). Ranked q420
  alone: 1,702 distinct, 46 at n>=5, 1 at n>=10. Counting each pairing in both directions doubles
  every figure and leaves the 2.9% unchanged, so the key orientation does not move the finding. The
  newest CLASSIC `game_creation_ts` is 2026-07-21 03:27 UTC (2026-07-20 local), the same ingest
  stall G7-06 records: no game since has reached this DB, so "density rises with every ranked
  game" has not been true for nearly four months. (2) CROSS-REF RE-RUN in memory, no md write:
  `tools/hz_mismatch_diagnose.py:442` `rewind_cross_ref` over `data/hz_choice_shadow.jsonl`
  (58,806 records, newest `ts` 2026-08-02 22:34 UTC) with a `mode=ro` connection passed through its
  `conn=` test seam (the tool's own path at `:478` opens the DB without `mode=ro`). It scans the 667
  SR matches with `_REWIND_MIN_SAMPLES = 3` (`:99`) and excludes 4,057 ARAM and 3 client mismatch
  records. Of 13 mismatch classes, **11 read insufficient_data** and 2 read disagree on thin
  support: `hold->trade` covers 1 of 6 class matchups over 4 lane games, `trade->hold` 2 of 10 over
  5. The SR mismatch side holds only 24 (class, my, enemy) matchup entries summed over classes;
  coverage is the binding constraint on the mismatch side too, not just the rewind side. (3)
  POOLING STILL NOT BUILT: neither `tools/hz_mismatch_diagnose.py` nor
  `tools/replay_matchup_validate.py` contains any pooling step (grep `pool`: no hit), so the fix the
  row names is still open headless code. VERDICT: row stands as written (settled headless,
  background accrual only); the residual's accrual premise is stalled with the rewind ingest
  (S144-G-139 (b) owns that cause). No game state moves this row.
- **G7-09** (was G9) Draft-Elo pairwise WR corpus densification - **DENSITY MEASURED 2026-07-18; this
  is NOT a drain-session row.** SETTLED HEADLESS: **8,188 distinct cross-team champion pairs observed,
  covering 55.0% of the C(173,2) = 14,878 possible pairs, but EXACTLY ONE pair reaches n>=20.** Median
  n=1. Per-pair win rate is therefore not reachable by playing; it needs archetype pooling (same
  finding as G7-08), and it is the same reason G7-19 stays PARKED.
  RESIDUAL (accrual, background only): the corpus tightens as matchmade games accumulate. Re-read the
  n>=20 count before proposing any pairwise-WR consumer.
  **AGE RE-CHECK 2026-11-10 (lane 9 s144 cycle 150, S144-G-141, source read at `639800106`; no game
  up; NOT a tick).** The finding reproduces almost to the pair. (1) DENSITY RE-DERIVED over the main
  checkout's `data/rewind_history.db` opened `mode=ro`, counting each unordered cross-team champion
  pair once per match, the same join `core/draft_elo_db.py:237` `pair_winrate` runs with
  `side="enemy"`: over the 667 `game_mode` CLASSIC matches, **8,201 distinct pairs, 55.1% of
  C(173,2) = 14,878, 41 at n>=10, EXACTLY ONE at n>=20 (max n=24), median n=1** (filed: 8,188 /
  55.0% / one / median 1). Over the route's own `DEFAULT_SR_QUEUES` (400 / 420 / 430 / 440 / 490,
  662 matches): 8,167 (54.9%), one at n>=20. Ranked q420 alone (516): 6,974 (46.9%), one at n>=20.
  The champion universe is unchanged: DDragon 16.22.1 `champion.json` carries 173, and all 173 occur
  in the corpus. SAME-TEAM (ally) pairs, the side `core/draft_score.py:197` reads, are thinner:
  7,043 distinct over CLASSIC, one at n>=20 (max 22); q420 alone has ZERO at n>=20. The newest SR
  `game_creation_ts` is 2026-07-21 UTC, the same ingest stall G7-06 / G7-08 record, so the
  RESIDUAL's "the corpus tightens as matchmade games accumulate" has not been true since then.
  (2) THE CONSUMER CAVEAT IS ALREADY OVERTAKEN: three dashboard routes read these per-pair rates today -
  `dashboard/routes_draft_elo.py` and `dashboard/routes_ban_suggest.py` (both added 2026-05-20, before
  this row) and `dashboard/routes_draft_score.py` (added 2026-07-23, five days after it). Per pair
  the DB side is Laplace alpha=1 only (`core/draft_elo_db.py:203` `_rate`, `:208`; no per-pair
  minimum n in any of the three), so a 1-game pair reads 0.667 or 0.333 (draft_score may blend a
  101qq duo rate at `_DUO_BLEND = 0.30`, `:78`, where that source covers the pair); `core/draft_score.py` sums `g` over the 10 ally pairs (`:204`) and lets the
  synergy layer contribute once that SUM reaches `MIN_GAMES = 5` (`:66`, `:115`), so five 1-game
  pairs clear the gate. Whether that is acceptable is a headless design question for the draft
  owners, NOT a gated one; recorded here so the next reader does not re-read "before proposing any
  consumer" as "no consumer exists". VERDICT: row stands (settled headless, background accrual only);
  no game state moves it.
- **G7-10** (was G10) B1 `det_coach_shadow` / WS3 `objective_playbook_shadow` / WS4
  `macro_response_shadow` flip gates (rows accruing ~37.6K / 33.6K / 32.7K on 2026-07-01; the flip
  DECISIONS are pending). SOURCE: commits `ee70536a` / `2cdf64cb` / `aec17657`.
  **AGE RE-CHECK 2026-11-10 (lane 9 s144 cycle 152, S144-G-143, source read at `ecef3bcbc`; no game
  up; NOT a tick).** The filed counts are stale, accrual stopped on 08-02, and all three gates
  still fail to support a flip - the macro one on a headline a constant beats. (1) COUNTS: the
  three report tools re-run read-only over the main checkout's `data/` (`--path`; sha256 of all
  three files identical before and after): `det_coach_shadow` total 60,721 rows (18,689
  both-present), `objective_playbook_shadow` 46,474 (27,345 both-present; 2,482 test-leak rows
  excluded, RM-872), `macro_response_shadow` 45,578 (15,171 both-present; 2,480 excluded), against
  the filed ~37.6K / 33.6K / 32.7K of 2026-07-01. Last row 2026-08-02T22:34:15Z (det) and
  22:29:50Z (objective, macro); the 2026-10-25 mtime on the two WS files is the RM-872 archive
  split (LEDGER 1835), not accrual. Same stop as G7-05 / G7-06. (2) VERDICTS: det_coach HOLD
  (domain alignment 294/18,689 = 0.0157; within-trade 5/256 = 0.0195); objective_playbook HOLD
  (11,072/27,345 = 0.4049 < 0.70); macro_response REVIEW (11,075/15,171 = 0.73 >= 0.70,
  `tools/macro_response_shadow_report.py:380`). (3) THE MACRO REVIEW IS DEGENERATE, NOT AGREEMENT:
  Haiku's register is ACTIVE on 14,097 of the 15,171 both-present rows, so a constant "ACTIVE"
  predictor scores 0.9292, 20 points above the det coach; the det register is constant per
  `lead_state` on these rows (ahead 9,284 / even 2,391 all ACTIVE, behind 3,496 all PASSIVE; the
  tool's own docstring `:27-28`), and the BEHIND bucket aligns 225/3,496 = 0.0644. The same
  baseline beats the det side on objective (constant "dragon" 11,306/27,345 = 0.4135 vs 0.4049;
  det names dragon on 24,478 rows, 0.895), and det_coach's det domain is one value (trade
  x18,689). None of the three `_flip_hint`s (`tools/det_coach_shadow_report.py:514`,
  `tools/objective_playbook_shadow_report.py:334`, `tools/macro_response_shadow_report.py:359`)
  compares against a native majority-class baseline (grep `baseline|majority` over the three hits
  classifier prose only). Filed as S144-G-144 (report-tool change, outside this lane's write set):
  a gate clears only on alignment ABOVE the native majority share. (4) PREP for the next SR game,
  stated before it: probe = the three commands with `--path <main>/data/<file>.jsonl --json`;
  ACCRUAL PASS iff each file's last `ts` is after the game start and `total` grew; a flip is
  operator-gated and never read off one game. SUBSTITUTION: the rates are COMPUTE over logged rows;
  they show both coaches were fed, not that a deterministic line RENDERED. One game moves no
  verdict (15K-27K comparable rows already), so the residual is an offline decision plus the
  S144-G-144 tool fix, not a game wait: filed as a "Not actually live-gated" CANDIDATE only;
  moving the row is a human doc edit.
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
  **RE-FILED 2026-10-25 (RM-868, s133; fix `d47e9906b` + `4d07738aa`): ROOT-CAUSED - the 0.7% was
  PLUMBING, not a coach defect.** (1) `ArenaVisionReader` rode the promptless relay (fixed TFT schema,
  no `camp_phase`), so the artifact's `camp_phase` was always False and the det camp rule never fired
  (det BUY ITEMS 1 of 480 live-fight rows); it now sets `USE_RELAY = False` (the RM-144 pattern). (2)
  the report compared free-text Haiku labels to the det 5-label set as exact strings and read
  `sample_met` / ready at 1%; it now scores a shared class map (SHOP / DEFENSIVE / NEUTRAL / AGGRESSIVE /
  NONCOMBAT) behind a 0.70 FLIP_GATE (states awaiting_accrual / not_ready / ready), and routes a tick
  dead only on an unambiguous player-dead / spectating statement. (3) rows from the placeholder
  artifact (round 0, hp 100 -> a fake PLAY AGGRO) are no longer written. Re-run over the existing 617
  rows (ALL PRE-FIX; sha256 unchanged by the run): class agreement **10/426 = 0.0235**, exact 3/426,
  146 dead-state, `not_ready`; most disagreements are Haiku SHOP vs a det fight posture, the
  dead-camp-signal signature; fight axis 9/32 same band, 30/32 within one band.
  LIVE VERIFICATION (G7-17 now waits on this, needs one real Arena game AFTER an RC restart that loads
  `d47e9906b`; note the restart time): (a) at a camp, `data/arena_coaching_data.json` reads
  `camp_phase: true` at least once (vision now goes direct to Sonnet, about 3 reads/min at
  `_VISION_INTERVAL` 20 s); (b) the new `data/arena_coach_shadow.jsonl` rows carry det `BUY ITEMS` > 0
  and no blank-Haiku / round-0 row; (c) `python tools/arena_shadow_report.py --since <restart ISO
  time>` - the POST-FIX cohort only, never mixed with the 617 pre-fix rows - and record the class
  agreement + state honestly, whatever it is; (d) on the first item anvil, run the GATE 5 DRAIN CARD
  G5-01 predicate (a row with `ts` after the game start naming the on-screen anvil cards; file
  existence proves nothing - RM-867). The flip stays operator-gated even at `ready`. Known residual
  outside RM-868: det has no partner-dead / opponent-HP input (21 FIGHT SMART vs Haiku-defensive rows
  at HP 25-70; one partner-dead row).
  **READY (lane 9, s144 cycle 7, PREP only, no game up; NOT ticked).** One read-only command reads
  (a)-(d) after the game: `python tools/gated_g717_arena_readback.py [--since <ISO>] [--samples N
  --interval S] [--json]` (reads the main checkout's `data/`; prints no path and no game id). The
  default cutoff is `ops/runtime/health.json` `started_at`; if RC restarted AFTER the game, pass
  `--since <game start>` instead, or the cohort is empty. **TRAP FIXED IN THE TOOL, NOT IN THE
  REPORT:** step (c)'s `arena_shadow_report.py --since` compares `ts >= since` as STRINGS
  (`_since_filter`), and the writer stamps UTC `+00:00`, so a local-offset cutoff such as
  `11:00-05:00` admits every row stamped 11:00-16:00Z (5 h of pre-restart rows; pinned in
  `tests/test_gated_g717_arena_readback.py`). Give the report a UTC cutoff only; this tool converts
  any offset to UTC first.
  Predicates, stated before any game (`checks.<name>.status`): `restart` PASS iff the cutoff is at
  or after 2026-10-25T06:28:48Z (committer time of `4d07738aa`, the later fix commit); `camp` PASS iff
  a coaching-file snapshot stamped after the cutoff reads `mode` arena with `camp_phase` true, or a
  cohort row carries det `BUY ITEMS` (`core/arena_action_rule.py` rule 1: only a truthy camp_phase
  yields it); `cohort` FAIL iff a post-cutoff row is a placeholder (no Haiku action AND round in
  0 / "" / None - the shipped `_arena_artifact_is_blank` predicate, so the row's "no blank-Haiku /
  round-0 row" is read as THAT: a blank Haiku on a real round still logs by design and is counted,
  not failed), PASS iff samples > 0 and det `BUY ITEMS` > 0; `report` RECORDED iff >= 1 live-fight
  comparable round (agreement and state printed verbatim, whatever they are); `anvil` CANDIDATE iff a
  post-cutoff arena row exists - it is never passed by the tool, its `offered` must be matched by eye
  to the cards on screen (G5-01 predicate). Exit 0 all met, 1 INCOMPLETE, 2 FAIL.
  Evidence contract: value = the BUY ITEMS count, placeholder count, `agree/comparable` + state, and
  the anvil `offered` list; source = `data/arena_coach_shadow.jsonl` / `data/anvil_shadow.jsonl`
  rows (`ts`, `round`) and `data/arena_coaching_data.json` `camp_phase` + mtime; timestamp = the
  cutoff and the row `ts` range, with mode Arena q1750; predicate = this paragraph.
  SUBSTITUTION check (answer it in the tick line): the report's class agreement is COMPUTE over what
  was logged; it shows the det and Haiku coaches were both fed, not that either verdict RENDERED.
  (a) and (b) are wiring evidence (vision -> artifact -> det rule), so they count; a unit test, a
  replayed jsonl or a fixture row never does, and the anvil row counts only once matched on screen.
  Idle baseline (2026-10-27 16:17Z, no game, lane/gated): restart PASS (RC `started_at`
  2026-10-27T12:47:45Z); `arena_coach_shadow.jsonl` 617 rows, all pre-fix (last `ts`
  2026-07-21T03:17Z; 36 int-0 rounds; det `BUY ITEMS` 1, `PLAY AGGRO` 282, `KITE BACK` 195,
  `FIGHT SMART` 139; 42 blank-Haiku rows), cohort 0, report `awaiting_accrual` (617 left out);
  `data/anvil_shadow.jsonl` is now ABSENT (the 30 leaked rows in the GATE 5 DRAIN CARD baseline are
  gone), so any anvil row after the cutoff is the first real one; exit 1.
  **RE-CHECK (lane 9 PREP s144 cycle 100, 2026-11-07, source read at `7f361a92e`; NOT a tick).**
  Cites HOLD, no drift: `_since_filter` `tools/arena_shadow_report.py:535` (still a plain string
  compare, `r["ts"] >= since`), `FLIP_GATE = 0.70` `:97`; `_arena_artifact_is_blank`
  `dashboard/_deterministic_coaching.py:1474`; rule 1 `core/arena_action_rule.py:109-110` (`camp_phase
  is True` -> `BUY ITEMS`); `USE_RELAY = False` `coaches/arena_coach.py:1202`; `_VISION_INTERVAL =
  20.0` `:441`; `4d07738aa` committer time 2026-10-25T01:28:48-05:00 = the tool's 06:28:48Z.
  Idle re-run (2026-11-07 09:11Z, no game, `:8888` and `:2999` both curl 000): exit 1 INCOMPLETE;
  restart PASS (cutoff 2026-11-01T01:33:09Z); camp NOT_SEEN (the one snapshot is mtime
  2026-07-21T03:17:31Z, `mode` arena, `camp_phase` false - before the cutoff, so not counted); cohort
  0 rows; report `awaiting_accrual`, 617 left out; anvil NO_ROW.
  **NEW TRAP - the `restart` PASS can read a DEAD RC.** `ops/runtime/health.json` still says `alive`
  true, `pid` 18724, `started_at` 2026-11-01T01:33:09Z (file mtime 2026-11-01T02:17:20Z), but that
  pid is not running and `ops/runtime/launcher_status.json` reads top `state` `halted` (every service
  `halted`, `updated` 2026-11-01T02:17:21Z; `_top_state` `ops/launcher/service_host.py:1718`). A
  stopped RC never rewrites `started_at`, so the tool's default cutoff is the LAST run's start, not a
  live one. It cannot give a false PASS on the evidence checks (an RC that is down logs no rows, so
  the cohort stays 0 and the verdict INCOMPLETE), but `restart` PASS alone is NOT proof RC loaded the
  fix for THIS game. Precondition, stated before any game: `launcher_status.json` top `state` reads
  `running` (`:1730-1731`) and `curl -sk https://127.0.0.1:8888/api/state` answers 200 BEFORE the
  game starts; else start RC first and use the new `started_at`, and record both times in the tick.
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

## EXTERNAL-LIFT INTAKE live halves (filed 2026-10-04; counted HERE, not in the OPEN figure above)

Prep halves shipped synthetically; each row below is the half that only a real game can close
(Settled: the live-gated set is not synthetically drainable; a replayed session never closes one).
Ids `LX-nn` map to the RM rows in `BACKLOG.md` "External-lift intake".

- **LX-01** (RM-609, draft log) In a real ranked / draft champ select with the LCU agent running:
  rows land in `rewind_history.db` table `draft_log`; record whether the session's gameId is set at
  FINALIZATION or the gameflow fallback fired; whether trades / bench swaps during FINALIZATION show
  in `final_champion_id`; the Match-V5 row for that game joins on game_id and `attach_draft_log`
  names the right lane opponent; an ARAM / Arena session with no pick actions writes no rows and
  reads `draft_source='none'`; the agent's writes coexist with the post-game ingest without lock
  errors.
  **READY (s144 lane gated c31, 2026-10-28; PREP only, nothing ticked).** PRECONDITIONS measured
  2026-10-28 at idle (read-only `mode=ro` opens of the main checkout's `data/rewind_history.db`):
  (1) the DB holds NO `draft_log` table. `ensure_table` runs only inside `store_draft`, so the
  sink has never written one draft since RM-609 landed (2026-10-04); the first drain's rows are the
  table's first rows. (2) The newest `matches` row is from 2026-07-20 (`game_creation_ts`); the last
  90 days of stored games are queues 420 / 400 / 1700 / 1750. The JOIN half therefore also waits on
  the post-game ingest (`app/_game_lifecycle.py` -> `lib/rewind_live_writer.schedule_live_insert`, a
  Match-V5 fetch about 90 s after the game ends, `rewind_live_writer:` lines in that day's
  `logs/YYYY-MM-DD.log`) landing that game's row; until it does, the grader reads `NO_MATCH_ROW`.
  (3) The running LCU agent (`pythonw`, its `lcu agent ->` start line at 2026-10-26 20:45:21 in
  `logs/lcu_agent.log`) imported `lcu/draft_log.py` BEFORE RM-1033 (`5b880630a`, 2026-10-28 01:03:
  Reconnect keeps the pending draft, a refused write is retried at most 5 times). Restarting
  RC-LCUAgent before the game is a main-session / operator act, never a lane's. Either way the
  evidence names the agent start time against `5b880630a`, so the graded code is known.
  STALE since the 2026-10-31 launcher cutover (s144 gated c108, S144-G-96; re-measured 2026-11-08
  at idle, read-only). (i) Read-only `schtasks /Query /TN RC-LCUAgent` answers "cannot find the
  file": no task starts the agent and none can be restarted. The rc-shell service host spawns it
  (`ops/launcher/services.json` `lcu_agent`, argv `tools/lcu_agent.py`, profiles packaged + dev,
  restart `always`) at every app launch, and stops it when the app quits. (ii) `5b880630a` is a
  pre-rewrite twin: the filter-repo commit-map gives `ab584e986` (same subject and committer
  time), which is itself on main's first-parent chain (2026-10-28 01:03:05 -05:00). (iii) Every
  agent start after that already imported RM-1033: the `lcu agent ->` start lines read 2026-10-30
  09:53:49, 2026-10-31 13:32:17, 16:49:15 and 19:13:04, the last one matching
  `ops/runtime/launcher_status.json` `services.lcu_agent.started` 2026-11-01T00:13:04Z. The
  launcher has been `halted` since 2026-11-01T02:17:21Z (`reason` stdin_stop, `lcu_agent.pid`
  null), so no agent runs now and the next launch starts a fresh one on the checkout's HEAD.
  (iv) The commits since `ab584e986` on `lcu/draft_log.py` and `lcu/snapshot_shape.py` are
  behaviour-preserving: cite-by-symbol comments (`c58458946`, `6d2d1a0d4`), `gid if gid > 0 else
  0` -> `max(0, gid)` (`1bbe6a9b4`), `sorted(list(x))` -> `sorted(x)` (`d2019d48f`), unread
  `err` -> `_err` (`275e43c73`), two if/else assignments -> conditional expressions
  (`9153cea44`). (v) (1) and (2) still hold (`mode=ro`): no `draft_log` table (7 tables), the
  newest `matches.game_creation_ts` is 2026-07-20 local (07-21 UTC). The (4) and (5) cites
  hold by symbol: `attach_draft_log` has no production caller (only the grader and tests),
  `note_game_id` is called from `lcu/snapshot_shape.py`, `INTERVAL = 1.0` in
  `tools/lcu_agent.py`. REPLACEMENT RULE: before the pop, read `launcher_status.json` (`state`
  running; in the `services` LIST, the entry named `lcu_agent` has `state` running, a `pid`,
  and `started` after `ab584e986`'s time), then tie that pid to the agent itself: the live
  process's CommandLine contains `tools` + a separator + `lcu_agent.py` (it may be quoted),
  matched separator-agnostic (the service host passes `<root>\tools\lcu_agent.py` with backslashes,
  `_resolve_argv`), AND its CreationDate is within 5 s of `started` with BOTH in UTC
  (CreationDate comes back in local time, `started` is UTC `+00:00` cut to whole seconds). Read
  it with read-only `Get-CimInstance Win32_Process -Filter "ProcessId=<pid>"`; `started` is
  stamped right after the spawn and job adopt (`ops/launcher/service_host.py` `started_wall`).
  The file can still say running after a host crash, and Windows can hand the pid to an
  unrelated process (the G7-17 stale-file trap); with no agent every count reads 0, so without
  this tie the COEXIST half could PASS on nothing. Record `started` in the evidence beside the
  main checkout's `git rev-parse --short HEAD` and `git log -1 --format=%h -- lcu/draft_log.py
  lcu/snapshot_shape.py tools/lcu_agent.py`; a HEAD commit newer than `started` means the
  agent may run older code, so name both. The launcher not running, a dead pid, or a pid whose
  CommandLine or CreationDate does not match = NOT-YET (no agent, no rows), never a PASS and
  never a FAIL.
  (4) `attach_draft_log` has NO production caller (only `tests/test_draft_log_*.py`). Nothing
  renders a draft, so LX-01 asks whether the rows are WRITTEN and JOIN right, never whether
  anything renders. The grader calls the real `attach_draft_log` on a read-only connection.
  (5) The row carries no "which path wrote me" field: time is the only witness. The recorder writes at the
  first finalized tick when the session carries a gameId (still in champ select), else at the
  first GameStart / InProgress / Reconnect tick (`lcu/snapshot_shape.py` `note_game_id`). The
  agent sends `lcu.phase` / `lcu.ts` every 1 s (`tools/lcu_agent.py` `INTERVAL`); they reach
  `/api/state` through the :8889 `/latest-lcu` relay (`dashboard/_liveclient.py`). `/api/state`
  exposes no champ-select gameId. (6) `lcu/draft_log.session_queue_id` has no gameflow fallback,
  while the champ-select shaper has one (`lcu/champ_select_shape.py`: the session "frequently
  omits gameData" during BAN_PICK). So a genuine draft can store `queue_id=0`; the grader then
  skips the queue comparison in the join.
  (5)/(6) RE-CHECK (s144 gated c109, S144-G-97; 2026-11-08 at idle, read-only, source read at
  `f6473123e`; NOT a tick). Every cite holds by symbol: `note_game_id` is defined in
  `lcu/draft_log.py` and its only production call is in `lcu/snapshot_shape.py`;
  `INTERVAL = 1.0` in `tools/lcu_agent.py`; `dashboard/_liveclient.py` GETs
  `http://127.0.0.1:8889/latest-lcu`; `lcu/draft_log.session_queue_id` reads only
  `gameData.queue.id` (no gameflow read); `lcu/champ_select_shape.py` still carries the
  "frequently omits gameData" comment and its `/lol-gameflow/v1/session` fallback;
  `dashboard/_state_builder.py` `_read_lcu_snapshot` gates the in-process read on
  `RC_LCU_INPROCESS == "1"`. The newest commit on these seven files is `9153cea44`
  (2026-11-06), behaviour-preserving as (iv) above says.
  STALE: "the evidence records the flag's value" named no way to read it, and since the
  2026-10-31 cutover the RC process is no longer started by a task. The flag now reaches
  `main.py` by inheritance only: rc-shell passes its own `process.env` to the service host,
  the service host applies `ops/launcher/services.json` `env` plus the profile's `env`
  (`child_environment`; neither names `RC_LCU_INPROCESS`: top-level `{}`, dev and packaged
  set only `RC_DASH_BIND`), and the supervisor's `subprocess.Popen` passes no `env=`. The
  in-process path logs nothing on success (`dashboard/_lcu_inprocess.py` logs only
  `_log_degrade`), so no log line can witness it either. Measured today: the variable is in
  NEITHER read-only `reg query "HKCU\Environment"` NOR the HKLM `Session Manager\Environment`
  key. RULE: record the flag as `unset (relay path)` only when ALL of these hold, else
  record `unknown (process env)` and treat the witness rows as possibly mixed:
  (a) the three sources lack it: services.json (top-level `env` plus the active profile's
  `env`), HKCU `Environment`, HKLM `Session Manager\Environment`, each read at the drain;
  (b) the operator launched rc-shell from its normal shortcut, not from a terminal;
  (c) every RC that ran from the launch through the drain descends from it, checked over
  the WHOLE window, not at the drain only: take the host's launch time as the
  CreationDate of `launcher_status.json` `host_pid` (read-only `Get-CimInstance
  Win32_Process -Filter "ProcessId=<host_pid>"`, CommandLine naming `service_host.py`, in
  UTC); from then through the drain `ops/runtime/logs/supervisor.log` (read with `grep -a`;
  the file holds binary bytes) holds NO `adopted existing app pid=` line; at the drain
  `ops/runtime/status.json` (rewritten every 1 s poll by `write_status`) has `updated_at`
  within 10 s of now and `process_running` true; exactly one live process has a CommandLine
  containing `main.py`; `launcher_status.json` `mode` is `owned` (NOT `attach`: an attach
  host starts nothing and only watches a supervisor started elsewhere, e.g. by
  `ops/start_ops.bat` from a terminal, `probe_existing`); and the parent chain holds: that
  `main.py` process's ParentProcessId is the `supervisor` service pid in
  `launcher_status.json`, whose own ParentProcessId is `host_pid` (read-only
  `Get-CimInstance Win32_Process`; a stub or any other parent reads `unknown`, which fails
  safe). Over the GAME window too: that `main.py` process's CreationDate is before the tape
  start, and from the tape start through the drain supervisor.log holds no `started app
  pid=` line and no `heartbeat_wrong_pid` line (`main.py` has no single-instance guard and
  the dashboard socket allows address reuse, so a terminal `main.py` can serve `/api/state`
  beside the owned one and exit before the drain; its heartbeat is what the supervisor
  logs as a wrong pid, if a poll reads it). Why the whole window: `_adopt_existing_app` takes over a
  fresh, alive `main.py` started elsewhere (env unknown), and a later spawn overwrites
  `last_restart_reason` (`start_app`), so status.json at the drain cannot show an adoption
  that served the game. `scripts/restart.bat` reaches the same place: its `taskkill /F /IM
  pythonw.exe` kills the pythonw supervisor but not the `python.exe` host, the host
  respawns the supervisor (`restart: on-failure`), and the new supervisor adopts the lone
  `main.py` the script started (or, if that one is not yet healthy, spawns a second; hence
  the one-process check). A supervisor-spawned child after an adoption inherits the
  supervisor's env, which is fine, but the adoption line already fails the window. Do not
  tie on the `health.json` pid: under a pythonw stub it can differ from `expected_pid`.
  Measured today, RC down: the newest start line is `started app ...
  reason='restart_trigger'` at 2026-11-01T01:33:09Z, then `stopping owned app` and
  `supervisor exiting (SystemExit)` at 02:17:21Z; status.json was last written then with
  `process_running` false, so (c) cannot hold until the app is launched again. Residual
  limit: the registry is read at the drain, not at launch, so a variable set before the
  launch and removed before the read is invisible; record both times (registry read,
  launcher `started`). Second residual: a short-lived second `main.py` whose `health.json`
  writes the supervisor never reads (it never writes one, or the owned app's 1 s write
  overwrites each before the 1 s poll) leaves no trace in any source above. Never record a
  value read from the probing shell's own environment: that is a fact about the probe, not
  about RC.
  PROBE (from the main checkout; queue a ranked or normal DRAFT game, SR):
  (a) BEFORE entering the queue, start the tape:
  `mkdir -p ops/runtime/lx01; python tools/gated_lx01_draft_check.py tape --out
  ops/runtime/lx01/phase_$(date +%s).jsonl`. Its first row is a read-only BASELINE of the DB
  (`draft_log` present? how many rows?). It then GETs `/api/state` and writes one row per
  `lcu.phase` CHANGE. While the phase is ChampSelect it also writes one WITNESS row per change of
  `lcu.champ_select` (timer phase, queue, cell -> locked champion over both teams; ids only, no
  name / puuid / summonerId). It writes into a NEW file (it refuses an existing one) and stops 5 s
  after a game phase, or after 3600 s.
  (b) Write down `date +%s` before the pop and again at the end screen.
  (c) After the post-game ingest's `rewind_live_writer:` line, run `python
  tools/gated_lx01_draft_check.py grade --since <pop epoch> --until <end epoch + 600>
  --phase-tape <tape> --log 'logs/lcu_agent.log*' --log 'logs/<day>.log*' --json`. Quote the
  globs: the tool expands them itself, because BOTH logs rotate by size inside a day (measured:
  `logs/2026-10-25.log.1` .. `.3`). If the window crosses midnight, add the next day's glob.
  `RC_LCU_INPROCESS=1` in the RC env lets the dashboard read LCU itself
  (`dashboard/_state_builder.py`), falling back to the agent's relay tick by tick. The tape
  cannot tell which source fed a witness row, so the evidence records the flag's value. With
  the flag on, the witness rows may mix the dashboard's own read and the agent's view. The no-pick half rides any ARAM / KIWI / Arena game afterwards, as the same `grade`
  over that game's window; no tape is needed.
  The grader is read-only: a `mode=ro` URI, and only the `lcu.draft_log` SELECT readers. Game and
  match ids print only with `--show-id` (RM-906: never paste them), and no player name is read.
  FIELD PATHS: `table_present`; `games[].actions`, `.types`, `.picks_ally`, `.picks_enemy`,
  `.swaps`, `.enemy_position_hidden`, `.unowned_actions`, `.queue_id`, `.captured_at`,
  `.problems[]`; `tape_baseline.table_present` / `.rows`; `games[].witness.witness` (`MATCH` /
  `MISMATCH` / `NONE`), `.cells_differing`, `.witness_cells`; `games[].captured_after_tape_start`;
  `games[].join.verdict` (`JOIN_OK` / `JOIN_MISMATCH` / `NO_MATCH_ROW`), `.mismatches[]`,
  `.match_queue_id`, `.tracked_position`, `.lane_opponent_champion_id`,
  `.expected_opponent_champion_id`, `.local_picked_before_opponent`; `games[].path.path`
  (`FINALIZATION` / `FALLBACK` / `LATE` / `UNKNOWN`), `.captured_minus_first_game_phase_s`,
  `.champ_select_on_tape`; `no_draft_matches[].queue_id`, `.draft_source`, `.clean_none`;
  `logs.files[].name` / `.lines_in_window` / `.counts.sink_failed` / `.observe_failed` /
  `.note_game_id_failed` / `.sink_not_installed` / `.database_locked` (totals in `logs.counts`).
  PREDICATE (stated before any game):
  - WRITE half PASSES iff ALL of these hold:
    - `table_present=true` and exactly one game is in the window;
    - `problems=[]`: action_index 0..n-1, turns non-decreasing, every pick / ban on ally or
      enemy, one `captured_at`, exactly one local pick, every pick completed with a final
      champion;
    - `picks_ally=5` and `picks_enemy=5`;
    - `queue_id` is the lobby's queue, or 0. A 0 is RECORDED, not failed: it is the (6) gap, and
      it files S144-G-21;
    - `captured_after_tape_start=true` (`store_draft` replaces a game's rows whole, so a row from
      before the tape would carry an earlier `captured_at`); on the first drain,
      `tape_baseline.table_present=false` as well;
    - `witness.witness=MATCH`;
    - `path.path` is `FINALIZATION` or `FALLBACK`.
    `LATE` never passes. A sink retry that finally lands after a refused write (with
    `sink_failed` above 0) cannot be told apart from a row written by hand after the game
    started, so it is RECORDED and the WRITE half stays OPEN for the next draft game.
    `unowned_actions` (actions with no actor cell) is RECORDED, never a fail.
  - PATH half is RECORDED: which of `FINALIZATION` / `FALLBACK` the live session took. `UNKNOWN`
    means the tape missed the game phase, so the row stays open for this half.
  - TRADE half is RECORDED: `swaps` equals the trades the operator saw in champ select (0 is a
    valid reading when nobody traded). A trade made but `swaps=0` is a FAIL.
  - JOIN half PASSES iff `join.verdict=JOIN_OK`: ally pick finals are the tracked team's
    champions, enemy pick finals the other team's, the local final is
    `matches.tracked_champion_id`, `lane_opponent` is the enemy at the tracked `team_position`,
    and a non-zero draft `queue_id` equals `matches.queue_id`. `NO_MATCH_ROW` keeps this half
    open.
  - NO-PICK half PASSES iff an ARAM / KIWI / Arena game in its own window has no draft game and
    a `no_draft_matches` entry with `clean_none=true`. A draft game in that window is RECORDED,
    not failed: those sessions DO carry pick actions, and the row's "no pick actions" premise is
    refuted.
  - COEXIST half PASSES iff:
    - every `logs.files[]` entry has every count at 0;
    - the agent-log glob matched at least one file (no `missing=true`);
    - within each day-log glob the window touches, at least one file has `lines_in_window`
      above 0.
    The agent log is quiet (about 6 KB over three days, measured 2026-10-28), so its
    `lines_in_window` is RECORDED and may read 0. Every agent-log line carries its full date, so
    any `draft_log sink failed` WARNING in the window is counted however few lines it has. A
    rotated `.N` file with 0 lines in the window is normal. A
    glob entry with `missing=true` is a FAIL for that glob. The check is per file because a zero count over zero lines proves
    nothing, and a total can hide a wrong-day log.
  EVIDENCE CONTRACT: the grader's JSON (values, not "ok"); the tape file itself (baseline,
  phase and witness rows); the two epochs; the queue and the trades the operator saw in champ
  select; the agent's `lcu agent ->` start line against `5b880630a`; the main checkout HEAD; and
  the `rewind_live_writer:` line with its time; and whether `RC_LCU_INPROCESS` was set.
  SUBSTITUTION CHECK: `tests/test_gated_lx01_draft_check.py` writes rows through the REAL
  `parse_draft` + `store_draft` from a hand-built session and reaches every verdict above, so a
  verdict proves nothing unless the rows came from the live agent's sink during the played champ
  select. Four wired checks narrow that:
  - the tape's BASELINE, taken before the pop, records the table's state before the game;
  - `captured_after_tape_start` shows the write came after;
  - `path` places it in champ select or within the slack of the first game phase;
  - the WITNESS shows the stored pick finals equal what `/api/state` showed during that champ
    select.
  A row written by hand after the first game phase plus the slack reads `LATE`, and `LATE` never
  passes the WRITE half, with or without `sink_failed`. THE RESIDUE THE GRADER CANNOT SEE is a row written
  by hand from the same session at any time between ALL picks being locked (the witness used is
  the last one taken no later than 2 s after the write, `WITNESS_LAG_S`, not the final one;
  `captured_at` is whole seconds and the relay stamp lags) and the first game phase plus the slack
  (`--path-slack`, default 10 s). Built from that witness, it reads
  `FINALIZATION` or `FALLBACK` and `MATCH`, exactly like the sink's own write. The tape itself is
  an operator-written file and is no stronger than its provenance. So no `store_draft` /
  `sqlite_sink` call by hand may run against the live DB at any point in the drain window, and
  none ever closes LX-01. The witness alone is not evidence of a WRITE: it shows
  what the agent SAW, the DB shows what it STORED, and the WRITE half needs both.
- **LX-02** (RM-601 / RM-602, Live Client hygiene) Capture one real allgamedata payload into a
  gitignored path and run `tools/liveclient_shape_audit.py` on it; confirm a real `HordeKill` event's
  fields (KillerName, Stolen type) match the synthetic fixture; record whether `KillerName` carries a
  champion name or a player name (decides RM-673).
  **READY (s144 lane gated c28, 2026-10-28; PREP only, nothing ticked).** PRECONDITIONS measured
  2026-10-28 at idle: the :8889 relay answers `/health` 200 and `/latest-liveclient` 404
  (`no_liveclient_yet`, `vision_server/_http.py` `/latest-liveclient`), and
  `ops/runtime/liveclient_captures/` does not exist yet (gitignored under `ops/runtime/`; the drain
  creates it). WHY THE ROW MATTERS NOW: RC reads `KillerName` two ways. `dashboard/_liveclient.py`
  (the `objective_events` block) classifies an objective's `killer_team` against `enemy_team` /
  `ally_team`, which hold `championName` only, so a player-name killer reads `unknown`;
  `game_reader/snapshot_normalizer.py` `_side_keys` (RM-236 drake tally) matches player names AND
  champion names. The synthetic fixture `tests/fixtures/liveclient/allgamedata_synthetic_rm601.json`
  is itself split: its ChampionKill / Multikill killers are player names, its DragonKill / HordeKill /
  TurretKilled killers are champion names. Only a real payload decides which RC reader is right. The
  same capture answers RM-674: `snapshot_normalizer.py` matches `"FirstBloodKill"`, `coaches/arena_coach.py`
  and the fixture use `"FirstBlood"`.
  PROBE (any League game with a voidgrub or dragon take: SR after the first grub camp, so past about
  6:00 game time; run from the main checkout, where the token resolves - a lane worktree answers
  401): take at least two captures at least 60 s apart, the last one after an objective falls:
  `mkdir -p ops/runtime/liveclient_captures; TOK=$(python -c 'from core.vision_token import
  get_vision_token as g; print(g())'); curl -sf -H "X-RC-Token: $TOK"
  http://127.0.0.1:8889/latest-liveclient -o ops/runtime/liveclient_captures/lx02_$(date +%s).json`
  (`-f`: a 401 / 404 error body is not saved as a capture), then `python tools/gated_lx02_payload_check.py ops/runtime/liveclient_captures/ --json` and
  `python tools/liveclient_shape_audit.py ops/runtime/liveclient_captures/` (both read-only). The
  checker never prints a name field (RM-906: every name field is reduced to a FORM against the
  payload's own `allPlayers`, and the shape audit's quoted mismatch examples are cut; event names,
  game modes and key names print verbatim, which on a real wire payload are fixed Riot strings); the raw `liveclient_shape_audit`
  output CAN quote a value, so paste only its event-name and key-path lists. FIELD PATHS:
  `events.Events[].EventName`, `.KillerName`, `.VictimName`, `.Recipient`, `.Acer`, `.Assisters[]`,
  `.Stolen`; `allPlayers[].championName` / `.riotIdGameName` / `.summonerName` / `.riotId`;
  `gameData.gameMode` / `.gameTime`; the relay wrapper `ts`.
  PREDICATE (stated before any game): VALID only if `synthetic=0`, `duplicates=0`, `payloads>=2`,
  `relay_ts_span_s>=30` and `game_time_max` is past the first objective (anything else is NO_RESULT,
  re-capture). Then, recorded as values: `rm673.verdict` PLAYER_NAME = RM-673 CONFIRMED (the
  `_liveclient.py` objective `killer_team` is `unknown` on live rows; the fix side is that reader),
  CHAMPION_NAME = EVERY objective killer is in `champion` form and equals a team-assigned roster
  `championName` EXACTLY (`rm673.champion_exact` equals the `champion` count, which equals the sum
  of `objective_killer_forms`; `_liveclient.py` tests the raw string, no case fold, no tag strip)
  AND `rm673.reader_killer_team` holds only `ally` / `enemy` (the checker's `reader_sets` /
  `reader_team` mirror that reader: "me" is the first `allPlayers` row whose raw `summonerName`
  equals `activePlayer.summonerName`, else both sets stay empty):
  RM-673 REFUTED (record it and close RM-673 as a non-defect; `_side_keys` keeps its wider match),
  CHAMPION_NAME_READER_FAILS = exact champion names, but the reader still reads `unknown` (no
  self-identification: `reader_self_identified` below `payloads`) or `ambiguous` (a mirror champion,
  blind pick / One for All, which the reader sends to `enemy` first): the name premise of RM-673 is
  refuted, the reader is NOT cleared - record both and file the reader failure, never close on it,
  CHAMPION_NAME_INEXACT = every killer in `champion` form but some match only after the checker's
  fold or belong to a roster row with no `team`, so `_liveclient.py` still reads `unknown` (RM-673
  CONFIRMED on that reader; record the count), MIXED = champion forms beside ANY other form
  (`player`, `unmapped` - possibly a player form the roster misses -, `nonplayer`, `empty`, or `both`
  - a player named like a champion): record the per-event forms and file it, never close RM-673 on
  it, NO_RESULT = no objective killer in `champion` or `player` form in the window (only `nonplayer` /
  `unmapped` / `empty` / `both`, or no objective at all: record the forms; RM-673 stays open;
  re-capture after a grub or drake take); `rm674.verdict` FIRSTBLOOD = the
  `snapshot_normalizer.py` side is the wrong one, FIRSTBLOODKILL = the `arena_coach.py` side is,
  BOTH or OTHER (a name that reads `firstblood` only once lowercased and stripped of underscores) =
  record the names and file it (both RC sides may then be wrong), NO_RESULT = no such event name in
  the window; `horde.verdict` MATCH (key set equals the fixture's `Assisters` /
  `EventID` / `EventName` / `EventTime` / `KillerName` / `Stolen`, and each key carries ONE JSON type
  equal to the fixture's own, `horde.fixture_types`, so `Stolen` a string) or DIFFERS (record the
  missing / extra keys and types; the fixture and
  `tests/test_liveclient_shape_audit_rm601.py` then owe a re-pin). LX-02 PASSES when the shape audit
  ran on a VALID capture set and `horde.verdict=MATCH`; the RM-673 / RM-674 verdicts are recorded
  either way and are each that row's own decision, not LX-02's pass bar. An SR game with no grub
  take reads `horde.verdict=NO_RESULT`: the row stays open on that half.
  EVIDENCE CONTRACT: the checker's JSON (`rm673`, `rm674`, `horde`, `name_forms`, `payloads`,
  `relay_ts_span_s`, `game_time_max`, `game_modes`), each capture file's mtime, the game's mode /
  queue, and the main checkout HEAD plus `ops/runtime/health.json` `pid` / `started_at`. LX-07
  (VictimName / KillerName forms) may cite the same `name_forms.ChampionKill` counts for its name
  half; its death-recap row is its own.
  SUBSTITUTION CHECK: `tests/test_gated_lx02_payload_check.py` and the RM-601 fixture produce every
  verdict above from hand-built payloads (the fixture alone reads CHAMPION_NAME / FIRSTBLOOD / MATCH),
  so a verdict proves nothing unless the files came off the live relay during the played game. Three
  look-alikes: a copy of the fixture (`synthetic=1`), one capture saved twice (`duplicates>0`), and the
  relay's last snapshot served after the game ended - `get_latest_liveclient` returns the stale cache
  when the :2999 self-read fails (`vision_server/_relay.py`), so two captures with the same `ts` are one
  read (`relay_ts_span_s=0`). Mtimes must fall inside the game window. This tool reads the wire FORM
  only; whether the dashboard then RENDERS the right grub / drake side is a separate on-screen check
  and is not closed by this row.
- **LX-04** (RM-606, self cast log) Replay recorded sessions (LX-03) through
  `core/self_cast_log.detect_from_frames`; per-slot totals within tolerance of Match-V5
  spell1..4 casts; re-measure FALL_THRESHOLD, GAP_S, the partial-cost tolerance and the validator
  tolerance on real data; note per-second drains / toggles (expected slot_guess None).
  **READY (s144 lane gated c33, 2026-10-30; PREP only, nothing ticked).** PRECONDITIONS measured
  2026-10-30 at idle: (1) LX-04 is an OFFLINE replay, so `RC_SELF_CAST_LOG` is NOT needed; it needs
  an LX-03 recording, and `logs/sessions/` does not exist on the live box (the LX-03 precondition:
  `RC_SESSION_RECORDER=1` in the RC process env plus an RC restart, a main-session / operator act).
  LX-04 drains on the SAME game that passes LX-03. (2) The truth is the Match-V5 participant row,
  which `lib/rewind_live_writer.py` writes into `data/rewind_history.db` about 90 s after the game
  ends (`schedule_live_insert`, wired at `app/_game_lifecycle.py` `on_game_end`); measured read-only:
  all 30440 participant rows carry non-null `spell1_casts` .. `spell4_casts`, across 2965 of the 2966
  matches (one q830 match has no participant rows) and 22 queue values (21 plus NULL). The live
  writer's pinned path ends a q2400 / KIWI game `event_mode_excluded` with no Riot call
  (`EVENT_MODE_QUEUE_IDS` / `EVENT_MODE_GAME_MODES`, `_is_event_mode`; only the legacy unpinned
  fallback, taken when no game-end pin exists, skips that check), so an ARAM Mayhem game gets
  no truth row at game end; the DB does hold ONE q2400 KIWI match with all 10 casts populated (how it
  landed was not measured), so a Mayhem game is graded only if its own row appears, else
  `no_match_row`. The one PRACTICETOOL (q3140) match present carries `spell1_casts=0` on both rows, so
  a Practice Tool row is no truth either. Play a matchmade SR (q400 / q420) or a plain ARAM (q450),
  whose rows the live writer does land. (3) The champion
  must spend MANA or ENERGY on at least one slot in the DS cost data (`data/daemon_slayer/current.txt`
  = `16.21.1` at prep, `champion_abilities.json` form 0): Ahri / Ezreal (all four MANA) qualify, Garen
  (no cost on any slot) reads `NO_COSTS` / `NOT_OBSERVABLE` and drains nothing, Akali grades Q and E
  only. Every match id (all 2966) has the shape `<PLATFORM>_<gameId>` with no two sharing a game id,
  so the tool joins the
  recording to its truth row by the file stem, with no id typed or printed.
  PROBE (after the game ends and the rewind write has landed, from the main checkout):
  `python tools/gated_lx04_cast_check.py logs/sessions/<file>.jsonl --truth-db
  data/rewind_history.db --json` (read-only: the session through `read_session`, the DB in sqlite
  `mode=ro`; no stem, match id or player name is printed - RM-906; `--champion-id` overrides a
  session that names no single champion; `--truth-json` takes a saved Match-V5 participant object
  instead of the DB). FIELD PATHS: `verdict`, `truth_status`, `truth_match.queue_id` /
  `game_duration_s`, `champion_id`, `costs.<slot>.observable`, `totals`, `validation.slots.<slot>`
  (`log` / `truth` / `diff` / `allowed` / `within` / `compared` / `rel_diff`), and the re-measure
  inputs `cadence` (median / p95 / max game-time step, `over_gap_s`), `sub_threshold` (falls under
  FALL_THRESHOLD between readings), `shortfall` (matched cost minus observed fall, `frac_of_tolerance`
  against `partial_tolerance`, `near_edge` above 80 percent of it), `gap_events`,
  `unattributed_costs` / `unattributed_top`.
  PREDICATE (stated before any game): PASS iff `verdict=PASS` - `truth_status=ok` (one match row whose
  id ends in `_<stem>`, one participant on the session's champion), at least one slot `compared=true`,
  and every compared slot `within=true` under `match_tolerance` (max(3, round(0.20 * truth))). FAIL on
  `verdict=FAIL` (record each slot's `log` / `truth` / `diff`); `no_match_row` 15 minutes after the
  end means the rewind write did not land (check `lib/ingest_receipt.py`'s receipt), not a detector
  fault. The RE-MEASURE half records values and grades no constant in the drain: it flags a follow-up
  row (never an edit) when `cadence.p95` exceeds GAP_S (1.25) or `over_gap_s` is above 5 percent of the
  steps; when `shortfall.near_edge` is above 0 or a FAIL slot under-counts while `gap_events` is 0 (the
  partial tolerance, PARTIAL_ABS 8 / PARTIAL_REL 0.15); when a PASS slot needed the absolute floor
  (|`rel_diff`| above 0.20); and it lists `unattributed_top` as the drains / toggles the row asks to
  note (slot_guess None is the EXPECTED result for them, not a FAIL; a champion whose drain sits on an
  untracked resource in the DS data, e.g. Anivia R `OTHER`, lands there too).
  EVIDENCE CONTRACT: the tool's JSON fields above (values, not "ok"), the session file's mtime, the
  game's mode / queue (`truth_match`) and `game_time_last` against `truth_match.game_duration_s`, the
  champion, the DS patch the cost table came from against the header `patch`, and the code RC ran
  (`ops/runtime/health.json` `pid` / `started_at` plus the main checkout's HEAD, as LX-03).
  SUBSTITUTION CHECK: `tests/test_gated_lx04_cast_check.py` and `tests/test_self_cast_log.py` reach
  `verdict=PASS` from hand-built frames and a hand-built truth row, so a PASS proves nothing unless
  the recording is the one that passed LX-03 for this game (stem = the LCU game id read while
  InProgress, mtime inside the game window) and the truth row came from Match-V5 for that same game
  (`--truth-db`, joined by the stem; a `--truth-json` file needs its fetch recorded). The live
  listener (`RC_SELF_CAST_LOG`, `self_cast_log.events()`) and any dashboard surface answer a
  different question and never close this row.
- **LX-12** (RM-639, death reel; after LX-10 and an operator ffmpeg install) Cut a real OBS recording after
  a real game: keyframe snapping still gives usable windows, the faststart output plays in the dashboard,
  ffprobe duration roughly equals the sum of the windows.
- **LX-13** (RM-641, review player; after LX-10) Real recording playback and seeking in Chrome over the
  dashboard's TLS handler with 206 responses; marker alignment against real footage; hotkeys and focus in
  a real browser; the PGR cost lane timing against the video.
- **LX-10** (RM-637, OBS auto-record; ONLY after the operator's batched ADR-016 setup: OBS running,
  websocket enabled, WGC capture source, locked resolution + Borderless, `obs.record.enabled` and
  `vod_record` allowed) One real match: StartRecord on InProgress + Live Client, STARTED carries
  outputPath on OBS 32 / websocket 5.7.3, sidecar finalised with offset and bookmarks, chapters land if
  the format is hybrid MP4, alignment against real video, stall detector on the real encoder, CPU and
  frame time measured before any default-on, LCU bus delivers both gameflow URIs; the resolution-swap
  hazard G6-03 never exercised stays out of scope while the resolution is locked.
- **LX-11** (RM-612, replay-scrubber minimap) Visual check on the real dashboard: map art loads, badges
  and ally / enemy rings render, "sampled every 60 s" label visible, a death hides the victim.
  **READY (s144 lane gated c35, 2026-10-30; PREP only, nothing ticked).** PRECONDITIONS measured
  2026-10-30 at idle (read-only): (1) This row needs NO game in progress. It reads a STORED match:
  `dev.js` draws from `/api/replay/match/<id>` (`core/replay_history.match_detail`, timeline frames +
  kill events in `rewind_history.db`). `/api/replay/matches?limit=30` listed 30 stored matches: 20
  queue 420 and 3 queue 400, each with a position on every frame entry (170 to 410 per match) and a
  kill position on every kill, plus 7 Arena (1750) matches, for which the map is HIDDEN by design
  (`NO_MAP_QUEUES` {2400, 1700, 1750} in `web/js/panels/replay_minimap.js`). No ARAM (450) match is in
  that list, so the ARAM art branch (`map12.png`) is not checkable on today's data. Filed as a
  "Not actually live-gated" CANDIDATE (provisional RM-1118, lane report c35); this lane neither
  moved nor ticked the row. (2) The map art serves from the dashboard origin:
  `/data/ddragon/16.21.1/img/map/map11.png` 200 (70985 B; `items_index.json` version 16.21.1),
  `map12.png` 200, fallback `/data/icons/sr-minimap.svg` 200. Champion icons come from
  `/icons/champions/`. All are same-origin, so the canvas is not tainted and `toDataURL` works.
  PROBE (from the main checkout, at any time; no game needed):
  (a) `mkdir -p ops/runtime/lx11`, then `curl -sk "https://127.0.0.1:8888/api/replay/matches?limit=30"`
  and pick an SR entry (`queue_id` 420 or 400). Save it with `curl -sk
  https://127.0.0.1:8888/api/replay/match/<id> > ops/runtime/lx11/match_<n>.json`. Never paste the id
  into a tracked file (RM-906).
  (b) `python tools/gated_lx11_minimap_check.py plan --match-json ops/runtime/lx11/match_<n>.json
  --json > ops/runtime/lx11/plan_<n>.json` (drop `--json` for the human form). Node runs the SHIPPED
  `replay_minimap.js` (`buildModel` / `stateAt` / `worldToCanvas`) over every stored frame. It picks
  the first slider index with a dead champion, an ally badge and an enemy badge that overlap nothing
  (`--index` overrides), and names that index, the frame clock (`t = X.Xmin`), the map clock (`Map at
  M:SS`), and the canvas pixel centre of each badge (ring role ally / enemy) and each death cross.
  The plan carries only a truncated SHA-256 of the match id.
  (c) In the dashboard (the operator's Chrome at `https://127.0.0.1:8888/`, or headless Chromium on
  that origin): View -> Replay, click that match, and move the slider to the planned index (the
  frame clock reads the planned text). Evaluate the expression `python
  tools/gated_lx11_minimap_check.py snippet` prints. In DevTools: `copy(JSON.stringify((<snippet>)()))`,
  pasted into `ops/runtime/lx11/evidence_<n>.json`. In Playwright: `page.evaluate(<snippet>)`. The
  bundle holds the DOM text, the resolved `--signal-info` / `--signal-bad` / `--text` tokens and the
  480x480 canvas as a PNG data URL.
  (d) `python tools/gated_lx11_minimap_check.py grade --plan ops/runtime/lx11/plan_<n>.json --evidence
  ops/runtime/lx11/evidence_<n>.json --json > ops/runtime/lx11/grade_<n>.json`. The tool is
  read-only, makes no network call and never prints a match id. Exit codes: 0 PASS, 1 FAIL,
  3 INCONCLUSIVE, 2 input error.
  PREDICATE (stated before any capture): PASS iff `verdict == PASS`. That needs all of:
  - provenance: `match_tie` and `real_origin` (https :8888) true, `ui_mock` not "1";
  - DOM: the figure is shown; the note holds "sampled every 60 s" and is visible; both clocks equal
    the plan;
  - capture: the slider is at the planned index (`slider_ok`);
  - art: `ART_DRAWN` (>= 0.9 of pixels opaque and >= 16 distinct colours on a 12 px grid; an opaque
    flat fill reads `ART_FLAT`);
  - rings: every unobstructed badge is `RING_OK` in its role colour (ally = the tracked champion's
    team, `--signal-info`; enemy `--signal-bad`), with at least one ally and one enemy;
  - death: every unobstructed dead champion is `HIDDEN` (ring share <= 0.2 at its death spot) with
    `CROSS_SEEN`, at least one of them.
  FAIL is a definite contradiction on PROVEN evidence: a ring missing, a badge on a dead champion,
  no art, a hidden Replay view or figure, a canvas of another size, or a wrong note. A provenance miss (not the :8888 origin, `ui_mock` on,
  `match_tie` false) reads INCONCLUSIVE whatever the canvas shows, and the render findings are
  still listed. So do DOM fields that are not real booleans or strings, and a ring whose samples
  fall mostly off the canvas. A wrong-shaped plan or evidence file exits 2. INCONCLUSIVE is never
  a pass. A wrong clock or slider reads INCONCLUSIVE
  (a capture taken at the wrong index, or before the next animation frame redrew the map): re-capture.
  The art loads asynchronously and the map redraws on its `onload`, so capture about 2 s after
  the match opens. An `ART_MISSING` counts as a defect only if a second capture also reads it.
  Anything else inconclusive: re-run at another `--index`. KNOWN LIMIT: "hidden" is graded only at
  the death spot. The grader does not count badges, so a stray badge elsewhere needs the human look.
  The positions themselves are not graded either: the plan runs the same shipped model the page
  draws with.
  CALIBRATION: the pixel thresholds were set on PIL-drawn canvases. They have NOT been run on a real
  Chromium canvas, since that run is the drain itself. If the first real bundle reads `RING_UNCLEAR`
  or `CROSS_UNCLEAR`, that is a threshold question: keep the bundle and fix the tool. It is neither a
  pass nor a failure of the row. A human look at the same frame goes with the grade either way.
  EVIDENCE: the plan, evidence and grade JSON (paths + mtimes), the bundle's `captured_at`, the queue
  and slider index, and the code RC ran: `ops/runtime/health.json` `pid` / `started_at` plus the
  main checkout HEAD.
  SUBSTITUTION CHECK: none of these closes the row:
  - `tests/test_gated_lx11_minimap_check.py` reaches PASS from PIL canvases and a hand-built match;
  - `web/js/panels/replay_minimap.test.mjs` and `tests/test_replay_minimap_crosscheck.py` prove only
    that the model COMPUTES;
  - the ui_mock fixture (`/data/ui_mock/replay.json`, body `data-ui-mock="1"`) runs the same drawing
    code on fixture data.
  Only a bundle read on the :8888 origin with `ui_mock` off, from a stored REAL match, with
  `match_tie` true, can close it.
- **LX-09** (RM-638, mark hotkey; restart the hotkey listener first so it loads the new slot -
  `taskkill /F /PID` of it, and the service host restarts it; the RC-HotkeyListener task is gone
  since the 2026-10-31 launcher cutover)
  In a real game press Ctrl+Shift+K: a row lands in `ops/runtime/moment_marks.jsonl` with a real game id;
  a press during the loading screen is dropped and logged; after the game the marks attach to that
  game and show as "you flagged" pins in Replay and PGR. Note: in the Practice Tool Shift+K spawns a
  drake, so the chord may also do that there.
  **READY (s144 lane gated c34, 2026-10-30; PREP only, nothing ticked).** PRECONDITIONS measured
  2026-10-30 at idle (read-only): (1) The row's "restart the RC-HotkeyListener task first" is ALREADY
  MET on today's tree. The running listener (`pythonw`, started 2026-10-26 20:45:11) logged
  `hotkey_listener starting (... Ctrl+Shift+K ...)` in `logs/hotkey_listener.log`, and the last
  change to `tools/hotkey_listener.py` is `6e351117b` (2026-10-25), BEFORE that start. Re-check it at
  drain time, because a later change to that file makes the restart owed again; restarting the task
  is a main-session / operator act. `core/moment_marks.py` is imported lazily on the first press, so
  the code on disk at that press is what runs. (2) No press has ever reached the listener.
  `logs/hotkey_listener.log` (one file, about 220 KB, not yet rotated at 512 KB; first line
  2026-06-27) holds ZERO `moment mark` lines, and neither `ops/runtime/moment_marks.jsonl` nor
  `ops/runtime/moment_marks_by_game/` exists. So the first drain's rows are the file's first rows.
  (3) The press ledger: `handle_moment_mark` logs exactly ONE outcome line per press that reaches the
  dispatch worker: `moment mark: game_id=<id> game_time_s=<t>` (recorded) or
  `moment mark dropped: <reason>`. (A game-id provider that RAISES adds a `game_id unknown` line
  before the recorded one; the default provider never raises.) The hook itself logs nothing per key,
  so a press the hook never saw leaves no trace; that is why the operator's own press count is an
  input. A press in champ select or the lobby is dropped exactly like a load-screen press (:2999 is
  down for both), so a load drop needs the first GameStart / InProgress time as its LOWER bound.
  (4) The game id comes from the :8889 `/latest-lcu` relay `data.game_id`
  (`core/live_session_recorder.default_game_id_provider`, 1 s timeout, '' on any miss). The LCU
  agent sets it only in GameStart / InProgress / Reconnect (`lcu/snapshot_shape.py`), so a null id
  is the relay-miss case. The collector then attaches it by wall window
  (`core/moment_marks.ATTACH_SLACK_S` = 300 s). (5) The attach runs in the post-game collector
  (`lcu/lcu_postgame_collector.py` `_attach_moment_marks`), keyed by the EOG `gameId`. Both routes
  add `you_flagged` per request (`dashboard/routes_replay_events.py`,
  `dashboard/routes_post_game_wpa.py`). The Replay rows and the PGR chart need the match in
  `rewind_history.db`, so the RENDER half waits on the post-game Match-V5 ingest, as LX-01 does.
  PROBE (a normal match or ARAM, NOT the Practice Tool (Shift+K spawns a drake there); from the main
  checkout):
  (a) Before the queue: `date +%s` (= SINCE), and start the LX-01 phase tape (`mkdir -p
  ops/runtime/lx09; python tools/gated_lx01_draft_check.py tape --out
  ops/runtime/lx09/phase_$(date +%s).jsonl`; one tape serves LX-01 and LX-09 in the same game). Its
  first GameStart / InProgress row is the load window's lower bound. While the game is InProgress,
  read the LCU game id once
  (the :8889 `/latest-lcu` relay `data.game_id`, plain http with the `X-RC-Token` header; never paste
  it into a tracked file).
  (b) Press Ctrl+Shift+K ONCE on the loading screen, then 3 times in game at clock times you note,
  each at least 30 s apart. That is 4 presses.
  (c) After the game, once the post-game screen is up and the collector has run: `date +%s` (= UNTIL),
  then `python tools/gated_lx09_mark_check.py --since SINCE --until UNTIL --game-id <id>
  --expect-presses 4 --phase-tape ops/runtime/lx09/phase_<n>.jsonl --json >
  ops/runtime/lx09/grade_<n>.json` (no tape: `--game-start <epoch>` of the first InProgress gives a
  DIAGNOSTIC read only, since PASS-LOAD needs the tape; with neither, the load drop reads
  `LOAD_DROP_UNBOUNDED`). The tool is read-only, never prints
  a game id (every id prints as a role: match / other / null), and reads `logs/hotkey_listener.log*`
  by default.
  (d) Render half, after the ingest lands: `curl -sk
  "https://127.0.0.1:8888/api/replay/events?match_id=<platform>_<id>"` and `/api/post-game-wpa?match_id=...`,
  field `you_flagged` (list length and each `game_time_s`). Then open that match in the dashboard
  Replay panel and the PGR win-prob card and read the DOM text-first:
  `button.replay-events-row[data-kind="flag"]` rows whose `.replay-events-clock` reads M:SS of each
  pin, and the PGR `g.pwp-flag-mark` markers with `<title>` `you flagged M:SS` plus the legend
  `dashed marker = you flagged (N)`.
  PREDICATES (stated before any game): PASS-WRITE iff `marks.verdict == REAL_ID`,
  `marks.rows_in_window == 3`, `marks.offset_consistent` true, `marks.near_zero == 0`, `rows_vs_log ==
  AGREE` and `presses.verdict == MATCH`. A `NULL_ONLY` / `MIXED` read is a finding against (4), not a
  pass. PASS-LOAD iff `game_start_source == tape`, `log.load_drop == LOAD_DROP_SEEN` (a
  `gamestats_unavailable` drop at or after the tape's first game phase AND before clock zero), and
  that drop's `minus_clock_zero_s` < -2 (well clear of the clock-zero estimate, which `wall_ts` taken
  before the :2999 GET can only make early). `LOAD_DROP_UNBOUNDED` never passes. A near-zero mark with no load drop REFUTES the "dropped" claim: :2999 answered on the
  loading screen. PASS-ATTACH iff `attach.verdict == ATTACHED`, `pins == 3`, `labels_ok` and
  `clock_s_ok` true, and `attached_after_last_mark_s` > 0. PASS-RENDER iff both route lists hold 3 pins
  equal to the graded marks AND both panels draw 3 flags at those clocks. The route field alone
  never passes it.
  EVIDENCE: the grade JSON (path + mtime), the noted press clock times, the route bodies' `you_flagged`
  and the DOM read (each with ts), the game's mode / queue, and the listener start line plus
  `6e351117b`-or-later HEAD.
  SUBSTITUTION CHECK: `tests/test_gated_lx09_mark_check.py` reaches every PASS verdict from rows the
  real `build_mark` / `append_mark` / `attach_for_game` wrote from a hand-built gamestats body (and
  `tests/test_moment_marks.py` / `tests/test_hotkey_moment_mark.py` drive the same writers
  headless), so a PASS proves nothing unless (i) every recorded row has its own listener log line (`rows_vs_log == AGREE`; a hand-appended
  row has none); (ii) `clock_zero` falls after that game's first InProgress phase (an LX-01 phase
  tape run alongside) and before its end; and (iii) the pin file's `attached_at` follows the post-game trigger
  of THAT game. A dashboard showing pins is the RENDER half only: it draws whatever the pin file
  holds, so it never closes the write or load halves.
- **LX-08** (RM-603, skill points) Capture whether `/allgamedata` `activePlayer.abilities` carries
  `abilityLevel` per slot; whether the free R rank of Jayce / Elise / Nidalee / Karma reads 1 at level 1;
  what Aphelios's slots report; whether ranks read the same in ARAM, Arena and URF.
  **READY (s144 lane gated c29, 2026-10-28; PREP only, nothing ticked).** PRECONDITIONS measured
  2026-10-28 at idle: the :8889 relay answers `/health` 200 and
  `ops/runtime/liveclient_captures/` does not exist yet (the LX-02 drain creates it; this row reuses
  that capture set). WHY THE ROW MATTERS: RC reads the ranks two ways. `dashboard/_liveclient.py`
  passes `activePlayer.level` + `activePlayer.abilities` to
  `core.skill_point_tracker.read_skill_snapshot` (the `ability_ranks` field), and
  `game_reader/snapshot_normalizer.py` `_read_my_abilities` reads the separate
  `/activeplayerabilities` endpoint and DROPS a slot with neither a `displayName` nor a `name`, so the tracker
  reads None for that whole state. The tracker's free-R model (`SPECIAL_KITS`, `free_r=1` for Jayce /
  Elise / Nidalee / Karma) and its Aphelios fence rest on a Match-V5 probe only; its own docstring
  says the free R rank reading 1 at level 1 "is unverified on a real frame".
  PROBE (run from the main checkout, where the token resolves; the LX-02 relay captures count here
  too): during any League game take relay captures as in LX-02 (`curl -sf -H "X-RC-Token: $TOK"
  http://127.0.0.1:8889/latest-liveclient -o ops/runtime/liveclient_captures/lx08_$(date +%s).json`),
  at least one at level 1 before the first level-up when the champion is Jayce / Elise / Nidalee /
  Karma; plus at least one direct read of the normalizer's endpoint,
  `curl -sfk https://127.0.0.1:2999/liveclientdata/activeplayerabilities -o
  ops/runtime/liveclient_captures/lx08_apa_$(date +%s).json` (no token: Riot's local API), then
  `python tools/gated_lx08_ranks_check.py ops/runtime/liveclient_captures/ --json` (read-only, no
  network). The checker prints the active player's `championName` (a fixed Riot string that picks
  the kit) and never a summoner name, Riot id or ability display name (RM-906). FIELD PATHS:
  `activePlayer.level`, `activePlayer.abilities.{Q,W,E,R}.abilityLevel`, the roster row matched on
  `activePlayer.summonerName` -> `allPlayers[].championName`, `gameData.gameMode`; for the apa file
  `{Q,W,E,R}.abilityLevel` / `.displayName`; the relay wrapper `ts`.
  PREDICATE (stated before any game): VALID only if `synthetic=0`, `duplicates=0` and every file's
  mtime falls inside the played game (else NO_RESULT, re-capture). Then, recorded as values:
  `ranks.verdict` PRESENT (every allgamedata capture carries an integer `abilityLevel` on all four of
  Q/W/E/R AND `read_skill_snapshot` returns a reading: the first LX-08 question is YES) / PARTIAL
  (record `ranks.abilityLevel_types` per slot and file it) / ABSENT (the dashboard `ability_ranks`
  field is structurally None live: file it against `dashboard/_liveclient.py`); `self` must read
  `exact` for every capture, else the kit lookup ran on a fallback row and the free-R / fenced answers
  are void for those captures. `free_r.verdict` READS_1 = the `free_r=1` model holds; READS_0 = the
  free R rank is NOT on the wire at level 1, so `unspent` still counts right but `slot_open` lights R
  at level 1 for that kit (file it against `core/skill_point_tracker.py` `_FREE_R_KIT` / Jayce);
  MIXED = record per champion and file it; NO_RESULT = no level-1 capture of a free-R kit (that half
  stays open). `fenced` (Aphelios): record the level and the four ranks; ranks that track level points
  would re-open the fence (file it, never edit the fence in the game), ranks frozen at 0 / 1 confirm
  it. `per_mode`: one row per `gameMode` (CLASSIC, ARAM, KIWI, CHERRY = Arena, URF); CONSISTENT =
  every capture has `0 <= unspent <= level` and no rank above the slot cap; the URF / ARAM / Arena
  half of the question is answered only for a mode that appears, and `modes_agree` is recorded,
  never extrapolated to an unplayed mode. `apa.verdict` READABLE (every slot named and ranked: the
  normalizer path reads) / DROPS_SLOT (record `apa.dropped_slots`: the normalizer state reads None for
  the tracker; file it against `_read_my_abilities` `if name:`) / NO_RANK / NO_RESULT (no apa
  capture). LX-08 PASSES on `ranks.verdict=PRESENT` from a VALID set; each other verdict is recorded
  and is its own question's answer, not LX-08's pass bar.
  EVIDENCE CONTRACT: the checker's JSON (`ranks`, `self`, `champions`, `free_r`, `fenced`, `per_mode`,
  `modes_agree`, `apa`, `kinds`, `synthetic`, `duplicates`, `relay_ts_span_s`), each file's mtime, the
  game's mode / queue and game time at each capture, and the main checkout HEAD plus
  `ops/runtime/health.json` `pid` / `started_at`.
  SUBSTITUTION CHECK: `tests/test_gated_lx08_ranks_check.py` produces every verdict above from
  hand-built payloads (`tests/test_skill_point_tracker.py` and
  `tests/test_liveclient_ability_ranks_rm603.py` do the same for the readers under it), so a verdict proves nothing unless the files came off the live relay / :2999 during the
  played game. Look-alikes: a copy of a test payload (`synthetic` catches only a SYNTHETIC
  `_comment` or `Synthetic` roster names, so a scrubbed hand-built file passes it - the mtime check
  is the guard), one capture saved twice (`duplicates>0`), the relay's last snapshot served after
  the game (`relay_ts_span_s=0` across the set), and a level-1 capture taken in the Practice Tool
  after a level reset (record the queue). This row reads the wire ranks only; whether the dashboard
  RENDERS a skill-point nag is a separate on-screen check, and `/api/state` callouts are blanked while
  a game is live (B4, `skill_point_callout` docstring), so no nag on screen is NOT a failure here.
- **LX-07** (RM-608, death recap) With `RC_DEATH_RECAP=1`, one real own death writes a row to
  `data/coaching/death_recaps.jsonl` (champion names only); confirm the live VictimName / KillerName
  forms (shared with LX-02 / RM-673); sanity-check the estimated split per mode (SR, ARAM / KIWI, Arena).
  **READY (s144 lane gated c30, 2026-10-28; PREP only, nothing ticked).** PRECONDITIONS measured
  2026-10-28 at idle: (1) the flag has never been ON in any retained RC lifetime -
  `data/coaching/death_recaps.jsonl` does not exist (gitignored), and none of the 37 `logs/*.log`
  files (the 15 dated daily logs span 2026-10-14 .. 2026-10-28, 14-day retention) holds the
  writer's INFO line `death recap (estimated) enabled`, while other `rc.*` INFO lines do reach them. The listener installs
  once, at `core/liveclient_cache.start()` (`_install_optional_taps` -> `core.death_recap.install_if_enabled`,
  flag read from the RC PROCESS env), so turning it on is an env change plus an RC restart BEFORE the
  game: a main-session / operator act, never a lane's; the INFO line in that day's log is the proof
  it took. (2) `DeathRecapTap.on_snapshot` uses the FIRST snapshot only to set the EventID
  high-water: a death already in the event list when RC first polls is never recapped, so the RC
  start must come before the game. (3) The DS split needs DS `:8860` up (`fetch_ds_profiles`,
  0.4 s per `/burst` call on one daemon worker thread); with DS down every row reads `basis=local`
  and only the local half can be graded. (4) No panel renders a recap: `latest_recap` /
  `format_line` have no caller outside `core/death_recap.py` and its tests, and the rows' only
  consumer is `scripts/postmortem_analyze.py` (`damage_recap`), so LX-07 asks whether the row is
  WRITTEN and right, never whether it renders. (5) THE RISK THIS ROW CAN EXPOSE: `is_self_death`
  matches `VictimName` against the active player's PLAYER-name keys only (`summonerName` /
  `riotIdGameName` / `riotId`), while `resolve_player` accepts a champion name for the killer
  (RM-673). If the wire's `VictimName` carries the champion name, the tap never fires and no row is
  ever written; `tests/test_gated_lx07_recap_check.py::test_champion_name_victim_is_tap_blind`
  shows the real `process_kill` returning None on that shape. The grader reads it as `TAP_BLIND`.
  PROBE (from the main checkout, during the same game as an LX-02 capture set, any mode): write down
  `date +%s` at game start; take an LX-02 capture (the LX-02 PROBE command, same directory) after
  each own death and one after the last; write down `date +%s` at the end screen; then run
  `python tools/gated_lx07_recap_check.py --since <start> --until <end + 60> --captures
  ops/runtime/liveclient_captures/ --json`. The capture directory is shared with LX-02 / LX-08 and
  will hold earlier games: the grader drops every capture whose relay wrapper `ts` falls outside
  the window (`captures_outside_window`), and a capture with no wrapper `ts` cannot be placed, so
  save this game's captures into a fresh subdirectory (`.../liveclient_captures/lx07_<start>/`) and
  pass that instead when any doubt remains. Read-only: the log is read line by line, the captures
  through the LX-02 loader, no network call. No player name is printed (RM-906); champion names,
  modes, event ids and game times are. FIELD PATHS: `log_exists`, `torn_lines`, `rows_in_window`,
  `rows_outside_window`, `recorded_at_first` / `_last`, `rows_verdict`, `rows_failed[].problems`
  (`schema` / `provenance` / `mode` / `contributors` / `shares` / `basis` / `names_only` /
  `player_name_leak`), `player_name_leaks`, `modes`, `per_mode.<MODE>.rows` / `.basis` /
  `.mean_shares` / `.ds_contributors` / `.divergent[]`; `join.join_verdict`, `join.own_deaths`,
  `join.tap_blind`, `join.deaths_without_row`, `join.contributors_mismatch`,
  `join.rows_without_wire_death`, `join.rows_after_last_capture`, `join.victim_forms`,
  `join.killer_forms`, `join.deaths[]`; `synthetic`, `payloads`, `captures_outside_window`.
  PREDICATE (stated before any game): the WRITE half PASSES iff `log_exists=true`, `torn_lines=0`,
  `rows_in_window` at least 1, `rows_verdict=PASS` (so `player_name_leaks=0` and `names_only` held on
  every row), and `join.join_verdict=MATCH` with `contributors_mismatch=0` and
  `rows_without_wire_death=0`, on a VALID LX-02 capture set (`synthetic=0`, its own `duplicates=0`
  and `relay_ts_span_s` above 0). `TAP_BLIND` is a FAIL: record `victim_forms` and file S144-G-20.
  `MISSING` with every death `tap_sees=true` is a FAIL to explain (an RC start after the death, a
  dropped worker, a DS hang), never to argue away. The NAME half is RECORDED either way:
  `victim_forms` / `killer_forms` over own deaths, beside LX-02's `name_forms.ChampionKill`; it is
  RM-673's decision, not LX-07's pass bar. The SPLIT half is graded PER MODE, one game each (SR;
  ARAM or KIWI, both `ARAM`; Arena `CHERRY` -> `ARENA`); an unplayed mode stays open. A mode PASSES
  iff it has at least one row with `basis` `ds` or `mixed` (DS up) and `divergent` holds at most half
  of that mode's `ds_contributors`; every `divergent` entry is listed in the evidence by champion
  (a divergence from the coarse DDragon fallback is not by itself a defect; more than half is a FAIL
  to file). A game with no own death reads `rows_verdict=NO_RESULT` / `join_verdict=NO_RESULT`: the
  row stays open. `names_only` checks champion names against the tracked
  `data/meta/ddragon_champions.json` (16.21.1 at this cycle): a champion newer than that file, or a
  non-English client's localized `championName`, reads `names_only` on a genuine row - record the
  name and refresh the catalog, it is not a leak.
  EVIDENCE CONTRACT: the grader's JSON (values, not "ok"); the two epochs and the end-screen time;
  the game's mode / queue and length; the capture files' mtimes; the RC that ran
  (`ops/runtime/health.json` `pid` / `started_at` against the game start, and the main checkout
  HEAD); the `death recap (estimated) enabled` log line with its time (who set the flag, where, and
  when RC restarted); and DS `:8860/health` read during the game.
  SUBSTITUTION CHECK: `tests/test_gated_lx07_recap_check.py` writes rows through the REAL
  `process_kill` from hand-built payloads (DS stubbed) and produces every verdict above, so a
  verdict proves nothing unless the rows came from the live RC during the played game. The rows
  carry NO game id, so `recorded_at` inside the observed game window and the `event_id` /
  `game_time_s` join against that game's own captures are the only per-game keys; on the FIRST
  drain the log file must first appear after the game starts (its absence was measured this cycle).
  A `process_kill` call by hand, or a test that omits `path=`, writes the same row into the live
  `DEFAULT_RECAPS_PATH`: no such call may run on the box between the game and the probe, and none
  ever closes LX-07. Grading against `/api/state` or a dashboard surface is the substitution kill:
  the join reads the wire's ChampionKill events from the relay captures only.
- **LX-06** (RM-604, event channel) A real game's death, level-up, completed item and objective events
  (including `stolen` on a stolen objective) reach a live `/api/events` EventSource client; a
  reconnect resumes with Last-Event-ID across the real 600 s connection cap and across a dashboard
  restart (expect a `gap`, then a re-read of /api/state).
  **READY (s144 lane gated c24, finished c27, 2026-10-28; PREP only, nothing ticked).** PRECONDITIONS measured
  2026-10-28 06:59 -05:00 at idle against the live RC (`ops/runtime/health.json` pid 6392,
  `started_at` 2026-10-28T06:49:36Z): (1) the running code serves the route with the s144 true-audit
  fixes - `GET /api/events` answered 200 `{"head": <h>, "events": [], "gap": null, ...}`, `?since=%C2%B2`
  answered 400 `{"error":"bad_since"}`, and an SSE GET sent `retry: 2000` then one `hello` at the head.
  (2) The hub had never been built in that RC lifetime: `<h>` equalled the wall clock in ms at this
  cycle's first request (the id seed), so no client had subscribed since the start. That probe itself
  built the hub and installed its listener (idempotent, one derive per 0.5 s relay poll, until the next
  RC restart): a later drain must not read a non-seed head as proof that a client ran. (3) The hub
  is built LAZILY by the first `/api/events` request (`core/live_event_hub.ensure_installed`), and
  there is no backlog before it: the recorder must connect BEFORE the game loads (champ select).
  (4) Nothing in `web/` subscribes to `/api/events`, so the drain's client is
  `tools/gated_lx06_events_check.py record`, an EventSource-semantics client (server `retry`, then
  `Last-Event-ID` = the last id seen, as WHATWG EventSource does). Its wire behaviour is pinned by
  `tests/test_gated_lx06_events_check.py` against the REAL route over loopback. A browser EventSource
  is not exercised: RC ships no browser consumer, so the row grades the protocol; a headless-Chromium
  page is an optional strengthening, not a pass condition (decision recorded here; it reverses if a
  `web/` consumer lands). (5) The restart half needs no game (a reconnect after any RC restart reads
  the new ms seed as a huge `gap`): RM-1058 proposes it as a `Not actually live-gated` candidate for
  a human to move; it stays here until then.
  PROBE (any checkout; the tool reads no `data/`; the capture holds riot ids from allPlayers, so it
  goes under gitignored `ops/runtime/`, whose directory must exist first): at champ select start
  `python tools/gated_lx06_events_check.py record --out ops/runtime/lx06/<stamp>.jsonl --final-url
  https://127.0.0.1:2999/liveclientdata/allgamedata --minutes 45` (GETs only; `RC_GAME_HOST` if the
  game is not local; `--out` must be NEW). It polls the Live Client every 20 s into
  `<out>.final.json` (the last non-empty body). Let it run at least 11 game minutes so the server's
  600 s cap closes one connection. After the game: `python tools/gated_lx06_events_check.py check
  ops/runtime/lx06/<stamp>.jsonl --json`. FIELD PATHS: `bases`, `replay_conns`, `non_sse_conns`,
  `connections`, `end_reasons`, `kinds`, `missing_kinds`, `unknown_kinds`, `stolen_objectives`,
  `duplicate_objective_ids`,
  `holes`, `bad_gaps`, `lost_gaps`, `answered_conns`, `reconnect_hello`, `last_event_id_mismatch`,
  `cap_resumes`, `restart_resumes`, `state_reread_after_restart`, `stream_ok`, and `final.window` /
  `objectives_in_window` / `objectives_missing` / `objectives_stolen_mismatch` /
  `objectives_unexpected` /
  `victim_name_form` / `death_mismatch` / `level_chain_breaks` / `level_final_mismatch` /
  `level_final_skipped` / `ok`.
  PREDICATE (stated before any game): PASS iff `bases=["https://127.0.0.1:8888"]` (or the
  configured dashboard host), `replay_conns=[]`, `non_sse_conns=[]` and `stream_ok=true`. That
  means: at least one connection answered 200 with a frame; every event id is exactly the previous
  id + 1; the only gap accepted is a reconnect's FIRST frame spanning more than 10 x RING_MAX ids
  (a new process's ms seed, the restart class); a gap a ring overflow left (`lost_gaps`) fails,
  because those events never reached the client; every connection sent the cursor as
  Last-Event-ID (none before the first frame ever arrived); no RESUME (a connection that sent
  Last-Event-ID) got a `hello`; and no objective `event_id` arrived twice
  (`duplicate_objective_ids=[]`). Also: `unknown_kinds=[]`;
  `missing_kinds=[]` (a game with no completed item or no objective leaves that kind open: record
  it open, not passed); `cap_resumes` non-empty (a connection that hit EOF at 595 s or later, whose
  successor answered 200 with a frame, resumed with Last-Event-ID, got no `hello` and no hole);
  `final.ok=true` with `objectives_in_window` of 1 or more. The window runs from
  the first timed event to the earlier of the last one and the final file's `gameData.gameTime`.
  `final.ok=true` means: every objective in `events.Events` inside that window matched by
  `event_id` with the same `stolen`; no objective_taken whose `event_id` the game never logged
  (`objectives_unexpected=[]`; one within 3 s of the final poll or after it is not judged);
  every death and every ChampionKill at least 5 s inside both
  edges paired (same champion, the kill at most 3 s before the death or 0.5 s after it, the relay
  poll lag); each champion's level_up chain is continuous; its level as of the final poll equals
  the final file's level (a champion with a level-up within 3 s of that poll is listed in
  `level_final_skipped`, not graded); and `victim_name_form` has no `unmapped`. `item_completed`
  is graded only as SEEN (`missing_kinds`), never against the final inventory: sales, consumption
  and transforms make the final file no witness for a completed buy (LX-05's tape fold owns item
  correctness). STOLEN half: only if the final file
  holds a `Stolen` objective in the window, `stolen_objectives` of 1 or more; otherwise it stays
  open (steals are rare; one game rarely closes it). RESTART half: `restart_resumes` non-empty and
  `state_reread_after_restart` non-empty and all 200. An RC restart is a main-session act, never a lane's, and is
  best done idle (RM-1058), not mid-game: a mid-game restart blinds the new hub across the
  outage, so that game's `final.ok` fails by design (missed objectives, unpaired kills, broken level
  chains) and cannot grade the event half. Record `victim_name_form` (`champion` vs `player`) for
  LX-02 / RM-673. A death the pairing cannot match is a FAIL to record with the champion and the
  time, not to argue away. (Untested assumption: a turret or minion execute fires a ChampionKill.
  If one does not, the unmatched death is the measurement that says so.)
  EVIDENCE CONTRACT: the check output (values, not "ok"); the capture's first `conn` wall time
  against the game start and the last `end` against the end screen; mode, queue and game length;
  the final file's `gameData.gameTime`; the capture's `meta` row `final_url` (it must name `:2999`, read by hand: `check` does not print it); and the code RC ran (`ops/runtime/health.json` `pid` /
  `started_at` against the game start and the main checkout's HEAD, as LX-03).
  SUBSTITUTION CHECK: the tests drive the REAL route and a REAL `LiveEventHub` with synthetic
  snapshots over loopback, and every stream check passes on them, so a passing capture proves
  nothing about a real game unless it came from the live dashboard during that game. So `bases` must
  name the live dashboard. `replay_conns` must be empty: `tools/replay_session.py` marks every
  response `X-RC-Replay: 1` and serves `/api/events` as JSON, which `non_sse_conns` catches. The
  first `conn` must come before the game's first event time. The objective and death checks must
  grade against the Live Client's OWN `/liveclientdata/allgamedata`, read directly at `:2999`, not
  against anything RC computed (`/api/state` reads the same RC liveclient cache feed the hub derives from, so
  grading against it is the substitution kill). A capture recorded from a replay, a test or a hand-fed hub never closes
  LX-06.
- **LX-05** (RM-607, item tape) One ARAM Mayhem (KIWI) game with `RC_ITEM_TAPE=1`: folded tape equals
  the final allPlayers inventories; combines match DDragon recipes; anvil / augment grants typed
  ITEM_GRANTED; rows land in timeline_events with `source='live_tape'` after the 180 s delay.
  **READY (s144 lane gated c23, 2026-10-28; PREP only, nothing ticked).** PRECONDITIONS measured
  2026-10-28 at idle: (1) the flag has never been ON on the live box - `data/rewind_history.db`
  `timeline_events` has NO `source` column (the column is added lazily by the first `persist_tape`,
  so its absence means no tape was ever written), and `RC_ITEM_TAPE` is in neither the user nor the
  machine environment key nor any tracked or gitignored config outside the code, docs and tests. The
  listener installs once, at `core/liveclient_cache.start()` (`_install_optional_taps` ->
  `install_if_enabled`, flag read from the RC PROCESS env), so turning it on is an env change plus an
  RC restart BEFORE the game: a main-session / operator act, never a lane's. An RC that starts
  mid-game sees held items as `INVENTORY_BASELINE`, which is never persisted, so the fold will not
  match: the RC start must come before the game's first shop visit. (2) The persist is a daemon
  `threading.Timer` of `DEFAULT_DELAY_S` = 180 s, scheduled from
  `PostgameCollector._publish_game_end_pin` with the EOG gameId: an RC restart (or a supervisor
  bounce) inside those 180 s loses the tape with no log line (the Timer only logs a failed open or
  write), so do not restart RC until the probe below shows rows. (3) The independent final-inventory
  source is the LCU end-of-game block in `data/postgame_stats.db` `aram_player_stats` (KIWI maps to
  ARAM in `_MODE_MAP`; `match_id` is the bare gameId; item0..item6 per `game_name#tag_line` + team),
  and its newest `aram_matches` row is `captured_at` 2026-08-02 (7 KIWI rows): no KIWI game has been
  stored since. Each of those 7 matches holds exactly ONE `aram_player_stats` row (with
  `is_local_player=0`), so the EOG source grades at most the players it names (the tool reports
  `all_players=false`; RM-1057). Only an LX-03 recording of the SAME game (`--session`, last frame
  with `allPlayers`, which needs `RC_SESSION_RECORDER=1` too) grades all ten. With neither, the fold
  half stays open and only the row / recipe / grant halves can be graded.
  PROBE (from the main checkout, where the DBs live; a lane worktree has no `data/`): note the LCU
  game id while InProgress (as LX-03: `/latest-lcu` -> `data.game_id`). Within 180 s of the end
  screen run `python tools/gated_lx05_tape_check.py --game-id <id> --no-final` once (expect
  `tape_rows=0`), then after 200 s `python tools/gated_lx05_tape_check.py --game-id <id> --json`
  (add `--session logs/sessions/<id>.jsonl` when the EOG row is missing). Read-only: both DBs open
  with a `mode=ro` URI; SQLite still updates the `-shm` wal-index mtime on any open (measured this
  cycle: content files' size and mtime unchanged, `-shm` mtime moved), which is every reader's
  behaviour and no content write. Riot ids and the match id print only with `--show-id`, and never go
  into this file (RM-906). FIELD PATHS: `source_column`, `tape_rows`, `rows_by_type`,
  `non_tape_item_rows`, `timestamp_ms_first` / `_last`, `combine_rows`, `combine_recipe_bad`,
  `grant_ids_persisted`, `fold.players_compared` / `players_tape_only` / `players_final_only` /
  `unexplained_diffs` / `fold_match` / `implicit_transforms`, and per player `tape_extra` / `final_extra` with each id's
  `explained` class (`grant` / `consumable` / `trinket` / `consumable_or_trinket` / `transform`).
  PREDICATE (stated before any game): PASS iff the first probe reads `tape_rows=0` and the second
  `source_column=true` with `tape_rows` above 0 (the delay); `non_tape_item_rows=0` (Match-V5 serves
  no KIWI timeline, so a non-zero means the tape was refused as `v5_present` - a FAIL to explain);
  `combine_rows` above 0 and `combine_recipe_bad=[]` (a game with no completed item cannot grade the
  recipe half: record it open, not passed); `grant_ids_persisted=[]` AND at least one player's
  `final_extra` carries an id explained `grant` (that is the only DB-visible trace of an
  ITEM_GRANTED: the type is never persisted, so a game with no Mayhem augment item or anvil grant
  leaves the grant half open); `unexplained_diffs=0`, `players_final_only=0` and `fold_match=true`,
  with `fold.players_compared=10` and `players_tape_only=0` on the session source
  (`all_players=true`), or `players_compared` equal to the EOG row count on the EOG source (a
  PARTIAL fold pass: record which players were graded); `timestamp_ms_last` within the game length.
  The fold reads PERSISTED rows only (PURCHASED / SOLD / COMBINED, one row per copy) and clamps at
  zero after every row as the writer's `fold` does, so the tool explains, never hides, a diff on a
  consumable, trinket, grant or transform id (a transform pairs one copy for one copy, and a sale or
  combine of a transform TARGET the fold never saw consumes its held source, counted in
  `implicit_transforms` - ITEM_TRANSFORMED itself is tape-only, never a row); a diff it cannot
  explain is a real tape miss and is a FAIL to record with the id, not to argue away. (The tape's
  known blind spots do NOT produce fold diffs: a buy-and-undo between two snapshots never reaches
  the tape, and a component bought and combined inside one poll - `_DEFAULT_POLL_S` 0.5 s in
  `core/liveclient_cache.py` - folds correctly as a PURCHASED of the finished item; both only
  mis-type, never mis-count.)
  EVIDENCE CONTRACT: the two probe outputs (values, not "ok") with the wall-clock time of each
  against the end-screen time; the game's mode / queue (KIWI / 2400) and length; which final source
  graded the fold (`eog` or `session`); the code RC ran (`ops/runtime/health.json` `pid` /
  `started_at` against the game start and the main checkout's HEAD, as LX-03); and how the flag was
  set (who set it, user env or launcher, and when RC restarted).
  SUBSTITUTION CHECK: `tests/test_gated_lx05_tape_check.py` drives the REAL diff engine over
  synthetic snapshots and writes through the REAL `persist_tape`, and every check above passes on
  it, so a passing probe proves nothing unless the rows came from the live RC: on the FIRST drain
  the `source` column must first appear AFTER the drain game's end (its absence was measured this
  cycle; once any tape has landed this check is gone, so later drains rely on the two below and on
  the first probe's `tape_rows=0` for this match id inside the 180 s window), the rows'
  match id must be `<PLATFORM>_<the gameId read live while InProgress>`, and the 180 s gap between
  the two probes must be observed, not assumed. A `persist_tape` / `on_game_end` call made by hand
  or by a test against the live DB writes the same rows: no such call may run on the box between
  the game and the probe, and none ever closes LX-05.
- **LX-03** (RM-605, session recorder) With `RC_SESSION_RECORDER=1` during a real match: the file
  under `logs/sessions/` carries the real gameId, the `config_key` from game.cfg and fresh
  vision_state; then replay it into the headless UI with `tools/replay_session.py`. A replay never
  closes any gated row.
  **READY (s144 lane gated c22, 2026-10-28; PREP only, nothing ticked).** PRECONDITIONS measured
  2026-10-28 at idle: (1) the flag is OFF on the live box - `logs/sessions/` does not exist, no day
  log carries `live session recorder enabled`, and `RC_SESSION_RECORDER` is in neither the user nor
  the machine environment key. The tap installs once, at `core/liveclient_cache.start()`
  (`install_if_enabled`, flag read from the RC PROCESS env), so turning it on is an env change plus an
  RC restart: a main-session / operator act, never a lane's. Without it the drain has nothing to read.
  (2) `config_key` reads `unknown` on this box today: `core.hud_settings.read_hud_settings()` finds no
  `[General]` `Width` / `Height` in game.cfg (`ok=False`; HEAD logs nothing for it, the unlanded
  rewrite below warns once), and the recorder writes that value through unchanged (`_config_key`). So
  "the config_key from game.cfg" is satisfied by `unknown` as long as it EQUALS the reader at drain
  time; a header `unknown` is not a recorder defect, and a `WxH|...` key would mean League rewrote
  game.cfg since this read (record which). The unlanded lane/true-audit `core/hud_settings.py` rewrite
  (`a9eb22c9d`) returns the same dict on this box (compared in memory, every field equal), so a drain
  on either code version reads the same key.
  PROBE (after the game ends, from the main checkout - the :8889 token file is gitignored and absent
  in a lane worktree, where `/latest-lcu` answers 401): note the LCU game id while InProgress
  (`/latest-lcu` -> `data.game_id`, the recorder's own `default_game_id_provider` source), then
  `python tools/gated_lx03_session_check.py logs/sessions/<file>.jsonl --live-config-key
  --expect-game-id <id> --json` (read-only; the stem is printed only with `--show-id`, and a real game
  id never goes into this file - RM-906). FIELD PATHS: file stem; header `config_key` / `mode_key` /
  `patch` / `ENGINE_VERSION`; per frame `seq`, `game_time`, `snapshot`, `vision_state`.
  PREDICATE (stated before any game): PASS iff `stem_kind=gameid` and `game_id_match=true`;
  `config_key_match=true` against the live reader; header `mode_key` is RC's mode for the game played
  (`sr` / `aram` / `arena` / `tft` / `brawl` / `jade` / `unsupported`, from
  `mode_from_game_mode_string(gameData.gameMode)`; `unsupported` for a playable mode is a FAIL);
  `seq_contiguous=true`; `game_time_backsteps=0` (a backstep of more than 5 s closes the session and
  reopens the same `<gameId>.jsonl` with `seq` back at 0 and no second header - `_write_frame` /
  `_start_session` - so it shows as `seq_contiguous=false`: a FAIL to explain, not a pass; if the LCU
  id was empty at that moment the reopen lands in a second, `nogameid-*` file instead, so list every
  file whose mtime falls in the game window); `frames_with_snapshot` equals `frames`; and
  `frames_with_vision_state` is above 0 (vision_state rides only when `data/vision_state.json` is
  under 10 s old, so not every frame carries it). FAIL on a `nogameid-*` stem (the LCU relay had no
  game id when the session opened - record whether the relay was up).
  EVIDENCE CONTRACT: the tool's JSON fields above (values, not "ok"), the file's mtime, the game's
  mode / queue and its last game_time, and the code RC ran: `ops/runtime/health.json` carries no
  commit, so record its `pid` / `started_at` and the main checkout's HEAD (an RC started after the
  HEAD commit runs that code, as the GATE 3 vision row does).
  SUBSTITUTION CHECK: `tests/test_live_session_recorder.py` and
  `tests/test_gated_lx03_session_check.py` write the same format from synthetic snapshots and pass
  every check above, so a passing check on a file whose frames did not come from the live :2999 poll
  proves nothing. The file must be created during the played game (mtime inside the game window,
  `captured_at` span close to the game length) and its stem must equal the id read live from the LCU
  while that game was InProgress. A `tools/replay_session.py` replay of the file is downstream UI work
  and never closes LX-03.

## TFT SET 18 live halves (filed 2026-10-24, RM-840; counted HERE, not in the OPEN figure above)

RM-840 made the TFT lane set-agnostic (`tft/tft_set.py` resolver, CommunityDragon Set 18 ingest in
`data/meta/tft_set18_cdragon.json`). The rows below are the halves only a real TFT game or the live
client can close; no gate above covers a TFT game, so each needs one (Set 18 ranked or normal; Set 17
stays playable beside it, so record which set the game ran).

- **LT-01 CLOSED 2026-10-25** (`a64f90c67`, LEDGER 1871: closed from QA game 20261025-070350 - a
  measured Set 18 schedule (`set18_measured`: carousel x-4, PvE x-7, augments 2-1 / 3-2 / 4-2) and
  gameTime table `_TIME_TO_ROUND_SET18` in `tft/tft_state_reader.py` (the Set 17 table matched 0 of
  28 measured round starts), routed by set and queue; the running set = LCU `tftsets.json`
  `mDefaultSet` paired with the gameflow queue id (`tft/tft_set.py` `set_from_lcu`, `QUEUE_SETS`
  {6110: 17}); post-game `players[].setCoreName` also names it. `set_from_lcu` has NO LCU caller yet,
  so the `RC_TFT_SET` pin and the newest-ingested default still decide a live game's set)
  (RM-840, running-set detection) During a real TFT game, capture whether `:2999`
  `/liveclientdata/allgamedata` `gameData` or any LCU endpoint names the running set. The
  `tft/tft_set.py` `LIVE_SET_KEYS` are CANDIDATE key names only; the one measured spelling in the tree
  is the LCU team planner's `"setId": "TFTSet17"`. Close with the key, its value for a Set 18 game, and
  whether `tft_state_reader.read` then notes Set 18 (resolver log), or record that neither surface
  exposes it (the `RC_TFT_SET` pin and the newest-ingested default stay the only routes).
  RM-855 (same game): Set 18's round schedule is UNVERIFIED - the CommunityDragon extract names
  carousel rounds and a Stage 3-7 in augment text but no round index - so a Set 18 state carries
  `round_schedule: "neutral_unverified"` (no event, PvE, god or tempo label; only Set 17 gets the
  Realm of the Gods schedule). Record which rounds are carousel, PvE and augment rounds, and whether
  the Set 17 calibrated `_TIME_TO_ROUND` table tracks Set 18 stage timing, so a grounded Set 18
  schedule can replace the neutral one.
- **LT-02 CLOSED 2026-10-25 for L4-L9** (`a64f90c67`, LEDGER 1871: Set 18 shop odds L4-L9 pinned
  from the live HUD odds bar in `tft/tft_data.py` `TIER_ODDS` (`CONSTANTS_SET` 18,
  `TIER_ODDS_VERIFIED_LEVELS` {4..9}, test `tests/test_tft_set18_odds_lt02.py`); the L7 frame
  overrides the game data (client 16/30/43/10/1, game data 19/30/40/10/1). The unread half is
  LT-02r below) (RM-840, Set 18 roll odds + pool sizes) Read the in-client shop odds per level and the
  champion pool sizes per cost for Set 18 and compare them with the constants modules
  (`tft/tft_data.py`, `tft/tft_pbe_data.py`; `CONSTANTS_SET_VERIFIED` stays False in both and
  `tft/tft_roll_odds.py` reports both STALE against the Set 18 lane until this closes). Close by pinning the measured table with a test, or recording
  that Set 18 kept the Set 17 values.
- **LT-02r** (filed s134 M1b, the residual of LT-02; half (1) CLOSED s156 by slice S6 `3b4f0baba`,
  merge `6bb3152ab`: Set 18 `POOL_SIZES` 30/25/18/10/9 from the game shop data, Set 14 tables kept
  as `POOL_SIZES_SET14`; half (2) stays open) Two halves the session 134 QA game did not read:
  (1) Set 18 champion pool sizes per cost - `tft/tft_data.py` `POOL_SIZES` is still a Set 14
  carry-over (`POOL_SIZES_FROM_SET` 14, unpinned) and the HUD does not show pool sizes; (2) the shop
  odds at L1-L3 and L10-L11, which come from the CommunityDragon map22 drop rates, not the client.
  `CONSTANTS_SET_VERIFIED` stays False until both are read. Close by pinning each measured value with
  a test, or recording which surface (client or game data) is authoritative for the level.
  **LT-02r READY (lane 9, s144 cycle 5, PREP only, no game up; NOT ticked).** One read-only
  command indexes what is already on disk and checks a read: `python tools/gated_tft_lt02r.py
  [--json] [--check-read <L>=<a>/<b>/<c>/<d>/<e> ...]` (reads the main checkout's
  `ops/runtime/tft_qa/` recorder dirs; prints file names, levels and game times only, never a pixel,
  a name, a game id or a machine path - the root prints as `<main>/ops/runtime/tft_qa`). Fields: `constants.unpinned_levels` / `unpinned_rows_pct` (the levels of
  `TIER_ODDS` outside `TIER_ODDS_VERIFIED_LEVELS`), `level_verdicts` (`on_disk_labelled` = a
  `hud_labels_*.csv` row reads that level - the level box only, never the odds bar; `on_disk_candidate` = frames with NO level labelled
  (level box not read) before the first L2 frame, for L1, or the last game / vision frames of a match whose `eog_raw.json`
  `localPlayer.boardPieces` held 10+ units - an inference, an extra-slot augment also gives 10;
  `needs_game`), `matches[]`, `pool_sizes_verdict`, `roster`, `checks[]`. Exit 0 report / every
  check equal, 1 a check differs or does not sum to 100, 2 bad arguments.
  Predicate, stated before any read: level L drains iff ONE `game_*` or `vision_*` frame of a real
  Set 18 game shows the HUD level box at L (L10: the max state, no x/y and Buy XP greyed) and a
  legible odds bar in the SAME frame, two independent readers (author plus blind, as TFT-06) agree on
  the five percents, and they sum to 100; then `--check-read L=<row>` decides the pin - equal: add L
  to `TIER_ODDS_VERIFIED_LEVELS`; different: replace the row (the live client wins, as LT-02's L7).
  Anything less (a candidate frame nobody read, one reader, a bar under an overlay) is not a drain.
  Evidence contract: value = the five percents; source = the match dir and frame file; timestamp =
  the frame's `gt` / `el`, the stage label in the frame, the queue from `MATCH_START.json`; predicate
  = this paragraph.
  SUBSTITUTION check (answer it in the tick line): `TIER_ODDS`, the CommunityDragon drop-rate table
  and `--check-read` are the compute half; only the CLIENT's odds bar is evidence. A `dash_*` frame
  shows RC's own rendering of `TIER_ODDS` and never counts; neither does a recorder QA_REPORT line
  (another agent's read, `feedback_subagent_inference_vs_evidence`) until a reader re-reads the frame.
  Idle baseline (2026-10-27 local, no game, lane/gated HEAD): 7 recorder dirs (2026-10-25);
  unpinned L1, L2, L3, L10, L11 -> L1 `on_disk_candidate` (3 + 6 early frames in 20261025-153652 /
  -162857), L2 and L3 `on_disk_labelled` (153652: vision_0004/0005 at L2, 0006/0007 at L3; 162857:
  vision_0007/0008 at L2, 0009 at L3), L10 `on_disk_candidate` (boards of 10 in 081234, 085349,
  104400), L11 `needs_game`; exit 0.
  Class-1 finding (the answer is partly on disk; recorded, not ticked): the session 134 match-2 report
  `ops/runtime/tft_qa/20261025-081234/QA_REPORT.md` section 4 already reads L3 = 75/25/0/0/0
  (game_0003) and L10 = 5/10/20/40/25 (game_0071; the L10 max state runs game_0071..0080), both equal
  to `TIER_ODDS`, and L4-L9 identical to match 1. So "never seen in client" (this row and the
  `tft/tft_data.py` comments) should read "reported seen (QA_REPORT, not yet re-read)" for L3 and
  L10: their drain is a frame re-read under the predicate above, no new game. The same section
  observed a level cap of 10 (Buy XP greyed at L10) in ONE normal game, played under the 1-1 Ashe
  modifier, so L11 likely needs an augment that raises the cap; one observation, not a measured rule.
  L11 stays game-data-only until such a game is seen.
  Pool sizes: `pool_sizes_verdict` is `no_client_surface` - the HUD and the shop never show pool
  sizes, so no live game can read them and "read in client" can never close that half as written.
  Reclassification PROPOSAL (for a human; not a move): move the pool-size half to "Not actually
  live-gated" with game data (the CommunityDragon map22 Set 18 data) as its authority, and restate
  `CONSTANTS_SET_VERIFIED` so it can flip on client-read odds plus game-data pools. UNITS_PER_COST
  (headless, compute half): the LT-03 live team-planner roster crossed with the Set 18 extract's
  costs gives {1: 14, 2: 13, 3: 14, 4: 14, 5: 10} against the Set 14 carry-over {1: 13, 2: 13, 3: 13,
  4: 12, 5: 8} (differs at 1, 3, 4, 5); whether every planner unit is in the shop pool is not shown
  by the planner, so this is a candidate, not a pin. Reverses if: `TIER_ODDS_VERIFIED_LEVELS`,
  `POOL_SIZES_FROM_SET` or `UNITS_PER_COST` move, a recorder dir gains a labelled L1 / L10 / L11
  frame, or a Set 18 surface that shows pool sizes is found.
- **LT-03 CLOSED 2026-10-25** (`2f254da18`, LEDGER 1864: 65 Set 18 codes read with GETs only in a
  live Set 18 lobby; `scripts/discover_champion_codes.py` is passive by default) (RM-840, Set 18
  team-planner codes) With the LCU agent running in a Set 18 lobby, capture
  the team-planner champion codes (`scripts/discover_champion_codes.py` shape) so a
  `data/meta/tft_set18_champion_codes.json` can be written; Set 17 is the only set with a codes file.
- **LT-04 CLOSED 2026-10-25** (`a64f90c67`, LEDGER 1871: Morgana `0` -> `88` in
  `data/meta/tft_set17_champion_codes.json`; the live client game data and the CommunityDragon
  teamplanner copy agree; case in `tests/test_tft_set18_champion_codes_lt03.py`)
  (filed s134 from LT-03, Set 17 Morgana planner code) `data/meta/tft_set17_champion_codes.json`
  (legacy mutating probe) gives Morgana `0`; the game data LT-03 read
  (`/lol-game-data/assets/v1/tftchampions-teamplanner.json`) gives `88`, and the other 63 Set 17 units
  agree. In a Set 17 lobby, read the planner code with the passive GET path
  (`scripts/discover_champion_codes.py --set 17 --dry-run`) and close by correcting the file to the
  measured value, or record why `0` is right.
- **RM-292 (c) READY (lane 9, s144 cycle 4, PREP only, no game up; NOT ticked)** (filed lane 8
  cycle 34, body in `BACKLOG.md` under RM-292; listed here in s144 because no gate above covers a TFT
  game) Three `data/tft_live_data.json` keys - `bench_units`, `shop_units`, `unit_swap` - are
  written by `tft/tft_live_analysis.py` `TftLiveAnalysis._write` and, per the row, read back only off
  in-memory dicts, never off the file. Confirm against a live TFT game before deleting them.
  Command, in a real TFT game (the game-up discriminator stated near the top of this file: `tasklist`
  shows `TFTClient-Win64-Shipping.exe` while `/api/state` `lcu.phase` is `InProgress` - the phase
  alone is also true in a League game; `liveclient` stays empty and `mode_key` can read `client` in
  a TFT game, so neither is a usable gate), from
  stage 2-1 on: `python tools/gated_tft_live_keys.py --since <game start, local ISO> --samples 40
  --interval 15 --json` (about 10 minutes, about ten analysis writes).
  Fields: `verdict`, `census.readers`, `census.files_scanned`, `snapshots[].kind` / `mtime_iso` /
  `stage_round` / `keys_present` / `filled` / `missing_head_keys`, `live_writes`, `degraded_states`,
  `populated_writes`, `head_writer_keys`, `read_at`.
  Predicate, stated before any game: PASS iff `census.readers` is empty AND `live_write` snapshots
  (key `degraded` present and false, `augment_select` false, mtime at or after `--since`) carrying
  all three keys and every key of the HEAD `_write` literal were seen in at least 3 distinct
  non-empty `stage_round` values (an augment-select merge or a `force_scan` pre-clear rewrites the
  last write in place with a new mtime, so neither counts and one round counts once). FAIL iff the
  census finds a reader (RM-292 (c) is refuted: keep the keys, file the reader) or a `live_write`
  snapshot lacks one of the three keys (the running process is not HEAD's writer: record it, re-run
  after the next RC restart). A `live_degraded` snapshot never counts and never fails:
  `_publish_degraded` copies whatever the file held, so over an absent or corrupt file HEAD itself
  writes one without the keys. Anything else is INCOMPLETE. Only PASS drains (c), and PASS
  licenses the delete as its own Tier-1 slice (the `_write` literal, the two seeds below, their
  tests); the tool deletes nothing.
  Evidence contract: value = `verdict`, the reader count, `live_writes` and `populated_writes` per
  key (both over `live_write` snapshots only; degraded republishes are counted apart in
  `degraded_states`; counts only, the tool never prints unit names); source = the tool's
  JSON over the main checkout's `data/tft_live_data.json` plus its tracked-source census; timestamp
  = `read_at`, the last live write's `mtime_iso` and `stage_round`, and the queue id from the LCU
  gameflow session; predicate = this paragraph.
  SUBSTITUTION check (answer it in the tick line): the census is the compute half, it is headless,
  and it is what decides the delete; the live half answers only whether the RUNNING writer puts the
  three keys into the FILE, which the census cannot. The facade seed (`coaches/tft_coach.py`
  `_default_payloads`) and the policy placeholder (`core/feature_policy.py`
  `_TFT_LIVE_DISABLED_PAYLOAD`) carry the same three keys, so a read of the file alone is NOT a live
  write: only a snapshot holding `degraded` counts (`_write` and `_publish_degraded` set it, and
  `tests/test_gated_tft_live_keys.py` pins that no seed literal carries it). A hand-edited file with
  `degraded` false would satisfy the live half; the `--since` window, the write cadence (about one a
  minute in the 2026-10-25 logs) and the `stage_round` values the predicate already requires to
  advance are the cross-check, so record all three.
  Census blind spots (recorded, not fixed): a key built at run time, a key inside a longer string or
  f-string, and a whole-dict pass-through are invisible to the Python scan, which matches only a
  string literal that IS the key. `agents/agent2_backend/file_ingest.py` broadcasts the whole file
  on WS /push to `web/js/main.js`, so the JS / TS / HTML word scan is the only guard on that path,
  and an out-of-tree WS client is not scanned at all. Hits in the writer module and in the upstream
  vision-reply producers (`tft/tft_vision_reader.py`, `vision_server/_inference.py`,
  `core/vision_routing.py`) are listed, never counted: the row's own claim is that they read the
  in-memory vision dict. Today only `tft/tft_vision_reader.py` produces such hits; the other two name
  the keys inside longer prompt / docstring text, which the scan does not see.
  Idle baseline (2026-10-27 local, no game, lane/gated HEAD): INCOMPLETE, exit 1; census 1133
  files, 17 key hits, 0 readers, 9 in the writer, 4 `sequence` (the writer's sanitizer loop and
  `tft/tft_vision_reader.py` `_STR_LIST_FIELDS`, both upstream of the file); the live file is a
  `seed` (mtime 2026-10-25 17:05 local, the game-end reset) with all three keys present and none
  filled. Prior partial evidence, not a drain: `logs/2026-10-25.log.2` (10:46 to 13:30 local) and
  `.log.1` (13:32 to 17:04 local) hold 124 `rc.tft.live` DEBUG `Live analysis written` lines across
  that day's TFT games, so `_write` ran live; its `out` key literal last changed 2026-04-26 and the
  `out["degraded"]` store landed 2026-08-31, both before those games. That the keys reached the file
  is an inference, not an observed value, and no QA recorder run under `ops/runtime/tft_qa/`
  snapshots this file.
  Reclassification PROPOSAL (for a human; not a move): the delete decision rests on the census,
  which needs no game; only the "running writer emits them" half does. Reverses if: the `_write`
  literal, the `degraded` discriminator or a seed literal changes (the source-pin tests in
  `tests/test_gated_tft_live_keys.py` fail first), or a reader of any of the three keys lands.
- **TFT-15 READY (lane 9, s144 cycle 6, PREP only, no game up; NOT ticked)** (`docs/TFT_PROGRAM.md`
  section 7 slice TFT-15, section 6 paths A / B; listed here in s144 because no gate above covers a
  TFT game; TFT-14 waits on it) Two unknowns: the team-code FORMAT (can path A copy a code with no
  LCU write?) and whether a planner change PROPAGATES between the client planner and the in-game
  planner mid-match. Findings go to the gitignored `ops/runtime/tft_qa/PLANNER_PROBE.md` (TFT-15's
  only file); this row holds the commands, predicates and the tick line. One read-only tool,
  `tools/gated_tft15_planner.py` (LCU GETs only through RC's own `lcu/lcu_client.py`, pinned by
  `tests/test_gated_tft15_planner.py`; prints no team title, no team id and no TFT.log line text).
  Half 1, FORMAT (any lobby or match, operator present): the operator builds a planner team whose
  units they name, takes its code from the client planner's own copy / share control (an in-client
  act, no RC write) and runs `python tools/gated_tft15_planner.py decode "<code>" --expect
  "<Unit1>,<Unit2>,..." --json`, once for a one-unit team and once for a team of 3 or more units in
  a known order. If the client shows no copy control, the code needs the write-shaped `POST
  /v1/sets/{set}/team-code/{team}`, which is path B's explicit-click rule (an attended session, never
  a lane): record which. Fields: `verdict`, `h1.prefix`, `h1.tail`, `slot_count`, `filled`, `units`,
  `unknown_codes`, `round_trip`, `empty_between`, `order_matches`. Candidate grammar H1, stated
  before any code is read: a 2-character prefix, 3-hex-digit slots (`000` = empty, filled slots
  first), an optional `TFTSet<N>` tail. Its one measured basis is the legacy Set 17 probe reading
  `code[2:5]` of a one-unit team as that unit's `team_planner_code` in hex
  (`scripts/discover_champion_codes.py` `legacy_probe`, source-pinned); every Set 18 code (1001 to
  1085) fits 3 hex digits. Predicate: PASS iff H1 parses the code, every filled slot maps to a unit
  in `data/meta/tft_set<N>_champion_codes.json`, re-encoding gives the code back and the units equal
  `--expect` as a multiset; FAIL iff any of those breaks. Close half 1 with PASS on both codes (H1 is
  the offline encoder; write the prefix value, slot count, tail and `order_matches` into
  PLANNER_PROBE.md) or with the refuting field ("no offline encoder under H1"; path A falls back as
  section 6 says).
  Half 2, PROPAGATION (a real TFT match; the game-up discriminator is RM-292 (c)'s: `tasklist` shows
  `TFTClient-Win64-Shipping.exe` while `/api/state` `lcu.phase` is `InProgress`). Game-to-client
  needs no RC write: `python tools/gated_tft15_planner.py snapshot --since <game start, local ISO>
  --json > <main>/ops/runtime/tft_qa/planner_before.json`, the operator adds or removes one unit of
  one team in the IN-GAME planner (note the local time), wait 60 s, the same command into
  `planner_after.json`, then `python tools/gated_tft15_planner.py diff <before> <after> --direction
  game-to-lcu --edit-at <the noted edit time, local ISO> --json`. Client-to-game needs a client
  planner write mid-match: that is path B's write, made only in an attended session with the
  operator present (never by a lane); bracket it with the same two snapshots and `--direction
  lcu-to-game --edit-at <the write time>`, then the operator reopens the in-game planner and says
  whether the changed team shows. Fields: `verdict`, `why`, `changes[].change` / `units_before` /
  `units_after`, `new_log_events[].kind` / `iso` (UTC), `edit_at`, `phase_before`, `phase_after`,
  and the snapshot `planner.dirty_shape`. `diff` says INCOMPLETE (never `NO_CHANGE`) unless both
  snapshots read a recognised planner shape holding at least one team and were both taken
  `InProgress`, and for game-to-client unless `--edit-at` is given. Predicate: game-to-client
  PROPAGATES iff `diff` says `PROPAGATED_LOG` (the client planner changed and a `data_saved` line
  follows BEFORE and the edit time) AND `changes[]` is exactly one `edited` team whose
  `units_before` / `units_after` differ by the one unit the operator added or removed (any other
  change: record it, close nothing); NOT MID-MATCH iff `NO_CHANGE` holds at 60 s and again on a
  third snapshot at 180 s; `NO_LOG_SIGNAL` is recorded as is (the change came another way);
  INCOMPLETE closes nothing (record `why`). Client-to-game PROPAGATES iff the
  operator sees the changed team in the in-game planner; DOES NOT iff they see the old team after
  reopening it - then path B is lobby-only (section 6). `PROPAGATED_LOG` (a `data_received` after
  BEFORE) supports that call and never replaces it.
  Evidence contract: value = the verdicts and fields above plus the operator's in-game observation
  (team shown: new or old); source = the tool's JSON over `GET /lol-tft-team-planner/v1/sets/dirty`,
  `/v1/previous-context`, `/lol-gameflow/v1/gameflow-phase` and the allowlisted
  `TFTPlannerSubsystem` lines of the client's `TFT.log`; timestamp = each snapshot's `read_at`, the
  log events' UTC `iso`, `edit_at` and `phase_before` / `phase_after` (the tool reads no queue id;
  TFT-15 does not depend on the queue, so record it only if the drain already has it); predicate =
  this paragraph. The codes themselves and the team titles stay in the gitignored notes,
  never in a tracked file.
  SUBSTITUTION check (answer it in the tick line): the format half is NOT a substitution only
  because its input is a code the CLIENT produced; the synthetic codes in the test file prove the
  parser, never the grammar. For propagation, the diff shows only that the CLIENT planner changed,
  and a log line only that the game's planner subsystem loaded or saved; neither shows the in-game
  planner RENDERED the team, so only the operator's look closes client-to-game. `data_saved` lines
  appear in matches with no RC planner write (baseline below), so a save that does not follow the
  operator's noted edit is no signal.
  Idle baseline (2026-10-27 local, no game, client closed): `snapshot` NO_LCU, exit 1. The TFT.log
  scan over the seven 2026-10-25 files (the live file and six backups): `data_received` exactly 1
  per file (the match-start load, as section 6 says), `set_loaded` 1 per file (`TFTSet18` in the
  live file), `data_saved` 7, 7, 0, 0, 5, 3, 2 with `prefs_saved` equal to it in each file - the
  same counts as a raw grep of those files (positive control). The `/v1/sets/dirty` shape is
  unmeasured here (the LCU TFT inventory names champions[].championId, title, id and reminder, 40
  TFTSet18 teams); the summary accepts a per-set list, a per-set `teams` list or a flat list and
  says `dirty_shape: unrecognised` otherwise, so the first drain records the real shape. Reverses
  if: the legacy probe's `code[2:5]` read changes (the source pin fails first), a fresh match's
  TFT.log scan finds no `data_received` (the line wording moved), or TFT-14 lands.

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
  **NOT TRUE AT HEAD (lane 9 s133, re-measured 2026-10-24 for ARAM in cycle 3 and 2026-10-25 for
  Arena in cycle 6):** today there is no replay input for either flag. No retained day log has an
  `ARAM Haiku raw` line or any Arena coach line, and `data/arena_coach_shadow.jsonl` lacks the
  signature fields. So the live G3-12 / G5-06 CHECKs are the path until a fresh game logs input. This
  entry stays because a future corpus could satisfy it.
- **CANDIDATE (lane 9 s133 cycle 6, 2026-10-25; a human moves it, the lane does not):** G5-08 Crown of
  the Shattered Queen 444644 Arena magnitude. The 2026-10-24 Settled amendment (RM-808: DDragon prose
  first, CommunityDragon second, Meraki last) decides which source DS seeds from (DDragon 90%), not the
  in-game value this row asks for. The headless answer is CommunityDragon 16.21 game data for 444644
  (RM-871 step 1, mandatory), and the row moves only if that data states 90%. The tooltip CHECK in the
  G5-08 row reads the same client string as DDragon, so it is a cross-check, not proof.
- **CANDIDATE (lane 9 s144 cycle 78, 2026-11-06, RM-1667; a human moves it, the lane does not):**
  G4-27 R47 PGR child-panel capture. PGR renders from stored post-game data with no game up, and the
  only R47 pixel delta (`.pld-aug-name` 13px -> 16px inside `@media (max-width: 900px)`) shows only
  at the companion's compact 380 px preset. The anytime CHECK and its predicate are in the G4-27 row.
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
- Stale-hash citations to correct OUTSIDE append-only ledgers: item 508 build-order report `5db73817`
  -> `7ee593d3`; QA4 chips `03c8d49b` -> `77f0e494`; HZ-B `--static` `035d7ff7` -> `d528f6cb`; HZ-B
  regen `07cb6365` -> `559245a0`; E12 `109c80f0` -> `4f19d305` + `16adb6cb`; G4-boots `54d0706a` ->
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
7. **[DONE 2026-11-08, RM-713 (a)]** `docs/_archive/2026-05/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md` (2026-05-25) - one-shot probe, complete; moved out of tools/.
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
  `https://rc-host:8888/?overlay=1` (not a fixture, not 127.0.0.1 - the rc-host origin so wss://
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

- 2026-06-20 RC2 rc-shell standalone-app live session (code fixes shipped `bc4625d8` + `30e2d3fa`;
  runtime recovery). LIVE-VERIFY OWED (needs a live ARAM/any lobby): `lcu.lobby.members[]` must render
  in the rc-shell PRE-GAME LOBBY panel (YOUR MAINS / PARTY / MY TOP-8). The agent DOES forward members[]
  (`tools/lcu_agent.py:706-717`) but the operator saw empty members during a live lobby; could NOT
  reproduce after they left it (LCU phase=None). Next lobby: confirm the panels populate; if empty,
  capture the agent's live `/lol-lobby/v2/lobby` read + `_slim_lobby_member` output to find why members
  drop (suspect event-mode 2400 member shape OR the post-RC-restart stale-agent window). ALSO eyeball
  the overlay surface gate (`bc4625d8`): companion dashboard shows in the lobby/champ-select and flips to
  the lean HUD only once `liveclient` populates (a real game starts). Separately tracked (NOT live-gated,
  headless next session): agent restart-resilience - RC-LCUAgent/Hotkey/Relay must survive boot + auto-
  resync after an RC restart (the systemic root cause of the whole session's cascade). NOT a DS seam.

- 2026-06-20 RC2 E-batch E12-L2 + E7a (RC-side, NOT DS seams; shipped code-safe, no flip flag).
  E7a (`eb361c27`) tightens the RC-LCUAgent bench-swap queue-drain (fast 0.1s re-poll on a
  latency-sensitive cmd vs the 0.5s idle wait). LIVE EYEBALL OWED: in a real ARAM champ-select,
  click a bench champ and confirm the swap registers visibly faster - cannot be exercised offline
  (needs a live LCU champ-select with a populated bench). The RC-LCUAgent runs as an ONLOGON task
  with no restart_trigger, so a code refresh needs `taskkill /F` the agent pid + `Start-ScheduledTask
  RC-LCUAgent`. E12-L2 (`16adb6cb`) memoizes RuneWriter's lobby gameMode per champ-select session.
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
- 2026-06-17 HZU1 (no ENGINE bump - tooling + docs; the item-level CODE shipped item 457 @ccfd2e18):
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
- 2026-06-20 RC2 P3.3 overlay pulse-rationing flip (UI behavior, NOT a DS seam; `7f9b274c` shipped
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
- 2026-06-20 RC2 P4.1 DPI/resolution overlay sizing live eyeball (UI geometry, NOT a DS seam; `1822e22f`
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
  `netsh interface portproxy show all` FIRST per `project_iphlpsvc_portproxy_2999` - that is a self-loop
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

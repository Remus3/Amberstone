# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) archived. Only the last 3 sessions kept here.

---

# 2026-07-04 late (HOME round-2 SHIPPED - E11 home slice + mode tabs + no-reflow; LEDGER 768)

Round-2 on HOME done end-to-end (operator interactive, 7 commits pushed `e7ab8e86..ae676f97`, CI green):
Hextech cohesion (single focal Tonight's Pick hx-card, flat hero, stack reorder, Recent/Week compaction,
hx-card-head primitive), SR/ARAM/ARENA MODE TABS (`/api/home/summary?mode=`; modes never taint each other),
mode-aware L20 (ARAM strip hidden - rewind has 0 Mayhem rows - AUTO-reintroduces on a queue-2400 probe),
RECENT 3 + WEEK 3 all tabs (pick pool = FULL week aggregate, decoupled from the display cap), whole page
inside the 920x1280 fold (chips in the hero right zone), and the NO-REFLOW principle applied 3x (reserved
L20 slot / tip "-" sentinels / one-line headline; hero pinned ~218px across all 4 tabs; NEW memory
feedback_no_reflow_on_data_absence). 5-phase audit SHIP (2 MUST-FIX in-slice). Full suite 10248 + snap 317.
Details: LEDGER 768 + docs/qa/HOME_QA_2026-07-04.md section E.

CARRY-OVER (next session or the one after):
- HEADER ROW 2 removal IN FLIGHT: operator ruled the shared header's 2nd row drops on ALL pages +
  contents emptied (dead in-game pills; trigger_pill 2Hz poll dies with it). WIP-snapshot commit sits on
  branch `worktree-agent-a218a07c4022c7923` (worktree still on disk, 17 files, NOT test-verified).
  FINISH: complete test updates, run FULL tests/snapshot_panels/, verify overlay=1 unaffected, merge,
  re-render 2-3 pages, push. Do NOT merge the WIP blind.
- OPEN operator question: Tonight's Pick >=2-game floor? (pick now scouts every week champ incl 1-game).
- Backfill chips still owed (items[] pre-ingest + queue_id/mode_subtype) - rebase onto ae676f97.
- E11 remaining surfaces (non-home) still OPEN in RC2_PLAN.

NEXT (operator-declared): live-gated items via ARAM Mayhem - /live-gated-drain against
docs/LIVE_GAME_GATED_SYNC.md while the operator plays (they were QUEUING at wrap: mode aram, Matchmaking).

---

# 2026-07-04 (Operator HOME-page QA rework + companion 920x1280 + daf09498 cleanup; LEDGER 767)

Ran the operator per-page UI-QA method on HOME (6-mapper MAP -> 4 AskUserQuestion advocate rounds ->
one worktree slice + verifier + 5-phase audit SHIP + ui_recon both widths). Rulings in
docs/qa/HOME_QA_2026-07-04.md. SURFACE VALIDATED: Home renders in the rc-shell COMPANION window
(mainWindow, plain :8888, out-of-game; main.js:523), NOT the ?overlay=1 HUD (pins active-match,
main.js:927-929); primary viewport now 920x1280 portrait. Home slice f7951769 (net -982): hero trims
(greeting/Season-WR/Gold-chip cut, momentum gated >=3 games), 6-tile portrait launcher restored (Find
Match tile dropped, CTA covers), Recent-5 W/L stripe (wired the unused `win` field; grade->badge),
dropped Advisories, REMOVED Weekly Digest + Last Build, deleted dead services render +
.home-trends/.home-grid CSS; backend stripped services/weekly_digest/last_build/season_wr (home-only).
Resize f71aee0d: config.js standard 923x1316->920x1280 + companion tests + recon (rc-shell 309 +
companion 11 pass; already-sized window keeps its saved size -> restart rc-shell + Ctrl+2 Standard to
adopt). Cleanup 7e101de3: completed daf09498 (deleted ban_suggest_toggle.css but left 2 token tests
pinning it - CI-hidden red, surfaced only in the /done full-suite; watch the exit-code trap - the bg
bash reported outer-shell exit 0 while pytest exited 1). Pushed f9259068..f71aee0d, CI green.

ARCH DECISION (operator): web/+dashboard/ retired as standalone VISUALS; all UI/UX -> the companion +
in-game overlays (both rc-shell windows that render web/). rc-shell KEPT (it IS the companion+overlay).
Path = #1-aggressive-finish (RC2 E11 Hextech reskin + dead-surface prune), NOT #2 native rebuild (RC2
~90% built; a rewrite = months + parity gap).

NEXT: HOME round-2 - operator says "feels disjointed still" -> a ui/ux agent pass + the RC2 E11 Hextech
reskin (docs/RC2_PLAN.md E11, greenlit+swarm-mapped). Deferred from HOME_QA_2026-07-04.md: This-Week
visibility (buried under Recent-5 in the portrait stack), Recent-5 depth, 1-col stack order,
Recent-meta density, dual-grade repetition. Also owed: the 2 backfill CHIPS (items[] pre-ingest +
queue_id/mode_subtype) rebase onto this slice. DO NOT redo: Home round-1 shipped (f7951769); companion
is 920x1280; ban_suggest cleanup done.

---

# 2026-07-03 (Operator champ-select QA rework + per-mode panel visibility; LEDGER 765)

Session pivot: /orchestrated-run bootstrap seeded the ORUN1-5 curated queue + relaunched the
gemini loop (`7ff688b0`), then the operator halted it (AHK never typed; STOP + AHK killed) and
ran an INTERACTIVE 4-round QA of the champ-select page with Claude as advocate. All rulings in
docs/qa/CHAMP_SELECT_QA_2026-07-03.md - the ORUN rows remain OPEN in ORCHESTRATION_PLAN for a
future loop run. Shipped (4 verifier-CONFIRMED worktree slices + sole-merge + 5-phase audit + 2
MUST-FIX fixed in-slice + 3 cross-slice test alignments): champ-select cut 7 surfaces (ghost
bans/pickorder wrappers + dead dual-score toggle, mood system ENTIRELY incl backend, YOUR-RECORD
path, ally-roles mirror, cc-pairing card, cooldown-watch card, GPI radar), moved DS
profile/knobs/statcheck to the active-match BUILD pane (CS3 family), merged build chooser+order
(one PUSH), compacted summ spells (2+EDIT), clustered CC-EHP/CC-pressure/team-damage into a
collapsed TEAM ANALYSIS block w/ deterministic verdict header, fixed queue-2400 KIWI/aram vocab
(backend alias map + frontend canonical), flipped RC_CAPGAP_SURFACE default ON (live-verified
capability_gap dict on /api/ds-preview post-restart pid 3644). Panel visibility: per-mode
contexts (in-game-sr/aram/arena/tft + out-game, brawl->sr), 17-panel registry, tabbed settings
card, legacy-blob migration. Suite 10566/2skip green; node 25/0. FOLLOW-UP CHIPS BOTH LANDED (LEDGER 766):
orphan cleanup `daf09498` (deleted cooldown_watch.js/ban_suggest_toggle.js/.css + buildOrderCardHtml
export; backends kept; test files -> deletion guards) + `#csv-picks-target` mode-gate `c80c1d0d`
(pre-existing bug: item-200 relocation left the SR-only PICK placeholder outside the .csv-card-pickban
gate -> lingered in ARAM/Arena; one CSS rule + computed-display test, RED-proven, verifier CONFIRM).
Both CI green. NEXT: run the SAME operator-QA method (6-mapper workflow -> AskUserQuestion advocate
rounds -> worktree slices + verifier + 5-phase audit) on the HOME page. capgap in-game eyeball stays
B37 (default-ON). The gemini loop ORUN1-5 rows remain OPEN in ORCHESTRATION_PLAN for a future relaunch
(controller/AHK are stopped; STOP file present).

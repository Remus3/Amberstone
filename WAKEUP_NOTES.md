# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-29e - RM-124 deterministic wave/cannon clock BUILT + GATED-OFF (Tier-1, no engine bump).

**Commits `266c1fac` (feature) + `965d829d` (tracker sync), both pushed + CI-green.**
Pure `wave_callout()` beside `recall_callout` in `core/event_callouts.py`: anchors on the live
`MinionsSpawning` EventTime, walks the wave cadence to the next cannon, returns a
`{tag,line,eta_s,kind=wave}` callout. Transport mirrors `inhib_events` - a 4th `minion_events`
extract in `dashboard/_liveclient.py` + gs pass-through in `dashboard/_deterministic_coaching.py`.
Renders on the GENERIC `web/js/panels/callouts.js` sink -> ZERO JS change.

Key decisions:
- Corrected the wakeup/teardown: it renders on `callouts.js` NOT `objective_chips.js`, and it does
  NOT light the `next.js:16-83` 3-lane per-lane % UI (that is the data-blocked STATE machine).
- Gated OFF (`enable_wave` default False, env `RC_WAVE_CALLOUT`) because cadence constants are
  provisional and NO live SR game was available to validate. `/api/state` byte-identical today.
- No backfill possible (pure live-compute). RED-first TDD: `tests/test_event_callouts_wave_rm124.py`
  8 cases. Verify this run: event_callouts 88, det_coaching/next_callout 80, targeted slice 147 green.

NEXT / do-NOT-redo:
- RM-124 is BUILT - do NOT rebuild it. The ONLY remaining task is gated item **G2-39** in
  `docs/LIVE_GAME_GATED_SYNC.md`: validate the cadence against one real SR game, correct the
  provisional constants if they miss the observed cannon arrivals, THEN flip `RC_WAVE_CALLOUT=1`.
- Follow-on F2 (CS efficiency curve, `core/lead_projection.py:57` flat 8.0) is unblocked once F1 flips.

---

# 2026-07-29d - RM-123 melee/ranged split reconciliation SHIPPED (ENGINE 1.263.0).

**Tier-2 DS: engine EHP-math change, ENGINE 1.262.0 -> 1.263.0, 7 doc anchors, build-table
regen, Share resync (516 files), DS :8893 restarted -> 1.263.0. Commits `8f67f810` (fix) +
docs sync. Full dual suite green: 24246 passed / 106 skipped / 7071 subtests. LEDGER 1109.**

Picked the NOW-lane RM-123 (first strong candidate). Root cause was WIDER than the filing
(named 2 sites): one boolean fact (melee vs ranged) was a magic base-attackrange threshold in
SEVEN classifier sites across three packages - two values (250 in `ehp._is_ranged`,
`rank._champion_is_melee`, `coaches/loadout_resolver`, `tools/hotfix_ranged_only_melee_loadouts`;
350 in `burst`/`dps`) and three operators (`>`, `<`, `<=`). 173-roster scan: the ONLY champs
in the 250 < ar <= 350 band are Rakan 300 + Lillia 325 (melee, wrongly ranged at 250) and Urgot
350 (ranged, wrongly melee under burst strict `>`). Canonical rule, correct for all 173:
**ranged iff base attackrange >= 350.0**. New leaf `agents/daemon_slayer/_melee_ranged.py`
single-sources it; all 7 sites route through `attackrange_is_ranged()`.

**Process win:** the dual suite caught 3 cross-package siblings (loadout_resolver, hotfix tool,
gate test) the engine-package grep missed - the `<=` operator + ceiling-bump-to-350 made Urgot
read melee. Fixed to the strict predicate. TDD: failing repro first; corrected two tests that
pinned the old 250. No build/loadout backfill needed (no melee champ ever carried Runaan's).

**Do NOT redo:** RM-123 is CLOSED. The split is now single-sourced - never re-introduce a
second threshold or a `<=` boundary (it breaks Urgot at exactly 350). Upstream still do-not-refresh
(ddragon 16.15.1 but meraki/cdragon 16.14). Next candidate: RM-124 (deterministic wave/cannon
clock, Tier-1, no ENGINE bump; full teardown `docs/COMPETITOR_LIFT_2026-07-28.md`).

---

# 2026-07-29c - ROADMAP + BACKLOG reconciliation: relocated done/shipped items, kept fences.

**Read-only-ish / docs session. Tier-0: NO engine edit, no ENGINE bump, no DS bounce, no Share, no restart.** `50e621a7`.

Operator ask: check upstream, then move done/completed/shipped items out of the two live
trackers. Upstream re-checked at start - NO drift (ddragon 16.15.1, meraki 25.15, cdragon
16.14 ok, sentinel advanced). Two read-only Explore agents built a ground-truth-verified
relocation plan (all cited SHAs/LEDGER numbers resolve; 0 UNVERIFIED).

**BACKLOG.md 71350 -> 59699B:** removed 9 fully-shipped rows already in LEDGER (R129 XOR +
superseded original, R67 Terminus SR + superseded original, draft-score, session-hygiene,
playstyle-labels, overlay-HUD-microlifts, patch-impact); trimmed 3 KEEP-RESIDUAL rows to
their open tails (boot-utility kite/poke, radar CHI-bands, R190 kit-pen d/e); trimmed 2
do-not-re-pitch fences (champ-select brief FLIP, F1/F5) to thin pointers.

**ROADMAP.md 73097 -> 72143B (under 80KB budget):** relocated the 2 remaining full-narrative
closed RM-04 sub-bullets (RC-2 follow-on, A-27b Golden Spatula) to fences, keeping the
base-id mirror trap + ID-SUFFIX-not-name lessons.

**Decision logged:** RM-106b left in place - labelled OPEN, not relocated without operator
call. CI docs-guards green. Do NOT re-relocate: ROADMAP was already pruned 4x, near its floor.

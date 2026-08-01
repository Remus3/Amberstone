# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-01 - Gemini decommissioned, tri-project headless contract, N=3 round closed

6 commits `15ddff90..8450dd2b`, all pushed. RC-side only; DS untouched (no Share sync).

**Shipped**
- `c926470a` port blocks folded - LW 8900-8919 and RM 8770-8789 both CONFIRMED in writing.
  Adopted LW's `next_free()` with a guard LW's version lacks: RC may only answer for its OWN
  blocks - a confident wrong number handed to a sibling is worse than no answer.
- `aee3bb96` + `13350e43` GEMINI FULLY DECOMMISSIONED (operator directive). Backend, failover,
  exhaustion matcher, ceiling accounting, 2 ps1 wrappers, 3 docs, the scheduled task: gone.
  `gemini()` -> `adjudicate()`, `/gemini-headless-upgrade` -> `/directed-headless-upgrade`.
- `666d2547` + `8b292a98` N=3 coordinated round with LW and RM; all three trees hash equal on
  `slots.py` (`5297f2d0...1cb0a6`).
- `8450dd2b` Claude co-author trailer swept - `gist_share_sync.py` was still EMITTING it into a
  SEPARATE repo the commit-msg hook does not cover.
- NEW: `docs/CONCURRENT_HEADLESS_CONTRACT.md` - portable 3-project headless contract.

**Decisions worth keeping**
- Removing `ceiling_usd` was REQUIRED, not tidy: with the metered vendor gone the only spend
  left was Claude's, so the check would have inverted into a cap on exactly the spend policy
  says is uncapped.
- A cross-repo equality guard makes an atomic change IMPOSSIBLE - whoever moves first is red.
  Rule 4.2a in the contract. Deciding rule: whoever is red should be the party NOT shipping.
- Contract section 10 was WRONG about the cause of the hooks finding: it is settings DISCOVERY
  (cwd), not headlessness. Verified locally - `.claude/` is gitignored, so every lane worktree
  has no settings.json and runs with ZERO agent hooks.
- Removed dangling machine-wide `"model": "rc-main"` from user settings (backup kept). It broke
  headless for EVERY project, and RC's earlier "Not logged in" reading was wrong - `claude -p`
  works now. A headless launch has several independent preconditions that all fail as "the run
  did nothing"; do not accept the first plausible cause.

**Do NOT redo**
- Gemini is gone; a decommission-guard test fails if any of the 8 deleted names return.
- N=3 and the slots re-pin are APPLIED on all three trees. Do not re-negotiate.
- `winmutex.py` GEMINI_MUTEX constant STAYS - shared byte-identical, LW has a live consumer.
- LW owns the hook probe. Do not duplicate it.

**Next:** link-ingest Phase 2. `Desktop/First-Pass.md` has 147 scored rows and 155 operator
`**!=` notes ALREADY PRESENT - the gate the memory calls "awaiting operator notes" is CLEARED.

**Loose end (not blocking):** `NIMBLE_API_KEY` sits in plaintext in user-level
`.claude/settings.json` env. Worth relocating; not touched this session.

---

# 2026-08-01a - LANE-RESEARCH REFILL (headless lane 5): 5 rows filed RM-130..RM-134, one NEW drift-guard gap.

**MERGE NOTE (added by the merger, 2026-08-01):** the five rows this run filed were authored
as RM-129..RM-133 and were RENUMBERED +1 to **RM-130..RM-134** at merge, because a DS
port-block-migration RM-129 landed on `main` while this lane was running - the lane branched
before it existed. Its LEDGER entry likewise moved 1142 -> **1143**. Whichever lands second
renumbers. The ids above are already corrected; `docs/DS_SWEEP_TRACKER.md` records the shift.

## Start here next session

REFILL pass on `lane/research` (Mission Control lane 5), docs-only, no live game
(`/api/state` `mode_key=client`, `liveclient` empty). Branch is READY TO MERGE (Tier-0
docs; no engine, no Share, no restart) - leave the merge to the merger, do not merge from
the worktree. Full detail in LEDGER 1142.

## What shipped (all docs, all PROBED this run)

- **RM-131 filed (NEW gap, flagship)** - 101.qq.com duo-synergy has NO drift guard while
  ddragon / meraki / cdragon / wiki all do. `tools/upstream_drift_check.py` tracks exactly 3
  signals and carries zero qq reference; `core/synergy_external_source.py:33` fetches the
  Tencent endpoint and fails SILENTLY back to the frozen May-25 seed. Acceptance = a 4th
  `probe_qq_synergy()` + `test_upstream_drift_qq_synergy_probe`. Lane 6/7, Tier-1. Companion
  to RM-128.
- **RM-130 / RM-132 / RM-133 / RM-134** - promoted thin BACKLOG cites to well-formed,
  id-carrying, acceptance-bearing rows; each re-grepped live. Corrected one STALE cite
  (RM-133 Arena chip: `_csvArenaPaneHtml` is now at `web/js/panels/champ_select.js:3512`,
  not the filed `:931`).
- Registered RM-130..RM-134 in `docs/DS_SWEEP_TRACKER.md`; next free is now **RM-134**.

## Do NOT redo

- Drift-guard coverage for ddragon / meraki / cdragon / wiki is CLOSED-COMPLETE (all
  GUARDED with cited guards) - do NOT re-audit those four. Only 101.qq.com (RM-131) is open.
- SGP / Match-V5 drift guard was CONSIDERED and DECLINED (live-gated reachability, no
  hand-maintained mirror, official versioned API) - do NOT file it.
- Competitor-lift research stays RETIRED / drained 4x - not re-opened this run.
- Before taking a new RM id run the grep recipe in `DS_SWEEP_TRACKER.md` (next free RM-134).

## Next

Lanes have well-formed work waiting: RM-131 (lane 6/7, the drift probe), RM-130 + RM-132
(lane 7 ASCII / token hygiene), RM-133 (lane 4 Arena chip), RM-134 (lane 8 MC error scrub),
plus still-open RM-128 (lane 6/7) and the DS RM-118 4 wireable seams (lane 6).

---

# 2026-07-31f - LANE-RESEARCH REFILL (headless lane 5): 2 stale strikes, id-registry fix, cdragon catalog torn down.

## Start here next session

**A RESEARCH LANE IS RUNNING RIGHT NOW - it is real work, not a test artifact.** Its run_id is
the unhelpful string `probe` because the merger session fired it BY ACCIDENT while trying to
read the lane lock: `fire_lane` is the only lock-state call exposed, and it does not merely
read - it reclaims a stale lock and launches. It was left running deliberately (the standing
operator directive is to keep a lane running) rather than killed. Treat its output exactly like
this entry's: merge `lane/research` when it lands, never merge from the worktree. Probe with
`curl -s --ssl-no-revoke https://legion-rc:8895/api/loop-status` (NEVER `-k`). **Do NOT call
`fire_lane` just to read lane state** - that is exactly what caused this.

This was a REFILL pass on `lane/research` (Mission Control lane 5), docs-only, no live game.
MERGED to main 2026-08-01 by the merger session (the 2026-07-31e entry below, which fired
this lane and then wrapped). Tier-0 docs; no engine, no Share, no restart. Detail in LEDGER 1141.
The lane exited code=0 at 23:58 after a ~15 min run; the RECLAIMABLE lock seen the next morning
was the 05:57 reboot clearing pid 14692, NOT a crash - the work was committed and pushed first.

## What shipped (all docs)

- **RM-128 filed** (cdragon `queues.json` grounds the hand-maintained `core/queue_modes.py:28`
  map + a drift guard; ITEM-87 SAFE - `core/game_snapshot.py` detects by gameMode-STRING, never
  queueId). Acceptance: a test asserting every `QUEUE_ID_TO_MODE_KEY` id still exists in a fresh
  `queues.json` with a consistent `gameSelectModeGroup`. Lane 6 or 7, Tier-1.
- cdragon `lol-game-data` 7-file teardown filed in `BACKLOG.md` (F2/F3 trigger-gated, F4/F5
  deferred, F6/F7 REJECT-recorded). License cleared (Riot data, no copyleft).
- Struck the STALE DDragon 16.15.1 patch-refresh row (shipped 2026-07-30, item-1130 / `9df58480`;
  live `/health` = 16.15.1, worktree clean).
- Fixed the `docs/DS_SWEEP_TRACKER.md` "next free" pointer: was RM-119 (stale), now RM-129.
- Decided the `tft/` U+2192 ASCII row: 24 arrows, all display-only, STRIP-SAFE, acceptance-bearing.

## Do NOT redo

- Do NOT re-run the DDragon 16.15.1 patch refresh - it is DONE (item-1130). If you see fake
  ddragon suite failures, that is a NEW dirty MAIN tree per `reference_dirty_ddragon_tree_fakes_49_failures`,
  not this row.
- Competitor-lift research is RETIRED/drained 4x (ROADMAP RM-01) - the cdragon teardown was Riot
  DATA, not a competitor; do not treat it as re-opening that lane.
- Before taking a new RM id, run the grep recipe in `DS_SWEEP_TRACKER.md` - do NOT trust ROADMAP prose.

## Next

Lanes have well-formed work waiting: RM-128 (lane 6/7), the tft-arrow strip (lane 7), the six
stale-process restart-owner gaps (`BACKLOG.md`, lane 7), the DS RM-118 4 wireable seams (lane 6).

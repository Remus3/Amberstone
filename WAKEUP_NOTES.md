# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-01a - LANE-RESEARCH REFILL (headless lane 5): 5 rows filed RM-129..RM-133, one NEW drift-guard gap.

## Start here next session

REFILL pass on `lane/research` (Mission Control lane 5), docs-only, no live game
(`/api/state` `mode_key=client`, `liveclient` empty). Branch is READY TO MERGE (Tier-0
docs; no engine, no Share, no restart) - leave the merge to the merger, do not merge from
the worktree. Full detail in LEDGER 1142.

## What shipped (all docs, all PROBED this run)

- **RM-130 filed (NEW gap, flagship)** - 101.qq.com duo-synergy has NO drift guard while
  ddragon / meraki / cdragon / wiki all do. `tools/upstream_drift_check.py` tracks exactly 3
  signals and carries zero qq reference; `core/synergy_external_source.py:33` fetches the
  Tencent endpoint and fails SILENTLY back to the frozen May-25 seed. Acceptance = a 4th
  `probe_qq_synergy()` + `test_upstream_drift_qq_synergy_probe`. Lane 6/7, Tier-1. Companion
  to RM-128.
- **RM-129 / RM-131 / RM-132 / RM-133** - promoted thin BACKLOG cites to well-formed,
  id-carrying, acceptance-bearing rows; each re-grepped live. Corrected one STALE cite
  (RM-132 Arena chip: `_csvArenaPaneHtml` is now at `web/js/panels/champ_select.js:3512`,
  not the filed `:931`).
- Registered RM-129..RM-133 in `docs/DS_SWEEP_TRACKER.md`; next free is now **RM-134**.

## Do NOT redo

- Drift-guard coverage for ddragon / meraki / cdragon / wiki is CLOSED-COMPLETE (all
  GUARDED with cited guards) - do NOT re-audit those four. Only 101.qq.com (RM-130) is open.
- SGP / Match-V5 drift guard was CONSIDERED and DECLINED (live-gated reachability, no
  hand-maintained mirror, official versioned API) - do NOT file it.
- Competitor-lift research stays RETIRED / drained 4x - not re-opened this run.
- Before taking a new RM id run the grep recipe in `DS_SWEEP_TRACKER.md` (next free RM-134).

## Next

Lanes have well-formed work waiting: RM-130 (lane 6/7, the drift probe), RM-129 + RM-131
(lane 7 ASCII / token hygiene), RM-132 (lane 4 Arena chip), RM-133 (lane 8 MC error scrub),
plus still-open RM-128 (lane 6/7) and the DS RM-118 4 wireable seams (lane 6).

---

# 2026-07-31e - LANE-RESEARCH REFILL (headless lane 5): 2 stale strikes, id-registry fix, cdragon catalog torn down.

## Start here next session

This was a REFILL pass on `lane/research` (Mission Control lane 5), docs-only, no live game.
The branch is READY TO MERGE (Tier-0 docs; no engine, no Share, no restart) - leave the merge
to the merger, do not merge from the worktree. Full detail in LEDGER 1141.

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

---

# 2026-07-31d - MISSION CONTROL S10 SHIPPED + MERGED (decoupled from the dashboard).

## Start here next session

S10 is DONE and on `main`. Mission Control is its own process on `:8895` under the
`RC-MissionControl` scheduled task; the dashboard's copy is deleted, so
`/api/loop-status` and `/api/loop-control` 404 on `:8888` by design.

Shipped (9 tasks, 20 commits, merged fast-forward): `mc/` package + `mission_control.py`,
bearer-token auth that FAILS CLOSED, bind restricted to loopback + tailnet only,
`web/mc/` standalone asset tree, `dashboard/_matchers.py` (the split that keeps pydantic
out of the control plane), and the dashboard-side removal. Post-merge: token ACL locked
to SYSTEM + Administrators, plus two guard fixes (`ab3d8b0b`, `2a55f40f`).
Detail in LEDGER 1139 + 1140. Design history in `docs/MISSION_CONTROL_PLAN.md` "S10 as shipped".

## Do NOT redo

- **S10 is complete and merged.** Do not re-plan it, re-pitch a `/healthz` watcher, or
  "fix" the two scheduled-task triggers - the logon trigger plus a time-based repeating
  trigger is the working combination, proven by a real reboot AND a taskkill recovery at t+49s.
- **The SDD execution workspace under `.superpowers/sdd/` is deleted on purpose.** Git
  history + LEDGER 1139/1140 + the BACKLOG entries are the record. Do not hunt for it.
- **Tailscale IS installed and running** (`legion-rc` / `100.70.22.55`). A mid-session claim
  that it was absent was WRONG - three guessed `Test-Path` checks against a machine where
  `Get-Process` would have settled it in one call. Lesson appended to memory
  `feedback_verify_before_declare_broken`.
- **`ops/loop/control/STOP` holds a REAL operator halt** ("operator halt via LW session
  2026-07-28"). It survived the whole build untouched. Do not clear it as a test artifact.
- Lanes 7 and 8 have still never been fired. Deliberate; ask before firing.

## Next

Top open item is whatever `ROADMAP.md` carries as the next `[!]`. The highest-value S10
follow-up in `BACKLOG.md` is `dashboard/_errors.send_error` leaking `str(exc)[:200]` to
`:8895` via the imported loop routes - pre-existing on `:8888`, so not urgent, but it
collides with the CLAUDE.md no-raw-error-strings rule. An owed pixel-screenshot pass on
`https://legion-rc:8895/` is also logged (Browser pane would not composite frames this session).

---

# 2026-07-31c - MISSION CONTROL S8 + S9 (lanes 7-8 wired; the INTERRUPT tier).

## Start here next session

**S10 - DECOUPLE Mission Control from the RC dashboard** (operator directive, 2026-07-31):
own process + port + asset tree, reachable by IP, so a game-overlay or dashboard change
cannot affect the control plane. Full design-question list in `docs/MISSION_CONTROL_PLAN.md`
"S10"; ROADMAP carries it as the top `[!]`. Two things NOT to do casually: **auth becomes
load-bearing** (the trust model is still "local / tailnet only, single-operator" and S9 added
an action that KILLS PROCESSES), and **move the serving layer, not the logic** (`ops/loop/*`
stays put - do not fork a second copy). The mkcert SAN list decides which IPs validate
(`tools/regen_rc_cert.ps1`), so a bare IP needs a cert regen, not just a firewall rule.

**Owed first:** `MEMORY.md` is 21.4 KB against a 24.4 KB read limit and a hook is asking for
compaction (`anthropic-skills:consolidate-memory`). Deferred twice now; it should lead.

## What shipped

- **S8 `97c74550`** - `tools/headless-repo.md` (BREADTH: restructure/clean/modularize) and
  `tools/headless-true-audit.md` (DEPTH: one file at a time, rewrite + harden), authored by
  parallel agents, mirrored to `.claude/commands/`, wired into `LANE_COMMANDS`. All six lanes
  startable; the panel derives `wired` from that map so it lit them up with no client change.
- **S9 `97c74550`** - `ops/loop/interrupt.py` + `interrupt_preview` / `interrupt` route
  actions + the panel block. `preview` fingerprints the exact victim set (pid AND process
  START TIME) and `execute` re-probes and REFUSES on mismatch. Descendants are victims too,
  reaped deepest-first; `taskkill` runs WITHOUT `/T`.
- **`79cdd590`** - an INTERRUPT audit row is no longer counted as pending guidance.

## The finding worth carrying forward

**Two defects passed the whole suite, my own mutation tests, and the source-contract tests -
and died on the first real click.** `mk` is a function-LOCAL const, so at module scope it is
a ReferenceError: the victim list never rendered while the armed button still read
"Confirm INTERRUPT - kill 3". Then `_mcArm.confirm()` notifies SYNCHRONOUSLY, the repaint
clears the fingerprint, and the POST went out fingerprint-less (failed SAFE, but could never
kill). Both are about a BINDING'S LIFETIME, which a source-literal test cannot see. Mutation
testing gave false confidence because every mutant of the WRITTEN property was caught - the
written property was not the broken one. Keep the live-audit ritual mandatory.

## Do NOT redo

- S1-S9 are shipped and CI-green. Do not rebuild the lock, idempotency table, intent
  consumer, panel, launcher, lane docs, steer channel, or the INTERRUPT tier.
- **Lanes 7 and 8 have never been FIRED.** That is deliberate - the plan gates both on
  operator sign-off and a fire starts a real autonomous worker against the repo. The launch
  path is proven structurally (worktree + branch + prompt-inside-checkout, verified with real
  `git worktree add`), so do not "fix" it; just ask before firing.
- Never edit `ops/loop/slots.py` or `ops/loop/winmutex.py` (byte-identical-by-contract).

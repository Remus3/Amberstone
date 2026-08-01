# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-31e - DESKTOP INGEST PHASE 1 (12 files classified) + research lane FIRED.

## Start here next session

The research lane is RUNNING headless (pid 14692 shell / claude.exe 18400, run_id
`ingest-580bb7d6`, worktree `C:
c-worktrees
c-lane-research`, log
`ops/loop/reports/lane_research_ingest-580bb7d6.log`). Check it before firing anything -
lanes are mutually exclusive on one lock. Status: `curl -s --ssl-no-revoke
https://legion-rc:8895/api/loop-status` (NEVER `-k`; mkcert CA has no CRL/OCSP).

**The remaining ingest work is RM-127**, and its two input files were deliberately LEFT on
the Desktop because the row cites them as its working input: `First-Pass.md` (105 KB, 155
operator note pairs) and `First-Pass-Addendum.md` (13 KB). Everything else is in
`Desktop/_ingested/` (10 files, reversible - the operator deletes that folder themselves).

## What shipped (`7cd9a812`, Tier-0 docs only)

All 12 Desktop planning files classified against ground truth; **zero duplicates filed**.

- **RM-121 CLOSED + relocated.** It read "items 1-3 DONE, two files left" for three days
  after LEDGER 1094 closed item 4 - the exact stale-ROADMAP class LEDGER 1093 named
  ("the stale artifact was not the digest, it was ROADMAP.md"). BOTH stale copies fixed
  (ROADMAP.md pointer + the `ROADMAP_HISTORY.md:28` copy), and the authoritative R217
  narrative retagged off `[WIP]`. That relocation also cleared a live drift_guard breach:
  the RM-127 addition took ROADMAP to 91 pct of budget, relocation brought it to 88.8.
- **RM-127 FILED - CCR link-ingest Phase 2 is UNBLOCKED.** Phase 1 (LEDGER 1108) ended
  awaiting operator notes; they have landed. RM-127b covers the build-calculator parity
  report (export ingest path already solved; 220 KB JSON, only 7 objects vary per champion).
- **BACKLOG: TFT F8 + F1** from `docs/COMPETITOR_LIFT_2026-07-30.md`, both rated HIGH in
  that teardown's own verdict table and never carried into any tracker.
- Verified-and-left-alone (no duplicate): G3-13 / G2-39 (gated sync), RM-124, RM-118,
  RM-122 (already absorbs `pending ui ux.txt`, with corrected line numbers), TFT Set 17
  constants + `tft_roll_odds` wiring + `tft_pbe_data` arrows, MEMORY.md compaction.
  CI run 30592954426 confirmed green LIVE rather than assumed.

## Lessons worth keeping

1. **Two grep patterns lied in the same session, both by near-miss.** `!= =!` returned 0
   because the CCR marker wraps the note TEXT (`**!= note =!**`) - that nearly closed
   RM-127 as "no operator notes yet" when 155 had landed. Then `MEMORY.md compact` missed
   the real row through its surrounding backticks, and nearly produced a duplicate BACKLOG
   row. **An empty grep is a claim about your pattern, not about the repo.**
2. **A ROADMAP row is a claim with a timestamp.** LEDGER 1093 wrote that lesson about this
   very row and the row went stale again anyway, because closing a ledger entry and closing
   the tracker row are two separate acts and only one of them is anybody's habit.
3. **`fire_lane`'s own docstring says it "never spawns anything" - that is STALE**, S5 added
   the launch directly below it. Read past a docstring to the code under it.
4. A live lane pid proves nothing (DETACHED_PROCESS no-op). The real probe is a `claude.exe`
   CHILD of the worker shell - confirmed here at pid 18400 / 382 MB.

## Do NOT redo

- RM-121 is CLOSED. The five-file queue is drained, there is no file 5.
- Do not re-move `First-Pass.md` / `First-Pass-Addendum.md` - RM-127 cites their Desktop paths.
- `logins.txt`, `LW continue.txt`, `RM continue.txt` were correctly left untouched (credentials
  + sibling-repo prefixes). Verified present and unmodified at wrap.
- `ops/loop/control/STOP` holds a REAL operator halt from 2026-07-28 and is UNTOUCHED. It gates
  the gemini CONTROLLER, not the lanes - the lane lock was FREE and fired normally with STOP in
  place. Do not clear it.
- Lanes 7 (repo) and 8 (true-audit) still have NEVER been fired and remain operator-gated.

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

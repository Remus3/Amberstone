# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-31b - MISSION CONTROL S5 + S6 + S7 (lanes fire for real; the steer channel).

## Start here next session

**S8 + S9** - the two highest-blast-radius lanes (Headless-Repo, Headless-True-Audit) and
the INTERRUPT tier. Worktree-first; a frozen-file edit needs an adjudicating agent's
approval. Lane 7 MUST encode the carve-out: `~/.claude/projects` holds the session
transcripts that make retroactive verification possible (compress or archive, NEVER delete),
and the 35.5 GB `Temp\claude\C--Sibling-A` belongs to the SIBLING repo - propose, never
auto-clean. Then the Desktop dashboard shortcut, then the First-Pass.md program.

## What shipped

- `6003b244` S5 lane launcher: one long-lived worktree per lane at `C:\rc-worktrees\rc-lane-<lane>`,
  spawn via the proven `run_lane.ps1`, lock re-pointed at the WORKER pid, lane RELEASED on any
  launch failure. Verified end to end: worktree on branch `lane/upgrade`, worker ran inside it,
  RUNNING -> RECLAIMABLE on exit, release -> FREE.
- `992a5a6c` S6 lanes 4-6 (`tools/headless-{uiux,research,ds}.md`, authored by parallel agents,
  every cited path verified) + S7 steer channel (`ops/loop/steer.py`, append-only JSONL + cursor).
- LEDGER 1135 + 1136. Full suite 17668 passed / exit 0; ruff clean; drift_guard 0.

## Lessons worth keeping

1. **`node --check` returns exit 0 on a duplicate `const`** in any file that leads with `import` -
   which is every module in `web/js`. One duplicate killed the ENTIRE panel while `node --check`
   and 35 source tests passed. `tests/test_web_js_esm_parse.py` now parses the tree as real ESM.
2. **`DETACHED_PROCESS` makes a spawned PowerShell worker a silent no-op** - real pid, rc=0, zero
   work. The lane flips RUNNING then RECLAIMABLE on schedule and looks like a healthy short run.
3. **A file-path module bind creates a SECOND copy with its own globals.** The launcher's private
   bind of `lanes.py` split `_OWNED`, so a repoint in one copy left the other unable to release.
4. **The plan's steer transport was wrong in both halves** - and a headless worker has no window
   at all, so no GUI transport could ever have worked. Probe the transport, not just the flag.
5. **`--accent` and `--warn` are the same gold in 5 of 6 themes.** Only arcane (the live one)
   separates them, so eyeballing the running dashboard cannot catch a colour collision.

## Do NOT redo

- S1-S7 are shipped and verified. Do not rebuild the lock, idempotency table, intent consumer,
  panel, launcher, lane docs, or steer channel.
- `repo` and `true-audit` are UNWIRED ON PURPOSE - that is S8, not an oversight.
- Do not edit `ops/loop/slots.py` / `ops/loop/winmutex.py` (byte-identical-by-contract).
- RM-122 is fenced verbatim against the headless loop; lane 4 may PREPARE it, never mark it DONE.
- The `test_web_ascii_sweep` live-half digest was re-captured twice this session - a red there
  next session is NEW drift.

---

# 2026-07-31a - MISSION CONTROL S4 (the dashboard panel) + the audit that paid for itself.

## Start here next session

**S5 of the Mission Control control plane** - shortcut 3, the existing headless-upgrade
command, the FIRST real lane fire. One supervised run, worktree-mandatory
(`try_acquire_lane` raises on the main tree by design). Spec + staging in
`docs/MISSION_CONTROL_PLAN.md`; S1-S4 are all in place and live.

## What shipped

- `ed5191b2` S4: the MISSION CONTROL settings card + `lanes` / `controller_lock` three-state
  blocks on `GET /api/loop-status` (read-only) + ARM/CONFIRM for shortcuts 1-2 over the new
  `web/js/lib/arm_confirm.js`. Live: `lanes FREE`, `controller_lock RECLAIMABLE pid 9380`.
- Plan constraint 2 RESOLVED - `root=None` is `lanes.DEFAULT_ROOT` on both sides of the
  S1/S2 seam, pinned by a test firing through the REAL route pair.
- 50 py + 14 node new; full `tests/` from the repo root 17601 passed / exit 0.

## Lessons worth keeping

1. **The panel had never rendered.** `#loop-status-body` was a CSS class and a
   `getElementById` and nothing else - no markup, anywhere. The 2026-06-07 card was dead
   from the day it landed, and every test that touched it tested the renderer's INPUTS.
   A rendered field is not evidence of a host either.
2. **`var(--x)` naming an undefined property fails SILENTLY.** `color: var(--bg)` fell back
   to inherited near-white at 1.9:1 on amber - on the ARMED button, the one state where
   misreading costs the most. `--bg` is defined in NO stylesheet in `web/css`; it passed
   every grep for the token name. Only reading the COMPUTED style in a live browser found it.
3. **A repaint can make a flow unreachable.** `innerHTML` at 4Hz threw keyboard focus to
   `<body>` on arm, so the confirm click could never be reached. Mouse-only, invisibly.
4. **`dim` is inert repo-wide** - every `.dim` rule in `web/css` is descendant-scoped.

## Do NOT redo

- S1, S2, S3, S4 are shipped and verified. Do not rebuild the lane lock, the idempotency
  table, the intent consumer, or the panel.
- Do not edit `ops/loop/slots.py` / `ops/loop/winmutex.py` (byte-identical-by-contract).
- The `test_web_ascii_sweep` live-half digest was re-captured this session (4 web files,
  two-tree diff verified) - a red there next session is NEW drift, not this.
- The pre-existing icon glyphs in `web/index.html` + `web/css/panels/header.css` (arrows,
  times, mute speaker) are LEFT ALONE on purpose - sweeping them breaks icons.

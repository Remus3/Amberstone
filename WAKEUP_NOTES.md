# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-30d - MISSION CONTROL S3 (intent consumer) + the stale-worktree glyph sweep.

## Start here next session

**S4 of the Mission Control control plane** - the dashboard panel wired to the real
`GET /api/loop-status`, read-only first, then the ARM/CONFIRM affordances for shortcuts 1-2.
Spec + staging in `docs/MISSION_CONTROL_PLAN.md`; S1/S2/S3 backend is all in place.
Render the lane lock as RUNNING / RECLAIMABLE / FREE and never collapse RECLAIMABLE into RUNNING.

## What shipped

- `b74b58e3` S3 consumer half: `ops/loop/intents.py` (`pending()` never writes; `consume()` writes
  the prompt FIRST then the consumed marker, both atomic) + `tools/session_intent.py` CLI + the
  done-ritual wiring. Live-verified end to end through the real `:8888` endpoint.
- **RC- NAMESPACE (operator, mid-session).** `Desktop/RC-NEXT-SESSION.txt`. The Desktop is SHARED
  and this design is meant to be lifted into Sibling-A and RM, so all three may run
  concurrently. The consumer ENFORCES the prefix - a doc pointing at `LW-NEXT-SESSION.txt` falls
  back to our own file. Lifting to LW/RM is one line: `REPO_PREFIX`.
- `2eef4d8b` glyph sweep (`-> x - approx` for U+2192 / U+00D7 / U+00B7 / U+2248), 17 files.
- `d01b01a4` mirrored the S3 wiring into the TRACKED `tools/done.md`.
- LEDGER 1132 + 1133; ROADMAP head moved S3 -> S4.

## Lessons worth keeping

1. **`Path.write_text` corrupted a byte count.** The first live consume reported 1375 bytes while
   the Desktop file held 1395 - Windows text mode rewrites LF as CRLF, and a `read_text` round-trip
   translates it back, so a string-equality test passes while the status line lies. Assert RAW BYTES.
2. **A guard reachable only off the non-default call path is invisible to a suite that always uses
   the default.** All 16 `consume()` tests passed `doc=None`, so `pending()` filtered the consumed
   intent out before the already-consumed guard ever ran, and a mutation removing it left the suite
   GREEN. The vacuous-test class again, second session running.
3. **A stale worktree is not automatically garbage.** `.claude/worktrees/clever-bardeen-9bcee0` held
   an uncommitted 17-file glyph sweep. `git worktree remove --force` WIPED the directory contents
   before failing on a lock - landing the work first is the only reason it survived.
4. **`drift_guard` earned its keep at wrap:** the S3 ritual edits went only into the gitignored
   `.claude/commands/done.md`, so a fresh clone would have got the ritual without them.

## Do NOT redo

- S1, S2, S3 are shipped and verified. Do not rebuild the lane lock, the idempotency table, or the
  intent consumer.
- The CLAUDE.md glyph-sweep constraint from `2026-07-30c` is DISCHARGED - that sweep was landed
  from the abandoned worktree this session. CLAUDE.md is safe to edit again.
- `ops/loop/slots.py` + `winmutex.py` stay pinned across two repos - consume, never edit.
- Ability-haste stays CLOSED.

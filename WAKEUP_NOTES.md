# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-30c - MISSION CONTROL S1+S2 (lane lock + idempotent control plane).

## Start here next session

**S3 of the Mission Control control plane.** S1+S2 shipped (`ef82bad0`); S3 is shortcuts 1 and 2
end to end - "Halt and Save" and "/done Continue" - the only two that cannot spawn a lane.
Spec + staging + all resolved decisions live in the plan (see below). Backend is already in place:
`ops/loop/lanes.py`, `dashboard/_idempotency.py`, and the two new `/api/loop-control` actions.

## What shipped

- `9b0784f9` docs(claude): session default is orchestrated + multi-agent + self-adjudicating +
  self-adversarial. R7 and R9 rewritten - they contradicted Subagent-First on the SHAPE of a
  session. File-count threshold REVOKED as the deciding test; substance decides.
- `ef82bad0` feat(mission-control): S1 lane lock + S2 idempotent control-plane actions.
  137 tests + 21 guards green from the repo root.
- Desktop/First-Pass.md gained CCR-120..CCR-146 (27 links scored) plus ADDENDUM A, the six
  RC-wide dashboard concepts. Two mockups rendered (Adjudication Inbox, Mission Control arcane).

## Lessons worth keeping

1. **Two agreeing stubs prove nothing.** Both slices passed their own suites carrying a live
   `REPO_ROOT` inversion. Only an integration probe against the REAL pair caught it. Any parallel
   split across an interface needs one test that exercises both sides for real.
2. **A regression test can be vacuous and still be green.** The first `REPO_ROOT` tests sourced
   their base from `REPO_ROOT` itself, so they passed whatever it pointed at - a mutation run
   restoring the bug went 23/23 green. Assert a PROPERTY of the value, not the value against
   itself. Mutation-test every regression test that guards a subtle defect.
3. **`git show --stat` after every commit is not ceremony.** The first S1+S2 commit was BLOCKED
   by the archmap hook and HEAD never moved; the push then said "Everything up-to-date", which
   reads exactly like success.
4. **Reddit is blocked to every default fetch path** - WebFetch, browser pane, curl on both
   hosts, r.jina.ai. Only the Apify actor works. See memory
   `reference_reddit_capture_transport_ladder`; do not re-walk the ladder.
5. **CLAUDE.md was NOT touched at wrap** - a background glyph-sweep task owns it in another
   session. Do not commit that file until that task reports.

## Do NOT redo

- CCR-01..119 are the operator's own review pass - do not re-score them.
- Ability-haste stays CLOSED. Three specs, one answer.
- `ops/loop/slots.py` + `winmutex.py` are pinned across two repos - consume, never edit.

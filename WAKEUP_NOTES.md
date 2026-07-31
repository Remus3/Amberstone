# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-30b - DDRAGON PATCH REFRESH 16.14.1 -> 16.15.1 + the throwback-mode partition.

**1 commit pushed, `f9f134a4` -> HEAD `9df58480`. LEDGER 1130. ENGINE 1.268.0 UNCHANGED
(patch is not an engine version). DS `:8893` live at `patch 16.15.1, champions 173,
items 706`. Suites: DS 10234 / 5913 subtests, RC 17441 / 1370 subtests, 0 failed.**

## Start here next session

1. **The dirty-tree suite trap is GONE.** The 8 dirty `data/meta/ddragon_*` files were a
   half-finished 16.15.1 pipeline run; this session consumed them. The 76 untracked
   `Jade_*.png` icons were throwback-mode icons the pipeline no longer requests - deleted.
   `git status` is clean and the MAIN tree gives a usable suite signal again. The standing
   "do not touch those files" instruction is RETIRED, and so is memory
   `reference_dirty_ddragon_tree_fakes_49_failures` (verify before trusting it).
2. **16.15.1 shipped a THROWBACK-MODE registry and RC now partitions it.** Read
   `agents/daemon_slayer/mode_variants.py` before touching any roster or item derivation.
   The prior session's read that these are `Jade_<Champion>` ALIASES was WRONG in a way
   that mattered: they carry their own older-patch stat line, and the same drop added 162
   items in `[770000, 780000)` plus 16 `modes:["JADE"]` spells. The dedupe guard that
   landed last run defused champion inflation but could not have caught the item half.
3. **When a JADE mode appears in mode detection, revisit the partition rather than extend
   it.** The live Flash row already advertises a `KIWI_JADE` mode, so an ARAM-Mayhem-Jade
   variant on the Howling Abyss is the likely first contact - that is exactly why 151 of
   the 162 throwback items claim `maps["12"]`.

## What shipped

- **Full refresh chain**: DDragon meta + mirror, DS extract, abilities extract, FRESH
  CDragon spell + ratio sidecars, curated/wiki copy-forward with patch restamps, Lane B
  build orders (173 champs x 3 modes, 519 cells each), HZ precompute + variants, pickban
  targets, Share mirror (517 files), 20-file parity with 16.14.1.
- **The partition** at every PRODUCER - `data_pipeline` on download, `daemon_slayer_extract`
  for the snapshot and its manifest counts, three further raw-snapshot roster derivations,
  and `DataSnapshot.load` + `full_roster` again at load. Champions test on the KEY, items on
  a CLOSED id band, never a name prefix; both predicates fail SAFE (unparseable = KEPT).
- **Two real defects, not pin churn.** The ARAM resolver handed the coach the Arena
  Heartsteel stat line (700 HP instead of 900) once Riot flagged mirror `223084` map-12
  legal, because collisions resolved first-write-wins = lexicographic; now
  lowest-numeric-id-wins. That same fix CLOSED the reachability half of R144. And the
  CDragon stale-copy guard fired as designed on a copied-forward ratio sidecar, after both
  table families had already been built with ratios DROPPED.

## Lessons worth keeping

- **A "duplicate row" reading is not a partition policy.** The champion half looked like
  aliases and got a dedupe; the item half had no display-name collision at all and would
  have sailed straight into the ARAM pool. Measure every axis a drop touches, not the one
  that surfaced first.
- **The stale-copy guard paid for itself.** Its docstring predicted the exact failure
  ("only bites if a future patch-refresh copies a sidecar forward again") and it caught two
  silently-degraded table families. Copy-forward is safe ONLY for artifacts nothing gates.
- **Digest controls need a fixed substrate.** 26 rm91 controls broke on pure upstream drift.
  Recomputing them against 16.14.1 - all 13 byte-exact - is what separated drift from
  regression BEFORE anything was re-pinned. Pin the data, not the code.
- **The `--force` ban was honored.** The snapshot was made canonical by applying the same
  predicate in place, with no Meraki re-fetch, rather than re-extracting against a mutable
  `latest`.

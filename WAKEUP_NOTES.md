# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-26d - the directive asked for a sweep that was already closed (R193, gemini loop cycle 3)

ENGINE **1.254.0 -> 1.255.0**, patch 16.14.1. HEAD `9fde56bb`. Three worktree
slices on disjoint file sets, Claude sole merger, read-only verifier gate before
every merge. Suites fresh AFTER the last edit: DS **9783 passed / 1 skipped /
4653 subtests**, RC `tests/` **13115 passed / 106 skipped / 460 subtests**.

**The first deliverable was refusing the stated scope.** R193 asked for base
lifesteal magnitudes + Arena/ARAM mirror parity on the six headline vamp items -
R181 verbatim, which measured ZERO DRIFT and left a 15-test guard on disk, with
Bloodthirster's Ichorshield, Shieldbow's Lifeline and Riftmaker's omnivamp all
already modelled. Re-running it would have produced a confident CLEAN and no
value. Three read-only recon agents were aimed at what R181 did NOT cover - the
vamp math model, the wider sustain family's magnitudes, and route reachability -
and every one came back with a real defect.

What landed:

- **hydra_cleave had desynced and the suite was defending the bug.** Ravenous
  Hydra 3074 / 223074 modelled Cleave at 0.35 total AD; Meraki 16.14.1 reads
  40%; the two siblings with byte-identical Meraki text were already at 0.40.
  Two tests asserted Ravenous scores BELOW its own siblings - a stale
  coefficient frozen as a feature. Sibling sweep then caught Tiamat 3077 at
  0.50, likewise pinned. Fixing only 3074 would have repeated the
  narrow-first-fix pattern of items 208/213.
- **Neither fix moves a shipped build table, and that was measured** - all four
  families regenerated full-roster across BOTH keyspaces, every diff is the two
  stamp lines. Cleave only fires at `targets_in_rotation > 1`; the tables are
  single-target.
- **DEFAULT-OFF `assume_crit_weighted_vamp`** - the vamp heal pool priced
  lifesteal off an auto-attack that never crits. OFF byte-identical (verifier
  re-measured against main, full result-dict md5 match), ARMED x1.7875 on Jinx
  L16, exact no-op at zero crit. It moves `blended_ehp`, so the flip is
  operator-gated.
- **`assume_max_stacks_omnivamp` was stranded** - zero occurrences in
  `server.py`. Now on `/ehp` + client keyword. **Both reachability guards were
  green the whole time and structurally cannot see this class**: they enumerate
  keys `server.py` already parses, so a never-parsed kwarg never enters the set.
  A green seam guard is evidence about parsed keys, not about capability.

**The verifier gate paid for itself again.** It BLOCKED slice B on a real
regression (`test_rune_resist_signature_convention_r134.py`) that neither of
that slice's own test scopes collected, so the slice's green claim was true and
insufficient. It also found corrupted git indexes in two worktrees (phantom
staged deletions, files intact) and proved every committed blob matched disk.

Three RC-side failures at the end were mine and are fixed, not waived: the
Share README release-history is a SEPARATE site from the auto-restamped header,
and the new route test imports the host-only client by design so it needed
registering in `ds_share_sync._HOST_DEPENDENT_TESTS`.

Next session: RM-116 (a) ranker-lane forwarding of the omnivamp flag, (b)
Sundered Sky 6610 overheal-to-bonus-health, (c) lifesteal credit on Ravenous
Cleave/Crescent. Do NOT re-commission a vamp base-magnitude sweep - closed
twice now.

---


# 2026-07-26c - the Share package's green-suite promise was false (R192, gemini loop cycle 2)

Commit `f26f651c`. No ENGINE bump, no DS bounce, no RC restart. Share mirror
regenerated (492 -> 494 files), `ds_share_sync.py --check` green.

Directive: unit (b) - read the ENTIRE `Share/` folder end to end and update /
clean / prune it as a new external presentation.

**Unit (b) has now run four times (R139 / R163 / R166 / R189 / this one), and
the two findings that mattered came from something no prior pass did: running
the package's own advertised quickstart.** `Share/README.md` promises the
shipped suite "exits green offline with no flags ... 0 failed, 0 errors, exit
code 0". It exited **1, with 4 failures**. For a package whose product IS a
runnable artifact, prose-checking cannot surface an exit code.

Two root causes, one bug class - the mirror shipped consumers without their
dependencies:

1. `tools/ds_feed_index.py` was not in the generator's `_DS_TOOLS`, so
   `test_artifact_patch_marker_guard.py` (landed `b23b5f16`, ENGINE 1.243.0 -
   after the last audit) raised `FileNotFoundError` on a path-import.
2. `web/data/champion_aliases.json` was unmirrored while the mirrored
   `tools/daemon_slayer_extract.py` reads it at MODULE IMPORT time. So a tool
   the package advertises as a shipped offline extractor could not be imported
   inside the package at all. That is the worse of the two, and the failing
   test is only how it surfaced.

Fixed at the generator (`_HOST_ASSET_FILES`, exact-path match, asset mirrored
at its identical repo-relative path), NOT by adding the test to
`_HOST_DEPENDENT_TESTS` - that would have gone green while dropping a real
engine guard and leaving the extractor broken. Guarded by a new failing-first
PROPERTY test, `tests/test_ds_share_mirror_self_contained.py`, which pins
self-containment rather than the two incident filenames.

**A premise in my own brief was measured and refuted.** I told slice C that
fourteen versions of RM-115 seam-wiring had probably made `docs/04`'s "no
caller can switch it on" rows stale. It re-probed every one: all still hold.
`docs/03` needed zero edits - all 22 mirror files, every size, every embedded
count correct. A no-change verdict backed by probes is the point.

Countable drift corrected: test files 309/358 -> 331/386, boundary set 49 ->
55, engine modules 106 -> 112, flag matrix 47 -> 55 names (tri-state 1 -> 4),
DS suite 9238 -> 9746, "the fourteen most recent" releases listed fifteen; 148
of 342 `file:line` citations re-anchored, 0 broken symbols; the generated
engine `__init__` docstring said six archetypes when there are seven.

Suites, all re-run by the merger after the last edit: Share package **7729
passed / 16 skipped / 3109 subtests, exit 0**; DS **9746 / 1 / 4653**; RC
`tests/` **13118 / 106 / 460**. ruff clean, 0 non-ASCII across every authored
Share file, six worktrees removed after confirming 0 unmerged each.

**Next Share pass: run the quickstart FIRST, then re-measure the countables.**
Do not re-read the prose top-to-bottom - both real findings this round came
from the exit code and from `find | wc -l`, not from reading. Two residuals
left deliberately: `ds_feed_index.py`'s CLI still imports a repo-side `tests/`
module so it cannot run inside the package (import and `KNOWN_STAMP_LAG` are
fine), and `test_abilities_content_freshness.py` may now be re-admittable to
the mirror but has a second host reach - that should be a measured decision,
not a side effect.

---

# 2026-07-26b - HEXCORE offline sync, and the debt was 9 not 54 (R191, gemini loop cycle 1)

Tier-0 presentation artifact. Commit `b4df6494`. No ENGINE bump, no DS bounce,
no RC restart, no Share sync.

Directive: re-sync `docs/HEXCORE_offline.html` against the net-new non-test .py
files added since `d584e02e` (2026-07-14).

**The measurement was the work.** `git diff --diff-filter=A d584e02e..HEAD -- '*.py'`
returns 297 files. Drop `Share/` (74 - byte mirrors of repo-root modules) and
`tests/` (223 - "non-test" is the unit's own wording) and 54 real source files
remain. **45 of those already had DUST leaves from the R138 pass**, so the real
debt was **9**. Adding all 54 would have made 45 duplicate particles; the guard's
`test_no_duplicate_dust_entries` catches that, but only after the edit.

Shipped: 9 leaves (parents from the existing DS spread - `m_dsengine`,
`m_dsserver`, `m_dsclient`, `ds`, `daemonslayer`, `m_buildorder`, `t_dsextract`),
dust 341 -> 350 across all four cross-asserted count sites, and a stats HUD
re-anchored to ground truth: ENGINE 1.240.0 -> 1.254.0, 9238 -> 9746 DS tests,
commits 3931 -> 3972, last `686a4b48` 2026-07-25, LEDGER high-water 997 -> 1054.
The same stale ENGINE pair sat in the `DAEMON_SLAYER.md` NODE description too -
a sweep that reads only the HUD tooltip misses it.

TDD RED-first (`EXPECTED_NEW_BASENAMES` 45 -> 54 before any HTML edit). Verifier
subagent CONFIRM on all 5 claims, re-deriving the missing set from git itself and
re-running `node --check` on the extracted 957k-char script block; it caught a
stale comment in the guard's own docstring (20/2 claimed vs 74/223 actual), fixed
in-slice. Rendered probe taken anyway (edit lands inside an inline JS literal):
0 console errors, HUD reads `dust: 350 files` / `engine: DS 1.254.0`.

Suites fresh after the last edit: **DS 9746 passed / 1 skipped / 4653 subtests**,
**RC `tests/` 13110 passed / 106 skipped / 460 subtests**. Guard 11/11, ruff clean,
0 non-ASCII.

**Next pass must re-derive its own delta** (`git diff --diff-filter=A <last-synced-sha>..HEAD`
minus `Share/` minus `tests/` minus basenames already in the DUST literal) and must
NOT trust a count carried in a directive.

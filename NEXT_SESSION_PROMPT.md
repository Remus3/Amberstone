# Riot Commander - next session: drain RM-115, the seam-reachability debt

## CONTEXT (do not re-derive)

- ENGINE **1.250.0**, patch 16.14.1. Tree clean and pushed at `944fde52`.
  DS `:8893` scheduled task is **Running** and `/health` reads 1.250.0.
- Suites measured fresh 2026-07-25 AFTER every edit: DS **9686 passed / 1 skipped /
  4646 subtests**; RC `tests/` **13110 passed / 106 skipped / 460 subtests**.
- Full writeup: `agents/daemon_slayer/CHANGELOG.md` 1.250.0 + `docs/LEDGER.md` 1050 +
  `docs/OPEN_ITEMS_REVIEW_2026-07-25.md` **PART 10** + `ROADMAP.md` **RM-115**.
- ROADMAP is at **69240 of 81920 bytes** (12680 headroom) after relocating the
  RM-35..RM-48 GAP table. You have room; keep it that way.

## THE ONE THING THAT MATTERS THIS SESSION

**RM-115.** Five independent probes on five different rows all converged on it, and it
is now measured and guarded but only partly paid down.

A DS seam has THREE gates: engine kwarg, HTTP route parse, and
`core/daemon_slayer_client.py`. Census: **43 route-parsed seam-shaped kwargs, 9
expressible through the client, 34 default-OFF and stranded.** The client is the
chokepoint every generated build table and every live coach tick passes through, and
none of `rank_for` / `rank_tank_for` / `rank_for_primary_archetype` carries `**kwargs`.

`agents/daemon_slayer/tests/test_route_seams_reach_the_client.py` now holds the stranded
set as an explicit debt ledger. **Your job is to shrink that allowlist, and the test tells
you honestly whether you did.**

### Priority order (measured, not guessed)

1. **`apply_ability_base_overrides` through gates 2 AND 3.** It is 0/0/0 - zero hits in
   `server.py`, `rank.py` and the client - so RM-81's six hand-authored ability-base
   corrections, *chosen precisely because they change a ranked order*, reach nothing but
   their own test file. Six known-wrong bases are live in every shipped table. Highest
   value in the list.
2. **`apply_passive_aura_damage` gate 3.** Shipped at 1.249.0, cleared gates 1-2, dead at
   the client. Mordekaiser's ability DPS 11.677 -> 72.155 is currently unreachable.
3. **`kit_conversion_strength` on `/rank-assassin` + the client assassin branch.** This
   CLOSES **RM-83 Naafiri**, which is already seeded and green in-engine: BotRK #2 -> #23
   at strength 1.0, with Talon and Zed byte-identical as controls. `server.py:481` parses
   it on the CARRY route only.
4. **Give `hybrid.py` the kwarg at all.** It has ZERO occurrences, so Olaf / Pantheon /
   RekSai / Riven are stranded at gate **1**, not 2 - the registry reaches 1 of its own 9
   curated champions.

Do NOT try to plumb all 34 in one session. Each needs its own before/after with a named
byte-identical control, and a blanket sweep would be unfalsifiable.

## ALSO READY TO BUILD (fully specced this session, not started)

- **A-17 / RM-96 Zilean.** Route half is MIS-FILED (deliberately HELD by design in
  `core/ds_support_route_overrides.json`); the CONDITIONALITY half is real. All 11
  enchanter-routed champions return a BYTE-IDENTICAL order today, and Zilean's summed
  heal/shield `casts_per_sec` is **0.00424, 6.5x below the next-lowest and 15.9x below
  Soraka** - cleanly separable. Needs a `heal_shield_trigger` channel in
  `kit_conversion.py` plus a lever on `rank_items_by_hps`; all three gates are OPEN.
  **THE TRAP:** on `ability_hps` MAGNITUDE he is 4.66 against Janna's 5.06, only 8 pct
  apart. A conversion factor seeded off HPS magnitude produces a SILENT NULL. Only the
  CAST RATE separates him. Bound the claim honestly - even a perfect gate leaves his real
  #1 (Solstice Sleigh 3876) pool-illegal behind the do-not-reopen RM-93 deny.
- **`parse_leveling_bases` blind spot** (`tools/ds_wiki_staleness_check.py:188-196`). It
  keeps only the first label pair per `{{st}}` block; over a 50-page sample **31 of 90
  blocks carry two or more, dropping 35 labels** that match Meraki attributes verbatim.
  So `ability_staleness.json` is a structural undercount and `_ability_base_overrides`'s
  "exactly those six" scope derives from it. Fixing the partition and re-running `--full`
  is cheap and would likely re-open the six.
- **B1 shipped code with no data.** `--full-roster` exists on all four sidecar extractors
  but no 16.14.1 artifact was regenerated with it - `wiki_ability_stats.json` (mtime
  07-16), `cdragon_ability_ratios.json` (`_champ_count: 171`) and `cdragon_spell_stats.json`
  all contain zero Locke/Zaahen records.

## DO NOT PICK

- **A-11 / RM-44, A-22 / RM-91, A-21 / RM-90 S3** - the "ds.ehp champion-sensitivity schema
  lift". **PREMISE REFUTED.** That prerequisite shipped at 1.247.0; the residual invariance
  was two 0.5 constants, now exposed. All three candidate lift shapes were rejected ON
  MEASUREMENT. Do not re-file this as a schema lift.
- **A-13 / RM-48 Azir soldier axis** - BLOCKED-UNFALSIFIABLE. Nine mages, pet or no pet,
  return Liandry's #1 / Nashor's #16-#19. RM-97 Zyra is a truthfulness fix, not an ordering
  one. The `weighted_dps == 0.0` bug that caused four sessions of misdiagnosis is FIXED.
- **A-32 / R190 kit-pen tails** - 3 of 4 MIS-FILED and the row names the wrong module
  (`_ANTITANK_REGISTRY` is in `antitank.py`, not `_kit_penetration.py`). (c) Amumu is
  INTENDED behavior. Only (a) Annie is real and it is provenance-only.
- **A-17 / RM-85 Nasus** - MIS-FILED. Five routes return the IDENTICAL 135-item set at both
  gates; "absent from the bruiser top-40" was the `top=40` trap.
- **A-12 Ranger's Focus, the RM-37/42/38 successor, A-27/RM-114, A-30/R129, A-15/RM-80,
  A-24/RM-93** - all closed in earlier sessions with measurements.

## METHOD (standing directive - this is a LOOP)

Five open non-gated items per session. **Probe every row to PROBED before building** -
seven consecutive sessions have found mis-files, and this session FOUR of five named rows
closed without code while the best result came from what all five probes noticed in
passing. **Read every probe report's tail.** Parallel worktree agents on disjoint file
sets, one Claude as sole merger. Self-adjudicate; do not gate on the operator mid-run.
End with `/done` plus a full next-session prompt.

## HAZARDS carried forward

- **Row agreement is NOT evidence.** Three rows independently naming the same blocker meant
  three rows inheriting one unverified premise. Verify the prerequisite before treating
  convergence as strength. This cost four sessions.
- **A pinned "signature tail" assertion is self-defeating** under the append-at-END
  convention. THREE tests carried one this session; each fails on the next legitimate
  append - the very convention they exist to protect. Repair the premise onto the shipped
  path (case the entry points separately), never weaken the assertion.
- **`/rank*` returns `item_id` as a STRING.** A probe comparing against integer ids reads
  ABSENT for every watched item and looks exactly like a clean pool-exclusion finding.
  Same status as the `top=40` and empty-list traps.
- **DS probe traps:** `POST /rank` IS the CARRY scorer (there is no `/rank-carry`) and
  silently ignores archetype kwargs - use `/rank-<archetype>`; body key is `items`, not
  `item_ids`; `top` defaults to **40**; always pass explicit non-zero target stats; NEVER
  probe at an empty item list (five false headlines). **DS is plain HTTP on `:8893`.**
- **Any new test under `agents/daemon_slayer/tests/` importing `core.*` at module level
  MUST be added to `_HOST_DEPENDENT_TESTS` in `tools/ds_share_sync.py`**, or the RC suite
  fails on the mirror. This bit me this session because I warned only one of three build
  agents. Warn ALL of them.
- **The ENGINE bump needs FOUR doc sites:** `agents/daemon_slayer/CHANGELOG.md` (guarded),
  plus three that are NOT: `docs/DAEMON_SLAYER.md` banner (version AND test count, bare
  prose - hand-edit), `Share/CHANGELOG.md`, and the `Share/README.md` release list -
  **trim to keep it at fourteen; it silently drifted to 15 and was corrected this session.**
- **Bump by QUOTED literal only**, excluding `.claude`, `docs/_archive` AND `Share`.
- **Regen BOTH families and corroborate with a stamp-stripped payload diff.** A numstat is
  not proof on single-line JSON. `python tools/daemon_slayer_build_orders_generate.py --mode all`
  (~190s, prints) then `python core/build_order_precompute.py --mode all --champions all`
  (silent, exit 0 - confirm via `git status data/`).
- **ENGINE bump ritual: bump -> RESTART `:8893` -> VERIFY `/health` reads the NEW version
  -> regen -> measure.** Restart in **PowerShell**. If the task goes `Ready` with
  `LastResult 0x0` and nothing listening, check for a process already holding `:8893`
  before suspecting the code. `taskkill /F` must run from PowerShell - Git Bash mangles
  `/F` into a path.
- **`git apply` of a worktree diff FAILS.** Merge by extracting committed blobs:
  `git -C <worktree> show HEAD:<path> > <path>`, **source paths only** - a precommit hook
  auto-syncs `Share/` into agent commits. Remove worktrees BEFORE committing from main and
  check `git show --stat HEAD` after every commit (0 phantom deletions this session).
- **Exit code is NOT ground truth.** Redirect pytest to a FILE. A `tests/` run takes
  **~20 minutes** - launch it in the background and do docs work while it runs, then re-run
  FRESH after any late edit.
- **Tell build agents to trust their own measurement over the brief.** This session a brief
  carried two wrong wiki numbers and an inflated seam count; agents caught all three.

## Start with

`/clear`, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES + git log + ROADMAP
RM-115.
